#include "boot.h"
#include <math.h>
#include "fx.h"
#include "wordmark.h"

#define HEX(v) C565(((v) >> 16) & 255, ((v) >> 8) & 255, (v) & 255)
#define Q(v) ((int)lrintf((v) * 16.0f))

/* geometry (px) */
#define CX 160.0f
#define CY 100.0f
#define PLATTER_R 88.0f
#define REC_R 82.0f
#define LABEL_R 27.0f
#define PIVOT_X 287.0f
#define PIVOT_Y 38.0f
#define ARM_L 112.0f
#define WORD_BASE 229
/* timeline (ms) */
#define T_DROP 100
#define T_LAND 470
#define T_ARM0 700
#define T_ARM1 1060
#define T_SET 1120
#define T_WORD 1200
#define T_DOT 1340

static const float DEG = 3.14159265f / 180.0f;

static float clamp01(float u) { return u < 0 ? 0 : u > 1 ? 1 : u; }

/* a straight stroke from (x0,y0) to (x1,y1), w px wide, as a convex quad */
static void stroke(gfx *g, float x0, float y0, float x1, float y1, float w, px16 c)
{
    float dx = x1 - x0, dy = y1 - y0, len = sqrtf(dx * dx + dy * dy);
    if (len < 0.01f) return;
    float nx = -dy / len * w * 0.5f, ny = dx / len * w * 0.5f;
    int32_t xy[8] = { Q(x0 + nx), Q(y0 + ny), Q(x1 + nx), Q(y1 + ny),
                      Q(x1 - nx), Q(y1 - ny), Q(x0 - nx), Q(y0 - ny) };
    g_convex(g, xy, 4, c);
}

static void wordmark(gfx *g, int x, int base, px16 c)
{
    int y0 = base - WORDMARK_BASELINE;
    for (int y = 0; y < WORDMARK_H; y++) {
        int py = y0 + y;
        if (py < g->cy0 || py >= g->cy1) continue;
        px16 *row = g->px + py * g->stride;
        for (int xx = 0; xx < WORDMARK_W; xx++) {
            int px = x + xx, a = wordmark_a8[y * WORDMARK_W + xx];
            if (!a || px < g->cx0 || px >= g->cx1) continue;
            row[px] = blend565(row[px], c, a + (a >> 7));
        }
    }
}

void boot_draw(gfx *g, uint32_t t)
{
    const px16 paper = HEX(0xf4f4f0), ink = HEX(0x141414), blue = HEX(0x002fa7),
               red = HEX(0xe0301e);
    const px16 groove = blend565(blue, paper, 40), groove_hi = blend565(blue, paper, 72);
    g_noclip(g);
    g_fill(g, 0, 0, LCD_W, LCD_H, paper);

    /* the platter: line art, with the spindle */
    g_ring(g, Q(CX), Q(CY), Q(PLATTER_R + 3), Q(2), ink);

    /* the record: falls (gravity), lands with a short mechanical settle, spins up */
    float y = CY, theta = 0;
    int landed = t >= T_LAND;
    if (t >= T_DROP) {
        if (!landed) {
            float u = (float)(t - T_DROP) / (T_LAND - T_DROP);
            y = (-REC_R - 6) + (CY + REC_R + 6) * u * u;
        } else {
            float d = (float)(t - T_LAND);
            y = CY + 3.5f * expf(-d / 55.0f) * cosf(d / 22.0f);
            float s = d / 1000.0f;                 /* 0 -> 200 deg/s over half a second */
            theta = s < 0.5f ? 200.0f * s * s : 50.0f + 200.0f * (s - 0.5f);
        }
        g_disc(g, Q(CX), Q(y), Q(REC_R), blue);
        for (int k = 0; k < 6; k++)
            g_ring(g, Q(CX), Q(y), Q(REC_R - 7 - k * 8), Q(0.7f), k == 1 ? groove_hi : groove);
        g_disc(g, Q(CX), Q(y), Q(LABEL_R), paper);
        g_ring(g, Q(CX), Q(y), Q(LABEL_R - 4), Q(1), blue);
        float a = (theta - 90.0f) * DEG;           /* a mark on the label shows the spin */
        stroke(g, CX + cosf(a) * 9, y + sinf(a) * 9, CX + cosf(a) * 19, y + sinf(a) * 19, 3, ink);
        if (!landed) g_disc(g, Q(CX), Q(y), Q(3), ink);   /* the hole, until it meets the spindle */
    }
    g_disc(g, Q(CX), Q(CY), Q(3.5f), red);

    /* the tonearm: rests straight down, swings in, sets down on the outer groove */
    float u = clamp01((float)((int)t - T_ARM0) / (T_ARM1 - T_ARM0));
    u = 1 - (1 - u) * (1 - u) * (1 - u);
    float phi = (90.0f + 32.0f * u) * DEG;
    float drop = t >= T_SET ? 0 : t >= T_ARM1 ? -1.5f : 0;
    float hx = PIVOT_X + cosf(phi) * ARM_L, hy = PIVOT_Y + sinf(phi) * ARM_L + drop;
    stroke(g, PIVOT_X - cosf(phi) * 20, PIVOT_Y - sinf(phi) * 20, PIVOT_X, PIVOT_Y, 9, ink);  /* counterweight */
    stroke(g, PIVOT_X, PIVOT_Y, hx, hy, 3, ink);
    float hx2 = hx + cosf(phi + 0.5f) * 12, hy2 = hy + sinf(phi + 0.5f) * 12;   /* the head */
    stroke(g, hx, hy, hx2, hy2, 7, ink);
    g_disc(g, Q(PIVOT_X), Q(PIVOT_Y), Q(9), ink);
    g_disc(g, Q(PIVOT_X), Q(PIVOT_Y), Q(3.5f), paper);

    /* the wordmark, stamped; then the signal-red dot, as on the menu's masthead */
    int wx = (LCD_W - (WORDMARK_W + 12)) / 2;
    if (t >= T_WORD) wordmark(g, wx, WORD_BASE, ink);
    if (t >= T_DOT) g_fill(g, wx + WORDMARK_W + 4, WORD_BASE - 9, 9, 9, red);
}
