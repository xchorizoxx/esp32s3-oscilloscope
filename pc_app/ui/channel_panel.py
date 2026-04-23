"""
channel_panel.py — Controles individuales para cada canal.

CH1 -> indice interno 0, CH2 -> indice interno 1.
El mapeo es explicito y consistente en toda la aplicacion.

Cambios UI:
  - BUG-08 FIX: Escalas limitadas a rango real del ADC (max 5 V/div)
  - Atenuacion: default fijo en 12 dB, con tooltip explicativo
  - BUG-12 FIX: Boton CAL GND para calibrar offset de cero del ADC
  - Tooltips en todos los controles
"""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QComboBox, QSlider, QDoubleSpinBox, QCheckBox,
                              QPushButton)
from PyQt6.QtCore import Qt, pyqtSignal


class ChannelPanel(QWidget):

    # Senales
    offset_changed      = pyqtSignal(float)
    scale_changed       = pyqtSignal(float)
    attenuation_changed = pyqtSignal(int)
    coupling_changed    = pyqtSignal(str)
    visibility_changed  = pyqtSignal(bool)
    cal_gnd_requested   = pyqtSignal()   # BUG-12 FIX: calibracion de cero

    # BUG-08 FIX: escalas limitadas al rango real del ADC (0-3.1V con 12dB).
    # El ADC del ESP32-S3 satura ~3100 mV con 12dB atten.
    # 50 V/div y 20 V/div no tienen utilidad y confunden al usuario.
    SCALES_MV = [10, 20, 50, 100, 200, 500, 1000, 2000, 3000, 5000]

    def __init__(self, title: str, color_hex: str, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        # --- Header: Enable checkbox ---
        header_layout = QHBoxLayout()
        self.chk_enable = QCheckBox(title)
        self.chk_enable.setChecked(True)
        self.chk_enable.setStyleSheet(f"color: {color_hex}; font-weight: bold;")
        self.chk_enable.setToolTip("Activar/desactivar la visualizacion de este canal")
        self.chk_enable.toggled.connect(self.visibility_changed.emit)
        header_layout.addWidget(self.chk_enable)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # --- Scale (V/div) ---
        scale_layout = QHBoxLayout()
        lbl_scale = QLabel("Scale:")
        lbl_scale.setToolTip("Escala de voltaje por division de cuadricula.\n"
                              "ADC del ESP32-S3: rango maximo ~3.1V con 12dB atten.")
        scale_layout.addWidget(lbl_scale)
        self.cb_scale = QComboBox()
        self.cb_scale.setToolTip("mV o V por division — cuanto voltaje representa cada cuadro")
        for s in self.SCALES_MV:
            if s >= 1000:
                self.cb_scale.addItem(f"{s/1000:.1f} V/div", s)
            else:
                self.cb_scale.addItem(f"{s} mV/div", s)
        self.cb_scale.setCurrentIndex(6)  # 1 V/div default
        self.cb_scale.currentIndexChanged.connect(
            lambda idx: self.scale_changed.emit(float(self.cb_scale.itemData(idx)))
        )
        scale_layout.addWidget(self.cb_scale)
        layout.addLayout(scale_layout)

        # --- Coupling ---
        cpl_layout = QHBoxLayout()
        lbl_cpl = QLabel("Coupling:")
        lbl_cpl.setToolTip(
            "DC: muestra la senal tal cual (incluye offset DC).\n"
            "AC: filtra el DC, muestra solo la componente alterna (software IIR).\n"
            "GND: muestra una linea de referencia en cero."
        )
        cpl_layout.addWidget(lbl_cpl)
        self.cb_coupling = QComboBox()
        self.cb_coupling.addItems(["DC", "AC", "GND"])
        self.cb_coupling.setToolTip("Modo de acoplamiento de senal")
        self.cb_coupling.currentTextChanged.connect(self.coupling_changed.emit)
        cpl_layout.addWidget(self.cb_coupling)
        layout.addLayout(cpl_layout)

        # --- GND Offset + CAL GND button ---
        offset_row = QHBoxLayout()
        lbl_off = QLabel("GND:")
        lbl_off.setToolTip(
            "Desplaza verticalmente la senal en pantalla.\n"
            "Presiona CAL para calibrar automaticamente el nivel de cero del ADC.\n"
            "Util cuando la senal 'cae a -1V' al desconectar la entrada."
        )
        offset_row.addWidget(lbl_off)

        self.spin_offset = QDoubleSpinBox()
        self.spin_offset.setRange(-3000, 3000)
        self.spin_offset.setSuffix(" mV")
        self.spin_offset.setDecimals(0)
        self.spin_offset.setToolTip("Offset vertical en mV")
        self.spin_offset.valueChanged.connect(self._on_spin_offset)
        offset_row.addWidget(self.spin_offset)

        # BUG-12 FIX: Boton CAL GND
        self.btn_cal = QPushButton("CAL")
        self.btn_cal.setFixedWidth(38)
        self.btn_cal.setToolTip(
            "Calibrar GND:\n"
            "  1. Resetea el integrador EMA del AC coupling.\n"
            "  2. Pone el offset a cero.\n"
            "Usa esto cuando la senal se desplaza al desconectar la entrada."
        )
        self.btn_cal.clicked.connect(self._on_cal_clicked)
        offset_row.addWidget(self.btn_cal)
        layout.addLayout(offset_row)

        # Slider de offset
        self.slider_offset = QSlider(Qt.Orientation.Horizontal)
        self.slider_offset.setRange(-3000, 3000)
        self.slider_offset.setToolTip("Arrastra para desplazar la senal verticalmente")
        self.slider_offset.valueChanged.connect(self._on_slider_offset)
        layout.addWidget(self.slider_offset)

        # --- ADC Attenuation (advanced, fixed at 12 dB) ---
        # Para el 99% de los casos 12 dB es correcto. Se muestra como control
        # avanzado con tooltip explicativo para que no confunda.
        atten_row = QHBoxLayout()
        lbl_att = QLabel("ADC Atten:")
        lbl_att.setToolTip(
            "Atenuacion interna del ADC del ESP32-S3.\n"
            "12 dB = rango 0-2500 mV (recomendado).\n"
            "Cambia solo si usas senales muy debiles con amplificador externo."
        )
        atten_row.addWidget(lbl_att)
        self.cb_atten = QComboBox()
        self.cb_atten.addItem("0 dB  (0-750 mV)",  0)
        self.cb_atten.addItem("2.5 dB (0-1100 mV)", 1)
        self.cb_atten.addItem("6 dB  (0-1500 mV)", 2)
        self.cb_atten.addItem("12 dB (0-2500 mV)", 3)
        self.cb_atten.setCurrentIndex(3)   # Default: 12 dB
        self.cb_atten.setToolTip("Atenuacion ADC — dejar en 12 dB para uso general")
        self.cb_atten.currentIndexChanged.connect(
            lambda idx: self.attenuation_changed.emit(self.cb_atten.itemData(idx))
        )
        atten_row.addWidget(self.cb_atten)
        layout.addLayout(atten_row)

    # ------------------------------------------------------------------
    # Slots internos
    # ------------------------------------------------------------------

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

    def _on_cal_clicked(self):
        """
        CAL GND: resetea el offset a cero y emite cal_gnd_requested
        para que MainWindow resetee el integrador EMA del AC coupling.
        Corrige el symptom 'senal cae a -1V al desconectar entrada'.
        """
        self.spin_offset.blockSignals(True)
        self.slider_offset.blockSignals(True)
        self.spin_offset.setValue(0.0)
        self.slider_offset.setValue(0)
        self.spin_offset.blockSignals(False)
        self.slider_offset.blockSignals(False)
        self.offset_changed.emit(0.0)
        self.cal_gnd_requested.emit()
