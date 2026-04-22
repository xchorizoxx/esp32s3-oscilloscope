"""
main_window.py — QMainWindow principal.
"""

import os
import numpy as np
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QSplitter
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

from .waveform_widget import WaveformWidget
from .fft_widget import FFTWidget
from .xy_widget import XYWidget
from .controls_panel import ControlsPanel
from .measurements_panel import MeasurementsPanel
from .status_bar import AppStatusBar


class MainWindow(QMainWindow):
    def __init__(self, controller, reader, data_store, fft_engine, meas_engine):
        super().__init__()
        self.setWindowTitle("ESP32-S3 Digital Oscilloscope")
        self.resize(1280, 800)

        # Icon with absolute path
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.controller = controller
        self.reader = reader
        self.data_store = data_store
        self.fft_engine = fft_engine
        self.meas_engine = meas_engine

        # Track stylesheet directory for theme switching
        self._assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        self._current_theme = 'dark'

        # Central Widget & Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter principal (Waveform vs FFT/XY)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_layout.addWidget(self.splitter)

        # Widgets principales
        self.waveform_widget = WaveformWidget()
        self.fft_widget = FFTWidget()
        self.xy_widget = XYWidget()

        self.splitter.addWidget(self.waveform_widget)
        self.splitter.addWidget(self.fft_widget)
        self.splitter.addWidget(self.xy_widget)

        # Ocultar paneles secundarios por defecto
        self.fft_widget.hide()
        self.xy_widget.hide()

        # Dock Widgets
        self.controls_panel = ControlsPanel("Controls")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.controls_panel)

        self.meas_panel = MeasurementsPanel("Measurements")
        self.meas_panel.setFeatures(
            MeasurementsPanel.DockWidgetFeature.DockWidgetClosable |
            MeasurementsPanel.DockWidgetFeature.DockWidgetMovable |
            MeasurementsPanel.DockWidgetFeature.DockWidgetFloatable
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.meas_panel)
        # Start collapsed (MEJORA-5)
        self.meas_panel.hide()

        # StatusBar
        self.status_bar = AppStatusBar()
        self.setStatusBar(self.status_bar)

        # Render Timer (30 FPS max)
        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._on_render_timer)
        self.render_timer.start(33)  # ~30 FPS

        self._overflow_count = 0
        self._setup_connections()
        self._populate_ports()

    def _setup_connections(self):
        cp = self.controls_panel

        # 1. Controller <-> ControlsPanel
        cp.connect_requested.connect(lambda p: self.controller.connect_device(p, 115200))
        cp.disconnect_requested.connect(self.controller.disconnect_device)
        cp.start_stream_requested.connect(self.controller.start_stream)
        cp.stop_stream_requested.connect(self.controller.stop_stream)
        cp.single_shot_requested.connect(self.controller.single_shot)

        cp.mode_changed.connect(self.controller.set_mode)
        cp.rate_changed.connect(self.controller.set_sample_rate)
        cp.frame_size_changed.connect(self.controller.set_frame_size)

        # Auto-scale (MEJORA-3)
        cp.auto_scale_requested.connect(self._on_auto_scale)

        # Refresh ports (BUG-5)
        cp.refresh_ports_requested.connect(self._populate_ports)

        # Theme toggle (MEJORA-6)
        cp.theme_toggle_requested.connect(self._on_theme_toggle)

        # Display modes
        cp.display_mode_changed.connect(self._on_display_mode)
        cp.timebase_changed.connect(self.waveform_widget.set_timebase)
        cp.roll_mode_changed.connect(self.waveform_widget.set_roll_mode)
        cp.roll_paused_changed.connect(self.waveform_widget.set_roll_paused)
        cp.chk_pers.toggled.connect(lambda s: self.waveform_widget.set_display_mode('persistence' if s else 'normal'))
        cp.chk_avg.toggled.connect(lambda s: self.waveform_widget.set_display_mode('average' if s else 'normal'))
        cp.chk_env.toggled.connect(lambda s: self.waveform_widget.set_display_mode('envelope' if s else 'normal'))

        # Cursors (MEJORA-2)
        cp.time_cursors_toggled.connect(self.waveform_widget.set_time_cursors_visible)
        cp.volt_cursors_toggled.connect(self.waveform_widget.set_volt_cursors_visible)

        # Channel Panels (BUG-3 is fixed in channel_panel.py)
        cp.ch1_panel.visibility_changed.connect(lambda v: self.waveform_widget.set_ch_visible(0, v))
        cp.ch1_panel.scale_changed.connect(lambda s: self.waveform_widget.set_voltage_scale(s, 0))
        cp.ch1_panel.offset_changed.connect(lambda o: self.waveform_widget.set_ch_offset(0, o))
        cp.ch1_panel.attenuation_changed.connect(lambda a: self.controller.set_attenuation(0, a))
        cp.ch1_panel.coupling_changed.connect(lambda c: self.controller.set_coupling(0, c))

        cp.ch2_panel.visibility_changed.connect(lambda v: self.waveform_widget.set_ch_visible(1, v))
        cp.ch2_panel.scale_changed.connect(lambda s: self.waveform_widget.set_voltage_scale(s, 1))
        cp.ch2_panel.offset_changed.connect(lambda o: self.waveform_widget.set_ch_offset(1, o))
        cp.ch2_panel.attenuation_changed.connect(lambda a: self.controller.set_attenuation(1, a))
        cp.ch2_panel.coupling_changed.connect(lambda c: self.controller.set_coupling(1, c))

        # Trigger
        cp.trig_panel.trigger_params_changed.connect(self.controller.set_trigger)
        cp.trig_panel.pre_trigger_changed.connect(self.controller.set_pre_trigger)
        cp.trig_panel.trigger_params_changed.connect(
            lambda ch, mv, edge: self.waveform_widget.set_trigger_level(mv, ch)
        )

        # 2. Reader -> UI Updates
        # BUG-4 fix: connect to BOTH status_bar AND controls_panel
        self.reader.connection_changed.connect(self.status_bar.set_connected)
        self.reader.connection_changed.connect(cp.on_connection_changed)
        self.reader.info_received.connect(cp.update_device_info)

        # Mediciones de hardware
        self.reader.measurements_received.connect(self.meas_panel.update_measurements)

    def _populate_ports(self):
        current = self.controls_panel.cb_ports.currentText()
        ports = self.controller.get_available_ports()
        self.controls_panel.cb_ports.blockSignals(True)
        self.controls_panel.cb_ports.clear()
        self.controls_panel.cb_ports.addItems(ports)
        # Restore previous selection if still available
        if current in ports:
            self.controls_panel.cb_ports.setCurrentText(current)
        self.controls_panel.cb_ports.blockSignals(False)

    def _on_display_mode(self, mode: str):
        self.waveform_widget.show()
        self.fft_widget.hide()
        self.xy_widget.hide()

        if mode == "XY":
            self.waveform_widget.hide()
            self.xy_widget.show()
        elif mode == "FFT":
            self.waveform_widget.hide()
            self.fft_widget.show()
        elif mode == "YT+FFT":
            self.fft_widget.show()
            self.splitter.setSizes([self.height() // 2, self.height() // 2, 0])

    def _on_auto_scale(self):
        """Auto-scale using the latest frame data."""
        frames = self.data_store.get_last_n(1)
        if not frames:
            return
        latest = frames[-1]
        ch1 = latest.get('ch0_mv')
        ch2 = latest.get('ch1_mv')
        rate = self.controller.current_config.sample_rate
        count = latest.get('sample_count', 0)
        self.waveform_widget.auto_scale(ch1, ch2, rate, count)

    def _on_theme_toggle(self, theme: str):
        """Switch between dark and light themes."""
        self._current_theme = theme
        if theme == 'light':
            qss_path = os.path.join(self._assets_dir, "stylesheet_light.qss")
        else:
            qss_path = os.path.join(self._assets_dir, "stylesheet.qss")

        try:
            with open(qss_path, "r") as f:
                from PyQt6.QtWidgets import QApplication
                QApplication.instance().setStyleSheet(f.read())
        except Exception:
            pass

        # Update plot backgrounds for theme
        if theme == 'light':
            bg = '#f8fafc'
            grid_color = '#cbd5e1'
        else:
            bg = '#09090b'
            grid_color = '#27272a'

        self.waveform_widget.plot_widget.setBackground(bg)
        self.waveform_widget.BG_COLOR = bg
        self.waveform_widget.GRID_MAJOR = grid_color
        self.waveform_widget._draw_dynamic_grid()

        self.fft_widget.plot_widget.setBackground(bg)
        self.xy_widget.plot_widget.setBackground(bg)

    def _on_render_timer(self):
        # 1. Update status bar stats
        if self.controller.connected:
            stats = self.reader.get_stats()
            self.status_bar.update_stats(stats['fps'], stats['bytes_per_sec'], stats['frames_crc_err'])
            self.status_bar.update_rate(self.controller.current_config.sample_rate)

        # 2. Get latest data
        frames = self.data_store.get_last_n(5)
        if not frames:
            return

        latest = frames[-1]
        ch1 = latest.get('ch0_mv')
        ch2 = latest.get('ch1_mv')
        rate = self.controller.current_config.sample_rate
        sample_count = latest.get('sample_count', 0)
        trigger_idx = latest.get('trigger_index', 0)

        # BUG-2 fix: Calculate proper time axis in µs using sample rate
        if rate > 0 and sample_count > 0:
            dt_us = 1e6 / rate
            t_us = np.arange(sample_count, dtype=np.float64) * dt_us
            # Center on trigger point (trigger at t=0, pre-trigger in negative time)
            t_us = t_us - trigger_idx * dt_us
        else:
            t_us = latest.get('time_axis_us')

        if t_us is None:
            return

        # Track overflow
        if latest.get('overflow', False):
            self._overflow_count += 1

        # 3. Waveform Render
        mode = self.waveform_widget.display_mode
        if mode == 'normal':
            self.waveform_widget.update_frame(t_us, ch1, ch2)
        elif mode == 'average':
            a1 = self.data_store.get_average(4, 'ch0_mv')
            a2 = self.data_store.get_average(4, 'ch1_mv')
            self.waveform_widget.update_frame(t_us, a1, a2)
        elif mode == 'envelope':
            e1 = self.data_store.get_envelope(4, 'ch0_mv')
            e2 = self.data_store.get_envelope(4, 'ch1_mv')
            min1, max1 = e1 if e1 else (None, None)
            min2, max2 = e2 if e2 else (None, None)
            self.waveform_widget.update_envelope(t_us, min1, max1, min2, max2)
        elif mode == 'persistence':
            # Assign corrected time axes to all historical frames
            for f in frames:
                sc = f.get('sample_count', 0)
                ti = f.get('trigger_index', 0)
                if rate > 0 and sc > 0:
                    f['time_axis_us'] = np.arange(sc, dtype=np.float64) * (1e6 / rate) - ti * (1e6 / rate)
            self.waveform_widget.update_persistence(frames)

        # 4. XY Render
        if not self.xy_widget.isHidden():
            self.xy_widget.update_xy(ch1, ch2)

        # 5. FFT Render
        if not self.fft_widget.isHidden():
            if ch1 is not None:
                res1 = self.fft_engine.compute(ch1, rate)
                if res1:
                    self.fft_widget.update_fft(0, res1['freqs'], res1['magnitudes_mv'],
                                               res1['magnitudes_db'], res1['peak_freq'], res1['peak_magnitude_mv'])
            if ch2 is not None:
                res2 = self.fft_engine.compute(ch2, rate)
                if res2:
                    self.fft_widget.update_fft(1, res2['freqs'], res2['magnitudes_mv'],
                                               res2['magnitudes_db'], res2['peak_freq'], res2['peak_magnitude_mv'])
