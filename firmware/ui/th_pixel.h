/* The pixel themes' shared look (docs/h2/room, docs/h2/pixel; firmware/tools/mock_room.py):
 * the listener's room as materials on a 2x2-pixel grid -- a walnut shelf for a header with
 * its light strip, a leaf-green cursor slab with a bobbing pointer, material keycaps, a
 * walnut desk for the now bar, covers standing on planks in Explore. Room uses all of it;
 * the others override their home (and some parts). Part of app.c, like th_poster.h.
 * Pixel text is Pixelify Sans on the grid; anything it can't spell (non-Latin names) falls
 * back to the card's fonts. */

/* each section's material, so a section looks the same on every screen */
static int px_mat(int sec)
{
    switch (sec) {
    case SEC_WHEEL: case SEC_SONGS: case SEC_WHEELSET: return MAT_WOOD;
    case SEC_NOW: case SEC_CLOCK: return MAT_LEATHER;
    case SEC_QUEUE: case SEC_GENRES: case SEC_SCREEN: return MAT_SHADE;
    case SEC_EXPLORE: case SEC_ARTISTS: case SEC_PLAYBACK: return MAT_LEAF;
    case SEC_SEARCH: case SEC_OSTS: case SEC_SLEEP: return MAT_SAGE;
    case SEC_LIBRARY: case SEC_BT: case SEC_SOUND: return MAT_SILVER;
    case SEC_LIKED: case SEC_THEME: return MAT_KEY;
    default: return MAT_FELT;
    }
}

static int px_sym(int sec)
{
    static const int S[SEC_COUNT] = {
        [SEC_WHEEL] = SYM_WHEEL, [SEC_NOW] = SYM_NOW, [SEC_QUEUE] = SYM_QUEUE, [SEC_EXPLORE] = SYM_EXPLORE,
        [SEC_SEARCH] = SYM_SEARCH, [SEC_LIBRARY] = SYM_LIBRARY, [SEC_LIKED] = SYM_LIKED, [SEC_SETTINGS] = SYM_SETTINGS,
        [SEC_SONGS] = SYM_SONGS, [SEC_ARTISTS] = SYM_ARTISTS, [SEC_GENRES] = SYM_GENRES, [SEC_OSTS] = SYM_OSTS,
        [SEC_HISTORY] = SYM_HISTORY, [SEC_BT] = SYM_BT, [SEC_CLOCK] = SYM_CLOCK, [SEC_SLEEP] = SYM_SLEEP,
        [SEC_SOUND] = SYM_SOUND, [SEC_SCREEN] = SYM_SCREEN, [SEC_THEME] = SYM_THEME, [SEC_WHEELSET] = SYM_WHEEL,
        [SEC_PLAYBACK] = SYM_PLAYBACK,
    };
    return sec >= 0 && sec < SEC_COUNT ? S[sec] : SYM_SETTINGS;
}

/* the room as a palette, for the screens every theme shares (the Wheel, Now playing, the
 * clock): wall for paper, walnut ink, leaf green for the accent, the orange keycap for live */
static const palette *px_pal(app *a)
{
    static palette pp;
    static int made;
    if (!made) {
        pp = a->th.day;
        pp.paper = RP.wall; pp.ink = RP.ink; pp.blue = RP.leaf_d; pp.red = RP.key; pp.sub = RP.sub;
        pp.rule = RP.wall_sh; pp.wash = RP.parch_d; pp.strip_bg = RP.walnut; pp.strip_fg = RP.cream;
        pp.strip_sub = RP.felt_l;
        made = 1;
    }
    return &pp;
}

static int px_ascii(const char *s)
{
    for (; *s; s++) if ((unsigned char)*s >= 0x80) return 0;
    return 1;
}

/* a label on the grid, cut to fit; non-Latin -> the card's font */
static int px_text(app *a, gfx *g, int x, int yb, const char *s, px16 c, int maxw)
{
    if (!px_ascii(s)) return txt_fit(a, g, F_POSTER15, x, yb - 3, s, maxw, c, T_TRACK(-3));
    char buf[96];
    int n = 0, w = 0;
    for (; s[n] && n < (int)sizeof buf - 3; n++) {
        int cw = PF_PIXEL11.w[(unsigned char)s[n] - 32] * 2;
        if (w + cw > maxw) {
            while (n > 0 && w + 2 * PF_PIXEL11.w['.' - 32] * 2 > maxw) {
                n--;
                w -= PF_PIXEL11.w[(unsigned char)s[n] - 32] * 2;
            }
            memcpy(buf, s, (size_t)n);
            memcpy(buf + n, "..", 3);
            return pf_text(g, &PF_PIXEL11, x, yb, buf, c, 2);
        }
        w += cw;
    }
    return pf_text(g, &PF_PIXEL11, x, yb, s, c, 2);
}

/* a battery on the grid, in the given ink */
static void px_battery(app *a, gfx *g, int x_right, int yb, px16 ink)
{
    int pct = plat_battery(), chg = plat_charging();
    if (pct < 0) return;
    if (pct > 100) pct = 100;
    int c0 = x_right / 2 - 9, r0 = yb / 2 - 4;
    ck_rect(g, c0, r0, c0 + 8, r0 + 1, ink);
    ck_rect(g, c0, r0 + 3, c0 + 8, r0 + 4, ink);
    ck_rect(g, c0, r0, c0 + 1, r0 + 4, ink);
    ck_rect(g, c0 + 7, r0, c0 + 8, r0 + 4, ink);
    ck_rect(g, c0 + 8, r0 + 1, c0 + 9, r0 + 3, ink);
    int fill = 1 + 5 * pct / 100;
    ck_rect(g, c0 + 1, r0 + 1, c0 + 1 + fill, r0 + 3, chg ? RP.leaf_l : pct <= 15 ? RP.red : ink);
    char s[8];
    snprintf(s, sizeof s, "%d%%", pct);
    txt_right(a, g, F_MONO10, x_right - 22, yb, s, ink);
}

/* ------------------------------------------------------------------ page, header, rows */
static void px_page(app *a, gfx *g) { (void)a; g_fill(g, 0, 0, LCD_W, LCD_H, RP.wall); }

/* the walnut shelf (its light strip under it), the section's tab on it */
static void px_shelf_strip(gfx *g, int rows)
{
    ck_material(g, 0, 0, 160, rows, MAT_WOOD, 7, 0);
    ck_rect(g, 0, rows, 160, rows + 1, RP.led);
    ck_rect(g, 0, rows + 1, 160, rows + 2, RP.wall_sh);
}

static void px_header(app *a, gfx *g, int sec, const char *title, const char *right)
{
    px_shelf_strip(g, 13);
    int mat = px_mat(sec);
    px16 base = mat_base(mat), ink = mat_ink(mat);
    char t[64];
    snprintf(t, sizeof t, "%s", title);
    int tw = px_ascii(t) ? pf_width(&PF_PIXEL11, t, 2) : text_w(F(a, F_POSTER15), t, T_TRACK(-3));
    if (tw > 180) tw = 180;
    int c1 = (34 + tw + 12) / 2;
    ck_rrect(g, 1, 1, c1 + 1, 13, RP.walnut_d, 2);
    ck_material(g, 2, 2, c1, 12, mat, 11, 2);
    ck_sym(g, px_sym(sec), 20, 13, 16, ink, base, mat_acc(mat), 1);
    if (ink == RP.cream && px_ascii(t)) pf_text(g, &PF_PIXEL11, 32, 21, t, RP.walnut_d, 2);
    px_text(a, g, 32, 19, t, ink, 180);
    px_battery(a, g, LCD_W - 8, 17, RP.cream);
    if (right) txt_right(a, g, F_MONO10, LCD_W - 60, 17, right, RP.felt_l);
}

static row_ink px_row(app *a, gfx *g, int y, int h, int state)
{
    row_ink k = { RP.ink, RP.sub, RP.sub, RP.leaf_d, 0 };
    if (state & (ROW_FOCUS | ROW_LIVE)) {
        int foc = state & ROW_FOCUS;
        float cy = foc ? cursor_y(a, y) : (float)y;
        int b = ((int)lrintf(cy) + 1) / 2, mat = foc ? (state & ROW_ADJ ? MAT_KEY : MAT_LEAF) : MAT_KEY;
        ck_rrect(g, 2, b, 158, b + h / 2, mat == MAT_LEAF ? RP.leaf_d : RP.key_d, 2);
        ck_material(g, 3, b, 157, b + h / 2 - 1, mat, 50 + y, 2);
        if (foc) ck_pointer(g, 0, (int)cy + h / 2, a->now_ms, RP.walnut_d, RP.cream);
        if (!foc || (cy > y - 8 && cy < y + 8)) {
            px16 on = mat_ink(mat);
            k.fg = on; k.sub = mat == MAT_LEAF ? RP.leaf_l : RP.walnut; k.note = on; k.accent = on; k.on = 1;
        }
        return k;
    }
    for (int x = 6; x < 154; x += 2) ck_point(g, x, (y + h - 2) / 2, RP.felt);
    if (state & ROW_DIM) k.fg = RP.sub;
    return k;
}

static void px_label(app *a, gfx *g, int x, int yb, const char *s, px16 c, int big, int maxw)
{
    (void)big;
    px_text(a, g, x, yb, s, c, maxw);
}

static void px_button(app *a, gfx *g, int x, int y, int w, int h, int sym, const char *label, int foc, int kind)
{
    int mat = foc ? MAT_LEAF : kind ? MAT_SILVER : MAT_WOOD, a0 = x / 2, b0 = y / 2, c0 = (x + w) / 2, d0 = (y + h) / 2;
    if (foc) { b0--; d0--; ck_rrect(g, a0 - 1, b0 - 1, c0 + 1, d0 + 1, RP.cream, 2); }
    ck_material(g, a0, b0, c0, d0, mat, 31 + kind, 2);
    px16 ink = mat_ink(mat);
    int s = h - 10;
    ck_sym(g, sym, 2 * a0 + 6 + s / 2, 2 * b0 + h / 2, s, ink, mat_base(mat), 0, 1);
    px_text(a, g, 2 * a0 + 12 + s, 2 * b0 + h / 2 + 7, label, ink, w - s - 18);
}

/* the walnut desk: cover, the song, the time, orange progress along its edge */
static void px_nowbar(app *a, gfx *g)
{
    const int y0 = BAR_Y;
    ck_material(g, 0, y0 / 2, 160, LCD_H / 2, MAT_WOOD, 5, 0);
    if (a->notice[0]) { txt_fit(a, g, F_BOLD11, 8, y0 + 18, a->notice, LCD_W - 16, RP.cream, 0); return; }
    if (a->peeking) {
        const lib_track *t = lib_get(a->L, a->peek_idx);
        txt(a, g, F_MONO10, 8, y0 + 16, "peeking", RP.key_l, 0);
        if (t) txt_fit(a, g, F_BOLD11, 62, y0 + 16, t->title, LCD_W - 70, RP.cream, 0);
        return;
    }
    if (!a->cur_valid) { txt(a, g, F_BODY10, 8, y0 + 18, "Nothing playing. Spin the wheel.", RP.felt_l, 0); return; }
    const lib_track *t = lib_get(a->L, a->cur);
    if (a->ps.length_ms) ck_rect(g, 0, y0 / 2, (int)((uint64_t)160 * a->ps.elapsed_ms / a->ps.length_ms), y0 / 2 + 1, RP.key);
    cover(a, g, a->cur, ART_S, 4, y0 + 3, 24);
    if (t) {
        txt_fit(a, g, F_BOLD11, 34, y0 + 14, t->title, 230, RP.cream, 0);
        txt_fit(a, g, F_BODY10, 34, y0 + 25, t->artist, 230, RP.felt_l, 0);
    }
    char e[16];
    mmss(e, sizeof e, a->ps.elapsed_ms / 1000);
    txt_right(a, g, F_MONO10, LCD_W - 6, y0 + 14, e, RP.cream);
}

/* ------------------------------------------------------------------ panels */
/* a material panel on the wall: its shadow; picked = lifted, a cream rim, the pointer */
static void px_panel(app *a, gfx *g, int x0, int y0, int x1, int y1, int mat, int seed, int lift, int foc)
{
    int a0 = x0 / 2, b0 = y0 / 2 - lift, c0 = x1 / 2, d0 = y1 / 2 - lift;
    ck_rrect(g, a0 + 1, b0 + 1 + lift, c0 + 1, d0 + 1 + lift, RP.wall_sh, 2);
    if (foc) {
        ck_rrect(g, a0 - 2, b0 - 2, c0 + 2, d0 + 2, RP.walnut_d, 3);
        ck_rrect(g, a0 - 1, b0 - 1, c0 + 1, d0 + 1, RP.cream, 2);
    }
    ck_material(g, a0, b0, c0, d0, mat, (uint32_t)seed, 2);
    if (mat == MAT_SHADE) {                             /* the lampshade's outline */
        ck_rect(g, a0 + 1, b0, c0 - 1, b0 + 1, RP.walnut);
        ck_rect(g, a0 + 1, d0 - 1, c0 - 1, d0, RP.walnut);
        ck_rect(g, a0, b0 + 1, a0 + 1, d0 - 1, RP.walnut);
        ck_rect(g, c0 - 1, b0 + 1, c0, d0 - 1, RP.walnut);
    }
    (void)a;
}

/* how far a picked panel stands off the wall: up two cells, settling to one */
static int px_lift(app *a, int foc)
{
    if (!foc) return 0;
    float t = (float)(a->now_ms - a->ui_t0);
    return a->ui_view == a->view && t < 120 ? 2 : 1;
}

static void px_mosaic(app *a, gfx *g, const mtile *tl, int n, int sel)
{
    for (int pass = 0; pass < 2; pass++)
        for (int i = 0; i < n; i++) {
            if ((pass == 0) == (i == sel)) continue;
            const mtile *m = &tl[i];
            int x0 = m->x0 < 6 ? 6 : (int)m->x0 & ~1, x1 = m->x1 > 314 ? 314 : (int)m->x1 & ~1;
            int y0 = ((int)m->y0 + 2) & ~1, y1 = ((int)m->y1 - 2) & ~1;
            int mat = px_mat(m->sec), foc = i == sel, lift = px_lift(a, foc), dy = -2 * lift;
            px_panel(a, g, x0, y0, x1, y1, mat, 70 + i, lift, foc);
            px16 ink = mat_ink(mat), base = mat_base(mat), subc = ink == RP.cream ? RP.felt_l : RP.sub;
            float u = foc && a->ui_view == a->view ? ez_seg((float)(a->now_ms - a->ui_t0), 60, 560) : 1;
            if (m->size == 2) {
                int s = (y1 - y0) > 70 ? 36 : 28;
                ck_sym(g, px_sym(m->sec), x1 - s / 2 - 10, y0 + s / 2 + 8 + dy, s, ink, base, mat_acc(mat), u);
                if (mat == MAT_SILVER) ck_vents(g, x0 / 2 + 4, y0 / 2 + 5 - lift, x1 / 2 - s / 2 - 8, y0 / 2 + 14 - lift);
                if (ink == RP.cream) pf_text(g, &PF_PIXEL11, x0 + 10, y1 - 10 + dy + 2, m->label, RP.walnut_d, 2);
                px_text(a, g, x0 + 10, y1 - 10 + dy, m->label, ink, x1 - x0 - 20);
                if (m->value) txt_fit(a, g, F_MONO10, x0 + 11, y1 - 34 + dy, m->value, x1 - x0 - s - 24, subc, 0);
            } else {
                ck_sym(g, px_sym(m->sec), x1 - 18, y0 + 16 + dy, 22, ink, base, mat_acc(mat), u);
                txt_fit(a, g, F_SEMI11, x0 + 8, y1 - 8 + dy, m->label, x1 - x0 - 12, ink, 0);
                if (m->value) txt_fit(a, g, F_MONO10, x0 + 8, y1 - 22 + dy, m->value, x1 - x0 - 34, subc, 0);
            }
            if (foc) ck_pointer(g, x0 - 10 < 0 ? 0 : x0 - 10, y0 + 12 + dy, a->now_ms, RP.walnut_d, RP.cream);
        }
    draw_nowbar(a, g);
}

/* ------------------------------------------------------------------ Explore, Search, the sheet */
/* covers standing on a walnut plank; the picked shelf's light strip is on */
static void px_shelf(app *a, gfx *g, int y0, int h, const char *name, const char *sub, const char *count,
                     const uint32_t *items, int n, int foc)
{
    if (foc) {
        int w = (px_ascii(name) ? pf_width(&PF_PIXEL11, name, 2) : 120) + 16;
        ck_rrect(g, 2, y0 / 2, (8 + w) / 2, y0 / 2 + 12, RP.leaf_d, 2);
        ck_material(g, 3, y0 / 2 + 1, (8 + w) / 2 - 1, y0 / 2 + 11, MAT_LEAF, 3, 2);
        ck_pointer(g, 0, y0 + 12, a->now_ms, RP.walnut_d, RP.cream);
    }
    px_text(a, g, 12, y0 + 18, name, foc ? RP.cream : P(a)->ink, 220);
    txt_right(a, g, F_MONO10, LCD_W - 12, y0 + 16, count, P(a)->sub);
    txt_fit(a, g, F_BODY10, 12, y0 + 31, sub, LCD_W - 24, P(a)->sub, 0);
    int py = (y0 + h - 12) & ~1, cs = py - (y0 + 36) - 2;
    if (cs > 44) cs = 44;
    ck_material(g, 1, py / 2, 159, py / 2 + 3, MAT_WOOD, 20 + y0, 0);
    ck_rect(g, 2, py / 2 + 3, 158, py / 2 + 4, foc ? RP.led : RP.wall_sh);
    for (int i = 0; i < n && 8 + i * (cs + 6) < LCD_W; i++) {
        int x = 8 + i * (cs + 6);
        g_fill(g, x - 1, py - cs - 1, cs + 2, cs + 1, RP.walnut_d);
        cover(a, g, items[i], ART_S, x, py - cs, cs);
    }
}

static void px_key(app *a, gfx *g, int x, int y, int w, int h, const char *label, int special, int foc, int dist)
{
    int a0 = x / 2, b0 = y / 2 + (foc ? 1 : 0), c0 = (x + w) / 2, d0 = (y + h) / 2 + (foc ? 1 : 0);
    int mat = foc ? MAT_KEY : MAT_FELT;
    if (!foc) ck_rrect(g, a0, b0 + 1, c0, d0 + 1, RP.felt_d, 1);
    ck_material(g, a0, b0, c0, d0, mat, 90 + x, 1);
    px16 ink = foc ? RP.ink : dist > 3 ? RP.sub : RP.ink;
    if (label && label[0]) {
        int lw = pf_width(&PF_PIXEL11, label, 2);
        pf_text(g, &PF_PIXEL11, 2 * a0 + (2 * (c0 - a0) - lw) / 2, 2 * d0 - 6, label, ink, 2);
    } else ck_sym(g, special == 1 ? SYM_STOP : special == 2 ? SYM_PREV : SYM_NOW, (a0 + c0), (b0 + d0), 12, ink,
                  mat_base(mat), 0, 1);
    (void)a;
}

static void px_sheet(app *a, gfx *g, const char *const *items, const int *syms, int n, int sel)
{
    float t = (float)(a->now_ms - a->sheet_t0);
    int dim = (int)(ez_out(ez_seg(t, 0, 160)) * 130);
    for (int y = 0; y < LCD_H; y++) {
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) row[x] = blend565(row[x], RP.walnut_d, dim);
    }
    int up = (int)((1 - ez_back(ez_seg(t, 0, 260), 1.6f)) * 40);
    int b0 = 22 + up / 2;
    ck_rrect(g, 6, b0, 154, b0 + 22, RP.walnut_d, 2);
    ck_material(g, 7, b0 + 1, 153, b0 + 21, MAT_PARCH, 4, 2);
    const lib_track *tr = lib_get(a->L, a->sheet_idx);
    cover(a, g, a->sheet_idx, ART_S, 22, 2 * b0 + 6, 32);
    if (tr) {
        txt_fit(a, g, F_BOLD11, 62, 2 * b0 + 19, tr->title, 232, RP.ink, 0);
        txt_fit(a, g, F_BODY10, 62, 2 * b0 + 33, tr->artist, 232, RP.sub, 0);
    }
    for (int i = 0; i < n; i++) {
        float ei = ez_back(ez_seg(t, 40.0f * i, 40.0f * i + 260), 1.9f);
        int y = (int)(98 + i * 28 + (1 - ei) * 140) & ~1;
        int foc = i == sel, mat = foc ? MAT_LEAF : MAT_SHADE;
        ck_rrect(g, 9, y / 2, 121, y / 2 + 13, foc ? RP.leaf_d : RP.walnut, 2);
        ck_material(g, 10, y / 2 + 1, 120, y / 2 + 12, mat, 60 + i, 2);
        px16 ink = mat_ink(mat);
        ck_sym(g, syms[i], 36, y + 13, 16, ink, mat_base(mat), syms[i] == SYM_QUEUE ? RP.key : 0, 1);
        px_text(a, g, 50, y + 20, items[i], ink, 180);
        if (foc) ck_pointer(g, 4, y + 13, a->now_ms, RP.walnut_d, RP.cream);
    }
}

/* a pothos trailing off the shelf */
static void px_vine_t(gfx *g, uint32_t now, int x, int y0, int y1)
{
    static const char *const LEAF[4] = { ".LL..", "LLLD.", ".LLDD", "..DD." };
    int side = 1;
    for (int k = 0, b = y0 / 2; b < y1 / 2; b++, k++) {
        float sway = sinf((float)now / 700.0f + k * .5f) * (k / 18.0f);
        int c = x / 2 + (int)lrintf(sinf(b * .45f) * 1.2f + sway);
        ck_point(g, c, b, RP.leaf_d);
        if (k % 4 == 2) {
            for (int r = 0; r < 4; r++)
                for (int q = 0; q < 5; q++) {
                    char ch = LEAF[r][q];
                    if (ch == '.') continue;
                    ck_point(g, c + (side > 0 ? q + 1 : -q - 1), b + r - 1, ch == 'L' ? RP.leaf_l : RP.leaf);
                }
            side = -side;
        }
    }
}
