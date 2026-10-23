/* Games: Library > Games (part of app.c, included after the themes). Two games played
 * next to the music, after docs/h2/games (firmware/tools/mock_games.py is the reference):
 *
 *   Beat Orbit     rings close in on the playing song's beat -- its tempo from the card's
 *                  pack, the beat itself heard in the bass -- and you live on a ring round
 *                  the song's cover. The wheel moves you round it, Prev/Next dash to the far
 *                  side, Play pauses. Last as long as you can.
 *   Fishing Hole   Bubloo on the dock. Play casts; when the float goes under, turn the wheel
 *                  to hook and reel -- too fast and the line snaps, too slow and it slips
 *                  the hook. Every catch is a song you've never played by an artist you
 *                  play a lot: Play listens now, Next puts it next, Back lets it go.
 *
 * The X1000 has no FPU, so what's per pixel is integer: Beat Orbit's rings are one pass
 * over a radius / angle table, the pond is a cached picture with what moves drawn over it.
 * Records (the longest orbit, the songs caught) are kept in /.coda/games.txt. */

enum { GM_ORBIT, GM_FISH, GM_N };

static struct {
    int which, loaded;
    uint32_t orbit_best_ms;            /* the longest Beat Orbit run */
    int fish_total;                    /* songs caught, ever */
    uint32_t last_ms, drawn_ms;        /* the game's clock; the last frame drawn */
} gm;

static int game_sec(void) { return gm.which == GM_FISH ? SEC_FISH : SEC_ORBIT; }

static void game_load(void)
{
    if (gm.loaded) return;
    gm.loaded = 1;
    size_t n = 0;
    const char *s = plat_load("games.txt", &n);
    if (!s) return;
    char buf[256];
    size_t m = n < sizeof buf - 1 ? n : sizeof buf - 1;
    memcpy(buf, s, m);
    buf[m] = 0;
    for (char *line = buf; line && *line;) {
        char *nl = strchr(line, '\n');
        if (nl) *nl = 0;
        char *eq = strchr(line, '=');
        if (eq) {
            *eq = 0;
            long v = strtol(eq + 1, NULL, 10);
            if (v < 0) v = 0;
            if (!strcmp(line, "orbit_best")) gm.orbit_best_ms = (uint32_t)v;
            else if (!strcmp(line, "fish_total")) gm.fish_total = (int)v;
        }
        line = nl ? nl + 1 : NULL;
    }
}

static void game_save(void)
{
    char buf[96];
    int n = snprintf(buf, sizeof buf, "orbit_best=%u\nfish_total=%d\n", (unsigned)gm.orbit_best_ms,
                     gm.fish_total);
    if (n > 0) plat_save("games.txt", buf, (size_t)n);
}

/* the Games page's two panels say these */
static void game_stats(char *orbit, size_t no, char *fish, size_t nf)
{
    game_load();
    if (gm.orbit_best_ms) {
        unsigned s = gm.orbit_best_ms / 1000;
        snprintf(orbit, no, "best %u:%02u", s / 60, s % 60);
    } else snprintf(orbit, no, "rings on the beat");
    if (gm.fish_total) snprintf(fish, nf, "%d caught", gm.fish_total);
    else snprintf(fish, nf, "songs you've never played");
}

/* a tilted slab with a hard ink shadow (Sakurai's), its text centred; s scales it in */
static void gm_slab(app *a, gfx *g, int cx, int cy, const char *s, int f, px16 bg, px16 fg, float k)
{
    int w = text_w(F(a, f), s, T_TRACK(-3)) + 22, h = f == F_POSTER22 ? 34 : f == F_POSTER18 ? 30 : 26;
    float hw = w * k / 2, hh = h * k / 2, lean = .09f * h * k;
    if (hw < 1) return;
    for (int pass = 0; pass < 2; pass++) {
        float o = pass ? 0 : 3;
        int32_t xy[8] = { (int32_t)((cx - hw + lean + o) * 16), (int32_t)((cy - hh + o) * 16),
                          (int32_t)((cx + hw + lean + o) * 16), (int32_t)((cy - hh + o) * 16),
                          (int32_t)((cx + hw - lean + o) * 16), (int32_t)((cy + hh + o) * 16),
                          (int32_t)((cx - hw - lean + o) * 16), (int32_t)((cy + hh + o) * 16) };
        g_convex(g, xy, 4, pass ? bg : P(a)->ink);
    }
    if (k > .85f) {
        int tw = text_w(F(a, f), s, T_TRACK(-3));
        int base = f == F_POSTER22 ? 8 : f == F_POSTER18 ? 7 : 6;
        txt(a, g, f, cx - tw / 2, cy + base, s, fg, T_TRACK(-3));
    }
}

static float gm_rand01(uint32_t *s)
{
    *s ^= *s << 13;
    *s ^= *s >> 17;
    *s ^= *s << 5;
    return (*s >> 8) / 16777216.0f;
}

/* ================================================================== Beat Orbit */
#define OB_CX 160
#define OB_CY 124
#define OB_TOP 36                       /* the header band above the arena */
#define OB_RP 34                        /* your ring */
#define OB_RC 21                        /* the song in the middle */
#define OB_FAR 214                      /* where the rings start: past the corners */
#define OB_WALL 8
#define OB_STEPS 24                     /* wheel detents to go round once */
#define OB_NW 12
#define OB_QW 160                       /* the radius / angle table: one quarter, mirrored */
#define OB_QH 124
#define A_RAD 10430.378f                /* angle units (65536 a turn) per radian */

enum { OB_READY, OB_RUN, OB_PAUSE, OB_OVER };

typedef struct { float t0, speed; uint16_t gap[3], half; uint8_t n, live, hit; } ob_wave;

static struct {
    int state;
    float t, beat_t, period, pulse_t, over_t, dash_t, dash_from;
    int beats, rings, new_best, spiral, spiral_dir;
    float pos, shown;                    /* steps round the ring, any real (taken mod OB_STEPS) */
    ob_wave w[OB_NW];
    uint32_t song, rng;
    float bass_avg, last_onset;
    uint16_t last_gap;
    uint16_t *lr, *la;                   /* per quarter pixel: radius (Q4), angle from the vertical */
} ob;

static void ob_table(void)
{
    if (ob.lr) return;
    ob.lr = plat_alloc(sizeof(uint16_t) * OB_QW * OB_QH);
    ob.la = plat_alloc(sizeof(uint16_t) * OB_QW * OB_QH);
    if (!ob.lr || !ob.la) { ob.lr = ob.la = NULL; return; }
    for (int qy = 0; qy < OB_QH; qy++)
        for (int qx = 0; qx < OB_QW; qx++) {
            float dx = qx + .5f, dy = qy + .5f;
            ob.lr[qy * OB_QW + qx] = (uint16_t)(sqrtf(dx * dx + dy * dy) * 16 + .5f);
            ob.la[qy * OB_QW + qx] = (uint16_t)(datan2(dx, dy) * A_RAD);
        }
}

/* the song's beat in seconds: its tempo from the pack, folded into 80..165 BPM */
static float ob_period(uint32_t song)
{
    float bpm = song == LIB_NONE ? 0 : brain_bpm10(song) / 10.0f;
    if (bpm < 40) bpm = 120;
    while (bpm < 80) bpm *= 2;
    while (bpm > 165) bpm /= 2;
    return 60.0f / bpm;
}

static uint16_t ob_angle(float steps) { return (uint16_t)(int32_t)(steps * (65536.0f / OB_STEPS)); }

static void ob_reset(app *a)
{
    uint16_t *lr = ob.lr, *la = ob.la;
    uint32_t rng = ob.rng ? ob.rng : 0x9E3779B9u ^ a->now_ms;
    memset(&ob, 0, sizeof ob);
    ob.lr = lr;
    ob.la = la;
    ob.rng = rng ? rng : 1;
    ob.song = a->cur_valid ? a->cur : LIB_NONE;
    ob.period = ob_period(ob.song);
    ob.beat_t = ob.period;
    ob.last_onset = -10;
}

/* a new ring: where its gaps go, so there is always a way through */
static void ob_spawn(void)
{
    ob_wave *w = NULL;
    for (int i = 0; i < OB_NW; i++)
        if (!ob.w[i].live) { w = &ob.w[i]; break; }
    if (!w) return;
    float d = ob.t / 100.0f;
    if (d > 1) d = 1;
    int every = ob.period < .42f ? 2 : 1;
    float gap_s = every * ob.period;                       /* time to the next ring */
    float travel = (4.2f - 1.4f * d) * gap_s;              /* edge to your ring */
    memset(w, 0, sizeof *w);
    w->t0 = ob.t;
    w->speed = (OB_FAR - OB_RP) / travel;
    w->live = 1;
    float half = .62f - .18f * d, r = gm_rand01(&ob.rng);
    uint16_t g = ob.last_gap;
    const uint16_t DEG = 182;                              /* a degree, in angle units */
    if (ob.spiral > 0) {
        g = (uint16_t)(g + ob.spiral_dir * 48 * DEG);
        ob.spiral--;
        w->n = 1;
    } else if (ob.t > 12 && r < .12f) {                    /* across: a dash */
        g = (uint16_t)(g + 32768);
        w->n = 1;
    } else if (r < .30f) {                                 /* two, opposite */
        g = (uint16_t)(g + (int)((gm_rand01(&ob.rng) * 120 - 60) * DEG));
        w->n = 2;
    } else if (d > .35f && r < .42f) {                     /* a spiral: the same way, ring after ring */
        ob.spiral = 2 + (int)(gm_rand01(&ob.rng) * 3);
        ob.spiral_dir = gm_rand01(&ob.rng) < .5f ? -1 : 1;
        g = (uint16_t)(g + ob.spiral_dir * 48 * DEG);
        w->n = 1;
    } else if (d > .5f && r < .52f) {                      /* three, narrower */
        g = (uint16_t)(g + (int)((gm_rand01(&ob.rng) * 80 - 40) * DEG));
        w->n = 3;
        half *= .72f;
    } else {                                               /* a step, as far as you can turn in time */
        float most = gap_s * 200;                          /* <= ~8 detents a second past the gap's edge */
        if (most < 40) most = 40;
        if (most > 100) most = 100;
        g = (uint16_t)(g + (int)((gm_rand01(&ob.rng) * 2 - 1) * most * DEG));
        w->n = 1;
    }
    w->half = (uint16_t)(half * A_RAD);
    for (int k = 0; k < w->n; k++) w->gap[k] = (uint16_t)(g + k * (65536 / w->n));
    ob.last_gap = g;
}

static void ob_beat(void)
{
    ob.beats++;
    ob.pulse_t = ob.t;
    int every = ob.period < .42f ? 2 : 1;
    if (ob.beats > 2 && ob.beats % every == 0) ob_spawn();
}

/* inside one of the ring's gaps at angle a (with a little give at the edges) */
static int ob_through(const ob_wave *w, uint16_t a)
{
    for (int k = 0; k < w->n; k++) {
        int d = (int16_t)(uint16_t)(a - w->gap[k]);
        if (d < 0) d = -d;
        if (d < (int)w->half - 700) return 1;
    }
    return 0;
}

static void ob_over(void)
{
    ob.state = OB_OVER;
    ob.over_t = ob.t;
    uint32_t ms = (uint32_t)(ob.t * 1000);
    ob.new_best = ms > gm.orbit_best_ms;
    if (ob.new_best) { gm.orbit_best_ms = ms; game_save(); }
}

static void ob_tick(app *a, float dt)
{
    if (ob.state != OB_RUN) return;
    /* the song: its tempo when it changes; its beat, heard in the bass */
    uint32_t song = a->cur_valid ? a->cur : LIB_NONE;
    if (song != ob.song) { ob.song = song; ob.period = ob_period(song); }
    uint8_t b[12];
    if (a->cur_valid && a->ps.playing && plat_spectrum(b)) {
        float bass = (float)b[0] + b[1] + b[2];
        if (bass > ob.bass_avg + 36 && ob.t - ob.last_onset > ob.period * .5f) {
            ob.last_onset = ob.t;
            float f = (ob.beat_t - ob.t) / ob.period;
            f -= floorf(f + .5f);                          /* -0.5..0.5 beats off the grid */
            if (f > -.35f && f < .35f) ob.beat_t -= f * ob.period * .3f;
        }
        ob.bass_avg += (bass - ob.bass_avg) * .08f;
    }
    /* in steps of at most 20 ms, so no ring goes through you between two frames */
    int n = (int)(dt / .02f) + 1;
    float h = dt / n;
    for (int s = 0; s < n && ob.state == OB_RUN; s++) {
        ob.t += h;
        while (ob.t >= ob.beat_t) { ob_beat(); ob.beat_t += ob.period; }
        uint16_t you = ob_angle(ob.pos);
        for (int i = 0; i < OB_NW; i++) {
            ob_wave *w = &ob.w[i];
            if (!w->live) continue;
            float ri = OB_FAR - w->speed * (ob.t - w->t0);
            if (ri + OB_WALL < OB_RP - 2) { w->live = 0; ob.rings++; continue; }
            if (ri < OB_RP + 10 && ri + OB_WALL > OB_RP + 3 && !ob_through(w, you)) {
                w->hit = 1;
                ob_over();
                break;
            }
        }
    }
    float k = 1 - expf(-dt / .035f);
    ob.shown += (ob.pos - ob.shown) * k;
    if (fabsf(ob.pos - ob.shown) < .01f) ob.shown = ob.pos;
}

static void ob_event(app *a, ui_ev e)
{
    switch (e.k) {
    case K_SCROLL:
        if (ob.state == OB_RUN) ob.pos += e.d;
        break;
    case K_PREV: case K_NEXT:
        if (ob.state == OB_RUN) {
            ob.dash_from = ob.shown;
            ob.dash_t = ob.t;
            ob.pos += e.k == K_NEXT ? OB_STEPS / 2 : -OB_STEPS / 2;
            ob.shown = ob.pos;                             /* a dash is instant; the smear shows it */
        }
        break;
    case K_PLAY:
        if (ob.state == OB_RUN) ob.state = OB_PAUSE;
        else if (ob.state == OB_PAUSE) ob.state = OB_RUN;
        else if (ob.state == OB_READY || ob.state == OB_OVER) {
            ob_reset(a);
            ob.state = OB_RUN;
        }
        break;
    default:
        break;
    }
    if (ob.pos >= OB_STEPS || ob.pos < 0) {                /* keep it small: floats lose steps far out */
        float w = floorf(ob.pos / OB_STEPS) * OB_STEPS;
        ob.pos -= w;
        ob.shown -= w;
        ob.dash_from -= w;
    }
}

/* the arena: the six slow sectors, the rings (anti-aliased edges), your ring -- one
 * integer pass over the screen above the now bar */
static void ob_arena(app *a, gfx *g)
{
    const palette *p = P(a);
    const px16 bg0 = p->paper, bg1 = mix565(p->paper, p->rule, 120);
    const px16 wall = p->ink, hitc = p->red, line = p->sub;
    int8_t wat[256];
    int32_t wi[OB_NW], wo[OB_NW];
    memset(wat, -1, sizeof wat);
    for (int i = 0; i < OB_NW; i++) {
        const ob_wave *w = &ob.w[i];
        if (!w->live) continue;
        float ri = OB_FAR - w->speed * (ob.t - w->t0);
        wi[i] = (int32_t)(ri * 16);
        wo[i] = wi[i] + OB_WALL * 16;
        int r0 = (int)ri - 1, r1 = (int)ri + OB_WALL + 1;
        if (r0 < 0) r0 = 0;
        if (r1 > 255) r1 = 255;
        for (int r = r0; r <= r1; r++) wat[r] = (int8_t)i;
    }
    uint16_t rot = (uint16_t)(int32_t)(ob.t * .35f * A_RAD);
    const int32_t RPQ = OB_RP * 16;
    for (int y = 0; y < BAR_Y; y++) {
        int up = y < OB_CY, qy = up ? OB_CY - 1 - y : y - OB_CY;
        if (qy >= OB_QH) qy = OB_QH - 1;
        const uint16_t *LR = ob.lr + qy * OB_QW, *LA = ob.la + qy * OB_QW;
        px16 *row = g->px + y * g->stride;
        for (int x = 0; x < LCD_W; x++) {
            int right = x >= OB_CX, qx = right ? x - OB_CX : OB_CX - 1 - x;
            int32_t r = LR[qx];
            uint16_t aq = LA[qx], ang;
            if (right) ang = up ? aq : (uint16_t)(32768 - aq);
            else ang = up ? (uint16_t)(0 - aq) : (uint16_t)(32768 + aq);
            px16 c = ((((uint32_t)(uint16_t)(ang - rot)) * 6u) >> 16) & 1 ? bg1 : bg0;
            int rp = r >> 4;
            if (rp < 256 && wat[rp] >= 0) {
                int k = wat[rp];
                int32_t cr = r - wi[k] + 8, co = wo[k] - r + 8;
                if (co < cr) cr = co;
                if (cr > 16) cr = 16;
                if (cr > 0) {
                    const ob_wave *w = &ob.w[k];
                    int best = -32768;
                    for (int j = 0; j < w->n; j++) {
                        int d = (int16_t)(uint16_t)(ang - w->gap[j]);
                        if (d < 0) d = -d;
                        if ((int)w->half - d > best) best = (int)w->half - d;
                    }
                    int32_t ca = 16;
                    if (best > -2048) {
                        ca = 8 - best * r / 10430;          /* Q4 px into the gap */
                        if (ca < 0) ca = 0;
                        if (ca > 16) ca = 16;
                    }
                    if (ca < cr) cr = ca;
                    if (cr > 0) c = blend565(c, w->hit ? hitc : wall, cr * 16);
                }
            }
            int32_t dr = r - RPQ;
            if (dr < 0) dr = -dr;
            if (dr < 14) c = blend565(c, line, (14 - dr) * 14);
            row[x] = c;
        }
    }
}

static void ob_draw(app *a, gfx *g)
{
    const palette *p = P(a);
    if (!ob.lr) {                                       /* no memory for the table: say so */
        g_fill(g, 0, 0, LCD_W, BAR_Y, p->paper);
        txt(a, g, F_SEMI12, 8, 100, "Not enough memory for Beat Orbit.", p->ink, 0);
        draw_nowbar(a, g);
        return;
    }
    ob_arena(a, g);
    int run = ob.state == OB_RUN || ob.state == OB_PAUSE || ob.state == OB_OVER;
    /* the song in the middle, kicking on the beat */
    float since = ob.t - ob.pulse_t, kick = run && since >= 0 && since < .22f ? 1 - since / .22f : 0;
    int rc = (int)((OB_RC + 3 * kick) * 16);
    g_disc(g, OB_CX * 16 + 40, OB_CY * 16 + 40, rc, p->ink);
    const px16 *tex = a->cur_valid ? tex_get(a, a->cur, ART_M) : NULL;
    if (tex) g_disc_tex(g, OB_CX * 16, OB_CY * 16, rc, tex, art_px[ART_M]);
    else {
        g_disc(g, OB_CX * 16, OB_CY * 16, rc, p->ink);
        sym_draw(g, SYM_SONGS, OB_CX, OB_CY, 20, p->paper, p->ink, 0, 1);
    }
    /* a dash leaves a blue smear the way you went */
    float ds = ob.t - ob.dash_t;
    if (ob.dash_t > 0 && ds >= 0 && ds < .3f) {
        float to = ob.pos, from = ob.dash_from;
        px16 c = mix565(p->blue, p->paper, (int)(ds / .3f * 256));
        for (int i = 0; i <= 16; i++) {
            float s = from + (to - from) * i / 16, a1 = s / OB_STEPS * 6.2832f;
            g_disc(g, (int32_t)((OB_CX + sinf(a1) * (OB_RP + 7)) * 16), (int32_t)((OB_CY - cosf(a1) * (OB_RP + 7)) * 16),
                   (int32_t)((3.2f - ds * 8) * 16), c);
        }
    }
    /* you: a red wedge on the ring, pointing out */
    float an = ob.shown / OB_STEPS * 6.2832f, sa = sinf(an), ca = cosf(an);
    float tipx = OB_CX + sa * (OB_RP + 13), tipy = OB_CY - ca * (OB_RP + 13);
    float lx = OB_CX + sinf(an - .2f) * (OB_RP + 2), ly = OB_CY - cosf(an - .2f) * (OB_RP + 2);
    float rx = OB_CX + sinf(an + .2f) * (OB_RP + 2), ry = OB_CY - cosf(an + .2f) * (OB_RP + 2);
    for (int pass = 0; pass < 2; pass++) {
        float o = pass ? 0 : 1.5f;
        int32_t xy[6] = { (int32_t)((tipx + o) * 16), (int32_t)((tipy + o) * 16), (int32_t)((rx + o) * 16),
                          (int32_t)((ry + o) * 16), (int32_t)((lx + o) * 16), (int32_t)((ly + o) * 16) };
        g_convex(g, xy, 3, pass ? p->red : p->ink);
    }
    /* the header: the name, the time; the tempo and the rings under them */
    g_fill(g, 0, 0, LCD_W, OB_TOP, p->paper);
    g_fill(g, 0, OB_TOP, LCD_W, 1, p->rule);
    txt(a, g, F_POSTER15, 8, 19, "Beat Orbit", p->ink, T_TRACK(-3));
    char s[48], tm[16];
    uint32_t sec = run ? (uint32_t)ob.t : gm.orbit_best_ms / 1000;
    snprintf(tm, sizeof tm, "%u:%02u", (unsigned)(sec / 60), (unsigned)(sec % 60));
    if (!run && gm.orbit_best_ms) {
        int w = text_w(F(a, F_POSTER15), tm, T_TRACK(-3));
        txt(a, g, F_BODY10, LCD_W - 8 - w - 4 - text_w(F(a, F_BODY10), "best", 0), 19, "best", p->sub, 0);
    }
    if (run || gm.orbit_best_ms) {
        int w = text_w(F(a, F_POSTER15), tm, T_TRACK(-3));
        txt(a, g, F_POSTER15, LCD_W - 8 - w, 19, tm, p->ink, T_TRACK(-3));
    }
    int bpm = (int)(60.0f / ob_period(a->cur_valid ? a->cur : LIB_NONE) + .5f);
    if (a->cur_valid && a->ps.playing) snprintf(s, sizeof s, "%d bpm  %d rings", bpm, ob.rings);
    else snprintf(s, sizeof s, "no music: %d bpm  %d rings", bpm, ob.rings);
    txt(a, g, F_BODY10, 8, 31, s, p->sub, 0);
    /* what to do now (on a paper band, clear of the rings) */
    if (ob.state != OB_RUN) {
        g_fill(g, 0, 168, LCD_W, BAR_Y - 168, p->paper);
        g_fill(g, 0, 168, LCD_W, 1, p->rule);
    }
    switch (ob.state) {
    case OB_READY: {
        float k = ez_back(ez_seg((float)(a->now_ms - a->ui_t0), 0, 260), 1.70158f);
        gm_slab(a, g, OB_CX, 60, "Play to start", F_POSTER18, p->blue, p->paper, k);
        txt_center(a, g, F_SEMI12, OB_CX, 182, "The wheel moves you round. Get through the gaps.", 300, p->ink, 0);
        txt_center(a, g, F_BODY10, OB_CX, 198, "Prev / Next: dash to the far side.  Play: pause.", 300, p->sub, 0);
        break;
    }
    case OB_PAUSE:
        gm_slab(a, g, OB_CX, 66, "Paused", F_POSTER18, p->ink, p->paper, 1);
        txt_center(a, g, F_BODY10, OB_CX, 198, "Play: go on.  Back: leave.", 300, p->sub, 0);
        break;
    case OB_OVER: {
        uint32_t ms = (uint32_t)(ob.t * 1000);
        snprintf(s, sizeof s, "%u:%02u", (unsigned)(ms / 60000), (unsigned)(ms / 1000 % 60));
        gm_slab(a, g, OB_CX, 62, s, F_POSTER22, ob.new_best ? p->red : p->ink, p->paper, 1);
        if (ob.new_best) txt_center(a, g, F_SEMI12, OB_CX, 184, "Your longest yet.", 300, p->ink, 0);
        else {
            unsigned b = gm.orbit_best_ms / 1000;
            snprintf(s, sizeof s, "Your best is %u:%02u.", b / 60, b % 60);
            txt_center(a, g, F_SEMI12, OB_CX, 184, s, 300, p->ink, 0);
        }
        txt_center(a, g, F_BODY10, OB_CX, 198, "Play: again.  Back: leave.", 300, p->sub, 0);
        break;
    }
    default:
        break;
    }
    draw_nowbar(a, g);
}

/* ================================================================== the Fishing Hole */
#define FH_W 160                         /* the pond on the 2 x 2 grid, above the now bar */
#define FH_H (BAR_Y / 2)
#define FH_POOL 192
#define FH_ART 40

enum { FH_IDLE, FH_CAST, FH_WAIT, FH_BITE, FH_REEL, FH_CAUGHT, FH_LOST };

static struct {
    int state;
    float t, st_t, wait_for;
    float tension, dist, rate, slack_t, snap_t, strength, phase, surge_next, surge_until;
    int reel_acc, crank;
    uint32_t catch_idx;
    char msg[96];
    int caught;                          /* this time at the pond */
    uint32_t rng;
    /* what can be caught: songs nobody's played, by the artists played most */
    uint32_t pool[FH_POOL];
    int np, built;
    uint8_t *heard;
    uint32_t heard_n;
    /* the pond as it stands, cached (redrawn when the light changes) */
    px16 *bg;
    int bg_k;
} fh;

static void fh_build(app *a)
{
    uint32_t n = lib_n(a->L);
    if (!fh.heard || fh.heard_n != n) {
        fh.heard = plat_alloc((n + 7) / 8 + 1);
        fh.heard_n = fh.heard ? n : 0;
    }
    fh.np = 0;
    fh.built = 1;
    if (!fh.heard) return;
    brain_heard_bits(fh.heard, n);
    uint32_t top_a[FH_ART], top_s[FH_ART];
    int nt = 0;
    uint32_t na = lib_n_artists(a->L);
    for (uint32_t ar = 0; ar < na; ar++) {
        uint32_t fi, c, s = 0;
        lib_artist(a->L, ar, &fi, &c);
        for (uint32_t i = 0; i < c && fi + i < n; i++) s += (uint32_t)brain_ytm_plays(fi + i);
        if (s < 3) continue;
        int at = nt < FH_ART ? nt : -1;
        if (at < 0) {                                      /* full: replace the smallest if this is bigger */
            int m = 0;
            for (int k = 1; k < FH_ART; k++) if (top_s[k] < top_s[m]) m = k;
            if (top_s[m] >= s) continue;
            at = m;
        } else nt++;
        top_a[at] = ar;
        top_s[at] = s;
    }
    /* round and round the artists, one unplayed song each, so the catches come from all of them */
    for (int round = 0; round < 48 && fh.np < FH_POOL; round++) {
        int added = 0;
        for (int k = 0; k < nt && fh.np < FH_POOL; k++) {
            uint32_t fi, c, seen = 0;
            lib_artist(a->L, top_a[k], &fi, &c);
            for (uint32_t i = 0; i < c && fi + i < n; i++) {
                uint32_t idx = fi + i;
                if (fh.heard[idx >> 3] & (1u << (idx & 7))) continue;
                if (seen++ == (uint32_t)round) { fh.pool[fh.np++] = idx; added = 1; break; }
            }
        }
        if (!added) break;
    }
    shuffle(fh.pool, fh.np);
}

/* what's on the hook: from the pool, else any song nobody's played, else any song */
static uint32_t fh_pick(app *a)
{
    uint32_t n = lib_n(a->L);
    if (!fh.built) fh_build(a);
    while (fh.np > 0) {
        uint32_t idx = fh.pool[--fh.np];
        if (idx < n && !(fh.heard && (fh.heard[idx >> 3] & (1u << (idx & 7))))) return idx;
    }
    for (int tries = 0; tries < 400 && n; tries++) {
        uint32_t idx = rnd(n);
        if (!fh.heard || !(fh.heard[idx >> 3] & (1u << (idx & 7)))) return idx;
    }
    return n ? rnd(n) : LIB_NONE;
}

static void fh_mark(uint32_t idx)
{
    if (fh.heard && idx < fh.heard_n) fh.heard[idx >> 3] |= (uint8_t)(1u << (idx & 7));
}

static void fh_set(int state, const char *msg)
{
    fh.state = state;
    fh.st_t = fh.t;
    snprintf(fh.msg, sizeof fh.msg, "%s", msg ? msg : "");
}

static void fh_open(app *a)
{
    px16 *bg = fh.bg;
    uint8_t *heard = fh.heard;
    uint32_t hn = fh.heard_n, rng = fh.rng ? fh.rng : 0x2545F491u ^ a->now_ms;
    memset(&fh, 0, sizeof fh);                    /* nothing of the last visit but the buffers */
    fh.bg = bg;
    fh.bg_k = -1;
    fh.heard = heard;
    fh.heard_n = hn;
    fh.rng = rng ? rng : 1;
    fh_build(a);
    fh_set(FH_IDLE, "Play to cast.");
}

static void fh_event(app *a, ui_ev e)
{
    switch (fh.state) {
    case FH_IDLE: case FH_LOST:
        if (e.k == K_PLAY) fh_set(FH_CAST, "");
        break;
    case FH_WAIT:
        if (e.k == K_PLAY) fh_set(FH_IDLE, "Reeled in. Play to cast again.");
        break;
    case FH_BITE:
        if (e.k == K_SCROLL) {                             /* hooked, whichever way it turned */
            fh_set(FH_REEL, "");
            fh.tension = 34;
            fh.dist = 55;
            fh.rate = 0;
            fh.slack_t = fh.snap_t = 0;
            fh.strength = .75f + gm_rand01(&fh.rng) * .55f;
            fh.phase = gm_rand01(&fh.rng) * 6.28f;
            fh.surge_next = fh.t + 1.5f + gm_rand01(&fh.rng) * 2;
            fh.surge_until = 0;
            fh.reel_acc = 0;
        }
        break;
    case FH_REEL:
        if (e.k == K_SCROLL) { fh.reel_acc += e.d; fh.crank += e.d; }
        break;
    case FH_CAUGHT:
        if (e.k == K_PLAY) { play_one(a, fh.catch_idx); fh_set(FH_IDLE, "Playing your catch. Play to cast again."); }
        else if (e.k == K_NEXT) { q_add(a, fh.catch_idx, 1, QS_USER); fh_set(FH_IDLE, "Your catch plays next. Play to cast again."); }
        else if (e.k == K_BACK) fh_set(FH_IDLE, "You let it go. Play to cast again.");
        break;
    default:
        break;
    }
}

static void fh_tick(app *a, float dt)
{
    if (dt <= 0) return;                                   /* the same millisecond: turns wait for the next */
    fh.t += dt;
    float in = fh.t - fh.st_t;
    switch (fh.state) {
    case FH_CAST:
        if (in > .9f) {
            fh_set(FH_WAIT, "Waiting for a bite...");
            fh.wait_for = 1.6f + gm_rand01(&fh.rng) * 4.2f;
        }
        break;
    case FH_WAIT:
        if (in > fh.wait_for) fh_set(FH_BITE, "A bite! Turn the wheel to hook it.");
        break;
    case FH_BITE:
        if (in > 1.6f) fh_set(FH_LOST, "It got away. Turn the wheel as soon as the float goes under.");
        break;
    case FH_REEL: {
        float rate = dt > 0 ? fh.reel_acc / dt : 0;
        fh.rate += (rate - fh.rate) * (1 - expf(-dt / .25f));
        if (fh.t > fh.surge_next) {                        /* it fights: a run every few seconds */
            fh.surge_until = fh.t + .7f;
            fh.surge_next = fh.t + 1.8f + gm_rand01(&fh.rng) * 2.2f;
        }
        float pull = fh.strength * (.55f + .35f * sinf(fh.t * 1.9f + fh.phase)) + (fh.t < fh.surge_until ? .9f : 0);
        float want = pull * 42 + fh.rate * 5.5f;
        if (want < 0) want = 0;
        fh.tension += (want - fh.tension) * (1 - expf(-dt / .2f));
        if (fh.reel_acc > 0) fh.dist -= fh.reel_acc * (fh.tension < 92 ? 1.0f : .25f);
        else fh.dist -= fh.reel_acc * 1.2f;                /* letting line out */
        fh.dist += pull * 2.5f * dt;
        fh.reel_acc = 0;
        if (fh.tension >= 100) fh.snap_t += dt; else fh.snap_t = 0;
        if (fh.tension < 14) fh.slack_t += dt; else if ((fh.slack_t -= dt * 2) < 0) fh.slack_t = 0;
        if (fh.snap_t > .2f) fh_set(FH_LOST, "The line snapped. Ease off when it runs.");
        else if (fh.slack_t > 2.6f) fh_set(FH_LOST, "It slipped the hook. Keep the line tight.");
        else if (fh.dist > 100) fh_set(FH_LOST, "It swam off with the line.");
        else if (fh.dist <= 0) {
            fh.catch_idx = fh_pick(a);
            if (fh.catch_idx == LIB_NONE) { fh_set(FH_LOST, "Nothing in the pond."); break; }
            fh_mark(fh.catch_idx);
            fh.caught++;
            gm.fish_total++;
            game_save();
            fh_set(FH_CAUGHT, "");
        }
        break;
    }
    default:
        break;
    }
}

/* ---- drawing the pond: cells of 2 x 2 px */
static px16 fh_c(int r, int g_, int b) { return nightc(C565(r, g_, b)); }

static void fh_ell(gfx *g, float cx, float cy, float rx, float ry, px16 c)
{
    for (int y = (int)(cy - ry) - 1; y <= (int)(cy + ry) + 1; y++)
        for (int x = (int)(cx - rx) - 1; x <= (int)(cx + rx) + 1; x++) {
            float dx = (x + .5f - cx) / rx, dy = (y + .5f - cy) / ry;
            if (dx * dx + dy * dy <= 1 && x >= 0 && x < FH_W && y >= 0 && y < FH_H) ck_point(g, x, y, c);
        }
}

static void fh_ring(gfx *g, float cx, float cy, float rx, float ry, px16 c)
{
    int n = (int)(rx * 4) + 8;
    for (int i = 0; i < n; i++) {
        float t = 6.2832f * i / n;
        int x = (int)(cx + cosf(t) * rx), y = (int)(cy + sinf(t) * ry);
        if (x >= 0 && x < FH_W && y >= 0 && y < FH_H) ck_point(g, x, y, c);
    }
}

static void fh_line(gfx *g, float x0, float y0, float x1, float y1, px16 c)
{
    float dx = x1 - x0, dy = y1 - y0, L = fabsf(dx) > fabsf(dy) ? fabsf(dx) : fabsf(dy);
    int n = (int)L + 1;
    for (int i = 0; i <= n; i++) {
        int x = (int)(x0 + dx * i / n), y = (int)(y0 + dy * i / n);
        if (x >= 0 && x < FH_W && y >= 0 && y < FH_H) ck_point(g, x, y, c);
    }
}

static void fh_scene(gfx *g)
{
    static const uint8_t SKY[3][3] = { { 0xe9, 0xc9, 0x9d }, { 0xe2, 0xb8, 0x8b }, { 0xd9, 0xa7, 0x7c } };
    for (int k = 0; k < 3; k++) ck_rect(g, 0, k * 11, FH_W, k * 11 + 11, fh_c(SKY[k][0], SKY[k][1], SKY[k][2]));
    uint32_t s = 3;
    for (int x = 0; x < FH_W; x += 6) {                    /* the far bank's trees */
        float h = 6 + gm_rand01(&s) * 7;
        fh_ell(g, x + 1.5f, 34 - h / 2 + 1, 5.5f, h / 2 + 2, RP.leaf_d);
    }
    for (int x = 3; x < FH_W; x += 9) {
        float h = 3 + gm_rand01(&s) * 5;
        fh_ell(g, x + 1, 36 - h / 2, 4, h / 2 + 1, RP.sage_d);
    }
    ck_rect(g, 0, 35, FH_W, 37, RP.sage);
    ck_rect(g, 0, 37, FH_W, FH_H, fh_c(0x5a, 0x8b, 0x93));
    /* the dock */
    ck_rect(g, 0, 60, 47, 65, RP.walnut_l);
    for (int x = 0; x < 46; x += 8) ck_rect(g, x, 60, x + 1, 65, RP.walnut_d);
    ck_rect(g, 0, 60, 47, 61, RP.walnut_hi);
    ck_rect(g, 0, 65, 47, 67, RP.walnut_d);
    for (int k = 0; k < 2; k++) {
        int x = k ? 40 : 4;
        ck_rect(g, x, 67, x + 4, 81, RP.walnut);
        ck_rect(g, x - 2, 80, x + 6, 81, fh_c(0x8c, 0xb8, 0xb6));
    }
}

/* Bubloo sitting on the dock (Room's head on the Diorama's sitting body); eyes 0 shut,
 * 1 at you, 2 up at the float */
static void fh_cat(gfx *g, int x, int y, int eyes, int bob, float t)
{
    int top = y - 14 + bob;
    float sw = sinf(t * 2.4f);
    float tx[5] = { x + 20.0f, x + 24.0f, x + 28 + sw, x + 29 + 2 * sw, x + 28 + 3 * sw };
    float ty[5] = { y - 2.0f, y - 1.0f, y - 4.0f, y - 9.0f, y - 12.0f };
    for (int pass = 0; pass < 2; pass++)
        for (int i = 0; i < 4; i++)
            for (int k = 0; k <= 4; k++) {
                float px = tx[i] + (tx[i + 1] - tx[i]) * k / 4, py = ty[i] + (ty[i + 1] - ty[i]) * k / 4;
                fh_ell(g, px, py, pass ? 1.1f : 2.0f, pass ? 1.1f : 2.0f,
                       nightc(cat_col(pass ? (i == 3 ? 'D' : 'd') : 'o')));
            }
    for (int r = 0; r < 14; r++)
        for (int q = 0; DB_SIT[r][q]; q++)
            if (DB_SIT[r][q] != '.') ck_point(g, x + q, top + r, nightc(cat_col(DB_SIT[r][q])));
    for (int r = 0; r < 13; r++)
        for (int q = 0; CAT_HEAD[r][q]; q++) {
            char ch = CAT_HEAD[r][q];
            if (ch == '.') continue;
            if (ch == 'E') {
                int right = q >= 8, c = q - (right ? 11 : 3), e = r - 6;
                if (eyes == 0) ch = e ? 'o' : 'm';
                else {
                    int pc = eyes == 2 ? (right ? 0 : 1) : (right ? 0 : 1);
                    int pr = eyes == 2 ? 0 : 1;
                    ch = c == pc && e == pr ? 'k' : 'e';
                }
            }
            ck_point(g, x + 3 + q, top - 9 + r, nightc(cat_col(ch)));
        }
}

static void fh_draw(app *a, gfx *g)
{
    if (!fh.bg) fh.bg = plat_alloc(sizeof(px16) * LCD_W * BAR_Y);
    if (fh.bg && fh.bg_k != rp_k) {
        gfx gb;
        g_init(&gb, fh.bg, LCD_W, BAR_Y, LCD_W);
        fh_scene(&gb);
        fh.bg_k = rp_k;
    }
    if (fh.bg) for (int y = 0; y < BAR_Y; y++) memcpy(g->px + y * g->stride, fh.bg + y * LCD_W, LCD_W * 2);
    else { g_clip(g, 0, 0, LCD_W, BAR_Y); fh_scene(g); g_noclip(g); }
    g_clip(g, 0, 0, LCD_W, BAR_Y);
    float t = fh.t, in = fh.t - fh.st_t;
    px16 wl = fh_c(0x8c, 0xb8, 0xb6), wd = fh_c(0x47, 0x72, 0x7b), cream = RP.cream;
    for (int k = 0; k < 14; k++) {                         /* light on the water, drifting */
        int y = 42 + k * 4 + k % 3;
        int x0 = (int)(k * 37 + t * 6 * (1 + k % 2)) % 190 - 20;
        for (int x = x0; x < x0 + 6 + k % 4; x++)
            if (x >= 0 && x < FH_W) ck_point(g, x, y, k % 2 ? wl : wd);
    }
    /* the rod, the line, the float */
    float hx = 40, hy = 50, tipx = 72, tipy = 24, bx = 118, by = 72;
    int show_float = 1;
    if (fh.state == FH_CAST) {
        float u = ez_out(in / .9f), sw = sinf(dmin(1, in / .35f) * 3.1416f) * -.9f * (1 - u);
        tipx = hx + 32 * cosf(-.62f + sw);
        tipy = hy - 32 * sinf(.82f - sw);
        bx = tipx + (118 - tipx) * u;
        by = tipy + (72 - tipy) * u - 30 * sinf(u * 3.1416f);
    } else if (fh.state == FH_WAIT || fh.state == FH_BITE) {
        float dip = fh.state == FH_BITE ? ((int)(in * 8) % 2 ? 0 : 2.5f) : 0;
        by = 72 + dip + (sinf(t * 3) > .6f ? 1 : 0);
    } else if (fh.state == FH_REEL) {
        bx = 52 + fh.dist * 1.2f;
        if (bx > 150) bx = 150;
        by = 72 - (1 - fh.dist / 55) * 3 + sinf(t * 25) * .8f;
        tipy = 24 + (fh.tension - 50) * .08f + sinf(t * 9) * (fh.tension > 75 ? 1.2f : .3f);
    } else show_float = fh.state == FH_LOST && in < .01f;
    fh_line(g, hx, hy, tipx, tipy, RP.walnut_d);
    ck_point(g, (int)tipx, (int)tipy, RP.key);
    if (show_float) {
        int taut = fh.state == FH_REEL;
        float mx = (tipx + bx) / 2, my = (tipy > by ? tipy : by) + (taut ? 2 : 10) - (fh.state == FH_CAST ? 8 : 0);
        float px0 = tipx, py0 = tipy;
        for (int k = 1; k <= 12; k++) {
            float u = k / 12.0f, v = 1 - u;
            float px1 = v * v * tipx + 2 * v * u * mx + u * u * bx, py1 = v * v * tipy + 2 * v * u * my + u * u * by;
            fh_line(g, px0, py0, px1, py1, cream);
            px0 = px1;
            py0 = py1;
        }
        if (fh.state != FH_CAST)
            for (int k = 0; k < 3; k++) {
                float ph = (t * .9f + k / 3.0f) - floorf(t * .9f + k / 3.0f), rw = 3 + ph * 14;
                fh_ring(g, bx, by + 2, rw, rw * .28f, ph < .6f ? wl : mix565(wl, fh_c(0x5a, 0x8b, 0x93), (int)((ph - .6f) / .4f * 256)));
            }
        ck_rect(g, (int)bx - 1, (int)by - 3, (int)bx + 2, (int)by, RP.red);
        ck_rect(g, (int)bx - 1, (int)by, (int)bx + 2, (int)by + 2, cream);
    }
    if (fh.state == FH_REEL) {                               /* the fish, a shadow coming in */
        float fx = bx + 6, fy = 80 - (1 - fh.dist / 55) * 6;
        fh_ell(g, fx, fy, 7, 2.2f, wd);
        for (int k = 0; k < 4; k++) ck_rect(g, (int)fx + 6 + k, (int)fy - k, (int)fx + 7 + k, (int)fy + k + 1, wd);
    }
    int eyes = fh.state == FH_BITE || fh.state == FH_REEL ? 2 : fh.state == FH_CAUGHT ? 0 : 1;
    int bob = (fh.state == FH_BITE && in < .25f) || (fh.state == FH_CAUGHT && (int)(in * 6) % 2 && in < 1.5f) ? -2 : 0;
    fh_cat(g, 18, 60, eyes, bob, t);
    g_noclip(g);

    /* the words over the sky: the name, the catches; what to do now */
    txt(a, g, F_POSTER15, 9, 19, "Bubloo's Fishing Hole", RP.ink, T_TRACK(-3));
    char s[32];
    snprintf(s, sizeof s, "%d caught", gm.fish_total);
    txt_right(a, g, F_POSTER15, LCD_W - 9, 19, s, RP.ink);
    if (fh.msg[0]) txt_fit(a, g, F_BODY10, 9, 32, fh.msg, 300, RP.ink, 0);
    if (fh.state == FH_BITE) {
        int jig = (int)(in * 10) % 2 ? 2 : 0;
        txt(a, g, F_POSTER22, 66, 68 + jig, "!", RP.key, 0);
    }
    if (fh.state == FH_REEL) {
        /* the line's tension: keep the needle in the green; the reel turning with the wheel */
        const int gx = 296, gy = 46, gh = 124;
        g_fill(g, gx - 1, gy - 1, 15, gh + 2, RP.ink);
        g_fill(g, gx, gy, 13, gh, cream);
        g_fill(g, gx, gy + gh * 25 / 100, 13, gh * 40 / 100, nightc(C565(0xa9, 0xc4, 0x6c)));
        g_fill(g, gx, gy, 13, gh * 8 / 100, nightc(C565(0xe8, 0x9a, 0x8a)));
        float tv = fh.tension > 100 ? 100 : fh.tension;
        int ny = gy + gh - (int)(tv * gh / 100);
        g_fill(g, gx - 4, ny - 1, 21, 3, RP.red);
        int ccx = 262, ccy = 178;
        g_ring(g, ccx * 16, ccy * 16, 14 * 16, 3 * 16, cream);
        float an = fh.crank * (6.2832f / 24);
        int ex = (int)((ccx + sinf(an) * 14) * 16), ey = (int)((ccy - cosf(an) * 14) * 16);
        g_disc(g, ex, ey, 4 * 16, RP.key);
        txt_right(a, g, F_BOLD11, ccx - 22, ccy + 4, fh.tension > 80 ? "easy!" : fh.tension < 25 ? "reel!" : "reel", cream);
    }
    if (fh.state == FH_CAUGHT) {
        float k = ez_back(ez_seg(in * 1000, 0, 350), 1.70158f);
        int cw = (int)(224 * k), ch = (int)(116 * k), x0 = 200 - cw / 2, y0 = 104 - ch / 2;
        if (cw > 4 && ch > 4) {
            g_fill(g, x0 + 3, y0 + 3, cw, ch, RP.ink);
            g_fill(g, x0, y0, cw, ch, cream);
            g_fill(g, x0, y0, cw, 3, RP.walnut);
        }
        if (k > .9f) {
            const lib_track *tr = lib_get(a->L, fh.catch_idx);
            cover(a, g, fh.catch_idx, ART_M, x0 + 10, y0 + 12, 78);
            int fx = x0 + 98, fw = cw - 106;
            txt(a, g, F_BOLD11, fx, y0 + 22, "New catch, never played", RP.key_d, 0);
            if (tr) {
                char lines[2][TEXT_LINE_MAX];
                int nl = text_wrap(F(a, F_SEMI12), tr->title, fw, 2, 0, lines);
                for (int i = 0; i < nl; i++) txt(a, g, F_SEMI12, fx, y0 + 40 + 14 * i, lines[i], RP.ink, 0);
                txt_fit(a, g, F_BODY10, fx, y0 + 42 + 14 * nl, tr->artist, fw, RP.sub, 0);
            }
            txt_fit(a, g, F_BODY10, x0 + 10, y0 + 106, "Play: listen now   Next: play next   Back: let go", cw - 20,
                    RP.ink, 0);
        }
    }
    draw_nowbar(a, g);
}

/* ================================================================== the app's side */
static void game_open(app *a, int which)
{
    game_load();
    gm.which = which == GM_FISH ? GM_FISH : GM_ORBIT;
    gm.last_ms = 0;
    gm.drawn_ms = 0;
    if (gm.which == GM_ORBIT) {
        ob_table();
        ob_reset(a);
        ob.state = OB_READY;
    } else fh_open(a);
    a->force_full = 1;
}

static void game_event(app *a, ui_ev e)
{
    if (e.k == K_MENU) {                                   /* home, as everywhere */
        if (gm.which == GM_ORBIT && ob.state == OB_RUN) ob.state = OB_PAUSE;
        a->depth = 0;
        a->view = V_MENU;
        return;
    }
    if (e.k == K_BACK && !(gm.which == GM_FISH && fh.state == FH_CAUGHT)) {
        if (gm.which == GM_ORBIT && ob.state == OB_RUN) { ob.state = OB_PAUSE; return; }   /* first Back pauses */
        pop(a);
        return;
    }
    if (gm.which == GM_ORBIT) ob_event(a, e);
    else fh_event(a, e);
}

static void game_draw(app *a, gfx *g)
{
    g_noclip(g);
    if (gm.which == GM_ORBIT) ob_draw(a, g);
    else fh_draw(a, g);
}

/* how often a frame: ~30 fps while something moves, slower while it waits for you */
static uint32_t game_frame_ms(void)
{
    if (gm.which == GM_ORBIT) return ob.state == OB_RUN ? 33 : ob.state == OB_READY ? 66 : 200;
    return fh.state == FH_REEL || fh.state == FH_CAST || fh.state == FH_BITE ? 33 : 66;
}

static int game_tick(app *a, uint32_t now)
{
    float dt = gm.last_ms ? (now - gm.last_ms) / 1000.0f : 0;
    if (dt > .1f) dt = .1f;                                /* a stall doesn't teleport anything */
    gm.last_ms = now;
    if (gm.which == GM_ORBIT) {
        if (ob.state == OB_READY || ob.state == OB_PAUSE || ob.state == OB_OVER) {
            /* the arena keeps turning slowly behind the words */
            if (ob.state != OB_PAUSE && ob.state != OB_OVER) ob.t += dt * .3f;
        }
        ob_tick(a, dt);
    } else fh_tick(a, dt);
    uint32_t every = game_frame_ms();
    if (a->force_full || now - gm.drawn_ms >= every) {
        /* the wheel's turns queue up faster than frames: take them all, then draw */
        if (plat_input_pending() && now - gm.drawn_ms < 60) return NEED_NONE;
        a->force_full = 0;
        gm.drawn_ms = now;
        return NEED_FULL;
    }
    return NEED_NONE;
}

static int game_interval(app *a)
{
    uint32_t every = game_frame_ms(), since = a->now_ms - gm.drawn_ms;
    int left = since >= every ? 1 : (int)(every - since);
    return left > 16 && every <= 33 ? 16 : left;             /* moving: tick at least every 16 ms */
}
