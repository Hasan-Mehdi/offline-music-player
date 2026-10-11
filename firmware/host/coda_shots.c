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
#include "boot.h"
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
        if (app_tick(A, plat_ms()) & NEED_FULL) app_draw(A, &G);    /* as the device does */
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

static void top(void) { key(K_SCROLL, -100000); }

/* what is in the framebuffer now, as drawn (no app_draw first) */
static void shot_raw(const char *name)
{
    char p[600];
    snprintf(p, sizeof p, "%s/%s.png", out_dir, name);
    plat_host_png(p, fb, LCD_W, LCD_H, 1);
    snprintf(p, sizeof p, "%s/%s@2x.png", out_dir, name);
    plat_host_png(p, fb, LCD_W, LCD_H, 2);
    printf("  %s\n", name);
}

static void pstate(const char *when)
{
    plat_play st;
    plat_player(&st);
    printf("  player %-12s active %d playing %d idx %u pos %d at %u/%u\n", when, st.active,
           st.playing, (unsigned)st.idx, st.pos, (unsigned)st.elapsed_ms, (unsigned)st.length_ms);
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
    if (getenv("SHOTS_ROOM")) {                        /* just Room: Bubloo, the door */
        static uint16_t from[LCD_W * LCD_H];
        char nm[64];
        run(3000);
        app_set_skin(A, 1);
        app_open(A, V_MENU);
        top();
        key(K_SCROLL, 3);
        run(900);
        shot("r_home");
        for (int i = 0; i < 12; i++) {                 /* him on his own, as the device draws him */
            int r[4];
            run(250);
            app_draw(A, &G);
            app_draw_hub(A, &G, r);
            snprintf(nm, sizeof nm, "r_pet%02d", i); shot_raw(nm);
        }
        run(9000);                                     /* settled: no button for a while */
        for (int i = 0; i < 150; i++) {                /* 12.5 s of him, for a GIF */
            int r[4];
            plat_host_advance(83);
            app_tick(A, plat_ms());
            app_draw_hub(A, &G, r);
            snprintf(nm, sizeof nm, "r_idle%03d", i); shot_raw(nm);
        }
        key(K_SCROLL, -3);
        run(900);
        shot("r_home_wheel");
        app_open(A, V_NOW);
        run(900);
        shot("r_now");
        key(K_PLAY, 0);                                /* paused: he dozes, then sleeps */
        run(20000);
        shot("r_now_doze");
        run(30000);
        shot("r_now_asleep");
        app_open(A, V_MENU);
        run(2000);
        shot("r_home_asleep");
        for (int i = 0; i < 60; i++) {
            int r[4];
            plat_host_advance(83);
            app_tick(A, plat_ms());
            app_draw_hub(A, &G, r);
            snprintf(nm, sizeof nm, "r_sleep%03d", i); shot_raw(nm);
        }
        for (int i = 0; i <= 48; i++) {
            app_boot_draw(1, &G, (uint32_t)i * 33);
            snprintf(nm, sizeof nm, "r_boot%02d", i); shot_raw(nm);
        }
        key(K_PLAY, 0);
        app_open(A, V_MENU);
        run(900);
        app_draw(A, &G);
        memcpy(from, fb, sizeof from);
        for (int i = 0; i <= 27; i++) {
            app_draw_off(A, &G, (uint32_t)i * 33, from, 0);
            snprintf(nm, sizeof nm, "r_off%02d", i); shot_raw(nm);
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
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
    key(K_BACK, 0);

    key(K_MENU, 0);
    for (int i = 0; i < 3; i++) key(K_SCROLL, 1);      /* Wheel, Now playing, Explore, Library */
    run(800);
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
    key(K_BACK, 0);

    key(K_MENU, 0);
    for (int i = 0; i < 7; i++) key(K_SCROLL, 1);
    key(K_PLAY, 0);
    shot("c_settings");

    /* step 1 views: Explore, Soundtracks, Genres, Search, Queue, sheets, peek.
     * top() first: list selections persist between visits */
    app_open(A, V_EXPLORE);
    top();
    shot("c_explore");
    key(K_PLAY, 0);
    top();
    shot("c_explore_shelf");
    key(K_SCROLL, 2);
    key(K_PLAY, 0);                                    /* a fresh find: plays, autoplay follows */
    run(3000);
    app_open(A, V_OST);
    top();
    shot("c_osts");
    key(K_SCROLL, 6);
    shot("c_osts_scrolled");
    key(K_PLAY, 0);
    top();
    shot("c_ost_tracks");
    key(K_PLAY, 0);                                    /* Play: the OST in album order */
    run(2000);
    app_open(A, V_QUEUE);
    shot("c_queue_ost");
    app_open(A, V_GENRES);
    top();
    shot("c_genres");
    key(K_SCROLL, 2);
    key(K_PLAY, 0);
    top();
    shot("c_genre_page");
    key(K_PLAY, 0);                                    /* Start station */
    run(400000);                                       /* let the fenced station run a while */
    app_open(A, V_QUEUE);
    shot("c_queue_station");
    app_open(A, V_NOW);
    shot("c_now_station");
    key(K_MENU, 0);                                    /* the Now playing sheet */
    run(700);
    shot("c_now_sheet");
    key(K_BACK, 0);
    key(K_BACK, 0);

    /* Settings: the panels; Sleep's list with a value being turned; the themes; the clock */
    app_open(A, V_SETTINGS);
    key(K_SCROLL, -10);                                /* Sleep */
    run(800);
    shot("c_settings_v2");
    key(K_PLAY, 0);
    key(K_SCROLL, 1);                                  /* Power off idle: adjusting in place */
    key(K_PLAY, 0);
    key(K_SCROLL, -3);
    run(400);
    shot("c_settings_adjust");
    key(K_PLAY, 0);
    key(K_BACK, 0);                                    /* back to the panels */
    key(K_SCROLL, 3);                                  /* Theme */
    key(K_PLAY, 0);
    run(400);
    shot("c_settings_end");
    key(K_BACK, 0);
    key(K_SCROLL, 4);                                  /* Clock */
    key(K_PLAY, 0);
    key(K_SCROLL, 2);
    key(K_PLAY, 0);
    shot("c_clock");
    key(K_BACK, 0);
    key(K_BACK, 0);

    /* Search: t, o, b, y -> results */
    app_open(A, V_SEARCH);
    shot("c_search_empty");
    const char *word = "toby";
    for (const char *c = word; *c; c++) {
        int target = *c - 'a';
        key(K_SCROLL, target - 0);                     /* rail starts at 'a' after each type? */
        key(K_PLAY, 0);
        key(K_SCROLL, -target);
    }
    shot("c_search_typed");
    key(K_PLAY_LONG, 0);                               /* to the results */
    shot("c_search_results");
    key(K_SCROLL, 4);                                  /* past the artist rows */
    key(K_PLAY_LONG, 0);                               /* the track sheet */
    run(700);
    shot("c_track_sheet");
    key(K_BACK, 0);

    /* Wheel peek: land on another slice and wait */
    app_open(A, V_WHEEL);
    run(800);
    key(K_SCROLL, 2);
    run(1200);
    shot("c_wheel_peek");
    pstate("peeking");
    key(K_SCROLL, -2);
    run(1500);
    pstate("after peek");

    app_set_night(A, 1);
    app_open(A, V_WHEEL);
    run(600);
    shot("c_wheel_a_night");
    app_open(A, V_NOW);
    shot("c_now_night");
    app_set_night(A, 0);
    pstate("before idle");
    app_open(A, V_NOW);
    for (int i = 0; i < 10; i++) key(K_SCROLL, 1);
    run(100);
    pstate("seek +50s");
    shot("c_now_seeking");
    run(2000);    /* power: how much drawing does 10s of doing nothing cost, per screen? */
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

    /* Settings > Bluetooth, on the host's stand-in radio (one pair remembered) */
    app_open(A, V_SETTINGS);
    top();
    key(K_SCROLL, 6);                                  /* the Bluetooth panel */
    shot("c_settings_bt");
    key(K_PLAY, 0);
    shot("c_bt_off");
    key(K_PLAY, 0);                                    /* switch on */
    run(400);
    shot("c_bt_starting");
    run(1500);
    shot("c_bt_on");
    key(K_SCROLL, 10);                                 /* down to the search row */
    key(K_PLAY, 0);
    run(2000);
    shot("c_bt_searching");
    run(2500);
    shot("c_bt_found");
    key(K_SCROLL, 1);                                  /* last row stays put: back up one */
    key(K_SCROLL, -1);
    shot("c_bt_found_focus");
    top();
    key(K_SCROLL, 1);                                  /* the remembered pair */
    key(K_PLAY, 0);
    run(500);
    shot("c_bt_connecting");
    run(2200);
    shot("c_bt_connected");
    app_open(A, V_NOW);
    shot("c_now_bt");
    app_open(A, V_MENU);
    shot("c_menu_bt");

    /* every theme: its home, a list, Library, Settings, a shelf page, the sheet (t<i>_*.png) */
    for (int sk = 1; sk < 8; sk++) {
        char nm[64];
        app_set_skin(A, sk);
        app_open(A, V_MENU);
        top();
        key(K_SCROLL, 3);
        run(800);
        snprintf(nm, sizeof nm, "t%d_home", sk); shot(nm);
        app_open(A, V_LIBRARY);
        run(800);
        snprintf(nm, sizeof nm, "t%d_library", sk); shot(nm);
        app_open(A, V_QUEUE);
        key(K_SCROLL, 1);
        run(600);
        snprintf(nm, sizeof nm, "t%d_queue", sk); shot(nm);
        app_open(A, V_SETTINGS);
        run(800);
        snprintf(nm, sizeof nm, "t%d_settings", sk); shot(nm);
        app_open(A, V_EXPLORE);
        run(600);
        snprintf(nm, sizeof nm, "t%d_explore", sk); shot(nm);
        app_open(A, V_WHEEL);
        run(900);
        snprintf(nm, sizeof nm, "t%d_wheel", sk); shot(nm);
        app_open(A, V_NOW);
        run(400);
        snprintf(nm, sizeof nm, "t%d_now", sk); shot(nm);
        key(K_MENU, 0);
        run(700);
        snprintf(nm, sizeof nm, "t%d_sheet", sk); shot(nm);
        key(K_BACK, 0);
    }
    /* each theme's power-on (no app needed) and power-off (from its home), as film strips */
    for (int sk = 1; sk < 8; sk++) {
        static uint16_t from[LCD_W * LCD_H];
        static const uint32_t TS[5] = { 200, 500, 800, 1100, 1600 }, TO[4] = { 60, 200, 450, 800 };
        char nm[64];
        for (int i = 0; i < 5; i++) {
            app_boot_draw(sk, &G, TS[i]);
            snprintf(nm, sizeof nm, "t%d_boot%d", sk, i); shot_raw(nm);
        }
        app_set_skin(A, sk);
        app_open(A, V_MENU);
        run(800);
        app_draw(A, &G);
        memcpy(from, fb, sizeof from);
        for (int i = 0; i < 4; i++) {
            app_draw_off(A, &G, TO[i], from, 0);
            snprintf(nm, sizeof nm, "t%d_off%d", sk, i); shot_raw(nm);
        }
    }
    app_set_skin(A, 0);

    /* Coda OS power-off ("your crate") from Now Playing: frames at 30 fps, off_NNN.png */
    {
        static uint16_t from[LCD_W * LCD_H];
        app_open(A, V_NOW);
        app_draw(A, &G);
        memcpy(from, fb, sizeof from);
        int n = 0;
        for (uint32_t t = 0; t <= BOOT_OFF_MS; t += 33, n++) {
            char p[600];
            app_draw_off(A, &G, t, from, 0);
            snprintf(p, sizeof p, "%s/off_%03d.png", out_dir, n);
            plat_host_png(p, fb, LCD_W, LCD_H, 1);
        }
        app_draw_off(A, &G, 0, from, 2);
        shot_raw("c_off_battery");
        printf("  %d power-off frames\n", n);
    }
    printf("ok -> %s\n", out_dir);
    return 0;
}
