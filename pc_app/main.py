"""
main.py — Punto de entrada de la aplicación Python del osciloscopio ESP32.
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

    # Inicializar módulos core
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

    # Ejecutar loop de UI
    exit_code = app.exec()

    # Limpieza al salir
    meas_engine.stop()
    controller.disconnect_device()

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
