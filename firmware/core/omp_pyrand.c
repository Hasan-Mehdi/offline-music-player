#include "omp_pyrand.h"

#include <math.h>
#include <string.h>

/* ------------------------------------------------------------------ SHA-512 (FIPS 180-4) */
static const uint64_t K512[80] = {
    0x428a2f98d728ae22ULL, 0x7137449123ef65cdULL,
    0xb5c0fbcfec4d3b2fULL, 0xe9b5dba58189dbbcULL,
    0x3956c25bf348b538ULL, 0x59f111f1b605d019ULL,
    0x923f82a4af194f9bULL, 0xab1c5ed5da6d8118ULL,
    0xd807aa98a3030242ULL, 0x12835b0145706fbeULL,
    0x243185be4ee4b28cULL, 0x550c7dc3d5ffb4e2ULL,
    0x72be5d74f27b896fULL, 0x80deb1fe3b1696b1ULL,
    0x9bdc06a725c71235ULL, 0xc19bf174cf692694ULL,
    0xe49b69c19ef14ad2ULL, 0xefbe4786384f25e3ULL,
    0x0fc19dc68b8cd5b5ULL, 0x240ca1cc77ac9c65ULL,
    0x2de92c6f592b0275ULL, 0x4a7484aa6ea6e483ULL,
    0x5cb0a9dcbd41fbd4ULL, 0x76f988da831153b5ULL,
    0x983e5152ee66dfabULL, 0xa831c66d2db43210ULL,
    0xb00327c898fb213fULL, 0xbf597fc7beef0ee4ULL,
    0xc6e00bf33da88fc2ULL, 0xd5a79147930aa725ULL,
    0x06ca6351e003826fULL, 0x142929670a0e6e70ULL,
    0x27b70a8546d22ffcULL, 0x2e1b21385c26c926ULL,
    0x4d2c6dfc5ac42aedULL, 0x53380d139d95b3dfULL,
    0x650a73548baf63deULL, 0x766a0abb3c77b2a8ULL,
    0x81c2c92e47edaee6ULL, 0x92722c851482353bULL,
    0xa2bfe8a14cf10364ULL, 0xa81a664bbc423001ULL,
    0xc24b8b70d0f89791ULL, 0xc76c51a30654be30ULL,
    0xd192e819d6ef5218ULL, 0xd69906245565a910ULL,
    0xf40e35855771202aULL, 0x106aa07032bbd1b8ULL,
    0x19a4c116b8d2d0c8ULL, 0x1e376c085141ab53ULL,
    0x2748774cdf8eeb99ULL, 0x34b0bcb5e19b48a8ULL,
    0x391c0cb3c5c95a63ULL, 0x4ed8aa4ae3418acbULL,
    0x5b9cca4f7763e373ULL, 0x682e6ff3d6b2b8a3ULL,
    0x748f82ee5defb2fcULL, 0x78a5636f43172f60ULL,
    0x84c87814a1f0ab72ULL, 0x8cc702081a6439ecULL,
    0x90befffa23631e28ULL, 0xa4506cebde82bde9ULL,
    0xbef9a3f7b2c67915ULL, 0xc67178f2e372532bULL,
    0xca273eceea26619cULL, 0xd186b8c721c0c207ULL,
    0xeada7dd6cde0eb1eULL, 0xf57d4f7fee6ed178ULL,
    0x06f067aa72176fbaULL, 0x0a637dc5a2c898a6ULL,
    0x113f9804bef90daeULL, 0x1b710b35131c471bULL,
    0x28db77f523047d84ULL, 0x32caab7b40c72493ULL,
    0x3c9ebe0a15c9bebcULL, 0x431d67c49c100d4cULL,
    0x4cc5d4becb3e42b6ULL, 0x597f299cfc657e2aULL,
    0x5fcb6fab3ad6faecULL, 0x6c44198c4a475817ULL,
};
static const uint64_t H512[8] = {
    0x6a09e667f3bcc908ULL, 0xbb67ae8584caa73bULL,
    0x3c6ef372fe94f82bULL, 0xa54ff53a5f1d36f1ULL,
    0x510e527fade682d1ULL, 0x9b05688c2b3e6c1fULL,
    0x1f83d9abfb41bd6bULL, 0x5be0cd19137e2179ULL,
};

static uint64_t ror64(uint64_t x, int n) { return (x >> n) | (x << (64 - n)); }

/* buffers are static: the H2 plugin's stack is 7.5 KB (single-threaded use) */
static void sha512_block(uint64_t h[8], const uint8_t *p)
{
    static uint64_t w[80];
    for (int i = 0; i < 16; i++) {
        w[i] = 0;
        for (int b = 0; b < 8; b++) w[i] = (w[i] << 8) | p[8 * i + b];
    }
    for (int i = 16; i < 80; i++) {
        uint64_t s0 = ror64(w[i - 15], 1) ^ ror64(w[i - 15], 8) ^ (w[i - 15] >> 7);
        uint64_t s1 = ror64(w[i - 2], 19) ^ ror64(w[i - 2], 61) ^ (w[i - 2] >> 6);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint64_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 80; i++) {
        uint64_t S1 = ror64(e, 14) ^ ror64(e, 18) ^ ror64(e, 41);
        uint64_t ch = (e & f) ^ (~e & g);
        uint64_t t1 = hh + S1 + ch + K512[i] + w[i];
        uint64_t S0 = ror64(a, 28) ^ ror64(a, 34) ^ ror64(a, 39);
        uint64_t mj = (a & b) ^ (a & c) ^ (b & c);
        uint64_t t2 = S0 + mj;
        hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}

void omp_sha512(const uint8_t *msg, size_t len, uint8_t out[64])
{
    uint64_t h[8];
    memcpy(h, H512, sizeof h);
    size_t off = 0;
    for (; off + 128 <= len; off += 128) sha512_block(h, msg + off);
    static uint8_t tail[256];
    size_t rem = len - off;
    memset(tail, 0, sizeof tail);
    memcpy(tail, msg + off, rem);
    tail[rem] = 0x80;
    size_t tl = rem + 1 + 16 <= 128 ? 128 : 256;
    uint64_t bits = (uint64_t)len * 8;
    for (int b = 0; b < 8; b++) tail[tl - 1 - b] = (uint8_t)(bits >> (8 * b));
    sha512_block(h, tail);
    if (tl == 256) sha512_block(h, tail + 128);
    for (int i = 0; i < 8; i++)
        for (int b = 0; b < 8; b++) out[8 * i + b] = (uint8_t)(h[i] >> (56 - 8 * b));
}

/* ------------------------------------------------------------------ MT19937 (_randommodule.c) */
static void init_genrand(omp_pyrand *r, uint32_t s)
{
    r->mt[0] = s;
    for (int i = 1; i < 624; i++)
        r->mt[i] = 1812433253u * (r->mt[i - 1] ^ (r->mt[i - 1] >> 30)) + (uint32_t)i;
    r->mti = 624;
}

void pyr_seed_key(omp_pyrand *r, const uint32_t *key, int n)
{
    init_genrand(r, 19650218u);
    int i = 1, j = 0;
    for (int k = 624 > n ? 624 : n; k; k--) {
        r->mt[i] = (r->mt[i] ^ ((r->mt[i - 1] ^ (r->mt[i - 1] >> 30)) * 1664525u)) + key[j] + (uint32_t)j;
        i++; j++;
        if (i >= 624) { r->mt[0] = r->mt[623]; i = 1; }
        if (j >= n) j = 0;
    }
    for (int k = 623; k; k--) {
        r->mt[i] = (r->mt[i] ^ ((r->mt[i - 1] ^ (r->mt[i - 1] >> 30)) * 1566083941u)) - (uint32_t)i;
        i++;
        if (i >= 624) { r->mt[0] = r->mt[623]; i = 1; }
    }
    r->mt[0] = 0x80000000u;
    r->mti = 624;
}

void pyr_seed_u64(omp_pyrand *r, uint64_t x)
{
    uint32_t key[2] = { (uint32_t)x, (uint32_t)(x >> 32) };
    pyr_seed_key(r, key, key[1] ? 2 : 1);
}

void pyr_seed_str(omp_pyrand *r, const char *s, size_t len)
{
    /* int.from_bytes(s + sha512(s), 'big') -> 32-bit words, least significant first */
    static uint8_t buf[256 + 64];
    if (len > 256) len = 256;
    memcpy(buf, s, len);
    omp_sha512((const uint8_t *)s, len, buf + len);
    size_t nb = len + 64, lead = 0;
    while (lead < nb && buf[lead] == 0) lead++;                   /* leading zero bytes */
    size_t sig = nb - lead;
    static uint32_t key[80];
    int n = sig ? (int)((sig + 3) / 4) : 1;
    memset(key, 0, sizeof key);
    for (size_t b = 0; b < sig; b++) {                            /* byte b from the LSB end */
        uint8_t v = buf[nb - 1 - b];
        key[b / 4] |= (uint32_t)v << (8 * (b % 4));
    }
    /* _PyLong_NumBits-based key length: drop a top word that is entirely zero */
    while (n > 1 && key[n - 1] == 0) n--;
    pyr_seed_key(r, key, n);
}

uint32_t pyr_u32(omp_pyrand *r)
{
    static const uint32_t mag01[2] = { 0u, 0x9908b0dfu };
    uint32_t y;
    if (r->mti >= 624) {
        int kk;
        for (kk = 0; kk < 624 - 397; kk++) {
            y = (r->mt[kk] & 0x80000000u) | (r->mt[kk + 1] & 0x7fffffffu);
            r->mt[kk] = r->mt[kk + 397] ^ (y >> 1) ^ mag01[y & 1u];
        }
        for (; kk < 623; kk++) {
            y = (r->mt[kk] & 0x80000000u) | (r->mt[kk + 1] & 0x7fffffffu);
            r->mt[kk] = r->mt[kk + (397 - 624)] ^ (y >> 1) ^ mag01[y & 1u];
        }
        y = (r->mt[623] & 0x80000000u) | (r->mt[0] & 0x7fffffffu);
        r->mt[623] = r->mt[396] ^ (y >> 1) ^ mag01[y & 1u];
        r->mti = 0;
    }
    y = r->mt[r->mti++];
    y ^= (y >> 11);
    y ^= (y << 7) & 0x9d2c5680u;
    y ^= (y << 15) & 0xefc60000u;
    y ^= (y >> 18);
    return y;
}

double pyr_random(omp_pyrand *r)
{
    uint32_t a = pyr_u32(r) >> 5, b = pyr_u32(r) >> 6;
    return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0);
}

uint32_t pyr_getrandbits(omp_pyrand *r, int k)
{
    if (k <= 0) return 0;
    return pyr_u32(r) >> (32 - k);
}

uint32_t pyr_randbelow(omp_pyrand *r, uint32_t n)
{
    int k = 0;
    for (uint32_t v = n; v; v >>= 1) k++;                          /* n.bit_length() */
    uint32_t x = pyr_getrandbits(r, k);
    while (x >= n) x = pyr_getrandbits(r, k);
    return x;
}

int pyr_sample(omp_pyrand *r, const uint32_t *pop, int n, int k, uint32_t *out)
{
    if (k < 0 || k > n) return -1;
    int setsize = 21;
    if (k > 5) setsize += (int)pow(4.0, ceil(log((double)(k * 3)) / log(4.0)));
    if (n <= setsize) {
        static uint32_t pool[512];
        if (n > 512) return -1;
        memcpy(pool, pop, (size_t)n * sizeof *pool);
        for (int i = 0; i < k; i++) {
            uint32_t j = pyr_randbelow(r, (uint32_t)(n - i));
            out[i] = pool[j];
            pool[j] = pool[n - i - 1];
        }
    } else {
        static uint32_t sel[512];
        if (k > 512) return -1;
        for (int i = 0; i < k; i++) {
            uint32_t j;
            int dup;
            do {
                j = pyr_randbelow(r, (uint32_t)n);
                dup = 0;
                for (int s = 0; s < i && !dup; s++) dup = sel[s] == j;
            } while (dup);
            sel[i] = j;
            out[i] = pop[j];
        }
    }
    return 0;
}

#define PY_LOG4 1.3862943611198906
#define PY_SG_MAGICCONST 2.504077396776274
#define PY_E 2.718281828459045

double pyr_gammavariate(omp_pyrand *r, double alpha, double beta)
{
    if (alpha <= 0.0 || beta <= 0.0) return 0.0;
    if (alpha > 1.0) {
        double ainv = sqrt(2.0 * alpha - 1.0), bbb = alpha - PY_LOG4, ccc = alpha + ainv;
        for (;;) {
            double u1 = pyr_random(r);
            if (!(1e-7 < u1 && u1 < 0.9999999)) continue;
            double u2 = 1.0 - pyr_random(r);
            double v = log(u1 / (1.0 - u1)) / ainv;
            double x = alpha * exp(v);
            double z = u1 * u1 * u2;
            double rr = bbb + ccc * v - x;
            if (rr + PY_SG_MAGICCONST - 4.5 * z >= 0.0 || rr >= log(z)) return x * beta;
        }
    } else if (alpha == 1.0) {
        return -log(1.0 - pyr_random(r)) * beta;
    }
    double x;
    for (;;) {
        double u = pyr_random(r);
        double b = (PY_E + alpha) / PY_E;
        double p = b * u;
        if (p <= 1.0) x = pow(p, 1.0 / alpha);
        else x = -log((b - p) / alpha);
        double u1 = pyr_random(r);
        if (p > 1.0) {
            if (u1 <= pow(x, alpha - 1.0)) break;
        } else if (u1 <= exp(-x)) break;
    }
    return x * beta;
}

double pyr_betavariate(omp_pyrand *r, double alpha, double beta)
{
    double y = pyr_gammavariate(r, alpha, 1.0);
    if (y != 0.0) return y / (y + pyr_gammavariate(r, beta, 1.0));
    return 0.0;
}
