/* Room, after the room as it is now (2026-10 photos): the walnut shelf over the desk with its
 * plants and the white clock, the pothos down its end, the monitor, the silver case on its
 * walnut foot -- and Bubloo, lying on the shelf with his tail over the edge. Part of app.c,
 * after th_pixel.h (the materials, rows and panels are Room's from there).
 *
 * Bubloo is a few sprites on the 2x grid and a tail that hangs and sways. What he does is
 * worked out from the clock and the player, never stored frame to frame, so any frame can
 * be drawn at any time: awake while music plays (and the tail goes with the bass), dozing
 * a while after it stops, asleep after that; a button wakes him and he looks where you
 * scroll. He's redrawn on his own between full frames (the "hub" path: his corner of the
 * screen is kept from the last full frame, he's drawn over it, only that corner goes out). */

/* ------------------------------------------------------------------ Bubloo */
static px16 cat_col(char ch)
{
    switch (ch) {
    case 'o': return C565(0x2b, 0x1f, 0x19);           /* outline */
    case 'D': return C565(0x3f, 0x30, 0x27);           /* the stripes */
    case 'd': return C565(0x5b, 0x48, 0x38);
    case 'm': return C565(0x7d, 0x6b, 0x59);           /* tabby grey-brown */
    case 'b': return C565(0x9a, 0x7b, 0x5c);           /* the warm flanks */
    case 't': return C565(0xc0, 0x9b, 0x72);
    case 'g': return C565(0xa3, 0x9a, 0x8f);
    case 'W': return C565(0xf3, 0xef, 0xe6);           /* bib, muzzle, mitts */
    case 'w': return C565(0xd3, 0xcb, 0xbf);
    case 'e': return C565(0xa9, 0xc4, 0x6c);           /* green eyes */
    case 'k': return C565(0x1d, 0x17, 0x12);
    case 'n': return C565(0xd0, 0x8f, 0x84);           /* pink nose */
    case 'p': return C565(0xb9, 0x88, 0x77);
    case 'r': return C565(0x9e, 0x4a, 0x48);           /* a yawn */
    default: return 0;
    }
}

/* lying down, facing right; the bottom row sits on whatever he's on */
static const char *const CAT_BODY[11] = {
    "..........o..oooooooo.o......",
    "........ooodddmDmmDmmdddoo...",
    "......oodmmDmmmDmmmDmmmmddoo.",
    ".....odmmmDmmmmDmmmmDmmmmmmdo",
    "....odmmmDmmmmmDmmmmmmmmmmmwo",
    "...odmmmmmmmmmmmmmmmmmmmmmwWo",
    "..odbmmmmmmmmmmmmmmmmmmmmwWWo",
    "..odbbbmmmmmmmmmmmmmmmmbwWWWo",
    ".odWWbbbbbmmmmmmbbbbbbbbwWWWo",
    ".oWWWWtbbbbbbbbbbbbbbbbbwWWWo",
    "..oooooooooooooooooooooooooo.",
};
/* turned to you; E = the eyes, worked out per frame */
static const char *const CAT_HEAD[13] = {
    "..o..........o..",
    "..odo......odo..",
    "..opdo....odpo..",
    "..oppdoooodppo..",
    ".odmmmDmmDmmmdo.",
    ".odmmmmDDmmmmdo.",
    "odmEEmmmmmmEEmdo",
    "odmEEmmmmmmEEmdo",
    "otbmmmmWWmmmmbto",
    "otbbmmWnnWmmbbto",
    ".otbbWWWWWWbbto.",
    "..otWWWWWWWWto..",
    "...owWWWWWWwo...",
};
static const char *const CAT_PAWS[2] = { "oWWWWooWWWWo", "owWWWoowWWWo" };
#define CAT_W 33                /* body + head, in cells */
#define CAT_HX 17               /* the head over the body's front */

typedef struct {
    int eyes;                   /* 0 shut, 1 half, 2 open */
    int lx, ly;                 /* looking: -1 / 0 / 1 across the screen, 1 = down; 0, 0 = at you */
    int yawn, flick, inhale, low, zz;
    float sway, curl;           /* the tail: how far it swings, a curl at its tip */
    uint32_t t;
} cat_pose;

/* one cell of him, mirrored if he faces left */
static void cat_px(gfx *g, int bx, int mir, int x, int y, char ch)
{
    if (ch == '.' || ch == ' ') return;
    ck_point(g, mir ? bx + CAT_W - 1 - x : bx + x, y, cat_col(ch));
}

static void cat_tail(gfx *g, float ax, float ay, int mir, const cat_pose *p)
{
    enum { N = 14 };
    float px[N], py[N], pr[N];
    float x = ax, y = ay, w = (float)p->t / 3400.0f * 6.2832f;
    for (int i = 0; i < N; i++) {
        float u = i / (float)(N - 1);
        float base = -1.3f * (i < 3 ? 1 - i / 3.0f : 0);           /* out over the edge first */
        float a = base + p->sway * sinf(w - 1.8f * u) * u * (.9f + .1f * u) + p->curl * u * u * u;
        x += (mir ? -1 : 1) * sinf(a) * 1.45f;
        y += cosf(a) * 1.45f;
        px[i] = x;
        py[i] = y;
        pr[i] = 2.1f + 1.2f * sinf(3.1416f * (u + 0.3f > 1 ? 1 : u + 0.3f));
    }
    for (int pass = 0; pass < 2; pass++)
        for (int i = 0; i < N; i++) {
            float r = pr[i] + (pass ? 0 : 1);
            for (int yy = (int)(py[i] - r) - 1; yy <= (int)(py[i] + r) + 1; yy++)
                for (int xx = (int)(px[i] - r) - 1; xx <= (int)(px[i] + r) + 1; xx++) {
                    float dx = xx + .5f - px[i], dy = yy + .5f - py[i];
                    if (dx * dx + dy * dy > r * r) continue;
                    char c = 'o';
                    if (pass) {
                        c = i >= N - 3 || i % 4 == 2 ? 'D' : dx < -pr[i] * .35f ? 'm' : 'd';
                    }
                    ck_point(g, xx, yy, cat_col(c));
                }
        }
}

/* the z's of a nap, drifting up from (x, y) */
static void cat_zz(gfx *g, int x, int y, uint32_t t, px16 c)
{
    static const char *const Z4[4] = { "####", "..#.", ".#..", "####" }, *const Z3[3] = { "###", ".#.", "###" };
    for (int k = 0; k < 3; k++) {
        uint32_t ph = (t + (uint32_t)k * 900) % 2700;
        if (ph > 2200) continue;
        int zx = x + (int)(ph * 10 / 2200) + 2 * k, zy = y - (int)(ph * 5 / 2200);
        int big = ph < 900;
        for (int r = 0; r < (big ? 4 : 3); r++)
            for (int q = 0; q < (big ? 4 : 3); q++)
                if ((big ? Z4 : Z3)[r][q] == '#') ck_point(g, zx + q, zy + r, c);
    }
}

/* Bubloo lying on a ledge whose top is row ly; bx = his left edge (cells) */
static void cat_draw(gfx *g, int bx, int ly, int mir, const cat_pose *p)
{
    int top = ly - 11;
    cat_tail(g, (float)(mir ? bx + CAT_W - 3 : bx + 2), (float)(top + 8) + .5f, mir, p);
    for (int r = 0; r < 11; r++) {
        int y = top + r - (p->inhale && r <= 4 ? 1 : 0);
        for (int x = 0; CAT_BODY[r][x]; x++) cat_px(g, bx, mir, x, y, CAT_BODY[r][x]);
        if (p->inhale && r == 4)
            for (int x = 0; CAT_BODY[r][x]; x++) cat_px(g, bx, mir, x, top + 4, CAT_BODY[r][x]);
    }
    for (int r = 0; r < 2; r++)
        for (int x = 0; CAT_PAWS[r][x]; x++) cat_px(g, bx, mir, 19 + x, top + 9 + r, CAT_PAWS[r][x]);
    int hy = top - 5 + (p->low ? 2 : 0), lx = mir ? -p->lx : p->lx;
    for (int r = 0; r < 13; r++)
        for (int x = 0; CAT_HEAD[r][x]; x++) {
            char ch = CAT_HEAD[r][x];
            if (ch == 'E') {
                int right = x >= 8, c = x - (right ? 11 : 3), e = r - 6;
                int pc = lx > 0 ? 1 : lx < 0 ? 0 : !right, pr = p->ly > 0;
                if (p->eyes == 0 || p->yawn) ch = e ? 'o' : 'm';
                else if (p->eyes == 1) ch = !e ? 'o' : c == pc ? 'k' : 'e';
                else ch = c == pc && e == pr ? 'k' : 'e';
            }
            if (p->yawn && ((r == 10 && x >= 6 && x <= 9) || (r == 11 && (x == 7 || x == 8))))
                ch = r == 10 && (x == 7 || x == 8) ? 'r' : 'o';
            int xx = x + (p->flick && r < 2 && x >= 9 ? 1 : 0);
            cat_px(g, bx, mir, CAT_HX + xx - (mir ? 0 : 0), hy + r, ch);
        }
    if (p->zz) cat_zz(g, mir ? bx + 2 : bx + CAT_HX + 14, hy + 1, p->t, RP.sub);
}

/* ------------------------------------------------------------------ what he's doing */
static uint32_t pet_hash(uint32_t k)
{
    k ^= k >> 16; k *= 0x7feb352du; k ^= k >> 15; k *= 0x846ca68bu; k ^= k >> 16;
    return k;
}

/* once a period, at a random moment, for len ms: how far into it (0..len), or -1 */
static int pet_event(uint32_t now, uint32_t period, uint32_t len, uint32_t salt)
{
    uint32_t k = now / period, off = pet_hash(k * 2654435761u + salt) % (period - len), t = now % period;
    return t >= off && t < off + len ? (int)(t - off) : -1;
}

static struct { int asleep; uint32_t idle0, wake0; } pet;

/* lx, ly: where the thing you're on is, from his eyes (0, 0 = nowhere in particular) */
static void pet_pose(app *a, cat_pose *p, int lx, int ly)
{
    uint32_t now = a->now_ms;
    int playing = a->cur_valid && a->ps.playing, poked = now - a->poke_ms < 8000;
    if (playing || poked) {
        if (pet.asleep) { pet.asleep = 0; pet.wake0 = now; }
        pet.idle0 = now;
    } else if (!pet.asleep && now - pet.idle0 > 30000) pet.asleep = 1;
    memset(p, 0, sizeof *p);
    p->t = now;
    float bass = 0;
    uint8_t bands[12];
    if (playing && plat_spectrum(bands)) bass = (bands[0] + bands[1] + bands[2]) / 765.0f;
    if (pet.asleep) {
        p->eyes = 0; p->low = 1; p->zz = 1;
        p->inhale = now % 3600 < 1500;
        p->sway = .06f;
        int tw = pet_event(now, 9700, 500, 7);                   /* the tip twitches in his sleep */
        if (tw >= 0) p->curl = .7f * sinf(3.1416f * tw / 500.0f);
        return;
    }
    int woke = (int)(now - pet.wake0);
    if (pet.wake0 && woke < 800) { p->yawn = 1; p->sway = .1f; return; }
    p->inhale = now % 2600 < 1100;
    p->eyes = 2;
    if (poked) { p->lx = lx; p->ly = ly; }
    else {
        if (playing && pet_event(now, 9000, 4200, 3) >= 0) p->eyes = 1;   /* content, half shut */
        int gl = pet_event(now, 7300, 1300, 5);
        if (gl >= 0) p->lx = pet_hash(now / 7300) & 1 ? 1 : -1;
        if (!playing && now - pet.idle0 > 14000) p->eyes = 1;              /* dozing off */
    }
    int bl = pet_event(now, 4300, 300, 1);
    if (bl >= 0 && (bl < 130 || (pet_hash(now / 4300) % 3 == 0 && bl > 200))) p->eyes = 0;
    int fl = pet_event(now, 6100, 260, 2);
    p->flick = fl >= 0 && (fl < 90 || fl > 170);
    p->sway = (playing ? .22f : .16f) + .35f * bass;
    int cu = pet_event(now, 8900, 600, 4);
    if (cu >= 0) p->curl = .9f * sinf(3.1416f * cu / 600.0f);
}

/* his corner of the screen: kept from the last full frame so he can be redrawn on his own */
#define PET_MW 128
#define PET_MH 112
#define PET_MS 83               /* his frame rate between full frames: 12 a second */
static struct { int x, y, w, h, live, view, bx, ly, mir, lx, lyk; px16 bg[PET_MW * PET_MH]; } petl;

static void pet_keep(gfx *g, int view, int x, int y, int w, int h)
{
    petl.x = x; petl.y = y; petl.w = w; petl.h = h; petl.view = view; petl.live = 1;
    for (int r = 0; r < h; r++) memcpy(petl.bg + r * w, g->px + (y + r) * g->stride + x, (size_t)w * 2);
}

static void pet_place(app *a, gfx *g, int view, int bx, int ly, int mir, int lx, int lyk)
{
    petl.bx = bx; petl.ly = ly; petl.mir = mir; petl.lx = lx; petl.lyk = lyk;
    cat_pose p;
    pet_pose(a, &p, lx, lyk);
    int x0 = 2 * bx - 24, x1 = 2 * (bx + CAT_W) + 24, y0 = 2 * (ly - 18), y1 = 2 * (ly + 26);
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > LCD_W) x1 = LCD_W;
    if (y1 > LCD_H) y1 = LCD_H;
    if (x1 - x0 > PET_MW) { if (mir) x0 = x1 - PET_MW; else x1 = x0 + PET_MW; }
    if (y1 - y0 > PET_MH) y1 = y0 + PET_MH;
    pet_keep(g, view, x0, y0, x1 - x0, y1 - y0);
    g_clip(g, x0, y0, x1, y1);
    cat_draw(g, bx, ly, mir, &p);
    g_noclip(g);
}

/* Room, on its home or Now playing, nothing over it: he can move between full frames */
static int pet_live(const app *a)
{
    return a->skin == 1 && a->sheet == SH_NONE && petl.live && petl.view == a->view &&
           (a->view == V_MENU || a->view == V_NOW);
}

/* just him: his corner back as it was, him over it; r = what changed */
static void pet_frame(app *a, gfx *g, int r[4])
{
    for (int y = 0; y < petl.h; y++)
        memcpy(g->px + (petl.y + y) * g->stride + petl.x, petl.bg + y * petl.w, (size_t)petl.w * 2);
    cat_pose p;
    pet_pose(a, &p, petl.lx, petl.lyk);
    g_clip(g, petl.x, petl.y, petl.x + petl.w, petl.y + petl.h);
    cat_draw(g, petl.bx, petl.ly, petl.mir, &p);
    g_noclip(g);
    r[0] = petl.x; r[1] = petl.y; r[2] = petl.w; r[3] = petl.h;
}

/* ------------------------------------------------------------------ the shelf and what's on it */
#define RM_LY 18                /* the shelf's top (cells); the panels start under its shadow */

static const px16 RM_POT = C565(0x2c, 0x2b, 0x2e), RM_POT_L = C565(0x45, 0x44, 0x48),
                  RM_RED = C565(0xc8, 0x32, 0x2a), RM_RED_D = C565(0x96, 0x22, 0x1e),
                  RM_CUBE = C565(0xe8, 0xc4, 0x48), RM_CUBE_D = C565(0xc0, 0x9a, 0x2c),
                  RM_BEZEL = C565(0x1c, 0x1b, 0x1f), RM_SCREEN = C565(0x23, 0x29, 0x3a),
                  RM_SCREEN_L = C565(0x2e, 0x36, 0x4c), RM_SKY = C565(0x9f, 0xb8, 0xdc);

static void rm_disc(gfx *g, float cx, float cy, float r, px16 c)
{
    for (int y = (int)(cy - r) - 1; y <= (int)(cy + r) + 1; y++)
        for (int x = (int)(cx - r) - 1; x <= (int)(cx + r) + 1; x++)
            if ((x + .5f - cx) * (x + .5f - cx) + (y + .5f - cy) * (y + .5f - cy) <= r * r) ck_point(g, x, y, c);
}

static void rm_line(gfx *g, float x0, float y0, float x1, float y1, px16 c)
{
    int n = (int)(fabsf(x1 - x0) > fabsf(y1 - y0) ? fabsf(x1 - x0) : fabsf(y1 - y0)) + 1;
    for (int i = 0; i <= n; i++) ck_point(g, (int)floorf(x0 + (x1 - x0) * i / n), (int)floorf(y0 + (y1 - y0) * i / n), c);
}

/* the white desk clock, at the real time */
static void rm_clock(gfx *g, float cx, float cy)
{
    rm_disc(g, cx, cy, 5.5f, RP.walnut_d);
    rm_disc(g, cx, cy, 4.6f, C565(0xfb, 0xf9, 0xf3));
    static const int8_t TK[4][2] = { { 0, -4 }, { 3, 0 }, { 0, 3 }, { -4, 0 } };
    for (int i = 0; i < 4; i++) ck_point(g, (int)floorf(cx) + TK[i][0], (int)floorf(cy) + TK[i][1], RP.felt_d);
    int h, m;
    plat_clock(&h, &m);
    float ha = ((h % 12) + m / 60.0f) / 12 * 6.2832f, ma = m / 60.0f * 6.2832f;
    rm_line(g, cx, cy, cx + sinf(ma) * 3.2f, cy - cosf(ma) * 3.2f, RP.ink);
    rm_line(g, cx, cy, cx + sinf(ha) * 2.1f, cy - cosf(ha) * 2.1f, RP.ink);
}

/* a fern in a black pot; base = the shelf's top row */
static void rm_fern(gfx *g, int x, int base, uint32_t now)
{
    ck_rect(g, x, base - 4, x + 7, base, RM_POT);
    ck_rect(g, x, base - 4, x + 7, base - 3, RM_POT_L);
    for (int k = 0; k < 9; k++) {
        float q = 3.1416f * (1.08f + .84f * k / 8), L = 6.5f + (k % 3) * 1.6f;
        float sw = sinf((float)now / 1500.0f + k) * .04f;
        for (int s = 1; s <= (int)L; s++) {
            float fx = x + 3.5f + cosf(q + sw) * s, fy = base - 4.5f + sinf(q + sw) * s + .05f * s * s;
            ck_point(g, (int)floorf(fx), (int)floorf(fy), k % 2 ? RP.leaf_d : RP.leaf);
            if (s % 2 == 0 && s < L - 1) ck_point(g, (int)floorf(fx), (int)floorf(fy) - 1, RP.leaf_l);
        }
    }
}

/* a succulent in a white pot */
static void rm_succ(gfx *g, int x, int base, int kind)
{
    ck_rect(g, x, base - 3, x + 5, base, RP.cream);
    ck_rect(g, x + 4, base - 3, x + 5, base, RP.shade_line);
    ck_rect(g, x, base - 1, x + 5, base, RP.shade_line);
    static const char *const R[2][3] = { { ".l.l.", "lLlLl", ".lDl." }, { "..l..", ".lLl.", "lLDLl" } };
    for (int r = 0; r < 3; r++)
        for (int q = 0; q < 5; q++) {
            char ch = R[kind][r][q];
            if (ch != '.') ck_point(g, x + q, base - 6 + r, ch == 'L' ? RP.leaf_l : ch == 'D' ? RP.leaf_d : RP.sage_l);
        }
}

/* the red spotted plant (a plush) */
static void rm_piranha(gfx *g, int x, int base)
{
    static const char *const P[9] = {
        "..rrrr..", ".rwrrrr.", "rrrrrwrr", "rwrrrrrr", "kWWWWWWk", ".rrrrrr.", "...gg...", ".llggll.", "lLl..lLl" };
    for (int r = 0; r < 9; r++)
        for (int q = 0; q < 8; q++) {
            char ch = P[r][q];
            if (ch == '.') continue;
            px16 c = ch == 'r' ? RM_RED : ch == 'w' || ch == 'W' ? RP.cream : ch == 'k' ? RM_RED_D :
                     ch == 'g' ? RP.leaf_d : ch == 'L' ? RP.leaf_l : RP.leaf;
            ck_point(g, x + q, base - 9 + r, c);
        }
}

/* the little yellow block figure */
static void rm_cube(gfx *g, int x, int base)
{
    ck_rect(g, x, base - 4, x + 4, base, RM_CUBE);
    ck_rect(g, x + 3, base - 4, x + 4, base, RM_CUBE_D);
    ck_point(g, x + 1, base - 3, RP.ink);
    ck_point(g, x + 2, base - 3, RP.ink);
}

/* the pothos's pot at the shelf's end; its vine hangs down the wall */
static void rm_pothos(gfx *g, int x, int base)
{
    ck_rect(g, x, base - 4, x + 7, base, RP.cream);
    ck_rect(g, x + 6, base - 4, x + 7, base, RP.shade_line);
    static const char *const L[4] = { ".LL.lL..", "LlLLlLLl", "lLlDLlDl", ".D.lL.D." };
    for (int r = 0; r < 4; r++)
        for (int q = 0; q < 8; q++) {
            char ch = L[r][q];
            if (ch != '.') ck_point(g, x - 1 + q, base - 8 + r, ch == 'L' ? RP.leaf_l : ch == 'D' ? RP.leaf_d : RP.leaf);
        }
}

/* the shelf across the top of the wall, with what's on it; Bubloo goes on later */
static void rm_shelf(app *a, gfx *g, uint32_t now)
{
    ck_material(g, 0, RM_LY, 160, RM_LY + 3, MAT_WOOD, 7, 0);
    ck_rect(g, 0, RM_LY + 3, 160, RM_LY + 4, RP.silver);         /* the light bar, lit */
    ck_rect(g, 0, RM_LY + 4, 160, RM_LY + 5, RP.led);
    ck_rect(g, 0, RM_LY + 5, 160, RM_LY + 6, RP.wall_sh);
    rm_clock(g, 54.0f, (float)RM_LY - 5.5f);
    rm_fern(g, 66, RM_LY, now);
    rm_succ(g, 78, RM_LY, 0);
    rm_succ(g, 85, RM_LY, 1);
    rm_piranha(g, 93, RM_LY);
    rm_cube(g, 104, RM_LY);
    rm_pothos(g, 149, RM_LY);
    int x = 220;
    pf_text(g, &PF_PIXEL11, x, 30, "Coda", RP.wall_sh, 2);
    int w = pf_text(g, &PF_PIXEL11, x, 28, "Coda", RP.walnut_d, 2);
    ck_rect(g, (x + w) / 2 + 1, 12, (x + w) / 2 + 3, 14, RP.key);
    if (a) px_battery(a, g, LCD_W - 8, 12, RP.ink);
}

/* ------------------------------------------------------------------ Room: the home */
enum { RK_WHEEL, RK_MONITOR, RK_SHADE, RK_LEAF, RK_SAGE, RK_CASE, RK_KEY, RK_FELT };
static const struct { int x0, y0, x1, y1, kind; } RH_CELL[8] = {    /* by menu item */
    { 6, 48, 112, 206, RK_WHEEL }, { 118, 48, 314, 110, RK_MONITOR }, { 118, 164, 162, 206, RK_SHADE },
    { 118, 116, 214, 158, RK_LEAF }, { 166, 164, 210, 206, RK_SAGE }, { 218, 116, 314, 158, RK_CASE },
    { 214, 164, 258, 206, RK_KEY }, { 262, 164, 314, 206, RK_FELT },
};
static const int RK_MAT[8] = { MAT_WOOD, MAT_WOOD, MAT_SHADE, MAT_LEAF, MAT_SAGE, MAT_SILVER, MAT_KEY, MAT_FELT };

/* the monitor: the song on its screen, in the editor's colours */
static void rm_monitor(app *a, gfx *g, int x0, int y0, int x1, int y1, int lift, int foc)
{
    int a0 = x0 / 2, b0 = y0 / 2 - lift, c0 = x1 / 2, d0 = y1 / 2 - lift, dy = -2 * lift;
    ck_rrect(g, a0 + 1, b0 + 1 + lift, c0 + 1, d0 + 1 + lift, RP.wall_sh, 2);
    if (foc) {
        ck_rrect(g, a0 - 2, b0 - 2, c0 + 2, d0 + 2, RP.walnut_d, 3);
        ck_rrect(g, a0 - 1, b0 - 1, c0 + 1, d0 + 1, RP.cream, 2);
    }
    ck_rrect(g, a0, b0, c0, d0, RM_BEZEL, 1);
    ck_rect(g, a0 + 2, b0 + 2, c0 - 2, d0 - 3, foc ? RM_SCREEN_L : RM_SCREEN);
    ck_rect(g, (a0 + c0) / 2 - 1, d0 - 2, (a0 + c0) / 2 + 1, d0 - 1, RM_RED);
    const lib_track *tr = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    int tx = x0 + 10;
    if (tr) {
        cover(a, g, a->cur, ART_M, x0 + 6, y0 + 6 + dy, 46);
        tx = x0 + 60;
        txt(a, g, F_MONO10, tx, y0 + 16 + dy, a->ps.playing ? "> now playing" : "> paused", RP.leaf_l, 0);
        char lines[2][TEXT_LINE_MAX];
        int nl = text_wrap(F(a, F_BOLD11), tr->title, x1 - tx - 14, 2, 0, lines);
        for (int k = 0; k < nl; k++) txt(a, g, F_BOLD11, tx, y0 + 30 + 12 * k + dy, lines[k], RP.cream, 0);
        txt_fit(a, g, F_BODY10, tx, y0 + 30 + 12 * nl + dy, tr->artist, x1 - tx - 14, RM_SKY, 0);
    } else {
        txt(a, g, F_MONO10, tx, y0 + 16 + dy, "> now playing", RP.leaf_l, 0);
        txt(a, g, F_BODY10, tx, y0 + 32 + dy, "Nothing yet.", RM_SKY, 0);
        if ((a->now_ms / 530) % 2) g_fill(g, tx + text_w(F(a, F_BODY10), "Nothing yet.", 0) + 3, y0 + 24 + dy, 6, 9, RP.cream);
    }
}

/* the home's panels with nothing on them yet: the room through the door, at power-on */
static void rm_furniture(gfx *g)
{
    for (int i = 0; i < 8; i++) {
        int a0 = RH_CELL[i].x0 / 2, b0 = RH_CELL[i].y0 / 2, c0 = RH_CELL[i].x1 / 2, d0 = RH_CELL[i].y1 / 2;
        if (RH_CELL[i].kind == RK_MONITOR) {
            ck_rrect(g, a0 + 1, b0 + 1, c0 + 1, d0 + 1, RP.wall_sh, 2);
            ck_rrect(g, a0, b0, c0, d0, RM_BEZEL, 1);
            ck_rect(g, a0 + 2, b0 + 2, c0 - 2, d0 - 3, RM_SCREEN);
            ck_rect(g, (a0 + c0) / 2 - 1, d0 - 2, (a0 + c0) / 2 + 1, d0 - 1, RM_RED);
            continue;
        }
        px_panel(NULL, g, 2 * a0, 2 * b0, 2 * c0, 2 * d0, RK_MAT[i], (uint32_t)i + 1, 0, 0);
        if (RH_CELL[i].kind == RK_CASE) {
            ck_material(g, a0, d0 - 3, c0, d0, MAT_WOOD, 40, 0);
            ck_vents(g, a0 + 3, b0 + 3, c0 - 18, b0 + 8);
        }
    }
}

static void room_home(app *a, gfx *g)
{
    rm_shelf(a, g, a->now_ms);
    int cur = menu_item_at(a, a->ls[V_MENU].sel);
    float t = a->ui_view == V_MENU ? (float)(a->now_ms - a->ui_t0) : 1e6f;
    for (int pass = 0; pass < 2; pass++)
        for (int i = 0; i < 8; i++) {
            if ((pass == 0) == (i == cur)) continue;
            int foc = i == cur, lift = foc ? (t < 120 ? 2 : 1) : 0, dy = -2 * lift;
            int x0 = RH_CELL[i].x0, y0 = RH_CELL[i].y0, x1 = RH_CELL[i].x1, y1 = RH_CELL[i].y1, mat = RK_MAT[i];
            float u = foc ? ez_seg(t, 60, 560) : 1;
            if (RH_CELL[i].kind == RK_MONITOR) {
                rm_monitor(a, g, x0, y0, x1, y1, lift, foc);
                if (foc) ck_pointer(g, x0 - 8, y0 + 12 + dy, a->now_ms, RP.walnut_d, RP.cream);
                continue;
            }
            px_panel(a, g, x0, y0, x1, y1, mat, i + 1, lift, foc);
            px16 ink = mat_ink(mat), base = mat_base(mat), sh = ink == RP.cream ? RP.walnut_d : 0;
            if (i == 0) {
                ck_sym(g, SYM_WHEEL, 58, 118 + dy, 88, ink, base, RP.key, u);
                char n[24], s[40];
                commas(n, sizeof n, brain_n());
                snprintf(s, sizeof s, "%s songs", n);
                txt(a, g, F_MONO10, 14, 176 + dy, s, RP.felt_l, 0);
                pf_text(g, &PF_PIXEL11, 14, 200 + dy, "Wheel", sh, 2);
                pf_text(g, &PF_PIXEL11, 14, 198 + dy, "Wheel", ink, 2);
            } else if (i == 3 || i == 5) {
                int foot = i == 5 ? 3 : 0;                      /* the case stands on walnut */
                if (foot) {
                    ck_material(g, x0 / 2, y1 / 2 - lift - foot, x1 / 2, y1 / 2 - lift, MAT_WOOD, 40, 0);
                    ck_vents(g, x0 / 2 + 3, y0 / 2 + 3 + dy / 2, x1 / 2 - 18, y0 / 2 + 8 + dy / 2);
                    ck_point(g, x1 / 2 - 3, y1 / 2 - lift - foot - 2, RP.leaf_l);
                }
                ck_sym(g, px_sym(i), x1 - 16, y0 + 13 + dy, 22, ink, base, mat_acc(mat), u);
                int lx = x0 + (x1 - x0 - pf_width(&PF_PIXEL11, menu_items[i], 2)) / 2 + 1;
                if (lx > x0 + 6) lx = x0 + 6;
                if (sh) pf_text(g, &PF_PIXEL11, lx, y1 - 3 - 2 * foot + dy, menu_items[i], sh, 2);
                pf_text(g, &PF_PIXEL11, lx, y1 - 5 - 2 * foot + dy, menu_items[i], ink, 2);
            } else {
                ck_sym(g, px_sym(i), (x0 + x1) / 2, y0 + 17 + dy, 26, ink, base, i == 2 ? RP.key : mat_acc(mat), u);
                int lw = text_w(F(a, F_SEMI11), menu_items[i], 0);
                txt(a, g, F_SEMI11, (x0 + x1) / 2 - lw / 2, y1 - 7 + dy, menu_items[i], ink, 0);
            }
            if (foc) ck_pointer(g, x0 - 8 < 0 ? 0 : x0 - 8, (i == 0 ? y0 + 76 : y0 + 12) + dy, a->now_ms, RP.walnut_d, RP.cream);
        }
    px_vine_t(g, a->now_ms, 312, 2 * (RM_LY + 4), 112);
    draw_nowbar(a, g);
    /* where he looks: the panel you're on, from his eyes (about (31, 8)) */
    int cx = (RH_CELL[cur].x0 + RH_CELL[cur].x1) / 4, cy = (RH_CELL[cur].y0 + RH_CELL[cur].y1) / 4;
    pet_place(a, g, V_MENU, 6, RM_LY, 0, cx > 44 ? 1 : cx < 20 ? -1 : 0, cy > 24);
}

/* ------------------------------------------------------------------ Room: Now playing
 * the wall: the cover framed like the posters, the song beside it; the shelf's light bar is
 * the progress; Bubloo on the desk, looking at it */
static int room_now(app *a, gfx *g)
{
    const int ly = 7;                                        /* a shelf across the top */
    ck_material(g, 0, 0, 160, ly, MAT_WOOD, 9, 0);
    uint32_t len = a->ps.length_ms, at = a->ps.elapsed_ms;
    int seeking = a->seek_ms && a->now_ms - a->seek_ms < 1500;
    if (seeking) at = a->seek_to;
    int fill = len ? (int)((uint64_t)160 * (at > len ? len : at) / len) : 0;
    ck_rect(g, 0, ly, 160, ly + 1, RP.silver_d);                /* its light bar: how far in */
    ck_rect(g, 0, ly, fill, ly + 1, seeking ? RP.key : RP.led);
    ck_rect(g, 0, ly + 1, fill, ly + 2, blend565(RP.wall, RP.led, 140));
    ck_rect(g, fill, ly + 1, 160, ly + 2, RP.wall_sh);
    px_battery(a, g, LCD_W - 8, 10, RP.cream);
    const lib_track *t = a->cur_valid ? lib_get(a->L, a->cur) : NULL;
    char e[16], tot[16];
    mmss(e, sizeof e, at / 1000);
    mmss(tot, sizeof tot, len ? len / 1000 : (t ? t->dur : 0));
    /* the poster: walnut frame, a cream mat, the cover */
    const int fx = 12, fy = 26, cs = 122;
    g_fill(g, fx + 3, fy + 3, cs + 16, cs + 16, RP.wall_sh);
    g_fill(g, fx, fy, cs + 16, cs + 16, RP.walnut_d);
    g_fill(g, fx + 2, fy + 2, cs + 12, cs + 12, RP.cream);
    if (a->cur_valid) cover(a, g, a->cur, ART_L, fx + 8, fy + 8, cs);
    else g_fill(g, fx + 8, fy + 8, cs, cs, RP.parch_d);
    const int x0 = 168, x1 = LCD_W - 10;
    txt(a, g, F_MONO10, x0, 38, e, seeking ? RP.key_d : RP.ink, 0);
    if (a->ps.playing && a->cur_valid) g_fill(g, x0 + text_w(F(a, F_MONO10), e, 0) + 4, 31, 5, 5, RP.red);
    txt_right(a, g, F_MONO10, x1, 38, tot, RP.sub);
    if (t) {
        char lines[3][TEXT_LINE_MAX];
        int nl = text_wrap(F(a, F_POSTER15), t->title, x1 - x0, 3, T_TRACK(-3), lines), y = 60;
        for (int i = 0; i < nl; i++) txt(a, g, F_POSTER15, x0, y + i * 16, lines[i], RP.ink, T_TRACK(-3));
        y += (nl - 1) * 16 + 16;
        txt_fit(a, g, F_SEMI12, x0, y, t->artist, x1 - x0, RP.leaf_d, 0);
        if (a->why[0]) {
            char wl[2][TEXT_LINE_MAX];
            int nw = text_wrap(F(a, F_BODY10), a->why, x1 - x0, 2, 0, wl);
            for (int i = 0; i < nw; i++) txt(a, g, F_BODY10, x0, y + 17 + i * 12, wl[i], RP.sub, 0);
            y += 17 + (nw - 1) * 12;
        }
        if (brain_is_liked(a->cur)) {
            ck_sym(g, SYM_LIKED, x0 + 6, y + 14, 12, RP.red, RP.wall, 0, 1);
            txt(a, g, F_BODY10, x0 + 16, y + 18, "liked", RP.ink, 0);
        }
    } else {
        txt(a, g, F_POSTER15, x0, 60, "Nothing on.", RP.ink, T_TRACK(-3));
        txt(a, g, F_BODY10, x0, 78, "Spin the wheel and press play.", RP.sub, 0);
    }
    /* the desk: what's next, and Bubloo */
    const int dy0 = 176;
    ck_material(g, 0, dy0 / 2, 160, LCD_H / 2, MAT_WOOD, 12, 0);
    ck_rect(g, 0, dy0 / 2 + 1, 160, dy0 / 2 + 2, RP.walnut_d);
    if (a->notice[0]) txt_fit(a, g, F_BOLD11, 10, dy0 + 32, a->notice, 200, RP.cream, 0);
    else {
        uint32_t nx = a->qpos + 1 < a->qn ? a->q[a->qpos + 1] : LIB_NONE;
        if (nx != LIB_NONE) {
            const lib_track *n = lib_get(a->L, nx);
            g_fill(g, 9, dy0 + 13, 38, 38, RP.walnut_d);
            cover(a, g, nx, ART_S, 10, dy0 + 14, 36);
            txt(a, g, F_MONO10, 54, dy0 + 24, a->qsrc[a->qpos + 1] == QS_AUTO ? "next, autoplay" : "next", RP.felt_l, 0);
            if (n) {
                txt_fit(a, g, F_BOLD11, 54, dy0 + 38, n->title, 150, RP.cream, 0);
                txt_fit(a, g, F_BODY10, 54, dy0 + 50, n->artist, 150, RP.felt_l, 0);
            }
        }
    }
    pet_place(a, g, V_NOW, 120, dy0 / 2, 1, -1, 0);
    return 1;
}

/* ------------------------------------------------------------------ the door (power on, off)
 * Power on: a dark hall, the door shut, music behind it -- light under the door going with
 * the beat, notes slipping out under it; it swings open, the room's light falls out, and
 * you walk in to Bubloo on the shelf. Power off: back out of the room, the door swings shut
 * on it, the light under it goes out. Everything is in cells; the camera is a scale k about
 * the doorway and an offset of the room behind it. */
static const px16 DR_HALL = C565(0x2a, 0x22, 0x1c), DR_HALL_D = C565(0x1b, 0x16, 0x12),
                  DR_FLOOR = C565(0x35, 0x2b, 0x23), DR_DOOR = C565(0xec, 0xea, 0xe3),
                  DR_DOOR_S = C565(0xd6, 0xd3, 0xca), DR_DOOR_L = C565(0xb8, 0xb4, 0xaa),
                  DR_TRIM = C565(0xe2, 0xdf, 0xd6), DR_TRIM_S = C565(0xa9, 0xa5, 0x9b),
                  DR_BRASS = C565(0xd8, 0xae, 0x52), DR_BRASS_D = C565(0x8e, 0x6a, 0x2a);
#define DR_X0 55                /* the doorway at k = 1, cells; it stands on the floor at DR_Y1 */
#define DR_X1 105
#define DR_Y0 10
#define DR_Y1 112
#define DR_FX 80.0f             /* what the camera walks towards */
#define DR_FY 58.0f

typedef struct { float k, theta, light; int shake; } dr_cam;

static float dr_io(float u)
{
    u = ez_clamp(u);
    return u < .5f ? 4 * u * u * u : 1 - (-2 * u + 2) * (-2 * u + 2) * (-2 * u + 2) / 2;
}

/* a note, outlined so it reads on the door and in the dark */
static void dr_note(gfx *g, int x, int y, int kind, px16 c, px16 o)
{
    static const char *const N[2][6] = { { "..#..", "..##.", "..#.#", "..#..", "###..", "###.." },
                                         { "..#####", "..#...#", "..#...#", "###.###", "###.###", "......." } };
    for (int pass = 0; pass < 2; pass++)
        for (int r = 0; r < 6; r++)
            for (int q = 0; N[kind][r][q]; q++)
                if (N[kind][r][q] == '#') ck_point(g, x + q + (pass ? 0 : 1), y + r + (pass ? 0 : 1), pass ? c : o);
}

/* notes out of the room: from under the door while it's shut, then out of the doorway */
static void dr_notes(gfx *g, uint32_t t, uint32_t t_end, float ox0, float ox1, float oy1, float open)
{
    for (int j = 0; j < 18; j++) {
        uint32_t born = 60 + (uint32_t)j * 80, life = 1100;
        if (t < born || t > born + life || born > t_end) continue;
        float u = (float)(t - born) / life, h = (float)(pet_hash((uint32_t)j * 7919u) % 1000) / 1000.0f;
        float sx = ox0 + 3 + h * (ox1 - ox0 - 8), sy = open > .3f ? oy1 - 30 * h - 8 : oy1 - 3;
        float x = sx + (h - .5f) * 40 * u + sinf(u * 9 + j) * 2, y = sy - 38 * u;
        dr_note(g, (int)x, (int)y, j % 3 == 1, u > .75f ? RP.key_d : RP.key, DR_HALL_D);
    }
}

/* everything but the room: the hall around the doorway, its casing, the door, the light */
static void dr_hall(gfx *g, const dr_cam *c)
{
    float k = c->k;
    float ox0 = DR_FX + (DR_X0 - DR_FX) * k, ox1 = DR_FX + (DR_X1 - DR_FX) * k;
    float oy0 = DR_FY + (DR_Y0 - DR_FY) * k, oy1 = DR_FY + (DR_Y1 - DR_FY) * k;
    int a0 = (int)lrintf(ox0), a1 = (int)lrintf(ox1), b0 = (int)lrintf(oy0), b1 = (int)lrintf(oy1);
    /* the hall: wall, a skirting, the floor */
    int base = (int)lrintf(oy1 - 3 * k);
    for (int y = 0; y < 120; y++) {
        px16 col = y >= b1 ? DR_FLOOR : y >= base ? blend565(DR_TRIM_S, DR_HALL, 120) : DR_HALL;
        if (y < b0 || y >= b1) ck_rect(g, 0, y, 160, y + 1, col);
        else { ck_rect(g, 0, y, a0 < 0 ? 0 : a0, y + 1, col); ck_rect(g, a1 > 160 ? 160 : a1, y, 160, y + 1, col); }
    }
    /* a mat at the door */
    int m0 = (int)lrintf(ox0 + 5 * k), m1 = (int)lrintf(ox1 - 5 * k), mb = (int)lrintf(oy1 + 1 + 3 * k);
    if (b1 + 1 < 120) {
        ck_rect(g, m0 - 1, b1 + 1, m1 + 1, mb, RP.sage_d);
        ck_rect(g, m0, b1 + 2, m1, mb - 1, C565(0x4a, 0x55, 0x2a));
    }
    /* the light out of the room on the hall floor; under the door when it's shut */
    if (c->light > 0) {
        float open = sinf(c->theta);
        for (int y = b1 < 0 ? 0 : b1; y < 120; y++) {
            float d = (y - oy1) / k, spread = d * (.4f + 1.2f * open);
            int x0 = (int)(ox0 + (ox1 - ox0) * (1 - open) * .9f - spread * .3f), x1 = (int)(ox1 + spread);
            int al = (int)(c->light * (open > .05f ? 150 : 110) * (1 - d / 18.0f));
            if (al <= 0) continue;
            for (int x = x0 < 0 ? 0 : x0; x < x1 && x < 160; x++)
                ck_point(g, x, y, blend565(g->px[2 * y * g->stride + 2 * x], RP.led, al));
        }
    }
    /* the casing */
    int cw = (int)lrintf(3 * k) < 2 ? 2 : (int)lrintf(3 * k);
    ck_rect(g, a0 - cw, b0 - cw, a0, b1, DR_TRIM);
    ck_rect(g, a1, b0 - cw, a1 + cw, b1, DR_TRIM);
    ck_rect(g, a0 - cw, b0 - cw, a1 + cw, b0, DR_TRIM);
    ck_rect(g, a0 - cw, b0 - cw, a0 - cw + 1, b1, DR_TRIM_S);
    ck_rect(g, a1 + cw - 1, b0 - cw, a1 + cw, b1, DR_TRIM_S);
    ck_rect(g, a0, b0, a1, b0 + 1, DR_TRIM_S);
    /* the door, hinged on the left, turning away into the room */
    float th = c->theta, cs = cosf(th), sn = sinf(th), H = oy1 - oy0, eye = oy0 + H * .45f;
    float fx = ox0 + (ox1 - ox0) * cs, s = 1 / (1 + .5f * sn);
    float ft = eye + (oy0 - eye) * s, fb = eye + (oy1 - 1 - eye) * s;
    int sh = c->shake, fxi = (int)lrintf(fx);
    px16 face = blend565(DR_DOOR, DR_HALL, (int)(sn * 120)), sface = blend565(DR_DOOR_S, DR_HALL, (int)(sn * 120)),
         line = blend565(DR_DOOR_L, DR_HALL, (int)(sn * 120));
    for (int x = a0; x < fxi; x++) {
        float u = (x + .5f - ox0) / (fx - ox0);
        int top = (int)lrintf(oy0 + (ft - oy0) * u), bot = (int)lrintf(oy1 - 1 + (fb - (oy1 - 1)) * u);
        for (int y = top; y < bot; y++) {
            float v = (y + .5f - top) / (float)(bot - top);
            int stile = u < .12f || u > .88f, rail = v < .06f || (v > .46f && v < .53f) || v > .93f;
            px16 col = stile || rail ? face : sface;
            if (!stile && !rail && ((v > .06f && v < .085f) || (v > .53f && v < .555f) || u < .15f)) col = line;
            ck_point(g, x + sh, y, x == fxi - 1 && th > .05f ? line : col);
        }
    }
    if (th < 1.2f) {                                  /* the knob */
        float u = .86f, top = oy0 + (ft - oy0) * u, bot = oy1 - 1 + (fb - (oy1 - 1)) * u;
        int kx = (int)lrintf(ox0 + (fx - ox0) * u) + sh, ky = (int)lrintf(top + (bot - top) * .52f);
        int kr = k > 1.5f ? 2 : 1;
        ck_rect(g, kx - kr, ky - kr, kx + kr, ky + kr, DR_BRASS);
        ck_point(g, kx + kr - 1, ky + kr - 1, DR_BRASS_D);
    }
    if (th < .05f && k < 1.05f) {                     /* the name on the door */
        int w = pf_width(&PF_PIXEL11, "Coda", 2), px0 = 2 * a0 + (2 * (a1 - a0) - w) / 2 + 2 * sh;
        ck_rrect(g, px0 / 2 - 3, b0 + 13, (px0 + w) / 2 + 3, b0 + 23, RP.walnut_d, 1);
        ck_material(g, px0 / 2 - 2, b0 + 14, (px0 + w) / 2 + 2, b0 + 22, MAT_WOOD, 5, 1);
        pf_text(g, &PF_PIXEL11, px0, 2 * (b0 + 14) + 13, "Coda", RP.cream, 2);
    }
    if (th < .02f && c->light > 0) {                  /* the gap under the door */
        px16 lc = blend565(RP.walnut_hi, RP.led, (int)(c->light * 256));
        ck_rect(g, a0 + 1, b1 - 1, a1 - 1, b1, lc);
    }
}

/* the room behind the door, moved by (dx, dy) cells; t drives Bubloo */
static void dr_room(gfx *g, uint32_t t, int dx, int dy, int blink)
{
    g_fill(g, 0, 0, LCD_W, LCD_H, RP.wall);
    rm_shelf(NULL, g, t);
    rm_furniture(g);
    ck_material(g, 0, BAR_Y / 2, 160, LCD_H / 2, MAT_WOOD, 5, 0);
    px_vine_t(g, t, 312, 2 * (RM_LY + 4), 112);
    cat_pose p;
    memset(&p, 0, sizeof p);
    p.t = t; p.eyes = blink ? 0 : 2; p.sway = .25f; p.inhale = t % 2600 < 1100;
    cat_draw(g, 6, RM_LY, 0, &p);
    if (dx || dy) {                                   /* shift what was drawn (the walk in) */
        int sx = 2 * dx, sy = 2 * dy;
        for (int y = LCD_H - 1; y >= 0; y--) {         /* dx, dy >= 0: copy from up-left, bottom-right first */
            px16 *row = g->px + y * g->stride;
            int fy = y - sy;
            if (fy < 0) { for (int x = 0; x < LCD_W; x++) row[x] = RP.wall; continue; }
            px16 *src = g->px + fy * g->stride;
            for (int x = LCD_W - 1; x >= 0; x--) row[x] = x - sx >= 0 ? src[x - sx] : RP.wall;
        }
    }
}

static void room_boot(gfx *g, uint32_t t)
{
    float tf = (float)t;
    dr_cam c = { 1, 0, 1, 0 };
    c.theta = 1.45f * dr_io(ez_seg(tf, 520, 980));
    float push = dr_io(ez_seg(tf, 820, 1450));
    c.k = 1 + 2.7f * push * push;
    int beat = (t > 110 && t < 170) || (t > 350 && t < 410);
    c.shake = beat && c.theta == 0 ? 1 : 0;
    c.light = c.theta > 0 ? 1 : .55f + (beat ? .45f : .15f * sinf(tf / 60.0f));
    if (t < 40) c.light = .7f;
    /* the room: Bubloo framed in the doorway, sliding home as we walk in */
    int dx = (int)lrintf(52 * (1 - push)), dy = (int)lrintf(22 * (1 - push));
    dr_room(g, t, dx, dy, t > 1480 && t < 1560);
    if (push < 1) {
        dr_hall(g, &c);
        float k = c.k;
        dr_notes(g, t, 1300, DR_FX + (DR_X0 - DR_FX) * k, DR_FX + (DR_X1 - DR_FX) * k, DR_FY + (DR_Y1 - DR_FY) * k,
                 sinf(c.theta));
    }
}

static void room_off(app *a, gfx *g, uint32_t t, const px16 *from)
{
    (void)a;
    float tf = (float)t, back = dr_io(ez_seg(tf, 0, 380));
    dr_cam c = { 1 + 2.7f * (1 - back) * (1 - back), 1.45f * (1 - dr_io(ez_seg(tf, 340, 700))), 1, 0 };
    if (t > 690 && t < 740) c.shake = 1;                  /* it shuts */
    c.light = t < 760 ? 1 : 0;
    /* the room as it was, slid off as we back out */
    int sx = 2 * (int)lrintf(52 * back), sy = 2 * (int)lrintf(22 * back);
    for (int y = 0; y < LCD_H; y++) {
        px16 *row = g->px + y * g->stride;
        int fy = y - sy;
        for (int x = 0; x < LCD_W; x++) {
            int fx = x - sx;
            row[x] = from && fy >= 0 && fy < LCD_H && fx >= 0 && fx < LCD_W ? from[fy * LCD_W + fx] : RP.wall;
        }
    }
    dr_hall(g, &c);
    if (t < 700) {                                        /* the music, until the door's shut on it */
        float k = c.k;
        dr_notes(g, t + 500, 500 + 260, DR_FX + (DR_X0 - DR_FX) * k, DR_FX + (DR_X1 - DR_FX) * k,
                 DR_FY + (DR_Y1 - DR_FY) * k, sinf(c.theta));
    }
    if (t > 760) {                                        /* then the hall goes dark */
        int k = (int)(256 * ez_out(ez_seg(tf, 760, 900)));
        for (int y = 0; y < LCD_H; y++) {
            px16 *row = g->px + y * g->stride;
            for (int x = 0; x < LCD_W; x++) row[x] = blend565(row[x], C565(0, 0, 0), k);
        }
    }
}
