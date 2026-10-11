#include "theme.h"
#include "../plat/plat.h"

#define HEX(v) C565(((v) >> 16) & 255, ((v) >> 8) & 255, (v) & 255)

static px16 hsl565(int h, int s_pct, int l_pct)
{
    /* integer HSL -> RGB (once at load) */
    int l = l_pct * 255 / 100, s = s_pct;
    int c = (255 - (2 * l - 255 < 0 ? 255 - 2 * l : 2 * l - 255)) * s / 100;   /* chroma */
    int hp = h % 360;
    int x = c * (60 - ((hp % 120) - 60 < 0 ? 60 - (hp % 120) : (hp % 120) - 60)) / 60;
    int r = 0, g = 0, b = 0;
    if (hp < 60) { r = c; g = x; }
    else if (hp < 120) { r = x; g = c; }
    else if (hp < 180) { g = c; b = x; }
    else if (hp < 240) { g = x; b = c; }
    else if (hp < 300) { r = x; b = c; }
    else { r = c; b = x; }
    int m = l - c / 2;
    return C565(r + m, g + m, b + m);
}

int theme_load(theme *t)
{
    palette *d = &t->day, *n = &t->night;
    d->paper = HEX(0xf4f4f0); d->ink = HEX(0x141414); d->blue = HEX(0x002fa7);
    d->red = HEX(0xe0301e); d->sub = HEX(0x6d6d66); d->rule = HEX(0xd9d8d0);
    d->wash = HEX(0xeaeae3); d->strip_bg = HEX(0x141414); d->strip_fg = HEX(0xf4f4f0);
    d->strip_sub = HEX(0x93938b);
    /* night = negative print; the strip goes deeper black instead of inverting */
    n->paper = HEX(0x141414); n->ink = HEX(0xf4f4f0); n->blue = HEX(0x4d6bff);
    n->red = HEX(0xff5040); n->sub = HEX(0x93938b); n->rule = HEX(0x2b2b28);
    n->wash = HEX(0x1f1f1c); n->strip_bg = HEX(0x060606); n->strip_fg = HEX(0xf4f4f0);
    n->strip_sub = HEX(0x93938b);
    for (int i = 0; i < 24; i++) {
        d->viz[i] = hsl565(i * 15, 78, 58);
        n->viz[i] = hsl565(i * 15, 70, 42);
    }
    t->p = d;
    /* all fonts live in one file: Rockbox's open-file budget is shared with playback */
    int fd = plat_open("glyphs.cgp");
    uint8_t h[8 + 8 * F_COUNT];
    if (fd < 0 || plat_pread(fd, h, sizeof h, 0) != (int)sizeof h || h[0] != 'C' || h[3] != '1' ||
        (h[4] | (h[5] << 8)) != F_COUNT) {
        plat_log("glyphs.cgp missing or built for a different font table");
        return -1;
    }
    for (int i = 0; i < F_COUNT; i++) {
        const uint8_t *e = h + 8 + 8 * i;
        uint32_t off = e[0] | (e[1] << 8) | (e[2] << 16) | ((uint32_t)e[3] << 24);
        if (font_open(&t->f[i], fd, off) != 0) {
            plat_log("font %d corrupt", i);
            return -1;
        }
    }
    return 0;
}

void theme_set_night(theme *t, int night) { t->p = night ? &t->night : &t->day; }
