#include "brain.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "omp_brain.h"
#include "omp_engine3.h"
#include "omp_speeddial.h"
#include "../plat/plat.h"

#define TAIL 50

static omp_pack pack;
static omp_play *plays;
static int n_plays, cap_plays;
static char plays_file[260];
static uint64_t rng_state = 0x9E3779B97F4A7C15ull;
/* engine v3 (the web player's current autoplay) when the card's pack carries its data */
static omp_v3data v3;
static omp_pyrand prng;
static int prng_seeded;

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
    return 0;
}

int brain_engine(void) { return v3.ok ? 3 : 1; }

uint32_t brain_n(void) { return pack.n; }
const void *brain_pack(void) { return &pack; }
uint16_t brain_duration(uint32_t idx) { return idx < pack.n ? omp_pack_track(&pack, idx)->duration_s : 0; }

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
    /* the core's prefs treat unknown events as 0-weight; unlike is filtered here */
    return omp_speeddial(&pack, plays, n_plays, now, n, 1, rng01, NULL, out);
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

int brain_play_count(uint32_t idx)
{
    int c = 0;
    for (int i = 0; i < n_plays; i++) c += plays[i].idx == idx && plays[i].event == OMP_EV_PLAY;
    return c;
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

uint32_t brain_next(uint32_t cur, const uint32_t *played, int n_played, int outcome, float secs,
                    double now, char *why, size_t whysz, const uint8_t *genre_of, int fence)
{
    if (v3.ok) {
        uint32_t pick = next_v3(cur, played, n_played, outcome, secs, now, why, whysz, genre_of, fence);
        if (pick != 0xFFFFFFFFu) return pick;
    }
    return next_v1(cur, played, n_played, now, why, whysz, genre_of, fence);
}
