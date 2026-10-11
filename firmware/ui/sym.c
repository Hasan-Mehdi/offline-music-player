#include "sym.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979f
#endif
#define Q(v) ((int32_t)lrintf((v) * 16.0f))

static void poly(gfx *g, const float *p, int n, px16 c)
{
    int32_t xy[32];
    for (int i = 0; i < 2 * n; i++) xy[i] = Q(p[i]);
    g_convex(g, xy, n, c);
}

static void disc(gfx *g, float cx, float cy, float r, px16 c)
{
    if (r > 0.2f) g_disc(g, Q(cx), Q(cy), Q(r), c);
}

static void ring(gfx *g, float cx, float cy, float r, float w, px16 c)
{
    g_ring(g, Q(cx), Q(cy), Q(r), Q(w), c);
}

static void bar(gfx *g, float x0, float y0, float x1, float y1, float w, px16 c)
{
    float dx = x1 - x0, dy = y1 - y0, L = sqrtf(dx * dx + dy * dy);
    if (L < 0.01f) return;
    float nx = -dy / L * w / 2, ny = dx / L * w / 2;
    float p[8] = { x0 + nx, y0 + ny, x1 + nx, y1 + ny, x1 - nx, y1 - ny, x0 - nx, y0 - ny };
    poly(g, p, 4, c);
}

static void rect(gfx *g, float x0, float y0, float x1, float y1, px16 c)
{
    float p[8] = { x0, y0, x1, y0, x1, y1, x0, y1 };
    poly(g, p, 4, c);
}

static void tri(gfx *g, float x0, float y0, float x1, float y1, float x2, float y2, px16 c)
{
    float p[6] = { x0, y0, x1, y1, x2, y2 };
    poly(g, p, 3, c);
}

static void rhomb(gfx *g, float cx, float cy, float ang, float L, float w, px16 c)
{
    float ca = cosf(ang), sa = sinf(ang);
    float p[8] = { cx + ca * L, cy + sa * L, cx - sa * w, cy + ca * w,
                   cx - ca * L, cy - sa * L, cx + sa * w, cy - ca * w };
    poly(g, p, 4, c);
}

/* an arc stroke, a0 -> a1 clockwise on screen (radians, 0 = 3 o'clock) */
static void arc(gfx *g, float cx, float cy, float r, float w, float a0, float a1, px16 c)
{
    int n = (int)((a1 - a0) / 0.26f) + 1;
    float px = cx + cosf(a0) * r, py = cy + sinf(a0) * r;
    disc(g, px, py, w / 2, c);
    for (int i = 1; i <= n; i++) {
        float a = a0 + (a1 - a0) * i / n, qx = cx + cosf(a) * r, qy = cy + sinf(a) * r;
        bar(g, px, py, qx, qy, w, c);
        disc(g, qx, qy, w / 2, c);
        px = qx;
        py = qy;
    }
}

/* a disc drawn only above y_cut */
static void disc_above(gfx *g, float cx, float cy, float r, float y_cut, px16 c)
{
    int s0 = g->cy0, s1 = g->cy1, cut = (int)lrintf(y_cut);
    if (cut < g->cy1) g->cy1 = cut > g->cy0 ? cut : g->cy0;
    disc(g, cx, cy, r, c);
    g->cy0 = s0;
    g->cy1 = s1;
}

void sym_draw(gfx *g, int kind, float cx, float cy, float s, px16 fg, px16 bg, px16 acc, float u)
{
    if (!acc) acc = fg;
    switch (kind) {
    case SYM_WHEEL: {                                /* covers on a wheel; turns a slice */
        disc(g, cx, cy, .46f * s, fg);
        float a0 = M_PI / 8 + M_PI / 4 * (ez_back(u, 1.70158f) - 1);
        for (int k = 0; k < 4; k++) {
            float a = a0 + M_PI * k / 4, dx = cosf(a) * .5f * s, dy = sinf(a) * .5f * s;
            bar(g, cx - dx, cy - dy, cx + dx, cy + dy, .075f * s, bg);
        }
        disc(g, cx, cy, .2f * s, bg);
        disc(g, cx, cy, .085f * s, acc);
        break;
    }
    case SYM_NOW: case SYM_PREV: {                   /* play; it kicks */
        float k = u < 1 ? 1 + .2f * sinf(M_PI * ez_clamp(u)) : 1, d = kind == SYM_PREV ? -1 : 1;
        tri(g, cx - .28f * s * k * d, cy - .4f * s * k, cx - .28f * s * k * d, cy + .4f * s * k,
            cx + .44f * s * k * d, cy, fg);
        if (kind == SYM_PREV) rect(g, cx - .48f * s, cy - .32f * s, cx - .34f * s, cy + .32f * s, fg);
        break;
    }
    case SYM_QUEUE: {                                /* what's next, the live one marked */
        float h = .16f * s, L[3] = { .67f, .5f, .34f };
        for (int j = 0; j < 3; j++) {
            float off = -(1 - ez_back(ez_seg(u, j * .12f, j * .12f + .55f), 1.70158f)) * .3f * s;
            float y = cy + (j - 1) * .3f * s;
            rect(g, cx - .22f * s + off, y - h / 2, cx + (L[j] - .22f) * s + off, y + h / 2, fg);
        }
        rect(g, cx - .46f * s, cy - .3f * s - h / 2, cx - .46f * s + h, cy - .3f * s + h / 2, acc);
        break;
    }
    case SYM_EXPLORE: {                              /* a compass rose; swings round to north */
        float a = M_PI / 2 * (ez_back(u, 1.70158f) - 1);
        rhomb(g, cx, cy, a, .5f * s, .13f * s, fg);
        rhomb(g, cx, cy, a + M_PI / 2, .5f * s, .13f * s, fg);
        rhomb(g, cx, cy, a + M_PI / 4, .3f * s, .08f * s, fg);
        rhomb(g, cx, cy, a + 3 * M_PI / 4, .3f * s, .08f * s, fg);
        float n = a - M_PI / 2, p = n + M_PI / 2;
        tri(g, cx + cosf(n) * .5f * s, cy + sinf(n) * .5f * s, cx + cosf(p) * .13f * s, cy + sinf(p) * .13f * s,
            cx - cosf(p) * .13f * s, cy - sinf(p) * .13f * s, acc);
        disc(g, cx, cy, .055f * s, bg);
        break;
    }
    case SYM_SEARCH: {                               /* a lens; it wiggles, looking */
        float wig = u < 1 ? sinf(u * M_PI * 3) * (1 - u) * .14f * s : 0;
        float rx = cx - .1f * s + wig, ry = cy - .1f * s, a = M_PI / 4;
        ring(g, rx, ry, .25f * s, .12f * s, fg);
        bar(g, rx + cosf(a) * .3f * s, ry + sinf(a) * .3f * s, cx + .42f * s + wig * .5f, cy + .42f * s, .15f * s, fg);
        break;
    }
    case SYM_LIBRARY: {                              /* spines; the last one tips over */
        float base = cy + .42f * s, w = .12f * s, gp = .045f * s, x = cx - .44f * s;
        static const float hs[4] = { .78f, .6f, .88f, .7f };
        for (int i = 0; i < 4; i++) {
            rect(g, x, base - hs[i] * s, x + w, base, i == 2 ? acc : fg);
            x += w + gp;
        }
        float lean = .2f * s * ez_back(ez_seg(u, .1f, .8f), 2.4f), xb = x + .04f * s;
        float p[8] = { xb, base, xb + w, base, xb + w - lean, base - .66f * s, xb - lean, base - .66f * s };
        poly(g, p, 4, fg);
        break;
    }
    case SYM_LIKED: {                                /* a heart; it beats twice */
        float k = 1 + .2f * sinf(M_PI * ez_seg(u, 0, .4f)) + .1f * sinf(M_PI * ez_seg(u, .45f, .75f));
        if (u >= 1) k = 1;
        float S = s * k, a = .56f * S, h = a / 1.41421f, m = a / 2.82843f, r = a / 2, c = cy + .041f * S;
        float p[8] = { cx, c - h, cx + h, c, cx, c + h, cx - h, c };
        poly(g, p, 4, fg);
        disc(g, cx - m, c - m, r, fg);
        disc(g, cx + m, c - m, r, fg);
        break;
    }
    case SYM_SETTINGS: {                             /* two sliders; the knobs slide to place */
        static const float dy[2] = { -.2f, .2f }, k0[2] = { -.3f, .3f }, k1[2] = { .17f, -.19f };
        for (int j = 0; j < 2; j++) {
            float uj = ez_back(ez_seg(u, j * .12f, j * .12f + .6f), 1.70158f), y = cy + dy[j] * s;
            rect(g, cx - .45f * s, y - .04f * s, cx + .45f * s, y + .04f * s, fg);
            float kx = cx + (k0[j] + (k1[j] - k0[j]) * uj) * s;
            disc(g, kx, y, .15f * s, fg);
            if (j) disc(g, kx, y, .065f * s, bg);
        }
        break;
    }
    case SYM_SONGS:                                  /* a note */
        disc(g, cx - .12f * s, cy + .26f * s, .18f * s, fg);
        rect(g, cx - .03f * s, cy - .42f * s, cx + .06f * s, cy + .26f * s, fg);
        { float p[8] = { cx + .06f * s, cy - .42f * s, cx + .36f * s, cy - .18f * s, cx + .36f * s, cy - .02f * s,
                         cx + .06f * s, cy - .26f * s };
          poly(g, p, 4, fg); }
        break;
    case SYM_ARTISTS:                                /* a bust */
        disc(g, cx, cy - .2f * s, .2f * s, fg);
        disc_above(g, cx, cy + .46f * s, .38f * s, cy + .46f * s, fg);
        break;
    case SYM_GENRES: {                               /* crates */
        float q = .36f * s, gp = .1f * s;
        for (int i = 0; i < 4; i++) {
            float x0 = cx - q - gp / 2 + (i % 2) * (q + gp), y0 = cy - q - gp / 2 + (i / 2) * (q + gp);
            rect(g, x0, y0, x0 + q, y0 + q, i == 1 ? acc : fg);
        }
        break;
    }
    case SYM_OSTS:                                   /* a d-pad: the soundtracks are mostly games */
        rect(g, cx - .45f * s, cy - .15f * s, cx + .45f * s, cy + .15f * s, fg);
        rect(g, cx - .15f * s, cy - .45f * s, cx + .15f * s, cy + .45f * s, fg);
        disc(g, cx, cy, .07f * s, bg);
        break;
    case SYM_HISTORY:                                /* rewind */
        tri(g, cx + .02f * s, cy - .32f * s, cx + .02f * s, cy + .32f * s, cx - .42f * s, cy, fg);
        tri(g, cx + .44f * s, cy - .32f * s, cx + .44f * s, cy + .32f * s, cx, cy, fg);
        break;
    case SYM_SHUFFLE:
        bar(g, cx - .42f * s, cy + .26f * s, cx + .2f * s, cy - .26f * s, .11f * s, fg);
        bar(g, cx - .42f * s, cy - .26f * s, cx + .2f * s, cy + .26f * s, .11f * s, fg);
        tri(g, cx + .14f * s, cy - .43f * s, cx + .46f * s, cy - .26f * s, cx + .14f * s, cy - .09f * s, fg);
        tri(g, cx + .14f * s, cy + .09f * s, cx + .46f * s, cy + .26f * s, cx + .14f * s, cy + .43f * s, fg);
        break;
    case SYM_STATION: {                              /* broadcast */
        float ox = cx - .32f * s;
        disc(g, ox, cy, .11f * s, fg);
        arc(g, ox, cy, .37f * s, .1f * s, -0.84f, 0.84f, fg);
        arc(g, ox, cy, .61f * s, .1f * s, -0.84f, 0.84f, fg);
        break;
    }
    case SYM_SOUND: {                                /* three faders */
        static const float xs[3] = { -.3f, 0, .3f }, ks[3] = { .15f, -.22f, .05f };
        for (int i = 0; i < 3; i++) {
            rect(g, cx + (xs[i] - .035f) * s, cy - .42f * s, cx + (xs[i] + .035f) * s, cy + .42f * s, fg);
            disc(g, cx + xs[i] * s, cy + ks[i] * s, .13f * s, fg);
        }
        break;
    }
    case SYM_SCREEN:                                 /* the sun */
        disc(g, cx, cy, .2f * s, fg);
        for (int k = 0; k < 8; k++) {
            float a = k * M_PI / 4;
            bar(g, cx + cosf(a) * .31f * s, cy + sinf(a) * .31f * s, cx + cosf(a) * .47f * s, cy + sinf(a) * .47f * s,
                .09f * s, fg);
        }
        break;
    case SYM_SLEEP:                                  /* a crescent */
        disc(g, cx, cy, .4f * s, fg);
        disc(g, cx + .2f * s, cy - .14f * s, .34f * s, bg);
        break;
    case SYM_POWER:
        arc(g, cx, cy + .04f * s, .33f * s, .11f * s, -0.96f, 4.10f, fg);
        rect(g, cx - .06f * s, cy - .46f * s, cx + .06f * s, cy - .02f * s, fg);
        break;
    case SYM_BT: {                                   /* the rune */
        static const float pt[6][2] = { { 0, 3 }, { 6, 7 }, { 3, 10 }, { 3, 0 }, { 6, 3 }, { 0, 7 } };
        for (int i = 0; i < 5; i++)
            bar(g, cx + (pt[i][0] - 3) / 11 * s * .95f, cy + (pt[i][1] - 5) / 11 * s * .95f,
                cx + (pt[i + 1][0] - 3) / 11 * s * .95f, cy + (pt[i + 1][1] - 5) / 11 * s * .95f, .1f * s, fg);
        break;
    }
    case SYM_CLOCK:
        ring(g, cx, cy, .4f * s, .1f * s, fg);
        bar(g, cx, cy, cx, cy - .26f * s, .09f * s, fg);
        bar(g, cx, cy, cx + .2f * s, cy, .09f * s, fg);
        disc(g, cx, cy, .07f * s, fg);
        break;
    case SYM_DISLIKE:
        bar(g, cx - .34f * s, cy - .34f * s, cx + .34f * s, cy + .34f * s, .15f * s, fg);
        bar(g, cx - .34f * s, cy + .34f * s, cx + .34f * s, cy - .34f * s, .15f * s, fg);
        break;
    case SYM_NEXT:                                   /* play next */
        tri(g, cx - .36f * s, cy - .32f * s, cx - .36f * s, cy + .32f * s, cx + .16f * s, cy, fg);
        rect(g, cx + .2f * s, cy - .32f * s, cx + .34f * s, cy + .32f * s, fg);
        break;
    case SYM_PLAYBACK:                               /* play inside a loop */
        ring(g, cx, cy, .38f * s, .1f * s, fg);
        tri(g, cx - .12f * s, cy - .2f * s, cx - .12f * s, cy + .2f * s, cx + .2f * s, cy, fg);
        break;
    case SYM_THEME:                                  /* half and half: how it looks */
        ring(g, cx, cy, .38f * s, .1f * s, fg);
        disc(g, cx, cy, .3f * s, fg);
        { int s0 = g->cx0, cut = (int)lrintf(cx);
          if (cut > g->cx0) g->cx0 = cut < g->cx1 ? cut : g->cx1;
          disc(g, cx, cy, .29f * s, bg);
          g->cx0 = s0; }
        break;
    case SYM_PAUSE:
        rect(g, cx - .3f * s, cy - .34f * s, cx - .08f * s, cy + .34f * s, fg);
        rect(g, cx + .08f * s, cy - .34f * s, cx + .3f * s, cy + .34f * s, fg);
        break;
    case SYM_STOP:
        rect(g, cx - .3f * s, cy - .3f * s, cx + .3f * s, cy + .3f * s, fg);
        break;
    default:
        break;
    }
}
