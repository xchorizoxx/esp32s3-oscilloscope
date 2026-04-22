"""
fft_widget.py — Widget de espectro FFT con PyQtGraph.

Mejoras:
  - Colores sincronizados con waveform_widget (CH1=cyan, CH2=amarillo).
  - Controles funcionales para cambiar unidad (dBV / mV / Linear).
  - Sincronizacion de ventana de enventanado con fft_engine.
"""

import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QComboBox, QPushButton)
from PyQt6.QtCore import Qt, pyqtSignal


class FFTWidget(QWidget):

    # Senal emitida cuando cambia la ventana seleccionada
    window_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        pg.setConfigOptions(antialias=True, useOpenGL=True)

        self.plot_widget = pg.PlotWidget(title="FFT Spectrum")
        self.plot_widget.setBackground('#111')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_item = self.plot_widget.getPlotItem()

        # Trazas — COLORES SINCRONIZADOS con waveform_widget
        # CH1 = cyan #22d3ee, CH2 = yellow #facc15
        self.curve_ch1 = self.plot_item.plot(pen=pg.mkPen('#22d3ee', width=1.5))
        self.curve_ch2 = self.plot_item.plot(pen=pg.mkPen('#facc15', width=1.5))

        # Peak labels
        self.peak_label_ch1 = pg.TextItem(color='#22d3ee', anchor=(0, 1))
        self.peak_label_ch2 = pg.TextItem(color='#facc15', anchor=(0, 1))
        self.plot_item.addItem(self.peak_label_ch1)
        self.plot_item.addItem(self.peak_label_ch2)

        layout.addWidget(self.plot_widget)

        # --- Controles inferiores ---
        controls = QHBoxLayout()
        controls.setSpacing(8)

        # Selector de unidad
        controls.addWidget(QLabel("Unit:"))
        self.cb_unit = QComboBox()
        self.cb_unit.addItem("dBV", "dbv")
        self.cb_unit.addItem("mV", "mv")
        self.cb_unit.addItem("Linear", "linear")
        self.cb_unit.currentIndexChanged.connect(self._on_unit_changed)
        controls.addWidget(self.cb_unit)

        controls.addSpacing(16)

        # Selector de ventana
        controls.addWidget(QLabel("Window:"))
        self.cb_window = QComboBox()
        self.cb_window.addItem("Hanning", "hanning")
        self.cb_window.addItem("Hamming", "hamming")
        self.cb_window.addItem("Blackman", "blackman")
        self.cb_window.addItem("Rectangular", "rectangular")
        self.cb_window.currentTextChanged.connect(self.window_changed.emit)
        controls.addWidget(self.cb_window)

        controls.addStretch()
        layout.addLayout(controls)

        # Estado
        self.ch1_visible = True
        self.ch2_visible = True
        self.y_mode = 'dbv'  # 'dbv', 'mv', 'linear'
        self.current_window = 'hanning'

        self.plot_item.setLabel('bottom', "Frequency (Hz)")
        self.plot_item.setLabel('left', "Magnitude (dBV)")

    def set_ch_visible(self, ch: int, visible: bool):
        if ch == 0:
            self.ch1_visible = visible
            self.curve_ch1.setVisible(visible)
            self.peak_label_ch1.setVisible(visible)
        else:
            self.ch2_visible = visible
            self.curve_ch2.setVisible(visible)
            self.peak_label_ch2.setVisible(visible)

    def _on_unit_changed(self, idx: int):
        mode = self.cb_unit.itemData(idx)
        self.set_y_mode(mode)

    def set_y_mode(self, mode: str):
        self.y_mode = mode.lower()
        if self.y_mode == 'dbv':
            self.plot_item.setLabel('left', "Magnitude (dBV)")
            self.plot_item.setYRange(-100, 20)
        elif self.y_mode == 'mv':
            self.plot_item.setLabel('left', "Magnitude (mV)")
            self.plot_item.autoRange()
        else:  # linear
            self.plot_item.setLabel('left', "Magnitude (linear)")
            self.plot_item.autoRange()

    def set_window(self, window: str):
        """Actualiza la ventana seleccionada en el combo (llamado desde MainWindow)."""
        idx = self.cb_window.findData(window.lower())
        if idx >= 0:
            self.cb_window.blockSignals(True)
            self.cb_window.setCurrentIndex(idx)
            self.cb_window.blockSignals(False)

    def update_fft(self, ch: int, freqs: np.ndarray, magnitudes_mv: np.ndarray,
                   magnitudes_db: np.ndarray, peak_freq: float, peak_mv: float):
        if ch == 0 and not self.ch1_visible:
            return
        if ch == 1 and not self.ch2_visible:
            return

        # Seleccionar magnitud segun modo
        if self.y_mode == 'dbv':
            mags = magnitudes_db
        elif self.y_mode == 'mv':
            mags = magnitudes_mv
        else:  # linear
            mags = magnitudes_mv

        curve = self.curve_ch1 if ch == 0 else self.curve_ch2
        label = self.peak_label_ch1 if ch == 0 else self.peak_label_ch2

        curve.setData(freqs, mags)

        # Position label at peak
        if len(freqs) > 0 and len(mags) > 0:
            peak_val = float(np.max(mags))
            label.setPos(peak_freq, peak_val)
            label.setText(f"Peak: {peak_freq/1000:.1f}kHz ({peak_mv:.1f}mV)")
