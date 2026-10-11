#include "fx.h"
#include <math.h>

#define ATAN_N 256
static uint16_t atan_tab[ATAN_N + 1];   /* atan(i/256) in binary-angle units (0..8192) */
#define SIN_N 1024
static int16_t sin_tab[SIN_N + 1];      /* quarter wave, Q14 */

void fx_init(void)
{
    for (int i = 0; i <= ATAN_N; i++)
        atan_tab[i] = (uint16_t)(atan((double)i / ATAN_N) * 32768.0 / 3.14159265358979 + 0.5);
    for (int i = 0; i <= SIN_N; i++)
        sin_tab[i] = (int16_t)(sin(i * 3.14159265358979 / 2 / SIN_N) * 16384.0 + 0.5);
}

/* atan(t) for t = num/den in [0, 1], binary angle units, linear interpolation */
static uint32_t atan_unit(uint32_t num, uint32_t den)
{
    if (den == 0) return 0;
    uint32_t t = (uint32_t)(((uint64_t)num << 16) / den);      /* Q16, <= 65536 */
    uint32_t i = t >> 8, f = t & 255;
    if (i >= ATAN_N) return atan_tab[ATAN_N];
    return atan_tab[i] + (((atan_tab[i + 1] - atan_tab[i]) * f + 128) >> 8);
}

uint16_t fx_atan2(int32_t y, int32_t x)
{
    uint32_t ax = x < 0 ? (uint32_t)-x : (uint32_t)x;
    uint32_t ay = y < 0 ? (uint32_t)-y : (uint32_t)y;
    uint32_t a = ay <= ax ? atan_unit(ay, ax) : 16384 - atan_unit(ax, ay);  /* 0..90deg */
    if (x < 0) a = 32768 - a;
    if (y < 0) a = 65536 - a;
    return (uint16_t)a;
}

uint32_t fx_isqrt(uint32_t v)
{
    uint32_t r = 0, bit = 1u << 30;
    while (bit > v) bit >>= 2;
    while (bit) {
        if (v >= r + bit) { v -= r + bit; r = (r >> 1) + bit; }
        else r >>= 1;
        bit >>= 2;
    }
    return r;
}

int32_t fx_sin_q14(uint16_t a)
{
    uint32_t q = a >> 14, i = (a & 16383) >> 4, f = a & 15;  /* 1024 steps per quadrant */
    int32_t v0, v1;
    switch (q) {
    case 0: v0 = sin_tab[i];          v1 = sin_tab[i + 1];          break;
    case 1: v0 = sin_tab[SIN_N - i];  v1 = sin_tab[SIN_N - i - 1];  break;
    case 2: v0 = -sin_tab[i];         v1 = -sin_tab[i + 1];         break;
    default: v0 = -sin_tab[SIN_N - i]; v1 = -sin_tab[SIN_N - i - 1]; break;
    }
    return v0 + (((v1 - v0) * (int32_t)f) >> 4);
}

int32_t fx_cos_q14(uint16_t a) { return fx_sin_q14((uint16_t)(a + 16384)); }
