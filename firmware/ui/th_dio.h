/* Diorama: a close look at the listener's desk as it is now (2026-10 photos) -- the shelf
 * over it with its plants and plushies, the Sekiro and Hollow Knight posters, the monitor,
 * the keyboard, the headphones on their stand, the white case on its walnut foot -- and
 * the menu as the things on it: the clock is the Wheel, the monitor Now playing, the
 * headphones the Queue, the posters Explore, the keyboard Search, the case the Library,
 * the pothos Liked, the H2 lying on the desk Settings. A floor lamp just out of frame on
 * the right lights it after dark; by day a patch of sun from the window on the left
 * crosses the wall. And Bubloo, living there: his day is further down.
 *
 * The still desk is drawn in cells (160 x 106) into dio_px, each cell with the thing it
 * belongs to (dio_id, to outline the picked one) and whether it gives light (dio_em); then
 * lit and put on screen. Everything that moves -- Bubloo, the clock's hands, the plants,
 * the steam off the mug, the monitor's bars, a moth at the lamp, dust in the sun -- is
 * drawn over a copy of that, 12 times a second, between full frames. Part of app.c,
 * after th_room.h (Bubloo's sprites and colours are Room's). */

#define DW 160
#define DH 106
static px16 dio_px[DH][DW];
static uint8_t dio_id[DH][DW], dio_em[DH][DW];
enum { DO_NONE, DO_WHEEL, DO_NOW, DO_QUEUE, DO_EXPLORE, DO_SEARCH, DO_LIBRARY, DO_LIKED, DO_SETTINGS,
       DO_RACK0 };                      /* + k: the Bluetooth board's card k */
static int dio_emit;                    /* what dp() draws now gives its own light */
static int dio_screen_on = 1;
static int dio_buds = -1;               /* the earbuds' battery for the case's light, -1 = dark */
static uint8_t dio_wl[DH][DW];          /* bare wall, where the song's light falls (dio_vibe) */
static int dio_walling;                 /* what dp() draws now is the bare wall */
static int dio_plain;                   /* preview renders (app_set_plain_scene): no figures, posters blank */
static int dio_rack_n;                  /* the Bluetooth board: how many cards, and each one's RK_ state */
static uint8_t dio_rack_st[RACK_MAX];
void app_set_plain_scene(app *a, int on) { (void)a; dio_plain = on; }

static void dp(int x, int y, px16 c, int id)
{
    if (x < 0 || x >= DW || y < 0 || y >= DH) return;
    dio_px[y][x] = c;
    dio_id[y][x] = (uint8_t)id;
    dio_em[y][x] = (uint8_t)dio_emit;
    dio_wl[y][x] = (uint8_t)dio_walling;
}
static void drect(int a, int b, int c, int d, px16 col, int id)
{
    for (int y = b; y < d; y++) for (int x = a; x < c; x++) dp(x, y, col, id);
}
static void ddisc(float cx, float cy, float r, px16 col, int id)
{
    for (int y = (int)(cy - r) - 1; y <= (int)(cy + r) + 1; y++)
        for (int x = (int)(cx - r) - 1; x <= (int)(cx + r) + 1; x++)
            if ((x + .5f - cx) * (x + .5f - cx) + (y + .5f - cy) * (y + .5f - cy) <= r * r) dp(x, y, col, id);
}
static void dline(float x0, float y0, float x1, float y1, px16 col, int id)
{
    int n = (int)(fabsf(x1 - x0) > fabsf(y1 - y0) ? fabsf(x1 - x0) : fabsf(y1 - y0)) + 1;
    for (int i = 0; i <= n; i++) dp((int)floorf(x0 + (x1 - x0) * i / n + .5f), (int)floorf(y0 + (y1 - y0) * i / n + .5f), col, id);
}
/* a little picture from a map of cells: '.' = nothing, else the colour from the key */
static void dmap(int x0, int y0, const char *const *rows, int n, const char *keys, const px16 *cols, int id)
{
    for (int r = 0; r < n; r++)
        for (int q = 0; rows[r][q]; q++) {
            const char *k = strchr(keys, rows[r][q]);
            if (k && rows[r][q] != '.') dp(x0 + q, y0 + r, cols[k - keys], id);
        }
}
static float dmod(float a, float b) { return a - b * floorf(a / b); }
/* the device's libm has no fminf, fmaxf, atan2f */
static float dmin(float a, float b) { return a < b ? a : b; }
static float dmax(float a, float b) { return a > b ? a : b; }
static float datan2(float y, float x)                  /* to about 0.005 rad */
{
    float ax = fabsf(x), ay = fabsf(y), mx = ax > ay ? ax : ay, mn = ax > ay ? ay : ax;
    if (mx == 0) return 0;
    float u = mn / mx, s = u * u, r = ((-.0464964749f * s + .15931422f) * s - .327622764f) * s * u + u;
    if (ay > ax) r = 1.57079637f - r;
    if (x < 0) r = 3.14159274f - r;
    return y < 0 ? -r : r;
}

#define H(v) C565(((v) >> 16) & 255, ((v) >> 8) & 255, (v) & 255)

/* ------------------------------------------------------------------ the light */
static struct {
    int k;                              /* night, 0..256 */
    int sun;                            /* daylight through the window, 0..256 */
    float sx;                           /* where the patch of sun is (its left edge at row 6) */
    int lamp, screen;                   /* the lamp lit, the monitor's glow, 0..256 */
    int close;                          /* a close-up (th_dio_close.h): only the room's light and the lamp */
} dl;

static float dio_hour(void)
{
    int h, m;
    plat_clock(&h, &m);
    return h + m / 60.0f;
}

static void dio_lights(int playing)
{
    float hr = dio_hour(), across;
    dl.k = rp_k;
    float day = app_daylight(hr, &across);           /* sunrise to sunset, for today's date */
    dl.sun = (int)(day * (256 - dl.k));
    dl.sx = -30 + across * 150;                      /* left in the morning, right by evening */
    dl.lamp = dl.k > 96 ? 256 : dl.k * 8 / 3;
    dl.screen = playing ? 256 : 160;
    dl.close = 0;
}

/* in the patch of sun on the wall (the window's four panes)? */
static int dio_sunny(int x, int y)
{
    if (dl.sun <= 0 || y < 6 || y >= 84) return 0;
    float u = x - dl.sx - (y - 6) * .55f;
    return u >= 0 && u < 40 && !(u >= 19 && u < 21) && !(y >= 42 && y < 44);
}

/* a cell's colour under the room's light: dim and cool after dark, the lamp's warm wash
 * from the right, the monitor's glow, the light bar's; the sun by day; darker towards the
 * corners. In steps, dithered, like the rest */
static px16 dio_lit(px16 c, int x, int y)
{
    int k = dl.k;
    int r = 256 - (176 * k >> 8), g = 256 - (166 * k >> 8), b = 256 - (120 * k >> 8);
    if (dl.sun > 0 && !dl.close && dio_sunny(x, y)) { r += 52 * dl.sun >> 8; g += 36 * dl.sun >> 8; b += 6 * dl.sun >> 8; }
    if (dl.lamp > 0) {
        int dx = x - 158, dy = (y - 20) * 3 / 4, d2 = dx * dx + dy * dy, R2 = 92 * 92;
        if (d2 < R2) {
            int f = (R2 - d2) * 256 / R2;
            f = (f * f >> 8) * dl.lamp >> 8;
            r += 210 * f >> 8; g += 150 * f >> 8; b += 70 * f >> 8;
        }
    }
    if (k > 0 && !dl.close) {
        int dx = x - 80, dy = y - 70, d2 = dx * dx + dy * dy * 2, R2 = 46 * 46;
        if (d2 < R2) {
            int f = (R2 - d2) * 256 / R2;
            f = (f * f >> 8) * k >> 8;
            f = f * dl.screen >> 8;
            r += 70 * f >> 8; g += 100 * f >> 8; b += 150 * f >> 8;
        }
        if (x >= 20 && x < 140 && y >= 30 && y < 46) {                 /* under the shelf's light bar */
            int f = (46 - y) * 18 * k >> 8;
            r += f; g += f * 3 / 4; b += f / 3;
        }
    }
    int ex = abs(2 * x - 159) * 256 / 159, ey = abs(2 * y - 100) * 256 / 100, e = ex > ey ? ex : ey;
    if (e > 150) { int v = (e - 150) * 70 >> 8; r -= r * v >> 8; g -= g * v >> 8; b -= b * v >> 8; }   /* vignette */
    int dth = ((x & 1) << 1 | ((x ^ y) & 1)) * 4;                       /* 2x2 dither */
    r = (r + dth) & ~15; g = (g + dth) & ~15; b = (b + dth) & ~15;
    int cr = (c >> 11) * r >> 8, cg = ((c >> 5) & 63) * g >> 8, cb = (c & 31) * b >> 8;
    return (px16)((cr > 31 ? 31 : cr) << 11 | (cg > 63 ? 63 : cg) << 5 | (cb > 31 ? 31 : cb));
}

/* a cell of something that moves, lit like the room */
static void dio_pt(gfx *g, int x, int y, px16 c) { if (y < DH && y >= 0) ck_point(g, x, y, dio_lit(c, x, y)); }

/* ------------------------------------------------------------------ the still desk */
static const px16 DC_WALL = H(0xd0bc9e), DC_WALL2 = H(0xc8b496), DC_BLACK = H(0x232226), DC_BLACK2 = H(0x343338),
                  DC_WHITE = H(0xf3f2ee), DC_WHITE2 = H(0xd9d8d2), DC_RED = H(0xc8322a), DC_RED2 = H(0x962220),
                  DC_NAVY = H(0x29304d), DC_SCREEN = H(0x1f2636), DC_UNDER = H(0x1c1410);

static void dio_wall(void)
{
    dio_walling = 1;
    for (int y = 0; y < 88; y++)
        for (int x = 0; x < DW; x++) dp(x, y, (pet_hash((uint32_t)(x * 131 + y * 977)) % 19) == 0 ? DC_WALL2 : DC_WALL, DO_NONE);
    dio_walling = 0;
    /* the corner of a diploma, top left */
    drect(0, 2, 12, 22, DC_BLACK2, DO_NONE);
    drect(0, 3, 11, 21, H(0x5a3a2a), DO_NONE);
    drect(0, 4, 10, 20, DC_WHITE, DO_NONE);
    for (int y = 7; y < 17; y += 2) drect(0, y, 7, y + 1, DC_WHITE2, DO_NONE);
}

#include "th_dio_shelf.h"

/* the shelf and what's on it; the clock is the Wheel, the pothos Liked */
static void dio_shelf(void)
{
    dio_shelf_board();
    dio_emit = dl.k > 96;
    drect(22, 29, 139, 30, dl.k > 96 ? H(0xfff0c8) : RP_DAY.silver, DO_NONE);
    dio_emit = 0;
    dio_shelf_things();
}

/* Sekiro and Hollow Knight, under the shelf: Explore */
/* a poster from posters.h (the photo of the wall, firmware/tools/gen_posters.py) */
static void dposter(int x0, int y0, const char *map, int stride, int w, int h, const px16 *pal, int id)
{
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++) {
            char c = map[y * stride + x];
            dp(x0 + x, y0 + y, pal[c <= '9' ? c - '0' : c - 'a' + 10], id);
        }
}

/* under the strip the monitor hides the print, as the real one does; what peeks out at its
 * sides carries the paint on down: each column's last colours brushed downwards (a stroke
 * every few cells, wandering a cell), settling into the print's ground towards its foot */
static void dposter_rest(int x0, int y0, const char *map, int stride, int w, int h, int y1,
                         const px16 *pal, px16 ground, int id)
{
    for (int y = y0 + h; y < y1; y++)
        for (int x = 0; x < w; x++) {
            uint32_t r = pet_hash((uint32_t)((x0 + x) * 73 + (y / 3) * 151)), q = pet_hash((uint32_t)((x0 + x) * 29 + y * 211));
            int sx = x + (int)(q % 3) - 1, sy = h - 1 - (int)(r % 5);
            if (sx < 0) sx = 0;
            if (sx >= w) sx = w - 1;
            char c = map[sy * stride + sx];
            int fade = (y - y0 - h) * 150 / (y1 - y0 - h);
            dp(x0 + x, y, blend565(pal[c <= '9' ? c - '0' : c - 'a' + 10], ground, fade), id);
        }
}

/* the two posters over the desk, as they are on the wall: Sekiro in ink on pale paper,
 * the Knight among the moths in indigo -- what shows over the monitor is his face and
 * blade, the Knight's mask */
static void dio_posters(void)
{
    if (dio_plain) {                                    /* preview renders: the prints' grounds only */
        drect(38, 33, 76, 76, H(0xeeeae2), DO_EXPLORE);
        drect(78, 33, 116, 76, H(0x262a4a), DO_EXPLORE);
        return;
    }
    dposter(38, 33, &PO_SK_STRIP[0][0], (int)sizeof PO_SK_STRIP[0], 38, 17, PO_SK_PAL, DO_EXPLORE);
    dposter_rest(38, 33, &PO_SK_STRIP[0][0], (int)sizeof PO_SK_STRIP[0], 38, 17, 76, PO_SK_PAL, H(0xeeeae2), DO_EXPLORE);
    dposter(78, 33, &PO_HK_STRIP[0][0], (int)sizeof PO_HK_STRIP[0], 38, 17, PO_HK_PAL, DO_EXPLORE);
    dposter_rest(78, 33, &PO_HK_STRIP[0][0], (int)sizeof PO_HK_STRIP[0], 38, 17, 76, PO_HK_PAL, H(0x262a4a), DO_EXPLORE);
}

/* the monitor (Now playing), the desk, the keyboard (Search), the H2 (Settings), the
 * headphones (Queue), the case (Library), a mug, the lamp just in the frame */
static void dio_desk(void)
{
    drect(78, 84, 83, 88, DC_BLACK2, DO_NOW);            /* its arm */
    drect(42, 50, 119, 86, DC_BLACK, DO_NOW);
    drect(42, 50, 119, 51, DC_BLACK2, DO_NOW);
    dio_emit = dio_screen_on;
    drect(44, 52, 117, 83, dio_screen_on ? DC_SCREEN : H(0x0b0c10), DO_NOW);
    dio_emit = 0;
    dp(80, 84, RM_RED_, DO_NOW);
    /* the desk: its top, its front, the dark under it, the white legs */
    drect(0, 88, DW, 89, RP_DAY.walnut_hi, DO_NONE);
    drect(0, 89, DW, 93, RP_DAY.walnut, DO_NONE);
    for (int x = 0; x < DW; x += 9) drect(x + 2, 90, x + 6, 91, RP_DAY.walnut_l, DO_NONE);
    drect(0, 93, DW, 97, RP_DAY.walnut_d, DO_NONE);
    drect(0, 96, DW, 97, H(0x2a1a12), DO_NONE);
    drect(0, 97, DW, DH, DC_UNDER, DO_NONE);
    for (int s = 0; s < 2; s++) {
        int x0 = s ? 146 : 4, x1 = x0 + 10;
        dline(x0, 97, x1, DH, H(0x4a4440), DO_NONE);       /* white, but in the shadow */
        dline(x1, 97, x0, DH, H(0x4a4440), DO_NONE);
    }
    drect(38, 88, 124, 91, H(0xa9a8a4), DO_NONE);        /* the felt mat */
    drect(38, 90, 124, 91, H(0x96958f), DO_NONE);
    for (int r = 0; r < 4; r++)                          /* the keyboard */
        for (int x = 54; x < 95; x++) {
            int key = (x - 54 + r) % 3 != 2;
            dp(x, 84 + r, !key ? H(0x8d8c86) : (x + r) % 7 < 2 ? DC_WHITE2 : DC_WHITE, DO_SEARCH);
        }
    drect(64, 87, 80, 88, H(0xe8b84a), DO_SEARCH);       /* the yellow space bar */
    drect(89, 85, 92, 87, H(0xe2732a), DO_SEARCH);       /* the orange enter */
    drect(54, 84, 56, 85, H(0x6fb6b0), DO_SEARCH);       /* the teal escape */
    drect(54, 88, 95, 90, RP_DAY.walnut_l, DO_SEARCH);   /* the walnut wrist rest */
    drect(54, 88, 95, 89, H(0x82593c), DO_SEARCH);
    drect(99, 85, 105, 90, DC_WHITE, DO_NONE);           /* the mouse */
    drect(99, 85, 105, 86, DC_WHITE2, DO_NONE);
    /* the H2, on the desk: Settings */
    drect(106, 80, 114, 90, H(0xc4c6c8), DO_SETTINGS);
    drect(106, 80, 114, 81, H(0xe2e4e6), DO_SETTINGS);
    dio_emit = 1;
    drect(107, 81, 113, 85, H(0x2b3a52), DO_SETTINGS);
    dio_emit = 0;
    ddisc(110, 87.5f, 2.2f, H(0x8f9194), DO_SETTINGS);
    dp(110, 87, H(0xc4c6c8), DO_SETTINGS);
    /* a mug */
    drect(2, 81, 11, 90, H(0x2f5a46), DO_NONE);
    drect(2, 81, 11, 82, H(0x3d7259), DO_NONE);
    drect(11, 83, 13, 88, H(0x2f5a46), DO_NONE);
    drect(11, 84, 12, 87, DC_WALL, DO_NONE);
    /* the headphones on their stand */
    drect(116, 88, 128, 90, DC_WHITE2, DO_QUEUE);
    drect(121, 66, 123, 88, DC_WHITE, DO_QUEUE);
    for (int k = 0; k <= 20; k++) {
        float q = 3.1416f * (1 + k / 20.0f);
        dp((int)lrintf(122 + cosf(q) * 7), (int)lrintf(67 + sinf(q) * 6), DC_WHITE, DO_QUEUE);
        dp((int)lrintf(122 + cosf(q) * 7), (int)lrintf(68 + sinf(q) * 6), DC_WHITE2, DO_QUEUE);
    }
    drect(113, 66, 117, 76, DC_WHITE2, DO_QUEUE);
    drect(127, 66, 131, 76, DC_WHITE2, DO_QUEUE);
    drect(114, 67, 116, 75, DC_WHITE, DO_QUEUE);
    drect(128, 67, 130, 75, DC_WHITE, DO_QUEUE);
    /* the Galaxy Buds' case, lid down, on the free end of the desk left of the keyboard: while
     * the buds are in your ears its light says how full they are -- green, amber, red */
    dio_buds_case(15, 83, dio_buds);
    /* the case: the Fractal Terra on its walnut foot (th_dio_shelf.h) */
    dio_terra(133, 56);
    /* the floor lamp's shade, just in the frame on the right */
    if (dl.lamp > 64) dio_emit = 1;
    for (int y = 4; y < 34; y++) {
        int w = 9 + (y - 4) / 8;
        for (int x = 160 - w; x < 160; x++) dp(x, y, (y - 4) % 5 == 4 ? H(0xe6e1d4) : H(0xf6f3ea), DO_NONE);
    }
    drect(150, 34, 160, 35, H(0xd8d2c2), DO_NONE);
    dio_emit = 0;
}

/* ------------------------------------------------------------------ the Bluetooth board
 * A cork board on the wall left of the monitor (bare in the photo), a card pinned on it
 * for each paired device, the pin its state: green connected, amber connecting, red not,
 * grey with the radio off, blue for the card that pairs some. Names in dio_rack_text. */
#define RACK_X0 1
#define RACK_X1 37
#define RACK_Y0 31
#define RACK_YMAX 77                     /* the desk's just under it */
static int16_t dio_rack_box[RACK_MAX][4];   /* each card (cells), set out by dio_rack_layout */
static uint8_t dio_rack_nl[RACK_MAX];       /* its name's lines */
static int dio_rack_y1;                     /* the board's foot */
static void dio_rack_card(int k, int *b) { for (int i = 0; i < 4; i++) b[i] = dio_rack_box[k][i]; }

/* each card as tall as its name (wrapped to two lines when that fits) and, for the one
 * connected or with the radio off, how it is */
static void dio_rack_layout(app *a)
{
    static const int LINE = 6;           /* cells */
    int nl[RACK_MAX], total = 0;
    for (int k = 0; k < dio_rack_n; k++) {
        char nm[48], lines[3][TEXT_LINE_MAX];
        rack_name(a, k, nm, sizeof nm);
        nl[k] = text_wrap(F(a, F_SEMI11), nm, 2 * (RACK_X1 - RACK_X0 - 2) - 8, 3, 0, lines) > 1 ? 2 : 1;
    }
    for (int pass = 0; pass < 2; pass++) {
        total = 3;
        for (int k = 0; k < dio_rack_n; k++) {
            int st = dio_rack_st[k], says = st != RK_IDLE && st != RK_PAIR;
            total += (nl[k] + says) * LINE + 5;
        }
        if (RACK_Y0 + total <= RACK_YMAX) break;
        for (int k = 0; k < dio_rack_n; k++) nl[k] = 1;          /* no room: one line each */
    }
    int y = RACK_Y0 + 3;
    for (int k = 0; k < dio_rack_n; k++) {
        int st = dio_rack_st[k], says = st != RK_IDLE && st != RK_PAIR, h = (nl[k] + says) * LINE + 2;
        dio_rack_box[k][0] = RACK_X0 + 1;
        dio_rack_box[k][2] = RACK_X1 - 1;
        dio_rack_box[k][1] = (int16_t)y;
        dio_rack_box[k][3] = (int16_t)(y + h);
        dio_rack_nl[k] = (uint8_t)nl[k];
        y += h + 3;
    }
    dio_rack_y1 = y;
}

static void dio_rack(void)
{
    static const uint32_t PIN[] = { 0xc8442c, 0x8a8a86, 0xe0a030, 0x74b14b, 0x74b14b, 0x4a7fd0 };
    if (!dio_rack_n) return;
    int y1 = dio_rack_y1;
    drect(RACK_X0 + 1, y1, RACK_X1 + 1, y1 + 1, DC_WALL2, DO_NONE);           /* its shadow */
    drect(RACK_X1, RACK_Y0 + 1, RACK_X1 + 1, y1, DC_WALL2, DO_NONE);
    drect(RACK_X0, RACK_Y0, RACK_X1, y1, H(0x5a3a26), DO_NONE);               /* the frame */
    for (int y = RACK_Y0 + 1; y < y1 - 1; y++)
        for (int x = RACK_X0 + 1; x < RACK_X1 - 1; x++) {
            uint32_t h = pet_hash((uint32_t)(x * 197 + y * 619)) % 7;
            dp(x, y, h == 0 ? H(0x9c6c40) : h == 1 ? H(0xc4955f) : H(0xb3834f), DO_NONE);
        }
    for (int k = 0; k < dio_rack_n; k++) {
        int b[4], id = DO_RACK0 + k, st = dio_rack_st[k];
        dio_rack_card(k, b);
        drect(b[0] + 1, b[1] + 1, b[2] + 1, b[3] + 1, H(0x7e5532), DO_NONE);   /* the card's shadow */
        drect(b[0], b[1], b[2], b[3], st == RK_OFF ? H(0xd9d3c6) : H(0xf4eee2), id);
        drect(b[0], b[3] - 1, b[2], b[3], H(0xe2dacb), id);
        int px = (b[0] + b[2]) / 2;                                           /* the pin */
        drect(px - 1, b[1] - 1, px + 1, b[1] + 1, H(PIN[st]), id);
        dp(px - 1, b[1] - 1, blend565(H(PIN[st]), H(0xffffff), 120), id);
    }
}

/* the cards' names and how each is, over the lit desk (screen pixels) */
static void dio_rack_text(app *a, gfx *g)
{
    static const char *const SAYS[] = { "", "off", "connecting", "connected", "playing", "" };
    for (int k = 0; k < dio_rack_n; k++) {
        int b[4], st = dio_rack_st[k];
        char nm[48], lines[2][TEXT_LINE_MAX];
        dio_rack_card(k, b);
        rack_name(a, k, nm, sizeof nm);
        int cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2, x = 2 * b[0] + 4, w = 2 * (b[2] - b[0]) - 8;
        int n = dio_rack_nl[k] > 1 ? text_wrap(F(a, F_SEMI11), nm, w, 2, 0, lines) : 0, y = 2 * b[1] + 13;
        px16 ink = dio_lit(H(0x2a2420), cx, cy);
        if (n > 1) for (int i = 0; i < n; i++, y += 12) txt(a, g, F_SEMI11, x, y, lines[i], ink, 0);
        else { txt_fit(a, g, F_SEMI11, x, y, nm, w, ink, 0); y += 12; }
        if (!SAYS[st][0]) continue;
        px16 c = st == RK_PLAYING || st == RK_ON ? H(0x3f7a2a) : st == RK_CONNECTING ? H(0xa0661a) : H(0x77706a);
        txt_fit(a, g, F_BODY10, x, y - 1, SAYS[st], w, dio_lit(c, cx, cy), 0);
    }
}

static void dio_scene(void)
{
    dio_wall();
    dio_rack();
    dio_shelf();
    dio_posters();
    dio_desk();
}

/* ------------------------------------------------------------------ Bubloo, close up
 * Room's Bubloo (th_room.h: CAT_BODY lying down, CAT_HEAD, CAT_PAWS) and, at the same
 * size, sitting, walking, curled up, from behind, mid-leap; tails are drawn, not stored */
static const char *const DB_SIT[14] = {
    "....odmmWWWWWWmmdo....", "...odmmWWWWWWWWmmdo...", "..odmmmWWWWWWWWmmmdo..", "..odmDmmWWWWWWmmDmdo..",
    ".odmmDmmWWWWWWmmDmmdo.", ".odmmmmmmWWWWmmmmmmdo.", "odbmmmmmmWWWWmmmmmmbdo", "odbmmmmmWWWWWWmmmmmbdo",
    "odbbmmmmWWwwWWmmmmbbdo", "odbbbmmWWWoWWWWmmbbbdo", "odbbbbmWWWoWWWWmbbbbdo", ".odbbbbWWWoWWWWbbbbdo.",
    ".oobbbWWWWoWWWWWbbboo.", "..ooooooooooooooooooo.",
};
static const char *const DB_WB[7] = {
    "....oooooooooooooooo.......", "..oodmDmmDmmmDmmDmmdoo.....", ".odmmmDmmmmDmmmmDmmmmdo....",
    "odmmmmmmmmmmmmmmmmmmmmmo...", "odbmmmmmmmmmmmmmmmmmmmwWo..", ".odbbbbmmmmmmmmmmmbbbwWWo..",
    "..odbbbbbbbbbbbbbbbbwWWo...",
};
static const char *const DB_WL[4][3] = {
    { "...odbo..........owWo......", "...oWWo...........oWWo.....", "..oWWo............oWWWo...." },
    { "....odbo.......owWo........", "....oWWo......oWWo.........", "....oWWWo.....oWWWo........" },
    { "..odbo.............owWo....", ".oWWo...............oWWo...", "oWWWo................oWWo.." },
    { "....odbo.......owWo........", "....oWWo......oWWo.........", "...oWWWo.....oWWWo........." },
};
static const char *const DB_CURL[12] = {
    "......o.o..ooooooooooo......", ".....ododoodmmDmmDmmmdooo...", "....odpdoddmmmDmmmDmmmmmmdo.",
    "...oddddmmmmmDmmmmmDmmmmmmdo", "..odmmmmmmmmmmmmmmmmmmmmmmmdo", "..odmoommmmmmmmmmmmmmmmmmmmdo",
    ".otmmmmmmmmmmmmmmmmmmmmmmmmdo", ".otWWnWmmmmmmmmmmmmmmmmmmmDdo", "..oWWWWddmmddDddmmddDddmmdDdo",
    "..owWWddmmmmddDddmmmmdddddo..", "...oooddDddmmddDddmmddDdoo...", ".....oooooooooooooooooooo....",
};
static const char *const DB_BACK[20] = {
    "..o..........o......", "..odo......odo......", "..oddo....oddo......", "..odddoooodddo......",
    ".odmmDmmmmDmmdo.....", ".odmmmDmmDmmmdo.....", ".odmmmmmmmmmmdo.....", "..odmmmmmmmmdo......",
    "...odmmDDmmdo.......", "..odmmDmmDmmdo......", ".odmmDmmmmDmmdo.....", ".odmmmDmmDmmmdo.....",
    "odmmmmmDDmmmmmdo....", "odmmmmmmmmmmmmdo....", "odbmmmmmmmmmmmbdo...", "odbmmmmmmmmmmmbdo...",
    "odbbmmmmmmmmmbbdo...", "odbbbmmmmmmmbbbdo...", ".odbbbbbbbbbbbdo....", "..oooooooooooooo....",
};
static const char *const DB_LEAP[8] = {
    "......oooooooooooooooooo......", "....oodmDmmDmmmDmmDmmmmoo.....", "..oodmmmmmmmmmmmmmmmmmmmmdo...",
    "oodbbbmmmmmmmmmmmmmmmmmmmwWo..", "oWWobbbbbbbbbbbbbbbbbbbbwWWWo.", "oWWo.oooooooooooooooooowWWWWo.",
    ".oo....................oWWWo..", "........................ooo...",
};
static const char *const DB_PAW[4] = { "oWWWo", "oWWWo", "oWWWo", ".ooo." };

typedef struct { int eyes, lx, ly, mouth, low; } dhead;  /* eyes 0 shut 1 sleepy 2 open; mouth 1 yawn 2 lick */

/* a piece of him at (ox, oy) inside a figure W wide whose left edge is X, top Y */
static void dsp(gfx *g, const char *const *rows, int n, int X, int Y, int W, int ox, int oy, int mir)
{
    for (int r = 0; r < n; r++)
        for (int q = 0; rows[r][q]; q++)
            if (rows[r][q] != '.') dio_pt(g, mir ? X + W - 1 - (ox + q) : X + ox + q, Y + oy + r, cat_col(rows[r][q]));
}

/* his head (Room's), its eyes and mouth worked out */
static void dhead_draw(gfx *g, int X, int Y, int W, int ox, int oy, int mir, const dhead *h)
{
    int lx = mir ? -h->lx : h->lx;
    for (int r = 0; r < 13; r++)
        for (int x = 0; CAT_HEAD[r][x]; x++) {
            char ch = CAT_HEAD[r][x];
            if (ch == 'E') {
                int right = x >= 8, c = x - (right ? 11 : 3), e = r - 6;
                int pc = lx > 0 ? 1 : lx < 0 ? 0 : !right, pr = h->ly > 0;
                if (h->eyes == 0 || h->mouth) ch = e ? 'o' : 'm';
                else if (h->eyes == 1) ch = !e ? 'o' : c == pc ? 'k' : 'e';
                else ch = c == pc && e == pr ? 'k' : 'e';
            }
            if (h->mouth == 1 && ((r == 10 && x >= 6 && x <= 9) || (r == 11 && (x == 7 || x == 8))))
                ch = r == 10 && (x == 7 || x == 8) ? 'r' : 'o';
            if (h->mouth == 2 && r == 10 && (x == 7 || x == 8)) ch = 'n';
            if (ch == '.') continue;
            dio_pt(g, mir ? X + W - 1 - (ox + x) : X + ox + x, Y + oy + r + (h->low ? 2 : 0), cat_col(ch));
        }
}

/* the tail: discs, outlined, ringed darker towards the tip */
static void dtail(gfx *g, const float *px, const float *py, const float *pr, int n)
{
    for (int pass = 0; pass < 2; pass++)
        for (int i = 0; i < n; i++) {
            float r = pr[i] + (pass ? 0 : 1);
            for (int yy = (int)(py[i] - r) - 1; yy <= (int)(py[i] + r) + 1; yy++)
                for (int xx = (int)(px[i] - r) - 1; xx <= (int)(px[i] + r) + 1; xx++) {
                    float dx = xx + .5f - px[i], dy = yy + .5f - py[i];
                    if (dx * dx + dy * dy > r * r) continue;
                    char c = !pass ? 'o' : i >= n - 2 || i % 3 == 1 ? 'D' : dx < -pr[i] * .35f ? 'm' : 'd';
                    dio_pt(g, xx, yy, cat_col(c));
                }
        }
}

static void dtail_up(gfx *g, float ax, float ay, float t, int mir, float swing)
{
    float px[11], py[11], pr[11], x = ax, y = ay;
    for (int i = 0; i < 11; i++) {
        float u = i / 10.0f, a = -0.4f - 0.95f * u + swing * sinf(t * 2.2f + u * 2);
        x += (mir ? -1 : 1) * sinf(a) * 1.7f;
        y -= cosf(a) * 1.7f;
        px[i] = x; py[i] = y; pr[i] = 2.1f + .9f * sinf(3.1416f * u);
    }
    dtail(g, px, py, pr, 11);
}

static void dtail_hang(gfx *g, float ax, float ay, float t, int mir, float sway, float curl)
{
    float px[14], py[14], pr[14], x = ax, y = ay;
    for (int i = 0; i < 14; i++) {
        float u = i / 13.0f, base = -1.3f * (i < 3 ? 1 - i / 3.0f : 0);
        float a = base + sway * sinf(t * 1.85f - 1.8f * u) * u + curl * u * u * u;
        x += (mir ? -1 : 1) * sinf(a) * 1.45f;
        y += cosf(a) * 1.45f;
        px[i] = x; py[i] = y; pr[i] = 2.1f + 1.2f * sinf(3.1416f * (u + .3f > 1 ? 1 : u + .3f));
    }
    dtail(g, px, py, pr, 14);
}

static void dtail_flat(gfx *g, float ax, float ay, float t, int mir, float swish)
{
    float px[10], py[10], pr[10], x = ax;
    for (int i = 0; i < 10; i++) {
        float u = i / 9.0f;
        x += (mir ? 1 : -1) * 1.6f;
        px[i] = x;
        py[i] = ay - (u > .6f ? (u - .6f) * 9 * (.5f + .5f * sinf(t * 2.5f) * swish) : 0);
        pr[i] = 1.7f + .8f * sinf(3.1416f * u);
    }
    dtail(g, px, py, pr, 10);
}

/* the z's of a nap */
static void dzz(gfx *g, int x, int y, float t)
{
    static const char *const Z4[4] = { "####", "..#.", ".#..", "####" }, *const Z3[3] = { "###", ".#.", "###" };
    px16 c = dl.k > 128 ? H(0xd8ccb8) : H(0x6f5d48);
    for (int k = 0; k < 3; k++) {
        float ph = dmod(t + k * .9f, 2.7f);
        if (ph > 2.2f) continue;
        int zx = x + (int)(ph * 5) + 2 * k, zy = y - (int)(ph * 4), big = ph < .9f;
        for (int r = 0; r < (big ? 4 : 3); r++)
            for (int q = 0; q < (big ? 4 : 3); q++)
                if ((big ? Z4 : Z3)[r][q] == '#') ck_point(g, zx + q, zy + r, c);
    }
}

/* ------------------------------------------------------------------ Bubloo's day
 * Where he can be (his middle and the row his feet are on), what he does there, and how
 * he gets from one place to the next: along the desk, up to the monitor or the case, or
 * off the front of the desk and out of the picture (his meals, his box, the zoomies
 * happen elsewhere -- the line under the desk says so). His day is a string of episodes
 * from midnight, picked by the hour (asleep on the warm case at night, off for breakfast,
 * at the monitor in the evening) and fed at the Bubloo clock's times; each is worked out
 * from the time alone, so the same moment always looks the same. */
enum { SP_DESK, SP_KEYS, SP_MON, SP_CASE, SP_AWAY, SP_N };
static const int16_t SP_CX[SP_N] = { 37, 74, 66, 143, 8 };
static const int16_t SP_ROW[SP_N] = { 89, 89, 49, 55, 130 };
enum { AC_LOAF, AC_NAP, AC_CURL, AC_WATCH, AC_SIT, AC_GROOM, AC_KEYS, AC_AWAY, AC_EAT, AC_ZOOM };
static const struct { uint8_t spot, act, w[4], dmin, dmax; } LIFE[] = {      /* w: night, morning, day, evening; 5 s units */
    { SP_DESK, AC_LOAF, { 0, 2, 2, 3 }, 12, 30 },  { SP_DESK, AC_CURL, { 3, 1, 3, 1 }, 24, 60 },
    { SP_DESK, AC_SIT, { 0, 2, 1, 2 }, 8, 18 },    { SP_DESK, AC_GROOM, { 1, 3, 2, 2 }, 6, 14 },
    { SP_KEYS, AC_WATCH, { 0, 1, 2, 4 }, 12, 36 }, { SP_KEYS, AC_KEYS, { 0, 1, 1, 2 }, 10, 24 },
    { SP_MON, AC_LOAF, { 1, 1, 3, 3 }, 12, 30 },   { SP_MON, AC_NAP, { 2, 1, 3, 1 }, 24, 60 },
    { SP_CASE, AC_CURL, { 5, 1, 3, 2 }, 24, 72 },  { SP_CASE, AC_LOAF, { 1, 1, 2, 2 }, 12, 30 },
    { SP_AWAY, AC_AWAY, { 1, 2, 2, 1 }, 12, 40 },  { SP_AWAY, AC_ZOOM, { 1, 0, 0, 1 }, 4, 8 },
};
#define N_LIFE ((int)(sizeof LIFE / sizeof LIFE[0]))
static const int16_t FEED[5] = { 8 * 60 + 30, 12 * 60, 15 * 60, 18 * 60, 20 * 60 + 30 };   /* minutes */

typedef struct { int spot, sx, act, from, fx, fact; float t0, dur; } dep;
typedef struct { int16_t x, y; } dpt;

/* the time of day in ms: the clock's second, running on smoothly from it */
static uint32_t life_ms(uint32_t now)
{
    static int have;
    static int64_t base;
    int h, m, s = plat_clock_sec();
    plat_clock(&h, &m);
    if (plat_clock_sec() < s) { plat_clock(&h, &m); s = 0; }      /* the minute turned over between */
    int64_t wall = ((int64_t)h * 3600 + m * 60 + s) * 1000, t = base + now;
    int64_t d = (((t - wall) % 86400000) + 86400000 + 43200000) % 86400000 - 43200000;
    if (!have || d > 1500 || d < -1500) { base = wall - now; have = 1; t = wall; }
    return (uint32_t)(((t % 86400000) + 86400000) % 86400000);
}

static dep life_at(float T)
{
    dep e = { SP_CASE, SP_CX[SP_CASE], AC_CURL, SP_CASE, SP_CX[SP_CASE], AC_CURL, 0, 86400 };
    float t = 0;
    int pa = AC_CURL, ps = SP_CASE, ate = -1;
    for (uint32_t i = 0; i < 4000; i++) {
        float hr = t / 3600;
        uint32_t h = pet_hash(i * 2654435761u ^ 0xb0b1007u);
        int mins = (int)(t / 60), spot = -1, act = 0;
        float dur = 60;
        for (int f = 0; f < 5; f++)
            if (mins >= FEED[f] - 5 && mins < FEED[f] + 20 && ate != f && pa != AC_EAT) {
                spot = SP_AWAY; act = AC_EAT; dur = 60 + (float)(h % 40); ate = f;
                break;
            }
        if (spot < 0) {
            int per = hr >= 23 || hr < 6 ? 0 : hr < 10 ? 1 : hr < 17 ? 2 : 3, tot = 0, w[N_LIFE];
            for (int k = 0; k < N_LIFE; k++) {
                w[k] = LIFE[k].w[per];
                if (LIFE[k].spot == ps && LIFE[k].act == pa) w[k] = 0;
                if (LIFE[k].spot == SP_AWAY && ps == SP_AWAY) w[k] = 0;
                tot += w[k];
            }
            int r = (int)(h % (uint32_t)tot), k = 0;
            while (r >= w[k]) r -= w[k++];
            spot = LIFE[k].spot;
            act = LIFE[k].act;
            dur = 5.0f * (LIFE[k].dmin + (int)((h >> 9) % (uint32_t)(LIFE[k].dmax - LIFE[k].dmin + 1)));
        }
        e = (dep){ spot, SP_CX[spot], act, ps, SP_CX[ps], pa, t, dur };
        if (t + dur > T) return e;
        t += dur;
        ps = spot; pa = act;
    }
    return e;
}

/* the way up to a place, from the left end of the desk */
static int dchain(int spot, dpt *o)
{
    int n = 0;
    if (spot == SP_AWAY) { o[0] = (dpt){ 8, 130 }; return 1; }
    o[n++] = (dpt){ 14, 89 };
    if (spot == SP_MON) o[n++] = (dpt){ 62, 89 };
    if (spot == SP_CASE) o[n++] = (dpt){ 112, 89 };
    o[n++] = (dpt){ SP_CX[spot], SP_ROW[spot] };
    return n;
}

/* from one place to another: back down his way there, along the desk, up the other's */
static int dpath(int a, int b, dpt *o)
{
    dpt ca[4], cb[4];
    int na = dchain(a, ca), nb = dchain(b, cb), n = 0, m = 0;
    if (a == SP_AWAY) { o[n++] = ca[0]; for (int i = 0; i < nb; i++) o[n++] = cb[i]; }
    else {
        for (int i = na - 1; i >= 1; i--) o[n++] = ca[i];
        if (b == SP_AWAY) { o[n++] = (dpt){ 14, 89 }; o[n++] = cb[0]; }
        else for (int i = 1; i < nb; i++) o[n++] = cb[i];
    }
    for (int i = 0; i < n; i++) {
        if (m >= 1 && o[m - 1].x == o[i].x && o[m - 1].y == o[i].y) continue;
        if (m >= 2 && o[m - 1].y == o[i].y && o[m - 2].y == o[i].y) { o[m - 1] = o[i]; continue; }
        o[m++] = o[i];
    }
    return m;
}

static float dseg(dpt p, dpt q)
{
    return p.y == q.y ? fabsf((float)(q.x - p.x)) / 18.0f : 0.4f + abs(q.y - p.y) * 0.006f;
}

static float dtravel(const dep *e, dpt *path, int *n)
{
    *n = e->from == e->spot ? 1 : dpath(e->from, e->spot, path);
    if (*n <= 1) return 0;
    float D = (e->fact == AC_NAP || e->fact == AC_CURL) ? 1.4f : 0;
    for (int i = 0; i + 1 < *n; i++) D += dseg(path[i], path[i + 1]);
    return D;
}

/* what he looks like this moment */
enum { DP_NONE, DP_LOAF, DP_SIT, DP_WALK, DP_CURL, DP_GROOM, DP_BACK, DP_LEAP };
typedef struct {
    int pose, mir, frame, y, tail, zz, inhale;           /* tail: 1 hanging, 2 lying along */
    float x, t, swing, curl;
    dhead h;
} dpose;

static void dio_cat_draw(gfx *g, const dpose *p)
{
    int X, W, by = p->y, mir = p->mir;
    float t = p->t;
    switch (p->pose) {
    case DP_LOAF: {
        W = CAT_W; X = (int)lrintf(p->x) - W / 2;
        int top = by - 10;
        if (p->tail == 1) dtail_hang(g, mir ? X + W - 3.0f : X + 2.0f, top + 8.5f, t, mir, p->swing, p->curl);
        else dtail_flat(g, mir ? X + W - 4.0f : X + 3.0f, by - 1.0f, t, mir, p->swing);
        for (int r = 0; r < 11; r++) {
            dsp(g, CAT_BODY + r, 1, X, top + r - (p->inhale && r <= 4 ? 1 : 0), W, 0, 0, mir);
            if (p->inhale && r == 4) dsp(g, CAT_BODY + r, 1, X, top + 4, W, 0, 0, mir);
        }
        dsp(g, CAT_PAWS, 2, X, top + 9, W, 19, 0, mir);
        dhead_draw(g, X, top - 5, W, CAT_HX, 0, mir, &p->h);
        if (p->zz) dzz(g, mir ? X - 4 : X + W, top - 4, t);
        break;
    }
    case DP_SIT: case DP_GROOM:
        W = 22; X = (int)lrintf(p->x) - W / 2;
        dtail_up(g, mir ? X + W - 3.0f : X + 2.0f, by - 1.0f, t, mir, p->pose == DP_GROOM ? .1f : p->swing);
        dsp(g, DB_SIT, 14, X, by - 13, W, 0, 0, mir);
        dhead_draw(g, X, by - 23 + (p->pose == DP_GROOM ? 1 + (p->frame & 1) : 0), W, 3, 0, mir, &p->h);
        if (p->pose == DP_GROOM) dsp(g, DB_PAW, 4, X, by - 14 + (p->frame & 1), W, 12, 0, mir);
        break;
    case DP_WALK:
        W = 30; X = (int)lrintf(p->x) - W / 2;
        dtail_up(g, mir ? X + W - 4.0f : X + 3.0f, by - 7.0f, t * 3, mir, .25f);
        dsp(g, DB_WB, 7, X, by - 9, W, 0, 0, mir);
        dsp(g, DB_WL[p->frame & 3], 3, X, by - 2, W, 0, 0, mir);
        dhead_draw(g, X, by - 18, W, 14, 0, mir, &p->h);
        break;
    case DP_CURL:
        W = 29; X = (int)lrintf(p->x) - W / 2;
        if (p->inhale) dsp(g, DB_CURL + 1, 1, X, by - 12, W, 0, 0, mir);
        dsp(g, DB_CURL, 12, X, by - 11, W, 0, 0, mir);
        if (p->zz) dzz(g, mir ? X + W : X - 4, by - 15, t);
        break;
    case DP_BACK:
        W = 20; X = (int)lrintf(p->x) - W / 2;
        dtail_up(g, X + 14.0f, by - 1.0f, t, 1, p->swing);
        dsp(g, DB_BACK, 8, X + p->frame, by - 19, W, 0, 0, 0);
        dsp(g, DB_BACK + 8, 12, X, by - 11, W, 0, 0, 0);
        break;
    case DP_LEAP:
        W = 33; X = (int)lrintf(p->x) - W / 2;
        dtail_up(g, mir ? X + W - 3.0f : X + 2.0f, by - 3.0f, t, mir, .1f);
        dsp(g, DB_LEAP, 8, X, by - 7, W, 0, 0, mir);
        dhead_draw(g, X, by - 15, W, 17, 0, mir, &p->h);
        break;
    default:
        break;
    }
}

/* the picked thing's tag, where he looks when you're choosing */
static const int16_t DIO_TAG[N_MENU][2] = { { 96, 4 }, { 80, 50 }, { 122, 60 }, { 56, 33 }, { 74, 83 },
                                            { 143, 55 }, { 138, 12 }, { 110, 79 } };

/* where he is and what he's doing at time T (s of the day); lookx: where to look (cells) */
static void life_pose(dpose *p, float T, int playing, int poked, int lookx, float bass)
{
    dep e = life_at(T);
    memset(p, 0, sizeof *p);
    p->t = T;
    p->h.eyes = 2;
    p->pose = DP_NONE;
    float u = T - e.t0;
    dpt path[10];
    int n;
    float D = dtravel(&e, path, &n), wake = (e.fact == AC_NAP || e.fact == AC_CURL) && n > 1 ? 1.4f : 0;
    if (n > 1 && u < D) {                                 /* on his way */
        if (u < wake) {                                   /* up from a nap: a yawn first */
            if (e.from == SP_AWAY) return;
            p->pose = DP_SIT; p->x = path[0].x; p->y = path[0].y; p->h.mouth = u < 1.1f;
            p->mir = path[1].x < path[0].x;
            return;
        }
        float s = u - wake;
        for (int i = 0; i + 1 < n; i++) {
            float d = dseg(path[i], path[i + 1]);
            if (s > d && i + 2 < n) { s -= d; continue; }
            float f = d > 0 ? s / d : 1;
            if (f > 1) f = 1;
            dpt a = path[i], b = path[i + 1];
            p->x = a.x + (b.x - a.x) * f;
            p->mir = b.x < a.x || (b.x == a.x && a.x > 80);
            if (a.y == b.y) { p->pose = DP_WALK; p->y = a.y; p->frame = (int)(T / .11f); }
            else {
                float arc = (8 + abs(b.y - a.y) * .25f) * 4 * f * (1 - f);
                p->pose = DP_LEAP; p->y = (int)lrintf(a.y + (b.y - a.y) * f - arc);
            }
            return;
        }
    }
    if (e.spot == SP_AWAY) return;                        /* out of the picture */
    float v = u - D;
    uint32_t salt = (uint32_t)e.t0, tm = (uint32_t)(T * 1000);
    p->x = e.sx;
    p->y = SP_ROW[e.spot];
    p->mir = e.spot == SP_CASE || e.spot == SP_MON;
    if (pet_event(tm, 4300, 160, salt) >= 0) p->h.eyes = 0;
    if (poked) p->h.lx = lookx > p->x + 8 ? 1 : lookx < p->x - 8 ? -1 : 0;
    else if (pet_event(tm, 7300, 1300, salt + 5) >= 0) p->h.lx = pet_hash((uint32_t)T / 7) & 1 ? 1 : -1;
    p->swing = .18f + (playing ? .3f * bass : 0);
    p->inhale = dmod(T, 2.8f) < 1.2f;
    int cu = pet_event(tm, 8900, 600, salt + 4);
    if (cu >= 0) p->curl = .9f * sinf(3.1416f * cu / 600.0f);
    int ledge = e.spot == SP_CASE;
    switch (e.act) {
    case AC_LOAF: case AC_KEYS:
        p->pose = DP_LOAF; p->tail = ledge ? 1 : 2;
        if (playing && !poked && pet_event(tm, 9000, 4200, salt + 3) >= 0) p->h.eyes = 1;
        break;
    case AC_NAP:
        p->pose = DP_LOAF; p->tail = ledge ? 1 : 2;
        p->h.eyes = poked ? 1 : 0; p->h.low = !poked; p->zz = !poked; p->swing = .05f;
        p->inhale = dmod(T, 3.6f) < 1.5f;
        break;
    case AC_CURL:
        p->pose = DP_CURL; p->zz = 1; p->inhale = dmod(T, 3.6f) < 1.5f;
        break;
    case AC_WATCH:
        p->pose = DP_BACK;
        p->frame = pet_event(tm, 5200, 1400, salt + 9) >= 0 ? (pet_hash((uint32_t)T / 5) & 1 ? 1 : -1) : 0;
        p->swing = .2f + (playing ? .35f + .4f * bass : 0);
        break;
    case AC_SIT:
        p->pose = DP_SIT;
        if (pet_event(tm, 23000, 900, salt + 11) >= 0) p->h.mouth = 1;
        break;
    case AC_GROOM: {
        float c = dmod(v, 4.5f);
        p->pose = c < 3 ? DP_GROOM : DP_SIT;
        p->frame = (int)(c / .22f);
        if (c < 3) { p->h.eyes = 0; p->h.mouth = p->frame & 1 ? 2 : 0; }
        break;
    }
    default:
        break;
    }
}

/* what he's up to, in a line; returns the seconds until he moves on */
static float dio_status(float T, char *out, size_t n)
{
    static const char *const AT[SP_N] = { "on the desk", "on your keyboard", "on top of the monitor", "on the warm case", "" };
    static const char *const TO[SP_N] = { "the desk", "your keyboard", "the top of the monitor", "the warm case", "somewhere" };
    static const char *const MEAL[5] = { "breakfast", "lunch", "snack", "dinner", "supper" };
    dep e = life_at(T);
    dpt path[10];
    int np;
    float D = dtravel(&e, path, &np), left = e.t0 + e.dur - T;
    if (np > 1 && T - e.t0 < D) {
        if (e.spot == SP_AWAY) snprintf(out, n, "Bubloo hops down and wanders off.");
        else if (e.from == SP_AWAY) snprintf(out, n, "Bubloo's back. Up he comes.");
        else snprintf(out, n, "Bubloo is heading for %s.", TO[e.spot]);
        return left;
    }
    int meal = 0;
    for (int f = 0; f < 5; f++) if (e.t0 / 60 >= FEED[f] - 5 && e.t0 / 60 < FEED[f] + 20) meal = f;
    const char *at = AT[e.spot];
    switch (e.act) {
    case AC_LOAF: snprintf(out, n, "Bubloo is loafing %s.", at); break;
    case AC_NAP: snprintf(out, n, "Bubloo is napping %s.", at); break;
    case AC_CURL: snprintf(out, n, "Bubloo is curled up asleep %s.", at); break;
    case AC_WATCH: snprintf(out, n, "Bubloo is watching your screen."); break;
    case AC_SIT: snprintf(out, n, "Bubloo is sitting %s, looking at you.", at); break;
    case AC_GROOM: snprintf(out, n, "Bubloo is washing his paws."); break;
    case AC_KEYS: snprintf(out, n, "Bubloo is lying on your keyboard. Of course he is."); break;
    case AC_EAT: snprintf(out, n, "Bubloo is off having his %s.", MEAL[meal]); break;
    case AC_ZOOM: snprintf(out, n, "Bubloo has the zoomies. You can hear him."); break;
    default: snprintf(out, n, "Bubloo is off somewhere. Probably his box."); break;
    }
    return left;
}

/* ------------------------------------------------------------------ what moves */
/* a stroke at full resolution (not on the grid), its edges blended: the clock's hands */
static void dio_hand(gfx *g, float cx, float cy, float ang, float len, float back, float w, px16 c)
{
    float dx = sinf(ang), dy = -cosf(ang);
    float ax = cx - dx * back, ay = cy - dy * back, vx = dx * (len + back), vy = dy * (len + back), L2 = vx * vx + vy * vy;
    int x0 = (int)floorf(dmin(ax, ax + vx) - w), x1 = (int)ceilf(dmax(ax, ax + vx) + w);
    int y0 = (int)floorf(dmin(ay, ay + vy) - w), y1 = (int)ceilf(dmax(ay, ay + vy) + w);
    for (int y = y0 < 0 ? 0 : y0; y <= y1 && y < BAR_Y; y++)
        for (int x = x0 < 0 ? 0 : x0; x <= x1 && x < LCD_W; x++) {
            float px = x + .5f - ax, py = y + .5f - ay, u = L2 > 0 ? (px * vx + py * vy) / L2 : 0;
            u = u < 0 ? 0 : u > 1 ? 1 : u;
            float ex = px - vx * u, ey = py - vy * u, cov = w / 2 + .5f - sqrtf(ex * ex + ey * ey);
            if (cov <= 0) continue;
            px16 *q = g->px + y * g->stride + x;
            *q = blend565(*q, c, cov >= 1 ? 256 : (int)(cov * 256));
        }
}

/* the shelf clock, as the real one: twelve marks, a short heavy hour hand, a long minute
 * hand, a thin red second hand that ticks; T = the time of day, s */
static void dio_clock_hands(gfx *g, float T)
{
    const float cx = DC_CLOCK_X * 2, cy = DC_CLOCK_Y * 2;  /* its middle, in pixels */
    const int qx = (int)DC_CLOCK_X, qy = (int)DC_CLOCK_Y;
    px16 ink = dio_lit(H(0x26262a), qx, qy), mark = dio_lit(H(0x8a8984), qx, qy), red = dio_lit(DC_RED, qx, qy);
    for (int i = 0; i < 12; i++) {
        float a = i * .5236f, r0 = i % 3 ? 10.6f : 9.2f;
        dio_hand(g, cx + sinf(a) * r0, cy - cosf(a) * r0, a, 12.0f - r0, 0, i % 3 ? .9f : 1.5f, i % 3 ? mark : ink);
    }
    float sec = floorf(dmod(T, 60)), m = dmod(T / 60, 60) / 60 * 6.2832f, h = dmod(T / 3600, 12) / 12 * 6.2832f;
    dio_hand(g, cx, cy, h, 6.4f, 1.6f, 2.3f, ink);
    dio_hand(g, cx, cy, m, 10.2f, 1.6f, 1.4f, ink);
    dio_hand(g, cx, cy, sec / 60 * 6.2832f, 10.6f, 2.8f, .8f, red);
    dio_hand(g, cx, cy, 0, .1f, .1f, 2.2f, red);
}

/* a cell of a plant that grows behind what stands on the shelf: only where the bare wall is */
static void dio_pt_behind(gfx *g, int x, int y, px16 c)
{
    if (x >= 0 && x < DW && y >= 0 && y < DH && dio_wl[y][x]) dio_pt(g, x, y, c);
}

/* one leaf (rows of L light, l mid, D dark, i/I the ivy's), behind the shelf's things or in
 * front; outline: the picked thing's cream ring round it instead */
static void dio_leaf(gfx *g, int x, int y, const char *const *rows, int nr, int behind, int outline)
{
    for (int r = 0; r < nr; r++)
        for (int c = 0; rows[r][c]; c++) {
            char ch = rows[r][c];
            if (ch == '.') continue;
            int px = x + c, py = y + r;
            if (behind && (px < 0 || px >= DW || py < 0 || py >= DH || !dio_wl[py][px])) continue;
            if (outline) {
                for (int d = 0; d < 4; d++) ck_point(g, px + (d == 0) - (d == 1), py + (d == 2) - (d == 3), RP.cream);
                continue;
            }
            px16 col = ch == 'L' ? RP_DAY.leaf_l : ch == 'D' ? RP_DAY.leaf_d : ch == 'I' ? H(0x4d7a44) :
                       ch == 'i' ? H(0x34573a) : ch == 'J' ? H(0x22382a) : RP_DAY.leaf;
            dio_pt(g, px, py, col);
        }
}

/* the plants, moving a little (2026-10-18, closer to the photo: "missing some things still and
 * weird empty space"): the fern as tall and wide as the real one, arching out of its black
 * pot up to the top of the picture, behind the frame and the clock; the ivy off the middle of
 * the shelf, a clump left of the clock and two strands down over where the posters meet; the
 * pothos at the end a full bush behind the figures, three vines down past the case */
static void dio_plants(gfx *g, float t, int liked_picked)
{
    for (int k = 0; k < 17; k++) {                       /* the fern: fronds apart, so it reads as fronds */
        float u = k / 16.0f, up = sinf(3.1416f * u);
        float q = 3.1416f * (1.02f + .96f * u), L = 13 + up * 10 + (k % 3) * 1.2f, sw = sinf(t * .7f + k) * .05f;
        float cq = cosf(q + sw), sq = sinf(q + sw);
        for (int s = 1; s <= (int)L; s++) {
            float fx = 66.5f + cq * s, fy = 15.5f + sq * s + .045f * s * s * (1 - .6f * up);
            int x = (int)floorf(fx), y = (int)floorf(fy);
            dio_pt_behind(g, x, y, k % 2 ? RP_DAY.leaf_d : RP_DAY.leaf);
            if (s > 2 && s < L - 1 && s % 2 == 0) {      /* its leaflets, both sides, every other cell */
                int nx = (int)lrintf(-sq * 1.4f), ny = (int)lrintf(cq * 1.4f);
                dio_pt_behind(g, x + nx, y + ny, s % 2 ? RP_DAY.leaf_l : RP_DAY.leaf);
                dio_pt_behind(g, x - nx, y - ny, s % 2 ? RP_DAY.leaf : RP_DAY.leaf_d);
            }
        }
    }
    /* the ivy: small dark leaves in a clump on its pot, two strands down to the monitor */
    static const char *const IVY[2] = { "Ii", "iJ" };
    for (int k = 0; k < 12; k++)
        dio_leaf(g, 75 + (k * 5) % 12, 11 + (k * 7) % 8, IVY, 2, 1, 0);
    for (int k = 0; k < 4; k++)                          /* and over the pot's rim */
        dio_leaf(g, 76 + k * 3, 17 + (k & 1), IVY, 2, 0, 0);
    for (int v = 0; v < 2; v++) {
        int x0 = v ? 81 : 77, y1 = v ? 45 : 49;
        for (int k = 0, y = 25; y < y1; y++, k++) {
            float sway = sinf(t / 1.1f + k * .35f + v * 1.3f) * (k / 18.0f);
            int x = x0 + (int)lrintf(sinf(y * .3f + v * 2) * 1.2f + sway);
            dio_pt(g, x, y, H(0x2b4630));
            if (k % 3 == 1) dio_leaf(g, (k / 3) % 2 ? x + 1 : x - 2, y, IVY, 2, 0, 0);
        }
    }
    /* the pothos: a full bush behind the figures at the shelf's end, and its vines */
    static const char *const LEAF[3] = { "LLl", "LlD", ".D." };
    static const char *const BIG[4] = { ".LL.", "LLlD", "LlDD", ".DD." };
    for (int pass = liked_picked ? 0 : 1; pass < 2; pass++) {
        for (int k = 0; k < 44; k++) {
            uint32_t h = pet_hash((uint32_t)k * 2654435761u);
            float a = (h % 628) / 100.0f, r = .25f + ((h >> 10) % 75) / 100.0f;
            int lx = (int)lrintf(137 + cosf(a) * r * 12 + sinf(t * .6f + k) * .4f), ly = (int)lrintf(12 + sinf(a) * r * 9);
            if (ly > 21) ly = 21;
            if (ly < 6) ly = 6;                          /* clear of the battery's figures */
            dio_leaf(g, lx - 2, ly - 2, k % 3 ? BIG : LEAF, k % 3 ? 4 : 3, 1, !pass);
        }
        for (int v = 0; v < 3; v++) {
            int side = v == 1 ? -1 : 1, x0 = v == 0 ? 144 : v == 1 ? 137 : 147, y1 = v == 0 ? 56 : v == 1 ? 49 : 54;
            for (int k = 0, y = 22; y < y1; y++, k++) {
                float sway = sinf(t / .9f + k * .4f + v * 2) * (k / 14.0f);
                int x = x0 + (int)lrintf(sinf(y * .35f + v) * 1.4f + sway);
                if (!pass) { ck_point(g, x - 1, y, RP.cream); ck_point(g, x + 1, y, RP.cream); continue; }
                dio_pt(g, x, y, RP_DAY.leaf_d);
                if (k % 3 == 1) {
                    dio_leaf(g, side > 0 ? x + 1 : x - 3, y - 1, k % 6 == 1 ? BIG : LEAF, k % 6 == 1 ? 4 : 3, 0, 0);
                    side = -side;
                }
            }
        }
    }
}

/* steam off the mug */
static void dio_steam(gfx *g, float t)
{
    for (int j = 0; j < 4; j++) {
        float ph = dmod(t * .35f + j / 4.0f, 1);
        float cx = 6.5f + sinf(ph * 7 + j * 1.7f) * 2, cy = 79 - ph * 16;
        int a = (int)(150 * (1 - ph));
        for (int k = 0; k < 2; k++) {
            int x = (int)floorf(cx + k), y = (int)floorf(cy);
            if ((pet_hash((uint32_t)(x * 7 + y * 131 + j)) & 255) < (uint32_t)a)
                ck_point(g, x, y, blend565(dio_lit(DC_WALL, x, y), H(0xffffff), 90));
        }
    }
}

/* the monitor: the song's bars in a strip under its cover, clear of the words beside it;
 * a cursor when nothing's on */
static void dio_screen(gfx *g, float t, int playing)
{
    uint8_t bands[12];
    if (playing && plat_spectrum(bands)) {
        for (int i = 0; i < 12; i++) {
            int h = 1 + bands[i] * 3 / 256;
            for (int y = 0; y < h; y++)
                ck_point(g, 47 + i * 2, 82 - y, y > 1 ? H(0xeaa22c) : y > 0 ? H(0xc9d86a) : H(0x74b14b));
        }
    } else if (dmod(t, 1.06f) < .53f) {
        ck_point(g, 78, 80, H(0xf4eee2));
        ck_point(g, 79, 80, H(0xf4eee2));
    }
}

static void dio_bits(app *a, gfx *g, float t, uint32_t now, int playing)
{
    if (playing) {                                         /* notes off the headphones */
        float ph = dmod(t, 2.6f) / 2.2f;
        if (ph < 1) {
            static const char *const N[5] = { ".##", ".#.", ".#.", "##.", "##." };
            int nx = 124 + (int)(ph * 8), ny = 58 - (int)(ph * 14);
            for (int r = 0; r < 5; r++) for (int c = 0; c < 3; c++) if (N[r][c] == '#') dio_pt(g, nx + c, ny + r, H(0xeaa22c));
        }
    }
    int led = (int)(128 + 127 * sinf(t * 2));               /* the case's light, breathing */
    ck_point(g, 155, 83, blend565(H(0x1d3a24), H(0x6cf06c), led));
    if (dmod(t, 3.1f) < .3f) ck_point(g, 108, 82, H(0x8fd0ff));   /* the H2's screen, a blink */
    if (dl.k > 128) {                                       /* a moth at the lamp */
        int mx = (int)(150 + cosf(t * 3.1f) * 7), my = (int)(30 + sinf(t * 4.3f) * 6);
        ck_point(g, mx, my, H(0xe9e2cf));
        if ((int)(t * 12) & 1) ck_point(g, mx + 1, my, H(0xcfc6b0));
    }
    if (dl.sun > 64)                                        /* dust in the sun */
        for (int j = 0; j < 10; j++) {
            uint32_t h = pet_hash((uint32_t)j * 4111u);
            float y = 8 + dmod(t * .7f + (h >> 8) % 70, 74), x = dl.sx + 4 + (h % 34) + sinf(t * .3f + j) * 2 + (y - 6) * .55f;
            if (dio_sunny((int)x, (int)y)) ck_point(g, (int)x, (int)y, H(0xfff4d2));
        }
    if (now - a->poke_ms < 350)                              /* keys going down as you scroll */
        for (int k = 0; k < 3; k++) {
            uint32_t h = pet_hash(a->poke_ms + (uint32_t)k);
            dio_pt(g, 54 + (int)(h % 40), 84 + (int)((h >> 8) % 3), H(0x9a9890));
        }
}

/* ---- the wall in the song's light (2026-10-18; the listener: "depending on the vibe of
 * the song the whole background wall changes colour and has some cool visualizer"). A
 * coloured light behind the desk washes the bare wall. Its colour is where the song's
 * sound sits from calm to driven (brain_vibe: its cluster ranked by energy): deep blue
 * and teal for the calmest, lavender and rose between, amber, red and magenta for the
 * most driven; a song with more energy lights it brighter. How it moves comes from the
 * same: a calm song, a slow aurora drifting over it at its tempo; a middling one, light
 * rising from behind the desk with the music (the spectrum's twelve bands); a driven one,
 * that and the wall flaring on the bass, rings of light off the monitor on each kick.
 * Paused, the colour stays, dimmer and still. Only the bare wall's cells change (dio_wl),
 * every frame from the kept frame's lit wall, so the shelf, the posters and Bubloo stay
 * as they are. Off with Settings' visualizer. */
static const uint32_t VIBE_RGB[16] = {
    0x3a4fd8, 0x3f7fe0, 0x2fa8c8, 0x36c0a8, 0x5fcf8a, 0x8a7fe0, 0xa46ad8, 0xc766c8,
    0xe46aa8, 0xf07a80, 0xf59a5a, 0xf2b64a, 0xf0d040, 0xf06a3a, 0xe03a4a, 0xe02a8a,
};

static inline px16 vibe_mul(px16 c, int lr, int lg, int lb)      /* the wall's colour under that light */
{
    int r = (c >> 11) * lr >> 8, g = ((c >> 5) & 63) * lg >> 8, b = (c & 31) * lb >> 8;
    return (px16)((r << 11) | (g << 5) | b);
}

static const char *const VIBE_NAME[16] = {
    "deep blue", "azure", "sea blue", "teal", "mint", "lavender", "violet", "orchid",
    "pink", "coral", "peach", "amber", "gold", "orange", "crimson", "magenta",
};

/* the wall's colour for a song (0..15) and its energy 0..1: its sound's place from calm to
 * driven, else its energy, else a colour of its own */
static int vibe_rank(uint32_t idx, float *energy)
{
    int e = -1, bpm10 = 0, rank = -1;
    brain_vibe(idx, &e, &bpm10, &rank);
    if (rank < 0 && e >= 0) rank = e * 15 / 254;
    if (rank < 0) rank = (int)(pet_hash(idx) % 16);
    if (energy) *energy = e >= 0 ? e / 254.0f : rank / 15.0f;
    return rank & 15;
}

/* the cover's two colours, for the wall (2026-10-18; the listener picked dusk and asked "are
 * you using the album photo for its colour scheme?"): of its 32 px thumbnail, the most of it
 * that has colour -- not near-grey, near-black or near-white, the more saturated the more it
 * counts -- and the most of the rest that's another colour (else a deeper shade of the
 * first). 0 when the cover has none to speak of, or there's no cover */
static int cover_tones(app *a, uint32_t idx, int rgb[2][3])
{
    static px16 px[32 * 32];
    static uint32_t w[512], sr[512], sg[512], sbl[512];
    if (lib_art(a->L, idx, ART_S, px) != 0) return 0;
    memset(w, 0, sizeof w);
    memset(sr, 0, sizeof sr);
    memset(sg, 0, sizeof sg);
    memset(sbl, 0, sizeof sbl);
    uint32_t total = 0;
    for (int i = 0; i < 32 * 32; i++) {
        int r = (px[i] >> 11) << 3, g = ((px[i] >> 5) & 63) << 2, b = (px[i] & 31) << 3;
        int mx = r > g ? (r > b ? r : b) : (g > b ? g : b), mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
        if (mx < 48 || mn > 225 || mx - mn < 32) continue;
        int bin = (r >> 5) << 6 | (g >> 5) << 3 | (b >> 5);
        uint32_t k = 1 + (uint32_t)(mx - mn) / 24;
        w[bin] += k;
        sr[bin] += (uint32_t)r * k;
        sg[bin] += (uint32_t)g * k;
        sbl[bin] += (uint32_t)b * k;
        total += k;
    }
    if (total < 80) return 0;
    int b1 = 0, b2 = -1;
    for (int i = 1; i < 512; i++) if (w[i] > w[b1]) b1 = i;
    rgb[0][0] = (int)(sr[b1] / w[b1]);
    rgb[0][1] = (int)(sg[b1] / w[b1]);
    rgb[0][2] = (int)(sbl[b1] / w[b1]);
    for (int i = 0; i < 512; i++) {
        if (!w[i] || i == b1) continue;
        int d = abs((int)(sr[i] / w[i]) - rgb[0][0]) + abs((int)(sg[i] / w[i]) - rgb[0][1]) +
                abs((int)(sbl[i] / w[i]) - rgb[0][2]);
        if (d > 110 && (b2 < 0 || w[i] > w[b2])) b2 = i;
    }
    for (int c = 0; c < 3; c++)
        rgb[1][c] = b2 >= 0 && w[b2] * 8 >= w[b1] ? (int)((c == 0 ? sr : c == 1 ? sg : sbl)[b2] / w[b2])
                                                  : rgb[0][c] * 3 / 5;
    return 1;
}

/* the wall's two tones for a song: its cover's (1), else from its sound (0) */
static int wall_tones(app *a, uint32_t idx, int rgb[2][3])
{
    static uint32_t c_idx = 0xFFFFFFFFu;
    static int c_ok, c_rgb[2][3];
    if (idx != c_idx) { c_idx = idx; c_ok = cover_tones(a, idx, c_rgb); }
    if (c_ok) { memcpy(rgb, c_rgb, sizeof c_rgb); return 1; }
    int rank = vibe_rank(idx, NULL);
    for (int k = 0; k < 2; k++) {
        uint32_t hx = VIBE_RGB[(rank + 3 * k) & 15];
        rgb[k][0] = (int)(hx >> 16); rgb[k][1] = (int)((hx >> 8) & 255); rgb[k][2] = (int)(hx & 255);
    }
    return 0;
}

/* which way the wall carries the song (drafts, 2026-10-18; the listener picks one):
 * 0 bars (light rising from behind the desk), 1 the monitor's glow (a halo on the wall round
 * it, swelling with the bass), 2 the shelf's strip (its light bar in the song's colour,
 * washing the wall under it, pulsing), 3 ripples (rings off the monitor on each kick),
 * 4 light dots (soft spots drifting over the wall, each with a part of the music, in two
 * tones), 5 dusk (the wall from the song's colour at the top to a second at the foot,
 * breathing, no beat) */
static int dio_wall_style = 5;                 /* the listener's pick: dusk, in the cover's colours */
void app_set_wall_style(app *a, int s) { (void)a; dio_wall_style = s < 0 ? 0 : s > 5 ? 5 : s; }

static void vibe_lift(int r, int g, int b, int *lr, int *lg, int *lb, int *gl)
{
    int lum = (r * 77 + g * 150 + b * 29) >> 8, up8 = 64 + (255 - lum) * 100 / 255;   /* a dark light lifts more */
    *lr = r; *lg = g; *lb = b;
    *gl = C565(r + ((255 - r) * up8 >> 8), g + ((255 - g) * up8 >> 8), b + ((255 - b) * up8 >> 8));
}

static void dio_vibe(app *a, gfx *g, uint32_t now, int playing)
{
    static float cr = 255, cg = 230, cb = 200, cr2 = 255, cg2 = 230, cb2 = 200, ca, lvl, sb[12], pk = .2f, bavg, benv;
    static uint32_t last, ring0[8];
    static int nr;
    const int ws = dio_wall_style;
    float dt = last && now > last ? (now - last) / 1000.0f : 0, t = now / 1000.0f;
    if (dt > .5f) dt = .5f;
    last = now;
    int on = a->viz_on && a->cur_valid, bpm10 = on ? brain_bpm10(a->cur) : 0;
    float en = 0;
    int rank = on ? vibe_rank(a->cur, &en) : 0;
    /* 10-18: "good but a bit too much" (Melatonin, energy 188 of 254, had the full show): on
     * this library a quarter of the songs sat past .68, so the aurora below the median, the
     * flares and rings only for the top tenth, and the light softer all round */
    int style = en < .42f ? 0 : en < .87f ? 1 : 2;
    float k = 1 - expf(-dt * 2.5f);                    /* a new song's colour comes up in ~half a second */
    int tones[2][3];
    if (on && ws == 5) wall_tones(a, a->cur, tones);   /* dusk: the cover's two colours */
    for (int c2 = 0; c2 < 2; c2++) {                   /* its colour, and a second tone three along */
        uint32_t hx = VIBE_RGB[(rank + 3 * c2) & 15];
        float tr = (float)(hx >> 16), tg = (float)((hx >> 8) & 255), tb = (float)(hx & 255);
        if (on && ws == 5) {                           /* bright enough to read as light, its hue kept */
            int m = tones[c2][0] > tones[c2][1] ? tones[c2][0] : tones[c2][1];
            if (tones[c2][2] > m) m = tones[c2][2];
            float up = m < 170 ? 170.0f / (m > 8 ? m : 8) : 1;
            tr = tones[c2][0] * up; tg = tones[c2][1] * up; tb = tones[c2][2] * up;
            if (tr > 255) tr = 255;
            if (tg > 255) tg = 255;
            if (tb > 255) tb = 255;
        }
        tr += (244 - tr) * .35f;                       /* a lamp's colour, not paint: towards warm white */
        tg += (232 - tg) * .35f;
        tb += (216 - tb) * .35f;
        float *R = c2 ? &cr2 : &cr, *G = c2 ? &cg2 : &cg, *B2 = c2 ? &cb2 : &cb;
        *R += (tr - *R) * k;
        *G += (tg - *G) * k;
        *B2 += (tb - *B2) * k;
    }
    ca += ((on ? playing ? .55f + .2f * en : .3f : 0) - ca) * k;
    if (ca < .02f) return;
    /* the music: the spectrum, or a beat at the song's tempo when there isn't one */
    uint8_t bands[12];
    float bass = 0, level = 0, tempo = bpm10 > 300 ? bpm10 / 600.0f : 1.8f;
    if (playing && plat_spectrum(bands)) {
        for (int i = 0; i < 12; i++) level += bands[i];
        level /= 12 * 255.0f;
        bass = (bands[0] + bands[1] + bands[2]) / 765.0f;
    } else if (playing) {
        float ph = t * tempo - floorf(t * tempo);
        bass = expf(-ph * 5) * .8f;
        level = .35f + .25f * bass;
        for (int i = 0; i < 12; i++) {
            float v = level * (.7f + .5f * sinf(t * (1.3f + i * .37f) + i));
            bands[i] = (uint8_t)(255 * (v > 1 ? 1 : v));
        }
    } else memset(bands, 0, sizeof bands);
    float atk = 1 - expf(-dt * 18), rel = 1 - expf(-dt * 4);
    for (int i = 0; i < 12; i++) { float v = bands[i] / 255.0f; sb[i] += (v - sb[i]) * (v > sb[i] ? atk : rel); }
    lvl += (level - lvl) * (1 - expf(-dt * 6));
    float mx = 0;                                      /* the bands against the song's own recent peak */
    for (int i = 0; i < 12; i++) if (sb[i] > mx) mx = sb[i];
    pk = mx > pk ? mx : pk - (pk - mx) * (1 - expf(-dt * .7f));
    if (pk < .05f) pk = .05f;
    float kick = bass - bavg;                          /* the bass over its own running level */
    bavg += (bass - bavg) * (1 - expf(-dt * 1.5f));
    float kb = kick * 5;                               /* the bass's swell: up on a kick, down slower */
    kb = kb < 0 ? 0 : kb > 1 ? 1 : kb;
    benv += (kb - benv) * (kb > benv ? 1 - expf(-dt * 20) : 1 - expf(-dt * 3));
    if ((ws == 3 || (ws == 0 && style == 2)) && playing && kick > .07f && bass > .25f && now - ring0[(nr + 7) & 7] > 240)
        ring0[nr++ & 7] = now ? now : 1;               /* a kick: a ring off the monitor */
    /* per column and per row, then per cell in integers. The bars: 20 of them, 8 cells
     * apart, the bass at both edges (what shows round the desk), the highs behind the
     * monitor; each with a peak that hangs, then falls */
    static int16_t A[DW], B[88], BH[20], BP[20], HALO[200], FX[DW], FY[88];
    static uint8_t dotA[88][DW], dotB[88][DW];
    static float peak[20];
    float sp = .25f + .35f * tempo;
    for (int x = 0; x < DW; x++)
        A[x] = (int16_t)(128 + 127 * sinf(x * .09f + t * sp + sinf(t * .21f + x * .025f) * 1.8f));
    for (int b = 0; b < 20; b++) {
        float u = (1 - fabsf(b * 8 + 3 - 79.5f) / 80) * 11;
        int i0 = (int)u;
        if (i0 > 11) i0 = 11;
        float f = u - i0, v = (sb[i0] * (1 - f) + sb[i0 < 11 ? i0 + 1 : 11] * f) / pk;
        float h = (v > 1 ? 1 : v) * 62;                /* two thirds of the wall at most */
        h = h * h / 62;
        peak[b] = h > peak[b] ? h : peak[b] - dt * 28;
        BH[b] = (int16_t)h;
        BP[b] = (int16_t)(peak[b] > 0 ? peak[b] : 0);
    }
    for (int y = 0; y < 88; y++) B[y] = (int16_t)(128 + 127 * sinf(y * .19f - t * sp * .8f));
    if (ws == 1) {                                     /* the halo's fall-off from the monitor's edge */
        float R = 9 + 10 * lvl, I = 120 + 136 * benv;
        for (int d = 0; d < 200; d++) HALO[d] = (int16_t)(I * expf(-d / R));
    }
    if (ws == 2) {                                     /* the strip's light: down the wall, a little up */
        float R = 14 + 8 * lvl, I = 130 + 110 * benv;
        for (int y = 0; y < 88; y++) FY[y] = (int16_t)(I * (y >= 30 ? expf(-(y - 30) / R) : expf(-(29 - y) / 2.5f)));
        for (int x = 0; x < DW; x++) { int e = x < 22 ? 22 - x : x > 139 ? x - 139 : 0; FX[x] = (int16_t)(256 * expf(-e / 6.0f)); }
    }
    if (ws == 4) {                                     /* the dots, into their two tones' buffers */
        memset(dotA, 0, sizeof dotA);
        memset(dotB, 0, sizeof dotB);
        for (int j = 0; j < 22; j++) {
            uint32_t h = pet_hash((uint32_t)j * 2246822519u);
            float px = (h % 160) + sinf(t * .15f + j) * 12, py = ((h >> 8) % 84) + cosf(t * .11f + j * 1.7f) * 6;
            int r = 4 + (int)((h >> 16) % 4), band = j % 12;
            float br = sb[band] / pk;
            br = br > 1 ? 1 : br;
            int v0 = (int)(br * br * 230);
            uint8_t (*buf)[DW] = j % 2 ? dotB : dotA;
            for (int y = (int)py - r; y <= (int)py + r; y++)
                for (int x = (int)px - r; x <= (int)px + r; x++) {
                    if (x < 0 || x >= DW || y < 0 || y >= 88) continue;
                    float dx = x + .5f - px, dy = y + .5f - py, f = 1 - (dx * dx + dy * dy) / (float)(r * r);
                    if (f <= 0) continue;
                    int v = buf[y][x] + (int)(v0 * f * f);
                    buf[y][x] = (uint8_t)(v > 255 ? 255 : v);
                }
        }
    }
    int ring_r[8], ring_a[8], n_ring = 0;
    float life = ws == 3 ? 1.8f : 1.4f;
    for (int i = 0; i < 8; i++) {
        float age = ring0[i] ? (now - ring0[i]) / 1000.0f : 9;
        if (age < life) {
            ring_r[n_ring] = (int)(age * (ws == 3 ? 70 : 90));
            ring_a[n_ring++] = (int)((ws == 3 ? 90 + 80 * en : 110) * (1 - age / life));
        }
    }
    float fl = kick * 5;
    int A_on = (int)(ca * 256), lv = (int)(lvl * 256),
        wash = A_on * (ws == 0 ? 115 : ws == 5 ? 190 : ws == 4 ? 70 : 60) >> 8,
        flare = ws == 0 && style == 2 ? (int)((fl < 0 ? 0 : fl > 1 ? 1 : fl) * 60) : 0;
    int lr, lg, lb, lr2, lg2, lb2, gi, gi2;
    vibe_lift((int)cr, (int)cg, (int)cb, &lr, &lg, &lb, &gi);
    vibe_lift((int)cr2, (int)cg2, (int)cb2, &lr2, &lg2, &lb2, &gi2);
    px16 glow = (px16)gi, glow2 = (px16)gi2;
    if (ws == 2) {                                     /* the strip itself, lit in the colour */
        int I = FY[30] > 0 ? FY[30] : 1;
        for (int x = 22; x < 139; x++) ck_point(g, x, 29, blend565(H(0xf0f0ec), glow, 140 + (I > 255 ? 115 : I * 115 / 256)));
    }
    float breath = .5f + .5f * sinf(t * .45f);
    const int gsh = ws == 0 || ws == 5 ? 9 : 8, gcap = ws == 0 || ws == 5 ? 130 : 190;
    for (int y = 0; y < 88; y++) {
        px16 *row = g->px + 2 * y * g->stride;
        int up = 88 - y, dy = y - 66;
        /* dusk: this row's colour between the two tones */
        int wy = y * 256 / 87, rr = lr + ((lr2 - lr) * wy >> 8), rg = lg + ((lg2 - lg) * wy >> 8), rb = lb + ((lb2 - lb) * wy >> 8);
        for (int x = 0; x < DW; x++) {
            if (!dio_wl[y][x]) continue;
            int gl = 0, gl2 = 0, mr = lr, mg = lg, mb = lb;
            if (ws == 0) {
                if (style == 0) {                      /* the aurora: soft bands crossing */
                    int s2 = (A[x] + B[y]) >> 1, r3 = (s2 * s2 >> 8) * s2 >> 8;   /* ribbons where the two crests meet */
                    gl = 14 + (r3 * (200 + (lv >> 1)) >> 8);
                } else {
                    int b = x >> 3, h = BH[b], in = (x & 7) < 6;
                    gl = 12 + (A[x] * B[y] >> 13);
                    if (in && up <= h) gl += h - up < 2 ? 230 : 110 + 60 * up / (h + 1);
                    else if (in && up == BP[b] + 1 && BP[b] > 2) gl += 200;     /* the peak, hanging */
                }
                gl += flare;
            } else if (ws == 1) {
                int ddx = x < 42 ? 42 - x : x > 119 ? x - 119 : 0, ddy = y < 50 ? (50 - y) * 4 / 3 : 0;
                int d = ddx > ddy ? ddx + ddy / 2 : ddy + ddx / 2;
                gl = HALO[d < 200 ? d : 199];
            } else if (ws == 2) {
                gl = FY[y] * FX[x] >> 8;
            } else if (ws == 4) {
                gl = dotA[y][x];
                gl2 = dotB[y][x];
            } else if (ws == 5) {
                mr = rr; mg = rg; mb = rb;
                gl = (int)(20 + 30 * breath * (.4f + lvl));
            }
            for (int i = 0; i < n_ring; i++) {
                int dx = x - 80, d2 = dx * dx + dy * dy * 3, r0 = ring_r[i] - 3, r1 = ring_r[i] + 3;
                if (d2 >= (r0 > 0 ? r0 * r0 : 0) && d2 < r1 * r1) gl += ring_a[i];
            }
            if (gl > 256) gl = 256;
            int ga = gl * A_on >> gsh, ga2 = gl2 * A_on >> gsh;   /* the local lights may peak brighter */
            if (ga > gcap) ga = gcap;
            if (ga2 > gcap) ga2 = gcap;
            px16 gcol = ws == 5 ? C565(mr, mg, mb) : glow;
            px16 *p = row + 2 * x, c0 = p[0];
            if (p[1] == c0 && p[g->stride] == c0 && p[g->stride + 1] == c0) {
                px16 c = blend565(blend565(c0, vibe_mul(c0, mr, mg, mb), wash), gcol, ga);
                if (ga2) c = blend565(c, glow2, ga2);
                p[0] = p[1] = p[g->stride] = p[g->stride + 1] = c;
            } else
                for (int j = 0; j < 4; j++) {          /* the time's or the battery's figures over it */
                    px16 *q = p + (j & 1) + (j >> 1) * g->stride;
                    *q = blend565(blend565(*q, vibe_mul(*q, mr, mg, mb), wash), gcol, ga);
                }
        }
    }
}

/* the still frame with its overlays, kept so what moves can be drawn over it */
static px16 dio_bg[LCD_W * BAR_Y];
static int dio_ok;

/* the cells he covers (x0, y0, x1, y1); 0 when he's out of the picture */
static int dcat_box(const dpose *p, int b[4])
{
    int hw, up;
    switch (p->pose) {
    case DP_LOAF: hw = CAT_W / 2 + 1; up = 16; break;
    case DP_SIT: case DP_GROOM: hw = 11; up = 24; break;
    case DP_WALK: hw = 15; up = 19; break;
    case DP_CURL: hw = 15; up = 16; break;
    case DP_BACK: hw = 10; up = 20; break;
    case DP_LEAP: hw = 17; up = 16; break;
    default: return 0;
    }
    int x = (int)lrintf(p->x);
    b[0] = x - hw; b[1] = p->y - up; b[2] = x + hw; b[3] = p->y + 1;
    return 1;
}

/* the picked thing's tag and the pointer at it; when he's settled where the tag would go
 * (asleep on the case, on your keyboard), it goes beside him and the pointer under him */
/* where the picked thing's tag points (cells): a menu item's, or a card on the board */
static void dio_tag_xy(int cur, int *tx, int *ty)
{
    if (cur < N_MENU) { *tx = DIO_TAG[cur][0]; *ty = DIO_TAG[cur][1]; return; }
    int b[4];
    dio_rack_card(cur - N_MENU, b);
    *tx = b[2] - 3;
    *ty = b[1] + 3;
}

static void dio_pick_tag(app *a, gfx *g, int cur, const dpose *p, uint32_t now)
{
    int tx, ty, b[4];
    dio_tag_xy(cur, &tx, &ty);
    const char *label = cur < N_MENU ? menu_items[cur] : rack_verb(a, cur - N_MENU);
    int w = text_w(F(a, F_SEMI11), label, 0) + 16;
    int gx = 2 * tx + 10 + w > LCD_W - 4 ? LCD_W - 4 - w : 2 * tx + 10, gy = 2 * ty - 22;
    int px = 2 * tx - 4, py = 2 * ty - 8;
    if (gy < 2) gy = 2;
    if (p->pose != DP_WALK && p->pose != DP_LEAP && dcat_box(p, b)) {
        if (gx < 2 * b[2] && gx + w > 2 * b[0] && gy < 2 * b[3] && gy + 18 > 2 * b[1]) {
            gx = 2 * b[0] - w - 4;
            if (gx < 4) gx = 2 * b[2] + 4;
        }
        if (2 * tx >= 2 * b[0] && 2 * tx < 2 * b[2] && 2 * ty >= 2 * b[1] && 2 * ty < 2 * b[3] + 4) py = 2 * b[3] + 4;
    }
    g_fill(g, gx, gy, w, 18, RP.walnut_d);
    g_fill(g, gx + 1, gy + 1, w - 2, 16, RP.parch);
    txt(a, g, F_SEMI11, gx + 8, gy + 13, label, RP.ink, 0);
    ck_pointer(g, px, py, now, RP.walnut_d, RP.cream);
}

static void dio_live(app *a, gfx *g, uint32_t now)
{
    float t = now / 1000.0f;
    float T = life_ms(now) / 1000.0f;
    int playing = a->cur_valid && a->ps.playing, poked = now - a->poke_ms < 6000;
    int cur = menu_item_at(a, a->ls[V_MENU].sel);          /* the item, not the position */
    g_clip(g, 0, 0, LCD_W, BAR_Y);
    dio_vibe(a, g, now, playing);                          /* first: the rest goes over the wall */
    dio_clock_hands(g, T);
    dio_plants(g, t, cur == 6);
    px_battery(a, g, LCD_W - 8, 12, C565(0x3a, 0x2a, 0x20));    /* over the leaves: the pothos and fern reach them */
    px_time(a, g, 62, 12, C565(0x3a, 0x2a, 0x20));
    dio_steam(g, t);
    dio_screen(g, t, playing);
    dio_bits(a, g, t, now, playing);
    float bass = 0;
    uint8_t bands[12];
    if (playing && plat_spectrum(bands)) bass = (bands[0] + bands[1] + bands[2]) / 765.0f;
    dpose p;
    int tx, ty;
    dio_tag_xy(cur, &tx, &ty);
    life_pose(&p, T, playing, poked, tx, bass);
    dio_cat_draw(g, &p);
    dio_pick_tag(a, g, cur, &p, now);
    /* under the desk: what the picked thing is; a while after your last button, what he's up to */
    char line[96];
    if (now - a->poke_ms > 9000) dio_status(T, line, sizeof line);
    else if (cur < N_MENU) snprintf(line, sizeof line, "%s", MENU_DESC[cur]);
    else rack_desc(a, cur - N_MENU, line, sizeof line);
    txt_fit(a, g, F_BODY10, 10, 207, line, 300, C565(0xd8, 0xcc, 0xb4), 0);
    g_noclip(g);
}

/* each thing's box on the desk (cells), for the camera (th_dio_close.h) */
static int16_t dio_bb[DO_SETTINGS + 1][4];
/* the wheel takes the focus round the desk clockwise: the clock, the pothos, the case,
 * the headphones, the H2 on the desk, the keyboard, up the monitor to the posters */
static const uint8_t DIO_ORDER[8] = { 0, 6, 5, 2, 7, 4, 1, 3 };
static void dio_boxes(void)
{
    for (int i = 0; i <= DO_SETTINGS; i++) { dio_bb[i][0] = dio_bb[i][1] = 999; dio_bb[i][2] = dio_bb[i][3] = -1; }
    for (int y = 0; y < DH; y++)
        for (int x = 0; x < DW; x++) {
            int id = dio_id[y][x];
            if (id <= DO_NONE || id > DO_SETTINGS) continue;
            int16_t *b = dio_bb[id];
            if (x < b[0]) b[0] = (int16_t)x;
            if (y < b[1]) b[1] = (int16_t)y;
            if (x + 1 > b[2]) b[2] = (int16_t)(x + 1);
            if (y + 1 > b[3]) b[3] = (int16_t)(y + 1);
        }
}

/* the desk, lit, the picked thing outlined */
static void dio_paint(gfx *g, int id)
{
    for (int y = 0; y < DH; y++)
        for (int x = 0; x < DW; x++) {
            px16 c = dio_em[y][x] ? dio_px[y][x] : dio_lit(dio_px[y][x], x, y);
            if (id && dio_id[y][x] != id && ((x > 0 && dio_id[y][x - 1] == id) || (x < DW - 1 && dio_id[y][x + 1] == id) ||
                                             (y > 0 && dio_id[y - 1][x] == id) || (y < DH - 1 && dio_id[y + 1][x] == id)))
                c = RP.cream;
            ck_point(g, x, y, c);
        }
}

/* the song on the monitor: its cover, "now playing", the title, the artist */
/* the biggest of fonts[] (each with its most lines) that shows s whole in w; else the last,
 * its last line cut. The font it chose; lines and *nl filled */
static int fit_wrap(app *a, const int *fonts, const int *maxl, int nf, const char *s, int w,
                    char lines[][TEXT_LINE_MAX], int *nl)
{
    static char tmp[9][TEXT_LINE_MAX];
    for (int i = 0; i < nf; i++)
        if (i == nf - 1 || text_wrap(F(a, fonts[i]), s, w, maxl[i] + 1, 0, tmp) <= maxl[i]) {
            *nl = text_wrap(F(a, fonts[i]), s, w, maxl[i], 0, lines);
            return fonts[i];
        }
    return fonts[nf - 1];
}

/* the monitor on the desk: the cover (its bars under it, dio_screen), "now playing", the
 * title -- bold in two lines, else smaller in three -- and the artist */
static void dio_monitor(app *a, gfx *g)
{
    const lib_track *tr = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    if (!tr) { pf_text(g, &PF_PIXEL11, 132, 140, "Coda", C565(0xf4, 0xee, 0xe2), 2); return; }
    if (dio_plain) {                                    /* preview renders: the cover's two tones */
        int tn[2][3];
        wall_tones(a, a->cur, tn);
        g_fill(g, 92, 108, 50, 25, C565(tn[0][0], tn[0][1], tn[0][2]));
        g_fill(g, 92, 133, 50, 25, C565(tn[1][0], tn[1][1], tn[1][2]));
    } else cover(a, g, a->cur, ART_M, 92, 108, 50);
    txt(a, g, F_MONO10, 150, 116, a->ps.playing ? "> now playing" : "> paused", H(0x74b14b), 0);
    static const int fonts[2] = { F_BOLD11, F_BODY10 }, maxl[2] = { 2, 3 };
    char lines[3][TEXT_LINE_MAX];
    int nl, f = fit_wrap(a, fonts, maxl, 2, tr->title, 80, lines, &nl), lh = f == F_BOLD11 ? 12 : 11, y = 128;
    for (int k = 0; k < nl; k++) txt(a, g, f, 150, y + lh * k, lines[k], C565(0xf4, 0xee, 0xe2), 0);
    txt_fit(a, g, F_BODY10, 150, y + lh * nl + 1, tr->artist, 80, H(0x9fb8dc), 0);
}

static void dio_home(app *a, gfx *g)
{
    static const uint8_t ID_OF[N_MENU] = { DO_WHEEL, DO_NOW, DO_QUEUE, DO_EXPLORE, DO_SEARCH, DO_LIBRARY, DO_LIKED, DO_SETTINGS };
    int cur = menu_item_at(a, a->ls[V_MENU].sel);          /* the item, not the position */
    dio_lights(a->cur_valid && a->ps.playing);
    dio_screen_on = 1;
    dio_buds = buds_level(a);
    dio_rack_n = rack_n(a);
    for (int k = 0; k < dio_rack_n; k++) dio_rack_st[k] = (uint8_t)rack_state(a, k);
    dio_rack_layout(a);
    dio_scene();
    dio_buds = -1;
    dio_boxes();
    dio_paint(g, cur < N_MENU ? ID_OF[cur] : DO_RACK0 + cur - N_MENU);
    dio_monitor(a, g);
    dio_rack_text(a, g);
    px_battery(a, g, LCD_W - 8, 12, C565(0x3a, 0x2a, 0x20));     /* the picked thing's tag goes on with him (dio_live) */
    px_time(a, g, 62, 12, C565(0x3a, 0x2a, 0x20));               /* top left, clear of the tags */
    for (int y = 0; y < BAR_Y; y++) memcpy(dio_bg + y * LCD_W, g->px + y * g->stride, LCD_W * 2);
    dio_ok = 1;
    petl.live = 1;
    petl.view = V_MENU;
    dio_live(a, g, a->now_ms);
    draw_nowbar(a, g);
}

/* just what moves, over the kept frame */
static void dio_frame(app *a, gfx *g, int r[4])
{
    for (int y = 0; y < BAR_Y; y++) memcpy(g->px + y * g->stride, dio_bg + y * LCD_W, LCD_W * 2);
    dio_live(a, g, a->now_ms);
    r[0] = 0; r[1] = 0; r[2] = LCD_W; r[3] = BAR_Y;
}

/* what he's up to, for the shots and the log */
float app_pet_status(app *a, char *out, int n)
{
    return dio_status(life_ms(a->now_ms) / 1000.0f, out, (size_t)n);
}

/* ------------------------------------------------------------------ power on, off
 * Room's door (th_room.h door_boot / door_off): a dark hall, music and light leaking round
 * the closed door; it swings open on the desk -- Bubloo on it, "Coda" on the monitor, the
 * room in its day or night -- and you walk in; off, you back out and it shuts. */
static const px16 DIO_DARK = H(0x14100d);

static void dio_inside(gfx *g, uint32_t t, int dx, int dy, int blink)
{
    dio_lights(0);
    dl.screen = 256;
    dio_screen_on = 1;
    dio_scene();
    dio_paint(g, 0);
    dio_clock_hands(g, dio_hour() * 3600 + t / 1000.0f);
    dio_plants(g, t / 1000.0f, 0);
    dio_steam(g, t / 1000.0f);
    pf_text(g, &PF_PIXEL11, 132, 140, "Coda", C565(0xf4, 0xee, 0xe2), 2);
    g_fill(g, 0, BAR_Y, LCD_W, LCD_H - BAR_Y, DIO_DARK);
    dpose p;                                           /* where his day has him now: the home carries on from it */
    life_pose(&p, life_ms(plat_ms()) / 1000.0f, 0, 0, 0, 0);
    if (blink && p.h.eyes) p.h.eyes = 0;
    dio_cat_draw(g, &p);
    dr_shift(g, dx, dy, DIO_DARK);
}

static void dio_boot(gfx *g, uint32_t t) { door_boot(g, t, dio_inside, 40, 8); }

static void dio_off(app *a, gfx *g, uint32_t t, const px16 *from)
{
    (void)a;
    door_off(g, t, from, 40, 8, DIO_DARK);
}
