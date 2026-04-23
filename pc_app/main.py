"""
main.py — Punto de entrada de la aplicacion Python del osciloscopio ESP32.

Integra ui_hold: STOP congela la visualizacion, RUN la descongela.
"""

import sys
import os
from PyQt6.QtWidgets import QApplication

from core.data_store import DataStore
from core.fft_engine import FFTEngine
from core.measurements_engine import MeasurementsEngine
from core.frame_parser import FrameParser
from core.serial_reader import SerialReader
from core.device_controller import DeviceController
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    # Resolve paths relative to this script's location
    base_dir = os.path.dirname(os.path.abspath(__file__))
    qss_path = os.path.join(base_dir, "assets", "stylesheet.qss")

    # Load dark theme by default
    try:
        with open(qss_path, "r") as f:
            app.setStyleSheet(f.read())
    except Exception as e:
        print(f"Warning: Could not load stylesheet: {e}")

    # Inicializar modulos core
    data_store  = DataStore(capacity=1000)
    fft_engine  = FFTEngine()
    meas_engine = MeasurementsEngine()

    parser      = FrameParser()
    reader      = SerialReader(parser)
    controller  = DeviceController(reader)

    # Conectar SerialReader con DataStore
    reader.data_frame_received.connect(data_store.push)

    # Arrancar hilo de mediciones
    meas_engine.start()

    # Ventana principal
    window = MainWindow(controller, reader, data_store, fft_engine, meas_engine)
    window.show()

    # NUEVO: Integrar ui_hold con botones RUN/STOP
    # STOP = congela UI + detiene stream del firmware
    # RUN = descongela UI + inicia stream del firmware
    def _on_run():
        window.set_ui_hold(False)
        controller.start_stream()

    def _on_stop():
        window.set_ui_hold(True)
        controller.stop_stream()

    # Reconectar las senales de los botones para incluir ui_hold
    # BUG-04 FIX: disconnect() sin args puede lanzar RuntimeError en PyQt6
    # si la senal no tiene slots previos conectados.
    cp = window.controls_panel
    try:
        cp.start_stream_requested.disconnect()
    except RuntimeError:
        pass
    try:
        cp.stop_stream_requested.disconnect()
    except RuntimeError:
        pass
    cp.start_stream_requested.connect(_on_run)
    cp.stop_stream_requested.connect(_on_stop)

    # Ejecutar loop de UI
    exit_code = app.exec()

    # Limpieza al salir
    meas_engine.stop()
    controller.disconnect_device()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
