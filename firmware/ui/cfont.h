/* CGF1 anti-aliased glyph atlases (scripts/h2_assets.py) + UTF-8 text layout. */
#ifndef CODA_CFONT_H
#define CODA_CFONT_H

#include <stddef.h>
#include <stdint.h>
#include "gfx.h"

#pragma pack(push, 1)
typedef struct {
    uint32_t cp;
    int8_t bx, by;          /* bitmap offset from pen / baseline (by < 0 = above) */
    uint8_t w, h;
    uint16_t adv_q4;
    uint16_t pad;
    uint32_t off;
} cgf_glyph;
#pragma pack(pop)

/* A font keeps its low code points (Latin, punctuation, symbols: cp < FONT_RAM_CP) in RAM
 * and reads everything above (CJK, Hangul) from the card on demand through a shared glyph
 * cache: the H2 plugin cannot hold ~2MB of atlases. */
#define FONT_RAM_CP 0x2700

typedef struct {
    int px, ascent, descent;
    uint32_t n, n_ram, data_off;
    cgf_glyph *tab;               /* the n_ram low entries */
    uint8_t *bits;                /* their bitmaps (prefix of the blob) */
    int fd;
    uint32_t base;                /* where this CGF1 starts inside glyphs.cgp */
} font;

int font_open(font *f, int fd, uint32_t base);   /* one CGF1 inside the open glyph pack */
/* glyph for cp (NULL = not in the font); *bits valid until ~64 more lookups */
const cgf_glyph *font_glyph(const font *f, uint32_t cp, const uint8_t **bits);

/* UTF-8 helpers */
uint32_t utf8_next(const char **s);           /* 0 at end; U+FFFD on bad bytes */
void utf8_upper(const char *in, char *out, size_t outsz);   /* Latin/Greek/Cyrillic */

/* layout (tracking in Q4 px, applied after every glyph) */
int text_w_q4(const font *f, const char *s, int track_q4);
static inline int text_w(const font *f, const char *s, int track_q4)
{
    return (text_w_q4(f, s, track_q4) + 15) / 16;
}
/* draw at pen x (Q4) on baseline y (px); returns advance in Q4 */
int text_draw(gfx *g, const font *f, int x_q4, int y, const char *s, px16 c, int track_q4);
/* copy s into out, ellipsized to fit max_w px */
void text_fit(const font *f, const char *s, int max_w, int track_q4, char *out, size_t outsz);
/* greedy word wrap into up to max_lines lines of LINE_MAX bytes; last line ellipsized.
 * returns line count */
#define TEXT_LINE_MAX 160
int text_wrap(const font *f, const char *s, int max_w, int max_lines, int track_q4,
              char lines[][TEXT_LINE_MAX]);

#endif
