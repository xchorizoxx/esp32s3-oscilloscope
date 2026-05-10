"""
render_pipeline.py — Extracted render logic from MainWindow._on_render_timer.

Separates data processing stages into a clean pipeline:
  1. Fetch data from DataStore
  2. Apply AC coupling filter
  3. Submit to MeasurementsEngine
  4. Dispatch to appropriate render mode (normal, average, envelope, persistence)
  5. Update secondary views (XY, FFT)
"""

import numpy as np
from core.data_store import DataStore
from core.measurements_engine import MeasurementsEngine
from core.fft_engine import FFTEngine


class RenderPipeline:
    """
    Stateless render pipeline that processes frames and dispatches
    to the appropriate visualization widgets.
    """

    def __init__(self, data_store: DataStore, meas_engine: MeasurementsEngine,
                 fft_engine: FFTEngine):
        self.data_store = data_store
        self.meas_engine = meas_engine
        self.fft_engine = fft_engine

        # AC coupling state (per channel)
        self._ac_state = {
            0: {'dc_offset': None, 'mode': 'DC'},
            1: {'dc_offset': None, 'mode': 'DC'},
        }
        self._overflow_count = 0

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    def set_ac_mode(self, channel: int, mode: str):
        """Set AC/DC coupling mode for a channel."""
        self._ac_state[channel]['mode'] = mode
        if mode == 'DC':
            self._ac_state[channel]['dc_offset'] = None

    def process_frame(self, cfg, waveform_widget, fft_widget=None,
                      xy_widget=None) -> bool:
        """
        Process one render cycle. Returns True if a frame was rendered.

        Args:
            cfg: OscConfig from the controller
            waveform_widget: WaveformWidget instance
            fft_widget: FFTWidget instance (optional, can be None/hidden)
            xy_widget: XYWidget instance (optional, can be None/hidden)
        """
        # 1. Fetch data
        frames = self.data_store.get_last_n(5)
        if not frames:
            return False

        latest = frames[-1]
        ch1_raw = latest.get('ch0_mv')
        ch2_raw = latest.get('ch1_mv')
        rate = cfg.sample_rate / max(1, cfg.oversampling)
        sample_count = latest.get('sample_count', 0)
        trigger_idx = latest.get('trigger_index', 0)

        # 2. Time indices
        t_indices = np.arange(sample_count, dtype=np.float64)

        # 3. AC coupling
        ch1 = self._apply_ac_coupling(ch1_raw, 0, rate) if ch1_raw is not None else None
        ch2 = self._apply_ac_coupling(ch2_raw, 1, rate) if ch2_raw is not None else None

        # 4. Measurements (non-blocking, runs in separate thread)
        self.meas_engine.submit(ch1, ch2, rate)

        # 5. Track overflow
        if latest.get('overflow', False):
            self._overflow_count += 1

        # 6. Waveform dispatch
        mode = waveform_widget.display_mode

        if waveform_widget.roll_mode or mode == 'normal':
            waveform_widget.update_frame(t_indices, ch1, ch2, trigger_idx, rate)
        elif mode == 'average':
            a1 = self.data_store.get_average(4, 'ch0_mv')
            a2 = self.data_store.get_average(4, 'ch1_mv')
            if a1 is not None and self._ac_state[0]['mode'] != 'DC':
                a1 = self._apply_ac_coupling(a1, 0, rate)
            if a2 is not None and self._ac_state[1]['mode'] != 'DC':
                a2 = self._apply_ac_coupling(a2, 1, rate)
            waveform_widget.update_frame(t_indices, a1, a2, trigger_idx, rate)
        elif mode == 'envelope':
            e1 = self.data_store.get_envelope(4, 'ch0_mv')
            e2 = self.data_store.get_envelope(4, 'ch1_mv')
            min1, max1 = e1 if e1 else (None, None)
            min2, max2 = e2 if e2 else (None, None)
            waveform_widget.update_envelope(t_indices, min1, max1, min2, max2, rate)
        elif mode == 'persistence':
            waveform_widget.update_persistence(frames, rate)

        # 7. XY Render
        if xy_widget and not xy_widget.isHidden():
            xy_widget.update_xy(ch1, ch2)

        # 8. FFT Render
        if fft_widget and not fft_widget.isHidden():
            fft_mags = latest.get('fft_magnitudes')
            fft_bin_hz = latest.get('fft_bin_hz')
            
            if fft_mags is not None and fft_bin_hz is not None and len(fft_mags) > 0:
                freqs = np.arange(len(fft_mags)) * fft_bin_hz
                # Evitar log10(0)
                mags_safe = np.maximum(fft_mags, 1e-6)
                mags_db = 20 * np.log10(mags_safe)
                
                peak_idx = np.argmax(fft_mags)
                peak_freq = freqs[peak_idx]
                peak_mag = fft_mags[peak_idx]
                
                # Por ahora el ESP32 solo calcula FFT del CH0, lo pasamos al canal 0
                fft_widget.update_fft(0, freqs, fft_mags, mags_db, peak_freq, peak_mag)

        return True

    def _apply_ac_coupling(self, samples: np.ndarray, channel: int,
                           sample_rate: float) -> np.ndarray:
        """Apply high-pass IIR filter for AC coupling."""
        state = self._ac_state[channel]
        if state['mode'] == 'GND':
            return np.zeros_like(samples)
        if state['mode'] == 'DC' or samples is None:
            return samples

        # Fast vectorized frame-level EMA (avoids slow Python loops)
        frame_mean = float(np.mean(samples))
        if state['dc_offset'] is None:
            state['dc_offset'] = frame_mean

        # Update slow integrador
        alpha_ema = 0.05
        state['dc_offset'] = alpha_ema * frame_mean + (1.0 - alpha_ema) * state['dc_offset']

        return samples - state['dc_offset']
