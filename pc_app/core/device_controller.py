"""
device_controller.py — Gestión del estado del device y envío de comandos serializados.
"""

import threading
import time
from typing import List, Optional, Tuple
from dataclasses import dataclass
import serial.tools.list_ports
from PyQt6.QtCore import QObject, pyqtSignal
from .serial_reader import SerialReader

@dataclass
class OscConfig:
    mode: int = 1         # 0=single, 1=dual, 2=oversample
    sample_rate: int = 100000
    frame_size: int = 1024
    fft_enabled: int = 0
    trig_ch: int = 0
    trig_mv: float = 0.0
    trig_edge: int = 0    # 0=none, 1=rising, 2=falling, 3=any
    pre_trig_pct: int = 0
    ch0_atten: int = 0
    ch1_atten: int = 0
    ch0_coupling: int = 0 # 0=DC, 1=AC
    ch1_coupling: int = 0

class DeviceController(QObject):
    """
    Controlador que maneja el envío de comandos ASCII al osciloscopio
    y mantiene el estado conocido del dispositivo.
    """
    # Señal emitida cuando hay un cambio en el estado local de configuración
    config_changed = pyqtSignal()

    def __init__(self, reader: SerialReader, parent=None) -> None:
        super().__init__(parent)
        self.reader = reader
        self.connected: bool = False
        self.firmware_version: str = "Unknown"
        self.max_sample_rate: int = 0
        self.max_frame_size: int = 0
        self.capabilities: dict = {}
        self.current_config = OscConfig()

        self._cmd_lock = threading.Lock()
        self._pending_ack: str | None = None
        self._ack_event = threading.Event()
        self._nak_reason: str = ""

        # Conectar señales del reader para interceptar info y acks
        self.reader.info_received.connect(self._on_info)
        self.reader.ack_received.connect(self._on_ack)
        self.reader.nak_received.connect(self._on_nak)
        self.reader.connection_changed.connect(self._on_connection_changed)

    def connect_device(self, port: str, baudrate: int = 115200) -> bool:
        """Inicia la conexión. Retorna False si ya está conectado."""
        if self.connected:
            return False
        self.reader.start_reading(port, baudrate)
        return True

    def disconnect_device(self) -> None:
        self.reader.stop_reading()

    @staticmethod
    def get_available_ports() -> List[str]:
        return [port.device for port in serial.tools.list_ports.comports()]

    # ------------------------------------------------------------------
    # Manejadores de respuestas
    # ------------------------------------------------------------------

    def _on_info(self, info: dict) -> None:
        self.firmware_version = info.get('fw_version', 'Unknown')
        self.max_sample_rate = info.get('max_rate_hz', 0)
        self.max_frame_size = info.get('max_frame_size', 0)
        self.capabilities = info

    def _on_ack(self, cmd: str) -> None:
        # Extraemos el comando base (antes del primer espacio si lo hay)
        base_cmd = cmd.split(' ')[0] if cmd else ''
        if base_cmd == self._pending_ack:
            self._ack_event.set()

    def _on_nak(self, cmd: str, reason: str) -> None:
        base_cmd = cmd.split(' ')[0] if cmd else ''
        if base_cmd == self._pending_ack:
            self._nak_reason = reason
            self._ack_event.set() # Desbloqueamos pero marcaremos como fallo

    def _on_connection_changed(self, connected: bool) -> None:
        self.connected = connected
        if not connected:
            self.firmware_version = "Unknown"

    # ------------------------------------------------------------------
    # Envío de comandos sincronizado
    # ------------------------------------------------------------------

    def _send_command(self, cmd_string: str, wait_ack: bool = True) -> Tuple[bool, str]:
        """
        Envía un comando ASCII y espera el ACK.
        Retorna (True, "") si fue exitoso, o (False, "razón") si falló.
        """
        if not self.connected:
            return False, "Not connected"

        base_cmd = cmd_string.split(' ')[0]

        with self._cmd_lock:
            self._pending_ack = base_cmd
            self._nak_reason = ""
            self._ack_event.clear()

            # Añadir newline al final como requiere el protocolo
            full_cmd = cmd_string.strip() + '\n'
            success = self.reader.send_bytes(full_cmd.encode('utf-8'))

            if not success:
                self._pending_ack = None
                return False, "Serial write error"

            if wait_ack:
                # Esperar hasta 2 segundos
                signaled = self._ack_event.wait(timeout=2.0)
                self._pending_ack = None

                if not signaled:
                    return False, "Timeout waiting for ACK"
                if self._nak_reason:
                    return False, f"NAK: {self._nak_reason}"

            self._pending_ack = None
            return True, ""

    # ------------------------------------------------------------------
    # Métodos de control específicos
    # ------------------------------------------------------------------

    def get_caps(self) -> bool:
        ok, _ = self._send_command("CMD_GET_CAPS")
        return ok

    def start_stream(self) -> bool:
        ok, _ = self._send_command("CMD_STREAM_START")
        return ok

    def stop_stream(self) -> bool:
        ok, _ = self._send_command("CMD_STREAM_STOP")
        return ok

    def single_shot(self) -> bool:
        ok, _ = self._send_command("CMD_SINGLE_SHOT", wait_ack=False)
        return ok

    def set_mode(self, mode: int) -> bool:
        ok, err = self._send_command(f"CMD_SET_MODE {mode}")
        if ok:
            self.current_config.mode = mode
            self.config_changed.emit()
        return ok

    def set_sample_rate(self, hz: int) -> bool:
        ok, err = self._send_command(f"CMD_SET_RATE {hz}")
        if ok:
            self.current_config.sample_rate = hz
            self.config_changed.emit()
        return ok

    def set_trigger(self, ch: int, mv: float, edge: int) -> bool:
        ok, err = self._send_command(f"CMD_SET_TRIG {ch} {mv:.1f} {edge}")
        if ok:
            self.current_config.trig_ch = ch
            self.current_config.trig_mv = mv
            self.current_config.trig_edge = edge
            self.config_changed.emit()
        return ok

    def set_attenuation(self, ch: int, db: int) -> bool:
        ok, err = self._send_command(f"CMD_SET_ATTEN {ch} {db}")
        if ok:
            if ch == 0: self.current_config.ch0_atten = db
            else: self.current_config.ch1_atten = db
            self.config_changed.emit()
        return ok

    def set_coupling(self, ch: int, coupling: str) -> bool:
        cpl_val = 1 if coupling.upper() == "AC" else 0
        ok, err = self._send_command(f"CMD_SET_CPL {ch} {cpl_val}")
        if ok:
            if ch == 0: self.current_config.ch0_coupling = cpl_val
            else: self.current_config.ch1_coupling = cpl_val
            self.config_changed.emit()
        return ok

    def set_frame_size(self, n: int) -> bool:
        ok, err = self._send_command(f"CMD_SET_FRAME {n}")
        if ok:
            self.current_config.frame_size = n
            self.config_changed.emit()
        return ok

    def set_pre_trigger(self, pct: int) -> bool:
        ok, err = self._send_command(f"CMD_SET_PRE_TRIG {pct}")
        if ok:
            self.current_config.pre_trig_pct = pct
            self.config_changed.emit()
        return ok

    def set_fft_enabled(self, en: int) -> bool:
        ok, err = self._send_command(f"CMD_SET_FFT {en}")
        if ok:
            self.current_config.fft_enabled = en
            self.config_changed.emit()
        return ok

    def factory_reset(self) -> bool:
        return self._send_command("CMD_FACTORY_RESET")[0]

    def get_status(self) -> bool:
        return self._send_command("CMD_GET_STATUS")[0]
