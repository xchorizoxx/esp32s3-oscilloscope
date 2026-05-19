# Hardware Interface & Pin Mapping Reference

This document outlines the pin configurations, strapping constraints, voltage limits, and diagnostic loop setups for the ESP32-S3 Digital Oscilloscope.

---

## 📌 1. Pin Configuration Table

These mappings are designed and validated on the **ESP32-S3-DevKitC-1** board (N8R8 / N16R8 variants).

| Pin (GPIO) | Direction | Signal Identifier | Voltage Range | Hardware & Firmware Description |
|:---:|:---:|:---|:---:|:---|
| **GPIO1** | Input | ADC CH0 (Scope CH1) | $0.0 - 2.5\text{ V}$ | ADC1_CH0. Direct channel A input. Input protected. |
| **GPIO2** | Input | ADC CH1 (Scope CH2) | $0.0 - 2.5\text{ V}$ | ADC1_CH1. Direct channel B input. Active in dual mode. |
| **GPIO3** | Output | Built-in Test Signal | $0.0 / 3.3\text{ V}$ | LEDC hardware PWM generator. Outputs 1 kHz square-wave. |
| **GPIO48** | Output | Status Indicator LED | $0.0 / 3.3\text{ V}$ | Onboard RGB/LED. Driven HIGH when active streaming is enabled. |
| **GPIO19** | Native | Native USB D− | Differential | Internally routed to physical **"USB"** connector (Native OTG). |
| **GPIO20** | Native | Native USB D+ | Differential | Internally routed to physical **"USB"** connector (Native OTG). |
| **GPIO43** | Serial | UART Console TX | $3.3\text{ V}$ | Routed to CH340 / CP210x bridge on **"UART"** physical connector. |
| **GPIO44** | Serial | UART Console RX | $3.3\text{ V}$ | Routed to CH340 / CP210x bridge on **"UART"** physical connector. |
| **GPIO39** | Output | PGA Control Bit 0 | $0.0 / 3.3\text{ V}$ | Controls switch $S_0$ for resistor $R_1$ in active PGA feedback. |
| **GPIO40** | Output | PGA Control Bit 1 | $0.0 / 3.3\text{ V}$ | Controls switch $S_1$ for resistor $R_2$ in active PGA feedback. |
| **GPIO41** | Output | PGA Control Bit 2 | $0.0 / 3.3\text{ V}$ | Controls switch $S_2$ for resistor $R_3$ in active PGA feedback. |

---

## ⚡ 2. ADC Electrical Specifications & Protections

> [!WARNING]
> **Voltage Constraint Alert**: The ESP32-S3 internal SAR ADC is single-ended and referenced directly to **Signal Ground (GND)**.
> - **Input Range Limit**: The absolute maximum analog input voltage is **$3.3\text{ V}$**. Do not exceed **$3.6\text{ V}$** under any circumstance to prevent permanent hardware damage to the silicon rail.
> - **ADC Linearity Limit**: Although the rail handles up to $3.3\text{ V}$, the ADC output response begins compressing above **$2.5\text{ V}$** when using the $12\text{ dB}$ attenuator scheme.

### Signal Conditioning Best Practices
- **For Bipolar AC Signals**: The input signal must be shifted into the positive voltage domain by applying a DC offset (Virtual Ground) of $1.65\text{ V}$ using an active buffer or resistor divider.
- **For High Voltages**: Use a 10:1 passive divider (e.g., $900\text{ k}\Omega$ series resistor with $100\text{ k}\Omega$ shunt to ground) to measure up to $25\text{ V}$ safely.

---

## ⚠️ 3. Boot Strapping Pins

The ESP32-S3 monitors specific pins during the rising edge of the reset signal to determine the boot mode. Keep these restrictions in mind:

1. **GPIO0 (Boot Pin)**: Must **not** be held LOW during a power-on reset or hardware restart, as this forces the system into the ROM Serial Download Mode (UART flashing).
2. **GPIO3**: Used as the diagnostic test signal generator. While safe once booted, ensure no external low-impedance load pulls this pin hard LOW during boot.
3. **GPIO45**: Controls the default flash/PSRAM voltage select LDO ($1.8\text{ V}$ vs $3.3\text{ V}$). Keep open/pulled-down.
4. **GPIO46**: Monitored by the ROM bootloader to enable or disable console print statements during initial ROM startup.

---

## 🔌 4. Cable Connectivity Guide

To fully operate the oscilloscope, connect **two USB cables** to your host workstation:

```
                      ┌─────────────────────────────────┐
                      │            Host PC              │
                      └────┬────────────────────────┬───┘
                           │                        │
               [USB-C Console Cable]      [USB-C High-Speed Cable]
                           │                        │
                           ▼                        ▼
                      ┌──────────┐              ┌──────────┐
                      │  "UART"  │              │  "USB"   │
                      └────┬─────┘              └────┬─────┘
                           │ (COM Port /dev/ttyACM0)│ (COM Port /dev/ttyACM1)
                           │                        │
                           ▼                        ▼
                      ┌─────────────────────────────────┐
                      │    ESP32-S3-DevKitC-1 Board     │
                      └─────────────────────────────────┘
```

1. **Physical "UART" Port**:
   - Interfaces through an onboard USB-to-UART bridge.
   - Provides flashing capability (`idf.py flash`), low-level boot diagnostics, and the persistent FreeRTOS console monitor.
2. **Physical "USB" Port**:
   - Connects directly to the ESP32-S3 internal OTG transceiver.
   - Handles the custom binary stream (12 Mbps Bulk endpoints) when streaming is active, and receives real-time control parameters.
