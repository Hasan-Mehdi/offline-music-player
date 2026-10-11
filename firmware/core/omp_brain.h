/* The autoplay brain — a line-for-line port of scripts/personalize.py plus the
 * session-context assembly from server.py /api/next. Kept numerically parallel
 * to the Python (double scalar math, float32 embedding dots) so the golden-trace
 * parity tests in firmware/host/ can hold it to tight tolerances.
 *
 * Differences from the web player, by design:
 *  - tracks are dense u32 pack indices, not video_id strings
 *  - artists are identified by their interned strings.bin offset
 *  - durations come from the pack's u16 seconds (goldens use the same truncation)
 */
#ifndef OMP_BRAIN_H
#define OMP_BRAIN_H

#include "omp_map.h"
#include "omp_pack.h"
#include "omp_playlog.h"

/* --- signal thresholds (personalize.py) --- */
#define OMP_STRONG_SKIP 0.15
#define OMP_LATE_OK 0.80
#define OMP_HALFLIFE_DAYS 30.0
#define OMP_SESSION_GAP_SECONDS (30.0 * 60.0)
#define OMP_EARLY_SESSION_TRACKS 3
#define OMP_EARLY_SKIP_FACTOR 0.5

typedef struct {
    double alpha, delta, gamma, gamma_artist, sigma, cooldown, nu, rho, rho_floor, mu;
} omp_rank_params;

/* The rank_next defaults. */
omp_rank_params omp_default_params(void);

/* Rolled-up preference state (compute_prefs). Sparse: only tracks/artists that
 * appear in the log have entries (absent = 0), so memory follows the history, not
 * the library -- the H2 plugin has 2 MiB for everything. Artists are keyed by
 * interned artist offset, tracks by pack index. */
typedef struct {
    omp_map track_pref;       /* idx -> signed, recency-decayed */
    omp_map play_counts;      /* idx -> count of 'play' (started) events, capped 65535 */
    omp_map artist_pref;
    uint32_t n;
} omp_prefs;

/* Signed value of one interaction. completion < 0 means unknown (Python None). */
double omp_event_weight(uint8_t event, double completion);

/* compute_prefs over a CHRONOLOGICALLY ORDERED play log (the append-only log's
 * natural order; Python sorts by ts first — equivalent for sorted input). */
int omp_prefs_compute(const omp_pack *pack, const omp_play *plays, int n_plays,
                      double now, double halflife_days, omp_prefs *out);
void omp_prefs_free(omp_prefs *p);

/* build_centroid: weighted L2-normalized centroid of track embeddings.
 * Returns 1 and fills out[] on success, 0 if there is no usable signal. */
int omp_centroid(omp_pack *pack, const uint32_t *idxs, const float *weights,
                 int n, int positive_only, float out[OMP_DIM]);

/* taste = centroid of signed track prefs; skip = centroid of strong-negative
 * tracks at weight 1.0 (mirrors server.py personalization()). */
int omp_taste_centroid(omp_pack *pack, const omp_prefs *prefs, float out[OMP_DIM]);
int omp_skip_centroid(omp_pack *pack, const omp_prefs *prefs, float out[OMP_DIM]);

enum {
    OMP_T_VIBE, OMP_T_MOOD, OMP_T_TASTE, OMP_T_PREF_TRACK, OMP_T_PREF_ARTIST,
    OMP_T_COOLDOWN, OMP_T_SKIP, OMP_T_FATIGUE, OMP_T_NOVELTY, OMP_T_COUNT
};

typedef struct {
    uint32_t idx;
    double score;
    float terms[OMP_T_COUNT];  /* signed components; they sum to score */
    uint32_t pos;              /* original candidate position (stable-sort tie-break) */
} omp_ranked;

typedef struct {
    const float *cur_vec;                  /* NULL-able unit vectors */
    const float *taste_vec, *skip_vec, *session_vec;
    const float *recent_vecs;              /* n_recent x OMP_DIM, most-recent-last */
    int n_recent;
    const omp_map *track_pref;             /* idx -> pref, or NULL */
    const omp_map *artist_pref;            /* or NULL */
    const omp_map *play_counts;            /* idx -> count, or NULL */
    const uint32_t *recent_artists;        /* interned artist offsets, no zeros */
    int n_recent_artists;
    omp_rank_params params;
} omp_rank_ctx;

/* Score candidates, best-first into out[] (cap >= n_cand). Returns count. */
int omp_rank_next(omp_pack *pack, const uint32_t *cand, int n_cand,
                  const omp_rank_ctx *ctx, omp_ranked *out);

typedef enum {
    OMP_PICK_EXPLOIT, OMP_PICK_EXPLORE_UNHEARD, OMP_PICK_EXPLORE_RANDOM,
    OMP_PICK_FALLBACK_GENRE, OMP_PICK_FALLBACK_RANDOM
} omp_pick_reason;

/* rng01: uniform double in [0,1) with caller state (esp_random / rand shim). */
typedef double (*omp_rng01)(void *state);

/* choose_next: exploit top pick; with prob epsilon take the best-ranked unheard
 * track in the top_k window, else a random top-4 pick. UINT32_MAX if empty. */
uint32_t omp_choose_next(const omp_ranked *ranked, int n, const omp_map *play_counts,
                         double epsilon, int top_k, omp_rng01 rng, void *rng_state,
                         omp_pick_reason *reason);

/* One full /api/next step: candidate retrieval from the neighbor row minus the
 * played list, session context from the played tail (mood 12 / fatigue 6 /
 * cooldown 4 + current artist), rank, epsilon-explore pick; random same-genre
 * fallback when the neighborhood is exhausted. played = oldest->newest, current
 * NOT included. Returns the pick or UINT32_MAX. */
uint32_t omp_next_track(omp_pack *pack, const omp_prefs *prefs,
                        const float *taste_vec, const float *skip_vec,
                        const uint32_t *played, int n_played, uint32_t cur,
                        double epsilon, omp_rng01 rng, void *rng_state,
                        omp_pick_reason *reason,
                        omp_ranked *ranked_out, int *n_ranked_out);

#endif
