#include "omp_playlog.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define REC_SIZE 20
static const char MAGIC[4] = { 'O', 'M', 'P', '1' };

static void put_u32(uint8_t *b, uint32_t v)
{
    b[0] = v & 0xFF; b[1] = (v >> 8) & 0xFF; b[2] = (v >> 16) & 0xFF; b[3] = (v >> 24) & 0xFF;
}

static uint32_t get_u32(const uint8_t *b)
{
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}

int omp_playlog_load(const char *path, omp_play **out)
{
    *out = NULL;
    FILE *f = fopen(path, "rb");
    if (!f) return 0;                          /* no log yet = empty history */
    char magic[4];
    if (fread(magic, 1, 4, f) != 4 || memcmp(magic, MAGIC, 4) != 0) {
        fclose(f);
        return -1;
    }
    fseek(f, 0, SEEK_END);
    long body = ftell(f) - 4;
    fseek(f, 4, SEEK_SET);
    if (body < 0 || body % REC_SIZE != 0) { fclose(f); return -1; }
    int n = (int)(body / REC_SIZE);
    omp_play *arr = malloc(n ? (size_t)n * sizeof *arr : 1);
    if (!arr) { fclose(f); return -1; }
    for (int i = 0; i < n; i++) {
        uint8_t r[REC_SIZE];
        if (fread(r, 1, REC_SIZE, f) != REC_SIZE) { free(arr); fclose(f); return -1; }
        uint64_t tsbits = (uint64_t)get_u32(r) | ((uint64_t)get_u32(r + 4) << 32);
        memcpy(&arr[i].ts, &tsbits, 8);
        arr[i].idx = get_u32(r + 8);
        uint32_t secbits = get_u32(r + 12);
        memcpy(&arr[i].seconds, &secbits, 4);
        arr[i].event = r[16];
    }
    fclose(f);
    *out = arr;
    return n;
}

int omp_playlog_append(const char *path, const omp_play *ev)
{
    FILE *f = fopen(path, "r+b");
    if (!f) {
        f = fopen(path, "wb");
        if (!f) return -1;
        if (fwrite(MAGIC, 1, 4, f) != 4) { fclose(f); return -1; }
    }
    fseek(f, 0, SEEK_END);
    uint8_t r[REC_SIZE] = { 0 };
    uint64_t tsbits;
    uint32_t secbits;
    memcpy(&tsbits, &ev->ts, 8);
    memcpy(&secbits, &ev->seconds, 4);
    put_u32(r, (uint32_t)tsbits);
    put_u32(r + 4, (uint32_t)(tsbits >> 32));
    put_u32(r + 8, ev->idx);
    put_u32(r + 12, secbits);
    r[16] = ev->event;
    int ok = fwrite(r, 1, REC_SIZE, f) == REC_SIZE;
    fclose(f);
    return ok ? 0 : -1;
}
