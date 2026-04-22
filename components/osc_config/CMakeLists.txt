idf_component_register(
    SRCS "osc_config.c"
    INCLUDE_DIRS "include"
    REQUIRES
        freertos
        nvs_flash
        esp_common
        log
)
