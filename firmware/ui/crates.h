/* CRT1 crate files from scripts/h2_crates.py: Explore shelves, soundtracks, genres.
 * The table and strings stay in RAM (small); a crate's members are read from the card
 * when it opens. */
#ifndef CODA_CRATES_H
#define CODA_CRATES_H

#include <stdint.h>

typedef struct {
    uint32_t name, sub, section;      /* string offsets */
    uint32_t first, count, seconds;
} crate;

typedef struct {
    char file[24];
    uint32_t n, n_members, members_off;
    crate *tab;
    char *str;
} crates;

int crates_open(crates *c, const char *rel);     /* 0 ok; a missing file = 0 crates */
static inline const char *crate_str(const crates *c, uint32_t off) { return c->str ? c->str + off : ""; }
/* members [from, from + n) of crate i into out; returns how many were read */
int crate_members(const crates *c, uint32_t i, uint32_t from, uint32_t *out, int n);

#endif
