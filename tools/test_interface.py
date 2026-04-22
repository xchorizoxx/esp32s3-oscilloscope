#!/usr/bin/env python3
"""
test_interface.py — Test básico de la interfaz USB CDC del osciloscopio ESP32-S3.

Verifica:
  1. Detección del puerto CDC (VID 303a de Espressif)
  2. Conexión serial
  3. CMD_GET_CAPS → INFO frame
  4. CMD_STREAM_START → recibe frames de datos por ~3 segundos
  5. CMD_STREAM_STOP → detiene el stream
  6. Resumen con estadísticas

Uso:
  python test_interface.py                    # Auto-detecta puerto
  python test_interface.py --port /dev/ttyACM1  # Puerto manual
  python test_interface.py --duration 5       # Duración del stream test
"""
import argparse
import serial
import serial.tools.list_ports
import struct
import time
import sys

# --- Constantes del protocolo ---
SYNC1 = 0xAA
SYNC2 = 0x55
FRAME_DATA         = 0x01
FRAME_MEASUREMENTS = 0x02
FRAME_ACK          = 0x03
FRAME_NAK          = 0x04
FRAME_INFO         = 0x05

# CRC8 table — MUST match the hardcoded table in osc_usb.c
CRC8_TABLE = [
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
]

def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = CRC8_TABLE[crc ^ b]
    return crc


def find_osc_port() -> str | None:
    """Auto-detecta el puerto CDC del osciloscopio (VID Espressif 0x303A)."""
    for p in serial.tools.list_ports.comports():
        if p.vid == 0x303A:
            return p.device
    return None


def read_until_sync(port: serial.Serial, timeout_s: float = 3.0) -> bool:
    """Busca el patrón de sincronización 0xAA 0x55."""
    deadline = time.time() + timeout_s
    prev = 0
    while time.time() < deadline:
        b = port.read(1)
        if not b:
            continue
        if prev == SYNC1 and b[0] == SYNC2:
            return True
        prev = b[0]
    return False


def read_frame_after_sync(port: serial.Serial) -> dict | None:
    """Lee un frame completo después de haber encontrado el sync."""
    # Leer tipo de frame (1 byte)
    frame_type_raw = port.read(1)
    if not frame_type_raw:
        return None
    frame_type = frame_type_raw[0]

    if frame_type == FRAME_INFO:
        # INFO: major(1) + minor(1) + max_rate(4) + max_frame(2) + caps(2) +
        #        fw_string(32) + crc(1) = 43 bytes after type
        rest = port.read(43)
        if len(rest) < 43:
            return None
        major = rest[0]
        minor = rest[1]
        max_rate = struct.unpack_from('<I', rest, 2)[0]
        max_frame = struct.unpack_from('<H', rest, 6)[0]
        caps = struct.unpack_from('<H', rest, 8)[0]
        fw_str = rest[10:42].split(b'\x00')[0].decode('utf-8', errors='replace')
        crc_byte = rest[42]
        all_data = bytes([SYNC1, SYNC2, frame_type]) + rest[:42]
        expected = crc8(all_data)
        return {
            'type': 'INFO',
            'major': major,
            'minor': minor,
            'max_rate': max_rate,
            'max_frame': max_frame,
            'caps': caps,
            'fw_str': fw_str,
            'crc_ok': expected == crc_byte,
        }

    elif frame_type == FRAME_ACK:
        # ACK: cmd_str(32) + crc(1) = 33 bytes
        rest = port.read(33)
        if len(rest) < 33:
            return None
        cmd = rest[:32].split(b'\x00')[0].decode('utf-8', errors='replace')
        crc_byte = rest[32]
        all_data = bytes([SYNC1, SYNC2, frame_type]) + rest[:32]
        expected = crc8(all_data)
        return {'type': 'ACK', 'cmd': cmd, 'crc_ok': expected == crc_byte}

    elif frame_type == FRAME_NAK:
        # NAK: cmd_str(32) + reason(32) + crc(1) = 65 bytes
        rest = port.read(65)
        if len(rest) < 65:
            return None
        cmd = rest[:32].split(b'\x00')[0].decode('utf-8', errors='replace')
        reason = rest[32:64].split(b'\x00')[0].decode('utf-8', errors='replace')
        crc_byte = rest[64]
        all_data = bytes([SYNC1, SYNC2, frame_type]) + rest[:64]
        expected = crc8(all_data)
        return {'type': 'NAK', 'cmd': cmd, 'reason': reason, 'crc_ok': expected == crc_byte}

    elif frame_type == FRAME_DATA:
        # DATA header: flags(1) + seq(2) + count(2) + timestamp(4) + trig_idx(4) = 13 bytes
        hdr = port.read(13)
        if len(hdr) < 13:
            return None
        flags = hdr[0]
        seq, count = struct.unpack_from('<HH', hdr, 1)
        ts_us = struct.unpack_from('<I', hdr, 5)[0]
        trig_idx = struct.unpack_from('<I', hdr, 9)[0]

        ch0_valid = bool(flags & 0x01)
        ch1_valid = bool(flags & 0x02)
        channels = (1 if ch0_valid else 0) + (1 if ch1_valid else 0)
        payload_size = count * channels * 2

        payload = port.read(payload_size)
        if len(payload) < payload_size:
            return None

        crc_raw = port.read(1)
        if not crc_raw:
            return None

        all_data = bytes([SYNC1, SYNC2, frame_type]) + hdr + payload
        expected = crc8(all_data)

        ch0_samples = []
        if ch0_valid and count > 0:
            ch0_raw = struct.unpack_from(f'<{count}h', payload, 0)
            ch0_samples = [s / 10.0 for s in ch0_raw]  # mV*10 → mV

        return {
            'type': 'DATA',
            'seq': seq,
            'count': count,
            'timestamp_us': ts_us,
            'trigger_hit': bool(flags & 0x04),
            'overflow': bool(flags & 0x08),
            'ch0_min': min(ch0_samples) if ch0_samples else 0,
            'ch0_max': max(ch0_samples) if ch0_samples else 0,
            'ch0_avg': sum(ch0_samples) / len(ch0_samples) if ch0_samples else 0,
            'crc_ok': expected == crc_raw[0],
        }

    else:
        # Frame desconocido, descartar
        return {'type': 'UNKNOWN', 'frame_type': frame_type, 'crc_ok': False}


def send_cmd(port: serial.Serial, cmd: str):
    """Envía un comando ASCII terminado en newline."""
    port.write(f'{cmd}\n'.encode())
    port.flush()


def test_get_caps(port: serial.Serial) -> dict | None:
    """Envía CMD_GET_CAPS y espera INFO + ACK."""
    port.reset_input_buffer()
    send_cmd(port, 'CMD_GET_CAPS')
    time.sleep(0.3)

    info = None
    ack = None
    attempts = 0
    while attempts < 10:
        if not read_until_sync(port, timeout_s=2.0):
            break
        frame = read_frame_after_sync(port)
        if not frame:
            break
        if frame['type'] == 'INFO':
            info = frame
        elif frame['type'] == 'ACK':
            ack = frame
            break
        attempts += 1

    return info


def test_stream(port: serial.Serial, duration: float) -> dict:
    """Inicia stream, recibe frames por `duration` segundos, detiene."""
    port.reset_input_buffer()
    send_cmd(port, 'CMD_STREAM_START')
    time.sleep(0.1)

    stats = {
        'frames_ok': 0,
        'frames_crc_err': 0,
        'frames_total': 0,
        'seq_gaps': 0,
        'last_seq': -1,
        'vmin': float('inf'),
        'vmax': float('-inf'),
    }

    start = time.time()
    while time.time() - start < duration:
        if not read_until_sync(port, timeout_s=1.0):
            continue
        frame = read_frame_after_sync(port)
        if not frame or frame['type'] != 'DATA':
            continue

        stats['frames_total'] += 1
        if not frame.get('crc_ok', False):
            stats['frames_crc_err'] += 1
            continue
        stats['frames_ok'] += 1

        if stats['last_seq'] >= 0:
            expected = (stats['last_seq'] + 1) & 0xFFFF
            if frame['seq'] != expected:
                stats['seq_gaps'] += 1
        stats['last_seq'] = frame['seq']

        if frame['ch0_min'] < stats['vmin']:
            stats['vmin'] = frame['ch0_min']
        if frame['ch0_max'] > stats['vmax']:
            stats['vmax'] = frame['ch0_max']

    send_cmd(port, 'CMD_STREAM_STOP')
    time.sleep(0.2)
    stats['elapsed'] = time.time() - start
    stats['fps'] = stats['frames_ok'] / stats['elapsed'] if stats['elapsed'] > 0 else 0
    return stats


def main():

    parser = argparse.ArgumentParser(description='ESP32-S3 Oscilloscope Interface Tester')
    parser.add_argument('--port', default=None, help='Puerto serial (auto-detecta si no se especifica)')
    parser.add_argument('--duration', type=float, default=3.0, help='Duración del stream test en segundos')
    args = parser.parse_args()

    print('=' * 60)
    print('  ESP32-S3 Oscilloscope — Test de Interfaz USB CDC')
    print('=' * 60)

    # --- Paso 1: Detectar puerto ---
    port_name = args.port
    if not port_name:
        print('\n[1/4] Buscando puerto CDC del osciloscopio (VID 0x303A)...')
        port_name = find_osc_port()
        if not port_name:
            print('  ❌ No se encontró dispositivo Espressif CDC.')
            print('     Dispositivos disponibles:')
            for p in serial.tools.list_ports.comports():
                vid = f'0x{p.vid:04X}' if p.vid else '----'
                pid = f'0x{p.pid:04X}' if p.pid else '----'
                print(f'       {p.device}  VID={vid} PID={pid}  {p.description}')
            print()
            print('  💡 ¿Conectaste un cable USB al puerto "USB" del DevKit?')
            print('     (No al UART, sino al otro conector USB-C)')
            sys.exit(1)
        print(f'  ✅ Encontrado: {port_name}')
    else:
        print(f'\n[1/4] Usando puerto manual: {port_name}')

    # --- Paso 2: Abrir conexión ---
    print('\n[2/4] Abriendo conexión serial...')
    try:
        port = serial.Serial(port_name, baudrate=115200, timeout=1.0)
    except serial.SerialException as e:
        print(f'  ❌ Error abriendo puerto: {e}')
        sys.exit(1)
    time.sleep(0.5)
    print(f'  ✅ Conectado a {port_name}')

    # --- Paso 3: CMD_GET_CAPS ---
    print('\n[3/4] Enviando CMD_GET_CAPS...')
    info = test_get_caps(port)
    if info:
        print(f'  ✅ INFO frame recibido:')
        print(f'     Firmware:    {info["fw_str"]} (v{info["major"]}.{info["minor"]})')
        print(f'     Max Rate:    {info["max_rate"]} Hz')
        print(f'     Max Frame:   {info["max_frame"]} samples')
        caps_list = []
        if info['caps'] & 0x01: caps_list.append('DUAL_CH')
        if info['caps'] & 0x02: caps_list.append('FFT')
        if info['caps'] & 0x04: caps_list.append('OVERSAMPLE')
        if info['caps'] & 0x08: caps_list.append('CLOCK_HACK')
        print(f'     Capacidades: {", ".join(caps_list)}')
        print(f'     CRC:         {"✅ OK" if info["crc_ok"] else "❌ ERROR"}')
    else:
        print('  ⚠️  No se recibió INFO frame (timeout)')
        print('     El dispositivo puede no haber respondido.')

    # --- Paso 4: Stream test ---
    print(f'\n[4/4] Test de stream ({args.duration}s)...')
    print(f'     (ADC en el aire = esperando ruido aleatorio)')
    stats = test_stream(port, args.duration)
    port.close()

    print(f'\n{"=" * 60}')
    print(f'  RESULTADO DEL TEST')
    print(f'{"=" * 60}')
    print(f'  Duración:        {stats["elapsed"]:.1f}s')
    print(f'  Frames OK:       {stats["frames_ok"]}')
    print(f'  Frames CRC err:  {stats["frames_crc_err"]}')
    print(f'  Frames/seg:      {stats["fps"]:.1f}')
    print(f'  Gaps de seq:     {stats["seq_gaps"]}')
    if stats['frames_ok'] > 0:
        print(f'  CH0 Vmin:        {stats["vmin"]:.1f} mV')
        print(f'  CH0 Vmax:        {stats["vmax"]:.1f} mV')
        print(f'  CH0 Vpp:         {stats["vmax"] - stats["vmin"]:.1f} mV')
    print()

    if stats['frames_ok'] > 0 and stats['frames_crc_err'] == 0:
        print('  🟢 PASS — Interfaz USB CDC funcionando correctamente')
    elif stats['frames_ok'] > 0:
        print('  🟡 WARN — Frames recibidos pero con errores CRC')
    else:
        print('  🔴 FAIL — No se recibieron frames de datos')
        print('     Verifica que el cable USB esté en el puerto "USB" del DevKit')
    print()


if __name__ == '__main__':
    main()
