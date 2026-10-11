#include "omp_engine3.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define EARLY_SKIP_COMPLETION 0.05
#define EARLY_SKIP_SECONDS 10.0
#define EARLY_SKIP_WEIGHT (-1.5)
#define NEG_HALFLIFE_DAYS 14.0
#define HEARD_MAX_AGE (14.0 * 86400.0)
#define REJECT_LOOKBACK (3.0 * 3600.0)
#define MOOD_DECAY 0.85
#define WINDOW_U_DEFAULT 0.12
#define WINDOW_U_FLOOR 1e-4
#define BPM_FREE_RATIO 1.05
#define BPM_FULL_RATIO 1.15
#define EPS_BASE 0.15
#define EPS_GAIN 0.3
#define EPS_LO 0.05
#define EPS_HI 0.30
#define EPS_GAMMA 0.3
#define OUTCOME_WINDOW 10
#define CLUSTER_WINDOW 40
#define TOP_K 12
#define SOUND_BUDGET 0.5
#define PRIOR_N 10.0
#define BLEND_CUR 120
#define BLEND_RADIO 50
#define BLEND_FRESH 10
#define BLEND_TOTAL 180
#define EV_UNLIKE 6

/* ------------------------------------------------------------------ pack data */
/* Big working buffers are static throughout: the H2 plugin runs on Rockbox's 7.5 KB main
 * stack, and the brain never runs on two threads at once (UI or background, not both). */
static void *read_file(const char *dir, const char *name, size_t *len)
{
    static char path[512];
    snprintf(path, sizeof path, "%s/%s", dir, name);
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    void *b = n > 0 ? malloc((size_t)n) : NULL;
    if (b && fread(b, 1, (size_t)n, f) != (size_t)n) { free(b); b = NULL; }
    fclose(f);
    if (b && len) *len = (size_t)n;
    return b;
}

static uint32_t rd32(const uint8_t *b) { return b[0] | (b[1] << 8) | (b[2] << 16) | ((uint32_t)b[3] << 24); }
static uint16_t rd16(const uint8_t *b) { return (uint16_t)(b[0] | (b[1] << 8)); }

int omp_v3_load(omp_v3data *d, const char *pack_dir, uint32_t n)
{
    memset(d, 0, sizeof *d);
    size_t len = 0;
    uint8_t *sig = read_file(pack_dir, "signals.bin", &len);
    if (!sig || len != (size_t)n * 8) { free(sig); return -1; }
    d->n = n;
    d->energy = malloc(n);
    d->bpm10 = malloc((size_t)n * 2);
    d->cluster = malloc((size_t)n * 2);
    d->hist_n = malloc((size_t)n * 2);
    if (!d->energy || !d->bpm10 || !d->cluster || !d->hist_n) { free(sig); omp_v3_free(d); return -1; }
    for (uint32_t i = 0; i < n; i++) {
        const uint8_t *r = sig + (size_t)i * 8;
        d->energy[i] = r[0];
        d->bpm10[i] = rd16(r + 2);
        d->cluster[i] = rd16(r + 4);
        d->hist_n[i] = rd16(r + 6);
    }
    free(sig);
    uint8_t *th = read_file(pack_dir, "taste_hist.bin", &len);
    if (th && len == OMP_DIM * 4 + 4) {
        memcpy(d->taste_hist, th, OMP_DIM * 4);
        memcpy(&d->taste_hist_total, th + OMP_DIM * 4, 4);
    }
    free(th);
    uint8_t *co = read_file(pack_dir, "cooc.bin", &len);
    if (co && len >= 8 + ((size_t)n + 1) * 4 && !memcmp(co, "COC1", 4) && rd32(co + 4) == n) {
        uint32_t m = (uint32_t)((len - 8 - ((size_t)n + 1) * 4) / 4);
        d->cooc_off = malloc(((size_t)n + 1) * 4);
        d->cooc_mem = malloc((size_t)(m ? m : 1) * 4);
        if (d->cooc_off && d->cooc_mem) {
            for (uint32_t i = 0; i <= n; i++) d->cooc_off[i] = rd32(co + 8 + 4 * (size_t)i);
            for (uint32_t i = 0; i < m; i++) d->cooc_mem[i] = rd32(co + 8 + 4 * ((size_t)n + 1) + 4 * (size_t)i);
        } else {
            free(d->cooc_off); free(d->cooc_mem);
            d->cooc_off = d->cooc_mem = NULL;
        }
    }
    free(co);
    d->ok = 1;
    return 0;
}

void omp_v3_free(omp_v3data *d)
{
    free(d->energy); free(d->bpm10); free(d->cluster); free(d->hist_n);
    free(d->cooc_off); free(d->cooc_mem);
    memset(d, 0, sizeof *d);
}

omp_v3_params omp_v3_default_params(void)
{
    omp_v3_params p;
    memset(&p, 0, sizeof p);
    p.alpha = 1.0; p.mu = 0.6; p.delta = 0.2; p.sigma = 0.25; p.kappa = 1.0;
    p.cooldown = 3.0; p.heard_w = 3.0; p.beta = 1.0; p.nu = 0.3; p.gamma = 1.0;
    p.gamma_artist = 0.5; p.energy_w = 6.0; p.bpm_w = 0.7; p.artist_prior = 3.0;
    p.same_w = 1.5; p.same_floor = 0.78; p.rho = 2.0; p.rho_floor = 0.67;
    p.energy_band = 0.35; p.heard_halflife = 24 * 3600.0;
    p.track_tanh = 1; p.window = 1;
    return p;
}

/* ------------------------------------------------------------------ prefs */
static double completion_of(float seconds, uint16_t duration)
{
    if (duration == 0 || seconds < 0.0f) return -1.0;
    double c = (double)seconds / (double)duration;
    return c < 0.0 ? 0.0 : (c > 1.0 ? 1.0 : c);
}

static double weight3(uint8_t ev, double comp)
{
    if (ev == EV_UNLIKE) return -3.0;
    return omp_event_weight(ev, comp);
}

static int explicit_ev(uint8_t ev)
{
    return ev == OMP_EV_LIKE || ev == EV_UNLIKE || ev == OMP_EV_DISLIKE;
}

static int is_early(const omp_pack *pack, uint32_t idx, float seconds)
{
    double c = completion_of(seconds, omp_pack_track(pack, idx)->duration_s);
    if (c >= 0.0) return c < OMP_STRONG_SKIP;
    return seconds >= 0.0f && seconds < EARLY_SKIP_SECONDS;
}

int omp_prefs3_compute(const omp_pack *pack, const omp_v3data *d, const omp_play *plays,
                       int n_plays, double now, omp_prefs3 *out)
{
    memset(out, 0, sizeof *out);
    omp_prefs *b = &out->base;
    b->n = pack->n;
    if (omp_map_init(&b->track_pref, 256) || omp_map_init(&b->play_counts, 256) ||
        omp_map_init(&b->artist_pref, 64) || omp_map_init(&out->artist_mass, 64) ||
        omp_map_init(&out->counts, 1024) || omp_map_init(&out->heard_age, 256))
        goto oom;

    /* explicit_state: the standing like/unlike of each track = its last one in the log */
    omp_map standing;
    if (omp_map_init(&standing, 64)) goto oom;
    for (int i = 0; i < n_plays; i++)
        if (plays[i].event == OMP_EV_LIKE || plays[i].event == EV_UNLIKE) {
            float *s = omp_map_slot(&standing, plays[i].idx);
            if (!s) { omp_map_free(&standing); goto oom; }
            *s = (float)i;
        }

    uint32_t *sess = NULL;
    int sess_n = 0, sess_cap = 0;
    double last_ts = -1.0;
    for (int i = 0; i < n_plays; i++) {
        const omp_play *ev = &plays[i];
        if (ev->idx >= pack->n) continue;
        int pos = 0;
        if (ev->ts > 0.0) {
            if (last_ts < 0.0 || ev->ts - last_ts > OMP_SESSION_GAP_SECONDS) sess_n = 0;
            int found = -1;
            for (int s = 0; s < sess_n; s++) if (sess[s] == ev->idx) { found = s; break; }
            if (found < 0) {
                if (sess_n == sess_cap) {
                    sess_cap = sess_cap ? sess_cap * 2 : 64;
                    uint32_t *ns = realloc(sess, (size_t)sess_cap * 4);
                    if (!ns) { free(sess); omp_map_free(&standing); goto oom; }
                    sess = ns;
                }
                sess[sess_n++] = ev->idx;
                found = sess_n - 1;
            }
            pos = found + 1;
            last_ts = ev->ts;
        }
        if (ev->event == OMP_EV_PLAY) {
            float *pc = omp_map_slot(&b->play_counts, ev->idx);
            if (pc && *pc < 65535.0f) *pc += 1.0f;
        }
        if ((ev->event == OMP_EV_PLAY || ev->event == OMP_EV_COMPLETE) && ev->ts > 0.0) {
            float *h = omp_map_slot(&out->heard_age, ev->idx);
            double age = now - ev->ts;
            if (h) *h = (float)(age > 0.0 ? age : 0.0);           /* chronological: last wins */
        }
        if ((ev->event == OMP_EV_LIKE || ev->event == EV_UNLIKE) &&
            (ev->event == EV_UNLIKE || (int)omp_map_get(&standing, ev->idx, -1.0f) != i))
            continue;
        const omp_track *tr = omp_pack_track(pack, ev->idx);
        double comp = completion_of(ev->seconds, tr->duration_s);
        double w = weight3(ev->event, comp);
        if (w == 0.0) continue;
        if (ev->event == OMP_EV_SKIP && w == -1.0 &&
            ((comp >= 0.0 && comp < EARLY_SKIP_COMPLETION) ||
             (ev->seconds >= 0.0f && ev->seconds < EARLY_SKIP_SECONDS)))
            w = EARLY_SKIP_WEIGHT;
        if (w < 0.0 && pos > 0 && pos <= OMP_EARLY_SESSION_TRACKS && !explicit_ev(ev->event))
            w *= OMP_EARLY_SKIP_FACTOR;
        double f = 1.0;
        if (ev->ts > 0.0 && now > 0.0) {
            double hl = w < 0.0 ? NEG_HALFLIFE_DAYS : OMP_HALFLIFE_DAYS;
            double days = (now - ev->ts) / 86400.0;
            if (days < 0.0) days = 0.0;
            f = pow(0.5, days / hl);
            w *= f;
        }
        float *tp = omp_map_slot(&b->track_pref, ev->idx);
        if (!tp) { free(sess); omp_map_free(&standing); goto oom; }
        *tp += (float)w;
        if (tr->artist_off) {
            float *ap = omp_map_slot(&b->artist_pref, tr->artist_off);
            if (ap) *ap += (float)w;
            if (ev->event != OMP_EV_PLAY) {
                float *am = omp_map_slot(&out->artist_mass, tr->artist_off);
                if (am) *am += (float)f;
            }
        }
    }
    free(sess);
    omp_map_free(&standing);

    /* merged counts: YouTube Music history + the device's own plays */
    if (d && d->hist_n)
        for (uint32_t i = 0; i < pack->n; i++)
            if (d->hist_n[i]) { float *c = omp_map_slot(&out->counts, i); if (c) *c = d->hist_n[i]; }
    for (uint32_t s = 0; s < b->play_counts.cap; s++) {
        if (b->play_counts.keys[s] == OMP_MAP_EMPTY) continue;
        float *c = omp_map_slot(&out->counts, b->play_counts.keys[s]);
        if (c) *c += b->play_counts.vals[s];
    }

    /* adaptive epsilon (server.outcome_epsilon) over the last OUTCOME_WINDOW verdicts */
    double xs[OUTCOME_WINDOW];
    int nx = 0, total = 0;
    for (int i = 0; i < n_plays; i++) {
        const omp_play *ev = &plays[i];
        double x;
        if (ev->idx >= pack->n) continue;
        if (ev->event == OMP_EV_COMPLETE || ev->event == OMP_EV_LIKE) x = 1.0;
        else if (ev->event == OMP_EV_DISLIKE) x = 0.0;
        else if (ev->event == OMP_EV_SKIP) {
            double c = completion_of(ev->seconds, omp_pack_track(pack, ev->idx)->duration_s);
            x = (c >= 0.0 && c > OMP_LATE_OK) ? 1.0 : 0.0;
        } else continue;
        if (nx == OUTCOME_WINDOW) { memmove(xs, xs + 1, sizeof xs - sizeof xs[0]); nx--; }
        xs[nx++] = x;
        total++;
    }
    double m = 0.5;
    if (nx) {
        m = xs[0];
        for (int i = 1; i < nx; i++) m = EPS_GAMMA * xs[i] + (1.0 - EPS_GAMMA) * m;
    }
    double eps = EPS_BASE + EPS_GAIN * (0.5 - m);
    out->epsilon = eps < EPS_LO ? EPS_LO : eps > EPS_HI ? EPS_HI : eps;
    (void)total;

    /* cluster arms (server.cluster_stats) */
    if (d && d->cluster) {
        uint32_t nc = 0;
        for (uint32_t i = 0; i < pack->n; i++)
            if (d->cluster[i] != 0xFFFF && d->cluster[i] + 1u > nc) nc = d->cluster[i] + 1u;
        out->n_clusters = nc;
        out->cl_acc = calloc(nc ? nc : 1, sizeof(float));
        out->cl_skip = calloc(nc ? nc : 1, sizeof(float));
        if (!out->cl_acc || !out->cl_skip) goto oom;
        for (int i = 0; i < n_plays; i++) {
            const omp_play *ev = &plays[i];
            if (ev->idx >= pack->n || d->cluster[ev->idx] == 0xFFFF) continue;
            uint16_t c = d->cluster[ev->idx];
            if (ev->event == OMP_EV_COMPLETE || ev->event == OMP_EV_LIKE) out->cl_acc[c] += 1.0f;
            else if (ev->event == OMP_EV_DISLIKE) out->cl_skip[c] += 1.0f;
            else if (ev->event == OMP_EV_SKIP) {
                double cc = completion_of(ev->seconds, omp_pack_track(pack, ev->idx)->duration_s);
                if (cc >= 0.0 && cc < OMP_STRONG_SKIP) out->cl_skip[c] += 1.0f;
            }
        }
    }
    return 0;
oom:
    omp_prefs3_free(out);
    return -1;
}

void omp_prefs3_free(omp_prefs3 *p)
{
    omp_prefs_free(&p->base);
    omp_map_free(&p->artist_mass);
    omp_map_free(&p->counts);
    omp_map_free(&p->heard_age);
    free(p->cl_acc);
    free(p->cl_skip);
    memset(p, 0, sizeof *p);
}

typedef struct { uint32_t idx; float w; } iw;
static int cmp_iw(const void *a, const void *b)
{
    uint32_t x = ((const iw *)a)->idx, y = ((const iw *)b)->idx;
    return x < y ? -1 : x > y;
}

/* centroid = (seed + sum w x) normalized; seed may be NULL */
static int centroid_seeded(omp_pack *pack, const float *seed, double seed_total, const iw *e,
                           int n, float out[OMP_DIM])
{
    static float acc[OMP_DIM], v[OMP_DIM];
    if (seed) memcpy(acc, seed, sizeof acc); else memset(acc, 0, sizeof acc);
    double total = seed_total;
    for (int i = 0; i < n; i++) {
        if (e[i].idx >= pack->n || omp_pack_vec(pack, e[i].idx, v) != 0) continue;
        for (int k = 0; k < OMP_DIM; k++) acc[k] += e[i].w * v[k];
        total += fabs((double)e[i].w);
    }
    if (total == 0.0) return 0;
    float sq = 0.0f;
    for (int k = 0; k < OMP_DIM; k++) sq += acc[k] * acc[k];
    float norm = sqrtf(sq);
    if (norm < 1e-9f) return 0;
    for (int k = 0; k < OMP_DIM; k++) out[k] = acc[k] / norm;
    return 1;
}

static int gather(const omp_map *m, int skip_mode, iw **out)
{
    iw *e = malloc((size_t)(m->used ? m->used : 1) * sizeof *e);
    if (!e) return -1;
    int n = 0;
    for (uint32_t s = 0; s < m->cap; s++) {
        if (m->keys[s] == OMP_MAP_EMPTY) continue;
        float w = m->vals[s];
        if (skip_mode) { if (w < 0.0f) { e[n].idx = m->keys[s]; e[n++].w = 1.0f; } }
        else if (w != 0.0f) { e[n].idx = m->keys[s]; e[n++].w = w; }
    }
    qsort(e, (size_t)n, sizeof *e, cmp_iw);
    *out = e;
    return n;
}

int omp_taste3(omp_pack *pack, const omp_v3data *d, const omp_prefs3 *p, float out[OMP_DIM])
{
    iw *e = NULL;
    int n = gather(&p->base.track_pref, 0, &e);
    if (n < 0) return 0;
    int ok = centroid_seeded(pack, d && d->ok ? d->taste_hist : NULL,
                             d && d->ok ? d->taste_hist_total : 0.0, e, n, out);
    free(e);
    return ok;
}

int omp_skip3(omp_pack *pack, const omp_prefs3 *p, float out[OMP_DIM])
{
    iw *e = NULL;
    int n = gather(&p->base.track_pref, 1, &e);
    if (n < 0) return 0;
    int ok = centroid_seeded(pack, NULL, 0.0, e, n, out);
    free(e);
    return ok;
}

/* ------------------------------------------------------------------ the decision */
static int has(const uint32_t *v, int n, uint32_t x)
{
    for (int i = 0; i < n; i++) if (v[i] == x) return 1;
    return 0;
}

static float dotf(const float *a, const float *b)
{
    float s = 0.0f;
    for (int k = 0; k < OMP_DIM; k++) s += a[k] * b[k];
    return s;
}

/* server.session_rejects over the log: tail ids turned down within the last 3 hours */
static int session_rejects(const omp_pack *pack, const omp_play *plays, int n_plays,
                           const uint32_t *tail, int n_tail, double now, uint32_t *out)
{
    int n_out = 0;
    int lo = 0, hi = n_plays;                                     /* first ts > now - 3h */
    while (lo < hi) { int mid = (lo + hi) / 2; if (plays[mid].ts > now - REJECT_LOOKBACK) hi = mid; else lo = mid + 1; }
    for (int t = 0; t < n_tail; t++) {
        uint32_t v = tail[t];
        if (has(tail, t, v)) continue;                            /* dict.fromkeys: distinct */
        int state = 0;                                            /* 0 none, 1 skip, 2 hard */
        for (int i = lo; i < n_plays; i++) {
            const omp_play *ev = &plays[i];
            if (ev->idx != v) continue;
            if (ev->event == OMP_EV_DISLIKE) state = 2;
            else if (ev->event == OMP_EV_COMPLETE || ev->event == OMP_EV_LIKE) state = 0;
            else if (ev->event == OMP_EV_SKIP && state != 2)
                state = is_early(pack, v, ev->seconds) ? 1 : 0;
        }
        if (state) out[n_out++] = v;
    }
    return n_out;
}

static void cooc_row(const omp_v3data *d, uint32_t i, const uint32_t **m, int *n)
{
    *m = NULL; *n = 0;
    if (!d || !d->cooc_off || i >= d->n) return;
    *m = d->cooc_mem + d->cooc_off[i];
    *n = (int)(d->cooc_off[i + 1] - d->cooc_off[i]);
}

static int cmp_r3(const void *pa, const void *pb)
{
    const omp_ranked3 *a = pa, *b = pb;
    if (a->score > b->score) return -1;
    if (a->score < b->score) return 1;
    return a->pos < b->pos ? -1 : (a->pos > b->pos ? 1 : 0);
}

static double std_of(const double *x, int n)
{
    double m = 0.0, v = 0.0;
    for (int i = 0; i < n; i++) m += x[i];
    m /= n;
    for (int i = 0; i < n; i++) v += (x[i] - m) * (x[i] - m);
    return sqrt(v / n);
}

int omp_next_v3(omp_pack *pack, const omp_v3data *d, const omp_prefs3 *prefs,
                const float *taste, const float *skip, const omp_play *plays, int n_plays,
                const uint32_t *ex, int n_ex, uint32_t cur, int outcome, float secs,
                double now, const omp_v3_params *P, omp_pyrand *rng,
                omp_ranked3 *ranked, omp_decision *out)
{
    memset(out, 0, sizeof *out);
    out->pick = UINT32_MAX;
    out->epsilon = prefs->epsilon;
    if (cur >= pack->n) return -1;

    /* the tail: the last 11 of the queue window that aren't cur, then cur */
    uint32_t tail[12];
    int nt = 0;
    {
        uint32_t tmp[11];
        int k = 0;
        for (int i = n_ex - 1; i >= 0 && k < 11; i--) if (ex[i] != cur) tmp[k++] = ex[i];
        for (int i = k - 1; i >= 0; i--) tail[nt++] = tmp[i];
        tail[nt++] = cur;
    }
    /* rejected: earlier verdicts of this sitting + how cur itself ended */
    uint32_t rej[13];
    int nr = session_rejects(pack, plays, n_plays, tail, nt - 1, now, rej);
    if (outcome == OMP_OUT_SKIP || outcome == OMP_OUT_DISLIKE) {
        if ((outcome != OMP_OUT_SKIP || is_early(pack, cur, secs)) && !has(rej, nr, cur)) rej[nr++] = cur;
    } else if (outcome == OMP_OUT_NONE) {
        uint32_t one[1];
        if (session_rejects(pack, plays, n_plays, &cur, 1, now, one) && !has(rej, nr, cur)) rej[nr++] = cur;
    }
    out->n_rejected = nr;
    static float v[OMP_DIM];
    uint32_t anchor = cur;
    if (has(rej, nr, cur))
        for (int i = nt - 2; i >= 0; i--)
            if (!has(rej, nr, tail[i]) && omp_pack_vec(pack, tail[i], v) == 0) { anchor = tail[i]; break; }
    out->anchor = anchor;
    uint32_t mood[12];
    int nm = 0;
    for (int i = 0; i < nt; i++) if (!has(rej, nr, tail[i])) mood[nm++] = tail[i];
    if (!nm) mood[nm++] = anchor;
    int n_recent = nt < 6 ? nt : 6;
    const uint32_t *recent = tail + (nt - n_recent);

    /* retrieval (blend_candidates, LOW_MEM caps): neighbours, radio, a never-played slice */
    uint32_t *nb = malloc((size_t)pack->k * 4), *cand = malloc((size_t)(pack->k + 64) * 4);
    if (!nb || !cand) { free(nb); free(cand); return -1; }
    int n_nb = omp_pack_neighbors(pack, anchor, nb), nc = 0;
    #define TAKEABLE(x) (!has(cand, nc, (x)) && !has(ex, n_ex, (x)) && (x) != cur && (x) < pack->n)
    for (int i = 0; i < n_nb && nc < BLEND_CUR; i++) if (TAKEABLE(nb[i])) cand[nc++] = nb[i];
    const uint32_t *rm; int rn;
    cooc_row(d, anchor, &rm, &rn);
    for (int i = 0, k = 0; i < rn && k < BLEND_RADIO; i++) if (TAKEABLE(rm[i])) { cand[nc++] = rm[i]; k++; }
    {
        static uint32_t pool[256];
        int np = 0;
        for (int i = 0; i < n_nb && np < 256; i++)
            if (TAKEABLE(nb[i]) && omp_map_get(&prefs->counts, nb[i], 0.0f) == 0.0f) pool[np++] = nb[i];
        if (np) {
            static omp_pyrand fr;
            const char *vid = omp_pack_id(pack, anchor);
            pyr_seed_str(&fr, vid, 11);
            uint32_t pick[BLEND_FRESH];
            int k = np < BLEND_FRESH ? np : BLEND_FRESH;
            if (pyr_sample(&fr, pool, np, k, pick) == 0)
                for (int i = 0; i < k; i++) if (TAKEABLE(pick[i])) cand[nc++] = pick[i];
        }
    }
    #undef TAKEABLE
    if (nc > BLEND_TOTAL) nc = BLEND_TOTAL;
    free(nb);
    out->n_cand = nc;
    if (!nc) { free(cand); return 0; }

    /* context vectors */
    static float cur_vec[OMP_DIM], session[OMP_DIM], sskip[OMP_DIM];
    int have_cur = omp_pack_vec(pack, anchor, cur_vec) == 0;
    iw me[12];
    {
        double wt[12], tot = 0.0;
        for (int i = 0; i < nm; i++) { wt[i] = pow(MOOD_DECAY, nm - 1 - i); tot += wt[i]; }
        int k = 0;                                                /* merge repeats (dict) */
        for (int i = 0; i < nm; i++) {
            int j;
            for (j = 0; j < k; j++) if (me[j].idx == mood[i]) break;
            if (j == k) { me[k].idx = mood[i]; me[k].w = 0.0f; k++; }
            me[j].w = (float)((double)me[j].w + wt[i] / tot);
        }
        nm = k;
    }
    int have_session = centroid_seeded(pack, NULL, 0.0, me, nm, session);
    iw re[13];
    for (int i = 0; i < nr; i++) { re[i].idx = rej[i]; re[i].w = 1.0f; }
    int have_sskip = nr ? centroid_seeded(pack, NULL, 0.0, re, nr, sskip) : 0;
    static float rvec[6 * OMP_DIM];
    int nrv = 0;
    for (int i = 0; i < n_recent; i++)
        if (omp_pack_vec(pack, recent[i], rvec + (size_t)nrv * OMP_DIM) == 0) nrv++;
    uint32_t ra[6];
    int nra = 0;
    for (int i = n_recent - (n_recent < 4 ? n_recent : 4); i < n_recent; i++) {
        uint32_t a = omp_pack_track(pack, recent[i])->artist_off;
        if (a && !has(ra, nra, a)) ra[nra++] = a;
    }
    uint32_t cur_art = omp_pack_track(pack, cur)->artist_off;
    if (cur_art && !has(ra, nra, cur_art)) ra[nra++] = cur_art;

    /* one pass of dot products, then the window scale, then the scores */
    double *dv = malloc((size_t)nc * 6 * sizeof(double));
    if (!dv) { free(cand); return -1; }
    int nk = 0;
    for (int i = 0; i < nc; i++) {
        if (omp_pack_vec(pack, cand[i], v) != 0) continue;
        double *r = dv + (size_t)nk * 6;
        r[0] = have_cur ? dotf(v, cur_vec) : 0.0;
        r[1] = have_session ? dotf(v, session) : 0.0;
        r[2] = taste ? dotf(v, taste) : 0.0;
        r[3] = skip ? dotf(v, skip) : 0.0;
        r[4] = have_sskip ? dotf(v, sskip) : 0.0;
        float mx = -2.0f;
        for (int k = 0; k < nrv; k++) { float x = dotf(rvec + (size_t)k * OMP_DIM, v); if (x > mx) mx = x; }
        r[5] = nrv ? mx : -2.0;
        ranked[nk].idx = cand[i];
        ranked[nk].pos = (uint32_t)i;
        nk++;
    }
    omp_v3_params p = *P;
    if (p.window && nk) {
        double *col = malloc((size_t)nk * sizeof(double));
        if (!col) { free(dv); free(cand); return -1; }
        double u = WINDOW_U_DEFAULT;
        if (have_cur && nk >= 2) {
            for (int i = 0; i < nk; i++) col[i] = (float)dv[i * 6 + 0];
            u = std_of(col, nk);
            if (u < WINDOW_U_FLOOR) u = WINDOW_U_FLOOR;
        }
        struct { double *w; int col, on, pos; } cos_terms[] = {
            { &p.mu, 1, have_session, 0 }, { &p.delta, 2, taste != NULL, 0 },
            { &p.sigma, 3, skip != NULL, 1 }, { &p.kappa, 4, have_sskip, 1 } };
        for (int t = 0; t < 4; t++) {
            if (!cos_terms[t].on || *cos_terms[t].w == 0.0) continue;
            for (int i = 0; i < nk; i++) {
                double x = (float)dv[i * 6 + cos_terms[t].col];
                col[i] = cos_terms[t].pos && x < 0.0 ? 0.0 : x;
            }
            double sd = std_of(col, nk);
            *cos_terms[t].w = sd > 1e-6 ? *cos_terms[t].w * u / sd : 0.0;
        }
        p.gamma *= u; p.gamma_artist *= u; p.cooldown *= u; p.nu *= u; p.beta *= u;
        p.heard_w *= u; p.energy_w *= u; p.bpm_w *= u;
        free(col);
    }
    const uint32_t *am; int an;
    cooc_row(d, anchor, &am, &an);
    int e_cur = d && d->energy ? d->energy[anchor] : 255;
    double b_cur = d && d->bpm10 && d->bpm10[anchor] ? d->bpm10[anchor] / 10.0 : 0.0;
    double free_ = log2(BPM_FREE_RATIO), span = log2(BPM_FULL_RATIO) - free_;
    for (int i = 0; i < nk; i++) {
        omp_ranked3 *r = &ranked[i];
        const double *x = dv + (size_t)i * 6;
        uint32_t j = r->idx;
        float *t = r->terms;
        memset(t, 0, sizeof r->terms);
        if (have_cur) {
            t[OMP_T_VIBE] = (float)(p.alpha * x[0]);
            if (p.same_w) { double o = x[0] - p.same_floor; t[OMP_T3_SAME] = (float)(-p.same_w * (o > 0 ? o : 0)); }
        }
        if (have_session) t[OMP_T_MOOD] = (float)(p.mu * x[1]);
        if (taste) t[OMP_T_TASTE] = (float)(p.delta * x[2]);
        double tp = omp_map_get(&prefs->base.track_pref, j, 0.0f);
        t[OMP_T_PREF_TRACK] = (float)(p.gamma * (p.track_tanh ? tanh(tp) : tp));
        uint32_t art = omp_pack_track(pack, j)->artist_off;
        if (art) {
            double a = omp_map_get(&prefs->base.artist_pref, art, 0.0f);
            if (p.artist_prior) a = a / ((double)omp_map_get(&prefs->artist_mass, art, 0.0f) + p.artist_prior);
            t[OMP_T_PREF_ARTIST] = (float)(p.gamma_artist * tanh(a));
            if (has(ra, nra, art)) t[OMP_T_COOLDOWN] = (float)-p.cooldown;
        }
        if (skip) t[OMP_T_SKIP] = (float)(-p.sigma * (x[3] > 0 ? x[3] : 0));
        if (nrv) { double o = x[5] - p.rho_floor; t[OMP_T_FATIGUE] = (float)(-p.rho * (o > 0 ? o : 0)); }
        t[OMP_T_NOVELTY] = (float)(p.nu * pow(0.5, omp_map_get(&prefs->counts, j, 0.0f)));
        if (d && d->cooc_off) {
            const uint32_t *cm; int cn;
            cooc_row(d, j, &cm, &cn);
            if (has(am, an, j) || has(cm, cn, anchor)) t[OMP_T3_COOC] = (float)p.beta;
        }
        float age = omp_map_get(&prefs->heard_age, j, -1.0f);
        if (age >= 0.0f && age < HEARD_MAX_AGE)
            t[OMP_T3_HEARD] = (float)(-p.heard_w * pow(0.5, age / p.heard_halflife));
        if (e_cur != 255 && d->energy[j] != 255) {
            double o = fabs(d->energy[j] / 254.0 - e_cur / 254.0) - p.energy_band;
            t[OMP_T3_ENERGY] = (float)(-p.energy_w * (o > 0 ? o : 0));
        }
        if (b_cur > 0.0 && d->bpm10[j]) {
            double rr = log2((d->bpm10[j] / 10.0) / b_cur);
            double dd = fmin(fabs(rr - 1.0), fmin(fabs(rr), fabs(rr + 1.0)));
            if (dd > free_) t[OMP_T3_BPM] = (float)(-p.bpm_w * fmin(1.0, (dd - free_) / span));
        }
        if (have_sskip) t[OMP_T3_SSKIP] = (float)(-p.kappa * (x[4] > 0 ? x[4] : 0));
        /* personalize's dict order: vibe taste pref_track pref_artist cooldown skip
         * fatigue mood novelty cooc heard energy bpm sameness [sskip] */
        static const int order[] = { OMP_T_VIBE, OMP_T_TASTE, OMP_T_PREF_TRACK, OMP_T_PREF_ARTIST,
            OMP_T_COOLDOWN, OMP_T_SKIP, OMP_T_FATIGUE, OMP_T_MOOD, OMP_T_NOVELTY, OMP_T3_COOC,
            OMP_T3_HEARD, OMP_T3_ENERGY, OMP_T3_BPM, OMP_T3_SAME, OMP_T3_SSKIP };
        double s = 0.0;
        for (int k = 0; k < (int)(sizeof order / sizeof order[0]); k++) s += (double)t[order[k]];
        r->score = s;
    }
    free(dv);
    free(cand);
    qsort(ranked, (size_t)nk, sizeof *ranked, cmp_r3);
    out->n_ranked = nk;

    /* choose_next_explained: exploit, or a Thompson-sampled cluster's best unheard track
     * within the sound budget, else the best unheard, else a random top-4 */
    out->reason = OMP_PICK_EXPLOIT;
    if (!nk) return 0;
    if (pyr_random(rng) >= prefs->epsilon) { out->pick = ranked[0].idx; return 0; }
    int win = nk < CLUSTER_WINDOW ? nk : CLUSTER_WINDOW;
    uint8_t ok[CLUSTER_WINDOW];
    {
        double *snd = malloc((size_t)nk * sizeof(double)), mx = -1e300;
        if (!snd) return -1;
        for (int i = 0; i < nk; i++) {
            const float *t = ranked[i].terms;
            snd[i] = (double)t[OMP_T_VIBE] + (double)t[OMP_T_MOOD] + (double)t[OMP_T_FATIGUE] +
                     (double)t[OMP_T3_SAME];
            if (snd[i] > mx) mx = snd[i];
        }
        double floor_ = mx - SOUND_BUDGET * (std_of(snd, nk) + 1e-9);
        for (int i = 0; i < win; i++) ok[i] = snd[i] >= floor_;
        free(snd);
    }
    if (d && d->cluster && prefs->cl_acc) {
        uint16_t arms[CLUSTER_WINDOW];
        int na = 0;
        for (int i = 0; i < win; i++) {
            if (!ok[i]) continue;
            uint16_t c = d->cluster[ranked[i].idx];
            int seen = 0;
            for (int a = 0; a < na; a++) seen |= arms[a] == c;
            if (c != 0xFFFF && !seen) arms[na++] = c;
        }
        if (na) {
            double acc = 0.0, tot = 0.0;
            for (uint32_t c = 0; c < prefs->n_clusters; c++) { acc += prefs->cl_acc[c]; tot += prefs->cl_acc[c] + prefs->cl_skip[c]; }
            double rate = (acc + 1.0) / (tot + 2.0), a0 = PRIOR_N * rate, b0 = PRIOR_N * (1.0 - rate);
            int best = -1;
            double bv = 0.0;
            for (int a = 0; a < na; a++) {
                uint16_t c = arms[a];
                double x = pyr_betavariate(rng, prefs->cl_acc[c] + a0, prefs->cl_skip[c] + b0);
                if (best < 0 || x > bv) { best = c; bv = x; }
            }
            for (int i = 0; i < win; i++)
                if (ok[i] && d->cluster[ranked[i].idx] == best &&
                    omp_map_get(&prefs->counts, ranked[i].idx, 0.0f) == 0.0f) {
                    out->pick = ranked[i].idx;
                    out->reason = OMP_PICK_EXPLORE_UNHEARD;        /* explore_cluster */
                    return 0;
                }
        }
    }
    int lim = nk < TOP_K ? nk : TOP_K;
    for (int i = 0; i < lim; i++)
        if (omp_map_get(&prefs->counts, ranked[i].idx, 0.0f) == 0.0f && (i >= win || ok[i])) {
            out->pick = ranked[i].idx;
            out->reason = OMP_PICK_EXPLORE_UNHEARD;
            return 0;
        }
    int m4 = nk < 4 ? nk : 4;
    out->pick = ranked[pyr_randbelow(rng, (uint32_t)m4)].idx;
    out->reason = OMP_PICK_EXPLORE_RANDOM;
    return 0;
}
