# Pin Mapping

## ESP32-S3-DevKitC-1 (N8R8 / N16R8)

### Signal Pins

| GPIO | Direction | Signal | Voltage | Notes |
|------|-----------|--------|---------|-------|
| **1** | Input | ADC CH0 (oscilloscope CH1) | 0–2500 mV | ADC1_CH0, 12-bit SAR |
| **2** | Input | ADC CH1 (oscilloscope CH2) | 0–2500 mV | ADC1_CH1, only in DUAL mode |
| **3** | Output | Test signal 1 kHz | 0/3.3 V | LEDC PWM, 50% duty, for self-test |
| **48** | Output | Status LED | 3.3 V | ON when USB streaming active |

### USB OTG (Native — physical "USB" connector)

| GPIO | Signal | Notes |
|------|--------|-------|
| **19** | USB D− | Connected internally to USB-C "USB" port |
| **20** | USB D+ | Connected internally to USB-C "USB" port |

> These pins are **not broken out** on most DevKits — they go directly to the USB-C connector labeled **"USB"**. Do not use GPIO19/20 for anything else.

### UART (Debug Monitor — physical "UART" connector)

| GPIO | Signal | Notes |
|------|--------|-------|
| **43** | UART0 TX | USB-C "UART" port (CH340/CP2102 bridge) |
| **44** | UART0 RX | USB-C "UART" port |

---

## USB Connectivity

The ESP32-S3-DevKitC-1 has **two USB-C ports**:

| Port Label | Chip | Linux Device | Purpose |
|------------|------|--------------|---------|
| **UART** | QinHeng CH340 (VID `0x1A86`) | `/dev/ttyACM0` | Flash firmware, serial monitor |
| **USB** | ESP32-S3 native USB OTG (VID `0x303A`) | `/dev/ttyACM1` | Oscilloscope data stream (CDC-ACM) |

Both can be connected simultaneously. The firmware requires the USB cable in the **"USB"** port to stream data.

---

## ADC Input Specifications

| Parameter | Value |
|-----------|-------|
| ADC resolution | 12-bit (0–4095 counts) |
| Reference | Internal, ~1.1 V |
| Attenuation (default 12 dB) | 0–2500 mV input range |
| Max safe input | 3.3 V (ADC input rail) |
| Absolute max | 3.6 V |
| Input impedance | ~200 kΩ (no external buffer) |
| Calibration | `curve_fitting` (ESP-IDF ADC calibration API) |

> ⚠️ **The ESP32-S3 ADC is single-ended, referenced to GND.** It cannot measure negative voltages. For AC signals, add a DC bias (e.g., 1.25 V divider).

---

## Strapping Pins (Avoid)

These ESP32-S3 pins affect boot mode — do not drive them at power-on:

| GPIO | Boot Function |
|------|--------------|
| 0 | Download mode if pulled LOW |
| 3 | JTAG if pulled LOW (used here as test output — safe, driven by firmware after boot) |
| 45 | VDD_SPI voltage select |
| 46 | ROM messages on/off |

---

## Connections Diagram

```
Host PC
  │
  ├── USB-C "UART" ──► CH340 ──► GPIO43/44 (flash & monitor, /dev/ttyACM0)
  │
  └── USB-C "USB"  ──► GPIO19/20 (oscilloscope CDC stream, /dev/ttyACM1)

Signal Source
  │
  ├── CH1 ──► GPIO1 (via 1:1 probe or resistive divider)
  └── CH2 ──► GPIO2 (optional, dual-channel mode only)

GPIO3 ──► Test output 1 kHz, loop to GPIO1 for self-test
```
