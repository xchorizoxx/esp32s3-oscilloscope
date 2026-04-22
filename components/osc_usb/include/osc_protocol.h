#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* =========================================================================
 * Protocolo binario ESP32-S3 Oscilloscope v1.0
 * =========================================================================
 *
 * DIRECCIÓN ESP32 → PC:
 *   Todos los frames comienzan con SYNC (0xAA 0x55) y terminan con CRC8.
 *
 * DIRECCIÓN PC → ESP32:
 *   Comandos ASCII terminados en '\n'. El ESP32 responde con ACK/NAK frame.
 *
 * CRC8: polinomio 0x31 (Dallas/Maxim). Se calcula sobre TODOS los bytes del
 *        frame incluyendo los bytes de sync.
 * ========================================================================= */

// Bytes de sincronización
#define OSC_PROTO_SYNC1 0xAA
#define OSC_PROTO_SYNC2 0x55

// Tipos de frame (FRAME_TYPE byte)
#define OSC_FRAME_DATA 0x01         ///< Frame de muestras ADC
#define OSC_FRAME_MEASUREMENTS 0x02 ///< Frame de mediciones automáticas
#define OSC_FRAME_ACK 0x03          ///< Confirmación de comando
#define OSC_FRAME_NAK 0x04          ///< Rechazo de comando
#define OSC_FRAME_INFO                                                         \
  0x05 ///< Información del dispositivo (respuesta a GET_CAPS)
#define OSC_FRAME_FFT 0x06       ///< Frame de datos FFT
#define OSC_FRAME_HEARTBEAT 0x07 ///< Heartbeat periódico (1 Hz)

// Bits de FLAGS (byte de flags en frames de datos)
#define OSC_FLAG_CH0_VALID (1 << 0)
#define OSC_FLAG_CH1_VALID (1 << 1)
#define OSC_FLAG_TRIGGER_HIT (1 << 2)
#define OSC_FLAG_OVERFLOW (1 << 3)
#define OSC_FLAG_FFT_ATTACHED (1 << 4) ///< frame de FFT sigue inmediatamente

/* =========================================================================
 * Layouts de frames
 * =========================================================================
 *
 * DATA FRAME (FRAME_TYPE = 0x01):
 * ┌────────┬────────┬────────────┬─────────┬──────────────┬────────────────┬─────────────────┬─────┐
 * │ 0xAA   │ 0x55   │ FRAME_TYPE │  FLAGS  │  SEQ_NUM     │ SAMPLE_COUNT   │
 * TIMESTAMP_US    │ ... │ │ 1 byte │ 1 byte │  1 byte    │ 1 byte  │  2 bytes
 * LE  │  2 bytes LE    │  4 bytes LE     │     │
 * ├────────┴────────┴────────────┴─────────┴──────────────┴────────────────┴─────────────────┤
 * │ │ TRIGGER_INDEX (4 bytes LE) │ CH0_DATA (SAMPLE_COUNT * 2 bytes, int16 LE,
 * mV*10)          │     │
 * ├────────────────────────────┴─────────────────────────────────────────────────────────────┤
 * │ │ [CH1_DATA (SAMPLE_COUNT * 2 bytes, int16 LE) si CH1_VALID=1] │     │
 * ├──────────────────────────────────────────────────────────────────────────────────────────┤
 * │ │ CRC8 (1 byte) — calculado sobre TODOS los bytes anteriores incluyendo
 * sync               │     │
 * └──────────────────────────────────────────────────────────────────────────────────────────┴─────┘
 *
 * Total header fijo: 2(sync) + 1(type) + 1(flags) + 2(seq) + 2(count) + 4(ts) +
 * 4(trig_idx) = 16 bytes
 *
 * MEASUREMENTS FRAME (FRAME_TYPE = 0x02):
 * ┌───────┬───────┬──────┬───────┬────────────────────────────────────────────────────────────┐
 * │ 0xAA  │ 0x55  │ 0x02 │ FLAGS │ CH0: vpp(4) vrms(4) vdc(4) vac_rms(4)
 * vmax(4) vmin(4)      │ │       │       │      │       │      freq(4)
 * period(4) duty(4) rise(4) fall(4) valid(1)    │ │       │       │      │ │
 * CH1: mismos campos que CH0 (si CH1_VALID=1)                │ │       │ │ │ │
 * CRC8 (1 byte)                                              │
 * └───────┴───────┴──────┴───────┴────────────────────────────────────────────────────────────┘
 * Total: 2+1+1 + 45 (ch0) + 45 (ch1, opcional) + 1 = 50 o 95 bytes
 *
 * INFO FRAME (FRAME_TYPE = 0x05):
 * ┌────────────────────────────────────────────────────────────────┐
 * │ 0xAA 0x55 0x05 VERSION_MAJOR VERSION_MINOR MAX_RATE_HZ(4)      │
 * │ MAX_FRAME_SIZE(2) CAPS_FLAGS(2) FW_STRING(32 bytes null-term)  │
 * │ CRC8                                                           │
 * └────────────────────────────────────────────────────────────────┘
 *
 * FFT FRAME (FRAME_TYPE = 0x06):
 * ┌────────────────────────────────────────────────────────────────┐
 * │ 0xAA 0x55 0x06 FLAGS SEQ(2) FFT_POINTS(2) BIN_HZ_x100(4)       │
 * │ MAGNITUDES_MV (FFT_POINTS/2 * 4 bytes float32 LE)              │
 * │ CRC8                                                           │
 * └────────────────────────────────────────────────────────────────┘
 * ========================================================================= */

// Capacidades del firmware (bits de CAPS_FLAGS en INFO frame)
#define OSC_CAP_DUAL_CHANNEL (1 << 0)
#define OSC_CAP_FFT (1 << 1)
#define OSC_CAP_OVERSAMPLE (1 << 2)
#define OSC_CAP_CLOCK_HACK (1 << 3) ///< frecuencia > 83333 Hz disponible

// Versión del firmware
#define OSC_FW_VERSION_MAJOR 1
#define OSC_FW_VERSION_MINOR 0

// Máximo tamaño de un frame de datos (para dimensionar buffers)
// 16 (header) + 2*512*2 (dual 512 samples) + 1 (CRC) = 2065 bytes
#define OSC_MAX_FRAME_BYTES 4096

/* =========================================================================
 * Comandos ASCII (PC → ESP32, terminados en '\n')
 * =========================================================================
 *
 * CMD_GET_CAPS                   → INFO frame
 * CMD_STREAM_START               → ACK + inicio del stream de DATA frames
 * CMD_STREAM_STOP                → ACK + detención del stream
 * CMD_SINGLE_SHOT                → ACK + espera trigger + 1 DATA frame
 * CMD_SET_MODE <mode>            → ACK (mode: 0=SINGLE_CH 1=DUAL_CH
 * 2=OVERSAMPLE) CMD_SET_RATE <hz>              → ACK (hz: 611..160000)
 * CMD_SET_TRIG <ch> <mv> <edge>  → ACK (ch: 0/1, mv: flotante, edge: 0=RISE
 * 1=FALL 2=ANY 3=NONE) CMD_SET_ATTEN <ch> <db>        → ACK (ch: 0/1, db:
 * 0/1/2/3 = 0/2.5/6/12 dB) CMD_SET_FRAME <n>              → ACK (n:
 * 64/128/256/512/1024/2048/4096) CMD_SET_PRE_TRIG <n>           → ACK (n:
 * 0..frame_size/2) CMD_SET_FFT <en>               → ACK (en: 0=off 1=on)
 * CMD_FACTORY_RESET              → ACK
 * CMD_GET_STATUS                 → MEASUREMENTS frame con estado actual
 * ========================================================================= */

#define OSC_CMD_GET_CAPS "CMD_GET_CAPS"
#define OSC_CMD_STREAM_START "CMD_STREAM_START"
#define OSC_CMD_STREAM_STOP "CMD_STREAM_STOP"
#define OSC_CMD_SINGLE_SHOT "CMD_SINGLE_SHOT"
#define OSC_CMD_SET_MODE "CMD_SET_MODE"
#define OSC_CMD_SET_RATE "CMD_SET_RATE"
#define OSC_CMD_SET_TRIG "CMD_SET_TRIG"
#define OSC_CMD_SET_ATTEN "CMD_SET_ATTEN"
#define OSC_CMD_SET_FRAME "CMD_SET_FRAME"
#define OSC_CMD_SET_PRE_TRIG "CMD_SET_PRE_TRIG"
#define OSC_CMD_SET_FFT "CMD_SET_FFT"
#define OSC_CMD_FACTORY_RESET "CMD_FACTORY_RESET"
#define OSC_CMD_GET_STATUS "CMD_GET_STATUS"

#ifdef __cplusplus
}
#endif
