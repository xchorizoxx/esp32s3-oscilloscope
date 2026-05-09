"""
measurements_panel.py — Compact measurement panel with configurable rows.

Receives data from MeasurementsEngine (via measurements_ready signal).
Displays key metrics in a compact horizontal table format.
"""

from PyQt6.QtWidgets import (
    QDockWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QVBoxLayout, QWidget, QMenu
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QAction


class MeasurementsPanel(QDockWidget):
    # Row definitions: (label, key, formatter)
    ROW_DEFS = [
        ("VPP",   'vpp_mv',        '_fmt_v'),
        ("VRMS",  'vrms_mv',       '_fmt_v'),
        ("VDC",   'vdc_mv',        '_fmt_v'),
        ("VAC",   'vac_rms_mv',    '_fmt_v'),
        ("VMAX",  'vmax_mv',       '_fmt_v'),
        ("VMIN",  'vmin_mv',       '_fmt_v'),
        ("FREQ",  'freq_hz',       '_fmt_f'),
        ("PER",   'period_us',     '_fmt_t'),
        ("DUTY",  'duty_cycle_pct','_fmt_pct'),
        ("RISE",  'rise_time_us',  '_fmt_t'),
        ("FALL",  'fall_time_us',  '_fmt_t'),
        ("PGA G", 'pga_gain',      '_fmt_gain'),
        ("BW",    'pga_bw',        '_fmt_bw'),
    ]

    def __init__(self, title="Measurements", parent=None):
        super().__init__(title, parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )

        n_rows = len(self.ROW_DEFS)
        self.table = QTableWidget(n_rows, 2)
        self.table.setHorizontalHeaderLabels(["CH1", "CH2"])
        self.table.setVerticalHeaderLabels([r[0] for r in self.ROW_DEFS])

        # Compact styling
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Compact font
        compact_font = QFont("Inter", 9)

        # Colored vertical headers for row labels
        vh = self.table.verticalHeader()
        vh.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        vh.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        vh.customContextMenuRequested.connect(self._show_context_menu)

        # Default visible rows: VPP, VMAX, VMIN, FREQ, PGA G, BW (0, 4, 5, 6, 11, 12)
        self._visible_rows = {0, 4, 5, 6, 11, 12}

        for r in range(n_rows):
            self.table.setRowHidden(r, r not in self._visible_rows)
            for c in range(2):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFont(compact_font)
                self.table.setItem(r, c, item)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

        self.setWidget(container)

        # Set max height to keep it compact when docked at bottom
        self.setMaximumHeight(280)

        # EMA state for smoothing [ch][key] = value
        self._ema_state = {0: {}, 1: {}}
        self._ema_alpha = 0.15  # Factor de suavizado

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #18181b; color: #d4d4d8; border: 1px solid #3f3f46; font-size: 10px; }
            QMenu::item:selected { background-color: #164e63; }
        """)

        for r, (label, _, _) in enumerate(self.ROW_DEFS):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(r in self._visible_rows)
            # Use default argument binding to capture 'r' in lambda
            action.triggered.connect(lambda checked, row=r: self._toggle_row(row, checked))
            menu.addAction(action)

        # Show menu at the cursor position mapping it to global coordinates
        menu.exec(self.table.verticalHeader().mapToGlobal(pos))

    def _toggle_row(self, row: int, visible: bool):
        if visible:
            self._visible_rows.add(row)
        else:
            self._visible_rows.discard(row)
        self.table.setRowHidden(row, not visible)

    @staticmethod
    def _fmt_v(v):
        if abs(v) < 1000:
            return f"{v:.1f} mV"
        return f"{v/1000:.2f} V"

    @staticmethod
    def _fmt_f(f):
        if f <= 0:
            return "-- Hz"
        if f < 1000:
            return f"{f:.1f} Hz"
        return f"{f/1000:.2f} kHz"

    @staticmethod
    def _fmt_t(t):
        if t <= 0:
            return "-- µs"
        if t < 1000:
            return f"{t:.1f} µs"
        return f"{t/1000:.2f} ms"

    @staticmethod
    def _fmt_pct(p):
        return f"{p:.1f} %"

    @staticmethod
    def _fmt_gain(g):
        return f"x{g:.2f}"

    @staticmethod
    def _fmt_bw(bw):
        if bw >= 1000000:
            return f"{bw/1000000:.1f} MHz"
        return f"{bw/1000:.0f} kHz"

    def update_pga_display(self, gain_eff: float, bw_hz: float):
        for c in range(2):
            self.table.item(11, c).setText(self._fmt_gain(gain_eff))
            self.table.item(12, c).setText(self._fmt_bw(bw_hz))

    def update_measurements(self, data: dict):
        """
        Update the table with measurement data.
        Format: {'ch0': {'vpp_mv': 123.4, ...}, 'ch1': {...}}
        """
        ch0 = data.get('ch0')
        ch1 = data.get('ch1')

        if ch0:
            self._fill_col(0, ch0)
        if ch1:
            self._fill_col(1, ch1)

    def _fill_col(self, col: int, meas: dict):
        # We assume meas_engine always returns valid dict for Python engine.
        is_valid = meas.get('valid', True)
        if not is_valid:
            for r in range(len(self.ROW_DEFS)):
                self.table.item(r, col).setText("--")
            self._ema_state[col].clear()
            return

        state = self._ema_state[col]

        for r, (label, key, fmt_name) in enumerate(self.ROW_DEFS):
            val = meas.get(key, 0.0)
            
            # EMA Filtering
            if key in state:
                # Evitar suavizar frecuencia si hay saltos gigantes (>50%)
                if key == 'freq_hz' and (val == 0 or abs(val - state[key]) > state[key]*0.5):
                    state[key] = val
                else:
                    state[key] = self._ema_alpha * val + (1.0 - self._ema_alpha) * state[key]
            else:
                state[key] = val
            
            ema_val = state[key]
            fmt_func = getattr(self, fmt_name)
            self.table.item(r, col).setText(fmt_func(ema_val))
