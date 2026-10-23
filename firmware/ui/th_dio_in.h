/* Diorama, inside things (part of app.c, after th_dio_close.h). Picking a thing on the desk
 * moves the camera in on it; for these its page is what's inside it, the way the case
 * opens on its parts:
 *
 *   the clock (the Wheel): the white shelf clock's back off -- its AA battery, the board
 *   with the quartz crystal and the chip under its blob, the copper coil and the magnet
 *   rotor that steps every second, and the wheel of covers as the big gear the rest
 *   drives, turning as you turn it.
 *
 * Each is drawn in cells like the desk: the still parts once (lit, kept in in_bg until the
 * light or the layout changes), what moves over them every frame. */

#define IW 160
#define IH 120
static px16 in_cell[IH][IW];                     /* in_bg, in_key: th_dio_close.h */

static void ip(int x, int y, px16 c) { if (x >= 0 && x < IW && y >= 0 && y < IH) in_cell[y][x] = c; }
static void irect(int a, int b, int c, int d, px16 col) { for (int y = b; y < d; y++) for (int x = a; x < c; x++) ip(x, y, col); }
static void idisc(float cx, float cy, float r, px16 col)
{
    for (int y = (int)(cy - r) - 1; y <= (int)(cy + r) + 1; y++)
        for (int x = (int)(cx - r) - 1; x <= (int)(cx + r) + 1; x++)
            if ((x + .5f - cx) * (x + .5f - cx) + (y + .5f - cy) * (y + .5f - cy) <= r * r) ip(x, y, col);
}
static void iline(float x0, float y0, float x1, float y1, px16 col)
{
    int n = (int)(fabsf(x1 - x0) > fabsf(y1 - y0) ? fabsf(x1 - x0) : fabsf(y1 - y0)) + 1;
    for (int i = 0; i <= n; i++) ip((int)floorf(x0 + (x1 - x0) * i / n + .5f), (int)floorf(y0 + (y1 - y0) * i / n + .5f), col);
}
/* tiny letters, 3 x 5 cells: what's printed on the parts */
static void itext(int x, int y, const char *s, px16 col)
{
    static const struct { char c; const char *rows[5]; } G[] = {
        { 'A', { ".#.", "#.#", "###", "#.#", "#.#" } }, { 'V', { "#.#", "#.#", "#.#", "#.#", ".#." } },
        { '1', { ".#.", "##.", ".#.", ".#.", "###" } }, { '5', { "###", "#..", "##.", "..#", "##." } },
        { '.', { "...", "...", "...", "...", ".#." } }, { 'Q', { ".#.", "#.#", "#.#", "#.#", ".##" } },
        { 'U', { "#.#", "#.#", "#.#", "#.#", "###" } }, { 'R', { "##.", "#.#", "##.", "#.#", "#.#" } },
        { 'T', { "###", ".#.", ".#.", ".#.", ".#." } }, { 'Z', { "###", "..#", ".#.", "#..", "###" } },
    };
    for (; *s; s++, x += 4)
        for (unsigned k = 0; k < sizeof G / sizeof G[0]; k++)
            if (G[k].c == *s)
                for (int r = 0; r < 5; r++)
                    for (int q = 0; q < 3; q++) if (G[k].rows[r][q] == '#') ip(x + q, y + r, col);
}

/* lit like the room (a close-up: the room's light and the lamp), on any row of the screen */
static void in_pt(gfx *g, int x, int y, px16 c) { if (x >= 0 && x < IW && y >= 0 && y < IH) ck_point(g, x, y, dio_lit(c, x, y)); }

/* a gear: teeth between r0 and r1 (cells) around cx, cy, turned by rot (radians), n teeth;
 * body inside r0 with a hub; holes > 0 cuts that many round windows in a big one */
static void in_gear(gfx *g, float cx, float cy, float r0, float r1, int n, float rot, px16 body, px16 edge,
                    px16 hi, int holes)
{
    float in2 = holes < 0 ? (r0 - 1) * (r0 - 1) : -1;        /* holes < 0: just the teeth and the rim */
    for (int y = (int)(cy - r1) - 1; y <= (int)(cy + r1) + 1; y++) {
        if (y < 0 || y >= IH) continue;
        float dy0 = y + .5f - cy;
        for (int x = (int)(cx - r1) - 1; x <= (int)(cx + r1) + 1; x++) {
            if (x < 0 || x >= IW) continue;
            float dx = x + .5f - cx, dy = dy0, d2 = dx * dx + dy * dy;
            if (d2 > r1 * r1 || d2 < in2) continue;
            float d = sqrtf(d2);
            px16 c = body;
            if (d > r0) {                                        /* a tooth, or the gap between */
                float u = (datan2(dy, dx) - rot) / 6.2832f * n;
                u -= floorf(u);
                float half = .27f + .12f * (r1 - d) / (r1 - r0);
                if (fabsf(u - .5f) > half) continue;
                c = fabsf(u - .5f) > half - .09f ? edge : body;
            } else if (d > r0 - 1) c = edge;                     /* the rim */
            else if (d < 1.6f) c = edge;                         /* the arbor */
            else if (d < 2.6f) c = hi;
            else if (holes > 0 && d > r0 * .4f && d < r0 * .74f) {  /* windows between spokes, turning with it */
                float u = (datan2(dy, dx) - rot) / 6.2832f * holes;
                if (fabsf(u - floorf(u) - .5f) < .3f) continue;
            }
            if (dy < -d * .55f && d > 2.6f && d < r0 - 1) c = blend565(c, hi, 90);     /* the light from above */
            in_pt(g, x, y, c);
        }
    }
}

/* ------------------------------------------------------------------ the clock */
static const px16 IC_CASE = H(0xe7e4dc), IC_CASE2 = H(0xdedbd2), IC_RIB = H(0xcac5b9), IC_RIBH = H(0xf4f2ed),
                  IC_SHADE = H(0xc4bfb2), IC_STEEL = H(0x8d9197), IC_STEEL2 = H(0x6b6f75), IC_SILVER = H(0xc9ccd1),
                  IC_SILVER2 = H(0xeef0f2), IC_BLACK = H(0x232226), IC_BLACK2 = H(0x3a3c40), IC_RED = H(0xc8322a),
                  IC_COPPER = H(0xb8692e), IC_COPPER2 = H(0xd98a45), IC_COPPER3 = H(0xeaa868), IC_PCB = H(0x2f5d3a),
                  IC_PCB2 = H(0x3f7a4c), IC_GOLD = H(0xc9a64a), IC_GEAR = H(0x8f9399), IC_GEAR_E = H(0x5f6368),
                  IC_GEAR_H = H(0xb4b8bd);

typedef struct { float cx, cy, r0, r1; } clk_geo;

/* where the wheel's covers are, in cells: the gear round them */
static clk_geo clk_great(const app *a)
{
    const wheel_geom *w = a->layout_b ? &WHEEL_B : &WHEEL_A;
    clk_geo c = { w->cx / 2.0f, w->cy / 2.0f, w->r2 / 2.0f + .5f, w->r2 / 2.0f + 5.0f };
    return c;
}

/* the still parts: the case's back, the battery in its holder, the wires, the board, the
 * coil and the stator round the rotor */
static void clk_scene(const app *a)
{
    for (int y = 0; y < IH; y++)
        for (int x = 0; x < IW; x++) {
            uint32_t h = pet_hash((uint32_t)(x * 131 + y * 977));
            in_cell[y][x] = h % 13 == 0 ? IC_CASE2 : IC_CASE;
        }
    clk_geo G = clk_great(a);
    for (int y = 0; y < IH; y++)                       /* the molded ring the movement sits in */
        for (int x = 0; x < IW; x++) {
            float d = sqrtf((x + .5f - G.cx) * (x + .5f - G.cx) + (y + .5f - G.cy) * (y + .5f - G.cy));
            if (fabsf(d - (G.r1 + 3.5f)) < .5f) in_cell[y][x] = IC_RIB;
            else if (fabsf(d - (G.r1 + 4.5f)) < .5f) in_cell[y][x] = IC_RIBH;
        }
    if (!a->layout_b) return;                          /* the full wheel leaves no room for the rest */

    /* the AA in its holder, top left: minus end against the spring, the copper top right */
    irect(3, 28, 42, 41, IC_SHADE);
    irect(2, 27, 41, 40, IC_BLACK2);
    irect(2, 27, 41, 28, H(0x55585e));
    for (int y = 30; y < 38; y++) ip(3 + (y & 1), y, IC_SILVER);              /* the spring */
    irect(5, 29, 7, 38, IC_SILVER);                                            /* minus: flat */
    irect(7, 29, 32, 38, IC_BLACK);
    irect(7, 29, 32, 30, H(0x4a4c50));
    irect(32, 29, 38, 38, IC_COPPER2);
    irect(32, 29, 38, 30, IC_COPPER3);
    irect(32, 37, 38, 38, IC_COPPER);
    irect(38, 31, 40, 36, IC_SILVER);                                          /* plus: the nub */
    itext(12, 31, "AA", IC_COPPER3);
    irect(21, 33, 29, 34, H(0x6b6f75));
    /* its wires, over to the board */
    iline(40, 30, 46, 25, IC_RED);
    iline(46, 25, 120, 23, IC_RED);
    iline(120, 23, 141, 18, IC_RED);
    iline(40, 34, 47, 27, IC_BLACK);
    iline(47, 27, 121, 25, IC_BLACK);
    iline(121, 25, 141, 21, IC_BLACK);
    /* the board, standing at the right: the chip under its blob, the crystal in its can */
    irect(142, 10, 160, 31, IC_SHADE);
    irect(141, 9, 159, 30, IC_PCB);
    irect(141, 9, 159, 10, IC_PCB2);
    for (int y = 12; y < 29; y += 4) irect(156, y, 158, y + 2, IC_PCB2);
    iline(148, 19, 148, 27, IC_GOLD);
    iline(148, 27, 153, 27, IC_GOLD);
    idisc(151, 14.5f, 3.7f, IC_BLACK);                                         /* the blob */
    ip(149, 13, H(0x55585e));
    irect(143, 16, 147, 28, IC_SILVER);                                        /* the crystal */
    irect(143, 16, 144, 28, IC_SILVER2);
    irect(144, 28, 145, 30, IC_GOLD); irect(146, 28, 147, 30, IC_GOLD);
    ip(141, 18, IC_SILVER); ip(141, 21, IC_SILVER);                            /* the wires' solder */
    irect(151, 23, 154, 26, H(0x8a5a3c));                                      /* a cap */
    /* the coil: copper windings on its bobbin, its leads up to the board */
    irect(123, 33, 148, 40, IC_SHADE);
    irect(121, 31, 124, 39, IC_BLACK);
    irect(143, 31, 146, 39, IC_BLACK);
    for (int x = 124; x < 143; x++) {
        irect(x, 32, x + 1, 38, x & 1 ? IC_COPPER : IC_COPPER2);
        ip(x, 32, IC_COPPER3);
    }
    iline(145, 31, 146, 30, IC_GOLD);
    iline(144, 31, 143, 30, IC_GOLD);
    /* the stator: two steel plates from the coil, round the rotor */
    irect(146, 31, 159, 41, IC_STEEL);
    irect(146, 31, 159, 32, IC_SILVER);
    irect(146, 40, 159, 41, IC_STEEL2);
    idisc(152.5f, 35.5f, 4.6f, IC_STEEL2);
    idisc(152.5f, 35.5f, 4.0f, IC_CASE2);
}

/* the clock's page: the still parts, then the gears (turned by the wheel) and the rotor
 * (a step every second) */
static void dio_clock_page(app *a, gfx *g)
{
    dio_close_light(a);
    int key = a->layout_b | rp_k << 1;
    if (key != in_key) {
        clk_scene(a);
        gfx b;
        g_init(&b, in_bg, LCD_W, LCD_H, LCD_W);
        for (int y = 0; y < IH; y++)
            for (int x = 0; x < IW; x++) ck_point(&b, x, y, dio_lit(in_cell[y][x], x, y));
        in_key = key;
    }
    for (int y = 0; y < LCD_H; y++) memcpy(g->px + y * g->stride, in_bg + y * LCD_W, LCD_W * 2);
    clk_geo G = clk_great(a);
    float rot = -a->s * 3.14159265f / 6;                      /* the covers: 30 degrees a detent */
    int n = (int)(6.2832f * G.r1 / 3.2f);
    in_gear(g, G.cx, G.cy, G.r0, G.r1, n, rot, IC_GEAR, IC_GEAR_E, IC_GEAR_H, -1);   /* its face is the covers */
    if (!a->layout_b) {                                       /* one pinion, low on the left */
        float pa = 2.62f, pr = 6.0f, d = G.r1 + pr;
        in_gear(g, G.cx + d * cosf(pa), G.cy + d * sinf(pa), pr, pr + 1.6f, 13, -rot * G.r1 / pr, IC_BLACK2,
                IC_BLACK, H(0x5c5f65), 0);
        return;
    }
    /* the train up to the rotor on the right, a pinion on the left */
    float a1 = -.611f, p1 = 8.7f, d1 = G.r1 + p1 - 1.2f;
    float x1 = G.cx + d1 * cosf(a1), y1 = G.cy + d1 * sinf(a1);
    float r1 = -rot * G.r1 / p1;
    in_gear(g, x1, y1, p1 - 1, p1 + .8f, 18, r1, IC_BLACK2, IC_BLACK, H(0x5c5f65), 4);
    float r2 = -r1 * p1 / 5.6f;
    in_gear(g, 151, 49, 5.0f, 6.6f, 12, r2, IC_RED, H(0x8e2018), H(0xe2604f), 0);
    float a3 = -2.41f, p3 = 6.0f, d3 = G.r1 + p3 - 1.0f;
    in_gear(g, G.cx + d3 * cosf(a3), G.cy + d3 * sinf(a3), p3 - 1, p3 + .8f, 13, -rot * G.r1 / p3, IC_BLACK2,
            IC_BLACK, H(0x5c5f65), 0);
    /* the rotor: a two-pole magnet, half a turn every second */
    int sec = plat_clock_sec();
    float ra = sec * 3.14159265f;
    for (int y = 31; y <= 40; y++)
        for (int x = 148; x <= 157; x++) {
            float dx = x + .5f - 152.5f, dy = y + .5f - 35.5f, d2 = dx * dx + dy * dy;
            if (d2 > 3.6f * 3.6f) continue;
            if (d2 < 1.1f) { in_pt(g, x, y, IC_SILVER); continue; }
            float u = dx * cosf(ra) + dy * sinf(ra);
            in_pt(g, x, y, u > 0 ? IC_RED : H(0x2b2f3a));
        }
}

/* ------------------------------------------------------------------ the H2
 * Settings: the player itself, lying open on the desk with its back off -- the board under
 * the screen's ribbon, and the battery -- and the eight groups are its parts: the battery
 * Sleep, the ES9018K2M Sound, the backlight's driver Screen, the display's ribbon Theme,
 * the wheel's encoder Wheel, the X1000 Playback, the Bluetooth module Bluetooth, the
 * crystal that keeps the time Clock. */
enum { PH_SLEEP = 40, PH_SOUND, PH_SCREEN, PH_THEME, PH_WHEEL, PH_PLAY, PH_BT, PH_CLOCK };
static const int16_t PH_BB[8][4] = {           /* each part's box, cells */
    { 14, 61, 70, 100 },                       /* the battery */
    { 40, 34, 49, 43 },                        /* the ES9018K2M */
    { 37, 19, 46, 24 },                        /* the backlight's driver */
    { 15, 19, 34, 28 },                        /* the display's ribbon */
    { 27, 45, 45, 59 },                        /* the wheel's encoder */
    { 21, 30, 37, 46 },                        /* the X1000 */
    { 49, 17, 69, 32 },                        /* the Bluetooth module */
    { 54, 34, 63, 39 },                        /* the crystal */
};
/* the wheel goes round the board clockwise: the ribbon at the top left, the backlight's
 * driver, the Bluetooth module, the crystal, in along its row to the DAC, down to the
 * battery, the encoder, the X1000, and up to the ribbon again -- never back up mid-way */
static const uint8_t DIO_H2_ORDER[8] = { 3, 2, 6, 7, 1, 0, 4, 5 };
static const char *const PH_PART[8] = { "The battery, 3.7 V, 1,300 mAh", "The DAC, an ES9018K2M",
                                        "The backlight's driver", "The display's ribbon",
                                        "The wheel's encoder", "Ingenic X1000, the processor",
                                        "The Bluetooth module", "32.768 kHz, the clock's crystal" };
static const char *const PH_SAYS[8] = { "When it sleeps and switches itself off.",
                                        "How loud it may go; bass and treble.",
                                        "How bright, and how long it stays lit.",
                                        "How Coda looks: the eight themes.",
                                        "The Wheel's dial, and its clicks.",
                                        "Autoplay, the previews, what plays on.",
                                        "Headphones and speakers, paired and found.",
                                        "The time, for the clock and the history." };

static void ph_scene(void)
{
    /* the desk under it: walnut, its grain */
    drect(0, 0, DW, DH, RP_DAY.walnut, DO_NONE);
    for (int y = 1; y < DH; y += 4)
        for (int x = (y * 7) % 11; x < DW; x += 11 + (y % 3)) drect(x, y, x + 6, y + 1, RP_DAY.walnut_l, DO_NONE);
    /* its back, off and lying beside it (the tag sits on it) */
    drect(86, 18, 154, 104, H(0x1c140f), DO_NONE);
    drect(84, 16, 152, 102, H(0x2e3034), DO_NONE);
    drect(84, 16, 152, 17, H(0x4c4f54), DO_NONE);
    for (int y = 22; y < 98; y += 4) drect(88, y, 148, y + 1, H(0x34363a), DO_NONE);
    /* the shell: brushed aluminium, black, the cavity */
    drect(12, 15, 76, 106, H(0x1c140f), DO_NONE);
    drect(10, 13, 74, 104, H(0x3a3c40), DO_NONE);
    drect(10, 13, 74, 14, H(0x5c5f65), DO_NONE);
    dp(10, 13, RP_DAY.walnut, DO_NONE); dp(73, 13, RP_DAY.walnut, DO_NONE);
    dp(10, 103, RP_DAY.walnut, DO_NONE); dp(73, 103, RP_DAY.walnut, DO_NONE);
    drect(13, 16, 71, 101, H(0x17181b), DO_NONE);
    drect(18, 13, 24, 15, H(0x0e0f11), DO_NONE);                     /* the jack, the USB port */
    drect(36, 102, 48, 104, H(0x0e0f11), DO_NONE);
    /* the board */
    drect(14, 17, 70, 59, H(0x1d2433), DO_NONE);
    for (int i = 0; i < 11; i++) {
        uint32_t hh = pet_hash((uint32_t)i * 5113u);
        int y = 18 + (int)(hh % 40), x0 = 15 + (int)((hh >> 8) % 40);
        drect(x0, y, x0 + 4 + (int)((hh >> 16) % 10), y + 1, H(0x283247), DO_NONE);
    }
    for (int i = 0; i < 18; i++) {                                   /* little parts */
        uint32_t hh = pet_hash((uint32_t)i * 1931u);
        dp(15 + (int)(hh % 54), 18 + (int)((hh >> 8) % 40), (hh >> 16) & 1 ? H(0xc9a64a) : H(0x8a6a4a), DO_NONE);
    }
    /* Theme: the display's ribbon, folded over, its latch */
    drect(16, 19, 33, 25, H(0xd98a2b), PH_THEME);
    for (int x = 17; x < 33; x += 2) drect(x, 19, x + 1, 25, H(0xe8a24a), PH_THEME);
    drect(16, 25, 33, 27, H(0x111214), PH_THEME);
    drect(17, 25, 32, 26, H(0x3a3c40), PH_THEME);
    /* Screen: the backlight's driver and its coil */
    drect(38, 20, 42, 23, H(0x111214), PH_SCREEN);
    dp(38, 20, H(0x5c5f65), PH_SCREEN);
    drect(42, 20, 45, 23, H(0x6b6f75), PH_SCREEN);
    dp(43, 21, H(0x9a9ea4), PH_SCREEN);
    /* Bluetooth: the module's can, its antenna */
    drect(50, 21, 68, 31, H(0xb9bcc0), PH_BT);
    drect(50, 21, 68, 22, H(0xe2e4e6), PH_BT);
    drect(50, 30, 68, 31, H(0x8d9197), PH_BT);
    for (int x = 52; x < 66; x += 3) dp(x, 26, H(0x9ea2a8), PH_BT);
    for (int x = 50; x < 68; x++) dp(x, 18 + ((x / 2) & 1), H(0xc9a64a), PH_BT);
    /* Playback: the X1000 */
    drect(22, 31, 36, 45, H(0x111214), PH_PLAY);
    drect(22, 31, 36, 32, H(0x2e3034), PH_PLAY);
    dp(23, 33, H(0x6b6f75), PH_PLAY);
    drect(25, 37, 33, 38, H(0x4a4d52), PH_PLAY);
    drect(25, 39, 31, 40, H(0x4a4d52), PH_PLAY);
    /* Sound: the ES9018K2M, the op-amp beside it */
    drect(41, 35, 48, 42, H(0x111214), PH_SOUND);
    dp(42, 36, H(0x6b6f75), PH_SOUND);
    drect(43, 38, 47, 39, H(0x4a4d52), PH_SOUND);
    drect(49, 36, 53, 41, H(0x1a1b1e), DO_NONE);
    for (int y = 36; y < 41; y += 2) { dp(48, y, H(0xb9bcc0), DO_NONE); dp(53, y, H(0xb9bcc0), DO_NONE); }
    /* Clock: the crystal, its legs */
    drect(55, 35, 61, 38, H(0xc9ccd1), PH_CLOCK);
    drect(55, 35, 61, 36, H(0xeef0f2), PH_CLOCK);
    dp(61, 36, H(0xc9a64a), PH_CLOCK);
    dp(62, 36, H(0xc9a64a), PH_CLOCK);
    /* the card in its slot */
    drect(58, 45, 69, 56, H(0xb9bcc0), DO_NONE);
    drect(59, 46, 68, 55, H(0x9ea2a8), DO_NONE);
    drect(60, 52, 67, 56, H(0x29304d), DO_NONE);
    /* Wheel: the encoder under the wheel, its ring of contacts */
    for (int y = 45; y < 59; y++)
        for (int x = 27; x < 45; x++) {
            float dx = x + .5f - 36, dy = y + .5f - 52, d = sqrtf(dx * dx + dy * dy);
            if (d > 7.0f || d < 3.2f) continue;
            int seg = (int)((datan2(dy, dx) + 3.1416f) / 6.2832f * 24);
            dp(x, y, d > 5.6f ? H(0x111214) : seg & 1 ? H(0xc9a64a) : H(0x2a2b2e), PH_WHEEL);
        }
    /* Sleep: the battery's pouch, its label, its leads up to the board */
    drect(15, 62, 69, 99, H(0xc7cad0), PH_SLEEP);
    drect(15, 62, 69, 63, H(0xe6e8eb), PH_SLEEP);
    drect(15, 98, 69, 99, H(0x9ea2a8), PH_SLEEP);
    drect(15, 62, 16, 99, H(0xb2b5bb), PH_SLEEP);
    drect(22, 70, 62, 91, H(0xf1f0ec), PH_SLEEP);
    drect(24, 73, 44, 74, H(0x4a4c50), PH_SLEEP);
    drect(24, 77, 52, 78, H(0x8d9197), PH_SLEEP);
    drect(24, 81, 40, 82, H(0x8d9197), PH_SLEEP);
    drect(52, 72, 60, 76, H(0xc8322a), PH_SLEEP);
    dline(18, 62, 18, 58, H(0xc8322a), DO_NONE);
    dline(20, 62, 20, 58, H(0x232226), DO_NONE);
}

/* what moves: the pointer; the battery's charge on its label; the module's light while
 * headphones are connected */
static void ph_live(app *a, gfx *g, uint32_t now)
{
    dio_close_light(a);
    g_clip(g, 0, 0, LCD_W, BAR_Y);
    int pct = plat_battery(), chg = plat_charging();
    if (pct >= 0) {
        int w = 36 * (pct > 100 ? 100 : pct) / 100;
        for (int x = 24; x < 60; x++) {
            int on = x < 24 + w, low = pct <= 15 && !chg;
            px16 hi = chg == 1 ? H(0xf08c1a) : low ? H(0xc8322a) : H(0x3f7a4c);
            px16 lo = chg == 1 ? H(0xb8650f) : low ? H(0x962220) : H(0x2f5d3a);
            dio_pt(g, x, 86, on ? hi : H(0xd9d8d2));
            dio_pt(g, x, 87, on ? lo : H(0xc9c8c2));
        }
    }
    if (a->bt_has && a->bt.link >= BTL_CONNECTED && (now / 500) % 2) dio_pt(g, 66, 29, H(0x4aa8ff));
    int sel = fx_clamp(a->gl.sel, 0, 7);
    const int16_t *b = PH_BB[sel];
    ck_pointer(g, 2 * b[0] - 8 < 0 ? 0 : 2 * b[0] - 8, b[1] + b[3], now, RP.walnut_d, RP.cream);
    txt_fit(a, g, F_BODY10, 10, 207, PH_SAYS[sel], 300, RP_DAY.cream, 0);
    g_noclip(g);
}

static void dio_h2(app *a, gfx *g, const mtile *tl, int sel)
{
    dio_close_light(a);
    ph_scene();
    dio_paint(g, PH_SLEEP + sel);
    const int cx = 170, cy = 70, cw = 142, ch = 82;
    dio_tag(g, cx, cy, cw, ch);
    txt_fit(a, g, F_SEMI12, cx + 10, cy + 19, tl[sel].label, cw - 20, RP.ink, 0);
    if (tl[sel].value) txt_fit(a, g, F_MONO12, cx + 10, cy + 37, tl[sel].value, cw - 20, RP.ink, 0);
    char lines[2][TEXT_LINE_MAX];
    int nl = text_wrap(F(a, F_BODY10), PH_PART[sel], cw - 20, 2, 0, lines);
    for (int i = 0; i < nl; i++) txt(a, g, F_BODY10, cx + 10, cy + 57 + 12 * i, lines[i], RP.sub, 0);
    dio_header(a, g, SEC_SETTINGS, "Settings", NULL);
    for (int y = 0; y < BAR_Y; y++) memcpy(dio_bg + y * LCD_W, g->px + y * g->stride, LCD_W * 2);
    dio_ok = 1;
    petl.live = 1;
    petl.view = V_SETTINGS;
    ph_live(a, g, a->now_ms);
    draw_nowbar(a, g);
}

/* between full frames: just what moves */
static void dio_h2_frame(app *a, gfx *g, int r[4])
{
    for (int y = 0; y < BAR_Y; y++) memcpy(g->px + y * g->stride, dio_bg + y * LCD_W, LCD_W * 2);
    ph_live(a, g, a->now_ms);
    r[0] = 0; r[1] = 0; r[2] = LCD_W; r[3] = BAR_Y;
}
