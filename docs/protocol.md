# Binary Communication Protocol Specification

This document details the low-overhead binary framing protocol used to transmit real-time waveform data, measurements, and Programmable Gain Amplifier (PGA) status parameters from the ESP32-S3 firmware to the PyQt6 PC host application.

---

## 🛰️ 1. Frame Structure & Serialization

All communication over the USB CDC-ACM link uses a structured packet architecture. Every frame begins with a **two-byte synchronization pattern**, followed by a **packet type**, **flags**, **sequence headers**, and ends with a **Dallas/Maxim CRC-8 checksum**.

### General Frame Envelope

```
┌───────────────┬───────────────┬───────────────┬───────────────┬───────────────────────────┬───────────────┐
│  SYNC1 (0x55) │  SYNC2 (0xAA) │  Frame Type   │     Flags     │          Payload          │  Dallas CRC8  │
│    (1 byte)   │    (1 byte)   │   (1 byte)    │   (1 byte)    │        (N bytes)          │   (1 byte)    │
└───────────────┴───────────────┴───────────────┴───────────────┴───────────────────────────┴───────────────┘
```

- **SYNC1 / SYNC2**: Standard preamble sequence (`0x55`, `0xAA`) to align stream readers.
- **Frame Type**: Identifies the payload layout (see Section 2).
- **Flags**: Bitmask carrying operational states (e.g., channel validation, trigger markers, overflows).
- **CRC-8 Checksum**: Standard Dallas/Maxim CRC-8 calculated over all preceding bytes in the packet.

---

## 📦 2. Packet Definitions & Payloads

### A. Data Frame (`0x01`)
Transmits high-speed captured raw wave samples and, optionally, real-time spectral FFT data.

*   **Flags Bitmask**:
    - `0x01`: Channel 0 (CH1) data valid.
    - `0x02`: Channel 1 (CH2) data valid.
    - `0x04`: Hardware trigger occurred during this acquisition.
    - `0x08`: DMA FIFO overflow occurred during capture.
    - `0x10`: Real-time FFT spectral payload is attached.

#### Header Layout (16 Bytes)

| Offset | Byte Count | Data Type | Field Name | Description |
|:---:|:---:|:---:|:---|:---|
| `0` | `1` | `uint8` | `SYNC1` | `0x55` |
| `1` | `1` | `uint8` | `SYNC2` | `0xAA` |
| `2` | `1` | `uint8` | `type` | `0x01` (Data Frame) |
| `3` | `1` | `uint8` | `flags` | Active channel & state bitmask |
| `4` | `2` | `uint16` | `seq_num` | Frame sequence number (increments monotonically) |
| `6` | `2` | `uint16` | `samples` | Number of samples ($S$) per channel in the payload |
| `8` | `4` | `uint32` | `timestamp`| System time of the first sample in microseconds |
| `12`| `4` | `uint32` | `trig_idx` | Index of the triggered sample inside the frame |

#### Payload Layout

- **Channel 0 Data Block**: $S \times \text{int16}$ array in millivolts multiplied by 10 (resolution: $0.1\text{ mV}$).
- **Channel 1 Data Block** *(Only if dual flags `0x02` is active)*: $S \times \text{int16}$ array.
- **FFT Spectral Block** *(Only if FFT flags `0x10` is active)*:
  - `uint16` (`fft_points`): Number of spectral points ($F$).
  - `float32` (`bin_width_hz`): Frequency step size of each spectral bin in Hz.
  - $F \times \text{float32}$ array: Spectral magnitude values.

- **Trailing Checksum**: `uint8` Dallas/Maxim CRC-8.

---

### B. Measurements Frame (`0x02`)
Transmits computed electrical parameters to the host PC application every 10 frames to avoid flooding the interface.

*   **Flags Bitmask**:
    - `0x01`: Channel 0 (CH1) measurements valid.
    - `0x02`: Channel 1 (CH2) measurements valid.

#### Struct Layout (Channel 0 & Channel 1 Serialized Consecutively)

Each channel measurements block occupies **45 bytes**:

| Offset | Byte Count | Data Type | Field Name | Units |
|:---:|:---:|:---:|:---|:---:|
| `0` | `4` | `float` | `vpp` | mV |
| `4` | `4` | `float` | `vrms` | mV |
| `8` | `4` | `float` | `vdc` | mV |
| `12`| `4` | `float` | `vac_rms` | mV |
| `16`| `4` | `float` | `vmax` | mV |
| `20`| `4` | `float` | `vmin` | mV |
| `24`| `4` | `float` | `freq` | Hz |
| `28`| `4` | `float` | `period` | µs |
| `32`| `4` | `float` | `duty` | % |
| `36`| `4` | `float` | `rise` | µs |
| `40`| `4` | `float` | `fall` | µs |
| `44`| `1` | `uint8` | `valid` | Boolean status |

- **Trailing Checksum**: `uint8` Dallas/Maxim CRC-8.

---

### C. PGA Status Frame (`0x08`)
Transmits the calibration parameters, nominal/effective gains, bandwidths, NVS status, and topology values.

#### Payload Structure

| Offset | Byte Count | Data Type | Field Name | Description |
|:---:|:---:|:---:|:---|:---|
| `0` | `1` | `uint8` | `step` | Active gain step ($0 - 7$) |
| `1` | `4` | `float` | `vg` | Virtual Ground bias level (mV) |
| `5` | `1` | `uint8` | `calibrated`| NVS Calibration flag (1 = Calibrated, 0 = Empty) |
| `6` | `1` | `uint8` | `enabled` | PGA driver power state (1 = Active, 0 = Inactive) |
| `7` | `32`| `float[8]` | `gain_eff` | Array of computed effective gains per step |
| `39`| `32`| `float[8]` | `gain_cal` | Array of calibration gain trim scalars per step |
| `71`| `32`| `float[8]` | `offset` | Array of calibration offsets (mV) per step |
| `103`| `32`| `float[8]` | `bw` | Array of physical -3dB analog bandwidths (Hz) |
| `135`| `4` | `float` | `div` | Input attenuator division ratio |
| `139`| `4` | `float` | `rf` | Feedback resistor $R_f$ value ($\Omega$) |
| `143`| `12`| `float[3]` | `r_nom` | Resistors $R_1, R_2, R_3$ values ($\Omega$) |
| `155`| `4` | `float` | `ron` | Internal Switch resistance $R_{on}$ ($\Omega$) |
| `159`| `4` | `float` | `vg_def` | Default persisted Virtual Ground voltage (mV) |

- **Trailing Checksum**: `uint8` Dallas/Maxim CRC-8.

---

### D. Response Packets (ACK / NAK)

Used to synchronize command handshakes.

- **ACK Packet (`0x0A`)**: Confirm command execution.
  - Payload: 32 bytes ASCII command echo.
- **NAK Packet (`0x0B`)**: Command rejected or failed.
  - Payload: 32 bytes ASCII command echo + 32 bytes ASCII failure description.

---

## 🧮 3. CRC-8 Maxim/Dallas Checksum

To guarantee packet validation, a CRC-8 code is computed using the polynomial $X^8 + X^5 + X^4 + 1$ (Value `0x31`, reversed `0x8C`).

> [!IMPORTANT]
> **CRC lookup optimization**: To avoid high computational loads in the FreeRTOS hot path, a precomputed table lookup is utilized by the firmware.

```c
// Precomputed Dallas/Maxim CRC-8 Lookup Table (Poly: 0x31)
static const uint8_t CRC8_TABLE[256] = {
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
};
```
