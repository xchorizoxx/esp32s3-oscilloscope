"""
serial_reader.py — QThread que lee el puerto USB CDC y emite señales con frames parseados.
"""

import time
import serial
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from .frame_parser import FrameParser, FRAME_DATA, FRAME_MEASUREMENTS, FRAME_INFO, FRAME_ACK, FRAME_NAK

class SerialReader(QThread):
    """
    Hilo dedicado a leer del puerto serie y parsear los datos.
    """

    # Señales para comunicarse con la UI
    data_frame_received   = pyqtSignal(dict)
    measurements_received = pyqtSignal(dict)
    info_received         = pyqtSignal(dict)
    ack_received          = pyqtSignal(str)
    nak_received          = pyqtSignal(str, str)
    connection_changed    = pyqtSignal(bool)
    error_occurred        = pyqtSignal(str)

    def __init__(self, parser: FrameParser, parent=None) -> None:
        super().__init__(parent)
        self.parser = parser
        self.port = ""
        self.baudrate = 115200
        self._running = False
        self._serial: serial.Serial | None = None
        self._mutex = QMutex()

        # Estadísticas
        self._frames_ok = 0
        self._frames_error = 0
        self._bytes_read = 0
        self._last_stats_time = time.time()
        self.fps = 0.0
        self.bytes_per_sec = 0.0

    def start_reading(self, port: str, baudrate: int = 115200) -> None:
        self._mutex.lock()
        self.port = port
        self.baudrate = baudrate
        self._running = True
        self._mutex.unlock()
        self.start()

    def stop_reading(self) -> None:
        self._mutex.lock()
        self._running = False
        self._mutex.unlock()
        self.wait()

    def send_bytes(self, data: bytes) -> bool:
        """Envía bytes al dispositivo si está conectado."""
        self._mutex.lock()
        ser = self._serial
        self._mutex.unlock()
        if ser and ser.is_open:
            try:
                ser.write(data)
                return True
            except Exception as e:
                self.error_occurred.emit(f"Error escritura serial: {e}")
                return False
        return False

    def get_stats(self) -> dict:
        return {
            'frames_ok': self._frames_ok,
            'frames_crc_err': self._frames_error,
            'fps': self.fps,
            'bytes_per_sec': self.bytes_per_sec
        }

    def run(self) -> None:
        self._mutex.lock()
        port = self.port
        baudrate = self.baudrate
        self._mutex.unlock()

        try:
            self._serial = serial.Serial(port, baudrate, timeout=0.1)
            self.connection_changed.emit(True)
            self.parser.reset()
        except Exception as e:
            self.error_occurred.emit(f"No se pudo abrir {port}: {e}")
            self.connection_changed.emit(False)
            return

        frames_in_interval = 0
        bytes_in_interval = 0

        while True:
            self._mutex.lock()
            running = self._running
            self._mutex.unlock()

            if not running:
                break

            try:
                if self._serial.in_waiting > 0:
                    # Leer en chunks relativamente grandes
                    chunk = self._serial.read(min(self._serial.in_waiting, 4096))
                    if chunk:
                        bytes_in_interval += len(chunk)
                        self._bytes_read += len(chunk)

                        # Parsear y emitir
                        frames = self.parser.feed(chunk)
                        for frame in frames:
                            self._frames_ok += 1
                            frames_in_interval += 1
                            ftype = frame.get('type')

                            if ftype == FRAME_DATA:
                                self.data_frame_received.emit(frame)
                            elif ftype == FRAME_MEASUREMENTS:
                                self.measurements_received.emit(frame)
                            elif ftype == FRAME_INFO:
                                self.info_received.emit(frame)
                            elif ftype == FRAME_ACK:
                                self.ack_received.emit(frame.get('cmd', ''))
                            elif ftype == FRAME_NAK:
                                self.nak_received.emit(frame.get('cmd', ''), frame.get('reason', ''))

                        self._frames_error = self.parser.frames_error
                else:
                    # Pequeña pausa si no hay datos para no saturar CPU
                    time.sleep(0.001)

            except serial.SerialException as e:
                self.error_occurred.emit(f"Desconexión inesperada: {e}")
                break
            except Exception as e:
                self.error_occurred.emit(f"Error procesando serial: {e}")
                break

            # Actualizar stats cada segundo
            now = time.time()
            if now - self._last_stats_time >= 1.0:
                dt = now - self._last_stats_time
                self.fps = frames_in_interval / dt
                self.bytes_per_sec = bytes_in_interval / dt
                frames_in_interval = 0
                bytes_in_interval = 0
                self._last_stats_time = now

        # Limpieza final
        if self._serial and self._serial.is_open:
            self._serial.close()
        self.connection_changed.emit(False)
