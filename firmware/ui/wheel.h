/* The Wheel (web: web/src/lib/views/Wheel.svelte), drawn per pixel in fixed point.
 * Geometry ratios are the web's: R2 300 / R1 128 svg units, 30deg detents, wedge
 * half-angle 13.6deg, visible wedges -5..+5 around the pointer, art rides its wedge. */
#ifndef CODA_WHEEL_H
#define CODA_WHEEL_H

#include "gfx.h"
#include "theme.h"

typedef struct {
    int cx, cy, r1, r2;      /* px */
    int base_deg;            /* pointer direction: 0 = right (layout A), -90 = up (B) */
} wheel_geom;

extern const wheel_geom WHEEL_A, WHEEL_B;

typedef struct {
    const px16 *tex[11];     /* 112px cover per wedge dd = -5..+5; NULL draws the wash */
    uint8_t show[11];        /* wedge present (small pools leave the back of the wheel empty) */
    const px16 *label;       /* focused track's cover for the record label, or NULL */
    float frac;              /* sub-detent offset s - round(s), in [-0.5, 0.5) */
    int settled;             /* focused wedge gets the blue rim, no shade */
    int playing;             /* label rim red + live bars */
    uint8_t bars[24];        /* spectrum, 0..255 */
} wheel_frame;

void wheel_draw(gfx *g, const palette *p, const wheel_geom *w, const wheel_frame *f);
/* visualizer-only refresh: redraws the hub inside its rim; rect = x, y, w, h to push */
void wheel_draw_hub(gfx *g, const palette *p, const wheel_geom *w, const wheel_frame *f, int rect[4]);

#endif
