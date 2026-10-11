#include "lib.h"
#include "omp_pack.h"
#include "../plat/plat.h"
#include <stdio.h>
#include <string.h>

const int art_px[3] = { 32, 112, 168 };
static const char art_key[3] = { 's', 'm', 'l' };

#define CACHE 64
#define SHARD_BYTES 2000000000u       /* = scripts/h2_assets.py SHARD_BYTES */
#define MAX_SHARDS 4

struct lib {
    const omp_pack *pk;
    uint32_t n;
    int fd_artidx;
    int fd_art[3][MAX_SHARDS];        /* opened lazily: -2 = not yet tried */
    lib_track cache[CACHE];
    uint32_t used[CACHE], clock;
    uint32_t n_artists;
    uint32_t *artist_first;           /* [n_artists + 1], sentinel = n */
};

static uint32_t rd32(const uint8_t *b) { return b[0] | (b[1] << 8) | (b[2] << 16) | ((uint32_t)b[3] << 24); }

lib *lib_open(const void *pack)
{
    lib *L = plat_alloc(sizeof *L);
    memset(L, 0, sizeof *L);
    L->pk = (const omp_pack *)pack;
    L->n = L->pk->n;
    L->fd_artidx = plat_open("art.idx");
    for (int k = 0; k < 3; k++)
        for (int s = 0; s < MAX_SHARDS; s++) L->fd_art[k][s] = -2;
    for (int i = 0; i < CACHE; i++) L->cache[i].idx = LIB_NONE;
    size_t len = 0;
    uint8_t *runs = plat_load("artists.bin", &len);
    L->n_artists = runs ? (uint32_t)(len / 4) : 0;
    L->artist_first = plat_alloc(sizeof(uint32_t) * (L->n_artists + 1));
    for (uint32_t i = 0; i < L->n_artists; i++) L->artist_first[i] = rd32(runs + 4 * i);
    L->artist_first[L->n_artists] = L->n;
    if (!runs) plat_log("lib: artists.bin missing (Artists view empty)");
    return L;
}

uint32_t lib_n(const lib *L) { return L->n; }

static void copy_str(char *out, size_t cap, const char *s)
{
    size_t len = strlen(s);
    if (len >= cap) {
        len = cap - 1;
        while (len > 0 && ((unsigned char)s[len] & 0xC0) == 0x80) len--;
    }
    memcpy(out, s, len);
    out[len] = 0;
}

const lib_track *lib_get(lib *L, uint32_t idx)
{
    if (idx >= L->n) return NULL;
    L->clock++;
    int victim = 0;
    for (int i = 0; i < CACHE; i++) {
        if (L->cache[i].idx == idx) { L->used[i] = L->clock; return &L->cache[i]; }
        if (L->used[i] < L->used[victim]) victim = i;
    }
    lib_track *t = &L->cache[victim];
    const omp_track *r = omp_pack_track(L->pk, idx);
    uint32_t title = r->title_off, artist = r->artist_off, genre = r->genre_off;
    t->idx = idx;
    t->artist_key = artist;
    t->dur = r->duration_s;
    t->gain_q78 = r->gain_q78;
    copy_str(t->title, sizeof t->title, omp_pack_str(L->pk, title));
    copy_str(t->artist, sizeof t->artist, omp_pack_str(L->pk, artist));
    copy_str(t->genre, sizeof t->genre, omp_pack_str(L->pk, genre));
    L->used[victim] = L->clock;
    return t;
}

int lib_art(lib *L, uint32_t idx, int size, px16 *out)
{
    if (idx >= L->n || L->fd_artidx < 0) return -1;
    uint8_t b[4];
    if (plat_pread(L->fd_artidx, b, 4, idx * 4) != 4) return -1;
    uint32_t slot = rd32(b);
    if (slot == LIB_NONE) return -1;
    uint32_t bytes = (uint32_t)art_px[size] * art_px[size] * 2, cap = SHARD_BYTES / bytes;
    uint32_t shard = slot / cap;
    if (shard >= MAX_SHARDS) return -1;
    int *fd = &L->fd_art[size][shard];
    if (*fd == -2) {
        char name[24];
        snprintf(name, sizeof name, "art_%c_%u.bin", art_key[size], (unsigned)shard);
        *fd = plat_open(name);
    }
    if (*fd < 0) return -1;
    return plat_pread(*fd, out, (int)bytes, (slot % cap) * bytes) == (int)bytes ? 0 : -1;
}

uint32_t lib_n_artists(const lib *L) { return L->n_artists; }

void lib_artist(const lib *L, uint32_t a, uint32_t *first_idx, uint32_t *count)
{
    *first_idx = L->artist_first[a];
    *count = L->artist_first[a + 1] - L->artist_first[a];
}

uint32_t lib_artist_of(const lib *L, uint32_t idx)
{
    uint32_t lo = 0, hi = L->n_artists;
    while (hi - lo > 1) {
        uint32_t mid = (lo + hi) / 2;
        if (L->artist_first[mid] <= idx) lo = mid; else hi = mid;
    }
    return lo;
}
