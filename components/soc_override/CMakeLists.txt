# components/soc_override/CMakeLists.txt
# Este componente no tiene fuentes .c, solo inyecta definiciones de preprocesador.
idf_component_register(
    SRCS ""
    INCLUDE_DIRS "include"
    PRIV_REQUIRES esp_common
)

# Inyectar las redefiniciones a TODOS los componentes que dependan de soc_override
# y también a los que usen el ADC (via target_compile_options global)

