#include "omp_map.h"

#include <stdlib.h>
#include <string.h>

static uint32_t hash_u32(uint32_t x)
{
    x ^= x >> 16;
    x *= 0x7FEB352Du;
    x ^= x >> 15;
    x *= 0x846CA68Bu;
    x ^= x >> 16;
    return x;
}

int omp_map_init(omp_map *m, uint32_t initial_cap)
{
    uint32_t cap = 16;
    while (cap < initial_cap) cap <<= 1;
    m->keys = malloc((size_t)cap * 4);
    m->vals = calloc(cap, 4);
    m->cap = cap;
    m->used = 0;
    if (!m->keys || !m->vals) return -1;
    memset(m->keys, 0xFF, (size_t)cap * 4);   /* all OMP_MAP_EMPTY */
    return 0;
}

void omp_map_free(omp_map *m)
{
    free(m->keys);
    free(m->vals);
    memset(m, 0, sizeof *m);
}

static int grow(omp_map *m)
{
    omp_map big;
    if (omp_map_init(&big, m->cap * 2) != 0) return -1;
    for (uint32_t i = 0; i < m->cap; i++)
        if (m->keys[i] != OMP_MAP_EMPTY) {
            float *v = omp_map_slot(&big, m->keys[i]);
            if (!v) { omp_map_free(&big); return -1; }
            *v = m->vals[i];
        }
    omp_map_free(m);
    *m = big;
    return 0;
}

float *omp_map_slot(omp_map *m, uint32_t key)
{
    if (m->used * 10 >= m->cap * 7 && grow(m) != 0) return NULL;
    uint32_t i = hash_u32(key) & (m->cap - 1);
    while (m->keys[i] != OMP_MAP_EMPTY) {
        if (m->keys[i] == key) return &m->vals[i];
        i = (i + 1) & (m->cap - 1);
    }
    m->keys[i] = key;
    m->vals[i] = 0.0f;
    m->used++;
    return &m->vals[i];
}

float omp_map_get(const omp_map *m, uint32_t key, float dflt)
{
    if (!m->cap) return dflt;
    uint32_t i = hash_u32(key) & (m->cap - 1);
    while (m->keys[i] != OMP_MAP_EMPTY) {
        if (m->keys[i] == key) return m->vals[i];
        i = (i + 1) & (m->cap - 1);
    }
    return dflt;
}
