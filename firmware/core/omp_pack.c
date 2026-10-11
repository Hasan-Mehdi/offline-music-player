#include "omp_pack.h"
#include "omp_fp16.h"

#include <stdlib.h>
#include <string.h>

static char *read_all(const char *path, uint32_t *len_out)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(len > 0 ? (size_t)len : 1);
    if (!buf || (len > 0 && fread(buf, 1, (size_t)len, f) != (size_t)len)) {
        free(buf);
        fclose(f);
        return NULL;
    }
    fclose(f);
    if (len_out) *len_out = (uint32_t)len;
    return buf;
}

/* Minimal extraction of an integer field from pack.json ("key": 123). */
static long json_int(const char *json, const char *key)
{
    char pat[64];
    snprintf(pat, sizeof pat, "\"%s\":", key);
    const char *p = strstr(json, pat);
    if (!p) return -1;
    return strtol(p + strlen(pat), NULL, 10);
}

static void join(char *out, size_t cap, const char *dir, const char *name)
{
    snprintf(out, cap, "%s/%s", dir, name);
}

int omp_pack_open(omp_pack *p, const char *dir, omp_pack_mode mode)
{
    char path[512];
    memset(p, 0, sizeof *p);
    p->mode = mode;

    join(path, sizeof path, dir, "pack.json");
    char *meta = read_all(path, NULL);
    if (!meta) return -1;
    long n = json_int(meta, "tracks"), k = json_int(meta, "k");
    long dim = json_int(meta, "dim"), rec = json_int(meta, "record_size");
    free(meta);
    if (n <= 0 || k <= 0 || dim != OMP_DIM || rec != (long)sizeof(omp_track))
        return -2;
    p->n = (uint32_t)n;
    p->k = (uint32_t)k;

    uint32_t len;
    if (mode == OMP_PACK_STREAM_ALL) {
        join(path, sizeof path, dir, "tracks.bin");
        p->tracks_f = fopen(path, "rb");
        join(path, sizeof path, dir, "strings.bin");
        p->strings_f = fopen(path, "rb");
        join(path, sizeof path, dir, "ids.bin");
        p->ids_f = fopen(path, "rb");
        if (!p->tracks_f || !p->strings_f || !p->ids_f) goto fail;
        fseek(p->strings_f, 0, SEEK_END);
        p->strings_len = (uint32_t)ftell(p->strings_f);
    } else {
        join(path, sizeof path, dir, "tracks.bin");
        p->tracks = (omp_track *)read_all(path, &len);
        if (!p->tracks || len != p->n * sizeof(omp_track)) goto fail;
        join(path, sizeof path, dir, "strings.bin");
        p->strings = read_all(path, &p->strings_len);
        if (!p->strings || p->strings_len == 0 || p->strings[p->strings_len - 1] != '\0') goto fail;
        join(path, sizeof path, dir, "ids.bin");
        p->ids = read_all(path, &len);
        if (!p->ids || len != p->n * 11) goto fail;
    }

    if (mode == OMP_PACK_LOAD_ALL) {
        join(path, sizeof path, dir, "embeddings.f16");
        p->emb = (uint16_t *)read_all(path, &len);
        if (!p->emb || len != p->n * OMP_DIM * 2) goto fail;
        join(path, sizeof path, dir, "neighbors.bin");
        p->nbr = (uint32_t *)read_all(path, &len);
        if (!p->nbr || len != p->n * p->k * 4) goto fail;
    } else {
        join(path, sizeof path, dir, "embeddings.f16");
        p->emb_f = fopen(path, "rb");
        join(path, sizeof path, dir, "neighbors.bin");
        p->nbr_f = fopen(path, "rb");
        if (!p->emb_f || !p->nbr_f) goto fail;
    }
    return 0;
fail:
    omp_pack_close(p);
    return -3;
}

void omp_pack_close(omp_pack *p)
{
    free(p->tracks);
    free(p->strings);
    free(p->ids);
    free(p->emb);
    free(p->nbr);
    free(p->id_index);
    if (p->emb_f) fclose(p->emb_f);
    if (p->nbr_f) fclose(p->nbr_f);
    if (p->tracks_f) fclose(p->tracks_f);
    if (p->strings_f) fclose(p->strings_f);
    if (p->ids_f) fclose(p->ids_f);
    memset(p, 0, sizeof *p);
}

#define STR_RING 8
#define STR_MAX 256
#define TRK_RING 16

const char *omp_pack_str(const omp_pack *p, uint32_t off)
{
    if (off >= p->strings_len) return "";
    if (p->mode != OMP_PACK_STREAM_ALL) return p->strings + off;
    static char ring[STR_RING][STR_MAX];
    static unsigned slot;
    char *b = ring[slot++ % STR_RING];
    size_t got = 0;
    if (fseek(p->strings_f, (long)off, SEEK_SET) == 0)
        got = fread(b, 1, STR_MAX - 1, p->strings_f);
    b[got] = 0;
    size_t len = strlen(b);
    if (len == STR_MAX - 1)                  /* clipped: back off to a UTF-8 boundary */
        while (len > 0 && ((unsigned char)b[len] & 0xC0) == 0x80) b[--len] = 0;
    return b;
}

const omp_track *omp_pack_track(const omp_pack *p, uint32_t i)
{
    if (p->mode != OMP_PACK_STREAM_ALL) return &p->tracks[i];
    static omp_track ring[TRK_RING];
    static unsigned slot;
    omp_track *t = &ring[slot++ % TRK_RING];
    if (fseek(p->tracks_f, (long)((size_t)i * sizeof(omp_track)), SEEK_SET) != 0 ||
        fread(t, sizeof *t, 1, p->tracks_f) != 1)
        memset(t, 0, sizeof *t);
    return t;
}

const char *omp_pack_id(const omp_pack *p, uint32_t i)
{
    if (p->mode != OMP_PACK_STREAM_ALL) return p->ids + (size_t)i * 11;
    static char ring[STR_RING][12];
    static unsigned slot;
    char *b = ring[slot++ % STR_RING];
    if (fseek(p->ids_f, (long)((size_t)i * 11), SEEK_SET) != 0 || fread(b, 1, 11, p->ids_f) != 11)
        memset(b, 0, 11);
    b[11] = 0;
    return b;
}

static uint32_t id_hash(const char *id)
{
    uint32_t h = 2166136261u;
    for (int i = 0; i < 11; i++) h = (h ^ (uint8_t)id[i]) * 16777619u;
    return h;
}

static int cmp_pair(const void *a, const void *b)
{
    uint32_t x = *(const uint32_t *)a, y = *(const uint32_t *)b;
    return x < y ? -1 : x > y;
}

uint32_t omp_pack_find_id(const omp_pack *p, const char *video_id)
{
    if (p->mode != OMP_PACK_STREAM_ALL) {
        for (uint32_t i = 0; i < p->n; i++)
            if (memcmp(p->ids + (size_t)i * 11, video_id, 11) == 0)
                return i;
        return UINT32_MAX;
    }
    static char chunk[11 * 256];
    omp_pack *mp = (omp_pack *)p;
    if (!mp->id_index) {
        /* one pass over ids.bin -> (hash, idx) sorted: lookups become a binary search
         * plus one 11-byte read, instead of a scan of the whole file each time */
        uint32_t *ix = malloc((size_t)p->n * 8 + 8);
        if (ix) {
            fseek(p->ids_f, 0, SEEK_SET);
            for (uint32_t i = 0; i < p->n; i += 256) {
                uint32_t k = p->n - i < 256 ? p->n - i : 256;
                if (fread(chunk, 11, k, p->ids_f) != k) { free(ix); ix = NULL; break; }
                for (uint32_t j = 0; j < k; j++) {
                    ix[2 * (i + j)] = id_hash(chunk + j * 11);
                    ix[2 * (i + j) + 1] = i + j;
                }
            }
            if (ix) qsort(ix, p->n, 8, cmp_pair);
            mp->id_index = ix;
        }
    }
    if (mp->id_index) {
        uint32_t h = id_hash(video_id), lo = 0, hi = p->n;
        while (lo < hi) {
            uint32_t mid = (lo + hi) / 2;
            if (mp->id_index[2 * mid] < h) lo = mid + 1; else hi = mid;
        }
        for (; lo < p->n && mp->id_index[2 * lo] == h; lo++) {
            uint32_t i = mp->id_index[2 * lo + 1];
            const char *id = omp_pack_id(p, i);
            if (id && memcmp(id, video_id, 11) == 0) return i;
        }
        return UINT32_MAX;
    }
    fseek(p->ids_f, 0, SEEK_SET);
    for (uint32_t i = 0; i < p->n; i += 256) {
        uint32_t k = p->n - i < 256 ? p->n - i : 256;
        if (fread(chunk, 11, k, p->ids_f) != k) break;
        for (uint32_t j = 0; j < k; j++)
            if (memcmp(chunk + j * 11, video_id, 11) == 0) return i + j;
    }
    return UINT32_MAX;
}

int omp_pack_vec(omp_pack *p, uint32_t i, float out[OMP_DIM])
{
    static uint16_t raw[OMP_DIM];       /* static: 7.5KB plugin stack on the H2 */
    const uint16_t *src;
    if (i >= p->n) return -1;
    if (p->mode == OMP_PACK_LOAD_ALL) {
        src = p->emb + (size_t)i * OMP_DIM;
    } else {
        if (fseek(p->emb_f, (long)((size_t)i * OMP_DIM * 2), SEEK_SET) != 0 ||
            fread(raw, 2, OMP_DIM, p->emb_f) != OMP_DIM)
            return -1;
        src = raw;
    }
    for (int d = 0; d < OMP_DIM; d++)
        out[d] = omp_half_to_float(src[d]);
    return 0;
}

int omp_pack_neighbors(omp_pack *p, uint32_t i, uint32_t *out)
{
    if (i >= p->n) return -1;
    if (p->mode == OMP_PACK_LOAD_ALL) {
        memcpy(out, p->nbr + (size_t)i * p->k, (size_t)p->k * 4);
    } else {
        if (fseek(p->nbr_f, (long)((size_t)i * p->k * 4), SEEK_SET) != 0 ||
            fread(out, 4, p->k, p->nbr_f) != p->k)
            return -1;
    }
    int cnt = 0;
    while (cnt < (int)p->k && out[cnt] != OMP_NBR_PAD)
        cnt++;
    return cnt;
}
