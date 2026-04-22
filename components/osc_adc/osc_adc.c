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

    adc_continuous_config_t dig_cfg = {
        .pattern_num    = n_channels,
        .adc_pattern    = pattern,
        .sample_freq_hz = cfg.sample_rate_hz,
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
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_adc_start(void)
{
    if (!s_adc_handle) return ESP_ERR_INVALID_STATE;
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
    vTaskDelay(pdMS_TO_TICKS(10));
    esp_err_t ret = osc_adc_init();
    if (ret == ESP_OK) ret = osc_adc_start();
    return ret;
}

/* --------------------------------------------------------------------------
 * Conversión RAW → mV*10 con calibración
 * -------------------------------------------------------------------------- */
static inline int16_t raw_to_mv10(uint16_t raw, uint8_t ch_idx)
{
    int voltage_mv = 0;
    if (s_cali_handle[ch_idx]) {
        adc_cali_raw_to_voltage(s_cali_handle[ch_idx], (int)raw, &voltage_mv);
    } else {
        // Sin calibración: escala lineal aproximada para 12dB atten (0–3100 mV)
        voltage_mv = (int)((raw * 3100L) / 4095);
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

    // Buffer temporal para median filter
    static int16_t prev_ch0[2] = {0};  // últimas 2 muestras ch0
    static int16_t prev_ch1[2] = {0};

    for (size_t i = 0; i < result_size && written < max_count; i++) {
        adc_digi_output_data_t *p = (adc_digi_output_data_t *)&s_raw_buf[i * SOC_ADC_DIGI_RESULT_BYTES];

        uint8_t  ch  = p->type2.channel;
        uint16_t raw = p->type2.data;

        if (!dual) {
            // Single channel: cada resultado es ch0
            int16_t cur = raw_to_mv10(raw, 0);
            int16_t filtered = median3_i16(prev_ch0[0], prev_ch0[1], cur);
            prev_ch0[0] = prev_ch0[1];
            prev_ch0[1] = cur;

            buf[written].ch0_mv10      = filtered;
            buf[written].ch1_mv10      = 0;
            buf[written].timestamp_us  = timestamp + (uint32_t)(i * 1000000UL / cfg.sample_rate_hz);
            written++;
        } else {
            // Dual channel: el ADC alterna CH0 y CH1
            // Buscamos pares (ch0, ch1) consecutivos
            static int16_t last_ch0 = 0;
            static bool has_ch0 = false;

            if (ch == 0) {
                last_ch0 = raw_to_mv10(raw, 0);
                has_ch0  = true;
            } else if (ch == 1 && has_ch0) {
                int16_t mv10_ch1 = raw_to_mv10(raw, 1);
                buf[written].ch0_mv10     = last_ch0;
                buf[written].ch1_mv10     = mv10_ch1;
                buf[written].timestamp_us = timestamp + (uint32_t)((i/2) * 2000000UL / cfg.sample_rate_hz);
                written++;
                has_ch0 = false;
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
