"""
measurements_panel.py — Panel lateral/inferior de mediciones automaticas.

Recibe datos de dos fuentes:
  1. Frames MEASUREMENTS (0x02) del firmware (via reader.measurements_received).
  2. Calculos locales del MeasurementsEngine (via measurements_ready signal).
"""

from PyQt6.QtWidgets import QDockWidget, QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt


class MeasurementsPanel(QDockWidget):
    def __init__(self, title="Measurements", parent=None):
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        self.table = QTableWidget(11, 2)
        self.table.setHorizontalHeaderLabels(["CH1", "CH2"])

        row_labels = ["Vpp", "Vrms", "Vdc", "Vac", "Vmax", "Vmin", "Freq", "Period", "Duty", "Rise", "Fall"]
        self.table.setVerticalHeaderLabels(row_labels)

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        for r in range(11):
            for c in range(2):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)

        self.setWidget(container)

    def update_measurements(self, data: dict):
        """
        Actualiza la tabla con datos del dict.
        Formato: {'ch0': {'vpp_mv': 123.4, ...}, 'ch1': {...}}
        """
        ch0 = data.get('ch0')
        ch1 = data.get('ch1')

        if ch0:
            self._fill_col(0, ch0)
        if ch1:
            self._fill_col(1, ch1)

    def _fill_col(self, col: int, meas: dict):
        if not meas.get('valid', False):
            for r in range(11):
                self.table.item(r, col).setText("--")
            return

        def fmt_v(v):
            return f"{v:.1f} mV" if abs(v) < 1000 else f"{v/1000:.2f} V"

        def fmt_f(f):
            return f"{f:.1f} Hz" if f < 1000 else f"{f/1000:.2f} kHz"

        def fmt_t(t):
            return f"{t:.1f} us" if t < 1000 else f"{t/1000:.2f} ms"

        self.table.item(0, col).setText(fmt_v(meas.get('vpp_mv', 0)))
        self.table.item(1, col).setText(fmt_v(meas.get('vrms_mv', 0)))
        self.table.item(2, col).setText(fmt_v(meas.get('vdc_mv', 0)))
        self.table.item(3, col).setText(fmt_v(meas.get('vac_rms_mv', 0)))
        self.table.item(4, col).setText(fmt_v(meas.get('vmax_mv', 0)))
        self.table.item(5, col).setText(fmt_v(meas.get('vmin_mv', 0)))
        self.table.item(6, col).setText(fmt_f(meas.get('freq_hz', 0)))
        self.table.item(7, col).setText(fmt_t(meas.get('period_us', 0)))
        self.table.item(8, col).setText(f"{meas.get('duty_cycle_pct', 0):.1f} %")
        self.table.item(9, col).setText(fmt_t(meas.get('rise_time_us', 0)))
        self.table.item(10, col).setText(fmt_t(meas.get('fall_time_us', 0)))
