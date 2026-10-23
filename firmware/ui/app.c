#include "app.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "brain.h"
#include "crates.h"
#include "fx.h"
#include "lib.h"
#include "search.h"
#include "theme.h"
#include "boot.h"
#include "wheel.h"
#include "sym.h"
#include "pix.h"
#include "../plat/plat.h"

#define ROW_H 30
#define LIST_Y 31
#define BAR_Y 212
#define POOL_N 512                /* the Wheel: songs and lists you go back to (brain_wheel) */
#define PLAN_N 25                 /* autoplay lays the radio out this far ahead, like YT Music's queue */
#define PLAN_LOW 5                /* ... and tops it up when fewer than this are left */
#define PICK_KEEP_MS 30000        /* a start counts toward the Wheel once you've stayed this long */
#define SESSION_MAX 512
#define TRACKS_MAX 4096
#define QMAX 256
#define SHELF_N 12                /* covers on a shelf's strip */
#define SHELF_ALL 400             /* songs in a shelf's list: what's still fresh of the card's pool */
#define STALL_MS 6000             /* "playing" and the clock stood still this long: stuck */
#define PEEK_AFTER_MS 600       /* wheel resting on a slice this long -> preview it */
#define PEEK_MAX_MS 30000      /* one preview this long and nothing chosen: back to the song */
#define SKIP_INTENT_MS 2500     /* a track change this soon after Next = the listener's skip */

typedef struct { int n, sel; float top; } list_state;

typedef struct { uint32_t idx; px16 *px; uint32_t used; int ok; } tex_slot;
#define NT_S 48
#define NT_M 16
#define NT_L 3

/* what a track list holds, and what picking a row does there (web TrackList semantics):
 * "single" lists are lookups -- the pick plays and autoplay carries on from it;
 * sequences (an artist, a soundtrack, your likes) play through in order */
enum { TK_ARTIST, TK_SONGS, TK_LIKED, TK_HISTORY, TK_RESULTS, TK_SHELF, TK_OST, TK_GENRE, TK_SAVED };
enum { CK_EXPLORE, CK_OST, CK_GENRE };
enum { QS_USER, QS_AUTO };
enum { SH_NONE, SH_NOW, SH_TRACK, SH_QROW };     /* QROW: a song in the queue, by position */
enum { OUT_NONE, OUT_SKIP, OUT_SWITCH };

/* the letter rail: a-z, 0-9, then space, delete, "to the results" */
static const char RAIL[] = "abcdefghijklmnopqrstuvwxyz0123456789";
#define RAIL_SPACE 36
#define RAIL_DEL 37
#define RAIL_GO 38
#define RAIL_N 39

struct app {
    theme th;
    lib *L;
    int view, stack[16], depth, section, night_mode;
    /* wheel */
    uint32_t pool[POOL_N];
    int n_pool, target, layout_b, spun;
    float s;
    uint32_t spin_ms;
    /* textures */
    tex_slot ts[NT_S], tm[NT_M], tl[NT_L];
    uint32_t tex_clock;
    /* player: the queue we own, mirrored in the platform player */
    plat_play ps;
    uint32_t q[QMAX];
    uint8_t qsrc[QMAX];
    int qn, qpos;
    uint32_t cur, last_elapsed, last_len, auto_idx;
    int cur_valid, outcome, autoplay_on, fence;
    uint32_t outcome_ms;
    uint32_t seek_to, seek_ms;            /* wheel seeking: detents add up before the player catches up */
    uint32_t session[SESSION_MAX];
    int n_session;
    char why[160], why_auto[160];
    /* a song or Wheel list you started yourself, counted toward the Wheel once it has played
     * PICK_KEEP_MS (brain_wheel_pick) */
    uint32_t pick_item, pick_song;
    int pick_on;
    /* wheel peek (one decoder: the preview replaces the song, then the song comes back) */
    int peek_on, peeking, peek_was_playing, peek_was_active;
    uint32_t peek_idx, peek_saved_ms, peek_t0, peek_ignore_until, peek_this_t0;   /* t0: the first preview; this: the one on */
    /* lists */
    list_state ls[V_COUNT];
    uint32_t *tracks;
    int n_tracks, tracks_kind, n_actions;
    uint32_t tracks_crate;
    char tracks_title[112];
    /* crates */
    crates cr[3];
    int crate_kind;
    int crate_rows[1024], n_crate_rows;     /* OST view: >= 0 crate, < 0 section header */
    uint32_t shelf[3][SHELF_N], shelf_all[3][SHELF_ALL];
    int shelf_n[3], shelf_all_n[3], shelves_drawn;
    uint8_t *genre_of;
    /* search */
    char query[40];
    int rail, s_results;
    search_hit hits[SEARCH_MAX];
    int n_hits;
    uint32_t hit_artist[3];
    int n_hit_artists;
    /* clock editor: hour, minute, day, month, year */
    int ck[5], ck_field;
    /* settings rows (what this platform has), and a device setting being adjusted */
    int set_row[24], n_set, adj, adj_i;
    /* Bluetooth (PF_BLUETOOTH): the platform's state and the list built from it; a row is
     * a device index or one of the BTROW_ codes */
    int bt_has, bt_autoscan;      /* autoscan: switched on here, search once it's up */
    uint8_t bt_pending[6];        /* a card on Diorama's board picked with the radio off: */
    int bt_pending_on;            /* connect it once the radio's up */
    plat_bt bt;
    plat_bt_dev bt_dev[24];
    int bt_ndev, bt_rows[32], bt_nrows;
    unsigned bt_gen_seen, bt_vol_seen;
    char bt_msg_seen[64];
    /* action sheet */
    int sheet, sheet_sel;
    uint32_t sheet_idx;
    int sheet_qpos;
    /* the queue on the card (q_save), brightness waiting to be saved */
    uint32_t qsave_ms, bright_ms;
    int qsave_dirty, bright_dirty;
    char notice[64];
    uint32_t notice_ms;
    uint32_t now_ms, last_ms;
    int tick_sound, viz_on, keep_playing;
    /* change detection: the last frame's inputs; a full redraw only when they differ */
    uint32_t drawn_sig, hub_ms;
    int force_full;
    /* the theme, and its motion: when the focus last moved (and from where), the list
     * cursor sliding to it, when the sheet came up */
    int skin;
    uint32_t ui_t0, sheet_t0, poke_ms;      /* poke: the last button, whatever it did */
    int ui_prev, ui_view;
    float cur_y, cur_from;
    int cur_target, cur_view;
    uint32_t cur_t0;
    /* Settings: the group open (-1 = the panels), and the panels' own focus */
    int set_group;
    list_state gl;
    /* the playback watchdog: where the song's clock last moved, and how far the rescue got */
    uint32_t stall_el, stall_idx, stall_t0;
    int stall_stage;
    /* switched on by the charger: the charge screen until a button (or off when unplugged) */
    int charge_mode;                  /* 1: show the charge, then off to charge; 2: stay on, dark */
    uint32_t unplugged_ms, charge_t0;
};

static const char *const menu_items[] = { "Wheel", "Now playing", "Queue", "Explore", "Search",
                                          "Library", "Liked", "Settings" };
#define N_MENU 8
static const int menu_view[N_MENU] = { V_WHEEL, V_NOW, V_QUEUE, V_EXPLORE, V_SEARCH, V_LIBRARY, -1,
                                       V_SETTINGS };
#define N_LIB 6

/* Settings: Coda's own (settings.txt) and, on Coda OS, the device's (Rockbox's config.cfg,
 * through plat_dev_*). Numbers are adjusted in place: Play starts, the wheel changes the
 * value live (brightness shows at once), Play or Back sets it. */
enum { SR_SLEEP, SR_THEME, SR_LAYOUT, SR_TICKS, SR_PEEK, SR_VIZ, SR_AUTOPLAY, SR_KEEP,
       SR_SCREEN, SR_BRIGHT, SR_POWEROFF, SR_VOLMAX, SR_BASS, SR_TREBLE, SR_BT, SR_UNPLUG,
       SR_CLOCK, SR_COUNT };
static const char *const sr_label[SR_COUNT] = {
    "Sleep timer", "Theme", "Wheel style", "Wheel clicks", "Wheel peek", "Visualizer",
    "Autoplay", "Keep playing", "Screen off after", "Brightness", "Power off idle",
    "Volume limit", "Bass", "Treble", "Bluetooth", "Headphones out", "Clock" };
static int sr_dev(int r)
{
    switch (r) {
    case SR_SLEEP: return DS_SLEEP;
    case SR_SCREEN: return DS_SCREEN;
    case SR_BRIGHT: return DS_BRIGHT;
    case SR_POWEROFF: return DS_POWEROFF;
    case SR_VOLMAX: return DS_VOLMAX;
    case SR_BASS: return DS_BASS;
    case SR_TREBLE: return DS_TREBLE;
    case SR_UNPLUG: return DS_UNPLUG;
    default: return -1;
    }
}

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

static void hm(char *out, size_t n, uint32_t sec)
{
    unsigned h = sec / 3600, m = (sec % 3600 + 30) / 60;
    if (h) snprintf(out, n, "%uh%02u", h, m);
    else snprintf(out, n, "%um", m ? m : 1);
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

static uint32_t rng_state = 0x2545F491u;
static uint32_t rnd(uint32_t n)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return n ? rng_state % n : 0;
}

static void shuffle(uint32_t *v, int n)
{
    for (int i = n - 1; i > 0; i--) {
        int j = (int)rnd((uint32_t)i + 1);
        uint32_t t = v[i]; v[i] = v[j]; v[j] = t;
    }
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

static void say(app *a, const char *msg)
{
    snprintf(a->notice, sizeof a->notice, "%s", msg);
    a->notice_ms = a->now_ms ? a->now_ms : 1;
}

/* ------------------------------------------------------------------ navigation */
static void open_view(app *a, int v);
static void coda_settings_save(app *a);
static void settings_rows(app *a);
static void clock_open(app *a);
static void bt_open(app *a);

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
    a->s = 0;                                      /* always opens at the top of the list, like the web's */
    a->target = 0;
    a->spun = 0;
}

static void set_tracks(app *a, int kind, const char *title)
{
    a->tracks_kind = kind;
    a->n_actions = kind == TK_ARTIST || kind == TK_OST || kind == TK_GENRE || kind == TK_SHELF || kind == TK_SAVED ? 2 : 0;
    snprintf(a->tracks_title, sizeof a->tracks_title, "%s", title);
    a->ls[V_TRACKS].sel = 0;
    a->ls[V_TRACKS].top = 0;
}

static void ost_rows(app *a)
{
    const crates *c = &a->cr[CK_OST];
    a->n_crate_rows = 0;
    uint32_t prev = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < c->n && a->n_crate_rows < 1022; i++) {
        uint32_t sec = c->tab[i].section;
        if (sec != prev && (sec || i)) a->crate_rows[a->n_crate_rows++] = -1 - (int)i;
        prev = sec;
        a->crate_rows[a->n_crate_rows++] = (int)i;
    }
}

static int crate_row_is_header(app *a, int row)
{
    return a->view == V_OST && row >= 0 && row < a->n_crate_rows && a->crate_rows[row] < 0;
}

static void draw_shelves(app *a);
static int sv_load(void);

static void open_view(app *a, int v)
{
    a->view = v;
    a->sheet = SH_NONE;
    if (v == V_WHEEL || v == V_NOW || v == V_EXPLORE || v == V_SEARCH || v == V_QUEUE) a->section = v;
    if (v == V_WHEEL) wheel_refresh(a);
    if (v == V_ARTISTS) a->ls[V_ARTISTS].n = (int)lib_n_artists(a->L);
    if (v == V_EXPLORE) { a->crate_kind = CK_EXPLORE; a->shelves_drawn = 0; draw_shelves(a); }
    if (v == V_OST) {
        a->crate_kind = CK_OST;
        ost_rows(a);
        a->ls[V_OST].n = a->n_crate_rows;
        while (crate_row_is_header(a, a->ls[V_OST].sel)) a->ls[V_OST].sel++;
    }
    if (v == V_GENRES) { a->crate_kind = CK_GENRE; a->ls[V_GENRES].n = (int)a->cr[CK_GENRE].n; }
    if (v == V_BT) bt_open(a);
    if (v == V_SETTINGS) { a->set_group = -1; settings_rows(a); }    /* the panels first */
    if (v == V_SAVED) { a->ls[V_SAVED].n = sv_load(); a->ls[V_SAVED].sel = 0; a->ls[V_SAVED].top = 0; }
    if (v == V_QUEUE) {
        a->ls[V_QUEUE].n = a->qn + 2;
        a->ls[V_QUEUE].sel = a->qpos > 0 ? a->qpos : 0;
        a->ls[V_QUEUE].top = (float)(a->qpos > 1 ? a->qpos - 1 : 0);
    }
    if (v == V_TRACKS) {
        switch (a->tracks_kind) {
        case TK_LIKED: a->n_tracks = brain_liked(a->tracks, TRACKS_MAX); break;
        case TK_HISTORY: a->n_tracks = brain_history(a->tracks, TRACKS_MAX); break;
        case TK_SONGS: a->n_tracks = (int)lib_n(a->L); break;     /* virtual: idx == row */
        default: break;
        }
        a->ls[V_TRACKS].n = a->n_tracks + a->n_actions;
    }
}

void app_open(app *a, int view)
{
    if (view == V_TRACKS) set_tracks(a, TK_LIKED, "Liked");
    push(a, view);
}

void app_set_wheel_layout(app *a, int b) { a->layout_b = b; }
int app_wheel_focus(app *a) { return a->n_pool ? mod(a->target, a->n_pool) : -1; }
uint32_t app_wheel_item(app *a, int i) { return i >= 0 && i < a->n_pool ? a->pool[i] : 0xFFFFFFFFu; }
int app_menu_sel(app *a) { return a->ls[V_MENU].sel; }
int app_lib_sel(app *a) { return a->ls[V_LIBRARY].sel; }
void app_set_night(app *a, int night) { a->night_mode = night; }

static uint32_t track_at(app *a, int i)
{
    return a->tracks_kind == TK_SONGS ? (uint32_t)i : a->tracks[i];
}

/* ------------------------------------------------------------------ the queue */
static void q_set(app *a, const uint32_t *idx, int n, int start, int src)
{
    if (n <= 0) return;
    if (a->peeking) a->peeking = 0;               /* the new queue replaces the preview */
    int from = 0;
    if (n > QMAX) { from = start > 8 ? start - 8 : 0; if (from + QMAX > n) from = n - QMAX; n = QMAX; }
    for (int i = 0; i < n; i++) { a->q[i] = idx[from + i]; a->qsrc[i] = (uint8_t)src; }
    a->qn = n;
    a->qpos = start - from;
    a->fence = -1;
    if (a->cur_valid) { a->outcome = OUT_SWITCH; a->outcome_ms = a->now_ms; }
    plat_play_tracks(a->q, a->qn, a->qpos, 0);
    a->why[0] = 0;
    a->qsave_dirty = 1;
}

/* you started this yourself: once `song` has played PICK_KEEP_MS, `item` (the song, or the
 * Wheel list it opens) climbs the Wheel. Leave sooner and it doesn't count */
static void pick_start(app *a, uint32_t item, uint32_t song)
{
    a->pick_item = item;
    a->pick_song = song;
    a->pick_on = 1;
}

/* one song, then autoplay -- unless it's already in the queue: then the queue goes on from
 * it there (the preview's one-song playlist or not, the player's is rebuilt from ours) */
static void play_one(app *a, uint32_t idx)
{
    pick_start(a, idx, idx);
    for (int i = a->qn - 1; i >= 0; i--) {
        if (a->q[i] != idx) continue;
        if (i == a->qpos && a->cur_valid && !a->peeking) {
            if (!a->ps.playing) plat_toggle();
            return;
        }
        if (a->cur_valid) { a->outcome = OUT_SWITCH; a->outcome_ms = a->now_ms; }
        a->peeking = 0;
        plat_play_tracks(a->q, a->qn, i, 0);
        a->qsave_dirty = 1;
        return;
    }
    q_set(a, &idx, 1, 0, QS_USER);
}

/* room at the end: drop the oldest played entry (or, where the player can't delete,
 * start the queue over from the current track -- only ever at a track change) */
static int q_make_room(app *a)
{
    if (a->qn < QMAX) return 1;
    if (a->qpos > 0 && plat_queue_remove(0) == 0) {
        memmove(a->q, a->q + 1, (QMAX - 1) * sizeof a->q[0]);
        memmove(a->qsrc, a->qsrc + 1, QMAX - 1);
        a->qn--;
        a->qpos--;
        return 1;
    }
    if (a->qpos < 8) return 0;
    int keep = a->qn - (a->qpos - 4);
    memmove(a->q, a->q + a->qpos - 4, (size_t)keep * sizeof a->q[0]);
    memmove(a->qsrc, a->qsrc + a->qpos - 4, (size_t)keep);
    a->qn = keep;
    a->qpos = 4;
    plat_play_tracks(a->q, a->qn, a->qpos, a->ps.elapsed_ms);
    return 1;
}

static void q_add(app *a, uint32_t idx, int next, int src)
{
    if (!a->qn || !a->cur_valid) { q_set(a, &idx, 1, 0, src); return; }
    if (!q_make_room(a)) return;
    int at = next ? a->qpos + 1 : a->qn;
    memmove(a->q + at + 1, a->q + at, (size_t)(a->qn - at) * sizeof a->q[0]);
    memmove(a->qsrc + at + 1, a->qsrc + at, (size_t)(a->qn - at));
    a->q[at] = idx;
    a->qsrc[at] = (uint8_t)src;
    a->qn++;
    plat_queue_add(idx, next);
    a->qsave_dirty = 1;
}

static void q_jump(app *a, int pos)
{
    if (pos < 0 || pos >= a->qn) return;
    if (pos == a->qpos && a->cur_valid) { plat_toggle(); return; }
    a->outcome = OUT_SWITCH;
    a->outcome_ms = a->now_ms;
    plat_jump(pos);
}

static void q_remove(app *a, int pos)
{
    if (pos < 0 || pos >= a->qn || pos == a->qpos) return;
    if (plat_queue_remove(pos) != 0) { say(a, "Can't take songs out here"); return; }
    memmove(a->q + pos, a->q + pos + 1, (size_t)(a->qn - pos - 1) * sizeof a->q[0]);
    memmove(a->qsrc + pos, a->qsrc + pos + 1, (size_t)(a->qn - pos - 1));
    a->qn--;
    if (pos < a->qpos) a->qpos--;
    a->qsave_dirty = 1;
}

/* ------------------------------------------------------------------ the queue across power-off
 * /.coda/queue.bin: the queue, where you are in it and how far into the song -- written at
 * every change and every 15 s while playing, and at power-off. At power-on the player
 * picks it up from there, paused. (Rockbox's own resume point only moves while its
 * playback screen runs, which Coda's never does: every queue came back at its first song.) */
#define QSAVE_MS 15000
#define QS_HEAD 28
static uint8_t qs_buf[QS_HEAD + QMAX * 5];

static void qs_w32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24); }
static uint32_t qs_r32(const uint8_t *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }

/* the song's title + artist, hashed: a card filled again later numbers its songs anew */
static uint32_t qs_mark(app *a, uint32_t idx)
{
    const lib_track *t = lib_get(a->L, idx);
    uint32_t h = 2166136261u;
    for (const char *s = t ? t->title : ""; *s; s++) h = (h ^ (uint8_t)*s) * 16777619u;
    for (const char *s = t ? t->artist : ""; *s; s++) h = (h ^ (uint8_t)*s) * 16777619u;
    return h;
}

static void q_save(app *a)
{
    a->qsave_ms = a->now_ms;
    a->qsave_dirty = 0;
    if (a->qn <= 0 || a->qpos < 0 || a->qpos >= a->qn) return;
    memcpy(qs_buf, "CQU1", 4);
    qs_w32(qs_buf + 4, brain_n());
    qs_w32(qs_buf + 8, (uint32_t)a->qn);
    qs_w32(qs_buf + 12, (uint32_t)a->qpos);
    qs_w32(qs_buf + 16, a->peeking ? a->peek_saved_ms : a->cur_valid ? a->last_elapsed : 0);
    qs_w32(qs_buf + 20, qs_mark(a, a->q[a->qpos]));
    qs_w32(qs_buf + 24, 0);
    for (int i = 0; i < a->qn; i++) qs_w32(qs_buf + QS_HEAD + 4 * i, a->q[i]);
    memcpy(qs_buf + QS_HEAD + 4 * a->qn, a->qsrc, (size_t)a->qn);
    plat_save("queue.bin", qs_buf, QS_HEAD + 5 * (size_t)a->qn);
}

void app_save_queue(app *a) { q_save(a); }

int app_resume_saved(app *a)
{
    int fd = plat_open("queue.bin");
    if (fd < 0) return 0;
    int r = plat_pread(fd, qs_buf, (int)sizeof qs_buf, 0);
    plat_close(fd);
    if (r < QS_HEAD || memcmp(qs_buf, "CQU1", 4) || qs_r32(qs_buf + 4) != brain_n()) return 0;
    uint32_t n = qs_r32(qs_buf + 8), pos = qs_r32(qs_buf + 12), el = qs_r32(qs_buf + 16);
    if (!n || n > QMAX || pos >= n || r < (int)(QS_HEAD + 5 * n)) return 0;
    for (uint32_t i = 0; i < n; i++)
        if (qs_r32(qs_buf + QS_HEAD + 4 * i) >= brain_n()) return 0;
    if (qs_mark(a, qs_r32(qs_buf + QS_HEAD + 4 * pos)) != qs_r32(qs_buf + 20)) return 0;
    for (uint32_t i = 0; i < n; i++) a->q[i] = qs_r32(qs_buf + QS_HEAD + 4 * i);
    memcpy(a->qsrc, qs_buf + QS_HEAD + 4 * n, n);
    a->qn = (int)n;
    a->qpos = (int)pos;
    uint32_t len = (uint32_t)brain_duration(a->q[pos]) * 1000u;
    if (len && el + 4000 > len) el = 0;              /* it had all but ended: from the top */
    plat_play_tracks(a->q, a->qn, a->qpos, el);
    plat_toggle();                                   /* paused, as you left it */
    plat_player(&a->ps);
    if (a->ps.active && a->ps.idx == a->q[pos]) {    /* following it already: not a new play */
        a->cur = a->ps.idx;
        a->cur_valid = 1;
        if (a->n_session < SESSION_MAX) a->session[a->n_session++] = a->cur;
        a->last_elapsed = el;
        a->last_len = a->ps.length_ms;
    }
    a->qsave_ms = a->now_ms;
    a->force_full = 1;
    plat_log("os: resumed Coda's queue: %d songs, at %d, %u ms, paused", a->qn, a->qpos + 1, (unsigned)el);
    return 1;
}

/* ------------------------------------------------------------------ autoplay */
static uint32_t genre_random(app *a, int g)
{
    const crates *c = &a->cr[CK_GENRE];
    if (g < 0 || (uint32_t)g >= c->n || !c->tab[g].count) return LIB_NONE;
    uint32_t m;
    return crate_members(c, (uint32_t)g, rnd(c->tab[g].count), &m, 1) == 1 ? m : LIB_NONE;
}

static int in_session(app *a, uint32_t idx)
{
    for (int i = 0; i < a->n_session; i++) if (a->session[i] == idx) return 1;
    return 0;
}

/* the engine came back empty-handed (it never should; it did once on the H2, and the queue
 * just ended): a song of the same genre, else any song not heard this session */
static uint32_t autoplay_fallback(app *a)
{
    int g = a->genre_of && a->cur < lib_n(a->L) ? a->genre_of[a->cur] : 255;
    for (int k = 0; k < 60; k++) {
        uint32_t c = g != 255 && k < 30 ? genre_random(a, g) : rnd(lib_n(a->L));
        if (c != LIB_NONE && c != a->cur && !in_session(a, c)) return c;
    }
    return LIB_NONE;
}

/* one pick queued past the end (whether or not autoplay is on: the caller decides) */
static int autoplay_add(app *a, double now)
{
    if (!a->cur_valid || a->qpos != a->qn - 1) return 0;
    uint32_t pick = brain_next(a->cur, a->session, a->n_session - 1, BRAIN_OUT_COMPLETE, 0.0f,
                               now, a->why_auto, sizeof a->why_auto, a->genre_of, a->fence);
    if (pick == LIB_NONE && a->fence >= 0) {
        pick = genre_random(a, a->fence);
        snprintf(a->why_auto, sizeof a->why_auto, "more from this station");
    }
    if (pick == LIB_NONE || pick == a->cur) {
        pick = autoplay_fallback(a);
        plat_log("autoplay: the engine had nothing after %u; %s", (unsigned)a->cur,
                 pick == LIB_NONE ? "nothing either way" : "a song of its genre instead");
        snprintf(a->why_auto, sizeof a->why_auto, "close to what's playing");
    }
    if (pick == LIB_NONE) return 0;
    a->auto_idx = pick;
    q_add(a, pick, 0, QS_AUTO);
    return 1;
}

/* The radio laid out ahead, as YT Music's queue is: up to PLAN_N songs after this one,
 * topped up when fewer than PLAN_LOW are left (songs you queued yourself count as ahead).
 * A skip leaves what's queued alone, as on YT Music: it's in the play log, so the songs the
 * next top-up adds steer off it. Genre stations and older packs still go one pick at a time. */
static int autoplay_fill(app *a, double now)
{
    if (!a->cur_valid || a->qpos < 0) return 0;
    int ahead = a->qn - 1 - a->qpos;
    if (a->fence >= 0 || brain_engine() < 4) return ahead ? 0 : autoplay_add(a, now);
    if (ahead >= PLAN_LOW) return 0;
    uint32_t plan[PLAN_N];
    char why[160];
    int got = brain_plan(a->cur, a->session, a->n_session - 1, a->q + a->qpos + 1, ahead,
                         BRAIN_OUT_COMPLETE, 0.0f, now, plan, PLAN_N - ahead, why, sizeof why);
    if (!got) return ahead ? 0 : autoplay_add(a, now);
    memcpy(a->why_auto, why, sizeof why);
    for (int i = 0; i < got; i++) q_add(a, plan[i], 0, QS_AUTO);
    a->auto_idx = plan[got - 1];
    return got;
}

/* keep the radio laid out ahead, so the player can buffer the next song gaplessly */
static void autoplay_extend(app *a, double now)
{
    if (a->autoplay_on) autoplay_fill(a, now);
}

/* after songs come out of the queue: if that left nothing after this one, autoplay fills in */
static void q_topup(app *a) { autoplay_extend(a, (double)plat_now()); }

/* Engine v3: the pick queued behind this song assumed you'd let it play. An early skip
 * (or a dislike) asks again with that verdict -- the web player's skip anchor: continue
 * from the last song you kept, steer away from this one -- and plays the new pick instead.
 * Returns 1 when it handled the skip. */
static int redecide_on_skip(app *a, int outcome)
{
    if (!a->cur_valid || a->qpos + 1 != a->qn - 1 || a->qsrc[a->qpos + 1] != QS_AUTO ||
        brain_engine() != 3)                       /* the radio keeps its queue (autoplay_fill) */
        return 0;
    uint32_t len = a->ps.length_ms, el = a->ps.elapsed_ms;
    int early = outcome == BRAIN_OUT_DISLIKE || (len ? (uint64_t)el * 100 < (uint64_t)len * 15 : el < 10000);
    if (!early) return 0;
    char why[160];
    uint32_t pick = brain_next(a->cur, a->session, a->n_session - 1, outcome, el / 1000.0f,
                               (double)plat_now(), why, sizeof why, a->genre_of, a->fence);
    if (pick == LIB_NONE || pick == a->q[a->qpos + 1] || pick == a->cur) return 0;
    a->q[a->qpos + 1] = pick;
    a->auto_idx = pick;
    memcpy(a->why_auto, why, sizeof why);
    a->outcome = OUT_SKIP;
    a->outcome_ms = a->now_ms;
    plat_play_tracks(a->q, a->qn, a->qpos + 1, 0);       /* this is the skip */
    return 1;
}

static void settle_outgoing(app *a, double now)
{
    if (!a->cur_valid) return;
    float done = a->last_len ? (float)a->last_elapsed / a->last_len : -1.0f;
    int recent = a->now_ms - a->outcome_ms < SKIP_INTENT_MS;
    int ev = a->outcome == OUT_SWITCH && recent ? EV_SWITCH :
             a->outcome == OUT_SKIP && recent ? EV_SKIP :
             done >= 0.8f || (a->last_len && a->last_len - a->last_elapsed < 4000) ? EV_COMPLETE : EV_SKIP;
    brain_log(a->cur, ev, a->last_elapsed / 1000.0f, now);
    a->outcome = OUT_NONE;
}

static void autoplay_tick(app *a)
{
    plat_player(&a->ps);
    if (a->peeking) return;                        /* the preview isn't listening */
    if (a->ps.active && a->ps.idx == a->peek_idx && a->now_ms < a->peek_ignore_until) return;
    double now = (double)plat_now();
    /* same song again at another queue position counts as a change too, but only when
     * the player's position agrees with our queue (else we'd re-trigger every tick) */
    int pos_moved = a->ps.pos >= 0 && a->ps.pos < a->qn && a->ps.pos != a->qpos &&
                    a->q[a->ps.pos] == a->ps.idx;
    if (a->ps.active && (!a->cur_valid || a->ps.idx != a->cur || pos_moved)) {
        settle_outgoing(a, now);
        /* where in our queue are we? */
        int at = -1;
        if (a->ps.pos >= 0 && a->ps.pos < a->qn && a->q[a->ps.pos] == a->ps.idx) at = a->ps.pos;
        for (int d = 1; at < 0 && d < a->qn; d++) {
            if (a->qpos + d < a->qn && a->q[a->qpos + d] == a->ps.idx) at = a->qpos + d;
            else if (a->qpos - d >= 0 && a->q[a->qpos - d] == a->ps.idx) at = a->qpos - d;
        }
        if (at < 0) { a->q[0] = a->ps.idx; a->qsrc[0] = QS_USER; a->qn = 1; at = 0; }
        a->qpos = at;
        int auto_pick = a->qsrc[at] == QS_AUTO;
        memcpy(a->why, auto_pick ? a->why_auto : "", sizeof a->why);
        plat_log("track %u (q %d/%d, auto %d) why='%s'", (unsigned)a->ps.idx, at + 1, a->qn,
                 auto_pick, a->why);
        a->cur = a->ps.idx;
        a->cur_valid = 1;
        if (a->pick_on && a->cur != a->pick_song) a->pick_on = 0;   /* left before it counted */
        if (a->qsrc[at] != QS_AUTO) brain_radio_seed(a->cur);   /* you chose it: autoplay goes on from it */
        brain_log(a->cur, EV_PLAY, 0, now);
        if (a->n_session == SESSION_MAX) {
            memmove(a->session, a->session + 1, (SESSION_MAX - 1) * sizeof a->session[0]);
            a->n_session--;
        }
        a->session[a->n_session++] = a->cur;
        autoplay_extend(a, now);
        a->qsave_dirty = 1;
    }
    if (a->pick_on && a->cur_valid && a->ps.active && a->cur == a->pick_song &&
        a->ps.elapsed_ms >= PICK_KEEP_MS) {
        brain_wheel_pick(a->pick_item, now);
        a->pick_on = 0;
    }
    if (a->ps.active) { a->last_elapsed = a->ps.elapsed_ms; a->last_len = a->ps.length_ms; }
}

/* ------------------------------------------------------------------ the playback watchdog
 * Once on the H2 a song stuttered and stopped while the player went on saying "playing";
 * other songs didn't play either, reconnecting the earbuds didn't help, a restart did. So:
 * playing, and the song's clock stands still for STALL_MS -> say what the audio path looks
 * like (coda.log, for the next look) and rescue it. First the queue again from where it
 * was; still stuck, the platform's stronger medicine: the wireless audio restarted, then
 * the player restarted (it comes back paused, the queue kept). */
static void stall_watch(app *a)
{
    const plat_play *ps = &a->ps;
    int quiet = !ps->active || !ps->playing || a->peeking ||
                (a->seek_ms && a->now_ms - a->seek_ms < 3000);
    if (quiet || ps->elapsed_ms != a->stall_el || ps->idx != a->stall_idx) {
        if (!quiet && a->stall_stage) {
            plat_log("os: playing again after rescue %d", a->stall_stage);
            a->stall_stage = 0;
        }
        a->stall_el = ps->elapsed_ms;
        a->stall_idx = ps->idx;
        a->stall_t0 = a->now_ms;
        return;
    }
    if (ps->length_ms && ps->elapsed_ms + 3000 > ps->length_ms) return;     /* the next song loading */
    if (a->now_ms - a->stall_t0 < (a->stall_stage ? STALL_MS + 6000 : STALL_MS)) return;
    char d[200];
    plat_play_diag(d, sizeof d);
    a->stall_stage++;
    a->stall_t0 = a->now_ms;
    plat_log("os: stuck %u ms into song %u, rescue %d: %s", (unsigned)ps->elapsed_ms, (unsigned)ps->idx,
             a->stall_stage, d);
    if (a->stall_stage == 1) {
        say(a, "Playback got stuck. Starting it again...");
        if (a->qn && a->qpos >= 0 && a->qpos < a->qn && a->q[a->qpos] == ps->idx)
            plat_play_tracks(a->q, a->qn, a->qpos, ps->elapsed_ms);
        else {
            uint32_t idx = ps->idx;
            plat_play_tracks(&idx, 1, 0, ps->elapsed_ms);
        }
    } else if (a->stall_stage == 2 && plat_audio_rescue(2)) {
        say(a, "Still stuck. Restarting Bluetooth...");
    } else {
        say(a, "Still stuck. Restarting the player...");
        q_save(a);
        plat_audio_rescue(3);
    }
}

/* ------------------------------------------------------------------ wheel peek */
static uint32_t hook_ms(app *a, uint32_t idx)
{
    uint32_t d = brain_duration(idx);
    return (d ? d : 90) * 350u;                   /* 35% in, the web's guess without analysis */
}

static void peek_start(app *a, uint32_t idx)
{
    if (!a->peeking) {
        a->peek_was_active = a->ps.active && a->cur_valid;
        a->peek_was_playing = a->ps.playing;
        a->peek_saved_ms = a->ps.elapsed_ms;
        a->peek_t0 = a->now_ms;
    }
    a->peeking = 1;
    a->peek_idx = idx;
    a->peek_this_t0 = a->now_ms;
    plat_play_tracks(&idx, 1, 0, hook_ms(a, idx));
    brain_log(idx, EV_PEEK, 0, (double)plat_now());
}

/* back to the song, where it would be now; play: 1 = playing whatever it was before */
static void peek_back(app *a, int play)
{
    if (!a->peeking) return;
    a->peeking = 0;
    a->peek_ignore_until = a->now_ms + 3000;
    if (!a->peek_was_active || !a->qn) { plat_stop(); a->cur_valid = 0; return; }
    uint32_t at = a->peek_saved_ms + (a->peek_was_playing ? a->now_ms - a->peek_t0 : 0);
    uint32_t len = (uint32_t)brain_duration(a->q[a->qpos]) * 1000u;
    int pos = a->qpos;
    if (len && at + 3000 > len) {                  /* it would have ended meanwhile */
        if (pos + 1 < a->qn) { pos++; at = 0; } else at = len > 3000 ? len - 3000 : 0;
    }
    plat_play_tracks(a->q, a->qn, pos, at);
    if (!a->peek_was_playing && !play) plat_toggle();
}

static void peek_stop(app *a) { peek_back(a, 0); }

/* ------------------------------------------------------------------ shared chrome */
/* on the charger: amber while it charges, green once it's full (every theme, like a phone) */
#define CHG_AMBER C565(0xf0, 0x8c, 0x1a)
#define CHG_FULL C565(0x3c, 0xa8, 0x4c)
static px16 charge_ink(int chg) { return chg == 1 ? CHG_AMBER : CHG_FULL; }

/* Battery, top right of every screen: the percentage in mono, then a flat cell drawn like
 * the rest of the poster -- ink outline, ink fill; amber while charging (green when full),
 * signal red when it is nearly empty. Returns the width it took (0 when the level is unknown). */
static int draw_battery_cell(app *a, gfx *g, int x_right, int y_base)
{
    const palette *p = P(a);
    int pct = plat_battery(), chg = plat_charging();
    if (pct < 0) return 0;
    if (pct > 100) pct = 100;
    const int w = 17, h = 8, x = x_right - 2 - w, y = y_base - h;
    px16 c = chg ? charge_ink(chg) : pct <= 15 ? p->red : p->ink;
    g_fill(g, x, y, w, 1, p->ink);                       /* the cell */
    g_fill(g, x, y + h - 1, w, 1, p->ink);
    g_fill(g, x, y, 1, h, p->ink);
    g_fill(g, x + w - 1, y, 1, h, p->ink);
    g_fill(g, x + w, y + 2, 2, h - 4, p->ink);           /* the terminal */
    int fill = (w - 4) * pct / 100;
    if (pct > 0 && fill < 1) fill = 1;
    g_fill(g, x + 2, y + 2, fill, h - 4, c);
    char s[8];
    snprintf(s, sizeof s, "%d%%", pct);
    int tw = text_w(F(a, F_MONO10), s, 0);
    txt(a, g, F_MONO10, x - 4 - tw, y_base, s, chg ? charge_ink(chg) : pct <= 15 ? p->red : p->sub, 0);
    if (chg == 1) {                                      /* a bolt over the cell */
        int bx = x + w / 2 - 1, by = y - 1;
        g_fill(g, bx + 1, by, 2, 3, p->paper);
        g_fill(g, bx, by + 3, 4, 2, p->paper);
        g_fill(g, bx - 1, by + 5, 2, 4, p->paper);
        g_fill(g, bx + 2, by + 1, 1, 2, CHG_AMBER);
        g_fill(g, bx + 1, by + 3, 2, 2, CHG_AMBER);
        g_fill(g, bx, by + 5, 1, 3, CHG_AMBER);
    }
    return w + 2 + 4 + tw;
}

static void line1(gfx *g, int x0, int y0, int x1, int y1, px16 c)
{
    int dx = abs(x1 - x0), dy = -abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    for (int err = dx + dy;;) {
        g_fill(g, x0, y0, 1, 1, c);
        if (x0 == x1 && y0 == y1) break;
        int e2 = 2 * err;
        if (e2 >= dy) { err += dy; x0 += sx; }
        if (e2 <= dx) { err += dx; y0 += sy; }
    }
}

/* the Bluetooth rune, 7 x 11, bottom-left at (x, y_base) */
static void bt_mark(gfx *g, int x, int y_base, px16 c)
{
    static const int8_t pt[6][2] = { { 0, 3 }, { 6, 7 }, { 3, 10 }, { 3, 0 }, { 6, 3 }, { 0, 7 } };
    int y = y_base - 10;
    for (int i = 0; i < 5; i++) line1(g, x + pt[i][0], y + pt[i][1], x + pt[i + 1][0], y + pt[i + 1][1], c);
}

/* the earbuds' battery while they're connected and tell it: the emptier one (that's the
 * one that decides how long they last), -1 when they don't say */
static int buds_level(const app *a)
{
    const plat_bt *b = &a->bt;
    if (!a->bt_has || b->radio != BTR_ON || b->link < BTL_CONNECTED) return -1;
    if (b->batt_l >= 0 && b->batt_r >= 0) return b->batt_l < b->batt_r ? b->batt_l : b->batt_r;
    return b->batt_l >= 0 ? b->batt_l : b->batt_r;
}

/* the battery, and left of it the Bluetooth rune while headphones are connected (Klein
 * blue), with the earbuds' own battery beside it when they tell it. Returns the width taken. */
static int draw_battery(app *a, gfx *g, int x_right, int y_base)
{
    int w = draw_battery_cell(a, g, x_right, y_base);
    if (a->bt_has && a->bt.radio == BTR_ON && a->bt.link >= BTL_CONNECTED) {
        int buds = buds_level(a), tw = 0;
        char s[8] = "";
        if (buds >= 0) {
            snprintf(s, sizeof s, "%d%%", buds);
            tw = text_w(F(a, F_MONO10), s, 0) + 3;
        }
        int x = x_right - w - (w ? 8 : 0) - tw - 7;
        bt_mark(g, x, y_base + 1, P(a)->blue);
        if (s[0]) txt(a, g, F_MONO10, x + 10, y_base, s, buds <= 15 ? P(a)->red : P(a)->blue, 0);
        w += 7 + tw + (w ? 8 : 0);
    }
    return w;
}

static void draw_status(app *a, gfx *g, int x_right, int y)
{
    char s[16];
    int h, m;
    plat_clock(&h, &m);
    snprintf(s, sizeof s, "%02d:%02d", h, m);
    int bw = draw_battery(a, g, x_right, y);
    txt_right(a, g, F_MONO10, x_right - (bw ? bw + 8 : 0), y, s, P(a)->sub);
}

/* ------------------------------------------------------------------ themes
 * A theme draws the shared pieces -- the page, its header, list rows and the cursor over
 * them, action buttons, the now bar, the home screen, Library's and Settings' panels,
 * Explore's shelves, Search's keys, the sheet -- while the views keep their layout and
 * data. The themes are th_*.h (Settings > Theme); "Sakurai" (th_poster.h) is the default.
 * Every section has an id, so a theme can give it a colour and a symbol. */
enum { SEC_WHEEL, SEC_NOW, SEC_QUEUE, SEC_EXPLORE, SEC_SEARCH, SEC_LIBRARY, SEC_LIKED, SEC_SETTINGS,
       SEC_SONGS, SEC_ARTISTS, SEC_GENRES, SEC_OSTS, SEC_HISTORY, SEC_BT, SEC_CLOCK,
       SEC_SLEEP, SEC_SOUND, SEC_SCREEN, SEC_THEME, SEC_WHEELSET, SEC_PLAYBACK,
       SEC_GAMES, SEC_ORBIT, SEC_FISH, SEC_COUNT };
enum { ROW_FOCUS = 1, ROW_LIVE = 2, ROW_DIM = 4, ROW_ADJ = 8 };
typedef struct { px16 fg, sub, note, accent; int on; } row_ink;   /* on: it sits on the cursor / live mark */
/* a panel of a mosaic (Library, Settings): unskewed cell, section, size 2 big / 1 mid / 0 small */
typedef struct { int sec; float x0, y0, x1, y1; int size; const char *label, *value; } mtile;

/* Settings in groups, each a panel */
enum { G_SLEEP, G_SOUND, G_SCREEN, G_THEME, G_WHEEL, G_PLAYBACK, G_BT, G_CLOCK, G_COUNT };
static const int G_SEC[G_COUNT] = { SEC_SLEEP, SEC_SOUND, SEC_SCREEN, SEC_THEME, SEC_WHEELSET, SEC_PLAYBACK,
                                    SEC_BT, SEC_CLOCK };
static const char *const G_NAME[G_COUNT] = { "Sleep", "Sound", "Screen", "Theme", "Wheel", "Playback",
                                             "Bluetooth", "Clock" };

static int view_sec(app *a);
static float cursor_y(app *a, int target);
static int menu_item_at(const app *a, int pos);
static void draw_nowbar(app *a, gfx *g);

/* the now bar of the poster themes: an ink strip, the cover, red progress */
static void nowbar_poster(app *a, gfx *g)
{
    const palette *p = P(a);
    const int y0 = BAR_Y, h = LCD_H - BAR_Y;
    g_fill(g, 0, y0, LCD_W, h, p->strip_bg);
    if (a->notice[0]) {
        txt_fit(a, g, F_BOLD11, 8, y0 + 18, a->notice, LCD_W - 16, p->strip_fg, 0);
        return;
    }
    if (a->peeking) {
        const lib_track *t = lib_get(a->L, a->peek_idx);
        g_fill(g, 8, y0 + 10, 5, 5, p->red);
        txt(a, g, F_MONO10, 17, y0 + 16, "peeking", p->strip_sub, 0);
        if (t) txt_fit(a, g, F_BOLD11, 70, y0 + 16, t->title, LCD_W - 78, p->strip_fg, 0);
        return;
    }
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

/* scrolled list frame: keeps sel visible */
static void list_follow(list_state *l, int visible)
{
    if (l->n <= 0) { l->sel = 0; l->top = 0; return; }
    l->sel = fx_clamp(l->sel, 0, l->n - 1);
    float want = l->top;
    if (l->sel < (int)ceilf(l->top)) want = (float)l->sel;
    if (l->sel > (int)floorf(l->top) + visible - 1) want = (float)(l->sel - visible + 1);
    if (want > l->n - visible) want = (float)(l->n - visible);
    if (want < 0) want = 0;
    l->top = want;
}

float app_daylight(float hour, float *across);   /* the sun (below): Diorama's window */
#include "th_poster.h"
/* what each menu item is, in a line (themes that say it) */
static const char *const MENU_DESC[N_MENU] = {
    "Spin through your songs, covers on a wheel.", "What's on, and what comes next.",
    "What plays next, and what Coda adds after it.", "Fresh finds and shelves picked from your taste.",
    "Spell a song or an artist with the wheel.", "Songs, artists, genres, soundtracks, history, games.",
    "Every song you held Play on.", "Sleep, sound, screen, theme, Bluetooth, clock." };

/* Diorama's home carries your Bluetooth devices too: cards pinned on a board on the wall
 * left of the monitor, where there was room (the user, 2026-10-19), next after the posters
 * on the wheel's way round. Item N_MENU + k is card k, from the top: Play connects it (or
 * lets go of it), hold Play opens Bluetooth. */
#define RACK_MAX 3
enum { RK_IDLE, RK_OFF, RK_CONNECTING, RK_ON, RK_PLAYING, RK_PAIR };
static int rack_n(const app *a)
{
    if (a->skin != 7 || !a->bt_has) return 0;
    int n = 0;
    for (int i = 0; i < a->bt_ndev; i++) n += a->bt_dev[i].paired != 0;
    return n > RACK_MAX ? RACK_MAX : n ? n : 1;          /* none yet: one card, to pair some */
}

/* card k's device (in bt_dev), -1 = the card to pair one */
static int rack_dev(const app *a, int k)
{
    for (int i = 0, j = 0; i < a->bt_ndev; i++)
        if (a->bt_dev[i].paired && j++ == k) return i;
    return -1;
}

static int rack_state(const app *a, int k)
{
    int d = rack_dev(a, k);
    if (d < 0) return RK_PAIR;
    if (a->bt.radio != BTR_ON) return RK_OFF;
    if (a->bt.link == BTL_NONE || memcmp(a->bt_dev[d].addr, a->bt.peer_addr, 6)) return RK_IDLE;
    return a->bt.link == BTL_CONNECTING ? RK_CONNECTING : a->bt.link == BTL_STREAMING ? RK_PLAYING : RK_ON;
}

/* short enough for a card: "HASAN's Buds3 Pro" -> "Buds3 Pro", "CAR MULTIMEDIA" -> "Car Multimedia" */
static void rack_name(const app *a, int k, char *out, size_t n)
{
    int d = rack_dev(a, k);
    const char *s = d < 0 ? "Pair some" : a->bt_dev[d].name, *ap = strstr(s, "'s ");
    if (ap && ap - s < 16 && strlen(ap + 3) >= 3) s = ap + 3;
    snprintf(out, n, "%s", s);
    int lower = 0;
    for (char *c = out; *c; c++) lower |= *c >= 'a' && *c <= 'z';
    for (char *c = out; !lower && *c; c++)
        if (*c >= 'A' && *c <= 'Z' && c > out && c[-1] != ' ') *c = (char)(*c - 'A' + 'a');
}

/* what Play does on card k (the picked card's tag) */
static const char *rack_verb(const app *a, int k)
{
    switch (rack_state(a, k)) {
    case RK_PAIR: return "Bluetooth";
    case RK_OFF: return "Turn on, connect";
    case RK_CONNECTING: return "Cancel";
    case RK_ON: case RK_PLAYING: return "Disconnect";
    default: return "Connect";
    }
}

/* the line under the desk */
static void rack_desc(const app *a, int k, char *out, size_t n)
{
    char nm[48];
    rack_name(a, k, nm, sizeof nm);
    switch (rack_state(a, k)) {
    case RK_PAIR: snprintf(out, n, "No headphones yet: Play, then search for some."); break;
    case RK_OFF: snprintf(out, n, "Bluetooth is off. Play: on, then %s.", nm); break;
    case RK_CONNECTING: snprintf(out, n, "Connecting to %s\xE2\x80\xA6", nm); break;
    case RK_PLAYING: snprintf(out, n, "Playing through %s.", nm); break;
    case RK_ON: snprintf(out, n, "Connected to %s.", nm); break;
    default: snprintf(out, n, "Play: connect %s. Hold: Bluetooth.", nm); break;
    }
}
#include "th_pixel.h"
#include "th_room.h"
#include "posters.h"
#include "th_dio.h"
#include "th_dio_close.h"
#include "th_dio_in.h"
#include "th_jtd.h"
#include "th_crd.h"
#include "th_anim.h"
#include "games.h"

typedef struct {
    const char *name;
    void (*page)(app *, gfx *);
    void (*header)(app *, gfx *, int sec, const char *title, const char *right);
    row_ink (*row)(app *, gfx *, int y, int h, int state);
    void (*label)(app *, gfx *, int x, int yb, const char *s, px16 c, int big, int maxw);
    void (*button)(app *, gfx *, int x, int y, int w, int h, int sym, const char *label, int foc, int kind);
    void (*nowbar)(app *, gfx *);
    void (*home)(app *, gfx *);
    int (*now)(app *, gfx *);                   /* its own Now playing (1), or the shared one (0 / NULL) */
    void (*mosaic)(app *, gfx *, const mtile *t, int n, int sel);
    void (*shelf)(app *, gfx *, int y, int h, const char *name, const char *sub, const char *count,
                  const uint32_t *items, int n, int foc);
    void (*key)(app *, gfx *, int x, int y, int w, int h, const char *label, int special, int foc, int dist);
    void (*sheet)(app *, gfx *, const char *const *items, const int *syms, int n, int sel);
    const uint8_t *order;                       /* the home's scroll order: position -> menu item */
    const palette *(*pal)(app *);               /* colours for the shared screens (NULL = day / night) */
} skin;

static const skin SKINS[] = {
    { "Sakurai", poster_page, poster_header, poster_row, poster_label, poster_button, nowbar_poster,
      poster_home, poster_now, poster_mosaic, poster_shelf, poster_key, poster_sheet, PA_ORDER, NULL },
    { "Room", px_page, px_header, px_row, px_label, px_button, px_nowbar,
      room_home, room_now, px_mosaic, px_shelf, px_key, px_sheet, PA_ORDER, px_pal },
    { "Jukebox", jb_page, jb_header, jb_row, px_label, px_button, jb_nowbar,
      jb_home, NULL, px_mosaic, px_shelf, px_key, px_sheet, NULL, jb_pal },
    { "Toybox", tb_page, tb_header, tb_row, px_label, px_button, tb_nowbar,
      tb_home, NULL, px_mosaic, px_shelf, px_key, px_sheet, NULL, tb_pal },
    { "Deck", dk_page, dk_header, dk_row, px_label, px_button, dk_nowbar,
      dk_home, NULL, px_mosaic, px_shelf, px_key, px_sheet, NULL, dk_pal },
    { "Crate", cr_page, px_header, cr_row, px_label, px_button, px_nowbar,
      cr_home, NULL, px_mosaic, px_shelf, px_key, px_sheet, NULL, cr_pal },
    { "Receiver", rx_page, rx_header, rx_row, px_label, px_button, rx_nowbar,
      rx_home, rx_now, px_mosaic, px_shelf, px_key, px_sheet, NULL, rx_pal },
    { "Diorama", dio_page, dio_header, dio_row, dio_label, dio_button, px_nowbar,
      dio_home, dio_now, dio_mosaic, dio_prints, dio_key, px_sheet, DIO_ORDER, px_pal },
};
#define N_SKINS ((int)(sizeof SKINS / sizeof SKINS[0]))

static const skin *SK(const app *a) { return &SKINS[a->skin >= 0 && a->skin < N_SKINS ? a->skin : 0]; }
void app_set_skin(app *a, int skin)
{
    a->skin = skin >= 0 && skin < N_SKINS ? skin : 0;
    a->force_full = 1;
    if (a->ls[V_MENU].sel >= N_MENU) a->ls[V_MENU].sel = 0;   /* off Diorama's board */
    a->ls[V_MENU].n = N_MENU + rack_n(a);
}

static void draw_header(app *a, gfx *g, const char *title, const char *right)
{
    SK(a)->header(a, g, view_sec(a), title, right);
}

static void draw_nowbar(app *a, gfx *g) { SK(a)->nowbar(a, g); }

/* ------------------------------------------------------------------ the sun
 * Sunrise and sunset for today, in wall-clock minutes, so "auto" goes dark at dusk the way
 * the window does: earlier in winter, later in summer. NOAA's short solar formulas. Where:
 * settings.txt "sun=<lat>,<lon>" in hundredths of a degree (west negative); New York by
 * default (the card is filled from a PC on US Eastern time). The H2's clock is wall time,
 * so the offset from UTC is Eastern's, with US daylight saving. */
static int sun_lat100 = 4071, sun_lon100 = -7401, sun_utc = -5;
static void civil(int64_t days, int *y, int *m, int *d)
{
    int64_t z = days + 719468, era = (z >= 0 ? z : z - 146096) / 146097;
    int64_t doe = z - era * 146097, yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100), mp = (5 * doy + 2) / 153;
    *d = (int)(doy - (153 * mp + 2) / 5 + 1);
    *m = (int)(mp < 10 ? mp + 3 : mp - 9);
    *y = (int)(yoe + era * 400 + (*m <= 2));
}

static int weekday(int64_t days) { return (int)(((days % 7) + 11) % 7); }   /* 0 = Sunday */

/* US daylight saving: from the second Sunday of March to the first Sunday of November */
static int us_dst(int64_t days, int y, int m, int d)
{
    if (m < 3 || m > 11) return 0;
    if (m > 3 && m < 11) return 1;
    int dow1 = weekday(days - (d - 1));                       /* the 1st of this month */
    int first_sun = 1 + (7 - dow1) % 7;
    (void)y;
    return m == 3 ? d >= first_sun + 7 : d < first_sun;
}

static double acos_(double x)
{
    if (x <= -1) return 3.14159265358979;
    if (x >= 1) return 0;
    return 2 * atan(sqrt((1 - x) / (1 + x)));
}

static void sun_times(int *rise, int *set)
{
    static int64_t day_done = -1;
    static int r = 6 * 60 + 30, s = 19 * 60;
    int64_t days = plat_now() / 86400;
    if (days != day_done && days > 20000) {                   /* once a day; not on an unset clock */
        day_done = days;
        int y, mo, d;
        civil(days, &y, &mo, &d);
        int64_t jan1 = days - (d - 1);
        for (int k = 1; k < mo; k++) {                        /* back to January the 1st */
            static const int ml[12] = { 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
            jan1 -= ml[k - 1] + (k == 2 && ((y % 4 == 0 && y % 100) || y % 400 == 0));
        }
        double doy = (double)(days - jan1), pi = 3.14159265358979, rad = pi / 180;
        double gm = 2 * pi / 365 * (doy - 1);
        double eqt = 229.18 * (0.000075 + 0.001868 * cos(gm) - 0.032077 * sin(gm) -
                               0.014615 * cos(2 * gm) - 0.040849 * sin(2 * gm));
        double decl = 0.006918 - 0.399912 * cos(gm) + 0.070257 * sin(gm) - 0.006758 * cos(2 * gm) +
                      0.000907 * sin(2 * gm) - 0.002697 * cos(3 * gm) + 0.00148 * sin(3 * gm);
        double lat = sun_lat100 / 100.0 * rad, lon = sun_lon100 / 100.0;
        double c = cos(90.833 * rad) / (cos(lat) * cos(decl)) - sin(lat) / cos(lat) * sin(decl) / cos(decl);
        double ha = acos_(c) / rad;
        int off = (sun_utc + us_dst(days, y, mo, d)) * 60;
        r = (int)(720 - 4 * (lon + ha) - eqt) + off;
        s = (int)(720 - 4 * (lon - ha) - eqt) + off;
    }
    *rise = r;
    *set = s;
}

/* Room's and Diorama's night, 0..256: day / night, or by the sun (-1): night from 40 min
 * after sunset to 40 before sunrise, dusk and dawn the hour around each */
static int night_of(int mode)
{
    if (mode >= 0) return mode ? 256 : 0;
    int h, m, rise, set;
    plat_clock(&h, &m);
    sun_times(&rise, &set);
    int t = h * 60 + m;
    if (t >= set + 40 || t < rise - 40) return 256;
    if (t >= set - 20) return (t - (set - 20)) * 256 / 60;
    if (t < rise + 20) return 256 - (t - (rise - 40)) * 256 / 60;
    return 0;
}

/* the poster themes' "auto": dark once the sun is down */
static int dark_now(void)
{
    int h, m, rise, set;
    plat_clock(&h, &m);
    sun_times(&rise, &set);
    int t = h * 60 + m;
    return t >= set + 20 || t < rise;
}

/* daylight, 0..1, and how far the sun is across its day (Diorama's patch of sun on the wall) */
float app_daylight(float hour, float *across)
{
    int rise, set;
    sun_times(&rise, &set);
    float t = hour * 60, d = t < rise - 30 ? 0 : t < rise + 30 ? (t - (rise - 30)) / 60 :
                            t < set - 30 ? 1 : t < set + 30 ? ((set + 30) - t) / 60 : 0;
    if (across) *across = (t - rise) / (float)(set - rise > 60 ? set - rise : 60);
    return d;
}
static int has_night(int skin) { return skin == 1 || skin == 7; }

/* the theme saved in /.coda/settings.txt: the power-on animation plays before the app loads.
 * -1 when the file can't be read -- on the H2 the first boot frame is drawn before the card
 * is mounted, so the caller must not take that for "Sakurai" and keep it */
static int saved_theme;
int app_saved_skin(void)
{
    char buf[256];
    int fd = plat_open("settings.txt");
    if (fd < 0) return -1;
    int r = plat_pread(fd, buf, sizeof buf - 1, 0);
    plat_close(fd);
    if (r <= 0) return -1;
    buf[r] = 0;
    const char *p = strstr(buf, "skin="), *q = strstr(buf, "theme=");
    int sk = p ? atoi(p + 5) : 0;
    saved_theme = q ? atoi(q + 6) : 0;
    return sk >= 0 && sk < N_SKINS ? sk : 0;
}

void app_boot_draw(int skin, gfx *g, uint32_t t)
{
    if (skin < 0 || skin >= (int)(sizeof BOOTS / sizeof BOOTS[0])) skin = 0;
    rp_night(has_night(skin) ? night_of(saved_theme) : 0);
    g_noclip(g);
    BOOTS[skin](g, t);
}

/* the home's focus -> which menu item */
static int menu_item_at(const app *a, int pos)
{
    int nr = rack_n(a);
    pos = fx_clamp(pos, 0, N_MENU + nr - 1);
    if (pos >= N_MENU) return N_MENU + nr - 1 - (pos - N_MENU);   /* Diorama's board, the bottom card first */
    return SK(a)->order ? SK(a)->order[pos] : pos;
}

int app_menu_item(app *a) { return menu_item_at(a, a->ls[V_MENU].sel); }
int app_skin(const app *a) { return a->skin; }

static int view_sec(app *a)
{
    switch (a->view) {
    case V_MENU: case V_WHEEL: return SEC_WHEEL;
    case V_NOW: return SEC_NOW;
    case V_QUEUE: case V_SAVED: return SEC_QUEUE;
    case V_EXPLORE: return SEC_EXPLORE;
    case V_SEARCH: return SEC_SEARCH;
    case V_LIBRARY: return SEC_LIBRARY;
    case V_ARTISTS: return SEC_ARTISTS;
    case V_GENRES: return SEC_GENRES;
    case V_OST: return SEC_OSTS;
    case V_BT: return SEC_BT;
    case V_CLOCK: return SEC_CLOCK;
    case V_GAMES: return SEC_GAMES;
    case V_GAME: return game_sec();
    case V_SETTINGS: return a->set_group >= 0 && a->set_group < G_COUNT ? G_SEC[a->set_group] : SEC_SETTINGS;
    case V_KEYS: return SEC_SETTINGS;
    case V_TRACKS:
        switch (a->tracks_kind) {
        case TK_ARTIST: return SEC_ARTISTS;
        case TK_SONGS: return SEC_SONGS;
        case TK_LIKED: return SEC_LIKED;
        case TK_HISTORY: return SEC_HISTORY;
        case TK_RESULTS: return SEC_SEARCH;
        case TK_SHELF: return SEC_EXPLORE;
        case TK_OST: return SEC_OSTS;
        case TK_GENRE: return SEC_GENRES;
        case TK_SAVED: return SEC_QUEUE;
        default: return SEC_LIBRARY;
        }
    default: return SEC_SETTINGS;
    }
}

/* the list cursor slides to the focus, with a hair of overshoot */
static float cursor_y(app *a, int target)
{
    if (a->cur_view != a->view) {
        a->cur_view = a->view;
        a->cur_y = a->cur_from = (float)target;
        a->cur_target = target;
        a->cur_t0 = 0;
    }
    if (target != a->cur_target) {
        a->cur_from = a->cur_y;
        a->cur_target = target;
        a->cur_t0 = a->now_ms ? a->now_ms : 1;
    }
    float u = a->cur_t0 ? (float)(a->now_ms - a->cur_t0) / 160.0f : 1.0f;
    a->cur_y = u >= 1 ? (float)target : a->cur_from + (target - a->cur_from) * ez_back(u, 2.2f);
    return a->cur_y;
}

/* one track row: [its number,] the cover, title, artist, a right-hand note (the duration
 * unless given) */
static void track_row(app *a, gfx *g, int y, uint32_t idx, int foc, int live, int dim,
                      const char *note, px16 note_c, int num)
{
    const palette *p = P(a);
    row_ink k = SK(a)->row(a, g, y, ROW_H, (foc ? ROW_FOCUS : 0) | (live ? ROW_LIVE : 0) | (dim ? ROW_DIM : 0));
    int cx = 12;
    if (num) {
        char ns[8];
        snprintf(ns, sizeof ns, "%02d", num);
        txt(a, g, F_POSTER15, 10, y + 21, ns, k.on ? k.fg : dim ? p->rule : p->ink, T_TRACK(-6));
        cx = 38;
    }
    cover(a, g, idx, ART_S, cx, y + 1, ROW_H - 2);
    const lib_track *t = lib_get(a->L, idx);
    if (!t) return;
    char d[16];
    if (!note) { mmss(d, sizeof d, t->dur); note = d; note_c = k.sub; }
    int dw = text_w(F(a, F_MONO10), note, 0), tx = cx + ROW_H + 6;
    txt_fit(a, g, F_BOLD11, tx, y + 13, t->title, LCD_W - tx - 18 - dw, k.fg, 0);
    txt_fit(a, g, F_BODY10, tx, y + 25, t->artist, LCD_W - tx - 24 - dw, k.sub, 0);
    txt_right(a, g, F_MONO10, LCD_W - 12, y + 13, note, k.on ? k.note : note_c);
}

/* an action in a list ("Search for headphones"): a button the width of the row */
static void action_row(app *a, gfx *g, int y, const char *label, int sym, int foc)
{
    SK(a)->button(a, g, 4, y + 2, LCD_W - 12, ROW_H - 4, sym, label, foc, 1);
}

/* ------------------------------------------------------------------ views */
static void draw_menu(app *a, gfx *g)
{
    a->ls[V_MENU].n = N_MENU;
    SK(a)->home(a, g);
}

/* a Wheel item's song: itself, or a list's first (its cover, its preview) */
static uint32_t pool_song(app *a, int i)
{
    return i >= 0 && i < a->n_pool ? brain_wheel_song(a->pool[i]) : LIB_NONE;
}

/* a Wheel item's two lines: a song's title and artist, a list's name and kind */
static int pool_text(app *a, int i, const char **title, const char **artist)
{
    if (i < 0 || i >= a->n_pool) return 0;
    const char *kind = "";
    const char *name = brain_wheel_list_name(a->pool[i], &kind);
    if (name) { *title = name; *artist = kind && *kind ? kind : "List"; return 1; }
    const lib_track *t = lib_get(a->L, a->pool[i]);
    if (!t) return 0;
    *title = t->title;
    *artist = t->artist;
    return 1;
}

static void wheel_frame_fill(app *a, wheel_frame *f, int *focused)
{
    memset(f, 0, sizeof *f);
    int b0 = (int)lrintf(a->s);
    f->frac = a->s - b0;
    f->settled = fabsf(a->s - a->target) < 0.02f;
    int n = a->n_pool;
    /* a history, not a loop: newest first, nothing before the start or past the end */
    for (int dd = -5; dd <= 5; dd++) {
        int i = b0 + dd;
        if (i < 0 || i >= n) continue;
        f->show[dd + 5] = 1;
        f->tex[dd + 5] = tex_get(a, pool_song(a, i), ART_M);
    }
    *focused = n ? fx_clamp(b0, 0, n - 1) : -1;
    if (*focused >= 0) f->label = tex_get(a, pool_song(a, *focused), ART_M);
    uint32_t fidx = *focused >= 0 ? pool_song(a, *focused) : LIB_NONE;
    f->playing = fidx != LIB_NONE && ((a->cur_valid && fidx == a->cur && a->ps.playing) ||
                                      (a->peeking && fidx == a->peek_idx));
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
    int peeking_here = a->peeking && focused >= 0 && pool_song(a, focused) == a->peek_idx;
    const char *live = peeking_here ? "\xE2\x97\x8F peeking" : f.playing ? "\xE2\x97\x8F playing" : NULL;
    if (!a->layout_b) {
        wheel_draw(g, p, &WHEEL_A, &f);
        const int x0 = 214, x1 = 316, cy = 120, row = 40;
        int b0 = (int)lrintf(a->s);
        for (int dd = -2; dd <= 2 && a->n_pool; dd++) {
            if (dd == 0 || b0 + dd < 0 || b0 + dd >= a->n_pool) continue;
            const char *title, *artist;
            if (!pool_text(a, b0 + dd, &title, &artist)) continue;
            float dist = fabsf(dd - f.frac);
            int op = (int)(fmaxf(0.0f, 1.0f - dist / 2.8f) * 256);
            px16 c = mix565(p->paper, p->sub, op);
            int y = cy + (int)lrintf((dd - f.frac) * row);
            txt_fit(a, g, F_BOLD11, x0 + 4, y + 1, title, x1 - x0 - 4, c, 0);
            txt_fit(a, g, F_BODY10, x0 + 4, y + 13, artist, x1 - x0 - 4, c, 0);
        }
        if (focused >= 0) {
            const char *title, *artist;
            if (pool_text(a, focused, &title, &artist)) {
                char up[TEXT_LINE_MAX * 2], lines[2][TEXT_LINE_MAX];
                utf8_upper(title, up, sizeof up);
                int nl = text_wrap(F(a, F_POSTER15), up, x1 - x0 - 10, 2, T_TRACK(-4), lines);
                int y = cy - (nl - 1) * 7 + 5 - (int)lrintf(f.frac * row);
                for (int i = 0; i < nl; i++)
                    txt(a, g, F_POSTER15, x0 + 10, y + i * 14, lines[i], p->ink, T_TRACK(-4));
                txt_fit(a, g, F_SEMI11, x0 + 10, y + (nl - 1) * 14 + 13, artist, x1 - x0 - 10, p->blue, 0);
            }
        }
        draw_status(a, g, 316, 12);
        if (live) txt(a, g, F_MONO10, 216, 233, live, p->red, 0);
        txt_right(a, g, F_MONO10, 316, 233, pos, p->sub);
    } else {
        wheel_draw(g, p, &WHEEL_B, &f);
        if (focused >= 0) {
            const char *title, *artist;
            if (pool_text(a, focused, &title, &artist)) {
                char up[TEXT_LINE_MAX * 2];
                utf8_upper(title, up, sizeof up);
                txt_center(a, g, F_POSTER18, 160, 24, up, 236, p->ink, T_TRACK(-5));
                txt_center(a, g, F_SEMI12, 160, 41, artist, 236, p->blue, 0);
            }
        }
        draw_status(a, g, 316, 12);
        txt(a, g, F_MONO10, 4, 12, pos, p->sub, 0);
        if (live) txt(a, g, F_MONO10, 4, 233, live, p->red, 0);
    }
}

static void draw_now(app *a, gfx *g)
{
    if (SK(a)->now && SK(a)->now(a, g)) return;           /* the theme's own */
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
    if (a->ps.playing) g_fill(g, x0, 10, 7, 7, p->red);
    draw_battery(a, g, x1, 17);
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
    int seeking = a->seek_ms && a->now_ms - a->seek_ms < 1500;
    uint32_t shown = seeking ? a->seek_to : a->ps.elapsed_ms;
    mmss(e, sizeof e, shown / 1000);
    mmss(tot, sizeof tot, (a->ps.length_ms ? a->ps.length_ms / 1000 : (t ? t->dur : 0)));
    if (seeking && a->ps.length_ms)
        g_fill(g, 0, y0, (int)((uint64_t)LCD_W * shown / a->ps.length_ms), 2, p->red);
    txt(a, g, F_MONO12, 8, y0 + 18, e, seeking ? p->red : p->strip_fg, 0);
    txt_right(a, g, F_MONO12, LCD_W - 8, y0 + 18, tot, p->strip_sub);
    if (a->notice[0]) {
        txt_fit(a, g, F_BOLD11, 52, y0 + 18, a->notice, 200, p->strip_fg, 0);
    }
    uint32_t nx = a->qpos + 1 < a->qn ? a->q[a->qpos + 1] : LIB_NONE;
    if (nx != LIB_NONE) {
        const lib_track *n = lib_get(a->L, nx);
        int ny = y0 + 28;
        cover(a, g, nx, ART_S, 8, ny, 36);
        txt(a, g, F_MONO10, 52, ny + 11, a->qsrc[a->qpos + 1] == QS_AUTO ? "next, autoplay" : "next",
            p->strip_sub, 0);
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
    for (int i = (int)floorf(l->top); i < n && i < (int)floorf(l->top) + 8; i++) {
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        int foc = i == l->sel;
        row_ink k = SK(a)->row(a, g, y, ROW_H, foc ? ROW_FOCUS : 0);
        int cw = counts && counts[i] ? text_w(F(a, F_MONO10), counts[i], 0) : 0;
        SK(a)->label(a, g, 14, y + 24, names[i], k.fg, 1, LCD_W - 40 - cw);
        if (cw) txt_right(a, g, F_MONO10, LCD_W - 12, y + 21, counts[i], k.on ? k.note : p->sub);
    }
    g_noclip(g);
}

static void draw_library(app *a, gfx *g)
{
    char songs[24], artists[24], genres[24], osts[24];
    commas(songs, sizeof songs, lib_n(a->L));
    commas(artists, sizeof artists, lib_n_artists(a->L));
    commas(genres, sizeof genres, a->cr[CK_GENRE].n);
    commas(osts, sizeof osts, a->cr[CK_OST].n);
    char games[32];
    snprintf(games, sizeof games, "%s albums", osts);
    draw_header(a, g, "Library", NULL);
    list_state *l = &a->ls[V_LIBRARY];
    l->n = N_LIB;
    l->sel = fx_clamp(l->sel, 0, N_LIB - 1);
    const mtile t[N_LIB] = {
        { SEC_SONGS, -40, 35, 120, 211, 2, "Songs", songs },
        { SEC_ARTISTS, 125, 35, 350, 112, 2, "Artists", artists },
        { SEC_GENRES, 125, 117, 236, 164, 0, "Genres", genres },
        { SEC_OSTS, 241, 117, 350, 164, 0, "Soundtracks", games },
        { SEC_HISTORY, 125, 169, 236, 211, 0, "History", "newest first" },
        { SEC_GAMES, 241, 169, 350, 211, 0, "Games", "2 games" },
    };
    SK(a)->mosaic(a, g, t, N_LIB, l->sel);
}

/* Library > Games: the two games, each with its record */
static void draw_games(app *a, gfx *g)
{
    char orbit[32], fish[32];
    game_stats(orbit, sizeof orbit, fish, sizeof fish);
    draw_header(a, g, "Games", NULL);
    list_state *l = &a->ls[V_GAMES];
    l->n = GM_N;
    l->sel = fx_clamp(l->sel, 0, GM_N - 1);
    const mtile t[GM_N] = {
        { SEC_ORBIT, -40, 35, 150, 211, 2, "Beat Orbit", orbit },
        { SEC_FISH, 155, 35, 350, 211, 2, "Fishing Hole", fish },
    };
    SK(a)->mosaic(a, g, t, GM_N, l->sel);
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
        row_ink k = SK(a)->row(a, g, y, ROW_H, foc ? ROW_FOCUS : 0);
        cover(a, g, fi, ART_S, 12, y + 1, ROW_H - 2);
        char cs[16];
        snprintf(cs, sizeof cs, "%u", (unsigned)c);
        int cw = text_w(F(a, F_MONO10), cs, 0);
        if (t) SK(a)->label(a, g, 12 + ROW_H + 6, y + 20, t->artist, k.fg, 0, LCD_W - ROW_H - 46 - cw);
        txt_right(a, g, F_MONO10, LCD_W - 12, y + 20, cs, k.on ? k.note : p->sub);
    }
    g_noclip(g);
    draw_nowbar(a, g);
}

static const char *const action_labels[][2] = {
    [TK_ARTIST] = { "Play all", "Shuffle" },
    [TK_OST] = { "Play", "Shuffle" },
    [TK_GENRE] = { "Start station", "Shuffle all" },
    [TK_SHELF] = { "Play all", "Shuffle" },
    [TK_SAVED] = { "Play in order", "Shuffle" },
};
static const int action_syms[][2] = {
    [TK_ARTIST] = { SYM_NOW, SYM_SHUFFLE },
    [TK_OST] = { SYM_NOW, SYM_SHUFFLE },
    [TK_GENRE] = { SYM_STATION, SYM_SHUFFLE },
    [TK_SHELF] = { SYM_NOW, SYM_SHUFFLE },
    [TK_SAVED] = { SYM_NOW, SYM_SHUFFLE },
};

static void draw_tracks(app *a, gfx *g)
{
    const palette *p = P(a);
    list_state *l = &a->ls[V_TRACKS];
    l->n = a->n_tracks + a->n_actions;
    char cnt[24];
    commas(cnt, sizeof cnt, (uint32_t)a->n_tracks);
    if (a->tracks_kind == TK_GENRE) {
        char up[TEXT_LINE_MAX];
        utf8_upper(a->tracks_title, up, sizeof up);
        draw_header(a, g, up, cnt);
    } else draw_header(a, g, a->tracks_title, cnt);
    /* the actions share the first row, side by side; the songs scroll under them */
    int na = a->n_actions, strip = na ? 1 : 0;
    list_state v = { a->n_tracks + strip, l->sel < na ? 0 : l->sel - na + strip, l->top };
    list_follow(&v, 6);
    l->top = v.top;
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    if (a->n_tracks == 0)
        txt(a, g, F_BODY10, 12, LIST_Y + 22 + strip * ROW_H, a->tracks_kind == TK_LIKED ?
            "Nothing liked yet. Hold play on any song." : "Nothing here yet.", p->sub, 0);
    int first = (int)floorf(v.top);
    for (int r = first; r < first + 8 && r < v.n; r++) {
        int y = LIST_Y + (int)lrintf((r - v.top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        if (strip && r == 0) {
            int w = (LCD_W - 12) / na;
            for (int i = 0; i < na; i++)
                SK(a)->button(a, g, 4 + i * w, y + 3, w - 6, ROW_H - 5, action_syms[a->tracks_kind][i],
                              action_labels[a->tracks_kind][i], l->sel == i, i);
            continue;
        }
        int i = r - strip;
        uint32_t idx = track_at(a, i);
        track_row(a, g, y, idx, l->sel == i + na, a->cur_valid && idx == a->cur, 0, NULL, 0, 0);
    }
    g_noclip(g);
    draw_nowbar(a, g);
}

/* ---- Explore: three shelves, each a title over a filmstrip of what it holds.
 * The card's pools come taste-ranked from the PC (scripts/h2_crates.py, a few hundred
 * each); here, at every visit, what you've played or turned down since drops out -- fresh
 * finds stay unheard, deep cuts barely played -- so both move on as you listen. The strip
 * shows a dozen at random from the best of what's left; the list, all of it, best first. */
static void draw_shelves(app *a)
{
    if (a->shelves_drawn) return;                  /* once per visit, like the web's */
    a->shelves_drawn = 1;
    const crates *c = &a->cr[CK_EXPLORE];
    static uint32_t pool[SHELF_ALL], top[48];
    for (uint32_t s = 0; s < c->n && s < 3; s++) {
        int n = crate_members(c, s, 0, pool, SHELF_ALL), k = 0;
        for (int i = 0; i < n; i++) {
            int plays = brain_play_count(pool[i]);
            if (brain_disliked(pool[i])) continue;
            if (s == 0 && plays) continue;         /* fresh finds: still unheard */
            if (s == 1 && plays > 3) continue;     /* deep cuts: still barely played */
            pool[k++] = pool[i];
        }
        a->shelf_all_n[s] = k;
        memcpy(a->shelf_all[s], pool, sizeof(uint32_t) * (size_t)k);
        int nt = k < 48 ? k : 48;
        memcpy(top, pool, sizeof(uint32_t) * (size_t)nt);
        shuffle(top, nt);
        a->shelf_n[s] = nt < SHELF_N ? nt : SHELF_N;
        memcpy(a->shelf[s], top, sizeof(uint32_t) * (size_t)a->shelf_n[s]);
    }
}

/* Diorama: the two shelves are the two posters over the desk (the page under them is
 * dio_page's, posters and all): a tag with the shelf's name, three of its covers pinned on */
static void dio_explore(app *a, gfx *g, const crates *c, int sel)
{
    draw_header(a, g, "Explore", crate_str(c, c->tab[sel].sub));
    for (int s = 0; s < 2; s++) {
        int x0 = PO_X[s] * 2, y0 = PO_Y * 2, w = 144, h = 168, foc = s == sel;
        const crate *k = &c->tab[s];
        if (foc) {                                         /* the picked one: framed in the tag's walnut */
            g_fill(g, x0 - 2, y0 - 2, w + 4, 2, RP.walnut_d);
            g_fill(g, x0 - 2, y0 + h, w + 4, 2, RP.walnut_d);
            g_fill(g, x0 - 2, y0, 2, h, RP.walnut_d);
            g_fill(g, x0 + w, y0, 2, h, RP.walnut_d);
            ck_pointer(g, x0 - 10 < 0 ? 0 : x0 - 10, y0 + 26, a->now_ms, RP.walnut_d, RP.cream);
        }
        char cnt[24];
        snprintf(cnt, sizeof cnt, "%d songs", a->shelf_all_n[s]);
        const char *name = crate_str(c, k->name);
        int tw = text_w(F(a, F_SEMI12), name, 0) + 16, cw = text_w(F(a, F_MONO10), cnt, 0) + 16;
        if (cw > tw) tw = cw;
        if (tw > w - 12) tw = w - 12;
        dio_tag(g, x0 + 6, y0 + 8, tw, 38);
        txt_fit(a, g, F_SEMI12, x0 + 14, y0 + 25, name, tw - 14, RP.ink, 0);
        txt(a, g, F_MONO10, x0 + 14, y0 + 39, cnt, RP.sub, 0);
        const int ps = 40;
        for (int i = 0; i < 3 && i < a->shelf_n[s]; i++) {   /* three covers, pinned on */
            /* on Sekiro, along the ink at its foot; on the Knight's, high up: his mask is at the foot */
            int x = x0 + 6 + i * (ps + 6), y = (s ? y0 + 60 : y0 + h - ps - 10) - (i == 1 ? 6 : 0);
            g_fill_a(g, x + 2, y + 3, ps, ps, C565(0, 0, 0), foc ? 90 : 60);
            g_fill(g, x, y, ps, ps, nightc(H(0xf2efe7)));
            cover(a, g, a->shelf[s][i], ART_S, x + 2, y + 2, ps - 4);
            g_fill_a(g, x + ps / 2 - 6, y - 3, 12, 6, nightc(H(0xe6dcc0)), 200);
        }
    }
}

static void draw_explore(app *a, gfx *g)
{
    const palette *p = P(a);
    const crates *c = &a->cr[CK_EXPLORE];
    if (a->skin == 7 && c->n == 2) {
        list_state *l = &a->ls[V_EXPLORE];
        l->n = 2;
        l->sel = fx_clamp(l->sel, 0, 1);
        dio_explore(a, g, c, l->sel);
        draw_nowbar(a, g);
        return;
    }
    draw_header(a, g, "Explore", NULL);
    list_state *l = &a->ls[V_EXPLORE];
    int n = (int)(c->n < 3 ? c->n : 3);
    l->n = n;
    l->sel = fx_clamp(l->sel, 0, n ? n - 1 : 0);
    if (!n) {
        txt(a, g, F_BODY10, 8, LIST_Y + 22, "Not enough listening yet. Play some music,", p->sub, 0);
        txt(a, g, F_BODY10, 8, LIST_Y + 36, "then refresh the card from the PC.", p->sub, 0);
    }
    const int H = n ? (BAR_Y - LIST_Y - 4) / n : 60;
    for (int s = 0; s < n; s++) {
        int y = LIST_Y + 2 + s * H;
        const crate *k = &c->tab[s];
        char cnt[16];
        snprintf(cnt, sizeof cnt, "%d", a->shelf_all_n[s]);
        SK(a)->shelf(a, g, y, H, crate_str(c, k->name), crate_str(c, k->sub), cnt, a->shelf[s], a->shelf_n[s],
                     s == l->sel);
    }
    draw_nowbar(a, g);
}

/* ---- Soundtracks: crate rows under franchise dividers */
static void draw_osts(app *a, gfx *g)
{
    const palette *p = P(a);
    const crates *c = &a->cr[CK_OST];
    list_state *l = &a->ls[V_OST];
    l->n = a->n_crate_rows;
    char cnt[24];
    commas(cnt, sizeof cnt, c->n);
    draw_header(a, g, "Soundtracks", cnt);
    if (!c->n) txt(a, g, F_BODY10, 8, LIST_Y + 22, "No soundtracks on this card.", p->sub, 0);
    list_follow(l, 6);
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    int first = (int)floorf(l->top);
    for (int r = first; r < first + 8 && r < l->n; r++) {
        int y = LIST_Y + (int)lrintf((r - l->top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        int ci = a->crate_rows[r];
        if (ci < 0) {                               /* franchise divider */
            const crate *k = &c->tab[-1 - ci];
            const char *sec = crate_str(c, k->section);
            txt_fit(a, g, F_SEMI11, 8, y + 24, sec[0] ? sec : "More soundtracks", LCD_W - 16, p->blue, 0);
            g_fill(g, 0, y + ROW_H - 2, LCD_W, 2, p->ink);
            continue;
        }
        const crate *k = &c->tab[ci];
        int foc = r == l->sel;
        row_ink rk = SK(a)->row(a, g, y, ROW_H, foc ? ROW_FOCUS : 0);
        uint32_t c0 = LIB_NONE;
        crate_members(c, (uint32_t)ci, 0, &c0, 1);
        cover(a, g, c0, ART_S, 12, y + 1, ROW_H - 2);
        char meta[32], d[16];
        hm(d, sizeof d, k->seconds);
        snprintf(meta, sizeof meta, "%u \xC2\xB7 %s", (unsigned)k->count, d);
        int mw = text_w(F(a, F_MONO10), meta, 0);
        SK(a)->label(a, g, 12 + ROW_H + 6, y + 20, crate_str(c, k->name), rk.fg, 0, LCD_W - ROW_H - 46 - mw);
        txt_right(a, g, F_MONO10, LCD_W - 12, y + 20, meta, rk.on ? rk.note : p->sub);
    }
    g_noclip(g);
    draw_nowbar(a, g);
}

static void draw_genres(app *a, gfx *g)
{
    const crates *c = &a->cr[CK_GENRE];
    static const char *names[64], *counts[64];
    static char cbuf[64][16];
    int n = (int)(c->n < 64 ? c->n : 64);
    for (int i = 0; i < n; i++) {
        names[i] = crate_str(c, c->tab[i].name);
        commas(cbuf[i], sizeof cbuf[i], c->tab[i].count);
        counts[i] = cbuf[i];
    }
    char cnt[16];
    snprintf(cnt, sizeof cnt, "%d", n);
    draw_header(a, g, "Genres", cnt);
    if (!n) txt(a, g, F_BODY10, 8, LIST_Y + 22, "No genres on this card.", P(a)->sub, 0);
    draw_crate_rows(a, g, &a->ls[V_GENRES], names, counts, n);
    draw_nowbar(a, g);
}

/* ---- Saved queues: /.coda/saved.bin, the queues kept for later (Queue > Save queue).
 * Songs go in by their YouTube ids, so a card filled again later (which numbers its songs
 * anew) still finds them; one that's no longer on the card is left out. Newest first.
 * File: "CSQ1", u32 count, then per queue u32 saved-at, u16 songs, a 48-byte name (NUL
 * padded) and 11 bytes per song. The whole file lives here; a change writes it again. */
#define SAVED_MAX 12
#define SV_NAME 48
#define SV_HEAD (4 + 2 + SV_NAME)
static uint8_t sv_buf[8 + SAVED_MAX * (SV_HEAD + QMAX * 11)];
static uint32_t sv_off[SAVED_MAX];
static int sv_n, sv_len, sv_forget = -1;
static uint32_t sv_forget_ms;

static const char *const MON[12] = { "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" };
static uint32_t sv_songs(int i) { return sv_buf[sv_off[i] + 4] | (sv_buf[sv_off[i] + 5] << 8); }
static const char *sv_name(int i) { return (const char *)sv_buf + sv_off[i] + 6; }

/* the queues in the first len bytes of sv_buf; a damaged tail is dropped */
static void sv_scan(int len)
{
    sv_n = 0;
    uint32_t off = 8, c = len >= 8 && !memcmp(sv_buf, "CSQ1", 4) ? qs_r32(sv_buf + 4) : 0;
    for (uint32_t i = 0; i < c && sv_n < SAVED_MAX && off + SV_HEAD <= (uint32_t)len; i++) {
        uint32_t n = sv_buf[off + 4] | (sv_buf[off + 5] << 8);
        if (n > QMAX || off + SV_HEAD + n * 11 > (uint32_t)len) break;
        sv_buf[off + SV_HEAD - 1] = 0;
        sv_off[sv_n++] = off;
        off += SV_HEAD + n * 11;
    }
    sv_len = (int)off;
    memcpy(sv_buf, "CSQ1", 4);
}

static int sv_load(void)
{
    int fd = plat_open("saved.bin"), r = 0;
    if (fd >= 0) { r = plat_pread(fd, sv_buf, (int)sizeof sv_buf, 0); plat_close(fd); }
    sv_scan(r);
    return sv_n;
}

static int sv_write(void)
{
    qs_w32(sv_buf + 4, (uint32_t)sv_n);
    return plat_save("saved.bin", sv_buf, (size_t)sv_len);
}

/* the queue as it stands, named for the song it began with */
static void save_queue(app *a)
{
    sv_load();
    if (a->qn <= 0) { say(a, "Nothing in the queue to save"); return; }
    if (sv_n >= SAVED_MAX) { say(a, "12 saved already. Hold play on one in Saved queues to let it go"); return; }
    uint8_t *e = sv_buf + sv_len;
    int n = 0;
    for (int i = 0; i < a->qn && n < QMAX; i++)
        if (brain_id(a->q[i], (char *)e + SV_HEAD + 11 * n)) n++;
    if (!n) { say(a, "Couldn't save this queue"); return; }
    const lib_track *t = lib_get(a->L, a->q[0]);
    const char *title = t && t->title[0] ? t->title : "Queue";
    size_t k = strlen(title);
    if (k > SV_NAME - 1) {                           /* cut on a whole character */
        k = SV_NAME - 1;
        while (k && ((uint8_t)title[k] & 0xC0) == 0x80) k--;
    }
    memset(e + 6, 0, SV_NAME);
    memcpy(e + 6, title, k);
    qs_w32(e, (uint32_t)plat_now());
    e[4] = (uint8_t)n;
    e[5] = (uint8_t)(n >> 8);
    sv_off[sv_n++] = (uint32_t)sv_len;
    sv_len += SV_HEAD + 11 * n;
    char msg[96];
    if (sv_write() == 0) snprintf(msg, sizeof msg, "Saved %d songs as \"%s\"", n, sv_name(sv_n - 1));
    else { sv_load(); snprintf(msg, sizeof msg, "Couldn't write to the card"); }
    say(a, msg);
}

/* list row -> the queue it shows (newest first) */
static int sv_at(int row) { return row >= 0 && row < sv_n ? sv_n - 1 - row : -1; }

static void saved_open(app *a, int row)
{
    int i = sv_at(row);
    if (i < 0) return;
    const char *ids = (const char *)sv_buf + sv_off[i] + SV_HEAD;
    uint32_t n = sv_songs(i);
    set_tracks(a, TK_SAVED, sv_name(i));
    a->n_tracks = 0;
    for (uint32_t k = 0; k < n && a->n_tracks < TRACKS_MAX; k++) {
        uint32_t idx = brain_find(ids + 11 * k);
        if (idx != LIB_NONE && idx < brain_n()) a->tracks[a->n_tracks++] = idx;
    }
    a->tracks_crate = (uint32_t)i;
    push(a, V_TRACKS);
    if ((uint32_t)a->n_tracks < n) {
        char msg[64];
        snprintf(msg, sizeof msg, "%u of its songs aren't on the card now", (unsigned)(n - (uint32_t)a->n_tracks));
        say(a, msg);
    }
}

/* hold play twice on a saved queue: it goes */
static void saved_forget(app *a, int row)
{
    int i = sv_at(row);
    if (i < 0) return;
    if (sv_forget != i || a->now_ms - sv_forget_ms > 4000) {
        sv_forget = i;
        sv_forget_ms = a->now_ms;
        say(a, "Hold play again to let this one go");
        return;
    }
    sv_forget = -1;
    uint32_t at = sv_off[i], len = SV_HEAD + sv_songs(i) * 11;
    memmove(sv_buf + at, sv_buf + at + len, (size_t)sv_len - at - len);
    qs_w32(sv_buf + 4, (uint32_t)(sv_n - 1));
    sv_scan(sv_len - (int)len);
    say(a, sv_write() == 0 ? "Let it go" : "Couldn't write to the card");
    a->ls[V_SAVED].n = sv_n;
    a->ls[V_SAVED].sel = fx_clamp(a->ls[V_SAVED].sel, 0, sv_n > 0 ? sv_n - 1 : 0);
}

static void draw_saved(app *a, gfx *g)
{
    static const char *names[SAVED_MAX], *counts[SAVED_MAX];
    static char cbuf[SAVED_MAX][24];
    for (int r = 0; r < sv_n; r++) {
        int i = sv_at(r);
        names[r] = sv_name(i);
        int y, m, d;                                 /* the day it was saved, and its songs */
        civil(qs_r32(sv_buf + sv_off[i]) / 86400, &y, &m, &d);
        snprintf(cbuf[r], sizeof cbuf[r], "%s %d \xC2\xB7 %u", MON[(m + 11) % 12], d, (unsigned)sv_songs(i));
        counts[r] = cbuf[r];
    }
    char cnt[16];
    snprintf(cnt, sizeof cnt, "%d", sv_n);
    draw_header(a, g, "Saved queues", cnt);
    if (!sv_n) {
        txt(a, g, F_BODY10, 8, LIST_Y + 22, "Nothing saved yet. At the end of the Queue,", P(a)->sub, 0);
        txt(a, g, F_BODY10, 8, LIST_Y + 36, "Save queue keeps it here for later.", P(a)->sub, 0);
    }
    draw_crate_rows(a, g, &a->ls[V_SAVED], names, counts, sv_n);
    draw_nowbar(a, g);
}

/* ---- Queue */
static void draw_queue(app *a, gfx *g)
{
    const palette *p = P(a);
    list_state *l = &a->ls[V_QUEUE];
    l->n = a->qn + 2;                    /* under the songs: Save queue | Saved queues, one row */
    l->sel = fx_clamp(l->sel, 0, l->n - 1);
    char cnt[24];
    snprintf(cnt, sizeof cnt, a->qn ? "%d of %d" : "empty", a->qpos + 1, a->qn);
    draw_header(a, g, "Queue", cnt);
    if (!a->qn) {
        txt(a, g, F_BODY10, 8, LIST_Y + ROW_H + 22, "Nothing queued. Play something and autoplay", p->sub, 0);
        txt(a, g, F_BODY10, 8, LIST_Y + ROW_H + 36, "keeps it going.", p->sub, 0);
    }
    list_state v = { a->qn + 1, l->sel < a->qn ? l->sel : a->qn, l->top };
    list_follow(&v, 6);
    l->top = v.top;
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    int first = (int)floorf(l->top);
    for (int i = first; i < first + 8 && i < v.n; i++) {
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        if (i == a->qn) {
            static const char *const lb[2] = { "Save queue", "Saved queues" };
            static const int sy[2] = { SYM_QUEUE, SYM_LIBRARY };
            int w = (LCD_W - 12) / 2;
            for (int k = 0; k < 2; k++)
                SK(a)->button(a, g, 4 + k * w, y + 3, w - 6, ROW_H - 5, sy[k], lb[k], l->sel == a->qn + k, k);
            continue;
        }
        int live = i == a->qpos && a->cur_valid;
        const char *note = live ? (a->ps.playing ? "playing" : "paused") :
                           a->qsrc[i] == QS_AUTO ? "autoplay" : NULL;
        track_row(a, g, y, a->q[i], i == l->sel, live, i < a->qpos, note,
                  live ? p->red : p->blue, i + 1);
    }
    g_noclip(g);
    draw_nowbar(a, g);
}

/* ---- Search: a letter rail on the wheel, results under it */
static void rail_label(int r, char *out)
{
    if (r < 36) { out[0] = (char)(RAIL[r] >= 'a' ? RAIL[r] - 32 : RAIL[r]); out[1] = 0; }
    else out[0] = 0;
}

static void draw_rail(app *a, gfx *g, int y)
{
    const palette *p = P(a);
    const int cx = LCD_W / 2, slot = 30, h = 34;
    g_fill(g, 0, y, LCD_W, 1, p->rule);
    g_fill(g, 0, y + h, LCD_W, 1, p->rule);
    for (int d = -5; d <= 5; d++) {
        if (d == 0) continue;                      /* the picked key last: it's on top */
        int r = mod(a->rail + d, RAIL_N), x = cx + d * slot - slot / 2 + 2;
        char lb[4];
        rail_label(r, lb);
        SK(a)->key(a, g, x, y + 4, slot - 5, h - 8, lb, r == RAIL_SPACE ? 1 : r == RAIL_DEL ? 2 : 3, 0, abs(d));
    }
    {
        int r = mod(a->rail, RAIL_N), x = cx - slot / 2 + 2;
        char lb[4];
        rail_label(r, lb);
        SK(a)->key(a, g, x, y + 4, slot - 5, h - 8, lb, r == RAIL_SPACE ? 1 : r == RAIL_DEL ? 2 : 3, 1, 0);
    }
    const char *hint = a->rail == RAIL_SPACE ? "space" : a->rail == RAIL_DEL ? "delete" :
                       a->rail == RAIL_GO ? "to the results" : NULL;
    if (hint) txt_center(a, g, F_MONO10, cx, y + h + 11, hint, 200, p->sub, 0);
}

static int search_rows(app *a) { return a->n_hit_artists + a->n_hits; }

static void draw_search_list(app *a, gfx *g, int y0, int visible, int with_focus)
{
    const palette *p = P(a);
    list_state *l = &a->ls[V_SEARCH];
    l->n = search_rows(a);
    list_follow(l, visible);
    g_clip(g, 0, y0, LCD_W, BAR_Y);
    int first = (int)floorf(l->top);
    for (int i = first; i < first + visible + with_focus && i < l->n; i++) {
        int y = y0 + (int)lrintf((i - l->top) * ROW_H);
        int foc = with_focus && i == l->sel;
        if (i < a->n_hit_artists) {                /* artist rows lead, like the web's */
            uint32_t fi, cnt;
            lib_artist(a->L, a->hit_artist[i], &fi, &cnt);
            const lib_track *t = lib_get(a->L, fi);
            row_ink k = SK(a)->row(a, g, y, ROW_H, foc ? ROW_FOCUS : 0);
            cover(a, g, fi, ART_S, 12, y + 1, ROW_H - 2);
            char cs[24];
            snprintf(cs, sizeof cs, "artist \xC2\xB7 %u", (unsigned)cnt);
            int cw = text_w(F(a, F_MONO10), cs, 0);
            if (t) SK(a)->label(a, g, 12 + ROW_H + 6, y + 20, t->artist, k.fg, 0, LCD_W - ROW_H - 46 - cw);
            txt_right(a, g, F_MONO10, LCD_W - 12, y + 20, cs, k.on ? k.note : p->blue);
            continue;
        }
        uint32_t idx = a->hits[i - a->n_hit_artists].idx;
        track_row(a, g, y, idx, foc, a->cur_valid && idx == a->cur, 0, NULL, 0, 0);
    }
    g_noclip(g);
}

static void draw_search(app *a, gfx *g)
{
    const palette *p = P(a);
    char cnt[24] = "";
    if (a->query[0]) snprintf(cnt, sizeof cnt, "%d found", a->n_hits);
    draw_header(a, g, "Search", a->query[0] ? cnt : NULL);
    if (!search_ready()) {
        txt(a, g, F_BODY10, 8, LIST_Y + 22, "No search index on this card.", p->sub, 0);
        txt(a, g, F_BODY10, 8, LIST_Y + 36, "Refresh the card from the PC.", p->sub, 0);
        draw_nowbar(a, g);
        return;
    }
    /* the typed line */
    char up[48];
    utf8_upper(a->query, up, sizeof up);
    int qy = LIST_Y + 27;
    if (a->query[0]) {
        int w = txt_fit(a, g, F_POSTER22, 8, qy, up, LCD_W - 30, p->ink, T_TRACK(-5));
        if (!a->s_results) g_fill(g, 8 + w + 2, qy - 17, 3, 20, p->red);
    } else {
        g_fill(g, 8, qy - 17, 3, 20, p->red);
        txt(a, g, F_BODY10, 18, qy - 4, "Spin for a letter, press play to type it", p->sub, 0);
    }
    if (!a->s_results) {
        draw_rail(a, g, LIST_Y + 36);
        if (a->query[0]) {
            if (!search_rows(a))
                txt(a, g, F_BODY10, 8, LIST_Y + 100, "Nothing matches yet.", p->sub, 0);
            else draw_search_list(a, g, LIST_Y + 84, 3, 0);
        }
    } else {
        g_fill(g, 0, LIST_Y + 36, LCD_W, 1, p->ink);
        draw_search_list(a, g, LIST_Y + 37, 5, 1);
    }
    draw_nowbar(a, g);
}

/* the values the wheel steps through for a device setting */
#define LADDER_MAX 40
static int dev_ladder(int ds, int *v)
{
    static const int sleep_m[] = { 0, 15, 30, 45, 60, 90, 120 };
    static const int screen_s[] = { 5, 10, 15, 20, 30, 45, 60, 90, 120, 300, 0 };
    static const int idle_m[] = { 0, 5, 10, 15, 20, 30, 45, 60 };
    const int *fixed = NULL;
    int n = 0, lo, hi, step;
    plat_dev_range(ds, &lo, &hi, &step);
    switch (ds) {
    case DS_SLEEP: fixed = sleep_m; n = 7; break;
    case DS_SCREEN: fixed = screen_s; n = 11; break;
    case DS_POWEROFF: fixed = idle_m; n = 8; break;
    case DS_BRIGHT:                                   /* 5% steps */
        for (int pct = 5; pct <= 100 && n < LADDER_MAX; pct += 5) v[n++] = lo + (hi - lo) * pct / 100;
        return n;
    case DS_VOLMAX:                                   /* not so low it sounds broken */
        for (int x = hi; x >= lo && x >= -60 && n < LADDER_MAX; x -= step) v[n++] = x;
        for (int i = 0; i < n / 2; i++) { int t = v[i]; v[i] = v[n - 1 - i]; v[n - 1 - i] = t; }
        return n;
    case DS_BASS: case DS_TREBLE:
        for (int x = -12; x <= 12; x++) if (x >= lo && x <= hi) v[n++] = x;
        return n;
    default:
        for (int x = lo; x <= hi && n < LADDER_MAX; x += step) v[n++] = x;
        return n;
    }
    memcpy(v, fixed, sizeof(int) * (size_t)n);
    return n;
}

static int dev_nearest(int ds, int cur)
{
    int v[LADDER_MAX], n = dev_ladder(ds, v), best = 0;
    for (int i = 0; i < n; i++) {
        if (v[i] == cur) return i;
        if ((ds == DS_SCREEN && cur == 0) || (ds == DS_SCREEN && v[i] == 0)) continue;
        if (abs(v[i] - cur) < abs(v[best] - cur)) best = i;
    }
    return best;
}

static void dev_fmt(int ds, int v, char *o, size_t n)
{
    int lo, hi, step;
    plat_dev_range(ds, &lo, &hi, &step);
    switch (ds) {
    case DS_SLEEP: if (v) snprintf(o, n, "%d min", v); else snprintf(o, n, "off"); break;
    case DS_SCREEN:
        if (v <= 0) snprintf(o, n, v ? "always off" : "never");
        else if (v < 60) snprintf(o, n, "%d s", v);
        else snprintf(o, n, "%d min", v / 60);
        break;
    case DS_BRIGHT: snprintf(o, n, "%d%%", hi > lo ? (int)lrintf((v - lo) * 100.0f / (hi - lo)) : 100); break;
    case DS_POWEROFF: if (v) snprintf(o, n, "%d min", v); else snprintf(o, n, "never"); break;
    case DS_VOLMAX: if (v >= hi) snprintf(o, n, "none"); else snprintf(o, n, "%d dB", v); break;
    case DS_BASS: case DS_TREBLE: if (v) snprintf(o, n, "%+d dB", v); else snprintf(o, n, "flat"); break;
    case DS_UNPLUG:
        snprintf(o, n, "%s", v == 1 ? "pause" : v == 2 ? "pause, resume" : "keep playing");
        break;
    default: snprintf(o, n, "%d", v); break;
    }
}

/* the themes (Settings > Theme): a theme, and for the poster ones day / night / auto */
typedef struct { int skin, night; const char *name, *desc; } theme_opt;
static const theme_opt THEMES[] = {
    { 0, 0, "Sakurai", "Paper, ink and Klein blue: tilted panels sized by use, a cursor that slides." },
    { 0, 1, "Sakurai night", "The same, printed in negative." },
    { 0, -1, "Sakurai auto", "Day while the sun is up, night from dusk to dawn." },
    { 1, -1, "Room", "Your room, Bubloo on the shelf. Daylight by day, lamp-lit after dark." },
    { 1, 0, "Room day", "Your room, always by day." },
    { 1, 1, "Room night", "Your room, always after dark: the lamp and the light bar on." },
    { 2, 0, "Jukebox", "A heavy wooden frame, songs on parchment slots, a sign hung from the wall." },
    { 3, 0, "Toybox", "Giant toy buttons on a drifting checkerboard; bubbles rise with the music." },
    { 4, 0, "Deck", "A silver and walnut hi-fi: amber display, spectrum, the sections as a playlist." },
    { 5, 0, "Crate", "Your covers as pixel art on walnut; the one you're on pulls into focus." },
    { 6, 0, "Receiver", "An amber dot-matrix behind glass; the wheel tunes a dial. VU meters." },
    { 7, -1, "Diorama", "Your desk up close, Bubloo living on it. Sun by day, the lamp at night." },
    { 7, 0, "Diorama day", "Your desk, always by day." },
    { 7, 1, "Diorama night", "Your desk, always after dark." },
};
#define N_THEMES ((int)(sizeof THEMES / sizeof THEMES[0]))

static int current_theme(const app *a)
{
    for (int i = 0; i < N_THEMES; i++)
        if (THEMES[i].skin == a->skin && THEMES[i].night == a->night_mode) return i;
    for (int i = 0; i < N_THEMES; i++)
        if (THEMES[i].skin == a->skin) return i;
    return 0;
}

/* on Coda OS Settings come in groups (panels); the plugin keeps one list */
static int settings_grouped(void) { return (plat_features() & PF_DEVICE) != 0; }

static int sr_group(int r)
{
    switch (r) {
    case SR_SLEEP: case SR_POWEROFF: return G_SLEEP;
    case SR_VOLMAX: case SR_BASS: case SR_TREBLE: case SR_UNPLUG: return G_SOUND;
    case SR_SCREEN: case SR_BRIGHT: return G_SCREEN;
    case SR_THEME: return G_THEME;
    case SR_LAYOUT: case SR_TICKS: case SR_PEEK: case SR_VIZ: return G_WHEEL;
    case SR_AUTOPLAY: case SR_KEEP: return G_PLAYBACK;
    case SR_BT: return G_BT;
    default: return G_CLOCK;
    }
}

static void settings_rows(app *a)
{
    int f = plat_features(), grouped = settings_grouped();
    a->n_set = 0;
    if (grouped && a->set_group == G_THEME) {
        for (int i = 0; i < N_THEMES; i++) a->set_row[a->n_set++] = i;
        a->ls[V_SETTINGS].n = a->n_set;
        return;
    }
    for (int r = 0; r < SR_COUNT; r++) {
        if (sr_dev(r) >= 0 && !(f & PF_DEVICE)) continue;
        if (r == SR_KEEP && !(f & PF_EXIT)) continue;
        if (r == SR_BT && !(f & PF_BLUETOOTH)) continue;
        if (grouped && (r == SR_THEME || sr_group(r) != a->set_group)) continue;
        a->set_row[a->n_set++] = r;
    }
    a->ls[V_SETTINGS].n = a->n_set;
}

static void setting_value(app *a, int r, char *o, size_t n)
{
    int ds = sr_dev(r);
    if (ds >= 0) {
        int v[LADDER_MAX];
        if (a->adj && a->set_row[a->ls[V_SETTINGS].sel] == r) {
            dev_ladder(ds, v);
            dev_fmt(ds, v[a->adj_i], o, n);
        } else {
            dev_fmt(ds, plat_dev_get(ds), o, n);
            if (ds == DS_SLEEP && plat_dev_get(ds)) snprintf(o + strlen(o), n - strlen(o), " left");
        }
        return;
    }
    int ch, cm;
    switch (r) {
    case SR_THEME: snprintf(o, n, "%s", a->night_mode < 0 ? "auto (dusk to dawn)" : a->night_mode ? "night" : "day"); break;
    case SR_LAYOUT: snprintf(o, n, "%s", a->layout_b ? "B: dial" : "A: full wheel"); break;
    case SR_TICKS: snprintf(o, n, "%s", a->tick_sound ? "on" : "off"); break;
    case SR_PEEK: snprintf(o, n, "%s", a->peek_on ? "on" : "off"); break;
    case SR_VIZ: snprintf(o, n, "%s", a->viz_on ? "on" : "off"); break;
    case SR_AUTOPLAY: snprintf(o, n, "%s", a->autoplay_on ? "on" : "off"); break;
    case SR_KEEP: snprintf(o, n, "%s", a->keep_playing ? "after exit" : "only in Coda"); break;
    case SR_CLOCK: plat_clock(&ch, &cm); snprintf(o, n, "%02d:%02d", ch, cm); break;
    case SR_BT: {
        const plat_bt *b = &a->bt;
        if (b->radio == BTR_STARTING) snprintf(o, n, "starting");
        else if (b->radio == BTR_FAILED) snprintf(o, n, "failed");
        else if (b->radio != BTR_ON) snprintf(o, n, "off");
        else if (b->link >= BTL_CONNECTED) snprintf(o, n, "%s", b->peer);
        else if (b->link == BTL_CONNECTING) snprintf(o, n, "connecting");
        else snprintf(o, n, "on");
        break;
    }
    default: o[0] = 0; break;
    }
}

/* what the focused row does, under the list (two lines at most) */
static const char *setting_help(int r)
{
    switch (r) {
    case SR_SLEEP: return "Switches the player off after this long. On the charger it pauses instead.";
    case SR_THEME: return "Day is light, night is dark. Auto goes dark at dusk and light at dawn.";
    case SR_LAYOUT: return "A: a wheel of covers with the songs listed beside it. B: a dial, the song's name above.";
    case SR_TICKS: return "A quiet click for each step the wheel turns.";
    case SR_PEEK: return "Rest the wheel on a song for a moment to hear it. Your own song carries on when you leave.";
    case SR_VIZ: return "The wheel's bars and Diorama's coloured wall move with the music. Off saves battery.";
    case SR_AUTOPLAY: return "When the queue runs out, Coda carries on with songs picked from what you play and skip.";
    case SR_KEEP: return "Whether autoplay keeps picking songs once you leave Coda.";
    case SR_SCREEN: return "How long the screen stays lit after the last button press.";
    case SR_BRIGHT: return "How bright the screen is. Dimmer lasts longer on a charge.";
    case SR_POWEROFF: return "Switches off after this long with no music playing and the screen dark.";
    case SR_VOLMAX: return "The volume buttons stop here, to protect your ears. None allows the player's full volume.";
    case SR_BASS: return "Boosts or cuts the low end, in dB. Flat plays the files as they are.";
    case SR_TREBLE: return "Boosts or cuts the high end, in dB. Flat plays the files as they are.";
    case SR_BT: return "Wireless headphones: switch the radio on, find them, connect.";
    case SR_UNPLUG: return "When the headphones come out: keep playing, pause, or pause and play again when they're back.";
    case SR_CLOCK: return "Sets the time and date, for the clock, the auto theme and your listening history.";
    default: return "";
    }
}

#define SET_ROWS 5                      /* below them, down to the now bar, the row's help */

/* the panels: each group with what it's set to */
/* ---- Shortcuts (hold Menu): every combination, and Play does it from here */
static void settings_help(app *a, gfx *g, int help_y, const char *help);
typedef struct { const char *what, *keys, *help; } key_row;
static const key_row KEYS[] = {
    { "History", "hold Back", "Hold Back anywhere: what you've played, newest first." },
    { "Screen off", "Power", "Press Power (don't hold it): the screen goes off, the music plays on. Any button brings it back." },
    { "Brightness", "hold |< or >|, turn", "Hold Prev or Next and turn the wheel. Play here opens the Screen settings." },
    { "Like the song", "hold Play", "On Now playing or the Wheel. Play here likes the song playing." },
    { "Dislike and skip", "hold >|", "Hold Next for a second, anywhere, screen on or off: not this one, next. Play here does it." },
    { "Like, dislike a song", "Menu", "Menu on Now playing, or on any song in the Queue, played or still to come." },
    { "Take out of the queue", "hold Play", "Hold Play on a song in the Queue." },
    { "Shortcuts", "hold Menu", "This list. Hold Menu anywhere." },
    { "Rockbox's own menus", "hold Menu + Back", "Hold both for a second and a half." },
};
#define N_KEYS ((int)(sizeof KEYS / sizeof KEYS[0]))

static void draw_keys(app *a, gfx *g)
{
    const palette *p = P(a);
    draw_header(a, g, "Shortcuts", NULL);
    list_state *l = &a->ls[V_KEYS];
    l->n = N_KEYS;
    l->sel = fx_clamp(l->sel, 0, N_KEYS - 1);
    list_follow(l, SET_ROWS);
    const int help_y = LIST_Y + SET_ROWS * ROW_H;
    g_clip(g, 0, LIST_Y, LCD_W, help_y);
    for (int i = (int)floorf(l->top); i < N_KEYS; i++) {
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H), foc = i == l->sel;
        row_ink k = SK(a)->row(a, g, y, ROW_H, foc ? ROW_FOCUS : 0);
        int vw = text_w(F(a, F_MONO10), KEYS[i].keys, 0);
        SK(a)->label(a, g, 14, y + 20, KEYS[i].what, k.fg, 0, LCD_W - 40 - vw);
        txt_right(a, g, F_MONO10, LCD_W - 12, y + 20, KEYS[i].keys, k.on ? k.note : p->blue);
    }
    g_noclip(g);
    settings_help(a, g, help_y, KEYS[l->sel].help);
    draw_nowbar(a, g);
}

static void draw_settings_groups(app *a, gfx *g)
{
    draw_header(a, g, "Settings", NULL);
    static char v[G_COUNT][40];
    char b1[16], b2[16];
    dev_fmt(DS_SLEEP, plat_dev_get(DS_SLEEP), v[G_SLEEP], sizeof v[0]);
    if (plat_dev_get(DS_SLEEP)) snprintf(v[G_SLEEP] + strlen(v[G_SLEEP]), sizeof v[0] - strlen(v[G_SLEEP]), " left");
    dev_fmt(DS_VOLMAX, plat_dev_get(DS_VOLMAX), b1, sizeof b1);
    snprintf(v[G_SOUND], sizeof v[0], "volume limit %s", b1);
    dev_fmt(DS_BRIGHT, plat_dev_get(DS_BRIGHT), b1, sizeof b1);
    dev_fmt(DS_SCREEN, plat_dev_get(DS_SCREEN), b2, sizeof b2);
    snprintf(v[G_SCREEN], sizeof v[0], "%s, %s", b1, b2);
    snprintf(v[G_THEME], sizeof v[0], "%s", THEMES[current_theme(a)].name);
    snprintf(v[G_WHEEL], sizeof v[0], "%s%s", a->layout_b ? "dial" : "full", a->tick_sound ? ", clicks" : "");
    snprintf(v[G_PLAYBACK], sizeof v[0], "autoplay %s", a->autoplay_on ? "on" : "off");
    if (plat_features() & PF_BLUETOOTH) setting_value(a, SR_BT, v[G_BT], sizeof v[0]);
    else snprintf(v[G_BT], sizeof v[0], "not on this firmware");
    setting_value(a, SR_CLOCK, v[G_CLOCK], sizeof v[0]);
    const mtile t[G_COUNT] = {
        { SEC_SLEEP, -40, 35, 128, 120, 2, "Sleep", v[G_SLEEP] },
        { SEC_SOUND, 133, 35, 350, 120, 2, "Sound", v[G_SOUND] },
        { SEC_SCREEN, -40, 125, 92, 168, 0, "Screen", v[G_SCREEN] },
        { SEC_THEME, 97, 125, 206, 168, 0, "Theme", v[G_THEME] },
        { SEC_WHEELSET, 211, 125, 350, 168, 0, "Wheel", v[G_WHEEL] },
        { SEC_PLAYBACK, -40, 173, 120, 211, 0, "Playback", v[G_PLAYBACK] },
        { SEC_BT, 125, 173, 236, 211, 0, "Bluetooth", v[G_BT] },
        { SEC_CLOCK, 241, 173, 350, 211, 0, "Clock", v[G_CLOCK] },
    };
    a->gl.n = G_COUNT;
    a->gl.sel = fx_clamp(a->gl.sel, 0, G_COUNT - 1);
    SK(a)->mosaic(a, g, t, G_COUNT, a->gl.sel);
}

/* a list with its focused row's help under it */
static void settings_help(app *a, gfx *g, int help_y, const char *help)
{
    char lines[2][TEXT_LINE_MAX];
    int nl = text_wrap(F(a, F_BODY10), help, LCD_W - 16, 2, 0, lines);
    int y = help_y + (nl > 1 ? 12 : 18);
    for (int i = 0; i < nl; i++) txt(a, g, F_BODY10, 8, y + i * 12, lines[i], P(a)->sub, 0);
}

static void draw_settings(app *a, gfx *g)
{
    const palette *p = P(a);
    if (settings_grouped() && a->set_group < 0) { draw_settings_groups(a, g); return; }
    int themes = a->set_group == G_THEME;
    draw_header(a, g, a->set_group >= 0 ? G_NAME[a->set_group] : "Settings", a->adj ? "turn, then Play" : NULL);
    list_state *l = &a->ls[V_SETTINGS];
    l->n = a->n_set;
    list_follow(l, SET_ROWS);
    const int help_y = LIST_Y + SET_ROWS * ROW_H;
    g_clip(g, 0, LIST_Y, LCD_W, help_y);
    for (int i = (int)floorf(l->top); i < a->n_set; i++) {
        int r = a->set_row[i];
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H), foc = i == l->sel;
        char val[40];
        const char *label;
        if (themes) {
            label = THEMES[r].name;
            snprintf(val, sizeof val, "%s", r == current_theme(a) ? "on" : "");
        } else {
            label = sr_label[r];
            setting_value(a, r, val, sizeof val);
            if (foc && a->adj) {                          /* being turned: < value > */
                char tmp[40];
                snprintf(tmp, sizeof tmp, "< %s >", val);
                snprintf(val, sizeof val, "%s", tmp);
            }
        }
        row_ink k = SK(a)->row(a, g, y, ROW_H, foc ? ROW_FOCUS | (a->adj ? ROW_ADJ : 0) : 0);
        int vw = text_w(F(a, F_MONO10), val, 0);
        SK(a)->label(a, g, 14, y + 20, label, k.fg, 0, LCD_W - 40 - vw);
        txt_right(a, g, F_MONO10, LCD_W - 12, y + 20, val, k.on ? k.note : p->blue);
    }
    g_noclip(g);
    if (a->n_set) settings_help(a, g, help_y, themes ? THEMES[a->set_row[l->sel]].desc : setting_help(a->set_row[l->sel]));
    draw_nowbar(a, g);
}

/* Play on a settings row */
static void settings_select(app *a)
{
    if (settings_grouped() && a->set_group < 0) {
        int gsel = fx_clamp(a->gl.sel, 0, G_COUNT - 1);
        if (gsel == G_BT) {
            if (plat_features() & PF_BLUETOOTH) push(a, V_BT);
            else say(a, "No Bluetooth on this firmware");
            return;
        }
        if (gsel == G_CLOCK) { clock_open(a); return; }
        a->set_group = gsel;
        a->ls[V_SETTINGS].sel = 0;
        a->ls[V_SETTINGS].top = 0;
        settings_rows(a);
        if (gsel == G_THEME) a->ls[V_SETTINGS].sel = current_theme(a);
        return;
    }
    if (a->set_group == G_THEME) {
        const theme_opt *t = &THEMES[a->set_row[fx_clamp(a->ls[V_SETTINGS].sel, 0, a->n_set - 1)]];
        app_set_skin(a, t->skin);
        a->night_mode = t->night;
        coda_settings_save(a);
        return;
    }
    int r = a->set_row[a->ls[V_SETTINGS].sel], ds = sr_dev(r);
    if (ds == DS_UNPLUG) {                           /* three choices: cycle, like Theme */
        plat_dev_set(ds, (plat_dev_get(ds) + 1) % 3);
        plat_dev_save();
        return;
    }
    if (ds >= 0) {
        a->adj = 1;
        a->adj_i = dev_nearest(ds, plat_dev_get(ds));
        return;
    }
    switch (r) {
    case SR_LAYOUT: a->layout_b = !a->layout_b; break;
    case SR_THEME: a->night_mode = a->night_mode == 0 ? 1 : a->night_mode == 1 ? -1 : 0; break;
    case SR_TICKS: a->tick_sound = !a->tick_sound; break;
    case SR_PEEK: a->peek_on = !a->peek_on; break;
    case SR_VIZ: a->viz_on = !a->viz_on; break;
    case SR_AUTOPLAY: a->autoplay_on = !a->autoplay_on; break;
    case SR_KEEP: a->keep_playing = !a->keep_playing; break;
    case SR_CLOCK: clock_open(a); return;
    case SR_BT: push(a, V_BT); return;
    default: return;
    }
    coda_settings_save(a);
}

/* input while a device setting is being adjusted; 1 = consumed */
static int settings_adjust_event(app *a, ui_ev e)
{
    int ds = sr_dev(a->set_row[a->ls[V_SETTINGS].sel]);
    if (ds < 0) { a->adj = 0; return 0; }
    if (e.k == K_SCROLL) {
        int v[LADDER_MAX], n = dev_ladder(ds, v);
        a->adj_i = fx_clamp(a->adj_i + e.d, 0, n - 1);
        plat_dev_set(ds, v[a->adj_i]);
        return 1;
    }
    a->adj = 0;                                      /* any key sets it */
    plat_dev_save();
    return e.k == K_PLAY || e.k == K_BACK || e.k == K_MENU;
}

/* ---- clock: the RTC behind the status clock and the evening theme. Wheel = adjust,
 * Play = next field (the last one sets it), Back = leave without setting. */
static const char *const CK_NAME[5] = { "hour", "minute", "day", "month", "year" };

static int days_in(int y, int m)
{
    static const int d[12] = { 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31 };
    return m == 2 && ((y % 4 == 0 && y % 100) || y % 400 == 0) ? 29 : d[m - 1];
}

static void clock_open(app *a)
{
    /* civil date from the platform's epoch (on the H2: wall time as if it were UTC) */
    int year, mon, day;
    civil(plat_now() / 86400, &year, &mon, &day);
    int h, m;
    plat_clock(&h, &m);
    if (year < 2025) year = 2026;
    a->ck[0] = h; a->ck[1] = m; a->ck[2] = day; a->ck[3] = mon; a->ck[4] = year;
    a->ck_field = 0;
    push(a, V_CLOCK);
}

static void clock_adjust(app *a, int d)
{
    int *v = &a->ck[a->ck_field];
    switch (a->ck_field) {
    case 0: *v = mod(*v + d, 24); break;
    case 1: *v = mod(*v + d, 60); break;
    case 2: *v = mod(*v - 1 + d, days_in(a->ck[4], a->ck[3])) + 1; break;
    case 3: *v = mod(*v - 1 + d, 12) + 1; break;
    default: *v = fx_clamp(*v + d, 2024, 2099); break;
    }
    if (a->ck[2] > days_in(a->ck[4], a->ck[3])) a->ck[2] = days_in(a->ck[4], a->ck[3]);
}

static void draw_clock(app *a, gfx *g)
{
    const palette *p = P(a);
    draw_header(a, g, "Clock", NULL);
    char f[5][8];
    snprintf(f[0], 8, "%02d", a->ck[0]); snprintf(f[1], 8, "%02d", a->ck[1]);
    snprintf(f[2], 8, "%02d", a->ck[2]); snprintf(f[3], 8, "%02d", a->ck[3]);
    snprintf(f[4], 8, "%04d", a->ck[4]);
    /* time big, date under it, the field being set printed in ink on paper */
    int x = 8, y = 98;
    for (int i = 0; i < 2; i++) {
        int w = text_w(F(a, F_POSTER22), f[i], 0);
        if (i == a->ck_field) g_fill(g, x - 3, y - 22, w + 6, 28, p->ink);
        txt(a, g, F_POSTER22, x, y, f[i], i == a->ck_field ? p->paper : p->ink, 0);
        x += w + 4;
        if (!i) { txt(a, g, F_POSTER22, x, y, ":", p->ink, 0); x += text_w(F(a, F_POSTER22), ":", 0) + 4; }
    }
    x = 8; y = 136;
    static const int order[3] = { 4, 3, 2 };
    for (int k = 0; k < 3; k++) {
        int i = order[k], w = text_w(F(a, F_POSTER18), f[i], 0);
        if (i == a->ck_field) g_fill(g, x - 3, y - 18, w + 6, 23, p->ink);
        txt(a, g, F_POSTER18, x, y, f[i], i == a->ck_field ? p->paper : p->ink, 0);
        x += w + 4;
        if (k < 2) { txt(a, g, F_POSTER18, x, y, "-", p->sub, 0); x += text_w(F(a, F_POSTER18), "-", 0) + 4; }
    }
    char hint[64];
    snprintf(hint, sizeof hint, "spin to set the %s, play for the next", CK_NAME[a->ck_field]);
    txt(a, g, F_BODY10, 8, 166, hint, p->sub, 0);
    txt(a, g, F_BODY10, 8, 180, a->ck_field == 4 ? "play sets the clock, back leaves it as it was" :
        "back leaves it as it was", p->sub, 0);
    draw_nowbar(a, g);
}

/* ---- Bluetooth: the switch and the sound quality, then remembered headphones, then what
 * a search found, then the search itself. Play connects (pairing first if needed) or
 * disconnects the connected pair; hold Play forgets a remembered one. The radio works in
 * the background: this view just redraws whenever the platform says something changed. */
enum { BTROW_POWER = -1, BTROW_PAIRED = -2, BTROW_NEARBY = -3, BTROW_SCAN = -4, BTROW_QUALITY = -5 };

static int bt_row_is_header(app *a, int r)
{
    return r >= 0 && r < a->bt_nrows && (a->bt_rows[r] == BTROW_PAIRED || a->bt_rows[r] == BTROW_NEARBY);
}

static int bt_n_paired(app *a)
{
    int n = 0;
    for (int i = 0; i < a->bt_ndev; i++) n += a->bt_dev[i].paired != 0;
    return n;
}

static void bt_build_rows(app *a)
{
    int n = 0, np = bt_n_paired(a);
    a->bt_rows[n++] = BTROW_POWER;
    if (a->bt.radio == BTR_ON) {
        a->bt_rows[n++] = BTROW_QUALITY;
        if (np) {
            a->bt_rows[n++] = BTROW_PAIRED;
            for (int i = 0; i < a->bt_ndev && n < 30; i++) if (a->bt_dev[i].paired) a->bt_rows[n++] = i;
        }
        if (a->bt_ndev > np || a->bt.scanning) {
            a->bt_rows[n++] = BTROW_NEARBY;
            for (int i = 0; i < a->bt_ndev && n < 31; i++) if (!a->bt_dev[i].paired) a->bt_rows[n++] = i;
        }
        a->bt_rows[n++] = BTROW_SCAN;
    }
    a->bt_nrows = n;
    list_state *l = &a->ls[V_BT];
    l->n = n;
    l->sel = fx_clamp(l->sel, 0, n - 1);
    while (bt_row_is_header(a, l->sel)) l->sel++;
}

/* poll the platform; rebuild and redraw only when its state changed */
static void bt_refresh(app *a)
{
    if (!a->bt_has) return;
    plat_bt_status(&a->bt);
    if (a->bt_pending_on && a->bt.radio == BTR_ON) {     /* a card picked while off: the radio's up */
        a->bt_pending_on = 0;
        plat_bt_connect(a->bt_pending);
    } else if (a->bt_pending_on && a->bt.radio == BTR_FAILED) a->bt_pending_on = 0;
    /* the headphones' own volume moved (their buttons, or ours): say where it is */
    if (a->bt.vol_gen != a->bt_vol_seen) {
        a->bt_vol_seen = a->bt.vol_gen;
        if (a->bt.abs_volume >= 0) {
            char s[24];
            snprintf(s, sizeof s, "Volume %d%%", (a->bt.abs_volume * 100 + 63) / 127);
            say(a, s);
            a->force_full = 1;
        }
    }
    if (a->bt.gen == a->bt_gen_seen && a->bt_nrows) return;
    a->bt_gen_seen = a->bt.gen;
    a->bt_ndev = plat_bt_devices(a->bt_dev, 24);
    bt_build_rows(a);
    if (a->bt.msg[0] && strcmp(a->bt.msg, a->bt_msg_seen)) say(a, a->bt.msg);
    snprintf(a->bt_msg_seen, sizeof a->bt_msg_seen, "%s", a->bt.msg);
    /* switched on from this screen with nothing remembered: search as soon as it's up */
    if (a->bt_autoscan && (a->bt.radio == BTR_ON || a->bt.radio == BTR_FAILED)) {
        if (a->bt.radio == BTR_ON && a->view == V_BT && !bt_n_paired(a) && !a->bt.scanning)
            plat_bt_scan(1);
        a->bt_autoscan = 0;
    }
    a->force_full = 1;
}

static void bt_open(app *a)
{
    a->bt_nrows = 0;
    bt_refresh(a);
    a->ls[V_BT].sel = 0;
    a->ls[V_BT].top = 0;
    if (a->bt.radio == BTR_ON && !bt_n_paired(a) && !a->bt.scanning) plat_bt_scan(1);
}

static int bt_is_peer(app *a, const plat_bt_dev *d)
{
    return a->bt.link != BTL_NONE && !memcmp(d->addr, a->bt.peer_addr, 6);
}

static const char *bt_hint(app *a)
{
    int r = a->bt_rows[a->ls[V_BT].sel];
    if (r == BTROW_QUALITY) return a->bt.weak ? "weak signal: fewer kbps" : "play to change";
    if (r < 0 || r >= a->bt_ndev) return NULL;
    const plat_bt_dev *d = &a->bt_dev[r];
    if (bt_is_peer(a, d)) return a->bt.link == BTL_CONNECTING ? "play to cancel" : "play to disconnect";
    return d->paired ? "hold to forget" : "play to pair";
}

static void draw_bt(app *a, gfx *g)
{
    const palette *p = P(a);
    const plat_bt *b = &a->bt;
    draw_header(a, g, "Bluetooth", a->bt_nrows ? bt_hint(a) : NULL);
    list_state *l = &a->ls[V_BT];
    l->n = a->bt_nrows;
    list_follow(l, 6);
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    int first = (int)floorf(l->top);
    for (int r = first; r < first + 8 && r < l->n; r++) {
        int y = LIST_Y + (int)lrintf((r - l->top) * ROW_H), foc = r == l->sel, code = a->bt_rows[r];
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        if (code == BTROW_PAIRED || code == BTROW_NEARBY) {          /* section divider */
            txt(a, g, F_SEMI11, 8, y + 24, code == BTROW_PAIRED ? "Your headphones" : "Nearby", p->blue, 0);
            if (code == BTROW_NEARBY && b->scanning) txt_right(a, g, F_MONO10, LCD_W - 8, y + 24, "searching", p->sub);
            g_fill(g, 0, y + ROW_H - 2, LCD_W, 2, p->ink);
            continue;
        }
        if (code == BTROW_SCAN) {
            action_row(a, g, y, b->scanning ? "Searching\xE2\x80\xA6" : a->bt_ndev > bt_n_paired(a) ?
                       "Search again" : "Search for headphones", SYM_SEARCH, foc);
            if (b->scanning) txt_right(a, g, F_MONO10, LCD_W - 8, y + 20, "stop", foc ? p->paper : p->sub);
            continue;
        }
        const char *label, *val = "";
        int live = 0;
        if (code == BTROW_POWER) {
            label = "Bluetooth";
            val = b->radio == BTR_ON ? "on" : b->radio == BTR_STARTING ? "starting" :
                  b->radio == BTR_STOPPING ? "turning off" : b->radio == BTR_FAILED ? "didn't start" : "off";
        } else if (code == BTROW_QUALITY) {
            /* the setting, and while connected what the link carries (until the stream
             * starts again after a change, still the old one) */
            static char qb[32];
            label = "Sound quality";
            if (b->link_kbps) snprintf(qb, sizeof qb, "%s, %u kbps", b->hq ? "high" : "standard", b->link_kbps);
            else snprintf(qb, sizeof qb, "%s", b->hq ? "high" : "standard");
            val = qb;
        } else {
            const plat_bt_dev *d = &a->bt_dev[code];
            label = d->name;
            if (bt_is_peer(a, d)) {
                val = b->link == BTL_STREAMING ? "playing" : b->link == BTL_CONNECTED ? "connected" : "connecting";
                live = b->link == BTL_STREAMING;
                static char vb[40];               /* earbuds that tell their batteries: each one */
                if (b->link >= BTL_CONNECTED && (b->batt_l >= 0 || b->batt_r >= 0)) {
                    char l[8] = "-", r[8] = "-";
                    if (b->batt_l >= 0) snprintf(l, sizeof l, "%d", b->batt_l);
                    if (b->batt_r >= 0) snprintf(r, sizeof r, "%d", b->batt_r);
                    snprintf(vb, sizeof vb, "L%s R%s  %s", l, r, val);
                    val = vb;
                }
            } else if (!d->paired) {
                val = "pair";
            }
        }
        row_ink k = SK(a)->row(a, g, y, ROW_H, (foc ? ROW_FOCUS : 0) | (live ? ROW_LIVE : 0));
        int quiet = code >= 0 && a->bt_dev[code].paired && !bt_is_peer(a, &a->bt_dev[code]);
        int vw = text_w(F(a, F_MONO10), val, 0);
        SK(a)->label(a, g, 14, y + 20, label, k.fg, 0, LCD_W - 40 - vw);
        txt_right(a, g, F_MONO10, LCD_W - 12, y + 20, val, k.on ? k.note : quiet ? p->sub : p->blue);
    }
    g_noclip(g);
    /* off / starting / failed: say what this is, under the switch */
    if (b->radio != BTR_ON) {
        int y = LIST_Y + ROW_H + 26;
        const char *l1 = NULL, *l2 = NULL;
        switch (b->radio) {
        case BTR_OFF: l1 = "Off. Turn it on to play through"; l2 = "wireless headphones or a speaker."; break;
        case BTR_STARTING: l1 = "Waking the radio\xE2\x80\xA6"; break;
        case BTR_STOPPING: l1 = "Turning off\xE2\x80\xA6"; break;
        default: l1 = b->msg[0] ? b->msg : "The radio didn't start."; l2 = "Play on the switch to try again."; break;
        }
        txt(a, g, F_SEMI12, 8, y, l1, b->radio == BTR_FAILED ? p->red : p->ink, 0);
        if (l2) txt(a, g, F_BODY10, 8, y + 18, l2, p->sub, 0);
    }
    draw_nowbar(a, g);
}

static void bt_event(app *a, ui_ev e)
{
    list_state *l = &a->ls[V_BT];
    if (e.k == K_SCROLL) {
        int d = e.d > 0 ? 1 : -1, steps = abs(e.d);
        for (int k = 0; k < steps; k++) {
            int s = l->sel + d;
            while (bt_row_is_header(a, s)) s += d;
            if (s < 0 || s >= l->n) break;
            l->sel = s;
        }
        return;
    }
    if (!a->bt_nrows || (e.k != K_PLAY && e.k != K_PLAY_LONG)) return;
    int code = a->bt_rows[l->sel];
    if (code == BTROW_POWER) {
        int on = a->bt.radio == BTR_OFF || a->bt.radio == BTR_FAILED;
        if (e.k == K_PLAY) { plat_bt_power(on); a->bt_autoscan = on; }
    } else if (code == BTROW_QUALITY) {
        if (e.k == K_PLAY) {
            a->bt.hq = !a->bt.hq;
            plat_bt_quality(a->bt.hq);
            /* each device keeps its own (a car may play nothing at all on high) */
            say(a, a->bt.hq ? "High for this device: more detail, more battery" :
                              "Standard for this device: the longest range");
        }
    } else if (code == BTROW_SCAN) {
        if (e.k == K_PLAY) plat_bt_scan(!a->bt.scanning);
    } else if (code >= 0 && code < a->bt_ndev) {
        const plat_bt_dev *d = &a->bt_dev[code];
        if (e.k == K_PLAY_LONG) {
            if (d->paired) {
                char m[64];
                snprintf(m, sizeof m, "Forgot %s", d->name);
                plat_bt_forget(d->addr);
                say(a, m);
            }
        } else if (bt_is_peer(a, d)) {
            plat_bt_disconnect();
        } else {
            char m[64];
            snprintf(m, sizeof m, "%s %s\xE2\x80\xA6", d->paired ? "Connecting to" : "Pairing with", d->name);
            plat_bt_connect(d->addr);
            say(a, m);
        }
    }
    a->bt_gen_seen--;                    /* re-read the platform on the next tick */
}

/* a card on Diorama's board: connect it, or let go of it; with the radio off, on first */
static void rack_select(app *a, int k)
{
    int d = rack_dev(a, k);
    if (d < 0) { push(a, V_BT); return; }
    char nm[48], m[80];
    rack_name(a, k, nm, sizeof nm);
    switch (rack_state(a, k)) {
    case RK_OFF:
        if (a->bt.radio == BTR_OFF || a->bt.radio == BTR_FAILED) plat_bt_power(1);
        memcpy(a->bt_pending, a->bt_dev[d].addr, 6);
        a->bt_pending_on = 1;
        snprintf(m, sizeof m, "Bluetooth on, then %s\xE2\x80\xA6", nm);
        break;
    case RK_CONNECTING: case RK_ON: case RK_PLAYING:
        plat_bt_disconnect();
        snprintf(m, sizeof m, "Let go of %s", nm);
        break;
    default:
        plat_bt_connect(a->bt_dev[d].addr);
        snprintf(m, sizeof m, "Connecting to %s\xE2\x80\xA6", nm);
        break;
    }
    say(a, m);
    a->bt_gen_seen--;                    /* re-read the platform on the next tick */
}

/* ---- action sheet: a slab of ink rising from the bottom; focus prints paper */
#define SHEET_MAX 5
#define NEW_QUEUE "New queue here"
#define SAVE_QUEUE "Save queue"
static int sheet_items(app *a, const char *items[SHEET_MAX])
{
    int liked = brain_is_liked(a->sheet_idx);
    if (a->sheet == SH_QROW) {
        int pos = a->sheet_qpos, n = 0, now = pos == a->qpos && a->cur_valid;
        items[n++] = liked ? "Unlike" : "Like";
        items[n++] = now ? "Dislike, skip it" : pos > a->qpos ? "Dislike, take it out" : "Dislike";
        if (!now) items[n++] = pos > a->qpos ? "Take it out" : "Play it again";
        else items[n++] = NEW_QUEUE;
        items[n++] = "Go to artist";
        items[n++] = SAVE_QUEUE;
        return n;
    }
    if (a->sheet == SH_NOW) {
        items[0] = liked ? "Unlike" : "Like";
        items[1] = "Dislike, skip it";
        items[2] = NEW_QUEUE;
        items[3] = "Go to artist";
        items[4] = "Queue";
        return 5;
    } else {
        items[0] = "Play next";
        items[1] = "Add to queue";
        items[2] = liked ? "Unlike" : "Like";
        items[3] = "Go to artist";
    }
    return 4;
}

static int sheet_sym(const char *item)
{
    return !strcmp(item, "Play next") || !strcmp(item, "Play it again") ? SYM_NEXT :
           !strcmp(item, "Add to queue") || !strcmp(item, "Queue") || !strcmp(item, "Take it out") ||
           !strcmp(item, SAVE_QUEUE) ? SYM_QUEUE :
           !strcmp(item, NEW_QUEUE) ? SYM_STATION :
           !strncmp(item, "Dislike", 7) ? SYM_DISLIKE : !strcmp(item, "Go to artist") ? SYM_ARTISTS : SYM_LIKED;
}

static void draw_sheet(app *a, gfx *g)
{
    const char *items[SHEET_MAX];
    int n = sheet_items(a, items), syms[SHEET_MAX];
    for (int i = 0; i < n; i++) syms[i] = sheet_sym(items[i]);
    if (SK(a)->sheet) { SK(a)->sheet(a, g, items, syms, n, a->sheet_sel); return; }
    const palette *p = P(a);
    const int rh = 28, head = 34, h = head + n * rh, y0 = LCD_H - h;
    g_fill(g, 0, y0 - 2, LCD_W, 2, p->paper);
    g_fill(g, 0, y0, LCD_W, h, p->strip_bg);
    const lib_track *t = lib_get(a->L, a->sheet_idx);
    cover(a, g, a->sheet_idx, ART_S, 0, y0, head - 2);
    if (t) {
        txt_fit(a, g, F_BOLD11, head + 6, y0 + 14, t->title, LCD_W - head - 14, p->strip_fg, 0);
        txt_fit(a, g, F_BODY10, head + 6, y0 + 27, t->artist, LCD_W - head - 14, p->strip_sub, 0);
    }
    for (int i = 0; i < n; i++) {
        int y = y0 + head + i * rh, foc = i == a->sheet_sel;
        if (foc) g_fill(g, 0, y, LCD_W, rh, p->strip_fg);
        txt(a, g, F_POSTER15, 12, y + 19, items[i], foc ? p->strip_bg : p->strip_fg, T_TRACK(-3));
        if (!foc && i) g_fill_a(g, 12, y, LCD_W - 24, 1, p->strip_sub, 90);
    }
}

/* The charge screen: the charger switched the player on. Dark, the cell big in the middle,
 * amber as it fills (green when full); any button starts the player proper, unplugging
 * switches it off again, and so does the screen going dark (the charger carries on alone). */
static void draw_charge(app *a, gfx *g)
{
    const px16 bg = C565(0x10, 0x10, 0x12), rim = C565(0x8a, 0x89, 0x84), dim = C565(0x5c, 0x5b, 0x57);
    int pct = plat_battery(), chg = plat_charging();
    if (pct > 100) pct = 100;
    g_noclip(g);
    g_fill(g, 0, 0, LCD_W, LCD_H, bg);
    const int w = 132, h = 60, x = (LCD_W - w) / 2 - 4, y = 64;
    px16 ink = chg == 2 ? CHG_FULL : CHG_AMBER;
    for (int i = 0; i < 3; i++) {                                  /* the cell, a heavy rim */
        g_fill(g, x + i, y + i, w - 2 * i, 1, rim);
        g_fill(g, x + i, y + h - 1 - i, w - 2 * i, 1, rim);
        g_fill(g, x + i, y + i, 1, h - 2 * i, rim);
        g_fill(g, x + w - 1 - i, y + i, 1, h - 2 * i, rim);
    }
    g_fill(g, x + w, y + h / 2 - 12, 8, 24, rim);                  /* the terminal */
    int inner = w - 14, fill = pct > 0 ? inner * pct / 100 : 0;
    if (pct > 0 && fill < 3) fill = 3;
    g_fill(g, x + 7, y + 7, fill, h - 14, ink);
    if (chg == 1) {                                                /* charging: the edge breathes */
        int k = (int)(a->now_ms / 600 % 2);
        if (fill < inner) g_fill_a(g, x + 7 + fill, y + 7, inner - fill < 10 ? inner - fill : 10, h - 14, ink, k ? 120 : 50);
    }
    char s[16];
    snprintf(s, sizeof s, pct >= 0 ? "%d%%" : "--", pct);
    txt_center(a, g, F_POSTER22, LCD_W / 2, y + h + 40, s, 200, C565(0xf2, 0xef, 0xe7), T_TRACK(-4));
    txt_center(a, g, F_SEMI12, LCD_W / 2, y + h + 60, chg == 2 ? "Charged" : chg ? "Charging" : "Not charging",
               200, ink, 0);
    txt_center(a, g, F_BODY10, LCD_W / 2, LCD_H - 14, a->charge_mode == 1 ?
               "Charging with the player off. A button now starts it." : "Any button starts the player.",
               LCD_W - 16, dim, 0);
}

int app_charge_mode(const app *a) { return a->charge_mode; }

void app_draw(app *a, gfx *g)
{
    if (a->charge_mode) { draw_charge(a, g); return; }
    if (a->night_mode >= 0) theme_set_night(&a->th, a->night_mode);
    else theme_set_night(&a->th, dark_now());
    rp_night(has_night(a->skin) ? night_of(a->night_mode) : 0);
    if (SK(a)->pal) a->th.p = SK(a)->pal(a);
    g_noclip(g);
    if (a->view == V_GAME) { game_draw(a, g); return; }   /* a game draws the whole screen */
    if (a->skin == 7) dio_pre(g);                    /* Diorama: the camera keeps the page it leaves */
    SK(a)->page(a, g);
    switch (a->view) {
    case V_MENU: draw_menu(a, g); break;
    case V_WHEEL: draw_wheel(a, g); break;
    case V_NOW: draw_now(a, g); break;
    case V_LIBRARY: draw_library(a, g); break;
    case V_ARTISTS: draw_artists(a, g); break;
    case V_TRACKS: draw_tracks(a, g); break;
    case V_SETTINGS: draw_settings(a, g); break;
    case V_KEYS: draw_keys(a, g); break;
    case V_EXPLORE: draw_explore(a, g); break;
    case V_SEARCH: draw_search(a, g); break;
    case V_OST: draw_osts(a, g); break;
    case V_GENRES: draw_genres(a, g); break;
    case V_QUEUE: draw_queue(a, g); break;
    case V_CLOCK: draw_clock(a, g); break;
    case V_BT: draw_bt(a, g); break;
    case V_GAMES: draw_games(a, g); break;
    case V_SAVED: draw_saved(a, g); break;
    default: break;
    }
    if (a->skin == 7) dio_post(a, g);               /* ... and moves in or out over the new one */
    if (a->sheet != SH_NONE) draw_sheet(a, g);
}

/* ------------------------------------------------------------------ input */
static void list_scroll(list_state *l, int d) { l->sel = fx_clamp(l->sel + d, 0, l->n > 0 ? l->n - 1 : 0); }

/* a short list that goes round (the home's sections, the Library's): past the end, the
 * start again; a big jump still stops at an end */
static void ring_scroll(list_state *l, int d)
{
    if (l->n > 0 && d > -l->n && d < l->n) l->sel = mod(l->sel + d, l->n);
    else list_scroll(l, d);
}

/* the same round a theme's own order (where the items sit in its picture): d steps on from
 * item sel, the item it lands on */
static int ring_step(const uint8_t *ord, int n, int sel, int d)
{
    int pos = 0;
    for (int i = 0; i < n; i++) if (ord[i] == sel) pos = i;
    return ord[mod(pos + d, n)];
}

static void toggle_like(app *a, uint32_t idx)
{
    int was = brain_is_liked(idx);
    brain_log(idx, was ? EV_UNLIKE : EV_LIKE, -1.0f, (double)plat_now());
    say(a, was ? "Unliked" : "Liked \xE2\x99\xA5");
}

static void go_artist(app *a, uint32_t idx)
{
    uint32_t ar = lib_artist_of(a->L, idx), fi, c;
    lib_artist(a->L, ar, &fi, &c);
    const lib_track *t = lib_get(a->L, fi);
    set_tracks(a, TK_ARTIST, t ? t->artist : "Artist");
    a->n_tracks = 0;
    for (uint32_t i = 0; i < c && a->n_tracks < TRACKS_MAX; i++) a->tracks[a->n_tracks++] = fi + i;
    push(a, V_TRACKS);
    a->ls[V_ARTISTS].sel = (int)ar;
    if (idx >= fi && idx < fi + c) a->ls[V_TRACKS].sel = (int)(idx - fi) + a->n_actions;
}

static void open_sheet(app *a, int kind, uint32_t idx)
{
    if (idx == LIB_NONE) return;
    a->sheet = kind;
    a->sheet_sel = 0;
    a->sheet_idx = idx;
}

/* a song already in the queue: go to it there; otherwise it plays now, right after the song
 * you're on, and the rest of the queue stays behind it */
static void play_keep(app *a, uint32_t idx)
{
    if (idx == LIB_NONE) return;
    for (int i = a->qn - 1; i >= 0; i--)
        if (a->q[i] == idx) {
            if (i == a->qpos && a->cur_valid) plat_toggle();
            else q_jump(a, i);
            return;
        }
    if (!a->qn || !a->cur_valid) { play_one(a, idx); return; }
    q_add(a, idx, 1, QS_USER);
    q_jump(a, a->qpos + 1);
}

/* on to the next song. At the end of the queue autoplay picks one first (even after songs
 * were taken out from under it), so Next never just does nothing; 0 if there's nothing */
static int skip_next(app *a, int outcome)
{
    a->outcome = OUT_SKIP;
    a->outcome_ms = a->now_ms;
    if (a->cur_valid && a->qpos >= a->qn - 1 && a->autoplay_on) autoplay_add(a, (double)plat_now());
    if (redecide_on_skip(a, outcome)) return 1;
    if (a->cur_valid && a->qpos >= a->qn - 1) return 0;
    plat_skip(+1);
    return 1;
}

static void dislike_current(app *a, uint32_t idx)
{
    brain_log(idx, EV_DISLIKE, a->ps.elapsed_ms / 1000.0f, (double)plat_now());
    say(a, skip_next(a, BRAIN_OUT_DISLIKE) ? "Disliked. Skipped." : "Disliked. Nothing after it.");
}

/* the song on now starts a queue of its own: what was queued after it goes, and autoplay
 * picks on from this one (its radio), as if you'd just chosen it */
static void new_queue_here(app *a)
{
    if (!a->cur_valid) return;
    for (int i = a->qn - 1; i > a->qpos; i--) {
        int n = a->qn;
        q_remove(a, i);
        if (a->qn == n) return;                    /* the player can't take songs out here */
    }
    a->fence = -1;
    brain_radio_seed(a->cur);
    autoplay_fill(a, (double)plat_now());
    say(a, "New queue from this song");
}

/* Menu on a song in the queue: played, playing or still to come */
static void qrow_select(app *a, const char *it)
{
    uint32_t idx = a->sheet_idx;
    int pos = a->sheet_qpos, here = pos >= 0 && pos < a->qn && a->q[pos] == idx;
    if (!strcmp(it, "Like") || !strcmp(it, "Unlike")) toggle_like(a, idx);
    else if (!strncmp(it, "Dislike", 7)) {
        if (here && pos == a->qpos && a->cur_valid) dislike_current(a, idx);
        else {
            brain_log(idx, EV_DISLIKE, 0.0f, (double)plat_now());
            if (here && pos > a->qpos) { q_remove(a, pos); q_topup(a); say(a, "Disliked. Taken out."); }
            else say(a, "Disliked");
        }
    } else if (!strcmp(it, "Take it out")) {
        if (here) { q_remove(a, pos); q_topup(a); }
        say(a, "Taken out of the queue");
    } else if (!strcmp(it, NEW_QUEUE)) {
        new_queue_here(a);
    } else if (!strcmp(it, "Play it again")) {
        if (here) q_jump(a, pos);
    } else if (!strcmp(it, SAVE_QUEUE)) {
        save_queue(a);
    } else go_artist(a, idx);
}

static void sheet_select(app *a)
{
    uint32_t idx = a->sheet_idx;
    int kind = a->sheet, s = a->sheet_sel;
    if (kind == SH_QROW) {
        const char *items[SHEET_MAX];
        int n = sheet_items(a, items);
        a->sheet = SH_NONE;
        if (s >= 0 && s < n) qrow_select(a, items[s]);
        return;
    }
    a->sheet = SH_NONE;
    if (kind == SH_NOW) {
        if (s == 0) toggle_like(a, idx);
        else if (s == 1) dislike_current(a, idx);  /* = web dislike(): the verdict, then Next */
        else if (s == 2) new_queue_here(a);
        else if (s == 3) go_artist(a, idx);
        else push(a, V_QUEUE);
    } else {
        if (s == 0) { q_add(a, idx, 1, QS_USER); say(a, "Plays next"); }
        else if (s == 1) { q_add(a, idx, 0, QS_USER); say(a, "Added to the queue"); }
        else if (s == 2) toggle_like(a, idx);
        else go_artist(a, idx);
    }
}

static void menu_select(app *a)
{
    int s = menu_item_at(a, a->ls[V_MENU].sel);
    if (s >= N_MENU) { rack_select(a, s - N_MENU); return; }
    if (menu_view[s] >= 0) push(a, menu_view[s]);
    else { set_tracks(a, TK_LIKED, "Liked"); push(a, V_TRACKS); }
}

static void library_select(app *a)
{
    switch (a->ls[V_LIBRARY].sel) {
    case 0: set_tracks(a, TK_SONGS, "Songs"); push(a, V_TRACKS); break;
    case 1: push(a, V_ARTISTS); break;
    case 2: push(a, V_GENRES); break;
    case 3: push(a, V_OST); break;
    case 5: push(a, V_GAMES); break;
    default: set_tracks(a, TK_HISTORY, "History"); push(a, V_TRACKS); break;
    }
}

static int load_crate(app *a, int kind, uint32_t i, int cap)
{
    int n = crate_members(&a->cr[kind], i, 0, a->tracks, cap);
    a->n_tracks = n;
    a->tracks_crate = i;
    return n;
}

static void play_shuffled(app *a, const uint32_t *v, int n)
{
    static uint32_t tmp[TRACKS_MAX];
    if (n <= 0) return;
    memcpy(tmp, v, sizeof(uint32_t) * (size_t)n);
    shuffle(tmp, n);
    q_set(a, tmp, n > 200 ? 200 : n, 0, QS_USER);
}

static void tracks_select(app *a)
{
    list_state *l = &a->ls[V_TRACKS];
    if (l->n <= 0) return;
    int row = l->sel;
    if (row < a->n_actions) {
        if (a->tracks_kind == TK_ARTIST || a->tracks_kind == TK_OST || a->tracks_kind == TK_SHELF ||
            a->tracks_kind == TK_SAVED) {
            if (row == 0) q_set(a, a->tracks, a->n_tracks, 0, QS_USER);
            else play_shuffled(a, a->tracks, a->n_tracks);
        } else if (a->tracks_kind == TK_GENRE) {
            int gi = (int)a->tracks_crate;
            if (row == 0) {                        /* station: a random seed, fenced autoplay */
                uint32_t seed = a->n_tracks ? a->tracks[rnd((uint32_t)a->n_tracks)] : LIB_NONE;
                if (seed == LIB_NONE) return;
                play_one(a, seed);
                a->pick_on = 0;                    /* a random song, not one you picked */
                a->fence = gi;
                say(a, "Station: autoplay stays in this genre");
            } else play_shuffled(a, a->tracks, a->n_tracks);
        }
        return;
    }
    int i = row - a->n_actions;
    switch (a->tracks_kind) {
    case TK_ARTIST: case TK_LIKED: case TK_OST: case TK_SAVED:    /* sequences: play on from here */
        q_set(a, a->tracks, a->n_tracks, i, QS_USER);
        pick_start(a, a->tracks[i], a->tracks[i]);
        break;
    case TK_HISTORY:                               /* back to a song: inside the queue you have */
        play_keep(a, track_at(a, i));
        break;
    default:                                       /* lookups: this song, then autoplay */
        play_one(a, track_at(a, i));
        break;
    }
}

static void crates_select(app *a)
{
    if (a->view == V_EXPLORE) {
        int s = a->ls[V_EXPLORE].sel;
        if (s >= (int)a->cr[CK_EXPLORE].n || s >= 3) return;
        set_tracks(a, TK_SHELF, crate_str(&a->cr[CK_EXPLORE], a->cr[CK_EXPLORE].tab[s].name));
        memcpy(a->tracks, a->shelf_all[s], sizeof(uint32_t) * (size_t)a->shelf_all_n[s]);
        a->n_tracks = a->shelf_all_n[s];
        push(a, V_TRACKS);
    } else if (a->view == V_OST) {
        int r = a->ls[V_OST].sel;
        if (r < 0 || r >= a->n_crate_rows || a->crate_rows[r] < 0) return;
        uint32_t ci = (uint32_t)a->crate_rows[r];
        set_tracks(a, TK_OST, crate_str(&a->cr[CK_OST], a->cr[CK_OST].tab[ci].name));
        load_crate(a, CK_OST, ci, TRACKS_MAX);
        push(a, V_TRACKS);
    } else if (a->view == V_GENRES) {
        uint32_t gi = (uint32_t)a->ls[V_GENRES].sel;
        if (gi >= a->cr[CK_GENRE].n) return;
        set_tracks(a, TK_GENRE, crate_str(&a->cr[CK_GENRE], a->cr[CK_GENRE].tab[gi].name));
        load_crate(a, CK_GENRE, gi, TRACKS_MAX);
        push(a, V_TRACKS);
    }
}

static void wheel_play(app *a)
{
    if (!a->n_pool) return;
    uint32_t item = a->pool[mod(a->target, a->n_pool)];
    if (item & BRAIN_WHEEL_LIST) {                 /* an album / playlist: in order, from the top */
        static uint32_t m[QMAX];
        int n = brain_wheel_list(item, m, QMAX);
        if (n <= 0) return;
        if (a->peeking) {
            if (m[0] != a->peek_idx) a->peek_ignore_until = a->now_ms + 3000;
            a->peeking = 0;
        }
        q_set(a, m, n, 0, QS_USER);
        pick_start(a, item, m[0]);
        return;
    }
    uint32_t idx = item;
    if (a->peeking) {
        if (a->cur_valid && idx == a->cur && a->peek_was_active) {   /* your song: on from where it was */
            peek_back(a, 1);
            return;
        }
        /* commit: this becomes the song. If it isn't the one previewing, the player says
         * that one for a moment longer -- not a new song, don't take it as one */
        if (idx != a->peek_idx) a->peek_ignore_until = a->now_ms + 3000;
        a->peeking = 0;
        play_one(a, idx);
        return;
    }
    if (a->cur_valid && idx == a->cur) plat_toggle();
    else play_one(a, idx);
}

/* ---- search input */
static void run_search(app *a)
{
    a->n_hits = a->query[0] ? search_run(a->query, a->hits, SEARCH_MAX) : 0;
    a->n_hit_artists = 0;
    for (int i = 0; i < a->n_hits && a->n_hit_artists < 3; i++) {
        if (!(a->hits[i].flags & SEARCH_ARTIST_HIT)) continue;
        uint32_t ar = lib_artist_of(a->L, a->hits[i].idx);
        int dup = 0;
        for (int k = 0; k < a->n_hit_artists; k++) dup |= a->hit_artist[k] == ar;
        if (!dup) a->hit_artist[a->n_hit_artists++] = ar;
    }
    a->ls[V_SEARCH].sel = 0;
    a->ls[V_SEARCH].top = 0;
}

static void search_type(app *a)
{
    size_t n = strlen(a->query);
    if (a->rail == RAIL_GO) { if (search_rows(a)) a->s_results = 1; return; }
    if (a->rail == RAIL_DEL) { if (n) a->query[n - 1] = 0; }
    else if (n + 1 < sizeof a->query) {
        char c = a->rail == RAIL_SPACE ? ' ' : RAIL[a->rail];
        if (c == ' ' && (!n || a->query[n - 1] == ' ')) return;
        a->query[n] = c;
        a->query[n + 1] = 0;
    }
    run_search(a);
}

static void search_pick(app *a)
{
    int r = a->ls[V_SEARCH].sel;
    if (r < a->n_hit_artists) {
        uint32_t fi, c;
        lib_artist(a->L, a->hit_artist[r], &fi, &c);
        go_artist(a, fi);
    } else if (r - a->n_hit_artists < a->n_hits) play_one(a, a->hits[r - a->n_hit_artists].idx);
}

static uint32_t focused_track(app *a)
{
    list_state *l = &a->ls[a->view];
    if (a->view == V_TRACKS && l->sel >= a->n_actions && l->sel - a->n_actions < a->n_tracks)
        return track_at(a, l->sel - a->n_actions);
    if (a->view == V_QUEUE && l->sel < a->qn) return a->q[l->sel];
    if (a->view == V_SEARCH && a->s_results && l->sel >= a->n_hit_artists &&
        l->sel - a->n_hit_artists < a->n_hits)
        return a->hits[l->sel - a->n_hit_artists].idx;
    return LIB_NONE;
}

static void open_history(app *a)
{
    if (a->view == V_TRACKS && a->tracks_kind == TK_HISTORY) return;
    set_tracks(a, TK_HISTORY, "History");
    push(a, V_TRACKS);
}

/* hold Prev or Next and turn: the backlight's brightness, saved once you stop */
static void bright_step(app *a, int d)
{
    int lo, hi, step;
    plat_dev_range(DS_BRIGHT, &lo, &hi, &step);
    if (hi <= lo) { say(a, "Brightness isn't Coda's to set here"); return; }
    int st = (hi - lo) / 16;                       /* sixteen detents from dim to full */
    if (st < (step > 0 ? step : 1)) st = step > 0 ? step : 1;
    int v = fx_clamp(plat_dev_get(DS_BRIGHT) + d * st, lo, hi);
    plat_dev_set(DS_BRIGHT, v);
    a->bright_dirty = 1;
    a->bright_ms = a->now_ms;
    char s[40];
    int pct = (v - lo) * 100 / (hi - lo);
    snprintf(s, sizeof s, "Brightness %d%%", pct < 1 ? 1 : pct);
    say(a, s);
}

int app_chords_ok(const app *a) { return a->view != V_GAME; }

static void keys_select(app *a)
{
    switch (a->ls[V_KEYS].sel) {
    case 0: open_history(a); break;
    case 1: plat_screen_off(); break;
    case 2:
        push(a, V_SETTINGS);
        if (settings_grouped()) { a->set_group = G_SCREEN; a->ls[V_SETTINGS].sel = 0; settings_rows(a); }
        break;
    case 3: if (a->cur_valid) toggle_like(a, a->cur); else say(a, "Nothing playing"); break;
    case 4: if (a->cur_valid) dislike_current(a, a->cur); else say(a, "Nothing playing"); break;
    case 5: if (a->cur_valid) open_sheet(a, SH_NOW, a->cur); else push(a, V_QUEUE); break;
    case 6: push(a, V_QUEUE); break;
    case 7: say(a, "You're here: hold Menu anywhere"); break;
    default: say(a, "Hold Menu and Back together"); break;
    }
}

/* where the focus is: the list's row, the home's / a mosaic's panel, the sheet's item */
static int focus_of(const app *a)
{
    if (a->sheet != SH_NONE) return 1000 + a->sheet_sel;
    if (a->view == V_SETTINGS && a->set_group < 0 && settings_grouped()) return a->gl.sel;
    if (a->view == V_SEARCH && !a->s_results) return 2000 + a->rail;
    return a->ls[a->view].sel;
}

static void app_event_in(app *a, ui_ev e);

void app_event(app *a, ui_ev e)
{
    int v0 = a->view, f0 = focus_of(a), sh0 = a->sheet, g0 = a->set_group;
    a->poke_ms = a->now_ms;
    app_event_in(a, e);
    if (a->view != v0 || a->set_group != g0) {          /* a new page: everything settles in */
        if (a->skin == 7 && a->view != v0) dio_nav(a, v0, a->view);
        a->ui_view = a->view;
        a->ui_prev = -1;
        a->ui_t0 = a->now_ms;
    } else if (focus_of(a) != f0) {                     /* the focus moved: it pops, the old one sinks */
        a->ui_view = a->view;
        a->ui_prev = f0 >= 1000 ? -1 : f0;
        a->ui_t0 = a->now_ms;
    }
    if (a->sheet != SH_NONE && sh0 == SH_NONE) a->sheet_t0 = a->now_ms;
}

static void app_event_in(app *a, ui_ev e)
{
    a->force_full = 1;                             /* input always repaints */
    if (a->charge_mode && e.k != K_POWER) {        /* a button on the charge screen: the player proper */
        a->charge_mode = 0;
        plat_log("os: on from the charge screen");
        plat_charge_screen(0);
        plat_bt_boot_resume();
        return;
    }
    if (a->notice[0] && e.k != K_SCROLL) a->notice[0] = 0;
    if (e.k == K_POWER) { plat_screen_off(); return; }           /* everywhere, games too */
    if (e.k == K_HOLD_SCROLL) { bright_step(a, e.d); return; }
    if (a->view == V_GAME) { game_event(a, e); return; }   /* every button is the game's */
    if (a->sheet != SH_NONE) {
        const char *items[SHEET_MAX];
        int n = sheet_items(a, items);
        if (e.k == K_SCROLL) a->sheet_sel = fx_clamp(a->sheet_sel + e.d, 0, n - 1);
        else if (e.k == K_PLAY) sheet_select(a);
        else if (e.k == K_BACK || e.k == K_MENU) a->sheet = SH_NONE;
        else if (e.k == K_PREV || e.k == K_NEXT) { a->sheet = SH_NONE; app_event(a, e); }
        return;
    }
    if (a->adj && a->view == V_SETTINGS && settings_adjust_event(a, e)) return;
    a->adj = 0;
    if (e.k == K_MENU_LONG) {                      /* the shortcuts, all of them */
        if (a->peeking) peek_stop(a);
        if (a->view != V_KEYS) push(a, V_KEYS);
        return;
    }
    if (e.k == K_BACK_LONG) {                      /* straight to History */
        if (a->peeking) peek_stop(a);
        open_history(a);
        return;
    }
    if (e.k == K_MENU) {
        if (a->view == V_NOW && a->cur_valid) { open_sheet(a, SH_NOW, a->cur); return; }
        if (a->view == V_QUEUE && a->qn) {         /* the song under the cursor, played or to come */
            int r = a->ls[V_QUEUE].sel;
            if (r >= 0 && r < a->qn) { open_sheet(a, SH_QROW, a->q[r]); a->sheet_qpos = r; return; }
        }
        if (a->peeking) peek_stop(a);
        if (a->view == V_MENU) { if (a->section != V_MENU) push(a, a->section); }
        else { a->depth = 0; a->view = V_MENU; }
        return;
    }
    if (e.k == K_NEXT_LONG) {                      /* hold Next: "not this one" -- dislike, skip */
        if (a->peeking) peek_stop(a);
        if (a->cur_valid) dislike_current(a, a->cur);
        else say(a, "Nothing playing");
        return;
    }
    if (e.k == K_PREV || e.k == K_NEXT) {
        if (a->peeking) peek_stop(a);
        if (e.k == K_NEXT) {
            if (!skip_next(a, BRAIN_OUT_SKIP)) say(a, "That's the end of the queue");
            return;
        }
        uint32_t at = a->seek_ms && a->now_ms - a->seek_ms < 1500 ? a->seek_to : a->ps.elapsed_ms;
        if (a->cur_valid && at > 5000) {               /* past its first 5 s: Prev starts it over */
            a->seek_to = 0;
            a->seek_ms = a->now_ms ? a->now_ms : 1;
            plat_seek(0);
            return;
        }
        a->outcome = OUT_SWITCH;
        a->outcome_ms = a->now_ms;
        plat_skip(-1);
        return;
    }
    if (e.k == K_BACK) {
        if (a->view == V_SEARCH) {
            if (a->s_results) { a->s_results = 0; return; }
            size_t n = strlen(a->query);
            if (n) { a->query[n - 1] = 0; run_search(a); return; }
        }
        if (a->view == V_SETTINGS && a->set_group >= 0 && settings_grouped()) {
            a->set_group = -1;
            a->adj = 0;
            settings_rows(a);
            return;
        }
        if (a->peeking) peek_stop(a);
        pop(a);
        return;
    }
    switch (a->view) {
    case V_MENU:
        a->ls[V_MENU].n = N_MENU + rack_n(a);          /* Diorama's board: as many as you've paired */
        if (e.k == K_SCROLL) ring_scroll(&a->ls[V_MENU], e.d);
        else if (e.k == K_PLAY) menu_select(a);
        else if (e.k == K_PLAY_LONG && menu_item_at(a, a->ls[V_MENU].sel) >= N_MENU) push(a, V_BT);
        break;
    case V_WHEEL:
        if (e.k == K_SCROLL && a->n_pool) {
            int to = fx_clamp(a->target + e.d, 0, a->n_pool - 1);
            if (to == a->target) break;                /* the start (newest) or the end */
            a->target = to;
            a->spun = 1;
            a->spin_ms = a->now_ms;
            if (a->tick_sound) plat_beep(1800, 3, 600);
        } else if (e.k == K_PLAY) wheel_play(a);
        else if (e.k == K_PLAY_LONG && a->n_pool && !(a->pool[mod(a->target, a->n_pool)] & BRAIN_WHEEL_LIST))
            toggle_like(a, a->pool[mod(a->target, a->n_pool)]);
        break;
    case V_NOW:
        if (e.k == K_SCROLL && a->cur_valid) {
            int64_t base = a->seek_ms && a->now_ms - a->seek_ms < 1500 ? a->seek_to : a->ps.elapsed_ms;
            int64_t to = base + (int64_t)e.d * 5000, len = a->ps.length_ms;
            if (to < 0) to = 0;
            if (len && to > len - 1000) to = len > 1000 ? len - 1000 : 0;
            a->seek_to = (uint32_t)to;
            a->seek_ms = a->now_ms ? a->now_ms : 1;
            plat_seek(a->seek_to);
        }
        else if (e.k == K_PLAY) plat_toggle();
        else if (e.k == K_PLAY_LONG && a->cur_valid) toggle_like(a, a->cur);
        break;
    case V_LIBRARY:
        if (e.k == K_SCROLL && a->skin == 7)           /* Diorama: round the case's parts */
            a->ls[V_LIBRARY].sel = ring_step(DIO_LIB_ORDER, N_LIB, fx_clamp(a->ls[V_LIBRARY].sel, 0, N_LIB - 1), e.d);
        else if (e.k == K_SCROLL) ring_scroll(&a->ls[V_LIBRARY], e.d);
        else if (e.k == K_PLAY) library_select(a);
        break;
    case V_GAMES:
        if (e.k == K_SCROLL) ring_scroll(&a->ls[V_GAMES], e.d);
        else if (e.k == K_PLAY) { game_open(a, a->ls[V_GAMES].sel); push(a, V_GAME); }
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
    case V_TRACKS: case V_QUEUE:
        if (e.k == K_SCROLL) list_scroll(&a->ls[a->view], e.d);
        else if (e.k == K_PLAY) {
            int s = a->ls[V_QUEUE].sel;
            if (a->view == V_TRACKS) tracks_select(a);
            else if (s < a->qn) q_jump(a, s);
            else if (s == a->qn) save_queue(a);
            else push(a, V_SAVED);
        } else if (e.k == K_PLAY_LONG) {
            int s = a->ls[V_QUEUE].sel;
            if (a->view == V_QUEUE && s >= a->qn) break;
            if (a->view == V_QUEUE && s != a->qpos) { q_remove(a, s); q_topup(a); }
            else open_sheet(a, SH_TRACK, focused_track(a));
        }
        break;
    case V_EXPLORE: case V_GENRES:
        if (e.k == K_SCROLL) list_scroll(&a->ls[a->view], e.d);
        else if (e.k == K_PLAY) crates_select(a);
        break;
    case V_SAVED:
        if (e.k == K_SCROLL) list_scroll(&a->ls[V_SAVED], e.d);
        else if (e.k == K_PLAY) saved_open(a, a->ls[V_SAVED].sel);
        else if (e.k == K_PLAY_LONG) saved_forget(a, a->ls[V_SAVED].sel);
        break;
    case V_OST:
        if (e.k == K_SCROLL) {
            list_state *l = &a->ls[V_OST];
            int d = e.d > 0 ? 1 : -1, steps = abs(e.d);
            for (int k = 0; k < steps; k++) {
                int s = l->sel + d;
                while (crate_row_is_header(a, s)) s += d;
                if (s < 0 || s >= l->n) break;
                l->sel = s;
            }
            if (l->sel == 1 && crate_row_is_header(a, 0)) l->top = 0;   /* show the first divider */
        } else if (e.k == K_PLAY) crates_select(a);
        break;
    case V_SEARCH:
        if (!a->s_results) {
            if (e.k == K_SCROLL) a->rail = mod(a->rail + e.d, RAIL_N);
            else if (e.k == K_PLAY) search_type(a);
            else if (e.k == K_PLAY_LONG && search_rows(a)) a->s_results = 1;
        } else {
            if (e.k == K_SCROLL) list_scroll(&a->ls[V_SEARCH], e.d);
            else if (e.k == K_PLAY) search_pick(a);
            else if (e.k == K_PLAY_LONG) open_sheet(a, SH_TRACK, focused_track(a));
        }
        break;
    case V_CLOCK:
        if (e.k == K_SCROLL) clock_adjust(a, e.d);
        else if (e.k == K_PLAY) {
            if (a->ck_field < 4) a->ck_field++;
            else {
                int oh, om;
                plat_clock(&oh, &om);                  /* for the log: how far off it had got */
                plat_log("clock: set by hand to %04d-%02d-%02d %02d:%02d (it read %02d:%02d)",
                         a->ck[4], a->ck[3], a->ck[2], a->ck[0], a->ck[1], oh, om);
                int ok = plat_set_clock(a->ck[4], a->ck[3], a->ck[2], a->ck[0], a->ck[1]) == 0;
                pop(a);
                say(a, ok ? "Clock set" : "Set the clock in Rockbox's settings on this firmware");
            }
        }
        break;
    case V_SETTINGS:
        if (e.k == K_SCROLL) {
            if (a->set_group < 0 && settings_grouped() && a->skin == 7)   /* Diorama: round the H2's board */
                a->gl.sel = ring_step(DIO_H2_ORDER, G_COUNT, fx_clamp(a->gl.sel, 0, G_COUNT - 1), e.d);
            else if (a->set_group < 0 && settings_grouped()) { a->gl.n = G_COUNT; list_scroll(&a->gl, e.d); }
            else list_scroll(&a->ls[V_SETTINGS], e.d);
        } else if (e.k == K_PLAY) settings_select(a);
        break;
    case V_BT:
        bt_event(a, e);
        break;
    case V_KEYS:
        if (e.k == K_SCROLL) list_scroll(&a->ls[V_KEYS], e.d);
        else if (e.k == K_PLAY) keys_select(a);
        break;
    default:
        break;
    }
}

static uint32_t mix32(uint32_t h, uint32_t v) { return (h ^ v) * 16777619u; }

/* What a frame depends on besides input (input always repaints), hashed. Same hash ->
 * the screen would look the same. */
static uint32_t frame_sig(app *a)
{
    int h, m;
    plat_clock(&h, &m);
    uint32_t s = 2166136261u;
    s = mix32(s, (uint32_t)a->view);
    s = mix32(s, (uint32_t)(a->layout_b | (a->night_mode + 1) << 1 | a->viz_on << 3 | a->peeking << 4));
    s = mix32(s, (uint32_t)(h * 60 + m));
    s = mix32(s, (uint32_t)(plat_battery() * 2 + plat_charging()));
    s = mix32(s, (uint32_t)lrintf(a->s * 64.0f));
    s = mix32(s, (uint32_t)a->n_pool);
    s = mix32(s, a->cur_valid ? a->cur : 0xFFFFFFFFu);
    s = mix32(s, (uint32_t)a->ps.playing);
    s = mix32(s, (uint32_t)(a->qn << 16 | a->qpos));
    s = mix32(s, a->notice[0] ? a->notice_ms : 0);
    if (a->view != V_WHEEL) s = mix32(s, a->ps.elapsed_ms / 1000);   /* time is on screen */
    else if (a->skin == 7) s = mix32(s, (uint32_t)plat_clock_sec());  /* the clock's rotor steps */
    s = mix32(s, (uint32_t)a->why[0]);
    s = mix32(s, a->bt.gen);                                          /* Bluetooth news */
    return s;
}

static int wheel_moving(const app *a) { return a->view == V_WHEEL && a->s != (float)a->target; }

/* a pop, a flourish, the cursor sliding, the sheet coming up: under a second after input */
static int ui_moving(const app *a)
{
    return a->now_ms - a->ui_t0 < 750 || (a->cur_t0 && a->now_ms - a->cur_t0 < 220) ||
           (a->sheet != SH_NONE && a->now_ms - a->sheet_t0 < 600);
}

static int viz_live(const app *a)
{
    return a->view == V_WHEEL && a->viz_on && ((a->ps.playing && a->cur_valid) || a->peeking) &&
           a->sheet == SH_NONE;
}

static void peek_tick(app *a)
{
    if (a->peeking) {
        uint32_t f = a->n_pool ? pool_song(a, mod(a->target, a->n_pool)) : LIB_NONE;
        if (a->view != V_WHEEL || a->now_ms - a->peek_this_t0 > PEEK_MAX_MS) { peek_stop(a); return; }
        if (f == a->peek_idx || wheel_moving(a) || a->now_ms - a->spin_ms < PEEK_AFTER_MS) return;
        if (plat_input_pending()) return;          /* still turning: switching now would be stale */
        /* landed somewhere else: back to the song, or straight on to the next preview
         * (one switch, not a return trip through the song) */
        a->spun = 0;
        if (a->cur_valid && f == a->cur) peek_stop(a);
        else peek_start(a, f);
        return;
    }
    if (!a->peek_on || a->view != V_WHEEL || !a->spun || !a->n_pool || wheel_moving(a) ||
        a->now_ms - a->spin_ms < PEEK_AFTER_MS || plat_input_pending())
        return;
    uint32_t f = pool_song(a, mod(a->target, a->n_pool));
    if (f == LIB_NONE || (a->cur_valid && f == a->cur)) return;   /* already the playing song */
    a->spun = 0;                                   /* one preview per landing */
    peek_start(a, f);
}

int app_tick(app *a, uint32_t now_ms)
{
    uint32_t dt = a->last_ms ? now_ms - a->last_ms : 16;
    if (dt > 200) dt = 200;
    a->last_ms = now_ms;
    a->now_ms = now_ms;
    if (a->charge_mode) {
        if (!a->charge_t0) a->charge_t0 = now_ms ? now_ms : 1;
        /* the charge, a few seconds at the lowest brightness, then off: it charges faster and
         * costs nothing with the player off. (2: the charger woke it again at once -- stay on) */
        if (now_ms - a->charge_t0 > 6000) {
            if (a->charge_mode == 1) {
                plat_log("os: charge screen done: off, charging");
                a->charge_mode = 0;
                plat_charge_off();
            } else if (now_ms - a->charge_t0 < 7000) plat_screen_off();
        }
        if (plat_charging()) a->unplugged_ms = 0;
        else if (!a->unplugged_ms) a->unplugged_ms = now_ms ? now_ms : 1;
        else if (now_ms - a->unplugged_ms > 2000) {
            plat_log("os: unplugged on the charge screen: off");
            a->charge_mode = 0;
            plat_power_off();
        }
        if (a->force_full || now_ms - a->hub_ms >= 600) {
            a->force_full = 0;
            a->hub_ms = now_ms;
            return NEED_FULL;
        }
        return NEED_NONE;
    }
    autoplay_tick(a);
    stall_watch(a);
    peek_tick(a);
    bt_refresh(a);
    if (a->qsave_dirty || (a->ps.playing && now_ms - a->qsave_ms > QSAVE_MS)) q_save(a);
    if (a->bright_dirty && now_ms - a->bright_ms > 2000) { a->bright_dirty = 0; plat_dev_save(); }
    if (a->notice[0] && now_ms - a->notice_ms > 2600) a->notice[0] = 0;
    /* wheel: ease toward the target detent */
    float k = 1.0f - expf(-(float)dt / 55.0f);
    a->s += (a->target - a->s) * k;
    if (fabsf(a->target - a->s) < 0.004f) a->s = (float)a->target;

    if (a->view == V_GAME) return game_tick(a, now_ms);        /* its own frames */
    uint32_t sig = frame_sig(a);
    if (ui_moving(a)) a->force_full = 1;
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
    if (pet_live(a) && now_ms - a->hub_ms >= PET_MS) {        /* Bubloo, on his own */
        a->hub_ms = now_ms;
        return NEED_HUB;
    }
    return NEED_NONE;
}

int app_interval_ms(app *a)
{
    if (a->charge_mode) return 300;
    if (a->view == V_GAME) return game_interval(a);
    if (wheel_moving(a)) return 16;
    if (ui_moving(a)) return 33;                             /* the theme's motion, ~30 fps */
    if (viz_live(a)) return 50;
    if (pet_live(a)) return PET_MS;
    if (a->view == V_WHEEL && a->peek_on && a->spun) return 100;   /* waiting to peek */
    if (a->view == V_BT && (a->bt.radio == BTR_STARTING || a->bt.scanning || a->bt.link == BTL_CONNECTING))
        return 250;                                          /* the radio is busy: follow it */
    return 500;                                              /* clock + progress only */
}

int app_background_autoplay(app *a) { return a->keep_playing; }

void app_autoplay_step(app *a) { autoplay_tick(a); }
void app_force_redraw(app *a) { a->force_full = 1; }
void app_say(app *a, const char *msg) { say(a, msg); a->force_full = 1; }

void app_draw_hub(app *a, gfx *g, int rect[4])
{
    if (pet_live(a) && !viz_live(a)) {
        if (a->skin == 7 && a->view == V_MENU) dio_frame(a, g, rect);
        else if (a->skin == 7 && a->view == V_LIBRARY) dio_pc_frame(a, g, rect);
        else if (a->skin == 7 && a->view == V_SETTINGS) dio_h2_frame(a, g, rect);
        else pet_frame(a, g, rect);
        return;
    }
    wheel_frame f;
    int focused;
    wheel_frame_fill(a, &f, &focused);
    wheel_draw_hub(g, P(a), a->layout_b ? &WHEEL_B : &WHEEL_A, &f, rect);
}

void app_draw_usb(app *a, gfx *g)
{
    const palette *p = P(a);
    theme_set_night(&a->th, 0);
    g_noclip(g);
    g_fill(g, 0, 0, LCD_W, LCD_H, p->paper);
    int w = txt(a, g, F_POSTER22, 8, 23, "Coda", p->ink, T_TRACK(-5));
    g_fill(g, 8 + w + 2, 17, 6, 6, p->red);
    draw_status(a, g, LCD_W - 8, 22);
    g_fill(g, 0, 30, LCD_W, 1, p->ink);
    txt(a, g, F_POSTER22, 8, 112, "Plugged in.", p->ink, T_TRACK(-6));
    txt(a, g, F_SEMI12, 8, 134, "The card is the computer's for now.", p->blue, 0);
    txt(a, g, F_BODY10, 8, 152, "Unplug (or eject it on the computer) to come back.", p->sub, 0);
    g_fill(g, 0, BAR_Y, LCD_W, LCD_H - BAR_Y, p->strip_bg);
    txt(a, g, F_BODY10, 8, BAR_Y + 18, "Charging while connected.", p->strip_sub, 0);
}

/* ------------------------------------------------------------------ power-off: your crate
 * (docs/h2/boot/v2, C; firmware/tools/mock_boot_v2.py is the reference). The last twelve
 * records you played, butted edge to edge, with a paper band "Coda." across them; the band
 * slides away and the sleeves sink back into the crate, column by column, into black. */
#define CRATE_N 12
#define CRATE_TILE 80
#define BAND_Y 86
#define BAND_H 68

static float off_clamp(float u) { return u < 0 ? 0 : u > 1 ? 1 : u; }
static float off_in(float u) { u = off_clamp(u); return u * u * u; }
static float off_io(float u)
{
    u = off_clamp(u);
    return u < 0.5f ? 4 * u * u * u : 1 - (-2 * u + 2) * (-2 * u + 2) * (-2 * u + 2) / 2;
}
static float off_seg(uint32_t t, float a, float b) { return off_clamp(((float)t - a) / (b - a)); }

static void crate_pick(app *a, uint32_t *out)
{
    int n = brain_history(out, CRATE_N);
    if (n <= 0) {                                     /* nothing played yet: the shelf's first */
        n = 0;
        for (uint32_t i = 0; i < lib_n(a->L) && n < CRATE_N; i++) out[n++] = i;
    }
    for (int i = n; i < CRATE_N && n > 0; i++) out[i] = out[i % n];
}

/* the twelve tiles; vis(k) = how much of sleeve k is up out of the crate (0..1) */
static void crate_tiles(app *a, gfx *g, const uint32_t *cr, uint32_t t, int sinking)
{
    for (int k = 0; k < CRATE_N; k++) {
        float v = sinking ? 1 - off_in(off_seg(t, 300 + 40 * (CRATE_N - 1 - k),
                                               300 + 40 * (CRATE_N - 1 - k) + 160)) : 1;
        int h = (int)lrintf(CRATE_TILE * v);
        if (h <= 0) continue;
        int x0 = (k / 3) * CRATE_TILE, y0 = (k % 3) * CRATE_TILE;   /* column by column */
        g_clip(g, x0, y0 + CRATE_TILE - h, x0 + CRATE_TILE, y0 + CRATE_TILE);
        const px16 *tx = tex_get(a, cr[k], ART_M);
        if (tx) g_blit_scaled(g, tx, art_px[ART_M], art_px[ART_M], x0, y0 + CRATE_TILE - h,
                              CRATE_TILE, CRATE_TILE);
        else g_fill(g, x0, y0, CRATE_TILE, CRATE_TILE, C565(0xea, 0xea, 0xe3));
        g_noclip(g);
    }
}

static void crate_band(app *a, gfx *g, int x_off, const char *note, px16 note_c)
{
    const px16 paper = C565(0xf4, 0xf4, 0xf0), ink = C565(0x14, 0x14, 0x14), red = C565(0xe0, 0x30, 0x1e);
    g_fill(g, x_off, BAND_Y, LCD_W, BAND_H, paper);
    boot_wordmark(g, x_off + 10, BAND_Y + 50, ink, red, 1);
    txt(a, g, F_MONO12, x_off + LCD_W - 10 - text_w(F(a, F_MONO12), note, 0), BAND_Y + 50, note, note_c, 0);
}

void app_draw_off(app *a, gfx *g, uint32_t t, const px16 *from, int why)
{
    if (!why && a->skin > 0 && a->skin < (int)(sizeof OFFS / sizeof OFFS[0]) && OFFS[a->skin]) {
        g_noclip(g);                                    /* the theme's own way out */
        OFFS[a->skin](a, g, t, from);
        return;
    }
    static uint32_t cr[CRATE_N];
    static int picked;
    const px16 black = C565(0, 0, 0), ink = C565(0x14, 0x14, 0x14), red = C565(0xe0, 0x30, 0x1e);
    char count[40], n[24];
    commas(n, sizeof n, lib_n(a->L));
    snprintf(count, sizeof count, "%s songs", n);
    if (!picked || t == 0) { crate_pick(a, cr); picked = 1; }
    g_noclip(g);
    g_fill(g, 0, 0, LCD_W, LCD_H, black);
    if (why) {                       /* battery: the crate, said plainly, no motion */
        crate_tiles(a, g, cr, 0, 0);
        crate_band(a, g, 0, why == 2 ? "battery empty" : "battery low", red);
        return;
    }
    if (t < 140) {                   /* the screen gives way to the crate */
        crate_tiles(a, g, cr, 0, 0);
        crate_band(a, g, 0, count, ink);
        int al = (int)lrintf(256 * off_io(t / 140.0f));
        if (from)
            for (int y = 0; y < LCD_H; y++) {
                px16 *row = g->px + y * g->stride;
                for (int x = 0; x < LCD_W; x++) row[x] = blend565(from[y * LCD_W + x], row[x], al);
            }
        return;
    }
    crate_tiles(a, g, cr, t, 1);
    float bp = off_in(off_seg(t, 140, 340));
    if (bp < 1) crate_band(a, g, (int)lrintf(LCD_W * bp), count, ink);
}

/* ------------------------------------------------------------------ settings file */
static void coda_settings_save(app *a)
{
    char buf[240];
    int n = snprintf(buf, sizeof buf, "layout=%c\ntheme=%d\nticks=%d\nviz=%d\nkeep=%d\npeek=%d\nautoplay=%d\nskin=%d\n"
                     "sun=%d,%d\n", a->layout_b ? 'b' : 'a', a->night_mode, a->tick_sound, a->viz_on,
                     a->keep_playing, a->peek_on, a->autoplay_on, a->skin, sun_lat100, sun_lon100);
    plat_save("settings.txt", buf, (size_t)n);
}

static void coda_settings_load(app *a)
{
    size_t len;
    char *s = plat_load("settings.txt", &len);
    if (!s) return;
    s[len] = 0;
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
            else if (!strcmp(line, "peek")) a->peek_on = iv != 0;
            else if (!strcmp(line, "skin")) a->skin = iv >= 0 && iv < N_SKINS ? iv : 0;
            else if (!strcmp(line, "autoplay")) a->autoplay_on = iv != 0;
            else if (!strcmp(line, "sun")) {           /* where you are: lat,lon in 1/100 degree */
                char *c = strchr(v, ',');
                if (c && iv >= -9000 && iv <= 9000) {
                    int lon = (int)strtol(c + 1, NULL, 10);
                    if (lon >= -18000 && lon <= 18000) { sun_lat100 = iv; sun_lon100 = lon; }
                }
            }
        }
        line = nl ? nl + 1 : NULL;
    }
}

/* pick up whatever the player already has queued (resume after a reboot / reopening) */
static void adopt_player_queue(app *a)
{
    int pos = -1;
    int n = plat_queue_read(a->q, QMAX, &pos);
    if (n <= 0) return;
    a->qn = n;
    a->qpos = pos >= 0 && pos < n ? pos : 0;
    memset(a->qsrc, QS_USER, sizeof a->qsrc);
    plat_player(&a->ps);
    if (a->ps.active) {
        a->cur = a->ps.idx;
        a->cur_valid = 1;
        a->session[a->n_session++] = a->cur;
        a->last_elapsed = a->ps.elapsed_ms;
        a->last_len = a->ps.length_ms;
        autoplay_extend(a, (double)plat_now());
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
    plat_log("coda: %u tracks, autoplay engine v%d", (unsigned)lib_n(a->L), brain_engine());
    a->tracks = plat_alloc(sizeof(uint32_t) * TRACKS_MAX);
    crates_open(&a->cr[CK_EXPLORE], "explore.bin");
    crates_open(&a->cr[CK_OST], "osts.bin");
    crates_open(&a->cr[CK_GENRE], "genres.bin");
    size_t gl = 0;
    a->genre_of = plat_load("genre_of.bin", &gl);
    if (gl != lib_n(a->L)) a->genre_of = NULL;     /* stale: built for another pack */
    a->view = V_MENU;
    a->section = V_WHEEL;
    a->night_mode = 0;          /* day (white) by default; Settings > Theme cycles day/night/auto */
    a->tick_sound = 1;
    a->viz_on = 1;
    a->keep_playing = 1;
    a->peek_on = 1;
    a->autoplay_on = 1;
    a->skin = 0;
    a->set_group = -1;
    a->ui_view = a->cur_view = -1;
    a->ui_prev = -1;
    a->fence = -1;
    a->qpos = -1;
    a->auto_idx = LIB_NONE;
    a->peek_idx = LIB_NONE;
    rng_state ^= (uint32_t)plat_now();
    coda_settings_load(a);
    a->charge_mode = plat_charger_boot();
    if (a->charge_mode) plat_charge_screen(1);
    a->bt_has = (plat_features() & PF_BLUETOOTH) != 0;
    bt_refresh(a);
    a->force_full = 1;
    a->ls[V_MENU].n = N_MENU;
    a->ls[V_LIBRARY].n = N_LIB;
    settings_rows(a);
    adopt_player_queue(a);
    return a;
}

void app_adopt_queue(app *a)
{
    if (a->cur_valid) return;                      /* already following something */
    adopt_player_queue(a);
    a->qsave_dirty = 1;                            /* from now on it's Coda's record */
    plat_log("adopted the player's queue: %d tracks, at %d, current %d", a->qn, a->qpos + 1,
             a->cur_valid);
    a->force_full = 1;
}

void app_play(app *a, uint32_t idx) { play_one(a, idx); }
