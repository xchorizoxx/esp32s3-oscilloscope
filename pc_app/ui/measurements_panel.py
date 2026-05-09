"""
measurements_panel.py — Compact measurement panel with configurable rows.

Receives data from MeasurementsEngine (via measurements_ready signal).
Displays key metrics in a compact horizontal table format.
"""

from PyQt6.QtWidgets import (
    QDockWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QVBoxLayout, QWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


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

        for r in range(n_rows):
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
        if not meas.get('valid', False):
            for r in range(len(self.ROW_DEFS)):
                self.table.item(r, col).setText("--")
            return

        for r, (label, key, fmt_name) in enumerate(self.ROW_DEFS):
            fmt = getattr(self, fmt_name)
            val = meas.get(key, 0)
            self.table.item(r, col).setText(fmt(val))
