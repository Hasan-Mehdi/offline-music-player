#include "crates.h"
#include <stdio.h>
#include <string.h>
#include "../plat/plat.h"

static uint32_t rd32(const uint8_t *b) { return b[0] | (b[1] << 8) | (b[2] << 16) | ((uint32_t)b[3] << 24); }

int crates_open(crates *c, const char *rel)
{
    memset(c, 0, sizeof *c);
    snprintf(c->file, sizeof c->file, "%s", rel);
    int fd = plat_open(rel);
    if (fd < 0) return 0;
    uint8_t h[16];
    if (plat_pread(fd, h, 16, 0) != 16 || memcmp(h, "CRT1", 4)) {
        plat_log("%s: not a CRT1 file", rel);
        plat_close(fd);
        return -1;
    }
    uint32_t n = rd32(h + 4), nm = rd32(h + 8), sl = rd32(h + 12);
    c->tab = plat_alloc(sizeof(crate) * (n ? n : 1));
    c->str = plat_alloc(sl + 1);
    uint8_t row[24];
    for (uint32_t i = 0; i < n; i++) {
        if (plat_pread(fd, row, 24, 16 + 24 * i) != 24) break;
        crate *k = &c->tab[i];
        k->name = rd32(row); k->sub = rd32(row + 4); k->section = rd32(row + 8);
        k->first = rd32(row + 12); k->count = rd32(row + 16); k->seconds = rd32(row + 20);
    }
    c->members_off = 16 + 24 * n;
    if (plat_pread(fd, c->str, (int)sl, c->members_off + 4 * nm) != (int)sl) sl = 0;
    c->str[sl] = 0;
    c->n = n;
    c->n_members = nm;
    plat_close(fd);
    return 0;
}

int crate_members(const crates *c, uint32_t i, uint32_t from, uint32_t *out, int n)
{
    if (i >= c->n || from >= c->tab[i].count || n <= 0) return 0;
    uint32_t left = c->tab[i].count - from;
    if ((uint32_t)n > left) n = (int)left;
    int fd = plat_open(c->file);
    if (fd < 0) return 0;
    int got = plat_pread(fd, out, 4 * n, c->members_off + 4 * (c->tab[i].first + from));
    plat_close(fd);
    got = got > 0 ? got / 4 : 0;
    for (int k = 0; k < got; k++) out[k] = rd32((const uint8_t *)&out[k]);   /* LE on any host */
    return got;
}
