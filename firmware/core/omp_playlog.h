/* Append-only binary play log — the device's plays table. Chronological by
 * construction (records are appended as events happen); the prefs code relies
 * on that ordering. Synced back to the PC keyed by video_id (ids.bin).
 *
 * File: 4-byte magic "OMP1", then 20-byte little-endian records:
 *   f64 ts (epoch seconds) | u32 track index | f32 seconds (<0 = unknown) |
 *   u8 event | 3 pad bytes
 */
#ifndef OMP_PLAYLOG_H
#define OMP_PLAYLOG_H

#include <stdint.h>

typedef enum {
    OMP_EV_PLAY = 0,      /* track started */
    OMP_EV_COMPLETE = 1,
    OMP_EV_SKIP = 2,
    OMP_EV_LIKE = 3,
    OMP_EV_DISLIKE = 4,
    OMP_EV_PEEK = 5,      /* wheel hook-preview; no prefs weight (parity with web) */
} omp_event;

typedef struct {
    double ts;
    uint32_t idx;
    float seconds;        /* playback position at event time; <0 = unknown */
    uint8_t event;
} omp_play;

/* Load whole log into a malloc'd array (caller frees). Returns count, or -1 on
 * missing/corrupt file. A missing file is a valid empty log: returns 0. */
int omp_playlog_load(const char *path, omp_play **out);
/* Append one record (creates file + magic if absent). Returns 0 on success. */
int omp_playlog_append(const char *path, const omp_play *ev);

#endif
