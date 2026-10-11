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
#include "../plat/plat.h"

#define ROW_H 30
#define LIST_Y 31
#define BAR_Y 212
#define POOL_N 512                /* the Wheel: your YouTube Music history (brain_wheel) */
#define SESSION_MAX 512
#define TRACKS_MAX 4096
#define QMAX 256
#define SHELF_N 12
#define PEEK_AFTER_MS 600       /* wheel resting on a slice this long -> preview it */
#define PEEK_MAX_MS 20000
#define SKIP_INTENT_MS 2500     /* a track change this soon after Next = the listener's skip */

typedef struct { int n, sel; float top; } list_state;

typedef struct { uint32_t idx; px16 *px; uint32_t used; int ok; } tex_slot;
#define NT_S 48
#define NT_M 16
#define NT_L 3

/* what a track list holds, and what picking a row does there (web TrackList semantics):
 * "single" lists are lookups -- the pick plays and autoplay carries on from it;
 * sequences (an artist, a soundtrack, your likes) play through in order */
enum { TK_ARTIST, TK_SONGS, TK_LIKED, TK_HISTORY, TK_RESULTS, TK_SHELF, TK_OST, TK_GENRE };
enum { CK_EXPLORE, CK_OST, CK_GENRE };
enum { QS_USER, QS_AUTO };
enum { SH_NONE, SH_NOW, SH_TRACK };
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
    /* wheel peek (one decoder: the preview replaces the song, then the song comes back) */
    int peek_on, peeking, peek_was_playing, peek_was_active;
    uint32_t peek_idx, peek_saved_ms, peek_t0, peek_ignore_until;
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
    uint32_t shelf[3][SHELF_N];
    int shelf_n[3], shelves_drawn;
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
    plat_bt bt;
    plat_bt_dev bt_dev[24];
    int bt_ndev, bt_rows[32], bt_nrows;
    unsigned bt_gen_seen;
    char bt_msg_seen[64];
    /* action sheet */
    int sheet, sheet_sel;
    uint32_t sheet_idx;
    char notice[64];
    uint32_t notice_ms;
    uint32_t now_ms, last_ms;
    int tick_sound, viz_on, keep_playing;
    /* change detection: the last frame's inputs; a full redraw only when they differ */
    uint32_t drawn_sig, hub_ms;
    int force_full;
};

static const char *const menu_items[] = { "Wheel", "Now playing", "Queue", "Explore", "Search",
                                          "Library", "Liked", "Settings" };
#define N_MENU 8
static const int menu_view[N_MENU] = { V_WHEEL, V_NOW, V_QUEUE, V_EXPLORE, V_SEARCH, V_LIBRARY, -1,
                                       V_SETTINGS };
static const char *const lib_items[] = { "Songs", "Artists", "Genres", "Soundtracks", "History" };
#define N_LIB 5

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
    a->s = 0;                                      /* always opens on the newest, like the web's */
    a->target = 0;
    a->spun = 0;
}

static void set_tracks(app *a, int kind, const char *title)
{
    a->tracks_kind = kind;
    a->n_actions = kind == TK_OST ? 2 : kind == TK_GENRE ? 2 : kind == TK_SHELF ? 1 : 0;
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

static void open_view(app *a, int v)
{
    a->view = v;
    a->sheet = SH_NONE;
    if (v == V_WHEEL || v == V_NOW || v == V_EXPLORE || v == V_SEARCH || v == V_QUEUE) a->section = v;
    if (v == V_WHEEL) wheel_refresh(a);
    if (v == V_ARTISTS) a->ls[V_ARTISTS].n = (int)lib_n_artists(a->L);
    if (v == V_EXPLORE) { a->crate_kind = CK_EXPLORE; draw_shelves(a); }
    if (v == V_OST) {
        a->crate_kind = CK_OST;
        ost_rows(a);
        a->ls[V_OST].n = a->n_crate_rows;
        while (crate_row_is_header(a, a->ls[V_OST].sel)) a->ls[V_OST].sel++;
    }
    if (v == V_GENRES) { a->crate_kind = CK_GENRE; a->ls[V_GENRES].n = (int)a->cr[CK_GENRE].n; }
    if (v == V_BT) bt_open(a);
    if (v == V_QUEUE) {
        a->ls[V_QUEUE].n = a->qn;
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
}

static void play_one(app *a, uint32_t idx) { q_set(a, &idx, 1, 0, QS_USER); }

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
}

/* ------------------------------------------------------------------ autoplay */
static uint32_t genre_random(app *a, int g)
{
    const crates *c = &a->cr[CK_GENRE];
    if (g < 0 || (uint32_t)g >= c->n || !c->tab[g].count) return LIB_NONE;
    uint32_t m;
    return crate_members(c, (uint32_t)g, rnd(c->tab[g].count), &m, 1) == 1 ? m : LIB_NONE;
}

/* keep one pick queued past the end, so the player can buffer it gaplessly */
static void autoplay_extend(app *a, double now)
{
    if (!a->autoplay_on || !a->cur_valid || a->qpos != a->qn - 1) return;
    uint32_t pick = brain_next(a->cur, a->session, a->n_session - 1, BRAIN_OUT_COMPLETE, 0.0f,
                               now, a->why_auto, sizeof a->why_auto, a->genre_of, a->fence);
    if (pick == LIB_NONE && a->fence >= 0) {
        pick = genre_random(a, a->fence);
        snprintf(a->why_auto, sizeof a->why_auto, "more from this station");
    }
    if (pick == LIB_NONE) return;
    a->auto_idx = pick;
    q_add(a, pick, 0, QS_AUTO);
}

/* Engine v3: the pick queued behind this song assumed you'd let it play. An early skip
 * (or a dislike) asks again with that verdict -- the web player's skip anchor: continue
 * from the last song you kept, steer away from this one -- and plays the new pick instead.
 * Returns 1 when it handled the skip. */
static int redecide_on_skip(app *a, int outcome)
{
    if (!a->cur_valid || a->qpos + 1 != a->qn - 1 || a->qsrc[a->qpos + 1] != QS_AUTO ||
        brain_engine() < 3)
        return 0;
    uint32_t len = a->ps.length_ms, el = a->ps.elapsed_ms;
    int early = outcome == BRAIN_OUT_DISLIKE || (len ? (uint64_t)el * 100 < (uint64_t)len * 15 : el < 10000);
    if (!early) return 0;
    char why[160];
    uint32_t pick = brain_next(a->cur, a->session, a->n_session - 1, outcome, el / 1000.0f,
                               (double)plat_now(), why, sizeof why, a->genre_of, a->fence);
    if (pick == LIB_NONE || pick == a->q[a->qpos + 1]) return 0;
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
        int auto_pick = a->qsrc[at] == QS_AUTO && a->ps.idx == a->auto_idx;
        memcpy(a->why, auto_pick ? a->why_auto : "", sizeof a->why);
        plat_log("track %u (q %d/%d, auto %d) why='%s'", (unsigned)a->ps.idx, at + 1, a->qn,
                 auto_pick, a->why);
        a->cur = a->ps.idx;
        a->cur_valid = 1;
        brain_log(a->cur, EV_PLAY, 0, now);
        if (a->n_session == SESSION_MAX) {
            memmove(a->session, a->session + 1, (SESSION_MAX - 1) * sizeof a->session[0]);
            a->n_session--;
        }
        a->session[a->n_session++] = a->cur;
        autoplay_extend(a, now);
    }
    if (a->ps.active) { a->last_elapsed = a->ps.elapsed_ms; a->last_len = a->ps.length_ms; }
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
    plat_play_tracks(&idx, 1, 0, hook_ms(a, idx));
    brain_log(idx, EV_PEEK, 0, (double)plat_now());
}

static void peek_stop(app *a)
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
    if (!a->peek_was_playing) plat_toggle();
}

/* ------------------------------------------------------------------ shared chrome */
/* Battery, top right of every screen: the percentage in mono, then a flat cell drawn like
 * the rest of the poster -- ink outline, ink fill; Klein blue while charging, signal red
 * when it is nearly empty. Returns the width it took (0 when the level is unknown). */
static int draw_battery_cell(app *a, gfx *g, int x_right, int y_base)
{
    const palette *p = P(a);
    int pct = plat_battery(), chg = plat_charging();
    if (pct < 0) return 0;
    if (pct > 100) pct = 100;
    const int w = 17, h = 8, x = x_right - 2 - w, y = y_base - h;
    px16 c = chg ? p->blue : pct <= 15 ? p->red : p->ink;
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
    txt(a, g, F_MONO10, x - 4 - tw, y_base, s, chg ? p->blue : pct <= 15 ? p->red : p->sub, 0);
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

/* the battery, and left of it the Bluetooth rune while headphones are connected (Klein
 * blue; a red dot under it while sound is going to them). Returns the width taken. */
static int draw_battery(app *a, gfx *g, int x_right, int y_base)
{
    int w = draw_battery_cell(a, g, x_right, y_base);
    if (a->bt_has && a->bt.radio == BTR_ON && a->bt.link >= BTL_CONNECTED) {
        int x = x_right - w - (w ? 8 : 0) - 7;
        bt_mark(g, x, y_base + 1, P(a)->blue);
        w += 7 + (w ? 8 : 0);
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

static void draw_header(app *a, gfx *g, const char *title, const char *right)
{
    int bw = draw_battery(a, g, LCD_W - 8, 22);
    int rx = LCD_W - 8 - (bw ? bw + 10 : 0);
    int rw = right ? text_w(F(a, F_MONO10), right, 0) + 10 : 0;
    txt_fit(a, g, F_POSTER22, 8, 24, title, rx - rw - 12, P(a)->ink, T_TRACK(-5));
    if (right) txt_right(a, g, F_MONO10, rx, 22, right, P(a)->sub);
    g_fill(g, 0, 30, LCD_W, 1, P(a)->ink);
}

static void draw_nowbar(app *a, gfx *g)
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

static void dotted_leader(gfx *g, int x0, int x1, int y, px16 c)
{
    for (int x = x0; x < x1; x += 3) g_fill_a(g, x, y, 1, 1, c, 170);
}

/* one track row: cover, title, artist, a right-hand note (duration by default) */
static void track_row(app *a, gfx *g, int y, uint32_t idx, int foc, int live, int dim,
                      const char *note, px16 note_c)
{
    const palette *p = P(a);
    if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
    cover(a, g, idx, ART_S, 0, y, ROW_H);
    const lib_track *t = lib_get(a->L, idx);
    if (!t) return;
    char d[16];
    if (!note) { mmss(d, sizeof d, t->dur); note = d; note_c = p->sub; }
    int dw = text_w(F(a, F_MONO10), note, 0);
    px16 tc = foc ? p->paper : live ? p->red : dim ? p->sub : p->ink;
    int tx = ROW_H + 8;
    if (live && !foc) { g_fill(g, tx, y + 8, 5, 5, p->red); tx += 9; }
    txt_fit(a, g, F_BOLD11, tx, y + 13, t->title, LCD_W - tx - 14 - dw, tc, 0);
    txt_fit(a, g, F_BODY10, ROW_H + 8, y + 25, t->artist, LCD_W - ROW_H - 22 - dw,
            foc ? p->strip_sub : p->sub, 0);
    txt_right(a, g, F_MONO10, LCD_W - 6, y + 13, note, foc ? p->paper : note_c);
    if (!foc) g_fill(g, ROW_H, y + ROW_H - 1, LCD_W - ROW_H, 1, p->rule);
}

/* solid play triangle, h px tall, left edge at x, centred on cy */
static void play_mark(gfx *g, int x, int cy, int h, px16 c)
{
    int32_t xy[6] = { x * 16, cy * 16 - h * 8, x * 16 + h * 14, cy * 16, x * 16, cy * 16 + h * 8 };
    g_convex(g, xy, 3, c);
}

/* an action row ("Play", "Start station") at the top of a list: Klein blue, like a link */
static void action_row(app *a, gfx *g, int y, const char *label, int foc)
{
    const palette *p = P(a);
    if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
    play_mark(g, 9, y + 15, 11, foc ? p->paper : p->blue);
    txt(a, g, F_POSTER15, 26, y + 20, label, foc ? p->paper : p->blue, T_TRACK(-3));
    if (!foc) g_fill(g, 0, y + ROW_H - 1, LCD_W, 1, p->rule);
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
    int bw = draw_battery(a, g, LCD_W - 8, 22);
    txt_right(a, g, F_MONO10, LCD_W - 8 - (bw ? bw + 10 : 0), 22, s, p->sub);
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
        if (!foc && menu_view[i] == a->section) g_fill(g, 8, y + 27, ww, 2, p->blue);
        if (menu_view[i] == V_QUEUE && a->qn) {
            char c[16];
            snprintf(c, sizeof c, "%d/%d", a->qpos + 1, a->qn);
            txt_right(a, g, F_MONO10, LCD_W - 8, y + 21, c, foc ? p->paper : p->sub);
        }
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
    /* a history, not a loop: newest first, nothing before the start or past the end */
    for (int dd = -5; dd <= 5; dd++) {
        int i = b0 + dd;
        if (i < 0 || i >= n) continue;
        f->show[dd + 5] = 1;
        f->tex[dd + 5] = tex_get(a, a->pool[i], ART_M);
    }
    *focused = n ? fx_clamp(b0, 0, n - 1) : -1;
    if (*focused >= 0) f->label = tex_get(a, a->pool[*focused], ART_M);
    uint32_t fidx = *focused >= 0 ? a->pool[*focused] : LIB_NONE;
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
    int peeking_here = a->peeking && focused >= 0 && a->pool[focused] == a->peek_idx;
    const char *live = peeking_here ? "\xE2\x97\x8F peeking" : f.playing ? "\xE2\x97\x8F playing" : NULL;
    if (!a->layout_b) {
        wheel_draw(g, p, &WHEEL_A, &f);
        const int x0 = 214, x1 = 316, cy = 120, row = 40;
        int b0 = (int)lrintf(a->s);
        for (int dd = -2; dd <= 2 && a->n_pool; dd++) {
            if (dd == 0 || b0 + dd < 0 || b0 + dd >= a->n_pool) continue;
            const lib_track *t = lib_get(a->L, a->pool[b0 + dd]);
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
        if (live) txt(a, g, F_MONO10, 216, 233, live, p->red, 0);
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
        if (live) txt(a, g, F_MONO10, 4, 233, live, p->red, 0);
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
        if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
        char nm[TEXT_LINE_MAX];
        text_fit(F(a, F_POSTER22), names[i], 220, T_TRACK(-6), nm, sizeof nm);
        int w = txt(a, g, F_POSTER22, 8, y + 24, nm, foc ? p->paper : p->ink, T_TRACK(-6));
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
    char songs[24], artists[24], genres[24], osts[24];
    commas(songs, sizeof songs, lib_n(a->L));
    commas(artists, sizeof artists, lib_n_artists(a->L));
    commas(genres, sizeof genres, a->cr[CK_GENRE].n);
    commas(osts, sizeof osts, a->cr[CK_OST].n);
    const char *counts[N_LIB] = { songs, artists, genres, osts, NULL };
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

static const char *const action_labels[][2] = {
    [TK_OST] = { "Play", "Shuffle" },
    [TK_GENRE] = { "Start station", "Shuffle all" },
    [TK_SHELF] = { "Play all", NULL },
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
    list_follow(l, 6);
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    if (a->n_tracks == 0)
        txt(a, g, F_BODY10, 8, LIST_Y + 22 + a->n_actions * ROW_H, a->tracks_kind == TK_LIKED ?
            "Nothing liked yet. Hold play on any song." : "Nothing here yet.", p->sub, 0);
    int first = (int)floorf(l->top);
    for (int i = first; i < first + 8 && i < l->n; i++) {
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        if (i < a->n_actions) { action_row(a, g, y, action_labels[a->tracks_kind][i], i == l->sel); continue; }
        uint32_t idx = track_at(a, i - a->n_actions);
        track_row(a, g, y, idx, i == l->sel, a->cur_valid && idx == a->cur, 0, NULL, 0);
    }
    g_noclip(g);
    draw_nowbar(a, g);
}

/* ---- Explore: three shelves, each a title over a filmstrip of what it holds */
static void draw_shelves(app *a)
{
    if (a->shelves_drawn) return;                  /* once per run, like the web's cache */
    a->shelves_drawn = 1;
    const crates *c = &a->cr[CK_EXPLORE];
    static uint32_t pool[256];
    for (uint32_t s = 0; s < c->n && s < 3; s++) {
        int n = crate_members(c, s, 0, pool, 256);
        if (s == 0) {                              /* fresh finds stay unheard */
            int k = 0;
            for (int i = 0; i < n; i++) if (!brain_play_count(pool[i])) pool[k++] = pool[i];
            n = k;
        }
        shuffle(pool, n);
        a->shelf_n[s] = n < SHELF_N ? n : SHELF_N;
        memcpy(a->shelf[s], pool, sizeof(uint32_t) * (size_t)a->shelf_n[s]);
    }
}

static void draw_explore(app *a, gfx *g)
{
    const palette *p = P(a);
    const crates *c = &a->cr[CK_EXPLORE];
    draw_header(a, g, "Explore", NULL);
    list_state *l = &a->ls[V_EXPLORE];
    int n = (int)(c->n < 3 ? c->n : 3);
    l->n = n;
    l->sel = fx_clamp(l->sel, 0, n ? n - 1 : 0);
    if (!n) {
        txt(a, g, F_BODY10, 8, LIST_Y + 22, "Not enough listening yet. Play some music,", p->sub, 0);
        txt(a, g, F_BODY10, 8, LIST_Y + 36, "then refresh the card from the PC.", p->sub, 0);
    }
    const int H = 60;
    for (int s = 0; s < n; s++) {
        int y = LIST_Y + s * H, foc = s == l->sel;
        if (foc) g_fill(g, 0, y, LCD_W, H, p->ink);
        const crate *k = &c->tab[s];
        int w = txt(a, g, F_POSTER18, 8, y + 21, crate_str(c, k->name), foc ? p->paper : p->ink, T_TRACK(-5));
        txt_fit(a, g, F_BODY10, 8 + w + 8, y + 20, crate_str(c, k->sub), LCD_W - w - 24,
                foc ? p->strip_sub : p->sub, 0);
        for (int i = 0; i < a->shelf_n[s] && i < 9; i++)
            cover(a, g, a->shelf[s][i], ART_S, 8 + i * 34, y + 26, 32);
        if (!foc) g_fill(g, 0, y + H - 1, LCD_W, 1, p->rule);
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
        if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
        uint32_t c0 = LIB_NONE;
        crate_members(c, (uint32_t)ci, 0, &c0, 1);
        cover(a, g, c0, ART_S, 0, y, ROW_H);
        char meta[32], d[16];
        hm(d, sizeof d, k->seconds);
        snprintf(meta, sizeof meta, "%u \xC2\xB7 %s", (unsigned)k->count, d);
        int mw = text_w(F(a, F_MONO10), meta, 0);
        int w = txt_fit(a, g, F_POSTER15, ROW_H + 8, y + 20, crate_str(c, k->name), LCD_W - ROW_H - 26 - mw,
                        foc ? p->paper : p->ink, T_TRACK(-3));
        dotted_leader(g, ROW_H + 8 + w + 5, LCD_W - 10 - mw, y + 18, foc ? p->strip_sub : p->sub);
        txt_right(a, g, F_MONO10, LCD_W - 6, y + 20, meta, foc ? p->paper : p->sub);
        if (!foc) g_fill(g, ROW_H, y + ROW_H - 1, LCD_W - ROW_H, 1, p->rule);
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

/* ---- Queue */
static void draw_queue(app *a, gfx *g)
{
    const palette *p = P(a);
    list_state *l = &a->ls[V_QUEUE];
    l->n = a->qn;
    char cnt[24];
    snprintf(cnt, sizeof cnt, a->qn ? "%d of %d" : "empty", a->qpos + 1, a->qn);
    draw_header(a, g, "Queue", cnt);
    if (!a->qn) {
        txt(a, g, F_BODY10, 8, LIST_Y + 22, "Nothing queued. Play something and autoplay", p->sub, 0);
        txt(a, g, F_BODY10, 8, LIST_Y + 36, "keeps it going.", p->sub, 0);
    }
    list_follow(l, 6);
    g_clip(g, 0, LIST_Y, LCD_W, BAR_Y);
    int first = (int)floorf(l->top);
    for (int i = first; i < first + 8 && i < l->n; i++) {
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H);
        if (y + ROW_H < LIST_Y || y > BAR_Y) continue;
        int live = i == a->qpos && a->cur_valid;
        const char *note = live ? (a->ps.playing ? "playing" : "paused") :
                           a->qsrc[i] == QS_AUTO ? "autoplay" : NULL;
        track_row(a, g, y, a->q[i], i == l->sel, live, i < a->qpos, note,
                  live ? p->red : p->blue);
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
        int r = mod(a->rail + d, RAIL_N), x = cx + d * slot - slot / 2;
        int foc = d == 0;
        px16 c = foc ? p->paper : mix565(p->paper, p->ink, 256 - abs(d) * 40);
        if (foc) g_fill(g, x, y + 1, slot, h - 1, p->ink);
        char lb[4];
        rail_label(r, lb);
        if (lb[0]) txt_center(a, g, F_POSTER22, x + slot / 2, y + 26, lb, slot, c, 0);
        else if (r == RAIL_SPACE) {                /* a printer's space mark: an open box */
            g_fill(g, x + 8, y + 22, slot - 16, 2, c);
            g_fill(g, x + 8, y + 17, 2, 5, c);
            g_fill(g, x + slot - 10, y + 17, 2, 5, c);
        } else if (r == RAIL_DEL) txt_center(a, g, F_POSTER18, x + slot / 2, y + 24, "\xE2\x86\x90", slot, c, 0);
        else txt_center(a, g, F_POSTER18, x + slot / 2, y + 24, "\xE2\x86\x93", slot, foc ? p->paper : p->blue, 0);
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
            if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
            cover(a, g, fi, ART_S, 0, y, ROW_H);
            char cs[24];
            snprintf(cs, sizeof cs, "artist \xC2\xB7 %u", (unsigned)cnt);
            int cw = text_w(F(a, F_MONO10), cs, 0);
            if (t) txt_fit(a, g, F_POSTER15, ROW_H + 8, y + 20, t->artist, LCD_W - ROW_H - 24 - cw,
                           foc ? p->paper : p->ink, T_TRACK(-3));
            txt_right(a, g, F_MONO10, LCD_W - 6, y + 20, cs, foc ? p->paper : p->blue);
            if (!foc) g_fill(g, ROW_H, y + ROW_H - 1, LCD_W - ROW_H, 1, p->rule);
            continue;
        }
        uint32_t idx = a->hits[i - a->n_hit_artists].idx;
        track_row(a, g, y, idx, foc, a->cur_valid && idx == a->cur, 0, NULL, 0);
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

static void settings_rows(app *a)
{
    int f = plat_features();
    a->n_set = 0;
    for (int r = 0; r < SR_COUNT; r++) {
        if (sr_dev(r) >= 0 && !(f & PF_DEVICE)) continue;
        if (r == SR_KEEP && !(f & PF_EXIT)) continue;
        if (r == SR_BT && !(f & PF_BLUETOOTH)) continue;
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
    case SR_THEME: snprintf(o, n, "%s", a->night_mode < 0 ? "auto (dark 7pm)" : a->night_mode ? "night" : "day"); break;
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
    case SR_THEME: return "Day is light, night is dark. Auto goes dark from 7pm to 7am.";
    case SR_LAYOUT: return "A: a wheel of covers with the songs listed beside it. B: a dial, the song's name above.";
    case SR_TICKS: return "A quiet click for each step the wheel turns.";
    case SR_PEEK: return "Rest the wheel on a song for a moment to hear it. Your own song carries on when you leave.";
    case SR_VIZ: return "Bars around the wheel's centre move with the music. Off redraws less and saves battery.";
    case SR_AUTOPLAY: return "When the queue runs out, Coda carries on with songs picked from what you play and skip.";
    case SR_KEEP: return "Whether autoplay keeps picking songs once you leave Coda.";
    case SR_SCREEN: return "How long the screen stays lit after the last button press.";
    case SR_BRIGHT: return "How bright the screen is. Dimmer lasts longer on a charge.";
    case SR_POWEROFF: return "Switches off after this long paused or stopped with no buttons pressed. Never while charging.";
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

static void draw_settings(app *a, gfx *g)
{
    const palette *p = P(a);
    draw_header(a, g, "Settings", a->adj ? "turn, then Play" : NULL);
    list_state *l = &a->ls[V_SETTINGS];
    l->n = a->n_set;
    list_follow(l, SET_ROWS);
    const int help_y = LIST_Y + SET_ROWS * ROW_H;
    g_clip(g, 0, LIST_Y, LCD_W, help_y);
    for (int i = (int)floorf(l->top); i < a->n_set; i++) {
        int r = a->set_row[i];
        int y = LIST_Y + (int)lrintf((i - l->top) * ROW_H), foc = i == l->sel;
        char val[32];
        setting_value(a, r, val, sizeof val);
        /* adjusting: the value sits in a Klein-blue block, like a dial being turned */
        px16 bg = foc ? (a->adj ? p->blue : p->ink) : p->paper;
        if (foc) g_fill(g, 0, y, LCD_W, ROW_H, bg);
        txt(a, g, F_POSTER15, 8, y + 20, sr_label[r], foc ? p->paper : p->ink, T_TRACK(-3));
        if (foc && a->adj) {
            char tmp[40];
            snprintf(tmp, sizeof tmp, "< %s >", val);
            txt_right(a, g, F_MONO10, LCD_W - 8, y + 20, tmp, p->paper);
        } else txt_right(a, g, F_MONO10, LCD_W - 8, y + 20, val, foc ? p->paper : p->blue);
        if (!foc) g_fill(g, 0, y + ROW_H - 1, LCD_W, 1, p->rule);
    }
    g_noclip(g);
    if (a->n_set) {
        char lines[2][TEXT_LINE_MAX];
        int nl = text_wrap(F(a, F_BODY10), setting_help(a->set_row[l->sel]), LCD_W - 16, 2, 0, lines);
        int y = help_y + (nl > 1 ? 12 : 18);
        for (int i = 0; i < nl; i++) txt(a, g, F_BODY10, 8, y + i * 12, lines[i], p->sub, 0);
    }
    draw_nowbar(a, g);
}

/* Play on a settings row */
static void settings_select(app *a)
{
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
    int64_t z = plat_now() / 86400 + 719468, era = (z >= 0 ? z : z - 146096) / 146097;
    int64_t doe = z - era * 146097, yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    int64_t doy = doe - (365 * yoe + yoe / 4 - yoe / 100), mp = (5 * doy + 2) / 153;
    int day = (int)(doy - (153 * mp + 2) / 5 + 1), mon = (int)(mp < 10 ? mp + 3 : mp - 9);
    int year = (int)(yoe + era * 400 + (mon <= 2));
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

/* ---- Bluetooth: the switch, then remembered headphones, then what a search found, then
 * the search itself. Play connects (pairing first if needed) or disconnects the connected
 * pair; hold Play forgets a remembered one. The radio works in the background: this view
 * just redraws whenever the platform says something changed. */
enum { BTROW_POWER = -1, BTROW_PAIRED = -2, BTROW_NEARBY = -3, BTROW_SCAN = -4 };

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
                       "Search again" : "Search for headphones", foc);
            if (b->scanning) txt_right(a, g, F_MONO10, LCD_W - 8, y + 20, "stop", foc ? p->paper : p->sub);
            continue;
        }
        if (foc) g_fill(g, 0, y, LCD_W, ROW_H, p->ink);
        const char *label, *val = "";
        px16 vc = foc ? p->paper : p->blue;
        int live = 0;
        if (code == BTROW_POWER) {
            label = "Bluetooth";
            val = b->radio == BTR_ON ? "on" : b->radio == BTR_STARTING ? "starting" :
                  b->radio == BTR_STOPPING ? "turning off" : b->radio == BTR_FAILED ? "didn't start" : "off";
        } else {
            const plat_bt_dev *d = &a->bt_dev[code];
            label = d->name;
            if (bt_is_peer(a, d)) {
                val = b->link == BTL_STREAMING ? "playing" : b->link == BTL_CONNECTED ? "connected" : "connecting";
                live = b->link == BTL_STREAMING;
            } else if (!d->paired) {
                val = "pair";
            } else {
                vc = foc ? p->strip_sub : p->sub;
            }
        }
        int vw = text_w(F(a, F_MONO10), val, 0), tx = 8;
        if (live && !foc) { g_fill(g, tx, y + 11, 5, 5, p->red); tx += 10; }
        txt_fit(a, g, F_POSTER15, tx, y + 20, label, LCD_W - tx - 20 - vw, foc ? p->paper : p->ink, T_TRACK(-3));
        txt_right(a, g, F_MONO10, LCD_W - 8, y + 20, val, vc);
        if (!foc) g_fill(g, 0, y + ROW_H - 1, LCD_W, 1, p->rule);
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

/* ---- action sheet: a slab of ink rising from the bottom; focus prints paper */
static int sheet_items(app *a, const char *items[4])
{
    int liked = brain_is_liked(a->sheet_idx);
    if (a->sheet == SH_NOW) {
        items[0] = liked ? "Unlike" : "Like";
        items[1] = "Dislike, skip it";
        items[2] = "Go to artist";
        items[3] = "Queue";
    } else {
        items[0] = "Play next";
        items[1] = "Add to queue";
        items[2] = liked ? "Unlike" : "Like";
        items[3] = "Go to artist";
    }
    return 4;
}

static void draw_sheet(app *a, gfx *g)
{
    const palette *p = P(a);
    const char *items[4];
    int n = sheet_items(a, items);
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
    case V_EXPLORE: draw_explore(a, g); break;
    case V_SEARCH: draw_search(a, g); break;
    case V_OST: draw_osts(a, g); break;
    case V_GENRES: draw_genres(a, g); break;
    case V_QUEUE: draw_queue(a, g); break;
    case V_CLOCK: draw_clock(a, g); break;
    case V_BT: draw_bt(a, g); break;
    default: break;
    }
    if (a->sheet != SH_NONE) draw_sheet(a, g);
}

/* ------------------------------------------------------------------ input */
static void list_scroll(list_state *l, int d) { l->sel = fx_clamp(l->sel + d, 0, l->n > 0 ? l->n - 1 : 0); }

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
    if (idx >= fi && idx < fi + c) a->ls[V_TRACKS].sel = (int)(idx - fi);
}

static void open_sheet(app *a, int kind, uint32_t idx)
{
    if (idx == LIB_NONE) return;
    a->sheet = kind;
    a->sheet_sel = 0;
    a->sheet_idx = idx;
}

static void sheet_select(app *a)
{
    uint32_t idx = a->sheet_idx;
    int kind = a->sheet, s = a->sheet_sel;
    a->sheet = SH_NONE;
    if (kind == SH_NOW) {
        if (s == 0) toggle_like(a, idx);
        else if (s == 1) {                         /* = web dislike(): the verdict, then Next */
            brain_log(idx, EV_DISLIKE, a->ps.elapsed_ms / 1000.0f, (double)plat_now());
            a->outcome = OUT_SKIP;
            a->outcome_ms = a->now_ms;
            if (!redecide_on_skip(a, BRAIN_OUT_DISLIKE)) plat_skip(+1);
            say(a, "Disliked. Skipped.");
        } else if (s == 2) go_artist(a, idx);
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
    int s = a->ls[V_MENU].sel;
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
        if (a->tracks_kind == TK_OST || a->tracks_kind == TK_SHELF) {
            if (row == 0) q_set(a, a->tracks, a->n_tracks, 0, QS_USER);
            else play_shuffled(a, a->tracks, a->n_tracks);
        } else if (a->tracks_kind == TK_GENRE) {
            int gi = (int)a->tracks_crate;
            if (row == 0) {                        /* station: a random seed, fenced autoplay */
                uint32_t seed = a->n_tracks ? a->tracks[rnd((uint32_t)a->n_tracks)] : LIB_NONE;
                if (seed == LIB_NONE) return;
                play_one(a, seed);
                a->fence = gi;
                say(a, "Station: autoplay stays in this genre");
            } else play_shuffled(a, a->tracks, a->n_tracks);
        }
        return;
    }
    int i = row - a->n_actions;
    switch (a->tracks_kind) {
    case TK_ARTIST: case TK_LIKED: case TK_OST:    /* sequences: play on from here */
        q_set(a, a->tracks, a->n_tracks, i, QS_USER);
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
        memcpy(a->tracks, a->shelf[s], sizeof(uint32_t) * (size_t)a->shelf_n[s]);
        a->n_tracks = a->shelf_n[s];
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
    uint32_t idx = a->pool[mod(a->target, a->n_pool)];
    if (a->peeking) {
        a->peeking = 0;                            /* commit: the preview becomes the song */
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

void app_event(app *a, ui_ev e)
{
    a->force_full = 1;                             /* input always repaints */
    if (a->notice[0] && e.k != K_SCROLL) a->notice[0] = 0;
    if (a->sheet != SH_NONE) {
        const char *items[4];
        int n = sheet_items(a, items);
        if (e.k == K_SCROLL) a->sheet_sel = fx_clamp(a->sheet_sel + e.d, 0, n - 1);
        else if (e.k == K_PLAY) sheet_select(a);
        else if (e.k == K_BACK || e.k == K_MENU) a->sheet = SH_NONE;
        else if (e.k == K_PREV || e.k == K_NEXT) { a->sheet = SH_NONE; app_event(a, e); }
        return;
    }
    if (a->adj && a->view == V_SETTINGS && settings_adjust_event(a, e)) return;
    a->adj = 0;
    if (e.k == K_MENU) {
        if (a->view == V_NOW && a->cur_valid) { open_sheet(a, SH_NOW, a->cur); return; }
        if (a->peeking) peek_stop(a);
        if (a->view == V_MENU) { if (a->section != V_MENU) push(a, a->section); }
        else { a->depth = 0; a->view = V_MENU; }
        return;
    }
    if (e.k == K_PREV || e.k == K_NEXT) {
        if (a->peeking) peek_stop(a);
        if (e.k == K_NEXT) { a->outcome = OUT_SKIP; a->outcome_ms = a->now_ms; }
        else { a->outcome = OUT_SWITCH; a->outcome_ms = a->now_ms; }
        if (e.k == K_NEXT && redecide_on_skip(a, BRAIN_OUT_SKIP)) return;
        plat_skip(e.k == K_NEXT ? +1 : -1);
        return;
    }
    if (e.k == K_BACK) {
        if (a->view == V_SEARCH) {
            if (a->s_results) { a->s_results = 0; return; }
            size_t n = strlen(a->query);
            if (n) { a->query[n - 1] = 0; run_search(a); return; }
        }
        if (a->peeking) peek_stop(a);
        pop(a);
        return;
    }
    switch (a->view) {
    case V_MENU:
        if (e.k == K_SCROLL) list_scroll(&a->ls[V_MENU], e.d);
        else if (e.k == K_PLAY) menu_select(a);
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
        else if (e.k == K_PLAY_LONG && a->n_pool) toggle_like(a, a->pool[mod(a->target, a->n_pool)]);
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
    case V_TRACKS: case V_QUEUE:
        if (e.k == K_SCROLL) list_scroll(&a->ls[a->view], e.d);
        else if (e.k == K_PLAY) { if (a->view == V_TRACKS) tracks_select(a); else q_jump(a, a->ls[V_QUEUE].sel); }
        else if (e.k == K_PLAY_LONG) {
            if (a->view == V_QUEUE && a->ls[V_QUEUE].sel != a->qpos) q_remove(a, a->ls[V_QUEUE].sel);
            else open_sheet(a, SH_TRACK, focused_track(a));
        }
        break;
    case V_EXPLORE: case V_GENRES:
        if (e.k == K_SCROLL) list_scroll(&a->ls[a->view], e.d);
        else if (e.k == K_PLAY) crates_select(a);
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
                int ok = plat_set_clock(a->ck[4], a->ck[3], a->ck[2], a->ck[0], a->ck[1]) == 0;
                pop(a);
                say(a, ok ? "Clock set" : "Set the clock in Rockbox's settings on this firmware");
            }
        }
        break;
    case V_SETTINGS:
        if (e.k == K_SCROLL) list_scroll(&a->ls[V_SETTINGS], e.d);
        else if (e.k == K_PLAY) settings_select(a);
        break;
    case V_BT:
        bt_event(a, e);
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
    s = mix32(s, (uint32_t)a->why[0]);
    s = mix32(s, a->bt.gen);                                          /* Bluetooth news */
    return s;
}

static int wheel_moving(const app *a) { return a->view == V_WHEEL && a->s != (float)a->target; }

static int viz_live(const app *a)
{
    return a->view == V_WHEEL && a->viz_on && ((a->ps.playing && a->cur_valid) || a->peeking) &&
           a->sheet == SH_NONE;
}

static void peek_tick(app *a)
{
    if (a->peeking) {
        uint32_t f = a->n_pool ? a->pool[mod(a->target, a->n_pool)] : LIB_NONE;
        if (a->view != V_WHEEL || a->now_ms - a->peek_t0 > PEEK_MAX_MS) { peek_stop(a); return; }
        if (f == a->peek_idx || wheel_moving(a) || a->now_ms - a->spin_ms < PEEK_AFTER_MS) return;
        /* landed somewhere else: back to the song, or straight on to the next preview
         * (one switch, not a return trip through the song) */
        a->spun = 0;
        if (a->cur_valid && f == a->cur) peek_stop(a);
        else peek_start(a, f);
        return;
    }
    if (!a->peek_on || a->view != V_WHEEL || !a->spun || !a->n_pool || wheel_moving(a) ||
        a->now_ms - a->spin_ms < PEEK_AFTER_MS)
        return;
    uint32_t f = a->pool[mod(a->target, a->n_pool)];
    if (a->cur_valid && f == a->cur) return;       /* already the playing song */
    a->spun = 0;                                   /* one preview per landing */
    peek_start(a, f);
}

int app_tick(app *a, uint32_t now_ms)
{
    uint32_t dt = a->last_ms ? now_ms - a->last_ms : 16;
    if (dt > 200) dt = 200;
    a->last_ms = now_ms;
    a->now_ms = now_ms;
    autoplay_tick(a);
    peek_tick(a);
    bt_refresh(a);
    if (a->notice[0] && now_ms - a->notice_ms > 2600) a->notice[0] = 0;
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
    char buf[200];
    int n = snprintf(buf, sizeof buf, "layout=%c\ntheme=%d\nticks=%d\nviz=%d\nkeep=%d\npeek=%d\nautoplay=%d\n",
                     a->layout_b ? 'b' : 'a', a->night_mode, a->tick_sound, a->viz_on,
                     a->keep_playing, a->peek_on, a->autoplay_on);
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
            else if (!strcmp(line, "autoplay")) a->autoplay_on = iv != 0;
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
    a->fence = -1;
    a->qpos = -1;
    a->auto_idx = LIB_NONE;
    a->peek_idx = LIB_NONE;
    rng_state ^= (uint32_t)plat_now();
    coda_settings_load(a);
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
    plat_log("adopted the player's queue: %d tracks, at %d, current %d", a->qn, a->qpos + 1,
             a->cur_valid);
    a->force_full = 1;
}
