"""Six pixel directions for Coda on the H2, each after a reference that holds up (none of
the stock "pixel music player" kits), all in the listener's room colours:

  jukebox   Stardew Valley's jukebox: a heavy two-tone wood frame, songs in parchment slots,
            the name on a sign hung from the wall
  toybox    Nintendo's DSi Sound: a checkerboard, two giant toy buttons, round buttons for the
            rest, a speech-bubble label; Now playing is a toy (bubbles rise with the music)
  deck      Winamp done right: a silver and walnut deck, amber display, spectrum, playlist
            window, the sections as its tabs
  crate     beatbit's cover grid: eight tiles, each a cover rendered as pixel art; the one
            the cursor is on pulls into focus
  receiver  a walnut hi-fi receiver: amber dot-matrix glass; the menu is a radio dial the
            click wheel tunes; Now playing has two VU meters
  room      the listener's own desk corner as the menu: the clock is the Wheel, headphones
            are Now playing, the posters are covers, the pothos is Liked

Output: docs/h2/pixel/<dir>_*.png, sheet.png, <dir>.gif
  .venv/Scripts/python firmware/tools/mock_pixel.py [--still]
"""
import math, random, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_menu as M
import mock_inner as I
import mock_room as R
from mock_room import (C, Grid, rrect, rr_mask, texture, vents, gsym, cursor, text1, pix,
                       pixel_face, tw, fit, wrap, W, H, FPS)

OUT = M.ROOT / 'docs' / 'h2' / 'pixel'
FD = M.ROOT / 'firmware' / 'assets' / 'fonts'
TR = I.TR
ITEMS = M.ITEMS
MENU = M.MENU

def silk(px):
    return ImageFont.truetype(str(FD / 'Silkscreen.ttf'), px)

def base(col=None):
    return Image.new('RGBA', (W, H), (col or C['wall']) + (255,))

def cover(path, px):
    return I.art(path, px).resize((px, px), Image.LANCZOS)

def nowbar(im):
    g = Grid()
    R.nowbar(g, im)
    g.onto(im)
    R.nowbar_1x(im)


# ================================================================== 1. jukebox
PARCH, PARCH_D, PARCH_L = (0xf2, 0xdc, 0xae), (0xe2, 0xc5, 0x8e), (0xf8, 0xea, 0xca)
SLOT, SLOT_B, SLOT_SEL = (0xec, 0xd2, 0x9e), (0xb9, 0x88, 0x50), (0xd2, 0x86, 0x3a)

def wood_frame(g, a, b, c, d, fill=PARCH):
    rrect(g.d, a, b, c, d, C['walnut_d'], 2)
    rrect(g.d, a + 1, b + 1, c - 1, d - 1, C['walnut'], 2)
    g.d.line([(a + 3, b + 1), (c - 4, b + 1)], fill=C['walnut_hi'])
    g.d.line([(a + 1, b + 3), (a + 1, d - 4)], fill=C['walnut_hi'])
    g.d.line([(a + 3, d - 2), (c - 4, d - 2)], fill=C['walnut_d'])
    g.d.line([(c - 2, b + 3), (c - 2, d - 4)], fill=C['walnut_d'])
    rrect(g.d, a + 3, b + 3, c - 3, d - 3, C['walnut_d'], 1)
    rrect(g.d, a + 4, b + 4, c - 4, d - 4, fill, 1)

def wallpaper(g, col=(0xcd, 0xb8, 0x97)):
    for y in range(0, 120, 4):
        for x in range((y // 4) % 2 * 2, 160, 4):
            g.d.point((x, y), fill=col)

def sign(g, a, b, c, d, text):
    g.im.paste(texture('wood', c - a, d - b, 81), (a, b))
    rrect(g.d, a - 1, b - 1, c + 1, d + 1, C['walnut_d'], 1)
    g.im.paste(texture('wood', c - a, d - b, 81), (a, b), rr_mask(c - a, d - b, 1))
    for x in (a + 2, c - 3):
        g.d.point((x, b + 2), fill=C['cream'])
        g.d.point((x, d - 3), fill=C['cream'])
    w = 2 * tw(text, pixel_face())
    g.text(int((a + c) - w / 2), 2 * d - 6, text, C['cream'], C['walnut_d'])

def slot(g, im, y, kind, label, note, sel):
    a, b, c, d = 9, y // 2, 144, y // 2 + 13
    g.d.rectangle([a, b, c - 1, d - 1], fill=SLOT_B)
    g.d.rectangle([a + 1, b + 1, c - 2, d - 2], fill=SLOT_SEL if sel else SLOT)
    g.d.line([(a + 1, b + 1), (c - 2, b + 1)], fill=(0xc2, 0x74, 0x2c) if sel else PARCH_D)
    ink = C['cream'] if sel else C['ink']
    gsym(g, kind, 2 * a + 16, y + 13, 16, ink, SLOT_SEL if sel else SLOT, C['key'] if not sel else None)
    g.text(2 * a + 30, y + 20, label, ink, (0xa0, 0x5c, 0x22) if sel else None)
    if sel:
        cursor(g, 2 * a - 16, y + 13, 0)
    return ink

def jukebox_menu(sel='queue'):
    im, g = base(), Grid()
    wallpaper(g)
    sign(g, 56, 2, 104, 13, 'Coda')
    R.battery(g, im, W - 8, 16, C['ink'])
    wood_frame(g, 3, 16, 157, 120)
    # currently playing, in the frame's head
    g.d.line([(8, 44), (151, 44)], fill=PARCH_D)
    g.d.line([(8, 45), (151, 45)], fill=PARCH_L)
    rrect(g.d, 9, 22, 27, 40, C['walnut_d'], 1)
    items = ['wheel', 'now', 'queue', 'explore', 'search']
    inks = {}
    for i, k in enumerate(items):
        inks[k] = slot(g, im, 96 + i * 28, k, ITEMS[k][0], '', k == sel)
    # the scrollbar, in wood
    g.d.rectangle([148, 48, 151, 116], fill=C['walnut'])
    g.d.rectangle([148, 56, 151, 70], fill=PARCH_L)
    g.d.rectangle([148, 56, 151, 56], fill=C['walnut_hi'])
    g.onto(im)
    t = TR[0]
    im.paste(cover(t[2], 32), (20, 46))
    text1(im, 62, 56, 'Currently playing:', (0x8a, 0x62, 0x3a), size=11, var='SemiBold')
    text1(im, 62, 70, fit(t[0], pix(11, 'SemiBold'), 222), C['ink'], size=11, var='SemiBold')
    text1(im, 62, 83, fit(t[1], pix(10), 222), (0x7a, 0x5a, 0x3a))
    notes = {'wheel': '18,388', 'queue': '3 of 24', 'explore': '2 shelves', 'now': '0:41'}
    for i, k in enumerate(items):
        n = notes.get(k, '')
        if n:
            text1(im, 280 - tw(n, pix(10)), 96 + i * 28 + 17, n, inks[k])
    return im.convert('RGB')

def jukebox_now():
    im, g = base(), Grid()
    wallpaper(g)
    sign(g, 46, 2, 114, 13, 'Now playing')
    R.battery(g, im, W - 8, 16, C['ink'])
    wood_frame(g, 3, 16, 157, 120)
    rrect(g.d, 9, 21, 63, 75, C['walnut_d'], 1)
    g.im.paste(texture('wood', 52, 52, 90), (10, 22))
    t = TR[0]
    lines = wrap(t[0], pixel_face(), 76, 3)
    for i, line in enumerate(lines):
        g.text(138, 58 + i * 20, line, C['ink'])
    # progress: a groove with a wooden knob
    g.d.rectangle([10, 82, 150, 84], fill=C['walnut_d'])
    px_ = 10 + int(140 * .31)
    g.d.rectangle([10, 82, px_, 84], fill=SLOT_SEL)
    rrect(g.d, px_ - 2, 80, px_ + 3, 87, C['walnut'], 1)
    g.d.line([(px_ - 1, 81), (px_ + 1, 81)], fill=C['walnut_hi'])
    # small square wooden buttons, Stardew's size
    for i, (k, w_) in enumerate((('history', 14), ('now', 18), ('next', 14))):
        x = 57 + [0, 17, 38][i]
        rrect(g.d, x, 90, x + w_, 104, C['walnut_d'], 1)
        g.im.paste(texture('wood', w_ - 2, 12, 95 + i), (x + 1, 91), rr_mask(w_ - 2, 12, 1))
        gsym(g, k, 2 * x + w_, 194, 14 if k != 'now' else 16, C['cream'], C['walnut'])
    g.d.line([(8, 107), (151, 107)], fill=PARCH_D)
    g.onto(im)
    im.paste(cover(t[2], 100), (22, 46))
    yb = 58 + (len(lines) - 1) * 20
    text1(im, 138, yb + 18, fit(t[1], pix(11, 'SemiBold'), 160), (0x7a, 0x5a, 0x3a), size=11, var='SemiBold')
    for i, line in enumerate(wrap("sounds like what's playing, fits this session's mood", pix(10), 160, 2)):
        text1(im, 138, yb + 34 + i * 12, line, (0x8a, 0x6c, 0x4c))
    text1(im, 22, 158, '0:41', C['ink'], size=11, var='SemiBold')
    text1(im, 300 - tw('5:00', pix(11, 'SemiBold')), 158, '5:00', C['ink'], size=11, var='SemiBold')
    nt = TR[1]
    text1(im, 20, 228, 'Up next:', (0x8a, 0x62, 0x3a), size=11, var='SemiBold')
    im.paste(cover(nt[2], 16), (74, 218))
    text1(im, 96, 228, fit(nt[0], pix(11, 'SemiBold'), 200), C['ink'], size=11, var='SemiBold')
    return im.convert('RGB')


# ================================================================== 2. toybox
CHK1, CHK2 = (0xee, 0xe5, 0xd4), (0xe1, 0xd5, 0xc0)
CARD, CARD_B = (0xfb, 0xf8, 0xf1), (0xbf, 0xb2, 0x9c)
OUTL = (0x7d, 0x6a, 0x55)

def checker(g, off=0):
    for y in range(120):
        for x in range(160):
            g.d.point((x, y), fill=CHK1 if ((x + off) // 8 + (y + off) // 8) % 2 else CHK2)

def toy_button(g, a, b, c, d, face, dark, light, pressed=0, r=3):
    o = pressed
    rrect(g.d, a, b + 1, c, d + 1, OUTL, r)                      # outline + base
    rrect(g.d, a + 1, b + 1 + o, c - 1, d, dark, r)            # the button's side
    rrect(g.d, a + 1, b + 1 + o, c - 1, d - 3 + o, face, r)    # its face
    g.d.line([(a + 1 + r, b + 2 + o), (c - 2 - r, b + 2 + o)], fill=light)
    return o

def card(g, a, b, c, d):
    rrect(g.d, a, b, c, d, CARD_B, 2)
    rrect(g.d, a + 1, b + 1, c - 1, d - 1, CARD, 2)

TOY = {'queue': ('shade', CARD, (0xd8, 0xcf, 0xbf)), 'explore': ('leaf', C['leaf'], C['leaf_d']),
       'search': ('sage', C['sage'], C['sage_d']), 'library': ('silver', C['silver'], C['silver_d']),
       'liked': ('key', C['key'], C['key_d']), 'settings': ('felt', C['felt'], C['felt_d'])}

def toybox_menu(sel='explore', t=0.0):
    im, g = base(), Grid()
    checker(g, int(t / 1000 * 8) % 16)
    card(g, 3, 2, 157, 14)
    g.text(14, 22, 'Coda', C['ink'])
    g.d.rectangle([28, 7, 29, 8], fill=C['key'])
    R.battery(g, im, W - 10, 18, C['ink'])
    big = sel in ('wheel', 'now')
    o1 = toy_button(g, 4, 17, 78, 74, C['leaf'], C['leaf_d'], C['leaf_l'], 2 if sel == 'wheel' else 0)
    gsym(g, 'wheel', 82, 62 + 2 * o1, 62, C['cream'], C['leaf'], C['key'])
    g.text(16, 134 + 2 * o1, 'Wheel', C['cream'], C['leaf_d'])
    o2 = toy_button(g, 82, 17, 156, 74, C['key'], C['key_d'], C['key_l'], 2 if sel == 'now' else 0)
    g.text(178, 134 + 2 * o2, 'Now playing', C['ink'])
    # the round buttons
    cx = [17 + i * 25 for i in range(6)]
    for i, k in enumerate(['queue', 'explore', 'search', 'library', 'liked', 'settings']):
        mat, face, dark = TOY[k]
        foc = k == sel
        y = 92 + (1 if foc else 0)
        g.d.ellipse([cx[i] - 11, 81, cx[i] + 11, 104], fill=OUTL)
        g.d.ellipse([cx[i] - 10, 82, cx[i] + 10, 103], fill=dark)
        g.d.ellipse([cx[i] - 10, 81 + (1 if foc else 0), cx[i] + 10, 100 + (1 if foc else 0)], fill=face)
        if foc:
            g.d.ellipse([cx[i] - 13, 79, cx[i] + 13, 106], outline=CARD)
        ink = C['ink'] if mat in ('shade', 'silver', 'key', 'felt') else C['cream']
        gsym(g, k, 2 * cx[i], 2 * y - 2, 22, ink, face, C['key'] if k == 'queue' else None)
    # the label: a speech bubble under the picked button
    if not big:
        i = ['queue', 'explore', 'search', 'library', 'liked', 'settings'].index(sel)
        bx = min(max(cx[i] - 40, 3), 157 - 80)
        card(g, bx, 107, bx + 80, 119)
        g.d.polygon([(cx[i] - 3, 107), (cx[i] + 3, 107), (cx[i], 104)], fill=CARD)
        g.d.line([(cx[i] - 3, 106), (cx[i], 104), (cx[i] + 3, 106)], fill=CARD_B)
    g.onto(im)
    t0 = TR[0]
    m = Image.new('L', (60, 60), 0)
    ImageDraw.Draw(m).rectangle([0, 0, 59, 59], fill=255)
    im.paste(Image.new('RGB', (64, 64), CARD), (206, 42 + 2 * o2))
    im.paste(cover(t0[2], 60), (208, 44 + 2 * o2))
    if not big:
        name, desc, _ = ITEMS[sel]
        x = (bx + 4) * 2
        text1(im, x, 228, name, C['ink'], size=11, var='SemiBold')
        text1(im, x + tw(name, pix(11, 'SemiBold')) + 6, 228, fit(desc, pix(10), 150 - tw(name, pix(11, 'SemiBold'))), C['sub'])
    return im.convert('RGB')

def toybox_now(t=0.0):
    im, g = base(), Grid()
    checker(g, int(t / 1000 * 8) % 16)
    card(g, 3, 2, 157, 21)
    R.battery(g, im, W - 10, 14, C['ink'])
    card(g, 3, 24, 157, 90)
    # the toy: bubbles rise with the music, colours from the room
    rnd = random.Random(5)
    cols = [(C['leaf'], C['leaf_l']), (C['key'], C['key_l']), (C['sage'], C['sage_l']),
            (C['leather'], C['stitch']), (C['silver'], C['silver_l'])]
    for k in range(22):
        sp = rnd.uniform(6, 16)
        r = rnd.choice([2, 3, 3, 4, 5, 6])
        x = rnd.uniform(8, 152) + math.sin(t / 400 + k) * 2
        y = 88 - ((t / 1000 * sp + rnd.uniform(0, 70)) % 64)
        c, l = cols[k % len(cols)]
        g.d.ellipse([x - r, y - r, x + r, y + r], fill=c)
        g.d.point((x - r / 2, y - r / 2), fill=l)
    g.d.ellipse([56, 32, 104, 80], fill=CARD_B)
    g.d.ellipse([57, 33, 103, 79], fill=CARD)
    # the toy transport
    toy_button(g, 22, 96, 50, 116, C['felt'], C['felt_d'], C['felt_l'])
    toy_button(g, 56, 94, 104, 117, C['leaf'], C['leaf_d'], C['leaf_l'])
    toy_button(g, 110, 96, 138, 116, C['felt'], C['felt_d'], C['felt_l'])
    gsym(g, 'history', 72, 210, 16, C['ink'], C['felt'])
    gsym(g, 'now', 160, 208, 20, C['cream'], C['leaf'])
    gsym(g, 'next', 248, 210, 16, C['ink'], C['felt'])
    g.d.rectangle([6, 92, 154, 92], fill=CARD_B)
    g.d.rectangle([6, 92, 6 + int(148 * .31), 92], fill=C['key'])
    g.onto(im)
    tr = TR[0]
    cv = cover(tr[2], 88)
    m = Image.new('L', (88, 88), 0)
    ImageDraw.Draw(m).ellipse([0, 0, 87, 87], fill=255)
    im.paste(cv, (116, 68), m)
    text1(im, 14, 20, fit(tr[0], pix(11, 'SemiBold'), 240), C['ink'], size=11, var='SemiBold')
    text1(im, 14, 34, fit(tr[1], pix(10), 200), C['sub'])
    return im.convert('RGB')


# ================================================================== 3. deck
AMBER, AMBER_D, GLASS = (0xff, 0xa8, 0x3a), (0x2c, 0x1b, 0x0e), (0x1b, 0x13, 0x0d)
SEG = {'0': 'abcdef', '1': 'bc', '2': 'abged', '3': 'abgcd', '4': 'fgbc', '5': 'afgcd',
       '6': 'afgedc', '7': 'abc', '8': 'abcdefg', '9': 'abcdfg'}

def seg7(g, x, y, ch, col, dim):
    """a 6 x 11 seven-segment digit on the 2x2 grid"""
    s = {'a': [(x + 1, y), (x + 4, y)], 'g': [(x + 1, y + 5), (x + 4, y + 5)], 'd': [(x + 1, y + 10), (x + 4, y + 10)],
         'f': [(x, y + 1), (x, y + 4)], 'b': [(x + 5, y + 1), (x + 5, y + 4)],
         'e': [(x, y + 6), (x, y + 9)], 'c': [(x + 5, y + 6), (x + 5, y + 9)]}
    on = SEG.get(ch, '')
    for k, ln in s.items():
        g.d.line(ln, fill=col if k in on else dim)

def deck(tab='queue', t=0.0):
    im, g = base(C['walnut']), Grid()
    # title bar: grooves either side of the name
    g.im.paste(texture('wood', 160, 9, 101), (0, 0))
    for y in (2, 4, 6):
        g.d.line([(4, y), (60, y)], fill=C['walnut_d'])
        g.d.line([(100, y), (126, y)], fill=C['walnut_d'])
    g.text(132, 15, 'Coda', C['cream'], C['walnut_d'])
    g.d.rectangle([146 - 4, 3, 147 - 4, 4], fill=C['key'])
    # the faceplate
    g.im.paste(texture('silver', 160, 53, 102), (0, 9))
    vents(g, 104, 48, 156, 60)
    rrect(g.d, 3, 11, 102, 45, (0x0e, 0x09, 0x06), 1)
    g.d.rectangle([4, 12, 100, 43], fill=GLASS)
    # the display: state, big time, spectrum
    g.d.polygon([(7, 15), (7, 21), (10, 18)], fill=AMBER)
    x = 14
    for ch in '0:41':
        if ch == ':':
            g.d.point((x, 17), fill=AMBER)
            g.d.point((x, 21), fill=AMBER)
            x += 3
        else:
            seg7(g, x, 13, ch, AMBER, AMBER_D)
            x += 8
    rnd = random.Random(int(t / 80))
    for i in range(14):
        h = int(abs(math.sin(i * .7 + t / 300)) * 12 + rnd.uniform(0, 6))
        bx = 52 + i * 3
        g.d.rectangle([bx, 28 - h, bx + 1, 28], fill=AMBER)
        g.d.point((bx, 26 - h), fill=C['cream'])
        g.d.point((bx + 1, 26 - h), fill=C['cream'])
        g.d.rectangle([bx, 29, bx + 1, 29], fill=AMBER_D)
    # cover in a silver bezel
    rrect(g.d, 104, 11, 157, 45, C['silver_d'], 1)
    g.d.rectangle([105, 12, 155, 43], fill=GLASS)
    # seek, transport keys, volume knob
    g.d.rectangle([4, 48, 100, 49], fill=(0x0e, 0x09, 0x06))
    g.d.rectangle([4, 48, 4 + int(96 * .31), 49], fill=C['key'])
    rrect(g.d, 4 + int(96 * .31) - 2, 46, 4 + int(96 * .31) + 3, 51, C['silver_l'], 1)
    for i, k in enumerate(['history', 'now', 'pause', 'stop', 'next']):
        kx = 4 + i * 14
        rrect(g.d, kx, 53, kx + 12, 61, C['slot'], 1)
        rrect(g.d, kx, 53, kx + 12, 60, C['silver_l'], 1)
        g.d.line([(kx + 1, 59), (kx + 11, 59)], fill=C['silver_d'])
        ccx, ccy = kx + 6, 56
        if k == 'pause':
            g.d.rectangle([ccx - 2, ccy - 2, ccx - 1, ccy + 2], fill=C['ink'])
            g.d.rectangle([ccx + 1, ccy - 2, ccx + 2, ccy + 2], fill=C['ink'])
        elif k == 'stop':
            g.d.rectangle([ccx - 2, ccy - 2, ccx + 2, ccy + 2], fill=C['ink'])
        else:
            gsym(g, k, 2 * ccx, 2 * ccy, 10, C['ink'], C['silver_l'])
    g.d.ellipse([80, 51, 96, 61], fill=C['slot'])
    g.d.ellipse([80, 50, 96, 60], fill=C['silver_l'])
    g.d.line([(88, 52), (91, 55)], fill=C['ink'])
    g.d.point((99, 55), fill=C['key'])
    # the playlist window: the sections are its tabs
    g.im.paste(texture('wood', 160, 58, 103), (0, 62))
    g.d.rectangle([3, 70, 156, 117], fill=(0x14, 0x0e, 0x0a))
    g.d.rectangle([152, 72, 155, 115], fill=(0x2a, 0x1e, 0x15))
    g.d.rectangle([152, 76, 155, 88], fill=C['silver'])
    g.onto(im)
    tr = TR[0]
    im.paste(cover(tr[2], 62), (214, 24))
    # the marquee under the time
    mq = Image.new('RGB', (88, 12), GLASS)
    ImageDraw.Draw(mq).text((-int(t / 30) % 200 - 40, -1), tr[0] + '   ' + tr[1], font=pix(10), fill=AMBER)
    im.paste(mq, (10, 70))
    text1(im, 120, 84, 'opus 128k 48kHz', AMBER, size=10)
    text1(im, 172, 70, 'stereo', AMBER)
    tabs = ['Queue', 'Wheel', 'Explore', 'Library', 'Liked', 'Search']
    x = 8
    d = ImageDraw.Draw(im)
    for name in tabs:
        on = name.lower() == tab
        w_ = tw(name, pix(10, 'SemiBold'))
        if on:
            d.rectangle([x - 3, 125, x + w_ + 3, 138], fill=C['key'])
        text1(im, x, 135, name, C['ink'] if on else C['felt_l'], var='SemiBold')
        x += w_ + 12
    rows = ([(f'{i + 1:02d}', t_[0], t_[1], I.mmss(t_[3])) for i, t_ in enumerate(TR[2:9])] if tab == 'queue'
            else [('', a, f'{n} songs', '') for a, n in (('Ado', 41), ('Akira Yamaoka', 12), ('Aphex Twin', 33),
                                                          ('C418', 58), ('Caleb Gordon', 7), ('Camellia', 64), ('Chipzel', 15))])
    for i, (num, a, b, dur) in enumerate(rows):
        y = 142 + i * 13
        if y > 232:
            break
        cur, sel = (i == 2 and tab == 'queue'), i == 4
        if sel:
            d.rectangle([7, y, 302, y + 12], fill=AMBER)
        col = (0x14, 0x0e, 0x0a) if sel else (C['key'] if cur else (0xd9, 0xcf, 0xbf))
        x0 = 10
        if num:
            text1(im, x0, y + 10, num, col)
            x0 = 30
        text1(im, x0, y + 10, fit(a, pix(10, 'SemiBold'), 160), col, var='SemiBold')
        text1(im, x0 + 166, y + 10, fit(b, pix(10), 80), col)
        if dur:
            text1(im, 298 - tw(dur, pix(10)), y + 10, dur, col)
    return im.convert('RGB')


# ================================================================== 4. crate
CRATE = {'wheel': None, 'now': 0, 'queue': 1, 'explore': 9, 'search': 12, 'library': 5, 'liked': 7, 'settings': None}

def pixelated(img, cells=18, colours=12):
    s = img.resize((cells, cells), Image.BOX).quantize(colours, method=Image.Quantize.MEDIANCUT).convert('RGB')
    return s.resize(img.size, Image.NEAREST)

def crate_tile(kind, px, focus):
    """a tile's picture: a cover (pixel art until it's picked), or a material"""
    if kind == 'wheel':
        im = Image.new('RGB', (px, px))
        h = px // 2
        for i, k in enumerate((3, 4, 10, 11)):
            im.paste(cover(TR[k][2], h), ((i % 2) * h, (i // 2) * h))
    elif kind == 'settings':
        im = texture('felt', px // 2, px // 2, 120).resize((px, px), Image.NEAREST)
    else:
        im = cover(TR[CRATE[kind]][2], px)
    return im if focus >= 1 else pixelated(im, int(12 + 60 * focus ** 2) if focus > 0 else 18)

def crate(sel='explore', t=0.0, prev=None, u=1.0):
    im, g = base(C['walnut']), Grid()
    g.im.paste(texture('wood', 160, 120, 130), (0, 0))
    g.d.line([(0, 11), (160, 11)], fill=C['walnut_d'])
    g.text(10, 17, 'Coda', C['cream'], C['walnut_d'])
    g.d.rectangle([24, 3, 25, 4], fill=C['key'])
    R.battery(g, im, W - 8, 15, C['cream'])
    g.onto(im)
    d = ImageDraw.Draw(im)
    for i, k in enumerate(MENU):
        x, y = 8 + (i % 4) * 77, 28 + (i // 4) * 80
        foc = (u if k == sel else (1 - u if k == prev else 0.0))
        lift = int(round(3 * foc))
        d.rectangle([x + 3, y + 3, x + 72, y + 72], fill=C['walnut_d'])          # its shadow
        if foc > 0:
            d.rectangle([x - 3, y - 3 - lift, x + 72, y + 72 - lift], fill=C['walnut_d'])
            d.rectangle([x - 2, y - 2 - lift, x + 71, y + 71 - lift], fill=C['cream'])
        im.paste(crate_tile(k, 70, foc), (x, y - lift))
        # the label strip and the section's badge
        d.rectangle([x, y + 56 - lift, x + 69, y + 69 - lift], fill=C['walnut_d'])
        text1(im, x + 4, y + 67 - lift, ITEMS[k][0], C['cream'], var='SemiBold')
    gb = Grid()
    for i, k in enumerate(MENU):
        x, y = 8 + (i % 4) * 77, 28 + (i // 4) * 80
        lift = 3 if k == sel and u >= 1 else 0
        mat = {'wheel': 'wood', 'now': 'leather', 'queue': 'shade', 'explore': 'leaf', 'search': 'sage',
               'library': 'silver', 'liked': 'key', 'settings': 'felt'}[k]
        b_, ink, acc = (C[q] for q in R.MAT[mat])
        a, b = (x + 52) // 2, (y + 2 - lift) // 2
        rrect(gb.d, a, b, a + 9, b + 9, C['walnut_d'], 1)
        gb.im.paste(texture(mat, 8, 8, 140 + i), (a + 1, b + 1), rr_mask(8, 8, 1))
        gsym(gb, k, 2 * a + 9, 2 * b + 9, 13, ink, b_, None)
    sx, sy = 8 + (MENU.index(sel) % 4) * 77, 28 + (MENU.index(sel) // 4) * 80
    cursor(gb, sx - 10, sy + 28, t)
    gb.onto(im)
    name, desc, _ = ITEMS[sel]
    text1(im, 10, 202, name, C['cream'], size=11, var='SemiBold')
    text1(im, 16 + tw(name, pix(11, 'SemiBold')), 202, fit(desc, pix(10), 250), C['felt_l'])
    nowbar(im)
    return im.convert('RGB')


# ================================================================== 5. receiver
DOT_ON, DOT_OFF, DOT_HI = (0xff, 0x9a, 0x2a), (0x33, 0x20, 0x11), (0xff, 0xd0, 0x8a)
CELL = 3

def dots(im, x0, y0, bmp):
    """an amber dot-matrix: each lit cell of bmp (mode 1) is a dot, the rest glow faintly"""
    d = ImageDraw.Draw(im)
    px = bmp.load()
    for y in range(bmp.size[1]):
        for x in range(bmp.size[0]):
            sx, sy = x0 + x * CELL, y0 + y * CELL
            if px[x, y]:
                d.rectangle([sx, sy, sx + 1, sy + 1], fill=DOT_ON)
                d.point((sx, sy), fill=DOT_HI)
            else:
                d.rectangle([sx, sy, sx + 1, sy + 1], fill=DOT_OFF)

def cabinet(im, g):
    g.im.paste(texture('wood', 160, 120, 150), (0, 0))
    g.d.rectangle([0, 0, 159, 0], fill=C['silver'])
    g.d.rectangle([0, 119, 159, 119], fill=C['silver'])
    rrect(g.d, 3, 3, 157, 80, C['silver_d'], 3)
    rrect(g.d, 4, 4, 156, 79, (0x0f, 0x0a, 0x06), 3)
    rrect(g.d, 5, 5, 155, 78, (0x1a, 0x11, 0x0b), 3)
    g.d.line([(118, 6), (98, 77)], fill=(0x22, 0x17, 0x10))       # the glass's shine
    g.d.line([(121, 6), (101, 77)], fill=(0x22, 0x17, 0x10))

STATIONS = ['wheel', 'now', 'queue', 'explore', 'search', 'library', 'liked', 'settings']

def receiver(sel='explore', pos=None, t=0.0):
    im, g = base(C['walnut']), Grid()
    cabinet(im, g)
    # the knobs: volume and tuning
    for cx_, lab in ((28, 'VOLUME'), (132, 'TUNING')):
        g.d.ellipse([cx_ - 13, 87, cx_ + 13, 113], fill=C['slot'])
        g.d.ellipse([cx_ - 12, 86, cx_ + 12, 111], fill=C['silver'])
        for k in range(16):
            a = k * math.pi / 8
            g.d.point((cx_ + math.cos(a) * 12, 98.5 + math.sin(a) * 12), fill=C['silver_d'])
        g.d.ellipse([cx_ - 8, 90, cx_ + 8, 107], fill=C['silver_l'])
        ang = (-.8 if lab == 'VOLUME' else (pos if pos is not None else STATIONS.index(sel)) * .7 - 2.4)
        g.d.line([(cx_, 98), (cx_ + math.cos(ang) * 7, 98 + math.sin(ang) * 7)], fill=C['ink'])
    # centre: power lamp, the name plate
    g.d.rectangle([62, 92, 98, 104], fill=C['silver_d'])
    g.d.rectangle([63, 93, 97, 103], fill=C['silver'])
    g.d.ellipse([75, 107, 78, 110], fill=C['key'])
    g.onto(im)
    d = ImageDraw.Draw(im)
    for cx_, lab in ((56, 'VOLUME'), (264, 'TUNING')):
        dd = ImageDraw.Draw(im)
        dd.fontmode = '1'
        dd.text((cx_ - tw(lab, silk(8)) / 2, 228), lab, font=silk(8), fill=C['cream'])
    dd = ImageDraw.Draw(im)
    dd.fontmode = '1'
    dd.text((160 - tw('CODA', silk(8)) / 2, 191), 'CODA', font=silk(8), fill=C['walnut_d'])
    dd.text((168, 211), 'POWER', font=silk(8), fill=C['cream'])
    # the glass: the dial on top, the station big below, what it does under that
    p = pos if pos is not None else STATIONS.index(sel)
    bmp = Image.new('1', (98, 47), 0)
    b = ImageDraw.Draw(bmp)
    b.fontmode = '1'
    span = 52
    off = int(round(p * span)) - 49
    b.line([(0, 12), (97, 12)], fill=1)
    for k in range(-2, 8 * span // 4 + 4):
        x = k * 4 - off % 4 + (0 if off >= 0 else 0)
        xx = k * 4 - off
        if 0 <= xx < 98:
            b.line([(xx, 13), (xx, 14 if k % 2 else 15)], fill=1)
    for i, s in enumerate(STATIONS):
        name = ITEMS[s][0].upper().replace('NOW PLAYING', 'NOW')
        xx = i * span - off - tw(name, silk(8)) / 2
        if -60 < xx < 98:
            b.text((xx, 3), name, font=silk(8), fill=1)
    name = ITEMS[sel][0].upper()
    f16 = silk(16)
    if tw(name, f16) > 96:
        name = name.replace('NOW PLAYING', 'NOW')
    b.text((49 - tw(name, f16) / 2, 20), name, font=f16, fill=1)
    desc = ITEMS[sel][1].upper()
    mq = int(t / 60) % (int(tw(desc, silk(8))) + 98)
    b.text((98 - mq, 38), desc, font=silk(8), fill=1)
    dots(im, 13, 12, bmp)
    # the needle
    nx = 13 + 49 * CELL
    d.rectangle([nx - 1, 10, nx, 64], fill=(0xe8, 0x3a, 0x2a))
    d.rectangle([nx + 1, 12, nx + 1, 64], fill=(0x0a, 0x06, 0x04))
    return im.convert('RGB')

def vu(g, a, b, c, d, level):
    rrect(g.d, a, b, c, d, C['walnut_d'], 2)
    rrect(g.d, a + 1, b + 1, c - 1, d - 1, (0xf3, 0xe6, 0xc8), 2)
    cx_, cy_ = (a + c) / 2, d - 3
    for k in range(11):
        ang = math.pi * (1.18 + .64 * k / 10)
        r0, r1 = 22, 25 if k % 5 else 27
        col = (0xd0, 0x3a, 0x2a) if k >= 8 else C['ink']
        g.d.line([(cx_ + math.cos(ang) * r0, cy_ + math.sin(ang) * r0),
                  (cx_ + math.cos(ang) * r1, cy_ + math.sin(ang) * r1)], fill=col)
    ang = math.pi * (1.18 + .64 * level)
    g.d.line([(cx_, cy_), (cx_ + math.cos(ang) * 26, cy_ + math.sin(ang) * 26)], fill=C['ink'])
    g.d.rectangle([cx_ - 2, cy_ - 1, cx_ + 2, cy_ + 1], fill=C['walnut_d'])

def receiver_now(t=0.0):
    im, g = base(C['walnut']), Grid()
    cabinet(im, g)
    lv = lambda k: .35 + .3 * abs(math.sin(t / 230 + k)) + .15 * abs(math.sin(t / 97 + 2 * k))
    vu(g, 8, 84, 76, 116, lv(0))
    vu(g, 84, 84, 152, 116, lv(1.3))
    g.onto(im)
    dd = ImageDraw.Draw(im)
    dd.fontmode = '1'
    for x, lab in ((84, 'L'), (236, 'R')):
        dd.text((x, 214), 'VU ' + lab, font=silk(8), fill=C['walnut_d'])
    tr = TR[0]
    bmp = Image.new('1', (98, 47), 0)
    b = ImageDraw.Draw(bmp)
    b.fontmode = '1'
    title = (tr[0] + '  -  ' + tr[1]).upper()
    mq = int(t / 50) % (int(tw(title, silk(8))) + 98)
    b.text((98 - mq, 1), title, font=silk(8), fill=1)
    b.text((2, 12), '0:41', font=silk(16), fill=1)
    b.text((62, 13), 'OPUS', font=silk(8), fill=1)
    b.text((62, 20), '48KHZ', font=silk(8), fill=1)
    b.rectangle([2, 34, 95, 36], outline=1)
    b.rectangle([2, 34, 2 + int(93 * .31), 36], fill=1)
    b.text((2, 39), 'NEXT  ' + TR[1][0].upper()[:20], font=silk(8), fill=1)
    dots(im, 13, 12, bmp)
    return im.convert('RGB')


# ================================================================== 6. room
def room_objects(t=0.0):
    """each object of the desk corner on its own layer: name -> RGBA 160 x 120"""
    L = {}
    def layer():
        return Image.new('RGBA', (160, 120), (0, 0, 0, 0))
    # the shelf and what's on it
    sh = layer(); d = ImageDraw.Draw(sh)
    sh.paste(texture('wood', 104, 4, 160), (16, 30))
    d.line([(16, 34), (119, 34)], fill=C['led'])
    d.line([(16, 35), (119, 35)], fill=(0xc8, 0xb2, 0x92))
    L['shelf'] = sh
    bx = layer(); d = ImageDraw.Draw(bx)                       # the boxes: Library
    d.rectangle([20, 13, 31, 29], fill=(0x2c, 0x2b, 0x2e)); d.line([(20, 13), (31, 13)], fill=(0x55, 0x55, 0x58))
    d.rectangle([23, 17, 28, 23], fill=(0x9a, 0x9a, 0x9c))
    d.rectangle([33, 15, 46, 21], fill=(0x1f, 0x5c, 0xa6)); d.rectangle([33, 22, 46, 29], fill=(0xe8, 0x80, 0x2a))
    d.ellipse([37, 18, 42, 24], fill=(0xf4, 0xee, 0xe2))
    L['library'] = bx
    fn = layer(); d = ImageDraw.Draw(fn)                       # a fern (not a menu item)
    d.rectangle([52, 24, 62, 29], fill=(0x24, 0x24, 0x26))
    for k in range(9):
        a = math.pi * (1.1 + .8 * k / 8)
        d.line([(57, 24), (57 + math.cos(a) * 9, 22 + math.sin(a) * 9)], fill=C['leaf_d'] if k % 2 else C['leaf'])
    L['fern'] = fn
    ck = layer(); d = ImageDraw.Draw(ck)                       # the clock: Wheel
    d.ellipse([66, 18, 78, 30], fill=C['ink']); d.ellipse([67, 19, 77, 29], fill=C['cream'])
    sec = t / 1000
    d.line([(72, 24), (72, 20)], fill=C['ink']); d.line([(72, 24), (75, 25)], fill=C['ink'])
    d.line([(72, 24), (72 + math.cos(sec - 1.5) * 4, 24 + math.sin(sec - 1.5) * 4)], fill=(0xd0, 0x3a, 0x2a))
    L['wheel'] = ck
    pt = layer(); d = ImageDraw.Draw(pt)                       # the pothos: Liked
    d.rectangle([98, 23, 108, 29], fill=(0x24, 0x24, 0x26))
    for k, y in enumerate(range(22, 74, 3)):
        sway = math.sin(t / 700 + k * .5) * (k / 10)
        x = 106 + int(round(math.sin(k * .8) * 2 + sway))
        d.point((x, y), fill=C['leaf_d']); d.point((x, y + 1), fill=C['leaf_d']); d.point((x, y + 2), fill=C['leaf_d'])
        side = 1 if k % 2 else -1
        lx = x + side * 2
        d.polygon([(lx, y), (lx + side * 4, y + 1), (lx + side * 2, y + 4)], fill=C['leaf'])
        d.point((lx + side, y + 1), fill=C['leaf_l'])
    for k in range(5):
        d.ellipse([99 + k * 2 - 2, 17 + (k % 2), 99 + k * 2 + 3, 22 + (k % 2)], fill=C['leaf'] if k % 2 else C['leaf_d'])
    L['liked'] = pt
    ps = layer(); d = ImageDraw.Draw(ps)                       # posters: Explore (filled with covers later)
    for x0 in (28, 60):
        d.rectangle([x0, 40, x0 + 28, 70], fill=(0xf4, 0xee, 0xe2))
    L['explore'] = ps
    mo = layer(); d = ImageDraw.Draw(mo)                       # the monitor: Queue
    d.rectangle([32, 73, 88, 94], fill=(0x16, 0x16, 0x18)); d.rectangle([34, 75, 86, 92], fill=(0x22, 0x26, 0x30))
    d.rectangle([57, 95, 63, 97], fill=(0x16, 0x16, 0x18)); d.rectangle([52, 97, 68, 98], fill=(0x16, 0x16, 0x18))
    L['queue'] = mo
    kb = layer(); d = ImageDraw.Draw(kb)                       # the keyboard: Settings
    d.rectangle([22, 96, 48, 99], fill=(0xbd, 0xbd, 0xb8))
    for x in range(23, 48, 2):
        d.point((x, 97), fill=(0xe9, 0xe7, 0xe0)); d.point((x, 98), fill=(0xd9, 0xd7, 0xd0))
    d.point((43, 97), fill=C['key']); d.point((44, 97), fill=C['key'])
    L['settings'] = kb
    pc = layer(); d = ImageDraw.Draw(pc)                       # the silver case (not a menu item)
    pc.paste(texture('silver', 22, 25, 161), (100, 74))
    for y in range(76, 86, 2):
        d.line([(102, y), (119, y)], fill=C['slot'])
    d.rectangle([100, 97, 121, 99], fill=C['walnut'])
    L['case'] = pc
    hp = layer(); d = ImageDraw.Draw(hp)                       # the headphones on it: Now playing
    d.arc([96, 68, 124, 92], 180, 360, fill=(0x1c, 0x1c, 0x1e), width=2)
    d.arc([97, 69, 123, 91], 200, 250, fill=(0xc8, 0x2a, 0x22), width=1)
    d.rectangle([95, 79, 99, 89], fill=(0x1c, 0x1c, 0x1e)); d.line([(96, 80), (96, 88)], fill=(0xc8, 0x2a, 0x22))
    L['now'] = hp
    lp = layer(); d = ImageDraw.Draw(lp)                       # the lamp: Search
    d.polygon([(134, 40), (152, 40), (154, 58), (132, 58)], fill=(0xf6, 0xf2, 0xea))
    d.line([(134, 40), (152, 40)], fill=(0xe2, 0xdc, 0xcf))
    d.line([(132, 57), (154, 57)], fill=(0xdd, 0xd4, 0xc4))
    d.rectangle([142, 58, 143, 104], fill=(0x1c, 0x1c, 0x1e))
    for y in (70, 84, 98):
        d.line([(138, y), (147, y)], fill=(0x1c, 0x1c, 0x1e))
    L['search'] = lp
    ch = layer(); d = ImageDraw.Draw(ch)                       # the chair's back (not a menu item)
    d.rounded_rectangle([-6, 70, 16, 106], 4, fill=C['leather'])
    d.line([(2, 74), (2, 104)], fill=C['leather_d']); d.line([(10, 74), (10, 104)], fill=C['leather_d'])
    L['chair'] = ch
    return L

ROOM_ORDER = ['wheel', 'now', 'queue', 'explore', 'search', 'library', 'liked', 'settings']
ROOM_TAG = {'wheel': (72, 16), 'now': (110, 66), 'queue': (60, 71), 'explore': (58, 38), 'search': (143, 38),
            'library': (33, 11), 'liked': (106, 15), 'settings': (35, 94)}

def outline(mask, col):
    big = mask.filter(ImageFilter.MaxFilter(3))
    ring = Image.eval(big, lambda v: v)
    o = Image.new('RGBA', mask.size, col + (255,))
    m = Image.composite(big, Image.new('L', mask.size, 0), Image.eval(mask, lambda v: 255 - v))
    return o, m

def room(sel='liked', t=0.0):
    im = base()
    g = Grid()
    for y in range(0, 100):                                      # the wall, faint vertical grain
        for x in range(0, 160, 7):
            g.d.point((x + (y // 9) % 3, y), fill=(0xd0, 0xbb, 0x9b))
    g.im.paste(texture('wood', 160, 8, 170), (0, 98))            # the desk top
    g.d.line([(0, 98), (160, 98)], fill=C['walnut_hi'])
    L = room_objects(t)
    for k in ['shelf', 'fern', 'library', 'wheel', 'liked', 'explore', 'chair', 'queue', 'case', 'now', 'search', 'settings']:
        lay = L[k]
        if k == sel:
            a = lay.split()[3]
            o, m = outline(a, C['cream'])
            g.im.paste(o, (0, 0), m)
        g.im.alpha_composite(lay)
    tx, ty = ROOM_TAG[sel]
    cursor(g, 2 * tx - 4, 2 * ty - 8, t)
    g.onto(im)
    # the posters are covers; the monitor shows the queue
    d = ImageDraw.Draw(im)
    for i, x0 in enumerate((56, 120)):
        im.paste(cover(TR[i][2], 52), (x0 + 3, 83))
    for i, tr_ in enumerate(TR[2:5]):
        text1(im, 72, 162 + i * 10, fit(tr_[0], pix(9), 98), (0xd9, 0xe0, 0xea) if i else C['key'], size=9)
    # the label: a parchment tag by the pointer
    name, desc, _ = ITEMS[sel]
    gx, gy = 2 * tx + 10, 2 * ty - 22
    w_ = max(tw(name, pix(11, 'SemiBold')), 0) + 16
    gx = min(gx, W - w_ - 4)
    d.rounded_rectangle([gx, gy, gx + w_, gy + 18], 3, fill=PARCH, outline=C['walnut_d'])
    text1(im, gx + 8, gy + 13, name, C['ink'], size=11, var='SemiBold')
    d.rectangle([0, 198, W, 211], fill=C['walnut_d'])
    text1(im, 8, 208, fit(desc, pix(10), 300), C['felt_l'])
    R.battery(Grid(), im, W - 8, 14, C['ink'])
    nowbar(im)
    return im.convert('RGB')


# ================================================================== output
def gif(path, fr, ms=None):
    big = [f.resize((W * 2, H * 2), Image.NEAREST) for f in fr]
    big[0].save(path, save_all=True, append_images=big[1:], duration=ms or int(1000 / FPS), loop=0)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shots = {
        'jukebox_menu': jukebox_menu(), 'jukebox_now': jukebox_now(),
        'toybox_menu': toybox_menu('explore', 400), 'toybox_now': toybox_now(1600),
        'deck_queue': deck('queue', 600), 'deck_library': deck('library', 1500),
        'crate_menu': crate('explore', 0), 'crate_liked': crate('liked', 300),
        'receiver_menu': receiver('explore', t=900), 'receiver_now': receiver_now(700),
        'room_liked': room('liked', 500), 'room_now': room('now', 900)}
    for k, im in shots.items():
        im.save(OUT / f'{k}.png')
        im.resize((W * 2, H * 2), Image.NEAREST).save(OUT / f'{k}@2x.png')
    g, cols = 10, 4
    keys = list(shots)
    sheet = Image.new('RGB', (cols * (W + g) + g, 3 * (H + g) + g), (0x6a, 0x58, 0x46))
    for i, k in enumerate(keys):
        sheet.paste(shots[k], (g + (i % cols) * (W + g), g + (i // cols) * (H + g)))
    sheet.save(OUT / 'sheet.png')
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(OUT / 'sheet@2x.png')
    if '--still' in sys.argv:
        print('ok', OUT)
        return
    n = lambda ms: int(ms * FPS / 1000)
    gif(OUT / 'toybox.gif', [toybox_now(j * 1000 / FPS) for j in range(n(3000))])
    fr = []
    for i, k in enumerate(MENU):
        prev = MENU[i - 1] if i else None
        for j in range(n(700)):
            tt = j * 1000 / FPS
            fr.append(crate(k, tt, prev, min(1.0, tt / 220)))
    gif(OUT / 'crate.gif', fr)
    fr = []
    for i, k in enumerate(STATIONS):
        p0 = i - 1 if i else 0
        for j in range(n(800)):
            tt = j * 1000 / FPS
            e = M.ease_back(min(1.0, tt / 380), 1.4)
            fr.append(receiver(k, p0 + (i - p0) * e, tt + i * 800))
    gif(OUT / 'receiver.gif', fr)
    gif(OUT / 'receiver_now.gif', [receiver_now(j * 1000 / FPS) for j in range(n(2500))])
    fr = []
    for i, k in enumerate(ROOM_ORDER):
        for j in range(n(700)):
            fr.append(room(k, (i * 700) + j * 1000 / FPS))
    gif(OUT / 'room.gif', fr)
    print('ok', OUT)

if __name__ == '__main__':
    main()
