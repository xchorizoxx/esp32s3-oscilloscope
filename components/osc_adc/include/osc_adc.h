#pragma once
#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"
#include "osc_config.h"

#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================================
 * Pines y constantes hardware
 * ========================================================================= */
#define OSC_ADC_UNIT          ADC_UNIT_1
#define OSC_ADC_CH0_GPIO      1     ///< GPIO1 = ADC1_CH0 = Canal A
#define OSC_ADC_CH1_GPIO      2     ///< GPIO2 = ADC1_CH1 = Canal B
#define OSC_ADC_BITWIDTH      ADC_BITWIDTH_12
#define OSC_ADC_DMA_BUF_SIZE  4096  ///< bytes del buffer DMA interno
#define OSC_ADC_POOL_SIZE     8192  ///< bytes del pool del driver adc_continuous

/**
 * @brief Muestra única del ADC con timestamp y metadatos de canal.
 *        Los valores están en mV * 10 (resolución de 0.1 mV).
 *        Ejemplo: 33150 = 3315.0 mV
 */
typedef struct {
    int16_t  ch0_mv10;      ///< Canal 0 en mV*10 (-32768..32767 → ~-3276.8..3276.7 mV)
    int16_t  ch1_mv10;      ///< Canal 1 en mV*10
    uint32_t timestamp_us;  ///< tiempo desde boot en µs (esp_timer_get_time())
} osc_sample_t;

/* =========================================================================
 * API pública
 * ========================================================================= */

/**
 * @brief Inicializar el driver ADC según la configuración actual en osc_config.
 *        Configura adc_continuous, patrón de canales, DMA, calibración.
 *        Debe llamarse DESPUÉS de osc_config_init().
 * @return ESP_OK en éxito
 */
esp_err_t osc_adc_init(void);

/**
 * @brief Iniciar la captura continua por DMA.
 *        Después de esta llamada, los datos empiezan a llegar al ring buffer.
 */
esp_err_t osc_adc_start(void);

/**
 * @brief Detener la captura y liberar el handle del ADC.
 */
esp_err_t osc_adc_stop(void);

/**
 * @brief Reinicializar el ADC con la configuración actual (útil tras cambio de modo/rate).
 *        Equivalente a osc_adc_stop() + osc_adc_init() + osc_adc_start().
 */
esp_err_t osc_adc_reconfigure(void);

/**
 * @brief Leer muestras procesadas del ring buffer interno.
 *        Bloquea hasta que hay datos o timeout.
 *        Los valores ya están en mV*10 (calibrados).
 *
 * @param[out] buf        Buffer destino de muestras
 * @param[in]  max_count  Máximo número de muestras a leer
 * @param[out] out_count  Número de muestras realmente leídas
 * @param[in]  timeout_ms Timeout en milisegundos (0 = no bloquear)
 * @return ESP_OK, ESP_ERR_TIMEOUT si no hay datos, ESP_FAIL si overflow
 */
esp_err_t osc_adc_read_samples(osc_sample_t *buf, size_t max_count,
                                size_t *out_count, uint32_t timeout_ms);

/**
 * @brief Obtener el handle nativo de adc_continuous (para uso avanzado).
 */
void *osc_adc_get_handle(void);

/**
 * @brief Obtener estadísticas de overflow del buffer DMA.
 */
uint32_t osc_adc_get_overflow_count(void);

/**
 * @brief Resetear contador de overflow.
 */
void osc_adc_reset_overflow_count(void);

/**
 * @brief Leer la media de N muestras ADC de un canal en mV*10.
 *        Usa adc_continuous_read() internamente (no requiere task notification).
 *        Funciona desde cualquier contexto de tarea.
 *        Timeout total ~timeout_ms.
 * @param ch_idx    Índice de canal (0=CH0, 1=CH1)
 * @param timeout_ms  Timeout en ms para cada lectura
 * @return Media en mV*10, o 14500 (1450.0 mV) como fallback si timeout
 */
int16_t osc_adc_read_mean_mv10(uint8_t ch_idx, uint32_t timeout_ms);

/**
 * @brief Update the ADC non-linearity correction factor at runtime.
 *        This only changes a scalar used in raw_to_mv10() — it does NOT
 *        reconfigure the ADC hardware or DMA, so it is safe to call from
 *        any task context at any time.
 * @param factor Correction multiplier (typically 1.0 to 1.1)
 */
void osc_adc_set_correction_factor(float factor);

#ifdef __cplusplus
}
#endif
