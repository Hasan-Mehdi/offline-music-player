/* Integer maths for the UI hot loops. The H2's X1000 runs Rockbox with -msoft-float,
 * so every per-pixel path is fixed point:
 *   binary angle  0..65535 == 0..360 degrees, 0 = +x, increasing clockwise (screen y down)
 *   Q4 coords     1/16 px (pixel centre of column x = x*16 + 8)
 * Floats are fine once per frame (per wedge, per glyph run), never per pixel. */
#ifndef CODA_FX_H
#define CODA_FX_H

#include <stdint.h>

#define FX_DEG(d) ((int32_t)((d) * 65536.0 / 360.0))

void fx_init(void);                          /* builds the atan / sine tables (floats, once) */
uint16_t fx_atan2(int32_t y, int32_t x);     /* binary angle of vector (x, y) */
uint32_t fx_isqrt(uint32_t v);
int32_t fx_sin_q14(uint16_t a);
int32_t fx_cos_q14(uint16_t a);

static inline int32_t fx_clamp(int32_t v, int32_t lo, int32_t hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

#endif
