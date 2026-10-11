/* Each theme's power-on (BOOT_MS, while the library loads -- no covers or card fonts yet,
 * only shapes, materials and the built-in fonts) and power-off (BOOT_OFF_MS, from the
 * screen as it was). Sakurai's are boot.c's grooves and app_draw_off's crate; Room's door
 * is in th_room.h. Part of app.c. */

static uint32_t an_hash(int x, int y) { uint32_t h = (uint32_t)(x * 73856093) ^ (uint32_t)(y * 19349663); h ^= h >> 13; return h * 0x5bd1e995u; }

/* the screen as it was, dimmed towards a colour (0..256) */
static void an_from(gfx *g, const px16 *from, px16 to, int amt)
{
    for (int y = 0; y < LCD_H; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) row[x] = blend565(from ? from[y * LCD_W + x] : to, to, amt);
    }
}

static void an_word(gfx *g, int x, int yb, const char *s, int n, px16 c, px16 sh)
{
    char b[16];
    snprintf(b, sizeof b, "%.*s", n, s);
    if (sh) pf_text(g, &PF_PIXEL11, x, yb + 2, b, sh, 2);
    pf_text(g, &PF_PIXEL11, x, yb, b, c, 2);
}

/* ---------------------------------------------------------------- Jukebox */
static void jb_boot(gfx *g, uint32_t t)
{
    jb_wallpaper(g);
    float e = ez_back(ez_seg((float)t, 0, 450), 1.3f);
    int cx = 80, cy = 68, hw = (int)(77 * e), hh = (int)(52 * e);
    if (hw > 6 && hh > 6) jb_frame(g, cx - hw, cy - hh, cx + hw, cy + hh);
    for (int i = 0; i < 5 && e >= 1; i++) {
        float ei = ez_back(ez_seg((float)t, 450 + 90.0f * i, 650 + 90.0f * i), 1.8f);
        if (ei <= 0) continue;
        int y = 46 + i * 14 - (int)((1 - ei) * 30);
        ck_rect(g, 9, y, 151, y + 12, JB_SLOT_B);
        ck_rect(g, 10, y + 1, 150, y + 11, i == 2 ? JB_SEL : JB_SLOT);
    }
    float s = ez_back(ez_seg((float)t, 900, 1300), 2.0f);
    int sy = (int)((1 - s) * -16);
    if (s > 0) {
        ck_rrect(g, 55, 1 + sy, 105, 14 + sy, RP.walnut_d, 1);
        ck_material(g, 56, 2 + sy, 104, 13 + sy, MAT_WOOD, 81, 1);
        int w = pf_width(&PF_PIXEL11, "Coda", 2);
        an_word(g, LCD_W / 2 - w / 2, 20 + 2 * sy, "Coda", 4, RP.cream, RP.walnut_d);
    }
}

static void jb_off(app *a, gfx *g, uint32_t t, const px16 *from)
{
    (void)a;
    an_from(g, from, RP.wall, 0);
    for (int i = 0; i < 6; i++) {                          /* the slots slide out, one by one */
        int y0 = 94 + i * 28, dx = (int)(LCD_W * ez_out(ez_seg((float)t, 60.0f * i, 60.0f * i + 260)));
        if (dx) g_fill(g, 14, y0, dx < 278 ? dx : 278, 26, RP.parch);
    }
    int k = (int)(256 * ez_out(ez_seg((float)t, 450, 900)));
    for (int y = 0; y < LCD_H && k; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) row[x] = blend565(row[x], RP.walnut_d, k);
    }
}

/* ---------------------------------------------------------------- Toybox */
static void tb_paint_checker(gfx *g, uint32_t t)
{
    int off = (int)(t / 125) % 16;
    for (int b = 0; b < 120; b++)
        for (int c = 0; c < 160; c += 8 - ((c + off) % 8)) {
            int c2 = c + 8 - ((c + off) % 8);
            ck_rect(g, c, b, c2 > 160 ? 160 : c2, b + 1, (((c + off) / 8) + ((b + off) / 8)) % 2 ? TB_CHK1 : TB_CHK2);
        }
}

static void tb_boot(gfx *g, uint32_t t)
{
    tb_paint_checker(g, t);
    float c = ez_back(ez_seg((float)t, 0, 300), 1.6f);
    int cy = (int)((1 - c) * -16);
    tb_card(g, 3, 2 + cy, 157, 14 + cy);
    if (t > 900) an_word(g, 14, 22 + 2 * cy, "Coda", (int)((t - 900) / 80) + 1 > 4 ? 4 : (int)((t - 900) / 80) + 1, RP.ink, 0);
    struct { int a, b, c, d; px16 f, dk, l; uint32_t at; } B[2] = {
        { 4, 17, 78, 74, RP.leaf, RP.leaf_d, RP.leaf_l, 200 }, { 82, 17, 156, 74, RP.key, RP.key_d, RP.key_l, 350 } };
    for (int i = 0; i < 2; i++) {
        float s = ez_back(ez_seg((float)t, (float)B[i].at, B[i].at + 400.0f), 2.2f);
        if (s <= 0.02f) continue;
        int cx = (B[i].a + B[i].c) / 2, cyy = (B[i].b + B[i].d) / 2, hw = (int)((B[i].c - B[i].a) / 2 * s), hh = (int)((B[i].d - B[i].b) / 2 * s);
        if (hw > 3 && hh > 3) tb_button(g, cx - hw, cyy - hh, cx + hw, cyy + hh, B[i].f, B[i].dk, B[i].l, 0, 3);
    }
    static const int MAT6[6] = { MAT_SHADE, MAT_LEAF, MAT_SAGE, MAT_SILVER, MAT_KEY, MAT_FELT };
    for (int i = 0; i < 6; i++) {
        float s = ez_back(ez_seg((float)t, 600.0f + 80 * i, 900.0f + 80 * i), 2.4f);
        if (s <= 0.02f) continue;
        int cx = 17 + i * 25;
        px16 face = MAT6[i] == MAT_SHADE ? TB_CARD : mat_base(MAT6[i]);
        g_disc(g, (2 * cx + 1) * 16, 188 * 16, (int)(23 * 16 * s), TB_OUTL);
        g_disc(g, (2 * cx + 1) * 16, 184 * 16, (int)(21 * 16 * s), face);
    }
}

static void tb_off(app *a, gfx *g, uint32_t t, const px16 *from)
{
    (void)a;
    /* everything sinks into the board, then the board fades to card white */
    int sink = (int)(18 * ez_out(ez_seg((float)t, 0, 500)));
    for (int y = LCD_H - 1; y >= 0; y--) {
        px16 *row = g->px + y * g->stride;
        int sy = y - sink;
        for (int x = 0; x < LCD_W; x++) row[x] = sy >= 0 && from ? from[sy * LCD_W + x] : TB_CHK1;
    }
    int k = (int)(256 * ez_out(ez_seg((float)t, 300, 900)));
    for (int y = 0; y < LCD_H && k; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) row[x] = blend565(row[x], TB_CARD, k);
    }
}

/* ---------------------------------------------------------------- Deck */
static void dk_faceplate(gfx *g)
{
    ck_material(g, 0, 0, 160, 9, MAT_WOOD, 101, 0);
    ck_material(g, 0, 9, 160, 62, MAT_SILVER, 102, 0);
    ck_vents(g, 104, 48, 156, 60);
    ck_rrect(g, 3, 11, 102, 45, C565(0x0e, 0x09, 0x06), 1);
    ck_rect(g, 4, 12, 101, 44, DK_GLASS);
    ck_material(g, 0, 62, 160, 120, MAT_WOOD, 103, 0);
    ck_rect(g, 2, 64, 158, 118, DK_LIST);
}

static void dk_boot(gfx *g, uint32_t t)
{
    dk_faceplate(g);
    if (t < 250) return;
    /* the display's own test: every segment, dim, then lit; the spectrum sweeps */
    float lit = ez_seg((float)t, 250, 550);
    px16 on = blend565(DK_AMBER_D, DK_AMBER, (int)(lit * 256));
    if (t < 1100) {
        dk_seg7(g, 14, 13, '8', on, DK_AMBER_D);
        ck_point(g, 22, 17, on);
        ck_point(g, 22, 21, on);
        dk_seg7(g, 25, 13, '8', on, DK_AMBER_D);
        dk_seg7(g, 33, 13, '8', on, DK_AMBER_D);
    } else {
        dk_seg7(g, 14, 13, '0', DK_AMBER, DK_AMBER_D);
        ck_point(g, 22, 17, DK_AMBER);
        ck_point(g, 22, 21, DK_AMBER);
        dk_seg7(g, 25, 13, '0', DK_AMBER, DK_AMBER_D);
        dk_seg7(g, 33, 13, '0', DK_AMBER, DK_AMBER_D);
    }
    float sw = ez_seg((float)t, 550, 1250), up = sw < .5f ? sw * 2 : (1 - sw) * 2;
    for (int i = 0; i < 14; i++) {
        int h = (int)(14 * up * (0.6f + 0.4f * sinf(i * 0.9f))), bx = 52 + i * 3;
        if (h > 0) ck_rect(g, bx, 28 - h, bx + 2, 28, DK_AMBER);
        ck_rect(g, bx, 29, bx + 2, 30, DK_AMBER_D);
    }
    if (t > 1100) {
        int n = (int)((t - 1100) / 70) + 1;
        an_word(g, 20, 156, "CODA", n > 4 ? 4 : n, DK_AMBER, 0);
        pf_text(g, &PF_SILK8, 20, 180, "MUSIC, OFFLINE", DK_AMBER_D, 1);
    }
}

static void dk_off(app *a, gfx *g, uint32_t t, const px16 *from)
{
    (void)a;
    an_from(g, from, 0, 0);
    /* the amber goes: it flickers, then the glass is dark, then the rest */
    int dark = t > 80 && (t < 120 || t > 180);
    if (dark) for (int y = 24; y < 90; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = 8; x < 204; x++) {
            int r = row[x] >> 11, gg = (row[x] >> 5) & 63;
            if (r > 20 && gg > 20 && gg < 50) row[x] = DK_GLASS;     /* amber -> off */
        }
    }
    int k = (int)(256 * ez_out(ez_seg((float)t, 350, 900)));
    for (int y = 0; y < LCD_H && k; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) row[x] = blend565(row[x], C565(0, 0, 0), k);
    }
}

/* ---------------------------------------------------------------- Crate */
static void cr_boot(gfx *g, uint32_t t)
{
    ck_material(g, 0, 0, 160, 120, MAT_WOOD, 130, 0);
    static const int MATS[8] = { MAT_LEATHER, MAT_LEAF, MAT_SAGE, MAT_KEY, MAT_SILVER, MAT_SHADE, MAT_FELT, MAT_PARCH };
    for (int i = 0; i < 8; i++) {
        float s = ez_seg((float)t, 120.0f * i, 120.0f * i + 500);
        if (s <= 0) continue;
        int x = 8 + (i % 4) * 77, y = 28 + (i / 4) * 80;
        g_fill(g, x + 3, y + 3, 70, 70, RP.walnut_d);
        ck_material(g, x / 2, y / 2, (x + 70) / 2, (y + 70) / 2, MATS[i], 300 + i, 0);
        int bs = (int)(14 * (1 - s)) + 1;                    /* big blocks resolving */
        if (bs > 2)
            for (int by = 0; by < 70; by += bs)
                for (int bx = 0; bx < 70; bx += bs) {
                    px16 c = g->px[(y + by) * g->stride + x + bx];
                    g_fill(g, x + bx, y + by, bx + bs > 70 ? 70 - bx : bs, by + bs > 70 ? 70 - by : bs, c);
                }
    }
    if (t > 1000) an_word(g, 10, 205, "Coda", (int)((t - 1000) / 80) + 1 > 4 ? 4 : (int)((t - 1000) / 80) + 1, RP.cream, RP.walnut_d);
}

static void cr_off(app *a, gfx *g, uint32_t t, const px16 *from)
{
    (void)a;
    an_from(g, from, 0, 0);
    int bs = 1 + (int)(15 * ez_out(ez_seg((float)t, 0, 600)));   /* it all goes to blocks */
    if (bs > 1)
        for (int by = 0; by < LCD_H; by += bs)
            for (int bx = 0; bx < LCD_W; bx += bs) {
                px16 c = g->px[by * g->stride + bx];
                g_fill(g, bx, by, bx + bs > LCD_W ? LCD_W - bx : bs, by + bs > LCD_H ? LCD_H - by : bs, c);
            }
    int k = (int)(256 * ez_out(ez_seg((float)t, 400, 900)));
    for (int y = 0; y < LCD_H && k; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) row[x] = blend565(row[x], C565(0, 0, 0), k);
    }
}

/* ---------------------------------------------------------------- Receiver */
static void rx_boot(gfx *g, uint32_t t)
{
    rx_cabinet(g, 77);
    memset(rx_bmp, 0, sizeof rx_bmp);
    int w = pf_width(&PF_SILK16, "CODA", 1);
    rx_text(RX_W / 2 - w / 2, 15, "CODA", &PF_SILK16);
    rx_text(RX_W / 2 - pf_width(&PF_SILK8, "MUSIC, OFFLINE", 1) / 2, 34, "MUSIC, OFFLINE", &PF_SILK8);
    float warm = ez_seg((float)t, 150, 650), show = ez_seg((float)t, 700, 1300);
    px16 off = blend565(RX_GLASS, RX_OFF, (int)(warm * 256));
    for (int y = 0; y < RX_H; y++)
        for (int x = 0; x < RX_W; x++) {
            int sx = 13 + x * 3, sy = 12 + y * 3;
            int on = rx_bmp[y][x] && (an_hash(x, y) % 1000) < (uint32_t)(show * 1000);
            g_fill(g, sx, sy, 2, 2, on ? RX_ON : off);
        }
    float n = ez_back(ez_seg((float)t, 500, 1200), 1.5f);
    int nx = 16 + (int)((13 + RX_W / 2 * 3 - 16) * n);
    if (t > 400) { g_fill(g, nx - 1, 10, 2, 55, RX_NEEDLE); g_fill(g, nx + 1, 12, 1, 53, RX_EDGE); }
    g_disc(g, 56 * 16, 195 * 16, 24 * 16, RP.silver);
    g_disc(g, 264 * 16, 195 * 16, 24 * 16, RP.silver);
    g_disc(g, 56 * 16, 195 * 16, 16 * 16, RP.silver_l);
    g_disc(g, 264 * 16, 195 * 16, 16 * 16, RP.silver_l);
    if (t > 300) g_disc(g, 153 * 16, 217 * 16, 2 * 16, RP.key);
}

static void rx_off(app *a, gfx *g, uint32_t t, const px16 *from)
{
    (void)a;
    an_from(g, from, 0, 0);
    /* the amber dots go out at random, then the glass cools */
    float gone = ez_seg((float)t, 0, 500);
    for (int y = 12; y < 12 + RX_H * 3; y += 3)
        for (int x = 13; x < 13 + RX_W * 3; x += 3)
            if ((an_hash(x, y) % 1000) < (uint32_t)(gone * 1000)) g_fill(g, x, y, 2, 2, RX_OFF);
    int k = (int)(256 * ez_out(ez_seg((float)t, 450, 900)));
    for (int y = 0; y < LCD_H && k; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) row[x] = blend565(row[x], C565(0, 0, 0), k);
    }
}

/* ---------------------------------------------------------------- Diorama */
static void dio_paint(gfx *g, int dark)
{
    for (int y = 0; y < 106; y++)
        for (int x = 0; x < 160; x++) ck_point(g, x, y, blend565(dio_px[y][x], C565(0, 0, 0), dark));
    g_fill(g, 0, 212, LCD_W, 28, blend565(RP.walnut, C565(0, 0, 0), dark));
}

static void dio_boot(gfx *g, uint32_t t)
{
    dio_scene_t(t);
    /* a dark room; the lamp clicks on */
    int dark = t < 600 ? 215 : 215 - (int)(215 * ez_out(ez_seg((float)t, 600, 1000)));
    dio_paint(g, dark);
    if (t > 600 && t < 660) g_fill(g, 270, 80, 34, 36, RP.led);
    if (t > 1100) {
        int w = pf_width(&PF_PIXEL11, "Coda", 2) + 14;
        g_fill(g, 160, 8, w, 22, RP.walnut_d);
        g_fill(g, 161, 9, w - 2, 20, RP.parch);
        an_word(g, 168, 24, "Coda", (int)((t - 1100) / 80) + 1 > 4 ? 4 : (int)((t - 1100) / 80) + 1, RP.ink, 0);
    }
}

static void dio_off(app *a, gfx *g, uint32_t t, const px16 *from)
{
    (void)a;
    /* the lamp goes off with a click: dark at once; the monitor glows on, then out */
    if (t < 100) { an_from(g, from, 0, 0); return; }
    an_from(g, from, C565(0, 0, 0), 200);
    int glow = (int)(256 * (1 - ez_seg((float)t, 100, 700)));
    if (glow > 0) g_fill_a(g, 68, 150, 104, 36, C565(0x22, 0x26, 0x30), glow);
    int k = (int)(256 * ez_out(ez_seg((float)t, 500, 900)));
    for (int y = 0; y < LCD_H && k; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) row[x] = blend565(row[x], C565(0, 0, 0), k);
    }
}

/* ---------------------------------------------------------------- by theme */
typedef void (*boot_fn)(gfx *, uint32_t);
typedef void (*off_fn)(app *, gfx *, uint32_t, const px16 *);
static const boot_fn BOOTS[] = { boot_draw, room_boot, jb_boot, tb_boot, dk_boot, cr_boot, rx_boot, dio_boot };
static const off_fn OFFS[] = { NULL, room_off, jb_off, tb_off, dk_off, cr_off, rx_off, dio_off };
