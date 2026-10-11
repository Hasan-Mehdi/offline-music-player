/* Three more pixel themes (docs/h2/pixel; firmware/tools/mock_pixel.py): Crate (after
 * beatbit's cover grid), Receiver (a walnut hi-fi with an amber dot-matrix and a radio dial
 * for a menu), Diorama (the listener's own desk corner as the menu). Part of app.c. */

/* ================================================================== Crate */
static void cr_page(app *a, gfx *g) { (void)a; ck_material(g, 0, 0, 160, 120, MAT_WOOD, 130, 0); }

static row_ink cr_row(app *a, gfx *g, int y, int h, int state)
{
    if (state & (ROW_FOCUS | ROW_LIVE)) return px_row(a, g, y, h, state);
    row_ink k = { RP.cream, RP.felt_l, RP.felt_l, RP.key_l, 0 };
    for (int x = 6; x < 154; x += 2) ck_point(g, x, (y + h - 2) / 2, RP.walnut_l);
    if (state & ROW_DIM) k.fg = RP.felt_d;
    return k;
}

static const palette *cr_pal(app *a)
{
    static palette pp;
    static int made;
    if (!made) {
        pp = *px_pal(a);
        pp.paper = RP.walnut_d; pp.ink = RP.cream; pp.blue = RP.key_l; pp.sub = RP.felt_l; pp.rule = RP.walnut;
        pp.wash = RP.walnut; pp.strip_bg = RP.ink;
        made = 1;
    }
    return &pp;
}

/* a cover as pixel art: blocks of bs px, each the average of its patch; bs <= 1 = the cover */
static void cr_cover(app *a, gfx *g, uint32_t idx, int x, int y, int px, int bs)
{
    const px16 *t = idx == LIB_NONE ? NULL : tex_get(a, idx, ART_M);
    if (!t) { g_fill(g, x, y, px, px, RP.walnut_l); return; }
    int tw = art_px[ART_M];
    if (bs <= 1) { g_blit_scaled(g, t, tw, tw, x, y, px, px); return; }
    for (int by = 0; by < px; by += bs)
        for (int bx = 0; bx < px; bx += bs) {
            int r = 0, gg = 0, b = 0, n = 0;
            for (int sy = 0; sy < 2; sy++)
                for (int sx = 0; sx < 2; sx++) {
                    int u = (bx + (sx * 2 + 1) * bs / 4) * tw / px, v = (by + (sy * 2 + 1) * bs / 4) * tw / px;
                    px16 c = t[(v < tw ? v : tw - 1) * tw + (u < tw ? u : tw - 1)];
                    r += c >> 11; gg += (c >> 5) & 63; b += c & 31; n++;
                }
            px16 avg = (px16)(((r / n) << 11) | ((gg / n) << 5) | (b / n));
            int w = bx + bs > px ? px - bx : bs, h = by + bs > px ? px - by : bs;
            g_fill(g, x + bx, y + by, w, h, avg);
        }
}

/* what each section shows: a cover of its own */
static uint32_t cr_pick(app *a, int item)
{
    uint32_t v[4];
    switch (item) {
    case 1: return a->cur_valid ? a->cur : LIB_NONE;
    case 2: return a->qpos + 1 < a->qn ? a->q[a->qpos + 1] : a->cur_valid ? a->cur : LIB_NONE;
    case 3: draw_shelves(a); return a->shelf_n[0] ? a->shelf[0][0] : LIB_NONE;
    case 4: draw_shelves(a); return a->shelf_n[1] ? a->shelf[1][0] : LIB_NONE;
    case 5: return brain_wheel(v, 4, (double)plat_now()) >= 3 ? v[2] : LIB_NONE;
    case 6: return brain_liked(v, 1) == 1 ? v[0] : LIB_NONE;
    default: return LIB_NONE;
    }
}

static void cr_home(app *a, gfx *g)
{
    ck_rect(g, 0, 11, 160, 12, RP.walnut_d);
    pf_text(g, &PF_PIXEL11, 10, 19, "Coda", RP.walnut_d, 2);
    pf_text(g, &PF_PIXEL11, 10, 17, "Coda", RP.cream, 2);
    ck_rect(g, 24, 3, 26, 5, RP.key);
    px_battery(a, g, LCD_W - 8, 15, RP.cream);
    int cur = fx_clamp(a->ls[V_MENU].sel, 0, N_MENU - 1);
    float t = a->ui_view == V_MENU ? (float)(a->now_ms - a->ui_t0) : 1e6f;
    for (int pass = 0; pass < 2; pass++)
        for (int i = 0; i < N_MENU; i++) {
            if ((pass == 0) == (i == cur)) continue;
            int x = 8 + (i % 4) * 77, y = 28 + (i / 4) * 80, foc = i == cur, lift = foc ? 3 : 0;
            int bs = foc ? (t < 60 ? 5 : t < 120 ? 3 : t < 180 ? 2 : 1) : 5;   /* it pulls into focus */
            g_fill(g, x + 3, y + 3, 70, 70, RP.walnut_d);
            if (foc) {
                g_fill(g, x - 3, y - 3 - lift, 76, 76, RP.walnut_d);
                g_fill(g, x - 2, y - 2 - lift, 74, 74, RP.cream);
            }
            if (i == 0) {                                     /* the Wheel: four of its newest */
                uint32_t v[4];
                int n = brain_wheel(v, 4, (double)plat_now());
                for (int k = 0; k < 4; k++)
                    cr_cover(a, g, k < n ? v[k] : LIB_NONE, x + (k % 2) * 35, y - lift + (k / 2) * 35, 35, bs > 1 ? bs - 1 : 1);
            } else if (i == 7) {
                ck_material(g, x / 2, (y - lift) / 2, (x + 70) / 2, (y - lift + 70) / 2, MAT_FELT, 120, 0);
                ck_sym(g, SYM_SETTINGS, x + 35, y - lift + 30, 40, RP.ink, RP.felt, 0, foc ? ez_seg(t, 60, 560) : 1);
            } else cr_cover(a, g, cr_pick(a, i), x, y - lift, 70, bs);
            g_fill(g, x, y + 56 - lift, 70, 14, RP.walnut_d);
            txt(a, g, F_SEMI11, x + 4, y + 67 - lift, menu_items[i], RP.cream, 0);
            int mat = px_mat(i), ba = (x + 52) / 2, bb = (y + 2 - lift) / 2;
            ck_rrect(g, ba, bb, ba + 9, bb + 9, RP.walnut_d, 1);
            ck_material(g, ba + 1, bb + 1, ba + 8, bb + 8, mat, 140 + i, 1);
            ck_sym(g, px_sym(i), 2 * ba + 9, 2 * bb + 9, 13, mat_ink(mat), mat_base(mat), 0, 1);
            if (foc) ck_pointer(g, x - 10, y + 28, a->now_ms, RP.walnut_d, RP.cream);
        }
    int nw = text_w(F(a, F_SEMI12), menu_items[cur], 0);
    txt(a, g, F_SEMI12, 10, 202, menu_items[cur], RP.cream, 0);
    txt_fit(a, g, F_BODY10, 16 + nw, 202, MENU_DESC[cur], 290 - nw, RP.felt_l, 0);
    draw_nowbar(a, g);
}

/* ================================================================== Receiver */
static const px16 RX_ON = C565(0xff, 0x9a, 0x2a), RX_OFF = C565(0x33, 0x20, 0x11), RX_HI = C565(0xff, 0xd0, 0x8a),
                  RX_GLASS = C565(0x1a, 0x11, 0x0b), RX_EDGE = C565(0x0f, 0x0a, 0x06), RX_SHINE = C565(0x22, 0x17, 0x10),
                  RX_NEEDLE = C565(0xe8, 0x3a, 0x2a);
#define RX_W 98
#define RX_H 47
static uint8_t rx_bmp[RX_H][RX_W];

/* text into the dot-matrix's bitmap (a built-in 1-bit font) */
static int rx_text(int x, int y_top, const char *s, const pixfont *f)
{
    int x0 = x;
    for (; *s; s++) {
        int c = (unsigned char)*s;
        if (c < 32 || c > 126) c = '?';
        int gi = c - 32, w = f->w[gi], rb = (w + 7) / 8;
        const uint8_t *d = f->data + f->off[gi];
        for (int yy = 0; yy < f->h; yy++)
            for (int xx = 0; xx < w; xx++)
                if ((d[yy * rb + xx / 8] & (0x80 >> (xx % 8))) && x + xx >= 0 && x + xx < RX_W && y_top + yy >= 0 && y_top + yy < RX_H)
                    rx_bmp[y_top + yy][x + xx] = 1;
        x += w;
    }
    return x - x0;
}

static void rx_dots(gfx *g, int x0, int y0)
{
    for (int y = 0; y < RX_H; y++)
        for (int x = 0; x < RX_W; x++) {
            int sx = x0 + x * 3, sy = y0 + y * 3;
            if (rx_bmp[y][x]) { g_fill(g, sx, sy, 2, 2, RX_ON); g->px[sy * g->stride + sx] = RX_HI; }
            else g_fill(g, sx, sy, 2, 2, RX_OFF);
        }
}

static void rx_cabinet(gfx *g, int glass_rows)
{
    ck_material(g, 0, 0, 160, 120, MAT_WOOD, 150, 0);
    ck_rect(g, 0, 0, 160, 1, RP.silver);
    ck_rect(g, 0, 119, 160, 120, RP.silver);
    ck_rrect(g, 3, 3, 157, 3 + glass_rows, RP.silver_d, 3);
    ck_rrect(g, 4, 4, 156, 2 + glass_rows, RX_EDGE, 3);
    ck_rrect(g, 5, 5, 155, 1 + glass_rows, RX_GLASS, 3);
    for (int k = 0; k < 2; k++)                          /* the glass's shine */
        for (int y = 6; y < glass_rows; y++) ck_point(g, 118 + 3 * k - (y - 6) * 20 / glass_rows, y, RX_SHINE);
}

static void rx_knob(app *a, gfx *g, int cx, float ang, const char *label)
{
    g_disc(g, 2 * cx * 16, 197 * 16, 26 * 16, RP.slot);
    g_disc(g, 2 * cx * 16, 195 * 16, 24 * 16, RP.silver);
    for (int k = 0; k < 16; k++) {
        float q = k * 0.3927f;
        g_fill(g, 2 * cx + (int)lrintf(cosf(q) * 23), 195 + (int)lrintf(sinf(q) * 23), 2, 2, RP.silver_d);
    }
    g_disc(g, 2 * cx * 16, 195 * 16, 16 * 16, RP.silver_l);
    int32_t xy[8];
    float c = cosf(ang), s = sinf(ang);
    xy[0] = (int32_t)((2 * cx - s * 1.5f) * 16); xy[1] = (int32_t)((195 + c * 1.5f) * 16);
    xy[2] = (int32_t)((2 * cx + c * 14 - s * 1.5f) * 16); xy[3] = (int32_t)((195 + s * 14 + c * 1.5f) * 16);
    xy[4] = (int32_t)((2 * cx + c * 14 + s * 1.5f) * 16); xy[5] = (int32_t)((195 + s * 14 - c * 1.5f) * 16);
    xy[6] = (int32_t)((2 * cx + s * 1.5f) * 16); xy[7] = (int32_t)((195 - c * 1.5f) * 16);
    g_convex(g, xy, 4, RP.ink);
    pf_text(g, &PF_SILK8, 2 * cx - pf_width(&PF_SILK8, label, 1) / 2, 236, label, RP.cream, 1);
    (void)a;
}

static void rx_home(app *a, gfx *g)
{
    rx_cabinet(g, 77);
    int cur = fx_clamp(a->ls[V_MENU].sel, 0, N_MENU - 1);
    float t = a->ui_view == V_MENU ? (float)(a->now_ms - a->ui_t0) : 1e6f;
    int prev = a->ui_view == V_MENU && a->ui_prev >= 0 && a->ui_prev < N_MENU ? a->ui_prev : cur;
    float pos = prev + (cur - prev) * ez_back(ez_seg(t, 0, 380), 1.4f);
    memset(rx_bmp, 0, sizeof rx_bmp);
    /* the dial: a scale, the stations along it, sliding past the needle */
    const int span = 52;
    int off = (int)lrintf(pos * span) - RX_W / 2;
    for (int x = 0; x < RX_W; x++) rx_bmp[12][x] = 1;
    for (int k = -4; k < N_MENU * span / 4 + 8; k++) {
        int xx = k * 4 - off;
        if (xx >= 0 && xx < RX_W) { rx_bmp[13][xx] = 1; if (k % 2 == 0) rx_bmp[14][xx] = 1; }
    }
    static const char *const ST[N_MENU] = { "WHEEL", "NOW", "QUEUE", "EXPLORE", "SEARCH", "LIBRARY", "LIKED", "SETTINGS" };
    for (int i = 0; i < N_MENU; i++) {
        int w = pf_width(&PF_SILK8, ST[i], 1), xx = i * span - off - w / 2;
        if (xx > -60 && xx < RX_W) rx_text(xx, 3, ST[i], &PF_SILK8);
    }
    char big[24];
    snprintf(big, sizeof big, "%s", cur == 1 ? "NOW" : ST[cur]);
    rx_text(RX_W / 2 - pf_width(&PF_SILK16, big, 1) / 2, 19, big, &PF_SILK16);
    char desc[96];
    int n = 0;
    for (const char *s = MENU_DESC[cur]; *s && n < 94; s++) desc[n++] = (char)(*s >= 'a' && *s <= 'z' ? *s - 32 : *s);
    desc[n] = 0;
    int dw = pf_width(&PF_SILK8, desc, 1), mq = (int)(a->now_ms / 60) % (dw + RX_W);
    rx_text(RX_W - mq, 38, desc, &PF_SILK8);
    rx_dots(g, 13, 12);
    int nx = 13 + RX_W / 2 * 3;
    g_fill(g, nx - 1, 10, 2, 55, RX_NEEDLE);
    g_fill(g, nx + 1, 12, 1, 53, RX_EDGE);
    /* the knobs: volume, and tuning -- the click wheel */
    rx_knob(a, g, 28, -0.8f, "VOLUME");
    rx_knob(a, g, 132, pos * 0.7f - 2.4f, "TUNING");
    ck_rect(g, 62, 92, 98, 104, RP.silver_d);
    ck_rect(g, 63, 93, 97, 103, RP.silver);
    pf_text(g, &PF_SILK8, 160 - pf_width(&PF_SILK8, "CODA", 1) / 2, 201, "CODA", RP.walnut_d, 1);
    g_disc(g, 153 * 16, 217 * 16, 2 * 16, RP.key);
    pf_text(g, &PF_SILK8, 160, 220, "POWER", RP.cream, 1);
}

static void rx_page(app *a, gfx *g)
{
    if (a->view == V_MENU || a->view == V_NOW) return;   /* they draw their own cabinet */
    rx_cabinet(g, 104);
}

static void rx_header(app *a, gfx *g, int sec, const char *title, const char *right)
{
    (void)sec;
    ck_material(g, 0, 0, 160, 14, MAT_SILVER, 151, 0);
    char up[40];
    int n = 0;
    for (const char *s = title; *s && n < 38; s++) up[n++] = (char)(*s >= 'a' && *s <= 'z' ? *s - 32 : *s);
    up[n] = 0;
    if (px_ascii(up)) pf_text(g, &PF_SILK16, 12, 22, up, RP.walnut_d, 1);
    else txt_fit(a, g, F_POSTER15, 12, 22, title, 200, RP.walnut_d, 0);
    px_battery(a, g, LCD_W - 8, 19, RP.walnut_d);
    if (right) txt_right(a, g, F_MONO10, LCD_W - 62, 19, right, RP.walnut);
}

static row_ink rx_row(app *a, gfx *g, int y, int h, int state)
{
    int foc = state & ROW_FOCUS;
    float cy = foc ? cursor_y(a, y) : (float)y;
    row_ink k = { RX_ON, C565(0x9a, 0x60, 0x28), C565(0x9a, 0x60, 0x28), RX_HI, 0 };
    if (state & ROW_LIVE) k.fg = RX_HI;
    if (foc) {
        g_fill(g, 12, (int)lrintf(cy) + 1, 296, h - 2, state & ROW_ADJ ? RP.leaf_l : RX_ON);
        if (cy > y - 8 && cy < y + 8) { k.fg = RX_GLASS; k.sub = C565(0x5a, 0x30, 0x10); k.note = RX_GLASS; k.on = 1; }
    }
    return k;
}

static void rx_nowbar(app *a, gfx *g)
{
    const int y0 = BAR_Y;
    const lib_track *t = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    if (a->notice[0]) { txt_fit(a, g, F_BOLD11, 14, y0 + 18, a->notice, LCD_W - 28, RX_HI, 0); return; }
    if (!t) return;
    char e[16];
    mmss(e, sizeof e, a->ps.elapsed_ms / 1000);
    txt(a, g, F_MONO10, 14, y0 + 18, e, RP.cream, 0);
    txt_fit(a, g, F_SEMI11, 52, y0 + 18, t->title, LCD_W - 64, RP.cream, 0);
}

static const palette *rx_pal(app *a)
{
    static palette pp;
    static int made;
    if (!made) {
        pp = *px_pal(a);
        pp.paper = RX_GLASS; pp.ink = RX_ON; pp.blue = RX_HI; pp.sub = C565(0x9a, 0x60, 0x28); pp.rule = RX_OFF;
        pp.wash = RX_EDGE; pp.strip_bg = RP.walnut_d;
        made = 1;
    }
    return &pp;
}

/* a VU meter: cream face, black scale, red past 0, the needle */
static void rx_vu(gfx *g, int a0, int b0, int c0, int d0, float level)
{
    ck_rrect(g, a0, b0, c0, d0, RP.walnut_d, 2);
    ck_rrect(g, a0 + 1, b0 + 1, c0 - 1, d0 - 1, C565(0xf3, 0xe6, 0xc8), 2);
    float cx = (a0 + c0), cy = 2 * d0 - 6;
    for (int k = 0; k <= 10; k++) {
        float q = 3.1416f * (1.18f + .64f * k / 10);
        int r1 = k % 5 ? 50 : 54;
        int32_t xy[4] = { (int32_t)((cx + cosf(q) * 44) * 16), (int32_t)((cy + sinf(q) * 44) * 16),
                          (int32_t)((cx + cosf(q) * r1) * 16), (int32_t)((cy + sinf(q) * r1) * 16) };
        int32_t quad[8] = { xy[0] - 12, xy[1], xy[2] - 12, xy[3], xy[2] + 12, xy[3], xy[0] + 12, xy[1] };
        g_convex(g, quad, 4, k >= 8 ? RP.red : RP.ink);
    }
    float q = 3.1416f * (1.18f + .64f * level);
    float nx = -sinf(q) * 0.8f, ny = cosf(q) * 0.8f;
    int32_t needle[8] = { (int32_t)((cx + nx) * 16), (int32_t)((cy + ny) * 16), (int32_t)((cx + cosf(q) * 52 + nx) * 16),
                          (int32_t)((cy + sinf(q) * 52 + ny) * 16), (int32_t)((cx + cosf(q) * 52 - nx) * 16),
                          (int32_t)((cy + sinf(q) * 52 - ny) * 16), (int32_t)((cx - nx) * 16), (int32_t)((cy - ny) * 16) };
    g_convex(g, needle, 4, RP.ink);
    g_fill(g, (int)cx - 4, (int)cy - 2, 8, 4, RP.walnut_d);
}

static int rx_now(app *a, gfx *g)
{
    rx_cabinet(g, 77);
    const lib_track *t = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    memset(rx_bmp, 0, sizeof rx_bmp);
    char title[160] = "NOTHING PLAYING";
    if (t) {
        int n = 0;
        for (const char *s = t->title; *s && n < 120; s++) title[n++] = (char)(*s >= 'a' && *s <= 'z' ? *s - 32 : *s);
        title[n] = 0;
    }
    int tw = pf_width(&PF_SILK8, title, 1), mq = (int)(a->now_ms / 50) % (tw + RX_W);
    rx_text(RX_W - mq, 1, title, &PF_SILK8);
    char e[16];
    uint32_t sec = a->cur_valid ? a->ps.elapsed_ms / 1000 : 0;
    snprintf(e, sizeof e, "%u:%02u", (unsigned)(sec / 60), (unsigned)(sec % 60));
    rx_text(2, 12, e, &PF_SILK16);
    rx_text(62, 13, a->ps.playing ? "PLAY" : "PAUSE", &PF_SILK8);
    rx_text(62, 20, "OPUS", &PF_SILK8);
    for (int x = 2; x < 96; x++) { rx_bmp[34][x] = rx_bmp[36][x] = 1; }
    rx_bmp[35][2] = rx_bmp[35][95] = 1;
    if (a->cur_valid && a->ps.length_ms)
        for (int x = 2; x < 2 + (int)((uint64_t)93 * a->ps.elapsed_ms / a->ps.length_ms); x++) rx_bmp[35][x] = 1;
    uint32_t nx = a->qpos + 1 < a->qn ? a->q[a->qpos + 1] : LIB_NONE;
    const lib_track *nt = nx != LIB_NONE ? lib_get(a->L, nx) : NULL;
    char nb[40] = "";
    if (nt && px_ascii(nt->title)) {
        snprintf(nb, sizeof nb, "NEXT  %s", nt->title);
        for (char *s = nb; *s; s++) if (*s >= 'a' && *s <= 'z') *s -= 32;
    }
    rx_text(2, 39, nb, &PF_SILK8);
    rx_dots(g, 13, 12);
    /* the meters move with the music */
    uint8_t bands[12];
    int live = a->cur_valid && a->ps.playing && plat_spectrum(bands);
    float l0 = 0.05f, l1 = 0.05f;
    if (live) {
        int lo = 0, hi = 0;
        for (int i = 0; i < 6; i++) { lo += bands[i]; hi += bands[6 + i]; }
        l0 = .1f + .8f * lo / (6 * 255.0f);
        l1 = .1f + .8f * hi / (6 * 255.0f);
    }
    rx_vu(g, 4, 81, 78, 117, l0);
    rx_vu(g, 82, 81, 156, 117, l1);
    pf_text(g, &PF_SILK8, 70, 228, "VU L", RP.walnut_d, 1);
    pf_text(g, &PF_SILK8, 226, 228, "VU R", RP.walnut_d, 1);
    return 1;
}

/* ================================================================== Diorama */
/* the scene is drawn cell by cell into its own buffers: colour, and which object each cell
 * belongs to, so the picked one can be outlined */
static px16 dio_px[120][160];
static uint8_t dio_id[120][160];
enum { DO_NONE, DO_WHEEL, DO_NOW, DO_QUEUE, DO_EXPLORE, DO_SEARCH, DO_LIBRARY, DO_LIKED, DO_SETTINGS };

static void dp(int x, int y, px16 c, int id)
{
    if (x < 0 || x >= 160 || y < 0 || y >= 120) return;
    dio_px[y][x] = c;
    dio_id[y][x] = (uint8_t)id;
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
    for (int i = 0; i <= n; i++) dp((int)lrintf(x0 + (x1 - x0) * i / n), (int)lrintf(y0 + (y1 - y0) * i / n), col, id);
}

static void dio_scene_t(uint32_t now)
{
    const px16 black = C565(0x2c, 0x2b, 0x2e), dark = C565(0x16, 0x16, 0x18), steel = C565(0x1c, 0x1c, 0x1e);
    for (int y = 0; y < 120; y++)                          /* the wall, a faint grain; the desk */
        for (int x = 0; x < 160; x++) dp(x, y, (x % 7 == (y / 9) % 3) ? C565(0xd0, 0xbb, 0x9b) : RP.wall, DO_NONE);
    drect(0, 98, 160, 106, RP.walnut, DO_NONE);
    for (int x = 0; x < 160; x++) dp(x, 98, RP.walnut_hi, DO_NONE);
    drect(16, 30, 120, 34, RP.walnut, DO_NONE);              /* the shelf, its light strip */
    for (int x = 16; x < 120; x++) { dp(x, 30, RP.walnut_hi, DO_NONE); dp(x, 34, RP.led, DO_NONE); dp(x, 35, RP.wall_sh, DO_NONE); }
    drect(20, 13, 32, 30, black, DO_LIBRARY);                /* the boxes: Library */
    drect(23, 17, 29, 24, C565(0x9a, 0x9a, 0x9c), DO_LIBRARY);
    drect(33, 15, 47, 22, C565(0x1f, 0x5c, 0xa6), DO_LIBRARY);
    drect(33, 22, 47, 30, C565(0xe8, 0x80, 0x2a), DO_LIBRARY);
    ddisc(39.5f, 21.5f, 2.6f, RP.cream, DO_LIBRARY);
    drect(52, 24, 63, 30, black, DO_NONE);                   /* a fern */
    for (int k = 0; k < 9; k++) {
        float q = 3.1416f * (1.1f + .8f * k / 8);
        dline(57, 24, 57 + cosf(q) * 9, 22 + sinf(q) * 9, k % 2 ? RP.leaf_d : RP.leaf, DO_NONE);
    }
    ddisc(72, 24, 6.2f, RP.ink, DO_WHEEL);                   /* the clock: the Wheel */
    ddisc(72, 24, 5.2f, RP.cream, DO_WHEEL);
    dline(72, 24, 72, 20, RP.ink, DO_WHEEL);
    dline(72, 24, 75, 25, RP.ink, DO_WHEEL);
    float sec = (float)(now % 60000) / 60000 * 6.2832f;
    dline(72, 24, 72 + sinf(sec) * 4, 24 - cosf(sec) * 4, RP.red, DO_WHEEL);
    drect(98, 23, 109, 30, black, DO_LIKED);                 /* the pothos: Liked */
    for (int k = 0; k < 5; k++) ddisc(99 + k * 2.2f, 19.5f + (k % 2), 2.6f, k % 2 ? RP.leaf : RP.leaf_d, DO_LIKED);
    for (int k = 0, y = 22; y < 74; y += 3, k++) {
        float sway = sinf((float)now / 700 + k * .5f) * (k / 10.0f);
        int x = 106 + (int)lrintf(sinf(k * .8f) * 2 + sway), side = k % 2 ? 1 : -1, lx = x + side * 2;
        for (int d = 0; d < 3; d++) dp(x, y + d, RP.leaf_d, DO_LIKED);
        dp(lx, y, RP.leaf, DO_LIKED); dp(lx + side, y + 1, RP.leaf_l, DO_LIKED); dp(lx + 2 * side, y + 1, RP.leaf, DO_LIKED);
        dp(lx + side, y + 2, RP.leaf, DO_LIKED); dp(lx + 3 * side, y + 1, RP.leaf, DO_LIKED); dp(lx + 2 * side, y + 3, RP.leaf, DO_LIKED);
    }
    drect(28, 40, 57, 71, RP.cream, DO_EXPLORE);             /* the posters (covers go on them): Explore */
    drect(60, 40, 89, 71, RP.cream, DO_EXPLORE);
    drect(32, 73, 89, 95, dark, DO_QUEUE);                   /* the monitor: the Queue */
    drect(34, 75, 87, 93, C565(0x22, 0x26, 0x30), DO_QUEUE);
    drect(57, 95, 64, 98, dark, DO_QUEUE);
    drect(52, 97, 69, 99, dark, DO_QUEUE);
    drect(22, 96, 49, 100, C565(0xbd, 0xbd, 0xb8), DO_SETTINGS);   /* the keyboard: Settings */
    for (int x = 23; x < 48; x += 2) { dp(x, 97, C565(0xe9, 0xe7, 0xe0), DO_SETTINGS); dp(x, 98, C565(0xd9, 0xd7, 0xd0), DO_SETTINGS); }
    dp(43, 97, RP.key, DO_SETTINGS); dp(44, 97, RP.key, DO_SETTINGS);
    drect(100, 74, 122, 99, RP.silver, DO_NONE);             /* the silver case, its wooden foot */
    for (int y = 76; y < 86; y += 2) for (int x = 102; x < 120; x++) dp(x, y, RP.slot, DO_NONE);
    drect(100, 97, 122, 100, RP.walnut, DO_NONE);
    for (int k = 0; k <= 24; k++) {                          /* the headphones on it: Now playing */
        float q = 3.1416f * (1 + k / 24.0f);
        dp((int)lrintf(110 + cosf(q) * 13), (int)lrintf(80 + sinf(q) * 11), steel, DO_NOW);
        dp((int)lrintf(110 + cosf(q) * 13), (int)lrintf(81 + sinf(q) * 11), k > 4 && k < 10 ? RP.red : steel, DO_NOW);
    }
    drect(95, 79, 100, 90, steel, DO_NOW);
    for (int y = 80; y < 89; y++) dp(96, y, RP.red, DO_NOW);
    for (int y = 40; y < 58; y++) {                          /* the lamp: Search */
        int w = 9 + (y - 40) / 8;
        drect(143 - w, y, 143 + w, y + 1, y == 57 ? C565(0xdd, 0xd4, 0xc4) : C565(0xf6, 0xf2, 0xea), DO_SEARCH);
    }
    drect(142, 58, 144, 104, steel, DO_SEARCH);
    for (int y = 70; y < 100; y += 14) drect(138, y, 148, y + 1, steel, DO_SEARCH);
    for (int y = 70; y < 106; y++) for (int x = 0; x < 17; x++) dp(x, y, x == 2 || x == 10 ? RP.leather_d : RP.leather, DO_NONE);
}

static void dio_home(app *a, gfx *g)
{
    static const uint8_t ID_OF[N_MENU] = { DO_WHEEL, DO_NOW, DO_QUEUE, DO_EXPLORE, DO_SEARCH, DO_LIBRARY, DO_LIKED, DO_SETTINGS };
    static const int16_t TAG[N_MENU][2] = { { 72, 16 }, { 110, 66 }, { 60, 71 }, { 58, 38 }, { 143, 38 }, { 33, 11 }, { 106, 15 }, { 35, 94 } };
    int cur = fx_clamp(a->ls[V_MENU].sel, 0, N_MENU - 1), id = ID_OF[cur];
    dio_scene_t(a->now_ms);
    for (int y = 0; y < 106; y++)
        for (int x = 0; x < 160; x++) {
            px16 c = dio_px[y][x];
            if (dio_id[y][x] != id && ((x > 0 && dio_id[y][x - 1] == id) || (x < 159 && dio_id[y][x + 1] == id) ||
                                       (y > 0 && dio_id[y - 1][x] == id) || (y < 119 && dio_id[y + 1][x] == id)))
                c = RP.cream;                                /* the picked one, outlined */
            ck_point(g, x, y, c);
        }
    /* the posters are covers; the monitor shows the queue */
    for (int i = 0; i < 2; i++) {
        uint32_t c = i == 0 ? (a->cur_valid ? a->cur : LIB_NONE) : (a->qpos + 1 < a->qn ? a->q[a->qpos + 1] : LIB_NONE);
        if (c != LIB_NONE) cover(a, g, c, ART_S, 59 + 64 * i, 83, 52);
    }
    for (int i = 0; i < 3 && a->qpos + i < a->qn; i++) {
        const lib_track *t = lib_get(a->L, a->q[a->qpos + i]);
        if (t) txt_fit(a, g, F_BODY10, 72, 162 + i * 10, t->title, 98, i ? C565(0xd9, 0xe0, 0xea) : RP.key, 0);
    }
    int tx = TAG[cur][0], ty = TAG[cur][1];
    ck_pointer(g, 2 * tx - 4, 2 * ty - 8, a->now_ms, RP.walnut_d, RP.cream);
    int w = text_w(F(a, F_SEMI11), menu_items[cur], 0) + 16, gx = 2 * tx + 10 + w > LCD_W - 4 ? LCD_W - 4 - w : 2 * tx + 10, gy = 2 * ty - 22;
    g_fill(g, gx, gy, w, 18, RP.walnut_d);
    g_fill(g, gx + 1, gy + 1, w - 2, 16, RP.parch);
    txt(a, g, F_SEMI11, gx + 8, gy + 13, menu_items[cur], RP.ink, 0);
    g_fill(g, 0, 198, LCD_W, 14, RP.walnut_d);
    txt_fit(a, g, F_BODY10, 8, 208, MENU_DESC[cur], 300, RP.felt_l, 0);
    px_battery(a, g, LCD_W - 8, 14, RP.ink);
    draw_nowbar(a, g);
}
