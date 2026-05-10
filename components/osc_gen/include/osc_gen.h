#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

// Tipos de onda
#ifndef OSC_WAVE_SQUARE
#define OSC_WAVE_SQUARE   0
#define OSC_WAVE_SINE     1
#define OSC_WAVE_TRIANGLE 2
#define OSC_WAVE_SAW      3
#endif

/**
 * Inicializa el modulo generador de senales.
 * @param gpio_num Pin de salida.
 */
esp_err_t osc_gen_init(int gpio_num);

/**
 * Configura una onda cuadrada (PWM hardware LEDC).
 * @param freq_hz   Frecuencia en Hz (1 a 150000).
 * @param duty_pct  Ciclo de trabajo en % (1 a 99).
 */
esp_err_t osc_gen_set_square(uint32_t freq_hz, uint8_t duty_pct);

/**
 * Configura e inicia cualquier tipo de onda.
 *  - OSC_WAVE_SQUARE: LEDC PWM directo (1..150000 Hz)
 *  - OSC_WAVE_SINE/TRIANGLE/SAW: software DDS + portadora PWM 40 kHz (1..2000 Hz)
 * @param wave_type Tipo de onda (OSC_WAVE_*).
 * @param freq_hz   Frecuencia en Hz.
 * @param duty_pct  Ciclo de trabajo en % (solo para SQUARE, ignorado en soft).
 */
esp_err_t osc_gen_set_wave(uint8_t wave_type, uint32_t freq_hz, uint8_t duty_pct);

/**
 * Detiene la generacion de senal y deja el pin en bajo.
 */
esp_err_t osc_gen_stop(void);

#ifdef __cplusplus
}
#endif
