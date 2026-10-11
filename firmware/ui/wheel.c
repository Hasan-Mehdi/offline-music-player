#include "wheel.h"
#include "fx.h"
#include <math.h>

const wheel_geom WHEEL_A = { 104, 120, 41, 100, 0 };
const wheel_geom WHEEL_B = { 160, 232, 70, 158, -90 };

#define TEX 112
#define SLICE_DEG 30.0f
#define HALF_Q16 29709               /* 13.6 / 30 of a slice, Q16 */
#define SLICE_RAD_Q16 34315          /* 30 deg in radians, Q16 */

static int floor_div65536(int32_t v) { return v >= 0 ? v >> 16 : -(((-v) + 65535) >> 16); }

/* hub: black vinyl silhouette, ink sunburst, record label. partial = the visualizer-only
 * refresh: the disc is redrawn just inside its anti-aliased edge (which the last full frame
 * already blended), so repeated refreshes never re-blend and darken the rim. */
static void draw_hub(gfx *g, const palette *p, const wheel_geom *w, const wheel_frame *f, int partial)
{
    const float k = w->r2 / 300.0f;
    const int cxq = w->cx * 16, cyq = w->cy * 16;
    const float u = w->r1 / 128.0f;
    int hub = (int)(w->r1 * 116 / 128.0f * 16);
    g_disc(g, cxq, cyq, partial ? hub - 24 : hub, p->ink);
    {
        float viz0 = 68 * u, bar = 27 * u, bw = fmaxf(1.0f, 2.6f * u) * 0.5f;
        for (int i = 0; i < 24; i++) {
            float a = (-90 + i * 15) * 3.14159265f / 180.0f, ca = cosf(a), sa = sinf(a);
            float b = (f->playing ? f->bars[i] : 20) / 255.0f;
            float ra = viz0, rb = viz0 + 2.5f * k + b * bar;
            float pts[8] = { w->cx + ra * ca - bw * sa, w->cy + ra * sa + bw * ca,
                             w->cx + rb * ca - bw * sa, w->cy + rb * sa + bw * ca,
                             w->cx + rb * ca + bw * sa, w->cy + rb * sa - bw * ca,
                             w->cx + ra * ca + bw * sa, w->cy + ra * sa - bw * ca };
            int32_t q[8];
            for (int j = 0; j < 8; j++) q[j] = (int32_t)lrintf(pts[j] * 16.0f);
            g_convex(g, q, 4, p->viz[i]);
        }
    }
    int rec = (int)(58 * u * 16);
    if (f->label) g_disc_tex(g, cxq, cyq, rec, f->label, TEX);
    else g_disc(g, cxq, cyq, rec, p->wash);
    g_ring(g, cxq, cyq, rec, (int)fmaxf(16.0f, 3 * u * 16), f->playing ? p->red : p->paper);
    g_disc(g, cxq, cyq, (int)(7.5f * u * 16), p->ink);
    g_ring(g, cxq, cyq, (int)(7.5f * u * 16), (int)fmaxf(10.0f, 2 * u * 16), p->paper);
    g_disc(g, cxq, cyq, (int)(2.4f * u * 16), p->paper);
}

void wheel_draw(gfx *g, const palette *p, const wheel_geom *w, const wheel_frame *f)
{
    const float k = w->r2 / 300.0f;
    const int r1q = w->r1 * 16, r2q = w->r2 * 16;
    const int cxq = w->cx * 16, cyq = w->cy * 16;
    const uint16_t base_bin = (uint16_t)FX_DEG(w->base_deg < 0 ? w->base_deg + 360 : w->base_deg);
    const int32_t frac_q16 = (int32_t)lrintf(f->frac * 65536.0f);
    const float mid = (w->r1 + w->r2) * 0.5f, art = w->r2 - w->r1 + 24.0f * k;
    const int32_t scale_q16 = (int32_t)(TEX / art * 65536.0f);
    const int32_t rim_half = (int32_t)(fmaxf(1.5f, 4.0f * k) * 8.0f);   /* half width, Q4 */

    /* per-wedge setup (11 wedges, floats are fine here) */
    int32_t wc[11], ws[11], wax[11], way[11];
    int shade[11];
    for (int i = 0; i < 11; i++) {
        float rel = ((i - 5) - f->frac) * SLICE_DEG;              /* degrees from pointer */
        float ang = (w->base_deg + rel) * 3.14159265f / 180.0f;
        float th = rel * 3.14159265f / 180.0f;
        wc[i] = (int32_t)lrintf(cosf(th) * 16384.0f);
        ws[i] = (int32_t)lrintf(sinf(th) * 16384.0f);
        wax[i] = (int32_t)lrintf(cosf(ang) * mid * 16.0f);
        way[i] = (int32_t)lrintf(sinf(ang) * mid * 16.0f);
        float op = 0.28f + fabsf(rel) / 160.0f;
        if (op > 0.75f) op = 0.75f;
        shade[i] = (f->settled && i == 5) ? 0 : (int)(op * 256.0f);
    }

    int x0 = w->cx - w->r2 - 3, x1 = w->cx + w->r2 + 3, y0 = w->cy - w->r2 - 3, y1 = w->cy + w->r2 + 3;
    if (x0 < g->cx0) x0 = g->cx0;
    if (y0 < g->cy0) y0 = g->cy0;
    if (x1 > g->cx1) x1 = g->cx1;
    if (y1 > g->cy1) y1 = g->cy1;
    const int32_t lo2 = (r1q - 32) * (r1q - 32), hi2 = (r2q + 32) * (r2q + 32);

    for (int y = y0; y < y1; y++) {
        int32_t dy = y * 16 + 8 - cyq;
        px16 *row = g->px + y * g->stride;
        for (int x = x0; x < x1; x++) {
            int32_t dx = x * 16 + 8 - cxq, d2 = dx * dx + dy * dy;
            if (d2 < lo2 || d2 > hi2) continue;
            int32_t r = (int32_t)fx_isqrt((uint32_t)d2);
            int16_t rel = (int16_t)(fx_atan2(dy, dx) - base_bin);
            int32_t t = rel * 12 + frac_q16;
            int dd = floor_div65536(t + 32768);
            if (dd < -5 || dd > 5 || !f->show[dd + 5]) continue;
            int32_t phi = t - dd * 65536;
            int32_t aphi = phi < 0 ? -phi : phi;
            int32_t e_ang = (int32_t)(((int64_t)(HALF_Q16 - aphi) * r * SLICE_RAD_Q16) >> 32);
            int32_t e = e_ang;
            if (r - r1q < e) e = r - r1q;
            if (r2q - r < e) e = r2q - r;
            int i = dd + 5;
            int cov = fx_clamp((e - 8 + 8) * 16, 0, 256);          /* 0.5px paper gap inset */
            if (cov > 0) {
                px16 c;
                if (f->tex[i]) {
                    int32_t ox = dx - wax[i], oy = dy - way[i];
                    int32_t u = (ox * wc[i] + oy * ws[i]) >> 14;     /* undo the wedge's turn */
                    int32_t v = (-ox * ws[i] + oy * wc[i]) >> 14;
                    int32_t tu = (int32_t)(((int64_t)u * scale_q16) >> 12) + TEX * 128;
                    int32_t tv = (int32_t)(((int64_t)v * scale_q16) >> 12) + TEX * 128;
                    c = g_sample(f->tex[i], TEX, TEX, tu, tv);
                } else {
                    c = p->wash;
                }
                if (shade[i]) c = blend565(c, p->paper, shade[i]);
                row[x] = blend565(row[x], c, cov);
            }
            if (f->settled && dd == 0) {                             /* focused rim, on top */
                int32_t ae = e < 0 ? -e : e;
                int rc = fx_clamp((rim_half - ae + 8) * 16, 0, 256);
                if (rc) row[x] = blend565(row[x], p->blue, rc);
            }
        }
    }

    /* pointer: solid ink die-cut triangle, reading outward */
    {
        float b = w->base_deg * 3.14159265f / 180.0f, ca = cosf(b), sa = sinf(b);
        float t0 = w->r2 + 8 * k, t1 = w->r2 + 30 * k, hw = 14 * k;
        float pts[6] = { w->cx + t0 * ca - hw * sa, w->cy + t0 * sa + hw * ca,
                         w->cx + t1 * ca, w->cy + t1 * sa,
                         w->cx + t0 * ca + hw * sa, w->cy + t0 * sa - hw * ca };
        int32_t q[6];
        for (int i = 0; i < 6; i++) q[i] = (int32_t)lrintf(pts[i] * 16.0f);
        g_convex(g, q, 3, p->ink);
    }

    draw_hub(g, p, w, f, 0);
}

void wheel_draw_hub(gfx *g, const palette *p, const wheel_geom *w, const wheel_frame *f, int rect[4])
{
    int r = (int)(w->r1 * 116 / 128.0f) + 1;
    int x0 = w->cx - r, y0 = w->cy - r, x1 = w->cx + r + 1, y1 = w->cy + r + 1;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > g->w) x1 = g->w;
    if (y1 > g->h) y1 = g->h;
    rect[0] = x0; rect[1] = y0; rect[2] = x1 - x0; rect[3] = y1 > y0 ? y1 - y0 : 0;
    draw_hub(g, p, w, f, 1);
}
