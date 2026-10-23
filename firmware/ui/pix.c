#include "pix.h"
#include <math.h>
#include "sym.h"

#define HEX(v) C565(((v) >> 16) & 255, ((v) >> 8) & 255, (v) & 255)

/* the listener's room (docs/h2/room): walnut desk and shelf, cognac leather, pothos, sage
 * curtains, the silver vented PC case, lampshade white, grey felt, one orange keycap */
#define RP_DAY_INIT { \
    .wall = HEX(0xd6c2a3), .wall_sh = HEX(0xb8a080), \
    .walnut = HEX(0x4d3322), .walnut_d = HEX(0x3a2619), .walnut_l = HEX(0x60422d), .walnut_hi = HEX(0x825c3c), \
    .ink = HEX(0x2e1f15), .cream = HEX(0xf4eee2), .sub = HEX(0x7c6852), \
    .leather = HEX(0xb26a35), .leather_d = HEX(0x915328), .stitch = HEX(0xe6b072), \
    .leaf = HEX(0x4b8a36), .leaf_l = HEX(0x74b14b), .leaf_d = HEX(0x2f5e24), \
    .sage = HEX(0x66733f), .sage_l = HEX(0x76844c), .sage_d = HEX(0x546031), \
    .silver = HEX(0xc9cac6), .silver_l = HEX(0xe7e8e4), .silver_d = HEX(0x9c9d99), .slot = HEX(0x6d6e6a), \
    .shade = HEX(0xf4efe5), .shade_line = HEX(0xe4dccd), \
    .key = HEX(0xeaa22c), .key_d = HEX(0xc37c1b), .key_l = HEX(0xf7c65d), \
    .felt = HEX(0xb7b5af), .felt_d = HEX(0xa8a6a0), .felt_l = HEX(0xc6c4be), \
    .led = HEX(0xfff2c9), .parch = HEX(0xf2dcae), .parch_d = HEX(0xe2c58e), .parch_l = HEX(0xf8eaca), \
    .red = HEX(0xd0382a), \
    .wink = HEX(0x2e1f15), .wsub = HEX(0x7c6852), .wacc = HEX(0x2f5e24), \
}
const room_pal RP_DAY = RP_DAY_INIT;
/* after dark: the walls go dim, the lampshade and the light bar glow, text on the wall turns light */
const room_pal RP_NIGHT = {
    .wall = HEX(0x463d38), .wall_sh = HEX(0x37302c),
    .walnut = HEX(0x34231a), .walnut_d = HEX(0x261911), .walnut_l = HEX(0x433022), .walnut_hi = HEX(0x5e4330),
    .ink = HEX(0x1d140e), .cream = HEX(0xece3d0), .sub = HEX(0x55483d),
    .leather = HEX(0x7a4a29), .leather_d = HEX(0x5f381e), .stitch = HEX(0xb48653),
    .leaf = HEX(0x356329), .leaf_l = HEX(0x4e8a3a), .leaf_d = HEX(0x22441c),
    .sage = HEX(0x48532f), .sage_l = HEX(0x535f37), .sage_d = HEX(0x3a4426),
    .silver = HEX(0x8a8c96), .silver_l = HEX(0xa3a5ae), .silver_d = HEX(0x6c6e78), .slot = HEX(0x4a4b52),
    .shade = HEX(0xffe9bd), .shade_line = HEX(0xf0d39c),
    .key = HEX(0xdb8d22), .key_d = HEX(0xa9661a), .key_l = HEX(0xf0ad48),
    .felt = HEX(0x6e6d72), .felt_d = HEX(0x616066), .felt_l = HEX(0x8a898e),
    .led = HEX(0xffd98e), .parch = HEX(0xd8c193), .parch_d = HEX(0xc2a776), .parch_l = HEX(0xe6d3a8),
    .red = HEX(0xd2443a),
    .wink = HEX(0xefe6d4), .wsub = HEX(0xae9f8b), .wacc = HEX(0x86c063),
};
room_pal RP = RP_DAY_INIT;
int rp_k;

void rp_night(int k)
{
    if (k < 0) k = 0;
    if (k > 256) k = 256;
    if (k == rp_k) return;
    rp_k = k;
    const px16 *d = (const px16 *)&RP_DAY, *n = (const px16 *)&RP_NIGHT;
    px16 *o = (px16 *)&RP;
    for (size_t i = 0; i < sizeof RP / sizeof(px16); i++) o[i] = blend565(d[i], n[i], k);
}

px16 nightc(px16 c)
{
    if (rp_k <= 0) return c;
    int r = c >> 11, g = (c >> 5) & 63, b = c & 31, k = rp_k;
    r = r * (256 - k * 150 / 256) >> 8;
    g = g * (256 - k * 150 / 256) >> 8;
    b = (b * (256 - k * 118 / 256) >> 8) + (k * 2 >> 8);
    return (px16)((r << 11) | (g << 5) | (b > 31 ? 31 : b));
}

/* ------------------------------------------------------------------ fonts */
static inline void put(gfx *g, int x, int y, px16 c)
{
    if (x >= g->cx0 && x < g->cx1 && y >= g->cy0 && y < g->cy1) g->px[y * g->stride + x] = c;
}

static inline void put2(gfx *g, int a, int b, px16 c)
{
    int x = 2 * a, y = 2 * b;
    if (x + 1 < g->cx0 || x >= g->cx1 || y + 1 < g->cy0 || y >= g->cy1) return;
    put(g, x, y, c);
    put(g, x + 1, y, c);
    put(g, x, y + 1, c);
    put(g, x + 1, y + 1, c);
}

int pf_width(const pixfont *f, const char *s, int scale)
{
    int w = 0;
    for (; *s; s++) {
        int c = (unsigned char)*s;
        if (c < 32 || c > 126) c = '?';
        w += f->w[c - 32];
    }
    return w * scale;
}

int pf_text(gfx *g, const pixfont *f, int x, int y_base, const char *s, px16 col, int scale)
{
    int x0 = x, top = y_base - f->base * scale;
    for (; *s; s++) {
        int c = (unsigned char)*s;
        if (c < 32 || c > 126) c = '?';
        int gi = c - 32, w = f->w[gi];
        const uint8_t *d = f->data + f->off[gi];
        if (f->mono) {
            int rb = (w + 7) / 8;
            for (int y = 0; y < f->h; y++)
                for (int xx = 0; xx < w; xx++)
                    if (d[y * rb + xx / 8] & (0x80 >> (xx % 8))) {
                        if (scale == 2) {
                            put(g, x + 2 * xx, top + 2 * y, col);
                            put(g, x + 2 * xx + 1, top + 2 * y, col);
                            put(g, x + 2 * xx, top + 2 * y + 1, col);
                            put(g, x + 2 * xx + 1, top + 2 * y + 1, col);
                        } else put(g, x + xx, top + y, col);
                    }
        } else {
            for (int y = 0; y < f->h; y++) {
                int py = top + y;
                if (py < g->cy0 || py >= g->cy1) continue;
                for (int xx = 0; xx < w; xx++) {
                    int a = d[y * w + xx], px = x + xx;
                    if (!a || px < g->cx0 || px >= g->cx1) continue;
                    px16 *p = g->px + py * g->stride + px;
                    *p = blend565(*p, col, a + (a >> 7));
                }
            }
        }
        x += w * scale;
    }
    return x - x0;
}

/* ------------------------------------------------------------------ the grid */
void ck_point(gfx *g, int a, int b, px16 col) { put2(g, a, b, col); }

void ck_rect(gfx *g, int a, int b, int c, int d, px16 col)
{
    if (c > a && d > b) g_fill(g, 2 * a, 2 * b, 2 * (c - a), 2 * (d - b), col);
}

void ck_hline(gfx *g, int a, int c, int b, px16 col) { ck_rect(g, a, b, c, b + 1, col); }

static const uint8_t IND[4][3] = { { 0 }, { 1 }, { 2, 1 }, { 3, 1, 1 } };
static const uint8_t NIND[4] = { 0, 1, 2, 3 };

static int corner_out(int x, int y, int w, int h, int r)
{
    if (r <= 0) return 0;
    int n = NIND[r];
    int row = y < n ? y : (h - 1 - y < n ? h - 1 - y : -1);
    if (row < 0) return 0;
    int k = IND[r][row];
    return x < k || x >= w - k;
}

void ck_rrect(gfx *g, int a, int b, int c, int d, px16 col, int r)
{
    int w = c - a, h = d - b;
    if (w <= 0 || h <= 0) return;
    int n = r > 0 ? NIND[r] : 0;
    if (h > 2 * n) ck_rect(g, a, b + n, c, d - n, col);
    for (int i = 0; i < n && i < h; i++) {
        int k = IND[r][i];
        ck_rect(g, a + k, b + i, c - k, b + i + 1, col);
        ck_rect(g, a + k, d - 1 - i, c - k, d - i, col);
    }
}

/* ------------------------------------------------------------------ materials */
px16 mat_base(int m)
{
    switch (m) {
    case MAT_WOOD: return RP.walnut;
    case MAT_LEATHER: return RP.leather;
    case MAT_LEAF: return RP.leaf;
    case MAT_SAGE: return RP.sage;
    case MAT_SILVER: return RP.silver;
    case MAT_SHADE: return RP.shade;
    case MAT_KEY: return RP.key;
    case MAT_FELT: return RP.felt;
    default: return RP.parch;
    }
}

px16 mat_ink(int m)
{
    return (m == MAT_SILVER || m == MAT_SHADE || m == MAT_KEY || m == MAT_FELT || m == MAT_PARCH) ? RP.ink : RP.cream;
}

px16 mat_acc(int m)
{
    return m == MAT_SILVER ? RP.leaf_d : m == MAT_KEY ? RP.cream : RP.key;
}

static uint32_t rs;
static inline uint32_t rr(void)
{
    rs ^= rs << 13;
    rs ^= rs >> 17;
    rs ^= rs << 5;
    return rs;
}
#define CHANCE(pct) ((rr() % 1000) < (pct) * 10)

void ck_material(gfx *g, int a, int b, int c, int d, int mat, uint32_t seed, int r)
{
    int w = c - a, h = d - b;
    if (w <= 0 || h <= 0 || w > 160) return;
    rs = seed * 2654435761u + 0x9E3779B9u;
    if (!rs) rs = 1;
    px16 row[160];
    px16 base = mat_base(mat);
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) row[x] = base;
        switch (mat) {
        case MAT_WOOD: {                                  /* grain: broken streaks */
            int x = -(int)(rr() % 8);
            while (x < w) {
                int L = 3 + (int)(rr() % 12), k = (int)(rr() % 5);
                px16 col = k == 1 || k == 4 ? RP.walnut_d : k == 2 ? RP.walnut_l : 0;
                if (col) for (int xx = x < 0 ? 0 : x; xx < x + L && xx < w; xx++) row[xx] = col;
                x += L + 2 + (int)(rr() % 7);
            }
            break;
        }
        case MAT_LEATHER:
            for (int x = 0; x < w; x++) if (CHANCE(7)) row[x] = RP.leather_d;
            if (y == 2 || y == h - 3)
                for (int x = 2; x < w - 2; x++) if ((x / 2) % 2 == 0) row[x] = RP.stitch;
            if (y >= 2 && y < h - 2 && (y / 2) % 2 == 0) { row[2] = RP.stitch; row[w - 3] = RP.stitch; }
            break;
        case MAT_LEAF:
            for (int x = 0; x < w; x++) row[x] = CHANCE(5) ? RP.leaf_l : CHANCE(5) ? RP.leaf_d : base;
            break;
        case MAT_SAGE:                                    /* curtain folds */
            for (int x = 0; x < w; x++) row[x] = x % 6 < 2 ? RP.sage_l : x % 6 == 3 ? RP.sage_d : base;
            break;
        case MAT_SHADE:
            for (int x = 0; x < w; x += 5) row[x] = RP.shade_line;
            break;
        case MAT_FELT:
            for (int x = 0; x < w; x++) row[x] = CHANCE(12) ? RP.felt_d : CHANCE(6) ? RP.felt_l : base;
            break;
        case MAT_PARCH:
            for (int x = 0; x < w; x++) if (CHANCE(3)) row[x] = RP.parch_d;
            break;
        default:
            break;
        }
        /* light from above, shadow below */
        px16 hi = mat == MAT_WOOD ? RP.walnut_hi : mat == MAT_LEAF ? RP.leaf_l : mat == MAT_SILVER ? RP.silver_l :
                  mat == MAT_KEY ? RP.key_l : mat == MAT_FELT ? RP.felt_l : 0;
        px16 lo = mat == MAT_WOOD ? RP.walnut_d : mat == MAT_LEATHER ? RP.leather_d : mat == MAT_LEAF ? RP.leaf_d :
                  mat == MAT_SAGE ? RP.sage_d : mat == MAT_SILVER ? RP.silver_d : mat == MAT_SHADE ? RP.shade_line :
                  mat == MAT_KEY ? RP.key_d : mat == MAT_FELT ? RP.felt_d : RP.parch_d;
        if (y == 0 && hi) for (int x = 0; x < w; x++) row[x] = hi;
        if (y == h - 1 || (mat == MAT_KEY && y == h - 2)) for (int x = 0; x < w; x++) row[x] = lo;
        for (int x = 0; x < w; x++)
            if (!corner_out(x, y, w, h, r)) put2(g, a + x, b + y, row[x]);
    }
}

void ck_vents(gfx *g, int a, int b, int c, int d)
{
    for (int k = 0, y = b; y < d; y += 3, k++)
        for (int x = a + (k % 2 ? 3 : 0); x + 5 <= c; x += 7) {
            ck_rect(g, x, y, x + 5, y + 1, RP.slot);
            put2(g, x, y + 1, RP.silver_l);
        }
}

/* ------------------------------------------------------------------ symbols on the grid */
static px16 symbuf[64 * 64];

static int dist565(px16 p, px16 q)
{
    int dr = (p >> 11) - (q >> 11), dg = ((p >> 5) & 63) - ((q >> 5) & 63), db = (p & 31) - (q & 31);
    return dr * dr * 4 + dg * dg + db * db * 4;
}

void ck_sym(gfx *g, int kind, int cx, int cy, int s, px16 fg, px16 bg, px16 acc, float u)
{
    int n = (s + 1) / 2;
    if (n < 4) n = 4;
    if (n > 64) n = 64;
    gfx t;
    g_init(&t, symbuf, n, n, n);
    g_fill(&t, 0, 0, n, n, bg);
    sym_draw(&t, kind, n / 2.0f, n / 2.0f, n * .96f, fg, bg, acc, u);
    int a0 = cx / 2 - n / 2, b0 = cy / 2 - n / 2;
    for (int y = 0; y < n; y++)
        for (int x = 0; x < n; x++) {
            px16 v = symbuf[y * n + x];
            int dbg = dist565(v, bg), dfg = dist565(v, fg), dac = acc ? dist565(v, acc) : 1 << 30;
            if (dbg <= dfg && dbg <= dac) continue;
            put2(g, a0 + x, b0 + y, dac < dfg ? acc : fg);
        }
}

void ck_pointer(gfx *g, int x, int y, uint32_t t, px16 outline, px16 fill)
{
    static const char *const ARROW[7] = { "#....", "##...", "#c#..", "#cc#.", "#c#..", "##...", "#...." };
    int bob = (int)lrintf(sinf((float)t / 1000.0f * 6.2832f * 1.6f));
    int a = x / 2 + bob, b = y / 2 - 3;
    for (int r = 0; r < 7; r++)
        for (int k = 0; k < 5; k++) {
            char ch = ARROW[r][k];
            if (ch != '.') put2(g, a + k, b + r, ch == '#' ? outline : fill);
        }
}
