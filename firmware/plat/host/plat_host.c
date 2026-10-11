/* PC implementation of plat.h: stdio files, a simulated clock and a fake player, so the
 * exact device UI code can be rendered and scripted on Windows (zig cc). */
#include "../plat.h"
#include "plat_host.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static char coda_dir[512], pack_dir[512];
static uint32_t sim_ms;
static int64_t epoch0 = 1791661320;           /* 2026-10-10 21:42 (local shot clock) */
static int fixed_clock_h = 21, fixed_clock_m = 42;
static uint16_t (*dur_fn)(uint32_t idx);

void plat_host_init(const char *coda, const char *pack, uint16_t (*duration)(uint32_t))
{
    snprintf(coda_dir, sizeof coda_dir, "%s", coda);
    snprintf(pack_dir, sizeof pack_dir, "%s", pack);
    dur_fn = duration;
}

uint32_t plat_ms(void) { return sim_ms; }
int64_t plat_now(void) { return epoch0 + sim_ms / 1000; }
int plat_battery(void) { return 87; }

void plat_clock(int *h, int *m)
{
    int mins = fixed_clock_h * 60 + fixed_clock_m + (int)(sim_ms / 60000);
    *h = (mins / 60) % 24;
    *m = mins % 60;
}

void plat_host_set_clock(int h, int m) { fixed_clock_h = h; fixed_clock_m = m; }

void plat_log(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
}

void *plat_alloc(size_t n)
{
    void *p = calloc(1, n);
    if (!p) { fprintf(stderr, "out of memory (%zu)\n", n); exit(3); }
    return p;
}

static void resolve(const char *rel, char *out, size_t n)
{
    if (!strncmp(rel, "pack/", 5)) snprintf(out, n, "%s/%s", pack_dir, rel + 5);
    else snprintf(out, n, "%s/%s", coda_dir, rel);
}

void *plat_load(const char *rel, size_t *len)
{
    char path[600];
    resolve(rel, path, sizeof path);
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *b = plat_alloc((size_t)n + 1);
    if (fread(b, 1, (size_t)n, f) != (size_t)n) { fclose(f); return NULL; }
    fclose(f);
    b[n] = 0;
    if (len) *len = (size_t)n;
    return b;
}

int plat_save(const char *rel, const void *data, size_t len)
{
    char path[600];
    resolve(rel, path, sizeof path);
    FILE *f = fopen(path, "wb");
    if (!f) return -1;
    size_t w = fwrite(data, 1, len, f);
    fclose(f);
    return w == len ? 0 : -1;
}

#define MAXF 32
static FILE *files[MAXF];

int plat_open(const char *rel)
{
    char path[600];
    resolve(rel, path, sizeof path);
    for (int i = 0; i < MAXF; i++)
        if (!files[i]) {
            files[i] = fopen(path, "rb");
            return files[i] ? i : -1;
        }
    return -1;
}

int plat_pread(int fd, void *buf, int n, uint32_t off)
{
    if (fd < 0 || fd >= MAXF || !files[fd]) return -1;
#ifdef _WIN32
    if (_fseeki64(files[fd], (long long)off, SEEK_SET) != 0) return -1;
#else
    if (fseeko(files[fd], (off_t)off, SEEK_SET) != 0) return -1;
#endif
    return (int)fread(buf, 1, (size_t)n, files[fd]);
}

void plat_close(int fd)
{
    if (fd >= 0 && fd < MAXF && files[fd]) { fclose(files[fd]); files[fd] = NULL; }
}

/* ---------------------------------------------------------------- fake player */
#define QMAX 1024
static uint32_t q[QMAX];
static int qn, qi, playing, active;
static uint32_t pos_ms;

static uint32_t len_ms(void)
{
    uint16_t d = dur_fn ? dur_fn(q[qi]) : 0;
    return (d ? d : 180) * 1000u;
}

void plat_player(plat_play *st)
{
    st->active = active;
    st->playing = active && playing;
    st->idx = active ? q[qi] : 0;
    st->pos = active ? qi : -1;
    st->elapsed_ms = pos_ms;
    st->length_ms = active ? len_ms() : 0;
}

void plat_play_tracks(const uint32_t *idx, int n, int start, uint32_t start_ms)
{
    qn = n > QMAX ? QMAX : n;
    memcpy(q, idx, (size_t)qn * sizeof *q);
    qi = start;
    pos_ms = start_ms;
    playing = active = qn > 0;
}

void plat_queue_add(uint32_t idx, int next)
{
    if (!active || qn == QMAX) return;
    int at = next ? qi + 1 : qn;
    memmove(q + at + 1, q + at, (size_t)(qn - at) * sizeof *q);
    q[at] = idx;
    qn++;
}

int plat_queue_remove(int pos)
{
    if (pos < 0 || pos >= qn || pos == qi) return -1;
    memmove(q + pos, q + pos + 1, (size_t)(qn - pos - 1) * sizeof *q);
    qn--;
    if (pos < qi) qi--;
    return 0;
}

int plat_queue_read(uint32_t *idx, int cap, int *pos)
{
    int n = qn < cap ? qn : cap;
    memcpy(idx, q, (size_t)n * sizeof *q);
    *pos = active ? qi : -1;
    return active ? n : 0;
}

void plat_jump(int pos)
{
    if (pos < 0 || pos >= qn) return;
    qi = pos;
    pos_ms = 0;
    playing = active = 1;
}

void plat_stop(void) { active = playing = 0; pos_ms = 0; }

void plat_toggle(void) { if (active) playing = !playing; }

void plat_skip(int dir)
{
    if (!active) return;
    if (dir > 0 && qi + 1 < qn) { qi++; pos_ms = 0; }
    else if (dir < 0) { if (pos_ms > 3000 || qi == 0) pos_ms = 0; else { qi--; pos_ms = 0; } }
}

void plat_seek(uint32_t p)
{
    if (active && p >= len_ms()) p = len_ms() - 1;
    pos_ms = p;
}

void plat_beep(int hz, int ms, int amp) { (void)hz; (void)ms; (void)amp; }

int plat_spectrum(uint8_t bands[12])
{
    if (!(active && playing)) return 0;
    /* deterministic stand-in shape: louder lows, a little motion over time */
    static const uint8_t shape[12] = { 242, 216, 230, 178, 158, 140, 153, 122, 102, 112, 84, 71 };
    for (int i = 0; i < 12; i++) {
        int wob = (int)((sim_ms / 90 + (uint32_t)i * 7) % 24) - 12;
        int v = shape[i] + wob;
        bands[i] = (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
    }
    return 1;
}

void plat_host_advance(uint32_t ms)
{
    sim_ms += ms;
    if (active && playing) {
        pos_ms += ms;
        if (pos_ms >= len_ms()) {
            if (qi + 1 < qn) { qi++; pos_ms = 0; }
            else { playing = 0; pos_ms = len_ms(); }
        }
    }
}

/* ---------------------------------------------------------------- PNG out */
static uint32_t crc_tab[256];
static uint32_t crc32_upd(uint32_t c, const uint8_t *b, size_t n)
{
    if (!crc_tab[1])
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t v = i;
            for (int k = 0; k < 8; k++) v = v & 1 ? 0xEDB88320u ^ (v >> 1) : v >> 1;
            crc_tab[i] = v;
        }
    c = ~c;
    for (size_t i = 0; i < n; i++) c = crc_tab[(c ^ b[i]) & 255] ^ (c >> 8);
    return ~c;
}

static void put32(FILE *f, uint32_t v)
{
    uint8_t b[4] = { (uint8_t)(v >> 24), (uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v };
    fwrite(b, 1, 4, f);
}

static void chunk(FILE *f, const char *type, const uint8_t *data, uint32_t n)
{
    put32(f, n);
    fwrite(type, 1, 4, f);
    if (n) fwrite(data, 1, n, f);
    uint32_t c = crc32_upd(0, (const uint8_t *)type, 4);
    put32(f, crc32_upd(c, data, n));
}

int plat_host_png(const char *path, const uint16_t *px, int w, int h, int scale)
{
    int W = w * scale, H = h * scale;
    size_t raw_n = (size_t)H * (1 + (size_t)W * 3);
    uint8_t *raw = malloc(raw_n);
    for (int y = 0; y < H; y++) {
        uint8_t *r = raw + (size_t)y * (1 + W * 3);
        r[0] = 0;
        for (int x = 0; x < W; x++) {
            uint16_t p = px[(y / scale) * w + x / scale];
            int R = p >> 11, G = (p >> 5) & 63, B = p & 31;
            r[1 + x * 3] = (uint8_t)((R << 3) | (R >> 2));
            r[2 + x * 3] = (uint8_t)((G << 2) | (G >> 4));
            r[3 + x * 3] = (uint8_t)((B << 3) | (B >> 2));
        }
    }
    /* zlib stream of stored deflate blocks */
    size_t nblk = (raw_n + 65534) / 65535;
    size_t z_n = 2 + raw_n + nblk * 5 + 4;
    uint8_t *z = malloc(z_n), *o = z;
    *o++ = 0x78; *o++ = 0x01;
    uint32_t a = 1, b = 0;
    for (size_t i = 0; i < raw_n; i++) { a = (a + raw[i]) % 65521; b = (b + a) % 65521; }
    for (size_t off = 0; off < raw_n; off += 65535) {
        size_t n = raw_n - off < 65535 ? raw_n - off : 65535;
        *o++ = off + n >= raw_n;
        *o++ = (uint8_t)n; *o++ = (uint8_t)(n >> 8);
        *o++ = (uint8_t)~n; *o++ = (uint8_t)(~n >> 8);
        memcpy(o, raw + off, n);
        o += n;
    }
    uint32_t ad = (b << 16) | a;
    *o++ = (uint8_t)(ad >> 24); *o++ = (uint8_t)(ad >> 16); *o++ = (uint8_t)(ad >> 8); *o++ = (uint8_t)ad;
    FILE *f = fopen(path, "wb");
    if (!f) { free(raw); free(z); return -1; }
    static const uint8_t sig[8] = { 137, 80, 78, 71, 13, 10, 26, 10 };
    fwrite(sig, 1, 8, f);
    uint8_t ihdr[13] = { (uint8_t)(W >> 24), (uint8_t)(W >> 16), (uint8_t)(W >> 8), (uint8_t)W,
                         (uint8_t)(H >> 24), (uint8_t)(H >> 16), (uint8_t)(H >> 8), (uint8_t)H,
                         8, 2, 0, 0, 0 };
    chunk(f, "IHDR", ihdr, 13);
    chunk(f, "IDAT", z, (uint32_t)(o - z));
    chunk(f, "IEND", NULL, 0);
    fclose(f);
    free(raw);
    free(z);
    return 0;
}
