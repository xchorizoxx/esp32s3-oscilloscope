#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"
#include "osc_adc.h"
#include "osc_config.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Resultado de una evaluación de trigger.
 */
typedef struct {
    bool     triggered;         ///< true si se detectó el evento de trigger
    size_t   trigger_index;     ///< índice dentro del buffer donde ocurrió el trigger
    uint32_t trigger_time_us;   ///< timestamp del sample de trigger
    float    trigger_level_mv;  ///< nivel de voltaje en el momento del trigger
} osc_trigger_result_t;

/**
 * @brief Inicializar el módulo de trigger. Sin memoria dinámica.
 */
esp_err_t osc_trigger_init(void);

/**
 * @brief Evaluar un buffer de muestras buscando el evento de trigger configurado.
 *        Esta función es stateful: mantiene la muestra anterior para detectar flancos
 *        que ocurran entre llamadas consecutivas.
 *
 * @param[in]  samples     Buffer de muestras del ADC
 * @param[in]  count       Número de muestras en el buffer
 * @param[out] result      Resultado de la evaluación
 * @return ESP_OK siempre (resultado se comunica via result->triggered)
 */
esp_err_t osc_trigger_evaluate(const osc_sample_t *samples, size_t count,
                                osc_trigger_result_t *result);

/**
 * @brief Resetear el estado del trigger (limpiar muestra anterior, hysteresis, etc).
 *        Llamar al cambiar configuración o al iniciar nueva captura.
 */
void osc_trigger_reset(void);

/**
 * @brief Aplicar configuración de trigger desde osc_config (carga nivel, edge, canal).
 *        Llamar cada vez que osc_config cambie.
 */
void osc_trigger_apply_config(void);

#ifdef __cplusplus
}
#endif
