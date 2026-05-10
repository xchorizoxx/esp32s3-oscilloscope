#include "osc_gen.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "driver/ledc.h"
#include <math.h>

static const char *TAG = "osc_gen";
static int s_gpio_num = -1;
static bool s_running = false;

// Estado para formas de onda por software (sine/triangle/saw)
#define WAVE_TABLE_SIZE    64
#define WAVE_CARRIER_FREQ  40000
#define WAVE_MAX_FREQ      2000
#define MIN_PERIOD_US      25

static uint8_t s_wave_table[WAVE_TABLE_SIZE];
static volatile uint8_t s_wave_idx;
static uint8_t s_wave_step;
static uint32_t s_wave_period_us;
static volatile bool s_soft_active;
static esp_timer_handle_t s_wave_timer;

// ------------------------------------------------------------------
// Tabla de ondas
// ------------------------------------------------------------------
static void fill_wave_table(uint8_t type)
{
    for (int i = 0; i < WAVE_TABLE_SIZE; i++) {
        switch (type) {
        case OSC_WAVE_SINE:
            s_wave_table[i] = (uint8_t)(127.5f + 127.5f * sinf(2.0f * M_PI * (float)i / WAVE_TABLE_SIZE));
            break;
        case OSC_WAVE_TRIANGLE:
            if (i < WAVE_TABLE_SIZE / 2)
                s_wave_table[i] = (uint8_t)(255 * i * 2 / WAVE_TABLE_SIZE);
            else
                s_wave_table[i] = (uint8_t)(255 * (WAVE_TABLE_SIZE - i) * 2 / WAVE_TABLE_SIZE);
            break;
        case OSC_WAVE_SAW:
            s_wave_table[i] = (uint8_t)(255 * i / (WAVE_TABLE_SIZE - 1));
            break;
        default:
            s_wave_table[i] = (i < WAVE_TABLE_SIZE / 2) ? 255 : 0;
            break;
        }
    }
}

// ------------------------------------------------------------------
// Callback del timer periodico (actualiza duty de la portadora PWM)
// ------------------------------------------------------------------
static void wave_timer_cb(void *arg)
{
    if (!s_soft_active) return;

    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0,
                  s_wave_table[s_wave_idx]);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
    s_wave_idx = (s_wave_idx + s_wave_step) % WAVE_TABLE_SIZE;
}

// ------------------------------------------------------------------
// Control del timer periodico
// ------------------------------------------------------------------
static void stop_soft_wave(void)
{
    s_soft_active = false;
    if (s_wave_timer) {
        esp_timer_stop(s_wave_timer);
        esp_timer_delete(s_wave_timer);
        s_wave_timer = NULL;
    }
}

static esp_err_t start_soft_wave(uint8_t type, uint32_t freq_hz)
{
    if (freq_hz < 1 || freq_hz > WAVE_MAX_FREQ)
        return ESP_ERR_INVALID_ARG;

    // Calcular step (skip samples) y periodo del callback
    s_wave_step = 1;
    s_wave_period_us = (uint32_t)s_wave_step * 1000000 / (freq_hz * WAVE_TABLE_SIZE);
    while (s_wave_period_us < MIN_PERIOD_US && s_wave_step < WAVE_TABLE_SIZE / 4) {
        s_wave_step *= 2;
        s_wave_period_us = (uint32_t)s_wave_step * 1000000 / (freq_hz * WAVE_TABLE_SIZE);
    }

    s_wave_idx = 0;
    fill_wave_table(type);

    // Configurar LEDC como portadora PWM 40 kHz, 8 bits
    ledc_timer_config_t timer_cfg = {
        .speed_mode      = LEDC_LOW_SPEED_MODE,
        .timer_num       = LEDC_TIMER_0,
        .duty_resolution = LEDC_TIMER_8_BIT,
        .freq_hz         = WAVE_CARRIER_FREQ,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    esp_err_t err = ledc_timer_config(&timer_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "ledc_timer_config (carrier) failed");
        return err;
    }

    ledc_channel_config_t ch_cfg = {
        .channel    = LEDC_CHANNEL_0,
        .duty       = 0,
        .gpio_num   = s_gpio_num,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .hpoint     = 0,
        .timer_sel  = LEDC_TIMER_0,
    };
    err = ledc_channel_config(&ch_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "ledc_channel_config (carrier) failed");
        return err;
    }

    s_soft_active = true;

    // Crear y arrancar timer periodico
    esp_timer_create_args_t timer_args = {
        .callback = wave_timer_cb,
        .name     = "wave_gen",
    };
    err = esp_timer_create(&timer_args, &s_wave_timer);
    if (err != ESP_OK) {
        s_soft_active = false;
        return err;
    }
    err = esp_timer_start_periodic(s_wave_timer, s_wave_period_us);
    if (err != ESP_OK) {
        s_soft_active = false;
        esp_timer_delete(s_wave_timer);
        s_wave_timer = NULL;
        return err;
    }

    int samples_per_cycle = WAVE_TABLE_SIZE / s_wave_step;
    ESP_LOGI(TAG, "%s %lu Hz, %d us/step, %d samples/cycle",
             (type == OSC_WAVE_SINE)     ? "Sine" :
             (type == OSC_WAVE_TRIANGLE) ? "Triangle" :
             (type == OSC_WAVE_SAW)      ? "Saw"   : "?",
             freq_hz, s_wave_period_us, samples_per_cycle);
    return ESP_OK;
}

// ------------------------------------------------------------------
// API publica
// ------------------------------------------------------------------
esp_err_t osc_gen_init(int gpio_num)
{
    s_gpio_num = gpio_num;
    s_running = false;
    s_soft_active = false;
    s_wave_timer = NULL;
    ESP_LOGI(TAG, "Signal Generator initialized on GPIO%d", gpio_num);
    return ESP_OK;
}

esp_err_t osc_gen_set_square(uint32_t freq_hz, uint8_t duty_pct)
{
    if (s_gpio_num < 0) return ESP_ERR_INVALID_STATE;
    if (freq_hz < 1 || freq_hz > 150000) return ESP_ERR_INVALID_ARG;
    if (duty_pct < 1 || duty_pct > 99) return ESP_ERR_INVALID_ARG;

    if (s_soft_active) stop_soft_wave();

    // Resolucion optima segun frecuencia
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

    s_running = true;
    ESP_LOGI(TAG, "Square %lu Hz, %u%% duty", freq_hz, duty_pct);
    return ESP_OK;
}

esp_err_t osc_gen_set_wave(uint8_t wave_type, uint32_t freq_hz, uint8_t duty_pct)
{
    if (s_gpio_num < 0) return ESP_ERR_INVALID_STATE;

    if (s_soft_active) stop_soft_wave();
    if (s_running) {
        ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
        s_running = false;
    }

    if (wave_type == OSC_WAVE_SQUARE)
        return osc_gen_set_square(freq_hz, duty_pct);

    if (wave_type > OSC_WAVE_SAW) return ESP_ERR_INVALID_ARG;
    if (freq_hz < 1 || freq_hz > WAVE_MAX_FREQ) return ESP_ERR_INVALID_ARG;

    return start_soft_wave(wave_type, freq_hz);
}

esp_err_t osc_gen_stop(void)
{
    if (s_soft_active) stop_soft_wave();

    if (s_gpio_num < 0) return ESP_ERR_INVALID_STATE;

    esp_err_t err = ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
    s_running = false;
    ESP_LOGI(TAG, "Generator Stopped");
    return err;
}
