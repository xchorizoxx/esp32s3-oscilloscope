# Communication Protocol

## Transport

- **Physical**: USB CDC-ACM over ESP32-S3 native USB OTG (GPIO19/20)
- **USB VID/PID**: `0x303A` / `0x4001` (Espressif default)
- **Baud rate**: irrelevant (USB bulk transfers, 115200 is nominal only)
- **Connection detected**: via `DTR || RTS` line state change

---

## Frame Structure

All binary frames share a common prefix:

```
[SYNC1: 0xAA] [SYNC2: 0x55] [FRAME_TYPE: 1 byte] [...payload...] [CRC8: 1 byte]
```

**CRC-8** is computed over **all bytes** including `SYNC1`, `SYNC2`, and `FRAME_TYPE`, using the lookup table hardcoded in `osc_usb.c` (CRC-8/MAXIM-DOW variant).

> ⚠️ Do NOT generate the table from poly `0x31` with the standard algorithm — the table does not match. Use the hardcoded table directly (see `tools/test_interface.py`).

---

## Frame Types

| Byte | Name | Direction | Description |
|------|------|-----------|-------------|
| `0x01` | DATA | ESP32 → PC | ADC sample data frame |
| `0x02` | MEASUREMENTS | ESP32 → PC | Automatic measurements |
| `0x03` | ACK | ESP32 → PC | Command accepted |
| `0x04` | NAK | ESP32 → PC | Command rejected |
| `0x05` | INFO | ESP32 → PC | Device capabilities |
| `0x06` | FFT | ESP32 → PC | FFT magnitude data |
| `0x07` | HEARTBEAT | ESP32 → PC | 1 Hz keep-alive |

---

## Frame Layouts

### DATA Frame (`0x01`)

```
Offset  Size  Field
──────  ────  ─────────────────────────────────────────────────────
0       1     SYNC1 = 0xAA
1       1     SYNC2 = 0x55
2       1     FRAME_TYPE = 0x01
3       1     FLAGS (see below)
4       2     SEQ_NUM (uint16 LE, wraps at 65535)
6       2     SAMPLE_COUNT (uint16 LE, samples per channel)
8       4     TIMESTAMP_US (uint32 LE, µs since boot)
12      4     TRIGGER_INDEX (uint32 LE, sample index of trigger event)
16      N*2   CH0_DATA (int16 LE array, N = SAMPLE_COUNT, units: mV×10)
16+N*2  N*2   CH1_DATA (int16 LE, only if CH1_VALID=1)
end     1     CRC8
```

**FLAGS byte:**

| Bit | Mask | Name | Meaning |
|-----|------|------|---------|
| 0 | `0x01` | CH0_VALID | CH0 data present |
| 1 | `0x02` | CH1_VALID | CH1 data present (dual mode) |
| 2 | `0x04` | TRIGGER_HIT | Trigger event was detected |
| 3 | `0x08` | OVERFLOW | DMA ring buffer overflowed |
| 4 | `0x10` | FFT_ATTACHED | FFT frame immediately follows |

**Sample encoding:** `int16` in units of **mV×10**. To convert: `voltage_mV = sample / 10.0`. Range: −3276.8 mV to +3276.7 mV.

---

### MEASUREMENTS Frame (`0x02`)

```
Offset  Size  Field
──────  ────  ─────────────────────────────────────────────────
0       1     SYNC1 = 0xAA
1       1     SYNC2 = 0x55
2       1     FRAME_TYPE = 0x02
3       1     FLAGS (same as DATA frame)
4       45    CH0 measurements (see below)
49      45    CH1 measurements (only if CH1_VALID=1)
end     1     CRC8
```

**Measurements block (45 bytes, per channel):**

```
Offset  Size  Field         Units
──────  ────  ────────────  ──────────────────
0       4     vpp_mv        float32 LE, mV
4       4     vrms_mv       float32 LE, mV
8       4     vdc_mv        float32 LE, mV
12      4     vac_rms_mv    float32 LE, mV
16      4     vmax_mv       float32 LE, mV
20      4     vmin_mv       float32 LE, mV
24      4     freq_hz       float32 LE, Hz
28      4     period_us     float32 LE, µs
32      4     duty_cycle    float32 LE, %
36      4     rise_time_us  float32 LE, µs (10%→90%)
40      4     fall_time_us  float32 LE, µs (90%→10%)
44      1     valid         uint8, 1=measurements valid
```

---

### INFO Frame (`0x05`)

Sent in response to `CMD_GET_CAPS`.

```
Offset  Size  Field
──────  ────  ─────────────────────────────────────────
0       1     SYNC1 = 0xAA
1       1     SYNC2 = 0x55
2       1     FRAME_TYPE = 0x05
3       1     VERSION_MAJOR
4       1     VERSION_MINOR
5       4     MAX_RATE_HZ (uint32 LE)
9       2     MAX_FRAME_SIZE (uint16 LE, samples)
11      2     CAPS_FLAGS (uint16 LE, see below)
13      32    FW_STRING (null-terminated, zero-padded)
45      1     CRC8
```

**CAPS_FLAGS:**

| Bit | Name | Meaning |
|-----|------|---------|
| 0 | `DUAL_CHANNEL` | Dual-channel mode supported |
| 1 | `FFT` | FFT supported |
| 2 | `OVERSAMPLE` | Oversampling mode supported |
| 3 | `CLOCK_HACK` | ADC rate > 83333 Hz available |

---

### ACK Frame (`0x03`)

```
Offset  Size  Field
──────  ────  ─────────────────────────
0       1     SYNC1 = 0xAA
1       1     SYNC2 = 0x55
2       1     FRAME_TYPE = 0x03
3       32    CMD_STRING (null-padded, echoes the command)
35      1     CRC8
```

---

### NAK Frame (`0x04`)

```
Offset  Size  Field
──────  ────  ─────────────────────────
0       1     SYNC1 = 0xAA
1       1     SYNC2 = 0x55
2       1     FRAME_TYPE = 0x04
3       32    CMD_STRING (null-padded)
35      32    REASON_STRING (null-padded)
67      1     CRC8
```

---

### FFT Frame (`0x06`)

```
Offset  Size     Field
──────  ───────  ─────────────────────────────────────────
0       1        SYNC1 = 0xAA
1       1        SYNC2 = 0x55
2       1        FRAME_TYPE = 0x06
3       1        FLAGS
4       2        SEQ_NUM (uint16 LE)
6       2        FFT_POINTS (uint16 LE, = N/2)
8       4        BIN_HZ_x100 (uint32 LE, Hz/bin × 100)
12      N/2 × 4  MAGNITUDES (float32 LE array, mV)
end     1        CRC8
```

---

## Commands (PC → ESP32)

Commands are **ASCII strings** terminated with `\n` (`0x0A`). Arguments separated by spaces.

| Command | Arguments | Response | Description |
|---------|-----------|----------|-------------|
| `CMD_GET_CAPS` | — | INFO frame + ACK | Query firmware capabilities |
| `CMD_STREAM_START` | — | ACK | Begin continuous DATA frame stream |
| `CMD_STREAM_STOP` | — | ACK | Stop stream |
| `CMD_SINGLE_SHOT` | — | ACK → DATA (on trigger) | Capture one triggered frame |
| `CMD_SET_MODE` | `<mode>` | ACK | `0`=SINGLE_CH `1`=DUAL_CH `2`=OVERSAMPLE |
| `CMD_SET_RATE` | `<hz>` | ACK | ADC rate in Hz (611–160000) |
| `CMD_SET_TRIG` | `<ch> <mv> <edge>` | ACK | ch: 0/1, mv: float, edge: 0=RISE 1=FALL 2=ANY 3=NONE |
| `CMD_SET_ATTEN` | `<ch> <db>` | ACK | ch: 0/1, db: 0=0dB 1=2.5dB 2=6dB 3=12dB |
| `CMD_SET_FRAME` | `<n>` | ACK | Frame size: 64/128/256/512/1024/2048/4096 |
| `CMD_SET_PRE_TRIG` | `<n>` | ACK | Pre-trigger samples (0 to frame_size/2) |
| `CMD_SET_FFT` | `<en>` | ACK | `0`=disable `1`=enable FFT |
| `CMD_FACTORY_RESET` | — | ACK | Restore defaults and save to NVS |
| `CMD_GET_STATUS` | — | MEASUREMENTS frame | Get current auto-measurements |

---

## Sync Recovery

The receiver must implement **sync byte scanning**:

1. Read bytes one by one until `0xAA` is found.
2. Check if next byte is `0x55`.
3. If not, continue scanning from step 1.
4. Once sync is confirmed, read `FRAME_TYPE`, then the fixed payload for that type.
5. Validate CRC. On failure, discard and return to step 1.

---

## CRC-8 Reference Implementation (Python)

```python
# Exact table from osc_usb.c — do not regenerate algorithmically
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
```
