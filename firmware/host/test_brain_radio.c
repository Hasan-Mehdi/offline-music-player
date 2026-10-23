/* brain.c's radio over a real card's pack (radio.bin, wheel.bin): how a sitting's skips steer
 * it, and the Wheel. Skips steer the station, they never move it (2026-10-22: you switch by
 * picking something else, as on YT Music); brain_plan lays the radio out ahead; a song you
 * start climbs the Wheel. Run it on a copy of the coda dir: it writes picks.bin there.
 *
 *   powershell -File firmware\host\build_coda.ps1      (builds this too)
 *   firmware\host\build\test_brain_radio.exe <dir with wheel.bin> <pack dir>
 */
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "brain.h"
#include "omp_pack.h"
#include "omp_radio.h"
#include "plat_host.h"

static const omp_pack *P;
static double now = 1792200000.0;
static uint32_t played[64];
static int n_played, fails;
static char why[160];

static const char *title(uint32_t i) { return omp_pack_str(P, omp_pack_track(P, i)->title_off); }

/* cur ends with `outcome` after `frac` of it; the next pick */
static uint32_t step(uint32_t cur, int outcome, float frac)
{
    float secs = frac * brain_duration(cur);
    brain_log(cur, outcome == BRAIN_OUT_SKIP ? EV_SKIP : EV_COMPLETE, secs, now);
    uint32_t pick = brain_next(cur, played, n_played, outcome, secs, now, why, sizeof why, NULL, -1);
    printf("  %-8s %-40.40s -> %-40.40s | %s\n", outcome == BRAIN_OUT_SKIP ? "skipped" : "finished",
           title(cur), pick < brain_n() ? title(pick) : "-", why);
    played[n_played++] = cur;
    now += 60;
    brain_log(pick, EV_PLAY, 0, now);
    return pick;
}

static void expect(int ok, const char *what)
{
    printf("    %s %s\n", ok ? "ok  " : "FAIL", what);
    fails += !ok;
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: %s <coda dir> <pack dir>\n", argv[0]); return 2; }
    char plays[400];
    snprintf(plays, sizeof plays, "%s/test_brain_radio.omp", argv[1]);
    remove(plays);
    plat_host_init(argv[1], argv[2], brain_duration);
    if (brain_open(argv[2], plays) != 0 || brain_engine() != 4) { puts("FAIL: no radio in this pack"); return 1; }
    P = brain_pack();
    uint32_t wheel[8];
    if (brain_wheel(wheel, 8, now) < 2) { puts("FAIL: no wheel.bin"); return 1; }

    puts("a sitting on a song you chose; then three skips in a row:");
    uint32_t seed = wheel[3];
    brain_radio_seed(seed);
    brain_log(seed, EV_PLAY, 0, now);
    uint32_t a = step(seed, BRAIN_OUT_COMPLETE, 1.0f);
    char want[200];
    snprintf(want, sizeof want, "on the radio for %s", title(seed));
    expect(!strcmp(why, want), "finished: the seed's radio");
    uint32_t b = step(a, BRAIN_OUT_SKIP, 0.4f);
    expect(!strcmp(why, want), "one skip (40%, past the old 15% line): still the seed's radio");
    uint32_t c = step(b, BRAIN_OUT_SKIP, 0.3f);
    expect(!strcmp(why, want), "two: still the seed's radio");
    uint32_t d = step(c, BRAIN_OUT_SKIP, 0.5f);
    expect(!strcmp(why, want), "three in a row: still the seed's radio (no fresh seed)");
    uint32_t e = step(d, BRAIN_OUT_SKIP, 0.3f);
    expect(!strcmp(why, want), "four: still the seed's radio");
    step(e, BRAIN_OUT_COMPLETE, 1.0f);
    expect(!strcmp(why, want), "a finish after it: the seed's radio");

    puts("a new sitting: the song you chose, skipped at 20% with nothing kept since:");
    now += 4 * 3600;
    n_played = 0;
    uint32_t s2 = wheel[1] & BRAIN_WHEEL_LIST ? wheel[2] : wheel[1];
    brain_radio_seed(s2);
    brain_log(s2, EV_PLAY, 0, now);
    step(s2, BRAIN_OUT_SKIP, 0.2f);
    snprintf(want, sizeof want, "on the radio for %s", title(s2));
    expect(!strcmp(why, want), "still its radio, steered off it");

    puts("the radio laid out ahead (brain_plan):");
    now += 4 * 3600;
    n_played = 0;
    uint32_t s3 = brain_wheel_song(wheel[0]);
    brain_radio_seed(s3);
    brain_log(s3, EV_PLAY, 0, now);
    uint32_t plan[25], more[25];
    int got = brain_plan(s3, played, 0, NULL, 0, BRAIN_OUT_COMPLETE, 0.0f, now, plan, 25, why, sizeof why);
    int dup = 0;
    for (int i = 0; i < got; i++) {
        dup += plan[i] == s3;
        for (int j = 0; j < i; j++) dup += plan[i] == plan[j];
    }
    printf("  %d planned for %s: %s, %s, %s ...\n", got, title(s3), got > 0 ? title(plan[0]) : "-",
           got > 1 ? title(plan[1]) : "-", got > 2 ? title(plan[2]) : "-");
    expect(got == 25 && !dup, "25 songs, no repeats, not the seed");
    int more_n = brain_plan(s3, played, 0, plan, got, BRAIN_OUT_COMPLETE, 0.0f, now, more, 10, why, sizeof why);
    int again = 0;
    for (int i = 0; i < more_n; i++) for (int j = 0; j < got; j++) again += more[i] == plan[j];
    expect(more_n > 0 && !again, "topped up after them: none of those again");

    puts("the Wheel: a song you keep starting climbs:");
    now = (double)time(NULL) + 86400.0;            /* a day after the export (picks before it are in it) */
    uint32_t w[64];
    int nw = brain_wheel(w, 64, now);
    uint32_t low = w[nw - 1];
    for (int k = 0; k < 4; k++) brain_wheel_pick(low, now - k * 3600.0);
    brain_wheel(w, 64, now);
    expect(w[0] == low, "four starts today: at the top");

    remove(plays);
    printf("%s\n", fails ? "FAILED" : "all ok");
    return fails ? 1 : 0;
}
