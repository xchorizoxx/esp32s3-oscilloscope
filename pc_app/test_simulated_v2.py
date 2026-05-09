"""
test_simulated_v2.py — Script de simulación actualizado para el nuevo flujo de datos.
Permite verificar el rediseño visual de la Fase 2 sin hardware.
"""

import sys
import os
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Asegurar que podemos importar desde el directorio actual
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.data_store import DataStore
from core.fft_engine import FFTEngine
from core.measurements_engine import MeasurementsEngine
from core.frame_parser import FrameParser, FRAME_DATA
from core.serial_reader import SerialReader
from core.device_controller import DeviceController
from ui.main_window import MainWindow

class SimulatedSource:
    def __init__(self, data_store, controller, sample_rate=100000, frame_size=1024):
        self.data_store = data_store
        self.controller = controller
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.seq = 0
        self.t_offset = 0.0

        # Señales
        self.ch1_freq = 1000.0    # 1 kHz
        self.ch1_amp = 1200.0     # 1.2V
        self.ch2_freq = 2500.0    # 2.5 kHz
        self.ch2_amp = 600.0      # 600mV

        self.timer = QTimer()
        self.timer.timeout.connect(self._generate_frame)

    def start(self, fps=30):
        self.timer.start(int(1000 / fps))

    def _generate_frame(self):
        dt = 1.0 / self.sample_rate
        t = np.arange(self.frame_size, dtype=np.float64) * dt + self.t_offset
        self.t_offset += self.frame_size * dt

        # CH1: Senoidal con offset
        ch0_mv = self.ch1_amp * np.sin(2 * np.pi * self.ch1_freq * t) + 200.0
        # CH2: Cuadrada con offset
        ch1_mv = self.ch2_amp * np.sign(np.sin(2 * np.pi * self.ch2_freq * t)) - 100.0

        # Ruido base
        ch0_mv += np.random.normal(0, 10, self.frame_size)
        ch1_mv += np.random.normal(0, 10, self.frame_size)

        # Trigger estable con histéresis (Schmitt Trigger)
        trigger_idx = 0
        lvl = 200.0
        hyst = 50.0  # Banda de guarda
        armed = False
        
        trig_src = ch0_mv
        for i in range(1, len(trig_src)):
            # Armar cuando cae por debajo de lvl - hyst
            if not armed and trig_src[i] < (lvl - hyst):
                armed = True
            # Disparar cuando cruza lvl estando armado
            if armed and trig_src[i] >= lvl:
                trigger_idx = i
                break

        frame = {
            'type': FRAME_DATA,
            'seq': self.seq,
            'flags': 0x03,
            'ch0_valid': True,
            'ch1_valid': True,
            'trigger_hit': True,
            'overflow': False,
            'sample_count': self.frame_size,
            'timestamp_us': int(self.t_offset * 1e6),
            'trigger_index': trigger_idx,
            'ch0_mv': ch0_mv.astype(np.float32),
            'ch1_mv': ch1_mv.astype(np.float32),
        }

        self.data_store.push(frame)
        self.seq += 1

def main():
    app = QApplication(sys.argv)

    # Estilos
    base_dir = os.path.dirname(os.path.abspath(__file__))
    qss_path = os.path.join(base_dir, "assets", "stylesheet.qss")
    try:
        with open(qss_path, "r") as f:
            app.setStyleSheet(f.read())
    except:
        pass

    # Setup
    data_store = DataStore(capacity=1000)
    fft_engine = FFTEngine()
    meas_engine = MeasurementsEngine()
    parser = FrameParser()
    # Importante: Pasar data_store al reader por la Tarea 4 de la Fase 1
    reader = SerialReader(parser, data_store)
    controller = DeviceController(reader)

    # Simular config de hardware
    controller.connected = True # Engañar a la UI para que muestre stats
    controller.current_config.sample_rate = 100000
    controller.current_config.frame_size = 1024

    meas_engine.start()

    window = MainWindow(controller, reader, data_store, fft_engine, meas_engine)
    window.setWindowTitle("ESP32-S3 Oscilloscope — SIMULATOR V2")
    window.show()

    # Fuente de datos simulada
    sim = SimulatedSource(data_store, controller)
    sim.start()

    print("Simulador iniciado. Verificando Fases 1 y 2...")
    
    code = app.exec()
    meas_engine.stop()
    sys.exit(code)

if __name__ == "__main__":
    main()
