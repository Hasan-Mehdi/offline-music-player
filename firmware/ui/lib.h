/* Library access for the UI, streamed from the card: track records/strings through the
 * brain's pack (OMP_PACK_STREAM_ALL, so one set of open files), covers from the sharded
 * art store, artist runs from artists.bin (scripts/h2_assets.py). The H2 plugin has
 * 2 MiB for everything, so decoded records sit in a small LRU cache. */
#ifndef CODA_LIB_H
#define CODA_LIB_H

#include <stdint.h>
#include "gfx.h"

#define LIB_NONE 0xFFFFFFFFu

typedef struct {
    uint32_t idx;
    uint32_t artist_key;          /* interned artist offset: equal <=> same artist */
    uint16_t dur;                 /* seconds, 0 unknown */
    int16_t gain_q78;
    char title[176];
    char artist[112];
    char genre[48];
} lib_track;

enum { ART_S, ART_M, ART_L };     /* 32 / 112 / 168 px */
extern const int art_px[3];

typedef struct lib lib;

lib *lib_open(const void *pack); /* shares the brain's omp_pack (brain_pack()) */
uint32_t lib_n(const lib *L);
const lib_track *lib_get(lib *L, uint32_t idx);   /* valid until ~32 more lib_get calls */
int lib_art(lib *L, uint32_t idx, int size, px16 *out);   /* 0 ok, -1 no cover */

/* artists = runs of equal artist in the pack's (artist, title) order */
uint32_t lib_n_artists(const lib *L);
void lib_artist(const lib *L, uint32_t a, uint32_t *first_idx, uint32_t *count);
uint32_t lib_artist_of(const lib *L, uint32_t idx);      /* artist number of a track */

#endif
