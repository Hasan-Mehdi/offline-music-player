/* Engine v3 parity: omp_next_v3 == the web player's next_decision on the same pack and
 * history (fixtures: firmware/tools/gen_goldens_v3.py).
 *   test_engine3 <device_pack_v3> <goldens_v3>
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "omp_engine3.h"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; if (fails < 40) { printf("FAIL: " __VA_ARGS__); printf("\n"); } } } while (0)

static FILE *fx;
static void rd(void *p, size_t n) { if (fread(p, 1, n, fx) != n) { printf("short fixture\n"); exit(2); } }

static int cmp_pos(const void *a, const void *b)
{
    uint32_t x = ((const omp_ranked3 *)a)->pos, y = ((const omp_ranked3 *)b)->pos;
    return x < y ? -1 : x > y;
}

int main(int argc, char **argv)
{
    if (argc < 3) { printf("usage: test_engine3 <pack_v3> <goldens_v3>\n"); return 2; }
    omp_pack pk;
    if (omp_pack_open(&pk, argv[1], OMP_PACK_LOAD_ALL) != 0) { printf("pack open failed\n"); return 2; }
    omp_v3data d;
    if (omp_v3_load(&d, argv[1], pk.n) != 0) { printf("not an engine-3 pack\n"); return 2; }
    char path[600];
    snprintf(path, sizeof path, "%s/plays.bin", argv[2]);
    omp_play *plays = NULL;
    int np = omp_playlog_load(path, &plays);
    snprintf(path, sizeof path, "%s/expect.bin", argv[2]);
    fx = fopen(path, "rb");
    if (np < 0 || !fx) { printf("fixtures missing\n"); return 2; }
    double now, eps;
    rd(&now, 8); rd(&eps, 8);
    uint8_t has_t, has_s;
    rd(&has_t, 1); rd(&has_s, 1);
    static float et[OMP_DIM], es[OMP_DIM], t[OMP_DIM], s[OMP_DIM];
    rd(et, sizeof et); rd(es, sizeof es);

    omp_prefs3 pr;
    CHECK(omp_prefs3_compute(&pk, &d, plays, np, now, &pr) == 0, "prefs3");
    CHECK(fabs(pr.epsilon - eps) < 1e-12, "epsilon %.6f != %.6f", pr.epsilon, eps);
    int ht = omp_taste3(&pk, &d, &pr, t), hs = omp_skip3(&pk, &pr, s);
    CHECK(ht == has_t && hs == has_s, "centroid presence %d/%d vs %d/%d", ht, hs, has_t, has_s);
    double dt = 0, ds = 0;
    for (int k = 0; k < OMP_DIM; k++) { dt += (double)t[k] * et[k]; ds += (double)s[k] * es[k]; }
    if (has_t) CHECK(dt > 0.99999, "taste dot %.7f", dt);
    if (has_s) CHECK(ds > 0.99999, "skip dot %.7f", ds);

    uint32_t n_cases;
    rd(&n_cases, 4);
    omp_v3_params P = omp_v3_default_params();
    omp_ranked3 *rk = malloc(sizeof *rk * (pk.k + 64));
    int picks_ok = 0, explored = 0;
    double worst = 0.0;
    for (uint32_t c = 0; c < n_cases; c++) {
        uint32_t nex, cur, seed, anchor, pick, ncand, nrank;
        uint8_t oc;
        float secs, eps_case;
        rd(&nex, 4); rd(&cur, 4); rd(&oc, 1); rd(&secs, 4); rd(&eps_case, 4); rd(&seed, 4); rd(&anchor, 4);
        rd(&pick, 4); rd(&ncand, 4); rd(&nrank, 4);
        uint32_t *ex = malloc(4 * (nex + 1)), *cand = malloc(4 * (ncand + 1));
        rd(ex, 4 * nex);
        rd(cand, 4 * ncand);
        uint32_t *ri = malloc(4 * (nrank + 1));
        double *rs = malloc(8 * (nrank + 1));
        for (uint32_t i = 0; i < nrank; i++) { rd(&ri[i], 4); rd(&rs[i], 8); }

        omp_pyrand rng;
        pyr_seed_u64(&rng, seed);
        omp_decision dec;
        pr.epsilon = eps_case < 0.0f ? eps : (double)eps_case;
        int rc = omp_next_v3(&pk, &d, &pr, ht ? t : NULL, hs ? s : NULL, plays, np, ex, (int)nex,
                             cur, oc, secs, now, &P, &rng, rk, &dec);
        CHECK(rc == 0, "case %u rc %d", c, rc);
        CHECK(dec.anchor == anchor, "case %u anchor %u != %u", c, dec.anchor, anchor);
        CHECK(dec.n_ranked == (int)nrank, "case %u ranked %d != %u", c, dec.n_ranked, nrank);
        /* scores per track, and the order up to float ties */
        for (int i = 0; i < dec.n_ranked && i < (int)nrank; i++) {
            int found = -1;
            for (uint32_t j = 0; j < nrank; j++) if (ri[j] == rk[i].idx) { found = (int)j; break; }
            CHECK(found >= 0, "case %u: %u ranked but not expected", c, rk[i].idx);
            if (found < 0) continue;
            double dlt = fabs(rk[i].score - rs[found]);
            if (dlt > worst) worst = dlt;
            CHECK(dlt < 5e-4, "case %u: score of %u %.6f != %.6f", c, rk[i].idx, rk[i].score, rs[found]);
            if (rk[i].idx != ri[i])
                CHECK(fabs(rs[i] - rk[i].score) < 1e-3, "case %u rank %d: %u (%.6f) vs %u (%.6f)",
                      c, i, rk[i].idx, rk[i].score, ri[i], rs[i]);
        }
        CHECK(dec.pick == pick, "case %u pick %u != %u (reason %d)", c, dec.pick, pick, dec.reason);
        picks_ok += dec.pick == pick;
        explored += dec.reason != OMP_PICK_EXPLOIT;
        /* candidate retrieval order */
        qsort(rk, (size_t)dec.n_ranked, sizeof *rk, cmp_pos);
        int same = dec.n_ranked == (int)ncand;
        for (int i = 0; same && i < dec.n_ranked; i++) same = rk[i].idx == cand[i];
        CHECK(same, "case %u: candidate list differs (%d vs %u)", c, dec.n_ranked, ncand);
        free(ex); free(cand); free(ri); free(rs);
    }
    printf("test_engine3: %u cases, %d picks match, %d explored, worst score diff %.2e\n",
           n_cases, picks_ok, explored, worst);
    if (fails) { printf("test_engine3: %d FAILURES\n", fails); return 1; }
    printf("test_engine3: OK - C engine v3 == web player next_decision\n");
    return 0;
}
