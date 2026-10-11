/* CPython's random.Random, bit for bit (3.13: Lib/random.py + Modules/_randommodule.c):
 * MT19937 seeded like Random(int) / Random(str) (version 2: int(s + sha512(s)), big-
 * endian), random() = genrand_res53, getrandbits, _randbelow, sample, choice,
 * gammavariate, betavariate. The engine v3 port draws exactly what the web player draws
 * (the never-played slice of retrieval is Random(anchor video id); the explore slot is
 * a Thompson draw), so a golden trace replays identically in C. */
#ifndef OMP_PYRAND_H
#define OMP_PYRAND_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint32_t mt[624];
    int mti;
} omp_pyrand;

void pyr_seed_key(omp_pyrand *r, const uint32_t *key, int n);   /* init_by_array */
void pyr_seed_u64(omp_pyrand *r, uint64_t x);                     /* Random(x), x >= 0 */
void pyr_seed_str(omp_pyrand *r, const char *s, size_t len);      /* Random("...") */
uint32_t pyr_u32(omp_pyrand *r);
double pyr_random(omp_pyrand *r);
uint32_t pyr_getrandbits(omp_pyrand *r, int k);                   /* 0 < k <= 32 */
uint32_t pyr_randbelow(omp_pyrand *r, uint32_t n);                /* n > 0 */
/* sample(population, k) for k <= n; out gets k picks in selection order. 0 ok, -1 err */
int pyr_sample(omp_pyrand *r, const uint32_t *pop, int n, int k, uint32_t *out);
double pyr_gammavariate(omp_pyrand *r, double alpha, double beta);
double pyr_betavariate(omp_pyrand *r, double alpha, double beta);

/* SHA-512 (for the str seed); exposed for the tests */
void omp_sha512(const uint8_t *msg, size_t len, uint8_t out[64]);

#endif
