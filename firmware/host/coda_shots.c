/* Render the device UI on the PC: drives the real app code with scripted buttons and a
 * simulated clock, writes 320x240 PNGs (1x and 2x). The design check for docs/h2/.
 *
 * usage: coda_shots <coda_dir> <pack_dir> <out_dir>
 *   coda_dir = the card's /.coda (glyphs/, art*, plays.omp), pack_dir = data/device_pack
 * The play log is copied to <out_dir>/plays_shots.omp so the real one is never touched.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "app.h"
#include "brain.h"
#include "gfx.h"
#include "plat_host.h"
#include "../plat/plat.h"

static uint16_t fb[LCD_W * LCD_H];
static gfx G;
static app *A;
static const char *out_dir;

static void run(uint32_t ms)
{
    for (uint32_t t = 0; t < ms; t += 16) {
        plat_host_advance(16);
        app_tick(A, plat_ms());
    }
}

static void key(key_kind k, int d)
{
    ui_ev e = { k, d };
    app_event(A, e);
    run(16);
}

static void shot(const char *name)
{
    char p[600];
    app_draw(A, &G);
    snprintf(p, sizeof p, "%s/%s.png", out_dir, name);
    plat_host_png(p, fb, LCD_W, LCD_H, 1);
    snprintf(p, sizeof p, "%s/%s@2x.png", out_dir, name);
    plat_host_png(p, fb, LCD_W, LCD_H, 2);
    printf("  %s\n", name);
}

static int copy_file(const char *src, const char *dst)
{
    FILE *a = fopen(src, "rb"), *b = fopen(dst, "wb");
    if (!a || !b) { if (a) fclose(a); if (b) fclose(b); return -1; }
    char buf[65536];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf, a)) > 0) fwrite(buf, 1, n, b);
    fclose(a);
    fclose(b);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 4) { printf("usage: coda_shots <coda_dir> <pack_dir> <out_dir>\n"); return 2; }
    out_dir = argv[3];
    char plays_src[600], plays[600];
    snprintf(plays_src, sizeof plays_src, "%s/plays.omp", argv[1]);
    snprintf(plays, sizeof plays, "%s/plays_shots.omp", out_dir);
    if (copy_file(plays_src, plays) != 0) printf("(no plays.omp -- starting with an empty log)\n");
    plat_host_init(argv[1], argv[2], brain_duration);
    g_init(&G, fb, LCD_W, LCD_H, LCD_W);
    A = app_create(argv[2], plays);
    if (!A) { printf("app_create failed\n"); return 1; }
    app_set_night(A, 0);

    /* wheel: open it, play the focused (most recent) track, let it run a while */
    app_open(A, V_WHEEL);
    key(K_PLAY, 0);
    run(40000);
    shot("c_wheel_a");
    app_set_wheel_layout(A, 1);
    shot("c_wheel_b");
    app_set_wheel_layout(A, 0);
    key(K_SCROLL, 1);
    run(48);
    shot("c_wheel_a_spin");
    run(600);
    shot("c_wheel_a_next");
    key(K_SCROLL, -1);
    run(600);

    app_open(A, V_NOW);
    shot("c_now");

    key(K_MENU, 0);
    for (int i = 0; i < 4; i++) key(K_SCROLL, 1);
    shot("c_menu");
    key(K_PLAY, 0);
    shot("c_library");
    key(K_SCROLL, 1);
    key(K_PLAY, 0);
    for (int i = 0; i < 40; i++) key(K_SCROLL, 300);   /* fast spin down the artist list */
    shot("c_artists");
    key(K_PLAY, 0);
    shot("c_artist_tracks");
    key(K_PLAY, 0);
    run(30000);
    key(K_NEXT, 0);                 /* skip -> the brain's pick plays, with its why */
    run(20000);
    app_open(A, V_NOW);
    shot("c_now_after_pick");

    key(K_MENU, 0);
    for (int i = 0; i < 6; i++) key(K_SCROLL, 1);
    key(K_PLAY, 0);
    shot("c_settings");

    app_set_night(A, 1);
    app_open(A, V_WHEEL);
    run(600);
    shot("c_wheel_a_night");
    app_open(A, V_NOW);
    shot("c_now_night");
    app_set_night(A, 0);

    /* power: how much drawing does 10s of doing nothing cost, per screen? */
    struct { int view; const char *name; } idle[] = {
        { V_MENU, "menu" }, { V_NOW, "now playing" }, { V_WHEEL, "wheel" } };
    for (int i = 0; i < 3; i++) {
        app_open(A, idle[i].view);
        run(1000);
        int full = 0, hub = 0, wakes = 0;
        for (uint32_t t = 0; t < 10000; ) {
            uint32_t step = (uint32_t)app_interval_ms(A);
            plat_host_advance(step);
            t += step;
            wakes++;
            int need = app_tick(A, plat_ms());
            full += (need & NEED_FULL) != 0;
            hub += (need & NEED_HUB) != 0;
        }
        printf("  idle 10s on %-12s %3d wakeups, %3d full redraws, %3d hub-only refreshes\n",
               idle[i].name, wakes, full, hub);
    }
    printf("ok -> %s\n", out_dir);
    return 0;
}
