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
    K_POWER,           /* the power button pressed (held is Rockbox's power-off) */
    K_BACK_LONG,
    K_HOLD_SCROLL,     /* the wheel turned while Prev or Next is held: d detents */
} key_kind;

typedef struct { key_kind k; int d; } ui_ev;

enum {
    V_MENU, V_WHEEL, V_NOW, V_LIBRARY, V_ARTISTS, V_TRACKS, V_EXPLORE, V_SEARCH,
    V_OST, V_GENRES, V_QUEUE, V_SETTINGS, V_CLOCK, V_BT, V_GAMES, V_GAME, V_KEYS, V_SAVED, V_COUNT
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
int app_resume_saved(app *a);      /* the queue saved at power-off, paused where it was; 1 if so */
void app_save_queue(app *a);
int app_chords_ok(const app *a);   /* hold Prev/Next + wheel means brightness here (not in a game) */
int app_charge_mode(const app *a); /* the charge screen is up (the charger switched the player on) */
/* a short line in the bottom strip (the platform's volume keys, ...) */
void app_say(app *a, const char *msg);
/* Coda OS: what the screen shows while a computer has the card (USB mass storage) */
void app_draw_usb(app *a, gfx *g);
/* Coda OS power-off ("your crate"), t = 0..BOOT_OFF_MS from the screen as it was;
 * why: 0 switched off, 1 battery low, 2 battery empty (a still) */
void app_draw_off(app *a, gfx *g, uint32_t t, const px16 *from, int why);
/* power-on: the saved theme's animation, t = 0..BOOT_MS (no app needed: it plays while the
 * library loads); app_saved_skin() is -1 while /.coda/settings.txt can't be read */
int app_saved_skin(void);
/* Bubloo in the Diorama: what he's doing, in a line; returns the seconds until he moves on */
float app_pet_status(app *a, char *out, int n);
/* where the home's and the Library's focus is (for the shots) */
int app_menu_sel(app *a);
int app_menu_item(app *a);         /* the home's focused item (its scroll order is the theme's) */
int app_lib_sel(app *a);
void app_boot_draw(int skin, gfx *g, uint32_t t);

/* for the host screenshot runner */
void app_open(app *a, int view);
void app_play(app *a, uint32_t idx);      /* that song now, autoplay after it */
void app_set_wall_style(app *a, int s);   /* Diorama's wall drafts, 0..5 (th_dio.h) */
void app_set_plain_scene(app *a, int on); /* preview renders: Diorama without its figures and prints */
void app_set_wheel_layout(app *a, int b);
/* the Wheel's slot in front (-1: empty) and its item (brain_wheel's: a song or a list) */
int app_wheel_focus(app *a);
uint32_t app_wheel_item(app *a, int i);
void app_set_night(app *a, int night);   /* -1 = auto by clock */
void app_set_skin(app *a, int skin);     /* the theme (Settings > Theme) */
int app_skin(const app *a);

#endif
