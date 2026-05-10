#include "osc_pga.h"
#include "osc_config.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "nvs.h"
#include <string.h>
#include <math.h>

static const char *TAG = "osc_pga";

#define NVS_NAMESPACE_PGA  "osc_pga"
#define NVS_KEY_CAL        "cal_v1"

#define LM358_GBW_HZ    1000000.0f
#define LM358_SR_VUS    0.3f
#define BW_WARNING_HZ   150000.0f

static const gpio_num_t s_gpio[3] = {
    (gpio_num_t)OSC_PGA_GPIO_R1,
    (gpio_num_t)OSC_PGA_GPIO_R2,
    (gpio_num_t)OSC_PGA_GPIO_R3,
};

static uint8_t       s_current_step = 0;
static osc_pga_cal_t s_cal;
static bool          s_initialized  = false;

volatile bool g_pga_gain_changed = false;

static osc_pga_step_t s_steps[OSC_PGA_NUM_STEPS];

static const uint8_t s_step_gpio_mask[OSC_PGA_NUM_STEPS] = {
    0b000,
    0b001,
    0b010,
    0b100,
    0b011,
    0b101,
    0b110,
    0b111,
};

static float compute_gain_eff(uint8_t gpio_mask)
{
    if (gpio_mask == 0) return 1.0f;
    float g_total = 0.0f;
    float rf = s_cal.r_fb_ohm;
    for (int i = 0; i < 3; i++) {
        if (gpio_mask & (1 << i)) {
            float rg_eff = s_cal.r_nom_ohm[i] + s_cal.gpio_ron_ohm;
            g_total += 1.0f / rg_eff;
        }
    }
    float rg_parallel_eff = 1.0f / g_total;
    return 1.0f + rf / rg_parallel_eff;
}

static float compute_gain_nom(uint8_t gpio_mask)
{
    if (gpio_mask == 0) return 1.0f;
    float g_total = 0.0f;
    float rf = s_cal.r_fb_ohm;
    for (int i = 0; i < 3; i++) {
        if (gpio_mask & (1 << i)) {
            g_total += 1.0f / s_cal.r_nom_ohm[i];
        }
    }
    float rg_parallel = 1.0f / g_total;
    return 1.0f + rf / rg_parallel;
}

static void precompute_steps(void)
{
    float vg         = s_cal.vg_mv;
    float div        = s_cal.div_ratio;
    float swing_up   = (float)OSC_PGA_ADC_MAX_MV - vg;
    float swing_down = vg - (float)OSC_PGA_ADC_MIN_MV;
    float swing_sym  = (swing_up < swing_down) ? swing_up : swing_down;
    float vout_pp    = 2.0f * swing_sym / 1000.0f;

    for (int s = 0; s < OSC_PGA_NUM_STEPS; s++) {
        uint8_t mask   = s_step_gpio_mask[s];
        float gain_nom = compute_gain_nom(mask);
        float gain_eff = compute_gain_eff(mask);

        s_steps[s].gain_nominal   = gain_nom;
        s_steps[s].gain_effective = gain_eff;
        s_steps[s].bw_hz          = LM358_GBW_HZ / gain_eff;
        s_steps[s].max_input_vpp  = vout_pp / gain_eff / div;
        float adc_lsb_mv = (float)(OSC_PGA_ADC_MAX_MV - OSC_PGA_ADC_MIN_MV) / 4096.0f;
        s_steps[s].res_input_mv   = adc_lsb_mv / gain_eff / div;
        s_steps[s].bw_warning     = (s_steps[s].bw_hz < BW_WARNING_HZ);
        s_steps[s].gpio_mask      = mask;
    }
}

static void apply_gpio_mask(uint8_t mask)
{
    for (int i = 0; i < 3; i++) {
        gpio_set_level(s_gpio[i], (mask & (1 << i)) ? 0 : 1);
    }
}

esp_err_t osc_pga_init(void)
{
    if (s_initialized) return ESP_OK;

    s_cal.vg_mv        = OSC_PGA_VG_DEFAULT_MV;
    s_cal.calibrated   = false;
    s_cal.div_ratio    = OSC_PGA_DIV_RATIO;
    s_cal.r_fb_ohm     = (float)OSC_PGA_RF_OHM;
    s_cal.r_nom_ohm[0] = (float)OSC_PGA_R1_OHM;
    s_cal.r_nom_ohm[1] = (float)OSC_PGA_R2_OHM;
    s_cal.r_nom_ohm[2] = (float)OSC_PGA_R3_OHM;
    s_cal.gpio_ron_ohm = (float)OSC_PGA_GPIO_RON_OHM;
    s_cal.vg_default   = OSC_PGA_VG_DEFAULT_MV;
    for (int i = 0; i < OSC_PGA_NUM_STEPS; i++) {
        s_cal.gain_cal_factor[i] = 1.0f;
        s_cal.offset_cal_mv[i]   = 0.0f;
    }

    osc_pga_cal_load();

    precompute_steps();

    for (int i = 0; i < 3; i++) {
        gpio_reset_pin(s_gpio[i]);
    }
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << OSC_PGA_GPIO_R1) |
                        (1ULL << OSC_PGA_GPIO_R2) |
                        (1ULL << OSC_PGA_GPIO_R3),
        .mode         = GPIO_MODE_OUTPUT_OD,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);

    gpio_set_level(OSC_PGA_GPIO_R1, 1);
    gpio_set_level(OSC_PGA_GPIO_R2, 1);
    gpio_set_level(OSC_PGA_GPIO_R3, 1);

    osc_config_t cfg;
    osc_config_get(&cfg);
    uint8_t saved_step = cfg.pga_step;
    if (saved_step >= OSC_PGA_NUM_STEPS) saved_step = 0;

    s_current_step = saved_step;
    apply_gpio_mask(s_step_gpio_mask[saved_step]);

    s_initialized = true;
    ESP_LOGI(TAG, "PGA init OK — paso=%d gain_eff=%.3f BW=%.0f Hz VG=%.1f mV div=%.4f",
             saved_step, s_steps[saved_step].gain_effective,
             s_steps[saved_step].bw_hz, s_cal.vg_mv, s_cal.div_ratio);

    if (s_steps[saved_step].bw_warning) {
        ESP_LOGW(TAG, "BW < 150 kHz en paso %d — senales >75kHz pueden atenuarse", saved_step);
    }
    return ESP_OK;
}

esp_err_t osc_pga_set_step(uint8_t step)
{
    if (step >= OSC_PGA_NUM_STEPS) return ESP_ERR_INVALID_ARG;
    if (step == s_current_step) return ESP_OK;

    g_pga_gain_changed = true;
    apply_gpio_mask(s_step_gpio_mask[step]);
    s_current_step = step;

    vTaskDelay(pdMS_TO_TICKS(2));

    osc_config_t cfg;
    osc_config_get(&cfg);
    cfg.pga_step = step;
    osc_config_set(&cfg);

    ESP_LOGI(TAG, "PGA step -> %d: gain=%.3f BW=%.0fHz max_in=%.2fVpp%s",
             step, s_steps[step].gain_effective, s_steps[step].bw_hz,
             s_steps[step].max_input_vpp,
             s_steps[step].bw_warning ? " [BW<150kHz]" : "");
    return ESP_OK;
}

uint8_t osc_pga_get_step(void) { return s_current_step; }

esp_err_t osc_pga_get_step_info(uint8_t step, osc_pga_step_t *out)
{
    if (step >= OSC_PGA_NUM_STEPS || !out) return ESP_ERR_INVALID_ARG;
    memcpy(out, &s_steps[step], sizeof(osc_pga_step_t));
    return ESP_OK;
}

float osc_pga_get_gain_eff(void)
{
    return s_steps[s_current_step].gain_effective
           * s_cal.gain_cal_factor[s_current_step];
}

float osc_pga_get_vg_mv(void)        { return s_cal.vg_mv; }
float osc_pga_get_vg_default(void)    { return s_cal.vg_default; }
float osc_pga_get_div_ratio(void)    { return s_cal.div_ratio; }

float osc_pga_adc_to_input_mv(int16_t adc_mv10)
{
    float v_adc_mv   = (float)adc_mv10 / 10.0f;
    float gain_total = s_steps[s_current_step].gain_effective
                       * s_cal.gain_cal_factor[s_current_step];
    float offset     = s_cal.offset_cal_mv[s_current_step];

    float v_in_mv = (v_adc_mv - s_cal.vg_mv - offset)
                    / gain_total
                    / s_cal.div_ratio;
    return v_in_mv;
}

esp_err_t osc_pga_calibrate_auto(int16_t (*read_adc_mv10_fn)(void))
{
    if (!read_adc_mv10_fn) return ESP_ERR_INVALID_ARG;

    ESP_LOGI(TAG, "Auto-calibracion PGA iniciada (entrada=0V/terminada)");

    apply_gpio_mask(0);
    vTaskDelay(pdMS_TO_TICKS(25));
    int16_t raw_vg = read_adc_mv10_fn();
    float vg = (float)raw_vg / 10.0f;

    if (vg < 500.0f || vg > 2500.0f) {
        ESP_LOGE(TAG, "Auto-cal fallo: entrada debe estar a GND (VG=%.1f mV fuera de rango)", vg);
        apply_gpio_mask(s_step_gpio_mask[s_current_step]);
        return ESP_ERR_INVALID_STATE;
    }

    s_cal.vg_mv = vg;
    osc_config_set_pga_vg(vg);

    s_cal.offset_cal_mv[0]  = 0.0f;
    s_cal.gain_cal_factor[0] = 1.0f;

    ESP_LOGI(TAG, "Cal: VG medido = %.1f mV", s_cal.vg_mv);

    for (int s = 1; s < OSC_PGA_NUM_STEPS; s++) {
        apply_gpio_mask(s_step_gpio_mask[s]);
        vTaskDelay(pdMS_TO_TICKS(25));

        int16_t raw = read_adc_mv10_fn();
        float v_adc = (float)raw / 10.0f;

        s_cal.offset_cal_mv[s]   = v_adc - s_cal.vg_mv;
        s_cal.gain_cal_factor[s] = 1.0f;

        ESP_LOGI(TAG, "Cal paso %d: V_out=%.1f mV offset=%.2f mV",
                 s, v_adc, s_cal.offset_cal_mv[s]);
    }

    apply_gpio_mask(s_step_gpio_mask[s_current_step]);
    vTaskDelay(pdMS_TO_TICKS(5));

    precompute_steps();

    s_cal.calibrated = true;
    ESP_LOGI(TAG, "Auto-calibracion completa. VG=%.1f mV", s_cal.vg_mv);
    return ESP_OK;
}

esp_err_t osc_pga_cal_set_vg(float vg_mv)
{
    if (vg_mv < 100.0f || vg_mv > 3000.0f) return ESP_ERR_INVALID_ARG;
    s_cal.vg_mv = vg_mv;
    osc_config_set_pga_vg(vg_mv);
    precompute_steps();
    return ESP_OK;
}

esp_err_t osc_pga_cal_set_gain_factor(uint8_t step, float factor)
{
    if (step >= OSC_PGA_NUM_STEPS) return ESP_ERR_INVALID_ARG;
    if (factor < 0.5f || factor > 2.0f) return ESP_ERR_INVALID_ARG;
    s_cal.gain_cal_factor[step] = factor;
    return ESP_OK;
}

esp_err_t osc_pga_cal_set_offset(uint8_t step, float offset_mv)
{
    if (step >= OSC_PGA_NUM_STEPS) return ESP_ERR_INVALID_ARG;
    s_cal.offset_cal_mv[step] = offset_mv;
    return ESP_OK;
}

esp_err_t osc_pga_cal_set_hardware(float div_ratio, float rf_ohm,
                                    float r1_ohm, float r2_ohm, float r3_ohm,
                                    float ron_ohm)
{
    if (div_ratio < 0.01f || div_ratio > 1.0f) return ESP_ERR_INVALID_ARG;
    if (rf_ohm  < 100.0f || rf_ohm  > 100000.0f) return ESP_ERR_INVALID_ARG;
    if (r1_ohm  < 100.0f || r1_ohm  > 100000.0f) return ESP_ERR_INVALID_ARG;
    if (r2_ohm  < 100.0f || r2_ohm  > 100000.0f) return ESP_ERR_INVALID_ARG;
    if (r3_ohm  < 100.0f || r3_ohm  > 100000.0f) return ESP_ERR_INVALID_ARG;
    if (ron_ohm < 0.0f   || ron_ohm > 500.0f)    return ESP_ERR_INVALID_ARG;

    s_cal.div_ratio    = div_ratio;
    s_cal.r_fb_ohm     = rf_ohm;
    s_cal.r_nom_ohm[0] = r1_ohm;
    s_cal.r_nom_ohm[1] = r2_ohm;
    s_cal.r_nom_ohm[2] = r3_ohm;
    s_cal.gpio_ron_ohm = ron_ohm;
    precompute_steps();
    ESP_LOGI(TAG, "PGA hardware config: div=%.4f Rf=%.0f R1=%.0f R2=%.0f R3=%.0f Ron=%.0f",
             div_ratio, rf_ohm, r1_ohm, r2_ohm, r3_ohm, ron_ohm);
    return ESP_OK;
}

esp_err_t osc_pga_cal_set_vg_default(float vg_mv)
{
    if (vg_mv < 100.0f || vg_mv > 3000.0f) return ESP_ERR_INVALID_ARG;
    s_cal.vg_default = vg_mv;
    ESP_LOGI(TAG, "VG default cambiado a %.1f mV", vg_mv);
    return ESP_OK;
}

esp_err_t osc_pga_cal_save(void)
{
    nvs_handle_t handle;
    esp_err_t ret = nvs_open(NVS_NAMESPACE_PGA, NVS_READWRITE, &handle);
    if (ret != ESP_OK) return ret;
    ret = nvs_set_blob(handle, NVS_KEY_CAL, &s_cal, sizeof(osc_pga_cal_t));
    if (ret == ESP_OK) ret = nvs_commit(handle);
    nvs_close(handle);
    if (ret == ESP_OK) ESP_LOGI(TAG, "Calibracion guardada en NVS");
    return ret;
}

esp_err_t osc_pga_cal_load(void)
{
    nvs_handle_t handle;
    esp_err_t ret = nvs_open(NVS_NAMESPACE_PGA, NVS_READONLY, &handle);
    if (ret != ESP_OK) return ret;

    size_t size = sizeof(osc_pga_cal_t);
    osc_pga_cal_t tmp;
    ret = nvs_get_blob(handle, NVS_KEY_CAL, &tmp, &size);
    nvs_close(handle);

    if (ret == ESP_OK && size == sizeof(osc_pga_cal_t)) {
        memcpy(&s_cal, &tmp, sizeof(osc_pga_cal_t));
        ESP_LOGI(TAG, "Calibracion cargada desde NVS. VG=%.1f mV", s_cal.vg_mv);
    }
    return ret;
}

esp_err_t osc_pga_cal_reset(void)
{
    s_cal.vg_mv      = s_cal.vg_default;
    s_cal.calibrated = false;
    for (int i = 0; i < OSC_PGA_NUM_STEPS; i++) {
        s_cal.gain_cal_factor[i] = 1.0f;
        s_cal.offset_cal_mv[i]   = 0.0f;
    }
    precompute_steps();
    return osc_pga_cal_save();
}

esp_err_t osc_pga_cal_get(osc_pga_cal_t *out)
{
    if (!out) return ESP_ERR_INVALID_ARG;
    memcpy(out, &s_cal, sizeof(osc_pga_cal_t));
    return ESP_OK;
}
