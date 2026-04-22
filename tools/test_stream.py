#!/usr/bin/env python3
"""
test_stream.py — Verificador básico del stream binario del osciloscopio ESP32-S3.
Uso: python test_stream.py --port /dev/ttyACM0 [--duration 5]
"""
import argparse
import serial
import struct
import time
import sys

SYNC1 = 0xAA
SYNC2 = 0x55
FRAME_HEADER_SIZE = 12  # bytes antes de los samples
CRC8_TABLE = None


def crc8_init():
    global CRC8_TABLE
    CRC8_TABLE = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 0x80:
                crc = (crc << 1) ^ 0x31
            else:
                crc <<= 1
            crc &= 0xFF
        CRC8_TABLE.append(crc)


def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc = CRC8_TABLE[crc ^ b]
    return crc


def find_sync(port: serial.Serial) -> bool:
    """Busca el patrón de sincronización 0xAA 0x55 en el stream."""
    buf = bytearray(2)
    timeout = time.time() + 2.0
    while time.time() < timeout:
        b = port.read(1)
        if not b:
            continue
        buf[0] = buf[1]
        buf[1] = b[0]
        if buf[0] == SYNC1 and buf[1] == SYNC2:
            return True
    return False


def parse_frame(port: serial.Serial) -> dict | None:
    """Lee y parsea un frame completo después de encontrar el sync."""
    # Leer header (10 bytes restantes después del sync de 2 bytes)
    header = port.read(10)
    if len(header) < 10:
        return None

    frame_type, flags, seq_num, sample_count, timestamp_us = struct.unpack_from(
        '<BBHHI', header, 0
    )

    # Determinar cuántos canales hay activos
    ch1_valid = bool(flags & 0x01)
    ch2_valid = bool(flags & 0x02)
    trigger_hit = bool(flags & 0x04)
    overflow = bool(flags & 0x08)

    channels = (1 if ch1_valid else 0) + (1 if ch2_valid else 0)
    payload_size = sample_count * channels * 2  # int16 = 2 bytes

    payload = port.read(payload_size)
    if len(payload) < payload_size:
        return None

    crc_byte = port.read(1)
    if not crc_byte:
        return None

    # Verificar CRC
    all_data = bytes([SYNC1, SYNC2]) + header + payload
    expected_crc = crc8(all_data)
    if expected_crc != crc_byte[0]:
        return {'crc_error': True, 'seq': seq_num}

    # Parsear muestras
    ch1_samples = []
    ch2_samples = []
    if ch1_valid:
        ch1_raw = struct.unpack_from(f'<{sample_count}h', payload, 0)
        ch1_samples = [s / 10.0 for s in ch1_raw]  # mV*10 → mV
    if ch2_valid:
        offset = sample_count * 2
        ch2_raw = struct.unpack_from(f'<{sample_count}h', payload, offset)
        ch2_samples = [s / 10.0 for s in ch2_raw]

    return {
        'type': frame_type,
        'seq': seq_num,
        'count': sample_count,
        'timestamp_us': timestamp_us,
        'trigger_hit': trigger_hit,
        'overflow': overflow,
        'ch1': ch1_samples,
        'ch2': ch2_samples,
        'crc_ok': True,
    }


def main():
    crc8_init()
    parser = argparse.ArgumentParser(description='ESP32-S3 Oscilloscope Stream Tester')
    parser.add_argument('--port', required=True, help='Puerto serial (ej: /dev/ttyACM0)')
    parser.add_argument('--duration', type=float, default=5.0, help='Duración del test en segundos')
    args = parser.parse_args()

    print(f"[INFO] Abriendo {args.port}...")
    try:
        port = serial.Serial(args.port, baudrate=115200, timeout=1.0)
    except serial.SerialException as e:
        print(f"[ERROR] No se pudo abrir el puerto: {e}")
        sys.exit(1)

    time.sleep(0.5)

    # Enviar comando de capacidades
    print("[INFO] Enviando CMD_GET_CAPS...")
    port.write(b'CMD_GET_CAPS\n')
    time.sleep(0.3)
    caps_response = port.read(256)
    if caps_response:
        print(f"[CAPS] {caps_response.decode('utf-8', errors='replace').strip()}")

    # Iniciar stream
    print("[INFO] Enviando CMD_STREAM_START...")
    port.write(b'CMD_STREAM_START\n')
    time.sleep(0.1)

    frames_ok = 0
    frames_crc_err = 0
    frames_total = 0
    start_time = time.time()
    last_seq = -1

    print(f"[INFO] Recibiendo frames por {args.duration} segundos...")
    try:
        while time.time() - start_time < args.duration:
            if not find_sync(port):
                continue
            frame = parse_frame(port)
            if frame is None:
                continue
            frames_total += 1
            if frame.get('crc_error'):
                frames_crc_err += 1
                continue
            frames_ok += 1

            # Detectar frames perdidos
            if last_seq >= 0:
                expected = (last_seq + 1) & 0xFFFF
                if frame['seq'] != expected:
                    dropped = (frame['seq'] - expected) & 0xFFFF
                    print(f"[WARN] Frames perdidos: {dropped} (seq esperado: {expected}, recibido: {frame['seq']})")
            last_seq = frame['seq']

            if frames_ok % 50 == 0:
                ch1 = frame['ch1']
                vpp = max(ch1) - min(ch1) if ch1 else 0
                print(f"[DATA] seq={frame['seq']:5d} | samples={frame['count']:4d} | "
                      f"Vpp_ch1={vpp:.1f}mV | trig={'HIT' if frame['trigger_hit'] else '---'} | "
                      f"overflow={'!' if frame['overflow'] else 'OK'}")

    except KeyboardInterrupt:
        pass

    port.write(b'CMD_STREAM_STOP\n')
    port.close()

    elapsed = time.time() - start_time
    fps = frames_ok / elapsed if elapsed > 0 else 0
    print(f"\n{'='*60}")
    print(f"RESULTADO DEL TEST")
    print(f"{'='*60}")
    print(f"Duración:      {elapsed:.1f}s")
    print(f"Frames OK:     {frames_ok}")
    print(f"Frames CRC err:{frames_crc_err}")
    print(f"Frames/seg:    {fps:.1f}")
    print(f"Estado:        {'PASS ✓' if frames_ok > 0 and frames_crc_err == 0 else 'FAIL ✗'}")


if __name__ == '__main__':
    main()
