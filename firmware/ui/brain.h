/* UI-facing wrapper around the autoplay core (firmware/core): the play log, the Wheel's
 * fresh speed-dial pool, the next pick with a plain-words "why", likes and history. */
#ifndef CODA_BRAIN_H
#define CODA_BRAIN_H

#include <stddef.h>
#include <stdint.h>

int brain_open(const char *pack_dir, const char *plays_path);
uint32_t brain_n(void);
const void *brain_pack(void);                 /* the omp_pack, for lib_open */
uint16_t brain_duration(uint32_t idx);        /* seconds, 0 unknown */

/* event codes = firmware/core/omp_playlog.h (play 0, complete 1, skip 2, like 3,
 * dislike 4, peek 5, unlike 6) */
void brain_log(uint32_t idx, int event, float seconds, double ts);

int brain_wheel(uint32_t *out, int n, double now);
/* next pick after `cur` given the session so far (oldest first, cur excluded) */
uint32_t brain_next(uint32_t cur, const uint32_t *played, int n_played, double now,
                    char *why, size_t whysz);
int brain_is_liked(uint32_t idx);
int brain_liked(uint32_t *out, int cap);        /* newest like first */
int brain_history(uint32_t *out, int cap);      /* newest first, distinct */
int brain_play_count(uint32_t idx);

#endif
