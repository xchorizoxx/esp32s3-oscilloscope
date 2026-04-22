"""
controls_panel.py — QDockWidget que agrupa los controles laterales.
"""

from PyQt6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
                            QGroupBox, QLabel, QComboBox, QPushButton, QCheckBox,
                            QSpacerItem, QSizePolicy, QSpinBox, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from .channel_panel import ChannelPanel
from .trigger_panel import TriggerPanel

class ControlsPanel(QDockWidget):

    # Señales para notificar al MainWindow
    connect_requested = pyqtSignal(str)
    disconnect_requested = pyqtSignal()
    start_stream_requested = pyqtSignal()
    stop_stream_requested = pyqtSignal()
    single_shot_requested = pyqtSignal()
    auto_scale_requested = pyqtSignal()
    refresh_ports_requested = pyqtSignal()
    theme_toggle_requested = pyqtSignal(str)  # 'dark' or 'light'

    mode_changed = pyqtSignal(int)          # 0=single, 1=dual, 2=oversample
    rate_changed = pyqtSignal(int)
    frame_size_changed = pyqtSignal(int)
    timebase_changed = pyqtSignal(float)    # us/div
    display_mode_changed = pyqtSignal(str)  # YT, XY, FFT, YT+FFT
    roll_mode_changed = pyqtSignal(bool)
    roll_paused_changed = pyqtSignal(bool)

    # Cursor visibility
    time_cursors_toggled = pyqtSignal(bool)
    volt_cursors_toggled = pyqtSignal(bool)

    # FFT Config
    fft_enabled_changed = pyqtSignal(int)
    fft_window_changed = pyqtSignal(str)
    fft_points_changed = pyqtSignal(int)

    def __init__(self, title="Controls", parent=None):
        super().__init__(title, parent)
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetFloatable | QDockWidget.DockWidgetFeature.DockWidgetMovable)

        # Main widget
        self.main_w = QWidget()
        self.layout = QVBoxLayout(self.main_w)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(6)

        # --- 1. Device Connection ---
        grp_dev = QGroupBox("Device")
        l_dev = QVBoxLayout(grp_dev)

        row_ports = QHBoxLayout()
        self.cb_ports = QComboBox()
        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setFixedWidth(30)
        self.btn_refresh.setToolTip("Refresh serial ports")
        row_ports.addWidget(self.cb_ports)
        row_ports.addWidget(self.btn_refresh)
        l_dev.addLayout(row_ports)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setCheckable(True)
        l_dev.addWidget(self.btn_connect)

        self.lbl_fw = QLabel("FW: Unknown")
        self.lbl_fw.setStyleSheet("color: #71717a; font-size: 10px;")
        l_dev.addWidget(self.lbl_fw)

        self.layout.addWidget(grp_dev)

        # --- 2. Acquisition & Timebase ---
        grp_acq = QGroupBox("Acquisition")
        l_acq = QVBoxLayout(grp_acq)

        # Mode
        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("Mode:"))
        self.cb_mode = QComboBox()
        self.cb_mode.addItem("Dual CH", 1)
        self.cb_mode.addItem("Single CH", 0)
        self.cb_mode.addItem("Oversample", 2)
        row_mode.addWidget(self.cb_mode)
        l_acq.addLayout(row_mode)

        # Rate
        row_rate = QHBoxLayout()
        row_rate.addWidget(QLabel("Rate:"))
        self.cb_rate = QComboBox()
        rates = [1000, 2000, 5000, 10000, 20000, 50000, 100000, 125000, 160000, 320000, 640000]
        for r in rates:
            if r >= 1000:
                self.cb_rate.addItem(f"{r//1000} kHz", r)
            else:
                self.cb_rate.addItem(f"{r} Hz", r)
        self.cb_rate.setCurrentText("100 kHz")
        row_rate.addWidget(self.cb_rate)
        l_acq.addLayout(row_rate)

        # Frame Size
        row_frame = QHBoxLayout()
        row_frame.addWidget(QLabel("Frame:"))
        self.cb_frame = QComboBox()
        for f in [64, 128, 256, 512, 1024, 2048, 4096]:
            self.cb_frame.addItem(f"{f} pts", f)
        self.cb_frame.setCurrentText("1024 pts")
        row_frame.addWidget(self.cb_frame)
        l_acq.addLayout(row_frame)

        # Timebase (us/div)
        row_tb = QHBoxLayout()
        row_tb.addWidget(QLabel("T/div:"))
        self.cb_timebase = QComboBox()
        timebases_us = [
            1, 2, 5, 10, 20, 50, 100, 200, 500,
            1000, 2000, 5000, 10000, 20000, 50000,
            100000, 200000, 500000, 1000000, 2000000, 5000000
        ]
        for t in timebases_us:
            if t >= 1000000:
                self.cb_timebase.addItem(f"{t/1000000:.1f} s", float(t))
            elif t >= 1000:
                self.cb_timebase.addItem(f"{t/1000:.1f} ms", float(t))
            else:
                self.cb_timebase.addItem(f"{t} µs", float(t))
        self.cb_timebase.setCurrentIndex(12)  # 10ms default
        row_tb.addWidget(self.cb_timebase)
        l_acq.addLayout(row_tb)

        # Run/Stop/Single
        row_run = QHBoxLayout()
        self.btn_run = QPushButton("RUN")
        self.btn_run.setObjectName("btn_run")
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_single = QPushButton("SINGLE")
        self.btn_single.setObjectName("btn_single")
        row_run.addWidget(self.btn_run)
        row_run.addWidget(self.btn_stop)
        row_run.addWidget(self.btn_single)
        l_acq.addLayout(row_run)

        # Auto-Scale
        self.btn_autoscale = QPushButton("⟲ AUTO SCALE")
        self.btn_autoscale.setObjectName("btn_autoscale")
        self.btn_autoscale.setToolTip("Auto-fit voltage scale and timebase to the current signal")
        l_acq.addWidget(self.btn_autoscale)

        self.layout.addWidget(grp_acq)

        # --- 3. Channels ---
        self.ch1_panel = ChannelPanel("CH1 (GPIO1)", "#22d3ee")
        grp_ch1 = QGroupBox("")
        l1 = QVBoxLayout(grp_ch1); l1.setContentsMargins(0, 0, 0, 0)
        l1.addWidget(self.ch1_panel)
        self.layout.addWidget(grp_ch1)

        self.ch2_panel = ChannelPanel("CH2 (GPIO2)", "#facc15")
        grp_ch2 = QGroupBox("")
        l2 = QVBoxLayout(grp_ch2); l2.setContentsMargins(0, 0, 0, 0)
        l2.addWidget(self.ch2_panel)
        self.layout.addWidget(grp_ch2)

        # --- 4. Trigger ---
        self.trig_panel = TriggerPanel()
        grp_trig = QGroupBox("Trigger")
        lt = QVBoxLayout(grp_trig); lt.setContentsMargins(0, 0, 0, 0)
        lt.addWidget(self.trig_panel)
        self.layout.addWidget(grp_trig)

        # --- 5. Display ---
        grp_disp = QGroupBox("Display")
        l_disp = QVBoxLayout(grp_disp)

        row_dmode = QHBoxLayout()
        row_dmode.addWidget(QLabel("Mode:"))
        self.cb_disp_mode = QComboBox()
        self.cb_disp_mode.addItems(["YT", "XY", "FFT", "YT+FFT"])
        row_dmode.addWidget(self.cb_disp_mode)
        l_disp.addLayout(row_dmode)

        # Modos visuales extra
        self.chk_roll = QCheckBox("Roll Mode (Continuous)")
        self.chk_pause_roll = QCheckBox("Pause Roll")
        self.chk_pause_roll.setEnabled(False)  # Only enabled if Roll Mode is checked
        self.chk_pers = QCheckBox("Persistence")
        self.chk_avg = QCheckBox("Average (n=4)")
        self.chk_env = QCheckBox("Envelope")
        l_disp.addWidget(self.chk_roll)
        l_disp.addWidget(self.chk_pause_roll)
        l_disp.addWidget(self.chk_pers)
        l_disp.addWidget(self.chk_avg)
        l_disp.addWidget(self.chk_env)

        self.layout.addWidget(grp_disp)

        # --- 6. Cursors ---
        grp_cursor = QGroupBox("Cursors")
        l_cur = QVBoxLayout(grp_cursor)
        self.chk_cursor_t = QCheckBox("Time cursors (T1/T2)")
        self.chk_cursor_v = QCheckBox("Voltage cursors (V1/V2)")
        l_cur.addWidget(self.chk_cursor_t)
        l_cur.addWidget(self.chk_cursor_v)
        self.layout.addWidget(grp_cursor)

        # --- 7. Theme ---
        grp_theme = QGroupBox("Theme")
        l_theme = QHBoxLayout(grp_theme)
        self.btn_theme_dark = QPushButton("Dark")
        self.btn_theme_light = QPushButton("Light")
        l_theme.addWidget(self.btn_theme_dark)
        l_theme.addWidget(self.btn_theme_light)
        self.layout.addWidget(grp_theme)

        # Spacer final
        self.layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Wrap everything in a QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.main_w)
        self.setWidget(scroll)

        # --- Conexiones ---
        self.btn_connect.clicked.connect(self._on_connect_clicked)
        self.btn_refresh.clicked.connect(self.refresh_ports_requested.emit)
        self.btn_run.clicked.connect(self.start_stream_requested.emit)
        self.btn_stop.clicked.connect(self.stop_stream_requested.emit)
        self.btn_single.clicked.connect(self.single_shot_requested.emit)
        self.btn_autoscale.clicked.connect(self.auto_scale_requested.emit)

        self.cb_mode.currentIndexChanged.connect(lambda i: self.mode_changed.emit(self.cb_mode.itemData(i)))
        self.cb_rate.currentIndexChanged.connect(lambda i: self.rate_changed.emit(self.cb_rate.itemData(i)))
        self.cb_frame.currentIndexChanged.connect(lambda i: self.frame_size_changed.emit(self.cb_frame.itemData(i)))
        self.cb_timebase.currentIndexChanged.connect(lambda i: self.timebase_changed.emit(self.cb_timebase.itemData(i)))
        self.cb_disp_mode.currentTextChanged.connect(self.display_mode_changed.emit)

        self.chk_roll.toggled.connect(self.roll_mode_changed.emit)
        self.chk_roll.toggled.connect(self.chk_pause_roll.setEnabled)
        self.chk_pause_roll.toggled.connect(self.roll_paused_changed.emit)

        self.chk_cursor_t.toggled.connect(self.time_cursors_toggled.emit)
        self.chk_cursor_v.toggled.connect(self.volt_cursors_toggled.emit)

        self.btn_theme_dark.clicked.connect(lambda: self.theme_toggle_requested.emit('dark'))
        self.btn_theme_light.clicked.connect(lambda: self.theme_toggle_requested.emit('light'))

        # Auto-refresh ports timer
        self._port_timer = QTimer(self)
        self._port_timer.timeout.connect(self.refresh_ports_requested.emit)
        self._port_timer.start(2000)

    def _on_connect_clicked(self, checked: bool):
        if checked:
            port = self.cb_ports.currentText()
            if port:
                self.connect_requested.emit(port)
            else:
                self.btn_connect.setChecked(False)
        else:
            self.disconnect_requested.emit()

    def update_device_info(self, info: dict):
        fw = info.get('fw_version', 'Unknown')
        rate = info.get('max_rate_hz', 0)
        self.lbl_fw.setText(f"FW: {fw} (Max {rate//1000}kHz)")

    def on_connection_changed(self, connected: bool):
        self.btn_connect.setChecked(connected)
        self.btn_connect.setText("Disconnect" if connected else "Connect")
        if not connected:
            self.lbl_fw.setText("FW: Unknown")
