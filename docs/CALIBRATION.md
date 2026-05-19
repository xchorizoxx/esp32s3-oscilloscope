# Analog Front-End & Calibration Reference Manual

This document provides a comprehensive technical breakdown of the analog frontend, active Programmable Gain Amplifier (PGA), mathematical scaling models, and the calibration routines implemented in the firmware and PC application.

---

## 🔍 1. Analog Front-End Topology

To handle wide voltage sweeps while optimizing resolution, the input stage consists of a passive attenuator followed by an active non-inverting Programmable Gain Amplifier (PGA).

### Electronic Diagram

```
Analog Input (Vin) ──► [Input Divider (Div)] ──► Op-Amp Non-Inverting (+) Input
                                                    ┌───────────────┐
                                                 ┌──┤ -           V+├─► +3.3V
                                                 │  │               │
                                 Virtual Ground ─┴──┤ +         Vout├─► To ADC1_CH0
                                 (VG Bias Board)    │ -Vee          │
                                                    └───────┬───────┘
                                                            │
                                                            ├───► Feedback Resistor Rf (36kΩ)
                                                            │
                                                            ▼  Gain Switches (GPIO-driven)
                                                       ┌────┴────┐
                                                       ├─►[S0]───┼──► R1 (36kΩ)  [GPIO39]
                                                       ├─►[S1]───┼──► R2 (9.09kΩ)[GPIO40]
                                                       └─►[S2]───┼──► R3 (4.02kΩ)[GPIO41]
                                                                 │
                                                                 ▼
                                                            Virtual Ground (VG)
```

### Digital Control Matrix (8 Gain Steps)

The gain of the PGA is selected by controlling the states of three open-drain or push-pull switches ($S_0, S_1, S_2$) connected to the resistors $R_1, R_2, R_3$ leading to the Virtual Ground reference.

| Step | $S_2$ (GPIO41) | $S_1$ (GPIO40) | $S_0$ (GPIO39) | Equivalent Gain Resistor ($R_{eq}$) | Nominal Gain Factor |
|:---:|:---:|:---:|:---:|:---|:---:|
| **0** | Open | Open | Open | $\infty$ (No path to VG) | **x1.00** |
| **1** | Open | Open | Closed | $R_1 + R_{on}$ | **x2.00** |
| **2** | Open | Closed | Open | $R_2 + R_{on}$ | **x4.96** |
| **3** | Open | Closed | Closed | $(R_1 + R_{on}) \parallel (R_2 + R_{on})$ | **x5.96** |
| **4** | Closed | Open | Open | $R_3 + R_{on}$ | **x9.96** |
| **5** | Closed | Open | Closed | $(R_1 + R_{on}) \parallel (R_3 + R_{on})$ | **x10.96** |
| **6** | Closed | Closed | Open | $(R_2 + R_{on}) \parallel (R_3 + R_{on})$ | **x13.92** |
| **7** | Closed | Closed | Closed | $(R_1 + R_{on}) \parallel (R_2 + R_{on}) \parallel (R_3 + R_{on})$ | **x14.92** |

---

## 🧮 2. Mathematical Transfer Function

The voltage read by the ESP32-S3's internal 12-bit SAR ADC ($V_{adc}$) is governed by the following system equation:

$$V_{adc} = VG + \left[ (V_{in} \cdot Div) - VG \right] \cdot G_{nominal} \cdot GainTrim$$

Where:
- $V_{in}$: Raw input signal voltage at the oscilloscope probe.
- $Div$: Attenuation ratio of the passive input voltage divider (default: $\approx 0.0909$ for a 1/11 divider).
- $VG$: Virtual Ground offset voltage (typically set to $1650.0\text{ mV}$ to offset bidirectional AC signals into the ADC's safe $0 - 3.3\text{ V}$ window).
- $G_{nominal}$: The theoretical non-inverting gain determined by the feedback network:

$$G_{nominal} = 1 + \frac{R_f}{R_{eq}}$$

- $GainTrim$: Fine calibration software multiplier applied dynamically.

### Accounting for Switch On-Resistance ($R_{on}$)

GPIO internal hardware switches inside the ESP32-S3 have a parasitic drain-source on-resistance $R_{on}$ (typically $\approx 50.0\ \Omega$ at $3.3\text{ V}$). This parasitic resistance is accounted for by the software model to prevent gain compression at high gain factors:

$$R_{eq, i} = R_{nom, i} + R_{on}$$

---

## ⚙️ 3. PGA Calibration Routines

To guarantee absolute voltage readings on the GUI, two calibration parameters are loaded per gain step: **Gain Trim** and **Offset Calibration (mV)**.

### A. Automatic Auto-Calibration
The PC client coordinates an automated auto-calibration sequence. **Before running, the analog inputs must be connected to signal ground (0 V).**

1. **Virtual Ground Sweep**: The firmware measures the quiescent voltage on the channel to isolate $VG$.
2. **Step Verification**: The firmware steps through all 8 PGA combinations.
3. **Offset Calculation**: Since $V_{in} = 0\text{ V}$, any deviation from the expected $VG$ value at step $i$ is calculated as the active offset:

$$\text{Offset}_{cal}[i] = V_{adc, raw}[i] - VG$$

4. **NVS Serialization**: Once completed, the firmware commits the computed offset maps and fine calibration values permanently to Non-Volatile Storage (NVS).

---

## 📈 4. Internal SAR ADC Calibration

The ESP32-S3 internal analog-to-digital converter has non-linearities, particularly in the lower ($<100\text{ mV}$) and upper ($>2500\text{ mV}$) regions of the curve at 12 dB attenuation.

```mermaid
graph LR
    Raw[Raw 12-bit counts] --> EFuse[eFuse Curve Fitting]
    EFuse --> Uniform[Uniform Correction Factor]
    Uniform --> Out[Calibrated Millivolts * 10]
```

### A. eFuse Curve Fitting (ESP-IDF API)
At startup, `osc_adc_init()` registers a calibration handle utilizing the chip's internal eFuse calibration table:
- Compensates for individual reference voltage ($V_{ref}$) deviations recorded at the factory.
- Uses `adc_cali_raw_to_voltage()` from the `esp_adc/adc_cali_scheme.h` framework.

### B. Uniform Non-Linearity Correction (Dynamic)
To linearize the upper region of the ADC scale without introducing signal transitions or voltage jumps, a runtime-tunable global correction multiplier is applied uniformly across the entire input range of the channel:

```c
// Applied during raw ADC data conversion to mV in osc_adc.c
if (s_current_atten[ch_idx] == 3 && s_adc_correction_factor != 1.0f) {
    voltage_mv = (int)(voltage_mv * s_adc_correction_factor);
}
```

- **Default Factor**: `1.037f` (compels a raw reading of $3.15\text{ V}$ to register at its true $3.268\text{ V}$ level).
- **Run-time Safety**: Handled in-place inside `raw_to_mv10()`. Updated dynamically via `CMD_ADC_SET_CORRECTION` using thread-safe atomic writes without interrupting the DMA controller.
