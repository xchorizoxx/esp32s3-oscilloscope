"""
fft_engine.py — FFT en Python para visualización en la PC.

Complementa la FFT del firmware, permite más resolución y análisis avanzado.
Implementado con scipy.fft.rfft para máxima eficiencia con señales reales.
"""

import numpy as np
import scipy.fft
from scipy import signal as scipy_signal

class FFTEngine:
    """
    Motor de FFT que toma muestras en el dominio del tiempo y retorna
    magnitudes en el dominio de la frecuencia.
    """

    def __init__(self) -> None:
        pass

    def compute(self,
                samples_mv: np.ndarray,
                sample_rate: int,
                window: str = 'hanning',
                n_points: int | None = None) -> dict:
        """
        Calcula la FFT de las muestras dadas.

        Args:
            samples_mv: Array NumPy de muestras en milivoltios.
            sample_rate: Tasa de muestreo en Hz.
            window: Tipo de ventana ('rectangular', 'hanning', 'hamming', 'blackman').
            n_points: Número de puntos para la FFT (padding/truncating). Si es None, usa len(samples).

        Returns:
            dict con frecuencias, magnitudes (mV y dBV), pico y THD estimado.
        """
        if samples_mv is None or len(samples_mv) == 0 or sample_rate <= 0:
            return {}

        # Remover DC offset para que el bin 0 no domine el gráfico
        ac_samples = samples_mv - np.mean(samples_mv)
        N = len(ac_samples)

        if n_points is None:
            n_points = N

        # Aplicar ventana
        if window == 'hanning':
            w = np.hanning(N)
        elif window == 'hamming':
            w = np.hamming(N)
        elif window == 'blackman':
            w = np.blackman(N)
        else: # 'rectangular'
            w = np.ones(N)

        windowed_samples = ac_samples * w

        # rfft es para entradas reales, retorna la mitad positiva del espectro
        fft_result = scipy.fft.rfft(windowed_samples, n=n_points)
        freqs = scipy.fft.rfftfreq(n_points, d=1.0 / sample_rate)

        # Magnitud en mV. Normalización: multiplicar por 2/N para recuperar la amplitud real de la sinusoide.
        # (El factor de corrección de la ventana se omite para simplicidad, pero podría agregarse si se requiere precisión absoluta).
        magnitudes_mv = (np.abs(fft_result) * 2.0) / N

        # Evitar log10 de 0
        eps = 1e-10
        magnitudes_mv_safe = np.maximum(magnitudes_mv, eps)

        # Magnitud en dBV (Referencia 1V = 1000mV)
        # dBV = 20 * log10(V_rms / 1V) = 20 * log10( (V_peak/sqrt(2)) / 1000 )
        # Simplificación: usamos la amplitud pico para dB relativo al pico,
        # o dBm si fuera necesario. Aquí calculamos dBV.
        # V_rms = magnitudes_mv / (sqrt(2) * 1000)
        v_rms_v = magnitudes_mv_safe / (np.sqrt(2.0) * 1000.0)
        magnitudes_db = 20.0 * np.log10(v_rms_v)

        # Encontrar el pico (ignorando el componente DC cercano si lo hubiera)
        peak_idx = np.argmax(magnitudes_mv[1:]) + 1 if len(magnitudes_mv) > 1 else 0
        peak_freq = float(freqs[peak_idx])
        peak_magnitude_mv = float(magnitudes_mv[peak_idx])

        # Estimación básica de THD (Total Harmonic Distortion)
        # Suma de la potencia de los armónicos / potencia de la fundamental
        thd_pct = 0.0
        if peak_magnitude_mv > 1.0: # Solo calcular si hay una señal apreciable
            # Identificar armónicos (multiplos de peak_freq)
            harmonics_power = 0.0
            fundamental_power = peak_magnitude_mv ** 2

            for i in range(2, 10): # Hasta el 9no armónico
                harmonic_freq = peak_freq * i
                if harmonic_freq > freqs[-1]:
                    break
                # Buscar el bin más cercano
                idx = (np.abs(freqs - harmonic_freq)).argmin()
                harmonics_power += magnitudes_mv[idx] ** 2

            if fundamental_power > 0:
                thd_pct = float(np.sqrt(harmonics_power / fundamental_power) * 100.0)

        # Estimación del noise floor
        # Promedio de la mitad superior del espectro
        noise_floor_db = float(np.mean(magnitudes_db[len(magnitudes_db)//2:]))

        return {
            'freqs': freqs,
            'magnitudes_mv': magnitudes_mv,
            'magnitudes_db': magnitudes_db,
            'peak_freq': peak_freq,
            'peak_magnitude_mv': peak_magnitude_mv,
            'thd_pct': thd_pct,
            'noise_floor_db': noise_floor_db,
        }
