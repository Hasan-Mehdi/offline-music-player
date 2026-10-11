/* Speed-dial ("listen again") ranking — port of server.py /api/speeddial.
 * Frequency mode: recency-weighted event scores over the last ~8 days, net-
 * positive tracks best-first, soft per-artist cap 3. Fresh mode (the Wheel):
 * lead with the most-recent distinct play/complete/like tracks (cap 5), then
 * fill with the frequency ranking, then pad with recents and random tracks.
 *
 * Known deviation from the web server: the per-artist cap keys on the interned
 * artist string (exact bytes) instead of Python str.lower(), so two artists
 * differing only in letter case count separately. */
#ifndef OMP_SPEEDDIAL_H
#define OMP_SPEEDDIAL_H

#include "omp_brain.h"

/* Fill out[] with up to n_out track indices. Returns the count. rng is used
 * only for the final random padding (pass NULL to skip that stage). */
int omp_speeddial(omp_pack *pack, const omp_play *plays, int n_plays,
                  double now, int n_out, int fresh,
                  omp_rng01 rng, void *rng_state, uint32_t *out);

#endif
