# Guía de Calibración y Ajustes Técnicos

Este documento detalla los factores de corrección y calibración implementados tanto en el firmware (ESP32-S3) como en la aplicación de PC.

## 1. Calibración del ADC (Firmware)

El ESP32-S3 utiliza un ADC de aproximaciones sucesivas (SAR) que tiene variaciones de fabricación. Se utilizan tres niveles de calibración:

### A. Calibración por eFuse (IDF Standard)
El firmware utiliza la librería `esp_adc/adc_cali.h` con el esquema `curve_fitting`. 
- **Funcionamiento**: Lee los valores de referencia grabados en el chip durante la fabricación para compensar el error de ganancia y el offset.
- **Ubicación**: `components/osc_adc/osc_adc.c` -> `osc_adc_init()`.

### B. Corrección por Saturación (Manual)
Debido a que el ADC a 12dB de atenuación pierde linealidad drásticamente por encima de los 2500mV, se ha implementado un factor de corrección no-lineal.
- **Factor**: `1.037x` (Calculado comparando 3.268V medidos por multímetro vs 3.15V leídos por el ADC).
- **Lógica**: Solo se aplica si el voltaje calculado supera los `2500mV`.
- **Macros en `osc_adc.c`**:
  ```c
  #define OSC_ADC_CORRECTION_FACTOR  1.037f
  #define OSC_ADC_SATURATION_MV      2500
  ```
- **Nota**: Si en el futuro se añade un divisor de voltaje físico (ej. 1/10), este factor debe revisarse o eliminarse si la señal de entrada al pin se mantiene siempre por debajo de 2500mV.

## 2. Procesamiento de Señal (Firmware)

### Decimación por Promedio
Para escalas de tiempo lentas (alto T/div), el firmware realiza una decimación.
- **Antes**: Subsampling (saltar muestras). Causaba aliasing y ruido.
- **Ahora**: Averaging (acumulación y división). Actúa como un filtro paso-bajo que suaviza la señal y mejora la precisión aparente.
- **Ubicación**: `osc_adc.c` -> `adc_capture_task()`.

## 3. Ajustes en la App (PC)

### A. Digital AC Coupling
El acoplamiento AC se realiza mediante un filtro EMA (Exponential Moving Average) que resta la componente DC en tiempo real.
- **Ubicación**: `pc_app/ui/main_window.py` -> `_apply_ac_coupling()`.

### B. PGA Gain y Vertical Offset
La App permite aplicar una ganancia digital (zoom) y un offset vertical para facilitar la visualización.
- **PGA**: Multiplicador digital sobre los valores en mV.
- **Offset**: Suma/resta de valores en mV antes del renderizado.
- **Ubicación**: `pc_app/ui/waveform_widget.py`.

## 4. Sincronismo (Trigger)

### Histéresis Digital
Para evitar disparos falsos por ruido, el trigger tiene una ventana de histéresis de **±50mV**.
- **Lógica**: La señal debe cruzar el nivel de trigger Y haber estado previamente por fuera de la banda de histéresis.
- **Ubicación**: `components/osc_trigger/osc_trigger.c`.

---
*Última actualización: 26 de Abril, 2026*
