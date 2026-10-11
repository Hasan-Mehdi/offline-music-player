#include "cfont.h"
#include "../plat/plat.h"
#include <string.h>

static uint32_t rd32(const uint8_t *b) { return b[0] | (b[1] << 8) | (b[2] << 16) | ((uint32_t)b[3] << 24); }

int font_open(font *f, int fd, uint32_t base)
{
    uint8_t h[20];
    memset(f, 0, sizeof *f);
    f->fd = fd;
    f->base = base;
    if (fd < 0 || plat_pread(fd, h, 20, base) != 20 || memcmp(h, "CGF1", 4) != 0) return -1;
    f->px = h[4] | (h[5] << 8);
    f->ascent = (int16_t)(h[6] | (h[7] << 8));
    f->descent = (int16_t)(h[8] | (h[9] << 8));
    f->n = rd32(h + 12);
    f->data_off = base + rd32(h + 16);
    /* low entries come first (table is sorted by code point) */
    cgf_glyph probe;
    uint32_t lo = 0, hi = f->n;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        plat_pread(fd, &probe, sizeof probe, base + 20 + mid * (uint32_t)sizeof probe);
        if (probe.cp < FONT_RAM_CP) lo = mid + 1; else hi = mid;
    }
    f->n_ram = lo;
    f->tab = plat_alloc(sizeof(cgf_glyph) * (f->n_ram ? f->n_ram : 1));
    if (f->n_ram) plat_pread(fd, f->tab, (int)(sizeof(cgf_glyph) * f->n_ram), base + 20);
    uint32_t end = 0;
    for (uint32_t i = 0; i < f->n_ram; i++) {
        uint32_t e = f->tab[i].off + (uint32_t)((f->tab[i].w + 1) / 2) * f->tab[i].h;
        if (e > end) end = e;
    }
    f->bits = plat_alloc(end ? end : 1);
    if (end) plat_pread(f->fd, f->bits, (int)end, f->data_off);
    return 0;
}

/* shared on-demand cache for high code points */
#define GC_SLOTS 160
#define GC_BITS 400
typedef struct {
    const font *f;
    uint32_t cp, used;
    uint8_t missing;
    cgf_glyph g;
    uint8_t bits[GC_BITS];
} gc_slot;
static gc_slot *gcache;
static uint32_t gc_clock;

const cgf_glyph *font_glyph(const font *f, uint32_t cp, const uint8_t **bits)
{
    if (cp < FONT_RAM_CP) {
        uint32_t lo = 0, hi = f->n_ram;
        while (lo < hi) {
            uint32_t mid = (lo + hi) / 2, c = f->tab[mid].cp;
            if (c == cp) { *bits = f->bits + f->tab[mid].off; return &f->tab[mid]; }
            if (c < cp) lo = mid + 1; else hi = mid;
        }
        return NULL;
    }
    if (!gcache) gcache = plat_alloc(sizeof(gc_slot) * GC_SLOTS);
    gc_clock++;
    int victim = 0;
    for (int i = 0; i < GC_SLOTS; i++) {
        gc_slot *s = &gcache[i];
        if (s->f == f && s->cp == cp) {
            s->used = gc_clock;
            if (s->missing) return NULL;
            *bits = s->bits;
            return &s->g;
        }
        if (s->used < gcache[victim].used) victim = i;
    }
    gc_slot *s = &gcache[victim];
    s->f = f; s->cp = cp; s->used = gc_clock; s->missing = 1;
    uint32_t lo = f->n_ram, hi = f->n;
    cgf_glyph probe;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        if (plat_pread(f->fd, &probe, sizeof probe, f->base + 20 + mid * (uint32_t)sizeof probe) != (int)sizeof probe) break;
        if (probe.cp == cp) {
            int nb = ((probe.w + 1) / 2) * probe.h;
            if (nb <= GC_BITS && (nb == 0 || plat_pread(f->fd, s->bits, nb, f->data_off + probe.off) == nb)) {
                s->g = probe;
                s->missing = 0;
                *bits = s->bits;
                return &s->g;
            }
            break;
        }
        if (probe.cp < cp) lo = mid + 1; else hi = mid;
    }
    return NULL;
}

uint32_t utf8_next(const char **sp)
{
    const unsigned char *s = (const unsigned char *)*sp;
    uint32_t c = *s;
    if (!c) return 0;
    int n = c < 0x80 ? 0 : (c & 0xE0) == 0xC0 ? 1 : (c & 0xF0) == 0xE0 ? 2 : (c & 0xF8) == 0xF0 ? 3 : -1;
    if (n < 0) { *sp += 1; return 0xFFFD; }
    if (n) c &= 0x3F >> n;
    for (int i = 1; i <= n; i++) {
        if ((s[i] & 0xC0) != 0x80) { *sp += i; return 0xFFFD; }
        c = (c << 6) | (s[i] & 0x3F);
    }
    *sp += n + 1;
    return c;
}

static int utf8_put(uint32_t c, char *o)
{
    if (c < 0x80) { o[0] = (char)c; return 1; }
    if (c < 0x800) { o[0] = (char)(0xC0 | (c >> 6)); o[1] = (char)(0x80 | (c & 63)); return 2; }
    if (c < 0x10000) {
        o[0] = (char)(0xE0 | (c >> 12)); o[1] = (char)(0x80 | ((c >> 6) & 63));
        o[2] = (char)(0x80 | (c & 63)); return 3;
    }
    o[0] = (char)(0xF0 | (c >> 18)); o[1] = (char)(0x80 | ((c >> 12) & 63));
    o[2] = (char)(0x80 | ((c >> 6) & 63)); o[3] = (char)(0x80 | (c & 63)); return 4;
}

static uint32_t upper_cp(uint32_t c)
{
    if (c >= 'a' && c <= 'z') return c - 32;
    if (c < 0xE0) return c;
    if (c <= 0xFE && c != 0xF7) return c - 32;              /* Latin-1 */
    if (c == 0xFF) return 0x178;
    if (c >= 0x100 && c <= 0x17F) {                         /* Latin Extended-A pairs */
        if ((c >= 0x139 && c <= 0x148) || (c >= 0x179 && c <= 0x17E)) return (c & 1) ? c : c - 1;
        return (c & 1) ? c - 1 : c;
    }
    if (c >= 0x3B1 && c <= 0x3C9 && c != 0x3C2) return c - 32;  /* Greek */
    if (c >= 0x430 && c <= 0x44F) return c - 32;            /* Cyrillic */
    if (c >= 0x450 && c <= 0x45F) return c - 80;
    if (c >= 0xFF41 && c <= 0xFF5A) return c - 32;          /* fullwidth */
    return c;
}

void utf8_upper(const char *in, char *out, size_t outsz)
{
    size_t o = 0;
    uint32_t c;
    while ((c = utf8_next(&in)) != 0) {
        char tmp[4];
        int n = utf8_put(upper_cp(c), tmp);
        if (o + n >= outsz) break;
        memcpy(out + o, tmp, n);
        o += n;
    }
    out[o] = 0;
}

/* marks that have no width of their own: joiners, direction marks, variation selectors,
 * combining overlays, tag characters, skin-tone modifiers, the braille blank. Missing from
 * the fonts, they'd each print a tofu box in the middle of a title. */
static int zero_width(uint32_t c)
{
    return (c >= 0x0300 && c <= 0x036F) || (c >= 0x1AB0 && c <= 0x1AFF) ||
           (c >= 0x200B && c <= 0x200F) || (c >= 0x202A && c <= 0x202E) ||
           (c >= 0x2060 && c <= 0x2064) || (c >= 0x20D0 && c <= 0x20FF) ||
           (c >= 0xFE00 && c <= 0xFE0F) || c == 0xFEFF || c == 0x2800 ||
           (c >= 0x1F3FB && c <= 0x1F3FF) || (c >= 0xE0000 && c <= 0xE007F);
}

static int glyph_adv(const font *f, uint32_t c, const cgf_glyph **gp, const uint8_t **bits)
{
    const cgf_glyph *g = font_glyph(f, c, bits);
    *gp = g;
    if (g) return g->adv_q4;
    if (zero_width(c)) return 0;
    return f->px * 16 * 6 / 10;          /* tofu box */
}

int text_w_q4(const font *f, const char *s, int track_q4)
{
    int w = 0;
    uint32_t c;
    const cgf_glyph *g;
    const uint8_t *bits;
    while ((c = utf8_next(&s)) != 0) w += glyph_adv(f, c, &g, &bits) + track_q4;
    return w;
}

static void draw_glyph(gfx *gx, const cgf_glyph *g, const uint8_t *bits, int x, int y, px16 col)
{
    int stride = (g->w + 1) / 2;
    for (int j = 0; j < g->h; j++) {
        int py = y + g->by + j;
        if (py < gx->cy0 || py >= gx->cy1) continue;
        px16 *row = gx->px + py * gx->stride;
        for (int i = 0; i < g->w; i++) {
            int px = x + g->bx + i;
            if (px < gx->cx0 || px >= gx->cx1) continue;
            int nib = bits[j * stride + i / 2];
            nib = (i & 1) ? (nib & 15) : (nib >> 4);
            if (nib) row[px] = blend565(row[px], col, nib == 15 ? 256 : nib * 17);
        }
    }
}

int text_draw(gfx *gx, const font *f, int x_q4, int y, const char *s, px16 c, int track_q4)
{
    int x0 = x_q4;
    uint32_t cp;
    const cgf_glyph *g;
    const uint8_t *bits;
    while ((cp = utf8_next(&s)) != 0) {
        int adv = glyph_adv(f, cp, &g, &bits);
        int px = (x_q4 + 8) >> 4;
        if (g) {
            if (g->w) draw_glyph(gx, g, bits, px, y, c);
        } else if (cp != ' ' && adv) {               /* tofu: hollow box */
            int bw = adv / 16 - 2, bh = f->ascent * 7 / 10;
            g_fill(gx, px + 1, y - bh, bw, 1, c);
            g_fill(gx, px + 1, y - 1, bw, 1, c);
            g_fill(gx, px + 1, y - bh, 1, bh, c);
            g_fill(gx, px + bw, y - bh, 1, bh, c);
        }
        x_q4 += adv + track_q4;
    }
    return x_q4 - x0;
}

void text_fit(const font *f, const char *s, int max_w, int track_q4, char *out, size_t outsz)
{
    size_t n = strlen(s);
    if (n >= outsz) n = outsz - 1;
    memcpy(out, s, n);
    out[n] = 0;
    if (text_w(f, out, track_q4) <= max_w) return;
    static const char ell[] = "\xE2\x80\xA6";          /* … */
    int ell_w = text_w_q4(f, ell, track_q4);
    /* walk forward keeping the longest prefix that fits with the ellipsis */
    const char *p = s;
    size_t keep = 0;
    int w = 0;
    uint32_t c;
    const cgf_glyph *g;
    const uint8_t *bits;
    while ((c = utf8_next(&p)) != 0) {
        w += glyph_adv(f, c, &g, &bits) + track_q4;
        if ((w + ell_w + 15) / 16 > max_w) break;
        keep = (size_t)(p - s);
    }
    while (keep > 0 && s[keep - 1] == ' ') keep--;
    if (keep + 4 > outsz) keep = outsz - 4;
    memcpy(out, s, keep);
    memcpy(out + keep, ell, 4);
}

int text_wrap(const font *f, const char *s, int max_w, int max_lines, int track_q4,
              char lines[][TEXT_LINE_MAX])
{
    int nl = 0;
    char cur[TEXT_LINE_MAX] = "";
    const char *p = s;
    while (*p && nl < max_lines) {
        while (*p == ' ') p++;
        if (!*p) break;
        const char *we = p;
        while (*we && *we != ' ') we++;
        char trial[TEXT_LINE_MAX];
        size_t cl = strlen(cur), wl = (size_t)(we - p);
        if (cl + 1 + wl >= TEXT_LINE_MAX) wl = TEXT_LINE_MAX - cl - 2;
        memcpy(trial, cur, cl);
        size_t tl = cl;
        if (cl) trial[tl++] = ' ';
        memcpy(trial + tl, p, wl);
        trial[tl + wl] = 0;
        if (!cl || text_w(f, trial, track_q4) <= max_w) {
            memcpy(cur, trial, tl + wl + 1);
            p = we;
            continue;
        }
        if (nl == max_lines - 1) break;                /* last line: rest gets ellipsized */
        text_fit(f, cur, max_w, track_q4, lines[nl++], TEXT_LINE_MAX);  /* one over-long word */
        cur[0] = 0;
    }
    if (nl < max_lines && (cur[0] || *p)) {
        char rest[TEXT_LINE_MAX * 2];
        size_t cl = strlen(cur);
        memcpy(rest, cur, cl);
        if (*p) {
            size_t pl = strlen(p);
            if (cl + 1 + pl >= sizeof rest) pl = sizeof rest - cl - 2;
            if (cl) rest[cl++] = ' ';
            memcpy(rest + cl, p, pl);
            cl += pl;
        }
        rest[cl] = 0;
        text_fit(f, rest, max_w, track_q4, lines[nl], TEXT_LINE_MAX);
        nl++;
    }
    return nl;
}
