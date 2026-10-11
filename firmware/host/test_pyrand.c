/* omp_pyrand == CPython's random module (expected values: tools/gen_pyrand_golden.py). */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "omp_pyrand.h"
#include "pyrand_golden.h"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL: " __VA_ARGS__); printf("\n"); } } while (0)
#define N(a) ((int)(sizeof a / sizeof a[0]))

int main(void)
{
    uint8_t d[64];
    char hex[129];
    omp_sha512((const uint8_t *)SHA_MSG, strlen(SHA_MSG), d);
    for (int i = 0; i < 64; i++) sprintf(hex + 2 * i, "%02x", d[i]);
    CHECK(!strcmp(hex, SHA_HEX), "sha512 %s", hex);

    omp_pyrand r;
    pyr_seed_str(&r, "dQw4w9WgXcQ", 11);
    for (int i = 0; i < N(STR_RANDOM); i++) {
        double x = pyr_random(&r);
        CHECK(x == STR_RANDOM[i], "str random[%d] %.17g != %.17g", i, x, STR_RANDOM[i]);
    }
    for (int i = 0; i < N(GETBITS7); i++) {
        unsigned x = pyr_getrandbits(&r, 7);
        CHECK(x == GETBITS7[i], "getrandbits[%d] %u != %u", i, x, GETBITS7[i]);
    }
    pyr_seed_u64(&r, 12345);
    for (int i = 0; i < N(INT_RANDOM); i++) {
        double x = pyr_random(&r);
        CHECK(x == INT_RANDOM[i], "int random[%d] %.17g != %.17g", i, x, INT_RANDOM[i]);
    }
    pyr_seed_str(&r, "~AbCdEfGhI", 10);
    uint32_t pop[1000], out[16];
    for (int i = 0; i < 1000; i++) pop[i] = (uint32_t)i;
    pyr_sample(&r, pop, 60, 10, out);
    for (int i = 0; i < 10; i++) CHECK(out[i] == SAMPLE_POOL[i], "sample pool[%d] %u != %u", i, out[i], SAMPLE_POOL[i]);
    pyr_sample(&r, pop, 1000, 10, out);
    for (int i = 0; i < 10; i++) CHECK(out[i] == SAMPLE_SET[i], "sample set[%d] %u != %u", i, out[i], SAMPLE_SET[i]);
    static const uint32_t ns[] = { 1, 2, 3, 100, 1000, 65537 };
    for (int i = 0; i < N(BELOW); i++) {
        uint32_t x = pyr_randbelow(&r, ns[i]);
        CHECK(x == BELOW[i], "randbelow(%u) %u != %u", ns[i], x, BELOW[i]);
    }
    pyr_seed_u64(&r, 7);
    static const double ab[][2] = { { 3.5, 7.2 }, { 1.0, 1.0 }, { 0.4, 2.0 }, { 12.0, 3.0 }, { 2.0, 0.6 } };
    for (int i = 0; i < N(BETA); i++) {
        double x = pyr_betavariate(&r, ab[i][0], ab[i][1]);
        CHECK(fabs(x - BETA[i]) < 1e-12, "beta[%d] %.17g != %.17g", i, x, BETA[i]);
    }
    static const double ga[] = { 0.3, 1.0, 5.5 };
    for (int i = 0; i < N(GAMMA); i++) {
        double x = pyr_gammavariate(&r, ga[i], 1.0);
        CHECK(fabs(x - GAMMA[i]) < 1e-12, "gamma[%d] %.17g != %.17g", i, x, GAMMA[i]);
    }
    if (fails) { printf("test_pyrand: %d FAILURES\n", fails); return 1; }
    printf("test_pyrand: OK - C random == CPython random\n");
    return 0;
}
