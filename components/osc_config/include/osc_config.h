#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================================
 * Tipos públicos
 * ========================================================================= */

typedef enum {
    OSC_MODE_SINGLE_CH1 = 0,  ///< 1 canal (CH1), máxima velocidad
    OSC_MODE_SINGLE_CH2 = 1,  ///< 1 canal (CH2), máxima velocidad
    OSC_MODE_DUAL_CH    = 2,  ///< 2 canales interleaved, velocidad/2
} osc_mode_t;

typedef enum {
    OSC_TRIG_EDGE_RISING  = 0,
    OSC_TRIG_EDGE_FALLING = 1,
    OSC_TRIG_EDGE_ANY     = 2,
    OSC_TRIG_NONE         = 3,  ///< sin trigger, freerun continuo
} osc_trig_edge_t;

typedef enum {
    OSC_ATTEN_0DB   = 0,  ///< 0–750 mV full scale
    OSC_ATTEN_2_5DB = 1,  ///< 0–1050 mV
    OSC_ATTEN_6DB   = 2,  ///< 0–1300 mV
    OSC_ATTEN_12DB  = 3,  ///< 0–2500 mV (default, recomendado)
} osc_atten_t;

typedef struct {
    osc_mode_t      mode;
    uint32_t        sample_rate_hz;        ///< Hz totales del ADC
    float           trigger_level_mv;      ///< nivel de trigger en mV
    osc_trig_edge_t trigger_edge;
    uint8_t         trigger_channel;       ///< 0=CH1, 1=CH2
    osc_atten_t     ch_atten[2];           ///< atenuación por canal
    bool            fft_enabled;           ///< habilitar FFT en DSP task
    bool            streaming;             ///< streaming continuo activo
    uint32_t        pre_trigger_samples;   ///< muestras a guardar antes del trigger
    uint32_t        frame_size;            ///< muestras por canal por frame
    bool            auto_trigger;          ///< forzar captura si no hay trigger
    uint32_t        auto_trigger_timeout_ms;
    bool            measurements_enabled;  ///< calcular Vpp/Vrms/etc en DSP
    uint8_t         oversample_factor;     ///< solo en OVERSAMPLE mode: 4/8/16
    float           adc_correction_factor; ///< corrección no-lineal ADC 12dB (1.0-1.1)

    /* PGA (Programmable Gain Amplifier) */
    uint8_t         pga_step;              ///< paso de ganancia PGA 0-7
    bool            pga_enabled;           ///< PGA habilitado
    float           pga_vg_mv;             ///< VG (virtual ground) en mV
} osc_config_t;

/** Configuración por defecto */
#define OSC_CONFIG_DEFAULT() {                       \
    .mode                     = OSC_MODE_SINGLE_CH1, \
    .sample_rate_hz           = 83333,               \
    .trigger_level_mv         = 1000.0f,             \
    .trigger_edge             = OSC_TRIG_EDGE_RISING,\
    .trigger_channel          = 0,                   \
    .ch_atten                 = {OSC_ATTEN_12DB,     \
                                    OSC_ATTEN_12DB}, \
    .fft_enabled              = false,               \
    .streaming                = false,               \
    .pre_trigger_samples      = 128,                 \
    .frame_size               = 512,                 \
    .auto_trigger             = true,                \
    .auto_trigger_timeout_ms  = 200,                 \
    .measurements_enabled     = true,                \
    .oversample_factor        = 1,                   \
    .adc_correction_factor    = 1.037f,              \
    .pga_step                 = 0,                   \
    .pga_enabled              = false,               \
    .pga_vg_mv                = 1450.0f,             \
}

/* =========================================================================
 * API pública
 * ========================================================================= */

/**
 * @brief Inicializar el módulo de configuración. Llama antes de todo lo demás.
 *        Crea el mutex interno. Intenta cargar configuración desde NVS.
 */
esp_err_t osc_config_init(void);

/** @brief Obtener copia de la configuración actual (thread-safe). */
esp_err_t osc_config_get(osc_config_t *out_cfg);

/**
 * @brief Aplicar una configuración completa nueva (thread-safe).
 *        Dispara un evento interno para que ADC/DSP se reconfiguren.
 */
esp_err_t osc_config_set(const osc_config_t *cfg);

/* Setters granulares (thread-safe, cada uno llama a osc_config_set internamente) */
esp_err_t osc_config_set_mode(osc_mode_t mode);
esp_err_t osc_config_set_rate(uint32_t hz);
esp_err_t osc_config_set_trigger(float level_mv, osc_trig_edge_t edge, uint8_t ch);
esp_err_t osc_config_set_atten(uint8_t ch, osc_atten_t atten);
esp_err_t osc_config_set_streaming(bool en);
esp_err_t osc_config_set_fft(bool en);
esp_err_t osc_config_set_frame_size(uint32_t n);
esp_err_t osc_config_set_pre_trigger(uint32_t samples);
esp_err_t osc_config_set_oversample(uint8_t factor);
esp_err_t osc_config_set_pga_step(uint8_t step);
esp_err_t osc_config_set_pga_enabled(bool en);
esp_err_t osc_config_set_pga_vg(float vg_mv);
esp_err_t osc_config_set_adc_correction(float factor);

/** @brief Persistir configuración en NVS flash. */
esp_err_t osc_config_save_nvs(void);

/** @brief Cargar configuración desde NVS (se llama automáticamente en init). */
esp_err_t osc_config_load_nvs(void);

/** @brief Restaurar valores de fábrica y guardar en NVS. */
esp_err_t osc_config_factory_reset(void);

#ifdef __cplusplus
}
#endif
