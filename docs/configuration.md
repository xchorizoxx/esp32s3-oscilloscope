# Configuration Reference

## Overview

All configuration is managed by `osc_config` (component). It exposes a `osc_config_t` struct, persisted in NVS flash, and protected by a FreeRTOS mutex.

---

## `osc_config_t` Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `osc_mode_t` | `SINGLE_CH` | Acquisition mode (see below) |
| `sample_rate_hz` | `uint32_t` | `83333` | ADC clock rate in Hz (total across all channels) |
| `trigger_level_mv` | `float` | `1000.0` | Trigger threshold in millivolts |
| `trigger_edge` | `osc_trig_edge_t` | `RISING` | Edge detection mode |
| `trigger_channel` | `uint8_t` | `0` | Channel used for trigger (0=CH1, 1=CH2) |
| `ch_atten[2]` | `osc_atten_t[2]` | `12DB, 12DB` | ADC input attenuation per channel |
| `fft_enabled` | `bool` | `false` | Compute FFT in DSP task |
| `streaming` | `bool` | `false` | Active USB data streaming |
| `pre_trigger_samples` | `uint32_t` | `128` | Samples captured before trigger event |
| `frame_size` | `uint32_t` | `512` | Samples per channel per frame |
| `auto_trigger` | `bool` | `true` | Force frame capture if no trigger within timeout |
| `auto_trigger_timeout_ms` | `uint32_t` | `200` | Auto-trigger timeout in ms |
| `measurements_enabled` | `bool` | `true` | Compute Vpp/Vrms/freq/etc per frame |
| `oversample_factor` | `uint8_t` | `16` | Oversampling factor (OVERSAMPLE mode only) |

---

## Acquisition Modes

| Mode | Enum | Effective Rate (CH1) | Notes |
|------|------|----------------------|-------|
| Single channel | `OSC_MODE_SINGLE_CH` | = `sample_rate_hz` | Max throughput, 1 channel |
| Dual channel | `OSC_MODE_DUAL_CH` | `sample_rate_hz / 2` | Interleaved ADC, both channels active |
| Oversampling | `OSC_MODE_OVERSAMPLE` | `sample_rate_hz / factor` | Single channel, averages `factor` samples |

---

## Attenuation / Input Range

| Enum | dB | Full-Scale Range |
|------|----|-----------------|
| `OSC_ATTEN_0DB` | 0 dB | 0 – 750 mV |
| `OSC_ATTEN_2_5DB` | 2.5 dB | 0 – 1050 mV |
| `OSC_ATTEN_6DB` | 6 dB | 0 – 1300 mV |
| `OSC_ATTEN_12DB` | 12 dB | 0 – 2500 mV ← **default** |

---

## Trigger Modes

| Enum | Behavior |
|------|----------|
| `OSC_TRIG_EDGE_RISING` | Trigger on low→high crossing |
| `OSC_TRIG_EDGE_FALLING` | Trigger on high→low crossing |
| `OSC_TRIG_EDGE_ANY` | Either edge |
| `OSC_TRIG_NONE` | Free-run (no trigger condition) |

Hysteresis is applied internally to avoid false triggers on noise.  
`pre_trigger_samples` samples are buffered before the trigger point.

---

## ADC Clock Hack

The ESP32-S3 ADC normally caps at ~83 kHz. A compile-time override extends this:

```cmake
# CMakeLists.txt (root)
add_compile_options("-DSOC_ADC_SAMPLE_FREQ_THRES_HIGH=160000")
add_compile_options("-DADC_LL_CLKM_DIV_NUM_DEFAULT=8")
```

This allows rates up to ~150 kHz per channel in single-channel mode. Beyond ~120 kHz the signal quality degrades due to ADC settling time — acceptable for oscilloscope use but not precision measurement.

---

## NVS Persistence

- Config is loaded from NVS at boot via `osc_config_init()`.
- Write to NVS with `osc_config_save_nvs()`.
- Factory reset: `osc_config_factory_reset()` (resets to defaults and saves).
- NVS namespace: `osc_cfg` (see `osc_config.c`).

---

## FreeRTOS Tasks

| Task | Core | Priority | Stack | Description |
|------|------|----------|-------|-------------|
| `ADC_CAPTURE` | 1 | 10 | 4096 B | Reads DMA ring buffer, runs trigger, sends to DSP queue |
| `DSP_PROCESS` | 0 | 8 | 8192 B | Processes frames: calibration, measurements, FFT |
| `osc_cmd` | 0 | 5 | 4096 B | Handles incoming USB commands |
| `TinyUSB` | 0 | 20 | 4096 B | USB stack task (managed by esp_tinyusb) |

---

## sdkconfig.defaults Key Settings

```kconfig
CONFIG_IDF_TARGET="esp32s3"
CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240=y
CONFIG_ESPTOOLPY_FLASHSIZE_8MB=y

# PSRAM
CONFIG_SPIRAM=y
CONFIG_SPIRAM_MODE_OCT=y
CONFIG_SPIRAM_SPEED_80M=y
CONFIG_SPIRAM_USE_MALLOC=y
CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL=16384

# TinyUSB
CONFIG_TINYUSB_CDC_ENABLED=y
CONFIG_TINYUSB_CDC_RX_BUFSIZE=512
CONFIG_TINYUSB_CDC_TX_BUFSIZE=4096
CONFIG_TINYUSB_DEBUG_LEVEL=0

# ADC
CONFIG_ADC_CONTINUOUS_ISR_IRAM_SAFE=y
CONFIG_ADC_ONESHOT_CTRL_FUNC_IN_IRAM=y
```

---

## Flash Partition Table

| Name | Type | Offset | Size | Purpose |
|------|------|--------|------|---------|
| `nvs` | data/nvs | 0x9000 | 24 KB | Configuration persistence |
| `phy_init` | data/phy | 0xF000 | 4 KB | RF calibration |
| `factory` | app/factory | 0x10000 | 3 MB | Main application |
| `storage` | data/nvs | 0x310000 | 24 KB | User data storage |
