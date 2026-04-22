"""
frame_parser.py — Parser stateful del protocolo binario ESP32 Oscilloscope.

Protocolo:
  - Sync: 0xAA 0x55
  - Frame types: DATA(0x01), MEASUREMENTS(0x02), ACK(0x03), NAK(0x04), INFO(0x05), FFT(0x06)
  - CRC8 Dallas/Maxim polinomio 0x31 sobre todos los bytes del frame (incluyendo sync)
"""

import struct
from typing import List, Optional
import numpy as np

# ---------------------------------------------------------------------------
# CRC8 Dallas/Maxim (polinomio 0x31)
# ---------------------------------------------------------------------------
_CRC8_TABLE: List[int] = []
for _i in range(256):
    _crc = _i
    for _ in range(8):
        _crc = ((_crc << 1) ^ 0x31) if (_crc & 0x80) else (_crc << 1)
        _crc &= 0xFF
    _CRC8_TABLE.append(_crc)


def crc8(data: bytes) -> int:
    """Calcula CRC8 Dallas/Maxim (polinomio 0x31) sobre los bytes dados."""
    crc = 0
    for b in data:
        crc = _CRC8_TABLE[crc ^ b]
    return crc


# ---------------------------------------------------------------------------
# Constantes de tipos de frame
# ---------------------------------------------------------------------------
FRAME_DATA         = 0x01
FRAME_MEASUREMENTS = 0x02
FRAME_ACK          = 0x03
FRAME_NAK          = 0x04
FRAME_INFO         = 0x05
FRAME_FFT          = 0x06

SYNC = b'\xAA\x55'

# Tamaños fijos de campos de cabecera por tipo (sin sync, sin CRC)
# Para DATA y FFT el tamaño es variable según SAMPLE_COUNT/FFT_POINTS
_FIXED_HEADER = {
    FRAME_DATA:         12,   # type(1)+flags(1)+seq(2)+count(2)+ts(4)+trig(4)
    FRAME_MEASUREMENTS: 1+1+44+44,  # type+flags+ch0(44)+ch1(44)  NOTE: spec = 44 bytes per ch
    FRAME_ACK:          1+32,       # type+cmd_string(32)
    FRAME_NAK:          1+32+32,    # type+cmd(32)+reason(32)
    FRAME_INFO:         1+1+1+4+2+2+32,  # type+maj+min+max_rate+max_frame+caps+str
    FRAME_FFT:          1+1+2+2+4,  # type+flags+seq+points+bin_hz
}

# Tamaño en bytes de medición CH (11 float32 + 1 byte valid)
_MEAS_CH_SIZE = 11 * 4 + 1  # = 45


class FrameParser:
    """
    Parser stateful que acepta bytes en chunks arbitrarios y retorna frames completos.

    Uso:
        parser = FrameParser()
        frames = parser.feed(chunk_bytes)
        for frame in frames:
            process(frame)
    """

    _MAX_BUF = 8192  # Si el buffer crece más sin sync, se limpia

    def __init__(self) -> None:
        self._buf = bytearray()
        self.frames_ok:    int = 0
        self.frames_error: int = 0

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes) -> List[dict]:
        """
        Ingesta nuevos bytes y retorna lista de frames parseados correctamente.
        Los frames con CRC incorrecto se descartan silenciosamente.
        """
        self._buf.extend(data)
        parsed: List[dict] = []

        while True:
            # Buscar sync
            idx = self._buf.find(SYNC)
            if idx == -1:
                # Sin sync — mantener los últimos N bytes por si el sync viene partido
                if len(self._buf) > self._MAX_BUF:
                    self._buf.clear()
                elif len(self._buf) > 2:
                    self._buf = self._buf[-1:]
                break

            if idx > 0:
                # Descartar bytes basura antes del sync
                del self._buf[:idx]

            # Necesitamos al menos sync(2) + type(1) = 3 bytes
            if len(self._buf) < 3:
                break

            frame_type = self._buf[2]
            frame = self._try_parse(frame_type)

            if frame is None:
                # Necesitamos más bytes
                break
            elif frame is False:
                # Frame inválido — saltar el sync actual y seguir buscando
                self.frames_error += 1
                del self._buf[:2]
            else:
                parsed.append(frame)
                self.frames_ok += 1

        # Sanity check: limpiar buffer si está demasiado lleno sin avanzar
        if len(self._buf) > self._MAX_BUF:
            self._buf.clear()

        return parsed

    # ------------------------------------------------------------------
    # Parsers internos por tipo
    # ------------------------------------------------------------------

    def _try_parse(self, frame_type: int) -> Optional[dict]:
        """
        Intenta parsear el frame del tipo dado desde el inicio del buffer.
        Retorna:
          - dict   : frame parseado OK
          - False  : frame inválido (CRC error o mal formato)
          - None   : datos insuficientes, esperar más bytes
        """
        if frame_type == FRAME_DATA:
            return self._parse_data()
        elif frame_type == FRAME_MEASUREMENTS:
            return self._parse_measurements()
        elif frame_type == FRAME_ACK:
            return self._parse_ack()
        elif frame_type == FRAME_NAK:
            return self._parse_nak()
        elif frame_type == FRAME_INFO:
            return self._parse_info()
        elif frame_type == FRAME_FFT:
            return self._parse_fft()
        else:
            # Tipo desconocido — saltar sync
            return False

    def _check_and_consume(self, total_size: int) -> Optional[bytes]:
        """
        Verifica CRC y consume `total_size` bytes del buffer.
        Retorna los bytes del frame (sin CRC) si es válido, False si CRC falla, None si faltan bytes.
        """
        if len(self._buf) < total_size:
            return None
        raw = bytes(self._buf[:total_size])
        expected_crc = raw[-1]
        computed_crc = crc8(raw[:-1])
        if computed_crc != expected_crc:
            return False
        del self._buf[:total_size]
        return raw

    def _parse_data(self) -> Optional[dict]:
        # Cabecera mínima: sync(2)+type(1)+flags(1)+seq(2)+count(2)+ts(4)+trig_idx(4) = 16 bytes
        HDR = 16
        if len(self._buf) < HDR + 1:  # +1 para CRC mínimo
            return None

        flags        = self._buf[3]
        seq_num      = struct.unpack_from('<H', self._buf, 4)[0]
        sample_count = struct.unpack_from('<H', self._buf, 6)[0]
        timestamp_us = struct.unpack_from('<I', self._buf, 8)[0]
        trigger_idx  = struct.unpack_from('<I', self._buf, 12)[0]

        ch0_valid  = bool(flags & 0x01)
        ch1_valid  = bool(flags & 0x02)
        trig_hit   = bool(flags & 0x04)
        overflow   = bool(flags & 0x08)
        fft_att    = bool(flags & 0x10)

        n_channels = (1 if ch0_valid else 0) + (1 if ch1_valid else 0)
        sample_bytes = sample_count * 2 * n_channels  # int16 = 2 bytes
        total = HDR + sample_bytes + 1  # +1 CRC

        raw = self._check_and_consume(total)
        if raw is None:
            return None
        if raw is False:
            return False

        offset = HDR
        ch0_mv = None
        ch1_mv = None

        if ch0_valid:
            raw_int16 = np.frombuffer(raw[offset:offset + sample_count * 2], dtype='<i2')
            ch0_mv = raw_int16.astype(np.float32) / 10.0
            offset += sample_count * 2

        if ch1_valid:
            raw_int16 = np.frombuffer(raw[offset:offset + sample_count * 2], dtype='<i2')
            ch1_mv = raw_int16.astype(np.float32) / 10.0

        # Eje temporal: trigger en t=0, pre-trigger en negativo
        # El sample_rate no lo conocemos aquí; lo calcula el receiver con timestamp
        time_axis_us = np.arange(sample_count, dtype=np.float64)

        return {
            'type':          FRAME_DATA,
            'seq':           seq_num,
            'flags':         flags,
            'ch0_valid':     ch0_valid,
            'ch1_valid':     ch1_valid,
            'trigger_hit':   trig_hit,
            'overflow':      overflow,
            'fft_attached':  fft_att,
            'sample_count':  sample_count,
            'timestamp_us':  timestamp_us,
            'trigger_index': trigger_idx,
            'ch0_mv':        ch0_mv,
            'ch1_mv':        ch1_mv,
            'time_axis_us':  time_axis_us,
        }

    def _parse_measurements(self) -> Optional[dict]:
        # sync(2)+type(1)+flags(1)+ch0(45)+ch1(45)+CRC(1) = 95
        TOTAL = 2 + 1 + 1 + _MEAS_CH_SIZE + _MEAS_CH_SIZE + 1
        raw = self._check_and_consume(TOTAL)
        if raw is None:
            return None
        if raw is False:
            return False

        flags     = raw[3]
        ch0_valid = bool(flags & 0x01)
        ch1_valid = bool(flags & 0x02)

        def parse_ch(offset: int) -> dict:
            fields = struct.unpack_from('<11f', raw, offset)
            valid  = raw[offset + 11 * 4]
            keys   = ['vpp_mv', 'vrms_mv', 'vdc_mv', 'vac_rms_mv', 'vmax_mv',
                      'vmin_mv', 'freq_hz', 'period_us', 'duty_cycle_pct',
                      'rise_time_us', 'fall_time_us']
            return {k: v for k, v in zip(keys, fields)} | {'valid': bool(valid)}

        ch0 = parse_ch(4)             if ch0_valid else None
        ch1 = parse_ch(4 + _MEAS_CH_SIZE) if ch1_valid else None

        return {'type': FRAME_MEASUREMENTS, 'flags': flags, 'ch0': ch0, 'ch1': ch1}

    def _parse_ack(self) -> Optional[dict]:
        # sync(2)+type(1)+cmd_string(32)+CRC(1) = 36
        TOTAL = 36
        raw = self._check_and_consume(TOTAL)
        if raw is None:
            return None
        if raw is False:
            return False
        cmd = raw[3:35].rstrip(b'\x00').decode('ascii', errors='replace')
        return {'type': FRAME_ACK, 'cmd': cmd}

    def _parse_nak(self) -> Optional[dict]:
        # sync(2)+type(1)+cmd(32)+reason(32)+CRC(1) = 68
        TOTAL = 68
        raw = self._check_and_consume(TOTAL)
        if raw is None:
            return None
        if raw is False:
            return False
        cmd    = raw[3:35].rstrip(b'\x00').decode('ascii', errors='replace')
        reason = raw[35:67].rstrip(b'\x00').decode('ascii', errors='replace')
        return {'type': FRAME_NAK, 'cmd': cmd, 'reason': reason}

    def _parse_info(self) -> Optional[dict]:
        # sync(2)+type(1)+maj(1)+min(1)+max_rate(4)+max_frame(2)+caps(2)+fw_str(32)+CRC(1) = 46
        TOTAL = 46
        raw = self._check_and_consume(TOTAL)
        if raw is None:
            return None
        if raw is False:
            return False

        maj       = raw[3]
        minor     = raw[4]
        max_rate  = struct.unpack_from('<I', raw, 5)[0]
        max_frame = struct.unpack_from('<H', raw, 9)[0]
        caps      = struct.unpack_from('<H', raw, 11)[0]
        fw_str    = raw[13:45].rstrip(b'\x00').decode('ascii', errors='replace')

        return {
            'type':             FRAME_INFO,
            'fw_version_major': maj,
            'fw_version_minor': minor,
            'fw_version':       f'{maj}.{minor}',
            'max_rate_hz':      max_rate,
            'max_frame_size':   max_frame,
            'caps_flags':       caps,
            'cap_dual':         bool(caps & 0x01),
            'cap_fft':          bool(caps & 0x02),
            'cap_oversample':   bool(caps & 0x04),
            'cap_clock_hack':   bool(caps & 0x08),
            'fw_string':        fw_str,
        }

    def _parse_fft(self) -> Optional[dict]:
        # sync(2)+type(1)+flags(1)+seq(2)+fft_points(2)+bin_hz_x100(4) = 12 cabecera fija
        HDR = 12
        if len(self._buf) < HDR + 1:
            return None

        flags      = self._buf[3]
        seq_num    = struct.unpack_from('<H', self._buf, 4)[0]
        fft_points = struct.unpack_from('<H', self._buf, 6)[0]
        bin_hz_x100 = struct.unpack_from('<I', self._buf, 8)[0]

        total = HDR + fft_points * 4 + 1  # float32 * points + CRC
        raw = self._check_and_consume(total)
        if raw is None:
            return None
        if raw is False:
            return False

        mags = np.frombuffer(raw[HDR:HDR + fft_points * 4], dtype='<f4').copy()
        bin_hz = bin_hz_x100 / 100.0
        freqs  = np.arange(fft_points, dtype=np.float64) * bin_hz

        return {
            'type':             FRAME_FFT,
            'flags':            flags,
            'seq':              seq_num,
            'fft_points':       fft_points,
            'bin_hz':           bin_hz,
            'freqs':            freqs,
            'magnitudes_mv':    mags,
        }
