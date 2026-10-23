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
/* a song's YouTube id (11 bytes, no terminator) and back: what outlives the card being
 * filled again, which numbers its songs anew. brain_find: 0xFFFFFFFF if it isn't here */
int brain_id(uint32_t idx, char out[11]);
uint32_t brain_find(const char id[11]);

/* event codes = firmware/core/omp_playlog.h (play 0, complete 1, skip 2, like 3,
 * dislike 4, peek 5) + unlike 6 and switch 7 (left by navigating, not a verdict: the
 * web player's 'switch'; the core gives both no weight) */
enum { EV_PLAY, EV_COMPLETE, EV_SKIP, EV_LIKE, EV_DISLIKE, EV_PEEK, EV_UNLIKE, EV_SWITCH };
void brain_log(uint32_t idx, int event, float seconds, double ts);

/* The Wheel, best first: what you start from and keep coming back to (wheel.bin from the PC,
 * plus what you've started here since). An item is a pack index, or BRAIN_WHEEL_LIST | i: a
 * list (an album / playlist) whose songs brain_wheel_list gives, in order. */
#define BRAIN_WHEEL_LIST 0x80000000u
int brain_wheel(uint32_t *out, int n, double now);
int brain_wheel_list(uint32_t item, uint32_t *out, int cap);
const char *brain_wheel_list_name(uint32_t item, const char **kind);   /* NULL: not a list */
uint32_t brain_wheel_song(uint32_t item);        /* a song item itself, a list's first song */
/* you started this yourself (and stayed): it climbs the Wheel; kept in picks.bin, which
 * scripts/h2_sync.py brings home */
void brain_wheel_pick(uint32_t item, double ts);
/* next pick after `cur` given the session so far (oldest first, cur excluded).
 * fence >= 0 keeps it inside one genre (a genre station): the best-ranked neighbour with
 * genre_of[idx] == fence, LIB_NONE (0xFFFFFFFF) if the neighbourhood has none. */
enum { BRAIN_OUT_NONE, BRAIN_OUT_SKIP, BRAIN_OUT_COMPLETE, BRAIN_OUT_SWITCH, BRAIN_OUT_DISLIKE };
/* outcome/secs: how `cur` ended (engine v3 steers away from an early skip and continues
 * from the last track you kept); the app asks ahead with BRAIN_OUT_COMPLETE */
uint32_t brain_next(uint32_t cur, const uint32_t *played, int n_played, int outcome, float secs,
                    double now, char *why, size_t whysz, const uint8_t *genre_of, int fence);
/* the radio's next n_out songs at once (n_out <= 64), planned after `ahead` (what's queued
 * after cur already, in order): YT Music lays a station out up front. 0 without the radio
 * engine (brain_engine() < 4) -- then brain_next one at a time */
int brain_plan(uint32_t cur, const uint32_t *played, int n_played, const uint32_t *ahead, int n_ahead,
               int outcome, float secs, double now, uint32_t *out, int n_out, char *why, size_t whysz);
int brain_engine(void);                          /* 4 = the web player's radio, 3 = its older walk */
void brain_radio_seed(uint32_t idx);            /* the song a radio started on: autoplay chooses for it */
int brain_is_liked(uint32_t idx);
int brain_liked(uint32_t *out, int cap);        /* newest like first */
int brain_history(uint32_t *out, int cap);      /* newest first, distinct */
int brain_play_count(uint32_t idx);
int brain_disliked(uint32_t idx);               /* turned down (and not liked since) */
/* engine-3 packs: a track's tempo x10 (0 unknown) and its YouTube Music plays */
int brain_bpm10(uint32_t idx);
int brain_ytm_plays(uint32_t idx);
/* a song's vibe: energy 0..254 (-1 unknown), tempo x10 (0 unknown), its sound's place from
 * calmest to most driven 0..15 (-1 unknown); 0 when the pack has none of it */
int brain_vibe(uint32_t idx, int *energy, int *bpm10, int *rank);
/* set bit idx of bits (n tracks) for every track you've heard: YouTube Music plays or
 * anything in the play log (a play, a skip, a dislike...) */
void brain_heard_bits(uint8_t *bits, uint32_t n);

#endif
