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
#define OSC_FRAME_PGA_INFO 0x08  ///< Información del PGA: pasos, cal, ganancia activa

// Bits de FLAGS (byte de flags en frames de datos)
#define OSC_FLAG_CH0_VALID (1 << 0)
#define OSC_FLAG_CH1_VALID (1 << 1)
#define OSC_FLAG_TRIGGER_HIT (1 << 2)
#define OSC_FLAG_OVERFLOW (1 << 3)
#define OSC_FLAG_FFT_ATTACHED (1 << 4) ///< frame de FFT sigue inmediatamente

// Capacidades del firmware (bits de CAPS_FLAGS en INFO frame)
#define OSC_CAP_DUAL_CHANNEL (1 << 0)
#define OSC_CAP_FFT (1 << 1)
#define OSC_CAP_OVERSAMPLE (1 << 2)
#define OSC_CAP_CLOCK_HACK (1 << 3) ///< frecuencia > 83333 Hz disponible
#define OSC_CAP_PGA        (1 << 4) ///< PGA (Programmable Gain Amplifier) presente

// Versión del firmware
#define OSC_FW_VERSION_MAJOR 1
#define OSC_FW_VERSION_MINOR 0

// Máximo tamaño de un frame de datos (para dimensionar buffers)
#define OSC_MAX_FRAME_BYTES 20480

/* =========================================================================
 * Comandos ASCII (PC → ESP32, terminados en '\n')
 * =========================================================================
 *
 * CMD_GET_CAPS                   → INFO frame
 * CMD_STREAM_START               → ACK + inicio del stream de DATA frames
 * CMD_STREAM_STOP                → ACK + detención del stream
 * CMD_SINGLE_SHOT                → ACK + espera trigger + 1 DATA frame
 * CMD_SET_MODE <mode>            → ACK (mode: 0=SINGLE_CH 1=DUAL_CH 2=OVERSAMPLE)
 * CMD_SET_RATE <hz>              → ACK (hz: 611..160000)
 * CMD_SET_TRIG <ch> <mv> <edge>  → ACK (ch: 0/1, mv: flotante, edge: 0=RISE 1=FALL 2=ANY 3=NONE)
 * CMD_SET_ATTEN <ch> <db>        → ACK (ch: 0/1, db: 0/1/2/3 = 0/2.5/6/12 dB)
 * CMD_SET_FRAME <n>              → ACK (n: 64/128/256/512/1024/2048/4096)
 * CMD_SET_PRE_TRIG <n>           → ACK (n: 0..frame_size/2)
 * CMD_SET_FFT <en>               → ACK (en: 0=off 1=on)
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
#define OSC_CMD_SET_OVERSAMPLE "CMD_SET_OVERSAMPLE"
#define OSC_CMD_ADC_SET_CORRECTION "CMD_ADC_SET_CORRECTION" ///< <factor_float> -> ACK

/* --- Tipos de onda para el generador de señales --- */
#define OSC_WAVE_SQUARE   0
#define OSC_WAVE_SINE     1
#define OSC_WAVE_TRIANGLE 2
#define OSC_WAVE_SAW      3

/* --- Comandos del generador de señales --- */
#define OSC_CMD_GEN_START "CMD_GEN_START"  ///< <wave_type> <freq_hz> <duty_pct> -> ACK
#define OSC_CMD_GEN_STOP  "CMD_GEN_STOP"   ///< -> ACK

/* --- Comandos PGA (Programable Gain Amplifier) --- */
#define OSC_CMD_PGA_SET_STEP        "CMD_PGA_SET_STEP"       ///< <0-7> -> ACK
#define OSC_CMD_PGA_CAL_START       "CMD_PGA_CAL_START"      ///< -> ACK (inicia auto-cal)
#define OSC_CMD_PGA_CAL_SET_VG      "CMD_PGA_CAL_SET_VG"     ///< <mv_float> -> ACK
#define OSC_CMD_PGA_CAL_SET_GAIN    "CMD_PGA_CAL_SET_GAIN"   ///< <step> <factor_float> -> ACK
#define OSC_CMD_PGA_CAL_SET_OFF     "CMD_PGA_CAL_SET_OFF"    ///< <step> <offset_mv_float> -> ACK
#define OSC_CMD_PGA_CAL_SAVE        "CMD_PGA_CAL_SAVE"       ///< -> ACK
#define OSC_CMD_PGA_CAL_RESET       "CMD_PGA_CAL_RESET"      ///< -> ACK (reset a defaults)
#define OSC_CMD_PGA_GET_INFO        "CMD_PGA_GET_INFO"       ///< -> PGA_INFO frame (type 0x08)
#define OSC_CMD_PGA_SET_HARDWARE    "CMD_PGA_SET_HARDWARE"   ///< <div_ratio> <rf> <r1> <r2> <r3> <ron> -> ACK
#define OSC_CMD_PGA_SET_DEFAULT_VG  "CMD_PGA_SET_DEFAULT_VG" ///< <mv_float> -> ACK
#define OSC_CMD_PGA_SET_ENABLED     "CMD_PGA_SET_ENABLED"    ///< <0|1> -> ACK

#ifdef __cplusplus
}
#endif
