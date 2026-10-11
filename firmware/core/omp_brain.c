#include "omp_brain.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

omp_rank_params omp_default_params(void)
{
    omp_rank_params p = { 1.0, 0.6, 0.5, 0.3, 0.7, 0.5, 0.1, 2.0, 0.80, 0.6 };
    return p;
}

/* completion fraction, or -1 for unknown (Python None) */
static double completion_of(float seconds, uint16_t duration)
{
    if (duration == 0 || seconds < 0.0f) return -1.0;
    double c = (double)seconds / (double)duration;
    return c < 0.0 ? 0.0 : (c > 1.0 ? 1.0 : c);
}

double omp_event_weight(uint8_t event, double completion)
{
    switch (event) {
    case OMP_EV_LIKE: return 3.0;
    case OMP_EV_DISLIKE: return -3.0;
    case OMP_EV_COMPLETE:
        return fmax(0.25, completion >= 0.0 ? completion : 1.0);
    case OMP_EV_SKIP:
        if (completion < 0.0) return 0.0;
        if (completion < OMP_STRONG_SKIP) return -1.0;
        if (completion > OMP_LATE_OK) return 0.5;
        return 0.0;
    case OMP_EV_PLAY: return 0.05;
    default: return 0.0;   /* peek and anything unknown */
    }
}

int omp_prefs_compute(const omp_pack *pack, const omp_play *plays, int n_plays,
                      double now, double halflife_days, omp_prefs *out)
{
    memset(out, 0, sizeof *out);
    out->n = pack->n;
    if (omp_map_init(&out->track_pref, 256) != 0 || omp_map_init(&out->play_counts, 256) != 0 ||
        omp_map_init(&out->artist_pref, 64) != 0) {
        omp_prefs_free(out);
        return -1;
    }

    /* Session position tracking, single chronological pass (personalize.py's
     * session_positions over ts-sorted events; our log is append-ordered). */
    uint32_t *sess = NULL;
    int sess_n = 0, sess_cap = 0;
    double last_ts = -1.0;

    for (int i = 0; i < n_plays; i++) {
        const omp_play *ev = &plays[i];
        if (ev->idx >= pack->n) continue;

        int pos = 0;                     /* 0 = no timestamp = no gating */
        if (ev->ts > 0.0) {
            if (last_ts < 0.0 || ev->ts - last_ts > OMP_SESSION_GAP_SECONDS)
                sess_n = 0;              /* new session */
            int found = -1;
            for (int s = 0; s < sess_n; s++)
                if (sess[s] == ev->idx) { found = s; break; }
            if (found < 0) {
                if (sess_n == sess_cap) {
                    sess_cap = sess_cap ? sess_cap * 2 : 64;
                    uint32_t *ns = realloc(sess, (size_t)sess_cap * 4);
                    if (!ns) { free(sess); omp_prefs_free(out); return -1; }
                    sess = ns;
                }
                sess[sess_n++] = ev->idx;
                found = sess_n - 1;
            }
            pos = found + 1;
            last_ts = ev->ts;
        }

        if (ev->event == OMP_EV_PLAY) {
            float *pc = omp_map_slot(&out->play_counts, ev->idx);
            if (!pc) { free(sess); omp_prefs_free(out); return -1; }
            if (*pc < (float)UINT16_MAX) *pc += 1.0f;
        }

        const omp_track *tr = omp_pack_track(pack, ev->idx);
        double w = omp_event_weight(ev->event, completion_of(ev->seconds, tr->duration_s));
        if (w == 0.0) continue;
        if (w < 0.0 && pos > 0 && pos <= OMP_EARLY_SESSION_TRACKS)
            w *= OMP_EARLY_SKIP_FACTOR;
        if (ev->ts > 0.0 && now > 0.0) {
            double days = (now - ev->ts) / 86400.0;
            if (days < 0.0) days = 0.0;
            w *= pow(0.5, days / halflife_days);
        }
        uint32_t art_off = tr->artist_off;
        float *tp = omp_map_slot(&out->track_pref, ev->idx);
        if (!tp) { free(sess); omp_prefs_free(out); return -1; }
        *tp += (float)w;
        if (art_off != 0) {              /* offset 0 = empty artist string */
            float *slot = omp_map_slot(&out->artist_pref, art_off);
            if (!slot) { free(sess); omp_prefs_free(out); return -1; }
            *slot += (float)w;
        }
    }
    free(sess);
    return 0;
}

void omp_prefs_free(omp_prefs *p)
{
    omp_map_free(&p->track_pref);
    omp_map_free(&p->play_counts);
    omp_map_free(&p->artist_pref);
    memset(p, 0, sizeof *p);
}

/* Working vectors are static, not stack: the H2 runs plugins on Rockbox's 7.5KB main
 * stack (X1000_STACKSIZE). The brain is single-threaded and never re-enters these. */
int omp_centroid(omp_pack *pack, const uint32_t *idxs, const float *weights,
                 int n, int positive_only, float out[OMP_DIM])
{
    static float acc[OMP_DIM], v[OMP_DIM];
    memset(acc, 0, sizeof acc);
    double total = 0.0;
    for (int i = 0; i < n; i++) {
        float w = weights[i];
        if (positive_only && w <= 0.0f) continue;
        if (idxs[i] >= pack->n || omp_pack_vec(pack, idxs[i], v) != 0) continue;
        for (int d = 0; d < OMP_DIM; d++)
            acc[d] += w * v[d];
        total += fabs((double)w);
    }
    if (total == 0.0) return 0;
    float sq = 0.0f;
    for (int d = 0; d < OMP_DIM; d++)
        sq += acc[d] * acc[d];
    float norm = sqrtf(sq);
    if (norm < 1e-9f) return 0;
    for (int d = 0; d < OMP_DIM; d++)
        out[d] = acc[d] / norm;
    return 1;
}

typedef struct { uint32_t idx; float w; } idx_w;

static int cmp_idx(const void *pa, const void *pb)
{
    const idx_w *a = pa, *b = pb;
    return a->idx < b->idx ? -1 : (a->idx > b->idx ? 1 : 0);
}

/* Gather (idx, weight) pairs from the sparse prefs by predicate, then centroid. Sorted
 * by idx first so the float accumulation runs in the same order as a dense scan. */
static int centroid_from_prefs(omp_pack *pack, const omp_prefs *prefs,
                               int skip_mode, float out[OMP_DIM])
{
    const omp_map *m = &prefs->track_pref;
    idx_w *e = malloc((size_t)(m->used ? m->used : 1) * sizeof *e);
    uint32_t *idxs = malloc((size_t)(m->used ? m->used : 1) * 4);
    float *ws = malloc((size_t)(m->used ? m->used : 1) * 4);
    if (!e || !idxs || !ws) { free(e); free(idxs); free(ws); return 0; }
    int n = 0;
    for (uint32_t s = 0; s < m->cap; s++) {
        if (m->keys[s] == OMP_MAP_EMPTY) continue;
        float w = m->vals[s];
        if (skip_mode) {                 /* skip centroid: strong negatives at 1.0 */
            if (w < 0.0f) { e[n].idx = m->keys[s]; e[n++].w = 1.0f; }
        } else if (w != 0.0f) {
            e[n].idx = m->keys[s]; e[n++].w = w;
        }
    }
    qsort(e, (size_t)n, sizeof *e, cmp_idx);
    for (int i = 0; i < n; i++) { idxs[i] = e[i].idx; ws[i] = e[i].w; }
    int ok = omp_centroid(pack, idxs, ws, n, 0, out);
    free(e);
    free(idxs);
    free(ws);
    return ok;
}

int omp_taste_centroid(omp_pack *pack, const omp_prefs *prefs, float out[OMP_DIM])
{
    return centroid_from_prefs(pack, prefs, 0, out);
}

int omp_skip_centroid(omp_pack *pack, const omp_prefs *prefs, float out[OMP_DIM])
{
    return centroid_from_prefs(pack, prefs, 1, out);
}

static float dotf(const float *a, const float *b)
{
    float s = 0.0f;
    for (int d = 0; d < OMP_DIM; d++)
        s += a[d] * b[d];
    return s;
}

static int cmp_ranked(const void *pa, const void *pb)
{
    const omp_ranked *a = pa, *b = pb;
    if (a->score > b->score) return -1;
    if (a->score < b->score) return 1;
    return a->pos < b->pos ? -1 : (a->pos > b->pos ? 1 : 0);   /* stable-sort parity */
}

int omp_rank_next(omp_pack *pack, const uint32_t *cand, int n_cand,
                  const omp_rank_ctx *ctx, omp_ranked *out)
{
    const omp_rank_params *p = &ctx->params;
    static float v[OMP_DIM];
    int n = 0;
    for (int i = 0; i < n_cand; i++) {
        uint32_t j = cand[i];
        if (j >= pack->n || omp_pack_vec(pack, j, v) != 0) continue;
        omp_ranked *r = &out[n];
        memset(r->terms, 0, sizeof r->terms);
        r->idx = j;
        r->pos = (uint32_t)i;

        if (ctx->cur_vec)
            r->terms[OMP_T_VIBE] = (float)(p->alpha * (double)dotf(v, ctx->cur_vec));
        if (ctx->session_vec)
            r->terms[OMP_T_MOOD] = (float)(p->mu * (double)dotf(v, ctx->session_vec));
        if (ctx->taste_vec)
            r->terms[OMP_T_TASTE] = (float)(p->delta * (double)dotf(v, ctx->taste_vec));
        if (ctx->track_pref)
            r->terms[OMP_T_PREF_TRACK] =
                (float)(p->gamma * (double)omp_map_get(ctx->track_pref, j, 0.0f));
        uint32_t art = omp_pack_track(pack, j)->artist_off;
        if (art != 0) {
            if (ctx->artist_pref)
                r->terms[OMP_T_PREF_ARTIST] =
                    (float)(p->gamma_artist * tanh((double)omp_map_get(ctx->artist_pref, art, 0.0f)));
            for (int a = 0; a < ctx->n_recent_artists; a++)
                if (ctx->recent_artists[a] == art) {
                    r->terms[OMP_T_COOLDOWN] = (float)-p->cooldown;
                    break;
                }
        }
        if (ctx->skip_vec) {
            double s = (double)dotf(v, ctx->skip_vec);
            r->terms[OMP_T_SKIP] = (float)(-p->sigma * (s > 0.0 ? s : 0.0));
        }
        if (ctx->recent_vecs && ctx->n_recent > 0) {
            float m = dotf(ctx->recent_vecs, v);
            for (int k = 1; k < ctx->n_recent; k++) {
                float d = dotf(ctx->recent_vecs + (size_t)k * OMP_DIM, v);
                if (d > m) m = d;
            }
            double over = (double)m - p->rho_floor;
            r->terms[OMP_T_FATIGUE] = (float)(-p->rho * (over > 0.0 ? over : 0.0));
        }
        r->terms[OMP_T_NOVELTY] =
            (float)(p->nu * pow(0.5, ctx->play_counts ?
                                         (double)omp_map_get(ctx->play_counts, j, 0.0f) : 0.0));

        double s = 0.0;
        for (int t = 0; t < OMP_T_COUNT; t++)
            s += (double)r->terms[t];
        r->score = s;
        n++;
    }
    qsort(out, (size_t)n, sizeof *out, cmp_ranked);
    return n;
}

uint32_t omp_choose_next(const omp_ranked *ranked, int n, const omp_map *play_counts,
                         double epsilon, int top_k, omp_rng01 rng, void *rng_state,
                         omp_pick_reason *reason)
{
    *reason = OMP_PICK_EXPLOIT;
    if (n <= 0) return UINT32_MAX;
    if (rng(rng_state) >= epsilon)
        return ranked[0].idx;
    int lim = n < top_k ? n : top_k;
    for (int i = 0; i < lim; i++)
        if (!play_counts || omp_map_get(play_counts, ranked[i].idx, 0.0f) == 0.0f) {
            *reason = OMP_PICK_EXPLORE_UNHEARD;
            return ranked[i].idx;
        }
    int m = n < 4 ? n : 4;
    *reason = OMP_PICK_EXPLORE_RANDOM;
    return ranked[(int)(rng(rng_state) * m)].idx;
}

static int in_list(const uint32_t *list, int n, uint32_t x)
{
    for (int i = 0; i < n; i++)
        if (list[i] == x) return 1;
    return 0;
}

uint32_t omp_next_track(omp_pack *pack, const omp_prefs *prefs,
                        const float *taste_vec, const float *skip_vec,
                        const uint32_t *played, int n_played, uint32_t cur,
                        double epsilon, omp_rng01 rng, void *rng_state,
                        omp_pick_reason *reason,
                        omp_ranked *ranked_out, int *n_ranked_out)
{
    *reason = OMP_PICK_EXPLOIT;
    if (n_ranked_out) *n_ranked_out = 0;
    if (cur >= pack->n) return UINT32_MAX;

    /* retrieval: current track's neighborhood minus already-played */
    uint32_t *nbrs = malloc((size_t)pack->k * 4);
    uint32_t *cand = malloc((size_t)pack->k * 4);
    if (!nbrs || !cand) { free(nbrs); free(cand); return UINT32_MAX; }
    int n_nbr = omp_pack_neighbors(pack, cur, nbrs);
    int n_cand = 0;
    for (int i = 0; i < n_nbr; i++)
        if (nbrs[i] != cur && !in_list(played, n_played, nbrs[i]))
            cand[n_cand++] = nbrs[i];
    free(nbrs);

    if (n_cand == 0) {
        /* fallback: random draw preferring the current genre (server.py shape) */
        free(cand);
        uint32_t draws[120];
        for (int i = 0; i < 120; i++)
            draws[i] = (uint32_t)(rng(rng_state) * pack->n) % pack->n;
        uint32_t g = omp_pack_track(pack, cur)->genre_off;
        if (g != 0)
            for (int i = 0; i < 120; i++)
                if (omp_pack_track(pack, draws[i])->genre_off == g && draws[i] != cur &&
                    !in_list(played, n_played, draws[i])) {
                    *reason = OMP_PICK_FALLBACK_GENRE;
                    return draws[i];
                }
        for (int i = 0; i < 120; i++)
            if (draws[i] != cur && !in_list(played, n_played, draws[i])) {
                *reason = OMP_PICK_FALLBACK_RANDOM;
                return draws[i];
            }
        return UINT32_MAX;
    }

    /* session context from the played tail (server.py /api/next):
     * mood = last 11 non-current + current; fatigue = last 6 of mood;
     * cooldown = artists of last 4 of fatigue window + current artist */
    uint32_t mood[12];
    int n_mood = 0;
    {
        uint32_t tail[11];
        int n_tail = 0;
        for (int i = n_played - 1; i >= 0 && n_tail < 11; i--)
            if (played[i] != cur)
                tail[n_tail++] = played[i];
        for (int i = n_tail - 1; i >= 0; i--)   /* restore oldest->newest */
            mood[n_mood++] = tail[i];
        mood[n_mood++] = cur;
    }
    float ones[12];
    for (int i = 0; i < 12; i++) ones[i] = 1.0f;
    static float session_vec[OMP_DIM], cur_vec[OMP_DIM];
    int have_session = omp_centroid(pack, mood, ones, n_mood, 0, session_vec);

    int n_recent = n_mood < 6 ? n_mood : 6;
    const uint32_t *recent_ids = mood + (n_mood - n_recent);
    float *rvecs = malloc((size_t)n_recent * OMP_DIM * 4);
    if (!rvecs) { free(cand); return UINT32_MAX; }
    for (int i = 0; i < n_recent; i++)
        omp_pack_vec(pack, recent_ids[i], rvecs + (size_t)i * OMP_DIM);

    uint32_t recent_artists[5];
    int n_ra = 0;
    int n_last4 = n_recent < 4 ? n_recent : 4;
    for (int i = n_recent - n_last4; i < n_recent; i++) {
        uint32_t a = omp_pack_track(pack, recent_ids[i])->artist_off;
        if (a != 0) recent_artists[n_ra++] = a;
    }
    if (omp_pack_track(pack, cur)->artist_off != 0)
        recent_artists[n_ra++] = omp_pack_track(pack, cur)->artist_off;

    omp_rank_ctx ctx = { 0 };
    ctx.params = omp_default_params();
    if (omp_pack_vec(pack, cur, cur_vec) == 0)
        ctx.cur_vec = cur_vec;
    ctx.taste_vec = taste_vec;
    ctx.skip_vec = skip_vec;
    ctx.session_vec = have_session ? session_vec : NULL;
    ctx.recent_vecs = rvecs;
    ctx.n_recent = n_recent;
    ctx.track_pref = prefs ? &prefs->track_pref : NULL;
    ctx.artist_pref = prefs ? &prefs->artist_pref : NULL;
    ctx.play_counts = prefs ? &prefs->play_counts : NULL;
    ctx.recent_artists = recent_artists;
    ctx.n_recent_artists = n_ra;

    int n_ranked = omp_rank_next(pack, cand, n_cand, &ctx, ranked_out);
    free(cand);
    free(rvecs);
    if (n_ranked_out) *n_ranked_out = n_ranked;
    return omp_choose_next(ranked_out, n_ranked,
                           prefs ? &prefs->play_counts : NULL,
                           epsilon, 12, rng, rng_state, reason);
}
