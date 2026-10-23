#include "omp_radio.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* player_server/radio.py's constants */
#define MAX_RUN 2
#define SEED_ARTIST_SHARE 0.3f
#define REJECT_W 2.0f
#define FAMILIAR_SHARE 0.35f
#define FAMILIAR_PULL 0.3f
#define GAME_PULL 0.5f
#define ARTIST_PULL 0.75f
#define SCAN 300
#define OVER_CAP 2.0f
#define ARTIST_OVER_CAP 4.0f
#define SEED_GAME_SHARE 0.45f
#define SHARE_SCALE 250.0f      /* radio_pack.py's ashare / gshare */
#define SHARE_WINDOW 12
#define MAX_K 256
#define MAX_REJ 16
#define MAX_DIM 128

static uint32_t rd32(const uint8_t *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }

void omp_radio_free(omp_radio *r)
{
    free(r->count); free(r->known); free(r->game); free(r->chan); free(r->chan2); free(r->work);
    free(r->ashare); free(r->gshare); free(r->fshare);
    memset(r, 0, sizeof *r);
}

int omp_radio_load(omp_radio *r, const char *pack_dir, uint32_t n)
{
    memset(r, 0, sizeof *r);
    snprintf(r->path, sizeof r->path, "%s/radio.bin", pack_dir);
    FILE *f = fopen(r->path, "rb");
    if (!f) return -1;
    uint8_t h[16];
    int got = fread(h, 1, 16, f) == 16;
    int v2 = got && !memcmp(h, "CRA2", 4);                         /* CRA1: one artist, no works */
    if (!got || (!v2 && memcmp(h, "CRA1", 4)) || rd32(h + 4) != n ||
        rd32(h + 8) == 0 || rd32(h + 8) > MAX_K || rd32(h + 12) > MAX_DIM) {
        fclose(f);
        return -1;
    }
    r->n = n; r->k = rd32(h + 8); r->dim = rd32(h + 12);
    r->count = malloc((size_t)n * 2);
    r->known = malloc(n);
    r->game = malloc(n);
    r->chan = malloc((size_t)n * 4);
    r->chan2 = calloc(n, 4);
    r->work = calloc(n, 4);
    int ok = r->count && r->known && r->game && r->chan && r->chan2 && r->work &&
             fread(r->count, 2, n, f) == n && fread(r->known, 1, n, f) == n &&
             fread(r->game, 1, n, f) == n && fread(r->chan, 4, n, f) == n &&
             (!v2 || (fread(r->chan2, 4, n, f) == n && fread(r->work, 4, n, f) == n));
    if (!ok) { fclose(f); omp_radio_free(r); return -1; }
    /* the file is little-endian, like both the H2 and the PC */
    r->rows_off = 16 + (long)n * (2 + 1 + 1 + 4 + (v2 ? 8 : 0));
    r->s2v_off = r->rows_off + (long)n * r->k * 6;
    /* each seed's channel / game-series share (radio.shares), after the song2vec rows;
       a file without them keeps the fixed shares */
    uint8_t m[4];
    if (fseek(f, r->s2v_off + (long)n * r->dim, SEEK_SET) == 0 && fread(m, 1, 4, f) == 4 &&
        !memcmp(m, "SHR1", 4)) {
        r->ashare = malloc(n);
        r->gshare = malloc(n);
        if (!r->ashare || !r->gshare || fread(r->ashare, 1, n, f) != n || fread(r->gshare, 1, n, f) != n) {
            free(r->ashare); free(r->gshare);
            r->ashare = r->gshare = NULL;
        } else if (fread(m, 1, 4, f) == 4 && !memcmp(m, "FAM1", 4)) {
            /* each seed's familiar share (radio.seed_familiar_share), after those */
            r->fshare = malloc(n);
            if (r->fshare && fread(r->fshare, 1, n, f) != n) { free(r->fshare); r->fshare = NULL; }
        }
    }
    fclose(f);
    r->ok = 1;
    return 0;
}

static int has(const uint32_t *a, int n, uint32_t v)
{
    for (int i = 0; i < n; i++) if (a[i] == v) return 1;
    return 0;
}

static float dot(const float *a, const float *b, int n)
{
    float s = 0.0f;
    for (int i = 0; i < n; i++) s += a[i] * b[i];
    return s;
}

static int s2v_row(FILE *f, const omp_radio *r, uint32_t i, int8_t *out)
{
    if (!r->dim || fseek(f, r->s2v_off + (long)i * r->dim, SEEK_SET) != 0 ||
        fread(out, 1, r->dim, f) != r->dim)
        return 0;
    for (uint32_t d = 0; d < r->dim; d++) if (out[d]) return 1;
    return 0;                                   /* all zero: no song2vec vector */
}

typedef struct { uint32_t idx; float s; } slot;

/* another version of the seed, of a song excluded, or of one in the tail (radio.work_key) */
static int heard_work(const omp_radio *r, uint32_t w, uint32_t seed, const uint32_t *ex, int n_ex,
                      const uint32_t *tail, int nt)
{
    if (r->work[seed] == w) return 1;
    for (int i = 0; i < n_ex; i++) if (ex[i] < r->n && r->work[ex[i]] == w) return 1;
    for (int i = 0; i < nt; i++) if (tail[i] < r->n && r->work[tail[i]] == w) return 1;
    return 0;
}

/* the artists two songs credit have one in common (radio.credits: up to two each) */
static int same_artist(const omp_radio *r, uint32_t a, uint32_t b)
{
    uint32_t a1 = r->chan[a], a2 = r->chan2[a], b1 = r->chan[b], b2 = r->chan2[b];
    return (a1 && (a1 == b1 || a1 == b2)) || (a2 && (a2 == b1 || a2 == b2));
}

/* songs past `share` of the slots so far if one more of this kind came now, at most cap */
static float over(int count, float share, int shown, float cap)
{
    float base = share * (shown + 1);
    if (base < 1.0f) base = 1.0f;
    float o = count + 1 - base;
    return o < 0.0f ? 0.0f : o > cap ? cap : o;
}

uint32_t omp_radio_next(const omp_radio *r, omp_pack *pack, uint32_t seed,
                        const uint32_t *tail, int nt, const uint32_t *ex, int n_ex,
                        const uint32_t *rej, int nr, const uint32_t *known_extra, int n_known)
{
    if (!r->ok || seed >= r->n || !r->count[seed]) return UINT32_MAX;
    static uint8_t raw[MAX_K * 6];
    static slot c[MAX_K];
    static float rv[MAX_REJ][OMP_DIM], v[OMP_DIM];
    static int8_t rs[MAX_REJ][MAX_DIM], cs[MAX_DIM];
    FILE *f = fopen(r->path, "rb");
    if (!f) return UINT32_MAX;
    uint32_t k = r->count[seed];
    if (fseek(f, r->rows_off + (long)seed * r->k * 6, SEEK_SET) != 0 || fread(raw, 6, k, f) != k) {
        fclose(f);
        return UINT32_MAX;
    }
    int nc = 0;
    for (uint32_t i = 0; i < k; i++) {
        const uint8_t *p = raw + 6 * i;
        uint32_t idx = rd32(p);
        int16_t sc = (int16_t)(p[4] | (p[5] << 8));
        if (idx >= r->n || idx == seed || has(ex, n_ex, idx)) continue;
        if (r->work[idx] && heard_work(r, r->work[idx], seed, ex, n_ex, tail, nt)) continue;
        c[nc].idx = idx;
        c[nc].s = sc / 1000.0f;
        nc++;
    }
    /* radio.reject_cost: resembling a song you turned down, by sound or song2vec */
    int nsr = 0, nss = 0;
    if (nr > MAX_REJ) nr = MAX_REJ;
    for (int j = 0; j < nr; j++) {
        if (omp_pack_vec(pack, rej[j], rv[nsr]) == 0) nsr++;
        if (s2v_row(f, r, rej[j], rs[nss])) nss++;
    }
    if (nsr || nss) {
        for (int i = 0; i < nc; i++) {
            float m = 0.0f;
            if (nsr && omp_pack_vec(pack, c[i].idx, v) == 0)
                for (int j = 0; j < nsr; j++) { float d = dot(v, rv[j], OMP_DIM); if (d > m) m = d; }
            if (nss && s2v_row(f, r, c[i].idx, cs))
                for (int j = 0; j < nss; j++) {
                    int32_t d = 0;
                    for (uint32_t q = 0; q < r->dim; q++) d += cs[q] * rs[j][q];
                    float df = d / (127.0f * 127.0f);
                    if (df > m) m = df;
                }
            c[i].s -= REJECT_W * m;
        }
        for (int i = 1; i < nc; i++) {                     /* best first again */
            slot t = c[i];
            int j = i - 1;
            while (j >= 0 && c[j].s < t.s) { c[j + 1] = c[j]; j--; }
            c[j + 1] = t;
        }
    }
    fclose(f);
    if (!nc) return UINT32_MAX;

    /* radio.sequence for one slot */
    #define KNOWN(x) (r->known[x] || has(known_extra, n_known, (x)))
    uint8_t seed_f = r->game[seed];
    const uint32_t *recent = tail + (nt > SHARE_WINDOW ? nt - SHARE_WINDOW : 0);
    int shown = nt > SHARE_WINDOW ? SHARE_WINDOW : nt, n_known_t = 0, n_art = 0, n_fr = 0;
    for (int i = 0; i < shown; i++) {
        uint32_t x = recent[i];
        if (x >= r->n) continue;
        n_known_t += KNOWN(x) ? 1 : 0;
        n_art += same_artist(r, x, seed);
        n_fr += seed_f && r->game[x] == seed_f;
    }
    /* the run: what the last MAX_RUN (2) songs both credit; a candidate crediting it waits */
    uint32_t run[2] = {0, 0};
    if (shown >= MAX_RUN && recent[shown - 1] < r->n && recent[shown - 2] < r->n) {
        uint32_t p = recent[shown - 2], q = recent[shown - 1], k = 0;
        uint32_t pc[2] = {r->chan[p], r->chan2[p]};
        for (int j = 0; j < 2; j++)
            if (pc[j] && (pc[j] == r->chan[q] || pc[j] == r->chan2[q]) && pc[j] != run[0]) run[k++] = pc[j];
    }
    float fam_sh = r->fshare ? r->fshare[seed] / SHARE_SCALE : FAMILIAR_SHARE;
    float want = fam_sh * (shown + 1) - n_known_t;
    float pull = FAMILIAR_PULL * (want < -1.0f ? -1.0f : want > 1.0f ? 1.0f : want);
    /* radio.shares: lower for a channel / series whose YT Music radios mostly go elsewhere */
    float a_sh = r->ashare ? r->ashare[seed] / SHARE_SCALE : SEED_ARTIST_SHARE;
    float g_sh = r->gshare ? r->gshare[seed] / SHARE_SCALE : SEED_GAME_SHARE;
    float cost_a = ARTIST_PULL * over(n_art, a_sh, shown, ARTIST_OVER_CAP);
    float cost_f = GAME_PULL * over(n_fr, g_sh, shown, OVER_CAP);
    int best = -1, fallback = -1;
    float best_s = -1e30f, lift = pull > 0.0f ? pull : 0.0f;
    for (int i = 0; i < nc && i < SCAN; i++) {
        if (c[i].s + lift <= best_s) break;                /* sorted: nothing below can win */
        uint32_t x = c[i].idx, a1 = r->chan[x], a2 = r->chan2[x];
        if ((run[0] && (a1 == run[0] || a2 == run[0])) || (run[1] && (a1 == run[1] || a2 == run[1]))) {
            if (fallback < 0) fallback = i;
            continue;
        }
        float eff = c[i].s + (KNOWN(x) ? pull : 0.0f);
        if (same_artist(r, x, seed)) eff -= cost_a;
        if (seed_f && r->game[x] == seed_f) eff -= cost_f;
        if (eff > best_s) { best = i; best_s = eff; }
    }
    #undef KNOWN
    if (best < 0) best = fallback >= 0 ? fallback : 0;
    return c[best].idx;
}
