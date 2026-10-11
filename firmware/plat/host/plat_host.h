/* Host-only controls for plat_host.c (not part of the device platform API). */
#ifndef CODA_PLAT_HOST_H
#define CODA_PLAT_HOST_H

#include <stdint.h>

void plat_host_init(const char *coda_dir, const char *pack_dir, uint16_t (*duration)(uint32_t));
void plat_host_set_clock(int hour, int minute);
void plat_host_advance(uint32_t ms);          /* simulated time + fake playback */
int plat_host_png(const char *path, const uint16_t *px, int w, int h, int scale);

#endif
