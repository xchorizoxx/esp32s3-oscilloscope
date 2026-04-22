"""
frame_parser.py — Parser stateful del protocolo binario ESP32 Oscilloscope.

Protocolo:
  - Sync: 0xAA 0x55
  - Frame types: DATA(0x01), MEASUREMENTS(0x02), ACK(0x03), NAK(0x04), INFO(0x05), FFT(0x06)
  - CRC8 Dallas/Maxim — hardcoded table from osc_usb.c (NO generar algoritmicamente)
"""

import struct
from typing import List, Optional
import numpy as np

# ---------------------------------------------------------------------------
# CRC-8 Dallas/Maxim — TABLA HARDCODEADA exacta de osc_usb.c
# ---------------------------------------------------------------------------
# WARNING: Do NOT regenerate this table algorithmically from poly 0x31.
# The algorithmic generation produces a DIFFERENT table. This is the
# exact table burned into the ESP32 firmware.
_CRC8_TABLE = bytes([
    0x00,0x5E,0xBC,0xE2,0x61,0x3F,0xDD,0x83,0xC2,0x9C,0x7E,0x20,0xA3,0xFD,0x1F,0x41,
    0x9D,0xC3,0x21,0x7F,0xFC,0xA2,0x40,0x1E,0x5F,0x01,0xE3,0xBD,0x3E,0x60,0x82,0xDC,
    0x23,0x7D,0x9F,0xC1,0x42,0x1C,0xFE,0xA0,0xE1,0xBF,0x5D,0x03,0x80,0xDE,0x3C,0x62,
    0xBE,0xE0,0x02,0x5C,0xDF,0x81,0x63,0x3D,0x7C,0x22,0xC0,0x9E,0x1D,0x43,0xA1,0xFF,
    0x46,0x18,0xFA,0xA4,0x27,0x79,0x9B,0xC5,0x84,0xDA,0x38,0x66,0xE5,0xBB,0x59,0x07,
    0xDB,0x85,0x67,0x39,0xBA,0xE4,0x06,0x58,0x19,0x47,0xA5,0xFB,0x78,0x26,0xC4,0x9A,
    0x65,0x3B,0xD9,0x87,0x04,0x5A,0xB8,0xE6,0xA7,0xF9,0x1B,0x45,0xC6,0x98,0x7A,0x24,
    0xF8,0xA6,0x44,0x1A,0x99,0xC7,0x25,0x7B,0x3A,0x64,0x86,0xD8,0x5B,0x05,0xE7,0xB9,
    0x8C,0xD2,0x30,0x6E,0xED,0xB3,0x51,0x0F,0x4E,0x10,0xF2,0xAC,0x2F,0x71,0x93,0xCD,
    0x11,0x4F,0xAD,0xF3,0x70,0x2E,0xCC,0x92,0xD3,0x8D,0x6F,0x31,0xB2,0xEC,0x0E,0x50,
    0xAF,0xF1,0x13,0x4D,0xCE,0x90,0x72,0x2C,0x6D,0x33,0xD1,0x8F,0x0C,0x52,0xB0,0xEE,
    0x32,0x6C,0x8E,0xD0,0x53,0x0D,0xEF,0xB1,0xF0,0xAE,0x4C,0x12,0x91,0xCF,0x2D,0x73,
    0xCA,0x94,0x76,0x28,0xAB,0xF5,0x17,0x49,0x08,0x56,0xB4,0xEA,0x69,0x37,0xD5,0x8B,
    0x57,0x09,0xEB,0xB5,0x36,0x68,0x8A,0xD4,0x95,0xCB,0x29,0x77,0xF4,0xAA,0x48,0x16,
    0xE9,0xB7,0x55,0x0B,0x88,0xD6,0x34,0x6A,0x2B,0x75,0x97,0xC9,0x4A,0x14,0xF6,0xA8,
    0x74,0x2A,0xC8,0x96,0x15,0x4B,0xA9,0xF7,0xB6,0xE8,0x0A,0x54,0xD7,0x89,0x6B,0x35,
])


def crc8(data: bytes) -> int:
    """Calcula CRC8 usando la tabla hardcodeada exacta del firmware osc_usb.c."""
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

# Tamaño en bytes de medicion por canal (11 float32 + 1 byte valid)
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

    _MAX_BUF = 8192  # Si el buffer crece mas sin sync, se limpia

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
                # Sin sync — mantener solo el ultimo byte por si es inicio de sync
                if len(self._buf) > 1:
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
                # Necesitamos mas bytes
                break
            elif frame is False:
                # Frame invalido — saltar el sync actual y seguir buscando
                self.frames_error += 1
                del self._buf[:2]
            else:
                parsed.append(frame)
                self.frames_ok += 1

        # Sanity check: limpiar buffer si esta demasiado lleno sin avanzar
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
          - False  : frame invalido (CRC error o mal formato)
          - None   : datos insuficientes, esperar mas bytes
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
        Retorna los bytes del frame (sin CRC) si es valido, False si CRC falla, None si faltan bytes.
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
        # Cabecera minima: sync(2)+type(1)+flags(1)+seq(2)+count(2)+ts(4)+trig_idx(4) = 16 bytes
        HDR = 16
        if len(self._buf) < HDR + 1:  # +1 para CRC minimo
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

        # time_axis_us: placeholder — el eje temporal real en us se calcula
        # en el render loop usando sample_rate y trigger_index, ya que el
        # parser no conoce la tasa de muestreo configurada.
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
