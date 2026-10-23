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
    if (getenv("SHOTS_CHARGE")) plat_host_set_battery(46, 1, 1);   /* the charger switched it on */
    A = app_create(argv[2], plays);
    if (!A) { printf("app_create failed\n"); return 1; }
    app_set_night(A, 0);

    if (getenv("SHOTS_CHARGE")) {                      /* the charge screen; then amber on every theme */
        run(1500);
        shot("chg_screen");
        plat_host_set_battery(100, 2, 0);
        run(700);
        shot("chg_full");
        plat_host_set_battery(46, 1, 0);
        key(K_PLAY, 0);                                /* any button: the player proper */
        run(600);
        static const int SK[3] = { 0, 7, 1 };
        char nm[64];
        for (int i = 0; i < 3; i++) {
            app_set_skin(A, SK[i]);
            app_open(A, V_MENU);
            top();
            run(2500);
            snprintf(nm, sizeof nm, "chg_home_t%d", SK[i]); shot(nm);
        }
        app_set_skin(A, 7);
        app_open(A, V_SETTINGS);
        run(2500);
        shot("chg_dio_h2");
        printf("ok -> %s\n", out_dir);
        return 0;
    }

    /* wheel: open it, play the focused (most recent) track, let it run a while */
    app_open(A, V_WHEEL);
    key(K_PLAY, 0);
    if (getenv("SHOTS_FIX")) {                         /* 10-15: Explore's lists, the sheet, Next at the end */
        char nm[64];
        static const int SK[2] = { 0, 7 };
        run(1500);
        for (int i = 0; i < 2; i++) {
            app_set_skin(A, SK[i]);
            app_open(A, V_NOW);
            run(600);
            key(K_MENU, 0);
            run(800);
            snprintf(nm, sizeof nm, "fix_sheet_t%d", SK[i]); shot(nm);
            key(K_BACK, 0);
            app_open(A, V_EXPLORE);
            run(900);
            snprintf(nm, sizeof nm, "fix_explore_t%d", SK[i]); shot(nm);
            key(K_PLAY, 0);                            /* Fresh finds: the whole list */
            run(900);
            snprintf(nm, sizeof nm, "fix_fresh_t%d", SK[i]); shot(nm);
            key(K_SCROLL, 40);
            run(600);
            snprintf(nm, sizeof nm, "fix_fresh_deep_t%d", SK[i]); shot(nm);
            key(K_BACK, 0);
            key(K_BACK, 0);
        }
        app_set_skin(A, 0);
        app_open(A, V_QUEUE);
        run(600);
        shot("fix_queue_before");
        app_open(A, V_NOW);
        key(K_MENU, 0);
        key(K_SCROLL, 2);                              /* New queue from here */
        key(K_PLAY, 0);
        run(400);
        shot("fix_newqueue_note");
        app_open(A, V_QUEUE);
        run(600);
        shot("fix_queue_after");
        key(K_NEXT_LONG, 0);                           /* hold Next: dislike, skip */
        run(400);
        shot("fix_dislike_note");
        app_open(A, V_KEYS);
        run(600);
        shot("fix_keys");
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_KEYS")) {                        /* the shortcuts list and Menu on a queue song */
        char nm[64];
        run(1500);
        key(K_NEXT, 0); run(800);                       /* a queue of three: played, playing, to come */
        key(K_NEXT, 0); run(800);
        static const int skins[] = { 0, 1, 7 };
        for (int k = 0; k < 3; k++) {
            app_set_skin(A, skins[k]);
            app_open(A, V_MENU); run(400);
            key(K_MENU_LONG, 0); run(900);
            snprintf(nm, sizeof nm, "k_keys_s%d", skins[k]); shot(nm);
            key(K_BACK, 0); run(500);
            app_open(A, V_QUEUE); run(700);
            key(K_SCROLL, -1); key(K_MENU, 0); run(700);
            snprintf(nm, sizeof nm, "k_qrow_s%d", skins[k]); shot(nm);
            key(K_BACK, 0); run(400);
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_RING")) {                        /* 10-18: Diorama's Library and Settings, round in a circle */
        char nm[64];
        app_set_skin(A, 7);
        app_set_night(A, 0);
        run(1500);
        app_open(A, V_LIBRARY); run(900);
        printf("  library:");
        for (int k = 0; k < 7; k++) { printf(" %d", app_lib_sel(A)); key(K_SCROLL, 1); run(200); }
        printf("\n  library back:");
        for (int k = 0; k < 7; k++) { printf(" %d", app_lib_sel(A)); key(K_SCROLL, -1); run(200); }
        printf("\n");
        key(K_BACK, 0); run(900);
        app_open(A, V_SETTINGS); run(900);
        for (int k = 0; k < 9; k++) {
            snprintf(nm, sizeof nm, "ring_set%d", k); shot(nm);
            key(K_SCROLL, 1); run(300);
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_NOWP")) {                        /* 10-18: Diorama's monitor and Now playing, long titles */
        char nm[64];
        app_set_skin(A, 7);
        app_set_night(A, 0);
        run(1500);
        const char *ids = getenv("SHOTS_NOWP");        /* video ids, comma-separated */
        for (int k = 0; k < 6 && strlen(ids) >= 11 * (size_t)(k + 1) + (size_t)k; k++) {
            char id[12];
            memcpy(id, ids + 12 * k, 11);
            id[11] = 0;
            uint32_t idx = brain_find(id);
            if (idx >= brain_n()) { printf("  %s not in this pack\n", id); continue; }
            app_play(A, idx);
            app_open(A, V_MENU); run(1200);
            snprintf(nm, sizeof nm, "nowp%d_home", k); shot(nm);
            app_open(A, V_NOW); run(1500);
            snprintf(nm, sizeof nm, "nowp%d_now", k); shot(nm);
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_VIBE")) {                        /* 10-18: Diorama's wall in a calm, a middling, a driven song */
        char nm[64];
        app_set_skin(A, 7);
        app_set_night(A, 0);
        if (getenv("SHOTS_VIBE_DRAFT")) app_set_wall_style(A, atoi(getenv("SHOTS_VIBE_DRAFT")));
        if (getenv("SHOTS_PLAIN")) app_set_plain_scene(A, 1);
        run(1500);
        uint32_t pick[3] = { 0xFFFFFFFFu, 0xFFFFFFFFu, 0xFFFFFFFFu };
        static const int want_lo[3] = { 0, 120, 225 }, want_hi[3] = { 80, 160, 255 };
        const char *one = getenv("SHOTS_VIBE_ID");          /* these songs (video ids, comma-separated, up to 3) */
        for (int k = 0; one && k < 3 && strlen(one) >= 11 * (size_t)(k + 1) + (size_t)k; k++) {
            char id[12];
            memcpy(id, one + 12 * k, 11);
            id[11] = 0;
            pick[k] = brain_find(id);
        }
        /* SHOTS_VIBE_FRAMES / SHOTS_VIBE_STEP: frames per song and ms between them (a GIF) */
        int frames = getenv("SHOTS_VIBE_FRAMES") ? atoi(getenv("SHOTS_VIBE_FRAMES")) : 3;
        int step_ms = getenv("SHOTS_VIBE_STEP") ? atoi(getenv("SHOTS_VIBE_STEP")) : 333;
        for (uint32_t i = 0; !one && i < brain_n(); i += 7) {
            int e, b, r;
            if (!brain_vibe(i, &e, &b, &r) || e < 0 || r < 0) continue;
            for (int k = 0; k < 3; k++)
                if (pick[k] == 0xFFFFFFFFu && e >= want_lo[k] && e < want_hi[k] && (k != 0 || r <= 3) && (k != 2 || r >= 12)) pick[k] = i;
        }
        for (int k = 0; k < 3; k++) {
            if (pick[k] == 0xFFFFFFFFu) { if (!one) printf("  no song for vibe %d\n", k); continue; }
            int e, b, r;
            brain_vibe(pick[k], &e, &b, &r);
            printf("  vibe %d: track %u energy %d bpm %.1f rank %d\n", k, (unsigned)pick[k], e, b / 10.0, r);
            app_play(A, pick[k]);
            app_open(A, V_MENU);
            run(1500);
            for (int f = 0; f < frames; f++) {
                run(f ? (uint32_t)step_ms : 0);
                snprintf(nm, sizeof nm, "vibe%d_f%03d", k, f); shot(nm);
            }
        }
        app_set_night(A, 1);                           /* after dark, the lamp on, the last song */
        run(1500);
        shot("vibe_night");
        for (int f = 1; frames > 3 && f < frames; f++) {
            run((uint32_t)step_ms);
            snprintf(nm, sizeof nm, "vibe_night_f%03d", f); shot(nm);
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_LISTEN")) {                      /* 10-22: the Wheel = Listen again (songs and lists);
                                                          a song's radio laid out 25 ahead; a skip keeps it */
        run(1500);
        app_set_skin(A, 0);
        app_open(A, V_MENU); top(); run(400);
        key(K_PLAY, 0); run(900);                      /* the Wheel */
        for (int d = 0; d < 40; d++) {                 /* spin till a list tile is in front */
            const char *kind = NULL;
            int at = app_wheel_focus(A);
            if (at >= 0 && brain_wheel_list_name(app_wheel_item(A, at), &kind)) break;
            key(K_SCROLL, 1); run(250);
        }
        run(800);
        shot("la_list_tile");
        key(K_SCROLL, -100000); run(900);
        shot("la_wheel_top");
        key(K_PLAY, 0); run(2500);                     /* play the top song: its radio */
        app_open(A, V_QUEUE); run(700);
        shot("la_queue_planned");
        key(K_NEXT, 0); run(1500);                     /* skipped early: the queue stays, as on YT Music */
        app_open(A, V_QUEUE); run(700);
        shot("la_queue_after_skip");
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_SAVED")) {                       /* 10-18: Save queue, Saved queues, play one */
        char nm[64];
        run(1500);
        key(K_NEXT, 0); run(800);
        key(K_NEXT, 0); run(800);
        static const int skins[] = { 0, 1, 7 };
        for (int k = 0; k < 3; k++) {
            app_set_skin(A, skins[k]);
            app_open(A, V_QUEUE); run(700);
            key(K_MENU, 0); run(700);                  /* Menu on a song: Save queue at the foot */
            snprintf(nm, sizeof nm, "sq_sheet_s%d", skins[k]); shot(nm);
            key(K_BACK, 0); run(400);
            key(K_SCROLL, 1000); key(K_SCROLL, -1); run(700);   /* past the last song: Save queue */
            snprintf(nm, sizeof nm, "sq_strip_s%d", skins[k]); shot(nm);
            if (k == 0) { key(K_PLAY, 0); run(300); shot("sq_saved_note"); }
            key(K_SCROLL, 1); key(K_PLAY, 0); run(900);
            snprintf(nm, sizeof nm, "sq_list_s%d", skins[k]); shot(nm);
            key(K_PLAY, 0); run(900);
            snprintf(nm, sizeof nm, "sq_open_s%d", skins[k]); shot(nm);
            key(K_BACK, 0); key(K_BACK, 0); run(400);
        }
        app_set_skin(A, 0);
        app_open(A, V_QUEUE); run(500);
        key(K_SCROLL, 1000); key(K_SCROLL, 1); key(K_PLAY, 0); run(600);
        key(K_PLAY, 0); run(600);
        key(K_SCROLL, -100); key(K_SCROLL, 1); key(K_PLAY, 0); run(900);   /* Shuffle */
        app_open(A, V_QUEUE); run(700);
        shot("sq_shuffled_queue");
        app_open(A, V_SAVED); run(500);
        key(K_PLAY_LONG, 0); run(300); shot("sq_forget_ask");
        key(K_PLAY_LONG, 0); run(600); shot("sq_forget_done");
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_GAMES")) {                       /* Library > Games: both games, played by script */
        char nm[64];
        run(2000);
        static const int skins[] = { 0, 1, 7 };       /* Sakurai, Room, Diorama */
        for (int k = 0; k < 3; k++) {
            app_set_skin(A, skins[k]);
            app_open(A, V_MENU);
            run(400);
            app_open(A, V_LIBRARY);
            key(K_SCROLL, -100); key(K_SCROLL, 5);    /* Games: the sixth panel */
            run(900);
            snprintf(nm, sizeof nm, "g_library_s%d", skins[k]); shot(nm);
            key(K_PLAY, 0); run(900);
            snprintf(nm, sizeof nm, "g_games_s%d", skins[k]); shot(nm);
            key(K_SCROLL, 1); run(900);
            snprintf(nm, sizeof nm, "g_games_fish_s%d", skins[k]); shot(nm);
            key(K_BACK, 0); run(600);
            key(K_BACK, 0); run(600);
        }
        app_set_skin(A, 0);
        /* Beat Orbit: ready, then a run with the wheel turned now and then, until a ring gets you */
        app_open(A, V_LIBRARY);
        key(K_SCROLL, -100); key(K_SCROLL, 5); key(K_PLAY, 0); run(600);
        key(K_SCROLL, -10); key(K_PLAY, 0); run(600);   /* Beat Orbit */
        shot("g_orbit_ready");
        key(K_PLAY, 0);
        uint32_t seed = 7;
        for (int f = 0; f < 900; f++) {                /* 30 s at most, a frame every 33 ms */
            if (f % 9 == 0) {
                seed = seed * 1103515245u + 12345u;
                int d = (int)((seed >> 16) % 7) - 3;
                if (d) key(K_SCROLL, d);
                if ((seed >> 8) % 23 == 0) key(K_NEXT, 0);
            }
            run(33);
            if (f == 75 || f == 140 || f == 200) { snprintf(nm, sizeof nm, "g_orbit_run%03d", f); shot(nm); }
        }
        run(500);
        shot("g_orbit_end");
        key(K_PLAY, 0); run(1500);
        key(K_PLAY, 0); run(300);                       /* pause */
        shot("g_orbit_paused");
        key(K_BACK, 0); run(400);                       /* back to the games */
        /* the Fishing Hole: cast, then turn the wheel steadily: it hooks on the bite and reels */
        key(K_SCROLL, 1); key(K_PLAY, 0); run(900);
        shot("g_fish_idle");
        for (int cast = 0; cast < 4; cast++) {
            key(K_PLAY, 0);
            run(400);
            if (cast == 0) shot("g_fish_cast");
            int caught = 0;
            for (int f = 0; f < 300; f++) {            /* 45 s at most */
                key(K_SCROLL, 1);
                run(134);
                if (cast == 0 && (f == 60 || f == 75)) { snprintf(nm, sizeof nm, "g_fish_reel%03d", f); shot(nm); }
                (void)caught;
            }
            snprintf(nm, sizeof nm, "g_fish_end%d", cast); shot(nm);
            key(K_NEXT, 0); run(500);                   /* a catch: up next (else nothing happens) */
        }
        run(2000);
        snprintf(nm, sizeof nm, "g_fish_after"); shot(nm);
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_CLOCK")) {                       /* Diorama: inside the clock (the Wheel) */
        char nm[64];
        run(3000);
        app_set_skin(A, 7);
        plat_host_set_clock(16, 0);
        for (int pass = 0; pass < 3; pass++) {         /* dial by day, by night; the full wheel */
            app_set_night(A, pass == 1);
            app_set_wheel_layout(A, pass < 2);
            app_open(A, V_MENU); top(); run(600);
            key(K_PLAY, 0); run(1200);
            snprintf(nm, sizeof nm, "c_clock%d", pass); shot(nm);
            if (pass == 0) {
                key(K_SCROLL, 1);                      /* a detent: the gears go with it */
                for (int f = 0; f < 8; f++) {
                    plat_host_advance(33);
                    if (app_tick(A, plat_ms()) & NEED_FULL) app_draw(A, &G);
                    snprintf(nm, sizeof nm, "c_spin%02d", f); shot_raw(nm);
                }
                run(1000);
                plat_host_advance(1000); run(100);
                shot("c_clock0b");                     /* a second on: the rotor's other pole */
            }
            key(K_BACK, 0); run(600);
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_ORDER")) {                       /* the home's scroll path, item by item */
        char nm[64];
        run(2000);
        static const int skins[] = { 0, 1, 7 };
        for (int k = 0; k < 3; k++) {
            app_set_skin(A, skins[k]);
            app_set_night(A, 0);
            app_open(A, V_MENU);
            top();
            run(900);
            for (int i = 0; i < 8; i++) {
                snprintf(nm, sizeof nm, "o_s%d_%d", skins[k], i); shot(nm);
                key(K_SCROLL, 1); run(700);
            }
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_H2")) {                          /* Diorama: Settings, inside the H2 */
        char nm[64];
        run(3000);
        app_set_skin(A, 7);
        app_set_night(A, 0);
        plat_host_set_clock(16, 0);
        app_open(A, V_MENU); run(400);
        app_open(A, V_SETTINGS); run(1200);
        for (int i = 0; i < 8; i++) {
            snprintf(nm, sizeof nm, "h_part%d", i); shot(nm);
            key(K_SCROLL, 1); run(700);
        }
        app_set_night(A, 1); run(900);
        shot("h_night");
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_DIOI")) {                        /* Diorama: every thing on the desk, opened */
        char nm[64];
        run(3000);
        app_set_skin(A, 7);
        app_set_night(A, 0);
        plat_host_set_clock(16, 0);
        for (int i = 0; i < 8; i++) {
            app_open(A, V_MENU);
            top();
            key(K_SCROLL, i);
            run(900);
            key(K_PLAY, 0);
            run(1500);
            snprintf(nm, sizeof nm, "i_item%d", app_menu_item(A)); shot(nm);
            key(K_BACK, 0); run(800);
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_DIOP")) {                        /* Diorama's pages, the camera between them */
        char nm[64];
        run(3000);
        app_set_skin(A, 7);
        app_set_night(A, 0);
        plat_host_set_clock(16, 0);
        app_open(A, V_MENU);
        top();
        run(1500);
        shot("p_home");
        static const int CK[6][2] = { { 4, 0 }, { 7, 10 }, { 8, 35 }, { 10, 30 }, { 1, 50 }, { 12, 0 } };
        for (int i = 0; i < 6; i++) {                  /* the shelf clock, at times that are easy to misread */
            plat_host_set_clock(CK[i][0], CK[i][1]);
            run(1100);
            snprintf(nm, sizeof nm, "p_clock%d", i); shot(nm);
        }
        plat_host_set_clock(16, 0);
        key(K_SCROLL, 7);
        key(K_SCROLL, 1);                              /* past Settings: round to the Wheel */
        printf("    after Settings + 1: item %d\n", app_menu_sel(A));
        key(K_SCROLL, -1);
        printf("    and back: item %d\n", app_menu_sel(A));
        top();
        key(K_SCROLL, 5);                              /* the case */
        run(1200);
        shot("p_home_lib");
        key(K_PLAY, 0);                                /* in: the camera, frame by frame */
        for (int f = 0; f < 16; f++) {
            plat_host_advance(33);
            if (app_tick(A, plat_ms()) & NEED_FULL) app_draw(A, &G);
            snprintf(nm, sizeof nm, "p_zin%02d", f); shot_raw(nm);
        }
        run(1200);
        static const char *const PART[6] = { "songs", "artists", "genres", "osts", "history", "games" };
        for (int i = 0; i < 6; i++) {
            snprintf(nm, sizeof nm, "p_lib_%s", PART[i]); shot(nm);
            key(K_SCROLL, 1);
            run(600);
        }
        printf("    Library after 6 steps: part %d\n", app_lib_sel(A));
        for (int i = 0; i < 6; i++) {                  /* into each part, its page, back out */
            top(); key(K_SCROLL, i); run(600);
            key(K_PLAY, 0);
            for (int f = 0; f < 16; f++) {
                plat_host_advance(33);
                if (app_tick(A, plat_ms()) & NEED_FULL) app_draw(A, &G);
                if (i == 0 || i == 3) { snprintf(nm, sizeof nm, "p_z%s%02d", PART[i], f); shot_raw(nm); }
            }
            run(1200);
            snprintf(nm, sizeof nm, "p_%s", PART[i]); shot(nm);
            key(K_SCROLL, 2);
            run(400);
            snprintf(nm, sizeof nm, "p_%s_down", PART[i]); shot(nm);
            key(K_BACK, 0);
            for (int f = 0; f < 16; f++) {
                plat_host_advance(33);
                if (app_tick(A, plat_ms()) & NEED_FULL) app_draw(A, &G);
                if (i == 0) { snprintf(nm, sizeof nm, "p_zout%02d", f); shot_raw(nm); }
            }
            run(800);
        }
        key(K_BACK, 0);                                /* out to the desk */
        for (int f = 0; f < 16; f++) {
            plat_host_advance(33);
            if (app_tick(A, plat_ms()) & NEED_FULL) app_draw(A, &G);
            snprintf(nm, sizeof nm, "p_zhome%02d", f); shot_raw(nm);
        }
        run(1500);
        top(); key(K_SCROLL, 4); run(800);             /* the keyboard: Search */
        key(K_PLAY, 0);
        for (int f = 0; f < 16; f++) {
            plat_host_advance(33);
            if (app_tick(A, plat_ms()) & NEED_FULL) app_draw(A, &G);
            snprintf(nm, sizeof nm, "p_zsearch%02d", f); shot_raw(nm);
        }
        run(800);
        shot("p_search");
        const char *word = "toby";
        for (const char *c = word; *c; c++) {
            int target = *c - 'a';
            key(K_SCROLL, target);
            key(K_PLAY, 0);
            key(K_SCROLL, -target);
        }
        run(400);
        shot("p_search_typed");
        key(K_PLAY_LONG, 0);
        run(400);
        shot("p_search_results");
        key(K_BACK, 0); key(K_BACK, 0); key(K_BACK, 0); key(K_BACK, 0); key(K_BACK, 0); key(K_BACK, 0);
        run(1500);
        top(); key(K_SCROLL, 3); run(800);             /* the posters: Explore */
        key(K_PLAY, 0);
        run(1200);
        shot("p_explore");
        key(K_SCROLL, 1); run(500);
        shot("p_explore2");
        key(K_BACK, 0); run(1500);
        top(); key(K_SCROLL, 2); run(800);             /* the headphones: the Queue */
        key(K_PLAY, 0);
        for (int f = 0; f < 16; f++) {
            plat_host_advance(33);
            if (app_tick(A, plat_ms()) & NEED_FULL) app_draw(A, &G);
            snprintf(nm, sizeof nm, "p_zqueue%02d", f); shot_raw(nm);
        }
        run(1200);
        shot("p_queue");
        key(K_BACK, 0); run(1500);
        top(); key(K_SCROLL, 6); run(800);             /* the pothos: Liked */
        key(K_PLAY, 0); run(1200);
        shot("p_liked");
        key(K_BACK, 0); run(1500);
        top(); key(K_SCROLL, 7); run(800);             /* the H2: Settings */
        key(K_PLAY, 0); run(1200);
        shot("p_settings");
        key(K_PLAY, 0); run(1200);
        shot("p_settings_group");
        key(K_BACK, 0); key(K_BACK, 0); run(1500);
        app_set_night(A, 1);                           /* after dark */
        top(); key(K_SCROLL, 5); run(800);
        key(K_PLAY, 0); run(1500);
        top(); run(600);
        shot("p_lib_night");
        key(K_PLAY, 0); run(1500);
        shot("p_songs_night");
        key(K_BACK, 0); key(K_BACK, 0); run(1500);
        top(); key(K_SCROLL, 4); run(800);
        key(K_PLAY, 0); run(1500);
        shot("p_search_night");
        key(K_BACK, 0); run(1500);
        shot("p_home_night");
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_DIOB")) {                        /* Bubloo on the case: the case's tag; the door's end vs. the home */
        char nm[64], msg[96];
        run(3000);
        app_set_skin(A, 7);
        app_set_night(A, 0);
        app_open(A, V_MENU);
        top();
        key(K_SCROLL, 5);                              /* the case */
        int found = 0;
        for (int m = 7 * 60; m < 23 * 60 && found < 3; m += 7) {
            plat_host_set_clock(m / 60, m % 60);
            run(10000);                                /* past the 9 s: the line says what he's doing */
            app_pet_status(A, msg, sizeof msg);
            if (!strstr(msg, "case")) continue;
            printf("    %02d:%02d %s\n", m / 60, m % 60, msg);
            snprintf(nm, sizeof nm, "b_case%d", found); shot(nm);
            for (int i = 0; i < 3; i++) {              /* the door's last frames, then the home they cut to */
                app_boot_draw(7, &G, 1450 + 100 * i);
                snprintf(nm, sizeof nm, "b_case%d_door%d", found, i); shot_raw(nm);
            }
            key(K_PLAY, 0); run(1500);                 /* the case opened up, him on top */
            snprintf(nm, sizeof nm, "b_case%d_pc", found); shot(nm);
            key(K_BACK, 0); run(1500);
            found++;
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_PREV")) {                        /* 10-19: Prev past 5 s starts the song over; again, the one before */
        app_open(A, V_ARTISTS);
        key(K_SCROLL, 300);                            /* one with a few songs */
        run(600);
        key(K_PLAY, 0);                                /* an artist: Play all / Shuffle over the songs */
        run(600);
        shot("artist_page");
        key(K_SCROLL, 3);                              /* past the buttons to the second song: play on from it */
        key(K_PLAY, 0);
        run(8000);
        pstate("8 s in");
        key(K_PREV, 0);
        run(300);
        pstate("Prev");
        key(K_PREV, 0);
        run(300);
        pstate("Prev again");
        app_open(A, V_ARTISTS);
        key(K_SCROLL, 300);
        run(300);
        key(K_PLAY, 0);
        run(300);
        key(K_SCROLL, 1);                              /* the Shuffle button */
        key(K_PLAY, 0);
        run(600);
        pstate("Shuffle");
        key(K_NEXT, 0);
        run(8000);
        pstate("Next, 8 s in");
        key(K_PREV, 0);
        run(300);
        pstate("Prev: from the start");
        key(K_PREV, 0);
        run(300);
        pstate("Prev again: the one before");
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_RACK")) {                        /* 10-19: Diorama's Bluetooth board, left of the monitor */
        static const uint8_t kef[6] = { 0x04, 0x52, 0xc7, 0x77, 0x88, 0x99 };
        app_set_skin(A, 7);
        app_set_night(A, 0);
        run(1500);
        app_open(A, V_MENU);
        top();
        run(1200);
        shot("rack_off");                              /* the radio off: the one paired, greyed */
        key(K_SCROLL, -1);                             /* back from the clock: the board's top card */
        run(900);
        shot("rack_off_pick");
        key(K_PLAY, 0);                                /* on, then connect it */
        run(1700);
        shot("rack_starting");
        run(2600);
        shot("rack_buds");
        plat_bt_connect(kef);                          /* a second one, paired from Bluetooth */
        run(2600);
        top();
        run(900);
        shot("rack_two");
        key(K_SCROLL, -1);
        run(900);
        shot("rack_two_pick_top");
        key(K_SCROLL, -1);
        run(900);
        shot("rack_two_pick_bottom");
        app_set_night(A, 1);
        run(900);
        shot("rack_night");
        app_set_night(A, 0);
        key(K_PLAY_LONG, 0);                           /* hold: the Bluetooth page */
        run(600);
        shot("rack_hold");
        printf("ok -> %s\n", out_dir);
        return 0;
    }
    if (getenv("SHOTS_BUDS")) {                        /* Galaxy Buds on: their battery, their volume */
        static const uint8_t buds[6] = { 0x38, 0x18, 0x4c, 0x11, 0x22, 0x33 };
        run(3000);
        plat_bt_power(1);
        run(1600);
        plat_bt_connect(buds);
        run(2600);
        static const int SK[4] = { 0, 7, 1, 2 };
        char nm[64];
        for (int i = 0; i < 4; i++) {
            app_set_skin(A, SK[i]);
            app_set_night(A, 0);
            app_open(A, V_MENU);
            top();
            run(3000);                                 /* past the "Volume" notice */
            snprintf(nm, sizeof nm, "buds_home_t%d", SK[i]); shot(nm);
        }
        app_set_skin(A, 0);
        app_open(A, V_SETTINGS);
        top();
        key(K_SCROLL, 6);
        key(K_PLAY, 0);
        run(600);
        shot("buds_bt_list");
        plat_bt_volume_step(1);                        /* as a volume key would */
        run(300);
        shot("buds_volume");
        run(3000);                                     /* past the "Volume" notice */
        key(K_SCROLL, 1);                              /* the sound quality, under the switch */
        run(300);
        shot("buds_quality");
        key(K_PLAY, 0);
        run(300);
        shot("buds_quality_high");
        return 0;
    }

    if (getenv("SHOTS_DIO")) {                         /* just Diorama: day, night, Bubloo's day */
        static uint16_t from[LCD_W * LCD_H];
        char nm[64], msg[96];
        run(3000);
        app_set_skin(A, 7);
        app_set_night(A, 0);
        app_open(A, V_MENU);
        top();
        static const int HM[10][2] = { { 3, 0 }, { 7, 10 }, { 8, 35 }, { 10, 30 }, { 13, 0 }, { 16, 20 },
                                       { 18, 55 }, { 20, 40 }, { 21, 30 }, { 23, 40 } };
        for (int i = 0; i < 10; i++) {                 /* his day, the room by the clock */
            app_set_night(A, -1);
            plat_host_set_clock(HM[i][0], HM[i][1]);
            run(10000);
            float left = app_pet_status(A, msg, sizeof msg);
            snprintf(nm, sizeof nm, "d_%02d%02d", HM[i][0], HM[i][1]); shot(nm);
            printf("    %02d:%02d %s (%.0f s more)\n", HM[i][0], HM[i][1], msg, left);
        }
        app_set_night(A, 0);
        plat_host_set_clock(10, 30);
        for (int i = 0; i < 8; i++) {                  /* each thing picked, by day */
            key(K_SCROLL, i ? 1 : 0);
            run(900);
            snprintf(nm, sizeof nm, "d_pick%d", i); shot(nm);
        }
        app_set_night(A, 1);
        run(600);
        shot("d_night");
        top();
        run(12000);
        shot("d_night_idle");
        app_open(A, V_NOW);
        run(900);
        shot("d_now_night");
        app_set_night(A, 0);
        run(900);
        shot("d_now_day");
        app_open(A, V_LIBRARY);
        app_set_night(A, 1);
        run(900);
        shot("d_lib_night");
        app_open(A, V_MENU);
        app_set_night(A, -1);
        plat_host_set_clock(17, 0);
        run(12000);
        for (int k = 0; k < 6; k++) {                  /* him moving on: the end of six episodes, live */
            float left = app_pet_status(A, msg, sizeof msg);
            printf("    episode %d: %s, %.1f s more\n", k, msg, left);
            run((uint32_t)(left * 1000) - 400 > 0 ? (uint32_t)(left * 1000) - 400 : 0);
            for (int f = 0; f < 72; f++) {
                int r[4];
                plat_host_advance(83);
                int need = app_tick(A, plat_ms());
                if (need & NEED_FULL) app_draw(A, &G); else app_draw_hub(A, &G, r);
                snprintf(nm, sizeof nm, "d_mv%d_%02d", k, f); shot_raw(nm);
            }
            app_pet_status(A, msg, sizeof msg);
            printf("      -> %s\n", msg);
        }
        for (int i = 0; i <= 48; i++) {
            app_boot_draw(7, &G, (uint32_t)i * 33);
            snprintf(nm, sizeof nm, "d_boot%02d", i); shot_raw(nm);
        }
        app_draw(A, &G);
        memcpy(from, fb, sizeof from);
        for (int i = 0; i <= 27; i++) {
            app_draw_off(A, &G, (uint32_t)i * 33, from, 0);
            snprintf(nm, sizeof nm, "d_off%02d", i); shot_raw(nm);
        }
        printf("ok -> %s\n", out_dir);
        return 0;
    }
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
        app_set_night(A, 1);                           /* after dark */
        app_open(A, V_MENU);
        run(900);
        shot("r_home_night");
        app_open(A, V_QUEUE);
        run(700);
        shot("r_queue_night");
        app_open(A, V_SETTINGS);
        run(700);
        shot("r_settings_night");
        app_open(A, V_EXPLORE);
        run(700);
        shot("r_explore_night");
        app_open(A, V_WHEEL);
        run(900);
        shot("r_wheel_night");
        app_open(A, V_NOW);
        run(700);
        shot("r_now_night");
        key(K_MENU, 0);
        run(700);
        shot("r_sheet_night");
        key(K_BACK, 0);
        app_set_night(A, 0);
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
