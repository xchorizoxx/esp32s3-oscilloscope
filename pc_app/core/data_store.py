"""
data_store.py — Almacenamiento circular de frames para funciones avanzadas.

Thread-safe: usa QMutex para proteger acceso concurrente entre SerialReader (QThread)
y el UI thread (QTimer de renderizado).
"""

from collections import deque
from typing import List, Tuple
import numpy as np
import csv
import wave
import struct

from PyQt6.QtCore import QMutex


class DataStore:
    """
    Buffer circular para almacenar el historial de frames recibidos.
    Permite acceso para modos persistencia, promedio y envolvente.
    """

    def __init__(self, capacity: int = 1000) -> None:
        self.capacity = capacity
        self._frames = deque(maxlen=capacity)
        self._mutex = QMutex()

    def push(self, frame: dict) -> None:
        """
        Agrega un frame al historial.
        Solo guarda frames DATA (0x01).
        Precalcula el eje temporal en us si se proporciona sample_rate.
        """
        if frame.get('type') != 0x01:  # Solo guardar frames DATA
            return

        self._mutex.lock()
        try:
            # Precalcular eje temporal en us si tenemos sample_count y trigger_index
            # El sample_rate se rellenara en el primer render loop que lo conozca
            self._frames.append(frame)
        finally:
            self._mutex.unlock()

    def get_last_n(self, n: int) -> List[dict]:
        """Retorna los ultimos n frames (copia segura)."""
        self._mutex.lock()
        try:
            count = min(n, len(self._frames))
            if count == 0:
                return []
            return list(self._frames)[-count:]
        finally:
            self._mutex.unlock()

    def get_average(self, n: int, channel: str = 'ch0_mv') -> np.ndarray | None:
        """
        Calcula el promedio de los ultimos N frames para un canal dado.
        channel: 'ch0_mv' o 'ch1_mv'
        """
        self._mutex.lock()
        try:
            frames = list(self._frames)[-min(n, len(self._frames)):]
        finally:
            self._mutex.unlock()

        if not frames:
            return None

        valid_arrays = []
        target_len = None

        for f in reversed(frames):  # Empezar desde el mas reciente
            arr = f.get(channel)
            if arr is not None:
                if target_len is None:
                    target_len = len(arr)
                    valid_arrays.append(arr)
                elif len(arr) == target_len:
                    valid_arrays.append(arr)

        if not valid_arrays:
            return None

        return np.mean(valid_arrays, axis=0)

    def get_envelope(self, n: int, channel: str = 'ch0_mv') -> Tuple[np.ndarray, np.ndarray] | None:
        """
        Calcula la envolvente (min, max) de los ultimos N frames para un canal.
        Retorna (array_min, array_max).
        """
        self._mutex.lock()
        try:
            frames = list(self._frames)[-min(n, len(self._frames)):]
        finally:
            self._mutex.unlock()

        if not frames:
            return None

        valid_arrays = []
        target_len = None

        for f in reversed(frames):
            arr = f.get(channel)
            if arr is not None:
                if target_len is None:
                    target_len = len(arr)
                    valid_arrays.append(arr)
                elif len(arr) == target_len:
                    valid_arrays.append(arr)

        if not valid_arrays:
            return None

        matrix = np.vstack(valid_arrays)
        return np.min(matrix, axis=0), np.max(matrix, axis=0)

    def clear(self) -> None:
        """Limpia el historial."""
        self._mutex.lock()
        try:
            self._frames.clear()
        finally:
            self._mutex.unlock()

    def export_csv(self, path: str, n_frames: int = 1) -> None:
        """Exporta los ultimos N frames a CSV."""
        self._mutex.lock()
        try:
            frames = list(self._frames)[-min(n_frames, len(self._frames)):]
        finally:
            self._mutex.unlock()

        if not frames:
            return

        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['frame_index', 'time_us', 'ch0_mv', 'ch1_mv'])

            for i, frame in enumerate(frames):
                t_axis = frame.get('time_axis_us', [])
                ch0 = frame.get('ch0_mv')
                ch1 = frame.get('ch1_mv')

                if ch0 is None and ch1 is None:
                    continue

                length = len(t_axis)
                for j in range(length):
                    t = t_axis[j] if j < len(t_axis) else 0.0
                    v0 = ch0[j] if ch0 is not None and j < len(ch0) else ""
                    v1 = ch1[j] if ch1 is not None and j < len(ch1) else ""
                    writer.writerow([i, t, v0, v1])

    def export_wav(self, path: str, channel: str = 'ch0_mv', sample_rate: int = 44100) -> None:
        """Exporta el ultimo frame como un archivo WAV (mono, 16-bit)."""
        self._mutex.lock()
        try:
            frames = list(self._frames)[-1:] if self._frames else []
        finally:
            self._mutex.unlock()

        if not frames:
            return

        data = frames[0].get(channel)
        if data is None or len(data) == 0:
            return

        # Normalizar a int16 rango completo (-32768 a 32767)
        max_val = np.max(np.abs(data))
        if max_val > 0:
            normalized = (data / max_val) * 32767.0
        else:
            normalized = data

        wav_data = normalized.astype(np.int16).tobytes()

        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)  # Mono
            wf.setsampwidth(2)  # 16-bit (2 bytes)
            wf.setframerate(sample_rate)
            wf.writeframes(wav_data)
