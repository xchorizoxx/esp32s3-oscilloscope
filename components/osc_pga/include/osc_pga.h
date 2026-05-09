#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define OSC_PGA_RF_OHM          36000
#define OSC_PGA_R1_OHM          36000
#define OSC_PGA_R2_OHM           9090
#define OSC_PGA_R3_OHM           4020
#define OSC_PGA_GPIO_RON_OHM       50
#define OSC_PGA_DIV_RATIO    (100000.0f / (1000000.0f + 100000.0f))

/* GPIOs Rg switches (open-drain, 0=LOW=activo, 1=Hi-Z) */
#define OSC_PGA_GPIO_R1          39
#define OSC_PGA_GPIO_R2          40
#define OSC_PGA_GPIO_R3          41

/* Rango ADC lineal (mV) */
#define OSC_PGA_ADC_MIN_MV      150
#define OSC_PGA_ADC_MAX_MV     2750

/* Virtual ground por defecto (mV) */
#define OSC_PGA_VG_DEFAULT_MV  1600.0f

#define OSC_PGA_NUM_STEPS        8

typedef struct {
    float    gain_nominal;
    float    gain_effective;
    float    bw_hz;
    float    max_input_vpp;
    float    res_input_mv;
    bool     bw_warning;
    uint8_t  gpio_mask;
} osc_pga_step_t;

typedef struct {
    float    vg_mv;
    float    gain_cal_factor[OSC_PGA_NUM_STEPS];
    float    offset_cal_mv[OSC_PGA_NUM_STEPS];
    bool     calibrated;
} osc_pga_cal_t;

extern volatile bool g_pga_gain_changed;

esp_err_t osc_pga_init(void);
esp_err_t osc_pga_set_step(uint8_t step);
uint8_t   osc_pga_get_step(void);
esp_err_t osc_pga_get_step_info(uint8_t step, osc_pga_step_t *out);
float     osc_pga_get_gain_eff(void);
float     osc_pga_get_vg_mv(void);
float     osc_pga_adc_to_input_mv(int16_t adc_mv10);
esp_err_t osc_pga_calibrate_auto(int16_t (*read_adc_mv10_fn)(void));
esp_err_t osc_pga_cal_set_vg(float vg_mv);
esp_err_t osc_pga_cal_set_gain_factor(uint8_t step, float factor);
esp_err_t osc_pga_cal_set_offset(uint8_t step, float offset_mv);
esp_err_t osc_pga_cal_save(void);
esp_err_t osc_pga_cal_load(void);
esp_err_t osc_pga_cal_reset(void);
esp_err_t osc_pga_cal_get(osc_pga_cal_t *out);

#ifdef __cplusplus
}
#endif
