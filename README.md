# ESP32-S3 Digital Oscilloscope

A dual-channel digital oscilloscope firmware for the **ESP32-S3** with USB CDC streaming, FFT analysis, and automatic measurements. Runs on ESP-IDF v6.0, communicates via a binary protocol over the native USB OTG peripheral.

## Hardware

- **MCU**: ESP32-S3 (tested on ESP32-S3-DevKitC-1 N8R8)
- **ADC**: Internal SAR ADC1 — 12-bit, up to **150 kHz** (clock hack applied)
- **USB**: Native USB OTG (GPIO19=D−, GPIO20=D+) → USB-C port labeled **"USB"** on the DevKit
- **Flash**: 8 MB, 240 MHz CPU, 8 MB Octal PSRAM @ 80 MHz

| Signal | GPIO | Notes |
|--------|------|-------|
| ADC Channel 0 (CH1) | **GPIO1** | ADC1_CH0, 0–2500 mV (12 dB atten) |
| ADC Channel 1 (CH2) | **GPIO2** | ADC1_CH1, 0–2500 mV (12 dB atten) |
| Test Signal (1 kHz PWM) | **GPIO3** | LEDC output for self-test |
| Status LED | **GPIO48** | On = transmitting |
| USB D− | **GPIO19** | Native USB OTG (internal) |
| USB D+ | **GPIO20** | Native USB OTG (internal) |
| UART TX (monitor) | **GPIO43** | UART0 — USB-C "UART" port |
| UART RX (monitor) | **GPIO44** | UART0 — USB-C "UART" port |

> ⚠️ GPIO1 and GPIO2 are input-only in some configurations. Do not exceed 2.5 V.

## Features

- Single-channel up to **~150 kHz** (ADC clock hack: `SOC_ADC_SAMPLE_FREQ_THRES_HIGH=160000`, `ADC_LL_CLKM_DIV_NUM_DEFAULT=8`)
- Dual-channel mode (interleaved, rate/2 per channel)
- Oversampling mode ×4/8/16 for higher effective resolution
- Hardware trigger: rising, falling, any edge — with pre-trigger buffer
- Auto-trigger fallback (configurable timeout)
- FFT up to 1024 points with Hanning/Hamming/Blackman/Rectangular window
- Automatic measurements: Vpp, Vrms, VDC, VAC-RMS, Vmax, Vmin, frequency, period, duty cycle, rise/fall time
- NVS-persisted configuration (survives power cycle)
- CRC-8 protected binary protocol

## Repository Structure

```
oscilloscope/
├── main/                   # App entry point, FreeRTOS task orchestration
├── components/
│   ├── osc_adc/            # ADC continuous-mode DMA driver
│   ├── osc_config/         # Thread-safe configuration + NVS persistence
│   ├── osc_dsp/            # DSP: calibration, measurements, FFT (esp-dsp)
│   ├── osc_trigger/        # Edge trigger engine
│   ├── osc_usb/            # TinyUSB CDC-ACM + binary protocol serializer
│   └── soc_override/       # ADC clock frequency hack component
├── pc_app/                 # Python PyQt6 desktop application
├── tools/
│   ├── test_interface.py   # USB CDC interface validation script
│   └── test_stream.py      # Streaming throughput/integrity test
├── docs/                   # Detailed technical documentation
│   ├── configuration.md
│   ├── pins.md
│   └── protocol.md
├── sdkconfig.defaults      # IDF Kconfig defaults
└── partitions.csv          # Flash partition table
```

## Quick Start

### Flash Firmware

```bash
# Source ESP-IDF v6.0
source ~/.espressif/v6.0/esp-idf/export.sh

# Build and flash (connect UART cable to "UART" port)
idf.py build flash monitor -p /dev/ttyACM0
```

### Connect & Test

```bash
# Connect a SECOND USB cable to the "USB" port on the DevKit
# A new /dev/ttyACM1 (VID 0x303A) will appear

pip install pyserial
python tools/test_interface.py
```

### PC Application

```bash
cd pc_app
pip install -r requirements.txt
python main.py
```

## Managed Dependencies

| Component | Version | Purpose |
|-----------|---------|---------|
| `espressif/esp_tinyusb` | 2.1.1 | USB CDC-ACM stack |
| `espressif/esp-dsp` | 1.8.1 | FFT (ANSI C, no Xtensa intrinsics required) |

## Technical Docs

- [Configuration Reference](docs/configuration.md)
- [Pin Mapping](docs/pins.md)
- [Binary Protocol](docs/protocol.md)
