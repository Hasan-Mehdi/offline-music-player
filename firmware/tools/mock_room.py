"""A second theme for Coda on the H2, "room": the listener's own room as the palette
(walnut desk and shelf, cognac leather chair, pothos and sage curtains, the silver vented PC
case, the white lampshade, grey felt, one orange keycap), with menu A's layout but soft,
pixel-stepped corners instead of tilted ones. Every panel is one material from the room;
shapes, symbols and headings are drawn on a 2x2-pixel grid (160 x 120), song titles, numbers
and covers at the screen's own pixels so they stay readable. Type: Pixelify Sans (OFL).

Output: docs/h2/room/<screen>.png, sheet.png, menu.gif
  .venv/Scripts/python firmware/tools/mock_room.py
"""
import math, random, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_menu as M
import mock_inner as I

ROOT = M.ROOT
OUT = ROOT / 'docs' / 'h2' / 'room'
FD = ROOT / 'firmware' / 'assets' / 'fonts'
W, H, FPS = 320, 240, 25

C = dict(
    wall=(0xd6, 0xc2, 0xa3), wall_sh=(0xb8, 0xa0, 0x80),
    walnut=(0x4d, 0x33, 0x22), walnut_d=(0x3a, 0x26, 0x19), walnut_l=(0x60, 0x42, 0x2d), walnut_hi=(0x82, 0x5c, 0x3c),
    ink=(0x2e, 0x1f, 0x15), cream=(0xf4, 0xee, 0xe2), sub=(0x7c, 0x68, 0x52),
    leather=(0xb2, 0x6a, 0x35), leather_d=(0x91, 0x53, 0x28), stitch=(0xe6, 0xb0, 0x72),
    leaf=(0x4b, 0x8a, 0x36), leaf_l=(0x74, 0xb1, 0x4b), leaf_d=(0x2f, 0x5e, 0x24),
    sage=(0x66, 0x73, 0x3f), sage_l=(0x76, 0x84, 0x4c), sage_d=(0x54, 0x60, 0x31),
    silver=(0xc9, 0xca, 0xc6), silver_l=(0xe7, 0xe8, 0xe4), silver_d=(0x9c, 0x9d, 0x99), slot=(0x6d, 0x6e, 0x6a),
    shade=(0xf4, 0xef, 0xe5), shade_line=(0xe4, 0xdc, 0xcd),
    key=(0xea, 0xa2, 0x2c), key_d=(0xc3, 0x7c, 0x1b), key_l=(0xf7, 0xc6, 0x5d),
    felt=(0xb7, 0xb5, 0xaf), felt_d=(0xa8, 0xa6, 0xa0), felt_l=(0xc6, 0xc4, 0xbe),
    led=(0xff, 0xf2, 0xc9))
MAT = {  # material: base colour, ink on it, accent on it
    'wood': ('walnut', 'cream', 'key'), 'leather': ('leather', 'cream', 'key'),
    'leaf': ('leaf', 'cream', 'key'), 'sage': ('sage', 'cream', 'key'),
    'silver': ('silver', 'ink', 'leaf_d'), 'shade': ('shade', 'ink', 'key'),
    'key': ('key', 'ink', 'cream'), 'felt': ('felt', 'ink', 'key')}

_fc = {}
def pix(px, var='Regular'):
    """screen-pixel text (titles, artists, times): the device's own Archivo, readable at
    10 px and with the card's CJK fallback; the pixel face is for the 2x2 grid only"""
    k = (px, var)
    if k not in _fc:
        f = ImageFont.truetype(str(FD / 'Archivo.ttf'), px)
        f.set_variation_by_name({'Regular': 'Regular', 'SemiBold': 'SemiBold'}.get(var, var))
        _fc[k] = f
    return _fc[k]

def pixel_face():
    """Pixelify Sans on its own grid: one design pixel is ~91 units of 1000, so 11 px"""
    if 'px' not in _fc:
        f = ImageFont.truetype(str(FD / 'PixelifySans.ttf'), 11)
        f.set_variation_by_name('Regular')
        _fc['px'] = f
    return _fc['px']

def tw(s, f): return f.getlength(s)

def fit(s, f, maxw):
    if tw(s, f) <= maxw:
        return s
    while s and tw(s + '...', f) > maxw:
        s = s[:-1]
    return s.rstrip() + '...'

def wrap(s, f, maxw, n):
    words, lines, cur = s.split(), [], ''
    for w_ in words:
        t = (cur + ' ' + w_).strip()
        if tw(t, f) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    lines.append(cur)
    if len(lines) > n:
        lines = lines[:n]
        lines[-1] = fit(lines[-1] + '...', f, maxw)
    return lines


# ------------------------------------------------------------------ the 2x2 grid
class Grid:
    """160 x 120 layer of 2 x 2 screen pixels; coordinates in screen px, snapped"""
    def __init__(self):
        self.im = Image.new('RGBA', (W // 2, H // 2), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)
        self.d.fontmode = '1'
    def rr(self, x0, y0, x1, y1, c, r=2):
        a, b, cc, d = x0 // 2, y0 // 2, x1 // 2, y1 // 2
        rrect(self.d, a, b, cc, d, c, r)
    def paste(self, img, x, y, mask=None):
        self.im.paste(img, (x // 2, y // 2), mask)
    def text(self, x, yb, s, c, shadow=None, var='Regular'):
        f = pixel_face()
        a = int(x) // 2
        b = int(yb) // 2 - f.getmetrics()[0]
        if shadow:
            self.d.text((a, b + 1), s, font=f, fill=shadow)
        self.d.text((a, b), s, font=f, fill=c)
        return x + 2 * tw(s, f)
    def onto(self, base):
        base.alpha_composite(self.im.resize((W, H), Image.NEAREST))

def rrect(d, a, b, c, e, col, r=2):
    """pixel-rounded rect over cells [a, c) x [b, e)"""
    ind = {0: [], 1: [1], 2: [2, 1], 3: [3, 1, 1]}[r]
    n = len(ind)
    if e - b > 2 * n:
        d.rectangle([a, b + n, c - 1, e - 1 - n], fill=col)
    for i, k in enumerate(ind):
        d.line([(a + k, b + i), (c - 1 - k, b + i)], fill=col)
        d.line([(a + k, e - 1 - i), (c - 1 - k, e - 1 - i)], fill=col)

def rr_mask(w, h, r=2):
    m = Image.new('L', (w, h), 0)
    rrect(ImageDraw.Draw(m), 0, 0, w, h, 255, r)
    return m

def texture(mat, w, h, seed=1):
    rnd = random.Random(seed)
    base = C[MAT[mat][0]]
    im = Image.new('RGB', (w, h), base)
    px = im.load()
    def speck(c, p):
        for y in range(h):
            for x in range(w):
                if rnd.random() < p:
                    px[x, y] = c
    if mat == 'wood':                             # grain: broken horizontal streaks
        for y in range(h):
            x = rnd.randrange(-8, 0)
            while x < w:
                L = rnd.randrange(3, 15)
                c = rnd.choice([C['walnut_d'], C['walnut_l'], None, None, C['walnut_d']])
                if c:
                    for xx in range(max(0, x), min(w, x + L)):
                        px[xx, y] = c
                x += L + rnd.randrange(2, 9)
        hi, lo = C['walnut_hi'], C['walnut_d']
    elif mat == 'leather':
        speck(C['leather_d'], .07)
        for x in range(2, w - 2):
            if (x // 2) % 2 == 0:
                px[x, 2] = px[x, h - 3] = C['stitch']
        for y in range(2, h - 2):
            if (y // 2) % 2 == 0:
                px[2, y] = px[w - 3, y] = C['stitch']
        hi, lo = None, C['leather_d']
    elif mat == 'leaf':
        speck(C['leaf_l'], .05)
        speck(C['leaf_d'], .05)
        hi, lo = C['leaf_l'], C['leaf_d']
    elif mat == 'sage':                           # curtain folds
        for y in range(h):
            for x in range(w):
                m = x % 6
                if m in (0, 1):
                    px[x, y] = C['sage_l']
                elif m == 3:
                    px[x, y] = C['sage_d']
        hi, lo = None, C['sage_d']
    elif mat == 'silver':
        hi, lo = C['silver_l'], C['silver_d']
    elif mat == 'shade':
        for y in range(h):
            for x in range(0, w, 5):
                px[x, y] = C['shade_line']
        hi, lo = None, C['shade_line']
    elif mat == 'key':
        hi, lo = C['key_l'], C['key_d']
        for x in range(w):
            px[x, h - 2] = lo
    elif mat == 'felt':
        speck(C['felt_d'], .12)
        speck(C['felt_l'], .06)
        hi, lo = C['felt_l'], C['felt_d']
    for x in range(w):
        if hi:
            px[x, 0] = hi
        if lo:
            px[x, h - 1] = lo
    return im

def vents(g, x0, y0, x1, y1):
    """the PC case's slots"""
    a, b, c, d = x0 // 2, y0 // 2, x1 // 2, y1 // 2
    for k, y in enumerate(range(b, d, 3)):
        x = a + (3 if k % 2 else 0)
        while x + 5 <= c:
            g.d.line([(x, y), (x + 4, y)], fill=C['slot'])
            g.d.point((x, y + 1), fill=C['silver_l'])
            x += 7

def panel(g, x0, y0, x1, y1, mat, seed=1, focus=False, outline=False):
    a, b, c, d = x0 // 2, y0 // 2, x1 // 2, y1 // 2
    lift = 1 if focus else 0
    rrect(g.d, a + 1, b + 1, c + 1, d + 1 + lift, C['wall_sh'])          # its shadow on the wall
    b -= lift
    d -= lift
    if focus:                                                           # picked: a cream rim
        rrect(g.d, a - 2, b - 2, c + 2, d + 2, C['walnut_d'], 3)
        rrect(g.d, a - 1, b - 1, c + 1, d + 1, C['cream'], 2)
    tex = texture(mat, c - a, d - b, seed)
    g.im.paste(tex, (a, b), rr_mask(c - a, d - b))
    if outline:
        m = rr_mask(c - a, d - b)
        inner = Image.new('L', m.size, 0)
        rrect(ImageDraw.Draw(inner), 1, 1, c - a - 1, d - b - 1, 255, 1)
        ring = Image.new('RGBA', m.size, C['walnut'] + (255,))
        g.im.paste(ring, (a, b), Image.fromarray(__import__('numpy').array(m) & ~__import__('numpy').array(inner)))
    return -2 * lift

def gsym(g, kind, cx, cy, s, fg, bg, acc=None):
    """a symbol on the 2x2 grid: drawn finely, then snapped to the grid in its own colours"""
    n = max(4, int(round(s / 2)))
    SS = M.SS
    tile = Image.new('RGB', (int(n * 2 * SS), int(n * 2 * SS)), bg)
    I.sym(M.Pen(tile), kind, n, n, n * 2 * .96, fg, bg, acc)
    small = tile.resize((n, n), Image.BOX)
    pal = [bg, fg] + ([acc] if acc else [])
    out = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    sp, op = small.load(), out.load()
    for y in range(n):
        for x in range(n):
            v = sp[x, y]
            best = min(pal, key=lambda q: sum((v[i] - q[i]) ** 2 for i in range(3)))
            if best != bg:
                op[x, y] = best + (255,)
    g.im.alpha_composite(out, (int(cx // 2 - n // 2), int(cy // 2 - n // 2)))

LEAF = ['.LL..', 'LLLD.', '.LLDD', '..DD.']
def vine(g, x, y0, y1, seed=3):
    """a pothos trailing down from the shelf"""
    rnd = random.Random(seed)
    a = x // 2
    side = 1
    for k, y in enumerate(range(y0 // 2, y1 // 2)):
        xx = a + int(round(math.sin(y * .45) * 1.2))
        g.d.point((xx, y), fill=C['leaf_d'])
        if k % 4 == 2:
            for r, row in enumerate(LEAF):
                for cidx, ch in enumerate(row):
                    if ch == '.':
                        continue
                    px_ = xx + (cidx + 1 if side > 0 else -cidx - 1)
                    g.d.point((px_, y + r - 1), fill=C['leaf_l'] if ch == 'L' else C['leaf'])
            side = -side

ARROW = ['#....', '##...', '#c#..', '#cc#.', '#c#..', '##...', '#....']
def cursor(g, x, y, t):
    """the little pointer beside whatever is picked; it bobs"""
    a = x // 2 + int(round(math.sin(t / 1000 * 2 * math.pi * 1.6)))
    b = y // 2 - 3
    for r, row in enumerate(ARROW):
        for cidx, ch in enumerate(row):
            if ch != '.':
                g.d.point((a + cidx, b + r), fill=C['walnut_d'] if ch == '#' else C['cream'])

def text1(im, x, yb, s, c, size=10, var='Regular'):
    d = ImageDraw.Draw(im)
    d.fontmode = '1'
    f = pix(size, var)
    d.text((int(round(x)), int(yb) - f.getmetrics()[0]), s, font=f, fill=c)
    return x + tw(s, f)

def battery(g, im, x_right, yb, col):
    a, b = x_right // 2 - 9, yb // 2 - 4
    g.d.rectangle([a, b, a + 7, b + 3], outline=col)
    g.d.rectangle([a + 2, b + 2, a + 6, b + 2], fill=col)
    g.d.point((a + 8, b + 1), fill=col)
    g.d.point((a + 8, b + 2), fill=col)
    text1(im, x_right - 22 - tw('87%', pix(10)), yb, '87%', col)

def shelf(g, im, title=None, mat=None, symk=None, h=24):
    """the header: the walnut shelf with the light strip under it; the page's tab on it"""
    tex = texture('wood', W // 2, h // 2, 7)
    g.im.paste(tex, (0, 0))
    g.d.line([(0, h // 2), (W // 2, h // 2)], fill=C['led'])
    g.d.line([(0, h // 2 + 1), (W // 2, h // 2 + 1)], fill=C['wall_sh'])
    if title:
        base, ink, acc = (C[k] for k in MAT[mat])
        f = pixel_face()
        x1 = int(8 + 26 + 2 * tw(title, f) + 10)
        rrect(g.d, 2, 1, x1 // 2, h // 2 - 1, C['walnut_d'])
        g.im.paste(texture(mat, x1 // 2 - 3, h // 2 - 3, 11), (3, 2), rr_mask(x1 // 2 - 3, h // 2 - 3))
        gsym(g, symk or 'wheel', 20, 12, 16, ink, base, acc)
        g.text(32, 19, title, ink, C['walnut_d'] if ink == C['cream'] else None)

def nowbar(g, im):
    y0 = 212
    g.im.paste(texture('wood', W // 2, (H - y0) // 2, 5), (0, y0 // 2))
    g.d.line([(0, y0 // 2), (int(W * .37) // 2, y0 // 2)], fill=C['key'])
    return y0

def nowbar_1x(im, y0=212):
    t = I.TR[0]
    cv = I.art(t[2], 28).resize((24, 24), Image.LANCZOS)
    im.paste(cv, (4, y0 + 3))
    text1(im, 34, y0 + 13, fit(t[0], pix(10, 'SemiBold'), 236), C['cream'], var='SemiBold')
    text1(im, 34, y0 + 24, fit(t[1], pix(10), 230), C['felt_l'])
    text1(im, W - 6 - tw('1:53', pix(10)), y0 + 13, '1:53', C['cream'])

def base():
    return Image.new('RGBA', (W, H), C['wall'] + (255,))


# ------------------------------------------------------------------ menu
MENU_P = {  # screen px cell, material
    'wheel': ((6, 28, 112, 206), 'wood'), 'now': ((118, 28, 314, 104), 'leather'),
    'explore': ((118, 110, 214, 156), 'leaf'), 'library': ((220, 110, 314, 156), 'silver'),
    'queue': ((118, 162, 162, 206), 'shade'), 'search': ((166, 162, 210, 206), 'sage'),
    'liked': ((214, 162, 258, 206), 'key'), 'settings': ((262, 162, 314, 206), 'felt')}
ORDER = ['wheel', 'now', 'explore', 'library', 'queue', 'search', 'liked', 'settings']

def menu(cur='wheel', t=0.0):
    im, g = base(), Grid()
    shelf(g, im, h=20)
    g.text(10, 16, 'Coda', C['cream'], C['walnut_d'])
    xd = int(10 + 2 * tw('Coda', pixel_face())) // 2
    g.d.rectangle([xd + 1, 6, xd + 2, 7], fill=C['key'])
    later = []
    lifts = {}
    for k in ORDER:
        (x0, y0, x1, y1), mat = MENU_P[k]
        lifts[k] = panel(g, x0, y0, x1, y1, mat, seed=ORDER.index(k) + 1, focus=k == cur,
                         outline=mat == 'shade')
    for k in ORDER:
        (x0, y0, x1, y1), mat = MENU_P[k]
        base_c, ink, acc = (C[q] for q in MAT[mat])
        dy = lifts[k]
        if k == 'wheel':
            gsym(g, 'wheel', 58, 100 + dy, 88, ink, base_c, acc)
            g.text(14, 198 + dy, 'Wheel', ink, C['walnut_d'])
        elif k == 'now':
            g.text(126, 48 + dy, 'Now playing', ink, C['leather_d'])
        elif k in ('explore', 'library'):
            g.text(x0 + 6, y1 - 5 + dy, k.title(), ink, C['walnut_d'] if ink == C['cream'] else None)
            if k == 'library':
                vents(g, x0 + 6, y0 + 6, x1 - 36, y0 + 16)
            gsym(g, k, x1 - 16, y0 + 13 + dy, 22, ink, base_c, acc)
        else:
            gsym(g, k, (x0 + x1) // 2, y0 + 17 + dy, 26, ink, base_c, acc)
    g.onto(im)
    # the screen's own pixels: the cover, song text, small labels
    (x0, y0, x1, y1), _ = MENU_P['now']
    dy = lifts['now']
    t0 = I.TR[0]
    cv = I.art(t0[2], 48).resize((48, 48), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    d.rectangle([x1 - 58, y0 + 22 + dy, x1 - 7, y0 + 73 + dy], fill=C['walnut_d'])
    im.paste(cv, (x1 - 56, y0 + 24 + dy))
    for i, line in enumerate(wrap(t0[0], pix(11, 'SemiBold'), 118, 2)):
        text1(im, 127, 66 + 12 * i + dy, line, C['cream'], size=11, var='SemiBold')
    text1(im, 127, 95 + dy, fit(t0[1], pix(10), 118), C['stitch'])
    text1(im, 14, 176 + lifts['wheel'], '18,388 songs', C['felt_l'])
    for k in ('queue', 'search', 'liked', 'settings'):
        (x0, y0, x1, y1), mat = MENU_P[k]
        ink = C[MAT[mat][1]]
        name = M.ITEMS[k][0]
        text1(im, (x0 + x1) // 2 - tw(name, pix(10, 'SemiBold')) / 2, y1 - 7 + lifts[k], name, ink, var='SemiBold')
    # the now bar; over everything, the pothos off the shelf and the pointer
    g2 = Grid()
    nowbar(g2, im)
    vine(g2, 312, 20, 96)
    cx0, cy0 = MENU_P[cur][0][:2]
    cursor(g2, max(0, cx0 - 8), cy0 + 12 + lifts[cur], t)
    g2.onto(im)
    nowbar_1x(im)
    return im.convert('RGB')


# ------------------------------------------------------------------ inner screens
def explore(focus=0, t=0.0):
    im, g = base(), Grid()
    shelf(g, im, 'Explore', 'leaf', 'explore')
    battery(g, im, W - 8, 16, C['cream'])
    shelves = [('Fresh finds', 'unheard, matched to your taste', I.TR[:7]),
               ('Deep cuts', 'barely played, the model says yes', I.TR[9:16])]
    tops = []
    for i, (name, sub_, items) in enumerate(shelves):
        y0 = 30 + i * 90
        foc = i == focus
        if foc:
            w_ = int(2 * tw(name, pixel_face()) + 16)
            rrect(g.d, 3, y0 // 2, (6 + w_) // 2, y0 // 2 + 11, C['walnut_d'])
            g.im.paste(texture('leaf', (w_) // 2 - 1, 9, 3), (4, y0 // 2 + 1), rr_mask(w_ // 2 - 1, 9))
            g.text(14, y0 + 18, name, C['cream'], C['leaf_d'])
            cursor(g, 0, y0 + 10, t)
        else:
            g.text(14, y0 + 18, name, C['ink'])
        # the plank the covers stand on (its light strip on when it's picked)
        py = y0 + 74
        g.im.paste(texture('wood', W // 2 - 4, 4, 20 + i), (2, py // 2))
        g.d.line([(3, py // 2 + 4), (W // 2 - 3, py // 2 + 4)], fill=C['led'] if foc else C['wall_sh'])
        tops.append((y0, sub_, items, foc))
    nowbar(g, im)
    g.onto(im)
    for y0, sub_, items, foc in tops:
        text1(im, 14, y0 + 30, sub_, C['sub'])
        text1(im, W - 12 - tw('24', pix(10)), y0 + 18, '24' if y0 < 100 else '31', C['sub'])
        for k, tr in enumerate(items):
            x = 8 + k * 44
            lean = (k == 4)
            cv = I.art(tr[2], 38).resize((38, 38), Image.LANCZOS)
            if lean:
                cv = cv.convert('RGBA').rotate(-8, resample=Image.NEAREST, expand=True, fillcolor=(0, 0, 0, 0))
                im.alpha_composite(cv, (x - 2, y0 + 74 - cv.size[1]))
            else:
                ImageDraw.Draw(im).rectangle([x - 1, y0 + 35, x + 38, y0 + 74], fill=C['walnut_d'])
                im.paste(cv, (x, y0 + 36))
    nowbar_1x(im)
    return im.convert('RGB')

def tracks(focus=2, t=0.0):
    im, g = base(), Grid()
    shelf(g, im, 'Fresh finds', 'leaf', 'explore')
    battery(g, im, W - 8, 16, C['cream'])
    # the buttons
    for i, (x0, x1, label, k, mat) in enumerate(((6, 160, 'Play all', 'now', 'leaf'),
                                                (166, 314, 'Shuffle', 'shuffle', 'silver'))):
        panel(g, x0, 30, x1, 56, mat, seed=30 + i, focus=focus == i)
        base_c, ink, acc = (C[q] for q in MAT[mat])
        dy = -2 if focus == i else 0
        gsym(g, k, x0 + 18, 43 + dy, 16, ink, base_c, None)
        g.text(x0 + 32, 50 + dy, label, ink, C['leaf_d'] if mat == 'leaf' else None)
    # the list, on lampshade white
    panel(g, 6, 62, 314, 208, 'shade', seed=40, outline=True)
    rows = I.TR[:5]
    fy = None
    for i in range(5):
        y = 64 + i * 29
        if focus == i + 2:
            rrect(g.d, 5, y // 2, 155, y // 2 + 14, C['leaf_d'])
            g.im.paste(texture('leaf', 150, 13, 50 + i), (5, y // 2), rr_mask(150, 13))
            fy = y
        elif i < 4:
            for x in range(6, 154, 2):
                g.d.point((x, (y + 28) // 2), fill=C['felt'])
    if fy is not None:
        cursor(g, 0, fy + 14, t)
    nowbar(g, im)
    g.onto(im)
    for i, tr in enumerate(rows):
        y = 64 + i * 29
        foc = focus == i + 2
        cv = I.art(tr[2], 24).resize((22, 22), Image.LANCZOS)
        im.paste(cv, (16, y + 3))
        fg, sub = (C['cream'], C['leaf_l']) if foc else (C['ink'], C['sub'])
        text1(im, 44, y + 12, fit(tr[0], pix(10, 'SemiBold'), 220), fg, var='SemiBold')
        text1(im, 44, y + 23, fit(tr[1], pix(10), 200), sub)
        d = I.mmss(tr[3])
        text1(im, 302 - tw(d, pix(10)), y + 12, d, fg)
    nowbar_1x(im)
    return im.convert('RGB')

def now():
    im, g = base(), Grid()
    shelf(g, im)
    # a "playing" tag on the shelf, in leather
    rrect(g.d, 3, 2, 42, 10, C['walnut_d'])
    g.im.paste(texture('leather', 38, 7, 61), (4, 3), rr_mask(38, 7))
    gsym(g, 'now', 18, 12, 10, C['cream'], C['leather'])
    battery(g, im, W - 8, 16, C['cream'])
    # the cover in a walnut frame, like the picture on the desk
    panel(g, 8, 32, 160, 184, 'wood', seed=62)
    # the desk: progress groove, knob
    y0 = 192
    g.im.paste(texture('wood', W // 2, (H - y0) // 2, 63), (0, y0 // 2))
    g.d.line([(0, y0 // 2), (W // 2, y0 // 2)], fill=C['walnut_hi'])
    gx0, gx1, gy = 6, 154, y0 // 2 + 4
    g.d.rectangle([gx0, gy, gx1, gy + 2], fill=C['walnut_d'])
    px_ = gx0 + int((gx1 - gx0) * .31)
    g.d.rectangle([gx0, gy, px_, gy + 2], fill=C['key'])
    rrect(g.d, px_ - 2, gy - 2, px_ + 3, gy + 5, C['cream'], 1)
    g.text(12, y0 + 34, '0:41', C['cream'], C['walnut_d'])
    tr = I.TR[0]
    f = pixel_face()
    lines = wrap(tr[0], f, 68, 3)
    for i, line in enumerate(lines):
        g.text(172, 52 + i * 20, line, C['ink'])
    yb = 52 + (len(lines) - 1) * 20
    g.onto(im)
    cv = I.art(tr[2], 140).resize((140, 140), Image.LANCZOS)
    im.paste(cv, (14, 38))
    text1(im, 30, 16, 'playing', C['cream'], var='SemiBold')
    text1(im, 172, yb + 18, fit(tr[1], pix(10, 'SemiBold'), 140), C['leaf_d'], var='SemiBold')
    for i, line in enumerate(wrap("sounds like what's playing, fits this session's mood", pix(10), 132, 3)):
        text1(im, 172, yb + 34 + i * 12, line, C['sub'])
    text1(im, 62, y0 + 34, '/ ' + I.mmss(tr[3]), C['felt_l'])
    nt = I.TR[1]
    im.paste(I.art(nt[2], 20).resize((20, 20), Image.LANCZOS), (170, y0 + 16))
    text1(im, 196, y0 + 23, 'next, autoplay', C['felt_l'])
    text1(im, 196, y0 + 35, fit(nt[0], pix(10, 'SemiBold'), 118), C['cream'], var='SemiBold')
    return im.convert('RGB')

def settings(cur='sleep', t=0.0):
    im, g = base(), Grid()
    shelf(g, im, 'Settings', 'felt', 'settings')
    battery(g, im, W - 8, 16, C['cream'])
    cells = {
        'sleep': ((6, 30, 124, 112), 'sage', 'Sleep', 'off', 'sleep'),
        'sound': ((130, 30, 314, 112), 'silver', 'Sound', 'limit -34 dB, flat', 'sound'),
        'screen': ((6, 118, 102, 164), 'shade', 'Screen', '27%, 30 s', 'screen'),
        'power': ((108, 118, 210, 164), 'key', 'Power', 'idle 10 min', 'power'),
        'wheel': ((216, 118, 314, 164), 'wood', 'Wheel', 'A, clicks', 'wheel'),
        'playback': ((6, 170, 124, 208), 'leaf', 'Playback', 'autoplay on', 'playback'),
        'bt': ((130, 170, 222, 208), 'felt', 'Bluetooth', 'WH-1000XM4', 'bt'),
        'clock': ((228, 170, 314, 208), 'leather', 'Clock', '12:41', 'clock')}
    lifts = {}
    for i, (k, (cell, mat, *_)) in enumerate(cells.items()):
        lifts[k] = panel(g, *cell, mat, seed=70 + i, focus=k == cur, outline=mat == 'shade')
    for k, (cell, mat, label, val, sk_) in cells.items():
        x0, y0, x1, y1 = cell
        base_c, ink, acc = (C[q] for q in MAT[mat])
        dy = lifts[k]
        big = y1 - y0 > 60
        if big:
            gsym(g, sk_, x1 - 30, y0 + 30 + dy, 36, ink, base_c, acc)
            if k == 'sound':
                vents(g, x0 + 8, y0 + 10, x1 - 60, y0 + 30)
            g.text(x0 + 10, y1 - 12 + dy, label, ink, C['walnut_d'] if ink == C['cream'] else None)
        else:
            gsym(g, sk_, x1 - 17, y0 + 16 + dy, 24, ink, base_c, acc)
    cx0, cy0 = cells[cur][0][:2]
    cursor(g, max(0, cx0 - 8), cy0 + 12 + lifts[cur], t)
    nowbar(g, im)
    g.onto(im)
    for k, (cell, mat, label, val, sk_) in cells.items():
        x0, y0, x1, y1 = cell
        ink = C[MAT[mat][1]]
        dy = lifts[k]
        subc = C['felt_l'] if ink == C['cream'] else C['sub']
        if y1 - y0 > 60:
            text1(im, x0 + 10, y1 - 34 + dy, val, subc)
        else:
            text1(im, x0 + 8, y1 - 8 + dy, label, ink, var='SemiBold')
            text1(im, x0 + 8, y1 - 21 + dy, fit(val, pix(10), x1 - x0 - 36), subc)
    nowbar_1x(im)
    return im.convert('RGB')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shots = {'menu': menu('wheel'), 'menu_explore': menu('explore'), 'explore': explore(0),
             'tracks': tracks(2), 'now': now(), 'settings': settings('sleep')}
    for k, im in shots.items():
        im.save(OUT / f'{k}.png')
        im.resize((W * 2, H * 2), Image.NEAREST).save(OUT / f'{k}@2x.png')
    g, cols = 10, 3
    order = list(shots)
    sheet = Image.new('RGB', (cols * (W + g) + g, 2 * (H + g) + g), (0x8a, 0x76, 0x5e))
    for i, k in enumerate(order):
        sheet.paste(shots[k], (g + (i % cols) * (W + g), g + (i // cols) * (H + g)))
    sheet.save(OUT / 'sheet.png')
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(OUT / 'sheet@2x.png')
    if '--still' not in sys.argv:
        fr = []
        for k in ORDER:
            for j in range(int(.6 * FPS)):
                fr.append(menu(k, j * 1000 / FPS))
        big = [f.resize((W * 2, H * 2), Image.NEAREST) for f in fr]
        big[0].save(OUT / 'menu.gif', save_all=True, append_images=big[1:], duration=int(1000 / FPS), loop=0)
    print('ok', OUT)

if __name__ == '__main__':
    main()
