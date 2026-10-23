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

int plat_clock_sec(void) { return rb->get_time()->tm_sec; }

/* ------------------------------------------------------------------ the battery figure
 * The power chip's gauge (Rockbox's battery_level) has no model of this battery: rested, it
 * reads well above where it stood when the player went off (off at 30%, on later at 46% --
 * no charger in between), then falls faster to make up. So Coda shows the gauge scaled to
 * carry on from the figure it last showed: on battery it only ever goes down, and it gets to
 * 0 when the gauge does. On the charger, or after the player was switched off on it, the
 * gauge as it is. /.coda/battery.txt keeps the figure, and whether the charger was in, across
 * a power-off. The battery log keeps the gauge's own reading too. */
#define BAT_FILE CODA_DIR "/battery.txt"
static int bat_shown = -1, bat_k = 1000, bat_saved = -1;
static bool bat_inited;

static void battery_save(void)
{
    if (bat_shown < 0) return;
    char buf[32];
    int n = snprintf(buf, sizeof buf, "%d %d\n", bat_shown, rb->charger_inserted() ? 1 : 0);
    int fd = rb->open(BAT_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd >= 0) { rb->write(fd, buf, n); rb->close(fd); }
    bat_saved = bat_shown;
}

int plat_battery(void)
{
    int g = rb->battery_level();
    if (g < 0) return bat_shown;
    if (!bat_inited) {
        bat_inited = true;
        int shown = -1, on_charger = 1;
        char buf[32];
        int fd = rb->open(BAT_FILE, O_RDONLY);
        if (fd >= 0) {
            int r = rb->read(fd, buf, sizeof buf - 1);
            rb->close(fd);
            if (r > 0) {
                buf[r] = 0;
                shown = atoi(buf);
                const char *sp = strchr(buf, ' ');
                on_charger = sp ? atoi(sp + 1) : 1;
            }
        }
        if (!on_charger && !rb->charger_inserted() && shown >= 0 && shown < g && g > 0)
            bat_k = shown * 1000 / g;
        plat_log("os: battery gauge %d%%, last shown %d%%%s: showing %d%%", g, shown,
                 on_charger ? " (charger at off)" : "", g * bat_k / 1000);
    }
    if (rb->charger_inserted()) {                 /* charging: the gauge, and from here on */
        bat_k = 1000;
        bat_shown = g;
    } else {
        int v = (g * bat_k + 500) / 1000;
        bat_shown = bat_shown < 0 || v < bat_shown ? v : bat_shown;
    }
    if (bat_shown != bat_saved) battery_save();
    return bat_shown;
}

/* 1 charging, 2 on the charger with nothing left to fill */
int plat_charging(void)
{
    if (!rb->charger_inserted()) return 0;
    return rb->charging_state() || rb->battery_level() < 95 ? 1 : 2;
}

/* What switched the player on (the power chip, patch_core "coda: power helpers"): the
 * charger plugged in, not the power key -> the charge screen. Asked once. */
#if defined(CODA_OS) && defined(EROS_QN) && (CONFIG_PLATFORM & PLATFORM_NATIVE)
extern int coda_pwron_source(void);
extern void coda_bright_save(int v);
extern int coda_chgled_by_charger(void);
extern int coda_pmu_reg(int reg);
#define CODA_PMU 1
#endif
static int pwron = -2;
static int charger_boot(void)
{
#ifdef CODA_PMU
    if (pwron == -2) pwron = coda_pwron_source();
#else
    pwron = -1;
#endif
    return pwron >= 0 && (pwron & 0x04) && !(pwron & 0x01);
}

/* the radio's own question at start-up (apps/bluetooth): hold off while the charge screen is up */
int coda_bt_hold(void) { return charger_boot() && (!rb || rb->charger_inserted()); }

#define CHARGE_OFF_FILE CODA_DIR "/charge_off.txt"
int plat_charger_boot(void)
{
    static bool asked;
    if (asked) return 0;                          /* after USB the app loads again: not again */
    asked = true;
    int r = charger_boot() && rb->charger_inserted();
    plat_log("os: switched on by %s (power chip 0x%02x)", r ? "the charger" : "the power key", pwron & 0xff);
    if (r) {                                      /* switched off to charge a moment ago, and the */
        char buf[24];                             /* charger woke it again: no loop, stay on, dark */
        int fd = rb->open(CHARGE_OFF_FILE, O_RDONLY), n = fd >= 0 ? rb->read(fd, buf, sizeof buf - 1) : 0;
        if (fd >= 0) rb->close(fd);
        if (n > 0) {
            buf[n] = 0;
            long t = atoi(buf), now = (long)plat_now();
            if (now >= t && now - t < 120) {
                plat_log("os: the charger woke it again %ld s after it went off to charge: staying on", now - t);
                r = 2;
            }
        }
    }
    return r;
}

void plat_charge_screen(int on)
{
    rb->backlight_set_brightness(on ? MIN_BRIGHTNESS_SETTING : rb->global_settings->brightness);
}

void plat_charge_off(void)
{
    char buf[24];
    int n = snprintf(buf, sizeof buf, "%ld\n", (long)plat_now());
    int fd = rb->open(CHARGE_OFF_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd >= 0) { rb->write(fd, buf, n); rb->close(fd); }
    rb->sys_poweroff();
}

void plat_power_off(void) { rb->sys_poweroff(); }

/* the RTC as it reads, for the log: the clock keeps going wrong across power-offs */
static const char *clock_str(void)
{
    static char b[24];
    struct tm *t = rb->get_time();
    snprintf(b, sizeof b, "%04d-%02d-%02d %02d:%02d:%02d", t->tm_year + 1900, t->tm_mon + 1, t->tm_mday,
             t->tm_hour, t->tm_min, t->tm_sec);
    return b;
}

int plat_set_clock(int year, int month, int day, int hour, int minute)
{
#ifdef CODA_OS
    /* compiled into the firmware: the core's own RTC setter (not in the plugin API) */
    extern int set_time(const struct tm *tm);
    extern void set_day_of_week(struct tm *tm);
    struct tm t = *rb->get_time();
    t.tm_year = year - 1900; t.tm_mon = month - 1; t.tm_mday = day;
    t.tm_hour = hour; t.tm_min = minute; t.tm_sec = 0;
    set_day_of_week(&t);
    return set_time(&t) == 0 ? 0 : -1;
#else
    (void)year; (void)month; (void)day; (void)hour; (void)minute;
    return -1;
#endif
}

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

/* Coda OS has an 8 MiB heap: the pack's records, strings and ids (~2.6 MB for 18k songs)
 * stay in RAM, so lists and search don't read the card per row. The plugin streams them. */
int plat_ram_rich(void)
{
#ifdef CODA_OS
    return 1;
#else
    return 0;
#endif
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

/* Power pressed: the screen off until a button. Ours to know, not the backlight's to say: with
 * the backlight set to stay on, is_backlight_on() would go on saying it is */
static bool dark_forced;
void plat_screen_off(void) { rb->backlight_off(); dark_forced = true; }

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

/* The door's sounds (Room's and Diorama's power on and off): recorded doors laid on the
 * animation's own clock (firmware/tools/gen_door_sfx.py -> .pcm files in /.coda/sfx, 16-bit mono
 * 22.05 kHz), played on the voice channel over whatever is playing -- stretched to the
 * mixer's rate a chunk at a time as the mixer asks for it. Static: at power-on the heap
 * isn't there yet. */
#define SFX_RATE 22050
#define SFX_CHUNK 1024
static int16_t sfx_src[SFX_RATE * 2];
static int sfx_n;
static uint32_t sfx_pos, sfx_step;              /* 16.16, in source samples */
static int16_t sfx_out[2][SFX_CHUNK * 2];
static int sfx_half;

static void sfx_more(const void **start, size_t *size)
{
    int16_t *o = sfx_out[sfx_half ^= 1];
    int k = 0;
    for (; k < SFX_CHUNK && (int)(sfx_pos >> 16) + 1 < sfx_n; k++, sfx_pos += sfx_step) {
        uint32_t i = sfx_pos >> 16, f = sfx_pos & 0xffff;
        int16_t v = (int16_t)((sfx_src[i] * (int32_t)(65536 - f) + sfx_src[i + 1] * (int32_t)f) >> 16);
        o[2 * k] = o[2 * k + 1] = v;
    }
    *start = k ? o : NULL;
    *size = (size_t)k * 4;
}

static void sfx_load(const char *name)
{
    char path[64];
    snprintf(path, sizeof path, CODA_DIR "/sfx/%s", name);
    sfx_n = 0;
    int fd = rb->open(path, O_RDONLY);
    if (fd < 0) return;
    int r = rb->read(fd, sfx_src, sizeof sfx_src);
    rb->close(fd);
    sfx_n = r > 4 ? r / 2 : 0;
}

static void sfx_play(void)
{
    if (sfx_n < 2) return;
    unsigned fr = rb->mixer_get_frequency();
    sfx_pos = 0;
    sfx_step = (uint32_t)(((uint64_t)SFX_RATE << 16) / (fr ? fr : 44100));
    static const struct mixer_play_cbs cbs = { sfx_more, NULL };
    rb->mixer_channel_stop(PCM_MIXER_CHAN_VOICE);
    rb->mixer_channel_set_amplitude(PCM_MIXER_CHAN_VOICE, MIX_AMP_UNITY);
    rb->mixer_channel_play_data(PCM_MIXER_CHAN_VOICE, &cbs, NULL, 0);
}

static int sfx_playing(void)
{
    return sfx_n >= 2 && (int)(sfx_pos >> 16) + 1 < sfx_n &&
           rb->mixer_channel_status(PCM_MIXER_CHAN_VOICE) == CHANNEL_PLAYING;
}

static int door_skin(int skin) { return skin == 1 || skin == 7; }   /* Room, Diorama: the door */
int plat_input_pending(void) { return rb->button_queue_count() > 0; }

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

/* ------------------------------------------------------------------ device settings
 * Rockbox's own settings (config.cfg), shown in Coda's Settings on Coda OS so Rockbox's
 * menus are never needed. Each one goes through the core's own setter, the same call
 * Rockbox's menu would make; nothing here touches power or battery management. */
int plat_bt_available(void);

int plat_features(void)
{
    int bt = plat_bt_available() ? PF_BLUETOOTH : 0;
#if defined(CODA_OS_STRIP)
    return PF_DEVICE | bt;
#elif defined(CODA_OS)
    return PF_DEVICE | PF_EXIT | bt;
#else
    return PF_EXIT | bt;
#endif
}

#ifdef CODA_OS
extern void set_poweroff_timeout(int timeout);

int plat_dev_get(int which)
{
    const struct user_settings *s = rb->global_settings;
    switch (which) {
    case DS_SLEEP: { int t = rb->get_sleep_timer(); return t ? (t + 59) / 60 : 0; }
    case DS_SCREEN: return s->backlight_timeout;
    case DS_BRIGHT: return s->brightness;
    case DS_POWEROFF: return s->poweroff;
    case DS_VOLMAX: return s->volume_limit;
    case DS_BASS: return s->bass;
    case DS_TREBLE: return s->treble;
    case DS_UNPLUG: return s->unplug_mode;
    default: return 0;
    }
}

void plat_dev_range(int which, int *lo, int *hi, int *step)
{
    *step = 1;
    switch (which) {
    case DS_SLEEP: *lo = 0; *hi = 300; break;
    case DS_SCREEN: *lo = -1; *hi = 7200; break;
    case DS_BRIGHT: *lo = MIN_BRIGHTNESS_SETTING; *hi = MAX_BRIGHTNESS_SETTING; break;
    case DS_POWEROFF: *lo = 0; *hi = 60; break;
    case DS_VOLMAX:
        *lo = rb->sound_min(SOUND_VOLUME); *hi = rb->sound_max(SOUND_VOLUME);
        *step = sound_steps(SOUND_VOLUME);
        break;
    case DS_BASS: *lo = rb->sound_min(SOUND_BASS); *hi = rb->sound_max(SOUND_BASS); break;
    case DS_TREBLE: *lo = rb->sound_min(SOUND_TREBLE); *hi = rb->sound_max(SOUND_TREBLE); break;
    case DS_UNPLUG: *lo = 0; *hi = 2; break;
    default: *lo = *hi = 0; break;
    }
}

void plat_dev_set(int which, int v)
{
    struct user_settings *s = rb->global_settings;
    int lo, hi, step;
    plat_dev_range(which, &lo, &hi, &step);
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    switch (which) {
    case DS_SLEEP: rb->set_sleeptimer_duration(v); break;
    case DS_SCREEN:                       /* the same timeout on battery and on the charger */
        s->backlight_timeout = s->backlight_timeout_plugged = v;
        rb->backlight_set_timeout(v);
        rb->backlight_set_timeout_plugged(v);
        break;
    case DS_BRIGHT:
        s->brightness = v;
        rb->backlight_set_brightness(v);
#ifdef CODA_PMU
        coda_bright_save(v);                /* the screen comes on at it next time, before the card is read */
#endif
        break;
    case DS_POWEROFF: s->poweroff = v; set_poweroff_timeout(v); break;
    case DS_VOLMAX:
        s->volume_limit = v;
        if (rb->global_status->volume > v) { rb->global_status->volume = v; setvol(); }
        break;
    case DS_BASS: s->bass = v; rb->sound_set(SOUND_BASS, v); break;
    case DS_TREBLE: s->treble = v; rb->sound_set(SOUND_TREBLE, v); break;
    case DS_UNPLUG: s->unplug_mode = v; break;
    default: break;
    }
}

void plat_dev_save(void) { rb->settings_save(); }
#else
int plat_dev_get(int which) { (void)which; return 0; }
void plat_dev_range(int which, int *lo, int *hi, int *step) { (void)which; *lo = *hi = 0; *step = 1; }
void plat_dev_set(int which, int v) { (void)which; (void)v; }
void plat_dev_save(void) {}
#endif

/* ------------------------------------------------------------------ Bluetooth
 * Coda OS on a Bluetooth build: the firmware's own service (apps/bluetooth), called
 * directly -- it isn't in the plugin API. Its enums line up with plat.h's BTR_ / BTL_. */
#if defined(CODA_OS) && defined(HAVE_BLUETOOTH)
#include "bluetooth/bluetooth.h"

int plat_bt_available(void) { return 1; }

void plat_bt_status(plat_bt *st)
{
    struct bt_status s;
    bt_get_status(&s);
    st->radio = s.radio;
    st->link = s.link;
    st->scanning = s.scanning;
    memcpy(st->peer_addr, s.peer, 6);
    rb->strlcpy(st->peer, s.peer_name, sizeof st->peer);
    rb->strlcpy(st->msg, s.msg, sizeof st->msg);
    st->gen = s.gen;
    st->abs_volume = s.abs_volume;
    st->vol_gen = s.vol_gen;
    st->batt_l = s.batt_l;
    st->batt_r = s.batt_r;
    st->batt_case = s.batt_case;
    st->hq = s.hq;
    st->link_hz = s.link_hz;
    st->link_kbps = s.link_kbps;
    st->weak = s.weak;
}

int plat_bt_volume_step(int dir)
{
    if (!bt_volume_step(dir)) return -1;
    struct bt_status s;
    bt_get_status(&s);
    return s.abs_volume < 0 ? -1 : (s.abs_volume * 100 + 63) / 127;
}

int plat_bt_devices(plat_bt_dev *out, int cap)
{
    static struct bt_device d[24];
    int n = bt_get_devices(d, cap < 24 ? cap : 24);
    for (int i = 0; i < n; i++) {
        memcpy(out[i].addr, d[i].addr, 6);
        rb->strlcpy(out[i].name, d[i].name, sizeof out[i].name);
        out[i].rssi = d[i].rssi;
        out[i].paired = d[i].paired;
    }
    return n;
}

void plat_bt_power(int on) { bt_set_power(on != 0); }
void plat_bt_scan(int on) { bt_set_scan(on != 0); }
void plat_bt_connect(const uint8_t addr[6]) { bt_connect(addr); }
void plat_bt_disconnect(void) { bt_disconnect(); }
void plat_bt_forget(const uint8_t addr[6]) { bt_forget(addr); }
void plat_bt_quality(int high) { bt_set_quality(high != 0); }
void plat_bt_boot_resume(void) { bt_boot_resume(); }
static void bt_diag_line(char *out, size_t n) { bt_diag(out, n); }
static int bt_rescue_audio(void) { return bt_rescue() ? 1 : 0; }
#else
void plat_bt_boot_resume(void) {}
static void bt_diag_line(char *out, size_t n) { if (n) out[0] = 0; }
static int bt_rescue_audio(void) { return 0; }
int plat_bt_available(void) { return 0; }
void plat_bt_status(plat_bt *st) { memset(st, 0, sizeof *st); }
int plat_bt_devices(plat_bt_dev *out, int cap) { (void)out; (void)cap; return 0; }
void plat_bt_power(int on) { (void)on; }
void plat_bt_scan(int on) { (void)on; }
void plat_bt_connect(const uint8_t addr[6]) { (void)addr; }
void plat_bt_disconnect(void) {}
void plat_bt_forget(const uint8_t addr[6]) { (void)addr; }
void plat_bt_quality(int high) { (void)high; }
int plat_bt_volume_step(int dir) { (void)dir; return -1; }
#endif

/* ------------------------------------------------------------------ playback stuck
 * (app.c stall_watch): the audio path in a line, and the rescues past restarting the queue */
#ifdef CODA_OS
extern bool pcm_is_playing(void);
extern size_t buf_used(void);
#endif
void plat_play_diag(char *out, size_t n)
{
    int st = rb->audio_status(), k;
#ifdef CODA_OS
    k = snprintf(out, n, "audio %x, pcm %d, mixer %d, buffered %u KB", st, pcm_is_playing() ? 1 : 0,
                 (int)rb->mixer_channel_status(PCM_MIXER_CHAN_PLAYBACK), (unsigned)(buf_used() / 1024));
#else
    k = snprintf(out, n, "audio %x, mixer %d", st, (int)rb->mixer_channel_status(PCM_MIXER_CHAN_PLAYBACK));
#endif
    if (k > 0 && (size_t)k + 3 < n) {
        char b[120];
        bt_diag_line(b, sizeof b);
        if (b[0]) snprintf(out + k, n - k, "; %s", b);
    }
}

int plat_audio_rescue(int stage)
{
    if (stage == 2) return bt_rescue_audio();
    if (stage >= 3) {
        plat_log("os: restarting the player to get playback going again");
        rb->sys_reboot();
        return 1;
    }
    return 0;
}

/* ------------------------------------------------------------------ battery log
 * Read-only measurements for the battery-life test (scripts/h2_battery.py): every 5 min,
 * and whenever the charger comes or goes, one line in /.coda/battery.csv:
 *   epoch, level %, mV, mA (or -1), charger 0/1, charging 0/1, playing 0/1, screen 0/1,
 *   then over the 5 min since the last line: CPU busy, screen lit, music playing (each in
 *   per mille, -1 unknown), and now: Bluetooth (0 off, 1 on, 2 connected, 3 streaming),
 *   the earbuds' battery % (-1 unknown), the figure Coda shows (plat_battery: the level
 *   column is the power chip's own gauge)
 * The level is the power chip's own gauge, the mV its measurement under whatever load
 * there is. On Coda OS also /.coda/cpu.log: which threads the CPU's busy time went to.
 * Only reads what the firmware reports; it changes nothing. */
#define BATT_EVERY (5 * 60 * HZ)
static long batt_last;
static int batt_charger = -1;
static uint32_t span_lit_ms, span_play_ms, span_ms, span_t;

/* the loop's own clock of what the 5 min were like: lit, playing */
static void battery_span_tick(bool lit, bool playing)
{
    uint32_t now = plat_ms(), dt = span_t ? now - span_t : 0;
    span_t = now;
    if (dt > 5000) dt = 5000;                  /* a gap (USB, a stall): don't guess */
    span_ms += dt;
    if (lit) span_lit_ms += dt;
    if (playing) span_play_ms += dt;
}

#if defined(CODA_OS) && (CONFIG_PLATFORM & PLATFORM_NATIVE) && CONFIG_CPU == X1000
/* patch_core "coda: cpu profile": totals since boot, in OST2 ticks, and per-tick samples */
extern uint64_t __cpu_ost_total, __cpu_idle_total;
extern unsigned __cpu_wait_hits;
extern unsigned short __cpu_thread_hits[64];
#include "thread.h"
#define CPU_PROFILE 1

/* busy per mille since the last call; the threads that had it, into /.coda/cpu.log */
static int cpu_busy_span(const char *state)
{
    static uint64_t ost0, idle0;
    unsigned short hits[64];
    int oldlevel = disable_irq_save();              /* the tick writes these */
    uint64_t ost = __cpu_ost_total, idle = __cpu_idle_total;
    memcpy(hits, (const void *)__cpu_thread_hits, sizeof hits);
    memset((void *)__cpu_thread_hits, 0, sizeof hits);
    unsigned wait = __cpu_wait_hits;
    __cpu_wait_hits = 0;
    restore_irq(oldlevel);
    int busy = -1;
    if (ost0 && ost > ost0) busy = (int)(1000 - (idle - idle0) * 1000 / (ost - ost0));
    ost0 = ost;
    idle0 = idle;
    unsigned all = wait;
    for (int i = 0; i < 64; i++) all += hits[i];
    if (!all || busy < 0) return busy;
    char line[256];
    int n = snprintf(line, sizeof line, "%ld %s busy %d.%d%%:", (long)plat_now(), state, busy / 10, busy % 10);
    for (int k = 0; k < 6; k++) {                    /* the six biggest */
        int best = -1;
        for (int i = 0; i < 64; i++) if (hits[i] && (best < 0 || hits[i] > hits[best])) best = i;
        if (best < 0) break;
        struct thread_debug_info info;
        const char *name = thread_get_debug_info(best, &info) > 0 ? info.name : "?";
        n += snprintf(line + n, sizeof line - n, " %s %u.%u%%", name, hits[best] * 100 / all,
                      hits[best] * 1000 / all % 10);
        hits[best] = 0;
        if (n >= (int)sizeof line - 2) { n = sizeof line - 2; break; }
    }
    line[n++] = '\n';
    int fd = rb->open(CODA_DIR "/cpu.log", O_WRONLY | O_CREAT | O_APPEND, 0666);
    if (fd >= 0) { rb->write(fd, line, n); rb->close(fd); }
    return busy;
}
#else
static int cpu_busy_span(const char *state) { (void)state; return -1; }
#endif

static void battery_log_tick(void)
{
    int ch = rb->charger_inserted() ? 1 : 0;
    long now = *rb->current_tick;
    if (batt_last && ch == batt_charger && now - batt_last < BATT_EVERY) return;
    batt_last = now ? now : 1;
    batt_charger = ch;
    char line[128];
    int st = rb->audio_status();
    int playing = (st & AUDIO_STATUS_PLAY) && !(st & AUDIO_STATUS_PAUSE) ? 1 : 0;
    int lit_pm = span_ms ? (int)((uint64_t)span_lit_ms * 1000 / span_ms) : -1;
    int play_pm = span_ms ? (int)((uint64_t)span_play_ms * 1000 / span_ms) : -1;
    plat_bt b;
    plat_bt_status(&b);
    int bt = b.radio != BTR_ON ? 0 : b.link == BTL_STREAMING ? 3 : b.link == BTL_CONNECTED ? 2 : 1;
    int buds = b.batt_l >= 0 && b.batt_r >= 0 ? (b.batt_l < b.batt_r ? b.batt_l : b.batt_r) :
               b.batt_l >= 0 ? b.batt_l : b.batt_r;
    char state[48];
    snprintf(state, sizeof state, "lit %d play %d bt %d", lit_pm, play_pm, bt);
    int busy = cpu_busy_span(state);
    int n = snprintf(line, sizeof line, "%ld,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n", (long)plat_now(),
                     rb->battery_level(), rb->battery_voltage(), rb->battery_current(), ch,
                     rb->charging_state() ? 1 : 0, playing, rb->is_backlight_on(true) ? 1 : 0,
                     busy, lit_pm, play_pm, bt, buds, plat_battery());
    span_ms = span_lit_ms = span_play_ms = 0;
    int fd = rb->open(CODA_DIR "/battery.csv", O_WRONLY | O_CREAT | O_APPEND, 0666);
    if (fd >= 0) { rb->write(fd, line, n); rb->close(fd); }
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
        battery_log_tick();
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
static bool long_fired, held_long;
#define ESCAPE_MS 1500            /* Coda OS: hold Menu + Back this long -> Rockbox's menus */

static key_kind short_of(int b)
{
    switch (b) {
    case BUTTON_PLAY: return K_PLAY;
    case BUTTON_MENU: return K_MENU;
    case BUTTON_POWER: return K_POWER;
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
    case BUTTON_BACK: return K_BACK_LONG;
    case BUTTON_PREV: return K_PREV_LONG;
    case BUTTON_NEXT: return K_NEXT_LONG;
    default: return K_NONE;
    }
}

/* volume keys: Rockbox's step, held under the volume limit, said in the bottom strip --
 * or, on headphones that share their volume, a step of theirs (the same one their own
 * buttons move) */
static void volume_key(int dir)
{
    int lim = rb->global_settings->volume_limit;
    char msg[40];
    int theirs = plat_bt_volume_step(dir);
    if (theirs >= 0) {
        snprintf(msg, sizeof msg, "Volume %d%%", theirs);
    } else if (dir > 0 && rb->global_status->volume >= lim) {
        snprintf(msg, sizeof msg, "Volume %d dB (the limit)", rb->global_status->volume);
    } else {
        rb->adjust_volume(dir);
        if (rb->global_status->volume > lim) {
            rb->global_status->volume = lim;
            rb->sound_set(SOUND_VOLUME, lim);
        }
        snprintf(msg, sizeof msg, "Volume %d dB", rb->global_status->volume);
    }
    if (A) app_say(A, msg);
}

/* A frame takes ~10 ms to reach the H2's panel (8-bit bus), and the LCD driver's wait for
 * the last one gives up after a few ms (lcd_wait counts polls, not time): a frame started
 * sooner lands on top of one still going out and the panel shows noise until a later one.
 * So never two full frames within two ticks. */
static long push_tick = -100;
static void push_full(void)
{
    long d = *rb->current_tick - push_tick;
    if (d >= 0 && d < 2) rb->sleep(2 - d);
    rb->lcd_bitmap(fb, 0, 0, LCD_W, LCD_H);
    rb->lcd_update();
    push_tick = *rb->current_tick;
}

#ifdef CODA_OS
static void boot_settled(void);
static void boot_poweroff(void);
static void resume_tick(void);

/* Idle power-off: no music and the screen dark for the setting's minutes (Settings > Sleep >
 * Power off idle, 5 by default) and the player switches itself off -- the same clean
 * power-off as holding the button, the queue kept for next time. Paused counts as no
 * music; a song playing or anything on screen (a game included) keeps it on. Rockbox's
 * own idle timer seldom got there: any write to the card (Coda's logs, its queue) put it
 * back to the start. */
static long idle_since;
static void idle_poweroff_tick(bool lit, bool playing)
{
    long now = *rb->current_tick;
    int mins = rb->global_settings->poweroff;
    long limit = (long)mins * 60 * HZ;
    if (A && app_charge_mode(A)) { mins = 1; limit = 20 * HZ; }   /* the charge screen gone dark: off, the charger carries on */
    if (lit || playing || mins <= 0 || !idle_since) { idle_since = now ? now : 1; return; }
    if (now - idle_since < limit) return;
    plat_log("os: %ld s without music, screen dark: power off", limit / HZ);
    idle_since = now;
    rb->sys_poweroff();
}
#endif

static int ui_loop(void)
{
    gfx g;
    g_init(&g, (px16 *)fb, LCD_W, LCD_H, LCD_W);
    rb->lcd_set_viewport(NULL);
    bool dark = false, press_dark = false;
    long repush_at = 0;
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
            if (btn & SYS_EVENT) {
                /* power-off, charger, battery, USB: always Rockbox's own handling (clean
                 * shutdown, USB mode) -- never mistaken for a button */
#ifdef CODA_OS
                if (btn == SYS_POWEROFF || btn == SYS_REBOOT) boot_poweroff();
#endif
                if (rb->default_event_handler(btn) == SYS_USB_CONNECTED) return LOOP_USB;
            } else if (base == (BUTTON_MENU | BUTTON_BACK)) {
#if defined(CODA_OS) && !defined(CODA_OS_STRIP)
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
                if (!(btn & BUTTON_REL) && !dark) {      /* turned in the dark: it only wakes the screen */
                    e.k = K_SCROLL;
                    e.d = (base & BUTTON_SCROLL_FWD) ? 1 : -1;
                    /* turned while Prev or Next is held: brightness, and that press is used up */
                    if ((press_btn == BUTTON_PREV || press_btn == BUTTON_NEXT) && A && app_chords_ok(A)) {
                        e.k = K_HOLD_SCROLL;
                        long_fired = true;
                    }
                }
            } else if (base == BUTTON_VOL_UP || base == BUTTON_VOL_DOWN) {
                if (!(btn & BUTTON_REL)) volume_key(base == BUTTON_VOL_UP ? 1 : -1);
            } else if (base == BUTTON_MULTIMEDIA_PREV || base == BUTTON_MULTIMEDIA_NEXT) {
                /* earbuds' or a car's Prev / Next: ours, not Rockbox's audio_prev -- so Prev
                 * past a song's first 5 s starts it over, and Next at the end asks autoplay */
                if (!(btn & BUTTON_REL)) e.k = base == BUTTON_MULTIMEDIA_PREV ? K_PREV : K_NEXT;
            } else if (short_of(base) != K_NONE) {
                bool skip_key = base == BUTTON_PREV || base == BUTTON_NEXT;
                if (!(btn & (BUTTON_REL | BUTTON_REPEAT))) {
                    press_btn = base; press_tick = *rb->current_tick; long_fired = false; held_long = false;
                    press_dark = dark;           /* a press that wakes the screen isn't Power's "off" */
                } else if ((btn & BUTTON_REPEAT) && base == press_btn && !long_fired && !held_long &&
                           (*rb->current_tick - press_tick) * (1000 / HZ) >= LONG_MS) {
                    if (skip_key) {
                        /* Prev / Next held: on release it's theirs (hold Next = dislike, skip),
                         * unless the wheel turns meanwhile (brightness) */
                        held_long = true;
                        if (base == BUTTON_NEXT && !press_dark && A) app_say(A, "Let go: dislike and skip");
                    } else {
                        long_fired = true;
                        e.k = press_dark ? K_NONE : long_of(base);
                    }
                } else if ((btn & BUTTON_REL) && (base == press_btn || press_btn == 0)) {
                    bool held = base == press_btn && held_long && !long_fired;
                    /* a release whose press we never saw (eaten by the backlight wake,
                     * or queued while we were busy) still counts as a short press */
                    if (held) e.k = long_of(base);        /* Prev / Next held and let go: dark or not */
                    else if (!(base == press_btn && long_fired)) e.k = short_of(base);
                    if (base == BUTTON_POWER && (base != press_btn || press_dark)) e.k = K_NONE;
                    /* the press that woke the screen: in a pocket, Play still pauses and the
                     * skips still skip, but nothing acts on what the screen was showing */
                    if (!held && (base == press_btn ? press_dark : dark) && e.k != K_NONE) {
                        if (e.k == K_PLAY && !app_charge_mode(A)) plat_toggle();
                        if (e.k != K_PREV && e.k != K_NEXT) e.k = K_NONE;
                    }
                    held_long = false;
                    press_btn = 0;
                } else if (btn & BUTTON_REL) press_btn = 0;
            } else if (rb->default_event_handler(btn) == SYS_USB_CONNECTED) {
                return LOOP_USB;
            }
#ifndef CODA_OS
            if (e.k == K_MENU_LONG) return LOOP_EXIT;   /* plugin: hold M = back to Rockbox */
#endif
            if (e.k != K_NONE) app_event(A, e);
            /* a press, a turn: awake (a tap on the earbuds isn't one on the player) */
            if (!(btn & (BUTTON_REL | SYS_EVENT | BUTTON_MULTIMEDIA))) dark_forced = false;
        }
        int need = app_tick(A, plat_ms());
        bool lit = rb->is_backlight_on(true) && !dark_forced;
        int ast = rb->audio_status();
        bool playing = (ast & AUDIO_STATUS_PLAY) && !(ast & AUDIO_STATUS_PAUSE);
        battery_span_tick(lit, playing);
        battery_log_tick();
#ifdef CODA_OS
        boot_settled();
        resume_tick();
        idle_poweroff_tick(lit, playing);
#endif
        if (lit == dark) plat_log("screen %s", lit ? "on" : "off");
        if (!lit) { dark = true; continue; }                          /* nothing to see */
        if (dark) {
            /* the backlight's wake (lcd_enable) has just sent a frame of its own: ours waits
             * for it, and goes again a moment later in case it landed on top of it anyway */
            dark = false;
            app_force_redraw(A);
            need = app_tick(A, plat_ms());
            push_tick = *rb->current_tick;
            repush_at = *rb->current_tick + HZ / 10;
        }
        if (repush_at && TIME_AFTER(*rb->current_tick, repush_at) && !(need & NEED_FULL)) {
            repush_at = 0;
            push_full();
        }
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
/* TLSF's heap-corruption check calls panicf; its own weak one just spins. Hand it to
 * Rockbox's instead, so a broken heap shows a message rather than a frozen screen. */
void panicf(const char *fmt, ...)
{
    char buf[128];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    rb->panicf("%s", buf);
    for (;;) ;
}

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
#ifdef HAVE_DIRCACHE
#include "dircache.h"
#endif
extern void panicf(const char *fmt, ...);     /* the core's (firmware/panic.c) */

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

/* the saved theme's power-on (read once, before the library loads). -1 = not known yet:
 * Rockbox draws Coda's first boot frame (coda_os_logo) before it mounts the card, and a
 * read that early used to stick as 0 -- every theme powered on as Sakurai */
static int boot_skin_v = -1;
static bool card_ready;                      /* set by coda_os_run: Rockbox has mounted the card */
static int boot_skin(void)
{
    if (boot_skin_v < 0) {
        int s = app_saved_skin();
        if (s < 0 && !card_ready) return -1;          /* no card yet: ask again next frame */
        boot_skin_v = s < 0 ? 0 : s;                  /* no settings on the card: Sakurai */
    }
    return boot_skin_v;
}

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
    if (animate) boot_skin();             /* the theme off the card now: the loader's close_all() mustn't catch it open */
    if (animate && door_skin(boot_skin())) sfx_load("door_open.pcm");   /* likewise the door's sound */
    load_state = 1;
    load_release = 0;
    unsigned int id = rb->create_thread(loader, load_stack, sizeof load_stack, 0, "coda load"
                                        IF_PRIO(, PRIORITY_USER_INTERFACE) IF_COP(, CPU));
    uint32_t t0 = plat_ms();
    if (animate && door_skin(boot_skin())) sfx_play();
    for (;;) {
        uint32_t t = plat_ms() - t0;
        if (animate) {
            app_boot_draw(boot_skin(), &g, t);
            push_full();
        }
        if (load_state != 1 && (!animate || t >= BOOT_MS)) break;
        rb->sleep(HZ / 30 ? HZ / 30 : 1);
    }
    plat_log("os: anim done t=%u state %d skin %d", (unsigned)(plat_ms() - t0), load_state, boot_skin());
    load_release = 1;
    rb->thread_wait(id);
    plat_log("os: loader joined");
}

static int ui_result;
static bool first_run = true;

/* no library on the card: say so, and keep USB working so it can be filled */
static void no_library(void)
{
    gfx g;
    g_init(&g, (px16 *)fb, LCD_W, LCD_H, LCD_W);
    app_boot_draw(boot_skin(), &g, BOOT_MS);
    push_full();
    rb->splash(HZ * 3, "No library on this card yet. Fill it from the PC (scripts/export_h2.py).");
    for (;;) {
        long btn = rb->button_get_w_tmo(HZ * 5);
        if (btn != BUTTON_NONE && rb->default_event_handler(btn) == SYS_USB_CONNECTED) return;
    }
}

/* Crash-loop guard. Every boot counts itself in /.coda/boot.txt; 8 s of running Coda (or
 * a clean power-off) clears it. A crash restarts the player (coda_os_panic), so a crash
 * during start-up would loop: after 3 starts that never settled, stop and ask instead. */
#define SETTLE_MS 8000
#define CRASH_LOOPS 3
static uint32_t settle_t0;
static bool settled = true;

static void boot_settled(void)
{
    if (settled || plat_ms() - settle_t0 < SETTLE_MS) return;
    settled = true;
    plat_save("boot.txt", "0\n", 2);
}

/* a clean power-off right after switching on is not a crash */
static void boot_poweroff(void)
{
    settle_t0 -= SETTLE_MS;
    boot_settled();
}

static void boot_guard(void)
{
    size_t len = 0;
    char *s = NULL;
    int n = 0, fd = plat_open("boot.txt");
    char buf[16];
    if (fd >= 0) {
        int r = plat_pread(fd, buf, sizeof buf - 1, 0);
        plat_close(fd);
        if (r > 0) { buf[r] = 0; s = buf; len = (size_t)r; }
    }
    if (s && len) n = atoi(s);
    if (n >= CRASH_LOOPS) {
        plat_log("os: %d starts without settling; asking", n);
        gfx g;
        g_init(&g, (px16 *)fb, LCD_W, LCD_H, LCD_W);
        app_boot_draw(boot_skin(), &g, BOOT_MS);
        push_full();
        rb->splash(0, "Coda stopped while starting, 3 times. Play: try again. "
                      "Or plug in to the computer.");
        for (;;) {
            long btn = rb->button_get_w_tmo(HZ * 5);
            if (btn == (BUTTON_PLAY | BUTTON_REL)) break;
            if (btn != BUTTON_NONE && rb->default_event_handler(btn) == SYS_USB_CONNECTED) break;
        }
        n = 0;
    }
    char out[16];
    int k = snprintf(out, sizeof out, "%d\n", n + 1);
    plat_save("boot.txt", out, (size_t)k);
    settle_t0 = plat_ms();
    settled = false;
}

/* After a power cycle: pick up where the listener left off, paused (Rockbox keeps the
 * queue in /.rockbox/.playlist_control and the position in its resume status). Its own
 * menus would do this on the way to the Now Playing screen; Coda OS never goes there.
 * playlist_resume() waits for the directory cache, which Rockbox builds in the background
 * for the first seconds after power-on (every file on the card): so Coda starts at once and
 * the UI loop resumes the queue once the cache is ready. Playing something first wins. */
#define RESUME_IDLE_MS 2000        /* cache not scanning this long after start: off or failed */
#define RESUME_GIVE_UP_MS 60000
static bool resume_pending;
static uint32_t resume_t0;

static bool dircache_settled(uint32_t waited)
{
#ifdef HAVE_DIRCACHE
    if (!rb->global_settings->dircache) return true;
    struct dircache_info info;
    dircache_get_info(&info);
    if (info.status == DIRCACHE_READY) return true;
    return info.status != DIRCACHE_SCANNING && waited > RESUME_IDLE_MS;
#elif !(CONFIG_PLATFORM & PLATFORM_NATIVE)
    return waited > 3000;          /* the simulator has no cache: stand in for the card's */
#else
    (void)waited;
    return true;
#endif
}

static void resume_tick(void)
{
    if (!resume_pending) return;
    struct system_status *st = rb->global_status;
    uint32_t waited = plat_ms() - resume_t0;
    if (rb->audio_status() || waited > RESUME_GIVE_UP_MS) {
        resume_pending = false;
        plat_log("os: no resume (%s, %u ms)", waited > RESUME_GIVE_UP_MS ? "cache still building" :
                 "already playing", (unsigned)waited);
        return;
    }
    if (!dircache_settled(waited)) return;
    resume_pending = false;
    /* Coda's own record of the queue (app.c q_save): Rockbox's resume point only moves
     * while its playback screen runs, so it brought every queue back at its first song */
    if (A && app_resume_saved(A)) return;
    if (st->resume_index < 0) { plat_log("os: no resume (nothing to resume)"); return; }
    if (rb->playlist_resume() == -1) return;
    /* by time, not Rockbox's byte offset: with the cover art in the Opus headers the
     * offset lands a few seconds late */
    rb->playlist_resume_track(st->resume_index, st->resume_crc32, st->resume_elapsed, 0);
    rb->audio_pause();
    plat_log("os: resumed queue at #%d, %lu ms, paused, %u ms after start", st->resume_index,
             (unsigned long)st->resume_elapsed, (unsigned)(plat_ms() - resume_t0));
    if (A) app_adopt_queue(A);
}

static void ui_thread(void)
{
    if (first_run) {
        boot_guard();
        resume_pending = true;
        resume_t0 = plat_ms();
    }
    if (!A || ui_result == LOOP_USB) {
        load_with_animation(first_run && !coda_bt_hold());    /* the charger switched it on: no door, no animation */
        if (!A) {
#ifdef CODA_OS_STRIP
            no_library();                         /* returns after USB: try again */
            ui_result = LOOP_USB;
#else
            rb->splash(HZ * 5, "Coda: no library in /.coda yet (refresh the card from the PC)");
            ui_result = LOOP_ESCAPE;
#endif
            return;
        }
    }
    first_run = false;
#if !(CONFIG_PLATFORM & PLATFORM_NATIVE)
    /* simulator only: a crash on demand, for the crash screen and the crash-loop guard */
    if (rb->file_exists(CODA_DIR "/crash_test")) {
        plat_log("os: crash test");
        panicf("crash test (simulator)");
    }
#endif
    ui_result = ui_loop();
    if (ui_result == LOOP_USB) A = NULL;          /* card may have changed: reload */
}

/* the first frame of the boot animation, drawn while Rockbox itself starts up; before the
 * card is mounted the theme isn't known, so dark (every theme's power-on starts from it).
 * The LCD driver has just sent the panel a first frame of its own (lcd_init): let it land
 * first -- the dark frame is ready at once, and pushed over it the panel came up as static */
void coda_os_logo(const struct plugin_api *api)
{
    use_api(api);
    gfx g;
    g_init(&g, (px16 *)fb, LCD_W, LCD_H, LCD_W);
    int skin = boot_skin();
    if (skin < 0) g_fill(&g, 0, 0, LCD_W, LCD_H, C565(0, 0, 0));
    else app_boot_draw(skin, &g, 0);
    if (push_tick < 0) rb->sleep(2);
    push_full();
    /* and once more: Rockbox calls this at each step of its start-up (patch_core "frame
     * again"), and a frame that landed on another one shows as TV static until a later
     * frame -- which, before the boot animation, would be seconds away */
    rb->sleep(3);
    push_full();
}

/* the USB screen's picture (apps/gui/usb_screen.c keeps doing the USB work) */
int coda_os_usb_draw(void)
{
    if (!core_api) return 0;
    gfx g;
    g_init(&g, (px16 *)fb, LCD_W, LCD_H, LCD_W);
    if (A) app_draw_usb(A, &g);
    else app_boot_draw(boot_skin(), &g, BOOT_MS);            /* no library yet: Coda's mark, not Rockbox's */
    push_full();
    return 1;
}

/* Rockbox's panicf() hands Coda OS the message first (firmware/panic.c). Stock Rockbox
 * shows *PANIC* and, on this player, waits forever -- until the battery is flat. Instead:
 * say it in Coda's colours, give it a few seconds to be read, restart (and the player
 * picks the queue up again, paused). Interrupts are off and memory may be damaged, so
 * only the core's own LCD calls and its built-in font; nothing of Coda's. */
void coda_os_panic(const char *msg)
{
    const unsigned paper = LCD_RGBPACK(0xf4, 0xf4, 0xf0), ink = LCD_RGBPACK(0x14, 0x14, 0x14);
    lcd_set_viewport(NULL);
    lcd_set_backdrop(NULL);
    lcd_set_drawinfo(DRMODE_SOLID, ink, paper);
    lcd_clear_display();
    lcd_setfont(FONT_SYSFIXED);
    lcd_set_foreground(LCD_RGBPACK(0xe0, 0x30, 0x1e));
    lcd_fillrect(8, 10, 8, 8);
    lcd_set_foreground(ink);
    lcd_putsxy(24, 10, "Coda stopped. Restarting...");
    lcd_set_foreground(LCD_RGBPACK(0x00, 0x2f, 0xa7));
    int y = 34, cols = (LCD_WIDTH - 16) / SYSFONT_WIDTH;
    char line[64];
    for (const char *p = msg; *p && y < LCD_HEIGHT - 10; y += SYSFONT_HEIGHT + 2) {
        int n = 0;
        while (p[n] && n < cols && n < (int)sizeof line - 1) n++;
        memcpy(line, p, n);
        line[n] = 0;
        lcd_putsxy(8, y, line);
        p += n;
    }
    lcd_update();
#if (CONFIG_PLATFORM & PLATFORM_NATIVE)
    mdelay(8000);
    system_reboot();
#else
    sleep(3 * HZ);    /* the simulator (a busy wait would stop its clock): time for a screenshot */
#endif
}

/* Rockbox's clean shutdown calls this instead of its "Shutting down" splash (apps/misc.c):
 * Coda's power-off animation, from whatever is on screen. Skipped when the screen is
 * already dark (sleep timer in a pocket) -- nobody to see it, no reason to wait. The
 * shutdown itself (saving, stopping, power) carries on in Rockbox afterwards. */
static px16 off_from[LCD_W * LCD_H];

void coda_os_shutdown(int why)
{
    if (!core_api) return;
    if (A) app_save_queue(A);     /* where you were, for the next power-on */
    battery_save();               /* the figure, and whether the charger is in as it goes off */
    plat_log("os: off, clock %s", clock_str());
    if (!why && !rb->is_backlight_on(true)) return;
    gfx g;
    g_init(&g, (px16 *)fb, LCD_W, LCD_H, LCD_W);
    rb->memcpy(off_from, fb, sizeof off_from);            /* the last frame Coda drew */
    push_full();                  /* back on screen at once, whatever the shutdown drew over it */
    if (why) {                    /* battery: say so and get out of the way, no waiting */
        if (A) app_draw_off(A, &g, 0, off_from, why);
        else boot_off_draw(&g, 0, off_from, why);
        push_full();
        return;
    }
    /* your crate (the covers come off the card on the first frame, before the clock starts) */
    if (A) app_draw_off(A, &g, 0, off_from, 0);
    int door = A && door_skin(app_skin(A));
    if (door) { sfx_load("door_close.pcm"); sfx_play(); }
    uint32_t t0 = plat_ms();
    for (;;) {
        uint32_t t = plat_ms() - t0;
        if (t > BOOT_OFF_MS) t = BOOT_OFF_MS;
        if (A) app_draw_off(A, &g, t ? t : 1, off_from, 0);
        else boot_off_draw(&g, t, off_from, 0);
        push_full();
        if (t >= BOOT_OFF_MS) break;
        rb->sleep(HZ / 30 ? HZ / 30 : 1);
    }
    /* the slam rings on a moment after the hall goes dark: let it, then power off */
    for (uint32_t w0 = plat_ms(); door && sfx_playing() && plat_ms() - w0 < 700; ) rb->sleep(HZ / 50 ? HZ / 50 : 1);
}

/* run Coda until the hidden way out; returns to Rockbox's root menu */
/* The Wheel's previews (and every skip) blend into each other instead of cutting: Rockbox's
 * own crossfade, on manual track changes only (albums and soundtracks stay gapless), a
 * second each way. Only if the listener hasn't set crossfade up themselves. */
static void crossfade_setup(void)
{
#ifdef HAVE_CROSSFADE
    extern void audio_set_crossfade(int enable);
    struct user_settings *s = rb->global_settings;
    if (s->crossfade != CROSSFADE_ENABLE_OFF) return;
    s->crossfade = CROSSFADE_ENABLE_MANSKIP;
    s->crossfade_fade_in_delay = s->crossfade_fade_out_delay = 0;
    s->crossfade_fade_in_duration = s->crossfade_fade_out_duration = 1;
    s->crossfade_fade_out_mixmode = 0;
    audio_set_crossfade(s->crossfade);
    plat_log("os: crossfade on manual track changes");
#endif
}

void coda_os_run(const struct plugin_api *api)
{
    use_api(api);
    plat_log("os: run, clock %s", clock_str());
    card_ready = true;
#ifdef CODA_PMU
    {   /* the status light to the charger; the brightness where the screen will find it next power-on */
        int led = coda_chgled_by_charger();
        coda_bright_save(rb->global_settings->brightness);
        plat_log("os: power chip: on by 0x%02x, status light was 0x%02x, input limit 0x%02x, charge 0x%02x",
                 coda_pmu_reg(0x20), led, coda_pmu_reg(0x16), coda_pmu_reg(0x62));
    }
#endif
    crossfade_setup();
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
