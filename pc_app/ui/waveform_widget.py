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
        self.plot_widget.showGrid(x=False, y=False)

        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setMouseEnabled(x=True, y=True)
        self.plot_item.hideButtons()

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

        # --- Dynamic grid lines (pre-allocated pool) ---
        self._grid_v_lines = []
        self._grid_h_lines = []
        _POOL_V = 30
        _POOL_H = 20

        for _ in range(_POOL_V):
            line = pg.InfiniteLine(angle=90, pen=pg.mkPen(self.GRID_MAJOR, width=0.5, style=Qt.PenStyle.DotLine))
            line.setVisible(False)
            self.plot_item.addItem(line, ignoreBounds=True)
            self._grid_v_lines.append(line)

        for _ in range(_POOL_H):
            line = pg.InfiniteLine(angle=0, pen=pg.mkPen(self.GRID_MAJOR, width=0.5, style=Qt.PenStyle.DotLine))
            line.setVisible(False)
            self.plot_item.addItem(line, ignoreBounds=True)
            self._grid_h_lines.append(line)

        # Zero-axis lines
        self._zero_x = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen('#3f3f46', width=1))
        self._zero_y = pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen('#3f3f46', width=1))
        self.plot_item.addItem(self._zero_x, ignoreBounds=True)
        self.plot_item.addItem(self._zero_y, ignoreBounds=True)

        # Debounce timer for grid updates
        from PyQt6.QtCore import QTimer as _QT
        self._grid_timer = _QT(self)
        self._grid_timer.setSingleShot(True)
        self._grid_timer.setInterval(30)
        self._grid_timer.timeout.connect(self._draw_dynamic_grid)

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

        # Connect view range changes
        self.plot_item.sigRangeChanged.connect(self._on_range_changed)
        self._update_ranges()

    # ==================================================================
    # Dynamic Grid
    # ==================================================================

    def _on_range_changed(self, _view_box=None, _range=None):
        self._grid_timer.start()
        self._update_gnd_markers()

    def _draw_dynamic_grid(self):
        vb = self.plot_item.getViewBox()
        x_range = vb.viewRange()[0]
        y_range = vb.viewRange()[1]
        x_span = x_range[1] - x_range[0]
        y_span = y_range[1] - y_range[0]

        if x_span <= 0 or y_span <= 0:
            return

        x_step = self.timebase_us
        y_step = self.ch1_scale_mv

        visible_x_divs = x_span / x_step
        visible_y_divs = y_span / y_step

        if visible_x_divs > 25 or visible_x_divs < 3:
            x_step = self._nice_step(x_span / 10.0)
        if visible_y_divs > 20 or visible_y_divs < 3:
            y_step = self._nice_step(y_span / 8.0)

        x_start = np.floor(x_range[0] / x_step) * x_step
        idx = 0
        x = x_start
        while x <= x_range[1] and idx < len(self._grid_v_lines):
            if abs(x) > x_step * 0.001:
                self._grid_v_lines[idx].setPos(x)
                self._grid_v_lines[idx].setVisible(True)
                idx += 1
            x += x_step
        for i in range(idx, len(self._grid_v_lines)):
            self._grid_v_lines[i].setVisible(False)

        y_start = np.floor(y_range[0] / y_step) * y_step
        idx = 0
        y = y_start
        while y <= y_range[1] and idx < len(self._grid_h_lines):
            if abs(y) > y_step * 0.001:
                self._grid_h_lines[idx].setPos(y)
                self._grid_h_lines[idx].setVisible(True)
                idx += 1
            y += y_step
        for i in range(idx, len(self._grid_h_lines)):
            self._grid_h_lines[i].setVisible(False)

    @staticmethod
    def _nice_step(raw_step: float) -> float:
        if raw_step <= 0:
            return 1.0
        magnitude = 10 ** np.floor(np.log10(raw_step))
        residual = raw_step / magnitude
        if residual <= 1.5:
            return magnitude
        elif residual <= 3.5:
            return 2.0 * magnitude
        elif residual <= 7.5:
            return 5.0 * magnitude
        else:
            return 10.0 * magnitude

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
        n_y_divs = 8
        y_max = (n_y_divs / 2) * self.ch1_scale_mv

        vb = self.plot_item.getViewBox()
        geom = vb.screenGeometry()
        if geom.width() > 0 and geom.height() > 0:
            aspect = geom.width() / geom.height()
        else:
            aspect = 16.0 / 9.0
        n_x_divs = n_y_divs * aspect
        x_half = (n_x_divs / 2) * self.timebase_us

        self.plot_item.setXRange(-x_half, x_half, padding=0)
        self.plot_item.setYRange(-y_max, y_max, padding=0)

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
        self.trig_line.setPos(mv)
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

    def update_frame(self, t_us: np.ndarray, ch1_mv: np.ndarray, ch2_mv: np.ndarray):
        """Render a waveform frame. In roll mode, accumulates data and scrolls."""
        if self.roll_mode:
            self._update_roll(t_us, ch1_mv, ch2_mv)
            return

        if self.ch1_visible and ch1_mv is not None:
            data = self._apply_pga(ch1_mv, 0) + self.ch1_offset_mv
            self.curve_ch1.setData(t_us, data)
        if self.ch2_visible and ch2_mv is not None:
            data = self._apply_pga(ch2_mv, 1) + self.ch2_offset_mv
            self.curve_ch2.setData(t_us, data)

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
            self._update_ranges()

    def update_envelope(self, t_us, ch1_min, ch1_max, ch2_min, ch2_max):
        if self.ch1_visible and ch1_min is not None and ch1_max is not None:
            lo = self._apply_pga(ch1_min, 0) + self.ch1_offset_mv
            hi = self._apply_pga(ch1_max, 0) + self.ch1_offset_mv
            self._env_ch1_lo.setData(t_us, lo)
            self._env_ch1_hi.setData(t_us, hi)
        if self.ch2_visible and ch2_min is not None and ch2_max is not None:
            lo = self._apply_pga(ch2_min, 1) + self.ch2_offset_mv
            hi = self._apply_pga(ch2_max, 1) + self.ch2_offset_mv
            self._env_ch2_lo.setData(t_us, lo)
            self._env_ch2_hi.setData(t_us, hi)

    def update_persistence(self, frames: list):
        """Render persistence. frames viene en orden oldest->newest."""
        for i in range(5):
            self.persistence_curves_ch1[i].setData([], [])
            self.persistence_curves_ch2[i].setData([], [])

        # BUG-M04 FIX: asignar newest -> alpha mas alto (curves[0])
        # Revertimos para iterar newest primero
        count = min(5, len(frames))
        for i in range(count):
            f = frames[-(i + 1)]  # frames[-1] = newest, frames[-5] = oldest
            t_us = f.get('time_axis_us')
            ch1 = f.get('ch0_mv')
            ch2 = f.get('ch1_mv')

            if self.ch1_visible and ch1 is not None and t_us is not None:
                data = self._apply_pga(ch1, 0) + self.ch1_offset_mv
                self.persistence_curves_ch1[i].setData(t_us, data)
            if self.ch2_visible and ch2 is not None and t_us is not None:
                data = self._apply_pga(ch2, 1) + self.ch2_offset_mv
                self.persistence_curves_ch2[i].setData(t_us, data)

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

        self._update_ranges()
