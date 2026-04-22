#include "osc_dsp.h"
#include "osc_config.h"
#include "esp_log.h"
#include "esp_dsp.h"          // librería esp-dsp de Espressif
#include <math.h>
#include <string.h>
#include <stdlib.h>

static const char *TAG = "osc_dsp";

// Tablas de ventanas pre-calculadas (para FFT_MAX_POINTS/2 puntos máximo)
static float s_win_hanning[OSC_FFT_MAX_POINTS];
static float s_win_hamming[OSC_FFT_MAX_POINTS];
static float s_win_blackman[OSC_FFT_MAX_POINTS];
static bool  s_windows_ready = false;

// Buffer de trabajo para FFT (complex: re/im intercalados, float32)
static float s_fft_work[OSC_FFT_MAX_POINTS * 2];

/* -------------------------------------------------------------------------- */
static void precompute_windows(void)
{
    for (int i = 0; i < OSC_FFT_MAX_POINTS; i++) {
        float t = (float)i / (OSC_FFT_MAX_POINTS - 1);
        s_win_hanning[i]  = 0.5f * (1.0f - cosf(2.0f * M_PI * t));
        s_win_hamming[i]  = 0.54f - 0.46f * cosf(2.0f * M_PI * t);
        s_win_blackman[i] = 0.42f - 0.5f * cosf(2.0f * M_PI * t)
                                  + 0.08f * cosf(4.0f * M_PI * t);
    }
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_dsp_init(void)
{
    if (!s_windows_ready) {
        precompute_windows();
        s_windows_ready = true;
        ESP_LOGI(TAG, "Tablas de ventanas pre-calculadas (%d puntos)", OSC_FFT_MAX_POINTS);
    }
    dsps_fft2r_init_fc32(NULL, OSC_FFT_MAX_POINTS);
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_dsp_compute_measurements(const int16_t *samples_mv10, size_t count,
                                        uint32_t sample_rate,
                                        osc_measurements_t *meas)
{
    if (!samples_mv10 || count < 4 || !meas) return ESP_ERR_INVALID_ARG;

    memset(meas, 0, sizeof(*meas));
    meas->valid = false;

    // --- Vmax, Vmin, DC, RMS ---
    int64_t sum = 0;
    int64_t sum_sq = 0;
    int16_t vmax = samples_mv10[0];
    int16_t vmin = samples_mv10[0];

    for (size_t i = 0; i < count; i++) {
        int16_t s = samples_mv10[i];
        if (s > vmax) vmax = s;
        if (s < vmin) vmin = s;
        sum    += s;
        sum_sq += (int64_t)s * s;
    }

    float vdc_mv10 = (float)sum / count;
    float vrms_mv10 = sqrtf((float)sum_sq / count);
    float vac_sq = (float)sum_sq / count - vdc_mv10 * vdc_mv10;
    float vac_mv10 = (vac_sq > 0) ? sqrtf(vac_sq) : 0.0f;

    meas->vmax_mv    = vmax   / 10.0f;
    meas->vmin_mv    = vmin   / 10.0f;
    meas->vpp_mv     = (vmax - vmin) / 10.0f;
    meas->vdc_mv     = vdc_mv10 / 10.0f;
    meas->vrms_mv    = vrms_mv10 / 10.0f;
    meas->vac_rms_mv = vac_mv10 / 10.0f;

    // --- Frecuencia por cruces por cero (método simple) ---
    float midpoint = vdc_mv10;
    int crossing_count = 0;
    uint32_t first_rising = 0;
    uint32_t last_rising  = 0;
    bool was_above = (samples_mv10[0] >= midpoint);
    bool found_first = false;

    for (size_t i = 1; i < count; i++) {
        bool now_above = (samples_mv10[i] >= midpoint);
        if (!was_above && now_above) {  // cruce ascendente
            crossing_count++;
            if (!found_first) {
                first_rising = i;
                found_first = true;
            }
            last_rising = i;
        }
        was_above = now_above;
    }

    if (crossing_count >= 2 && sample_rate > 0) {
        float period_samples = (float)(last_rising - first_rising) / (crossing_count - 1);
        meas->period_us = period_samples * 1e6f / sample_rate;
        meas->freq_hz   = (meas->period_us > 0) ? 1e6f / meas->period_us : 0.0f;
    }

    // --- Duty cycle (solo para señales que cruzan el 50% del rango) ---
    int high_count = 0;
    for (size_t i = 0; i < count; i++) {
        if (samples_mv10[i] > midpoint) high_count++;
    }
    meas->duty_cycle_pct = 100.0f * high_count / count;

    // --- Rise time (10% a 90% del rango) ---
    if (meas->vpp_mv > 50.0f) {  // solo medir si hay señal significativa
        float low10  = (meas->vmin_mv + meas->vpp_mv * 0.10f) * 10.0f;
        float high90 = (meas->vmin_mv + meas->vpp_mv * 0.90f) * 10.0f;
        int rise_start = -1, rise_end = -1;

        for (size_t i = 1; i < count; i++) {
            if (rise_start < 0 && samples_mv10[i-1] < low10 && samples_mv10[i] >= low10)
                rise_start = i;
            if (rise_start >= 0 && rise_end < 0 && samples_mv10[i] >= high90)
                rise_end = i;
            if (rise_start >= 0 && rise_end >= 0) break;
        }
        if (rise_start >= 0 && rise_end > rise_start && sample_rate > 0) {
            meas->rise_time_us = (float)(rise_end - rise_start) * 1e6f / sample_rate;
        }
    }

    meas->valid = true;
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_dsp_compute_fft(const int16_t *samples_mv10, size_t n,
                               osc_fft_window_t window, uint32_t sample_rate,
                               float *magnitudes, float *bin_hz)
{
    if (!samples_mv10 || !magnitudes || !bin_hz) return ESP_ERR_INVALID_ARG;
    if (n < 64 || n > OSC_FFT_MAX_POINTS || (n & (n-1)) != 0) return ESP_ERR_INVALID_ARG;

    // Seleccionar tabla de ventana
    const float *win = NULL;
    switch (window) {
        case OSC_FFT_WIN_HANNING:  win = s_win_hanning;  break;
        case OSC_FFT_WIN_HAMMING:  win = s_win_hamming;  break;
        case OSC_FFT_WIN_BLACKMAN: win = s_win_blackman; break;
        default: win = NULL; break;  // rectangular
    }

    // Llenar buffer complejo: re[i] = sample, im[i] = 0
    // Calcular DC para removerlo antes de la FFT
    float dc = 0;
    for (size_t i = 0; i < n; i++) dc += samples_mv10[i];
    dc /= n;

    float scale = 1.0f / 10000.0f;  // mV*10 → voltios (para que la FFT trabaje en V)
    for (size_t i = 0; i < n; i++) {
        float sample = ((float)samples_mv10[i] - dc) * scale;
        float w = win ? win[i * OSC_FFT_MAX_POINTS / n] : 1.0f;
        s_fft_work[2*i]     = sample * w;  // parte real
        s_fft_work[2*i + 1] = 0.0f;        // parte imaginaria
    }

    // FFT radix-2 (esp-dsp)
    esp_err_t ret = dsps_fft2r_fc32(s_fft_work, n);
    if (ret != ESP_OK) return ret;
    dsps_bit_rev_fc32(s_fft_work, n);
    dsps_cplx2reC_fc32(s_fft_work, n);

    // Calcular magnitudes (primera mitad + DC, convertir a mV)
    float norm = 2.0f / n;  // factor de normalización
    for (size_t i = 0; i < n / 2; i++) {
        float re = s_fft_work[2*i];
        float im = s_fft_work[2*i + 1];
        magnitudes[i] = sqrtf(re*re + im*im) * norm * 1000.0f;  // V → mV
    }
    magnitudes[0] /= 2.0f;  // DC no tiene componente espejo

    *bin_hz = (float)sample_rate / n;
    return ESP_OK;
}

/* -------------------------------------------------------------------------- */
esp_err_t osc_dsp_process_frame(const osc_sample_t *raw_samples, size_t count,
                                 osc_frame_t *frame,
                                 const osc_trigger_result_t *trigger_res)
{
    if (!raw_samples || count == 0 || !frame) return ESP_ERR_INVALID_ARG;

    osc_config_t cfg;
    osc_config_get(&cfg);

    bool dual = (cfg.mode == OSC_MODE_DUAL_CH);
    uint32_t effective_rate = cfg.sample_rate_hz;
    if (dual) effective_rate /= 2;

    frame->sample_count  = (uint16_t)count;
    frame->ch0_valid     = true;
    frame->ch1_valid     = dual;
    frame->timestamp_us  = raw_samples[0].timestamp_us;
    frame->trigger_hit   = trigger_res ? trigger_res->triggered : false;
    frame->trigger_index = trigger_res ? (uint32_t)trigger_res->trigger_index : 0;

    // Llenar arrays de datos (el llamador debe haber asignado ch0_data y ch1_data)
    for (size_t i = 0; i < count; i++) {
        frame->ch0_data[i] = raw_samples[i].ch0_mv10;
        if (dual && frame->ch1_data) {
            frame->ch1_data[i] = raw_samples[i].ch1_mv10;
        }
    }

    // Mediciones automáticas
    if (cfg.measurements_enabled) {
        osc_dsp_compute_measurements(frame->ch0_data, count, effective_rate, &frame->meas_ch0);
        if (dual && frame->ch1_data) {
            osc_dsp_compute_measurements(frame->ch1_data, count, effective_rate, &frame->meas_ch1);
        }
    }

    // FFT
    frame->fft_points = 0;
    frame->fft_bin_hz = 0;
    if (cfg.fft_enabled && frame->fft_magnitudes_ch0 && count >= 64) {
        size_t fft_n = count;
        if (fft_n > OSC_FFT_MAX_POINTS) fft_n = OSC_FFT_MAX_POINTS;
        // Asegurar potencia de 2
        size_t p = 64;
        while (p * 2 <= fft_n) p *= 2;
        fft_n = p;

        float bin_hz = 0;
        osc_dsp_compute_fft(frame->ch0_data, fft_n, OSC_FFT_WIN_HANNING,
                             effective_rate, frame->fft_magnitudes_ch0, &bin_hz);
        frame->fft_points = (uint16_t)(fft_n / 2);
        frame->fft_bin_hz = bin_hz;
    }

    return ESP_OK;
}
