/* Coda OS boot animation (~1.6 s): a Klein-blue record drops onto the platter, spins up,
 * the tonearm swings over and sets down, the wordmark is stamped. Frame 0 (platter,
 * spindle, tonearm at rest) is what shows while Rockbox itself starts; the rest plays while
 * the library loads. Self-contained: no card files (the wordmark is baked in). */
#ifndef CODA_BOOT_H
#define CODA_BOOT_H

#include <stdint.h>
#include "gfx.h"

#define BOOT_MS 1600

void boot_draw(gfx *g, uint32_t t_ms);

#endif
