idf_component_register(
    SRCS "app_main.c"
         "../../core/omp_pack.c"
         "../../core/omp_map.c"
         "../../core/omp_playlog.c"
         "../../core/omp_brain.c"
         "../../core/omp_speeddial.c"
    INCLUDE_DIRS "." "../../core"
    REQUIRES fatfs sdmmc esp_timer)
