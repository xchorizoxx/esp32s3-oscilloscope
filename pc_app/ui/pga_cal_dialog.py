"""
pga_cal_dialog.py — Dialog for PGA calibration.

Allows auto-calibration, manual VG setting, per-step gain factor
and offset correction, save/reset calibration to NVS.
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QLabel, QPushButton, QDoubleSpinBox, QComboBox,
                             QFormLayout, QMessageBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont


class _PgaCalWorker(QThread):
    finished = pyqtSignal(bool)

    def __init__(self, controller):
        super().__init__()
        self._ctrl = controller

    def run(self):
        self._ctrl.pga_cal_start()
        # The result comes asynchronously via PGA_INFO frame
        self.finished.emit(True)


class PgaCalDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PGA Calibration")
        self.setMinimumWidth(400)
        self._controller = controller

        layout = QVBoxLayout(self)

        # --- VG Section ---
        grp_vg = QGroupBox("Virtual Ground (VG)")
        vg_layout = QFormLayout(grp_vg)

        self.spin_vg = QDoubleSpinBox()
        self.spin_vg.setRange(100.0, 3000.0)
        self.spin_vg.setSuffix(" mV")
        self.spin_vg.setDecimals(1)
        self.spin_vg.setValue(controller.current_config.pga_vg_mv)
        vg_layout.addRow("VG:", self.spin_vg)

        btn_set_vg = QPushButton("Set VG")
        btn_set_vg.clicked.connect(self._on_set_vg)
        vg_layout.addRow(btn_set_vg)

        layout.addWidget(grp_vg)

        # --- Auto-calibrate ---
        self.btn_auto = QPushButton("Auto-Calibrate (connect input to GND)")
        self.btn_auto.clicked.connect(self._on_auto_cal)
        layout.addWidget(self.btn_auto)

        # --- Per-step correction ---
        grp_cal = QGroupBox("Per-Step Correction")
        cal_layout = QFormLayout(grp_cal)

        self.cb_step = QComboBox()
        for i in range(8):
            self.cb_step.addItem(f"Step {i}", i)
        self.cb_step.currentIndexChanged.connect(self._on_step_changed)
        cal_layout.addRow("Step:", self.cb_step)

        self.spin_gain_factor = QDoubleSpinBox()
        self.spin_gain_factor.setRange(0.5, 2.0)
        self.spin_gain_factor.setDecimals(4)
        self.spin_gain_factor.setSingleStep(0.001)
        self.spin_gain_factor.setValue(1.0)
        cal_layout.addRow("Gain factor:", self.spin_gain_factor)

        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-500.0, 500.0)
        self.spin_offset.setSuffix(" mV")
        self.spin_offset.setDecimals(1)
        self.spin_offset.setValue(0.0)
        cal_layout.addRow("Offset:", self.spin_offset)

        btn_set_gain = QPushButton("Set Gain Factor")
        btn_set_gain.clicked.connect(self._on_set_gain)
        cal_layout.addRow(btn_set_gain)

        btn_set_offset = QPushButton("Set Offset")
        btn_set_offset.clicked.connect(self._on_set_offset)
        cal_layout.addRow(btn_set_offset)

        layout.addWidget(grp_cal)

        # --- Save / Reset ---
        btn_row = QHBoxLayout()
        btn_save = QPushButton("Save to NVS")
        btn_save.clicked.connect(self._on_save)
        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._on_reset)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_reset)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        layout.addWidget(self.lbl_status)

        # Load initial step data from config
        self._on_step_changed(0)

    def _on_step_changed(self, idx: int):
        cfg = self._controller.current_config
        step = self.cb_step.itemData(idx)
        gains = cfg.pga_gain_eff
        offsets = cfg.pga_offset_cal
        if gains and step < len(gains):
            self.spin_gain_factor.setValue(gains[step] / (1.0 if step == 0 else gains[0]))
        if offsets and step < len(offsets):
            self.spin_offset.setValue(offsets[step])

    def _on_set_vg(self):
        vg = self.spin_vg.value()
        ok = self._controller.pga_cal_set_vg(vg)
        self.lbl_status.setText("VG set" if ok else "Failed to set VG")

    def _on_auto_cal(self):
        self.btn_auto.setEnabled(False)
        self.lbl_status.setText("Auto-calibrating... (connect input to GND)")
        self._worker = _PgaCalWorker(self._controller)
        self._worker.finished.connect(self._on_auto_cal_done)
        self._worker.start()

    def _on_auto_cal_done(self, ok: bool):
        self.btn_auto.setEnabled(True)
        if ok:
            self.lbl_status.setText("Auto-calibration complete!")
            self._controller.pga_get_info()
        else:
            self.lbl_status.setText("Auto-calibration failed")

    def _on_set_gain(self):
        step = self.cb_step.currentData()
        factor = self.spin_gain_factor.value()
        ok = self._controller.pga_cal_set_gain(step, factor)
        self.lbl_status.setText("Gain factor set" if ok else "Failed")

    def _on_set_offset(self):
        step = self.cb_step.currentData()
        offset = self.spin_offset.value()
        ok = self._controller.pga_cal_set_offset(step, offset)
        self.lbl_status.setText("Offset set" if ok else "Failed")

    def _on_save(self):
        ok = self._controller.pga_cal_save()
        self.lbl_status.setText("Saved to NVS" if ok else "Save failed")

    def _on_reset(self):
        ok = self._controller.pga_cal_reset()
        if ok:
            self.lbl_status.setText("Reset to defaults")
            self._controller.pga_get_info()
            self._on_step_changed(self.cb_step.currentIndex())
