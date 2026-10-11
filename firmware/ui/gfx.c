#include "gfx.h"
#include "fx.h"

void g_init(gfx *g, px16 *px, int w, int h, int stride)
{
    g->px = px; g->w = w; g->h = h; g->stride = stride;
    g_noclip(g);
}

void g_clip(gfx *g, int x0, int y0, int x1, int y1)
{
    g->cx0 = x0 < 0 ? 0 : x0;
    g->cy0 = y0 < 0 ? 0 : y0;
    g->cx1 = x1 > g->w ? g->w : x1;
    g->cy1 = y1 > g->h ? g->h : y1;
}

void g_noclip(gfx *g) { g->cx0 = 0; g->cy0 = 0; g->cx1 = g->w; g->cy1 = g->h; }

static int clip_rect(const gfx *g, int *x, int *y, int *w, int *h)
{
    int x0 = *x, y0 = *y, x1 = *x + *w, y1 = *y + *h;
    if (x0 < g->cx0) x0 = g->cx0;
    if (y0 < g->cy0) y0 = g->cy0;
    if (x1 > g->cx1) x1 = g->cx1;
    if (y1 > g->cy1) y1 = g->cy1;
    if (x1 <= x0 || y1 <= y0) return 0;
    *x = x0; *y = y0; *w = x1 - x0; *h = y1 - y0;
    return 1;
}

void g_fill(gfx *g, int x, int y, int w, int h, px16 c)
{
    if (!clip_rect(g, &x, &y, &w, &h)) return;
    for (int j = 0; j < h; j++) {
        px16 *p = g->px + (y + j) * g->stride + x;
        for (int i = 0; i < w; i++) p[i] = c;
    }
}

void g_fill_a(gfx *g, int x, int y, int w, int h, px16 c, int a)
{
    if (!clip_rect(g, &x, &y, &w, &h)) return;
    for (int j = 0; j < h; j++) {
        px16 *p = g->px + (y + j) * g->stride + x;
        for (int i = 0; i < w; i++) p[i] = blend565(p[i], c, a);
    }
}

void g_blit(gfx *g, const px16 *src, int sw, int sh, int x, int y)
{
    int cx = x, cy = y, w = sw, h = sh;
    if (!clip_rect(g, &cx, &cy, &w, &h)) return;
    for (int j = 0; j < h; j++) {
        const px16 *s = src + (cy - y + j) * sw + (cx - x);
        px16 *p = g->px + (cy + j) * g->stride + cx;
        for (int i = 0; i < w; i++) p[i] = s[i];
    }
}

px16 g_sample(const px16 *tex, int tw, int th, int32_t u, int32_t v)
{
    /* texel centres at integer + 0.5: shift so that (u, v) = 0 hits texel 0's centre */
    u -= 128; v -= 128;
    if (u < 0) u = 0;
    if (v < 0) v = 0;
    int32_t umax = (tw - 1) << 8, vmax = (th - 1) << 8;
    if (u > umax) u = umax;
    if (v > vmax) v = vmax;
    int x0 = u >> 8, y0 = v >> 8, fx = u & 255, fy = v & 255;
    int x1 = x0 + 1 < tw ? x0 + 1 : x0, y1 = y0 + 1 < th ? y0 + 1 : y0;
    px16 a = tex[y0 * tw + x0], b = tex[y0 * tw + x1];
    px16 c = tex[y1 * tw + x0], d = tex[y1 * tw + x1];
    int w00 = (256 - fx) * (256 - fy), w10 = fx * (256 - fy), w01 = (256 - fx) * fy, w11 = fx * fy;
    int r = ((a >> 11) * w00 + (b >> 11) * w10 + (c >> 11) * w01 + (d >> 11) * w11 + 32768) >> 16;
    int gg = (((a >> 5) & 63) * w00 + ((b >> 5) & 63) * w10 + ((c >> 5) & 63) * w01 + ((d >> 5) & 63) * w11 + 32768) >> 16;
    int bl = ((a & 31) * w00 + (b & 31) * w10 + (c & 31) * w01 + (d & 31) * w11 + 32768) >> 16;
    return (px16)((r << 11) | (gg << 5) | bl);
}

void g_blit_scaled(gfx *g, const px16 *src, int sw, int sh, int x, int y, int dw, int dh)
{
    if (dw == sw && dh == sh) { g_blit(g, src, sw, sh, x, y); return; }
    int cx = x, cy = y, w = dw, h = dh;
    if (!clip_rect(g, &cx, &cy, &w, &h)) return;
    int32_t su = (sw << 16) / dw, sv = (sh << 16) / dh;   /* texels per px, Q16 */
    for (int j = 0; j < h; j++) {
        int32_t v = (int32_t)(((int64_t)((cy - y + j) * 2 + 1) * sv) >> 9);   /* Q8 centre */
        px16 *p = g->px + (cy + j) * g->stride + cx;
        for (int i = 0; i < w; i++) {
            int32_t u = (int32_t)(((int64_t)((cx - x + i) * 2 + 1) * su) >> 9);
            p[i] = g_sample(src, sw, sh, u, v);
        }
    }
}

/* coverage (0..256) of a pixel whose centre is d_q4 inside an edge (negative = outside) */
static inline int edge_cov(int32_t d_q4)
{
    return fx_clamp((d_q4 + 8) * 16, 0, 256);
}

void g_disc(gfx *g, int cx, int cy, int r, px16 c)
{
    int x0 = (cx - r) / 16 - 1, x1 = (cx + r) / 16 + 2;
    int y0 = (cy - r) / 16 - 1, y1 = (cy + r) / 16 + 2;
    if (x0 < g->cx0) x0 = g->cx0;
    if (y0 < g->cy0) y0 = g->cy0;
    if (x1 > g->cx1) x1 = g->cx1;
    if (y1 > g->cy1) y1 = g->cy1;
    int32_t rin = r > 8 ? (r - 8) * (r - 8) : 0, rout = (r + 8) * (r + 8);
    for (int y = y0; y < y1; y++) {
        int32_t dy = y * 16 + 8 - cy;
        px16 *p = g->px + y * g->stride;
        for (int x = x0; x < x1; x++) {
            int32_t dx = x * 16 + 8 - cx, d2 = dx * dx + dy * dy;
            if (d2 >= rout) continue;
            if (d2 <= rin) { p[x] = c; continue; }
            p[x] = blend565(p[x], c, edge_cov(r - (int32_t)fx_isqrt((uint32_t)d2)));
        }
    }
}

void g_ring(gfx *g, int cx, int cy, int r, int width, px16 c)
{
    int ro = r + width / 2, ri = r - width / 2;
    int x0 = (cx - ro) / 16 - 1, x1 = (cx + ro) / 16 + 2;
    int y0 = (cy - ro) / 16 - 1, y1 = (cy + ro) / 16 + 2;
    if (x0 < g->cx0) x0 = g->cx0;
    if (y0 < g->cy0) y0 = g->cy0;
    if (x1 > g->cx1) x1 = g->cx1;
    if (y1 > g->cy1) y1 = g->cy1;
    int32_t lo = ri > 8 ? (ri - 8) * (ri - 8) : 0, hi = (ro + 8) * (ro + 8);
    for (int y = y0; y < y1; y++) {
        int32_t dy = y * 16 + 8 - cy;
        px16 *p = g->px + y * g->stride;
        for (int x = x0; x < x1; x++) {
            int32_t dx = x * 16 + 8 - cx, d2 = dx * dx + dy * dy;
            if (d2 >= hi || d2 <= lo) continue;
            int32_t d = (int32_t)fx_isqrt((uint32_t)d2);
            int32_t e = (ro - d) < (d - ri) ? (ro - d) : (d - ri);
            p[x] = blend565(p[x], c, edge_cov(e));
        }
    }
}

void g_disc_tex(gfx *g, int cx, int cy, int r, const px16 *tex, int tw)
{
    int x0 = (cx - r) / 16 - 1, x1 = (cx + r) / 16 + 2;
    int y0 = (cy - r) / 16 - 1, y1 = (cy + r) / 16 + 2;
    if (x0 < g->cx0) x0 = g->cx0;
    if (y0 < g->cy0) y0 = g->cy0;
    if (x1 > g->cx1) x1 = g->cx1;
    if (y1 > g->cy1) y1 = g->cy1;
    int32_t rout = (r + 8) * (r + 8);
    int32_t scale = (int32_t)(((int64_t)tw << 16) / (2 * r));  /* texels per Q4 unit, Q16 */
    for (int y = y0; y < y1; y++) {
        int32_t dy = y * 16 + 8 - cy;
        px16 *p = g->px + y * g->stride;
        for (int x = x0; x < x1; x++) {
            int32_t dx = x * 16 + 8 - cx, d2 = dx * dx + dy * dy;
            if (d2 >= rout) continue;
            int32_t u = (int32_t)(((int64_t)(dx + r) * scale) >> 8);   /* Q8 texels */
            int32_t v = (int32_t)(((int64_t)(dy + r) * scale) >> 8);
            px16 s = g_sample(tex, tw, tw, u, v);
            int a = edge_cov(r - (int32_t)fx_isqrt((uint32_t)d2));
            p[x] = blend565(p[x], s, a);
        }
    }
}

void g_convex(gfx *g, const int32_t *xy, int n, px16 c)
{
    if (n < 3 || n > 16) return;
    int32_t nx[16], ny[16], ox[16], oy[16];
    int64_t area = 0;
    for (int i = 0; i < n; i++) {
        int j = (i + 1) % n;
        area += (int64_t)xy[2 * i] * xy[2 * j + 1] - (int64_t)xy[2 * j] * xy[2 * i + 1];
    }
    int sgn = area > 0 ? 1 : -1;     /* screen coords: area>0 = clockwise */
    int32_t minx = xy[0], maxx = xy[0], miny = xy[1], maxy = xy[1];
    for (int i = 0; i < n; i++) {
        int j = (i + 1) % n;
        int32_t ex = xy[2 * j] - xy[2 * i], ey = xy[2 * j + 1] - xy[2 * i + 1];
        int32_t len = (int32_t)fx_isqrt((uint32_t)(ex * ex + ey * ey));
        if (len == 0) len = 1;
        /* inward normal, Q14 */
        nx[i] = (int32_t)(((int64_t)-ey * sgn * 16384) / len);
        ny[i] = (int32_t)(((int64_t)ex * sgn * 16384) / len);
        ox[i] = xy[2 * i]; oy[i] = xy[2 * i + 1];
        if (xy[2 * i] < minx) minx = xy[2 * i];
        if (xy[2 * i] > maxx) maxx = xy[2 * i];
        if (xy[2 * i + 1] < miny) miny = xy[2 * i + 1];
        if (xy[2 * i + 1] > maxy) maxy = xy[2 * i + 1];
    }
    /* clockwise in screen space has the inward normal on the right: flip test */
    int x0 = minx / 16 - 1, x1 = maxx / 16 + 2, y0 = miny / 16 - 1, y1 = maxy / 16 + 2;
    if (x0 < g->cx0) x0 = g->cx0;
    if (y0 < g->cy0) y0 = g->cy0;
    if (x1 > g->cx1) x1 = g->cx1;
    if (y1 > g->cy1) y1 = g->cy1;
    for (int y = y0; y < y1; y++) {
        int32_t py = y * 16 + 8;
        px16 *p = g->px + y * g->stride;
        for (int x = x0; x < x1; x++) {
            int32_t pxq = x * 16 + 8, dmin = 1 << 30;
            for (int i = 0; i < n; i++) {
                int32_t d = (int32_t)(((int64_t)nx[i] * (pxq - ox[i]) + (int64_t)ny[i] * (py - oy[i])) >> 14);
                if (d < dmin) dmin = d;
                if (dmin < -8) break;
            }
            if (dmin < -8) continue;
            p[x] = blend565(p[x], c, edge_cov(dmin));
        }
    }
}
