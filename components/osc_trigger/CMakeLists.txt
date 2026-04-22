idf_component_register(
    SRCS "osc_trigger.c"
    INCLUDE_DIRS "include"
    REQUIRES
        osc_config
        osc_adc
        freertos
        esp_common
        log
)
