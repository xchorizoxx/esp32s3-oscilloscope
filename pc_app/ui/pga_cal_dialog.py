"""
pga_cal_dialog.py — Dialog for PGA calibration.

Allows auto-calibration, manual VG setting, per-step gain trim
and offset, hardware topology config, and save/reset to NVS.
"""

import time

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
        for _ in range(150):  # 30s timeout (150 * 200ms)
            time.sleep(0.2)
            self._ctrl.pga_get_info()
            if self._ctrl.current_config.pga_calibrated:
                self.finished.emit(True)
                return
        self.finished.emit(False)


class PgaCalDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PGA Calibration")
        self.setMinimumWidth(450)
        self._controller = controller

        layout = QVBoxLayout(self)

        # --- 1. Hardware Configuration ---
        grp_hw = QGroupBox("Hardware Configuration")
        hw_layout = QFormLayout(grp_hw)

        self.spin_div = QDoubleSpinBox()
        self.spin_div.setRange(0.01, 1.0)
        self.spin_div.setDecimals(6)
        self.spin_div.setSingleStep(0.001)
        self.spin_div.setValue(controller.current_config.pga_div_ratio)
        hw_layout.addRow("Divider Ratio:", self.spin_div)

        self.spin_rf = QDoubleSpinBox()
        self.spin_rf.setRange(100, 100000)
        self.spin_rf.setSuffix(" Ohm")
        self.spin_rf.setDecimals(0)
        self.spin_rf.setValue(controller.current_config.pga_r_fb_ohm)
        hw_layout.addRow("Rf (feedback):", self.spin_rf)

        self.spin_r1 = QDoubleSpinBox()
        self.spin_r1.setRange(100, 100000)
        self.spin_r1.setSuffix(" Ohm")
        self.spin_r1.setDecimals(0)
        self.spin_r1.setValue(controller.current_config.pga_r_nom_ohm[0])
        hw_layout.addRow("R1 (GPIO39, bit 0):", self.spin_r1)

        self.spin_r2 = QDoubleSpinBox()
        self.spin_r2.setRange(100, 100000)
        self.spin_r2.setSuffix(" Ohm")
        self.spin_r2.setDecimals(0)
        self.spin_r2.setValue(controller.current_config.pga_r_nom_ohm[1])
        hw_layout.addRow("R2 (GPIO40, bit 1):", self.spin_r2)

        self.spin_r3 = QDoubleSpinBox()
        self.spin_r3.setRange(100, 100000)
        self.spin_r3.setSuffix(" Ohm")
        self.spin_r3.setDecimals(0)
        self.spin_r3.setValue(controller.current_config.pga_r_nom_ohm[2])
        hw_layout.addRow("R3 (GPIO41, bit 2):", self.spin_r3)

        self.spin_ron = QDoubleSpinBox()
        self.spin_ron.setRange(0, 500)
        self.spin_ron.setSuffix(" Ohm")
        self.spin_ron.setDecimals(1)
        self.spin_ron.setValue(controller.current_config.pga_gpio_ron_ohm)
        hw_layout.addRow("GPIO Ron:", self.spin_ron)

        hw_btn_row = QHBoxLayout()
        btn_apply_hw = QPushButton("Apply Hardware Config")
        btn_apply_hw.clicked.connect(self._on_apply_hardware)
        hw_btn_row.addWidget(btn_apply_hw)
        btn_hw_defaults = QPushButton("Load Factory Defaults")
        btn_hw_defaults.clicked.connect(self._on_load_factory_defaults)
        hw_btn_row.addWidget(btn_hw_defaults)
        hw_layout.addRow(hw_btn_row)

        layout.addWidget(grp_hw)

        # --- 2. Virtual Ground ---
        grp_vg = QGroupBox("Virtual Ground (VG)")
        vg_layout = QFormLayout(grp_vg)

        self.spin_vg = QDoubleSpinBox()
        self.spin_vg.setRange(100.0, 3000.0)
        self.spin_vg.setSuffix(" mV")
        self.spin_vg.setDecimals(1)
        self.spin_vg.setValue(controller.current_config.pga_vg_mv)
        vg_layout.addRow("VG:", self.spin_vg)

        vg_btn_row = QHBoxLayout()
        btn_set_vg = QPushButton("Set VG")
        btn_set_vg.clicked.connect(self._on_set_vg)
        vg_btn_row.addWidget(btn_set_vg)
        btn_set_vg_default = QPushButton("Set as Default")
        btn_set_vg_default.clicked.connect(self._on_set_vg_default)
        vg_btn_row.addWidget(btn_set_vg_default)
        vg_layout.addRow(vg_btn_row)

        self.btn_auto = QPushButton("Auto-Calibrate (connect input to GND)")
        self.btn_auto.clicked.connect(self._on_auto_cal)
        vg_layout.addRow(self.btn_auto)

        layout.addWidget(grp_vg)

        # --- 3. Per-Step Calibration ---
        grp_cal = QGroupBox("Per-Step Calibration")
        cal_layout = QFormLayout(grp_cal)

        self.cb_step = QComboBox()
        for i in range(8):
            self.cb_step.addItem(f"Step {i}", i)
        self.cb_step.currentIndexChanged.connect(self._on_step_changed)
        cal_layout.addRow("Step:", self.cb_step)

        self.lbl_nominal = QLabel("Nominal: x1.00")
        self.lbl_nominal.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        cal_layout.addRow(self.lbl_nominal)

        self.spin_gain_trim = QDoubleSpinBox()
        self.spin_gain_trim.setRange(0.5, 2.0)
        self.spin_gain_trim.setDecimals(4)
        self.spin_gain_trim.setSingleStep(0.001)
        self.spin_gain_trim.setValue(1.0)
        self.spin_gain_trim.valueChanged.connect(self._on_trim_changed)
        cal_layout.addRow("Gain Trim (near 1.0):", self.spin_gain_trim)

        self.lbl_effective = QLabel("Effective: x1.0000")
        self.lbl_effective.setStyleSheet("color: #22c55e; font-size: 10px;")
        cal_layout.addRow(self.lbl_effective)

        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-500.0, 500.0)
        self.spin_offset.setSuffix(" mV")
        self.spin_offset.setDecimals(1)
        self.spin_offset.setValue(0.0)
        cal_layout.addRow("Offset:", self.spin_offset)

        cal_btn_row = QHBoxLayout()
        btn_set_gain = QPushButton("Set Gain Trim")
        btn_set_gain.clicked.connect(self._on_set_gain)
        cal_btn_row.addWidget(btn_set_gain)
        btn_set_offset = QPushButton("Set Offset")
        btn_set_offset.clicked.connect(self._on_set_offset)
        cal_btn_row.addWidget(btn_set_offset)
        cal_layout.addRow(cal_btn_row)

        layout.addWidget(grp_cal)

        # --- 4. Persistence ---
        btn_row = QHBoxLayout()
        btn_save = QPushButton("Save to NVS")
        btn_save.clicked.connect(self._on_save)
        btn_reset = QPushButton("Reset Calibration")
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refresh_from_config(self):
        cfg = self._controller.current_config
        self.spin_vg.setValue(cfg.pga_vg_mv)
        self.spin_div.setValue(cfg.pga_div_ratio)
        self.spin_rf.setValue(cfg.pga_r_fb_ohm)
        if len(cfg.pga_r_nom_ohm) >= 3:
            self.spin_r1.setValue(cfg.pga_r_nom_ohm[0])
            self.spin_r2.setValue(cfg.pga_r_nom_ohm[1])
            self.spin_r3.setValue(cfg.pga_r_nom_ohm[2])
        self.spin_ron.setValue(cfg.pga_gpio_ron_ohm)
        self._on_step_changed(self.cb_step.currentIndex())

    def _on_step_changed(self, idx: int):
        cfg = self._controller.current_config
        step = self.cb_step.itemData(idx)

        nominals = cfg.pga_gain_nominal
        cal_factors = cfg.pga_gain_cal_factor
        offsets = cfg.pga_offset_cal

        nominal = nominals[step] if nominals and step < len(nominals) else 1.0
        trim = cal_factors[step] if cal_factors and step < len(cal_factors) else 1.0
        offset_mv = offsets[step] if offsets and step < len(offsets) else 0.0

        self.lbl_nominal.setText(f"Nominal: x{nominal:.4f}")
        self.spin_gain_trim.blockSignals(True)
        self.spin_gain_trim.setValue(trim)
        self.spin_gain_trim.blockSignals(False)
        self.lbl_effective.setText(f"Effective: x{nominal * trim:.4f}")
        self.spin_offset.setValue(offset_mv)

    def _on_trim_changed(self, value: float):
        cfg = self._controller.current_config
        step = self.cb_step.currentData()
        nominals = cfg.pga_gain_nominal
        nominal = nominals[step] if nominals and step < len(nominals) else 1.0
        self.lbl_effective.setText(f"Effective: x{nominal * value:.4f}")

    # ------------------------------------------------------------------
    # Hardware
    # ------------------------------------------------------------------

    def _on_apply_hardware(self):
        ok = self._controller.pga_set_hardware(
            self.spin_div.value(), self.spin_rf.value(),
            self.spin_r1.value(), self.spin_r2.value(),
            self.spin_r3.value(), self.spin_ron.value())
        if ok:
            self._controller.pga_get_info()
            self._refresh_from_config()
            self.lbl_status.setText("Hardware config applied")
        else:
            self.lbl_status.setText("Failed to apply hardware config")

    def _on_load_factory_defaults(self):
        self.spin_div.setValue(100000.0 / (1000000.0 + 100000.0))
        self.spin_rf.setValue(36000.0)
        self.spin_r1.setValue(36000.0)
        self.spin_r2.setValue(9090.0)
        self.spin_r3.setValue(4020.0)
        self.spin_ron.setValue(50.0)
        self._on_apply_hardware()

    # ------------------------------------------------------------------
    # Virtual Ground
    # ------------------------------------------------------------------

    def _on_set_vg(self):
        vg = self.spin_vg.value()
        ok = self._controller.pga_cal_set_vg(vg)
        if ok:
            self._controller.pga_get_info()
            self.lbl_status.setText("VG set")
        else:
            self.lbl_status.setText("Failed to set VG")

    def _on_set_vg_default(self):
        vg = self.spin_vg.value()
        ok = self._controller.pga_set_vg_default(vg)
        if ok:
            self.lbl_status.setText(f"VG default set to {vg:.1f} mV (persisted)")
        else:
            self.lbl_status.setText("Failed to set VG default")

    def _on_auto_cal(self):
        self.btn_auto.setEnabled(False)
        self.lbl_status.setText("Auto-calibrating... (connect input to GND)")
        self._worker = _PgaCalWorker(self._controller)
        self._worker.finished.connect(self._on_auto_cal_done)
        self._worker.start()

    def _on_auto_cal_done(self, ok: bool):
        self.btn_auto.setEnabled(True)
        if ok:
            self._controller.pga_get_info()
            self._refresh_from_config()
            self.lbl_status.setText("Auto-calibration complete!")
        else:
            self.lbl_status.setText("Auto-calibration timeout (30s)")

    # ------------------------------------------------------------------
    # Per-step correction
    # ------------------------------------------------------------------

    def _on_set_gain(self):
        step = self.cb_step.currentData()
        trim = self.spin_gain_trim.value()
        ok = self._controller.pga_cal_set_gain(step, trim)
        if ok:
            self._controller.pga_get_info()
            self.lbl_status.setText(f"Step {step} gain trim set to {trim:.4f}")
        else:
            self.lbl_status.setText("Failed")

    def _on_set_offset(self):
        step = self.cb_step.currentData()
        offset = self.spin_offset.value()
        ok = self._controller.pga_cal_set_offset(step, offset)
        if ok:
            self._controller.pga_get_info()
            self.lbl_status.setText(f"Step {step} offset set to {offset:.1f} mV")
        else:
            self.lbl_status.setText("Failed")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _on_save(self):
        ok = self._controller.pga_cal_save()
        if ok:
            self.lbl_status.setText("Saved to NVS")
        else:
            self.lbl_status.setText("Save failed")

    def _on_reset(self):
        ok = self._controller.pga_cal_reset()
        if ok:
            self.lbl_status.setText("Calibration reset to defaults")
            self._controller.pga_get_info()
            self._refresh_from_config()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _stop_worker(self):
        """PC-10 FIX: Stop auto-cal worker before dialog is destroyed.
        Prevents the finished signal from being delivered to a dead widget."""
        if hasattr(self, '_worker') and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)  # Max 2 s grace period

    def closeEvent(self, event):
        self._stop_worker()
        super().closeEvent(event)

    def reject(self):
        self._stop_worker()
        super().reject()
