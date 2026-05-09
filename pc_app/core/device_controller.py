"""
device_controller.py — Gestion del estado del device y envio de comandos serializados.

Mejoras:
  - Validacion de parametros antes de enviar (ValueError con mensaje claro).
  - Mapeo correcto de trigger edge entre UI y firmware.
  - Pre-trigger: conversion de porcentaje a samples.
  - AC coupling: solo estado local (el firmware no lo soporta).
  - Sincronizacion automatica de estado al conectar via CMD_GET_CAPS.
"""

import threading
import time
import logging
from typing import List, Optional, Tuple
from dataclasses import dataclass
import serial.tools.list_ports
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, QThread
from .serial_reader import SerialReader

# Configurar logging para que los mensajes sean visibles en la consola
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# ---------------------------------------------------------------------------
# Validacion — limites del protocolo y del ESP32-S3
# ---------------------------------------------------------------------------

# Sample rate en Hz (limites segun protocolo + ADC clock hack del ESP32-S3)
MIN_SAMPLE_RATE = 611
MAX_SAMPLE_RATE = 160000  # Con CLOCK_HACK; el INFO frame del firmware puede reportar menos

# Frame sizes validos segun protocolo
VALID_FRAME_SIZES = [64, 128, 256, 512, 1024, 2048, 4096]

# Attenuation indices validos (0=0dB, 1=2.5dB, 2=6dB, 3=12dB)
VALID_ATTEN_INDICES = [0, 1, 2, 3]

# Modos validos (0=Single CH1, 1=Single CH2, 2=Dual)
VALID_MODES = [0, 1, 2]
VALID_OVERSAMPLING_FACTORS = [1, 2, 4, 8, 16]

# Mapeo de trigger edge: UI -> Firmware
# UI: 0=None, 1=Rising, 2=Falling, 3=Any
# Firmware: 0=RISE, 1=FALL, 2=ANY, 3=NONE
_EDGE_UI_TO_FW = {0: 3, 1: 0, 2: 1, 3: 2}
_EDGE_FW_TO_UI = {3: 0, 0: 1, 1: 2, 2: 3}


@dataclass
class OscConfig:
    """Configuracion local que refleja (lo mejor posible) el estado del firmware."""
    mode: int = 2              # 0=Single CH1, 1=Single CH2, 2=Dual
    sample_rate: int = 100000
    frame_size: int = 1024
    fft_enabled: int = 0
    trig_ch: int = 0
    trig_mv: float = 0.0
    trig_edge: int = 1        # UI encoding: 0=none, 1=rising, 2=falling, 3=any
    pre_trig_pct: int = 50    # Porcentaje (0-100), se convierte a samples para el firmware
    ch0_atten_idx: int = 3     # 0=0dB, 1=2.5dB, 2=6dB, 3=12dB (default 12dB)
    ch1_atten_idx: int = 3
    ch0_coupling: str = "AC+DC"      # Modos locales: AC+DC, AC, DC, GND
    ch1_coupling: str = "AC+DC"
    streaming: bool = False
    oversampling: int = 1

class _ConfigPushWorker(QObject):
    """Worker que corre en hilo separado para evitar bloquear la UI."""
    finished = pyqtSignal()

    def __init__(self, controller: 'DeviceController', mode: str = "config") -> None:
        super().__init__()
        self._ctrl = controller
        self._mode = mode

    def run(self) -> None:
        if self._mode == "config":
            self._ctrl._push_config_blocking()
        elif self._mode == "atten":
            self._ctrl._push_atten_blocking()
        self.finished.emit()

class DeviceController(QObject):
    """
    Controlador que maneja el envio de comandos ASCII al osciloscopio
    y mantiene el estado conocido del dispositivo.
    """
    config_changed = pyqtSignal()

    def __init__(self, reader: SerialReader, parent=None) -> None:
        super().__init__(parent)
        self.reader = reader
        self.connected: bool = False
        self.port_name: str = ""
        self.firmware_version: str = "Unknown"
        self.max_sample_rate: int = 0
        self.max_frame_size: int = 0
        self.capabilities: dict = {}
        self.current_config = OscConfig()

        self._cmd_lock = threading.Lock()
        self._pending_ack: str | None = None
        self._ack_event = threading.Event()
        self._nak_reason: str = ""

        # Conectar senales del reader
        self.reader.info_received.connect(self._on_info)
        self.reader.ack_received.connect(self._on_ack)
        self.reader.nak_received.connect(self._on_nak)
        self.reader.connection_changed.connect(self._on_connection_changed)

    # ------------------------------------------------------------------
    # Conexion / desconexion
    # ------------------------------------------------------------------

    def connect_device(self, port: str, baudrate: int = 115200) -> bool:
        """Inicia la conexion. Retorna False si ya esta conectado."""
        if self.connected:
            return False
        self.port_name = port
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
        base_cmd = cmd.split(' ')[0] if cmd else ''
        if base_cmd == self._pending_ack:
            self._ack_event.set()

    def _on_nak(self, cmd: str, reason: str) -> None:
        base_cmd = cmd.split(' ')[0] if cmd else ''
        if base_cmd == self._pending_ack:
            self._nak_reason = reason
            self._ack_event.set()

    def _on_connection_changed(self, connected: bool, port: str = "") -> None:
        was_connected = self.connected
        self.connected = connected
        if connected and not was_connected:
            # Sincronizar estado al conectar
            QTimer = __import__('PyQt6.QtCore', fromlist=['QTimer']).QTimer
            QTimer.singleShot(500, self._sync_state_on_connect)
        if not connected:
            self.firmware_version = "Unknown"
            self.port_name = ""



    # --- Continúa métodos de DeviceController ---

    def _sync_state_on_connect(self) -> None:
        """Lee capabilities del firmware y sincroniza la UI."""
        if not self.connected:
            return
        self.get_caps()
        # BUG-06 FIX: push current UI config to firmware
        self.push_config_to_device()
        self.config_changed.emit()

    def _push_config_blocking(self) -> None:
        """
        Lógica de push secuencial con sleeps — corre en hilo worker.
        """
        if not self.connected:
            return

        cfg = self.current_config
        was_streaming = cfg.streaming

        if was_streaming:
            self._send_command("CMD_STREAM_STOP", wait_ack=True)

        time.sleep(0.15)

        self._send_command(f"CMD_SET_MODE {cfg.mode}",        wait_ack=True)
        self._send_command(f"CMD_SET_RATE {cfg.sample_rate}", wait_ack=True)
        self._send_command(f"CMD_SET_FRAME {cfg.frame_size}", wait_ack=True)
        self._send_command(f"CMD_SET_OVERSAMPLE {cfg.oversampling}", wait_ack=True)

        edge_fw = _EDGE_UI_TO_FW.get(cfg.trig_edge, 3)
        self._send_command(
            f"CMD_SET_TRIG {cfg.trig_ch} {cfg.trig_mv:.1f} {edge_fw}",
            wait_ack=True
        )

        if was_streaming:
            time.sleep(0.05)
            self._send_command("CMD_STREAM_START", wait_ack=True)

    def push_config_to_device(self) -> None:
        """Despacha el push a un hilo worker para no bloquear la UI."""
        if not self.connected:
            return
        self._push_thread = QThread()
        self._push_worker = _ConfigPushWorker(self, mode="config")
        self._push_worker.moveToThread(self._push_thread)
        self._push_thread.started.connect(self._push_worker.run)
        self._push_worker.finished.connect(self._push_thread.quit)
        self._push_worker.finished.connect(self._push_worker.deleteLater)
        self._push_thread.finished.connect(self._push_thread.deleteLater)
        self._push_thread.start()

    def _push_atten_blocking(self) -> None:
        """Push de atenuación en hilo worker."""
        if not self.connected:
            return
        # Nota: asumiendo que push_atten_to_device usa sleeps similares
        # Si no los tiene aún, se pueden añadir aquí.
        self._send_command(f"CMD_SET_ATTEN 0 {self.current_config.ch0_atten_idx}", wait_ack=True)
        time.sleep(0.05)
        self._send_command(f"CMD_SET_ATTEN 1 {self.current_config.ch1_atten_idx}", wait_ack=True)

    def push_atten_to_device(self) -> None:
        """Despacha el push de atenuación a un hilo worker."""
        if not self.connected:
            return
        self._atten_thread = QThread()
        self._atten_worker = _ConfigPushWorker(self, mode="atten")
        self._atten_worker.moveToThread(self._atten_thread)
        self._atten_thread.started.connect(self._atten_worker.run)
        self._atten_worker.finished.connect(self._atten_thread.quit)
        self._atten_worker.finished.connect(self._atten_worker.deleteLater)
        self._atten_thread.finished.connect(self._atten_thread.deleteLater)
        self._atten_thread.start()

    # ------------------------------------------------------------------
    # Envio de comandos sincronizado
    # ------------------------------------------------------------------

    def _send_command(self, cmd_string: str, wait_ack: bool = True) -> Tuple[bool, str]:
        """
        Envia un comando ASCII y espera el ACK.
        Retorna (True, "") si fue exitoso, o (False, "razon") si fallo.
        """
        if not self.connected:
            return False, "Not connected"

        base_cmd = cmd_string.split(' ')[0]

        with self._cmd_lock:
            self._pending_ack = base_cmd
            self._nak_reason = ""
            self._ack_event.clear()

            full_cmd = cmd_string.strip() + '\n'
            success = self.reader.send_bytes(full_cmd.encode('utf-8'))

            if not success:
                self._pending_ack = None
                return False, "Serial write error"

            if wait_ack:
                signaled = self._ack_event.wait(timeout=2.0)
                self._pending_ack = None

                if not signaled:
                    return False, "Timeout waiting for ACK"
                if self._nak_reason:
                    return False, f"NAK: {self._nak_reason}"

            self._pending_ack = None
            return True, ""

    # ------------------------------------------------------------------
    # Metodos de control especificos (con validacion)
    # ------------------------------------------------------------------

    def get_caps(self) -> bool:
        ok, _ = self._send_command("CMD_GET_CAPS")
        return ok

    def start_stream(self) -> bool:
        ok, _ = self._send_command("CMD_STREAM_START")
        if ok:
            self.current_config.streaming = True
        return ok

    def stop_stream(self) -> bool:
        ok, _ = self._send_command("CMD_STREAM_STOP")
        if ok:
            self.current_config.streaming = False
        return ok

    def set_mode(self, mode: int) -> bool:
        """Establece modo: 0=Single CH1, 1=Single CH2, 2=Dual."""
        if mode not in VALID_MODES:
            return False
        prev = self.current_config.mode
        self.current_config.mode = mode
        if prev != mode:
            self._safe_reconfig()
        self.config_changed.emit()
        return True

    def set_oversampling(self, factor: int) -> bool:
        """Establece factor de oversampling promediado (1, 2, 4, 8, 16)."""
        if factor not in VALID_OVERSAMPLING_FACTORS:
            return False
        prev = self.current_config.oversampling
        self.current_config.oversampling = factor
        if prev != factor:
            self._safe_reconfig()
        self.config_changed.emit()
        return True

    def set_sample_rate(self, hz: int) -> bool:
        """Cambia la tasa de muestreo. Para el stream antes de reconfigurar el ADC."""
        if not (MIN_SAMPLE_RATE <= hz <= MAX_SAMPLE_RATE):
            raise ValueError(
                f"Sample rate invalido: {hz} Hz. "
                f"Rango valido: {MIN_SAMPLE_RATE} - {MAX_SAMPLE_RATE} Hz"
            )
        prev = self.current_config.sample_rate
        self.current_config.sample_rate = hz
        if prev != hz:
            self._safe_reconfig()
        self.config_changed.emit()
        return True

    def set_trigger(self, ch: int, mv: float, edge_ui: int) -> bool:
        """
        Configura el trigger.
        edge_ui: 0=none, 1=rising, 2=falling, 3=any
        Se mapea internamente al encoding del firmware.
        """
        if ch not in (0, 1):
            raise ValueError(f"Canal de trigger invalido: {ch}. Use 0 o 1.")
        if edge_ui not in _EDGE_UI_TO_FW:
            raise ValueError(f"Edge invalido: {edge_ui}. Validos: 0=none, 1=rising, 2=falling, 3=any")

        edge_fw = _EDGE_UI_TO_FW[edge_ui]
        ok, err = self._send_command(f"CMD_SET_TRIG {ch} {mv:.1f} {edge_fw}")
        if ok:
            self.current_config.trig_ch = ch
            self.current_config.trig_mv = mv
            self.current_config.trig_edge = edge_ui
            self.config_changed.emit()
        return ok

    def set_attenuation(self, ch: int, atten_idx: int) -> bool:
        """
        Configura la atenuacion del canal.
        atten_idx: 0=0dB, 1=2.5dB, 2=6dB, 3=12dB
        """
        if atten_idx not in VALID_ATTEN_INDICES:
            raise ValueError(
                f"Indice de atenuacion invalido: {atten_idx}. "
                f"Validos: {VALID_ATTEN_INDICES} (0=0dB, 1=2.5dB, 2=6dB, 3=12dB)"
            )
        ok, err = self._send_command(f"CMD_SET_ATTEN {ch} {atten_idx}")
        if ok:
            if ch == 0:
                self.current_config.ch0_atten_idx = atten_idx
            else:
                self.current_config.ch1_atten_idx = atten_idx
            self.config_changed.emit()
        return ok

    def set_coupling(self, ch: int, coupling: str) -> bool:
        """
        AC/DC coupling es SOLO local (software). El firmware NO soporta este comando.
        """
        # No enviamos comando al firmware — CMD_SET_CPL no existe en el protocolo
        if ch == 0:
            self.current_config.ch0_coupling = coupling
        else:
            self.current_config.ch1_coupling = coupling
        self.config_changed.emit()
        return True

    def set_frame_size(self, n: int) -> bool:
        """Cambia el tamano del frame. Para el stream antes de reconfigurar el ADC."""
        if n not in VALID_FRAME_SIZES:
            raise ValueError(
                f"Frame size invalido: {n}. Validos: {VALID_FRAME_SIZES}"
            )
        prev = self.current_config.frame_size
        self.current_config.frame_size = n
        if prev != n:
            self._safe_reconfig()
        self.config_changed.emit()
        return True

    def _safe_reconfig(self) -> None:
        """
        Stop → send config → restart stream.
        Mitiga el race condition del firmware: adc_capture_task no puede estar
        corriendo mientras osc_adc_reconfigure() se ejecuta desde el cmd_task.
        """
        import time
        cfg = self.current_config
        was_streaming = cfg.streaming

        if was_streaming:
            # Parar el stream y esperar que el firmware liquide el batch en curso
            self._send_command("CMD_STREAM_STOP", wait_ack=True)
            cfg.streaming = False
            time.sleep(0.20)  # 200ms: da tiempo al ADC DMA de vaciar su buffer

        # Enviar la config nueva
        self._send_command(f"CMD_SET_MODE {cfg.mode}",        wait_ack=True)
        self._send_command(f"CMD_SET_RATE {cfg.sample_rate}", wait_ack=True)
        self._send_command(f"CMD_SET_FRAME {cfg.frame_size}", wait_ack=True)

        if was_streaming:
            time.sleep(0.05)
            self._send_command("CMD_STREAM_START", wait_ack=True)
            cfg.streaming = True

    def set_pre_trigger(self, pct: int) -> bool:
        """
        Convierte porcentaje (0-100) a samples antes de enviar al firmware.
        El firmware espera: 0 to frame_size/2 samples.
        """
        if not (0 <= pct <= 100):
            raise ValueError(f"Pre-trigger invalido: {pct}%. Rango: 0-100")

        # Convertir porcentaje a samples
        max_samples = self.current_config.frame_size // 2
        samples = int(pct * max_samples / 100)
        samples = max(0, min(samples, max_samples))

        ok, err = self._send_command(f"CMD_SET_PRE_TRIG {samples}")
        if ok:
            self.current_config.pre_trig_pct = pct
            self.config_changed.emit()
        return ok

    def set_fft_enabled(self, en: int) -> bool:
        if en not in (0, 1):
            raise ValueError(f"FFT enabled invalido: {en}. Use 0 o 1.")
        ok, err = self._send_command(f"CMD_SET_FFT {en}")
        if ok:
            self.current_config.fft_enabled = en
            self.config_changed.emit()
        return ok

    def factory_reset(self) -> bool:
        return self._send_command("CMD_FACTORY_RESET")[0]

    def single_shot(self) -> bool:
        logging.warning("Single shot no implementado en firmware todavia.")
        return False

    def get_status(self) -> bool:
        return self._send_command("CMD_GET_STATUS")[0]

    # --- Signal Generator ---
    def set_gen_start(self, wave_type: int, freq_hz: int, duty_pct: int) -> bool:
        """
        Envía comando CMD_GEN_START type freq duty
        """
        if not self.connected:
            return False
        if freq_hz < 1 or freq_hz > 150000:
            raise ValueError(f"Frecuencia invalida: {freq_hz} Hz. Rango: 1-150000")
        if duty_pct < 1 or duty_pct > 99:
            raise ValueError(f"Duty invalido: {duty_pct} %. Rango: 1-99")
            
        ok, err = self._send_command(f"CMD_GEN_START {wave_type} {freq_hz} {duty_pct}")
        return ok

    def set_gen_stop(self) -> bool:
        if not self.connected:
            return False
        ok, err = self._send_command("CMD_GEN_STOP")
        return ok
