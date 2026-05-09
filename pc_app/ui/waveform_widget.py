"""
waveform_widget.py — Widget PyQtGraph de waveform dual channel.

Correcciones:
  - Roll mode: proteccion contra arrays vacios (IndexError).
  - Persistence: frames asignados en orden correcto (newest = alpha mas alto).
  - Offset temporal determinista en roll mode.
"""

import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QFont


class WaveformWidget(QWidget):

    cursor_moved = pyqtSignal(float, float)  # x_us, y_mv
    # scale_mv, timebase_us
    autoscale_finished = pyqtSignal(float, float)

    # Colors — CH1 = indice 0, CH2 = indice 1
    CH1_COLOR = '#22d3ee'   # Cyan for CH1
    CH2_COLOR = '#facc15'   # Yellow for CH2
    GRID_MAJOR = '#27272a'
    GRID_MINOR = '#1a1a1f'
    BG_COLOR   = '#09090b'
    CURSOR_COLOR_T = '#a78bfa'  # Purple for time cursors
    CURSOR_COLOR_V = '#f472b6'  # Pink for voltage cursors

    def __init__(self, parent=None):
        super().__init__(parent)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- PyQtGraph plot ---
        pg.setConfigOptions(antialias=True, useOpenGL=True)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(self.BG_COLOR)
        
        self.plot_item = self.plot_widget.getPlotItem()
        # Configuración de Lienzo Moderno (Táctil/Fluido)
        self.plot_item.setMouseEnabled(x=True, y=True)
        self.plot_item.hideButtons()
        
        # Ocultar los números de los ejes para un look limpio, pero mantener los ejes físicos
        self.plot_item.getAxis('bottom').setStyle(showValues=False)
        self.plot_item.getAxis('left').setStyle(showValues=False)
        
        # Encender el grid nativo acelerado por hardware
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)

        # Deshabilitar AutoRange en X para estabilidad total (el usuario controla el zoom)
        self.plot_item.enableAutoRange(axis='x', enable=False)
        self.plot_item.getViewBox().setMouseEnabled(x=True, y=True)

        # Axis labels (disabled auto SI prefixes to prevent kV and ks since data is in mV and µs)
        self.plot_item.setLabel('bottom', 'Time (µs)')
        self.plot_item.setLabel('left', 'Voltage (mV)')

        main_layout.addWidget(self.plot_widget)

        # --- Cursor readout bar ---
        self.cursor_bar = QWidget()
        cursor_layout = QHBoxLayout(self.cursor_bar)
        cursor_layout.setContentsMargins(8, 2, 8, 2)
        cursor_layout.setSpacing(16)
        font = QFont("Inter", 9)

        self.lbl_t1 = QLabel("T1: --")
        self.lbl_t2 = QLabel("T2: --")
        self.lbl_dt = QLabel("dT: --")
        self.lbl_freq = QLabel("1/dT: --")
        self.lbl_v1 = QLabel("V1: --")
        self.lbl_v2 = QLabel("V2: --")
        self.lbl_dv = QLabel("dV: --")

        for lbl in [self.lbl_t1, self.lbl_t2, self.lbl_dt, self.lbl_freq,
                     self.lbl_v1, self.lbl_v2, self.lbl_dv]:
            lbl.setFont(font)
            lbl.setStyleSheet("color: #a1a1aa; font-size: 10px;")
            cursor_layout.addWidget(lbl)

        cursor_layout.addStretch()
        self.cursor_bar.setFixedHeight(22)
        main_layout.addWidget(self.cursor_bar)

        # --- Channel traces ---
        self.curve_ch1 = self.plot_item.plot(pen=pg.mkPen(self.CH1_COLOR, width=1.5))
        self.curve_ch2 = self.plot_item.plot(pen=pg.mkPen(self.CH2_COLOR, width=1.5))

        # --- Envelope curves ---
        self._env_ch1_lo = pg.PlotCurveItem(pen=pg.mkPen(self.CH1_COLOR, width=0.5))
        self._env_ch1_hi = pg.PlotCurveItem(pen=pg.mkPen(self.CH1_COLOR, width=0.5))
        self._env_ch2_lo = pg.PlotCurveItem(pen=pg.mkPen(self.CH2_COLOR, width=0.5))
        self._env_ch2_hi = pg.PlotCurveItem(pen=pg.mkPen(self.CH2_COLOR, width=0.5))

        self.env_ch1 = pg.FillBetweenItem(self._env_ch1_lo, self._env_ch1_hi,
                                           brush=pg.mkBrush(34, 211, 238, 40))
        self.env_ch2 = pg.FillBetweenItem(self._env_ch2_lo, self._env_ch2_hi,
                                           brush=pg.mkBrush(250, 204, 21, 40))

        for item in [self._env_ch1_lo, self._env_ch1_hi, self._env_ch2_lo, self._env_ch2_hi,
                      self.env_ch1, self.env_ch2]:
            self.plot_item.addItem(item)
            item.setVisible(False)

        # --- Persistence traces ---
        self.persistence_curves_ch1 = []
        self.persistence_curves_ch2 = []
        for i in range(5):
            alpha = max(20, 80 - i * 15)
            c1 = self.plot_item.plot(pen=pg.mkPen(34, 211, 238, alpha, width=1))
            c2 = self.plot_item.plot(pen=pg.mkPen(250, 204, 21, alpha, width=1))
            c1.setVisible(False)
            c2.setVisible(False)
            self.persistence_curves_ch1.append(c1)
            self.persistence_curves_ch2.append(c2)

        # --- Trigger level line ---
        self.trig_line = pg.InfiniteLine(
            angle=0,
            pen=pg.mkPen('#ef4444', style=Qt.PenStyle.DashLine, width=1),
            movable=False
        )
        self.plot_item.addItem(self.trig_line)

        # --- Ground reference indicators ---
        self.gnd_marker_ch1 = pg.ArrowItem(
            angle=0, tipAngle=60, headLen=10, headWidth=8,
            pen=pg.mkPen(self.CH1_COLOR, width=1),
            brush=pg.mkBrush(self.CH1_COLOR)
        )
        self.gnd_marker_ch2 = pg.ArrowItem(
            angle=0, tipAngle=60, headLen=10, headWidth=8,
            pen=pg.mkPen(self.CH2_COLOR, width=1),
            brush=pg.mkBrush(self.CH2_COLOR)
        )
        self.plot_item.addItem(self.gnd_marker_ch1)
        self.plot_item.addItem(self.gnd_marker_ch2)

        # Zero-axis lines
        # (Eliminado en Fase 2 por rediseño moderno)

        # --- Measurement cursors ---
        self.cursor_t1 = pg.InfiniteLine(
            angle=90, movable=True,
            pen=pg.mkPen(self.CURSOR_COLOR_T, style=Qt.PenStyle.DashLine, width=1.5),
            label='T1', labelOpts={'color': self.CURSOR_COLOR_T, 'position': 0.95}
        )
        self.cursor_t2 = pg.InfiniteLine(
            angle=90, movable=True,
            pen=pg.mkPen(self.CURSOR_COLOR_T, style=Qt.PenStyle.DashDotLine, width=1.5),
            label='T2', labelOpts={'color': self.CURSOR_COLOR_T, 'position': 0.90}
        )
        self.cursor_v1 = pg.InfiniteLine(
            angle=0, movable=True,
            pen=pg.mkPen(self.CURSOR_COLOR_V, style=Qt.PenStyle.DashLine, width=1.5),
            label='V1', labelOpts={'color': self.CURSOR_COLOR_V, 'position': 0.95}
        )
        self.cursor_v2 = pg.InfiniteLine(
            angle=0, movable=True,
            pen=pg.mkPen(self.CURSOR_COLOR_V, style=Qt.PenStyle.DashDotLine, width=1.5),
            label='V2', labelOpts={'color': self.CURSOR_COLOR_V, 'position': 0.90}
        )

        for c in [self.cursor_t1, self.cursor_t2, self.cursor_v1, self.cursor_v2]:
            self.plot_item.addItem(c)
            c.setVisible(False)
            c.sigPositionChanged.connect(self._update_cursor_readout)

        self.cursors_time_visible = False
        self.cursors_volt_visible = False

        # --- Internal state ---
        self.timebase_us = 10000.0   # 10 ms/div
        self.ch1_scale_mv = 1000.0   # 1 V/div
        self.ch2_scale_mv = 1000.0
        self.ch1_offset_mv = 0.0
        self.ch2_offset_mv = 0.0
        self.ch1_visible = True
        self.ch2_visible = True
        self.display_mode = 'normal'

        # Roll mode
        self.roll_mode = False
        self.roll_paused = False
        self._roll_max_pts = 10000
        self._roll_t_us = np.array([], dtype=np.float64)
        self._roll_ch1 = np.array([], dtype=np.float32)
        self._roll_ch2 = np.array([], dtype=np.float32)
        self._roll_t_offset = 0.0
        self._last_dt_us = 10.0  # Deterministic fallback for delta

        # PGA
        self.ch1_pga_gain = 1.0
        self.ch2_pga_gain = 1.0

        self._update_ranges()

    # ==================================================================
    # Dynamic Grid (ELIMINADO en Fase 2: Usando grid nativo)
    # ==================================================================

    # ==================================================================
    # Ground reference markers
    # ==================================================================

    def _update_gnd_markers(self):
        vb = self.plot_item.getViewBox()
        x_range = vb.viewRange()[0]
        left_x = x_range[0]

        if self.ch1_visible:
            self.gnd_marker_ch1.setPos(left_x, self.ch1_offset_mv)
            self.gnd_marker_ch1.setVisible(True)
        else:
            self.gnd_marker_ch1.setVisible(False)

        if self.ch2_visible:
            self.gnd_marker_ch2.setPos(left_x, self.ch2_offset_mv)
            self.gnd_marker_ch2.setVisible(True)
        else:
            self.gnd_marker_ch2.setVisible(False)

    # ==================================================================
    # Cursor readout
    # ==================================================================

    def _update_cursor_readout(self):
        if self.cursors_time_visible:
            t1 = self.cursor_t1.value()
            t2 = self.cursor_t2.value()
            dt = abs(t2 - t1)
            self.lbl_t1.setText(f"T1: {self._fmt_time(t1)}")
            self.lbl_t2.setText(f"T2: {self._fmt_time(t2)}")
            self.lbl_dt.setText(f"dT: {self._fmt_time(dt)}")
            if dt > 0:
                freq = 1e6 / dt
                self.lbl_freq.setText(f"1/dT: {self._fmt_freq(freq)}")
            else:
                self.lbl_freq.setText("1/dT: --")

        if self.cursors_volt_visible:
            v1 = self.cursor_v1.value()
            v2 = self.cursor_v2.value()
            dv = abs(v2 - v1)
            self.lbl_v1.setText(f"V1: {self._fmt_volt(v1)}")
            self.lbl_v2.setText(f"V2: {self._fmt_volt(v2)}")
            self.lbl_dv.setText(f"dV: {self._fmt_volt(dv)}")

    @staticmethod
    def _fmt_time(us: float) -> str:
        if abs(us) >= 1e6:
            return f"{us/1e6:.2f} s"
        elif abs(us) >= 1000:
            return f"{us/1000:.2f} ms"
        else:
            return f"{us:.1f} us"

    @staticmethod
    def _fmt_volt(mv: float) -> str:
        if abs(mv) >= 1000:
            return f"{mv/1000:.3f} V"
        else:
            return f"{mv:.1f} mV"

    @staticmethod
    def _fmt_freq(hz: float) -> str:
        if hz >= 1e6:
            return f"{hz/1e6:.2f} MHz"
        elif hz >= 1000:
            return f"{hz/1000:.2f} kHz"
        else:
            return f"{hz:.1f} Hz"

    # ==================================================================
    # Public API — cursor toggles
    # ==================================================================

    def set_time_cursors_visible(self, visible: bool):
        self.cursors_time_visible = visible
        self.cursor_t1.setVisible(visible)
        self.cursor_t2.setVisible(visible)
        if not visible:
            self.lbl_t1.setText("T1: --")
            self.lbl_t2.setText("T2: --")
            self.lbl_dt.setText("dT: --")
            self.lbl_freq.setText("1/dT: --")

    def set_volt_cursors_visible(self, visible: bool):
        self.cursors_volt_visible = visible
        self.cursor_v1.setVisible(visible)
        self.cursor_v2.setVisible(visible)
        if not visible:
            self.lbl_v1.setText("V1: --")
            self.lbl_v2.setText("V2: --")
            self.lbl_dv.setText("dV: --")

    # ==================================================================
    # Public API — scale & visibility
    # ==================================================================

    def _update_ranges(self):
        # Eje Y: 8 divisiones fijas
        n_y_divs = 8
        y_max = (n_y_divs / 2) * self.ch1_scale_mv
        self.plot_item.setYRange(-y_max, y_max, padding=0)
        
        # Eje X: 10 divisiones fijas centradas en el trigger (t=0)
        # Esto garantiza que la onda NO se mueva de su sitio.
        n_x_divs = 10
        x_half = (n_x_divs / 2) * self.timebase_us
        self.plot_item.setXRange(-x_half, x_half, padding=0)

    def set_timebase(self, us_per_div: float):
        self.timebase_us = us_per_div
        self._update_ranges()

    def set_voltage_scale(self, mv_per_div: float, channel: int):
        if channel == 0:
            self.ch1_scale_mv = mv_per_div
        else:
            self.ch2_scale_mv = mv_per_div
        self._update_ranges()

    def set_ch_offset(self, ch: int, offset_mv: float):
        if ch == 0:
            self.ch1_offset_mv = offset_mv
        else:
            self.ch2_offset_mv = offset_mv
        self._update_gnd_markers()

    def set_ch_visible(self, ch: int, visible: bool):
        if ch == 0:
            self.ch1_visible = visible
            self.curve_ch1.setVisible(visible)
        else:
            self.ch2_visible = visible
            self.curve_ch2.setVisible(visible)
        self._update_gnd_markers()

    def set_trigger_level(self, mv: float, channel: int):
        # El trigger debe moverse visualmente junto con el offset del canal asociado
        offset = self.ch1_offset_mv if channel == 0 else self.ch2_offset_mv
        self.trig_line.setPos(mv + offset)
        color = self.CH1_COLOR if channel == 0 else self.CH2_COLOR
        self.trig_line.setPen(pg.mkPen(color, style=Qt.PenStyle.DashLine, width=1))

    def set_display_mode(self, mode: str):
        self.display_mode = mode
        show_pers = (mode == 'persistence')
        show_env  = (mode == 'envelope')

        for c in self.persistence_curves_ch1:
            c.setVisible(show_pers and self.ch1_visible)
        for c in self.persistence_curves_ch2:
            c.setVisible(show_pers and self.ch2_visible)

        for item in [self.env_ch1, self.env_ch2,
                      self._env_ch1_lo, self._env_ch1_hi,
                      self._env_ch2_lo, self._env_ch2_hi]:
            item.setVisible(False)

        if show_env:
            self._env_ch1_lo.setVisible(self.ch1_visible)
            self._env_ch1_hi.setVisible(self.ch1_visible)
            self.env_ch1.setVisible(self.ch1_visible)
            self._env_ch2_lo.setVisible(self.ch2_visible)
            self._env_ch2_hi.setVisible(self.ch2_visible)
            self.env_ch2.setVisible(self.ch2_visible)

    # ==================================================================
    # PGA
    # ==================================================================

    def set_pga_gain(self, channel: int, gain: float):
        if channel == 0:
            self.ch1_pga_gain = gain
        else:
            self.ch2_pga_gain = gain

    def _apply_pga(self, mv: np.ndarray, channel: int) -> np.ndarray:
        gain = self.ch1_pga_gain if channel == 0 else self.ch2_pga_gain
        if gain != 1.0 and gain > 0:
            return mv / gain
        return mv

    # ==================================================================
    # Rendering
    # ==================================================================

    def update_frame(self, t_us: np.ndarray, ch1_mv: np.ndarray, ch2_mv: np.ndarray, trigger_index: int = 0, sample_rate_hz: float = 100000.0):
        """Render a waveform frame with real-time conversion and proportional scaling."""
        if self.roll_mode:
            self._update_roll(t_us, ch1_mv, ch2_mv)
            return

        # 1. Convertir índices a microsegundos reales
        t_real_us = t_us * (1000000.0 / sample_rate_hz)

        # 2. Alinear con el trigger
        if len(t_real_us) > trigger_index >= 0:
            t_aligned = t_real_us - t_real_us[trigger_index]
        else:
            t_aligned = t_real_us

        # 3. CH1
        if self.ch1_visible and ch1_mv is not None:
            data1 = self._apply_pga(ch1_mv, 0) + self.ch1_offset_mv
            self.curve_ch1.setData(t_aligned, data1)
        else:
            self.curve_ch1.setData([], [])

        # 4. CH2 (Escalado relativo al CH1 para independencia visual)
        if self.ch2_visible and ch2_mv is not None:
            factor_escala = self.ch1_scale_mv / self.ch2_scale_mv
            data2 = (self._apply_pga(ch2_mv, 1) * factor_escala) + self.ch2_offset_mv
            self.curve_ch2.setData(t_aligned, data2)
        else:
            self.curve_ch2.setData([], [])

    def _update_roll(self, t_us: np.ndarray, ch1_mv: np.ndarray, ch2_mv: np.ndarray):
        """Roll mode: append new data and scroll the view."""
        n = len(t_us)
        if n == 0:
            return

        if not self.roll_paused:
            # Calculate time step deterministically
            dt_us = (t_us[-1] - t_us[0]) / n if n > 1 else self._last_dt_us
            self._last_dt_us = dt_us

            # Convert frame time axis to absolute rolling time
            abs_t = t_us + self._roll_t_offset
            self._roll_t_offset = abs_t[-1] + dt_us

            self._roll_t_us = np.append(self._roll_t_us, abs_t)

            if ch1_mv is not None:
                d1 = self._apply_pga(ch1_mv, 0) + self.ch1_offset_mv
                self._roll_ch1 = np.append(self._roll_ch1, d1)
            if ch2_mv is not None:
                d2 = self._apply_pga(ch2_mv, 1) + self.ch2_offset_mv
                self._roll_ch2 = np.append(self._roll_ch2, d2)

            # Trim to max points
            if len(self._roll_t_us) > self._roll_max_pts:
                excess = len(self._roll_t_us) - self._roll_max_pts
                self._roll_t_us = self._roll_t_us[excess:]
                if len(self._roll_ch1) > self._roll_max_pts:
                    self._roll_ch1 = self._roll_ch1[excess:]
                if len(self._roll_ch2) > self._roll_max_pts:
                    self._roll_ch2 = self._roll_ch2[excess:]

        # Draw
        if self.ch1_visible and len(self._roll_ch1) > 0:
            self.curve_ch1.setData(self._roll_t_us[:len(self._roll_ch1)], self._roll_ch1)
        if self.ch2_visible and len(self._roll_ch2) > 0:
            self.curve_ch2.setData(self._roll_t_us[:len(self._roll_ch2)], self._roll_ch2)

        # Scroll viewport
        if not self.roll_paused and len(self._roll_t_us) > 0:
            t_latest = self._roll_t_us[-1]
            vb = self.plot_item.getViewBox()
            geom = vb.screenGeometry()
            aspect = geom.width() / geom.height() if geom.height() > 0 else 16/9
            n_x_divs = 8 * aspect
            window_us = n_x_divs * self.timebase_us
            self.plot_item.setXRange(t_latest - window_us, t_latest, padding=0)

    def set_roll_paused(self, paused: bool):
        self.roll_paused = paused

    def set_roll_mode(self, enabled: bool):
        self.roll_mode = enabled
        if not enabled:
            self._roll_t_us = np.array([], dtype=np.float64)
            self._roll_ch1 = np.array([], dtype=np.float32)
            self._roll_ch2 = np.array([], dtype=np.float32)
            self._roll_t_offset = 0.0
            self._last_dt_us = 10.0
            # BUG-PC-07 FIX: Limpiar curvas inmediatamente para evitar "ghost frame"
            self.curve_ch1.setData([], [])
            self.curve_ch2.setData([], [])
            self._update_ranges()

    def update_envelope(self, t_us: np.ndarray, ch1_min, ch1_max, ch2_min, ch2_max, sample_rate_hz: float = 100000.0):
        # Conversión a tiempo real
        t_real_us = t_us * (1000000.0 / sample_rate_hz)
        
        if self.ch1_visible and ch1_min is not None and ch1_max is not None:
            lo = self._apply_pga(ch1_min, 0) + self.ch1_offset_mv
            hi = self._apply_pga(ch1_max, 0) + self.ch1_offset_mv
            self._env_ch1_lo.setData(t_real_us, lo)
            self._env_ch1_hi.setData(t_real_us, hi)
        if self.ch2_visible and ch2_min is not None and ch2_max is not None:
            # Aplicar factor de escala relativo al CH2 para el sobre
            factor = self.ch1_scale_mv / self.ch2_scale_mv
            lo = (self._apply_pga(ch2_min, 1) * factor) + self.ch2_offset_mv
            hi = (self._apply_pga(ch2_max, 1) * factor) + self.ch2_offset_mv
            self._env_ch2_lo.setData(t_real_us, lo)
            self._env_ch2_hi.setData(t_real_us, hi)

    def update_persistence(self, frames: list, sample_rate_hz: float = 100000.0):
        """Render persistence. frames viene en orden oldest->newest."""
        for i in range(5):
            self.persistence_curves_ch1[i].setData([], [])
            self.persistence_curves_ch2[i].setData([], [])

        count = min(5, len(frames))
        factor = self.ch1_scale_mv / self.ch2_scale_mv

        for i in range(count):
            f = frames[-(i + 1)]  # frames[-1] = newest
            t_idx = f.get('time_axis_us') # En realidad son índices
            ch1 = f.get('ch0_mv')
            ch2 = f.get('ch1_mv')
            trig_idx = f.get('trigger_index', 0)

            if t_idx is not None:
                t_real = t_idx * (1000000.0 / sample_rate_hz)
                # Alineación con trigger
                if len(t_real) > trig_idx >= 0:
                    t_aligned = t_real - t_real[trig_idx]
                else:
                    t_aligned = t_real

                if self.ch1_visible and ch1 is not None:
                    data = self._apply_pga(ch1, 0) + self.ch1_offset_mv
                    self.persistence_curves_ch1[i].setData(t_aligned, data)
                if self.ch2_visible and ch2 is not None:
                    data = (self._apply_pga(ch2, 1) * factor) + self.ch2_offset_mv
                    self.persistence_curves_ch2[i].setData(t_aligned, data)

    # ==================================================================
    # Auto-scale
    # ==================================================================

    def auto_scale(self, ch1_mv: np.ndarray | None, ch2_mv: np.ndarray | None,
                   sample_rate: int, sample_count: int):
        vpp = 0.0
        if ch1_mv is not None and len(ch1_mv) > 0:
            vpp = max(vpp, np.max(ch1_mv) - np.min(ch1_mv))
        if ch2_mv is not None and len(ch2_mv) > 0:
            vpp = max(vpp, np.max(ch2_mv) - np.min(ch2_mv))

        if vpp < 1.0:
            vpp = 100.0

        target_v_div = vpp / 6.0
        scales = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
        best_scale = scales[-1]
        for s in scales:
            if s >= target_v_div:
                best_scale = s
                break

        self.ch1_scale_mv = best_scale
        self.ch2_scale_mv = best_scale

        if sample_rate > 0 and sample_count > 0:
            window_us = (sample_count / sample_rate) * 1e6
            target_tb = window_us / 10.0
            timebases = [1, 2, 5, 10, 20, 50, 100, 200, 500,
                         1000, 2000, 5000, 10000, 20000, 50000,
                         100000, 200000, 500000, 1000000, 2000000, 5000000]
            best_tb = timebases[-1]
            for tb in timebases:
                if tb >= target_tb:
                    best_tb = tb
                    break
            self.timebase_us = best_tb
            self.autoscale_finished.emit(float(best_scale), float(best_tb))

        self._update_ranges()
