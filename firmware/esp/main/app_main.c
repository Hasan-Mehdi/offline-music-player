/* ESP32-S3 bring-up smoke for the Waveshare Touch-AMOLED-2.16 board.
 * STATUS: SCAFFOLD — written before hardware arrived, never flashed. It is the
 * milestone-0/2 firmware: mount the SD card, open the device pack in STREAM
 * mode, replay the play log, and ask the brain for a next track — proving the
 * whole data path on real hardware before any audio/UI work.
 *
 * SD pins per https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-2.16
 * (SPI mode: CMD/MOSI=GPIO1, CLK=GPIO2, D0/MISO=GPIO3, CS=GPIO41).
 */
#include <stdio.h>

#include "driver/sdspi_host.h"
#include "esp_heap_caps.h"
#include "esp_random.h"
#include "esp_vfs_fat.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "omp_brain.h"
#include "omp_gain.h"
#include "omp_pack.h"
#include "omp_playlog.h"
#include "omp_speeddial.h"

#define PIN_SD_MOSI 1
#define PIN_SD_CLK 2
#define PIN_SD_MISO 3
#define PIN_SD_CS 41

#define MOUNT "/sd"
#define PACK_DIR MOUNT "/pack"
#define PLAYLOG MOUNT "/plays.omp"

static double rng01(void *s)
{
    (void)s;
    return (double)esp_random() / 4294967296.0;
}

static void mount_sd(void)
{
    sdmmc_host_t host = SDSPI_HOST_DEFAULT();
    spi_bus_config_t bus = {
        .mosi_io_num = PIN_SD_MOSI,
        .miso_io_num = PIN_SD_MISO,
        .sclk_io_num = PIN_SD_CLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 4096,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(host.slot, &bus, SDSPI_DEFAULT_DMA));
    sdspi_device_config_t dev = SDSPI_DEVICE_CONFIG_DEFAULT();
    dev.gpio_cs = PIN_SD_CS;
    esp_vfs_fat_sdmmc_mount_config_t cfg = {
        .format_if_mount_failed = false,
        .max_files = 8,                 /* pack streams + playlog + opus file */
        .allocation_unit_size = 0,
    };
    sdmmc_card_t *card;
    ESP_ERROR_CHECK(esp_vfs_fat_sdspi_mount(MOUNT, &host, &dev, &cfg, &card));
    sdmmc_card_print_info(stdout, card);
}

void app_main(void)
{
    printf("omp bring-up: free heap %u, PSRAM %u\n",
           (unsigned)esp_get_free_heap_size(),
           (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    mount_sd();

    static omp_pack pack;               /* static: keep app_main stack small */
    int rc = omp_pack_open(&pack, PACK_DIR, OMP_PACK_STREAM);
    printf("pack open: %d (%u tracks, k=%u)\n", rc, pack.n, pack.k);
    if (rc != 0) return;

    omp_play *plays;
    int n_plays = omp_playlog_load(PLAYLOG, &plays);
    printf("playlog: %d events\n", n_plays);

    omp_prefs prefs;
    omp_prefs_compute(&pack, plays, n_plays > 0 ? n_plays : 0,
                      1784000000.0 /* TODO: RTC */, OMP_HALFLIFE_DAYS, &prefs);
    static float taste[OMP_DIM], skipv[OMP_DIM];
    int ht = omp_taste_centroid(&pack, &prefs, taste);
    int hs = omp_skip_centroid(&pack, &prefs, skipv);

    uint32_t cur = esp_random() % pack.n;
    omp_pick_reason reason;
    int n_ranked = 0;
    omp_ranked *ranked = malloc(pack.k * sizeof *ranked);
    int64_t t0 = esp_timer_get_time();
    uint32_t pick = omp_next_track(&pack, &prefs, ht ? taste : NULL,
                                   hs ? skipv : NULL, NULL, 0, cur, 0.15,
                                   rng01, NULL, &reason, ranked, &n_ranked);
    int64_t dt = esp_timer_get_time() - t0;
    if (pick != UINT32_MAX) {
        const omp_track *t = omp_pack_track(&pack, pick);
        printf("brain: %s — %s -> %s — %s  (%d cands, %.1f ms, gain x%.2f)\n",
               omp_pack_str(&pack, omp_pack_track(&pack, cur)->artist_off),
               omp_pack_str(&pack, omp_pack_track(&pack, cur)->title_off),
               omp_pack_str(&pack, t->artist_off), omp_pack_str(&pack, t->title_off),
               n_ranked, dt / 1000.0, omp_gain_mult(t->gain_q78));
    }
    printf("free heap after: %u\n", (unsigned)esp_get_free_heap_size());

    /* TODO milestone 1+: audio task on core 1 (SD read -> esp_audio_codec opus
     * decode -> omp_gain_mult scale -> I2S1 DMA to PCM5102A), LVGL UI task on
     * core 0, playlog appends on every transition, prefs cache invalidation. */
    for (;;)
        vTaskDelay(pdMS_TO_TICKS(10000));
}
