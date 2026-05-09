"""
serial_reader.py — QThread que lee el puerto USB CDC y emite senales con frames parseados.

Mejoras de robustez:
  - Manejo graceful de desconexion USB durante streaming.
  - Estadisticas protegidas con QMutex (acceso desde UI thread).
  - Emite nombre de puerto junto con estado de conexion.
"""

import time
import serial
from PyQt6.QtCore import QThread, pyqtSignal, QMutex
from .frame_parser import FrameParser, FRAME_DATA, FRAME_MEASUREMENTS, FRAME_INFO, FRAME_ACK, FRAME_NAK


class SerialReader(QThread):
    """
    Hilo dedicado a leer del puerto serie y parsear los datos.
    """

    # Senales para comunicarse con la UI (Data frame se pasa directo a DataStore)
    measurements_received = pyqtSignal(dict)
    measurements_received = pyqtSignal(dict)
    info_received         = pyqtSignal(dict)
    ack_received          = pyqtSignal(str)
    nak_received          = pyqtSignal(str, str)
    # Emite (connected: bool, port: str) para que la status bar muestre el puerto
    connection_changed    = pyqtSignal(bool, str)
    error_occurred        = pyqtSignal(str)

    def __init__(self, parser: FrameParser, data_store=None, parent=None) -> None:
        super().__init__(parent)
        self.parser = parser
        self.data_store = data_store
        self.port = ""
        self.baudrate = 115200
        self._running = False
        self._serial: serial.Serial | None = None
        self._mutex = QMutex()
        self._stats_mutex = QMutex()

        # Estadisticas
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
        was_running = self._running
        self._running = False
        self._mutex.unlock()
        # Solo esperar si el hilo estaba corriendo y no es el hilo actual
        if was_running and self is not QThread.currentThread():
            if not self.wait(3000):  # Timeout de 3 segundos
                self.terminate()
                self.wait(1000)

    def send_bytes(self, data: bytes) -> bool:
        """Envia bytes al dispositivo si esta conectado."""
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
        """Obtiene estadisticas de forma thread-safe."""
        self._stats_mutex.lock()
        try:
            return {
                'frames_ok': self._frames_ok,
                'frames_crc_err': self._frames_error,
                'fps': self.fps,
                'bytes_per_sec': self.bytes_per_sec
            }
        finally:
            self._stats_mutex.unlock()

    def run(self) -> None:
        self._mutex.lock()
        port = self.port
        baudrate = self.baudrate
        self._mutex.unlock()

        try:
            self._serial = serial.Serial(port, baudrate, timeout=0.1)
            self.parser.reset()
        except Exception as e:
            self.error_occurred.emit(f"No se pudo abrir {port}: {e}")
            self.connection_changed.emit(False, "")
            return

        # Emitir conexion exitosa con nombre de puerto
        self.connection_changed.emit(True, port)

        frames_in_interval = 0
        bytes_in_interval = 0

        while True:
            self._mutex.lock()
            running = self._running
            self._mutex.unlock()

            if not running:
                break

            try:
                # Tarea 2: No Active Polling - read() bloquea nativamente hasta timeout=0.1
                # Pedimos max(1, in_waiting) para leer al menos 1 byte o lo que haya en buffer.
                chunk = self._serial.read(max(1, min(self._serial.in_waiting, 4096)))
                
                if chunk:
                    bytes_in_interval += len(chunk)
                    self._stats_mutex.lock()
                    self._bytes_read += len(chunk)
                    self._stats_mutex.unlock()

                    # Parsear
                    frames = self.parser.feed(chunk)
                    frames_count = len(frames)
                    
                    if frames_count > 0:
                        # Tarea 1: Mutex Grouping - Actualizar contadores una sola vez por chunk
                        self._stats_mutex.lock()
                        self._frames_ok += frames_count
                        self._stats_mutex.unlock()
                        frames_in_interval += frames_count

                        for frame in frames:
                            ftype = frame.get('type')

                            if ftype == FRAME_DATA:
                                # Tarea 4: UI Throttling - Push directo al DataStore (sin señal Qt)
                                if self.data_store:
                                    self.data_store.push(frame)
                            elif ftype == FRAME_MEASUREMENTS:
                                self.measurements_received.emit(frame)
                            elif ftype == FRAME_INFO:
                                self.info_received.emit(frame)
                            elif ftype == FRAME_ACK:
                                self.ack_received.emit(frame.get('cmd', ''))
                            elif ftype == FRAME_NAK:
                                self.nak_received.emit(frame.get('cmd', ''), frame.get('reason', ''))

                    # Sincronizar errores de CRC
                    self._stats_mutex.lock()
                    self._frames_error = self.parser.frames_error
                    self._stats_mutex.unlock()

            except serial.SerialException as e:
                self.error_occurred.emit(f"Desconexion inesperada: {e}")
                break
            except Exception as e:
                self.error_occurred.emit(f"Error procesando serial: {e}")
                break

            # Actualizar stats cada segundo
            now = time.time()
            if now - self._last_stats_time >= 1.0:
                dt = now - self._last_stats_time
                self._stats_mutex.lock()
                self.fps = frames_in_interval / dt
                self.bytes_per_sec = bytes_in_interval / dt
                self._stats_mutex.unlock()
                frames_in_interval = 0
                bytes_in_interval = 0
                self._last_stats_time = now

        # Limpieza final
        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass
        self._serial = None
        self.connection_changed.emit(False, "")
