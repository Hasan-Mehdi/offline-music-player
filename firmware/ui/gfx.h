/* RGB565 framebuffer drawing for the 320x240 H2 screen. Everything anti-aliased is
 * integer: geometry in Q4 (1/16 px), alpha 0..256. Shared by the PC host build and
 * the Rockbox plugin (which points px at rb->lcd_framebuffer). */
#ifndef CODA_GFX_H
#define CODA_GFX_H

#include <stdint.h>

#define LCD_W 320
#define LCD_H 240

typedef uint16_t px16;

typedef struct {
    px16 *px;
    int w, h, stride;
    int cx0, cy0, cx1, cy1;      /* clip rect, half-open */
} gfx;

#define C565(r, g, b) ((px16)((((r) >> 3) << 11) | (((g) >> 2) << 5) | ((b) >> 3)))

static inline px16 blend565(px16 d, px16 s, int a)    /* a: 0..256 */
{
    if (a <= 0) return d;
    if (a >= 256) return s;
    int dr = d >> 11, dg = (d >> 5) & 63, db = d & 31;
    int sr = s >> 11, sg = (s >> 5) & 63, sb = s & 31;
    dr += ((sr - dr) * a + 128) >> 8;
    dg += ((sg - dg) * a + 128) >> 8;
    db += ((sb - db) * a + 128) >> 8;
    return (px16)((dr << 11) | (dg << 5) | db);
}

/* mix two colours (t 0..256 towards b) -- for faded text etc. */
static inline px16 mix565(px16 a, px16 b, int t) { return blend565(a, b, t); }

void g_init(gfx *g, px16 *px, int w, int h, int stride);
void g_clip(gfx *g, int x0, int y0, int x1, int y1);
void g_noclip(gfx *g);

void g_fill(gfx *g, int x, int y, int w, int h, px16 c);
void g_fill_a(gfx *g, int x, int y, int w, int h, px16 c, int a);
/* 1:1 copy of an RGB565 image */
void g_blit(gfx *g, const px16 *src, int sw, int sh, int x, int y);
/* bilinear scale of a square-or-not RGB565 image into a dw x dh rect */
void g_blit_scaled(gfx *g, const px16 *src, int sw, int sh, int x, int y, int dw, int dh);
/* AA shapes. Centres/radii/vertices in Q4. */
void g_disc(gfx *g, int cx, int cy, int r, px16 c);
void g_ring(gfx *g, int cx, int cy, int r, int width, px16 c);   /* stroke centred on r */
void g_disc_tex(gfx *g, int cx, int cy, int r, const px16 *tex, int tw);
void g_convex(gfx *g, const int32_t *xy, int n, px16 c);         /* xy: n (x, y) pairs */

/* bilinear sample of an RGB565 texture; u, v in Q8 texel units, clamped */
px16 g_sample(const px16 *tex, int tw, int th, int32_t u, int32_t v);

#endif
