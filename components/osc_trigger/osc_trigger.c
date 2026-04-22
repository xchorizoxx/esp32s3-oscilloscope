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
    int16_t         prev_sample_mv10;  // última muestra de la llamada anterior
    bool            prev_above;        // ¿estaba por encima del nivel?
    bool            initialized;
    // Hysteresis: ±5% del rango full scale para evitar retriggering
    float           hyst_mv;
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
    // Hysteresis: 2.5% del full scale según atenuación
    // 12dB → full scale ≈ 2500 mV → hyst ≈ 62.5 mV
    s_trig.hyst_mv  = 50.0f;
    osc_trigger_reset();
}

/* -------------------------------------------------------------------------- */
void osc_trigger_reset(void)
{
    s_trig.prev_sample_mv10 = 0;
    s_trig.prev_above       = false;
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
    const float hyst10_up   = (s_trig.level_mv + s_trig.hyst_mv) * 10.0f;
    const float hyst10_down = (s_trig.level_mv - s_trig.hyst_mv) * 10.0f;

    int16_t prev = s_trig.prev_sample_mv10;
    bool    prev_above = s_trig.prev_above;

    for (size_t i = 0; i < count; i++) {
        int16_t cur = (s_trig.channel == 0) ? samples[i].ch0_mv10 : samples[i].ch1_mv10;
        float   cur_f = (float)cur;
        bool    cur_above = (cur_f >= level10);

        bool rising  = (!prev_above && cur_above && (float)prev <= hyst10_down);
        bool falling = (prev_above && !cur_above && (float)prev >= hyst10_up);

        bool fire = false;
        switch (s_trig.edge) {
            case OSC_TRIG_EDGE_RISING:  fire = rising;          break;
            case OSC_TRIG_EDGE_FALLING: fire = falling;         break;
            case OSC_TRIG_EDGE_ANY:     fire = rising || falling; break;
            default: break;
        }

        if (fire) {
            result->triggered       = true;
            result->trigger_index   = i;
            result->trigger_time_us = samples[i].timestamp_us;
            // Interpolar para mayor precisión del timestamp
            if (i > 0 && prev != cur) {
                float frac = (level10 - (float)prev) / ((float)cur - (float)prev);
                result->trigger_time_us = samples[i-1].timestamp_us +
                    (uint32_t)(frac * (samples[i].timestamp_us - samples[i-1].timestamp_us));
            }
            // Guardar estado DESPUÉS del trigger para la próxima llamada
            s_trig.prev_sample_mv10 = cur;
            s_trig.prev_above       = cur_above;
            return ESP_OK;
        }

        prev       = cur;
        prev_above = cur_above;
    }

    // Sin trigger encontrado: actualizar estado con la última muestra
    s_trig.prev_sample_mv10 = prev;
    s_trig.prev_above       = prev_above;
    return ESP_OK;
}
