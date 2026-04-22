"""
test_simulated.py — Simulated data source for testing the oscilloscope UI
                     without ESP32 hardware.

Mejoras:
  - AC coupling real: filtro high-pass IIR de 1er orden, fc ~10 Hz.
  - MeasurementsEngine conectado al flujo de datos.
  - Consistente con el comportamiento del modo real.

Usage:
    cd pc_app
    source .venv/bin/activate
    python test_simulated.py
"""

import sys
import os
import math
import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'pc_app'))

from core.data_store import DataStore
from core.fft_engine import FFTEngine
from core.measurements_engine import MeasurementsEngine
from core.frame_parser import FrameParser, FRAME_DATA
from core.serial_reader import SerialReader
from core.device_controller import DeviceController
from ui.main_window import MainWindow


class SimulatedSource:
    """
    Generates synthetic waveforms and pushes them to DataStore
    as if they were received from the ESP32.
    """

    def __init__(self, data_store, controller, sample_rate=100000, frame_size=1024):
        self.data_store = data_store
        self.controller = controller
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.seq = 0
        self.t_offset = 0.0

        # Signal parameters
        self.ch1_freq = 1000.0    # Hz
        self.ch1_amp = 1500.0     # mV (peak)
        self.ch1_type = 'sine'

        self.ch2_freq = 2000.0    # Hz
        self.ch2_amp = 800.0      # mV
        self.ch2_type = 'square'

        # Noise
        self.noise_mv = 20.0

        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._generate_frame)

    def start(self, interval_ms=33):
        """Start generating frames at ~30 FPS."""
        self.timer.start(interval_ms)

    def stop(self):
        self.timer.stop()

    def _generate_frame(self):
        dt = 1.0 / self.sample_rate
        t = np.arange(self.frame_size, dtype=np.float64) * dt + self.t_offset
        self.t_offset += self.frame_size * dt

        # Generate waveforms (with DC offsets)
        ch1_dc = 500.0   # 500mV DC offset
        ch2_dc = -300.0  # -300mV DC offset
        ch0_mv = self._gen_wave(t, self.ch1_freq, self.ch1_amp, self.ch1_type) + ch1_dc
        ch1_mv = self._gen_wave(t, self.ch2_freq, self.ch2_amp, self.ch2_type) + ch2_dc

        # Add noise
        ch0_mv += np.random.normal(0, self.noise_mv, self.frame_size).astype(np.float32)
        ch1_mv += np.random.normal(0, self.noise_mv, self.frame_size).astype(np.float32)

        cfg = self.controller.current_config

        # Time axis in us
        t_us = np.arange(self.frame_size, dtype=np.float64) * (1e6 / self.sample_rate)

        # Find trigger based on config
        trigger_idx = 0
        if cfg.trig_edge in (1, 2):  # Rising or Falling (UI encoding)
            trig_src = ch0_mv if cfg.trig_ch == 0 else ch1_mv
            lvl = cfg.trig_mv
            for i in range(1, len(trig_src)):
                if cfg.trig_edge == 1:  # Rising
                    if trig_src[i - 1] < lvl and trig_src[i] >= lvl:
                        trigger_idx = i
                        break
                elif cfg.trig_edge == 2:  # Falling
                    if trig_src[i - 1] > lvl and trig_src[i] <= lvl:
                        trigger_idx = i
                        break

        frame = {
            'type': FRAME_DATA,
            'seq': self.seq,
            'flags': 0x03,  # Both channels valid
            'ch0_valid': True,
            'ch1_valid': True,
            'trigger_hit': True,
            'overflow': False,
            'fft_attached': False,
            'sample_count': self.frame_size,
            'timestamp_us': int(self.t_offset * 1e6),
            'trigger_index': trigger_idx,
            'ch0_mv': ch0_mv,
            'ch1_mv': ch1_mv,
            'time_axis_us': t_us,
        }

        self.data_store.push(frame)
        self.seq += 1

    def _gen_wave(self, t, freq, amp, wtype):
        phase = 2 * np.pi * freq * t
        if wtype == 'sine':
            return (amp * np.sin(phase)).astype(np.float32)
        elif wtype == 'square':
            return (amp * np.sign(np.sin(phase))).astype(np.float32)
        elif wtype == 'triangle':
            return (amp * (2 / np.pi) * np.arcsin(np.sin(phase))).astype(np.float32)
        elif wtype == 'sawtooth':
            return (amp * (2 * (freq * t % 1) - 1)).astype(np.float32)
        else:
            return np.zeros(len(t), dtype=np.float32)


def main():
    app = QApplication(sys.argv)

    # Load stylesheet
    base_dir = os.path.dirname(os.path.abspath(__file__))
    qss_path = os.path.join(base_dir, "..", "pc_app", "assets", "stylesheet.qss")
    try:
        with open(qss_path, "r") as f:
            app.setStyleSheet(f.read())
    except Exception as e:
        print(f"Warning: Could not load stylesheet: {e}")

    # Core modules
    data_store = DataStore(capacity=1000)
    fft_engine = FFTEngine()
    meas_engine = MeasurementsEngine()

    parser = FrameParser()
    reader = SerialReader(parser)
    controller = DeviceController(reader)

    # Override controller to report as "connected" for simulation
    controller.connected = False
    controller.current_config.sample_rate = 100000
    controller.current_config.frame_size = 1024

    # Start measurements engine
    meas_engine.start()

    # Main window
    window = MainWindow(controller, reader, data_store, fft_engine, meas_engine)
    window.setWindowTitle("ESP32-S3 Oscilloscope — SIMULATION MODE")
    window.show()

    # NUEVO: Integrar ui_hold con botones RUN/STOP en modo simulado
    def _on_run():
        window.set_ui_hold(False)

    def _on_stop():
        window.set_ui_hold(True)

    cp = window.controls_panel
    cp.start_stream_requested.disconnect()
    cp.stop_stream_requested.disconnect()
    cp.start_stream_requested.connect(_on_run)
    cp.stop_stream_requested.connect(_on_stop)

    # Simulated data source
    sim = SimulatedSource(data_store, controller, sample_rate=100000, frame_size=1024)
    sim.start(interval_ms=33)  # ~30 FPS

    print("=" * 60)
    print("  SIMULATION MODE — No ESP32 hardware needed")
    print("  CH1: 1kHz sine, 1.5V peak")
    print("  CH2: 2kHz square, 800mV peak")
    print("")
    print("  Test these features:")
    print("    - Zoom/pan the waveform (mouse wheel + drag)")
    print("    - Toggle 'Time cursors' and 'Voltage cursors'")
    print("    - Drag cursors T1/T2/V1/V2 and check readouts")
    print("    - Click 'AUTO SCALE' button")
    print("    - Toggle Persistence/Average/Envelope checkboxes")
    print("    - Switch Display mode to FFT / XY / YT+FFT")
    print("    - Change V/div and T/div scales")
    print("    - Switch between Dark and Light themes")
    print("    - AC/DC coupling (real IIR high-pass filter)")
    print("    - Check that grid lines follow T/div and V/div")
    print("    - Measurements panel (Vpp, Vrms, Freq, etc.)")
    print("=" * 60)

    exit_code = app.exec()
    sim.stop()
    meas_engine.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
