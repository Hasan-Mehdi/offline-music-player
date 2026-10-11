/* IEEE 754 half -> float conversion, bit-exact with numpy's astype(float32).
 * ESP32-S3 has no half-float FPU; this is ~4 ops on the hot path (normals). */
#ifndef OMP_FP16_H
#define OMP_FP16_H

#include <stdint.h>
#include <string.h>

static inline float omp_half_to_float(uint16_t h)
{
    uint32_t sign = (uint32_t)(h & 0x8000u) << 16;
    uint32_t exp = (h >> 10) & 0x1Fu;
    uint32_t man = h & 0x3FFu;
    uint32_t bits;
    float f;
    if (exp == 0) {
        /* zero / subnormal: man * 2^-24 is exact in float32 */
        f = (float)man * 5.9604644775390625e-8f;
        return (h & 0x8000u) ? -f : f;
    }
    if (exp == 31)
        bits = sign | 0x7F800000u | (man << 13);           /* inf / nan */
    else
        bits = sign | ((exp + 112u) << 23) | (man << 13);  /* normal */
    memcpy(&f, &bits, 4);
    return f;
}

#endif
