# CMakeLists.txt (raíz del proyecto)
cmake_minimum_required(VERSION 3.16)

# Agregar componentes locales al path de búsqueda ANTES de include(project)
set(EXTRA_COMPONENT_DIRS "components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32s3_oscilloscope)

# Hack global para el ADC y desactivar error por redefinición de macros
add_compile_options("-DSOC_ADC_SAMPLE_FREQ_THRES_HIGH=160000")
add_compile_options("-DADC_LL_CLKM_DIV_NUM_DEFAULT=8")
add_compile_options("-Wno-error=macro-redefined")
add_compile_options("-Wno-macro-redefined")

