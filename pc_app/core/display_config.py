"""
display_config.py — Single source of truth for all display-related state.

Centralizes configuration that was previously scattered across
ControlsPanel, WaveformWidget, and MainWindow. Uses Qt signals
for observable changes so any component can react.
"""

from dataclasses import dataclass, field
from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class ChannelConfig:
    """Per-channel display configuration."""
    visible: bool = True
    scale_mv: float = 1000.0    # V/div in mV
    offset_mv: float = 0.0
    coupling: str = 'DC'        # 'DC' or 'AC'
    pga_gain: float = 1.0
    atten_idx: int = 0


class DisplayConfig(QObject):
    """
    Observable display configuration container.

    Emits `changed` signal whenever any property is modified,
    allowing all UI components to stay in sync.
    """
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Channel configs
        self.ch0 = ChannelConfig()
        self.ch1 = ChannelConfig()

        # Timebase
        self.timebase_us: float = 1000.0    # T/div in µs

        # Acquisition
        self.sample_rate: int = 100000      # Hz
        self.frame_size: int = 1024
        self.oversampling: int = 1
        self.mode: int = 2                  # 0=CH1, 1=CH2, 2=Dual

        # Display modes
        self.display_mode: str = 'normal'   # 'normal', 'average', 'envelope', 'persistence'
        self.roll_mode: bool = False

        # Trigger
        self.trigger_level_mv: float = 0.0
        self.trigger_channel: int = 0
        self.trigger_holdoff_us: float = 0.0  # 0 = auto

        # UI state
        self.ui_hold: bool = False
        self.theme: str = 'dark'

    @property
    def effective_rate(self) -> float:
        """Effective sample rate after oversampling."""
        return self.sample_rate / max(1, self.oversampling)

    @property
    def data_window_us(self) -> float:
        """Total data window duration in microseconds."""
        return (self.frame_size / self.effective_rate) * 1e6

    @property
    def auto_timebase_us(self) -> float:
        """Automatic T/div to fill 10 divisions with data."""
        return self.data_window_us / 10.0

    def notify(self):
        """Emit changed signal. Call after modifying properties."""
        self.changed.emit()

    def channel(self, idx: int) -> ChannelConfig:
        """Get channel config by index (0 or 1)."""
        return self.ch0 if idx == 0 else self.ch1
