"""
trigger_panel.py — Controles de trigger.

Edge values (UI encoding):
  0=None, 1=Rising, 2=Falling, 3=Any

El mapeo al firmware (0=RISE, 1=FALL, 2=ANY, 3=NONE) se hace en device_controller.py.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSlider, QDoubleSpinBox, QSpinBox
from PyQt6.QtCore import Qt, pyqtSignal


class TriggerPanel(QWidget):

    # ch_idx, mv, edge_idx
    trigger_hw_changed = pyqtSignal(int, float, int)
    # mv, ch_idx (solo para mover la linea en el grafico sin enviar comando)
    trigger_ui_preview = pyqtSignal(float, int)
    pre_trigger_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Source & Edge
        row1 = QHBoxLayout()
        self.cb_source = QComboBox()
        self.cb_source.addItem("CH1", 0)
        self.cb_source.addItem("CH2", 1)
        self.cb_source.currentIndexChanged.connect(self._emit_hw_update)

        self.cb_edge = QComboBox()
        self.cb_edge.addItem("None", 0)
        self.cb_edge.addItem("Rising", 1)
        self.cb_edge.addItem("Falling", 2)
        self.cb_edge.addItem("Any", 3)
        self.cb_edge.setCurrentIndex(1)
        self.cb_edge.currentIndexChanged.connect(self._emit_hw_update)

        row1.addWidget(QLabel("Src:"))
        row1.addWidget(self.cb_source)
        row1.addWidget(QLabel("Edge:"))
        row1.addWidget(self.cb_edge)
        layout.addLayout(row1)

        # Level
        lvl_layout = QHBoxLayout()
        lvl_layout.addWidget(QLabel("Level:"))
        self.spin_lvl = QDoubleSpinBox()
        self.spin_lvl.setRange(-3000, 3000)
        self.spin_lvl.setSuffix(" mV")
        self.spin_lvl.setDecimals(1)
        # BUG FIX: valueChanged solo actualiza UI local y preview, NO hardware
        self.spin_lvl.valueChanged.connect(self._on_spin_value_changed)
        # Hardware solo en Enter o perder foco
        self.spin_lvl.editingFinished.connect(self._emit_hw_update)
        lvl_layout.addWidget(self.spin_lvl)
        layout.addLayout(lvl_layout)

        self.slider_lvl = QSlider(Qt.Orientation.Horizontal)
        self.slider_lvl.setRange(-3000, 3000)
        # Preview en tiempo real
        self.slider_lvl.valueChanged.connect(self._on_slider_value_changed)
        # Hardware solo al soltar
        self.slider_lvl.sliderReleased.connect(self._emit_hw_update)
        layout.addWidget(self.slider_lvl)

        # Pre-trigger
        row3 = QHBoxLayout()
        self.spin_pre = QSpinBox()
        self.spin_pre.setRange(0, 100)
        self.spin_pre.setSuffix(" %")
        self.spin_pre.setValue(50)
        self.spin_pre.valueChanged.connect(self.pre_trigger_changed.emit)

        row3.addWidget(QLabel("Pre:"))
        row3.addWidget(self.spin_pre)
        layout.addLayout(row3)

    def _on_spin_value_changed(self, val: float):
        self.slider_lvl.blockSignals(True)
        self.slider_lvl.setValue(int(val))
        self.slider_lvl.blockSignals(False)
        self.trigger_ui_preview.emit(val, self.cb_source.currentData())

    def _on_slider_value_changed(self, val: int):
        self.spin_lvl.blockSignals(True)
        self.spin_lvl.setValue(float(val))
        self.spin_lvl.blockSignals(False)
        self.trigger_ui_preview.emit(float(val), self.cb_source.currentData())

    def _emit_hw_update(self):
        """Emite la señal de cambio de hardware (envío por serial)."""
        ch = self.cb_source.currentData()
        mv = self.spin_lvl.value()
        edge = self.cb_edge.currentData()
        self.trigger_hw_changed.emit(ch, mv, edge)
