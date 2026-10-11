#include "app.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "brain.h"
#include "fx.h"
#include "lib.h"
#include "theme.h"
#include "wheel.h"
#include "../plat/plat.h"

#define ROW_H 30
#define LIST_Y 31
#define BAR_Y 212
#define POOL_N 24
#define SESSION_MAX 512
#define TRACKS_MAX 4096

typedef struct { int n, sel; float top; } list_state;

typedef struct { uint32_t idx; px16 *px; uint32_t used; int ok; } tex_slot;
#define NT_S 48
#define NT_M 16
#define NT_L 3

enum { TK_ARTIST, TK_SONGS, TK_LIKED, TK_HISTORY, TK_QUEUE, TK_RESULTS };

struct app {
    theme th;
    lib *L;
    int view, stack[16], depth, section, night_mode;
    /* wheel */
    uint32_t pool[POOL_N];
    int n_pool, target, layout_b;
    float s;
    /* textures */
    tex_slot ts[NT_S], tm[NT_M], tl[NT_L];
    uint32_t tex_clock;
    /* player + autoplay */
    plat_play ps;
    uint32_t cur, last_elapsed, last_len, next_pick;
    int cur_valid;
    uint32_t session[SESSION_MAX];
    int n_session;
    char why[160], why_next[160];
    /* lists */
    list_state ls[V_COUNT];
    uint32_t *tracks;
    int n_tracks, tracks_kind;
    char tracks_title[112];
    uint32_t now_ms, last_ms;
    int tick_sound, viz_on, keep_playing;
    /* change detection: the last frame's inputs; a full redraw only when they differ */
    uint32_t drawn_sig, hub_ms;
    int force_full;
};

static const char *const menu_items[] = { "Wheel", "Now playing", "Explore", "Search", "Library", "Liked", "Settings" };
#define N_MENU 7
static const char *const lib_items[] = { "Songs", "Artists", "Genres", "OST", "History" };
#define N_LIB 5
#define N_SETTINGS 5

/* ------------------------------------------------------------------ helpers */
static const palette *P(app *a) { return a->th.p; }
static const font *F(app *a, int i) { return &a->th.f[i]; }

static int txt(app *a, gfx *g, int f, int x, int y, const char *s, px16 c, int track)
{
    return text_draw(g, F(a, f), x * 16, y, s, c, track) / 16;
}

static int txt_fit(app *a, gfx *g, int f, int x, int y, const char *s, int max_w, px16 c, int track)
{
    char buf[TEXT_LINE_MAX];
    text_fit(F(a, f), s, max_w, track, buf, sizeof buf);
    return txt(a, g, f, x, y, buf, c, track);
}

static void txt_right(app *a, gfx *g, int f, int x_right, int y, const char *s, px16 c)
{
    txt(a, g, f, x_right - text_w(F(a, f), s, 0), y, s, c, 0);
}

static void txt_center(app *a, gfx *g, int f, int cx, int y, const char *s, int max_w, px16 c, int track)
{
    char buf[TEXT_LINE_MAX];
    text_fit(F(a, f), s, max_w, track, buf, sizeof buf);
    txt(a, g, f, cx - text_w(F(a, f), buf, track) / 2, y, buf, c, track);
}

static void mmss(char *out, size_t n, uint32_t sec)
{
    snprintf(out, n, "%u:%02u", (unsigned)(sec / 60), (unsigned)(sec % 60));
}

static void commas(char *out, size_t n, uint32_t v)
{
    char tmp[16];
    snprintf(tmp, sizeof tmp, "%u", (unsigned)v);
    size_t len = strlen(tmp), o = 0;
    for (size_t i = 0; i < len && o + 2 < n; i++) {
        if (i && (len - i) % 3 == 0) out[o++] = ',';
        out[o++] = tmp[i];
    }
    out[o] = 0;
}

static const px16 *tex_get(app *a, uint32_t idx, int size)
{
    tex_slot *slots = size == ART_S ? a->ts : size == ART_M ? a->tm : a->tl;
    int n = size == ART_S ? NT_S : size == ART_M ? NT_M : NT_L;
    int victim = 0;
    a->tex_clock++;
    for (int i = 0; i < n; i++) {
        if (slots[i].px && slots[i].idx == idx) {
            slots[i].used = a->tex_clock;
            return slots[i].ok ? slots[i].px : NULL;
        }
        if (slots[i].used < slots[victim].used) victim = i;
    }
    tex_slot *t = &slots[victim];
    if (!t->px) t->px = plat_alloc((size_t)art_px[size] * art_px[size] * 2);
    t->idx = idx;
    t->used = a->tex_clock;
    t->ok = lib_art(a->L, idx, size, t->px) == 0;
    return t->ok ? t->px : NULL;
}

static void cover(app *a, gfx *g, uint32_t idx, int size, int x, int y, int px)
{
    const px16 *t = idx == LIB_NONE ? NULL : tex_get(a, idx, size);
    if (t) g_blit_scaled(g, t, art_px[size], art_px[size], x, y, px, px);
    else g_fill(g, x, y, px, px, P(a)->wash);
}

static int mod(int v, int n) { return ((v % n) + n) % n; }

/* ------------------------------------------------------------------ navigation */
static void open_view(app *a, int v);
static void coda_settings_save(app *a);

static void push(app *a, int v)
{
    if (a->depth < 15) a->stack[a->depth++] = a->view;
    open_view(a, v);
}

static void pop(app *a)
{
    if (a->depth > 0) a->view = a->stack[--a->depth];
    else a->view = V_MENU;
}

static void wheel_refresh(app *a)
{
    a->n_pool = brain_wheel(a->pool, POOL_N, (double)plat_now());
    a->s = 0;
    a->target = 0;
    if (a->cur_valid)
        for (int i = 0; i < a->n_pool; i++)
            if (a->pool[i] == a->cur) { a->target = i; a->s = (float)i; break; }
}

static void set_tracks(app *a, int kind, const char *title)
{
    a->tracks_kind = kind;
    snprintf(a->tracks_title, sizeof a->tracks_title, "%s", title);
    a->ls[V_TRACKS].sel = 0;
    a->ls[V_TRACKS].top = 0;
}

static void open_view(app *a, int v)
{
    a->view = v;
    if (v == V_WHEEL || v == V_NOW || v == V_EXPLORE || v == V_SEARCH) a->section = v;
    if (v == V_WHEEL) wheel_refresh(a);
    if (v == V_ARTISTS) a->ls[V_ARTISTS].n = (int)lib_n_artists(a->L);
    if (v == V_TRACKS) {
        switch (a->tracks_kind) {
        case TK_LIKED: a->n_tracks = brain_liked(a->tracks, TRACKS_MAX); break;
        case TK_HISTORY: a->n_tracks = brain_history(a->tracks, TRACKS_MAX); break;
        case TK_SONGS: a->n_tracks = (int)lib_n(a->L); break;     /* virtual: idx == row */
        default: break;
        }
        a->ls[V_TRACKS].n = a->n_tracks;
    }
}

void app_open(app *a, int view)
{
    if (view == V_TRACKS) set_tracks(a, TK_LIKED, "Liked");
    push(a, view);
}

void app_set_wheel_layout(app *a, int b) { a->layout_b = b; }
void app_set_night(app *a, int night) { a->night_mode = night; }

static uint32_t track_at(app *a, int row)
{
    return a->tracks_kind == TK_SONGS ? (uint32_t)row : a->tracks[row];
}

/* ------------------------------------------------------------------ playback */
static void play_from(app *a, const uint32_t *idx, int n)
{
    if (n <= 0) return;
    plat_play_tracks(idx, n, 0);
    a->why[0] = 0;
}

static void play_one(app *a, uint32_t idx) { play_from(a, &idx, 1); }

static void autoplay_tick(app *a)
{
    plat_player(&a->ps);
    double now = (double)plat_now();
    if (a->ps.active && (!a->cur_valid || a->ps.idx != a->cur)) {
        if (a->cur_valid) {
            float done = a->last_len ? (float)a->last_elapsed / a->last_len : -1.0f;
            brain_log(a->cur, done >= 0.8f ? 1 : 2, a->last_elapsed / 1000.0f, now);
        }
        int auto_pick = a->cur_valid && a->ps.idx == a->next_pick;
        memcpy(a->why, auto_pick ? a->why_next : "", sizeof a->why);
        plat_log("track %u (prev %u, queued %u, auto %d) why='%s'", (unsigned)a->ps.idx,
                 a->cur_valid ? (unsigned)a->cur : 0u, (unsigned)a->next_pick, auto_pick, a->why);
        a->cur = a->ps.idx;
        a->cur_valid = 1;
        brain_log(a->cur, 0, 0, now);
        if (a->n_session == SESSION_MAX) {
            memmove(a->session, a->session + 1, (SESSION_MAX - 1) * sizeof a->session[0]);
            a->n_session--;
        }
        a->session[a->n_session++] = a->cur;
        a->next_pick = brain_next(a->cur, a->session, a->n_session - 1, now,
                                  a->why_next, sizeof a->why_next);
        if (a->next_pick != LIB_NONE) plat_queue_next(a->next_pick);
    }
    if (a->ps.active) { a->last_elapsed = a->ps.elapsed_ms; a->last_len = a->ps.length_ms; }
}

/* ------------------------------------------------------------------ shared chrome */
static void draw_status(app *a, gfx *g, int x_right, int y)
{
    char s[32];
    int h, m, bat = plat_battery();
    plat_clock(&h, &m);
    if (bat >= 0) snprintf(s, sizeof s, "%02d:%02d  %d%%", h, m, bat);
    else snprintf(s, sizeof s, "%02d:%02d", h, m);
    txt_right(a, g, F_MONO10, x_right, y, s, P(a)->sub);
}

static void draw_header(app *a, gfx *g, const char *title, const char *right)
{
    txt_fit(a, g, F_POSTER22, 8, 24, title, right ? 230 : 300, P(a)->ink, T_TRACK(-5));
    if (right) txt_right(a, g, F_MONO10, LCD_W - 8, 22, right, P(a)->sub);
    g_fill(g, 0, 30, LCD_W, 1, P(a)->ink);
}

static void draw_nowbar(app *a, gfx *g)
{
    const palette *p = P(a);
    const int y0 = BAR_Y, h = LCD_H - BAR_Y;
    g_fill(g, 0, y0, LCD_W, h, p->strip_bg);
    if (!a->cur_valid) {
        txt(a, g, F_BODY10, 8, y0 + 18, "Nothing playing. Spin the wheel.", p->strip_sub, 0);
        return;
    }
    const lib_track *t = lib_get(a->L, a->cur);
    cover(a, g, a->cur, ART_S, 0, y0, h);
    if (a->ps.length_ms) g_fill(g, 0, y0, (int)((uint64_t)LCD_W * a->ps.elapsed_ms / a->ps.length_ms), 2, p->red);
    int tx = h + 6;
    if (a->ps.playing) { g_fill(g, tx, y0 + 9, 5, 5, p->red); tx += 9; }
    if (t) {
        txt_fit(a, g, F_BOLD11, tx, y0 + 15, t->title, 236 - tx, p->strip_fg, 0);
        txt_fit(a, g, F_BODY10, h + 6, y0 + 25, t->artist, 230 - h, p->strip_sub, 0);
    }
    char e[16];
    mmss(e, sizeof e, a->ps.elapsed_ms / 1000);
    txt_right(a, g, F_MONO10, LCD_W - 6, y0 + 15, e, p->strip_fg);
}

/* scrolled list frame: keeps sel visible, animates top */
static void list_follow(list_state *l, int visible)
{
    if (l->n <= 0) { l->sel = 0; l->top = 0; return; }
    l->sel = fx_clamp(l->sel, 0, l->n - 1);
    float want = l->top;
    if (l->sel < (int)ceilf(l->top)) want = (float)l->sel;
    if (l->sel > (int)floorf(l->top) + visible - 1) want = (float)(l->sel - visible + 1);
    l->top = want;
}

static void dotted_leader(gfx *g, int x0, int x1, int y, px16 c)
{
    for (int x = x0; x < x1; x += 3) g_fill_a(g, x, y, 1, 1, c, 170);
}

/* ------------------------------------------------------------------ views */
static void draw_menu(app *a, gfx *g)
{
    const palette *p = P(a);
    int w = txt(a, g, F_POSTER22, 8, 23, "Coda", p->ink, T_TRACK(-5));
    g_fill(g, 8 + w + 2, 17, 6, 6, p->red);
    char n[24], s[40];
    commas(n, sizeof n, lib_n(a->L));
    snprintf(s, sizeof s, "%s tracks", n);
    txt_right(a, g, F_MONO10, LCD_W - 8, 22, s, p->sub);
    g_fill(g, 0, 30, LCD_W, 1, p->ink);
    list_state *l = &a->ls[V_MENU];
    l->n = N_MENU;
    list_follow(l, 6);
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    for (int i = 0; i < N_MENU; i++) {
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        int foc = i == l->sel;
        if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
        int ww = txt(a, g, F_POSTER22, 8, y + 24, menu_items[i], foc ? p->paper : p->ink, T_TRACK(-6));
        static const int sect[N_MENU] = { V_WHEEL, V_NOW, V_EXPLORE, V_SEARCH, -1, -1, -1 };
        if (!foc && sect[i] == a->section) g_fill(g, 8, y + 27, ww, 2, p->blue);
    }
    g_noclip(g);
    draw_nowbar(a, g);
}

static void wheel_frame_fill(app *a, wheel_frame *f, int *focused)
{
    memset(f, 0, sizeof *f);
    int b0 = (int)lrintf(a->s);
    f->frac = a->s - b0;
    f->settled = fabsf(a->s - a->target) < 0.02f;
    int n = a->n_pool;
    int lo = n >= 11 ? 5 : (n - 1) / 2, hi = n >= 11 ? 5 : n - 1 - lo;
    for (int dd = -5; dd <= 5; dd++) {
        if (dd < -lo || dd > hi || n == 0) continue;
        f->show[dd + 5] = 1;
        f->tex[dd + 5] = tex_get(a, a->pool[mod(b0 + dd, n)], ART_M);
    }
    *focused = n ? mod(b0, n) : -1;
    if (*focused >= 0) f->label = tex_get(a, a->pool[*focused], ART_M);
    f->playing = *focused >= 0 && a->cur_valid && a->pool[*focused] == a->cur && a->ps.playing;
    uint8_t bands[12];
    if (!plat_spectrum(bands)) memset(bands, 40, sizeof bands);
    for (int i = 0; i < 12; i++) { f->bars[i] = bands[i]; f->bars[23 - i] = bands[i]; }
}

static void draw_wheel(app *a, gfx *g)
{
    const palette *p = P(a);
    wheel_frame f;
    int focused;
    wheel_frame_fill(a, &f, &focused);
    char pos[16];
    snprintf(pos, sizeof pos, "%d/%d", focused + 1, a->n_pool);
    if (!a->layout_b) {
        wheel_draw(g, p, &WHEEL_A, &f);
        const int x0 = 214, x1 = 316, cy = 120, row = 40;
        int b0 = (int)lrintf(a->s);
        for (int dd = -2; dd <= 2 && a->n_pool; dd++) {
            if (dd == 0) continue;
            const lib_track *t = lib_get(a->L, a->pool[mod(b0 + dd, a->n_pool)]);
            if (!t) continue;
            float dist = fabsf(dd - f.frac);
            int op = (int)(fmaxf(0.0f, 1.0f - dist / 2.8f) * 256);
            px16 c = mix565(p->paper, p->sub, op);
            int y = cy + (int)lrintf((dd - f.frac) * row);
            txt_fit(a, g, F_BOLD11, x0 + 4, y + 1, t->title, x1 - x0 - 4, c, 0);
            txt_fit(a, g, F_BODY10, x0 + 4, y + 13, t->artist, x1 - x0 - 4, c, 0);
        }
        if (focused >= 0) {
            const lib_track *t = lib_get(a->L, a->pool[focused]);
            if (t) {
                char up[TEXT_LINE_MAX * 2], lines[2][TEXT_LINE_MAX];
                utf8_upper(t->title, up, sizeof up);
                int nl = text_wrap(F(a, F_POSTER15), up, x1 - x0 - 10, 2, T_TRACK(-4), lines);
                int y = cy - (nl - 1) * 7 + 5 - (int)lrintf(f.frac * row);
                for (int i = 0; i < nl; i++)
                    txt(a, g, F_POSTER15, x0 + 10, y + i * 14, lines[i], p->ink, T_TRACK(-4));
                txt_fit(a, g, F_SEMI11, x0 + 10, y + (nl - 1) * 14 + 13, t->artist, x1 - x0 - 10, p->blue, 0);
            }
        }
        draw_status(a, g, 316, 12);
        if (f.playing) txt(a, g, F_MONO10, 216, 233, "\xE2\x97\x8F playing", p->red, 0);
        txt_right(a, g, F_MONO10, 316, 233, pos, p->sub);
    } else {
        wheel_draw(g, p, &WHEEL_B, &f);
        if (focused >= 0) {
            const lib_track *t = lib_get(a->L, a->pool[focused]);
            if (t) {
                char up[TEXT_LINE_MAX * 2];
                utf8_upper(t->title, up, sizeof up);
                txt_center(a, g, F_POSTER18, 160, 24, up, 236, p->ink, T_TRACK(-5));
                txt_center(a, g, F_SEMI12, 160, 41, t->artist, 236, p->blue, 0);
            }
        }
        draw_status(a, g, 316, 12);
        txt(a, g, F_MONO10, 4, 12, pos, p->sub, 0);
        if (f.playing) txt(a, g, F_MONO10, 4, 233, "\xE2\x97\x8F playing", p->red, 0);
    }
}

static void draw_now(app *a, gfx *g)
{
    const palette *p = P(a);
    const int A = 168, x0 = A + 10, x1 = LCD_W - 8;
    if (!a->cur_valid) {
        draw_header(a, g, "Now playing", NULL);
        txt(a, g, F_BODY10, 8, 60, "Nothing playing yet.", p->sub, 0);
        txt(a, g, F_BODY10, 8, 74, "Spin the wheel and press play.", p->sub, 0);
        return;
    }
    const lib_track *t = lib_get(a->L, a->cur);
    cover(a, g, a->cur, ART_L, 0, 0, A);
    if (a->ps.playing) g_fill(g, x1 - 7, 10, 7, 7, p->red);
    int y = 40;
    if (t) {
        char up[TEXT_LINE_MAX * 2], lines[4][TEXT_LINE_MAX];
        utf8_upper(t->title, up, sizeof up);
        int nl = text_wrap(F(a, F_POSTER18), up, x1 - x0, 4, T_TRACK(-4), lines);
        for (int i = 0; i < nl; i++) txt(a, g, F_POSTER18, x0, y + i * 18, lines[i], p->ink, T_TRACK(-4));
        y += (nl - 1) * 18 + 17;
        txt_fit(a, g, F_SEMI12, x0, y, t->artist, x1 - x0, p->blue, 0);
    }
    if (a->why[0]) {
        char lines[3][TEXT_LINE_MAX];
        int nl = text_wrap(F(a, F_BODY10), a->why, x1 - x0, 3, 0, lines);
        for (int i = 0; i < nl; i++) txt(a, g, F_BODY10, x0, y + 20 + i * 12, lines[i], p->sub, 0);
        y += 20 + (nl - 1) * 12;
    }
    if (brain_is_liked(a->cur)) txt(a, g, F_BODY10, x0, y + 16, "\xE2\x99\xA5 liked", p->ink, 0);

    const int y0 = A;
    g_fill(g, 0, y0, LCD_W, LCD_H - y0, p->strip_bg);
    if (a->ps.length_ms)
        g_fill(g, 0, y0, (int)((uint64_t)LCD_W * a->ps.elapsed_ms / a->ps.length_ms), 2, p->red);
    char e[16], tot[16];
    mmss(e, sizeof e, a->ps.elapsed_ms / 1000);
    mmss(tot, sizeof tot, (a->ps.length_ms ? a->ps.length_ms / 1000 : (t ? t->dur : 0)));
    txt(a, g, F_MONO12, 8, y0 + 18, e, p->strip_fg, 0);
    txt_right(a, g, F_MONO12, LCD_W - 8, y0 + 18, tot, p->strip_sub);
    if (a->next_pick != LIB_NONE) {
        const lib_track *n = lib_get(a->L, a->next_pick);
        int ny = y0 + 28;
        cover(a, g, a->next_pick, ART_S, 8, ny, 36);
        txt(a, g, F_MONO10, 52, ny + 11, "next", p->strip_sub, 0);
        if (n) {
            txt_fit(a, g, F_BOLD11, 52, ny + 24, n->title, 250, p->strip_fg, 0);
            txt_fit(a, g, F_BODY10, 52, ny + 35, n->artist, 250, p->strip_sub, 0);
        }
    }
}

static void draw_crate_rows(app *a, gfx *g, list_state *l, const char *const *names,
                            const char *const *counts, int n)
{
    const palette *p = P(a);
    l->n = n;
    list_follow(l, 6);
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    for (int i = 0; i < n; i++) {
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        int foc = i == l->sel;
        if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
        int w = txt(a, g, F_POSTER22, 8, y + 24, names[i], foc ? p->paper : p->ink, T_TRACK(-6));
        if (counts && counts[i]) {
            int cw = text_w(F(a, F_MONO10), counts[i], 0);
            dotted_leader(g, 8 + w + 6, LCD_W - 10 - cw, y + 19, foc ? p->strip_sub : p->sub);
            txt_right(a, g, F_MONO10, LCD_W - 6, y + 21, counts[i], foc ? p->paper : p->sub);
        }
        if (!foc) g_fill(g, 0, y + ROW_H - 1, LCD_W, 1, p->rule);
    }
    g_noclip(g);
}

static void draw_library(app *a, gfx *g)
{
    char songs[24], artists[24];
    commas(songs, sizeof songs, lib_n(a->L));
    commas(artists, sizeof artists, lib_n_artists(a->L));
    const char *counts[N_LIB] = { songs, artists, NULL, NULL, NULL };
    draw_header(a, g, "Library", NULL);
    draw_crate_rows(a, g, &a->ls[V_LIBRARY], lib_items, counts, N_LIB);
    draw_nowbar(a, g);
}

static void draw_artists(app *a, gfx *g)
{
    const palette *p = P(a);
    list_state *l = &a->ls[V_ARTISTS];
    l->n = (int)lib_n_artists(a->L);
    char cnt[24];
    commas(cnt, sizeof cnt, (uint32_t)l->n);
    draw_header(a, g, "Artists", cnt);
    list_follow(l, 6);
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    int first = (int)floorf(l->top);
    for (int i = first; i < first + 8 && i < l->n; i++) {
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        uint32_t fi, c;
        lib_artist(a->L, (uint32_t)i, &fi, &c);
        const lib_track *t = lib_get(a->L, fi);
        int foc = i == l->sel;
        if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
        cover(a, g, fi, ART_S, 0, y, ROW_H);
        int w = t ? txt_fit(a, g, F_POSTER15, ROW_H + 8, y + 20, t->artist, 210, foc ? p->paper : p->ink, T_TRACK(-3)) : 0;
        char cs[16];
        snprintf(cs, sizeof cs, "%u", (unsigned)c);
        int cw = text_w(F(a, F_MONO10), cs, 0);
        dotted_leader(g, ROW_H + 8 + w + 5, LCD_W - 10 - cw, y + 18, foc ? p->strip_sub : p->sub);
        txt_right(a, g, F_MONO10, LCD_W - 6, y + 20, cs, foc ? p->paper : p->sub);
        if (!foc) g_fill(g, ROW_H, y + ROW_H - 1, LCD_W - ROW_H, 1, p->rule);
    }
    g_noclip(g);
    draw_nowbar(a, g);
}

static void draw_tracks(app *a, gfx *g)
{
    const palette *p = P(a);
    list_state *l = &a->ls[V_TRACKS];
    l->n = a->n_tracks;
    char cnt[24];
    commas(cnt, sizeof cnt, (uint32_t)l->n);
    draw_header(a, g, a->tracks_title, cnt);
    list_follow(l, 6);
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    if (l->n == 0)
        txt(a, g, F_BODY10, 8, LIST_Y + 22, a->tracks_kind == TK_LIKED ?
            "Nothing liked yet. Long-press play on a song." : "Nothing here yet.", p->sub, 0);
    int first = (int)floorf(l->top);
    for (int i = first; i < first + 8 && i < l->n; i++) {
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        uint32_t idx = track_at(a, i);
        const lib_track *t = lib_get(a->L, idx);
        int foc = i == l->sel, live = a->cur_valid && idx == a->cur;
        if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
        cover(a, g, idx, ART_S, 0, y, ROW_H);
        if (!t) continue;
        char d[16];
        mmss(d, sizeof d, t->dur);
        int dw = text_w(F(a, F_MONO10), d, 0);
        txt_fit(a, g, F_BOLD11, ROW_H + 8, y + 13, t->title, LCD_W - ROW_H - 22 - dw,
                live && !foc ? p->red : foc ? p->paper : p->ink, 0);
        txt_fit(a, g, F_BODY10, ROW_H + 8, y + 25, t->artist, LCD_W - ROW_H - 22 - dw,
                foc ? p->strip_sub : p->sub, 0);
        txt_right(a, g, F_MONO10, LCD_W - 6, y + 13, d, foc ? p->paper : p->sub);
        if (!foc) g_fill(g, ROW_H, y + ROW_H - 1, LCD_W - ROW_H, 1, p->rule);
    }
    g_noclip(g);
    draw_nowbar(a, g);
}

static void draw_settings(app *a, gfx *g)
{
    const palette *p = P(a);
    draw_header(a, g, "Settings", NULL);
    list_state *l = &a->ls[V_SETTINGS];
    l->n = N_SETTINGS;
    list_follow(l, 6);
    const char *labels[N_SETTINGS] = { "Wheel style", "Theme", "Wheel clicks", "Visualizer",
                                       "Keep playing" };
    const char *vals[N_SETTINGS] = {
        a->layout_b ? "B: dial" : "A: full wheel",
        a->night_mode < 0 ? "auto (dark 7pm)" : a->night_mode ? "night" : "day",
        a->tick_sound ? "on" : "off",
        a->viz_on ? "on" : "off",
        a->keep_playing ? "after exit" : "only in Coda",
    };
    for (int i = 0; i < N_SETTINGS; i++) {
        int y = LIST_Y + i * ROW_H, foc = i == l->sel;
        if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
        txt(a, g, F_POSTER15, 8, y + 20, labels[i], foc ? p->paper : p->ink, T_TRACK(-3));
        txt_right(a, g, F_MONO10, LCD_W - 8, y + 20, vals[i], foc ? p->paper : p->blue);
        if (!foc) g_fill(g, 0, y + ROW_H - 1, LCD_W, 1, p->rule);
    }
    draw_nowbar(a, g);
}

static void draw_soon(app *a, gfx *g, const char *title)
{
    draw_header(a, g, title, NULL);
    txt(a, g, F_BODY10, 8, LIST_Y + 22, "Being built.", P(a)->sub, 0);
    draw_nowbar(a, g);
}

void app_draw(app *a, gfx *g)
{
    if (a->night_mode >= 0) theme_set_night(&a->th, a->night_mode);
    else { int h, m; plat_clock(&h, &m); theme_set_night(&a->th, h >= 19 || h < 7); }
    g_noclip(g);
    g_fill(g, 0, 0, LCD_W, LCD_H, P(a)->paper);
    switch (a->view) {
    case V_MENU: draw_menu(a, g); break;
    case V_WHEEL: draw_wheel(a, g); break;
    case V_NOW: draw_now(a, g); break;
    case V_LIBRARY: draw_library(a, g); break;
    case V_ARTISTS: draw_artists(a, g); break;
    case V_TRACKS: draw_tracks(a, g); break;
    case V_SETTINGS: draw_settings(a, g); break;
    case V_EXPLORE: draw_soon(a, g, "Explore"); break;
    case V_SEARCH: draw_soon(a, g, "Search"); break;
    case V_OST: draw_soon(a, g, "OST"); break;
    case V_GENRES: draw_soon(a, g, "Genres"); break;
    default: draw_soon(a, g, "Queue"); break;
    }
}

/* ------------------------------------------------------------------ input */
static void list_scroll(list_state *l, int d) { l->sel = fx_clamp(l->sel + d, 0, l->n > 0 ? l->n - 1 : 0); }

static void menu_select(app *a)
{
    switch (a->ls[V_MENU].sel) {
    case 0: push(a, V_WHEEL); break;
    case 1: push(a, V_NOW); break;
    case 2: push(a, V_EXPLORE); break;
    case 3: push(a, V_SEARCH); break;
    case 4: push(a, V_LIBRARY); break;
    case 5: set_tracks(a, TK_LIKED, "Liked"); push(a, V_TRACKS); break;
    default: push(a, V_SETTINGS); break;
    }
}

static void library_select(app *a)
{
    switch (a->ls[V_LIBRARY].sel) {
    case 0: set_tracks(a, TK_SONGS, "Songs"); push(a, V_TRACKS); break;
    case 1: push(a, V_ARTISTS); break;
    case 2: push(a, V_GENRES); break;
    case 3: push(a, V_OST); break;
    default: set_tracks(a, TK_HISTORY, "History"); push(a, V_TRACKS); break;
    }
}

static void tracks_select(app *a)
{
    list_state *l = &a->ls[V_TRACKS];
    if (l->n <= 0) return;
    if (a->tracks_kind == TK_RESULTS) { play_one(a, track_at(a, l->sel)); return; }
    static uint32_t q[200];
    int n = 0;
    for (int i = l->sel; i < l->n && n < 200; i++) q[n++] = track_at(a, i);
    play_from(a, q, n);
}

static void wheel_play(app *a)
{
    if (!a->n_pool) return;
    uint32_t idx = a->pool[mod(a->target, a->n_pool)];
    if (a->cur_valid && idx == a->cur) plat_toggle();
    else play_one(a, idx);
}

static void toggle_like(app *a, uint32_t idx)
{
    brain_log(idx, brain_is_liked(idx) ? 6 : 3, -1.0f, (double)plat_now());
}

void app_event(app *a, ui_ev e)
{
    if (e.k == K_MENU) {
        if (a->view == V_MENU) { if (a->section != V_MENU) push(a, a->section); }
        else { a->depth = 0; a->view = V_MENU; }
        return;
    }
    if (e.k == K_PREV) { plat_skip(-1); return; }
    if (e.k == K_NEXT) { plat_skip(+1); return; }
    if (e.k == K_BACK) { pop(a); return; }
    switch (a->view) {
    case V_MENU:
        if (e.k == K_SCROLL) list_scroll(&a->ls[V_MENU], e.d);
        else if (e.k == K_PLAY) menu_select(a);
        break;
    case V_WHEEL:
        if (e.k == K_SCROLL && a->n_pool) {
            a->target += e.d;
            if (a->tick_sound) plat_beep(1800, 3, 600);
        } else if (e.k == K_PLAY) wheel_play(a);
        else if (e.k == K_PLAY_LONG && a->n_pool) toggle_like(a, a->pool[mod(a->target, a->n_pool)]);
        break;
    case V_NOW:
        if (e.k == K_SCROLL) plat_seek(e.d * 5000);
        else if (e.k == K_PLAY) plat_toggle();
        else if (e.k == K_PLAY_LONG && a->cur_valid) toggle_like(a, a->cur);
        break;
    case V_LIBRARY:
        if (e.k == K_SCROLL) list_scroll(&a->ls[V_LIBRARY], e.d);
        else if (e.k == K_PLAY) library_select(a);
        break;
    case V_ARTISTS:
        if (e.k == K_SCROLL) list_scroll(&a->ls[V_ARTISTS], e.d);
        else if (e.k == K_PLAY) {
            uint32_t fi, c;
            lib_artist(a->L, (uint32_t)a->ls[V_ARTISTS].sel, &fi, &c);
            const lib_track *t = lib_get(a->L, fi);
            set_tracks(a, TK_ARTIST, t ? t->artist : "Artist");
            a->n_tracks = 0;
            for (uint32_t i = 0; i < c && a->n_tracks < TRACKS_MAX; i++) a->tracks[a->n_tracks++] = fi + i;
            push(a, V_TRACKS);
        }
        break;
    case V_TRACKS:
        if (e.k == K_SCROLL) list_scroll(&a->ls[V_TRACKS], e.d);
        else if (e.k == K_PLAY) tracks_select(a);
        else if (e.k == K_PLAY_LONG && a->n_tracks) toggle_like(a, track_at(a, a->ls[V_TRACKS].sel));
        break;
    case V_SETTINGS:
        if (e.k == K_SCROLL) list_scroll(&a->ls[V_SETTINGS], e.d);
        else if (e.k == K_PLAY) {
            int s = a->ls[V_SETTINGS].sel;
            if (s == 0) a->layout_b = !a->layout_b;
            else if (s == 1) a->night_mode = a->night_mode == 0 ? 1 : a->night_mode == 1 ? -1 : 0;
            else if (s == 2) a->tick_sound = !a->tick_sound;
            else if (s == 3) a->viz_on = !a->viz_on;
            else a->keep_playing = !a->keep_playing;
            coda_settings_save(a);
        }
        break;
    default:
        break;
    }
}

static uint32_t mix32(uint32_t h, uint32_t v) { return (h ^ v) * 16777619u; }

/* Everything a frame depends on, hashed. Same hash -> the screen would look the same. */
static uint32_t frame_sig(app *a)
{
    int h, m;
    plat_clock(&h, &m);
    uint32_t s = 2166136261u;
    s = mix32(s, (uint32_t)a->view);
    s = mix32(s, (uint32_t)(a->layout_b | (a->night_mode + 1) << 1 | a->viz_on << 3));
    s = mix32(s, (uint32_t)(h * 60 + m));
    s = mix32(s, (uint32_t)lrintf(a->s * 64.0f));
    s = mix32(s, (uint32_t)a->target);
    s = mix32(s, (uint32_t)a->n_pool);
    s = mix32(s, a->cur_valid ? a->cur : 0xFFFFFFFFu);
    s = mix32(s, (uint32_t)a->ps.playing);
    s = mix32(s, a->next_pick);
    if (a->view != V_WHEEL) s = mix32(s, a->ps.elapsed_ms / 1000);   /* time is on screen */
    const list_state *l = &a->ls[a->view];
    s = mix32(s, (uint32_t)l->sel);
    s = mix32(s, (uint32_t)lrintf(l->top * 16.0f));
    s = mix32(s, (uint32_t)a->n_tracks);
    s = mix32(s, (uint32_t)a->why[0]);
    return s;
}

static int wheel_moving(const app *a) { return a->view == V_WHEEL && a->s != (float)a->target; }

static int viz_live(const app *a)
{
    return a->view == V_WHEEL && a->viz_on && a->ps.playing && a->cur_valid;
}

int app_tick(app *a, uint32_t now_ms)
{
    uint32_t dt = a->last_ms ? now_ms - a->last_ms : 16;
    if (dt > 200) dt = 200;
    a->last_ms = now_ms;
    a->now_ms = now_ms;
    autoplay_tick(a);
    /* wheel: ease toward the target detent */
    float k = 1.0f - expf(-(float)dt / 55.0f);
    a->s += (a->target - a->s) * k;
    if (fabsf(a->target - a->s) < 0.004f) a->s = (float)a->target;

    uint32_t sig = frame_sig(a);
    if (a->force_full || sig != a->drawn_sig) {
        a->force_full = 0;
        a->drawn_sig = sig;
        a->hub_ms = now_ms;
        return NEED_FULL;
    }
    if (viz_live(a) && now_ms - a->hub_ms >= 50) {            /* sunburst at 20 fps */
        a->hub_ms = now_ms;
        return NEED_HUB;
    }
    return NEED_NONE;
}

int app_interval_ms(app *a)
{
    if (wheel_moving(a)) return 16;
    if (viz_live(a)) return 50;
    return 500;                                              /* clock + progress only */
}

int app_background_autoplay(app *a) { return a->keep_playing; }
void app_autoplay_step(app *a) { autoplay_tick(a); }
void app_force_redraw(app *a) { a->force_full = 1; }

void app_draw_hub(app *a, gfx *g, int rect[4])
{
    wheel_frame f;
    int focused;
    wheel_frame_fill(a, &f, &focused);
    wheel_draw_hub(g, P(a), a->layout_b ? &WHEEL_B : &WHEEL_A, &f, rect);
}

/* ------------------------------------------------------------------ settings file */
static void coda_settings_save(app *a)
{
    char buf[160];
    int n = snprintf(buf, sizeof buf, "layout=%c\ntheme=%d\nticks=%d\nviz=%d\nkeep=%d\n",
                     a->layout_b ? 'b' : 'a', a->night_mode, a->tick_sound, a->viz_on,
                     a->keep_playing);
    plat_save("settings.txt", buf, (size_t)n);
}

static void coda_settings_load(app *a)
{
    size_t len;
    char *s = plat_load("settings.txt", &len);
    if (!s) return;
    for (char *line = s; line && *line; ) {
        char *nl = strchr(line, '\n');
        if (nl) *nl = 0;
        char *eq = strchr(line, '=');
        if (eq) {
            *eq = 0;
            const char *v = eq + 1;
            int iv = (int)strtol(v, NULL, 10);
            if (!strcmp(line, "layout")) a->layout_b = v[0] == 'b';
            else if (!strcmp(line, "theme")) a->night_mode = iv < -1 || iv > 1 ? 0 : iv;
            else if (!strcmp(line, "ticks")) a->tick_sound = iv != 0;
            else if (!strcmp(line, "viz")) a->viz_on = iv != 0;
            else if (!strcmp(line, "keep")) a->keep_playing = iv != 0;
        }
        line = nl ? nl + 1 : NULL;
    }
}

app *app_create(const char *pack_dir, const char *plays_path)
{
    static app A;
    app *a = &A;
    memset(a, 0, sizeof *a);
    fx_init();
    if (theme_load(&a->th) != 0) return NULL;
    if (brain_open(pack_dir, plays_path) != 0) { plat_log("brain: pack open failed"); return NULL; }
    a->L = lib_open(brain_pack());
    a->tracks = plat_alloc(sizeof(uint32_t) * TRACKS_MAX);
    a->view = V_MENU;
    a->section = V_WHEEL;
    a->night_mode = 0;          /* day (white) by default; Settings > Theme cycles day/night/auto */
    a->tick_sound = 1;
    a->viz_on = 1;
    a->keep_playing = 1;
    coda_settings_load(a);
    a->force_full = 1;
    a->next_pick = LIB_NONE;
    a->ls[V_MENU].n = N_MENU;
    a->ls[V_LIBRARY].n = N_LIB;
    a->ls[V_SETTINGS].n = N_SETTINGS;
    return a;
}
