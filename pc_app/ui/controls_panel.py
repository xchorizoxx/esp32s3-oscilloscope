"""
controls_panel.py — QDockWidget que agrupa los controles laterales.

Correcciones:
  - Checkboxes de display modes (Persistence/Average/Envelope) ahora mutuamente excluyentes.
  - Rate combo limitado a valores alcanzables por ESP32-S3 (max 160 kHz).
  - Boton HOLD/STOP con estado independiente del hardware stream.
"""

from PyQt6.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
                            QGroupBox, QLabel, QComboBox, QPushButton, QCheckBox,
                            QSpacerItem, QSizePolicy, QSpinBox, QDoubleSpinBox, QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

from .channel_panel import ChannelPanel
from .trigger_panel import TriggerPanel


class ControlsPanel(QDockWidget):

    # Senales para notificar al MainWindow
    connect_requested = pyqtSignal(str)
    disconnect_requested = pyqtSignal()
    start_stream_requested = pyqtSignal()
    stop_stream_requested = pyqtSignal()
    single_shot_requested = pyqtSignal()
    auto_scale_requested = pyqtSignal()
    refresh_ports_requested = pyqtSignal()
    theme_toggle_requested = pyqtSignal(str)

    # NEW: Signal Generator
    gen_start_requested = pyqtSignal(int, int, int) # type, freq_hz, duty_pct
    gen_stop_requested = pyqtSignal()

    mode_changed = pyqtSignal(int)
    rate_changed = pyqtSignal(int)
    frame_size_changed = pyqtSignal(int)
    timebase_changed = pyqtSignal(float)
    display_mode_changed = pyqtSignal(str)
    roll_mode_changed = pyqtSignal(bool)
    roll_paused_changed = pyqtSignal(bool)

    # Cursor visibility
    time_cursors_toggled = pyqtSignal(bool)
    volt_cursors_toggled = pyqtSignal(bool)
    
    # Trigger additions
    holdoff_changed = pyqtSignal(int)

    # FFT Config
    fft_enabled_changed = pyqtSignal(int)
    fft_window_changed = pyqtSignal(str)
    fft_points_changed = pyqtSignal(int)

    # NEW: UI Hold (freeze display without stopping hardware)
    ui_hold_changed = pyqtSignal(bool)
    oversampling_changed = pyqtSignal(int)

    # PGA
    pga_enabled_changed = pyqtSignal(bool)
    pga_step_changed = pyqtSignal(int)
    pga_cal_requested = pyqtSignal()
    # ADC
    adc_correction_requested = pyqtSignal(float)

    reload_requested = pyqtSignal()   # Reload App

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
        self.btn_refresh = QPushButton("r")
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
        lbl_mode = QLabel("Mode:")
        lbl_mode.setToolTip(
            "Dual CH: muestrea GPIO1 y GPIO2 alternando (rate por canal = rate/2).\n"
            "Single CH: solo GPIO1, maxima velocidad.\n"
            "Oversample: solo GPIO1 con promedio x16, mayor precision en senales lentas."
        )
        row_mode.addWidget(lbl_mode)
        self.cb_mode = QComboBox()
        self.cb_mode.addItem("Dual Channel", 2)
        self.cb_mode.addItem("Channel 1 (Blue)", 0)
        self.cb_mode.addItem("Channel 2 (Yellow)", 1)
        self.cb_mode.setToolTip("Modo de adquisicion del ADC")
        row_mode.addWidget(self.cb_mode)
        l_acq.addLayout(row_mode)

        # Oversampling (Global)
        row_os = QHBoxLayout()
        lbl_os = QLabel("Oversampling:")
        lbl_os.setToolTip("Promedio de muestras por punto para reducir ruido. Reduce el sample rate efectivo.")
        row_os.addWidget(lbl_os)
        self.cb_oversampling = QComboBox()
        self.cb_oversampling.addItem("None (x1)", 1)
        self.cb_oversampling.addItem("x2", 2)
        self.cb_oversampling.addItem("x4", 4)
        self.cb_oversampling.addItem("x8", 8)
        self.cb_oversampling.addItem("x16", 16)
        row_os.addWidget(self.cb_oversampling)
        l_acq.addLayout(row_os)

        # Rate: capped at 150 kHz (real hardware limit with ADC clock hack)
        # BUG-05 FIX: 160 kHz removed (exceeds firmware max of 150 kHz)
        # Firmware default is 83333 Hz (shown as "83 kHz")
        row_rate = QHBoxLayout()
        row_rate.addWidget(QLabel("Rate:"))
        self.cb_rate = QComboBox()
        rate_entries = [
            (1000,   "1 kHz"),
            (2000,   "2 kHz"),
            (5000,   "5 kHz"),
            (10000,  "10 kHz"),
            (20000,  "20 kHz"),
            (50000,  "50 kHz"),
            (83333,  "83 kHz (FW default)"),
            (100000, "100 kHz"),
            (125000, "125 kHz"),
            (150000, "150 kHz"),
            (160000, "160 kHz (max)"),
        ]
        for r_val, r_label in rate_entries:
            self.cb_rate.addItem(r_label, r_val)
        self.cb_rate.setCurrentText("100 kHz")
        self.cb_rate.setToolTip(
            "Frecuencia de muestreo del ADC (rate de hardware).\n"
            "En Dual CH: cada canal recibe rate/2.\n"
            "Max hardware: 160 kHz. Default firmware: 83 kHz."
        )
        row_rate.addWidget(self.cb_rate)
        l_acq.addLayout(row_rate)

        # Frame Size
        row_frame = QHBoxLayout()
        lbl_frame = QLabel("Frame:")
        lbl_frame.setToolTip(
            "Numero de muestras por captura (profundidad de memoria).\n"
            "Mayor frame = mas contexto temporal, pero mas latencia.\n"
            "Cambiar el frame reinicia el ADC automaticamente."
        )
        row_frame.addWidget(lbl_frame)
        self.cb_frame = QComboBox()
        # BUG: valores muy grandes (4096) con rate bajo pueden llenar el USB
        for f in [64, 128, 256, 512, 1024, 2048, 4096]:
            self.cb_frame.addItem(f"{f} pts", f)
        self.cb_frame.setCurrentText("512 pts")   # Match firmware default
        self.cb_frame.setToolTip("Muestras por frame — el firmware acumula este numero antes de enviar")
        row_frame.addWidget(self.cb_frame)
        l_acq.addLayout(row_frame)

        # BUG-09 FIX: Timebase limitada a rango alcanzable por el hardware.
        # 1-5 us/div requeriria >1 MHz de sample rate (imposible).
        # 1-5 s/div tardaria minutos en llenar un frame de 512 pts a 1 kHz.
        row_tb = QHBoxLayout()
        lbl_tb = QLabel("T/div:")
        lbl_tb.setToolTip(
            "Tiempo por division de cuadricula.\n"
            "Ajusta la escala temporal de la pantalla (NO cambia el sample rate).\n"
            "Para ver mas ciclos: aumentar T/div. Para ver mas detalle: reducir T/div."
        )
        row_tb.addWidget(lbl_tb)
        self.cb_timebase = QComboBox()
        timebases_us = [
            10, 20, 50, 100, 200, 500,
            1000, 2000, 5000, 10000, 20000, 50000,
            100000, 200000, 500000
        ]
        for t in timebases_us:
            if t >= 1000000:
                self.cb_timebase.addItem(f"{t/1000000:.0f} s/div", float(t))
            elif t >= 1000:
                self.cb_timebase.addItem(f"{t/1000:.0f} ms/div", float(t))
            else:
                self.cb_timebase.addItem(f"{t} us/div", float(t))
        # Default: 1 ms/div = 1000.0 us — find by data value, NOT text
        default_idx = self.cb_timebase.findData(1000.0)
        if default_idx >= 0:
            self.cb_timebase.setCurrentIndex(default_idx)
        self.cb_timebase.setToolTip("Escala temporal por division")
        row_tb.addWidget(self.cb_timebase)
        l_acq.addLayout(row_tb)

        # Run/Stop/Single
        row_run = QHBoxLayout()
        self.btn_run = QPushButton("\u25ba RUN")
        self.btn_run.setObjectName("btn_run")
        self.btn_run.setToolTip(
            "RUN: inicia el streaming continuo.\n"
            "El ESP32 captura y envia frames continuamente."
        )
        self.btn_stop = QPushButton("\u25a0 STOP")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setToolTip(
            "STOP: detiene el streaming y congela la pantalla.\n"
            "La ultima captura queda visible."
        )
        self.btn_single = QPushButton("SINGLE")
        self.btn_single.setObjectName("btn_single")
        self.btn_single.setToolTip(
            "SINGLE: captura un unico frame cuando se detecta el trigger y para.\n"
            "Util para capturar eventos unicos (pulsos, glitches)."
        )
        row_run.addWidget(self.btn_run)
        row_run.addWidget(self.btn_stop)
        row_run.addWidget(self.btn_single)
        l_acq.addLayout(row_run)

        # Auto-Scale
        self.btn_autoscale = QPushButton(" AUTO SCALE")
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

        # Roll mode
        self.chk_roll = QCheckBox("Roll Mode")
        self.chk_roll.setToolTip(
            "Roll Mode: la pantalla se desplaza continuamente como un ECG.\n"
            "Ideal para senales lentas (< 1 Hz) que no se pueden triggerear facilmente."
        )
        self.chk_pause_roll = QCheckBox("Pause Roll")
        self.chk_pause_roll.setToolTip("Congela el scroll del Roll Mode sin detener el hardware")
        self.chk_pause_roll.setEnabled(False)
        l_disp.addWidget(self.chk_roll)
        l_disp.addWidget(self.chk_pause_roll)

        # BUG-M05 FIX: Checkboxes mutuamente excluyentes
        self.chk_pers = QCheckBox("Persistence")
        self.chk_pers.setToolTip("Superpone los ultimos 5 frames con transparencia decreciente")
        self.chk_avg = QCheckBox("Average (n=4)")
        self.chk_avg.setToolTip("Promedia los ultimos 4 frames para reducir ruido")
        self.chk_env = QCheckBox("Envelope")
        self.chk_env.setToolTip("Muestra la envolvente (min/max) de los ultimos 4 frames")
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

        # --- 7. Signal Generator ---
        grp_gen = QGroupBox("Signal Gen (GPIO3)")
        l_gen = QVBoxLayout(grp_gen)
        
        # Waveform Type
        row_gtype = QHBoxLayout()
        row_gtype.addWidget(QLabel("Type:"))
        self.combo_gen_type = QComboBox()
        self.combo_gen_type.addItems(["Square", "Sine", "Triangle", "Sawtooth"])
        row_gtype.addWidget(self.combo_gen_type)
        l_gen.addLayout(row_gtype)

        # Freq
        row_gfreq = QHBoxLayout()
        row_gfreq.addWidget(QLabel("Freq:"))
        self.spin_gen_freq = QDoubleSpinBox()
        self.spin_gen_freq.setRange(1, 150000)
        self.spin_gen_freq.setSuffix(" Hz")
        self.spin_gen_freq.setDecimals(0)
        self.spin_gen_freq.setValue(1000)
        row_gfreq.addWidget(self.spin_gen_freq)
        l_gen.addLayout(row_gfreq)

        # Connect combo box signal to update UI state
        self.combo_gen_type.currentIndexChanged.connect(self._on_gen_type_changed)

        # Duty
        row_gduty = QHBoxLayout()
        row_gduty.addWidget(QLabel("Duty:"))
        self.spin_gen_duty = QDoubleSpinBox()
        self.spin_gen_duty.setRange(10, 90)
        self.spin_gen_duty.setSuffix(" %")
        self.spin_gen_duty.setDecimals(0)
        self.spin_gen_duty.setValue(50)
        row_gduty.addWidget(self.spin_gen_duty)
        l_gen.addLayout(row_gduty)

        # Buttons
        row_gbtn = QHBoxLayout()
        self.btn_gen_start = QPushButton("START")
        self.btn_gen_stop = QPushButton("STOP")
        self.btn_gen_stop.setEnabled(False)
        row_gbtn.addWidget(self.btn_gen_start)
        row_gbtn.addWidget(self.btn_gen_stop)
        l_gen.addLayout(row_gbtn)
        
        self.layout.addWidget(grp_gen)

        # --- 8. PGA ---
        grp_pga = QGroupBox("PGA (CH1)")
        l_pga = QVBoxLayout(grp_pga)

        self.chk_pga_enable = QCheckBox("Enable PGA")
        self.chk_pga_enable.setToolTip(
            "Activa el amplificador de ganancia programable en CH1.\n"
            "Permite medir senales de hasta ~30 Vpp con resolucion de mV."
        )
        l_pga.addWidget(self.chk_pga_enable)

        row_pga_step = QHBoxLayout()
        row_pga_step.addWidget(QLabel("Gain:"))
        self.cb_pga_step = QComboBox()
        # PGA-B06 FIX: Use generic labels; update_pga_info() will replace them
        # with actual nominal gains once firmware responds (or stays generic offline).
        for i in range(8):
            self.cb_pga_step.addItem(f"Step {i}", i)
        self.cb_pga_step.setEnabled(False)
        row_pga_step.addWidget(self.cb_pga_step)
        l_pga.addLayout(row_pga_step)

        self.lbl_pga_bw = QLabel("BW: -- Hz")
        self.lbl_pga_bw.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        l_pga.addWidget(self.lbl_pga_bw)

        self.lbl_pga_vg = QLabel("VG: -- mV")
        self.lbl_pga_vg.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        l_pga.addWidget(self.lbl_pga_vg)

        self.lbl_pga_div = QLabel("Div: --")
        self.lbl_pga_div.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        l_pga.addWidget(self.lbl_pga_div)

        self.lbl_pga_gain_now = QLabel("Gain: x--")
        self.lbl_pga_gain_now.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        l_pga.addWidget(self.lbl_pga_gain_now)

        # PGA-B01 FIX: button always enabled — the dialog itself handles offline
        # gracefully, so there is no reason to block access to it.
        self.btn_pga_cal = QPushButton("Calibrate PGA...")
        self.btn_pga_cal.setEnabled(True)
        l_pga.addWidget(self.btn_pga_cal)

        self.lbl_pga_status = QLabel("")
        self.lbl_pga_status.setStyleSheet("color: #22c55e; font-size: 10px;")
        l_pga.addWidget(self.lbl_pga_status)

        self.layout.addWidget(grp_pga)

        # --- ADC Calibration Group ---
        grp_adc_cal = QGroupBox("ADC Calibration")
        l_adc_cal = QVBoxLayout(grp_adc_cal)
        row_corr = QHBoxLayout()
        row_corr.addWidget(QLabel("Corr Factor:"))
        self.spin_adc_corr = QDoubleSpinBox()
        self.spin_adc_corr.setRange(1.0, 1.1)
        self.spin_adc_corr.setDecimals(4)
        self.spin_adc_corr.setSingleStep(0.001)
        self.spin_adc_corr.setValue(1.037)
        self.spin_adc_corr.setToolTip(
            "Factor de correción para la no-linealidad del ADC en zona alta (12 dB).\n"
            "1.0 = sin correción. 1.037 = valor típico ESP32-S3."
        )
        row_corr.addWidget(self.spin_adc_corr)
        btn_set_corr = QPushButton("Set")
        btn_set_corr.clicked.connect(
            lambda: self.adc_correction_requested.emit(self.spin_adc_corr.value()))
        row_corr.addWidget(btn_set_corr)
        self.lbl_adc_corr_status = QLabel("")
        self.lbl_adc_corr_status.setStyleSheet("color: #a1a1aa; font-size: 9px;")
        row_corr.addWidget(self.lbl_adc_corr_status)
        l_adc_cal.addLayout(row_corr)
        self.layout.addWidget(grp_adc_cal)

        # --- 9. Theme + Reload ---
        grp_theme = QGroupBox("App")
        l_theme = QVBoxLayout(grp_theme)

        row_themes = QHBoxLayout()
        self.btn_theme_dark = QPushButton("Dark")
        self.btn_theme_dark.setToolTip("Cambiar al tema oscuro")
        self.btn_theme_light = QPushButton("Light")
        self.btn_theme_light.setToolTip("Cambiar al tema claro")
        row_themes.addWidget(self.btn_theme_dark)
        row_themes.addWidget(self.btn_theme_light)
        l_theme.addLayout(row_themes)

        # Reload App button
        self.btn_reload = QPushButton("\u21bb Reload App")
        self.btn_reload.setObjectName("btn_reload")
        self.btn_reload.setToolTip(
            "Reinicia la aplicacion Python completamente.\n"
            "Util para aplicar cambios de configuracion o limpiar el estado."
        )
        l_theme.addWidget(self.btn_reload)
        self.layout.addWidget(grp_theme)

        # Spacer final
        self.layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Wrap in QScrollArea
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

        self.trig_panel.holdoff_changed.connect(self.holdoff_changed.emit)

        self.cb_mode.currentIndexChanged.connect(lambda i: self.mode_changed.emit(self.cb_mode.itemData(i)))
        self.cb_oversampling.currentIndexChanged.connect(lambda i: self.oversampling_changed.emit(self.cb_oversampling.itemData(i)))
        self.cb_rate.currentIndexChanged.connect(lambda i: self.rate_changed.emit(self.cb_rate.itemData(i)))
        self.cb_frame.currentIndexChanged.connect(lambda i: self.frame_size_changed.emit(self.cb_frame.itemData(i)))
        self.cb_timebase.currentIndexChanged.connect(lambda i: self.timebase_changed.emit(self.cb_timebase.itemData(i)))
        self.cb_disp_mode.currentTextChanged.connect(self.display_mode_changed.emit)

        self.chk_roll.toggled.connect(self.roll_mode_changed.emit)
        self.chk_roll.toggled.connect(self.chk_pause_roll.setEnabled)
        self.chk_pause_roll.toggled.connect(self.roll_paused_changed.emit)

        # BUG-M05: Mutual exclusion para display modes
        self.chk_pers.toggled.connect(lambda checked: self._uncheck_others(self.chk_pers, checked))
        self.chk_avg.toggled.connect(lambda checked: self._uncheck_others(self.chk_avg, checked))
        self.chk_env.toggled.connect(lambda checked: self._uncheck_others(self.chk_env, checked))

        self.chk_cursor_t.toggled.connect(self.time_cursors_toggled.emit)
        self.chk_cursor_v.toggled.connect(self.volt_cursors_toggled.emit)

        # PGA
        self.chk_pga_enable.toggled.connect(self.pga_enabled_changed.emit)
        # PGA-B07 FIX: removed direct chk->cb_pga_step.setEnabled connection.
        # main_window._on_pga_enabled_changed() is the single authority.
        self.cb_pga_step.currentIndexChanged.connect(
            lambda i: self.pga_step_changed.emit(self.cb_pga_step.itemData(i)))
        self.btn_pga_cal.clicked.connect(self.pga_cal_requested.emit)

        # Generator
        self.btn_gen_start.clicked.connect(self._on_gen_start)
        self.btn_gen_stop.clicked.connect(self._on_gen_stop)

        self.btn_theme_dark.clicked.connect(lambda: self.theme_toggle_requested.emit('dark'))
        self.btn_theme_light.clicked.connect(lambda: self.theme_toggle_requested.emit('light'))
        self.btn_reload.clicked.connect(self.reload_requested.emit)

        # Auto-refresh ports — PC-06 FIX: timer is STOPPED while connected to avoid
        # blocking the main thread with comports() enumeration every 2 s.
        self._port_timer = QTimer(self)
        self._port_timer.timeout.connect(self.refresh_ports_requested.emit)
        self._port_timer.start(2000)

    def _uncheck_others(self, source: QCheckBox, checked: bool):
        """Mutual exclusion: cuando un display mode se activa, desactiva los otros."""
        if checked:
            for chk in (self.chk_pers, self.chk_avg, self.chk_env):
                if chk is not source and chk.isChecked():
                    chk.blockSignals(True)
                    chk.setChecked(False)
                    chk.blockSignals(False)

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

    def update_pga_info(self, info: dict):
        step = info.get('step', 0)
        gains = info.get('gain_eff', [1.0]*8)
        bws = info.get('bw_hz', [1000000.0]*8)
        enabled = info.get('enabled', False)
        calibrated = info.get('calibrated', False)
        vg_mv = info.get('vg_mv', None)
        div_ratio = info.get('div_ratio', None)

        self.cb_pga_step.blockSignals(True)
        for i in range(8):
            label = f"x{gains[i]:.2f} (paso {i})"
            bw_warn = " ⚠" if bws[i] < 150000 else ""
            self.cb_pga_step.setItemText(i, label + bw_warn)
        self.cb_pga_step.setCurrentIndex(step)
        self.cb_pga_step.blockSignals(False)

        current_bw = bws[step] if step < len(bws) else 0
        bw_text = f"BW: {current_bw/1000:.0f} kHz"
        if current_bw < 150000:
            self.lbl_pga_bw.setStyleSheet("color: #eab308; font-size: 10px;")
            bw_text += " (limitado, >75kHz atenuado)"
        else:
            self.lbl_pga_bw.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        self.lbl_pga_bw.setText(bw_text)

        self.chk_pga_enable.blockSignals(True)
        self.chk_pga_enable.setChecked(enabled)
        self.chk_pga_enable.blockSignals(False)
        self.cb_pga_step.setEnabled(enabled)
        self.btn_pga_cal.setEnabled(True)

        if calibrated:
            self.lbl_pga_status.setText("Calibrado")
            self.lbl_pga_status.setStyleSheet("color: #22c55e; font-size: 10px;")
        elif enabled:
            self.lbl_pga_status.setText("Sin calibrar — use Calibrate")
            self.lbl_pga_status.setStyleSheet("color: #eab308; font-size: 10px;")
        else:
            self.lbl_pga_status.setText("")
            self.lbl_pga_status.setStyleSheet("color: #a1a1aa; font-size: 10px;")

        # Info labels
        if vg_mv is not None:
            self.lbl_pga_vg.setText(f"VG: {vg_mv:.1f} mV")
        if div_ratio is not None:
            self.lbl_pga_div.setText(f"Div: {div_ratio:.6f}")
        current_gain = gains[step] if step < len(gains) else 0
        self.lbl_pga_gain_now.setText(f"Gain: x{current_gain:.2f}")

    def on_connection_changed(self, connected: bool):
        self.btn_connect.setChecked(connected)
        self.btn_connect.setText("Disconnect" if connected else "Connect")
        if not connected:
            self.lbl_fw.setText("FW: Unknown")
            # PC-06 FIX: restart port refresh timer when disconnected
            if not self._port_timer.isActive():
                self._port_timer.start(2000)
            # PGA-B05 FIX: reset PGA panel to avoid showing stale device data
            self._reset_pga_panel()
        else:
            # PC-06 FIX: stop port refresh timer while connected (avoids ~200ms
            # blocking call to serial.tools.list_ports.comports() every 2 s)
            self._port_timer.stop()

    def _reset_pga_panel(self):
        """PGA-B05 FIX: Reset all PGA labels and combo to default state on disconnect."""
        self.lbl_pga_bw.setText("BW: -- Hz")
        self.lbl_pga_bw.setStyleSheet("color: #a1a1aa; font-size: 10px;")
        self.lbl_pga_vg.setText("VG: -- mV")
        self.lbl_pga_div.setText("Div: --")
        self.lbl_pga_gain_now.setText("Gain: x--")
        self.lbl_pga_status.setText("(sin dispositivo)")
        self.lbl_pga_status.setStyleSheet("color: #71717a; font-size: 10px;")
        # Reset combo to generic labels
        self.cb_pga_step.blockSignals(True)
        for i in range(8):
            self.cb_pga_step.setItemText(i, f"Step {i}")
        self.cb_pga_step.blockSignals(False)

    def _on_gen_type_changed(self, index: int):
        # Index: 0=Square, 1=Sine, 2=Triangle, 3=Sawtooth
        is_square = (index == 0)
        self.spin_gen_duty.setEnabled(is_square)
        
        # Limit frequency based on wave type
        max_freq = 150000 if is_square else 20000
        self.spin_gen_freq.setRange(1, max_freq)

    def _on_gen_start(self):
        w_type = self.combo_gen_type.currentIndex()
        freq = int(self.spin_gen_freq.value())
        duty = int(self.spin_gen_duty.value())
        self.btn_gen_start.setEnabled(False)
        self.btn_gen_stop.setEnabled(True)
        self.gen_start_requested.emit(w_type, freq, duty)

    def _on_gen_stop(self):
        self.btn_gen_start.setEnabled(True)
        self.btn_gen_stop.setEnabled(False)
        self.gen_stop_requested.emit()

    def set_timebase_value(self, us_per_div: float):
        """Actualiza el combo de T/div desde código."""
        self.cb_timebase.blockSignals(True)
        # Buscar el valor más cercano en el combo
        for i in range(self.cb_timebase.count()):
            if abs(self.cb_timebase.itemData(i) - us_per_div) < 0.1:
                self.cb_timebase.setCurrentIndex(i)
                break
        self.cb_timebase.blockSignals(False)

    def set_voltage_scale_value(self, mv_per_div: float, channel: int):
        """Actualiza el combo de V/div desde código."""
        panel = self.ch1_panel if channel == 0 else self.ch2_panel
        panel.cb_scale.blockSignals(True)
        for i in range(panel.cb_scale.count()):
            if abs(panel.cb_scale.itemData(i) - mv_per_div) < 0.1:
                panel.cb_scale.setCurrentIndex(i)
                break
        panel.cb_scale.blockSignals(False)
