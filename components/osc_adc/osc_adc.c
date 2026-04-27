#include "osc_adc.h"
#include "osc_config.h"
#include "esp_adc/adc_continuous.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_rom_sys.h"
#include <string.h>
#include <stdlib.h>

static const char *TAG = "osc_adc";

/* --------------------------------------------------------------------------
 * Estado interno
 * -------------------------------------------------------------------------- */
static adc_continuous_handle_t  s_adc_handle  = NULL;
static adc_cali_handle_t        s_cali_handle[2] = {NULL, NULL};
static volatile uint32_t        s_overflow_count = 0;
static TaskHandle_t             s_notify_task = NULL;

/* Rango máximo en mV por índice de atenuación (ADC_ATTEN_DB_0/2.5/6/12)
 * Valores del datasheet ESP32-S3, típicos a 25°C, VDD=3.3V.
 */
static const int s_atten_full_scale_mv[4] = {
    950,    // ADC_ATTEN_DB_0
    1250,   // ADC_ATTEN_DB_2_5
    1750,   // ADC_ATTEN_DB_6
    2500,   // ADC_ATTEN_DB_12 (era 3100, corregido a 2500)
};

// Caché de atenuación para evitar mutex en el hot path
static uint8_t s_current_atten[2] = {3, 3};

/* --- Factores de Corrección --- */
#define OSC_ADC_CORRECTION_FACTOR  1.037f   // Ajuste para 12dB (3.268V / 3.15V)
#define OSC_ADC_SATURATION_MV      2500     // Punto donde empieza la corrección no-lineal

/* Estado del filtro y decimación — se inicializa/resetea en osc_adc_start() */
static int32_t  s_acc_ch0 = 0;
static int32_t  s_acc_ch1 = 0;
static uint32_t s_acc_count = 0;
static int16_t  s_last_ch0 = 0;
static bool     s_has_ch0  = false;

static void reset_filter_state(void)
{
    s_acc_ch0 = 0;
    s_acc_ch1 = 0;
    s_acc_count = 0;
    s_last_ch0   = 0;
    s_has_ch0    = false;
}

/* Ring buffer para muestras procesadas */
#define SAMPLE_RING_SIZE  2048   // en osc_sample_t
static osc_sample_t   s_ring[SAMPLE_RING_SIZE];
static volatile int   s_ring_head = 0;  // escritura
static volatile int   s_ring_tail = 0;  // lectura
static SemaphoreHandle_t s_ring_mutex = NULL;
static SemaphoreHandle_t s_data_ready = NULL;

/* Buffer DMA raw del driver */
#define RAW_READ_BUF_SIZE  (OSC_ADC_DMA_BUF_SIZE)
static uint8_t s_raw_buf[RAW_READ_BUF_SIZE];

/* --------------------------------------------------------------------------
 * ISR callback (IRAM_ATTR — debe ser rápida)
 * -------------------------------------------------------------------------- */
static IRAM_ATTR bool adc_conv_done_cb(adc_continuous_handle_t handle,
                                        const adc_continuous_evt_data_t *edata,
                                        void *user_data)
{
    BaseType_t high_prio_task_woken = pdFALSE;
    if (s_notify_task) {
        vTaskNotifyGiveFromISR(s_notify_task, &high_prio_task_woken);
    }
    return high_prio_task_woken == pdTRUE;
}

static IRAM_ATTR bool adc_pool_overflow_cb(adc_continuous_handle_t handle,
                                             const adc_continuous_evt_data_t *edata,
                                             void *user_data)
{
    s_overflow_count++;
    return false;
}

/* --------------------------------------------------------------------------
 * Inicialización de calibración por canal
 * -------------------------------------------------------------------------- */
static esp_err_t init_calibration(adc_unit_t unit, adc_channel_t channel,
                                   adc_atten_t atten, adc_cali_handle_t *out_handle)
{
    esp_err_t ret = ESP_FAIL;

#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    adc_cali_curve_fitting_config_t cali_cfg = {
        .unit_id   = unit,
        .chan      = channel,
        .atten     = atten,
        .bitwidth  = OSC_ADC_BITWIDTH,
    };
    ret = adc_cali_create_scheme_curve_fitting(&cali_cfg, out_handle);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "Calibración curve_fitting OK ch%d", channel);
        return ESP_OK;
    }
#endif

#if ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED
    adc_cali_line_fitting_config_t lf_cfg = {
        .unit_id   = unit,
        .atten     = atten,
        .bitwidth  = OSC_ADC_BITWIDTH,
    };
    ret = adc_cali_create_scheme_line_fitting(&lf_cfg, out_handle);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "Calibración line_fitting OK ch%d", channel);
        return ESP_OK;
    }
#endif

    ESP_LOGW(TAG, "Sin calibración disponible para ch%d, usando raw", channel);
    *out_handle = NULL;
    return ESP_OK;  // No es fatal
}

/* --------------------------------------------------------------------------
 * API pública
 * -------------------------------------------------------------------------- */
esp_err_t osc_adc_init(void)
{
    if (s_adc_handle) {
        ESP_LOGW(TAG, "Ya inicializado, llamar osc_adc_reconfigure() para cambiar config");
        return ESP_OK;
    }

    s_ring_mutex = xSemaphoreCreateMutex();
    s_data_ready = xSemaphoreCreateBinary();
    if (!s_ring_mutex || !s_data_ready) return ESP_ERR_NO_MEM;

    osc_config_t cfg;
    osc_config_get(&cfg);

    // --- Configurar handle del ADC continuo ---
    adc_continuous_handle_cfg_t handle_cfg = {
        .max_store_buf_size = OSC_ADC_POOL_SIZE,
        .conv_frame_size    = OSC_ADC_DMA_BUF_SIZE,
        .flags = {
            .flush_pool = true,  // descartar datos viejos si el pool se llena
        },
    };
    ESP_ERROR_CHECK(adc_continuous_new_handle(&handle_cfg, &s_adc_handle));

    // --- Patrón de canales ---
    uint8_t n_channels = (cfg.mode == OSC_MODE_SINGLE_CH || cfg.mode == OSC_MODE_OVERSAMPLE) ? 1 : 2;
    adc_digi_pattern_config_t pattern[2];

    // Mapeo de osc_atten_t → adc_atten_t (valores idénticos en ESP-IDF)
    adc_atten_t atten0 = (adc_atten_t)cfg.ch_atten[0];
    adc_atten_t atten1 = (adc_atten_t)cfg.ch_atten[1];

    pattern[0] = (adc_digi_pattern_config_t){
        .atten    = atten0,
        .channel  = ADC_CHANNEL_0,  // GPIO1
        .unit     = ADC_UNIT_1,
        .bit_width = OSC_ADC_BITWIDTH,
    };
    if (n_channels == 2) {
        pattern[1] = (adc_digi_pattern_config_t){
            .atten    = atten1,
            .channel  = ADC_CHANNEL_1,  // GPIO2
            .unit     = ADC_UNIT_1,
            .bit_width = OSC_ADC_BITWIDTH,
        };
    }

    // El ESP32-S3 solo soporta entre 20kHz y 83.3kHz en modo continuo.
    // Para frecuencias menores, usamos 20kHz y diezmamos en software.
    uint32_t hw_rate = cfg.sample_rate_hz;
    if (hw_rate < 20000) hw_rate = 20000;
    if (hw_rate > 83333) hw_rate = 83333;

    adc_continuous_config_t dig_cfg = {
        .pattern_num    = n_channels,
        .adc_pattern    = pattern,
        .sample_freq_hz = hw_rate,
        .conv_mode      = ADC_CONV_SINGLE_UNIT_1,
        .format         = ADC_DIGI_OUTPUT_FORMAT_TYPE2,
    };
    ESP_ERROR_CHECK(adc_continuous_config(s_adc_handle, &dig_cfg));

    // --- Registrar callbacks ---
    adc_continuous_evt_cbs_t cbs = {
        .on_conv_done     = adc_conv_done_cb,
        .on_pool_ovf      = adc_pool_overflow_cb,
    };
    ESP_ERROR_CHECK(adc_continuous_register_event_callbacks(s_adc_handle, &cbs, NULL));

    // --- Inicializar calibración ---
    init_calibration(ADC_UNIT_1, ADC_CHANNEL_0, atten0, &s_cali_handle[0]);
    if (n_channels == 2) {
        init_calibration(ADC_UNIT_1, ADC_CHANNEL_1, atten1, &s_cali_handle[1]);
    }

    ESP_LOGI(TAG, "ADC init OK: %d ch @ %lu Hz", n_channels, cfg.sample_rate_hz);
    s_current_atten[0] = (uint8_t)cfg.ch_atten[0];
    s_current_atten[1] = (uint8_t)cfg.ch_atten[1];
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_adc_start(void)
{
    if (!s_adc_handle) return ESP_ERR_INVALID_STATE;
    reset_filter_state();
    s_notify_task = xTaskGetCurrentTaskHandle();
    return adc_continuous_start(s_adc_handle);
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_adc_stop(void)
{
    if (!s_adc_handle) return ESP_OK;

    adc_continuous_stop(s_adc_handle);
    adc_continuous_deinit(s_adc_handle);
    s_adc_handle  = NULL;
    s_notify_task = NULL;

    for (int i = 0; i < 2; i++) {
        if (s_cali_handle[i]) {
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
            adc_cali_delete_scheme_curve_fitting(s_cali_handle[i]);
#elif ADC_CALI_SCHEME_LINE_FITTING_SUPPORTED
            adc_cali_delete_scheme_line_fitting(s_cali_handle[i]);
#endif
            s_cali_handle[i] = NULL;
        }
    }

    if (s_ring_mutex)  { vSemaphoreDelete(s_ring_mutex);  s_ring_mutex = NULL; }
    if (s_data_ready)  { vSemaphoreDelete(s_data_ready);  s_data_ready = NULL; }

    ESP_LOGI(TAG, "ADC detenido");
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_adc_reconfigure(void)
{
    ESP_LOGI(TAG, "Reconfigurando ADC...");
    osc_adc_stop();
    // Delay activo corto para que el DMA termine de vaciar sin ceder CPU
    esp_rom_delay_us(500); 
    esp_err_t ret = osc_adc_init();
    if (ret == ESP_OK) ret = osc_adc_start();
    return ret;
}

static inline int16_t raw_to_mv10(uint16_t raw, uint8_t ch_idx)
{
    int voltage_mv = 0;
    if (s_cali_handle[ch_idx]) {
        adc_cali_raw_to_voltage(s_cali_handle[ch_idx], (int)raw, &voltage_mv);
    } else {
        uint8_t atten_idx = s_current_atten[ch_idx > 1 ? 1 : ch_idx];
        if (atten_idx > 3) atten_idx = 3;
        int full_scale = s_atten_full_scale_mv[atten_idx];
        voltage_mv = (int)((raw * (long)full_scale) / 4095);
    }

    // Aplicar corrección si estamos en 12dB (index 3) y el voltaje es alto (>2500mV)
    if (s_current_atten[ch_idx] == 3 && voltage_mv > OSC_ADC_SATURATION_MV) {
        voltage_mv = (int)(voltage_mv * OSC_ADC_CORRECTION_FACTOR);
    }

    return (int16_t)(voltage_mv * 10);
}

/* --------------------------------------------------------------------------
 * Filtro de mediana de 3 puntos (elimina spikes de silicio)
 * -------------------------------------------------------------------------- */
static inline int16_t median3_i16(int16_t a, int16_t b, int16_t c)
{
    if (a > b) { int16_t t = a; a = b; b = t; }
    if (b > c) { int16_t t = b; b = c; c = t; }
    if (a > b) { int16_t t = a; a = b; b = t; }
    return b;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_adc_read_samples(osc_sample_t *buf, size_t max_count,
                                size_t *out_count, uint32_t timeout_ms)
{
    if (!buf || !out_count || !s_adc_handle) return ESP_ERR_INVALID_STATE;
    *out_count = 0;

    osc_config_t cfg;
    osc_config_get(&cfg);
    bool dual = (cfg.mode == OSC_MODE_DUAL_CH);

    // Esperar notificación de la ISR
    if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(timeout_ms)) == 0) {
        return ESP_ERR_TIMEOUT;
    }

    uint32_t bytes_read = 0;
    esp_err_t ret = adc_continuous_read(s_adc_handle, s_raw_buf,
                                         RAW_READ_BUF_SIZE, &bytes_read, 0);
    if (ret != ESP_OK || bytes_read == 0) return ESP_ERR_TIMEOUT;

    uint32_t timestamp = (uint32_t)esp_timer_get_time();
    size_t result_size = bytes_read / SOC_ADC_DIGI_RESULT_BYTES;
    size_t written = 0;

    // Decimation logic for low sample rates
    uint32_t hw_rate = cfg.sample_rate_hz;
    if (hw_rate < 20000) hw_rate = 20000;
    if (hw_rate > 83333) hw_rate = 83333;
    
    uint32_t skip_factor = hw_rate / cfg.sample_rate_hz;
    if (skip_factor < 1) skip_factor = 1;

    for (size_t i = 0; i < result_size && written < max_count; i++) {
        adc_digi_output_data_t *p = (adc_digi_output_data_t *)&s_raw_buf[i * SOC_ADC_DIGI_RESULT_BYTES];

        uint8_t  ch  = p->type2.channel;
        uint16_t raw = p->type2.data;

        if (!dual) {
            s_acc_ch0 += raw;
            if (++s_acc_count < skip_factor) continue;

            uint16_t avg_raw = (uint16_t)(s_acc_ch0 / s_acc_count);
            s_acc_ch0 = 0;
            s_acc_count = 0;

            int16_t filtered = raw_to_mv10(avg_raw, 0);

            buf[written].ch0_mv10      = filtered;
            buf[written].ch1_mv10      = 0;
            buf[written].timestamp_us  = timestamp + (uint32_t)(written * 1000000UL / cfg.sample_rate_hz);
            written++;
        } else {
            // Dual channel: el ADC alterna CH0 y CH1
            if (ch == 0) {
                s_acc_ch0 += raw;
            } else if (ch == 1) {
                s_acc_ch1 += raw;
                s_has_ch0 = true; // Marcamos que tenemos al menos un par en proceso
            }

            // Cuando completamos el ciclo de acumulación para ambos canales
            if (s_has_ch0 && ++s_acc_count >= skip_factor) {
                uint16_t avg0 = (uint16_t)(s_acc_ch0 / skip_factor);
                uint16_t avg1 = (uint16_t)(s_acc_ch1 / skip_factor);
                
                buf[written].ch0_mv10 = raw_to_mv10(avg0, 0);
                buf[written].ch1_mv10 = raw_to_mv10(avg1, 1);
                buf[written].timestamp_us = timestamp + (uint32_t)(written * 1000000UL / (cfg.sample_rate_hz));
                
                written++;
                s_acc_ch0 = 0;
                s_acc_ch1 = 0;
                s_acc_count = 0;
                s_has_ch0 = false;
            }
        }
    }

    *out_count = written;
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
void *osc_adc_get_handle(void) { return s_adc_handle; }
uint32_t osc_adc_get_overflow_count(void) { return s_overflow_count; }
void osc_adc_reset_overflow_count(void) { s_overflow_count = 0; }
