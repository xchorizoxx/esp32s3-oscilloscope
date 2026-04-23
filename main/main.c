/**
 * @file main.c
 * @brief ESP32-S3 Oscilloscope — Entry point y coordinación de tareas FreeRTOS.
 *
 * Arquitectura de tareas:
 *   Core 1 (APP_CPU, pinned):
 *     - ADC_CAPTURE_Task (prio 24): captura DMA, notifica a DSP_PROCESS_Task
 *
 *   Core 0 (PRO_CPU):
 *     - DSP_PROCESS_Task (prio 10): procesamiento, trigger, mediciones, FFT
 *     - USB_COMM_Task es manejada internamente por osc_usb (cmd_task + TinyUSB)
 *
 * Sincronización:
 *   - ADC_CAPTURE_Task escribe en ring buffer global
 *   - DSP_PROCESS_Task lee del ring buffer y produce osc_frame_t
 *   - DSP_PROCESS_Task llama a osc_usb_send_data_frame() para transmitir
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "driver/gpio.h"
#include "driver/ledc.h"

#include "osc_config.h"
#include "osc_adc.h"
#include "osc_trigger.h"
#include "osc_dsp.h"
#include "osc_usb.h"
#include "osc_protocol.h"
#include "osc_gen.h"

static const char *TAG = "osc_main";

/* --------------------------------------------------------------------------
 * Pines
 * -------------------------------------------------------------------------- */
#define PIN_LED_STATUS   48   ///< LED indicador de estado
#define PIN_TEST_SIGNAL  3    ///< Señal de test PWM 1 kHz

/* --------------------------------------------------------------------------
 * Buffers de trabajo del DSP_PROCESS_Task
 * Los buffers de muestras se asignan en PSRAM (heap externo)
 * -------------------------------------------------------------------------- */
#define MAX_FRAME_SAMPLES  4096

static int16_t s_ch0_buf[MAX_FRAME_SAMPLES];
static int16_t s_ch1_buf[MAX_FRAME_SAMPLES];
static float   s_fft_buf[MAX_FRAME_SAMPLES / 2];  // magnitudes FFT

/* Buffer de muestras raw del ADC (para la tarea ADC_CAPTURE) */
static osc_sample_t *s_sample_buf = NULL;
#define SAMPLE_BUF_SIZE  2048  // osc_sample_t

/* Queue entre ADC_CAPTURE y DSP_PROCESS */
typedef struct {
    size_t count;
    uint32_t timestamp_us;
} adc_batch_t;
static QueueHandle_t s_adc_queue = NULL;
static osc_sample_t  s_adc_staging[SAMPLE_BUF_SIZE];
static SemaphoreHandle_t s_staging_mutex = NULL;

/* --------------------------------------------------------------------------
 * Señal de test (PWM 1 kHz en GPIO3, para auto-test sin señal externa)
 * -------------------------------------------------------------------------- */
static void init_test_signal(void)
{
    // Reemplazado por el nuevo componente osc_gen
    // Inicializamos el generador en el pin de test
    esp_err_t err = osc_gen_init(PIN_TEST_SIGNAL);
    if (err == ESP_OK) {
        // Configuramos una señal por defecto al arrancar (1 kHz, 50% duty)
        osc_gen_set_square(1000, 50);
        ESP_LOGI(TAG, "Generador de señal de test activado en GPIO%d", PIN_TEST_SIGNAL);
    } else {
        ESP_LOGE(TAG, "Fallo al inicializar generador de señal");
    }
}

/* --------------------------------------------------------------------------
 * LED de estado
 * -------------------------------------------------------------------------- */
static void led_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << PIN_LED_STATUS),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    gpio_set_level(PIN_LED_STATUS, 0);
}

static void led_set(bool on) { gpio_set_level(PIN_LED_STATUS, on ? 1 : 0); }

/* --------------------------------------------------------------------------
 * TAREA: ADC_CAPTURE (Core 1, máxima prioridad)
 *   - Lee muestras del ADC por DMA
 *   - Copia al staging buffer compartido
 *   - Notifica a DSP_PROCESS_Task via queue
 * -------------------------------------------------------------------------- */
static void adc_capture_task(void *arg)
{
    ESP_LOGI(TAG, "ADC_CAPTURE iniciado en Core %d", xPortGetCoreID());

    osc_config_t cfg;
    uint32_t last_config_check = 0;

    // Iniciar ADC (ya inicializado en app_main, solo lo arrancamos)
    ESP_ERROR_CHECK(osc_adc_start());

    while (1) {
        // Verificar si la configuración cambió cada 100ms (para reconfigurarse)
        uint32_t now = (uint32_t)(esp_timer_get_time() / 1000);
        if (now - last_config_check > 100) {
            osc_config_get(&cfg);
            last_config_check = now;
        }

        size_t count = 0;
        esp_err_t ret = osc_adc_read_samples(s_sample_buf, SAMPLE_BUF_SIZE,
                                              &count, 50);
        if (ret == ESP_ERR_TIMEOUT || count == 0) continue;

        // Copiar al staging buffer para DSP
        if (xSemaphoreTake(s_staging_mutex, pdMS_TO_TICKS(5)) == pdTRUE) {
            size_t copy = count < SAMPLE_BUF_SIZE ? count : SAMPLE_BUF_SIZE;
            memcpy(s_adc_staging, s_sample_buf, copy * sizeof(osc_sample_t));
            xSemaphoreGive(s_staging_mutex);

            adc_batch_t batch = {
                .count        = copy,
                .timestamp_us = s_sample_buf[0].timestamp_us,
            };
            // No bloquear si el queue está lleno (la DSP task está ocupada)
            xQueueSend(s_adc_queue, &batch, 0);
        }
    }
}

/* --------------------------------------------------------------------------
 * TAREA: DSP_PROCESS (Core 0, prioridad media)
 *   - Recibe batches del queue
 *   - Acumula muestras hasta completar un frame
 *   - Aplica trigger, mediciones, FFT
 *   - Envía frame por USB si streaming=true
 * -------------------------------------------------------------------------- */
static void dsp_process_task(void *arg)
{
    ESP_LOGI(TAG, "DSP_PROCESS iniciado en Core %d", xPortGetCoreID());

    // Acumulador de muestras para el frame completo
    static osc_sample_t frame_accum[MAX_FRAME_SAMPLES];
    size_t frame_fill = 0;

    // Pre-trigger ring buffer
    static osc_sample_t pre_trig_buf[512];
    size_t pre_trig_len = 0;
    bool   waiting_trigger = false;
    uint64_t last_auto_trigger_ms = 0;

    osc_trigger_init();

    // Preparar frame de salida (los buffers apuntan a arrays estáticos)
    osc_frame_t out_frame = {
        .ch0_data          = s_ch0_buf,
        .ch1_data          = s_ch1_buf,
        .fft_magnitudes_ch0 = s_fft_buf,
    };

    adc_batch_t batch;

    while (1) {
        if (xQueueReceive(s_adc_queue, &batch, pdMS_TO_TICKS(10)) != pdTRUE) {
            continue;
        }

        osc_config_t cfg;
        osc_config_get(&cfg);

        if (!cfg.streaming) {
            frame_fill = 0;
            continue;
        }

        // Copiar batch del staging buffer al acumulador
        if (xSemaphoreTake(s_staging_mutex, pdMS_TO_TICKS(5)) != pdTRUE) continue;
        size_t to_copy = batch.count;
        if (frame_fill + to_copy > cfg.frame_size) {
            to_copy = cfg.frame_size - frame_fill;
        }
        memcpy(&frame_accum[frame_fill], s_adc_staging, to_copy * sizeof(osc_sample_t));
        xSemaphoreGive(s_staging_mutex);

        frame_fill += to_copy;

        // ¿Tenemos un frame completo?
        if (frame_fill < cfg.frame_size) continue;

        // --- Trigger evaluation ---
        osc_trigger_apply_config();
        osc_trigger_result_t trig_result;
        osc_trigger_evaluate(frame_accum, frame_fill, &trig_result);

        // Auto-trigger si no se detectó trigger en el timeout
        uint64_t now_ms = esp_timer_get_time() / 1000;
        if (!trig_result.triggered && cfg.auto_trigger &&
            (now_ms - last_auto_trigger_ms) >= cfg.auto_trigger_timeout_ms) {
            trig_result.triggered     = false;  // marcado como auto-trigger
            last_auto_trigger_ms      = now_ms;
        } else if (trig_result.triggered) {
            last_auto_trigger_ms = now_ms;
        } else {
            // No trigger y no auto-trigger todavía: descartar frame
            frame_fill = 0;
            continue;
        }

        // --- Procesar frame completo ---
        uint8_t overflow_flag = osc_adc_get_overflow_count() > 0;
        osc_adc_reset_overflow_count();

        out_frame.overflow     = overflow_flag;
        out_frame.seq_num      = 0;  // será asignado por osc_usb
        out_frame.fft_points   = 0;

        esp_err_t dsp_ret = osc_dsp_process_frame(frame_accum, frame_fill,
                                                    &out_frame, &trig_result);

        if (dsp_ret == ESP_OK && osc_usb_is_connected()) {
            led_set(true);
            osc_usb_send_data_frame(&out_frame);

            // Enviar mediciones cada 10 frames para no saturar USB
            static uint8_t meas_counter = 0;
            if (++meas_counter >= 10) {
                osc_usb_send_measurements(&out_frame);
                meas_counter = 0;
            }
            led_set(false);
        }

        // Resetear acumulador para el próximo frame
        frame_fill = 0;
        osc_trigger_reset();
    }
}

/* --------------------------------------------------------------------------
 * app_main — Entry point
 * -------------------------------------------------------------------------- */
void app_main(void)
{
    ESP_LOGI(TAG, "ESP32-S3 Oscilloscope v%d.%d arrancando...",
             OSC_FW_VERSION_MAJOR, OSC_FW_VERSION_MINOR);

    // --- NVS Flash ---
    esp_err_t nvs_ret = nvs_flash_init();
    if (nvs_ret == ESP_ERR_NVS_NO_FREE_PAGES ||
        nvs_ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS limpiando...");
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_ret);

    // --- Hardware básico ---
    led_init();
    init_test_signal();

    // --- Inicializar módulos (en orden de dependencia) ---
    ESP_ERROR_CHECK(osc_config_init());
    ESP_ERROR_CHECK(osc_adc_init());
    ESP_ERROR_CHECK(osc_dsp_init());
    ESP_ERROR_CHECK(osc_usb_init());

    // --- Allocar buffers en PSRAM ---
    s_sample_buf = (osc_sample_t *)heap_caps_malloc(
        SAMPLE_BUF_SIZE * sizeof(osc_sample_t), MALLOC_CAP_SPIRAM);
    if (!s_sample_buf) {
        ESP_LOGE(TAG, "Sin memoria PSRAM para sample buffer");
        s_sample_buf = (osc_sample_t *)malloc(SAMPLE_BUF_SIZE * sizeof(osc_sample_t));
        if (!s_sample_buf) {
            ESP_LOGE(TAG, "FATAL: sin memoria");
            abort();
        }
    }

    // --- Sincronización entre tareas ---
    s_adc_queue     = xQueueCreate(8, sizeof(adc_batch_t));
    s_staging_mutex = xSemaphoreCreateMutex();
    if (!s_adc_queue || !s_staging_mutex) {
        ESP_LOGE(TAG, "FATAL: no se pudo crear queue/mutex");
        abort();
    }

    // --- Crear tareas ---
    // DSP_PROCESS en Core 0 (debe crearse ANTES de ADC_CAPTURE para que el
    // queue receptor esté listo)
    xTaskCreatePinnedToCore(
        dsp_process_task, "dsp_proc",
        8192, NULL,
        10, NULL, 0  // Core 0
    );

    // ADC_CAPTURE en Core 1 — máxima prioridad, pinned
    xTaskCreatePinnedToCore(
        adc_capture_task, "adc_cap",
        4096, NULL,
        24, NULL, 1  // Core 1
    );

    // Heartbeat cada 1s para indicar que el sistema está vivo
    while (1) {
        led_set(true);
        vTaskDelay(pdMS_TO_TICKS(50));
        led_set(false);
        vTaskDelay(pdMS_TO_TICKS(950));
        ESP_LOGD(TAG, "Heap libre: %lu KB | PSRAM libre: %lu KB",
                 esp_get_free_heap_size() / 1024,
                 heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024);
    }
}
