"""
xy_widget.py — Widget de modo XY (Lissajous).
"""

import pyqtgraph as pg
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout

class XYWidget(QWidget):
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        pg.setConfigOptions(antialias=True, useOpenGL=True)
        
        self.plot_widget = pg.PlotWidget(title="XY Mode (Lissajous)")
        self.plot_widget.setBackground('#111')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setAspectLocked(True) # Relación de aspecto 1:1
        
        # Traza XY (ScatterPlot o Curve)
        self.curve = self.plot_item.plot(pen=None, symbol='o', symbolSize=3, symbolBrush='#3498db')
        
        layout.addWidget(self.plot_widget)
        
        self.plot_item.setLabel('bottom', "CH1 (mV)")
        self.plot_item.setLabel('left', "CH2 (mV)")
        self.plot_item.setXRange(-3300, 3300)
        self.plot_item.setYRange(-3300, 3300)

    def update_xy(self, ch1_mv: np.ndarray, ch2_mv: np.ndarray):
        if ch1_mv is None or ch2_mv is None:
            return
            
        # Asegurar mismo tamaño
        min_len = min(len(ch1_mv), len(ch2_mv))
        if min_len == 0:
            return
            
        self.curve.setData(x=ch1_mv[:min_len], y=ch2_mv[:min_len])
