"""
render_pipeline.py — Extracted render logic from MainWindow._on_render_timer.

Separates data processing stages into a clean pipeline:
  1. Fetch data from DataStore
  2. Apply AC coupling filter
  3. Submit to MeasurementsEngine (PGA-corrected for CH1)
  4. Dispatch to appropriate render mode (normal, average, envelope, persistence)
  5. Update secondary views (XY, FFT) with PGA-corrected data
"""

import numpy as np
from core.data_store import DataStore
from core.measurements_engine import MeasurementsEngine
from core.fft_engine import FFTEngine


class RenderPipeline:

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

        # PGA state (copied from controller when it changes)
        self._pga_enabled = False
        self._pga_vg_mv = 1450.0
        self._pga_gain_eff = 1.0
        self._pga_offset_mv = 0.0
        self._pga_div_ratio = 100000.0 / (1000000.0 + 100000.0)

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    def set_ac_mode(self, channel: int, mode: str):
        self._ac_state[channel]['mode'] = mode
        if mode == 'DC':
            self._ac_state[channel]['dc_offset'] = None

    def set_pga_params(self, enabled: bool, vg_mv: float, gain_eff: float,
                       offset_mv: float, div_ratio: float):
        self._pga_enabled = enabled
        self._pga_vg_mv = vg_mv
        self._pga_gain_eff = gain_eff
        self._pga_offset_mv = offset_mv
        self._pga_div_ratio = div_ratio

    def _apply_pga(self, samples: np.ndarray) -> np.ndarray:
        """Apply PGA inverse transfer function to convert ADC mV to input mV."""
        if not self._pga_enabled or samples is None or len(samples) == 0:
            return samples
        g = self._pga_gain_eff
        if g <= 0:
            return samples
        return (samples - self._pga_vg_mv - self._pga_offset_mv) / g / self._pga_div_ratio

    def process_frame(self, cfg, waveform_widget, fft_widget=None,
                      xy_widget=None) -> bool:
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

        # 4. PGA correction for measurements, XY, and FFT
        ch1_corrected = self._apply_pga(ch1) if ch1 is not None else None

        # 5. Measurements (non-blocking — runs in separate thread)
        self.meas_engine.submit(ch1_corrected, ch2, rate)

        # 6. Track overflow
        if latest.get('overflow', False):
            self._overflow_count += 1

        # 7. Waveform dispatch
        #    Note: waveform_widget does its OWN PGA correction in _pga_adc_to_input_mv()
        #    so we pass uncorrected data here.
        mode = waveform_widget.display_mode

        if waveform_widget.roll_mode or mode == 'normal':
            waveform_widget.update_frame(t_indices, ch1, ch2, trigger_idx, rate)
        elif mode == 'average':
            a1 = self.data_store.get_average(4, 'ch0_mv')
            a2 = self.data_store.get_average(4, 'ch1_mv')
            # PC-02 FIX: the EMA integrator was already updated in step 3 above.
            # Subtract the stored dc_offset directly — do NOT call _apply_ac_coupling
            # again, which would re-run the EMA and corrupt the DC level.
            if a1 is not None:
                dc0 = self._ac_state[0].get('dc_offset')
                if self._ac_state[0]['mode'] == 'GND':
                    a1 = np.zeros_like(a1)
                elif dc0 is not None and self._ac_state[0]['mode'] != 'DC':
                    a1 = a1 - dc0
            if a2 is not None:
                dc1 = self._ac_state[1].get('dc_offset')
                if self._ac_state[1]['mode'] == 'GND':
                    a2 = np.zeros_like(a2)
                elif dc1 is not None and self._ac_state[1]['mode'] != 'DC':
                    a2 = a2 - dc1
            waveform_widget.update_frame(t_indices, a1, a2, trigger_idx, rate)
        elif mode == 'envelope':
            e1 = self.data_store.get_envelope(4, 'ch0_mv')
            e2 = self.data_store.get_envelope(4, 'ch1_mv')
            min1, max1 = e1 if e1 else (None, None)
            min2, max2 = e2 if e2 else (None, None)
            waveform_widget.update_envelope(t_indices, min1, max1, min2, max2, rate)
        elif mode == 'persistence':
            waveform_widget.update_persistence(frames, rate)

        # 8. XY Render (PGA-corrected CH1)
        if xy_widget and not xy_widget.isHidden():
            xy_widget.update_xy(ch1_corrected, ch2)

        # 9. FFT Render (PGA-corrected)
        if fft_widget and not fft_widget.isHidden():
            fft_mags = latest.get('fft_magnitudes')
            fft_bin_hz = latest.get('fft_bin_hz')

            if fft_mags is not None and fft_bin_hz is not None and len(fft_mags) > 0:
                freqs = np.arange(len(fft_mags)) * fft_bin_hz

                # Correct FFT magnitudes for PGA gain and input divider
                fft_mags_corrected = fft_mags.copy()
                if self._pga_enabled:
                    g = self._pga_gain_eff
                    if g > 0:
                        fft_mags_corrected = fft_mags_corrected / g / self._pga_div_ratio

                mags_safe = np.maximum(fft_mags_corrected, 1e-6)
                mags_db = 20 * np.log10(mags_safe)

                peak_idx = np.argmax(fft_mags_corrected)
                peak_freq = freqs[peak_idx]
                peak_mag = fft_mags_corrected[peak_idx]

                fft_widget.update_fft(0, freqs, fft_mags_corrected, mags_db, peak_freq, peak_mag)

        return True

    def _apply_ac_coupling(self, samples: np.ndarray, channel: int,
                           sample_rate: float) -> np.ndarray:
        state = self._ac_state[channel]
        if state['mode'] == 'GND':
            return np.zeros_like(samples)
        if state['mode'] == 'DC' or samples is None:
            return samples

        frame_mean = float(np.mean(samples))
        if state['dc_offset'] is None:
            state['dc_offset'] = frame_mean

        alpha_ema = 0.05
        state['dc_offset'] = alpha_ema * frame_mean + (1.0 - alpha_ema) * state['dc_offset']

        return samples - state['dc_offset']
