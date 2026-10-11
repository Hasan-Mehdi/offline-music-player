#include "search.h"
#include <string.h>
#include "../plat/plat.h"

#define CAND 4096                 /* candidate table (open addressing, power of two) */
#define POST_BUDGET 24000         /* postings read per typed word */
#define REFINE 160                /* candidates re-scored against their folded text */
#define MAX_TOK 6

static struct {
    int tried, fd;
    uint32_t n_words, n_post, n_tracks;
    uint32_t tab_off, post_off, fold_off_off, words_off, fold_off;
    uint32_t fold_len;
    uint16_t *plays;
} S;

typedef struct { uint32_t idx; uint16_t mask; uint8_t fields, used; int32_t score; } cand;
static cand C[CAND];
static int n_cand;

static uint32_t rd32(const uint8_t *b) { return b[0] | (b[1] << 8) | (b[2] << 16) | ((uint32_t)b[3] << 24); }

int search_ready(void)
{
    if (S.tried) return S.fd >= 0;
    S.tried = 1;
    S.fd = plat_open("search.bin");
    if (S.fd < 0) return 0;
    uint8_t h[24];
    if (plat_pread(S.fd, h, 24, 0) != 24 || memcmp(h, "SRC1", 4)) {
        plat_log("search.bin: not SRC1");
        plat_close(S.fd);
        S.fd = -1;
        return 0;
    }
    S.n_words = rd32(h + 4); S.n_post = rd32(h + 8); S.n_tracks = rd32(h + 12);
    uint32_t words_len = rd32(h + 16);
    S.fold_len = rd32(h + 20);
    S.tab_off = 24;
    S.post_off = S.tab_off + 12 * S.n_words;
    uint32_t plays_off = S.post_off + 4 * S.n_post;
    S.fold_off_off = plays_off + 2 * S.n_tracks + (S.n_tracks & 1 ? 2 : 0);
    S.words_off = S.fold_off_off + 4 * S.n_tracks;
    S.fold_off = S.words_off + words_len;
    S.plays = plat_alloc(2 * (S.n_tracks + 1));
    if (S.plays) {
        uint8_t *b = (uint8_t *)S.plays;
        plat_pread(S.fd, b, (int)(2 * S.n_tracks), plays_off);
        for (uint32_t i = 0; i < S.n_tracks; i++) S.plays[i] = (uint16_t)(b[2 * i] | (b[2 * i + 1] << 8));
    }
    return 1;
}

/* ------------------------------------------------------------------ word table */
static int word_at(uint32_t i, char *buf, int cap, uint32_t *post_first, uint32_t *post_n)
{
    uint8_t e[12];
    if (plat_pread(S.fd, e, 12, S.tab_off + 12 * i) != 12) return -1;
    if (post_first) *post_first = rd32(e + 4);
    if (post_n) *post_n = rd32(e + 8);
    int got = plat_pread(S.fd, buf, cap - 1, S.words_off + rd32(e));
    if (got < 0) got = 0;
    buf[got] = 0;
    return 0;
}

static uint32_t lower_bound(const char *key)
{
    uint32_t lo = 0, hi = S.n_words;
    char w[40];
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        if (word_at(mid, w, sizeof w, NULL, NULL) != 0) return hi;
        if (strcmp(w, key) < 0) lo = mid + 1; else hi = mid;
    }
    return lo;
}

/* ------------------------------------------------------------------ candidates */
static cand *slot(uint32_t idx, int create)
{
    uint32_t h = (idx * 2654435761u) & (CAND - 1);
    for (int probe = 0; probe < CAND; probe++, h = (h + 1) & (CAND - 1)) {
        if (!C[h].used) {
            if (!create || n_cand >= CAND * 3 / 4) return NULL;
            C[h].used = 1; C[h].idx = idx; C[h].mask = 0; C[h].fields = 0; C[h].score = 0;
            n_cand++;
            return &C[h];
        }
        if (C[h].idx == idx) return &C[h];
    }
    return NULL;
}

/* every posting of every word starting with tok marks bit `bit` (adding new candidates
 * only when `add`) */
static void gather(const char *tok, int bit, int add)
{
    char next[40];
    size_t len = strlen(tok);
    if (!len || len >= sizeof next) return;
    memcpy(next, tok, len + 1);
    next[len - 1]++;                        /* first key past the prefix range */
    uint32_t lo = lower_bound(tok), hi = lower_bound(next), budget = POST_BUDGET;
    static uint8_t tab[12 * 64];
    static uint8_t pb[4 * 512];
    for (uint32_t w = lo; w < hi && budget; ) {
        uint32_t nw = hi - w > 64 ? 64 : hi - w;
        if (plat_pread(S.fd, tab, (int)(12 * nw), S.tab_off + 12 * w) != (int)(12 * nw)) return;
        for (uint32_t k = 0; k < nw && budget; k++) {
            uint32_t first = rd32(tab + 12 * k + 4), cnt = rd32(tab + 12 * k + 8);
            if (cnt > budget) cnt = budget;
            budget -= cnt;
            for (uint32_t off = 0; off < cnt; ) {
                uint32_t m = cnt - off > 512 ? 512 : cnt - off;
                if (plat_pread(S.fd, pb, (int)(4 * m), S.post_off + 4 * (first + off)) != (int)(4 * m)) return;
                for (uint32_t j = 0; j < m; j++) {
                    uint32_t p = rd32(pb + 4 * j);
                    cand *c = slot(p >> 2, add);
                    if (!c) continue;
                    c->mask |= (uint16_t)(1u << bit);
                    c->fields |= (uint8_t)(1u << (p & 3));
                }
                off += m;
            }
        }
        w += nw;
    }
}

/* substring tier: scan the folded text of every track */
static void substring_scan(const char *q)
{
    static char buf[16384 + 4096];
    uint32_t track = 0, pos = 0;
    size_t carry = 0;
    while (pos < S.fold_len && track < S.n_tracks) {
        int want = (int)(S.fold_len - pos > 16384 ? 16384 : S.fold_len - pos);
        int got = plat_pread(S.fd, buf + carry, want, S.fold_off + pos);
        if (got <= 0) break;
        size_t n = carry + (size_t)got;
        /* walk record by record; a record cut by the chunk end is carried over */
        size_t rec = 0;
        for (size_t i = 0; i < n; i++) {
            if (buf[i]) continue;
            const char *r = buf + rec;
            if (strstr(r, q)) {
                cand *c = slot(track, 1);
                if (c) c->mask |= 0x8000;
            }
            track++;
            rec = i + 1;
        }
        carry = n - rec;
        memmove(buf, buf + rec, carry);
        pos += (uint32_t)got;
        if (carry > 4096) carry = 0;        /* absurd record: drop it */
    }
}

static int fold_text(uint32_t idx, char *out, int cap)
{
    uint8_t b[4];
    if (plat_pread(S.fd, b, 4, S.fold_off_off + 4 * idx) != 4) return -1;
    int got = plat_pread(S.fd, out, cap - 1, S.fold_off + rd32(b));
    if (got <= 0) return -1;
    out[got] = 0;
    return 0;
}

static int starts_with(const char *s, const char *p) { return strncmp(s, p, strlen(p)) == 0; }

static int boost_plays(uint32_t idx)
{
    /* = server.search: min(3, 1 + 0.6 * log2(1 + n)), x100 */
    uint32_t n = S.plays && idx < S.n_tracks ? S.plays[idx] : 0;
    if (!n) return 0;
    int lg = 0;
    for (uint32_t v = n + 1; v > 1; v >>= 1) lg++;
    int b = 100 + 60 * lg;
    return b > 300 ? 300 : b;
}

static void sort_desc(search_hit *h, int n)
{
    for (int i = 1; i < n; i++) {
        search_hit x = h[i];
        int j = i - 1;
        while (j >= 0 && h[j].score < x.score) { h[j + 1] = h[j]; j--; }
        h[j + 1] = x;
    }
}

int search_run(const char *q, search_hit *hits, int cap)
{
    if (!search_ready() || !q) return 0;
    char toks[MAX_TOK][40];
    int nt = 0;
    for (const char *s = q; *s && nt < MAX_TOK; ) {
        while (*s == ' ') s++;
        int l = 0;
        while (*s && *s != ' ') { if (l < 39) toks[nt][l++] = *s; s++; }
        if (l) { toks[nt][l] = 0; nt++; }
    }
    if (!nt) return 0;
    char ql[64];
    int qn = 0;                              /* the query, single-spaced */
    for (int t = 0; t < nt; t++) {
        for (const char *s = toks[t]; *s && qn < 62; s++) ql[qn++] = *s;
        if (t < nt - 1 && qn < 62) ql[qn++] = ' ';
    }
    ql[qn] = 0;

    memset(C, 0, sizeof C);
    n_cand = 0;
    for (int t = 0; t < nt; t++) gather(toks[t], t, 1);
    uint16_t all = (uint16_t)((1u << nt) - 1);
    int n_and = 0;
    for (int i = 0; i < CAND; i++) n_and += C[i].used && (C[i].mask & all) == all;
    if (n_and < 8 && qn >= 3) substring_scan(ql);

    /* cheap score for every candidate, keep the best REFINE */
    static search_hit pool[REFINE];
    int np = 0;
    for (int i = 0; i < CAND; i++) {
        cand *c = &C[i];
        if (!c->used || c->idx >= S.n_tracks) continue;
        int m = 0;
        for (int t = 0; t < nt; t++) m += (c->mask >> t) & 1;
        int32_t sc;
        if (m == nt) sc = 1000;                      /* all words as prefixes */
        else if (m > 0 && nt > 1) sc = 600;          /* some of them */
        else if (c->mask & 0x8000) sc = 400;         /* substring */
        else continue;
        sc += 80 * m + boost_plays(c->idx);
        if (c->fields & 2) sc += 50;                 /* matched an artist word */
        search_hit h = { c->idx, sc, 0 };
        if (np < REFINE) pool[np++] = h;
        else {
            int worst = 0;
            for (int k = 1; k < np; k++) if (pool[k].score < pool[worst].score) worst = k;
            if (sc > pool[worst].score) pool[worst] = h;
        }
    }
    /* query-shape boosts against the folded title / artist */
    for (int k = 0; k < np; k++) {
        char f[256];
        if (fold_text(pool[k].idx, f, sizeof f) != 0) continue;
        char *artist = strchr(f, 1), *album = NULL;
        if (artist) { *artist++ = 0; album = strchr(artist, 1); if (album) *album = 0; }
        if (starts_with(f, ql)) pool[k].score += 400;
        if (artist && starts_with(artist, ql)) { pool[k].score += 300; pool[k].flags |= SEARCH_ARTIST_HIT; }
        int every = 1;
        for (int t = 0; t < nt && every; t++)
            every = strstr(f, toks[t]) || (artist && strstr(artist, toks[t]));
        if (every) pool[k].score += 150;
    }
    sort_desc(pool, np);
    int n = np < cap ? np : cap;
    memcpy(hits, pool, sizeof *hits * (size_t)n);
    return n;
}
