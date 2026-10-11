/* Record-shop poster, on a 320x240 screen (docs/DESIGN_NOTES.md, docs/h2/). */
#ifndef CODA_THEME_H
#define CODA_THEME_H

#include "gfx.h"
#include "cfont.h"

/* order must match scripts/h2_assets.py FONT_TABLE */
enum { F_POSTER22, F_POSTER18, F_POSTER15, F_BOLD11, F_SEMI12, F_SEMI11, F_BODY10,
       F_MONO10, F_MONO12, F_COUNT };

typedef struct {
    px16 paper, ink, blue, red, sub, rule, wash, strip_bg, strip_fg, strip_sub;
    px16 viz[24];                /* hub sunburst: hue by angle */
} palette;

typedef struct {
    palette day, night;
    const palette *p;            /* active */
    font f[F_COUNT];
} theme;

int theme_load(theme *t);        /* fonts from glyphs.cgp (scripts/h2_assets.py) */
void theme_set_night(theme *t, int night);

#define T_TRACK(px_tenths) ((px_tenths) * 16 / 10)   /* tracking, tenths of a px -> Q4 */

#endif
