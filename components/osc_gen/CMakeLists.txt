idf_component_register(SRCS "osc_gen.c"
                       INCLUDE_DIRS "include"
                       REQUIRES esp_driver_ledc esp_driver_gpio driver log esp_timer)
