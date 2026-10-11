/* R128 loudness gain -> linear multiplier, identical to the web player:
 * pack gain is dB*256 relative to -23 LUFS; retarget to -14 LUFS (+9 dB) and
 * attenuate only (never boost -> no clipping, quiet tracks stay quiet). */
#ifndef OMP_GAIN_H
#define OMP_GAIN_H

#include <math.h>
#include <stdint.h>

#include "omp_pack.h"

#define OMP_LOUDNESS_OFFSET_DB 9.0   /* -23 LUFS tags retargeted to -14 LUFS */

static inline float omp_gain_mult(int16_t gain_q78)
{
    if (gain_q78 == OMP_NO_GAIN) return 1.0f;
    double db = (double)gain_q78 / 256.0 + OMP_LOUDNESS_OFFSET_DB;
    double m = pow(10.0, db / 20.0);
    return m < 1.0 ? (float)m : 1.0f;
}

#endif
