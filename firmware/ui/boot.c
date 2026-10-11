#include "boot.h"
#include <math.h>
#include <stdlib.h>
#include "fx.h"
#include "wordmark.h"

/* Coda OS boot animation, "grooves" (docs/h2/boot/v2, B; firmware/tools/mock_boot_v2.py is
 * the reference): ink arcs cut around a red spindle while the disc turns, one of them Klein
 * blue, Muller-Brockmann style; then "Coda." sets on the left margin.
 * Frame 0 -- paper and the spindle -- is what shows while Rockbox itself starts. */

#define HEX(v) C565(((v) >> 16) & 255, ((v) >> 8) & 255, (v) & 255)
#define Q(v) ((int)lrintf((v) * 16.0f))

static float clamp01(float u) { return u < 0 ? 0 : u > 1 ? 1 : u; }
static float ease_out(float u) { u = clamp01(u); return 1 - (1 - u) * (1 - u) * (1 - u); }
static float seg(uint32_t t, float a, float b) { return clamp01(((float)t - a) / (b - a)); }

/* an 8-bit alpha bitmap at (x, baseline), drawn only left of x_clip */
static void blit_a8(gfx *g, const uint8_t *a8, int w, int h, int baseline, int x, int base,
                    px16 c, int x_clip)
{
    int y0 = base - baseline;
    for (int y = 0; y < h; y++) {
        int py = y0 + y;
        if (py < g->cy0 || py >= g->cy1) continue;
        px16 *row = g->px + py * g->stride;
        for (int xx = 0; xx < w; xx++) {
            int px = x + xx, a = a8[y * w + xx];
            if (!a || px < g->cx0 || px >= g->cx1 || px >= x_clip) continue;
            row[px] = blend565(row[px], c, a + (a >> 7));
        }
    }
}

int boot_wordmark(gfx *g, int x, int base, px16 ink, px16 dot, float dot_scale)
{
    blit_a8(g, wordmark_a8, WORDMARK_W, WORDMARK_H, WORDMARK_BASELINE, x, base, ink, 1 << 30);
    float s = 10.0f * dot_scale;                       /* the square full stop */
    if (s > 0.5f) {
        float cx = x + WORDMARK_W + 3 + 5.0f, cy = base - 5.0f;
        int si = (int)lrintf(s);
        g_fill(g, (int)lrintf(cx - s / 2), (int)lrintf(cy - s / 2), si, si, dot);
    }
    return WORDMARK_W + 3 + 10;
}

/* ------------------------------------------------------------------ the grooves */
#define SP_X 236                                 /* the spindle */
#define SP_Y 150
#if !(defined(PLUGIN) && !defined(CODA_OS))     /* not in the stock-firmware plugin */
#define NRING 12
#define FULL 11520                               /* angles in 1/32 degree */
static const uint8_t RW[NRING] = { 3, 9, 3, 5, 14, 3, 7, 3, 11, 4, 6, 3 };
static const int16_t RSWEEP[NRING] = { 300, 250, 330, 200, 280, 160, 310, 230, 190, 270, 140, 240 };
static const int16_t RSTART[NRING] = { 200, 120, 260, 30, 180, 300, 90, 210, 0, 150, 240, 60 };
#define BX0 80                                   /* the box the rings can reach */
#define BW (LCD_W - BX0)
#define BN (BW * LCD_H)
static uint8_t lut_ring[BN], lut_cov[BN];        /* which ring, radial coverage 0..16 */
static uint16_t lut_ang[BN], lut_r16[BN];        /* angle (1/32 deg), radius (1/16 px) */
static int16_t ring_start[NRING], ring_sweep[NRING];
static int lut_ready;

/* atan2 for screen coordinates (y down), clockwise from +x, in 1/32 degree; integer only
 * (the X1000 has no FPU) and within ~0.3 degree */
static int iatan2(int y, int x)
{
    if (!x && !y) return 0;
    int ax = abs(x), ay = abs(y);
    int mn = ax < ay ? ax : ay, mx = ax < ay ? ay : ax;
    int32_t z = (mn << 15) / mx;                               /* tan, Q15, 0..1 */
    int32_t a = (z * 1440 >> 15) + ((z * (32768 - z) >> 15) * 501 >> 15);
    if (ay > ax) a = 2880 - a;
    if (x < 0) a = 5760 - a;
    if (y < 0) a = FULL - a;
    return a % FULL;
}

/* once: which ring each pixel belongs to, how much of it, and its angle and radius --
 * after that a frame is a table walk, no square roots or arctangents */
static void lut_build(void)
{
    int32_t c16[NRING], h16[NRING];
    float r = 16;
    for (int i = 0; i < NRING; i++) {
        int a0 = RSTART[i], sw = RSWEEP[i];
        if (r > 84) {                    /* outer arcs leave the type's corner clear */
            a0 = 252 + RSTART[i] % 40;
            if (sw > 296 - RSTART[i] % 40) sw = 296 - RSTART[i] % 40;
        }
        ring_start[i] = (int16_t)(a0 * 32 % FULL);
        ring_sweep[i] = (int16_t)(sw * 32);
        c16[i] = (int32_t)lrintf(r * 16);
        h16[i] = RW[i] * 8;
        r += RW[i] + 6;
    }
    int32_t lim16 = c16[NRING - 1] + h16[NRING - 1] + 16;
    for (int y = 0; y < LCD_H; y++)
        for (int x = BX0; x < LCD_W; x++) {
            int k = y * BW + (x - BX0);
            int dx = 2 * x + 1 - 2 * SP_X, dy = 2 * y + 1 - 2 * SP_Y;    /* half pixels */
            int32_t r16 = (int32_t)fx_isqrt((uint32_t)(dx * dx + dy * dy) * 64);
            lut_ring[k] = 255;
            if (r16 > lim16) continue;
            for (int i = 0; i < NRING; i++) {
                int32_t in = c16[i] - h16[i], out = c16[i] + h16[i];
                if (r16 < in - 8 || r16 > out + 8) continue;
                int32_t a = fx_clamp(r16 - in + 8, 0, 16), b = fx_clamp(out - r16 + 8, 0, 16);
                lut_ring[k] = (uint8_t)i;
                lut_cov[k] = (uint8_t)(a < b ? a : b);
                lut_ang[k] = (uint16_t)iatan2(dy, dx);
                lut_r16[k] = (uint16_t)r16;
                break;
            }
        }
    lut_ready = 1;
}

/* the arcs: each shows part of its sweep (cut while the disc turns), the set turned by rot */
static void grooves(gfx *g, uint32_t t, px16 ink, px16 blue)
{
    if (!lut_ready) lut_build();
    float rot = -40.0f * (1 - ease_out(seg(t, 80, 1100)));
    int32_t rot32 = (int32_t)lrintf(rot * 32);
    int32_t ext[NRING], st[NRING];
    for (int i = 0; i < NRING; i++) {
        float p = ease_out(seg(t, 80 + 40 * i, 80 + 40 * i + 520));
        ext[i] = (int32_t)lrintf(ring_sweep[i] * p);
        st[i] = ((ring_start[i] + rot32) % FULL + FULL) % FULL;
    }
    for (int y = 0; y < LCD_H; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = BX0; x < LCD_W; x++) {
            int k = y * BW + (x - BX0), i = lut_ring[k];
            if (i == 255 || ext[i] <= 0) continue;
            int32_t d = lut_ang[k] - st[i];
            if (d < 0) d += FULL;
            if (d > FULL - 200) d -= FULL;            /* just before the start: its AA edge */
            /* distance to either end along the arc in 1/16 px: units * r16 * pi / 5760 / 16 */
            int32_t to_end = (ext[i] - d) * lut_r16[k] / 1834;
            int32_t from_start = d * lut_r16[k] / 1834;
            int32_t ce = fx_clamp(to_end + 8, 0, 16), cs = fx_clamp(from_start + 8, 0, 16);
            int32_t cov = lut_cov[k] * (ce < cs ? ce : cs);   /* 0..256 */
            if (cov <= 0) continue;
            row[x] = blend565(row[x], i == 4 ? blue : ink, cov);
        }
    }
}
#else
static void grooves(gfx *g, uint32_t t, px16 ink, px16 blue) { (void)g; (void)t; (void)ink; (void)blue; }
#endif

void boot_draw(gfx *g, uint32_t t)
{
    const px16 paper = HEX(0xf4f4f0), ink = HEX(0x141414), blue = HEX(0x002fa7),
               red = HEX(0xe0301e), sub = HEX(0x6d6d66);
    g_noclip(g);
    g_fill(g, 0, 0, LCD_W, LCD_H, paper);
    if (t >= 80) grooves(g, t, ink, blue);
    g_disc(g, SP_X * 16, SP_Y * 16, Q(4.5f), red);

    /* the type sets on a hard left margin: a short slide, revealed left to right */
    float tp = seg(t, 820, 1080);
    if (tp > 0) {
        float e = ease_out(tp);
        int x = (int)lrintf(10 - 12 * (1 - e)), clip = (int)lrintf(10 + e * 200);
        g_clip(g, 0, 0, clip, LCD_H);
        float dot = t < 1120 ? 0 : 1 + 0.45f * (1 - ease_out(seg(t, 1120, 1240)));
        boot_wordmark(g, x, 58, ink, red, dot);
        blit_a8(g, tagline_a8, TAGLINE_W, TAGLINE_H, TAGLINE_BASELINE, x + 2, 76, sub, clip);
        g_noclip(g);
    }
}

/* Power-off when Coda has no library loaded (the crate needs the covers): the screen as it
 * was dims to black, the spindle dot last. Low / empty battery: the wordmark, a still. */
void boot_off_draw(gfx *g, uint32_t t, const px16 *from, int why)
{
    const px16 black = HEX(0x000000), red = HEX(0xe0301e), paper = HEX(0xf4f4f0);
    g_noclip(g);
    if (why) {
        g_fill(g, 0, 0, LCD_W, LCD_H, black);
        boot_wordmark(g, (LCD_W - WORDMARK_W - 13) / 2, 136, paper, red, 1);
        return;
    }
    float u = clamp01((float)t / (BOOT_OFF_MS * 0.7f));
    int a = (int)lrintf(256.0f * u);
    for (int y = 0; y < LCD_H; y++)
        for (int x = 0; x < LCD_W; x++)
            g->px[y * g->stride + x] = blend565(from ? from[y * LCD_W + x] : paper, black, a);
    float d = 1.0f - clamp01(((float)t - BOOT_OFF_MS * 0.7f) / (BOOT_OFF_MS * 0.3f));
    if (d > 0) g_disc(g, SP_X * 16, SP_Y * 16, Q(4.5f * d), red);
}
