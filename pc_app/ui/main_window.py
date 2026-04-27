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

        # --- NUEVO: Estado ui_hold independiente del hardware ---
        self._ui_hold = False

        # --- NUEVO: Estado del AC coupling filter (Integrador EMA) ---
        self._ac_couple_state = {
            0: {'dc_offset': None, 'mode': 'DC'},
            1: {'dc_offset': None, 'mode': 'DC'},
        }

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
        cp.ch1_panel.cal_gnd_requested.connect(lambda: self._on_cal_gnd(0))

        cp.ch2_panel.visibility_changed.connect(lambda v: self.waveform_widget.set_ch_visible(1, v))
        cp.ch2_panel.scale_changed.connect(lambda s: self.waveform_widget.set_voltage_scale(s, 1))
        cp.ch2_panel.offset_changed.connect(lambda o: self.waveform_widget.set_ch_offset(1, o))
        cp.ch2_panel.attenuation_changed.connect(lambda a: self.controller.set_attenuation(1, a))
        cp.ch2_panel.coupling_changed.connect(lambda c: self._on_coupling_changed(1, c))
        # BUG-12 FIX: CAL GND resets EMA integrator for CH2
        cp.ch2_panel.cal_gnd_requested.connect(lambda: self._on_cal_gnd(1))

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

        # Mediciones del firmware (frames MEASUREMENTS)
        self.reader.measurements_received.connect(self.meas_panel.update_measurements)

        # NUEVO: Mediciones locales del MeasurementsEngine
        self.meas_engine.measurements_ready.connect(self.meas_panel.update_measurements)

        # NUEVO: FFT controls
        self.fft_widget.window_changed.connect(self._on_fft_window_changed)

    def _on_connection_changed(self, connected: bool, port: str = ""):
        """Maneja cambios de conexion del SerialReader."""
        self.status_bar.set_connected(connected, port)
        self.controls_panel.on_connection_changed(connected)
        if not connected:
            self.status_bar.update_rate(0)
            # Ghost frame fix: clear waveform when disconnected
            self._clear_waveform()

    def _clear_waveform(self):
        """Borra todas las curvas del waveform widget (evita ghost frames)."""
        ww = self.waveform_widget
        ww.curve_ch1.setData([], [])
        ww.curve_ch2.setData([], [])
        for c in ww.persistence_curves_ch1:
            c.setData([], [])
        for c in ww.persistence_curves_ch2:
            c.setData([], [])
        ww._env_ch1_lo.setData([], [])
        ww._env_ch1_hi.setData([], [])
        ww._env_ch2_lo.setData([], [])
        ww._env_ch2_hi.setData([], [])

    def _on_coupling_changed(self, ch: int, coupling: str):
        """Maneja cambio de AC/DC/GND coupling. Actualiza estado local y controller."""
        self._ac_couple_state[ch]['mode'] = coupling.upper()
        if coupling.upper() in ['DC', 'GND']:
            self._ac_couple_state[ch]['dc_offset'] = None
        self.controller.set_coupling(ch, coupling)

    def _on_cal_gnd(self, ch: int):
        """
        BUG-12 FIX: Calibracion de GND.
        Resetea el integrador EMA del canal dado para que la senal se
        muestre centrada en su nivel real de cero del ADC.
        Corrige el sintoma: 'senal cae a -1V al desconectar la entrada'.
        """
        self._ac_couple_state[ch]['dc_offset'] = None
        # Tambien limpiar la pantalla para que el usuario vea el efecto inmediato
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

    def _apply_ac_coupling(self, samples: np.ndarray, ch: int, sample_rate: int) -> np.ndarray:
        """
        Aplica filtro de visualización según el modo seleccionado (DC, AC, GND).
        Usa un Integrador (EMA) para aislar la componente DC de la alterna.
        """
        mode = self._ac_couple_state[ch].get('mode', 'DC')
        
        if mode == 'GND':
            return np.zeros_like(samples)
            
        if mode == 'DC':
            return samples
            
        if len(samples) == 0:
            return samples

        # 1. Obtenemos el DC inmediato de este frame
        frame_mean = np.mean(samples)

        # 2. Actualizamos el integrador lento (EMA)
        alpha_ema = 0.05
        state = self._ac_couple_state[ch]

        if state['dc_offset'] is None:
            state['dc_offset'] = frame_mean
        else:
            state['dc_offset'] = alpha_ema * frame_mean + (1.0 - alpha_ema) * state['dc_offset']

        # 3. Retornar según el modo
        if mode == 'AC':
            ac_signal = samples - state['dc_offset']
            return ac_signal.astype(samples.dtype)
            
        return samples

    def _on_fft_window_changed(self, window: str):
        """Propaga cambio de ventana FFT al engine."""
        # El engine lee el parametro en cada compute(), asi que solo necesitamos guardarlo
        self.fft_engine.last_window = window.lower()

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
        frames = self.data_store.get_last_n(1)
        if not frames:
            return
        latest = frames[-1]
        ch1 = latest.get('ch0_mv')
        ch2 = latest.get('ch1_mv')
        rate = self.controller.current_config.sample_rate
        count = latest.get('sample_count', 0)
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
        self.waveform_widget._draw_dynamic_grid()

        self.fft_widget.plot_widget.setBackground(bg)
        self.xy_widget.plot_widget.setBackground(bg)

    def _on_render_timer(self):
        # 1. Update status bar stats
        if self.controller.connected:
            stats = self.reader.get_stats()
            # BUG-01 FIX: key was 'bytes_sec', real key is 'bytes_per_sec'
            # BUG-03 FIX: update_stats expects (fps, bytes_sec, overflow_count)
            #             pass _overflow_count as overflow counter, not frames_crc_err
            self.status_bar.update_stats(stats['fps'], stats['bytes_per_sec'], self._overflow_count)
            cfg = self.controller.current_config
            self.status_bar.update_rate(cfg.sample_rate // cfg.oversampling)

        # NUEVO: Si ui_hold esta activo, NO renderizar datos nuevos
        if self._ui_hold:
            return

        # 2. Get latest data
        frames = self.data_store.get_last_n(5)
        if not frames:
            return

        latest = frames[-1]
        ch1_raw = latest.get('ch0_mv')
        ch2_raw = latest.get('ch1_mv')
        cfg = self.controller.current_config
        rate = cfg.sample_rate / cfg.oversampling
        sample_count = latest.get('sample_count', 0)
        trigger_idx = latest.get('trigger_index', 0)

        # 3. Calcular eje temporal en us
        if rate > 0 and sample_count > 0:
            dt_us = 1e6 / rate
            t_us = np.arange(sample_count, dtype=np.float64) * dt_us
            t_us = t_us - trigger_idx * dt_us
        else:
            t_us = latest.get('time_axis_us')

        if t_us is None:
            return

        # 4. NUEVO: Aplicar AC coupling digital si esta activo
        ch1 = self._apply_ac_coupling(ch1_raw, 0, rate) if ch1_raw is not None else None
        ch2 = self._apply_ac_coupling(ch2_raw, 1, rate) if ch2_raw is not None else None

        # 5. NUEVO: Enviar datos al MeasurementsEngine
        self.meas_engine.submit(ch1, ch2, rate)

        # Track overflow
        if latest.get('overflow', False):
            self._overflow_count += 1

        # 6. Waveform Render
        mode = self.waveform_widget.display_mode
        trig_idx = latest.get('trigger_index', 0)

        if self.waveform_widget.roll_mode:
            # En Roll mode, forzamos render normal acumulativo y saltamos otros modos
            self.waveform_widget.update_frame(t_us, ch1, ch2, trig_idx)
        elif mode == 'normal':
            self.waveform_widget.update_frame(t_us, ch1, ch2, trig_idx)
        elif mode == 'average':
            a1 = self.data_store.get_average(4, 'ch0_mv')
            a2 = self.data_store.get_average(4, 'ch1_mv')
            # Aplicar AC coupling a los promedios tambien
            if a1 is not None and self._ac_couple_state[0]['mode'] != 'DC':
                a1 = self._apply_ac_coupling(a1, 0, rate)
            if a2 is not None and self._ac_couple_state[1]['mode'] != 'DC':
                a2 = self._apply_ac_coupling(a2, 1, rate)
            self.waveform_widget.update_frame(t_us, a1, a2, trig_idx)
        elif mode == 'envelope':
            e1 = self.data_store.get_envelope(4, 'ch0_mv')
            e2 = self.data_store.get_envelope(4, 'ch1_mv')
            min1, max1 = e1 if e1 else (None, None)
            min2, max2 = e2 if e2 else (None, None)
            self.waveform_widget.update_envelope(t_us, min1, max1, min2, max2)
        elif mode == 'persistence':
            processed_frames = []
            for f in frames:
                f_ch1_raw = f.get('ch0_mv')
                f_ch2_raw = f.get('ch1_mv')
                f_ch1 = self._apply_ac_coupling(f_ch1_raw, 0, rate) if f_ch1_raw is not None else None
                f_ch2 = self._apply_ac_coupling(f_ch2_raw, 1, rate) if f_ch2_raw is not None else None
                
                f_count = f.get('sample_count', 0)
                f_trig = f.get('trigger_index', 0)
                if rate > 0 and f_count > 0:
                    dt = 1e6 / rate
                    f_t = np.arange(f_count, dtype=np.float64) * dt - f_trig * dt
                else:
                    f_t = f.get('time_axis_us')
                    
                processed_frames.append({
                    'time_axis_us': f_t,
                    'ch0_mv': f_ch1,
                    'ch1_mv': f_ch2
                })
            self.waveform_widget.update_persistence(processed_frames)

        # 7. XY Render
        if not self.xy_widget.isHidden():
            self.xy_widget.update_xy(ch1, ch2)

        # 8. FFT Render
        if not self.fft_widget.isHidden():
            window = self.fft_engine.last_window
            if ch1 is not None:
                res1 = self.fft_engine.compute(ch1, rate, window=window)
                if res1:
                    self.fft_widget.update_fft(0, res1['freqs'], res1['magnitudes_mv'],
                                               res1['magnitudes_db'], res1['peak_freq'], res1['peak_magnitude_mv'])
            if ch2 is not None:
                res2 = self.fft_engine.compute(ch2, rate, window=window)
                if res2:
                    self.fft_widget.update_fft(1, res2['freqs'], res2['magnitudes_mv'],
                                               res2['magnitudes_db'], res2['peak_freq'], res2['peak_magnitude_mv'])

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
