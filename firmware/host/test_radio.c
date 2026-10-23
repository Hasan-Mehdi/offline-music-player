/* The device radio engine (core/omp_radio.c) against player_server/radio.py: cases from
 * firmware/tools/test_radio_parity.py on stdin, one pick per line on stdout.
 *
 *   test_radio.exe <pack_dir> < cases.txt
 * case: seed nt tail.. n_ex ex.. nr rej.. nk known.. */
#include <stdio.h>
#include <stdlib.h>

#include "omp_pack.h"
#include "omp_radio.h"

static int read_list(uint32_t *out, int cap)
{
    int n;
    if (scanf("%d", &n) != 1 || n < 0 || n > cap) return -1;
    for (int i = 0; i < n; i++) if (scanf("%u", &out[i]) != 1) return -1;
    return n;
}

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "usage: test_radio <pack_dir> < cases\n"); return 2; }
    static omp_pack pack;
    static omp_radio r;
    if (omp_pack_open(&pack, argv[1], OMP_PACK_STREAM) != 0) { fprintf(stderr, "no pack\n"); return 1; }
    if (omp_radio_load(&r, argv[1], pack.n) != 0) { fprintf(stderr, "no radio.bin\n"); return 1; }
    static uint32_t tail[64], ex[512], rej[16], known[512];
    uint32_t seed;
    while (scanf("%u", &seed) == 1) {
        int nt = read_list(tail, 64), ne = read_list(ex, 512), nr = read_list(rej, 16),
            nk = read_list(known, 512);
        if (nt < 0 || ne < 0 || nr < 0 || nk < 0) { fprintf(stderr, "bad case\n"); return 1; }
        uint32_t pick = omp_radio_next(&r, &pack, seed, tail, nt, ex, ne, rej, nr, known, nk);
        printf("%d\n", pick == UINT32_MAX ? -1 : (int)pick);
    }
    return 0;
}
