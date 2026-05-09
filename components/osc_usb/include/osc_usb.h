#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"
#include "osc_dsp.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Inicializar el stack TinyUSB CDC y las tareas de comunicación.
 *        Llama después de osc_config_init() y osc_dsp_init().
 */
esp_err_t osc_usb_init(void);

/**
 * @brief Serializar y enviar un frame de datos por USB CDC.
 *        Thread-safe. No bloquea si el buffer TX está lleno (descarta el frame).
 */
esp_err_t osc_usb_send_data_frame(const osc_frame_t *frame);

/**
 * @brief Enviar un frame de mediciones.
 */
esp_err_t osc_usb_send_measurements(const osc_frame_t *frame);

/**
 * @brief Enviar un frame de información del dispositivo.
 */
esp_err_t osc_usb_send_info(void);

/**
 * @brief Enviar ACK de un comando.
 * @param cmd_str  String del comando que se confirma (max 32 chars)
 */
esp_err_t osc_usb_send_ack(const char *cmd_str);

/**
 * @brief Enviar NAK con mensaje de error.
 */
esp_err_t osc_usb_send_nak(const char *cmd_str, const char *reason);

/**
 * @brief Verificar si hay un host USB conectado y listo.
 */
bool osc_usb_is_connected(void);

/**
 * @brief Enviar frame PGA_INFO (0x08) con estado completo del PGA.
 */
esp_err_t osc_usb_send_pga_info(void);

#ifdef __cplusplus
}
#endif
