#include "omp_speeddial.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define SD_WINDOW (8.0 * 86400.0)
#define SD_HALFLIFE (3.0 * 86400.0)

static double event_val(uint8_t event)
{
    switch (event) {
    case OMP_EV_LIKE: return 2.0;
    case OMP_EV_COMPLETE: return 1.5;
    case OMP_EV_PLAY: return 1.0;
    case OMP_EV_SKIP: return 0.1;
    case OMP_EV_DISLIKE: return -3.0;
    default: return 0.5;               /* EVENT_VAL.get(event, 0.5) — peek included */
    }
}

typedef struct { uint32_t idx; double score; double latest; } sd_entry;

static int cmp_score(const void *pa, const void *pb)
{
    const sd_entry *a = pa, *b = pb;
    if (a->score != b->score) return a->score > b->score ? -1 : 1;
    if (a->latest != b->latest) return a->latest > b->latest ? -1 : 1;
    return a->idx < b->idx ? -1 : (a->idx > b->idx ? 1 : 0);
}

static int cmp_latest(const void *pa, const void *pb)
{
    const sd_entry *a = pa, *b = pb;
    if (a->latest != b->latest) return a->latest > b->latest ? -1 : 1;
    return a->idx < b->idx ? -1 : (a->idx > b->idx ? 1 : 0);
}

typedef struct {
    uint32_t *out;
    int n, cap;
    omp_map artist_count;
    const omp_pack *pack;
} sd_state;

static int in_out(const sd_state *s, uint32_t idx)
{
    for (int i = 0; i < s->n; i++)
        if (s->out[i] == idx) return 1;
    return 0;
}

static int sd_add(sd_state *s, uint32_t idx, int cap)
{
    uint32_t art = omp_pack_track(s->pack, idx)->artist_off;
    float *cnt = omp_map_slot(&s->artist_count, art);
    if (!cnt || (int)*cnt >= cap) return 0;
    s->out[s->n++] = idx;
    *cnt += 1.0f;
    return 1;
}

/* Sparse: only tracks that appear in the log carry state, so memory follows the
 * history, not the library (the H2 plugin has 2 MiB in total). Every ranking stage
 * qsorts with an idx tie-break, so the result is independent of gather order and
 * identical to the dense version the goldens were written against. */
int omp_speeddial(omp_pack *pack, const omp_play *plays, int n_plays,
                  double now, int n_out, int fresh,
                  omp_rng01 rng, void *rng_state, uint32_t *out)
{
    sd_state s = { out, 0, n_out, { 0 }, pack };
    omp_map slot_of = { 0 };                          /* idx -> slot + 1 */
    uint32_t *idx_of = NULL;
    double *scores = NULL, *latest = NULL, *latest_pcl = NULL, *latest_any = NULL;
    sd_entry *tmp = NULL;
    int m = 0;
    if (omp_map_init(&s.artist_count, 64) != 0 || omp_map_init(&slot_of, 256) != 0) goto done;

    for (int i = 0; i < n_plays; i++) {
        if (plays[i].idx >= pack->n) continue;
        float *sl = omp_map_slot(&slot_of, plays[i].idx);
        if (!sl) goto done;
        if (*sl == 0.0f) *sl = (float)++m;
    }
    size_t mm = (size_t)(m ? m : 1);
    idx_of = malloc(mm * sizeof *idx_of);
    scores = calloc(mm, sizeof(double));
    latest = calloc(mm, sizeof(double));
    latest_pcl = calloc(mm, sizeof(double));      /* play/complete/like, any age */
    latest_any = calloc(mm, sizeof(double));
    tmp = malloc(mm * sizeof *tmp);
    if (!idx_of || !scores || !latest || !latest_pcl || !latest_any || !tmp) goto done;

    for (int i = 0; i < n_plays; i++) {
        const omp_play *ev = &plays[i];
        if (ev->idx >= pack->n) continue;
        int k = (int)omp_map_get(&slot_of, ev->idx, 0.0f) - 1;
        idx_of[k] = ev->idx;
        if (ev->ts > latest_any[k]) latest_any[k] = ev->ts;
        if ((ev->event == OMP_EV_PLAY || ev->event == OMP_EV_COMPLETE ||
             ev->event == OMP_EV_LIKE) && ev->ts > latest_pcl[k])
            latest_pcl[k] = ev->ts;
        if (ev->ts <= now - SD_WINDOW) continue;
        scores[k] += event_val(ev->event) * pow(0.5, (now - ev->ts) / SD_HALFLIFE);
        if (ev->ts > latest[k]) latest[k] = ev->ts;
    }

    /* fresh mode leads with the most-recent distinct positive plays (cap 5) */
    if (fresh) {
        int t = 0;
        for (int k = 0; k < m; k++)
            if (latest_pcl[k] > 0.0) {
                tmp[t].idx = idx_of[k]; tmp[t].latest = latest_pcl[k]; tmp[t].score = 0.0; t++;
            }
        qsort(tmp, (size_t)t, sizeof *tmp, cmp_latest);
        int lim = t < n_out * 3 ? t : n_out * 3;
        for (int i = 0; i < lim && s.n < n_out; i++)
            if (!in_out(&s, tmp[i].idx))
                sd_add(&s, tmp[i].idx, 5);
    }

    /* recency-weighted frequency ranking, net-positive only, artist cap 3 */
    {
        int t = 0;
        for (int k = 0; k < m; k++)
            if (scores[k] > 0.0) {
                tmp[t].idx = idx_of[k]; tmp[t].score = scores[k]; tmp[t].latest = latest[k]; t++;
            }
        qsort(tmp, (size_t)t, sizeof *tmp, cmp_score);
        for (int i = 0; i < t && s.n < n_out; i++)
            if (!in_out(&s, tmp[i].idx))
                sd_add(&s, tmp[i].idx, 3);
    }

    /* pad 1: most-recent plays of any kind (appended without the artist cap) */
    if (s.n < n_out) {
        int t = 0;
        for (int k = 0; k < m; k++)
            if (latest_any[k] > 0.0) {
                tmp[t].idx = idx_of[k]; tmp[t].latest = latest_any[k]; tmp[t].score = 0.0; t++;
            }
        qsort(tmp, (size_t)t, sizeof *tmp, cmp_latest);
        int lim = t < n_out * 4 ? t : n_out * 4;
        for (int i = 0; i < lim && s.n < n_out; i++)
            if (!in_out(&s, tmp[i].idx))
                out[s.n++] = tmp[i].idx;
    }

    /* pad 2: random library tracks */
    if (s.n < n_out && rng) {
        for (int tries = 0; tries < n_out * 4 && s.n < n_out; tries++) {
            uint32_t i = (uint32_t)(rng(rng_state) * pack->n) % pack->n;
            if (!in_out(&s, i))
                out[s.n++] = i;
        }
    }

done:
    ;
    int n = s.n;
    omp_map_free(&s.artist_count);
    omp_map_free(&slot_of);
    free(idx_of); free(scores); free(latest); free(latest_pcl); free(latest_any); free(tmp);
    return n;
}
