#include "brain.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "omp_brain.h"
#include "omp_engine3.h"
#include "omp_radio.h"
#include "omp_speeddial.h"
#include "crates.h"
#include "../plat/plat.h"

#define TAIL 50
#define PLAN_MAX 64              /* brain_plan: at most this many at once */

static omp_pack pack;
static omp_play *plays;
static int n_plays, cap_plays;
static char plays_file[260];
static uint64_t rng_state = 0x9E3779B97F4A7C15ull;
/* engine v3 (the web player's current autoplay) when the card's pack carries its data */
static omp_v3data v3;
static omp_pyrand prng;
static int prng_seeded;
/* the radio engine (the web player's autoplay since 2026-10-11) when the pack has radio.bin:
 * autoplay keeps choosing for the song you started on, the radio's seed */
static omp_radio radio;
static uint32_t radio_seed = 0xFFFFFFFFu;

/* The Wheel: what you start from and keep coming back to (scripts/player_server/wheel.py) --
 * YouTube Music's Listen again, then your own starts -- songs and lists (an album or playlist
 * from Listen again). wheel.bin (scripts/export_h2.py): "CWH2" u32 n f64 export time (this
 * clock), then n of {u32 item, f32 score} best first; an item is a pack index, or
 * BRAIN_WHEEL_LIST | i for list i of wheel_lists.bin (CRT1: name, sub = its YouTube Music id,
 * section = "Album" / "Playlist" / "Artist", members in order). A score fades by
 * WHEEL_HALFLIFE_DAYS from the export, and every song or list you start here (picks.bin:
 * "CPK1" then {f64 ts, u32 item, u32 0}, written by brain_wheel_pick) adds
 * 0.5^(age / half-life): what you keep starting climbs before the next sync. "CWH1" (pack
 * indices, most first) still loads. Without either, the speed dial over this player's own log
 * stands in. */
#define WHEEL_MAX 512
#define PICKS_MAX 512
#define WHEEL_HALFLIFE_DAYS 21.0
static uint32_t wheel_list[WHEEL_MAX];         /* the export's items, best first */
static float wheel_score[WHEEL_MAX];
static int wheel_n;
static double wheel_t0;                        /* the export's time; 0: an old file, no fading */
static uint8_t wheel_buf[WHEEL_MAX * 8];
static crates wheel_lists;
static struct { double ts; uint32_t item; } picks[PICKS_MAX];
static int n_picks;

static uint32_t rdu32(const uint8_t *b) { return b[0] | (b[1] << 8) | (b[2] << 16) | ((uint32_t)b[3] << 24); }

static int wheel_item_ok(uint32_t v)
{
    return (v & BRAIN_WHEEL_LIST) ? (v & ~BRAIN_WHEEL_LIST) < wheel_lists.n : v < pack.n;
}

static void wheel_load(void)
{
    wheel_n = 0;
    wheel_t0 = 0.0;
    crates_open(&wheel_lists, "wheel_lists.bin");
    int fd = plat_open("wheel.bin");
    if (fd >= 0) {
        uint8_t h[16];
        if (plat_pread(fd, h, 16, 0) == 16 && !memcmp(h, "CWH2", 4)) {
            uint32_t n = rdu32(h + 4);
            memcpy(&wheel_t0, h + 8, 8);
            if (n > WHEEL_MAX) n = WHEEL_MAX;
            int r = plat_pread(fd, wheel_buf, (int)n * 8, 16);
            for (int i = 0; i + 8 <= r; i += 8) {
                uint32_t v = rdu32(wheel_buf + i);
                if (!wheel_item_ok(v)) continue;
                wheel_list[wheel_n] = v;
                memcpy(&wheel_score[wheel_n], wheel_buf + i + 4, 4);
                wheel_n++;
            }
        } else if (plat_pread(fd, h, 8, 0) == 8 && !memcmp(h, "CWH1", 4)) {
            uint32_t n = rdu32(h + 4);
            if (n > WHEEL_MAX) n = WHEEL_MAX;
            int r = plat_pread(fd, wheel_buf, (int)n * 4, 8);
            for (int i = 0; i + 4 <= r; i += 4) {
                uint32_t v = rdu32(wheel_buf + i);
                if (v >= pack.n) continue;
                wheel_list[wheel_n] = v;
                wheel_score[wheel_n] = 1.0f - (float)wheel_n / (float)n;
                wheel_n++;
            }
        }
        plat_close(fd);
    }
    n_picks = 0;
    size_t len = 0;
    uint8_t *pk = plat_load("picks.bin", &len);
    if (pk && len >= 4 && !memcmp(pk, "CPK1", 4))
        for (size_t o = 4; o + 16 <= len && n_picks < PICKS_MAX; o += 16) {
            memcpy(&picks[n_picks].ts, pk + o, 8);
            picks[n_picks].item = rdu32(pk + o + 8);
            if (wheel_item_ok(picks[n_picks].item)) n_picks++;
        }
    plat_log("wheel: %d songs and lists (%d lists), %d of your starts since", wheel_n,
             (int)wheel_lists.n, n_picks);
}

void brain_wheel_pick(uint32_t item, double ts)
{
    if (!wheel_item_ok(item)) return;
    if (n_picks == PICKS_MAX) {                    /* full: the oldest go (they've faded most) */
        memmove(picks, picks + 1, (PICKS_MAX - 1) * sizeof picks[0]);
        n_picks--;
    }
    picks[n_picks].ts = ts;
    picks[n_picks].item = item;
    n_picks++;
    static uint8_t buf[4 + PICKS_MAX * 16];
    memcpy(buf, "CPK1", 4);
    for (int i = 0; i < n_picks; i++) {
        uint8_t *o = buf + 4 + 16 * i;
        memcpy(o, &picks[i].ts, 8);
        o[8] = picks[i].item & 0xFF;
        o[9] = (picks[i].item >> 8) & 0xFF;
        o[10] = (picks[i].item >> 16) & 0xFF;
        o[11] = (uint8_t)(picks[i].item >> 24);
        memset(o + 12, 0, 4);
    }
    if (plat_save("picks.bin", buf, 4 + (size_t)n_picks * 16) != 0) plat_log("wheel: couldn't save picks.bin");
}

int brain_wheel_list(uint32_t item, uint32_t *out, int cap)
{
    if (!(item & BRAIN_WHEEL_LIST)) return 0;
    return crate_members(&wheel_lists, item & ~BRAIN_WHEEL_LIST, 0, out, cap);
}

const char *brain_wheel_list_name(uint32_t item, const char **kind)
{
    uint32_t i = item & ~BRAIN_WHEEL_LIST;
    if (!(item & BRAIN_WHEEL_LIST) || i >= wheel_lists.n) return NULL;
    if (kind) *kind = crate_str(&wheel_lists, wheel_lists.tab[i].section);
    return crate_str(&wheel_lists, wheel_lists.tab[i].name);
}

uint32_t brain_wheel_song(uint32_t item)
{
    if (!(item & BRAIN_WHEEL_LIST)) return item;
    uint32_t first;
    return brain_wheel_list(item, &first, 1) == 1 ? first : 0xFFFFFFFFu;
}

static double wheel_fade(double age_s)
{
    return pow(0.5, (age_s > 0.0 ? age_s : 0.0) / (WHEEL_HALFLIFE_DAYS * 86400.0));
}

static double rng01(void *s)
{
    (void)s;
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return (double)(rng_state >> 11) * (1.0 / 9007199254740992.0);
}

int brain_open(const char *pack_dir, const char *plays_path)
{
    if (!plat_ram_rich() || omp_pack_open(&pack, pack_dir, OMP_PACK_STREAM) != 0)
        if (omp_pack_open(&pack, pack_dir, OMP_PACK_STREAM_ALL) != 0) return -1;
    snprintf(plays_file, sizeof plays_file, "%s", plays_path);
    n_plays = omp_playlog_load(plays_path, &plays);
    if (n_plays < 0) n_plays = 0;
    cap_plays = n_plays;
    if (omp_v3_load(&v3, pack_dir, pack.n) != 0) memset(&v3, 0, sizeof v3);
    if (omp_radio_load(&radio, pack_dir, pack.n) != 0) memset(&radio, 0, sizeof radio);
    wheel_load();
    return 0;
}

int brain_engine(void) { return radio.ok ? 4 : v3.ok ? 3 : 1; }

void brain_radio_seed(uint32_t idx) { radio_seed = idx; }

uint32_t brain_n(void) { return pack.n; }
const void *brain_pack(void) { return &pack; }
uint16_t brain_duration(uint32_t idx) { return idx < pack.n ? omp_pack_track(&pack, idx)->duration_s : 0; }

int brain_id(uint32_t idx, char out[11])
{
    const char *id = idx < pack.n ? omp_pack_id(&pack, idx) : NULL;
    if (!id) return 0;
    memcpy(out, id, 11);
    return 1;
}

uint32_t brain_find(const char id[11]) { return omp_pack_find_id(&pack, id); }

void brain_log(uint32_t idx, int event, float seconds, double ts)
{
    if (n_plays == cap_plays) {
        cap_plays = cap_plays ? cap_plays * 2 : 256;
        plays = realloc(plays, (size_t)cap_plays * sizeof *plays);
    }
    omp_play ev = { ts, idx, seconds, (uint8_t)event };
    plays[n_plays++] = ev;
    omp_playlog_append(plays_file, &ev);
}

int brain_wheel(uint32_t *out, int n, double now)
{
    if (wheel_n || n_picks) {
        static uint32_t item[WHEEL_MAX + PICKS_MAX];
        static double score[WHEEL_MAX + PICKS_MAX];
        int m = 0;
        double fade = wheel_t0 > 0.0 ? wheel_fade(now - wheel_t0) : 1.0;
        for (int i = 0; i < wheel_n; i++) { item[m] = wheel_list[i]; score[m++] = wheel_score[i] * fade; }
        for (int p = 0; p < n_picks; p++) {
            if (picks[p].ts <= wheel_t0) continue;     /* counted in the export already */
            int at = -1;
            for (int i = 0; i < m; i++) if (item[i] == picks[p].item) { at = i; break; }
            if (at < 0) { at = m++; item[at] = picks[p].item; score[at] = 0.0; }
            score[at] += wheel_fade(now - picks[p].ts);
        }
        /* best first; a stable insertion sort keeps the export's order among equals */
        for (int i = 1; i < m; i++) {
            uint32_t vi = item[i];
            double si = score[i];
            int j = i - 1;
            while (j >= 0 && score[j] < si) { item[j + 1] = item[j]; score[j + 1] = score[j]; j--; }
            item[j + 1] = vi;
            score[j + 1] = si;
        }
        int k = m < n ? m : n;
        memcpy(out, item, (size_t)k * sizeof *out);
        return k;
    }
    /* the core's prefs treat unknown events as 0-weight; unlike is filtered here */
    return omp_speeddial(&pack, plays, n_plays, now, n < 24 ? n : 24, 1, rng01, NULL, out);
}

static const char *term_phrase(int t)
{
    switch (t) {
    case OMP_T_VIBE: return "sounds like what's playing";
    case OMP_T_MOOD: return "fits this session's mood";
    case OMP_T_TASTE: return "close to your overall taste";
    case OMP_T_PREF_TRACK: return "you keep coming back to it";
    case OMP_T_PREF_ARTIST: return "an artist you play a lot";
    case OMP_T_NOVELTY: return "new to you";
    default: return NULL;
    }
}

static uint32_t next_v1(uint32_t cur, const uint32_t *played, int n_played, double now,
                        char *why, size_t whysz, const uint8_t *genre_of, int fence)
{
    omp_prefs prefs;
    static float taste[OMP_DIM], skipv[OMP_DIM];   /* off the 7.5KB H2 plugin stack */
    omp_prefs_compute(&pack, plays, n_plays, now, OMP_HALFLIFE_DAYS, &prefs);
    int ht = omp_taste_centroid(&pack, &prefs, taste);
    int hs = omp_skip_centroid(&pack, &prefs, skipv);
    const uint32_t *tail = played + (n_played > TAIL ? n_played - TAIL : 0);
    int n_tail = n_played > TAIL ? TAIL : n_played;
    omp_ranked *ranked = malloc((size_t)pack.k * sizeof *ranked);
    int n_ranked = 0;
    omp_pick_reason reason;
    uint32_t pick = omp_next_track(&pack, &prefs, ht ? taste : NULL, hs ? skipv : NULL,
                                   tail, n_tail, cur, 0.15, rng01, NULL, &reason,
                                   ranked, &n_ranked);
    if (fence >= 0 && genre_of && (pick == 0xFFFFFFFFu || genre_of[pick] != fence)) {
        /* genre station: the best-ranked neighbour inside the genre, not just played */
        pick = 0xFFFFFFFFu;
        reason = OMP_PICK_EXPLOIT;
        for (int i = 0; i < n_ranked && pick == 0xFFFFFFFFu; i++) {
            uint32_t c = ranked[i].idx;
            int recent = c == cur;
            for (int j = 0; j < n_tail && !recent; j++) recent = tail[j] == c;
            if (!recent && genre_of[c] == fence) pick = c;
        }
    }
    if (why && whysz) {
        why[0] = 0;
        const omp_ranked *pr = NULL;
        for (int i = 0; i < n_ranked; i++)
            if (ranked[i].idx == pick) { pr = &ranked[i]; break; }
        if (reason == OMP_PICK_FALLBACK_GENRE) snprintf(why, whysz, "more of the same genre");
        else if (reason == OMP_PICK_FALLBACK_RANDOM) snprintf(why, whysz, "a random pick");
        else if (pr) {
            /* the two biggest positive terms, in plain words */
            int a = -1, b = -1;
            for (int t = 0; t < OMP_T_COUNT; t++) {
                if (!term_phrase(t) || pr->terms[t] <= 0.005f) continue;
                if (a < 0 || pr->terms[t] > pr->terms[a]) { b = a; a = t; }
                else if (b < 0 || pr->terms[t] > pr->terms[b]) b = t;
            }
            const char *lead = reason == OMP_PICK_EXPLORE_UNHEARD ? "a step off the path: " :
                               reason == OMP_PICK_EXPLORE_RANDOM ? "a wildcard: " : "";
            if (a >= 0 && b >= 0) snprintf(why, whysz, "%s%s, %s", lead, term_phrase(a), term_phrase(b));
            else if (a >= 0) snprintf(why, whysz, "%s%s", lead, term_phrase(a));
        }
    }
    free(ranked);
    omp_prefs_free(&prefs);
    return pick;
}

int brain_is_liked(uint32_t idx)
{
    for (int i = n_plays - 1; i >= 0; i--)
        if (plays[i].idx == idx && (plays[i].event == OMP_EV_LIKE || plays[i].event == EV_UNLIKE))
            return plays[i].event == OMP_EV_LIKE;
    return 0;
}

int brain_liked(uint32_t *out, int cap)
{
    int n = 0;
    for (int i = n_plays - 1; i >= 0 && n < cap; i--) {
        if (plays[i].event != OMP_EV_LIKE && plays[i].event != EV_UNLIKE) continue;
        int seen = 0;
        for (int j = i + 1; j < n_plays && !seen; j++)
            seen = plays[j].idx == plays[i].idx &&
                   (plays[j].event == OMP_EV_LIKE || plays[j].event == EV_UNLIKE);
        if (!seen && plays[i].event == OMP_EV_LIKE) out[n++] = plays[i].idx;
    }
    return n;
}

int brain_history(uint32_t *out, int cap)
{
    int n = 0;
    for (int i = n_plays - 1; i >= 0 && n < cap; i--) {
        if (plays[i].event != OMP_EV_PLAY) continue;
        int dup = 0;
        for (int j = 0; j < n && !dup; j++) dup = out[j] == plays[i].idx;
        if (!dup) out[n++] = plays[i].idx;
    }
    return n;
}

int brain_disliked(uint32_t idx)
{
    for (int i = n_plays - 1; i >= 0; i--)
        if (plays[i].idx == idx && (plays[i].event == OMP_EV_DISLIKE || plays[i].event == OMP_EV_LIKE))
            return plays[i].event == OMP_EV_DISLIKE;
    return 0;
}

int brain_play_count(uint32_t idx)
{
    int c = 0;
    for (int i = 0; i < n_plays; i++) c += plays[i].idx == idx && plays[i].event == OMP_EV_PLAY;
    return c;
}

int brain_bpm10(uint32_t idx) { return v3.ok && v3.bpm10 && idx < v3.n ? v3.bpm10[idx] : 0; }
int brain_ytm_plays(uint32_t idx) { return v3.ok && v3.hist_n && idx < v3.n ? v3.hist_n[idx] : 0; }

/* a song's vibe, for Diorama's wall: its energy (0..254, -1 unknown), its tempo x10, and
 * where its sound (its cluster) sits from the calmest to the most driven, 0..15 (-1
 * unknown) -- the clusters ranked once by their songs' mean energy */
#define VIBE_CL 64
int brain_vibe(uint32_t idx, int *energy, int *bpm10, int *rank)
{
    static int8_t cl_rank[VIBE_CL];
    static int ranked;
    *energy = v3.ok && v3.energy && idx < v3.n && v3.energy[idx] != 255 ? v3.energy[idx] : -1;
    *bpm10 = brain_bpm10(idx);
    *rank = -1;
    if (!v3.ok || !v3.cluster || !v3.energy || idx >= v3.n) return *energy >= 0;
    if (!ranked) {
        static uint32_t sum[VIBE_CL], cnt[VIBE_CL];
        int nc = 0;
        for (uint32_t i = 0; i < v3.n; i++) {
            uint16_t c = v3.cluster[i];
            if (c >= VIBE_CL || v3.energy[i] == 255) continue;
            sum[c] += v3.energy[i];
            cnt[c]++;
            if (c + 1 > nc) nc = c + 1;
        }
        for (int c = 0; c < VIBE_CL; c++) cl_rank[c] = -1;
        for (int c = 0; c < nc; c++) {
            if (!cnt[c]) continue;
            int below = 0, used = 0;                      /* how many clusters are calmer */
            for (int o = 0; o < nc; o++) {
                if (!cnt[o]) continue;
                used++;
                if ((uint64_t)sum[o] * cnt[c] < (uint64_t)sum[c] * cnt[o] || (sum[o] * cnt[c] == sum[c] * cnt[o] && o < c)) below++;
            }
            cl_rank[c] = (int8_t)(used > 1 ? below * 15 / (used - 1) : 7);
        }
        ranked = 1;
    }
    uint16_t c = v3.cluster[idx];
    if (c < VIBE_CL) *rank = cl_rank[c];
    return 1;
}

void brain_heard_bits(uint8_t *bits, uint32_t n)
{
    memset(bits, 0, (n + 7) / 8);
    for (uint32_t i = 0; i < n; i++)
        if (brain_ytm_plays(i) > 0) bits[i >> 3] |= (uint8_t)(1u << (i & 7));
    for (int i = 0; i < n_plays; i++)
        if (plays[i].idx < n) bits[plays[i].idx >> 3] |= (uint8_t)(1u << (plays[i].idx & 7));
}

/* ------------------------------------------------------------------ engine v3 */
static const char *term3_phrase(int t)
{
    switch (t) {
    case OMP_T_VIBE: return "sounds like what's playing";
    case OMP_T_MOOD: return "fits this session's mood";
    case OMP_T_TASTE: return "close to your overall taste";
    case OMP_T_PREF_TRACK: return "you keep coming back to it";
    case OMP_T_PREF_ARTIST: return "an artist you like";
    case OMP_T_NOVELTY: return "new to you";
    case OMP_T3_COOC: return "on this song's radio";
    default: return NULL;
    }
}

static uint32_t next_v3(uint32_t cur, const uint32_t *played, int n_played, int outcome,
                        float secs, double now, char *why, size_t whysz,
                        const uint8_t *genre_of, int fence)
{
    if (!prng_seeded) { pyr_seed_u64(&prng, (uint64_t)now); prng_seeded = 1; }
    omp_prefs3 pr;
    if (omp_prefs3_compute(&pack, &v3, plays, n_plays, now, &pr) != 0) return 0xFFFFFFFFu;
    static float taste[OMP_DIM], skipv[OMP_DIM];
    int ht = omp_taste3(&pack, &v3, &pr, taste), hs = omp_skip3(&pack, &pr, skipv);
    omp_ranked3 *rk = malloc((size_t)(pack.k + 64) * sizeof *rk);
    if (!rk) { omp_prefs3_free(&pr); return 0xFFFFFFFFu; }
    omp_v3_params P = omp_v3_default_params();
    omp_decision dec;
    const uint32_t *ex = played + (n_played > TAIL ? n_played - TAIL : 0);
    int n_ex = n_played > TAIL ? TAIL : n_played;
    omp_next_v3(&pack, &v3, &pr, ht ? taste : NULL, hs ? skipv : NULL, plays, n_plays, ex, n_ex,
                cur, outcome, secs, now, &P, &prng, rk, &dec);
    uint32_t pick = dec.pick;
    int reason = dec.reason;
    if (fence >= 0 && genre_of && (pick == 0xFFFFFFFFu || genre_of[pick] != fence)) {
        pick = 0xFFFFFFFFu;                       /* genre station: best in-genre neighbour */
        reason = OMP_PICK_EXPLOIT;
        for (int i = 0; i < dec.n_ranked && pick == 0xFFFFFFFFu; i++)
            if (genre_of[rk[i].idx] == fence) pick = rk[i].idx;
    }
    if (why && whysz) {
        why[0] = 0;
        const omp_ranked3 *r = NULL;
        for (int i = 0; i < dec.n_ranked; i++) if (rk[i].idx == pick) { r = &rk[i]; break; }
        if (r) {
            int a = -1, b = -1;
            for (int t = 0; t < OMP_T3_COUNT; t++) {
                if (!term3_phrase(t) || r->terms[t] <= 0.0f) continue;
                if (a < 0 || r->terms[t] > r->terms[a]) { b = a; a = t; }
                else if (b < 0 || r->terms[t] > r->terms[b]) b = t;
            }
            const char *lead = reason == OMP_PICK_EXPLORE_UNHEARD ? "a step off the path: " :
                               reason == OMP_PICK_EXPLORE_RANDOM ? "a wildcard: " : "";
            if (dec.anchor != cur && reason == OMP_PICK_EXPLOIT) lead = "back toward what you kept: ";
            if (a >= 0 && b >= 0) snprintf(why, whysz, "%s%s, %s", lead, term3_phrase(a), term3_phrase(b));
            else if (a >= 0) snprintf(why, whysz, "%s%s", lead, term3_phrase(a));
        }
    }
    free(rk);
    omp_prefs3_free(&pr);
    return pick;
}

static int has_idx(const uint32_t *a, int n, uint32_t v)
{
    for (int i = 0; i < n; i++) if (a[i] == v) return 1;
    return 0;
}

/* a skip short of the end (radio.KEEP_FRAC); unknown length or position: any skip */
static int short_of(uint32_t v, float secs)
{
    float d = omp_pack_track(&pack, v)->duration_s;
    return d <= 0.0f || secs < 0.0f || secs / d < OMP_RADIO_KEEP_FRAC;
}

/* the radio's reading of the sitting (server.next_decision, radio branch): the songs of the
 * tail turned down in the last 3 hours -- a dislike, or any skip short of the end; a later
 * finish or like clears it. cur's own outcome comes with the call. */
static int radio_down(const uint32_t *tail, int nt, uint32_t cur, int outcome, float secs,
                      double now, uint32_t *out)
{
    int lo = n_plays, n = 0;
    while (lo > 0 && plays[lo - 1].ts > now - 3 * 3600.0) lo--;
    for (int t = 0; t < nt; t++) {
        uint32_t v = tail[t];
        if (v >= pack.n || has_idx(tail, t, v)) continue;
        int state = 0;                                    /* 0 no verdict / kept, 1 skip, 2 dislike */
        for (int i = lo; i < n_plays; i++) {
            const omp_play *p = &plays[i];
            if (p->idx != v) continue;
            if (p->event == OMP_EV_DISLIKE) state = 2;
            else if (p->event == OMP_EV_COMPLETE || p->event == OMP_EV_LIKE) state = 0;
            else if (p->event == OMP_EV_SKIP && state != 2) state = short_of(v, p->seconds);
        }
        if (v == cur) {
            if (outcome == BRAIN_OUT_DISLIKE) state = 2;
            else if (outcome == BRAIN_OUT_SKIP && state != 2) state = short_of(v, secs);
            else if (outcome == BRAIN_OUT_COMPLETE) state = 0;
        }
        if (state) out[n++] = v;
    }
    return n;
}

/* radio.fresh_seed: one of your most played lately (the Wheel's order) with a radio of its
 * own, sounding no closer than OMP_RADIO_AWAY_SIM to what you turned down, and of those the
 * one most like what you kept this sitting (home) -- the vibe you were in, from somewhere
 * else in your music. With nothing kept, the first of them also away from the old seed.
 * Failing all that, the least like what you turned down. */
static float dot512(const float *a, const float *b)
{
    float d = 0.0f;
    for (int q = 0; q < OMP_DIM; q++) d += a[q] * b[q];
    return d;
}

static uint32_t fresh_seed(const uint32_t *down, int nd, uint32_t seed, const uint32_t *never, int nn,
                           const uint32_t *home, int nh)
{
    static float va[14][OMP_DIM], vh[12][OMP_DIM], v[OMP_DIM];
    int na = 0, nhv = 0;
    for (int j = 0; j < nh && nhv < 12; j++) if (omp_pack_vec(&pack, home[j], vh[nhv]) == 0) nhv++;
    for (int j = 0; j < nd && na < 13; j++) if (omp_pack_vec(&pack, down[j], va[na]) == 0) na++;
    if (!nhv && seed < pack.n && omp_pack_vec(&pack, seed, va[na]) == 0) na++;
    uint32_t best = 0xFFFFFFFFu, best_home = 0xFFFFFFFFu;
    float best_near = 1e30f, best_like = -1e30f;
    for (int i = 0, seen = 0; i < wheel_n && seen < OMP_RADIO_RESEED_POOL; i++) {
        uint32_t x = wheel_list[i];
        if ((x & BRAIN_WHEEL_LIST) || x >= pack.n || x == seed || has_idx(down, nd, x) || has_idx(never, nn, x) ||
            !radio.count[x] || omp_pack_vec(&pack, x, v) != 0)
            continue;
        seen++;
        float near = -1e30f;
        for (int j = 0; j < na; j++) { float d = dot512(v, va[j]); if (d > near) near = d; }
        if (!na || near < OMP_RADIO_AWAY_SIM) {
            if (!nhv) return x;
            float like = -1e30f;
            for (int j = 0; j < nhv; j++) { float d = dot512(v, vh[j]); if (d > like) like = d; }
            if (like > best_like) { best_like = like; best_home = x; }
        } else if (near < best_near) { best_near = near; best = x; }
    }
    return best_home != 0xFFFFFFFFu ? best_home : best;
}

/* server._radio_decision: the next songs of the seed's radio (the song you started; without
 * one, the current song): n_out of them, each planned as if the ones before it had played
 * (radio.sequence building a queue at once), after the `ahead` songs already queued. The
 * station stays the seed's: skips steer it (turned down for the sitting), they don't move it.
 * With OMP_RADIO_RESEED on, a turned-down seed would follow the last song you kept since it
 * started and, with none or after OMP_RADIO_STREAK turned down in a row, a fresh seed. */
static int next_radio(uint32_t cur, const uint32_t *played, int n_played, const uint32_t *ahead,
                      int n_ahead, int outcome, float secs, double now, uint32_t *out, int n_out,
                      char *why, size_t whysz)
{
    const uint32_t *ex = played + (n_played > TAIL ? n_played - TAIL : 0);
    int n_ex = n_played > TAIL ? TAIL : n_played;
    uint32_t tail[12], rej[13], anchor, down[13];
    int nt = 0;
    omp_v3_sitting(&pack, plays, n_plays, ex, n_ex, cur, outcome, secs, now, tail, &nt, rej, &anchor);
    int nd = radio_down(tail, nt, cur, outcome, secs, now, down);
    /* never again: the sitting, this song, anything played in the last 6 hours, what's queued */
    static uint32_t never[TAIL + 3 + 256 + 2 * PLAN_MAX], known[256];
    int nn = 0, nk = 0;
    for (int i = 0; i < n_ex; i++) never[nn++] = ex[i];
    never[nn++] = cur;
    for (int i = n_plays - 1; i >= 0; i--) {
        const omp_play *p = &plays[i];
        if (p->event == OMP_EV_PLAY && p->ts > now - 6 * 3600.0 && nn < (int)(sizeof never / 4) - 1 &&
            !has_idx(never, nn, p->idx))
            never[nn++] = p->idx;
        if ((p->event == OMP_EV_COMPLETE || p->event == OMP_EV_LIKE) && nk < 256 &&
            !has_idx(known, nk, p->idx))
            known[nk++] = p->idx;                  /* you know it: the familiar mix counts it */
    }
    uint32_t seed = radio_seed < pack.n ? radio_seed : cur;
    int streak = 0, fresh = 0;
    while (streak < nt && has_idx(down, nd, tail[nt - 1 - streak])) streak++;
    uint32_t home[12];                             /* what you kept this sitting: the vibe a fresh seed keeps */
    int nh = 0;
    for (int i = 0; i < nt && nh < 12; i++) if (!has_idx(down, nd, tail[i])) home[nh++] = tail[i];
    uint32_t kept = 0xFFFFFFFFu;
    if (has_idx(down, nd, seed)) {                 /* radio.station_anchor */
        int from = 0;
        for (int i = nt - 1; i >= 0; i--) if (tail[i] == seed) { from = i + 1; break; }
        for (int i = nt - 1; i >= from; i--)
            if (tail[i] != seed && !has_idx(down, nd, tail[i])) { kept = tail[i]; break; }
    }
    /* each full run of OMP_RADIO_STREAK (radio.reseed_now): the fourth skip is the fresh seed's
     * first pick, not three more */
    if (OMP_RADIO_RESEED &&
        ((streak > 0 && streak % OMP_RADIO_STREAK == 0) || (has_idx(down, nd, seed) && kept == 0xFFFFFFFFu))) {
        uint32_t f = fresh_seed(down, nd, seed, never, nn, home, nh);
        if (f != 0xFFFFFFFFu) {
            plat_log("radio: %d turned down, a fresh seed: %s", nd,
                     omp_pack_str(&pack, omp_pack_track(&pack, f)->title_off));
            seed = radio_seed = f;
            fresh = 1;
        }
    }
    if (OMP_RADIO_RESEED && !fresh && has_idx(down, nd, seed))
        seed = kept != 0xFFFFFFFFu ? kept : (!has_idx(down, nd, anchor) ? anchor : seed);
    (void)streak; (void)home; (void)kept;
    never[nn++] = seed;
    /* what's queued already counts as heard: the shares spread over the whole queue */
    for (int i = 0; i < n_ahead && i < PLAN_MAX; i++) {
        if (nt == 12) { memmove(tail, tail + 1, 11 * sizeof tail[0]); nt--; }
        tail[nt++] = ahead[i];
        if (!has_idx(never, nn, ahead[i])) never[nn++] = ahead[i];
    }
    int got = 0;
    if (n_out > PLAN_MAX) n_out = PLAN_MAX;
    while (got < n_out) {
        uint32_t pick = omp_radio_next(&radio, &pack, seed, tail, nt, never, nn, down, nd, known, nk);
        if (pick == 0xFFFFFFFFu) break;
        out[got++] = pick;
        if (nt == 12) { memmove(tail, tail + 1, 11 * sizeof tail[0]); nt--; }
        tail[nt++] = pick;
        never[nn++] = pick;
    }
    if (got && why && whysz) {
        const char *t = omp_pack_str(&pack, omp_pack_track(&pack, seed)->title_off);
        snprintf(why, whysz, "%s %s", fresh ? "Changing it up: on the radio for" : "on the radio for",
                 t && *t ? t : "the song you started");
    }
    return got;
}

int brain_plan(uint32_t cur, const uint32_t *played, int n_played, const uint32_t *ahead, int n_ahead,
               int outcome, float secs, double now, uint32_t *out, int n_out, char *why, size_t whysz)
{
    if (!radio.ok || cur >= pack.n) return 0;
    return next_radio(cur, played, n_played, ahead, n_ahead, outcome, secs, now, out, n_out, why, whysz);
}

uint32_t brain_next(uint32_t cur, const uint32_t *played, int n_played, int outcome, float secs,
                    double now, char *why, size_t whysz, const uint8_t *genre_of, int fence)
{
    if (radio.ok && fence < 0 && cur < pack.n) {   /* genre stations keep the walk, as on the web */
        uint32_t pick;
        if (next_radio(cur, played, n_played, NULL, 0, outcome, secs, now, &pick, 1, why, whysz) == 1)
            return pick;
    }
    if (v3.ok) {
        uint32_t pick = next_v3(cur, played, n_played, outcome, secs, now, why, whysz, genre_of, fence);
        if (pick != 0xFFFFFFFFu) return pick;
    }
    return next_v1(cur, played, n_played, now, why, whysz, genre_of, fence);
}
