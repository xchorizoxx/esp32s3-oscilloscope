#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"
#include "osc_adc.h"
#include "osc_trigger.h"

#ifdef __cplusplus
extern "C" {
#endif

#define OSC_FFT_MAX_POINTS  1024  ///< máximo de puntos FFT soportados

/**
 * @brief Ventanas disponibles para FFT.
 */
typedef enum {
    OSC_FFT_WIN_RECTANGULAR = 0,
    OSC_FFT_WIN_HANNING     = 1,
    OSC_FFT_WIN_HAMMING     = 2,
    OSC_FFT_WIN_BLACKMAN    = 3,
} osc_fft_window_t;

/**
 * @brief Mediciones automáticas calculadas sobre un frame de muestras.
 */
typedef struct {
    float vpp_mv;         ///< Voltaje pico a pico
    float vrms_mv;        ///< Voltaje RMS (AC + DC)
    float vdc_mv;         ///< Componente DC (promedio)
    float vac_rms_mv;     ///< Componente AC RMS (sin DC)
    float vmax_mv;        ///< Máximo absoluto
    float vmin_mv;        ///< Mínimo absoluto
    float freq_hz;        ///< Frecuencia estimada (por cruces por cero)
    float period_us;      ///< Período en microsegundos
    float duty_cycle_pct; ///< Duty cycle en porcentaje (señales digitales)
    float rise_time_us;   ///< Tiempo de subida 10%→90%
    float fall_time_us;   ///< Tiempo de bajada 90%→10%
    bool  valid;          ///< true si las mediciones son confiables
} osc_measurements_t;

/**
 * @brief Frame de datos procesado listo para enviar por USB.
 */
typedef struct {
    uint16_t           seq_num;
    uint32_t           timestamp_us;
    uint16_t           sample_count;        ///< muestras por canal
    bool               ch0_valid;
    bool               ch1_valid;
    bool               trigger_hit;
    bool               overflow;
    uint32_t           trigger_index;
    int16_t           *ch0_data;            ///< puntero a array de int16_t (mV*10)
    int16_t           *ch1_data;            ///< NULL si modo single channel
    osc_measurements_t meas_ch0;
    osc_measurements_t meas_ch1;
    float             *fft_magnitudes_ch0;  ///< NULL si fft_enabled=false
    uint16_t           fft_points;
    float              fft_bin_hz;          ///< Hz por bin FFT
} osc_frame_t;

/**
 * @brief Inicializar el módulo DSP (pre-calcula tablas de ventanas, etc).
 */
esp_err_t osc_dsp_init(void);

/**
 * @brief Procesar un buffer de muestras RAW del ADC y producir un frame completo.
 *        Aplica: separación de canales, calibración, filtro de mediana,
 *        detección de trigger, cálculo de mediciones, FFT opcional.
 *
 * @param[in]  raw_samples  Buffer de muestras del osc_adc
 * @param[in]  count        Número de muestras en el buffer
 * @param[out] frame        Frame procesado (el llamador debe proveer los buffers internos)
 * @param[in]  trigger_res  Resultado del trigger (puede ser NULL)
 */
esp_err_t osc_dsp_process_frame(const osc_sample_t *raw_samples, size_t count,
                                 osc_frame_t *frame,
                                 const osc_trigger_result_t *trigger_res);

/**
 * @brief Calcular mediciones automáticas sobre un canal de datos.
 *
 * @param[in]  samples_mv10  Array de muestras en mV*10
 * @param[in]  count         Número de muestras
 * @param[in]  sample_rate   Frecuencia de muestreo en Hz (para cálculos temporales)
 * @param[out] meas          Mediciones calculadas
 */
esp_err_t osc_dsp_compute_measurements(const int16_t *samples_mv10, size_t count,
                                        uint32_t sample_rate,
                                        osc_measurements_t *meas);

/**
 * @brief Calcular FFT de un canal.
 *
 * @param[in]  samples_mv10  Array de muestras en mV*10
 * @param[in]  n             Número de puntos (potencia de 2, max OSC_FFT_MAX_POINTS)
 * @param[in]  window        Tipo de ventana a aplicar
 * @param[in]  sample_rate   Frecuencia de muestreo en Hz
 * @param[out] magnitudes    Array de magnitudes en mV (n/2 puntos)
 * @param[out] bin_hz        Resolución de frecuencia (Hz por bin)
 */
esp_err_t osc_dsp_compute_fft(const int16_t *samples_mv10, size_t n,
                               osc_fft_window_t window, uint32_t sample_rate,
                               float *magnitudes, float *bin_hz);

#ifdef __cplusplus
}
#endif
