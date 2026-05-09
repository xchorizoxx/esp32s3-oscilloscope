idf_component_register(
    SRCS "osc_pga.c"
    INCLUDE_DIRS "include"
    REQUIRES osc_config driver esp_driver_gpio esp_timer log nvs_flash
)
