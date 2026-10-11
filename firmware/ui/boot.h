/* Coda OS boot animation (~1.6 s), "grooves": ink arcs are cut around a red spindle while
 * the disc turns, then "Coda." sets on the left margin. Frame 0 (paper and the spindle) is
 * what shows while Rockbox itself starts; the rest plays while the library loads.
 * Self-contained: no card files (the type is baked in, firmware/ui/wordmark.h).
 * The power-off ("your crate") lives in app.c (app_draw_off): it needs the covers. */
#ifndef CODA_BOOT_H
#define CODA_BOOT_H

#include <stdint.h>
#include "gfx.h"

#define BOOT_MS 1600
#define BOOT_OFF_MS 900

void boot_draw(gfx *g, uint32_t t_ms);
/* "Coda" + the square red full stop at (x, baseline); returns its width */
int boot_wordmark(gfx *g, int x, int base, px16 ink, px16 dot, float dot_scale);
/* power-off: t from 0 to BOOT_OFF_MS, starting from `from` (the screen as it was) and
 * ending dark. why: 0 switched off, 1 battery low, 2 battery empty (a still note, no motion) */
void boot_off_draw(gfx *g, uint32_t t_ms, const px16 *from, int why);

#endif
