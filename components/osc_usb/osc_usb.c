#include "osc_usb.h"
#include "osc_protocol.h"
#include "osc_config.h"
#include "osc_adc.h"
#include "osc_dsp.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "tinyusb.h"
#include "tinyusb_cdc_acm.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

static const char *TAG = "osc_usb";

/* --------------------------------------------------------------------------
 * Estado interno
 * -------------------------------------------------------------------------- */
static bool              s_connected     = false;
static SemaphoreHandle_t s_tx_mutex      = NULL;
static uint8_t           s_tx_buf[OSC_MAX_FRAME_BYTES];
static uint16_t          s_seq_num       = 0;
static uint8_t           s_rx_buf[256];
static size_t            s_rx_len        = 0;
static QueueHandle_t     s_cmd_queue     = NULL;

/* --------------------------------------------------------------------------
 * CRC8 Dallas/Maxim (polinomio 0x31)
 * -------------------------------------------------------------------------- */
static const uint8_t CRC8_TABLE[256] = {
    0x00,0x5E,0xBC,0xE2,0x61,0x3F,0xDD,0x83,0xC2,0x9C,0x7E,0x20,0xA3,0xFD,0x1F,0x41,
    0x9D,0xC3,0x21,0x7F,0xFC,0xA2,0x40,0x1E,0x5F,0x01,0xE3,0xBD,0x3E,0x60,0x82,0xDC,
    0x23,0x7D,0x9F,0xC1,0x42,0x1C,0xFE,0xA0,0xE1,0xBF,0x5D,0x03,0x80,0xDE,0x3C,0x62,
    0xBE,0xE0,0x02,0x5C,0xDF,0x81,0x63,0x3D,0x7C,0x22,0xC0,0x9E,0x1D,0x43,0xA1,0xFF,
    0x46,0x18,0xFA,0xA4,0x27,0x79,0x9B,0xC5,0x84,0xDA,0x38,0x66,0xE5,0xBB,0x59,0x07,
    0xDB,0x85,0x67,0x39,0xBA,0xE4,0x06,0x58,0x19,0x47,0xA5,0xFB,0x78,0x26,0xC4,0x9A,
    0x65,0x3B,0xD9,0x87,0x04,0x5A,0xB8,0xE6,0xA7,0xF9,0x1B,0x45,0xC6,0x98,0x7A,0x24,
    0xF8,0xA6,0x44,0x1A,0x99,0xC7,0x25,0x7B,0x3A,0x64,0x86,0xD8,0x5B,0x05,0xE7,0xB9,
    0x8C,0xD2,0x30,0x6E,0xED,0xB3,0x51,0x0F,0x4E,0x10,0xF2,0xAC,0x2F,0x71,0x93,0xCD,
    0x11,0x4F,0xAD,0xF3,0x70,0x2E,0xCC,0x92,0xD3,0x8D,0x6F,0x31,0xB2,0xEC,0x0E,0x50,
    0xAF,0xF1,0x13,0x4D,0xCE,0x90,0x72,0x2C,0x6D,0x33,0xD1,0x8F,0x0C,0x52,0xB0,0xEE,
    0x32,0x6C,0x8E,0xD0,0x53,0x0D,0xEF,0xB1,0xF0,0xAE,0x4C,0x12,0x91,0xCF,0x2D,0x73,
    0xCA,0x94,0x76,0x28,0xAB,0xF5,0x17,0x49,0x08,0x56,0xB4,0xEA,0x69,0x37,0xD5,0x8B,
    0x57,0x09,0xEB,0xB5,0x36,0x68,0x8A,0xD4,0x95,0xCB,0x29,0x77,0xF4,0xAA,0x48,0x16,
    0xE9,0xB7,0x55,0x0B,0x88,0xD6,0x34,0x6A,0x2B,0x75,0x97,0xC9,0x4A,0x14,0xF6,0xA8,
    0x74,0x2A,0xC8,0x96,0x15,0x4B,0xA9,0xF7,0xB6,0xE8,0x0A,0x54,0xD7,0x89,0x6B,0x35,
};

static uint8_t crc8(const uint8_t *data, size_t len)
{
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) crc = CRC8_TABLE[crc ^ data[i]];
    return crc;
}

/* --------------------------------------------------------------------------
 * Callbacks TinyUSB
 * -------------------------------------------------------------------------- */
static void tusb_cdc_rx_callback(int itf, cdcacm_event_t *event)
{
    uint8_t tmp[256];
    size_t rx_size = 0;
    tinyusb_cdcacm_read(itf, tmp, sizeof(tmp), &rx_size);

    for (size_t i = 0; i < rx_size; i++) {
        if (tmp[i] == '\n' || tmp[i] == '\r') {
            if (s_rx_len > 0) {
                s_rx_buf[s_rx_len] = '\0';
                // CDC callback en esp_tinyusb v2.x corre desde tarea, NO desde ISR
                if (s_cmd_queue) {
                    char cmd[256];
                    memcpy(cmd, s_rx_buf, s_rx_len + 1);
                    xQueueSend(s_cmd_queue, cmd, 0);
                }
                s_rx_len = 0;
            }
        } else if (s_rx_len < sizeof(s_rx_buf) - 1) {
            s_rx_buf[s_rx_len++] = tmp[i];
        }
    }
}

static void tusb_cdc_line_state_callback(int itf, cdcacm_event_t *event)
{
    bool dtr = event->line_state_changed_data.dtr;
    bool rts = event->line_state_changed_data.rts;
    s_connected = dtr || rts;
    ESP_LOGI(TAG, "USB CDC %s", s_connected ? "conectado" : "desconectado");
    if (!s_connected) {
        // Detener stream al desconectar
        osc_config_set_streaming(false);
    }
}

/* --------------------------------------------------------------------------
 * Procesador de comandos (corre en USB_COMM_Task)
 * -------------------------------------------------------------------------- */
static void process_command(const char *cmd)
{
    ESP_LOGD(TAG, "CMD: [%s]", cmd);

    if (strcmp(cmd, OSC_CMD_GET_CAPS) == 0) {
        osc_usb_send_info();
        osc_usb_send_ack(cmd);
        return;
    }

    if (strcmp(cmd, OSC_CMD_STREAM_START) == 0) {
        osc_config_set_streaming(true);
        osc_usb_send_ack(cmd);
        return;
    }

    if (strcmp(cmd, OSC_CMD_STREAM_STOP) == 0) {
        osc_config_set_streaming(false);
        osc_usb_send_ack(cmd);
        return;
    }

    if (strcmp(cmd, OSC_CMD_FACTORY_RESET) == 0) {
        osc_config_factory_reset();
        osc_usb_send_ack(cmd);
        return;
    }

    // CMD_SET_MODE <mode>
    if (strncmp(cmd, OSC_CMD_SET_MODE, strlen(OSC_CMD_SET_MODE)) == 0) {
        int mode = 0;
        if (sscanf(cmd + strlen(OSC_CMD_SET_MODE), " %d", &mode) == 1) {
            if (osc_config_set_mode((osc_mode_t)mode) == ESP_OK)
                osc_usb_send_ack(cmd);
            else
                osc_usb_send_nak(cmd, "modo invalido");
        } else {
            osc_usb_send_nak(cmd, "argumento requerido");
        }
        return;
    }

    // CMD_SET_RATE <hz>
    if (strncmp(cmd, OSC_CMD_SET_RATE, strlen(OSC_CMD_SET_RATE)) == 0) {
        unsigned hz = 0;
        if (sscanf(cmd + strlen(OSC_CMD_SET_RATE), " %u", &hz) == 1) {
            if (osc_config_set_rate(hz) == ESP_OK)
                osc_usb_send_ack(cmd);
            else
                osc_usb_send_nak(cmd, "frecuencia fuera de rango");
        } else {
            osc_usb_send_nak(cmd, "argumento requerido");
        }
        return;
    }

    // CMD_SET_TRIG <ch> <mv> <edge>
    if (strncmp(cmd, OSC_CMD_SET_TRIG, strlen(OSC_CMD_SET_TRIG)) == 0) {
        int ch = 0, edge = 0; float mv = 0;
        if (sscanf(cmd + strlen(OSC_CMD_SET_TRIG), " %d %f %d", &ch, &mv, &edge) == 3) {
            if (osc_config_set_trigger(mv, (osc_trig_edge_t)edge, (uint8_t)ch) == ESP_OK)
                osc_usb_send_ack(cmd);
            else
                osc_usb_send_nak(cmd, "parametros invalidos");
        } else {
            osc_usb_send_nak(cmd, "3 argumentos requeridos: ch mv edge");
        }
        return;
    }

    // CMD_SET_ATTEN <ch> <db>
    if (strncmp(cmd, OSC_CMD_SET_ATTEN, strlen(OSC_CMD_SET_ATTEN)) == 0) {
        int ch = 0, db = 0;
        if (sscanf(cmd + strlen(OSC_CMD_SET_ATTEN), " %d %d", &ch, &db) == 2) {
            if (osc_config_set_atten((uint8_t)ch, (osc_atten_t)db) == ESP_OK)
                osc_usb_send_ack(cmd);
            else
                osc_usb_send_nak(cmd, "parametros invalidos");
        } else {
            osc_usb_send_nak(cmd, "2 argumentos requeridos: ch db");
        }
        return;
    }

    // CMD_SET_FRAME <n>
    if (strncmp(cmd, OSC_CMD_SET_FRAME, strlen(OSC_CMD_SET_FRAME)) == 0) {
        unsigned n = 0;
        if (sscanf(cmd + strlen(OSC_CMD_SET_FRAME), " %u", &n) == 1) {
            if (osc_config_set_frame_size(n) == ESP_OK)
                osc_usb_send_ack(cmd);
            else
                osc_usb_send_nak(cmd, "debe ser potencia de 2 entre 64 y 4096");
        } else {
            osc_usb_send_nak(cmd, "argumento requerido");
        }
        return;
    }

    // CMD_SET_PRE_TRIG <n>
    if (strncmp(cmd, OSC_CMD_SET_PRE_TRIG, strlen(OSC_CMD_SET_PRE_TRIG)) == 0) {
        unsigned n = 0;
        if (sscanf(cmd + strlen(OSC_CMD_SET_PRE_TRIG), " %u", &n) == 1) {
            osc_config_set_pre_trigger(n);
            osc_usb_send_ack(cmd);
        } else {
            osc_usb_send_nak(cmd, "argumento requerido");
        }
        return;
    }

    // CMD_SET_FFT <en>
    if (strncmp(cmd, OSC_CMD_SET_FFT, strlen(OSC_CMD_SET_FFT)) == 0) {
        int en = 0;
        if (sscanf(cmd + strlen(OSC_CMD_SET_FFT), " %d", &en) == 1) {
            osc_config_set_fft(en != 0);
            osc_usb_send_ack(cmd);
        } else {
            osc_usb_send_nak(cmd, "argumento requerido: 0 o 1");
        }
        return;
    }

    osc_usb_send_nak(cmd, "comando desconocido");
}

/* --------------------------------------------------------------------------
 * Construcción de frames binarios
 * -------------------------------------------------------------------------- */
static size_t build_data_frame(const osc_frame_t *frame, uint8_t *out_buf)
{
    size_t pos = 0;
    osc_config_t cfg;
    osc_config_get(&cfg);
    bool dual = (cfg.mode == OSC_MODE_DUAL_CH);

    uint8_t flags = OSC_FLAG_CH0_VALID;
    if (dual)                 flags |= OSC_FLAG_CH1_VALID;
    if (frame->trigger_hit)   flags |= OSC_FLAG_TRIGGER_HIT;
    if (frame->overflow)      flags |= OSC_FLAG_OVERFLOW;
    if (cfg.fft_enabled && frame->fft_points > 0)
                              flags |= OSC_FLAG_FFT_ATTACHED;

    // Header (16 bytes)
    out_buf[pos++] = OSC_PROTO_SYNC1;
    out_buf[pos++] = OSC_PROTO_SYNC2;
    out_buf[pos++] = OSC_FRAME_DATA;
    out_buf[pos++] = flags;
    out_buf[pos++] = (uint8_t)(s_seq_num & 0xFF);
    out_buf[pos++] = (uint8_t)((s_seq_num >> 8) & 0xFF);
    out_buf[pos++] = (uint8_t)(frame->sample_count & 0xFF);
    out_buf[pos++] = (uint8_t)((frame->sample_count >> 8) & 0xFF);
    // timestamp_us (4 bytes LE)
    uint32_t ts = frame->timestamp_us;
    memcpy(&out_buf[pos], &ts, 4); pos += 4;
    // trigger_index (4 bytes LE)
    uint32_t ti = frame->trigger_index;
    memcpy(&out_buf[pos], &ti, 4); pos += 4;

    // CH0 data
    size_t data_bytes = frame->sample_count * sizeof(int16_t);
    memcpy(&out_buf[pos], frame->ch0_data, data_bytes);
    pos += data_bytes;

    // CH1 data (si dual)
    if (dual && frame->ch1_data) {
        memcpy(&out_buf[pos], frame->ch1_data, data_bytes);
        pos += data_bytes;
    }

    // CRC8 sobre todos los bytes anteriores
    out_buf[pos] = crc8(out_buf, pos);
    pos++;

    s_seq_num++;
    return pos;
}

static size_t build_measurements_frame(const osc_frame_t *frame, uint8_t *out_buf)
{
    size_t pos = 0;
    osc_config_t cfg;
    osc_config_get(&cfg);
    bool dual = (cfg.mode == OSC_MODE_DUAL_CH);

    uint8_t flags = OSC_FLAG_CH0_VALID | (dual ? OSC_FLAG_CH1_VALID : 0);

    out_buf[pos++] = OSC_PROTO_SYNC1;
    out_buf[pos++] = OSC_PROTO_SYNC2;
    out_buf[pos++] = OSC_FRAME_MEASUREMENTS;
    out_buf[pos++] = flags;

    // Serializar osc_measurements_t ch0
    const osc_measurements_t *m = &frame->meas_ch0;
    memcpy(&out_buf[pos], &m->vpp_mv,         4); pos += 4;
    memcpy(&out_buf[pos], &m->vrms_mv,        4); pos += 4;
    memcpy(&out_buf[pos], &m->vdc_mv,         4); pos += 4;
    memcpy(&out_buf[pos], &m->vac_rms_mv,     4); pos += 4;
    memcpy(&out_buf[pos], &m->vmax_mv,        4); pos += 4;
    memcpy(&out_buf[pos], &m->vmin_mv,        4); pos += 4;
    memcpy(&out_buf[pos], &m->freq_hz,        4); pos += 4;
    memcpy(&out_buf[pos], &m->period_us,      4); pos += 4;
    memcpy(&out_buf[pos], &m->duty_cycle_pct, 4); pos += 4;
    memcpy(&out_buf[pos], &m->rise_time_us,   4); pos += 4;
    memcpy(&out_buf[pos], &m->fall_time_us,   4); pos += 4;
    out_buf[pos++] = m->valid ? 1 : 0;

    if (dual) {
        m = &frame->meas_ch1;
        memcpy(&out_buf[pos], &m->vpp_mv,         4); pos += 4;
        memcpy(&out_buf[pos], &m->vrms_mv,        4); pos += 4;
        memcpy(&out_buf[pos], &m->vdc_mv,         4); pos += 4;
        memcpy(&out_buf[pos], &m->vac_rms_mv,     4); pos += 4;
        memcpy(&out_buf[pos], &m->vmax_mv,        4); pos += 4;
        memcpy(&out_buf[pos], &m->vmin_mv,        4); pos += 4;
        memcpy(&out_buf[pos], &m->freq_hz,        4); pos += 4;
        memcpy(&out_buf[pos], &m->period_us,      4); pos += 4;
        memcpy(&out_buf[pos], &m->duty_cycle_pct, 4); pos += 4;
        memcpy(&out_buf[pos], &m->rise_time_us,   4); pos += 4;
        memcpy(&out_buf[pos], &m->fall_time_us,   4); pos += 4;
        out_buf[pos++] = m->valid ? 1 : 0;
    }

    out_buf[pos] = crc8(out_buf, pos); pos++;
    return pos;
}

/* --------------------------------------------------------------------------
 * API pública de envío
 * -------------------------------------------------------------------------- */
static esp_err_t usb_write_raw(const uint8_t *buf, size_t len)
{
    if (!s_connected || !tud_cdc_n_connected(0)) return ESP_ERR_INVALID_STATE;
    size_t queued = tinyusb_cdcacm_write_queue(0, buf, len);
    if (queued > 0) {
        tinyusb_cdcacm_write_flush(0, pdMS_TO_TICKS(10));
    }
    return (queued == len) ? ESP_OK : ESP_FAIL;
}

esp_err_t osc_usb_send_data_frame(const osc_frame_t *frame)
{
    if (!frame || !frame->ch0_data) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_tx_mutex, portMAX_DELAY);
    size_t len = build_data_frame(frame, s_tx_buf);
    esp_err_t ret = usb_write_raw(s_tx_buf, len);
    xSemaphoreGive(s_tx_mutex);
    return ret;
}

esp_err_t osc_usb_send_measurements(const osc_frame_t *frame)
{
    if (!frame) return ESP_ERR_INVALID_ARG;
    xSemaphoreTake(s_tx_mutex, portMAX_DELAY);
    size_t len = build_measurements_frame(frame, s_tx_buf);
    esp_err_t ret = usb_write_raw(s_tx_buf, len);
    xSemaphoreGive(s_tx_mutex);
    return ret;
}

esp_err_t osc_usb_send_info(void)
{
    uint8_t buf[64];
    memset(buf, 0, sizeof(buf));
    size_t pos = 0;

    buf[pos++] = OSC_PROTO_SYNC1;
    buf[pos++] = OSC_PROTO_SYNC2;
    buf[pos++] = OSC_FRAME_INFO;
    buf[pos++] = OSC_FW_VERSION_MAJOR;
    buf[pos++] = OSC_FW_VERSION_MINOR;

    uint32_t max_rate = 150000;
    memcpy(&buf[pos], &max_rate, 4); pos += 4;

    uint16_t max_frame = 4096;
    memcpy(&buf[pos], &max_frame, 2); pos += 2;

    uint16_t caps = OSC_CAP_DUAL_CHANNEL | OSC_CAP_FFT |
                    OSC_CAP_OVERSAMPLE   | OSC_CAP_CLOCK_HACK;
    memcpy(&buf[pos], &caps, 2); pos += 2;

    const char *fw_str = "ESP32S3-OSC v1.0";
    size_t fw_len = strlen(fw_str);
    if (fw_len > 31) fw_len = 31;
    memcpy(&buf[pos], fw_str, fw_len);
    pos += 32;  // campo fijo de 32 bytes

    buf[pos] = crc8(buf, pos); pos++;

    xSemaphoreTake(s_tx_mutex, portMAX_DELAY);
    esp_err_t ret = usb_write_raw(buf, pos);
    xSemaphoreGive(s_tx_mutex);
    return ret;
}

esp_err_t osc_usb_send_ack(const char *cmd_str)
{
    uint8_t buf[48];
    memset(buf, 0, sizeof(buf));
    size_t pos = 0;
    buf[pos++] = OSC_PROTO_SYNC1;
    buf[pos++] = OSC_PROTO_SYNC2;
    buf[pos++] = OSC_FRAME_ACK;
    size_t clen = strlen(cmd_str);
    if (clen > 31) clen = 31;
    memcpy(&buf[pos], cmd_str, clen);
    pos += 32;
    buf[pos] = crc8(buf, pos); pos++;

    xSemaphoreTake(s_tx_mutex, portMAX_DELAY);
    esp_err_t ret = usb_write_raw(buf, pos);
    xSemaphoreGive(s_tx_mutex);
    return ret;
}

esp_err_t osc_usb_send_nak(const char *cmd_str, const char *reason)
{
    uint8_t buf[80];
    memset(buf, 0, sizeof(buf));
    size_t pos = 0;
    buf[pos++] = OSC_PROTO_SYNC1;
    buf[pos++] = OSC_PROTO_SYNC2;
    buf[pos++] = OSC_FRAME_NAK;
    size_t clen = strlen(cmd_str);
    if (clen > 31) clen = 31;
    memcpy(&buf[pos], cmd_str, clen);
    pos += 32;
    size_t rlen = reason ? strlen(reason) : 0;
    if (rlen > 31) rlen = 31;
    if (reason) memcpy(&buf[pos], reason, rlen);
    pos += 32;
    buf[pos] = crc8(buf, pos); pos++;

    xSemaphoreTake(s_tx_mutex, portMAX_DELAY);
    esp_err_t ret = usb_write_raw(buf, pos);
    xSemaphoreGive(s_tx_mutex);
    return ret;
}

bool osc_usb_is_connected(void) { return s_connected; }

/* --------------------------------------------------------------------------
 * Tarea de procesamiento de comandos
 * -------------------------------------------------------------------------- */
static void cmd_task(void *arg)
{
    char cmd[256];
    while (1) {
        if (xQueueReceive(s_cmd_queue, cmd, portMAX_DELAY) == pdTRUE) {
            process_command(cmd);
        }
    }
}

/* --------------------------------------------------------------------------
 * Inicialización
 * -------------------------------------------------------------------------- */
esp_err_t osc_usb_init(void)
{
    s_tx_mutex  = xSemaphoreCreateMutex();
    s_cmd_queue = xQueueCreate(16, 256);
    if (!s_tx_mutex || !s_cmd_queue) return ESP_ERR_NO_MEM;

    // Configurar TinyUSB
    const tinyusb_config_t tusb_cfg = {
        .port = TINYUSB_PORT_FULL_SPEED_0,
        .phy = {
            .skip_setup = false,
            .self_powered = false,
            .vbus_monitor_io = -1,
        },
        .descriptor = {
            .device = NULL,
            .string = NULL,
            .string_count = 0,
            .full_speed_config = NULL,
            .high_speed_config = NULL,
        },
        .task = {
            .size = 4096,
            .priority = 20,
            .xCoreID = 0,
        }
    };
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));

    // Configurar CDC ACM
    const tinyusb_config_cdcacm_t acm_cfg = {
        .cdc_port                  = TINYUSB_CDC_ACM_0,
        .callback_rx               = tusb_cdc_rx_callback,
        .callback_rx_wanted_char   = NULL,
        .callback_line_state_changed = tusb_cdc_line_state_callback,
        .callback_line_coding_changed = NULL,
    };
    ESP_ERROR_CHECK(tinyusb_cdcacm_init(&acm_cfg));

    // Tarea de comandos en Core 0, baja prioridad
    xTaskCreatePinnedToCore(cmd_task, "osc_cmd", 4096, NULL, 5, NULL, 0);

    ESP_LOGI(TAG, "USB CDC listo (GPIO19=D-, GPIO20=D+)");
    return ESP_OK;
}
