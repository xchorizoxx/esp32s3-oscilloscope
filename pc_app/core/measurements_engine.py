"""
measurements_engine.py — Calculo de mediciones automaticas en Python/NumPy.

Corre en un QThread separado para no bloquear la UI.
Toma arrays de muestras en mV y calcula todas las metricas estandar de osciloscopio.
"""

import numpy as np
from scipy import signal as scipy_signal
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition


class MeasurementsEngine(QThread):
    """
    Thread que calcula mediciones automaticas sobre arrays de muestras en mV.

    Senal emitida:
        measurements_ready(dict) — dict con canales 'ch0' y 'ch1'
    """
    measurements_ready = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mutex    = QMutex()
        self._cond     = QWaitCondition()
        self._running  = True
        self._pending  = None  # {'ch0': ndarray|None, 'ch1': ndarray|None, 'rate': int}

    # ------------------------------------------------------------------
    # Interfaz publica
    # ------------------------------------------------------------------

    def submit(self, ch0_mv: np.ndarray | None, ch1_mv: np.ndarray | None, sample_rate: int) -> None:
        """Envia nuevas muestras para calcular. No bloqueante."""
        self._mutex.lock()
        self._pending = {'ch0': ch0_mv, 'ch1': ch1_mv, 'rate': sample_rate}
        self._cond.wakeOne()
        self._mutex.unlock()

    def stop(self) -> None:
        self._mutex.lock()
        self._running = False
        self._cond.wakeOne()
        self._mutex.unlock()
        self.wait()

    # ------------------------------------------------------------------
    # QThread main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        while True:
            self._mutex.lock()
            while self._pending is None and self._running:
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            job = self._pending
            self._pending = None
            self._mutex.unlock()

            result = {}
            rate = job['rate']
            if job['ch0'] is not None:
                result['ch0'] = self.compute_all(job['ch0'], rate)
            if job['ch1'] is not None:
                result['ch1'] = self.compute_all(job['ch1'], rate)

            if result:
                self.measurements_ready.emit(result)

    # ------------------------------------------------------------------
    # Calculos estaticos (se pueden usar directamente sin el thread)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_vpp(samples: np.ndarray) -> float:
        """Voltaje pico a pico en mV."""
        return float(np.max(samples) - np.min(samples))

    @staticmethod
    def compute_vmax(samples: np.ndarray) -> float:
        return float(np.max(samples))

    @staticmethod
    def compute_vmin(samples: np.ndarray) -> float:
        return float(np.min(samples))

    @staticmethod
    def compute_vrms(samples: np.ndarray) -> float:
        """RMS total (incluyendo DC) en mV."""
        return float(np.sqrt(np.mean(samples ** 2)))

    @staticmethod
    def compute_vdc(samples: np.ndarray) -> float:
        """Componente DC (media) en mV."""
        return float(np.mean(samples))

    @staticmethod
    def compute_vac_rms(samples: np.ndarray) -> float:
        """RMS de la componente AC (sin DC) en mV."""
        ac = samples - np.mean(samples)
        return float(np.sqrt(np.mean(ac ** 2)))

    @staticmethod
    def compute_frequency(samples: np.ndarray, sample_rate: int) -> float:
        """
        Frecuencia fundamental en Hz.
        Usa autocorrelacion para senales periodicas.
        Retorna 0.0 si no se detecta periodo valido.
        """
        if sample_rate <= 0 or len(samples) < 4:
            return 0.0
        ac = samples - np.mean(samples)
        if np.max(np.abs(ac)) < 1.0:  # Senal plana (< 1mV AC)
            return 0.0
        N = len(ac)
        corr = np.correlate(ac, ac, mode='full')
        corr = corr[N - 1:]
        corr /= corr[0]
        try:
            peaks, _ = scipy_signal.find_peaks(corr[1:], height=0.3)
            if len(peaks) == 0:
                return 0.0
            period_samples = peaks[0] + 1
            if period_samples == 0:
                return 0.0
            return float(sample_rate / period_samples)
        except Exception:
            return 0.0

    @staticmethod
    def compute_period(samples: np.ndarray, sample_rate: int) -> float:
        """Periodo en us."""
        freq = MeasurementsEngine.compute_frequency(samples, sample_rate)
        if freq <= 0:
            return 0.0
        return float(1e6 / freq)

    @staticmethod
    def compute_duty_cycle(samples: np.ndarray) -> float:
        """
        Duty cycle en % para senales digitales.
        Usa el umbral del 50% entre vmin y vmax.
        """
        vmax = np.max(samples)
        vmin = np.min(samples)
        if (vmax - vmin) < 1.0:
            return 50.0
        threshold = (vmax + vmin) / 2.0
        high = np.sum(samples >= threshold)
        return float(high / len(samples) * 100.0)

    @staticmethod
    def compute_rise_time(samples: np.ndarray, sample_rate: int) -> float:
        """
        Tiempo de subida (10% -> 90%) en us.
        Retorna 0.0 si no hay transicion detectada.
        """
        if sample_rate <= 0 or len(samples) < 4:
            return 0.0
        vmax = np.max(samples)
        vmin = np.min(samples)
        vpp  = vmax - vmin
        if vpp < 1.0:
            return 0.0
        lo = vmin + 0.1 * vpp
        hi = vmin + 0.9 * vpp
        sample_period_us = 1e6 / sample_rate
        for i in range(len(samples) - 1):
            if samples[i] <= lo:
                for j in range(i + 1, len(samples)):
                    if samples[j] >= hi:
                        return float((j - i) * sample_period_us)
                    if samples[j] < lo:
                        break
        return 0.0

    @staticmethod
    def compute_fall_time(samples: np.ndarray, sample_rate: int) -> float:
        """
        Tiempo de bajada (90% -> 10%) en us.
        """
        if sample_rate <= 0 or len(samples) < 4:
            return 0.0
        vmax = np.max(samples)
        vmin = np.min(samples)
        vpp  = vmax - vmin
        if vpp < 1.0:
            return 0.0
        lo = vmin + 0.1 * vpp
        hi = vmin + 0.9 * vpp
        sample_period_us = 1e6 / sample_rate
        for i in range(len(samples) - 1):
            if samples[i] >= hi:
                for j in range(i + 1, len(samples)):
                    if samples[j] <= lo:
                        return float((j - i) * sample_period_us)
                    if samples[j] > hi:
                        break
        return 0.0

    @classmethod
    def compute_all(cls, samples: np.ndarray, sample_rate: int) -> dict:
        """Calcula todas las metricas y retorna un dict."""
        if samples is None or len(samples) == 0:
            return {}
        return {
            'vpp_mv':        cls.compute_vpp(samples),
            'vrms_mv':       cls.compute_vrms(samples),
            'vdc_mv':        cls.compute_vdc(samples),
            'vac_rms_mv':    cls.compute_vac_rms(samples),
            'vmax_mv':       cls.compute_vmax(samples),
            'vmin_mv':       cls.compute_vmin(samples),
            'freq_hz':       cls.compute_frequency(samples, sample_rate),
            'period_us':     cls.compute_period(samples, sample_rate),
            'duty_cycle_pct': cls.compute_duty_cycle(samples),
            'rise_time_us':  cls.compute_rise_time(samples, sample_rate),
            'fall_time_us':  cls.compute_fall_time(samples, sample_rate),
            'valid':         True,
        }
