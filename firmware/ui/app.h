/* Coda, the app: views, navigation, autoplay loop. Platform-free; driven by
 * app_event (buttons + wheel), app_tick (time) and app_draw (one full frame). */
#ifndef CODA_APP_H
#define CODA_APP_H

#include <stdint.h>
#include "gfx.h"

typedef enum {
    K_NONE,
    K_SCROLL,          /* d = +/- detents (clockwise +) */
    K_PLAY, K_PLAY_LONG,
    K_BACK, K_MENU, K_MENU_LONG,
    K_PREV, K_NEXT, K_PREV_LONG, K_NEXT_LONG,
} key_kind;

typedef struct { key_kind k; int d; } ui_ev;

enum {
    V_MENU, V_WHEEL, V_NOW, V_LIBRARY, V_ARTISTS, V_TRACKS, V_EXPLORE, V_SEARCH,
    V_OST, V_GENRES, V_QUEUE, V_SETTINGS, V_CLOCK, V_BT, V_COUNT
};

typedef struct app app;

app *app_create(const char *pack_dir, const char *plays_path);
void app_event(app *a, ui_ev e);
/* advance time; returns what needs redrawing (NEED_*). Nothing changes on screen ->
 * NEED_NONE, so the platform can sleep instead of rendering (battery). */
enum { NEED_NONE = 0, NEED_FULL = 1, NEED_HUB = 2 };
int app_tick(app *a, uint32_t now_ms);
void app_draw(app *a, gfx *g);
/* visualizer-only refresh of the wheel hub; rect = x, y, w, h that changed */
void app_draw_hub(app *a, gfx *g, int rect[4]);
/* how soon the app next wants a tick: short while animating, long when idle */
int app_interval_ms(app *a);
/* keep autoplaying after the UI closes (Settings > Keep playing) */
int app_background_autoplay(app *a);
/* autoplay housekeeping without the UI (the plugin's background thread) */
void app_autoplay_step(app *a);
void app_force_redraw(app *a);
/* the player picked up a queue after start-up (Coda OS resumes once the card is indexed) */
void app_adopt_queue(app *a);
/* a short line in the bottom strip (the platform's volume keys, ...) */
void app_say(app *a, const char *msg);
/* Coda OS: what the screen shows while a computer has the card (USB mass storage) */
void app_draw_usb(app *a, gfx *g);
/* Coda OS power-off ("your crate"), t = 0..BOOT_OFF_MS from the screen as it was;
 * why: 0 switched off, 1 battery low, 2 battery empty (a still) */
void app_draw_off(app *a, gfx *g, uint32_t t, const px16 *from, int why);
/* power-on: the saved theme's animation, t = 0..BOOT_MS (no app needed: it plays while the
 * library loads) */
int app_saved_skin(void);
void app_boot_draw(int skin, gfx *g, uint32_t t);

/* for the host screenshot runner */
void app_open(app *a, int view);
void app_set_wheel_layout(app *a, int b);
void app_set_night(app *a, int night);   /* -1 = auto by clock */
void app_set_skin(app *a, int skin);     /* the theme (Settings > Theme) */

#endif
