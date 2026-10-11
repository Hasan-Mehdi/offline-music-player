/* Engine v3: the web player's CURRENT autoplay (scripts/server.py next_decision with
 * AUTOPLAY_PARAMS + EXPLORE, personalize.py opt-ins), ported to the device. The v1 port in
 * omp_brain.* stays as it is (its goldens pin personalize.py's defaults); this is the
 * opt-in layer on top, held to its own goldens (tools/gen_goldens_v3.py,
 * host/test_engine3.c).
 *
 * What the device does like the web player:
 *   centered embeddings (the pack stores them; engine-3 packs only)
 *   compute_prefs(neg_halflife 14 d, strong_early_skip, explicit_state) + artist_mass
 *   taste = YouTube Music history (pre-summed on the PC) + the device's own log
 *   play counts = history + device plays; heard = last play/complete
 *   session_rejects (3 h), the skip anchor, decayed session mood, session-skip vector
 *   LOW_MEM retrieval: neighbours + song-radio co-occurrence + a never-played slice drawn
 *     with Random(anchor video id), exactly as blend_candidates does
 *   rank_next(scale="window", same_w, kappa, track_tanh, artist_prior, cooc, heard,
 *     energy, bpm)
 *   choose_next_explained: adaptive epsilon, clustered Thompson sampling with a pooled
 *     prior, the explore sound budget
 * What differs: retrieval is the server's LOW_MEM path (no 55k full-matrix scan on the
 * device); energy is quantized to 1/254 and tempo to 0.1 BPM; the 122 split-chapter
 * tracks seed the fresh slice with their short id. */
#ifndef OMP_ENGINE3_H
#define OMP_ENGINE3_H

#include "omp_brain.h"
#include "omp_pyrand.h"

typedef struct {
    uint32_t n;
    uint8_t *energy;          /* 255 = none */
    uint16_t *bpm10;          /* 0 = none */
    uint16_t *cluster;        /* 0xFFFF = none */
    uint16_t *hist_n;         /* YouTube Music plays */
    float taste_hist[OMP_DIM];
    float taste_hist_total;
    uint32_t *cooc_off;       /* n + 1, or NULL */
    uint32_t *cooc_mem;
    int ok;
} omp_v3data;

int omp_v3_load(omp_v3data *d, const char *pack_dir, uint32_t n);   /* 0 ok */
void omp_v3_free(omp_v3data *d);

/* AUTOPLAY_PARAMS + rank_next's defaults for the rest */
typedef struct {
    double alpha, mu, delta, sigma, kappa, cooldown, heard_w, beta, nu, gamma, gamma_artist,
           energy_w, bpm_w, artist_prior, same_w, same_floor, rho, rho_floor, energy_band,
           heard_halflife;
    int track_tanh, window;
} omp_v3_params;
omp_v3_params omp_v3_default_params(void);

/* the extra per-history state v3 needs (beside omp_prefs' track/artist/play maps) */
typedef struct {
    omp_prefs base;           /* track_pref, play_counts (device only), artist_pref */
    omp_map artist_mass;
    omp_map counts;           /* merged: history + device plays */
    omp_map heard_age;        /* idx -> now - last play/complete (s) */
    double epsilon;
    uint32_t n_clusters;
    float *cl_acc, *cl_skip;  /* per cluster arm history */
} omp_prefs3;

int omp_prefs3_compute(const omp_pack *pack, const omp_v3data *d, const omp_play *plays,
                       int n_plays, double now, omp_prefs3 *out);
void omp_prefs3_free(omp_prefs3 *p);
int omp_taste3(omp_pack *pack, const omp_v3data *d, const omp_prefs3 *p, float out[OMP_DIM]);
int omp_skip3(omp_pack *pack, const omp_prefs3 *p, float out[OMP_DIM]);

/* term slots beyond omp_brain.h's (same omp_ranked.terms array) */
enum { OMP_T3_COOC = OMP_T_COUNT, OMP_T3_HEARD, OMP_T3_ENERGY, OMP_T3_BPM, OMP_T3_SAME,
       OMP_T3_SSKIP, OMP_T3_COUNT };

typedef struct {
    double score;
    uint32_t idx, pos;
    float terms[OMP_T3_COUNT];
} omp_ranked3;

enum { OMP_OUT_NONE, OMP_OUT_SKIP, OMP_OUT_COMPLETE, OMP_OUT_SWITCH, OMP_OUT_DISLIKE };

typedef struct {
    uint32_t pick, anchor;
    int reason;               /* omp_pick_reason */
    int n_ranked, n_rejected, n_cand;
    double epsilon;
} omp_decision;

/* One /api/next: ex = the queue tail (oldest -> newest, current included or not), cur =
 * the track being left, outcome/secs = how it ended. rng = the explore draws (the web
 * player uses Python's global random). ranked must hold pack->k + 64 entries. */
int omp_next_v3(omp_pack *pack, const omp_v3data *d, const omp_prefs3 *prefs,
                const float *taste, const float *skip, const omp_play *plays, int n_plays,
                const uint32_t *ex, int n_ex, uint32_t cur, int outcome, float secs,
                double now, const omp_v3_params *params, omp_pyrand *rng,
                omp_ranked3 *ranked, omp_decision *out);

#endif
