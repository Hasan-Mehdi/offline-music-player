/* Pack-reader sanity: LOAD_ALL vs STREAM vs STREAM_ALL equivalence, unit norms, neighbor
 * plausibility, string/id integrity, gain decode.  Usage: test_pack <pack_dir> */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "omp_fp16.h"
#include "omp_gain.h"
#include "omp_pack.h"

static int fails;
#define CHECK(cond, ...) do { if (!(cond)) { fails++; printf("FAIL: " __VA_ARGS__); printf("\n"); } } while (0)

int main(int argc, char **argv)
{
    if (argc < 2) { printf("usage: test_pack <pack_dir>\n"); return 2; }
    omp_pack pa, ps, pz;
    CHECK(omp_pack_open(&pa, argv[1], OMP_PACK_LOAD_ALL) == 0, "open LOAD_ALL");
    CHECK(omp_pack_open(&ps, argv[1], OMP_PACK_STREAM) == 0, "open STREAM");
    CHECK(omp_pack_open(&pz, argv[1], OMP_PACK_STREAM_ALL) == 0, "open STREAM_ALL");
    if (fails) return 1;
    printf("pack: %u tracks, k=%u\n", pa.n, pa.k);

    uint32_t samples[] = { 0, 7, pa.n / 3, pa.n / 2, pa.n - 1 };
    float va[OMP_DIM], vs[OMP_DIM];
    uint32_t na[512], ns[512];
    for (int t = 0; t < 5; t++) {
        uint32_t i = samples[t];
        CHECK(omp_pack_vec(&pa, i, va) == 0, "vec load_all %u", i);
        CHECK(omp_pack_vec(&ps, i, vs) == 0, "vec stream %u", i);
        CHECK(memcmp(va, vs, sizeof va) == 0, "vec modes differ at %u", i);
        double sq = 0;
        for (int d = 0; d < OMP_DIM; d++) sq += (double)va[d] * va[d];
        CHECK(fabs(sqrt(sq) - 1.0) < 2e-3, "norm %u = %f", i, sqrt(sq));
        int ca = omp_pack_neighbors(&pa, i, na), cs = omp_pack_neighbors(&ps, i, ns);
        CHECK(ca == cs && memcmp(na, ns, (size_t)pa.k * 4) == 0, "nbr modes differ at %u", i);
        CHECK(ca > 0 && ca <= (int)pa.k, "nbr count %u = %d", i, ca);

        /* brute-force top-1 must essentially match neighbors[0] */
        float best = -2.0f, vj[OMP_DIM], v0[OMP_DIM];
        for (uint32_t j = 0; j < pa.n; j++) {
            if (j == i) continue;
            const uint16_t *h = pa.emb + (size_t)j * OMP_DIM;
            float s = 0;
            for (int d = 0; d < OMP_DIM; d++)
                s += va[d] * omp_half_to_float(h[d]);
            if (s > best) best = s;
        }
        omp_pack_vec(&pa, na[0], vj);
        memcpy(v0, vj, sizeof v0);
        float s0 = 0;
        for (int d = 0; d < OMP_DIM; d++) s0 += va[d] * v0[d];
        CHECK(best - s0 < 1e-3f, "top nbr of %u: stored sim %f vs brute best %f", i, s0, best);

        const omp_track *tr = omp_pack_track(&pa, i);
        const char *file = omp_pack_str(&pa, tr->file_off);
        CHECK(strstr(file, "/") != NULL, "file not sharded: %s", file);
        CHECK(strlen(file) > 6 && strcmp(file + strlen(file) - 5, ".opus") == 0,
              "file ext: %s", file);
        CHECK(file[0] == omp_pack_id(&pa, i)[0], "shard char mismatch: %s", file);
        float g = omp_gain_mult(tr->gain_q78);
        CHECK(g > 0.0f && g <= 1.0f, "gain mult %f", g);
    }


    /* STREAM_ALL (the H2 plugin's mode) must read back exactly what LOAD_ALL holds */
    for (uint32_t t = 0, i = 0; t < 3000; t++, i = (i * 2654435761u + 12345u) % pa.n) {
        const omp_track *a = omp_pack_track(&pa, i), *z = omp_pack_track(&pz, i);
        CHECK(memcmp(a, z, sizeof *a) == 0, "stream_all track %u", i);
        CHECK(strcmp(omp_pack_str(&pa, a->title_off), omp_pack_str(&pz, z->title_off)) == 0 ||
              strlen(omp_pack_str(&pa, a->title_off)) >= 255, "stream_all title %u", i);
        CHECK(strcmp(omp_pack_str(&pa, a->artist_off), omp_pack_str(&pz, z->artist_off)) == 0,
              "stream_all artist %u", i);
        CHECK(memcmp(omp_pack_id(&pa, i), omp_pack_id(&pz, i), 11) == 0, "stream_all id %u", i);
        if (t % 300 == 0) {
            CHECK(omp_pack_vec(&pa, i, va) == 0 && omp_pack_vec(&pz, i, vs) == 0 &&
                  memcmp(va, vs, sizeof va) == 0, "stream_all vec %u", i);
            int ca = omp_pack_neighbors(&pa, i, na), cz = omp_pack_neighbors(&pz, i, ns);
            CHECK(ca == cz && memcmp(na, ns, (size_t)pa.k * 4) == 0, "stream_all nbr %u", i);
        }
    }
    CHECK(omp_pack_find_id(&pz, omp_pack_id(&pa, pa.n - 1)) == pa.n - 1, "stream_all find_id");

    /* id lookup + artist interning (adjacent tracks by same artist share offset) */
    char vid[11];
    memcpy(vid, omp_pack_id(&pa, 7), 11);
    CHECK(omp_pack_find_id(&pa, vid) == 7, "find_id roundtrip");
    int interned_pair = 0;
    for (uint32_t i = 1; i < pa.n && !interned_pair; i++)
        if (pa.tracks[i].artist_off == pa.tracks[i - 1].artist_off &&
            pa.tracks[i].artist_off != 0)
            interned_pair = 1;
    CHECK(interned_pair, "no interned artist pair found");
    CHECK(omp_gain_mult(OMP_NO_GAIN) == 1.0f, "no-gain sentinel");

    omp_pack_close(&pa);
    omp_pack_close(&ps);
    omp_pack_close(&pz);
    printf(fails ? "test_pack: %d FAILURES\n" : "test_pack: OK\n", fails);
    return fails ? 1 : 0;
}
