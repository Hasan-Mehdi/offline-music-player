/* Autoplay simulator — runs the EXACT device brain over the real pack on the
 * PC: seeds at a track, walks N steps, logging each pick with its score
 * breakdown; simulated listens (complete / periodic skips) feed back into the
 * preference state so you can watch taste/skip/fatigue shape the walk.
 *
 * usage: sim_autoplay <pack_dir> [--seed VIDEO_ID] [--steps N] [--skip-every K]
 *                     [--rng SEED] [--stream]
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "omp_brain.h"
#include "omp_gain.h"
#include "omp_speeddial.h"

#define MAX_STEPS 500
#define TAIL 50                    /* web client sends the last 50 queue ids */

static uint64_t rng_state;
static double rng01(void *s)
{
    (void)s;
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return (double)(rng_state >> 11) * (1.0 / 9007199254740992.0);
}

static const char *reason_str(omp_pick_reason r)
{
    switch (r) {
    case OMP_PICK_EXPLOIT: return "exploit";
    case OMP_PICK_EXPLORE_UNHEARD: return "explore-unheard";
    case OMP_PICK_EXPLORE_RANDOM: return "explore-random";
    case OMP_PICK_FALLBACK_GENRE: return "fallback-genre";
    default: return "fallback-random";
    }
}

int main(int argc, char **argv)
{
    const char *seed_id = NULL;
    int steps = 25, skip_every = 0;
    omp_pack_mode mode = OMP_PACK_LOAD_ALL;
    rng_state = 0x9E3779B97F4A7C15ull;
    if (argc < 2) { printf("usage: sim_autoplay <pack_dir> [options]\n"); return 2; }
    for (int i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "--seed") && i + 1 < argc) seed_id = argv[++i];
        else if (!strcmp(argv[i], "--steps") && i + 1 < argc) steps = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--skip-every") && i + 1 < argc) skip_every = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--rng") && i + 1 < argc) rng_state = (uint64_t)atoll(argv[++i]) | 1u;
        else if (!strcmp(argv[i], "--stream")) mode = OMP_PACK_STREAM;
    }
    if (steps > MAX_STEPS) steps = MAX_STEPS;

    omp_pack pack;
    if (omp_pack_open(&pack, argv[1], mode) != 0) { printf("pack open failed\n"); return 2; }

    uint32_t cur;
    if (seed_id && strlen(seed_id) == 11) {
        cur = omp_pack_find_id(&pack, seed_id);
        if (cur == UINT32_MAX) { printf("seed id not in pack\n"); return 2; }
    } else {
        cur = (uint32_t)(rng01(NULL) * pack.n) % pack.n;
    }

    omp_play log[MAX_STEPS * 2 + 2];
    int n_log = 0;
    uint32_t played[MAX_STEPS + 1];
    int n_played = 0;
    double clock = 1784000000.0;
    omp_ranked *ranked = malloc((size_t)pack.k * sizeof *ranked);

    printf("mode=%s  seed: %s — %s\n\n", mode == OMP_PACK_STREAM ? "stream" : "load_all",
           omp_pack_str(&pack, pack.tracks[cur].artist_off),
           omp_pack_str(&pack, pack.tracks[cur].title_off));

    for (int step = 0; step < steps; step++) {
        /* listen to `cur` (skip every k-th step at 8%, else complete at 90%) */
        const omp_track *tc = &pack.tracks[cur];
        double dur = tc->duration_s ? tc->duration_s : 180;
        int skipped = skip_every && (step % skip_every) == skip_every - 1;
        omp_play ev = { clock, cur, -1.0f, OMP_EV_PLAY };
        log[n_log++] = ev;
        clock += skipped ? dur * 0.08 : dur * 0.9;
        ev.ts = clock;
        ev.seconds = (float)(skipped ? dur * 0.08 : dur * 0.9);
        ev.event = skipped ? OMP_EV_SKIP : OMP_EV_COMPLETE;
        log[n_log++] = ev;
        clock += 2.0;
        played[n_played++] = cur;

        /* recompute the personalization state (the device would cache this) */
        omp_prefs prefs;
        float taste[OMP_DIM], skipv[OMP_DIM];
        omp_prefs_compute(&pack, log, n_log, clock, OMP_HALFLIFE_DAYS, &prefs);
        int ht = omp_taste_centroid(&pack, &prefs, taste);
        int hs = omp_skip_centroid(&pack, &prefs, skipv);

        const uint32_t *tail = played + (n_played > TAIL ? n_played - TAIL : 0);
        int n_tail = n_played > TAIL ? TAIL : n_played;
        omp_pick_reason reason;
        int n_ranked = 0;
        uint32_t pick = omp_next_track(&pack, &prefs, ht ? taste : NULL,
                                       hs ? skipv : NULL, tail, n_tail, cur,
                                       0.15, rng01, NULL, &reason, ranked, &n_ranked);
        if (pick == UINT32_MAX) { printf("dead end\n"); break; }

        const omp_ranked *pr = NULL;
        for (int i = 0; i < n_ranked; i++)
            if (ranked[i].idx == pick) { pr = &ranked[i]; break; }
        const omp_track *tp = &pack.tracks[pick];
        printf("%2d. %s%s — %s\n", step + 1, skipped ? "[skipped prev] " : "",
               omp_pack_str(&pack, tp->artist_off), omp_pack_str(&pack, tp->title_off));
        if (pr)
            printf("      score %+0.3f  (vibe %+0.2f mood %+0.2f taste %+0.2f fatigue %+0.2f "
                   "cooldown %+0.2f novelty %+0.2f)  gain x%0.2f  cand %d  %s\n",
                   pr->score, pr->terms[OMP_T_VIBE], pr->terms[OMP_T_MOOD],
                   pr->terms[OMP_T_TASTE], pr->terms[OMP_T_FATIGUE],
                   pr->terms[OMP_T_COOLDOWN], pr->terms[OMP_T_NOVELTY],
                   omp_gain_mult(tp->gain_q78), n_ranked, reason_str(reason));
        omp_prefs_free(&prefs);
        cur = pick;
    }

    /* wheel preview: what the speed-dial would show after this session */
    uint32_t dial[12];
    int nd = omp_speeddial(&pack, log, n_log, clock, 12, 1, rng01, NULL, dial);
    printf("\nwheel (fresh speed-dial) after session:\n");
    for (int i = 0; i < nd; i++)
        printf("  %2d. %s — %s\n", i + 1,
               omp_pack_str(&pack, pack.tracks[dial[i]].artist_off),
               omp_pack_str(&pack, pack.tracks[dial[i]].title_off));

    free(ranked);
    omp_pack_close(&pack);
    return 0;
}
