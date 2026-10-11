/* Theme "Sakurai" (the default): the record-shop poster -- paper, ink, Klein blue, red for
 * what's live -- set as menu A (docs/h2/menu, docs/h2/inner; firmware/tools/mock_menu.py and
 * mock_inner.py): tilted panels sized by use, each section keeping its panel's colour and
 * symbol as a tilted tab, a cursor slab with a hard shadow that slides, buttons with
 * symbols, panels for Library and Settings. Part of app.c (included once, after the views'
 * helpers): its functions are static and see the app's internals. */

#define PK 0.2f                                   /* the lean: x shifts 0.2 px per px up */
#define PQ(v) ((int32_t)lrintf((v) * 16.0f))

/* how each section looks: its panel's colours and symbol */
typedef struct { int sym; int bg, fg, acc, outlined; } pstyle;
enum { PC_PAPER, PC_INK, PC_BLUE, PC_RED, PC_NONE };

static px16 pcol(app *a, int c)
{
    const palette *p = P(a);
    return c == PC_INK ? p->ink : c == PC_BLUE ? p->blue : c == PC_RED ? p->red : c == PC_PAPER ? p->paper : 0;
}

static pstyle poster_style(int sec)
{
    static const pstyle S[SEC_COUNT] = {
        [SEC_WHEEL] = { SYM_WHEEL, PC_INK, PC_PAPER, PC_RED, 0 },
        [SEC_NOW] = { SYM_NOW, PC_RED, PC_PAPER, PC_NONE, 0 },
        [SEC_QUEUE] = { SYM_QUEUE, PC_PAPER, PC_INK, PC_RED, 1 },
        [SEC_EXPLORE] = { SYM_EXPLORE, PC_BLUE, PC_PAPER, PC_INK, 0 },
        [SEC_SEARCH] = { SYM_SEARCH, PC_INK, PC_PAPER, PC_NONE, 0 },
        [SEC_LIBRARY] = { SYM_LIBRARY, PC_PAPER, PC_INK, PC_BLUE, 1 },
        [SEC_LIKED] = { SYM_LIKED, PC_BLUE, PC_PAPER, PC_NONE, 0 },
        [SEC_SETTINGS] = { SYM_SETTINGS, PC_PAPER, PC_INK, PC_NONE, 1 },
        [SEC_SONGS] = { SYM_SONGS, PC_INK, PC_PAPER, PC_RED, 0 },
        [SEC_ARTISTS] = { SYM_ARTISTS, PC_BLUE, PC_PAPER, PC_NONE, 0 },
        [SEC_GENRES] = { SYM_GENRES, PC_PAPER, PC_INK, PC_BLUE, 1 },
        [SEC_OSTS] = { SYM_OSTS, PC_INK, PC_PAPER, PC_RED, 0 },
        [SEC_HISTORY] = { SYM_HISTORY, PC_PAPER, PC_INK, PC_BLUE, 1 },
        [SEC_BT] = { SYM_BT, PC_INK, PC_PAPER, PC_NONE, 0 },
        [SEC_CLOCK] = { SYM_CLOCK, PC_PAPER, PC_INK, PC_NONE, 1 },
        [SEC_SLEEP] = { SYM_SLEEP, PC_BLUE, PC_PAPER, PC_NONE, 0 },
        [SEC_SOUND] = { SYM_SOUND, PC_INK, PC_PAPER, PC_NONE, 0 },
        [SEC_SCREEN] = { SYM_SCREEN, PC_PAPER, PC_INK, PC_NONE, 1 },
        [SEC_THEME] = { SYM_THEME, PC_INK, PC_PAPER, PC_NONE, 0 },
        [SEC_WHEELSET] = { SYM_WHEEL, PC_PAPER, PC_INK, PC_RED, 1 },
        [SEC_PLAYBACK] = { SYM_PLAYBACK, PC_BLUE, PC_PAPER, PC_NONE, 0 },
    };
    return sec >= 0 && sec < SEC_COUNT ? S[sec] : S[SEC_SETTINGS];
}

/* a parallelogram on the lean around y = 116, scaled by s about (cx, cy), in Q4 */
static void p_quad(float x0, float y0, float x1, float y1, float s, float cx, float cy, int32_t *xy)
{
    float p[8] = { x0 + (116 - y0) * PK, y0, x1 + (116 - y0) * PK, y0,
                   x1 + (116 - y1) * PK, y1, x0 + (116 - y1) * PK, y1 };
    for (int i = 0; i < 4; i++) {
        xy[2 * i] = PQ(cx + (p[2 * i] - cx) * s);
        xy[2 * i + 1] = PQ(cy + (p[2 * i + 1] - cy) * s);
    }
}

static void p_offset(int32_t *xy, int n, float dx, float dy)
{
    for (int i = 0; i < n; i++) { xy[2 * i] += PQ(dx); xy[2 * i + 1] += PQ(dy); }
}

/* a slab: a parallelogram leaning h*PK over its height, its own top-left at (x0, y) */
static void p_slab(gfx *g, float x0, float y, float x1, float h, px16 c, px16 shadow, float sh)
{
    float ln = h * PK;
    int32_t xy[8] = { PQ(x0 + ln), PQ(y), PQ(x1), PQ(y), PQ(x1 - ln), PQ(y + h), PQ(x0), PQ(y + h) };
    if (sh > 0) {
        int32_t s2[8];
        memcpy(s2, xy, sizeof s2);
        p_offset(s2, 4, sh, sh * .75f);
        g_convex(g, s2, 4, shadow);
    }
    g_convex(g, xy, 4, c);
}

/* the shadow colour under a popped panel: blue under ink, ink under everything else */
static px16 p_shadow(app *a, px16 bg) { return bg == P(a)->ink ? P(a)->blue : P(a)->ink; }

/* ---- a panel of menu A (or of Library's / Settings' mosaics): unskewed cell, its section's
 * colours; pop 0..1 = how far it's come forward (scale k), shadow when picked */
typedef struct { float cx, cy, s; px16 bg, fg, acc; } ppanel;

static ppanel p_panel(app *a, gfx *g, float x0, float y0, float x1, float y1, int sec, float pop, float k)
{
    pstyle st = poster_style(sec);
    ppanel r;
    r.bg = pcol(a, st.bg);
    r.fg = pcol(a, st.fg);
    r.acc = st.acc == PC_NONE ? 0 : pcol(a, st.acc);
    float cx = (x0 + x1) / 2 + (116 - (y0 + y1) / 2) * PK, cy = (y0 + y1) / 2;
    r.cx = cx;
    r.cy = cy;
    r.s = 1 + k * pop;
    int32_t q[8];
    p_quad(x0, y0, x1, y1, r.s, cx, cy, q);
    if (pop > 0.01f) {
        int32_t sq[8];
        memcpy(sq, q, sizeof sq);
        float o = 5 * (pop > 1 ? 1 : pop);
        p_offset(sq, 4, o, o);
        g_convex(g, sq, 4, p_shadow(a, r.bg));
    }
    if (st.outlined) {
        g_convex(g, q, 4, P(a)->ink);
        int32_t in[8];
        p_quad(x0 + 2, y0 + 2, x1 - 2, y1 - 2, r.s, cx, cy, in);
        g_convex(g, in, 4, r.bg);
    } else g_convex(g, q, 4, r.bg);
    return r;
}

/* a point of the panel's unscaled layout, where it lands once the panel has popped */
static float p_tx(const ppanel *r, float x) { return r->cx + (x - r->cx) * r->s; }
static float p_ty(const ppanel *r, float y) { return r->cy + (y - r->cy) * r->s; }
static float p_left(float x0, float y) { return x0 + (116 - y) * PK; }        /* the lean's left edge */
static float p_right(float x1, float y) { float v = x1 + (116 - y) * PK; return v < LCD_W ? v : LCD_W; }

/* ------------------------------------------------------------------ page, header, rows */
static void poster_page(app *a, gfx *g) { g_fill(g, 0, 0, LCD_W, LCD_H, P(a)->paper); }

/* the section's tab: its panel's colour and symbol, leaning, the rule under the page head */
static void poster_header(app *a, gfx *g, int sec, const char *title, const char *right)
{
    const palette *p = P(a);
    pstyle st = poster_style(sec);
    px16 bg = pcol(a, st.bg), fg = pcol(a, st.fg), acc = st.acc == PC_NONE ? 0 : pcol(a, st.acc);
    char t[TEXT_LINE_MAX];
    text_fit(F(a, F_POSTER18), title, 186, T_TRACK(-9), t, sizeof t);
    float x1 = 33 + text_w(F(a, F_POSTER18), t, T_TRACK(-9)) + 11;
    g_fill(g, 0, 29, LCD_W, 2, p->ink);
    int32_t q[8] = { PQ(-2), 0, PQ(x1 + 6), 0, PQ(x1), PQ(30), PQ(-8), PQ(30) };
    g_convex(g, q, 4, st.outlined ? p->ink : bg);
    if (st.outlined) {
        int32_t in[8] = { PQ(-2), PQ(2), PQ(x1 + 3.6f), PQ(2), PQ(x1 - 2), PQ(28), PQ(-8), PQ(28) };
        g_convex(g, in, 4, bg);
    }
    sym_draw(g, st.sym, 17, 15, 18, fg, bg, acc, 1);
    txt(a, g, F_POSTER18, 31, 23, t, fg, T_TRACK(-9));
    int bw = draw_battery(a, g, LCD_W - 8, 20);
    if (right) txt_right(a, g, F_MONO10, LCD_W - 8 - (bw ? bw + 10 : 0), 20, right, p->sub);
}

/* a list row's ground: the cursor is a leaning ink slab with the section's hard shadow,
 * sliding to the focus; the playing song sits on red; the rest have a hairline */
static row_ink poster_row(app *a, gfx *g, int y, int h, int state)
{
    const palette *p = P(a);
    row_ink k = { p->ink, p->sub, p->sub, p->blue, 0 };
    if (state & ROW_FOCUS) {
        float cy = cursor_y(a, y);
        px16 sec_bg = pcol(a, poster_style(view_sec(a)).bg);
        px16 slab = state & ROW_ADJ ? p->blue : p->ink;       /* being turned: Klein blue */
        p_slab(g, 3, cy, LCD_W - 3, (float)h, slab, slab == p->blue || sec_bg == p->blue ? p->ink : p->blue, 4);
        if (cy > y - 8 && cy < y + 8) {
            k.fg = p->paper; k.sub = p->strip_sub; k.note = p->paper; k.accent = p->paper; k.on = 1;
        } else g_fill(g, 0, y + h - 1, LCD_W, 1, p->rule);
        return k;
    }
    if (state & ROW_LIVE) {
        p_slab(g, 3, (float)y, LCD_W - 3, (float)h, p->red, 0, 0);
        k.fg = p->paper; k.sub = mix565(p->paper, p->red, 100); k.note = p->paper; k.accent = p->paper; k.on = 1;
        return k;
    }
    g_fill(g, 0, y + h - 1, LCD_W, 1, p->rule);
    if (state & ROW_DIM) k.fg = p->sub;
    return k;
}

static void poster_label(app *a, gfx *g, int x, int yb, const char *s, px16 c, int big, int maxw)
{
    txt_fit(a, g, big ? F_POSTER22 : F_POSTER15, x, yb, s, maxw, c, T_TRACK(big ? -6 : -3));
}

/* an action: a leaning button, its symbol, its name; picked = Klein blue on an ink shadow;
 * kind 1 = the quieter one (outlined) */
static void poster_button(app *a, gfx *g, int x, int y, int w, int h, int sym, const char *label, int foc, int kind)
{
    const palette *p = P(a);
    px16 bg = p->ink, fg = p->paper;
    float ln = h * PK;
    if (foc) { bg = p->blue; p_slab(g, (float)x, (float)y, (float)(x + w), (float)h, bg, p->ink, 4); }
    else {
        p_slab(g, (float)x, (float)y, (float)(x + w), (float)h, p->ink, 0, 0);
        if (kind) { bg = p->paper; fg = p->ink; p_slab(g, x + 2.4f, y + 2.0f, x + w - 2.0f, h - 4.0f, bg, 0, 0); }
    }
    float s = h * .56f;
    float u = foc && a->ui_view == a->view ? ez_seg((float)(a->now_ms - a->ui_t0), 40, 540) : 1;
    sym_draw(g, sym, x + ln / 2 + 8 + s / 2, y + h / 2.0f, s, fg, bg, 0, u);
    txt(a, g, F_POSTER15, (int)(x + ln / 2 + 16 + s), y + h / 2 + 6, label, fg, T_TRACK(-5));
}

/* ------------------------------------------------------------------ home: menu A */
typedef struct { float x0, y0, x1, y1, k; int size; } pcell;      /* size: 3 Wheel, 4 Now, 1 mid, 0 small */
static const pcell PA_CELL[8] = {        /* by menu item: Wheel, Now, Queue, Explore, Search, Library, Liked, Settings */
    { -40, 25, 98, 210, .035f, 3 }, { 103, 25, 350, 104, .04f, 4 }, { 103, 161, 154, 210, .09f, 0 },
    { 103, 109, 222, 156, .08f, 1 }, { 159, 161, 210, 210, .09f, 0 }, { 227, 109, 350, 156, .08f, 1 },
    { 215, 161, 266, 210, .09f, 0 }, { 271, 161, 350, 210, .09f, 0 },
};
static const uint8_t PA_ORDER[8] = { 0, 1, 3, 5, 2, 4, 6, 7 };   /* reading order */

/* a panel's contents at its pop; u runs its symbol's flourish */
static void pa_contents(app *a, gfx *g, int item, const ppanel *r, float u)
{
    const pcell *c = &PA_CELL[item];
    const palette *p = P(a);
    pstyle st = poster_style(item);
    if (c->size == 3) {                                   /* the Wheel: the symbol, huge */
        sym_draw(g, SYM_WHEEL, p_tx(r, 46), p_ty(r, 102), 116 * r->s, r->fg, r->bg, p->red, u);
        char n[24], s[40];
        commas(n, sizeof n, brain_n());
        snprintf(s, sizeof s, "%s songs", n);
        txt(a, g, F_MONO10, (int)p_tx(r, 10), (int)p_ty(r, 181), s, p->strip_sub, 0);
        txt(a, g, F_POSTER22, (int)p_tx(r, 9), (int)p_ty(r, 202), "Wheel", r->fg, T_TRACK(-11));
    } else if (c->size == 4) {                            /* Now playing: the cover, the song */
        int32_t q[8];
        p_quad(210, c->y0, c->x1, c->y1, r->s, r->cx, r->cy, q);
        if (a->cur_valid) {
            const px16 *t = tex_get(a, a->cur, ART_M);
            if (t) g_blit_scaled_clip(g, t, art_px[ART_M], art_px[ART_M], (int)p_tx(r, 228), (int)p_ty(r, 19),
                                      (int)(92 * r->s), (int)(92 * r->s), q, 4);
        }
        txt(a, g, F_POSTER15, (int)p_tx(r, p_left(c->x0, 43) + 6), (int)p_ty(r, 43), "Now playing", r->fg, T_TRACK(-7));
        const lib_track *t = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
        if (t) {
            char lines[2][TEXT_LINE_MAX];
            int nl = text_wrap(F(a, F_BOLD11), t->title, 92, 2, 0, lines);
            for (int i = 0; i < nl; i++)
                txt(a, g, F_BOLD11, (int)p_tx(r, p_left(c->x0, 60 + 13 * i) + 6), (int)p_ty(r, 60 + 13 * i), lines[i], r->fg, 0);
            txt_fit(a, g, F_BODY10, (int)p_tx(r, p_left(c->x0, 95) + 6), (int)p_ty(r, 95), t->artist, 90,
                    mix565(r->bg, p->paper, 184), 0);
        } else txt(a, g, F_BODY10, (int)p_tx(r, p_left(c->x0, 64) + 6), (int)p_ty(r, 64), "Nothing yet.",
                   mix565(r->bg, p->paper, 200), 0);
    } else if (c->size == 1) {                            /* Explore, Library */
        txt(a, g, F_POSTER15, (int)p_tx(r, p_left(c->x0, 148) + 6), (int)p_ty(r, 148), menu_items[item], r->fg, T_TRACK(-6));
        float rx = p_right(c->x1, 125) - 22;
        sym_draw(g, st.sym, p_tx(r, rx), p_ty(r, 128), 28 * r->s, r->fg, r->bg, r->acc, u);
    } else {                                              /* the small four */
        float ym = c->y0 + 19, mid = (p_left(c->x0, ym) + p_right(c->x1, ym)) / 2;
        sym_draw(g, st.sym, p_tx(r, mid), p_ty(r, ym), 21 * r->s, r->fg, r->bg, r->acc, u);
        float yl = c->y0 + 41, ml = (p_left(c->x0, yl) + p_right(c->x1, yl)) / 2;
        int w = pf_width(&PF_POSTER11, menu_items[item], 1);
        pf_text(g, &PF_POSTER11, (int)(p_tx(r, ml) - w / 2.0f), (int)p_ty(r, yl), menu_items[item], r->fg, 1);
    }
}

static void poster_home(app *a, gfx *g)
{
    const palette *p = P(a);
    int w = txt(a, g, F_POSTER15, 8, 17, "Coda", p->ink, T_TRACK(-7));
    g_fill(g, 8 + w + 2, 12, 5, 5, p->red);
    draw_battery(a, g, LCD_W - 8, 16);
    int sel = fx_clamp(a->ls[V_MENU].sel, 0, 7), cur = PA_ORDER[sel];
    float t = a->ui_view == V_MENU ? (float)(a->now_ms - a->ui_t0) : 1e6f;
    int prev = a->ui_view == V_MENU && a->ui_prev >= 0 && a->ui_prev < 8 && t < 150 ? PA_ORDER[a->ui_prev] : -1;
    if (prev == cur) prev = -1;
    for (int pass = 0; pass < 3; pass++)
        for (int i = 0; i < 8; i++) {
            if ((pass == 0 && (i == cur || i == prev)) || (pass == 1 && i != prev) || (pass == 2 && i != cur)) continue;
            const pcell *c = &PA_CELL[i];
            float pop = i == cur ? ez_back(ez_seg(t, 0, 220), 2.2f) : i == prev ? 1 - ez_out(ez_seg(t, 0, 150)) : 0;
            ppanel r = p_panel(a, g, c->x0, c->y0, c->x1, c->y1, i, pop, c->k);
            pa_contents(a, g, i, &r, i == cur ? ez_seg(t, 60, 560) : 1);
        }
    draw_nowbar(a, g);
}

/* ------------------------------------------------------------------ mosaics: Library, Settings */
static void poster_mosaic(app *a, gfx *g, const mtile *tl, int n, int sel)
{
    const palette *p = P(a);
    float t = a->ui_view == a->view ? (float)(a->now_ms - a->ui_t0) : 1e6f;
    int prev = a->ui_view == a->view && t < 150 ? a->ui_prev : -1;
    if (prev == sel) prev = -1;
    for (int pass = 0; pass < 3; pass++)
        for (int i = 0; i < n; i++) {
            if ((pass == 0 && (i == sel || i == prev)) || (pass == 1 && i != prev) || (pass == 2 && i != sel)) continue;
            const mtile *m = &tl[i];
            float k = m->size == 2 ? .035f : .06f;
            float pop = i == sel ? ez_back(ez_seg(t, 0, 220), 2.2f) : i == prev ? 1 - ez_out(ez_seg(t, 0, 150)) : 0;
            ppanel r = p_panel(a, g, m->x0, m->y0, m->x1, m->y1, m->sec, pop, k);
            pstyle st = poster_style(m->sec);
            float u = i == sel ? ez_seg(t, 60, 560) : 1;
            px16 subc = mix565(r.fg, r.bg, 100);
            if (m->size == 2) {
                float l = p_left(m->x0, m->y1 - 12) + 6;
                if (l < 10) l = 10;
                sym_draw(g, st.sym, p_tx(&r, (l + p_right(m->x1, m->y0 + 40)) / 2 + 4), p_ty(&r, m->y0 + (m->y1 - m->y0) * .42f),
                         (m->y1 - m->y0) * .5f * r.s, r.fg, r.bg, r.acc ? r.acc : p->red, u);
                if (m->value) txt(a, g, F_MONO10, (int)p_tx(&r, l + 1), (int)p_ty(&r, m->y1 - 34), m->value, subc, 0);
                txt(a, g, F_POSTER22, (int)p_tx(&r, l), (int)p_ty(&r, m->y1 - 11), m->label, r.fg, T_TRACK(-11));
            } else {
                float yb = m->y1 - 8, l = p_left(m->x0, yb) + 6 + (st.outlined ? 2 : 0), rx = p_right(m->x1, m->y0 + 14);
                if (l < 9) l = 9;
                int f = text_w(F(a, F_POSTER15), m->label, T_TRACK(-6)) < rx - l - 6 ? F_POSTER15 : -1;
                if (f >= 0) txt(a, g, f, (int)p_tx(&r, l), (int)p_ty(&r, yb), m->label, r.fg, T_TRACK(-6));
                else pf_text(g, &PF_POSTER11, (int)p_tx(&r, l), (int)p_ty(&r, yb), m->label, r.fg, 1);
                if (m->value) txt_fit(a, g, F_MONO10, (int)p_tx(&r, l), (int)p_ty(&r, yb - 16), m->value,
                                      (int)(rx - l - 26), subc, 0);
                float s = (m->y1 - m->y0) > 50 ? 30 : 20;
                sym_draw(g, st.sym, p_tx(&r, rx - s / 2 - 6), p_ty(&r, m->y0 + s / 2 + 6), s * r.s, r.fg, r.bg, r.acc, u);
            }
        }
    draw_nowbar(a, g);
}

/* ------------------------------------------------------------------ Explore: shelves */
static void poster_shelf(app *a, gfx *g, int y0, int h, const char *name, const char *sub, const char *count,
                         const uint32_t *items, int n, int foc)
{
    const palette *p = P(a);
    int nw = text_w(F(a, F_POSTER18), name, T_TRACK(-8));
    if (foc) p_slab(g, 3, (float)(y0 + 2), (float)(22 + nw + 8), 24, p->blue, p->ink, 3);
    txt(a, g, F_POSTER18, 12, y0 + 20, name, foc ? p->paper : p->ink, T_TRACK(-8));
    txt_right(a, g, F_MONO10, LCD_W - 12, y0 + 18, count, p->sub);
    txt_fit(a, g, F_BODY10, 12, y0 + 38, sub, LCD_W - 24, p->sub, 0);
    /* the covers, butted edge to edge, the row cut on the lean */
    float ry = y0 + 44, rh = h - 48, ln = rh * PK;
    int32_t q[8] = { PQ(ln), PQ(ry), PQ(LCD_W), PQ(ry), PQ(LCD_W - ln), PQ(ry + rh), 0, PQ(ry + rh) };
    if (foc) {
        int32_t s2[8];
        memcpy(s2, q, sizeof s2);
        p_offset(s2, 4, 4, 3);
        g_convex(g, s2, 4, p->ink);
    }
    int px = (int)rh;
    for (int i = 0; i * px - 6 < LCD_W && i < n; i++) {
        const px16 *t = tex_get(a, items[i], ART_S);
        if (t) g_blit_scaled_clip(g, t, art_px[ART_S], art_px[ART_S], i * px - 6, (int)ry, px, px, q, 4);
    }
}

/* ------------------------------------------------------------------ Search: the letter keys */
static void poster_key(app *a, gfx *g, int x, int y, int w, int h, const char *label, int special, int foc, int dist)
{
    const palette *p = P(a);
    px16 face = foc ? p->blue : p->paper, ink = foc ? p->paper : mix565(p->ink, p->paper, dist * 40);
    if (foc) p_slab(g, x + 2.0f, y + 2.0f, x + w + 2.0f, (float)h, face, 0, 0);
    else {
        p_slab(g, x + 2.0f, y + 2.0f, x + w + 2.0f, (float)h, mix565(p->ink, p->paper, dist * 40), 0, 0);
        p_slab(g, (float)x, (float)y, (float)(x + w), (float)h, mix565(p->ink, p->paper, dist * 40), 0, 0);
        p_slab(g, x + 1.5f, y + 1.5f, x + w - 1.5f, h - 3.0f, face, 0, 0);
    }
    int o = foc ? 2 : 0;
    if (label && label[0]) txt_center(a, g, F_POSTER18, x + w / 2 + o, y + h / 2 + 7 + o, label, w, ink, 0);
    else if (special == 1) g_fill(g, x + w / 2 - 6 + o, y + h / 2 + 3 + o, 12, 3, ink);           /* space */
    else if (special == 2) sym_draw(g, SYM_PREV, x + w / 2.0f + o, y + h / 2.0f + o, h * .45f, ink, face, 0, 1);
    else sym_draw(g, SYM_NOW, x + w / 2.0f + o, y + h / 2.0f + o, h * .45f, foc ? ink : p->blue, face, 0, 1);
}

/* ------------------------------------------------------------------ Now playing */
/* the cover cut on the lean, a red "playing" tag, the title stacked in poster caps; under it
 * a chunky slanted progress slab, the time big, what's next on its own card */
static int poster_now(app *a, gfx *g)
{
    const palette *p = P(a);
    if (!a->cur_valid) return 0;                          /* the shared "nothing yet" */
    const lib_track *t = lib_get(a->L, a->cur);
    const int A = 168, x0 = A + 8, x1 = LCD_W - 8;
    const px16 *tex = tex_get(a, a->cur, ART_L);
    int32_t q[8] = { 0, 0, PQ(172), 0, PQ(158), PQ(A), 0, PQ(A) };
    if (tex) g_blit_scaled_clip(g, tex, art_px[ART_L], art_px[ART_L], 0, 0, A, A, q, 4);
    else g_convex(g, q, 4, p->wash);
    /* the tag: red while playing, outlined when paused */
    int pw = pf_width(&PF_POSTER11, a->ps.playing ? "playing" : "paused", 1) + 30;
    if (a->ps.playing) p_slab(g, (float)x0, 9, (float)(x0 + pw), 17, p->red, 0, 0);
    else { p_slab(g, (float)x0, 9, (float)(x0 + pw), 17, p->ink, 0, 0); p_slab(g, x0 + 1.5f, 10.5f, x0 + pw - 1.5f, 14, p->paper, 0, 0); }
    px16 tg = a->ps.playing ? p->paper : p->ink;
    sym_draw(g, a->ps.playing ? SYM_NOW : SYM_PAUSE, x0 + 13.0f, 17.5f, 10, tg, a->ps.playing ? p->red : p->paper, 0, 1);
    pf_text(g, &PF_POSTER11, x0 + 22, 22, a->ps.playing ? "playing" : "paused", tg, 1);
    draw_battery(a, g, x1, 21);
    int y = 48;
    if (t) {
        char up[TEXT_LINE_MAX * 2], lines[4][TEXT_LINE_MAX];
        utf8_upper(t->title, up, sizeof up);
        int nl = text_wrap(F(a, F_POSTER18), up, x1 - x0 - 4, 4, T_TRACK(-4), lines);
        for (int i = 0; i < nl; i++) txt(a, g, F_POSTER18, x0 + 4 - 2 * i, y + i * 18, lines[i], p->ink, T_TRACK(-4));
        y += (nl - 1) * 18 + 17;
        txt_fit(a, g, F_SEMI12, x0 + 4, y, t->artist, x1 - x0 - 4, p->blue, 0);
    }
    if (a->why[0]) {
        char lines[3][TEXT_LINE_MAX];
        int nl = text_wrap(F(a, F_BODY10), a->why, x1 - x0 - 4, 3, 0, lines);
        for (int i = 0; i < nl; i++) txt(a, g, F_BODY10, x0 + 4, y + 20 + i * 12, lines[i], p->sub, 0);
        y += 20 + (nl - 1) * 12;
    }
    if (brain_is_liked(a->cur)) {
        sym_draw(g, SYM_LIKED, x0 + 9.0f, y + 12.0f, 11, p->red, p->paper, 0, 1);
        txt(a, g, F_BODY10, x0 + 18, y + 16, "liked", p->ink, 0);
    }
    /* the strip */
    const int y0 = A;
    g_fill(g, 0, y0, LCD_W, LCD_H - y0, p->strip_bg);
    int seeking = a->seek_ms && a->now_ms - a->seek_ms < 1500;
    uint32_t shown = seeking ? a->seek_to : a->ps.elapsed_ms;
    if (a->ps.length_ms) {
        float px = (float)((uint64_t)LCD_W * shown / a->ps.length_ms);
        int32_t bar[8] = { PQ(-10), PQ(y0), PQ(px + 4), PQ(y0), PQ(px - 4), PQ(y0 + 8), PQ(-10), PQ(y0 + 8) };
        g_convex(g, bar, 4, p->red);
    }
    char e[16], tot[24];
    mmss(e, sizeof e, shown / 1000);
    mmss(tot + 2, sizeof tot - 2, (a->ps.length_ms ? a->ps.length_ms / 1000 : (t ? t->dur : 0)));
    tot[0] = '/'; tot[1] = ' ';
    int ew = txt(a, g, F_POSTER22, 10, y0 + 35, e, seeking ? p->red : p->strip_fg, T_TRACK(-8));
    txt(a, g, F_MONO10, 10 + ew + 8, y0 + 34, tot, p->strip_sub, 0);
    if (a->notice[0]) txt_fit(a, g, F_BOLD11, 120, y0 + 33, a->notice, LCD_W - 128, p->strip_fg, 0);
    uint32_t nx = a->qpos + 1 < a->qn ? a->q[a->qpos + 1] : LIB_NONE;
    if (nx != LIB_NONE) {
        const lib_track *n = lib_get(a->L, nx);
        p_slab(g, 6, (float)(y0 + 44), LCD_W - 6, 24, mix565(p->strip_bg, p->strip_fg, 30), 0, 0);
        cover(a, g, nx, ART_S, 14, y0 + 46, 20);
        txt(a, g, F_MONO10, 40, y0 + 55, a->qsrc[a->qpos + 1] == QS_AUTO ? "next, autoplay" : "next", p->strip_sub, 0);
        if (n) txt_fit(a, g, F_BOLD11, 40, y0 + 66, n->title, 250, p->strip_fg, 0);
    }
    return 1;
}

/* ------------------------------------------------------------------ the sheet */
static void poster_sheet(app *a, gfx *g, const char *const *items, const int *syms, int n, int sel)
{
    const palette *p = P(a);
    float t = (float)(a->now_ms - a->sheet_t0), dim = ez_out(ez_seg(t, 0, 160)) * 140;
    for (int y = 0; y < LCD_H; y++) {                    /* the page dims under it */
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) row[x] = blend565(row[x], p->ink, (int)dim);
    }
    float e = ez_back(ez_seg(t, 0, 260), 1.6f);
    float ty = 52 - (1 - e) * 70;
    p_slab(g, 6, ty, 300, 38, p->ink, 0, 0);
    const lib_track *tr = lib_get(a->L, a->sheet_idx);
    cover(a, g, a->sheet_idx, ART_S, 18, (int)ty + 4, 30);
    if (tr) {
        txt_fit(a, g, F_BOLD11, 56, (int)ty + 16, tr->title, 236, p->strip_fg, 0);
        txt_fit(a, g, F_BODY10, 56, (int)ty + 30, tr->artist, 236, p->strip_sub, 0);
    }
    for (int i = 0; i < n; i++) {
        float ei = ez_back(ez_seg(t, 40.0f * i, 40.0f * i + 260), 1.9f);
        float y = 96 + i * 29 + (1 - ei) * 160;
        int foc = i == sel;
        px16 bg = foc ? p->blue : p->paper, fg = foc ? p->paper : p->ink;
        p_slab(g, 10, y, 230, 25, bg, foc ? p->ink : 0, foc ? 4 : 0);
        sym_draw(g, syms[i], 32, y + 12.5f, 15, fg, bg, syms[i] == SYM_QUEUE ? p->red : 0, 1);
        txt(a, g, F_POSTER15, 48, (int)y + 18, items[i], fg, T_TRACK(-6));
    }
}
