/* Device-pack reader — the flat-file library index built by
 * scripts/export_device_pack.py (see docs/EMBEDDED_PLAN.md for the layout).
 *
 * Three modes:
 *   OMP_PACK_LOAD_ALL   — every file into RAM (host tests / boards with spare RAM)
 *   OMP_PACK_STREAM     — tracks/strings/ids in RAM, embeddings + neighbors read
 *                         per-call from disk/SD (one rerank touches ~124KB)
 *   OMP_PACK_STREAM_ALL — nothing in RAM: track records, strings and ids are read on
 *                         demand too (the HiFi Walker H2 / Rockbox plugin has 2 MiB for
 *                         everything; tracks+strings+ids alone are ~8MB). Pointers
 *                         returned by omp_pack_track/str/id then live in small rotating
 *                         buffers: valid for the next 16 / 8 / 8 calls respectively.
 */
#ifndef OMP_PACK_H
#define OMP_PACK_H

#include <stdint.h>
#include <stdio.h>

#define OMP_DIM 512
#define OMP_NO_GAIN 32767          /* gain_q78 sentinel: no loudness measurement */
#define OMP_NBR_PAD 0xFFFFFFFFu    /* neighbors.bin padding for tracks with <K rows */

#pragma pack(push, 1)
typedef struct {
    uint32_t file_off;             /* "V/basename.opus", V = video_id[0] (FAT32 shard) */
    uint32_t title_off;
    uint32_t artist_off;           /* interned: equal offsets <=> same artist string */
    uint32_t album_off;
    uint32_t genre_off;
    uint16_t duration_s;           /* 0 = unknown */
    int16_t  gain_q78;             /* R128 gain dB*256 re -23 LUFS, OMP_NO_GAIN = none */
} omp_track;
#pragma pack(pop)

typedef enum { OMP_PACK_LOAD_ALL, OMP_PACK_STREAM, OMP_PACK_STREAM_ALL } omp_pack_mode;

typedef struct {
    uint32_t n;                    /* track count */
    uint32_t k;                    /* neighbors per track */
    omp_pack_mode mode;
    omp_track *tracks;             /* n records, sorted by (artist,title) casefold;
                                      NULL in STREAM_ALL: use omp_pack_track() */
    char *strings;                 /* NUL-terminated UTF-8 pool */
    uint32_t strings_len;
    char *ids;                     /* n * 11 bytes, video_id per track */
    uint16_t *emb;                 /* LOAD_ALL: n*512 raw fp16; STREAM: NULL */
    uint32_t *nbr;                 /* LOAD_ALL: n*k u32;       STREAM: NULL */
    FILE *emb_f, *nbr_f;           /* STREAM handles */
    FILE *tracks_f, *strings_f, *ids_f;   /* STREAM_ALL handles */
    uint32_t *id_index;            /* STREAM_ALL: (hash, idx) pairs sorted, built on the
                                      first omp_pack_find_id; NULL until then */
} omp_pack;

/* Open pack at dir (expects pack.json + the 5 .bin files). Returns 0 on success. */
int omp_pack_open(omp_pack *p, const char *dir, omp_pack_mode mode);
void omp_pack_close(omp_pack *p);

const char *omp_pack_str(const omp_pack *p, uint32_t off);
const omp_track *omp_pack_track(const omp_pack *p, uint32_t i);
/* 11-byte video_id (NOT NUL-terminated) for track i. */
const char *omp_pack_id(const omp_pack *p, uint32_t i);
/* Linear scan for an 11-char video_id; returns index or UINT32_MAX. */
uint32_t omp_pack_find_id(const omp_pack *p, const char *video_id);

/* L2-normalized embedding of track i as float32. Returns 0 on success. */
int omp_pack_vec(omp_pack *p, uint32_t i, float out[OMP_DIM]);
/* Neighbor row of track i (k u32 indices, best-first, OMP_NBR_PAD padded) into out.
 * Returns count of real (non-pad) entries, or -1 on IO error. */
int omp_pack_neighbors(omp_pack *p, uint32_t i, uint32_t *out);

#endif
