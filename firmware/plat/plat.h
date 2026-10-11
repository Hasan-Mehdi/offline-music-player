/* What the Coda UI needs from the platform. Two implementations:
 *   firmware/plat/host/plat_host.c       PC: stdio files, fake player clock, PNG frames
 *   firmware/rockbox/coda/plat_rockbox.c  H2: rb-> API (lcd, buttons, playlist, beep, pcm)
 */
#ifndef CODA_PLAT_H
#define CODA_PLAT_H

#include <stddef.h>
#include <stdint.h>

uint32_t plat_ms(void);                       /* monotonic milliseconds */
int64_t plat_now(void);                       /* wall clock, epoch seconds */
int plat_battery(void);                       /* percent, -1 unknown */
int plat_charging(void);                      /* 1 while the charger is filling the battery */
void plat_clock(int *hour, int *minute);      /* local wall clock */
/* set the RTC (local wall time); 0 ok, -1 where the platform can't (the plugin) */
int plat_set_clock(int year, int month, int day, int hour, int minute);
void plat_log(const char *fmt, ...);

void *plat_alloc(size_t n);                   /* arena: never freed */
int plat_ram_rich(void);                      /* 1: room to keep the library index in RAM */
/* path relative to the app data dir (/.coda on the card) */
void *plat_load(const char *rel, size_t *len);           /* whole file, NULL if missing */
int plat_save(const char *rel, const void *data, size_t len);  /* replace; 0 on success */
int plat_open(const char *rel);                           /* -1 if missing */
int plat_pread(int fd, void *buf, int n, uint32_t off);   /* bytes read */
void plat_close(int fd);

typedef struct {
    int playing;                              /* 1 playing, 0 paused/stopped */
    int active;                               /* something loaded */
    uint32_t idx;                             /* pack index of the current track */
    int pos;                                  /* its position in the player's queue, -1 unknown */
    uint32_t elapsed_ms, length_ms;
} plat_play;

/* The player's queue mirrors the app's (firmware/ui/app.c): same tracks, same order. */
void plat_player(plat_play *st);
void plat_play_tracks(const uint32_t *idx, int n, int start, uint32_t start_ms);  /* replace + play */
void plat_queue_add(uint32_t idx, int next);  /* next: right after the current track, else last */
int plat_queue_remove(int pos);               /* 0 ok, -1 not supported here */
int plat_queue_read(uint32_t *idx, int cap, int *pos);   /* the player's queue (app start) */
void plat_jump(int pos);                      /* play queue position pos from the start */
void plat_stop(void);
void plat_toggle(void);
void plat_skip(int dir);                      /* +1 next, -1 previous */
void plat_seek(uint32_t pos_ms);              /* absolute; clamped short of the end */
void plat_beep(int hz, int ms, int amp);      /* wheel detent tick */
int plat_spectrum(uint8_t bands[12]);         /* 0 if unavailable */

/* What this platform can do beyond the basics (Settings shows only what applies). */
enum {
    PF_EXIT = 1,       /* there is somewhere to leave Coda to (the plugin, Coda OS's escape) */
    PF_DEVICE = 2,     /* the device settings below are Coda's to show (Coda OS) */
    PF_BLUETOOTH = 4,  /* wireless headphones (Coda OS on the H2) */
};
int plat_features(void);

/* Bluetooth headphones. Every call returns at once; the radio works in the background and
 * plat_bt_status says where it got (gen changes whenever anything in it does). */
enum { BTR_OFF, BTR_STARTING, BTR_ON, BTR_FAILED, BTR_STOPPING };
enum { BTL_NONE, BTL_CONNECTING, BTL_CONNECTED, BTL_STREAMING };
typedef struct {
    int radio, link, scanning;
    uint8_t peer_addr[6];
    char peer[48];                            /* connected, or being connected to */
    char msg[64];                             /* the latest news, "" if none */
    unsigned gen;
} plat_bt;
typedef struct { uint8_t addr[6]; char name[48]; int rssi; int paired; } plat_bt_dev;
void plat_bt_status(plat_bt *st);
int plat_bt_devices(plat_bt_dev *out, int cap);  /* paired first, then nearby */
void plat_bt_power(int on);                   /* remembered across boots */
void plat_bt_scan(int on);                    /* ~13 s, stops by itself */
void plat_bt_connect(const uint8_t addr[6]);  /* pairs first if needed */
void plat_bt_disconnect(void);
void plat_bt_forget(const uint8_t addr[6]);

/* Device settings the platform keeps (Rockbox's config.cfg on the H2). Values in each
 * setting's own unit: sleep = minutes left (0 off), screen = seconds before the backlight
 * goes off (0 never), brightness = raw level, poweroff = idle minutes (0 never), volume
 * limit / bass / treble = dB, unplug = 0 keep playing, 1 pause, 2 pause + resume. */
enum { DS_SLEEP, DS_SCREEN, DS_BRIGHT, DS_POWEROFF, DS_VOLMAX, DS_BASS, DS_TREBLE, DS_UNPLUG,
       DS_COUNT };
int plat_dev_get(int which);
void plat_dev_set(int which, int value);      /* applied at once */
void plat_dev_range(int which, int *lo, int *hi, int *step);
void plat_dev_save(void);                     /* persist what was set */

#endif
