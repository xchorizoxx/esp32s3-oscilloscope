#include "osc_trigger.h"
#include "osc_config.h"
#include "esp_log.h"
#include <math.h>

static const char *TAG = "osc_trigger";

/* --------------------------------------------------------------------------
 * Estado interno del trigger
 * -------------------------------------------------------------------------- */
static struct {
    float           level_mv;
    osc_trig_edge_t edge;
    uint8_t         channel;
    int16_t         prev_sample_mv10;
    bool            armed;             // Nuevo: Indica si el trigger ha cruzado la banda de histéresis opuesta
    bool            initialized;
    float           hyst_mv;           // Histéresis real (banda muerta)
} s_trig = {0};

/* -------------------------------------------------------------------------- */
esp_err_t osc_trigger_init(void)
{
    osc_trigger_apply_config();
    s_trig.initialized = true;
    ESP_LOGI(TAG, "Trigger init: level=%.1f mV, edge=%d, ch=%d",
             s_trig.level_mv, s_trig.edge, s_trig.channel);
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
void osc_trigger_apply_config(void)
{
    osc_config_t cfg;
    osc_config_get(&cfg);
    s_trig.level_mv = cfg.trigger_level_mv;
    s_trig.edge     = cfg.trigger_edge;
    s_trig.channel  = cfg.trigger_channel;
    
    // Histéresis dinámica: 3% del rango aproximado (asumimos 12dB/2500mV por ahora)
    // 2500 * 0.03 = 75mV. Ajustamos a 40mV para mayor sensibilidad pero con estabilidad.
    s_trig.hyst_mv  = 40.0f; 
    osc_trigger_reset();
}

/* -------------------------------------------------------------------------- */
void osc_trigger_reset(void)
{
    s_trig.prev_sample_mv10 = 0;
    s_trig.armed             = false;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_trigger_evaluate(const osc_sample_t *samples, size_t count,
                                osc_trigger_result_t *result)
{
    result->triggered = false;
    result->trigger_index = 0;
    result->trigger_time_us = 0;
    result->trigger_level_mv = s_trig.level_mv;

    if (!samples || count == 0) return ESP_OK;
    if (s_trig.edge == OSC_TRIG_NONE) return ESP_OK;

    const float level10     = s_trig.level_mv * 10.0f;
    const float upper_band  = (s_trig.level_mv + s_trig.hyst_mv) * 10.0f;
    const float lower_band  = (s_trig.level_mv - s_trig.hyst_mv) * 10.0f;

    for (size_t i = 0; i < count; i++) {
        int16_t cur = (s_trig.channel == 0) ? samples[i].ch0_mv10 : samples[i].ch1_mv10;
        float   cur_f = (float)cur;

        bool fire = false;

        if (s_trig.edge == OSC_TRIG_EDGE_RISING) {
            // Se arma cuando cae por debajo de la banda inferior
            if (!s_trig.armed && cur_f < lower_band) {
                s_trig.armed = true;
            }
            // Dispara cuando cruza el nivel estando armado
            if (s_trig.armed && cur_f >= level10) {
                fire = true;
                s_trig.armed = false; // Desarmar hasta cruzar banda de nuevo
            }
        } 
        else if (s_trig.edge == OSC_TRIG_EDGE_FALLING) {
            // Se arma cuando sube por encima de la banda superior
            if (!s_trig.armed && cur_f > upper_band) {
                s_trig.armed = true;
            }
            // Dispara cuando cae por debajo del nivel estando armado
            if (s_trig.armed && cur_f <= level10) {
                fire = true;
                s_trig.armed = false;
            }
        }
        else if (s_trig.edge == OSC_TRIG_EDGE_ANY) {
            // Simple edge para ANY (sin hysteresis compleja por ahora)
            bool prev_above = (s_trig.prev_sample_mv10 >= (int16_t)level10);
            bool cur_above  = (cur_f >= level10);
            if (prev_above != cur_above) fire = true;
        }

        if (fire) {
            result->triggered       = true;
            result->trigger_index   = i;
            result->trigger_time_us = samples[i].timestamp_us;
            
            // Interpolación lineal para precisión sub-muestreo
            if (i > 0 && s_trig.prev_sample_mv10 != cur) {
                float prev_f = (float)s_trig.prev_sample_mv10;
                float frac = (level10 - prev_f) / (cur_f - prev_f);
                result->trigger_time_us = samples[i-1].timestamp_us +
                    (uint32_t)(frac * (samples[i].timestamp_us - samples[i-1].timestamp_us));
            }
            s_trig.prev_sample_mv10 = cur;
            return ESP_OK;
        }

        s_trig.prev_sample_mv10 = cur;
    }

    // Sin trigger encontrado: el estado ya se actualizó en el bucle
    return ESP_OK;
}
