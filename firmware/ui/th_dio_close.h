/* Diorama, up close (part of app.c, after th_dio.h). Picking a thing on the desk moves the
 * camera in on it, and its page is that thing close up, under the desk's light. The case
 * opens on its parts and the Library's five sections are the parts -- the listener's own
 * (2026-10, a Fractal Terra, drawn from their photos: opened out like a book, the RTX 5080
 * Founders Edition one side of the spine, the Corsair SF850 and the Noctua cooler the other,
 * the board's drives and chipset on the spine): the Samsung 990 EVO holds the Songs, the
 * Ryzen 7 9800X3D under its Noctua the Artists, the B850I's chipset the Genres, the RTX 5080 the
 * Soundtracks, the Vengeance sticks the History, the WD_BLACK SN750 (the gaming drive) the
 * Games -- and picking one moves in again. Search
 * types on the keyboard's own keycaps, Explore's shelves are posters pinned to the wall,
 * the lists sit on what they're inside (the case's aluminium, the felt mat, the wall), and
 * the picked row wears the parchment tag the things on the desk wear. Back moves the camera
 * out to where you came from. */

/* ------------------------------------------------------------------ the camera
 * Into a thing: the screen as it was, scaled up about the thing's box, then the page shows
 * through. Out of one: the page fades into the thing close up, which pulls back to the
 * whole scene. Every frame of the move is a full one (app.c keeps drawing for 750 ms
 * after a page changes). */
#define DZ_MS 460
static struct { int kind, snap; uint32_t t0; float r[4]; } dz;      /* kind: 1 in, -1 out */
static px16 dz_old[LCD_W * LCD_H], dz_new[LCD_W * LCD_H];

enum { PT_SONGS = 20, PT_ARTISTS, PT_GENRES, PT_OSTS, PT_HISTORY, PT_GAMES };
static const int16_t PT_BB[N_LIB][4] = {       /* each part's box in the case, cells */
    { 76, 9, 85, 31 },                         /* the 990 EVO, on the spine */
    { 120, 15, 155, 70 },                      /* the Noctua on the 9800X3D */
    { 75, 57, 86, 71 },                        /* the B850I's chipset */
    { 5, 16, 73, 59 },                         /* the RTX 5080 */
    { 120, 6, 155, 14 },                       /* the Vengeance sticks, over the cooler */
    { 76, 33, 85, 55 },                        /* the SN750 */
};
/* the wheel goes round the case clockwise, as it goes round the desk: the 990 EVO at the
 * spine's top, the sticks, the Noctua, in down the spine past the SN750 to the chipset,
 * across to the card, and up again */
static const uint8_t DIO_LIB_ORDER[N_LIB] = { 0, 4, 1, 5, 2, 3 };

/* the thing on the desk a page belongs to (the home's items) */
static int dio_item_of(const app *a, int v)
{
    switch (v) {
    case V_WHEEL: return 0;
    case V_NOW: return 1;
    case V_QUEUE: case V_SAVED: return 2;
    case V_EXPLORE: return 3;
    case V_SEARCH: return 4;
    case V_TRACKS:
        return a->tracks_kind == TK_LIKED ? 6 : a->tracks_kind == TK_RESULTS ? 4 : a->tracks_kind == TK_SHELF ? 3 :
               a->tracks_kind == TK_SAVED ? 2 : 5;
    case V_SETTINGS: case V_CLOCK: case V_BT: case V_KEYS: return 7;
    default: return 5;                         /* the Library and what's in it */
    }
}

/* the part in the case a page belongs to, or -1 */
static int dio_part_of(const app *a, int v)
{
    switch (v) {
    case V_ARTISTS: return 1;
    case V_GENRES: return 2;
    case V_OST: return 3;
    case V_TRACKS: return a->tracks_kind == TK_SONGS ? 0 : a->tracks_kind == TK_HISTORY ? 4 : -1;
    case V_GAMES: return 5;
    default: return -1;
    }
}

/* a box (px) -> the screen-shaped one around it with some room, inside the screen, no
 * more than 4x */
static void dz_fit(float *r)
{
    const float A = (float)LCD_W / LCD_H;
    float cx = (r[0] + r[2]) / 2, cy = (r[1] + r[3]) / 2, w = (r[2] - r[0]) * 1.35f, h = (r[3] - r[1]) * 1.35f;
    if (w < h * A) w = h * A; else h = w / A;
    if (w < LCD_W / 4.0f) { w = LCD_W / 4.0f; h = w / A; }
    if (w > LCD_W) { w = LCD_W; h = LCD_H; }
    float x0 = cx - w / 2, y0 = cy - h / 2;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x0 + w > LCD_W) x0 = LCD_W - w;
    if (y0 + h > LCD_H) y0 = LCD_H - h;
    r[0] = x0; r[1] = y0; r[2] = x0 + w; r[3] = y0 + h;
}

/* a page change (app_event): which way the camera goes, and about what */
static void dio_nav(app *a, int from, int to)
{
    const int16_t *b = NULL;
    int kind = 0;
    if (from == V_MENU && to != V_MENU) { kind = 1; b = dio_bb[dio_item_of(a, to) + 1]; }
    else if (to == V_MENU && from != V_MENU) { kind = -1; b = dio_bb[dio_item_of(a, from) + 1]; }
    else if (from == V_LIBRARY && dio_part_of(a, to) >= 0) { kind = 1; b = PT_BB[dio_part_of(a, to)]; }
    else if (to == V_LIBRARY && dio_part_of(a, from) >= 0) { kind = -1; b = PT_BB[dio_part_of(a, from)]; }
    if (!kind || b[2] <= b[0]) { dz.kind = 0; return; }        /* the desk not drawn yet: no move */
    for (int i = 0; i < 4; i++) dz.r[i] = 2.0f * b[i];
    dz_fit(dz.r);
    dz.kind = kind;
    dz.t0 = a->now_ms;
    dz.snap = 1;
}

/* before a frame is drawn: on a page change, keep what's on the screen (the page left) */
static void dio_pre(gfx *g)
{
    if (!dz.snap) return;
    dz.snap = 0;
    for (int y = 0; y < LCD_H; y++) memcpy(dz_old + y * LCD_W, g->px + y * g->stride, LCD_W * 2);
}

/* src seen through the box b (px) and scaled to the screen, over what's drawn by k/256 */
static void dz_blit(gfx *g, const px16 *src, const float *b, int k)
{
    int32_t sx = (int32_t)((b[2] - b[0]) / LCD_W * 65536), sy = (int32_t)((b[3] - b[1]) / LCD_H * 65536);
    int32_t x0 = (int32_t)(b[0] * 65536), yy = (int32_t)(b[1] * 65536);
    for (int y = 0; y < LCD_H; y++, yy += sy) {
        int fy = yy >> 16;
        const px16 *s = src + (fy < LCD_H ? fy : LCD_H - 1) * LCD_W;
        px16 *d = g->px + y * g->stride;
        int32_t xx = x0;
        for (int x = 0; x < LCD_W; x++, xx += sx) {
            int fx = xx >> 16;
            px16 c = s[fx < LCD_W ? fx : LCD_W - 1];
            d[x] = k >= 256 ? c : blend565(d[x], c, k);
        }
    }
}

/* after the page is drawn: the move over it */
static void dio_post(app *a, gfx *g)
{
    if (!dz.kind) return;
    float t = (float)(a->now_ms - dz.t0), b[4];
    const float full[4] = { 0, 0, LCD_W, LCD_H };
    if (t >= DZ_MS) { dz.kind = 0; return; }
    if (dz.kind > 0) {                                   /* in: the old screen scales up, the page shows through */
        float u = dr_io(t / (DZ_MS * .8f));
        for (int i = 0; i < 4; i++) b[i] = full[i] + (dz.r[i] - full[i]) * u;
        dz_blit(g, dz_old, b, 256 - (int)(256 * ez_seg(t, DZ_MS * .45f, DZ_MS)));
        return;
    }
    for (int y = 0; y < LCD_H; y++) memcpy(dz_new + y * LCD_W, g->px + y * g->stride, LCD_W * 2);
    float u = dr_io(t / DZ_MS);                          /* out: the scene, from the thing to all of it */
    for (int i = 0; i < 4; i++) b[i] = dz.r[i] + (full[i] - dz.r[i]) * u;
    dz_blit(g, dz_new, b, 256);
    int k = 256 - (int)(256 * ez_seg(t, 0, DZ_MS * .3f));  /* the page you left, fading off it */
    if (k > 0)
        for (int y = 0; y < LCD_H; y++) {
            px16 *d = g->px + y * g->stride;
            const px16 *s = dz_old + y * LCD_W;
            for (int x = 0; x < LCD_W; x++) d[x] = blend565(d[x], s[x], k);
        }
}

/* ------------------------------------------------------------------ what the pages sit on */
enum { BK_WALL, BK_ALU, BK_FELT, BK_CUP, BK_PLATE, BK_LEAF };

static int dio_bk(int sec)
{
    switch (sec) {
    case SEC_LIBRARY: case SEC_SONGS: case SEC_ARTISTS: case SEC_GENRES: case SEC_OSTS: case SEC_HISTORY:
    case SEC_GAMES:
        return BK_ALU;                                   /* inside the case */
    case SEC_SEARCH: return BK_PLATE;                    /* inside the keyboard */
    case SEC_QUEUE: return BK_CUP;                       /* inside the headphones */
    case SEC_LIKED: return BK_LEAF;                      /* the pothos, up close */
    default: return BK_WALL;
    }
}

static px16 dio_bk_cell(int bk, int x, int y)
{
    uint32_t h = pet_hash((uint32_t)(x * 131 + y * 977));
    switch (bk) {
    case BK_ALU: {                                       /* brushed: a faint grain along it */
        uint32_t s = pet_hash((uint32_t)(y * 7919 + x / 37));
        return s % 9 == 0 ? H(0xc8c9c5) : h % 29 == 0 ? H(0xc6c7c3) : H(0xcccdc9);
    }
    case BK_FELT: return h % 7 == 0 ? H(0x9b9a95) : h % 11 == 0 ? H(0xb2b1ac) : H(0xa7a6a1);
    case BK_CUP: {                                       /* the white Scape's earcup: its cushion, the knit, the driver */
        int ex = x < 5 ? 5 - x : x > 154 ? x - 154 : 0, ey = y < 4 ? 4 - y : y > 101 ? y - 101 : 0, e = ex > ey ? ex : ey;
        if (e) return e > 3 ? H(0xbdbdb9) : e > 1 ? H(0xe9e9e6) : H(0xd6d6d2);
        float dx = x + .5f - 132, dy = y + .5f - 56, d = sqrtf(dx * dx + dy * dy);
        px16 c = ((x + (y >> 1)) & 3) == 0 ? H(0xc4c4c0) : H(0xcfcfcb);
        if (d < 46) {
            if (d > 44) c = H(0xb2b2ae);                                 /* the driver's rim */
            else if (d > 34) c = ((int)d & 1) ? H(0xc8c8c4) : H(0xbcbcb8);   /* the surround */
            else if (d > 13) c = d > 33 ? H(0xb6b6b2) : H(0xc6c6c2);    /* the cone */
            else c = d < 10 && dx < -2 && dy < -2 ? H(0xe2e2df) : H(0xd5d5d1);   /* the dome */
            if (((x ^ y) & 1) == 0 && d < 44) c = blend565(c, H(0x9a9a96), 70);   /* the mesh over it */
        }
        return c;
    }
    case BK_PLATE: {                                     /* the keyboard's plate, a switch in each hole */
        static const int8_t off[6] = { 0, 4, 6, 9, 3, 0 };
        int row = y / 10, ry = y % 10, rx = (x + off[row % 6]) % 10;
        px16 c = pet_hash((uint32_t)(y * 7919 + x / 41)) % 9 == 0 ? H(0xbcbdb9) : H(0xc4c5c1);
        if (rx >= 1 && rx <= 8 && ry >= 1 && ry <= 8) {                  /* faint: lists sit on it */
            c = rx == 1 || ry == 1 ? H(0xb3b4b0) : H(0xbabbb7);
            if ((rx == 4 || rx == 5) && (ry == 4 || ry == 5)) c = H(0xc7aaa5);   /* the stem */
        }
        return c;
    }
    case BK_LEAF: {                                      /* a golden pothos leaf: midrib, veins, gold streaks */
        float u = (x - 10) * .8f + (106 - y) * .6f, v = (10 - x) * .6f + (106 - y) * .8f, av = fabsf(v);
        float t = u / 205, w = t > 0 && t < 1 ? 66 * sqrtf(sinf(3.1416f * t)) : 0;   /* its outline */
        if (av > w) return pet_hash((uint32_t)(x * 131 + y * 977)) % 5 == 0 ? H(0x86ad62) : H(0x7ea65a);
        if (av > w - 1.5f) return H(0x9cbf74);
        px16 c = H(0xb8cf8c);
        if (pet_hash((uint32_t)((int)(u / 6) * 131 + (int)((v + 200) / 3))) % 7 == 0) c = H(0xd6d69a);
        if (dmod(u - av * .9f, 16) < 1.0f && av > 2) c = H(0xcadc9e);
        if (av < 1.5f) c = H(0xdfe8b8);
        else if (av < 2.5f) c = H(0xa9c27c);
        return c;
    }
    default: return h % 19 == 0 ? DC_WALL2 : DC_WALL;
    }
}

/* the light on a close-up: the room's, the lamp from the right after dark */
static void dio_close_light(app *a)
{
    dio_lights(a->cur_valid && a->ps.playing);
    dl.close = 1;
}

static void dio_clock_page(app *a, gfx *g);                  /* th_dio_in.h */

/* what a close-up page sits on, lit, drawn once and kept until the light or the page's
 * surface changes (the H2 has no float unit: the leaf or the earcup cell by cell, every
 * frame, made the lists drag). One screen's worth, shared with the clock (th_dio_in.h) */
static px16 in_bg[LCD_W * LCD_H];
static int in_key = -1;
static const int PO_X[2] = { 5, 83 }, PO_Y = 19;     /* Explore's posters, cells */

static void dio_page(app *a, gfx *g)
{
    if (a->view == V_MENU || a->view == V_LIBRARY) return;    /* the desk, the case: drawn whole */
    if (a->view == V_WHEEL) { dio_clock_page(a, g); return; } /* inside the clock */
    if (a->view == V_WHEEL || a->view == V_NOW || a->view == V_CLOCK || a->view == V_BT) { px_page(a, g); return; }
    int bk = dio_bk(view_sec(a));
    dio_close_light(a);
    int posters = a->view == V_EXPLORE && a->cr[CK_EXPLORE].n == 2;   /* its two shelves: the posters */
    int key = 0x10000 | posters << 15 | bk << 12 | rp_k;
    if (key != in_key) {
        gfx b;
        g_init(&b, in_bg, LCD_W, LCD_H, LCD_W);
        for (int y = 0; y < DH; y++)
            for (int x = 0; x < DW; x++) ck_point(&b, x, y, dio_lit(dio_bk_cell(bk, x, y), x, y));
        for (int s = 0; posters && s < 2; s++) {
            const char *map = s ? &PO_HK[0][0] : &PO_SK[0][0];
            const px16 *pal = s ? PO_HK_PAL : PO_SK_PAL;
            int x0 = PO_X[s], st = (int)sizeof PO_SK[0];
            for (int y = 0; y < 84; y++)                 /* its shadow on the wall, then it */
                for (int x = 0; x < 72; x++) {
                    int sx = x0 + x + 1, sy = PO_Y + y + 1;
                    if (x == 71 || y == 83) ck_point(&b, sx, sy, dio_lit(blend565(dio_bk_cell(bk, sx, sy), 0, 90), sx, sy));
                    char c = map[y * st + x];
                    ck_point(&b, x0 + x, PO_Y + y, dio_lit(pal[c <= '9' ? c - '0' : c - 'a' + 10], x0 + x, PO_Y + y));
                }
        }
        in_key = key;
    }
    for (int y = 0; y < 2 * DH; y++) memcpy(g->px + y * g->stride, in_bg + y * LCD_W, LCD_W * 2);
}

/* ------------------------------------------------------------------ the header: the thing's tag */
/* each section's thing, small (10 x 9 cells) */
static const char *const DS_SSD[9] = { "..........", "..........", "..........", "gkkkkkkkkk", "gkwwwwkKks",
                                       "gkkkkkkkkk", "..........", "..........", ".........." };
static const char *const DS_CPU[9] = { ".KKKKKKKK.", ".KSSSSSSK.", ".KSssssSK.", ".KSssssSK.", ".KSssssSK.",
                                       ".KSssssSK.", ".KgSSSSSK.", ".KKKKKKKK.", ".........." };
static const char *const DS_SINK[9] = { ".KKKKKKKK.", ".KssssssK.", ".KKKKKKKK.", ".KsssysK..", ".KKKyyKKK.",
                                        ".KssysssK.", ".KKKKKKKK.", ".KssssssK.", ".KKKKKKKK." };
static const char *const DS_GPU[9] = { "SSSSSSSSSS", "kkkkkkkkkk", "kKKKkkKKKk", "KkskKKksKK", "kKKKkkKKKk",
                                       "kkkkkkkkkk", ".g......g.", "..........", ".........." };
static const char *const DS_RAM[9] = { "..........", "..........", "wkkkkkkkkw", "wkkWWkkkkw", "wkkkkkkkkw",
                                       ".gggggggg.", "..........", "..........", ".........." };
static const char *const DS_CASE[9] = { ".SSSSSSS..", ".SwwwwwS..", ".SwWwWwS..", ".SwwwwwS..", ".SwWwWwS..",
                                        ".SwwwwwS..", ".SwwwwwS..", ".uuuuuuu..", ".........." };
static const char *const DS_KEY[9] = { "..........", ".WWWWWWWW.", ".WwwwwwwW.", ".WwwkkwwW.", ".WwkwwkwW.",
                                       ".WwkkkkwW.", ".WWWWWWWW.", ".KKKKKKKK.", ".........." };
static const char *const DS_POSTER[9] = { ".nnnnnnnn.", ".nwnnnnwn.", ".nwwnnwwn.", ".nwwwwwwn.", ".nwkwwkwn.",
                                          ".nwkwwkwn.", ".nnwwwwnn.", ".nnnnnnnn.", ".........." };
static const char *const DS_PHONES[9] = { "...WWWW...", "..W....W..", ".W......W.", ".W......W.", "ww......ww",
                                          "ww......ww", "ww......ww", "..........", ".........." };
static const char *const DS_LEAF[9] = { "....l.....", "...lLl....", "..lLLLl...", "..lLdLl...", "..lLdLl...",
                                        "...ldl....", "....d.....", "....d.....", ".........." };
static const char *const DS_H2[9] = { "..SSSSSS..", "..SnnnnS..", "..SnnnnS..", "..SSSSSS..", "..SSKKSS..",
                                      "..SKSSKS..", "..SSKKSS..", "..SSSSSS..", ".........." };
static const char *const DS_CLOCK[9] = { "...WWWW...", "..WwwwwW..", ".WwwwkwwW.", ".Wwwwkwww.", ".WwwwkkkW.",
                                         ".WwwwwwwW.", "..WwwwwW..", "...WWWW...", ".........." };
static const char *const DS_MON[9] = { "kkkkkkkkkk", "knnnnnnnnk", "knnnnnnnnk", "knnnnnnnnk", "kkkkkkkkkk",
                                       "....kk....", "...kkkk...", "..........", ".........." };

static void dio_spr(gfx *g, int x0, int y0, int sec)
{
    const char *const *m;
    switch (sec) {
    case SEC_SONGS: case SEC_GAMES: m = DS_SSD; break;
    case SEC_ARTISTS: m = DS_CPU; break;
    case SEC_GENRES: m = DS_SINK; break;
    case SEC_OSTS: m = DS_GPU; break;
    case SEC_HISTORY: m = DS_RAM; break;
    case SEC_LIBRARY: m = DS_CASE; break;
    case SEC_SEARCH: m = DS_KEY; break;
    case SEC_EXPLORE: m = DS_POSTER; break;
    case SEC_QUEUE: case SEC_BT: m = DS_PHONES; break;
    case SEC_LIKED: m = DS_LEAF; break;
    case SEC_WHEEL: case SEC_CLOCK: m = DS_CLOCK; break;
    case SEC_NOW: m = DS_MON; break;
    default: m = DS_H2; break;
    }
    static const char K[] = "kKsSwWgynlLduo";
    const px16 C[] = { H(0x1f2023), H(0x45484d), H(0xb9bcc0), H(0xdfe1e3), DC_WHITE, H(0xc9c8c2), H(0xc9a64a),
                       H(0xe8b84a), DC_NAVY, RP_DAY.leaf, RP_DAY.leaf_l, RP_DAY.leaf_d, H(0x6b4a32), H(0xe2732a) };
    for (int r = 0; r < 9; r++)
        for (int q = 0; m[r][q]; q++) {
            const char *k = strchr(K, m[r][q]);
            if (k && m[r][q] != '.') ck_point(g, x0 + q, y0 + r, nightc(C[k - K]));
        }
}

/* a parchment tag (the desk's): its walnut edge, px */
static void dio_tag(gfx *g, int x, int y, int w, int h)
{
    g_fill_a(g, x + 2, y + 2, w, h, C565(0, 0, 0), 60);
    g_fill(g, x, y, w, h, RP.walnut_d);
    g_fill(g, x + 1, y + 1, w - 2, h - 2, RP.parch);
}

static void dio_header(app *a, gfx *g, int sec, const char *title, const char *right)
{
    char t[64];
    snprintf(t, sizeof t, "%s", title);
    int tw = text_w(F(a, F_SEMI12), t, 0);
    if (tw > 170) tw = 170;
    dio_tag(g, 3, 3, 36 + tw + 10, 24);
    dio_spr(g, 5, 4, sec);
    txt_fit(a, g, F_SEMI12, 36, 20, t, 170, RP.ink, 0);
    int bl = px_battery(a, g, LCD_W - 8, 17, sec == SEC_LIBRARY ? RP_DAY.cream : RP.wink);
    px_time(a, g, bl - 10, 17, sec == SEC_LIBRARY ? RP_DAY.cream : RP.wink);
    if (right) txt_right(a, g, F_MONO10, LCD_W - 60, 17, right, RP.wsub);
}

/* ------------------------------------------------------------------ rows, labels, buttons */
static row_ink dio_row(app *a, gfx *g, int y, int h, int state)
{
    row_ink k = { RP.wink, RP.wsub, RP.wsub, RP.wacc, 0 };
    if (state & ROW_FOCUS) {                             /* the parchment tag, sliding to it */
        float cy = cursor_y(a, y);
        int top = (int)lrintf(cy);
        dio_tag(g, 6, top + 1, LCD_W - 14, h - 2);
        if (state & ROW_ADJ) g_fill(g, 7, top + 2, 4, h - 4, H(0xe2732a));
        ck_pointer(g, 0, top + h / 2, a->now_ms, RP.walnut_d, RP.cream);
        if (cy > y - 8 && cy < y + 8) { k.fg = RP.ink; k.sub = RP.sub; k.note = RP.ink; k.accent = RP.ink; k.on = 1; }
        return k;
    }
    if (state & ROW_LIVE) g_fill(g, 4, y + 5, 3, h - 10, H(0xe2732a));   /* what's on: the orange key */
    g_fill_a(g, 10, y + h - 1, LCD_W - 20, 1, C565(0, 0, 0), 34);         /* a seam under the row */
    if (state & ROW_DIM) k.fg = RP.wsub;
    return k;
}

static void dio_label(app *a, gfx *g, int x, int yb, const char *s, px16 c, int big, int maxw)
{
    txt_fit(a, g, big ? F_SEMI12 : F_SEMI11, x, big ? yb - 4 : yb, s, maxw, c, 0);
}

/* a keycap like the keyboard's: its top, its side below, an edge; px */
static void dio_cap(gfx *g, int x, int y, int w, int h, px16 top, px16 side)
{
    g_fill_a(g, x + 1, y + 2, w, h, C565(0, 0, 0), 70);
    g_fill(g, x, y, w, h, nightc(H(0x6d6c67)));
    g_fill(g, x + 1, y + 1, w - 2, h - 2, nightc(side));
    g_fill(g, x + 2, y + 1, w - 4, h - 5, nightc(top));
}

static void dio_button(app *a, gfx *g, int x, int y, int w, int h, int sym, const char *label, int foc, int kind)
{
    (void)kind;
    px16 top = foc ? H(0xe2732a) : DC_WHITE, side = foc ? H(0xa8501c) : H(0xc9c8c2);
    px16 ink = foc ? DC_WHITE : H(0x3a3a40);
    dio_cap(g, x + 4, y, w - 4, h, top, side);
    int s = h - 12;
    ck_sym(g, sym, x + 14 + s / 2, y + (h - 3) / 2, s, nightc(ink), nightc(top), 0, 1);
    txt_fit(a, g, F_SEMI11, x + 22 + s, y + h / 2 + 2, label, w - s - 30, nightc(ink), 0);
    if (foc) ck_pointer(g, 0, y + h / 2, a->now_ms, RP.walnut_d, RP.cream);
}

/* Search's letters, on keycaps: letters white, space the yellow bar, delete a grey
 * modifier, "to the results" the orange enter; the one you're on stands up */
static void dio_key(app *a, gfx *g, int x, int y, int w, int h, const char *label, int special, int foc, int dist)
{
    int sym = !(label && label[0]);
    px16 top = DC_WHITE, side = H(0xc9c8c2), ink = H(0x3a3a40);
    if (sym && special == 1) { top = H(0xe8b84a); side = H(0xb98e33); }
    else if (sym && special == 2) { top = H(0xbdbcb6); side = H(0x8d8c86); }
    else if (sym) { top = H(0xe2732a); side = H(0xa8501c); ink = DC_WHITE; }
    int up = foc ? 3 : 0;
    if (foc) {
        g_fill(g, x - 3, y - up - 3, w + 6, h + 6, RP.walnut_d);
        g_fill(g, x - 2, y - up - 2, w + 4, h + 4, RP.cream);
    }
    dio_cap(g, x, y - up, w, h, top, side);
    if (dist > 3) ink = blend565(ink, top, 120);
    if (!sym) {
        int lw = text_w(F(a, F_SEMI12), label, 0);
        txt(a, g, F_SEMI12, x + (w - lw) / 2, y - up + h / 2 + 2, label, nightc(ink), 0);
    } else
        ck_sym(g, special == 1 ? SYM_STOP : special == 2 ? SYM_PREV : SYM_NOW, x + w / 2, y - up + (h - 3) / 2, 12,
               nightc(ink), nightc(top), 0, 1);
}

/* Explore: each shelf is a row of prints pinned to the wall, its name on the left */
static void dio_prints(app *a, gfx *g, int y0, int h, const char *name, const char *sub, const char *count,
                       const uint32_t *items, int n, int foc)
{
    if (foc) {
        int w = text_w(F(a, F_SEMI12), name, 0) + 14;
        dio_tag(g, 6, y0 + 4, w > 124 ? 124 : w, 20);
        ck_pointer(g, 0, y0 + 14, a->now_ms, RP.walnut_d, RP.cream);
    }
    txt_fit(a, g, F_SEMI12, 12, y0 + 18, name, 112, foc ? RP.ink : RP.wink, 0);
    char lines[2][TEXT_LINE_MAX];
    int nl = text_wrap(F(a, F_BODY10), sub, 116, 2, 0, lines);
    for (int i = 0; i < nl; i++) txt(a, g, F_BODY10, 12, y0 + 34 + 11 * i, lines[i], RP.wsub, 0);
    char c[24];
    snprintf(c, sizeof c, "%s songs", count);
    if (nl < 2) txt(a, g, F_MONO10, 12, y0 + 34 + 11 * nl, c, RP.wsub, 0);
    int ps = h - 14;
    if (ps > 42) ps = 42;
    int py = y0 + (h - ps) / 2 + 1 - (foc ? 1 : 0);
    for (int i = 0, x = 136; i < n && x + ps <= LCD_W - 4; i++, x += ps + 5) {
        g_fill_a(g, x + 2, py + 3, ps, ps, C565(0, 0, 0), foc ? 90 : 60);
        g_fill(g, x, py, ps, ps, nightc(H(0xf2efe7)));                  /* the print's white edge */
        cover(a, g, items[i], ART_S, x + 2, py + 2, ps - 4);
        g_fill_a(g, x + ps / 2 - 6, py - 3, 12, 6, nightc(H(0xe6dcc0)), 200);  /* a bit of tape */
    }
}

/* ------------------------------------------------------------------ the Library: inside the case */
static void pc_scene(void)
{
    const px16 BLK = H(0x17181b), BLK2 = H(0x232428), ALU = H(0xc4c6c4), ALU3 = H(0xdfe1df),
               BEIGE = H(0xd8cdb6), BEIGE2 = H(0xb9ab90), BROWN = H(0x7a5440), NICKEL = H(0xd3d6da),
               NICKEL2 = H(0xa4a8ae), RED = H(0xa82c38), RED2 = H(0x7c1f2a);
    /* the desk under it, the case's floor; the case: its aluminium, its walnut front */
    drect(0, 0, DW, DH, H(0x2a1d14), DO_NONE);
    for (int y = 82; y < DH; y += 3)
        for (int x = (y * 5) % 9; x < DW; x += 9 + y % 4) drect(x, y, x + 5, y + 1, H(0x34251a), DO_NONE);
    drect(0, 0, DW, 80, ALU, DO_NONE);
    drect(0, 0, DW, 1, ALU3, DO_NONE);
    drect(0, 6, 4, 80, RP_DAY.walnut, DO_NONE);                     /* the walnut front */
    for (int y = 9; y < 78; y += 5) drect(1, y, 3, y + 2, RP_DAY.walnut_l, DO_NONE);
    drect(4, 6, 157, 78, BLK, DO_NONE);
    drect(4, 78, 157, 80, H(0x0f1012), DO_NONE);
    /* the side panel, hinged up: its slots, its two hinges */
    for (int x = 8; x < 152; x += 3) drect(x, 1, x + 1, 5, H(0x55575a), DO_NONE);
    drect(18, 4, 26, 7, H(0x111214), DO_NONE);
    drect(134, 4, 142, 7, H(0x111214), DO_NONE);
    /* the GPU's side: the riser over it, the card, a Noctua under it, the cables */
    drect(8, 9, 62, 13, RED, DO_NONE);
    drect(8, 12, 62, 13, RED2, DO_NONE);
    for (int x = 12; x < 60; x += 6) drect(x, 10, x + 3, 11, H(0x8f2230), DO_NONE);
    drect(56, 8, 63, 14, BLK2, DO_NONE);
    /* the RTX 5080 Founders Edition: black, its fins either side, the silver X */
    drect(5, 16, 73, 59, H(0x1b1c1f), PT_OSTS);
    drect(5, 16, 73, 17, H(0x3a3c40), PT_OSTS);
    drect(5, 58, 73, 59, H(0x0e0f11), PT_OSTS);
    for (int y = 17; y < 58; y++)
        for (int x = 6; x < 72; x++) {
            float u = (x - 5) / 68.0f, v = (y - 16) / 43.0f;          /* across the card, 0..1 */
            float bow = .06f * (1 - 4 * (u - .5f) * (u - .5f));        /* the arms bow outwards */
            float a1 = u * .86f + .07f, a2 = (1 - u) * .86f + .07f;    /* where each arm crosses this column */
            float d1 = fabsf(v - a1 + (u < .5f ? bow : -bow)), d2 = fabsf(v - a2 + (u < .5f ? -bow : bow));
            int lobe = u < .5f ? (v > a1 && v < a2) : (v < a1 && v > a2);
            float c = fabsf(u - .5f) * 2;                              /* 0 at the crossing */
            if (d1 < .05f || d2 < .05f) {
                px16 m = (d1 < .02f || d2 < .02f) ? (c < .35f ? H(0xf4f6f8) : H(0xd3d6da)) : H(0x8d9197);
                dp(x, y, m, PT_OSTS);
            } else if (lobe) {                                         /* the fins, their edge */
                float e = d1 < d2 ? d1 : d2;
                dp(x, y, e < .09f ? H(0x0e0f11) : x & 1 ? H(0x3d3f44) : H(0x1c1d20), PT_OSTS);
            }
        }
    drect(5, 16, 6, 59, H(0x4a4c50), PT_OSTS);
    drect(8, 62, 70, 64, H(0x101113), DO_NONE);                       /* its cables */
    for (int k = 0; k < 3; k++) dline(10 + k * 7, 64, 30 + k * 9, 75, H(0x26282c), DO_NONE);
    drect(40, 65, 72, 77, BEIGE, DO_NONE);                            /* a Noctua under it */
    drect(42, 67, 70, 76, H(0x1d1e21), DO_NONE);
    ddisc(56, 71.5f, 2.6f, BEIGE2, DO_NONE);
    /* the spine: the board's back -- the two drives, the chipset under its heatsink */
    drect(74, 6, 87, 78, H(0x1d1f23), DO_NONE);
    drect(74, 6, 75, 78, H(0x2e3035), DO_NONE);
    drect(86, 6, 87, 78, H(0x0e0f11), DO_NONE);
    for (int y = 8; y < 78; y += 9) { dp(75, y, H(0xb9bcc0), DO_NONE); dp(85, y, H(0xb9bcc0), DO_NONE); }
    /* Songs: the 990 EVO */
    drect(77, 9, 84, 31, H(0x161719), PT_SONGS);
    drect(78, 12, 83, 27, H(0x25272c), PT_SONGS);
    drect(79, 13, 82, 20, H(0xe8e8e6), PT_SONGS);                     /* SAMSUNG */
    drect(79, 22, 81, 25, H(0x6f8fc8), PT_SONGS);
    for (int x = 78; x < 84; x += 2) dp(x, 30, H(0xc9a64a), PT_SONGS);
    ddisc(80.5f, 10.5f, 1.4f, H(0xb9bcc0), PT_SONGS);
    /* Games: the SN750, the gaming drive */
    drect(77, 33, 84, 55, H(0x111214), PT_GAMES);
    drect(78, 36, 83, 51, H(0x1c1d21), PT_GAMES);
    drect(79, 37, 82, 43, H(0xe8e8e6), PT_GAMES);                     /* WD_BLACK */
    drect(79, 45, 81, 48, H(0x9fa6b2), PT_GAMES);
    for (int x = 78; x < 84; x += 2) dp(x, 54, H(0xc9a64a), PT_GAMES);
    ddisc(80.5f, 34.5f, 1.4f, H(0xb9bcc0), PT_GAMES);
    /* Genres: the B850I's chipset, its heatsink */
    drect(76, 57, 86, 71, H(0x383b40), PT_GENRES);
    drect(76, 57, 86, 58, H(0x5a5e64), PT_GENRES);
    for (int y = 59; y < 70; y += 2) drect(77, y, 85, y + 1, H(0x4b4f55), PT_GENRES);
    drect(78, 62, 84, 66, H(0x8d9197), PT_GENRES);
    /* the CPU's side: the SF850, its cables, the Noctua on the floor */
    drect(89, 15, 119, 57, H(0x1a1b1e), DO_NONE);
    drect(89, 15, 119, 16, H(0x3a3c40), DO_NONE);
    for (int y = 17; y < 56; y++)                                     /* its pattern of triangles */
        for (int x = 90; x < 118; x++)
            if ((y % 6 == 0) || ((x + y) % 6 == 0 && (y / 6) % 2 == 0) || ((x - y + 60) % 6 == 0 && (y / 6) % 2))
                dp(x, y, H(0x26272b), DO_NONE);
    static const char *const SAIL[5] = { "w....", "ww...", "wwww.", "wwwww", ".www." };
    const px16 wc[1] = { H(0x9a9da2) };
    dmap(102, 33, SAIL, 5, "w", wc, DO_NONE);
    for (int c = 0; c < 4; c++) ddisc(c & 1 ? 116.5f : 91.5f, c & 2 ? 54.5f : 17.5f, .9f, H(0x55585e), DO_NONE);
    for (int k = 0; k < 5; k++) dline(90 + k * 6, 58, 96 + k * 5, 62, H(0x2a2c30), DO_NONE);
    drect(88, 58, 119, 60, H(0x111214), DO_NONE);
    drect(89, 62, 119, 77, BEIGE, DO_NONE);
    drect(89, 62, 119, 63, H(0xe8dfcb), DO_NONE);
    drect(91, 64, 117, 76, H(0x1d1e21), DO_NONE);
    for (int c = 0; c < 4; c++) dp(c & 1 ? 117 : 90, c & 2 ? 75 : 63, BEIGE2, DO_NONE);
    /* Artists: the Noctua on the 9800X3D -- its fan to the side, the nickel fins, six heat pipes */
    drect(120, 15, 125, 70, BEIGE, PT_ARTISTS);
    drect(121, 17, 124, 68, BROWN, PT_ARTISTS);
    for (int y = 19; y < 68; y += 7) drect(121, y, 124, y + 1, BEIGE2, PT_ARTISTS);
    for (int x = 125; x < 155; x++) drect(x, 18, x + 1, 70, x & 1 ? NICKEL : NICKEL2, PT_ARTISTS);
    for (int y = 30; y < 66; y += 12) drect(129, y, 151, y + 3, H(0x6e7278), PT_ARTISTS);   /* the notches */
    for (int k = 0; k < 6; k++) {
        ddisc(128.5f + k * 4.8f, 16.5f, 1.4f, H(0xeef0f2), PT_ARTISTS);
        dp(128 + (int)(k * 4.8f), 16, H(0x8d9197), PT_ARTISTS);
    }
    drect(125, 69, 155, 70, H(0x6e7278), PT_ARTISTS);
    /* History: the Vengeance sticks, their tops over the cooler */
    for (int k = 0; k < 2; k++) {
        int y = 7 + k * 4;
        drect(121, y, 155, y + 3, H(0x1f2124), PT_HISTORY);
        drect(121, y, 155, y + 1, H(0x3d4046), PT_HISTORY);
        drect(128, y + 1, 145, y + 2, H(0xbfc2c6), PT_HISTORY);     /* VENGEANCE */
    }
}

static const char *const PT_PART[N_LIB] = { "Samsung 990 EVO, 2 TB", "AMD Ryzen 7 9800X3D, under its Noctua",
                                            "ASRock B850I Lightning WiFi", "NVIDIA GeForce RTX 5080",
                                            "Corsair Vengeance DDR5, 2 x 16 GB", "WD_BLACK SN750, 500 GB" };
static const char *const PT_SAYS[N_LIB] = { "Every song on the card. Play: all of them, A to Z.",
                                            "The people who made them, A to Z.",
                                            "What kind of music, sorted.",
                                            "The games and films, series by series.",
                                            "What you've played, newest first.",
                                            "Beat Orbit and the Fishing Hole, for the wheel." };

/* blades, turning (cells about cx, cy) */
static void pc_blades(gfx *g, float cx, float cy, float r, float rot)
{
    for (int y = (int)(cy - r); y <= (int)(cy + r); y++)
        for (int x = (int)(cx - r); x <= (int)(cx + r); x++) {
            float dx = x + .5f - cx, dy = y + .5f - cy, d2 = dx * dx + dy * dy;
            if (d2 < 3.6f * 3.6f || d2 > r * r) continue;
            float u = datan2(dy, dx) / 6.2832f * 7 + rot * 7 + sqrtf(d2) * .09f;
            float f = u - floorf(u);
            if (f < .55f) dio_pt(g, x, y, f < .14f ? H(0x7a7e84) : H(0x50545a));
        }
}

/* what moves in the case: the fans (the card's stand still until there's music, like the
 * real one's), Bubloo on top when he's asleep there, the pointer */
static void pc_live(app *a, gfx *g, uint32_t now)
{
    float t = now / 1000.0f, T = life_ms(now) / 1000.0f;
    int playing = a->cur_valid && a->ps.playing;
    uint8_t bands[12];
    float bass = playing && plat_spectrum(bands) ? (bands[0] + bands[1] + bands[2]) / 765.0f : 0;
    dio_close_light(a);
    g_clip(g, 0, 0, LCD_W, BAR_Y);
    pc_blades(g, 104, 69.5f, 6.6f, t * (playing ? .22f + .1f * bass : .12f));   /* the Noctua on the floor */
    pc_blades(g, 56, 71.5f, 5.2f, -t * (playing ? .2f + .1f * bass : .1f));      /* and the one under the card */
    dep e = life_at(T);
    if (e.spot == SP_CASE && (e.act == AC_CURL || e.act == AC_LOAF || e.act == AC_NAP) && T - e.t0 > 8) {
        dpose p;                                          /* him on top, seen from the side: belly, mitts, tail */
        memset(&p, 0, sizeof p);
        p.pose = DP_LOAF; p.x = 118; p.y = 6; p.tail = 1; p.t = T; p.swing = .2f;
        p.inhale = dmod(T, 3.6f) < 1.5f;
        dio_cat_draw(g, &p);
    }
    int sel = fx_clamp(a->ls[V_LIBRARY].sel, 0, N_LIB - 1);
    const int16_t *b = PT_BB[sel];
    ck_pointer(g, 2 * b[0] - 8 < 0 ? 0 : 2 * b[0] - 8, b[1] + b[3], now, RP.walnut_d, RP.cream);
    char line[96];
    if (now - a->poke_ms > 9000 && e.spot == SP_CASE && e.act != AC_AWAY)
        snprintf(line, sizeof line, "Bubloo is asleep on top of the case. It's warm.");
    else snprintf(line, sizeof line, "%s", PT_SAYS[sel]);
    txt_fit(a, g, F_BODY10, 10, 205, line, 300, RP_DAY.cream, 0);
    g_noclip(g);
}

static void dio_pc(app *a, gfx *g, const mtile *tl, int sel)
{
    dio_close_light(a);
    dio_screen_on = 1;
    pc_scene();
    dio_paint(g, PT_SONGS + sel);
    txt(a, g, F_MONO10, 55, 109, "RTX 5080", dio_lit(H(0x8d9197), 39, 54), 0);
    /* along the desk under it: the section, how many, the part it's in */
    int w = txt(a, g, F_SEMI12, 10, 178, tl[sel].label, RP_DAY.cream, 0);
    if (tl[sel].value) txt(a, g, F_MONO12, 10 + w + 10, 178, tl[sel].value, H(0xe8b84a), 0);
    txt_fit(a, g, F_BODY10, 10, 192, PT_PART[sel], 300, H(0xbfb4a4), 0);
    dio_header(a, g, SEC_LIBRARY, "Library", NULL);
    for (int y = 0; y < BAR_Y; y++) memcpy(dio_bg + y * LCD_W, g->px + y * g->stride, LCD_W * 2);
    dio_ok = 1;
    petl.live = 1;
    petl.view = V_LIBRARY;
    pc_live(a, g, a->now_ms);
    draw_nowbar(a, g);
}

/* ------------------------------------------------------------------ Now playing, on the monitor
 * Picking the monitor moves the camera into it, so the page is its screen (2026-10-18; the
 * listener: song names cut off on the monitor and on Room's Now playing, which Diorama used,
 * "we have lots of room on screen, show the full song name and other details"): the cover, the
 * title whole -- the biggest type it fits in, down to small over six lines -- the artist, the
 * genre; how far in; why it's on; what you know about it (liked, how often you've played it,
 * its tempo, the colour the wall is in for it); what's next. The bezel round it, the power
 * light under it, as on the desk. */
static void dio_chip(app *a, gfx *g, int *x, int y, const char *s, px16 swatch, px16 swatch2)
{
    int w = text_w(F(a, F_BODY10), s, 0) + (swatch ? 26 : 14) + (swatch2 ? 9 : 0);
    if (*x + w > LCD_W - 14) return;                         /* no room left on the row */
    g_fill(g, *x, y, w, 16, H(0x2b3448));
    g_fill(g, *x, y, w, 1, H(0x3a4560));
    int tx = *x + 7;
    if (swatch) { g_fill(g, tx, y + 4, 8, 8, swatch); tx += 12; }
    if (swatch2) { g_fill(g, tx - 3, y + 4, 8, 8, swatch2); tx += 9; }
    txt(a, g, F_BODY10, tx, y + 12, s, H(0xdfe5ef), 0);
    *x += w + 6;
}

static int dio_now(app *a, gfx *g)
{
    const px16 SCR = H(0x1f2636), INK = H(0xf4eee2), SUB = H(0x9aa7bd), ACC = H(0x9fb8dc), GRN = H(0x74b14b);
    g_noclip(g);
    g_fill(g, 0, 0, LCD_W, LCD_H, H(0x141416));                /* the bezel */
    g_fill(g, 5, 5, LCD_W - 10, LCD_H - 14, SCR);
    g_fill(g, LCD_W / 2 - 1, LCD_H - 5, 3, 2, RM_RED_);        /* the power light */
    const lib_track *t = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    txt(a, g, F_MONO10, 14, 20, !t ? "> nothing on" : a->ps.playing ? "> now playing" : "> paused", GRN, 0);
    px_battery(a, g, LCD_W - 14, 17, SUB);
    if (!t) {
        txt(a, g, F_POSTER15, 14, 60, "Nothing on.", INK, T_TRACK(-3));
        txt(a, g, F_BODY10, 14, 78, "Spin the wheel and press play.", SUB, 0);
        return 1;
    }
    /* the cover, and beside it the words, as big as they'll go */
    const int cs = 112, cx = 14, cy = 28, x0 = cx + cs + 12, w = LCD_W - 14 - x0;
    g_fill(g, cx - 1, cy - 1, cs + 2, cs + 2, H(0x0e1118));
    cover(a, g, a->cur, ART_M, cx, cy, cs);
    static const int fonts[3] = { F_POSTER15, F_BOLD11, F_BODY10 }, maxl[3] = { 3, 5, 7 };
    char lines[7][TEXT_LINE_MAX];
    int nl, f = fit_wrap(a, fonts, maxl, 3, t->title, w, lines, &nl);
    int lh = f == F_POSTER15 ? 17 : f == F_BOLD11 ? 13 : 12, y = cy + (f == F_POSTER15 ? 14 : 11);
    for (int k = 0; k < nl; k++)
        txt(a, g, f, x0, y + lh * k, lines[k], INK, f == F_POSTER15 ? T_TRACK(-3) : 0);
    y += lh * (nl - 1) + 17;
    char al[2][TEXT_LINE_MAX];
    int na = text_wrap(F(a, F_SEMI12), t->artist, w, 2, 0, al);
    for (int k = 0; k < na; k++) txt(a, g, F_SEMI12, x0, y + 14 * k, al[k], ACC, 0);
    y += 14 * (na - 1) + 14;
    if (t->genre[0] && y < cy + cs + 4) txt_fit(a, g, F_BODY10, x0, y, t->genre, w, SUB, 0);
    /* how far in */
    uint32_t len = a->ps.length_ms ? a->ps.length_ms : (uint32_t)t->dur * 1000u, at = a->ps.elapsed_ms;
    int seeking = a->seek_ms && a->now_ms - a->seek_ms < 1500;
    if (seeking) at = a->seek_to;
    char e[16], tot[16];
    mmss(e, sizeof e, at / 1000);
    mmss(tot, sizeof tot, len / 1000);
    int py = cy + cs + 18, bx0 = 54, bx1 = LCD_W - 54;
    txt(a, g, F_MONO10, 14, py + 4, e, seeking ? H(0xeaa22c) : INK, 0);
    txt_right(a, g, F_MONO10, LCD_W - 14, py + 4, tot, SUB);
    g_fill(g, bx0, py, bx1 - bx0, 3, H(0x39445a));
    int fill = len ? (int)((uint64_t)(bx1 - bx0) * (at > len ? len : at) / len) : 0;
    g_fill(g, bx0, py, fill, 3, seeking ? H(0xeaa22c) : GRN);
    g_fill(g, bx0 + fill - 1, py - 2, 3, 7, INK);
    /* why it's on */
    y = py + 22;
    if (a->why[0]) {
        char wl[2][TEXT_LINE_MAX];
        int nw = text_wrap(F(a, F_BODY10), a->why, LCD_W - 28, 2, 0, wl);
        for (int k = 0; k < nw; k++) txt(a, g, F_BODY10, 14, y + 12 * k, wl[k], SUB, 0);
        y += 12 * nw + 4;
    }
    /* what you know about it, in chips */
    int x = 14;
    char s[48];
    if (brain_is_liked(a->cur)) dio_chip(a, g, &x, y, "liked", H(0xd8382c), 0);
    int plays = brain_play_count(a->cur) + brain_ytm_plays(a->cur);
    if (plays > 0) { snprintf(s, sizeof s, plays == 1 ? "played once" : "played %d times", plays); dio_chip(a, g, &x, y, s, 0, 0); }
    else dio_chip(a, g, &x, y, "new to you", 0, 0);
    int bpm10 = brain_bpm10(a->cur);
    if (bpm10 > 300) { snprintf(s, sizeof s, "%d BPM", (bpm10 + 5) / 10); dio_chip(a, g, &x, y, s, 0, 0); }
    int tn[2][3], from_cover = wall_tones(a, a->cur, tn);    /* the wall's two tones, and where from */
    if (from_cover) snprintf(s, sizeof s, "the wall: the cover");
    else snprintf(s, sizeof s, "the wall: %s", VIBE_NAME[vibe_rank(a->cur, NULL)]);
    dio_chip(a, g, &x, y, s, C565(tn[0][0], tn[0][1], tn[0][2]), C565(tn[1][0], tn[1][1], tn[1][2]));
    /* what's next, or the notice */
    int ny = LCD_H - 34;
    g_fill(g, 5, ny - 6, LCD_W - 10, 1, H(0x2b3448));
    if (a->notice[0]) { txt_fit(a, g, F_BOLD11, 14, ny + 14, a->notice, LCD_W - 28, INK, 0); return 1; }
    uint32_t nx = a->qpos + 1 < a->qn ? a->q[a->qpos + 1] : LIB_NONE;
    const lib_track *n = nx != LIB_NONE ? lib_get(a->L, nx) : NULL;
    if (n) {
        cover(a, g, nx, ART_S, 14, ny - 1, 24);
        txt(a, g, F_MONO10, 46, ny + 9, a->qsrc[a->qpos + 1] == QS_AUTO ? "next, autoplay" : "next", GRN, 0);
        int nw2 = text_w(F(a, F_MONO10), a->qsrc[a->qpos + 1] == QS_AUTO ? "next, autoplay" : "next", 0);
        txt_fit(a, g, F_BOLD11, 46 + nw2 + 8, ny + 9, n->title, LCD_W - 60 - nw2 - 8, INK, 0);
        txt_fit(a, g, F_BODY10, 46, ny + 21, n->artist, LCD_W - 60, SUB, 0);
    } else txt(a, g, F_BODY10, 14, ny + 14, "Nothing after it yet: autoplay picks one as it ends.", SUB, 0);
    return 1;
}

static void dio_h2(app *a, gfx *g, const mtile *tl, int sel);    /* th_dio_in.h */

static void dio_mosaic(app *a, gfx *g, const mtile *tl, int n, int sel)
{
    if (a->view == V_LIBRARY && n == N_LIB) dio_pc(a, g, tl, sel);
    else if (a->view == V_SETTINGS && n == 8) dio_h2(a, g, tl, sel);       /* the H2, opened */
    else px_mosaic(a, g, tl, n, sel);
}

/* between full frames: just what moves in the case */
static void dio_pc_frame(app *a, gfx *g, int r[4])
{
    for (int y = 0; y < BAR_Y; y++) memcpy(g->px + y * g->stride, dio_bg + y * LCD_W, LCD_W * 2);
    pc_live(a, g, a->now_ms);
    r[0] = 0; r[1] = 0; r[2] = LCD_W; r[3] = BAR_Y;
}
