/* Diorama's shelf and PC case, drawn cell by cell from the photo of the desk wall
 * (Downloads/20261011_1600340.jpg) at the photo's own scale along the shelf -- its 121
 * cells are the real shelf's length -- with the shading and the small things the posters
 * have: the aloe, the succulent and the dark spiky one in their white pots, the piranha plants, the silver
 * frame, the green train with the blue disc, the clock, Luigi, the block figures; and the
 * Fractal Terra on its walnut foot, seen from the side: the lattice front with its blue
 * light, the top's two panels, the bare aluminium side, the round power button.
 * Part of th_dio.h (dmap, drect, dp, the DC_ colours). */

/* where the clock is on the shelf (its face and hands are drawn round this, in cells) */
#define DC_CLOCK_X 96.5f
#define DC_CLOCK_Y 14.5f

static void dio_shelf_things(void)
{
    /* far left: the little green figure */
    static const char *const FIG[6] = { ".mmm.", "mkmkm", "mmmmm", "MmkmM", ".mmm.", ".M.M." };
    const px16 figc[3] = { H(0x5bb6a6), H(0x3b8a7e), DC_BLACK };
    dmap(22, 18, FIG, 6, "mMk", figc, DO_NONE);

    /* the piranha plant, behind them: red head, white spots and lips, open mouth */
    static const char *const PIRH[11] = {
        "....rRRRr....", "..rRRWRRRRr..", ".rRRRRRRRWRr.", ".RWRRRRRRRRRr", "rRRRRRRWRRRRr",
        "LLLLLLLLLLLLL", "kkTkkkTkkkTkk", "LLLLLLLLLLLLL", "rRRRWRRRRRRRr", ".rRRRRRWRRRr.", "..rrRRRRRrr.." };
    const px16 pirc[6] = { H(0xd8382c), H(0x9e2420), H(0xf6f3ee), H(0xece6dc), H(0x3a1416), H(0xffffff) };
    if (!dio_plain) dmap(38, 0, PIRH, 11, "RrWLkT", pirc, DO_NONE);
    static const char *const PIRS[7] = { ".....gG.....", "..llLgG.....", ".lLLdgG..ll.", "lLd..gGdLLl.",
                                         ".....gGLd...", ".....gG.....", ".....gG....." };
    const px16 stc[5] = { H(0x4f8f3e), H(0x2f6a2c), H(0x7cc35a), H(0x4f9a3c), H(0x2f6a2c) };
    if (!dio_plain) dmap(38, 11, PIRS, 7, "gGlLd", stc, DO_NONE);

    /* the silver frame and its picture */
    drect(44, 6, 56, 24, H(0xaeb1b4), DO_NONE);
    drect(44, 6, 56, 7, H(0xe4e6e7), DO_NONE);
    drect(44, 6, 45, 24, H(0xd9dbdc), DO_NONE);
    drect(55, 7, 56, 24, H(0x8a8e92), DO_NONE);
    drect(46, 8, 54, 22, H(0xf4f5f2), DO_NONE);         /* the mat */
    static const char *const PIC[12] = {
        "111111", "112111", "111111", "122211", "222222", "232222", "333322", "334333",
        "344433", "444444", "435444", "444444" };
    const px16 picc[5] = { H(0xe2ecf0), H(0xc6dbe4), H(0xa9cdb9), H(0x6f9a86), H(0x3c5f52) };
    dmap(47, 9, PIC, 12, "12345", picc, DO_NONE);

    /* the aloe, spiky, in a white pot; the plump succulent beside it in another */
    static const char *const ALOE[7] = {
        "..e.....e......", ".aA....aA...e..", ".aAq..aAq..aA..", "..aAqaAq..aAq..",
        "...aAAAqaaAq...", "..eaAAAAAAAq...", "...qAAAAAAq...." };
    const px16 aloec[4] = { H(0xc9e2c2), H(0x9fc7a0), H(0x6f9f77), H(0x4a7556) };
    dmap(24, 11, ALOE, 7, "eaAq", aloec, DO_NONE);
    static const char *const POT[7] = { "vwwWWWWWw", "vwWWWWWWw", ".vwWWWWw.", ".vwWWWWw.", ".vwWWWWw.", ".vvwWWWw.", "..vvwww.." };
    const px16 potc[3] = { H(0xf2f1ec), H(0xdcdad3), H(0xb9b6ad) };
    dmap(27, 17, POT, 7, "Wwv", potc, DO_NONE);
    /* the dark spiky one sharing the second pot, its blades over the succulent's shoulder */
    static const char *const SPIKE[8] = {
        "..k....k..", "..kK..kK..", "...kK.kK.k", "k..kKkK.kK", ".kK.kKKkK.", "..kKkKKK..", "...kKKKk..", "....kKk..." };
    const px16 spkc[2] = { H(0x3e5f3c), H(0x27412a) };
    dmap(36, 9, SPIKE, 8, "kK", spkc, DO_NONE);
    static const char *const SUCC[6] = {
        "...p..p...", "..uUpUu...", ".puUjUup..", "uUjUuUjUu.", ".UjjUjjU..", "..jjjjj..." };
    const px16 succ[4] = { H(0xd9a3a8), H(0xa8c9b0), H(0x7aa489), H(0x557f68) };
    dmap(37, 12, SUCC, 6, "puUj", succ, DO_NONE);
    dmap(37, 17, POT, 7, "Wwv", potc, DO_NONE);

    /* the fern's black pot (its fronds move: dio_plants), the blue disc, the green train
     * with two little riders */
    drect(61, 15, 72, 23, DC_BLACK, DO_NONE);
    drect(61, 15, 72, 16, DC_BLACK2, DO_NONE);
    drect(70, 16, 72, 23, H(0x18171a), DO_NONE);
    static const char *const DISC[5] = { ".cBB.", "cBBBb", "BBbBb", "BBBbb", ".bbb." };
    const px16 dc[3] = { H(0x9cc0f2), H(0x3d6fd1), H(0x254a96) };
    dmap(45, 19, DISC, 5, "cBb", dc, DO_NONE);
    static const char *const TRAIN[5] = {
        "........R.....yy....", ".......RkR...yky....", ".TTTTTTTTTTTTTTTTTT.", "TtWTtTTWTtTTTWTtTTTt", ".nkkn.nkkn..nkkn.nn." };
    const px16 trc[6] = { H(0x58b04a), H(0x3b8434), H(0xf3f2ee), H(0x24502a), DC_BLACK, H(0xd8382c) };
    const px16 trc2[7] = { trc[0], trc[1], trc[2], trc[3], trc[4], trc[5], H(0xe8c84a) };
    dmap(50, 19, TRAIN, 5, "TtWnkRy", trc2, DO_NONE);

    /* the ivy's pot, between the fern and the clock (its leaves and strands move: dio_plants) */
    drect(77, 18, 86, 24, H(0x2b2b2f), DO_NONE);
    drect(76, 18, 87, 19, H(0x45454b), DO_NONE);          /* its rim */
    drect(84, 19, 86, 24, H(0x1d1d20), DO_NONE);          /* its shaded side */
    drect(78, 19, 84, 20, H(0x38383d), DO_NONE);

    /* the clock: a white rim, its face; the marks and hands go over at full resolution
     * (dio_clock_hands), so it reads the time */
    ddisc(DC_CLOCK_X, DC_CLOCK_Y, 7.8f, H(0xb9b8b2), DO_WHEEL);
    ddisc(DC_CLOCK_X, DC_CLOCK_Y, 7.1f, DC_WHITE2, DO_WHEEL);
    ddisc(DC_CLOCK_X, DC_CLOCK_Y, 6.5f, DC_WHITE, DO_WHEEL);
    /* the plush in the green cap */
    static const char *const LU[19] = {
        "....gggggggg....", "..gggggggggggg..", ".ggggggWWWgggggg", ".gggggWWLWWggggg", "ggggggWLWWggggGg",
        "gggggggWWWgggGGg", "GGGGGGGGGGGGGGG.", "..ssssssssssss..", ".sssSesssSessss.", ".ssssssssssssss.",
        "..ssnnnnnnnss...", "...SsnnnnsS.....", "..GbbbBBBbbbG...", ".GGbbyBbbybbGG..", ".WWbbbbbbbbbWW..",
        ".WWbbbbbbbbbWW..", "..bbbbbbbbbbb...", "..bbbb...bbbb...", ".oooo.....oooo.." };
    const px16 luc[11] = { H(0x3f9a45), H(0x2e7a36), H(0xf3f2ee), H(0x2e7a36), H(0xf2c9a0), H(0xd9a882),
                           H(0x2a3a7a), H(0x5a3a28), H(0x2d4f9e), H(0x4a6fc2), H(0xe8c84a) };
    const px16 luc2[12] = { luc[0], luc[1], luc[2], luc[3], luc[4], luc[5], luc[6], luc[7], luc[8], luc[9], luc[10],
                            H(0x6b4a32) };
    /* the second piranha plant peeks over his cap */
    static const char *const PIR2[6] = { "...rRRRr...", ".rRWRRRRWr.", "rRRRRRWRRRr", "LLLLLLLLLLL", "kkTkkTkkTkk", "LLLLLLLLLLL" };
    if (!dio_plain) {
        dmap(109, 0, PIR2, 6, "RrWLkT", pirc, DO_NONE);
        dmap(104, 5, LU, 19, "gGWLsSenbByo", luc2, DO_NONE);
    }

    /* the pothos's pot at the end (its leaves move: dio_plants) */
    drect(134, 17, 141, 24, DC_WHITE, DO_LIKED);
    drect(139, 17, 141, 24, DC_WHITE2, DO_LIKED);
    drect(134, 17, 141, 18, H(0xe7e5df), DO_LIKED);    /* the blue box figure and the yellow block figure, faces and all */
    static const char *const BOX[5] = { "cccccccc", "ckccccck", "ccccmccc", "dccccccd", "dddddddd" };
    const px16 boxc[4] = { H(0x9fd0ee), DC_BLACK, H(0x5a92bd), H(0x7ab3d9) };
    dmap(120, 19, BOX, 5, "ckmd", boxc, DO_NONE);
    static const char *const BLK[8] = {
        "yyyyyyyyY", "yyyyyyyyY", "ykyyyykyY", "ypyyyypyY", "yyykkyyyY", "yyyyyyyyY", "YyyyyyyYZ", "ZYYYYYYZZ" };
    const px16 blkc[5] = { H(0xf3d84f), H(0xe0bc35), DC_BLACK, H(0xeb8f7f), H(0xc29a22) };
    dmap(128, 16, BLK, 8, "yYkpZ", blkc, DO_NONE);

}

/* the shelf itself: walnut with its grain, the top's lit edge, the light bar under it */
static void dio_shelf_board(void)
{
    for (int y = 24; y < 29; y++)
        for (int x = 20; x < 141; x++) {
            uint32_t h = pet_hash((uint32_t)(x / 3 * 97 + y * 13));
            px16 c = h % 7 == 0 ? RP_DAY.walnut_l : h % 11 == 0 ? RP_DAY.walnut_d : RP_DAY.walnut;
            if ((x + y * 5) % 23 < 3) c = H(0x7a5236);                 /* the grain's long streaks */
            dp(x, y, c, DO_NONE);
        }
    drect(20, 24, 141, 25, RP_DAY.walnut_hi, DO_NONE);
    drect(20, 28, 141, 29, RP_DAY.walnut_d, DO_NONE);
    drect(140, 24, 141, 29, RP_DAY.walnut_d, DO_NONE);
}

/* the Fractal Terra, seen from its right: in cells x0..x0+25, y0..y0+34 */
static void dio_terra(int x0, int y0)
{
    /* the top: two brushed panels, a seam between them */
    for (int y = 0; y < 4; y++)
        for (int x = 3 - y; x < 25 - y; x++)
            dp(x0 + x, y0 + y, x == 3 - y ? H(0x9b958d) : (x + y) % 9 == 4 ? H(0x8a857e) : H(0xa7a29a), DO_LIBRARY);
    dline(x0 + 12, y0, x0 + 9, y0 + 3, H(0x6f6a64), DO_LIBRARY);
    /* the front, in the shade: the lattice, its blue light */
    for (int y = 3; y < 29; y++)
        for (int x = 0; x < 6; x++) {
            px16 c = (x + y) % 2 ? H(0x5e6670) : H(0x7c8692);
            if (x == 5) c = H(0x4a5058);
            if (y >= 11 && y < 15 && x >= 1 && x < 4) c = y == 12 || y == 13 ? H(0xb8d6ff) : H(0x6f9ee0);
            dp(x0 + x, y0 + y, c, DO_LIBRARY);
        }
    /* the side: bare aluminium, a fine speckle, lighter to the top */
    for (int y = 4; y < 29; y++)
        for (int x = 6; x < 25; x++) {
            px16 c = y < 8 ? H(0xdcd9d2) : H(0xcfccc5);
            if (pet_hash((uint32_t)(x * 53 + y * 101)) % 9 == 0) c = H(0xbebbb3);
            if (x == 24) c = H(0xb3b0a9);
            dp(x0 + x, y0 + y, c, DO_LIBRARY);
        }
    drect(x0 + 6, y0 + 4, x0 + 25, y0 + 5, H(0xe8e6e0), DO_LIBRARY);
    /* the walnut foot and the round power button at its front */
    for (int y = 29; y < 34; y++)
        for (int x = 1; x < 25; x++)
            dp(x0 + x, y0 + y, y == 29 ? H(0x82593c) : (x * 7 + y * 3) % 11 < 2 ? H(0x5a3c28) : H(0x6b4a32), DO_LIBRARY);
    drect(x0 + 1, y0 + 33, x0 + 25, y0 + 34, H(0x3e2a1c), DO_LIBRARY);
    ddisc(x0 + 8.5f, y0 + 31.5f, 1.3f, H(0xeeeeec), DO_LIBRARY);
}

/* the earbuds' case, lid down; its light (lit by the caller) says how full the buds are */
static void dio_buds_case(int x, int y, int level)
{
    drect(x + 1, y, x + 7, y + 1, H(0x9aa1a8), DO_NONE);          /* the smoked lid, rounded */
    drect(x, y + 1, x + 8, y + 3, H(0x858c93), DO_NONE);
    drect(x, y + 1, x + 8, y + 2, H(0xb0b6bc), DO_NONE);
    drect(x, y + 3, x + 8, y + 5, H(0xe4e4e6), DO_NONE);          /* the white body */
    drect(x, y + 4, x + 8, y + 5, H(0xc9c9cc), DO_NONE);
    if (level >= 0) {
        dio_emit = 1;
        dp(x + 4, y + 3, level >= 50 ? H(0x5bd36f) : level >= 20 ? H(0xf2a43a) : H(0xe5484d), DO_NONE);
        dio_emit = 0;
    }
}
