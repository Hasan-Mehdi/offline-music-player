/* Letter-by-letter search over the card's SRC1 index (scripts/h2_crates.py build_search).
 * Tiers follow the web player's /api/search: every typed word as a word prefix (AND) >
 * any word (OR) > substring, then a personal boost for what you play and query-shape
 * boosts (title / artist starts with what you typed). Streamed from the card; only the
 * per-track play counts sit in RAM. */
#ifndef CODA_SEARCH_H
#define CODA_SEARCH_H

#include <stdint.h>

#define SEARCH_MAX 100
#define SEARCH_ARTIST_HIT 1u           /* flags: the artist name starts with the query */

typedef struct { uint32_t idx; int32_t score; uint32_t flags; } search_hit;

int search_ready(void);                 /* opens search.bin on first use; 0 if missing */
/* q: lower-case a-z 0-9 and spaces (what the letter rail can type) */
int search_run(const char *q, search_hit *hits, int cap);

#endif
