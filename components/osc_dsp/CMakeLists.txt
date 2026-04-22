idf_component_register(
    SRCS "osc_dsp.c"
    INCLUDE_DIRS "include"
    REQUIRES
        osc_config
        osc_adc
        osc_trigger
        esp_adc
        freertos
        esp_common
        log
        esp-dsp
)
