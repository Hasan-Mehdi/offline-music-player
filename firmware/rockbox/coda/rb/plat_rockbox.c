/* Coda as a Rockbox plugin: plat.h on top of the rb-> API + the plugin's main loop.
 * Rockbox keeps doing the hard parts (decoding, gapless, ReplayGain, buffering); we
 * drive its playlist and draw every frame ourselves. */
#include "plugin.h"
#include <tlsf.h>

#include "../plat/plat.h"
#include "../ui/app.h"
#include "../ui/brain.h"
#include "../ui/gfx.h"
#include "omp_pack.h"

#define CODA_DIR "/.coda"
#define MUSIC_ROOT "/Music/"
#define LONG_MS 550

static fb_data fb[LCD_W * LCD_H];

/* ------------------------------------------------------------------ time, log, memory */
uint32_t plat_ms(void) { return (uint32_t)(*rb->current_tick) * (1000 / HZ); }

int64_t plat_now(void) { return (int64_t)rb->mktime(rb->get_time()); }

void plat_clock(int *h, int *m)
{
    struct tm *t = rb->get_time();
    *h = t->tm_hour;
    *m = t->tm_min;
}

int plat_battery(void) { return rb->battery_level(); }

void plat_log(const char *fmt, ...)
{
    char buf[200];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof buf - 1, fmt, ap);
    va_end(ap);
    if (n < 0) return;
    if (n > (int)sizeof buf - 2) n = sizeof buf - 2;
    buf[n++] = '\n';
    int fd = rb->open(CODA_DIR "/coda.log", O_WRONLY | O_CREAT | O_APPEND, 0666);
    if (fd >= 0) { rb->write(fd, buf, n); rb->close(fd); }
}

void *plat_alloc(size_t n)
{
    void *p = tlsf_malloc(n ? n : 1);
    if (!p) { plat_log("out of memory: %u bytes", (unsigned)n); return NULL; }
    rb->memset(p, 0, n);
    return p;
}

static void full_path(const char *rel, char *out, size_t n)
{
    snprintf(out, n, CODA_DIR "/%s", rel);
}

void *plat_load(const char *rel, size_t *len)
{
    char path[MAX_PATH];
    full_path(rel, path, sizeof path);
    int fd = rb->open(path, O_RDONLY);
    if (fd < 0) return NULL;
    off_t size = rb->lseek(fd, 0, SEEK_END);
    rb->lseek(fd, 0, SEEK_SET);
    char *b = plat_alloc((size_t)size + 1);
    if (!b || rb->read(fd, b, size) != size) { rb->close(fd); return NULL; }
    rb->close(fd);
    if (len) *len = (size_t)size;
    return b;
}

int plat_open(const char *rel)
{
    char path[MAX_PATH];
    full_path(rel, path, sizeof path);
    return rb->open(path, O_RDONLY);
}

int plat_pread(int fd, void *buf, int n, uint32_t off)
{
    if (rb->lseek(fd, (off_t)off, SEEK_SET) < 0) return -1;
    return (int)rb->read(fd, buf, n);
}

void plat_close(int fd) { if (fd >= 0) rb->close(fd); }

int plat_save(const char *rel, const void *data, size_t len)
{
    char path[MAX_PATH];
    full_path(rel, path, sizeof path);
    int fd = rb->open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) return -1;
    ssize_t w = rb->write(fd, data, len);
    rb->close(fd);
    return w == (ssize_t)len ? 0 : -1;
}

/* ------------------------------------------------------------------ player */
static const omp_pack *pack(void) { return (const omp_pack *)brain_pack(); }

static void track_path(uint32_t idx, char *out, size_t n)
{
    const omp_track *t = omp_pack_track(pack(), idx);
    uint32_t off = t->file_off;
    snprintf(out, n, MUSIC_ROOT "%s", omp_pack_str(pack(), off));
}

/* path -> pack index: remember what we queued, else the [video_id] in the file name */
#define KNOWN 8
static struct { uint32_t idx; char path[MAX_PATH]; } known[KNOWN];
static int known_next;
static char last_path[MAX_PATH];
static uint32_t last_idx = 0xFFFFFFFFu;

static void remember(uint32_t idx, const char *path)
{
    known[known_next].idx = idx;
    rb->strlcpy(known[known_next].path, path, MAX_PATH);
    known_next = (known_next + 1) % KNOWN;
}

static uint32_t idx_of_path(const char *path)
{
    if (!strcmp(path, last_path)) return last_idx;
    uint32_t idx = 0xFFFFFFFFu;
    for (int i = 0; i < KNOWN; i++)
        if (known[i].path[0] && !strcmp(known[i].path, path)) { idx = known[i].idx; break; }
    if (idx == 0xFFFFFFFFu) {
        const char *lb = rb->strrchr(path, '[');
        if (lb && strlen(lb) >= 13 && lb[12] == ']') {
            char vid[12];
            rb->memcpy(vid, lb + 1, 11);
            vid[11] = 0;
            idx = omp_pack_find_id(pack(), vid);
        }
    }
    rb->strlcpy(last_path, path, MAX_PATH);
    last_idx = idx;
    return idx;
}

void plat_player(plat_play *st)
{
    int s = rb->audio_status();
    struct mp3entry *id3 = (s & AUDIO_STATUS_PLAY) ? rb->audio_current_track() : NULL;
    st->active = id3 != NULL;
    st->playing = st->active && !(s & AUDIO_STATUS_PAUSE);
    st->idx = 0;
    st->pos = -1;
    st->elapsed_ms = st->length_ms = 0;
    if (!id3) return;
    uint32_t idx = idx_of_path(id3->path);
    if (idx == 0xFFFFFFFFu) { st->active = 0; return; }     /* not one of ours */
    st->idx = idx;
    st->pos = rb->playlist_amount() > 0 ? rb->playlist_get_display_index() - 1 : -1;
    st->elapsed_ms = id3->elapsed;
    st->length_ms = id3->length;
}

void plat_play_tracks(const uint32_t *idx, int n, int start, uint32_t start_ms)
{
    char path[MAX_PATH];
    if (n <= 0 || rb->playlist_create(NULL, NULL) != 0) return;
    for (int i = 0; i < n; i++) {
        track_path(idx[i], path, sizeof path);
        remember(idx[i], path);
        if (rb->playlist_insert_track(NULL, path, PLAYLIST_INSERT_LAST, false, false) < 0)
            plat_log("insert failed: %s", path);
        if ((i & 15) == 15) rb->yield();
    }
    rb->playlist_sync(NULL);
    rb->playlist_start(start, start_ms, 0);
}

void plat_queue_add(uint32_t idx, int next)
{
    char path[MAX_PATH];
    track_path(idx, path, sizeof path);
    remember(idx, path);
    int amount = rb->playlist_amount(), cur = rb->playlist_get_display_index() - 1;
    if (rb->playlist_insert_track(NULL, path, next ? PLAYLIST_INSERT_FIRST : PLAYLIST_INSERT_LAST,
                                  false, true) < 0) {
        plat_log("queue failed: %s", path);
        return;
    }
    /* the player may already have buffered what came next (or decided nothing does) */
    if (next || cur >= amount - 1) rb->audio_flush_and_reload_tracks();
}

int plat_queue_remove(int pos)
{
#ifdef CODA_OS
    if (playlist_delete(NULL, pos) < 0) return -1;
    return 0;
#else
    (void)pos;
    return -1;                  /* not in the plugin API */
#endif
}

int plat_queue_read(uint32_t *idx, int cap, int *pos)
{
    int n = rb->playlist_amount();
    *pos = -1;
    if (n <= 0 || n > cap || !(rb->audio_status() & AUDIO_STATUS_PLAY)) return 0;
    struct playlist_track_info info;
    for (int i = 0; i < n; i++) {
        if (rb->playlist_get_track_info(NULL, i, &info) < 0) return 0;
        uint32_t t = idx_of_path(info.filename);
        if (t == 0xFFFFFFFFu) return 0;          /* someone else's playlist: start fresh */
        idx[i] = t;
        if ((i & 15) == 15) rb->yield();
    }
    *pos = rb->playlist_get_display_index() - 1;
    return n;
}

void plat_jump(int pos)
{
    if (pos < 0 || pos >= rb->playlist_amount()) return;
    rb->playlist_start(pos, 0, 0);
}

void plat_stop(void) { rb->audio_stop(); }

void plat_toggle(void)
{
    int s = rb->audio_status();
    if (!(s & AUDIO_STATUS_PLAY)) return;
    if (s & AUDIO_STATUS_PAUSE) rb->audio_resume();
    else rb->audio_pause();
}

void plat_skip(int dir)
{
    if (!(rb->audio_status() & AUDIO_STATUS_PLAY)) return;
    if (dir > 0) rb->audio_next();
    else rb->audio_prev();
}

void plat_seek(uint32_t p)
{
    if (!(rb->audio_status() & AUDIO_STATUS_PLAY)) return;
    struct mp3entry *id3 = rb->audio_current_track();
    if (!id3) return;
    if (id3->length && p + 1000 > id3->length) p = id3->length > 1000 ? id3->length - 1000 : 0;
    rb->audio_ff_rewind((long)p);
}

void plat_beep(int hz, int ms, int amp) { rb->beep_play(hz, ms, amp); }

/* 12 log-spaced Goertzel bands over the PCM chunk being played (integer only) */
#define GZ_N 256
static int32_t gz_coef[12];

static void spectrum_init(void)
{
    static const int freqs[12] = { 60, 100, 160, 250, 400, 630, 1000, 1600, 2500, 4000, 6300, 10000 };
    for (int i = 0; i < 12; i++)
        gz_coef[i] = (int32_t)(2.0 * cos(2.0 * 3.14159265358979 * freqs[i] / 44100.0) * 16384.0);
}

int plat_spectrum(uint8_t bands[12])
{
    if ((rb->audio_status() & (AUDIO_STATUS_PLAY | AUDIO_STATUS_PAUSE)) != AUDIO_STATUS_PLAY) return 0;
    int count = 0;
    const int16_t *pcm = rb->mixer_channel_get_buffer(PCM_MIXER_CHAN_PLAYBACK, &count);
    if (!pcm || count < GZ_N) return 0;
    for (int b = 0; b < 12; b++) {
        int32_t s1 = 0, s2 = 0;
        for (int i = 0; i < GZ_N; i++) {
            int32_t x = (pcm[2 * i] + pcm[2 * i + 1]) >> 4;
            int32_t s0 = x + (int32_t)(((int64_t)gz_coef[b] * s1) >> 14) - s2;
            s2 = s1;
            s1 = s0;
        }
        int64_t p = (int64_t)s1 * s1 + (int64_t)s2 * s2 - (((int64_t)gz_coef[b] * s1 >> 14) * s2);
        int lv = 0;                              /* ~3dB steps on a log scale */
        while (p > 1 && lv < 64) { p >>= 1; lv++; }
        int v = (lv - 24) * 11;
        bands[b] = (uint8_t)(v < 0 ? 0 : v > 255 ? 255 : v);
    }
    return 1;
}

/* ------------------------------------------------------------------ background mode
 * Leaving Coda (hold M) keeps autoplay going: the plugin stays resident (TSR), a small
 * thread with its own stack wakes on each track change and queues the brain's next pick.
 * No drawing at all, so it costs about nothing on top of normal playback. Reopening Coda
 * (or opening another plugin) stops the thread and lets Rockbox unload us; another plugin
 * gets us restarted in background mode afterwards (parameter == rb->plugin_tsr). */
#define EV_TRACK 1
#define EV_QUIT 2
static struct {
    struct event_queue q;
    long stack[16 * 1024 / sizeof(long)];
    unsigned int id;
    bool running, in_usb;
} bg;
static app *A;

static void bg_track_cb(unsigned short id, void *data)
{
    (void)id; (void)data;
    if (bg.running) rb->queue_post(&bg.q, EV_TRACK, 0);
}

static void bg_thread(void)
{
    struct queue_event ev;
    for (;;) {
        rb->queue_wait_w_tmo(&bg.q, &ev, HZ * 2);     /* poll too: completion % for the log */
        if (ev.id == EV_QUIT) return;
        if (ev.id == SYS_USB_CONNECTED) {
            /* files go away under USB mass storage; reopen Coda afterwards to resume */
            rb->usb_acknowledge(SYS_USB_CONNECTED_ACK, ev.data);
            bg.in_usb = true;
            continue;
        }
        if (ev.id == SYS_USB_DISCONNECTED) { bg.in_usb = false; continue; }
        if (bg.in_usb) continue;
        if (ev.id == EV_TRACK) rb->sleep(HZ / 10);    /* let the new track's id3 settle */
        app_autoplay_step(A);
    }
}

static void bg_start(void)
{
    rb->queue_init(&bg.q, true);
    bg.running = true;
    bg.id = rb->create_thread(bg_thread, bg.stack, sizeof(bg.stack), 0, "coda autoplay"
                              IF_PRIO(, PRIORITY_BACKGROUND) IF_COP(, CPU));
    rb->add_event(PLAYBACK_EVENT_TRACK_CHANGE, bg_track_cb);
}

static void bg_stop(void)
{
    if (!bg.running) return;
    rb->remove_event(PLAYBACK_EVENT_TRACK_CHANGE, bg_track_cb);
    rb->queue_post(&bg.q, EV_QUIT, 0);
    rb->thread_wait(bg.id);
    rb->queue_delete(&bg.q);
    bg.running = false;
}

#ifndef CODA_OS
static int exit_tsr(bool reenter)
{
    (void)reenter;          /* reopening Coda: unload us and load a fresh UI instance */
    bg_stop();
    return PLUGIN_TSR_SUSPEND;
}

static void go_background(void)
{
    rb->plugin_tsr(exit_tsr);
    bg_start();
}
#endif

/* ------------------------------------------------------------------ the UI loop
 * Shared by the plugin and by Coda OS (where it runs in its own thread). */
enum { LOOP_EXIT, LOOP_USB, LOOP_ESCAPE };
static int press_btn;
static bool dbg_buttons = false;  /* set true to log raw button codes to /.coda/coda.log */
static long press_tick, combo_tick;
static bool long_fired;
#define ESCAPE_MS 1500            /* Coda OS: hold Menu + Back this long -> Rockbox's menus */

static key_kind short_of(int b)
{
    switch (b) {
    case BUTTON_PLAY: return K_PLAY;
    case BUTTON_MENU: return K_MENU;
    case BUTTON_BACK: return K_BACK;
    case BUTTON_PREV: return K_PREV;
    case BUTTON_NEXT: return K_NEXT;
    default: return K_NONE;
    }
}

static key_kind long_of(int b)
{
    switch (b) {
    case BUTTON_PLAY: return K_PLAY_LONG;
    case BUTTON_MENU: return K_MENU_LONG;
    case BUTTON_PREV: return K_PREV_LONG;
    case BUTTON_NEXT: return K_NEXT_LONG;
    default: return K_NONE;
    }
}

static void push_full(void)
{
    rb->lcd_bitmap(fb, 0, 0, LCD_W, LCD_H);
    rb->lcd_update();
}

static int ui_loop(void)
{
    gfx g;
    g_init(&g, (px16 *)fb, LCD_W, LCD_H, LCD_W);
    rb->lcd_set_viewport(NULL);
    bool dark = false;
    app_force_redraw(A);
    press_btn = 0;
    combo_tick = 0;

    for (;;) {
        /* sleep until the next button or until the app next has something to show:
         * 16ms while the wheel moves, 50ms for the visualizer, 0.5s idle, 1s screen off */
        int ms = dark ? 1000 : app_interval_ms(A);
        int ticks = ms * HZ / 1000;
        long btn = rb->button_get_w_tmo(ticks > 0 ? ticks : 1);
        if (btn != BUTTON_NONE) {
            int base = (int)(btn & ~(BUTTON_REL | BUTTON_REPEAT));
            if (dbg_buttons) plat_log("btn %08lx t=%ld", btn, *rb->current_tick);
            ui_ev e = { K_NONE, 0 };
            if (base == (BUTTON_MENU | BUTTON_BACK)) {
#ifdef CODA_OS
                /* the hidden way out: both held -> Rockbox's own menus */
                if (!(btn & BUTTON_REL)) {
                    if (!combo_tick) combo_tick = *rb->current_tick;
                    else if ((*rb->current_tick - combo_tick) * (1000 / HZ) >= ESCAPE_MS) {
                        combo_tick = 0;
                        return LOOP_ESCAPE;
                    }
                } else combo_tick = 0;
#endif
                press_btn = -1;                      /* swallow the combo's releases */
            } else if (base & (BUTTON_SCROLL_FWD | BUTTON_SCROLL_BACK)) {
                if (!(btn & BUTTON_REL)) { e.k = K_SCROLL; e.d = (base & BUTTON_SCROLL_FWD) ? 1 : -1; }
            } else if (base == BUTTON_VOL_UP || base == BUTTON_VOL_DOWN) {
                if (!(btn & BUTTON_REL)) rb->adjust_volume(base == BUTTON_VOL_UP ? 1 : -1);
            } else if (short_of(base) != K_NONE) {
                if (!(btn & (BUTTON_REL | BUTTON_REPEAT))) {
                    press_btn = base; press_tick = *rb->current_tick; long_fired = false;
                } else if ((btn & BUTTON_REPEAT) && base == press_btn && !long_fired &&
                           (*rb->current_tick - press_tick) * (1000 / HZ) >= LONG_MS) {
                    long_fired = true;
                    e.k = long_of(base);
                } else if ((btn & BUTTON_REL) && (base == press_btn || press_btn == 0)) {
                    /* a release whose press we never saw (eaten by the backlight wake,
                     * or queued while we were busy) still counts as a short press */
                    if (!(base == press_btn && long_fired)) e.k = short_of(base);
                    press_btn = 0;
                } else if (btn & BUTTON_REL) press_btn = 0;
            } else if (rb->default_event_handler(btn) == SYS_USB_CONNECTED) {
                return LOOP_USB;
            }
#ifndef CODA_OS
            if (e.k == K_MENU_LONG) return LOOP_EXIT;   /* plugin: hold M = back to Rockbox */
#endif
            if (e.k != K_NONE) app_event(A, e);
        }
        int need = app_tick(A, plat_ms());
        bool lit = rb->is_backlight_on(true);
        if (lit == dark) plat_log("screen %s", lit ? "on" : "off");
        if (!lit) { dark = true; continue; }                          /* nothing to see */
        if (dark) { dark = false; app_force_redraw(A); need = app_tick(A, plat_ms()); }
        if (need & NEED_FULL) {
            app_draw(A, &g);
            push_full();
        } else if (need & NEED_HUB) {
            int r[4];
            app_draw_hub(A, &g, r);
            if (r[2] > 0 && r[3] > 0) {
                rb->lcd_bitmap_part(fb, r[0], r[1], LCD_W, r[0], r[1], r[2], r[3]);
                rb->lcd_update_rect(r[0], r[1], r[2], r[3]);
            }
        }
    }
}

#ifndef CODA_OS
/* ------------------------------------------------------------------ plugin entry */
enum plugin_status plugin_start(const void *parameter)
{
    bool resume = parameter == rb->plugin_tsr;
    size_t sz;
    void *buf = rb->plugin_get_buffer(&sz);
    init_memory_pool(sz, buf);
    spectrum_init();

    A = app_create(CODA_DIR "/pack", CODA_DIR "/plays.omp");
    if (!A) {
        if (!resume) rb->splash(HZ * 4, "Coda: app data missing in /.coda (see /.coda/coda.log)");
        return PLUGIN_ERROR;
    }
    if (resume) {                                   /* restarted after another plugin */
        if (app_background_autoplay(A)) go_background();
        return PLUGIN_OK;
    }
    int r = ui_loop();
    if (r == LOOP_USB) return PLUGIN_USB_CONNECTED;
    if (app_background_autoplay(A)) go_background();
    return PLUGIN_OK;
}

#else
/* ------------------------------------------------------------------ Coda OS entry
 * Coda compiled into the firmware as the root app (firmware/rockbox/os/). The core's
 * root_menu() calls coda_os_run(); it returns when the listener takes the hidden way out
 * (Menu + Back held), and Rockbox's own menus take over until Back at their root.
 * Memory: a static heap instead of the 2 MiB plugin buffer. Coda's own thread and stack.
 * Files: Coda's copy of the API table counts every open/close, so after USB mass storage
 * (the card may have changed) everything is closed and the library loads afresh. */
#include "../ui/boot.h"

const struct plugin_api *rb;
static struct plugin_api api_copy;
static const struct plugin_api *core_api;
static int (*core_open)(const char *path, int oflag, ...);
static int (*core_close)(int fd);
#define MAX_TRACKED 40
static int tracked[MAX_TRACKED], n_tracked;

static int t_open(const char *path, int oflag, ...)
{
    va_list ap;
    va_start(ap, oflag);
    int mode = va_arg(ap, int);
    va_end(ap);
    int fd = core_open(path, oflag, mode);
    if (fd >= 0 && n_tracked < MAX_TRACKED) tracked[n_tracked++] = fd;
    return fd;
}

static int t_close(int fd)
{
    for (int i = 0; i < n_tracked; i++)
        if (tracked[i] == fd) { tracked[i] = tracked[--n_tracked]; break; }
    return core_close(fd);
}

static void close_all(void)
{
    while (n_tracked) core_close(tracked[--n_tracked]);
}

static void use_api(const struct plugin_api *api)
{
    if (core_api) return;
    core_api = api;
    api_copy = *api;
    core_open = api->open;
    core_close = api->close;
    api_copy.open = t_open;
    api_copy.close = t_close;
    rb = &api_copy;
}

#define CODA_HEAP (8 * 1024 * 1024)
static unsigned char heap[CODA_HEAP] __attribute__((aligned(16)));
static long ui_stack[64 * 1024 / sizeof(long)];
static long load_stack[32 * 1024 / sizeof(long)];
static volatile int load_state;              /* 0 idle, 1 loading, 2 ok, 3 failed */
static volatile int load_release;

static void loader(void)
{
    plat_log("os: loading");
    close_all();
    init_memory_pool(CODA_HEAP, heap);
    A = app_create(CODA_DIR "/pack", CODA_DIR "/plays.omp");
    load_state = A ? 2 : 3;
    plat_log("os: loaded %d", load_state);
    /* exit only once the UI thread is waiting on us: a thread that exits while every
     * other thread sleeps can leave the scheduler idling with interrupts off (seen in
     * the simulator's green threads) */
    while (!load_release) rb->sleep(1);
}

/* load the library on its own thread while the boot animation plays */
static void load_with_animation(int animate)
{
    gfx g;
    g_init(&g, (px16 *)fb, LCD_W, LCD_H, LCD_W);
    load_state = 1;
    load_release = 0;
    unsigned int id = rb->create_thread(loader, load_stack, sizeof load_stack, 0, "coda load"
                                        IF_PRIO(, PRIORITY_USER_INTERFACE) IF_COP(, CPU));
    uint32_t t0 = plat_ms();
    for (;;) {
        uint32_t t = plat_ms() - t0;
        if (animate) {
            boot_draw(&g, t);
            push_full();
        }
        if (load_state != 1 && (!animate || t >= BOOT_MS)) break;
        rb->sleep(HZ / 30 ? HZ / 30 : 1);
    }
    plat_log("os: anim done t=%u state %d", (unsigned)(plat_ms() - t0), load_state);
    load_release = 1;
    rb->thread_wait(id);
    plat_log("os: loader joined");
}

static int ui_result;
static bool first_run = true;

static void ui_thread(void)
{
    if (!A || ui_result == LOOP_USB) {
        load_with_animation(first_run);
        if (!A) {
            rb->splash(HZ * 5, "Coda: no library in /.coda yet (refresh the card from the PC)");
            ui_result = LOOP_ESCAPE;
            return;
        }
    }
    first_run = false;
    ui_result = ui_loop();
    if (ui_result == LOOP_USB) A = NULL;          /* card may have changed: reload */
}

/* the first frame of the boot animation, drawn while Rockbox itself starts up */
void coda_os_logo(const struct plugin_api *api)
{
    use_api(api);
    gfx g;
    g_init(&g, (px16 *)fb, LCD_W, LCD_H, LCD_W);
    boot_draw(&g, 0);
    push_full();
}

/* run Coda until the hidden way out; returns to Rockbox's root menu */
void coda_os_run(const struct plugin_api *api)
{
    use_api(api);
    plat_log("os: run");
    bg_stop();
    spectrum_init();
    do {
        unsigned int id = rb->create_thread(ui_thread, ui_stack, sizeof ui_stack, 0, "coda"
                                            IF_PRIO(, PRIORITY_USER_INTERFACE) IF_COP(, CPU));
        plat_log("os: ui thread %u", id);
        if (!id) break;
        rb->thread_wait(id);
    } while (ui_result == LOOP_USB);
    if (A && app_background_autoplay(A)) bg_start();
}
#endif
