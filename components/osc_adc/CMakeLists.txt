idf_component_register(
    SRCS "osc_adc.c"
    INCLUDE_DIRS "include"
    REQUIRES
        osc_config
        esp_adc
        freertos
        esp_common
        log
        driver
        esp_timer
)
