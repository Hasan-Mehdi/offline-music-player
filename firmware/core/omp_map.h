/* Tiny open-addressing hash map, uint32 key -> float value. Used for artist
 * preference scores (keyed by the artist's interned strings.bin offset — string
 * interning makes offset equality identical to string equality) and the
 * speed-dial per-artist caps, and (sparse) per-track prefs/play counts keyed by pack
 * index -- 0xFFFFFFFF is never a valid index either. */
#ifndef OMP_MAP_H
#define OMP_MAP_H

#include <stdint.h>

#define OMP_MAP_EMPTY 0xFFFFFFFFu   /* never a valid strings.bin offset (pool < 4GB) */

typedef struct {
    uint32_t *keys;
    float *vals;
    uint32_t cap;                   /* power of two */
    uint32_t used;
} omp_map;

int omp_map_init(omp_map *m, uint32_t initial_cap);
void omp_map_free(omp_map *m);
/* *omp_map_slot(m,key) is the value; creates (0.0) if absent. NULL on OOM. */
float *omp_map_slot(omp_map *m, uint32_t key);
/* Value or dflt if absent (does not insert). */
float omp_map_get(const omp_map *m, uint32_t key, float dflt);

#endif
