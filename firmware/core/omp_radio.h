/* The radio engine (the web player's autoplay since 2026-10-11, player_server/radio.py) on
 * the device. Every song's radio is ranked on the PC (scripts/radio_pack.py -> radio.bin):
 * what goes with it, best first. Per pick this drops what the sitting played, steers off
 * songs you turned down (their sound and song2vec neighbourhood cost more), and runs
 * radio.sequence() for one slot: the familiar mix, the seed's game and channel shares
 * (each seed's own, from radio.shares on the PC),
 * no more than two in a row from one channel (a collaboration counts for both credited
 * artists), never another version of a song the sitting has heard. */
#ifndef OMP_RADIO_H
#define OMP_RADIO_H

#include <stdint.h>

#include "omp_pack.h"

/* player_server/radio.py: how a sitting's skips steer the radio (the caller, brain.c) */
#define OMP_RADIO_KEEP_FRAC 0.8f   /* a skip before this share of the song turns it down */
#define OMP_RADIO_RESEED 0         /* radio.RESEED: off since 2026-10-22, the station is the song
                                      you started until you pick another */
#define OMP_RADIO_STREAK 3         /* this many turned down in a row: a fresh seed (each full run) */
#define OMP_RADIO_RESEED_POOL 200  /* ... from this many of your most played lately */
#define OMP_RADIO_AWAY_SIM 0.25f   /* ... sounding no closer than this to them, the most like
                                      what you kept (radio.py fresh_seed) */

typedef struct {
    int ok;
    uint32_t n, k, dim;
    uint16_t *count;          /* filled slots of each seed's radio */
    uint8_t *known;           /* you already play it */
    uint8_t *game;            /* game series id, 0 none */
    uint32_t *chan, *chan2;   /* first and second credited artist, 0 none */
    uint32_t *work;           /* the song under the version, 0 unknown */
    uint8_t *ashare, *gshare; /* its radio's channel / game-series share x 250 (the "SHR1"
                                 trailer; without it radio.py's fixed shares) */
    uint8_t *fshare;          /* its radio's share of songs you know x 250 ("FAM1", after
                                 SHR1: radio.seed_familiar_share; without it FAMILIAR_SHARE) */
    long rows_off, s2v_off;   /* in radio.bin */
    char path[200];
} omp_radio;

int omp_radio_load(omp_radio *r, const char *pack_dir, uint32_t n);   /* 0 ok */
void omp_radio_free(omp_radio *r);

/* The next song of `seed`'s radio. tail: the songs as heard, oldest -> newest (<= 12 count);
 * ex: never these (the sitting so far, recent plays); rej: turned down this sitting;
 * known_extra: songs this player's own log says you finished or liked. UINT32_MAX when
 * the seed has no radio or every slot is excluded. */
uint32_t omp_radio_next(const omp_radio *r, omp_pack *pack, uint32_t seed,
                        const uint32_t *tail, int nt, const uint32_t *ex, int n_ex,
                        const uint32_t *rej, int nr, const uint32_t *known_extra, int n_known);

#endif
