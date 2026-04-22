idf_component_register(
    SRCS "osc_usb.c"
    INCLUDE_DIRS "include"
    REQUIRES
        osc_config
        osc_dsp
        freertos
        esp_common
        log
        esp_tinyusb
        esp_timer
)
