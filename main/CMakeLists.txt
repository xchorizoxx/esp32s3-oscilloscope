idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES
        soc_override
        osc_config
        osc_adc
        osc_trigger
        osc_dsp
        osc_usb
        osc_gen
        freertos
        esp_timer
        nvs_flash
        esp_system
        driver
        esp_driver_ledc
        esp_driver_gpio
        log
)
