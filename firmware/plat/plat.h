/* What the Coda UI needs from the platform. Two implementations:
 *   firmware/plat/host/plat_host.c       PC: stdio files, fake player clock, PNG frames
 *   firmware/rockbox/coda/plat_rockbox.c  H2: rb-> API (lcd, buttons, playlist, beep, pcm)
 */
#ifndef CODA_PLAT_H
#define CODA_PLAT_H

#include <stddef.h>
#include <stdint.h>

uint32_t plat_ms(void);                       /* monotonic milliseconds */
int64_t plat_now(void);                       /* wall clock, epoch seconds */
int plat_battery(void);                       /* percent, -1 unknown */
void plat_clock(int *hour, int *minute);      /* local wall clock */
void plat_log(const char *fmt, ...);

void *plat_alloc(size_t n);                   /* arena: never freed */
/* path relative to the app data dir (/.coda on the card) */
void *plat_load(const char *rel, size_t *len);           /* whole file, NULL if missing */
int plat_save(const char *rel, const void *data, size_t len);  /* replace; 0 on success */
int plat_open(const char *rel);                           /* -1 if missing */
int plat_pread(int fd, void *buf, int n, uint32_t off);   /* bytes read */
void plat_close(int fd);

typedef struct {
    int playing;                              /* 1 playing, 0 paused/stopped */
    int active;                               /* something loaded */
    uint32_t idx;                             /* pack index of the current track */
    uint32_t elapsed_ms, length_ms;
} plat_play;

void plat_player(plat_play *st);
void plat_play_tracks(const uint32_t *idx, int n, int start);   /* replace queue + play */
void plat_queue_next(uint32_t idx);           /* insert right after the current track */
void plat_toggle(void);
void plat_skip(int dir);                      /* +1 next, -1 previous */
void plat_seek(int32_t delta_ms);
void plat_beep(int hz, int ms, int amp);      /* wheel detent tick */
int plat_spectrum(uint8_t bands[12]);         /* 0 if unavailable */

#endif
