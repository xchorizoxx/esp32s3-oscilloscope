"""
status_bar.py — Barra de estado inferior.
"""

from PyQt6.QtWidgets import QStatusBar, QLabel
from PyQt6.QtCore import Qt

class AppStatusBar(QStatusBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Labels
        self.conn_label = QLabel("● DISCONNECTED")
        self.conn_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
        
        self.port_label = QLabel("")
        self.rate_label = QLabel("0 Hz")
        self.fps_label = QLabel("FPS: 0")
        self.overflow_label = QLabel("Overflow: 0")
        
        # Añadir a la barra
        self.addWidget(self.conn_label)
        self.addWidget(self.port_label)
        self.addWidget(self.rate_label)
        
        # A la derecha
        self.addPermanentWidget(self.fps_label)
        self.addPermanentWidget(self.overflow_label)

    def set_connected(self, connected: bool, port: str = ""):
        if connected:
            self.conn_label.setText("● CONNECTED")
            self.conn_label.setStyleSheet("color: #2ecc71; font-weight: bold;")
            self.port_label.setText(port)
        else:
            self.conn_label.setText("● DISCONNECTED")
            self.conn_label.setStyleSheet("color: #e74c3c; font-weight: bold;")
            self.port_label.setText("")
            self.rate_label.setText("0 Hz")

    def update_stats(self, fps: float, bytes_sec: float, overflow_count: int):
        self.fps_label.setText(f"FPS: {fps:.1f} ({bytes_sec/1024:.1f} KB/s)")
        self.overflow_label.setText(f"Overflow: {overflow_count}")
        if overflow_count > 0:
            self.overflow_label.setStyleSheet("color: #e74c3c;")
        else:
            self.overflow_label.setStyleSheet("")
            
    def update_rate(self, rate: int):
        if rate > 1000:
            self.rate_label.setText(f"{rate/1000:.1f} kHz")
        else:
            self.rate_label.setText(f"{rate} Hz")
