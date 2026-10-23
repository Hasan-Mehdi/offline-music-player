/* The pixel themes' toolkit (docs/h2/pixel, docs/h2/room; firmware/tools/mock_room.py and
 * mock_pixel.py are the reference renders): the built-in fonts, a 2x2-pixel grid ("chunky"
 * coordinates are half the screen's: 160 x 120), pixel-stepped rounded corners, the room's
 * materials as textures, symbols snapped to the grid, the bobbing pointer. */
#ifndef CODA_PIX_H
#define CODA_PIX_H

#include "gfx.h"
#include "pixfont.h"

/* text in a built-in font; scale 2 draws each font pixel as a 2x2 block. Returns the
 * advance in screen px. 8-bit fonts (PF_POSTER11) only at scale 1. */
int pf_text(gfx *g, const pixfont *f, int x, int y_base, const char *s, px16 c, int scale);
int pf_width(const pixfont *f, const char *s, int scale);

/* the 2x2 grid: everything in chunky cells */
void ck_rect(gfx *g, int a, int b, int c, int d, px16 col);            /* cells [a,c) x [b,d) */
void ck_rrect(gfx *g, int a, int b, int c, int d, px16 col, int r);    /* r 0..3: stepped corners */
void ck_hline(gfx *g, int a, int c, int b, px16 col);
void ck_point(gfx *g, int a, int b, px16 col);

/* the room's materials */
enum { MAT_WOOD, MAT_LEATHER, MAT_LEAF, MAT_SAGE, MAT_SILVER, MAT_SHADE, MAT_KEY, MAT_FELT,
       MAT_PARCH, MAT_COUNT };
typedef struct {
    px16 wall, wall_sh, walnut, walnut_d, walnut_l, walnut_hi, ink, cream, sub,
         leather, leather_d, stitch, leaf, leaf_l, leaf_d, sage, sage_l, sage_d,
         silver, silver_l, silver_d, slot, shade, shade_line, key, key_d, key_l,
         felt, felt_d, felt_l, led, parch, parch_d, parch_l, red,
         wink, wsub, wacc;          /* text straight on the wall: ink, secondary, accent */
} room_pal;
/* the room by day and after dark (the lamp on); RP is the one in use, set by rp_night */
extern const room_pal RP_DAY, RP_NIGHT;
extern room_pal RP;
extern int rp_k;                    /* how far into night RP is, 0..256 */
void rp_night(int k);
/* any other colour taken into the same night (k = rp_k) */
px16 nightc(px16 c);
px16 mat_base(int mat);
px16 mat_ink(int mat);              /* what's written on it */
px16 mat_acc(int mat);
/* a panel of material (cells, stepped corners); its texture is generated from the seed */
void ck_material(gfx *g, int a, int b, int c, int d, int mat, uint32_t seed, int r);
/* the PC case's vent slots */
void ck_vents(gfx *g, int a, int b, int c, int d);

/* a symbol (sym.h) drawn finely and snapped to the grid in its own colours; centre and
 * size in screen px */
void ck_sym(gfx *g, int kind, int cx, int cy, int s, px16 fg, px16 bg, px16 acc, float u);
/* the pointer beside whatever is picked; t (ms) makes it bob */
void ck_pointer(gfx *g, int x, int y, uint32_t t, px16 outline, px16 fill);

#endif
