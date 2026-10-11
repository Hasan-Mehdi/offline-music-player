/* Three pixel themes on th_pixel.h's grid and materials (docs/h2/pixel; firmware/tools/
 * mock_pixel.py): Jukebox (after Stardew Valley's), Toybox (after the DSi Sound), Deck
 * (Winamp done right). Each has its own home, page, header, rows and now bar; the rest is
 * the room's. Part of app.c, like th_poster.h. */

/* ================================================================== Jukebox */
static const px16 JB_SLOT = C565(0xec, 0xd2, 0x9e), JB_SLOT_B = C565(0xb9, 0x88, 0x50),
                  JB_SEL = C565(0xd2, 0x86, 0x3a), JB_SEL_D = C565(0xa0, 0x5c, 0x22), JB_PAPER = C565(0xcd, 0xb8, 0x97);

static void jb_wallpaper(gfx *g)
{
    g_fill(g, 0, 0, LCD_W, LCD_H, RP.wall);
    for (int b = 0; b < 120; b += 4)
        for (int c = (b / 4) % 2 * 2; c < 160; c += 4) ck_point(g, c, b, JB_PAPER);
}

/* a heavy two-tone walnut frame with parchment inside (cells) */
static void jb_frame(gfx *g, int a, int b, int c, int d)
{
    ck_rrect(g, a, b, c, d, RP.walnut_d, 2);
    ck_rrect(g, a + 1, b + 1, c - 1, d - 1, RP.walnut, 2);
    ck_rect(g, a + 3, b + 1, c - 4, b + 2, RP.walnut_hi);
    ck_rect(g, a + 1, b + 3, a + 2, d - 4, RP.walnut_hi);
    ck_rect(g, a + 3, d - 2, c - 4, d - 1, RP.walnut_d);
    ck_rect(g, c - 2, b + 3, c - 1, d - 4, RP.walnut_d);
    ck_rrect(g, a + 3, b + 3, c - 3, d - 3, RP.walnut_d, 1);
    ck_rrect(g, a + 4, b + 4, c - 4, d - 4, RP.parch, 1);
}

/* the name on a sign hung from the wall */
static void jb_sign(app *a, gfx *g, const char *text)
{
    int w = px_ascii(text) ? pf_width(&PF_PIXEL11, text, 2) : 100, c0 = (LCD_W / 2 - w / 2 - 12) / 2, c1 = (LCD_W / 2 + w / 2 + 12) / 2;
    ck_rrect(g, c0 - 1, 1, c1 + 1, 14, RP.walnut_d, 1);
    ck_material(g, c0, 2, c1, 13, MAT_WOOD, 81, 1);
    ck_point(g, c0 + 2, 4, RP.cream);
    ck_point(g, c1 - 3, 4, RP.cream);
    if (px_ascii(text)) pf_text(g, &PF_PIXEL11, LCD_W / 2 - w / 2, 22, text, RP.walnut_d, 2);
    px_text(a, g, LCD_W / 2 - w / 2, 20, text, RP.cream, 200);
}

static void jb_page(app *a, gfx *g)
{
    jb_wallpaper(g);
    if (a->view != V_MENU && a->view != V_WHEEL && a->view != V_NOW) jb_frame(g, 2, 12, 158, 106);
}

static void jb_header(app *a, gfx *g, int sec, const char *title, const char *right)
{
    (void)sec;
    jb_sign(a, g, title);
    px_battery(a, g, LCD_W - 8, 17, RP.ink);
    if (right) txt(a, g, F_MONO10, 8, 17, right, RP.sub, 0);
}

/* songs and the rest in parchment slots; the picked one is orange */
static row_ink jb_row(app *a, gfx *g, int y, int h, int state)
{
    int foc = state & ROW_FOCUS, live = state & ROW_LIVE, b = (y + 1) / 2, d = (y + h - 2) / 2;
    float cy = foc ? cursor_y(a, y) : (float)y;
    row_ink k = { RP.ink, RP.sub, C565(0x8a, 0x62, 0x3a), RP.leather_d, 0 };
    ck_rect(g, 7, b, 153, d, JB_SLOT_B);
    ck_rect(g, 8, b + 1, 152, d - 1, JB_SLOT);
    if (foc || live) {
        int fb = foc ? ((int)lrintf(cy) + 1) / 2 : b, fd = fb + (d - b);
        ck_rect(g, 8, fb + 1, 152, fd - 1, foc && (state & ROW_ADJ) ? RP.leaf : JB_SEL);
        ck_rect(g, 8, fb + 1, 152, fb + 2, JB_SEL_D);
        if (foc) ck_pointer(g, 0, (int)cy + h / 2, a->now_ms, RP.walnut_d, RP.cream);
        if (!foc || (cy > y - 8 && cy < y + 8)) { k.fg = RP.cream; k.sub = RP.parch_l; k.note = RP.cream; k.on = 1; }
    }
    return k;
}

static void jb_nowbar(app *a, gfx *g)
{
    if (a->view == V_MENU) return;                      /* the jukebox's head says what's playing */
    px_nowbar(a, g);
}

static const palette *jb_pal(app *a)
{
    static palette pp;
    static int made;
    if (!made) {
        pp = *px_pal(a);
        pp.paper = RP.parch; pp.blue = RP.leather_d; pp.rule = JB_SLOT_B; pp.wash = JB_SLOT;
        made = 1;
    }
    return &pp;
}

static void jb_home(app *a, gfx *g)
{
    jb_sign(a, g, "Coda");
    px_battery(a, g, LCD_W - 8, 17, RP.ink);
    jb_frame(g, 3, 16, 157, 120);
    ck_rect(g, 8, 44, 152, 45, RP.parch_d);
    ck_rect(g, 8, 45, 152, 46, RP.parch_l);
    /* what's playing, in the jukebox's head */
    ck_rrect(g, 9, 22, 27, 40, RP.walnut_d, 1);
    if (a->cur_valid) cover(a, g, a->cur, ART_S, 20, 46, 32);
    txt(a, g, F_SEMI11, 62, 56, "Currently playing:", C565(0x8a, 0x62, 0x3a), 0);
    const lib_track *t = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    txt_fit(a, g, F_SEMI11, 62, 70, t ? t->title : "nothing yet", 222, RP.ink, 0);
    if (t) txt_fit(a, g, F_BODY10, 62, 83, t->artist, 222, C565(0x7a, 0x5a, 0x3a), 0);
    /* the menu in slots, five at a time */
    list_state *l = &a->ls[V_MENU];
    l->n = N_MENU;
    list_follow(l, 5);
    int top = (int)l->top;
    for (int i = top; i < top + 5 && i < N_MENU; i++) {
        int y = 94 + (i - top) * 28, foc = i == l->sel;
        row_ink k = jb_row(a, g, y, 26, foc ? ROW_FOCUS : 0);
        float u = foc && a->ui_view == V_MENU ? ez_seg((float)(a->now_ms - a->ui_t0), 60, 560) : 1;
        ck_sym(g, px_sym(i), 34, y + 13, 16, k.fg, foc ? JB_SEL : JB_SLOT, foc ? 0 : RP.key, u);
        if (k.on) pf_text(g, &PF_PIXEL11, 48, y + 21, menu_items[i], JB_SEL_D, 2);
        pf_text(g, &PF_PIXEL11, 48, y + 19, menu_items[i], k.fg, 2);
        char n[24] = "";
        if (i == 0) commas(n, sizeof n, brain_n());
        else if (i == 2 && a->qn) snprintf(n, sizeof n, "%d of %d", a->qpos + 1, a->qn);
        if (n[0]) txt_right(a, g, F_BODY10, 286, y + 17, n, k.on ? RP.cream : RP.sub);
    }
    /* the wooden scrollbar */
    ck_rect(g, 148, 48, 151, 116, RP.walnut);
    int th = 68 * 5 / N_MENU, ty = 48 + (68 - th) * top / (N_MENU - 5);
    ck_rect(g, 148, ty, 151, ty + th, RP.parch_l);
}

/* ================================================================== Toybox */
static const px16 TB_CHK1 = C565(0xee, 0xe5, 0xd4), TB_CHK2 = C565(0xe1, 0xd5, 0xc0), TB_CARD = C565(0xfb, 0xf8, 0xf1),
                  TB_CARD_B = C565(0xbf, 0xb2, 0x9c), TB_OUTL = C565(0x7d, 0x6a, 0x55);

static void tb_page(app *a, gfx *g)
{
    int off = (int)(a->now_ms / 125) % 16;               /* it drifts, slowly */
    for (int b = 0; b < 120; b++)
        for (int c = 0; c < 160; c += 8 - ((c + off) % 8)) {
            int c2 = c + 8 - ((c + off) % 8);
            if (c2 > 160) c2 = 160;
            ck_rect(g, c, b, c2, b + 1, (((c + off) / 8) + ((b + off) / 8)) % 2 ? TB_CHK1 : TB_CHK2);
        }
}

static void tb_card(gfx *g, int a, int b, int c, int d)
{
    ck_rrect(g, a, b, c, d, TB_CARD_B, 2);
    ck_rrect(g, a + 1, b + 1, c - 1, d - 1, TB_CARD, 2);
}

/* a toy button: outline, its side, its face, a highlight; pressed = face down to the side */
static void tb_button(gfx *g, int a, int b, int c, int d, px16 face, px16 dark, px16 light, int pressed, int r)
{
    ck_rrect(g, a, b + 1, c, d + 1, TB_OUTL, r);
    ck_rrect(g, a + 1, b + 1 + pressed, c - 1, d, dark, r);
    ck_rrect(g, a + 1, b + 1 + pressed, c - 1, d - 3 + pressed, face, r);
    ck_rect(g, a + 1 + r, b + 2 + pressed, c - 1 - r, b + 3 + pressed, light);
}

static void tb_header(app *a, gfx *g, int sec, const char *title, const char *right)
{
    tb_card(g, 2, 1, 158, 14);
    int mat = px_mat(sec);
    ck_sym(g, px_sym(sec), 16, 15, 16, mat_base(mat) == RP.shade ? RP.ink : mat_base(mat), TB_CARD, RP.key, 1);
    px_text(a, g, 30, 21, title, RP.ink, 180);
    px_battery(a, g, LCD_W - 10, 18, RP.ink);
    if (right) txt_right(a, g, F_MONO10, LCD_W - 62, 18, right, RP.sub);
}

static row_ink tb_row(app *a, gfx *g, int y, int h, int state)
{
    int foc = state & ROW_FOCUS, live = state & ROW_LIVE, b = (y + 1) / 2, d = (y + h - 1) / 2;
    float cy = foc ? cursor_y(a, y) : (float)y;
    row_ink k = { RP.ink, RP.sub, RP.sub, RP.leaf_d, 0 };
    if (foc || live) {
        int fb = foc ? ((int)lrintf(cy) + 1) / 2 : b;
        int mat = foc ? (state & ROW_ADJ ? MAT_KEY : MAT_LEAF) : MAT_KEY;
        tb_button(g, 3, fb, 157, fb + (d - b), mat_base(mat), mat == MAT_LEAF ? RP.leaf_d : RP.key_d,
                  mat == MAT_LEAF ? RP.leaf_l : RP.key_l, 0, 2);
        if (!foc || (cy > y - 8 && cy < y + 8)) {
            px16 on = mat_ink(mat);
            k.fg = on; k.sub = mat == MAT_LEAF ? RP.leaf_l : RP.walnut; k.note = on; k.on = 1;
        }
        return k;
    }
    tb_card(g, 3, b, 157, d);
    return k;
}

static void tb_nowbar(app *a, gfx *g)
{
    const int y0 = BAR_Y;
    tb_card(g, 2, y0 / 2, 158, 120);
    if (a->cur_valid && a->ps.length_ms)
        ck_rect(g, 4, y0 / 2 + 1, 4 + (int)((uint64_t)152 * a->ps.elapsed_ms / a->ps.length_ms), y0 / 2 + 2, RP.key);
    const lib_track *t = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    if (a->notice[0]) { txt_fit(a, g, F_BOLD11, 10, y0 + 18, a->notice, LCD_W - 20, RP.ink, 0); return; }
    if (!t) { txt(a, g, F_BODY10, 10, y0 + 18, "Nothing playing. Spin the wheel.", RP.sub, 0); return; }
    cover(a, g, a->cur, ART_S, 8, y0 + 5, 22);
    txt_fit(a, g, F_BOLD11, 36, y0 + 15, t->title, 226, RP.ink, 0);
    txt_fit(a, g, F_BODY10, 36, y0 + 26, t->artist, 226, RP.sub, 0);
    char e[16];
    mmss(e, sizeof e, a->ps.elapsed_ms / 1000);
    txt_right(a, g, F_MONO10, LCD_W - 10, y0 + 15, e, RP.ink);
}

static const palette *tb_pal(app *a)
{
    static palette pp;
    static int made;
    if (!made) { pp = *px_pal(a); pp.paper = TB_CHK1; pp.wash = TB_CARD; pp.rule = TB_CARD_B; made = 1; }
    return &pp;
}

static void tb_home(app *a, gfx *g)
{
    tb_card(g, 3, 2, 157, 14);
    pf_text(g, &PF_PIXEL11, 14, 22, "Coda", RP.ink, 2);
    ck_rect(g, 28, 7, 30, 9, RP.key);
    px_battery(a, g, LCD_W - 10, 18, RP.ink);
    int cur = fx_clamp(a->ls[V_MENU].sel, 0, N_MENU - 1);
    float t = a->ui_view == V_MENU ? (float)(a->now_ms - a->ui_t0) : 1e6f;
    int press = t < 90 ? 2 : 1;
    /* the two giant buttons */
    int p1 = cur == 0 ? press : 0, p2 = cur == 1 ? press : 0;
    tb_button(g, 4, 17, 78, 74, RP.leaf, RP.leaf_d, RP.leaf_l, p1, 3);
    ck_sym(g, SYM_WHEEL, 82, 62 + 2 * p1, 62, RP.cream, RP.leaf, RP.key, cur == 0 ? ez_seg(t, 60, 560) : 1);
    pf_text(g, &PF_PIXEL11, 16, 136 + 2 * p1, "Wheel", RP.leaf_d, 2);
    pf_text(g, &PF_PIXEL11, 16, 134 + 2 * p1, "Wheel", RP.cream, 2);
    tb_button(g, 82, 17, 156, 74, RP.key, RP.key_d, RP.key_l, p2, 3);
    g_fill(g, 206, 42 + 2 * p2, 64, 64, TB_CARD);
    if (a->cur_valid) cover(a, g, a->cur, ART_M, 208, 44 + 2 * p2, 60);
    pf_text(g, &PF_PIXEL11, 178, 134 + 2 * p2, "Now playing", RP.ink, 2);
    if (cur < 2) ck_pointer(g, cur == 0 ? 0 : 156, 60, a->now_ms, RP.walnut_d, RP.cream);
    /* the round ones */
    for (int i = 2; i < N_MENU; i++) {
        int cx = 17 + (i - 2) * 25, foc = i == cur, mat = px_mat(i), dn = foc ? press - 1 : 0;
        px16 face = mat == MAT_SHADE ? TB_CARD : mat_base(mat), dark = mat == MAT_LEAF ? RP.leaf_d : mat == MAT_KEY ? RP.key_d :
                    mat == MAT_SAGE ? RP.sage_d : mat == MAT_SILVER ? RP.silver_d : mat == MAT_FELT ? RP.felt_d : C565(0xd8, 0xcf, 0xbf);
        if (foc) g_disc(g, (2 * cx + 1) * 16, 186 * 16, 27 * 16, TB_CARD);
        g_disc(g, (2 * cx + 1) * 16, 188 * 16, 23 * 16, TB_OUTL);
        g_disc(g, (2 * cx + 1) * 16, 188 * 16, 21 * 16, dark);
        g_disc(g, (2 * cx + 1) * 16, (184 + 2 * dn) * 16, 21 * 16, face);
        px16 ink = mat_ink(mat);
        ck_sym(g, px_sym(i), 2 * cx + 1, 184 + 2 * dn, 22, ink, face, i == 2 ? RP.key : 0, foc ? ez_seg(t, 60, 560) : 1);
    }
    /* what the picked one is, in a speech bubble */
    if (cur >= 2) {
        int cx = 17 + (cur - 2) * 25, bx = cx - 40 < 3 ? 3 : cx - 40 > 77 ? 77 : cx - 40;
        tb_card(g, bx, 107, bx + 80, 119);
        ck_rect(g, cx - 2, 105, cx + 3, 108, TB_CARD);
        ck_point(g, cx, 104, TB_CARD);
        int nw = text_w(F(a, F_SEMI11), menu_items[cur], 0);
        txt(a, g, F_SEMI11, 2 * bx + 8, 228, menu_items[cur], RP.ink, 0);
        txt_fit(a, g, F_BODY10, 2 * bx + 14 + nw, 228, MENU_DESC[cur], 150 - nw, RP.sub, 0);
    }
}

/* ================================================================== Deck */
static const px16 DK_AMBER = C565(0xff, 0xa8, 0x3a), DK_AMBER_D = C565(0x2c, 0x1b, 0x0e), DK_GLASS = C565(0x1b, 0x13, 0x0d),
                  DK_LIST = C565(0x14, 0x0e, 0x0a), DK_ROWTX = C565(0xd9, 0xcf, 0xbf);

static void dk_seg7(gfx *g, int x, int y, char ch, px16 on, px16 off)
{
    static const char *const SEG[10] = { "abcdef", "bc", "abged", "abgcd", "fgbc", "afgcd", "afgedc", "abc", "abcdefg", "abcdfg" };
    const char *lit = ch >= '0' && ch <= '9' ? SEG[ch - '0'] : "";
    struct { char k; int a, b, c, d; } s[7] = {
        { 'a', x + 1, y, x + 5, y + 1 }, { 'g', x + 1, y + 5, x + 5, y + 6 }, { 'd', x + 1, y + 10, x + 5, y + 11 },
        { 'f', x, y + 1, x + 1, y + 5 }, { 'b', x + 5, y + 1, x + 6, y + 5 }, { 'e', x, y + 6, x + 1, y + 10 },
        { 'c', x + 5, y + 6, x + 6, y + 10 } };
    for (int i = 0; i < 7; i++) ck_rect(g, s[i].a, s[i].b, s[i].c, s[i].d, strchr(lit, s[i].k) ? on : off);
}

static void dk_page(app *a, gfx *g)
{
    if (a->view == V_MENU) { ck_material(g, 0, 0, 160, 120, MAT_WOOD, 101, 0); return; }
    ck_material(g, 0, 0, 160, 120, MAT_WOOD, 103, 0);
    ck_rect(g, 2, 16, 158, 105, DK_LIST);
    ck_rect(g, 154, 17, 157, 104, C565(0x2a, 0x1e, 0x15));
}

static void dk_header(app *a, gfx *g, int sec, const char *title, const char *right)
{
    ck_material(g, 0, 0, 160, 14, MAT_SILVER, 102, 0);
    for (int y = 3; y < 12; y += 2) { ck_rect(g, 3, y, 14, y + 1, RP.silver_d); ck_rect(g, 140, y, 157, y + 1, RP.silver_d); }
    ck_sym(g, px_sym(sec), 40, 14, 14, RP.ink, RP.silver, RP.key, 1);
    px_text(a, g, 52, 20, title, RP.ink, 160);
    if (right) txt_right(a, g, F_MONO10, 274, 20, right, RP.walnut);
    (void)right;
}

/* the playlist window: amber on black; the picked row inverted */
static row_ink dk_row(app *a, gfx *g, int y, int h, int state)
{
    int foc = state & ROW_FOCUS, live = state & ROW_LIVE;
    float cy = foc ? cursor_y(a, y) : (float)y;
    row_ink k = { DK_ROWTX, RP.felt_d, RP.felt_d, DK_AMBER, 0 };
    if (live && !foc) { k.fg = DK_AMBER; k.sub = C565(0xc0, 0x80, 0x30); k.note = DK_AMBER; }
    if (foc) {
        g_fill(g, 6, (int)lrintf(cy) + 1, 300, h - 2, state & ROW_ADJ ? RP.leaf : DK_AMBER);
        if (cy > y - 8 && cy < y + 8) { k.fg = DK_LIST; k.sub = C565(0x5a, 0x3a, 0x1a); k.note = DK_LIST; k.on = 1; }
    }
    return k;
}

static void dk_nowbar(app *a, gfx *g)
{
    if (a->view == V_MENU) return;                      /* the deck itself shows it */
    const int y0 = BAR_Y;
    ck_material(g, 0, y0 / 2, 160, 120, MAT_SILVER, 104, 0);
    g_fill(g, 4, y0 + 4, LCD_W - 8, 22, DK_GLASS);
    const lib_track *t = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    if (a->notice[0]) { txt_fit(a, g, F_BOLD11, 10, y0 + 19, a->notice, LCD_W - 20, DK_AMBER, 0); return; }
    if (!t) { txt(a, g, F_BODY10, 10, y0 + 19, "stopped", DK_AMBER, 0); return; }
    char e[16];
    mmss(e, sizeof e, a->ps.elapsed_ms / 1000);
    txt(a, g, F_MONO12, 10, y0 + 20, e, DK_AMBER, 0);
    txt_fit(a, g, F_BOLD11, 54, y0 + 19, t->title, LCD_W - 66, DK_AMBER, 0);
}

static const palette *dk_pal(app *a)
{
    static palette pp;
    static int made;
    if (!made) {
        pp = *px_pal(a);
        pp.paper = DK_LIST; pp.ink = DK_ROWTX; pp.blue = DK_AMBER; pp.sub = RP.felt_d; pp.rule = C565(0x2a, 0x1e, 0x15);
        pp.wash = DK_GLASS; pp.strip_bg = RP.walnut_d;
        made = 1;
    }
    return &pp;
}

static void dk_home(app *a, gfx *g)
{
    /* title bar: the name between grooves */
    ck_material(g, 0, 0, 160, 9, MAT_WOOD, 101, 0);
    for (int y = 2; y < 8; y += 2) { ck_rect(g, 4, y, 60, y + 1, RP.walnut_d); ck_rect(g, 100, y, 126, y + 1, RP.walnut_d); }
    pf_text(g, &PF_PIXEL11, 130, 17, "Coda", RP.walnut_d, 2);
    pf_text(g, &PF_PIXEL11, 130, 15, "Coda", RP.cream, 2);
    /* the faceplate: display, cover, seek, keys, the volume knob */
    ck_material(g, 0, 9, 160, 62, MAT_SILVER, 102, 0);
    ck_vents(g, 104, 48, 156, 60);
    ck_rrect(g, 3, 11, 102, 45, C565(0x0e, 0x09, 0x06), 1);
    ck_rect(g, 4, 12, 101, 44, DK_GLASS);
    int playing = a->cur_valid && a->ps.playing;
    if (playing) { g_convex(g, (int32_t[]){ 14 * 16, 30 * 16, 14 * 16, 42 * 16, 20 * 16, 36 * 16 }, 3, DK_AMBER); }
    else { ck_rect(g, 7, 15, 8, 21, DK_AMBER); ck_rect(g, 9, 15, 10, 21, DK_AMBER); }
    char e[8];
    uint32_t sec = a->cur_valid ? a->ps.elapsed_ms / 1000 : 0;
    snprintf(e, sizeof e, "%u%02u", (unsigned)(sec / 60 % 10), (unsigned)(sec % 60));
    dk_seg7(g, 14, 13, e[0], DK_AMBER, DK_AMBER_D);
    ck_point(g, 22, 17, DK_AMBER);
    ck_point(g, 22, 21, DK_AMBER);
    dk_seg7(g, 25, 13, e[1], DK_AMBER, DK_AMBER_D);
    dk_seg7(g, 33, 13, e[2], DK_AMBER, DK_AMBER_D);
    uint8_t bands[12];
    if (!playing || !plat_spectrum(bands)) memset(bands, 0, sizeof bands);
    for (int i = 0; i < 14; i++) {
        int h = bands[i % 12] * 14 / 255, bx = 52 + i * 3;
        if (h > 0) ck_rect(g, bx, 28 - h, bx + 2, 28, DK_AMBER);
        ck_rect(g, bx, 26 - h, bx + 2, 27 - h, RP.cream);
        ck_rect(g, bx, 29, bx + 2, 30, DK_AMBER_D);
    }
    ck_rrect(g, 104, 11, 157, 45, RP.silver_d, 1);
    ck_rect(g, 105, 12, 156, 44, DK_GLASS);
    if (a->cur_valid) cover(a, g, a->cur, ART_M, 214, 24, 62);
    int sk = a->cur_valid && a->ps.length_ms ? (int)((uint64_t)96 * a->ps.elapsed_ms / a->ps.length_ms) : 0;
    ck_rect(g, 4, 48, 100, 50, C565(0x0e, 0x09, 0x06));
    ck_rect(g, 4, 48, 4 + sk, 50, RP.key);
    ck_rrect(g, 2 + sk, 46, 7 + sk, 52, RP.silver_l, 1);
    static const int KEYS[5] = { SYM_HISTORY, SYM_NOW, SYM_PAUSE, SYM_STOP, SYM_NEXT };
    for (int i = 0; i < 5; i++) {
        int kx = 4 + i * 14;
        ck_rrect(g, kx, 53, kx + 12, 61, RP.slot, 1);
        ck_rrect(g, kx, 53, kx + 12, 60, RP.silver_l, 1);
        ck_rect(g, kx + 1, 59, kx + 11, 60, RP.silver_d);
        ck_sym(g, KEYS[i], 2 * kx + 12, 112, 10, RP.ink, RP.silver_l, 0, 1);
    }
    g_disc(g, 176 * 16, 112 * 16, 16 * 16, RP.slot);
    g_disc(g, 176 * 16, 110 * 16, 16 * 16, RP.silver_l);
    ck_point(g, 99, 55, RP.key);
    /* the playlist window: the sections; the marquee under the time */
    ck_material(g, 0, 62, 160, 120, MAT_WOOD, 103, 0);
    ck_rect(g, 2, 64, 158, 118, DK_LIST);
    const lib_track *t = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    if (t) {
        int sw = 176, off = (int)(a->now_ms / 40) % (text_w(F(a, F_BOLD11), t->title, 0) + sw);
        g_clip(g, 10, 62, 10 + sw, 76);
        txt(a, g, F_BOLD11, 10 + sw - off, 73, t->title, DK_AMBER, 0);
        g_noclip(g);
    }
    txt(a, g, F_MONO10, 120, 86, "opus 48kHz", DK_AMBER, 0);
    list_state *l = &a->ls[V_MENU];
    l->n = N_MENU;
    for (int i = 0; i < N_MENU; i++) {
        int y = 130 + i * 13, foc = i == l->sel;
        if (foc) g_fill(g, 6, y, 300, 12, DK_AMBER);
        px16 c = foc ? DK_LIST : DK_ROWTX;
        char n[8];
        snprintf(n, sizeof n, "%02d", i + 1);
        txt(a, g, F_MONO10, 10, y + 10, n, foc ? DK_LIST : RP.felt_d, 0);
        txt(a, g, F_SEMI11, 30, y + 10, menu_items[i], c, 0);
        txt_fit(a, g, F_BODY10, 120, y + 10, MENU_DESC[i], 180, foc ? C565(0x5a, 0x3a, 0x1a) : RP.felt_d, 0);
    }
}
