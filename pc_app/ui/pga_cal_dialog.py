"""
pga_cal_dialog.py — Dialog for PGA calibration.

Allows auto-calibration, manual VG setting, per-step gain trim
and offset, hardware topology config, and save/reset to NVS.

PGA-B03 FIX: Every action now:
  - Updates current_config locally (works fully offline)
  - Shows clear feedback when device is not connected
  - Never silently swallows failures

PGA-B04 FIX: Factory defaults updates local config without triggering
  a "Failed" error when offline.

PGA-B09 FIX: Auto-cal worker uses an abort flag instead of relying on
  QThread.quit() which has no effect on non-event-loop threads.
"""

import time

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QLabel, QPushButton, QDoubleSpinBox, QComboBox,
                             QFormLayout)
from PyQt6.QtCore import QThread, pyqtSignal


# ---------------------------------------------------------------------------
# Auto-calibration worker
# ---------------------------------------------------------------------------

class _PgaCalWorker(QThread):
    finished = pyqtSignal(bool)

    def __init__(self, controller):
        super().__init__()
        self._ctrl = controller
        self._abort = False  # PGA-B09: abort flag — QThread.quit() won't stop a sleep() loop

    def request_abort(self):
        """Signal the worker to stop at its next iteration boundary."""
        self._abort = True

    def run(self):
        self._ctrl.pga_cal_start()
        for _ in range(150):   # 30 s timeout (150 × 200 ms)
            if self._abort:
                self.finished.emit(False)
                return
            time.sleep(0.2)
            if self._abort:
                self.finished.emit(False)
                return
            self._ctrl.pga_get_info()
            if self._ctrl.current_config.pga_calibrated:
                self.finished.emit(True)
                return
        self.finished.emit(False)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class PgaCalDialog(QDialog):

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PGA Calibration")
        self.setMinimumWidth(490)
        self._controller = controller

        layout = QVBoxLayout(self)

        # ── Offline banner ──────────────────────────────────────────────
        self._lbl_offline = QLabel()
        self._lbl_offline.setStyleSheet(
            "background: #854d0e; color: #fef3c7; padding: 6px 10px;"
            " border-radius: 4px; font-size: 11px;")
        self._lbl_offline.setWordWrap(True)
        self._lbl_offline.setVisible(False)
        layout.addWidget(self._lbl_offline)

        # ── 1. Hardware Configuration ───────────────────────────────────
        grp_hw = QGroupBox("Hardware Configuration")
        hw_layout = QFormLayout(grp_hw)

        self.spin_div = QDoubleSpinBox()
        self.spin_div.setRange(0.0001, 1.0)
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

        # ── 2. Virtual Ground ───────────────────────────────────────────
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

        # ── 3. Per-Step Calibration ─────────────────────────────────────
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

        # ── 4. Persistence ──────────────────────────────────────────────
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

        # Initial population
        self._on_step_changed(0)
        self._update_offline_banner()

    # ------------------------------------------------------------------
    # Offline awareness helpers
    # ------------------------------------------------------------------

    def _connected(self) -> bool:
        return self._controller.connected

    def _update_offline_banner(self):
        offline = not self._connected()
        self._lbl_offline.setVisible(offline)
        if offline:
            self._lbl_offline.setText(
                "\u26a0  No device connected.  Hardware parameters and calibration "
                "values are stored locally and will be pushed on next connection.  "
                "Auto-Calibrate and Save/Reset to NVS require a connected device.")

    def _status_ok(self, msg: str):
        self.lbl_status.setStyleSheet("color: #22c55e; font-size: 10px;")
        self.lbl_status.setText(msg)

    def _status_warn(self, msg: str):
        self.lbl_status.setStyleSheet("color: #eab308; font-size: 10px;")
        self.lbl_status.setText(msg)

    def _status_err(self, msg: str):
        self.lbl_status.setStyleSheet("color: #ef4444; font-size: 10px;")
        self.lbl_status.setText(msg)

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

    def _apply_hw_to_local_config(self):
        """PGA-B03/04: save spinner values to current_config — no firmware needed."""
        cfg = self._controller.current_config
        cfg.pga_div_ratio    = self.spin_div.value()
        cfg.pga_r_fb_ohm     = self.spin_rf.value()
        cfg.pga_r_nom_ohm    = [self.spin_r1.value(),
                                 self.spin_r2.value(),
                                 self.spin_r3.value()]
        cfg.pga_gpio_ron_ohm = self.spin_ron.value()

    def _on_step_changed(self, idx: int):
        cfg = self._controller.current_config
        step = self.cb_step.itemData(idx)

        nominals    = cfg.pga_gain_nominal
        cal_factors = cfg.pga_gain_cal_factor
        offsets     = cfg.pga_offset_cal

        nominal   = nominals[step]    if nominals    and step < len(nominals)    else 1.0
        trim      = cal_factors[step] if cal_factors and step < len(cal_factors) else 1.0
        offset_mv = offsets[step]     if offsets     and step < len(offsets)     else 0.0

        self.lbl_nominal.setText(f"Nominal: x{nominal:.4f}")
        self.spin_gain_trim.blockSignals(True)
        self.spin_gain_trim.setValue(trim)
        self.spin_gain_trim.blockSignals(False)
        self.lbl_effective.setText(f"Effective: x{nominal * trim:.4f}")
        self.spin_offset.setValue(offset_mv)

    def _on_trim_changed(self, value: float):
        cfg   = self._controller.current_config
        step  = self.cb_step.currentData()
        noms  = cfg.pga_gain_nominal
        nom   = noms[step] if noms and step < len(noms) else 1.0
        self.lbl_effective.setText(f"Effective: x{nom * value:.4f}")

    # ------------------------------------------------------------------
    # Hardware
    # ------------------------------------------------------------------

    def _on_apply_hardware(self):
        """PGA-B03/04 FIX: Always save locally. Push to device only when connected."""
        self._apply_hw_to_local_config()

        if not self._connected():
            self._status_warn("Hardware config saved locally (offline — will push on connect)")
            return

        ok = self._controller.pga_set_hardware(
            self.spin_div.value(), self.spin_rf.value(),
            self.spin_r1.value(), self.spin_r2.value(),
            self.spin_r3.value(), self.spin_ron.value())
        if ok:
            self._controller.pga_get_info()
            self._refresh_from_config()
            self._status_ok("Hardware config applied")
        else:
            self._status_err("Failed to push hardware config to device")

    def _on_load_factory_defaults(self):
        """PGA-B04 FIX: populate spinners then apply (handles online/offline)."""
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
        self._controller.current_config.pga_vg_mv = vg   # Always local

        if not self._connected():
            self._status_warn(f"VG = {vg:.1f} mV saved locally (offline)")
            return

        ok = self._controller.pga_cal_set_vg(vg)
        if ok:
            self._controller.pga_get_info()
            self._status_ok(f"VG set to {vg:.1f} mV")
        else:
            self._status_err("Failed to set VG on device")

    def _on_set_vg_default(self):
        vg = self.spin_vg.value()
        self._controller.current_config.pga_vg_default = vg  # Always local

        if not self._connected():
            self._status_warn(f"VG default = {vg:.1f} mV saved locally (offline)")
            return

        ok = self._controller.pga_set_vg_default(vg)
        if ok:
            self._status_ok(f"VG default set to {vg:.1f} mV (persisted)")
        else:
            self._status_err("Failed to set VG default on device")

    def _on_auto_cal(self):
        if not self._connected():
            self._status_err("Auto-Calibrate requires a connected device")
            return
        # Switch button to "Cancel" mode
        self.btn_auto.clicked.disconnect()
        self.btn_auto.clicked.connect(self._on_auto_cal_cancel)
        self.btn_auto.setText("Calibrating\u2026 (click to cancel)")
        self._status_warn("Auto-calibrating\u2026 (connect input to GND)")
        self._worker = _PgaCalWorker(self._controller)
        self._worker.finished.connect(self._on_auto_cal_done)
        self._worker.start()

    def _on_auto_cal_cancel(self):
        """PGA-B09 FIX: abort flag — QThread.quit() has no effect on sleep() loops."""
        if hasattr(self, '_worker') and self._worker.isRunning():
            self._worker.request_abort()
        self._reset_auto_cal_button()
        self._status_warn("Auto-calibration cancelled")

    def _on_auto_cal_done(self, ok: bool):
        self._reset_auto_cal_button()
        if ok:
            self._controller.pga_get_info()
            self._refresh_from_config()
            self._status_ok("Auto-calibration complete!")
        else:
            self._status_err("Auto-calibration failed or timed out (30 s)")

    def _reset_auto_cal_button(self):
        try:
            self.btn_auto.clicked.disconnect()
        except RuntimeError:
            pass
        self.btn_auto.clicked.connect(self._on_auto_cal)
        self.btn_auto.setText("Auto-Calibrate (connect input to GND)")

    # ------------------------------------------------------------------
    # Per-step correction
    # ------------------------------------------------------------------

    def _on_set_gain(self):
        step = self.cb_step.currentData()
        trim = self.spin_gain_trim.value()

        # Always update local config
        cfg = self._controller.current_config
        if cfg.pga_gain_cal_factor and step < len(cfg.pga_gain_cal_factor):
            cfg.pga_gain_cal_factor[step] = trim

        if not self._connected():
            self._status_warn(f"Step {step} gain trim = {trim:.4f} saved locally (offline)")
            self._on_step_changed(self.cb_step.currentIndex())
            return

        ok = self._controller.pga_cal_set_gain(step, trim)
        if ok:
            self._controller.pga_get_info()
            self._status_ok(f"Step {step} gain trim set to {trim:.4f}")
        else:
            self._status_err(f"Failed to push gain trim for step {step}")

    def _on_set_offset(self):
        step   = self.cb_step.currentData()
        offset = self.spin_offset.value()

        # Always update local config
        cfg = self._controller.current_config
        if cfg.pga_offset_cal and step < len(cfg.pga_offset_cal):
            cfg.pga_offset_cal[step] = offset

        if not self._connected():
            self._status_warn(f"Step {step} offset = {offset:.1f} mV saved locally (offline)")
            return

        ok = self._controller.pga_cal_set_offset(step, offset)
        if ok:
            self._controller.pga_get_info()
            self._status_ok(f"Step {step} offset set to {offset:.1f} mV")
        else:
            self._status_err(f"Failed to push offset for step {step}")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _on_save(self):
        if not self._connected():
            self._status_err("Save to NVS requires a connected device")
            return
        ok = self._controller.pga_cal_save()
        if ok:
            self._status_ok("Saved to NVS")
        else:
            self._status_err("Save to NVS failed")

    def _on_reset(self):
        if not self._connected():
            self._status_err("Reset Calibration requires a connected device")
            return
        ok = self._controller.pga_cal_reset()
        if ok:
            self._status_ok("Calibration reset to defaults")
            self._controller.pga_get_info()
            self._refresh_from_config()
        else:
            self._status_err("Reset failed")

    # ------------------------------------------------------------------
    # Cleanup  (PC-10 + PGA-B09 FIX)
    # ------------------------------------------------------------------

    def _stop_worker(self):
        if hasattr(self, '_worker') and self._worker.isRunning():
            self._worker.request_abort()   # PGA-B09: abort flag, not quit()
            self._worker.wait(1000)        # 1 s grace — covers one sleep(0.2) iteration

    def closeEvent(self, event):
        self._stop_worker()
        super().closeEvent(event)

    def reject(self):
        self._stop_worker()
        super().reject()
