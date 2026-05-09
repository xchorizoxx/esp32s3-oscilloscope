# AGENTS.md — ESP32-S3 Oscilloscope

## Build & Flash

```bash
source ~/.espressif/v6.0/esp-idf/export.sh   # ESP-IDF v6.0 required
idf.py build flash monitor -p /dev/ttyACM0    # UART port ("UART" label on DevKit)
```

- `idf.py build` — compile only
- `idf.py fullclean` — nuke build dir + managed components
- **Never** run `idf.py build/flash/clean` unless the user explicitly asks.

## Init Order

Components must init in this exact order:
1. `osc_config_init()` — mutex + NVS load
2. `osc_adc_init()` — reads config for channel mode/rate
3. `osc_dsp_init()` — precomputes FFT window tables
4. `osc_usb_init()` — **must be last**: TinyUSB takes over the USB serial console, logs stop appearing after this call

## Critical Hardware Quirks

- **GPIO1, GPIO2** are input-only on ESP32-S3. Max 2.5 V input voltage.
- **DMA buffers must live in internal RAM**: `heap_caps_malloc(..., MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA)`. PSRAM will not work for DMA.
- **ADC clock hack** (enables >83 kHz sampling): global compile defines `SOC_ADC_SAMPLE_FREQ_THRES_HIGH=160000` and `ADC_LL_CLKM_DIV_NUM_DEFAULT=8` injected via root `CMakeLists.txt` and `soc_override` component. Do not remove these.
- **Power management MUST be disabled** (`CONFIG_PM_ENABLE=n`). Enabling it destabilizes the ADC clock.
- **WiFi and BT are disabled** in sdkconfig — the hardware isn't used and enabling them costs RAM.

## USB / Two-Port Setup

The DevKit requires **two USB cables**:
- **"UART" port**: serial monitor, logs, `idf.py flash` (connected to USB-UART bridge, GPIO43/44)
- **"USB" port**: TinyUSB CDC-ACM data channel (native OTG, GPIO19/20)

After `osc_usb_init()`, the USB port enumerates as `/dev/ttyACM1` (VID `0x303A`). The PC app connects here. Serial logs via the UART port continue to work.

## Protocol Gotchas

- **CRC-8 table is non-standard**: The lookup table hardcoded in `osc_usb.c` does **not** match a standard CRC-8/MAXIM computed from poly `0x31` at runtime. Always copy/reuse the existing table — never regenerate it.
- Binary protocol docs: `docs/protocol.md`
- Command set and frame layouts: `components/osc_usb/include/osc_protocol.h`

## Architecture

- **Pure C** firmware (despite external `extern "C"` guards in headers — no C++ is used).
- **Task layout**: ADC_CAPTURE on Core 1 (prio 24, pinned), DSP_PROCESS on Core 0 (prio 10). USB command handling runs inside `osc_usb` on its own task.
- **Ping-pong double buffer** between ADC and DSP tasks (no mutex — queue messages act as ownership handoff).
- **NVS-persisted config** survives power cycles. `osc_config` wraps all access with a FreeRTOS mutex.

## Components

| Component | Purpose |
|-----------|---------|
| `osc_adc` | ADC continuous DMA driver, calibration, decimation |
| `osc_config` | Thread-safe config struct + NVS persistence |
| `osc_dsp` | FFT (esp-dsp), auto-measurements, channel separation |
| `osc_trigger` | Edge trigger with digital hysteresis (±50 mV) |
| `osc_usb` | TinyUSB CDC-ACM, binary protocol serialization, command parser |
| `osc_gen` | LEDC PWM test signal generator on GPIO3 |
| `soc_override` | Header-only component that redefines ADC clock macros |

## Dependencies

- `espressif/esp_tinyusb` ^2.1.1 — USB CDC stack
- `espressif/esp-dsp` ^1.8.1 — FFT library
- `managed_components/` is gitignored; ESP-IDF component manager fetches it at build time

## PC App

Separate Python application in `pc_app/`:
```bash
cd pc_app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 main.py           # production mode (needs ESP32)
python3 test_simulated.py # simulated mode (no hardware)
```

## Logging

- Tag convention: `osc_adc`, `osc_config`, `osc_usb`, etc. Top-level uses `osc_main`.
- Log level defaults to INFO, max DEBUG. Use `ESP_LOGI`/`ESP_LOGE`/`ESP_LOGD` — no `printf` or `std::cout`.
