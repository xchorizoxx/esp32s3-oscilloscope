"""
main_window.py — QMainWindow principal.

Correcciones integradas:
  - Estado ui_hold independiente del hardware (STOP congela UI, RUN la descongela).
  - AC coupling digital: filtro high-pass IIR de 1er orden, fc ~10 Hz.
  - MeasurementsEngine conectado al flujo de datos (submit + signal).
  - Persistence: precalculo de eje temporal evitado (DataStore ya lo tiene).
  - Status bar con nombre de puerto y sample rate.
  - FFT controles funcionales (unidad + ventana).
"""

import os
import numpy as np
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QSplitter
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QShortcut, QKeySequence

from .waveform_widget import WaveformWidget
from .fft_widget import FFTWidget
from .xy_widget import XYWidget
from .controls_panel import ControlsPanel
from .measurements_panel import MeasurementsPanel
from .status_bar import AppStatusBar
from .pga_cal_dialog import PgaCalDialog
from core.render_pipeline import RenderPipeline


class MainWindow(QMainWindow):
    def __init__(self, controller, reader, data_store, fft_engine, meas_engine):
        super().__init__()
        self.setWindowTitle("ESP32-S3 Digital Oscilloscope")
        self.resize(1280, 800)

        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.controller = controller
        self.reader = reader
        self.data_store = data_store
        self.fft_engine = fft_engine
        self.meas_engine = meas_engine

        self._assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        self._current_theme = 'dark'

        # Central Widget & Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Splitter principal
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_layout.addWidget(self.splitter)

        # Widgets principales
        self.waveform_widget = WaveformWidget()
        self.fft_widget = FFTWidget()
        self.xy_widget = XYWidget()

        self.splitter.addWidget(self.waveform_widget)
        self.splitter.addWidget(self.fft_widget)
        self.splitter.addWidget(self.xy_widget)

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
        # BUG-10 FIX: show measurements panel by default (was hidden)
        # self.meas_panel.hide()  <-- removed

        # StatusBar
        self.status_bar = AppStatusBar()
        self.setStatusBar(self.status_bar)

        # Render Timer (30 FPS max)
        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._on_render_timer)
        self.render_timer.start(33)

        self._overflow_count = 0

        # --- UI state ---
        self._ui_hold = False

        # --- Render pipeline (extracts all render logic) ---
        self.render_pipeline = RenderPipeline(data_store, meas_engine, fft_engine)

        # --- AC coupling state reference (delegates to pipeline) ---
        self._ac_couple_state = self.render_pipeline._ac_state

        self._setup_connections()
        self._setup_shortcuts()
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
        cp.oversampling_changed.connect(self.controller.set_oversampling)
        cp.frame_size_changed.connect(self.controller.set_frame_size)

        cp.auto_scale_requested.connect(self._on_auto_scale)
        cp.refresh_ports_requested.connect(self._populate_ports)
        cp.theme_toggle_requested.connect(self._on_theme_toggle)
        cp.reload_requested.connect(self.reload_app)

        # Display modes
        cp.display_mode_changed.connect(self._on_display_mode)
        cp.ui_hold_changed.connect(self.set_ui_hold)

        # Signal Generator
        cp.gen_start_requested.connect(self.controller.set_gen_start)
        cp.gen_stop_requested.connect(self.controller.set_gen_stop)

        # PGA
        cp.pga_enabled_changed.connect(self._on_pga_enabled_changed)
        cp.pga_step_changed.connect(self._on_pga_step_changed)
        cp.pga_cal_requested.connect(self._on_pga_cal_requested)
        cp.adc_correction_requested.connect(self._on_adc_correction_requested)

        cp.timebase_changed.connect(self.waveform_widget.set_timebase)
        cp.roll_mode_changed.connect(self.waveform_widget.set_roll_mode)
        cp.roll_paused_changed.connect(self.waveform_widget.set_roll_paused)
        cp.chk_pers.toggled.connect(lambda s: self.waveform_widget.set_display_mode('persistence' if s else 'normal'))
        cp.chk_avg.toggled.connect(lambda s: self.waveform_widget.set_display_mode('average' if s else 'normal'))
        cp.chk_env.toggled.connect(lambda s: self.waveform_widget.set_display_mode('envelope' if s else 'normal'))

        # Cursors
        cp.time_cursors_toggled.connect(self.waveform_widget.set_time_cursors_visible)
        cp.volt_cursors_toggled.connect(self.waveform_widget.set_volt_cursors_visible)

        # Channel Panels — CH1=indice 0, CH2=indice 1 (mapeo explicito)
        cp.ch1_panel.visibility_changed.connect(lambda v: self.waveform_widget.set_ch_visible(0, v))
        cp.ch1_panel.scale_changed.connect(lambda s: self.waveform_widget.set_voltage_scale(s, 0))
        cp.ch1_panel.offset_changed.connect(lambda o: self.waveform_widget.set_ch_offset(0, o))
        cp.ch1_panel.attenuation_changed.connect(lambda a: self.controller.set_attenuation(0, a))
        cp.ch1_panel.coupling_changed.connect(lambda c: self._on_coupling_changed(0, c))
        # BUG-12 FIX: CAL GND resets EMA integrator for CH1
        cp.ch1_panel.cal_gnd_requested.connect(lambda: self._reset_ac_coupling(0))

        cp.ch2_panel.cal_gnd_requested.connect(lambda: self._reset_ac_coupling(1))

        # Trigger
        cp.trig_panel.trigger_hw_changed.connect(self.controller.set_trigger)
        cp.trig_panel.trigger_ui_preview.connect(
            lambda mv, ch: self.waveform_widget.set_trigger_level(mv, ch)
        )
        cp.trig_panel.pre_trigger_changed.connect(self.controller.set_pre_trigger)

        # Autoscale synchronization
        self.waveform_widget.autoscale_finished.connect(self._on_autoscale_finished)

        # 2. Reader -> UI Updates
        self.reader.connection_changed.connect(self._on_connection_changed)
        self.reader.info_received.connect(cp.update_device_info)

        # NUEVO: Mediciones locales del MeasurementsEngine (ignorar las del hardware para evitar jitter)
        self.meas_engine.measurements_ready.connect(self.meas_panel.update_measurements)
        self.meas_engine.measurements_ready.connect(self._on_measurements_update)

        # NUEVO: FFT controls
        self.fft_widget.window_changed.connect(self._on_fft_window_changed)

        # PGA info from reader
        self.reader.pga_info_received.connect(self._on_pga_info_received)

    def _setup_shortcuts(self):
        """Keyboard shortcuts for oscilloscope-style operation."""
        # Space = toggle RUN/STOP
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self._toggle_run_stop)
        # S = Single shot
        QShortcut(QKeySequence(Qt.Key.Key_S), self, activated=self.controller.single_shot)
        # A = AutoScale
        QShortcut(QKeySequence(Qt.Key.Key_A), self, activated=self._on_auto_scale)
        # H = Hold toggle
        QShortcut(QKeySequence(Qt.Key.Key_H), self, activated=lambda: self.set_ui_hold(not self._ui_hold))

    def _toggle_run_stop(self):
        """Toggle between RUN and STOP states."""
        if self.controller.connected:
            if self._ui_hold:
                self.set_ui_hold(False)
                self.controller.start_stream()
            else:
                self.controller.stop_stream()
                self.set_ui_hold(True)

    def _on_connection_changed(self, connected: bool, port: str = ""):
        """Maneja cambios de conexion del SerialReader."""
        self.status_bar.set_connected(connected, port)
        self.controls_panel.on_connection_changed(connected)
        if not connected:
            self.status_bar.update_rate(0)
            # Ghost frame fix: clear waveform when disconnected
            self._clear_waveform()

    def _clear_waveform(self):
        """Delega el borrado de curvas al WaveformWidget (PC-15 FIX: no more internal access)."""
        self.waveform_widget.clear()

    def _on_coupling_changed(self, ch: int, coupling: str):
        """Maneja cambio de AC/DC/GND coupling. Actualiza estado local y controller."""
        self._ac_couple_state[ch]['mode'] = coupling.upper()
        if coupling.upper() in ['DC', 'GND']:
            self._ac_couple_state[ch]['dc_offset'] = None
        self.controller.set_coupling(ch, coupling)

    def _reset_ac_coupling(self, ch: int):
        """Resetea el integrador EMA del canal dado.
           Esto NO es una calibración de hardware — solo reinicia el
           filtro AC coupling software en la PC."""
        self._ac_couple_state[ch]['dc_offset'] = None
        if ch == 0:
            self.waveform_widget.curve_ch1.setData([], [])
        else:
            self.waveform_widget.curve_ch2.setData([], [])

    def reload_app(self):
        """Recarga completa de la aplicacion Python (re-exec del proceso)."""
        import os, sys
        # Asegurarse de desconectar hardware antes de reiniciar
        try:
            self.controller.disconnect_device()
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)


    def _on_fft_window_changed(self, window: str):
        """Propaga cambio de ventana FFT al engine."""
        # El engine lee el parametro en cada compute(), asi que solo necesitamos guardarlo
        self.fft_engine.last_window = window.lower()

    # ------------------------------------------------------------------
    # PGA handlers
    # ------------------------------------------------------------------

    def _on_pga_info_received(self, info: dict):
        cfg = self.controller.current_config
        self.controls_panel.update_pga_info({
            'step': cfg.pga_step,
            'gain_eff': cfg.pga_gain_eff,
            'offset_cal': cfg.pga_offset_cal,
            'bw_hz': cfg.pga_bw_hz,
            'vg_mv': cfg.pga_vg_mv,
            'div_ratio': cfg.pga_div_ratio,
            'calibrated': cfg.pga_calibrated,
            'enabled': cfg.pga_enabled,
        })

        gain = cfg.pga_gain_eff[cfg.pga_step] if cfg.pga_step < len(cfg.pga_gain_eff) else 1.0
        offset = cfg.pga_offset_cal[cfg.pga_step] if cfg.pga_step < len(cfg.pga_offset_cal) else 0.0
        self.waveform_widget.set_pga_params(
            enabled=cfg.pga_enabled, step=cfg.pga_step, vg_mv=cfg.pga_vg_mv,
            gain_eff=gain, offset_mv=offset, div_ratio=cfg.pga_div_ratio)
        self.render_pipeline.set_pga_params(
            enabled=cfg.pga_enabled, vg_mv=cfg.pga_vg_mv,
            gain_eff=gain, offset_mv=offset, div_ratio=cfg.pga_div_ratio)

        bw = cfg.pga_bw_hz[cfg.pga_step] if cfg.pga_step < len(cfg.pga_bw_hz) else 1000000.0
        self.meas_panel.update_pga_display(gain, bw)

    def _on_pga_enabled_changed(self, enabled: bool):
        # PC-03 FIX: always update local config + pipeline state, even when offline.
        # This ensures waveform_widget and render_pipeline stay consistent.
        self.controller.current_config.pga_enabled = enabled
        self.controls_panel.cb_pga_step.setEnabled(enabled)
        cfg = self.controller.current_config
        gain   = cfg.pga_gain_eff[cfg.pga_step]   if cfg.pga_step < len(cfg.pga_gain_eff)   else 1.0
        offset = cfg.pga_offset_cal[cfg.pga_step] if cfg.pga_step < len(cfg.pga_offset_cal) else 0.0
        self.waveform_widget.set_pga_params(
            enabled=enabled, step=cfg.pga_step, vg_mv=cfg.pga_vg_mv,
            gain_eff=gain, offset_mv=offset, div_ratio=cfg.pga_div_ratio)
        self.render_pipeline.set_pga_params(
            enabled=enabled, vg_mv=cfg.pga_vg_mv,
            gain_eff=gain, offset_mv=offset, div_ratio=cfg.pga_div_ratio)
        if not self.controller.connected:
            return
        self.controller.set_pga_enabled(enabled)
        if enabled:
            self.controller.pga_get_info()

    def _on_pga_step_changed(self, step: int):
        if not self.controller.connected:
            return
        self.controller.set_pga_step(step)
        cfg = self.controller.current_config
        self.controls_panel.update_pga_info({
            'step': step,
            'gain_eff': cfg.pga_gain_eff,
            'offset_cal': cfg.pga_offset_cal,
            'bw_hz': cfg.pga_bw_hz,
            'vg_mv': cfg.pga_vg_mv,
            'div_ratio': cfg.pga_div_ratio,
            'calibrated': cfg.pga_calibrated,
            'enabled': cfg.pga_enabled,
        })
        gain = cfg.pga_gain_eff[step] if step < len(cfg.pga_gain_eff) else 1.0
        offset = cfg.pga_offset_cal[step] if step < len(cfg.pga_offset_cal) else 0.0
        self.waveform_widget.set_pga_params(
            enabled=cfg.pga_enabled, step=step, vg_mv=cfg.pga_vg_mv,
            gain_eff=gain, offset_mv=offset, div_ratio=cfg.pga_div_ratio)
        self.render_pipeline.set_pga_params(
            enabled=cfg.pga_enabled, vg_mv=cfg.pga_vg_mv,
            gain_eff=gain, offset_mv=offset, div_ratio=cfg.pga_div_ratio)
        bw = cfg.pga_bw_hz[step] if step < len(cfg.pga_bw_hz) else 1000000.0
        self.meas_panel.update_pga_display(gain, bw)

    def _on_pga_cal_requested(self):
        dialog = PgaCalDialog(self.controller, self)
        dialog.exec()
        if self.controller.connected:
            self.controller.pga_get_info()

    def _on_adc_correction_requested(self, factor: float):
        # PC-08 FIX: set_adc_correction now updates local config unconditionally.
        # Returns True even when offline (saved locally, pushed on next connect).
        ok = self.controller.set_adc_correction(factor)
        if ok:
            if self.controller.connected:
                self.controls_panel.lbl_adc_corr_status.setText("OK")
            else:
                self.controls_panel.lbl_adc_corr_status.setText("Saved (offline)")
        else:
            self.controls_panel.lbl_adc_corr_status.setText("FAIL")

    def _populate_ports(self):
        current = self.controls_panel.cb_ports.currentText()
        ports = self.controller.get_available_ports()
        self.controls_panel.cb_ports.blockSignals(True)
        self.controls_panel.cb_ports.clear()
        self.controls_panel.cb_ports.addItems(ports)
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
        import numpy as np
        frames = self.data_store.get_last_n(1)
        if not frames:
            return
        latest = frames[-1]
        ch1_raw = latest.get('ch0_mv')
        ch2_raw = latest.get('ch1_mv')
        rate = self.controller.current_config.sample_rate
        count = latest.get('sample_count', 0)

        ch1 = np.array(ch1_raw, dtype=np.float32) if ch1_raw is not None else None
        ch2 = np.array(ch2_raw, dtype=np.float32) if ch2_raw is not None else None

        if ch1 is not None and self.controller.current_config.pga_enabled:
            cfg = self.controller.current_config
            gain = cfg.pga_gain_eff[cfg.pga_step] if cfg.pga_step < len(cfg.pga_gain_eff) else 1.0
            offset = cfg.pga_offset_cal[cfg.pga_step] if cfg.pga_step < len(cfg.pga_offset_cal) else 0.0
            if gain > 0:
                ch1 = (ch1 - cfg.pga_vg_mv - offset) / gain / cfg.pga_div_ratio

        self.waveform_widget.auto_scale(ch1, ch2, rate, count)

    def _on_autoscale_finished(self, scale_mv: float, timebase_us: float):
        """Sincroniza los controles de la UI tras un Autoscale."""
        self.controls_panel.set_timebase_value(timebase_us)
        self.controls_panel.set_voltage_scale_value(scale_mv, 0)
        self.controls_panel.set_voltage_scale_value(scale_mv, 1)

    def _on_theme_toggle(self, theme: str):
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

        if theme == 'light':
            bg = '#f8fafc'
            grid_color = '#cbd5e1'
        else:
            bg = '#09090b'
            grid_color = '#27272a'

        self.waveform_widget.plot_widget.setBackground(bg)
        self.waveform_widget.BG_COLOR = bg
        self.waveform_widget.GRID_MAJOR = grid_color

        self.fft_widget.plot_widget.setBackground(bg)
        self.xy_widget.plot_widget.setBackground(bg)

    def _on_render_timer(self):
        # 1. Update status bar
        if self.controller.connected:
            stats = self.reader.get_stats()
            self.status_bar.update_stats(
                stats['fps'], stats['bytes_per_sec'],
                self.render_pipeline.overflow_count
            )
            cfg = self.controller.current_config
            self.status_bar.update_rate(int(cfg.sample_rate / cfg.oversampling))

        # 2. Skip rendering if UI is held
        if self._ui_hold:
            return

        # 3. Delegate all rendering to the pipeline
        self.render_pipeline.process_frame(
            cfg=self.controller.current_config,
            waveform_widget=self.waveform_widget,
            fft_widget=self.fft_widget,
            xy_widget=self.xy_widget
        )

    # ------------------------------------------------------------------
    # NUEVO: Control de ui_hold (independiente del hardware stream)
    # ------------------------------------------------------------------

    def set_ui_hold(self, hold: bool):
        """
        Activa o desactiva el congelamiento de la UI.
        Cuando hold=True, la visualizacion se congela (no se actualiza con datos nuevos).
        El firmware puede seguir transmitiendo o no — es independiente.
        """
        self._ui_hold = hold

    def is_ui_hold(self) -> bool:
        return self._ui_hold

    # ------------------------------------------------------------------
    # Measurement overlay on waveform
    # ------------------------------------------------------------------

    def _on_measurements_update(self, data: dict):
        """Pipe measurement results to the waveform overlay."""
        self.waveform_widget.update_overlay(
            ch0_meas=data.get('ch0'),
            ch1_meas=data.get('ch1')
        )
