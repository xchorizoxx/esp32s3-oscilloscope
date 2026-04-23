#include "osc_gen.h"
#include "esp_log.h"
#include "driver/ledc.h"

static const char *TAG = "osc_gen";
static int s_gpio_num = -1;
static bool s_is_running = false;

esp_err_t osc_gen_init(int gpio_num)
{
    s_gpio_num = gpio_num;
    s_is_running = false;
    ESP_LOGI(TAG, "Signal Generator initialized on GPIO%d", gpio_num);
    return ESP_OK;
}

esp_err_t osc_gen_set_square(uint32_t freq_hz, uint8_t duty_pct)
{
    if (s_gpio_num < 0) return ESP_ERR_INVALID_STATE;
    if (freq_hz < 1 || freq_hz > 150000) return ESP_ERR_INVALID_ARG;
    if (duty_pct < 1 || duty_pct > 99) return ESP_ERR_INVALID_ARG;

    // Determinar la resolución óptima basada en la frecuencia
    // APB_CLK es 80 MHz típicamente. Max freq para N bits = 80MHz / (2^N)
    ledc_timer_bit_t resolution = LEDC_TIMER_10_BIT;
    uint32_t max_val = 1024;

    if (freq_hz > 78000) {
        resolution = LEDC_TIMER_8_BIT;
        max_val = 256;
    } else if (freq_hz > 39000) {
        resolution = LEDC_TIMER_9_BIT;
        max_val = 512;
    }

    ledc_timer_config_t timer_cfg = {
        .speed_mode      = LEDC_LOW_SPEED_MODE,
        .timer_num       = LEDC_TIMER_0,
        .duty_resolution = resolution,
        .freq_hz         = freq_hz,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    esp_err_t err = ledc_timer_config(&timer_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "ledc_timer_config failed");
        return err;
    }

    uint32_t duty_val = (max_val * duty_pct) / 100;

    ledc_channel_config_t ch_cfg = {
        .channel    = LEDC_CHANNEL_0,
        .duty       = duty_val,
        .gpio_num   = s_gpio_num,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .hpoint     = 0,
        .timer_sel  = LEDC_TIMER_0,
    };
    err = ledc_channel_config(&ch_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "ledc_channel_config failed");
        return err;
    }

    s_is_running = true;
    ESP_LOGI(TAG, "Generator Started: %lu Hz, %u%% duty", freq_hz, duty_pct);
    return ESP_OK;
}

esp_err_t osc_gen_stop(void)
{
    if (s_gpio_num < 0) return ESP_ERR_INVALID_STATE;
    
    // Stop the PWM signal and set the output to 0
    esp_err_t err = ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
    if (err == ESP_OK) {
        s_is_running = false;
        ESP_LOGI(TAG, "Generator Stopped");
    }
    return err;
}
