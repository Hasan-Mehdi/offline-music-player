/* Coda's symbols: plain geometric marks (no drawings) built from the renderer's own shapes
 * -- discs, rings, bars, convex polygons -- so every theme can draw them at any size. The
 * eight menu symbols each have a short flourish for when they're picked (u 0..1 through
 * it, 1 = at rest): the wheel turns a slice, the compass swings to north, the heart beats.
 * firmware/tools/mock_menu.py and mock_inner.py are the reference drawings. */
#ifndef CODA_SYM_H
#define CODA_SYM_H

#include "gfx.h"

enum {
    SYM_WHEEL, SYM_NOW, SYM_QUEUE, SYM_EXPLORE, SYM_SEARCH, SYM_LIBRARY, SYM_LIKED, SYM_SETTINGS,
    SYM_SONGS, SYM_ARTISTS, SYM_GENRES, SYM_OSTS, SYM_HISTORY, SYM_SHUFFLE, SYM_STATION,
    SYM_SOUND, SYM_SCREEN, SYM_SLEEP, SYM_POWER, SYM_BT, SYM_CLOCK, SYM_DISLIKE, SYM_NEXT,
    SYM_PLAYBACK, SYM_THEME, SYM_PAUSE, SYM_STOP, SYM_PREV, SYM_GAMES, SYM_ORBIT, SYM_FISH,
    SYM_COUNT
};

/* kind's symbol in an s x s box centred on (cx, cy), in px; fg the mark, bg what it sits on
 * (cut-outs are drawn in it), acc the accent (0 = fg) */
void sym_draw(gfx *g, int kind, float cx, float cy, float s, px16 fg, px16 bg, px16 acc, float u);

/* easing, shared by the themes */
static inline float ez_clamp(float u) { return u < 0 ? 0 : u > 1 ? 1 : u; }
static inline float ez_seg(float t, float a, float b) { return ez_clamp((t - a) / (b - a)); }
static inline float ez_out(float u) { u = ez_clamp(u); return 1 - (1 - u) * (1 - u) * (1 - u); }
static inline float ez_back(float u, float k)
{
    u = ez_clamp(u) - 1;
    return 1 + (k + 1) * u * u * u + k * u * u;
}

#endif
