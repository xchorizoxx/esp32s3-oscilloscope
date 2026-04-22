"""
channel_panel.py — Controles individuales para cada canal.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSlider, QDoubleSpinBox, QCheckBox
from PyQt6.QtCore import Qt, pyqtSignal

class ChannelPanel(QWidget):
    
    # Señales: offset_mv, v_div_idx, attenuation_db, coupling, visible
    offset_changed = pyqtSignal(float)
    scale_changed = pyqtSignal(float)
    attenuation_changed = pyqtSignal(int)
    coupling_changed = pyqtSignal(str)
    visibility_changed = pyqtSignal(bool)
    
    def __init__(self, title: str, color_hex: str, parent=None):
        super().__init__(parent)
        
        self.scales_mv = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000]
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Header (Enable checkbox + Title)
        header_layout = QHBoxLayout()
        self.chk_enable = QCheckBox(title)
        self.chk_enable.setChecked(True)
        self.chk_enable.setStyleSheet(f"color: {color_hex}; font-weight: bold;")
        self.chk_enable.toggled.connect(self.visibility_changed.emit)
        header_layout.addWidget(self.chk_enable)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # Scale (V/div)
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("Scale:"))
        self.cb_scale = QComboBox()
        for s in self.scales_mv:
            if s >= 1000:
                self.cb_scale.addItem(f"{s/1000:.1f} V/div", s)
            else:
                self.cb_scale.addItem(f"{s} mV/div", s)
        self.cb_scale.setCurrentIndex(6) # 1V/div default
        self.cb_scale.currentIndexChanged.connect(
            lambda idx: self.scale_changed.emit(float(self.cb_scale.itemData(idx)))
        )
        scale_layout.addWidget(self.cb_scale)
        layout.addLayout(scale_layout)
        
        # Offset
        offset_layout = QHBoxLayout()
        offset_layout.addWidget(QLabel("Offset:"))
        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-50000, 50000)
        self.spin_offset.setSuffix(" mV")
        self.spin_offset.setDecimals(1)
        self.spin_offset.valueChanged.connect(self._on_spin_offset)
        
        self.slider_offset = QSlider(Qt.Orientation.Horizontal)
        self.slider_offset.setRange(-5000, 5000) # mV
        self.slider_offset.valueChanged.connect(self._on_slider_offset)
        
        offset_layout.addWidget(self.spin_offset)
        layout.addLayout(offset_layout)
        layout.addWidget(self.slider_offset)
        
        # Coupling & Attenuation
        opts_layout = QHBoxLayout()
        self.cb_coupling = QComboBox()
        self.cb_coupling.addItems(["DC", "AC"])
        self.cb_coupling.currentTextChanged.connect(self.coupling_changed.emit)
        opts_layout.addWidget(QLabel("Cpl:"))
        opts_layout.addWidget(self.cb_coupling)
        
        self.cb_atten = QComboBox()
        self.cb_atten.addItem("0 dB", 0)
        self.cb_atten.addItem("2.5 dB", 1)
        self.cb_atten.addItem("6 dB", 2)
        self.cb_atten.addItem("12 dB", 3)
        self.cb_atten.currentIndexChanged.connect(
            lambda idx: self.attenuation_changed.emit(self.cb_atten.itemData(idx))
        )
        opts_layout.addWidget(QLabel("Att:"))
        opts_layout.addWidget(self.cb_atten)
        layout.addLayout(opts_layout)

    def _on_spin_offset(self, val: float):
        self.slider_offset.blockSignals(True)
        self.slider_offset.setValue(int(val))
        self.slider_offset.blockSignals(False)
        self.offset_changed.emit(val)
        
    def _on_slider_offset(self, val: int):
        self.spin_offset.blockSignals(True)
        self.spin_offset.setValue(float(val))
        self.spin_offset.blockSignals(False)
        self.offset_changed.emit(float(val))
