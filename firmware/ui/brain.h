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
 * dislike 4, peek 5) + unlike 6 and switch 7 (left by navigating, not a verdict: the
 * web player's 'switch'; the core gives both no weight) */
enum { EV_PLAY, EV_COMPLETE, EV_SKIP, EV_LIKE, EV_DISLIKE, EV_PEEK, EV_UNLIKE, EV_SWITCH };
void brain_log(uint32_t idx, int event, float seconds, double ts);

int brain_wheel(uint32_t *out, int n, double now);
/* next pick after `cur` given the session so far (oldest first, cur excluded).
 * fence >= 0 keeps it inside one genre (a genre station): the best-ranked neighbour with
 * genre_of[idx] == fence, LIB_NONE (0xFFFFFFFF) if the neighbourhood has none. */
uint32_t brain_next(uint32_t cur, const uint32_t *played, int n_played, double now,
                    char *why, size_t whysz, const uint8_t *genre_of, int fence);
int brain_is_liked(uint32_t idx);
int brain_liked(uint32_t *out, int cap);        /* newest like first */
int brain_history(uint32_t *out, int cap);      /* newest first, distinct */
int brain_play_count(uint32_t idx);

#endif
