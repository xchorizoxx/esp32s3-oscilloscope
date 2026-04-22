"""
fft_widget.py — Widget de espectro FFT con PyQtGraph.
"""

import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout

class FFTWidget(QWidget):
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        pg.setConfigOptions(antialias=True, useOpenGL=True)
        
        self.plot_widget = pg.PlotWidget(title="FFT Spectrum")
        self.plot_widget.setBackground('#111')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_item = self.plot_widget.getPlotItem()
        
        # Trazas
        self.curve_ch1 = self.plot_item.plot(pen=pg.mkPen('#2ecc71', width=1.5))
        self.curve_ch2 = self.plot_item.plot(pen=pg.mkPen('#f1c40f', width=1.5))
        
        # Peak labels
        self.peak_label_ch1 = pg.TextItem(color='#2ecc71', anchor=(0, 1))
        self.peak_label_ch2 = pg.TextItem(color='#f1c40f', anchor=(0, 1))
        self.plot_item.addItem(self.peak_label_ch1)
        self.plot_item.addItem(self.peak_label_ch2)
        
        layout.addWidget(self.plot_widget)
        
        self.ch1_visible = True
        self.ch2_visible = True
        self.y_mode = 'dbv' # 'dbv' o 'mv'
        
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

    def set_y_mode(self, mode: str):
        self.y_mode = mode.lower()
        if self.y_mode == 'dbv':
            self.plot_item.setLabel('left', "Magnitude (dBV)")
            self.plot_item.setYRange(-100, 20)
        else:
            self.plot_item.setLabel('left', "Magnitude (mV)")
            self.plot_item.autoRange()

    def update_fft(self, ch: int, freqs: np.ndarray, magnitudes_mv: np.ndarray, magnitudes_db: np.ndarray, peak_freq: float, peak_mv: float):
        if ch == 0 and not self.ch1_visible: return
        if ch == 1 and not self.ch2_visible: return
        
        mags = magnitudes_db if self.y_mode == 'dbv' else magnitudes_mv
        curve = self.curve_ch1 if ch == 0 else self.curve_ch2
        label = self.peak_label_ch1 if ch == 0 else self.peak_label_ch2
        
        curve.setData(freqs, mags)
        
        # Position label at peak
        if len(freqs) > 0 and len(mags) > 0:
            peak_val = mags.max()
            label.setPos(peak_freq, peak_val)
            label.setText(f"Peak: {peak_freq/1000:.1f}kHz ({peak_mv:.1f}mV)")
