#include "osc_config.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "osc_config";
#define NVS_NAMESPACE  "osc_cfg"
#define NVS_KEY_CONFIG "config_v2"

static SemaphoreHandle_t s_mutex    = NULL;
static osc_config_t      s_config;
static bool              s_initialized = false;

/* -------------------------------------------------------------------------- */
esp_err_t osc_config_init(void)
{
    if (s_initialized) return ESP_OK;

    s_mutex = xSemaphoreCreateMutex();
    if (!s_mutex) {
        ESP_LOGE(TAG, "No se pudo crear mutex");
        return ESP_ERR_NO_MEM;
    }

    // Intentar cargar desde NVS; si falla, usar defaults
    esp_err_t ret = osc_config_load_nvs();
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "NVS no disponible o sin datos, usando defaults");
        osc_config_t def = OSC_CONFIG_DEFAULT();
        memcpy(&s_config, &def, sizeof(osc_config_t));
    }

    s_initialized = true;
    ESP_LOGI(TAG, "Inicializado. mode=%d rate=%lu Hz", s_config.mode, s_config.sample_rate_hz);
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_config_get(osc_config_t *out_cfg)
{
    if (!out_cfg) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    memcpy(out_cfg, &s_config, sizeof(osc_config_t));
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_config_set(const osc_config_t *cfg)
{
    if (!cfg) return ESP_ERR_INVALID_ARG;

    // Validaciones básicas
    if (cfg->frame_size < 64 || cfg->frame_size > 4096) {
        ESP_LOGE(TAG, "frame_size inválido: %lu", cfg->frame_size);
        return ESP_ERR_INVALID_ARG;
    }
    if (cfg->sample_rate_hz < 611 || cfg->sample_rate_hz > 160000) {
        ESP_LOGE(TAG, "sample_rate_hz fuera de rango: %lu", cfg->sample_rate_hz);
        return ESP_ERR_INVALID_ARG;
    }
    if (cfg->trigger_channel > 1) return ESP_ERR_INVALID_ARG;
    if (cfg->ch_atten[0] > OSC_ATTEN_12DB || cfg->ch_atten[1] > OSC_ATTEN_12DB)
        return ESP_ERR_INVALID_ARG;
    if (cfg->oversample_factor != 1 && cfg->oversample_factor != 2 &&
        cfg->oversample_factor != 4 && cfg->oversample_factor != 8 &&
        cfg->oversample_factor != 16)
        return ESP_ERR_INVALID_ARG;

    xSemaphoreTake(s_mutex, portMAX_DELAY);
    memcpy(&s_config, cfg, sizeof(osc_config_t));
    xSemaphoreGive(s_mutex);

    ESP_LOGI(TAG, "Config actualizada: mode=%d rate=%lu", cfg->mode, cfg->sample_rate_hz);
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_config_set_mode(osc_mode_t mode)
{
    if (mode > OSC_MODE_DUAL_CH) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.mode = mode;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_rate(uint32_t hz)
{
    if (hz < 611 || hz > 160000) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.sample_rate_hz = hz;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_trigger(float level_mv, osc_trig_edge_t edge, uint8_t ch)
{
    if (ch > 1) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.trigger_level_mv = level_mv;
    s_config.trigger_edge     = edge;
    s_config.trigger_channel  = ch;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_atten(uint8_t ch, osc_atten_t atten)
{
    if (ch > 1 || atten > OSC_ATTEN_12DB) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.ch_atten[ch] = atten;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_streaming(bool en)
{
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.streaming = en;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_fft(bool en)
{
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.fft_enabled = en;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_frame_size(uint32_t n)
{
    // Debe ser potencia de 2 entre 64 y 4096
    if (n < 64 || n > 4096 || (n & (n - 1)) != 0) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.frame_size = n;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_pre_trigger(uint32_t samples)
{
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    if (samples > s_config.frame_size / 2) samples = s_config.frame_size / 2;
    s_config.pre_trigger_samples = samples;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_oversample(uint8_t factor)
{
    if (factor != 1 && factor != 2 && factor != 4 && factor != 8 && factor != 16)
        return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.oversample_factor = factor;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_config_set_pga_step(uint8_t step)
{
    if (step > 7) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.pga_step = step;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_pga_enabled(bool en)
{
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.pga_enabled = en;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_pga_vg(float vg_mv)
{
    if (vg_mv < 100.0f || vg_mv > 3000.0f) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.pga_vg_mv = vg_mv;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

esp_err_t osc_config_set_adc_correction(float factor)
{
    if (factor < 1.0f || factor > 1.1f) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_config.adc_correction_factor = factor;
    xSemaphoreGive(s_mutex);
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_config_save_nvs(void)
{
    nvs_handle_t handle;
    esp_err_t ret = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (ret != ESP_OK) return ret;

    xSemaphoreTake(s_mutex, portMAX_DELAY);
    ret = nvs_set_blob(handle, NVS_KEY_CONFIG, &s_config, sizeof(osc_config_t));
    xSemaphoreGive(s_mutex);

    if (ret == ESP_OK) ret = nvs_commit(handle);
    nvs_close(handle);
    if (ret == ESP_OK) ESP_LOGI(TAG, "Config guardada en NVS");
    return ret;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_config_load_nvs(void)
{
    nvs_handle_t handle;
    esp_err_t ret = nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle);
    if (ret != ESP_OK) return ret;

    size_t required = sizeof(osc_config_t);
    osc_config_t tmp;
    ret = nvs_get_blob(handle, NVS_KEY_CONFIG, &tmp, &required);
    nvs_close(handle);

    if (ret == ESP_OK && required == sizeof(osc_config_t)) {
        xSemaphoreTake(s_mutex, portMAX_DELAY);
        memcpy(&s_config, &tmp, sizeof(osc_config_t));
        xSemaphoreGive(s_mutex);
        ESP_LOGI(TAG, "Config cargada desde NVS");
    } else if (ret == ESP_OK && required != sizeof(osc_config_t)) {
        ret = ESP_ERR_INVALID_SIZE;
    }
    return ret;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_config_factory_reset(void)
{
    osc_config_t def = OSC_CONFIG_DEFAULT();
    esp_err_t ret = osc_config_set(&def);
    if (ret == ESP_OK) ret = osc_config_save_nvs();
    ESP_LOGI(TAG, "Factory reset completado");
    return ret;
}
