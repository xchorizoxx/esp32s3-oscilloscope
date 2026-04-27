#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Inicializa el módulo generador de señales.
 * @param gpio_num Pin de salida para el generador.
 * @return ESP_OK si todo fue exitoso.
 */
esp_err_t osc_gen_init(int gpio_num);

/**
 * @brief Configura e inicia la generación de una onda cuadrada (PWM).
 * @param freq_hz Frecuencia en Hz (1 a 150000).
 * @param duty_pct Ciclo de trabajo en % (10 a 90).
 * @return ESP_OK si fue exitoso, ESP_ERR_INVALID_ARG si los parámetros están fuera de rango.
 */
esp_err_t osc_gen_set_square(uint32_t freq_hz, uint8_t duty_pct);

/**
 * @brief Detiene la generación de la señal y deja el pin en bajo.
 * @return ESP_OK si fue exitoso.
 */
esp_err_t osc_gen_stop(void);

#ifdef __cplusplus
}
#endif
