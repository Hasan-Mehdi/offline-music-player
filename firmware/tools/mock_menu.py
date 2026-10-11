"""Main-menu mockups for Coda on the H2, after Masahiro Sakurai's menus (Smash Bros.
Ultimate's tilted mode panels, Kirby's bouncy cursors): the menu as symbols on buttons,
sized and placed with intent, a snappy cursor, and a line saying what the focused item does.
Inside the record-shop poster language (paper, ink, Klein blue; red only for what's live;
the user's covers for colour). Every symbol is built from the device renderer's primitives
(rects, discs, rings, convex polygons), so whichever is picked can be drawn on the X1000.
On focus each symbol does one short flourish (the wheel turns a slice, the heart beats...).

  A  panels   skewed panels sized by use, Smash Ultimate's main menu set in print
  B  keypad   eight hardware keys on a plinth; the focused key goes down
  C  dial     the symbols ride a ring the click wheel turns; the focused one comes forward

Output: docs/h2/menu/<A|B|C>.gif (the cursor through all eight), <A|B|C>.png, sheet.png
  .venv/Scripts/python firmware/tools/mock_menu.py
"""
import base64, io, math, sqlite3
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import mutagen
from mutagen.flac import Picture

ROOT = Path(__file__).resolve().parents[2]
FD = ROOT / 'firmware' / 'assets' / 'fonts'
OUT = ROOT / 'docs' / 'h2' / 'menu'
W, H, SS, FPS = 320, 240, 3, 25
PAPER, INK, BLUE, RED = (0xf4, 0xf4, 0xf0), (0x14, 0x14, 0x14), (0x00, 0x2f, 0xa7), (0xe0, 0x30, 0x1e)
SUB, RULE, STRIP_SUB = (0x6d, 0x6d, 0x66), (0xd9, 0xd8, 0xd0), (0x93, 0x93, 0x8b)
BAR_Y = 212
POSTER, BODY, MONO = 'ArchivoBlack-Regular.ttf', 'Archivo.ttf', 'Inconsolata.ttf'
SONGS = '18,388'

_fc = {}
def font(name, px, var=None):
    k = (name, px, var)
    if k not in _fc:
        f = ImageFont.truetype(str(FD / name), max(1, int(round(px * SS))))
        if var:
            f.set_variation_by_name(var)
        _fc[k] = f
    return _fc[k]

def tw(s, f, track=0.0):
    return sum(f.getlength(c) for c in s) / SS + track * max(0, len(s) - 1)

def fit(s, f, maxw, track=0.0):
    if tw(s, f, track) <= maxw:
        return s
    while s and tw(s + '…', f, track) > maxw:
        s = s[:-1]
    return s.rstrip() + '…'

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
        lines[-1] = fit(lines[-1] + '…', f, maxw)
    return lines

def clamp01(v): return 0.0 if v < 0 else 1.0 if v > 1 else v
def seg(t, a, b): return clamp01((t - a) / (b - a))
def ease_out(u): u = clamp01(u); return 1 - (1 - u) ** 3
def ease_back(u, k=1.70158): u = clamp01(u); return 1 + (k + 1) * (u - 1) ** 3 + k * (u - 1) ** 2
def mix(a, b, t): return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


class Pen:
    """Draws in screen px onto an SS-scale image whose origin is (ox, oy) in SS px."""
    def __init__(self, im, ox=0, oy=0):
        self.im, self.d, self.ox, self.oy = im, ImageDraw.Draw(im), ox, oy
    def X(self, x): return x * SS - self.ox
    def Y(self, y): return y * SS - self.oy
    def rect(self, x0, y0, x1, y1, c):
        if x1 > x0 and y1 > y0:
            self.d.rectangle([self.X(x0), self.Y(y0), self.X(x1) - 1, self.Y(y1) - 1], fill=c)
    def poly(self, pts, c, outline=None, width=0):
        self.d.polygon([(self.X(x), self.Y(y)) for x, y in pts], fill=c, outline=outline,
                       width=int(round(width * SS)) if outline else 1)
    def disc(self, cx, cy, r, c):
        if r > 0:
            self.d.ellipse([self.X(cx - r), self.Y(cy - r), self.X(cx + r), self.Y(cy + r)], fill=c)
    def ring(self, cx, cy, r, w, c):
        ro = r + w / 2
        self.d.ellipse([self.X(cx - ro), self.Y(cy - ro), self.X(cx + ro), self.Y(cy + ro)],
                       outline=c, width=max(1, int(round(w * SS))))
    def bar(self, x0, y0, x1, y1, w, c):
        L = math.hypot(x1 - x0, y1 - y0) or 1
        nx, ny = -(y1 - y0) / L * w / 2, (x1 - x0) / L * w / 2
        self.poly([(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)], c)
    def text(self, x, yb, s, f, c, track=0.0):
        cx = self.X(x)
        for ch in s:
            self.d.text((cx, self.Y(yb)), ch, font=f, fill=c, anchor='ls')
            cx += f.getlength(ch) + track * SS
        return (cx + self.ox) / SS
    def paste(self, img, x, y, mask=None):
        self.im.paste(img, (int(round(self.X(x))), int(round(self.Y(y)))), mask)


# --------------------------------------------------------------------- the symbols
def rhomb(p, cx, cy, ang, L, w, c):
    ca, sa = math.cos(ang), math.sin(ang)
    p.poly([(cx + ca * L, cy + sa * L), (cx - sa * w, cy + ca * w),
            (cx - ca * L, cy - sa * L), (cx + sa * w, cy - ca * w)], c)

def sym(p, kind, cx, cy, s, fg, bg, acc=None, u=1.0):
    """kind's symbol in an s x s box; u = 0..1 through its focus flourish (1 = at rest)"""
    acc = acc or fg
    if kind == 'wheel':                         # covers on a wheel; it turns a slice
        p.disc(cx, cy, .46 * s, fg)
        a0 = math.pi / 8 + math.pi / 4 * (ease_back(u) - 1)
        for k in range(4):
            a = a0 + math.pi * k / 4
            dx, dy = math.cos(a) * .5 * s, math.sin(a) * .5 * s
            p.bar(cx - dx, cy - dy, cx + dx, cy + dy, .075 * s, bg)
        p.disc(cx, cy, .2 * s, bg)
        p.disc(cx, cy, .085 * s, acc)
    elif kind == 'now':                         # play; it kicks
        k = 1 + .2 * math.sin(math.pi * clamp01(u)) if u < 1 else 1
        p.poly([(cx + x * s * k, cy + y * s * k) for x, y in ((-.28, -.4), (-.28, .4), (.44, 0))], fg)
    elif kind == 'queue':                       # what's next, the live one marked; they slide in
        h = .16 * s
        for j, (dy, L) in enumerate(((-.3, .67), (0, .5), (.3, .34))):
            off = -(1 - ease_back(seg(u, j * .12, j * .12 + .55))) * .3 * s
            y = cy + dy * s
            p.rect(cx - .22 * s + off, y - h / 2, cx + (L - .22) * s + off, y + h / 2, fg)
        p.rect(cx - .46 * s, cy - .3 * s - h / 2, cx - .46 * s + h, cy - .3 * s + h / 2, acc)
    elif kind == 'explore':                     # a compass rose; it swings round to north
        a = math.pi / 2 * (ease_back(u) - 1)
        rhomb(p, cx, cy, a, .5 * s, .13 * s, fg)
        rhomb(p, cx, cy, a + math.pi / 2, .5 * s, .13 * s, fg)
        rhomb(p, cx, cy, a + math.pi / 4, .3 * s, .08 * s, fg)
        rhomb(p, cx, cy, a + 3 * math.pi / 4, .3 * s, .08 * s, fg)
        n = a - math.pi / 2
        p.poly([(cx + math.cos(n) * .5 * s, cy + math.sin(n) * .5 * s),
                (cx + math.cos(n + math.pi / 2) * .13 * s, cy + math.sin(n + math.pi / 2) * .13 * s),
                (cx - math.cos(n + math.pi / 2) * .13 * s, cy - math.sin(n + math.pi / 2) * .13 * s)], acc)
        p.disc(cx, cy, .055 * s, bg)
    elif kind == 'search':                      # a lens; it wiggles, looking
        wig = math.sin(u * math.pi * 3) * (1 - u) * .14 * s if u < 1 else 0
        rx, ry = cx - .1 * s + wig, cy - .1 * s
        p.ring(rx, ry, .25 * s, .12 * s, fg)
        a = math.pi / 4
        p.bar(rx + math.cos(a) * .3 * s, ry + math.sin(a) * .3 * s, cx + .42 * s + wig * .5,
              cy + .42 * s, .15 * s, fg)
    elif kind == 'library':                     # spines on a shelf; the last one tips over
        base, w_, g = cy + .42 * s, .12 * s, .045 * s
        x = cx - .44 * s
        for hgt, c in ((.78, fg), (.6, fg), (.88, acc), (.7, fg)):
            p.rect(x, base - hgt * s, x + w_, base, c)
            x += w_ + g
        lean = .2 * s * ease_back(seg(u, .1, .8), 2.4)
        xb = x + .04 * s
        p.poly([(xb, base), (xb + w_, base), (xb + w_ - lean, base - .66 * s), (xb - lean, base - .66 * s)], fg)
    elif kind == 'liked':                       # a heart; it beats twice
        k = 1 + .2 * math.sin(math.pi * seg(u, 0, .4)) + .1 * math.sin(math.pi * seg(u, .45, .75))
        S = s * k
        a = .56 * S
        h, m, r = a / math.sqrt(2), a / (2 * math.sqrt(2)), a / 2
        c = cy + .041 * S
        p.poly([(cx, c - h), (cx + h, c), (cx, c + h), (cx - h, c)], fg)
        p.disc(cx - m, c - m, r, fg)
        p.disc(cx + m, c - m, r, fg)
    elif kind == 'settings':                    # two sliders; the knobs slide to place
        for j, (dy, k0, k1, hollow) in enumerate(((-.2, -.3, .17, False), (.2, .3, -.19, True))):
            uj = ease_back(seg(u, j * .12, j * .12 + .6))
            y = cy + dy * s
            p.rect(cx - .45 * s, y - .04 * s, cx + .45 * s, y + .04 * s, fg)
            kx = cx + (k0 + (k1 - k0) * uj) * s
            p.disc(kx, y, .15 * s, fg)
            if hollow:
                p.disc(kx, y, .065 * s, bg)


# --------------------------------------------------------------------- real content
def cover_of(path, px):
    try:
        f = mutagen.File(path)
        for b in (f.tags or {}).get('metadata_block_picture', []):
            im = Image.open(io.BytesIO(Picture(base64.b64decode(b)).data)).convert('RGB')
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
            return im.resize((px * SS, px * SS), Image.LANCZOS)
    except Exception:
        pass
    return None

def now_song():
    db = sqlite3.connect(f'file:{ROOT / "data" / "library.db"}?mode=ro', uri=True)
    for title, artist, path in db.execute("""select t.title, t.artist, t.path from plays p
            join tracks t on t.video_id = p.video_id order by p.ts desc limit 20"""):
        if cover_of(path, 8):
            return title, artist, path
    return 'Nothing playing', '', None

SONG = now_song()
_covers = {}
def cover(px):
    if px not in _covers:
        _covers[px] = cover_of(SONG[2], px) if SONG[2] else None
        if _covers[px] is None:
            _covers[px] = Image.new('RGB', (px * SS, px * SS), (0xea, 0xea, 0xe3))
    return _covers[px]

ITEMS = {
    'wheel': ('Wheel', 'Spin through your songs, covers on a wheel.', f'{SONGS} songs'),
    'now': ('Now playing', f'{SONG[0]} — {SONG[1]}', '1:53 / 3:12'),
    'queue': ('Queue', 'What plays next, and what Coda adds after it.', '3 of 24'),
    'explore': ('Explore', 'Fresh finds and shelves picked from your taste.', '12 shelves'),
    'search': ('Search', 'Spell a song or an artist with the wheel.', ''),
    'library': ('Library', 'Songs, artists, genres, soundtracks, history.', f'{SONGS} songs'),
    'liked': ('Liked', 'Every song you held Play on.', '412 songs'),
    'settings': ('Settings', 'Sleep, sound, screen, Bluetooth, clock.', ''),
}
MENU = ['wheel', 'now', 'queue', 'explore', 'search', 'library', 'liked', 'settings']


def battery(p, x_right, yb):
    x0, y0 = x_right - 19, yb - 8
    p.rect(x0, y0, x0 + 17, y0 + 8, INK)
    p.rect(x0 + 1, y0 + 1, x0 + 16, y0 + 7, PAPER)
    p.rect(x0 + 2, y0 + 2, x0 + 2 + 13 * .87, y0 + 6, INK)
    p.rect(x0 + 17, y0 + 2, x0 + 19, y0 + 6, INK)
    s = '87%'
    f = font(MONO, 10)
    p.text(x0 - 6 - tw(s, f), yb, s, f, SUB)

def status(p, yb=16, px=16):
    x = p.text(8, yb, 'Coda', font(POSTER, px), INK, track=-px * .05)
    p.rect(x + 1.5, yb - 5, x + 6.5, yb, RED)
    battery(p, W - 8, yb - 1)

def nowbar(p):
    y0, h = BAR_Y, H - BAR_Y
    p.rect(0, y0, W, H, INK)
    p.paste(cover(h), 0, y0)
    p.rect(0, y0, W * .37, y0 + 2, RED)
    p.rect(h + 6, y0 + 9, h + 11, y0 + 14, RED)
    p.text(h + 15, y0 + 15, fit(SONG[0], font(BODY, 11, 'Bold'), 236 - h - 15), font(BODY, 11, 'Bold'), PAPER)
    p.text(h + 6, y0 + 25, fit(SONG[1], font(BODY, 10), 230 - h), font(BODY, 10), STRIP_SUB)
    f = font(MONO, 10)
    p.text(W - 6 - tw('1:53', f), y0 + 15, '1:53', f, PAPER)

def canvas():
    im = Image.new('RGB', (W * SS, H * SS), PAPER)
    return im, Pen(im)

def down(im):
    return im.resize((W, H), Image.LANCZOS)


# --------------------------------------------------------------------- A: panels
K = .2                                         # the lean
def sk(x, y): return (x + (116 - y) * K, y)
A_SPEC = {  # unskewed cell, bg, fg, accent, style, outlined, focus scale
    'wheel': ((-40, 25, 98, 210), INK, PAPER, RED, 'big', False, 1.035),
    'now': ((103, 25, 350, 104), RED, PAPER, None, 'now', False, 1.04),
    'explore': ((103, 109, 222, 156), BLUE, PAPER, INK, 'mid', False, 1.08),
    'library': ((227, 109, 350, 156), PAPER, INK, BLUE, 'mid', True, 1.08),
    'queue': ((103, 161, 154, 210), PAPER, INK, RED, 'small', True, 1.09),
    'search': ((159, 161, 210, 210), INK, PAPER, None, 'small', False, 1.09),
    'liked': ((215, 161, 266, 210), BLUE, PAPER, None, 'small', False, 1.09),
    'settings': ((271, 161, 350, 210), PAPER, INK, None, 'small', True, 1.09),
}
A_ORDER = ['wheel', 'now', 'explore', 'library', 'queue', 'search', 'liked', 'settings']

def a_panel(kind, u):
    (x0, y0, x1, y1), bg, fg, acc, style, outlined, _ = A_SPEC[kind]
    pts = [sk(x0, y0), sk(x1, y0), sk(x1, y1), sk(x0, y1)]
    bx0 = int(math.floor(min(x for x, _ in pts) * SS)) - 2
    by0 = int(math.floor(min(y for _, y in pts) * SS)) - 2
    bx1 = int(math.ceil(max(x for x, _ in pts) * SS)) + 2
    by1 = int(math.ceil(max(y for _, y in pts) * SS)) + 2
    lay = Image.new('RGB', (bx1 - bx0, by1 - by0), bg)
    p = Pen(lay, bx0, by0)
    lx = lambda y: sk(x0, y)[0] + 6               # the left margin follows the lean
    vis_cx = lambda y: (sk(x0, y)[0] + min(sk(x1, y)[0], W)) / 2    # middle of what's on screen
    if style == 'big':
        sym(p, kind, 46, 102, 124, fg, bg, acc, u)
        p.text(10, 181, f'{SONGS} songs', font(MONO, 10), STRIP_SUB)
        p.text(9, 202, 'Wheel', font(POSTER, 22), fg, track=-1.1)
    elif style == 'now':
        cv = cover(92).crop((0, 6 * SS, 92 * SS, 85 * SS))
        cm = Image.new('L', cv.size, 0)
        cx0 = 210
        ImageDraw.Draw(cm).polygon([((sk(cx0, 25)[0] - 228) * SS, 0), (92 * SS, 0), (92 * SS, 79 * SS),
                                    ((sk(cx0, 104)[0] - 228) * SS, 79 * SS)], fill=255)
        p.paste(cv, 228, 25, cm)
        p.text(lx(43), 43, 'Now playing', font(POSTER, 15), fg, track=-.7)
        fb = font(BODY, 11, 'Bold')
        for i, line in enumerate(wrap(SONG[0], fb, 92, 2)):
            p.text(lx(60 + 13 * i), 60 + 13 * i, line, fb, fg)
        p.text(lx(95), 95, fit(SONG[1], font(BODY, 10), 90), font(BODY, 10), mix(RED, PAPER, .72))
    elif style == 'mid':
        p.text(lx(148), 148, ITEMS[kind][0], font(POSTER, 15), fg, track=-.6)
        r = min(sk(x1, 125)[0], W) - 22
        sym(p, kind, r, 128, 28, fg, bg, acc, u)
    else:
        f = font(POSTER, 11)
        name = ITEMS[kind][0]
        sym(p, kind, vis_cx(y0 + 19), y0 + 19, 21, fg, bg, acc, u)
        p.text(vis_cx(y0 + 40) - tw(name, f, -.3) / 2, y0 + 41, name, f, fg, track=-.3)
    mask = Image.new('L', lay.size, 0)
    mp = [(x * SS - bx0, y * SS - by0) for x, y in pts]
    ImageDraw.Draw(mask).polygon(mp, fill=255)
    if outlined:
        ImageDraw.Draw(lay).polygon(mp, outline=INK, width=int(4 * SS))
    return lay, mask, (bx0, by0), pts, bg

def a_frame(cur, prev, t):
    im, p = canvas()
    status(p)
    later = []
    for kind in A_ORDER:
        if kind == cur:
            later.append(kind)
            continue
        if kind == prev and t < 150:
            later.insert(0, kind)
            continue
        lay, mask, (bx0, by0), pts, bg = a_panel(kind, 1.0)
        im.paste(lay, (bx0, by0), mask)
    for kind in later:
        focused = kind == cur
        u = seg(t, 60, 560) if focused else 1.0
        lay, mask, (bx0, by0), pts, bg = a_panel(kind, u)
        k = A_SPEC[kind][6] - 1
        sc = 1 + k * ease_back(seg(t, 0, 220), 2.2) if focused else 1 + k * (1 - ease_out(seg(t, 0, 150)))
        cx = (bx0 + lay.size[0] / 2) / SS
        cy = (by0 + lay.size[1] / 2) / SS
        spts = [(cx + (x - cx) * sc, cy + (y - cy) * sc) for x, y in pts]
        if focused:
            sh = BLUE if bg == INK else INK
            o = 5 * ease_out(seg(t, 0, 160))
            p.poly([(x + o, y + o) for x, y in spts], sh)
        nw, nh = int(lay.size[0] * sc), int(lay.size[1] * sc)
        im.paste(lay.resize((nw, nh), Image.LANCZOS),
                 (int(round(cx * SS - nw / 2)), int(round(cy * SS - nh / 2))),
                 mask.resize((nw, nh), Image.BILINEAR))
    nowbar(p)
    return down(im)


# --------------------------------------------------------------------- B: keypad
def b_key(i):
    col, row = i % 4, i // 4
    return 18 + col * 76, 86 + row * 66, (col + row) % 2 == 0      # x, y, round

def b_frame(cur, prev, t):
    im, p = canvas()
    status(p)
    # the focused item's name comes up from below the line; what it does, under it
    name, desc, count = ITEMS[cur]
    lay = Image.new('RGB', (W * SS, 34 * SS), PAPER)
    lp = Pen(lay, 0, 24 * SS)
    lift = 16 * (1 - ease_back(seg(t, 0, 240), 1.9))
    lp.text(16, 54 + lift, name, font(POSTER, 26), INK, track=-1.3)
    if count:
        f = font(MONO, 10)
        lp.text(W - 16 - tw(count, f), 53, count, f, SUB)
    im.paste(lay, (0, 24 * SS))
    if t >= 70:
        p.text(16, 73, fit(desc, font(BODY, 11), W - 32), font(BODY, 11), SUB)
    for i, kind in enumerate(MENU):
        x, y, rnd = b_key(i)
        focused = kind == cur
        press = ease_out(seg(t, 0, 120)) if focused else (1 - ease_out(seg(t, 0, 140)) if kind == prev else 0)
        o = 4 * press
        S = 56
        def shape(xx, yy, c, outline=None, width=0):
            if rnd:
                p.disc(xx + S / 2, yy + S / 2, S / 2, c)
                if outline:
                    p.ring(xx + S / 2, yy + S / 2, S / 2 - width / 2, width, outline)
            else:
                p.rect(xx, yy, xx + S, yy + S, c)
                if outline:
                    p.d.rectangle([p.X(xx), p.Y(yy), p.X(xx + S) - 1, p.Y(yy + S) - 1], outline=outline,
                                  width=int(round(width * SS)))
        shape(x + 4, y + 4, INK)                                       # the plinth
        fx, fy = x + o, y + o
        if kind == 'now':
            cv = cover(S)
            m = Image.new('L', cv.size, 0)
            if rnd:
                ImageDraw.Draw(m).ellipse([0, 0, S * SS - 1, S * SS - 1], fill=255)
            else:
                m.paste(255, (0, 0, S * SS, S * SS))
            p.paste(cv, fx, fy, m)
            shape(fx, fy, None, BLUE if focused else INK, 4 if focused else 2.5)
            p.disc(fx + S - 9, fy + 9, 4, RED)
            p.ring(fx + S - 9, fy + 9, 4, 1.5, PAPER)
            continue
        face = BLUE if focused else PAPER
        shape(fx, fy, face, INK, 2.5)
        fg = PAPER if focused else INK
        acc = {'wheel': RED, 'queue': RED, 'explore': BLUE if not focused else INK,
               'library': BLUE if not focused else PAPER}.get(kind)
        sym(p, kind, fx + S / 2, fy + S / 2, 31, fg, face, acc, seg(t, 40, 540) if focused else 1.0)
    nowbar(p)
    return down(im)


# --------------------------------------------------------------------- C: dial
C_C, C_R, C_STEP = (384, 118), 150, math.radians(27)

def c_frame(cur, prev, t):
    im, p = canvas()
    status(p)
    n = len(MENU)
    ic, ip = MENU.index(cur), MENU.index(prev)
    step = (ic - ip + n // 2) % n - n // 2                  # the short way round
    f = ip + step * ease_back(seg(t, 0, 340), 1.5)
    p.ring(C_C[0], C_C[1], C_R, 2, RULE)
    meds = []
    for i, kind in enumerate(MENU):
        dd = (i - f + n / 2) % n - n / 2
        if abs(dd) > 2.6:
            continue
        a = math.pi + dd * C_STEP
        x, y = C_C[0] + math.cos(a) * C_R, C_C[1] + math.sin(a) * C_R
        near = max(0.0, 1 - abs(dd))
        meds.append((near, kind, x, y, 17 + 17 * near))
    for near, kind, x, y, r in sorted(meds):
        focused = kind == cur
        if kind == 'now':
            d2 = int(round(2 * r))
            cv = cover(max(8, d2))
            m = Image.new('L', cv.size, 0)
            ImageDraw.Draw(m).ellipse([0, 0, cv.size[0] - 1, cv.size[1] - 1], fill=255)
            p.paste(cv, x - cv.size[0] / SS / 2, y - cv.size[1] / SS / 2, m)
            p.ring(x, y, r - 1.5, 3, mix(INK, BLUE, near) if near > .5 else INK)
            p.disc(x, y, r * .2, PAPER)
            p.disc(x, y, r * .11, RED)
            continue
        bg = mix(INK, BLUE, clamp01(near * 2 - 1))
        p.disc(x, y, r, bg)
        acc = {'wheel': RED, 'queue': RED}.get(kind)
        sym(p, kind, x, y, r * 1.12, PAPER, bg, acc, seg(t, 120, 620) if focused else 1.0)
    p.rect(0, 0, W, 24, PAPER)                     # the ring passes under the status line
    status(p)
    # the name sets on the left margin, revealed left to right (as the boot animation's)
    name, desc, count = ITEMS[cur]
    px = 30
    while tw(name, font(POSTER, px), -px * .05) > 176 and px > 18:
        px -= 1
    e = ease_out(seg(t, 0, 260))
    lay = Image.new('RGB', (190 * SS, 40 * SS), PAPER)
    lp = Pen(lay, 0, 70 * SS)
    lp.text(14 - 12 * (1 - e), 104, name, font(POSTER, px), INK, track=-px * .05)
    clip = min(lay.size[0], int((14 + e * 180) * SS))
    im.paste(lay.crop((0, 0, max(1, clip), lay.size[1])), (0, 70 * SS))
    if t >= 120:
        fb = font(BODY, 11)
        for i, line in enumerate(wrap(desc, fb, 176, 2)):
            p.text(14, 124 + 14 * i, line, fb, SUB)
        if count:
            p.text(14, 163, count, font(MONO, 10), INK)
    nowbar(p)
    return down(im)


# --------------------------------------------------------------------- output
STEP_MS, HOLD_MS = 800, 800

def run(fn, order):
    fr = []
    n = int(STEP_MS * FPS / 1000)
    for k in range(len(order)):
        cur, prev = order[k], order[k - 1] if k else order[-1]
        for j in range(n):
            fr.append(fn(cur, prev, j * 1000 / FPS))
    return fr

def gif(path, fr):
    big = [f.resize((W * 2, H * 2), Image.NEAREST) for f in fr]
    big[0].save(path, save_all=True, append_images=big[1:], duration=int(1000 / FPS), loop=0)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stills = {}
    for key, fn, order in (('A', a_frame, A_ORDER), ('B', b_frame, MENU), ('C', c_frame, MENU)):
        fr = run(fn, order)
        gif(OUT / f'{key}.gif', fr)
        rest = [fn(k, k, 5000) for k in ('wheel', 'now', 'settings')]
        rest[0].save(OUT / f'{key}.png')
        rest[0].resize((W * 2, H * 2), Image.NEAREST).save(OUT / f'{key}@2x.png')
        stills[key] = rest
        print(key, len(fr), 'frames')
    g = 10
    sheet = Image.new('RGB', (3 * W + 4 * g, 3 * H + 4 * g), (0xc8, 0xc8, 0xc4))
    for r, key in enumerate('ABC'):
        for c, im in enumerate(stills[key]):
            sheet.paste(im, (g + c * (W + g), g + r * (H + g)))
    sheet.save(OUT / 'sheet.png')
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(OUT / 'sheet@2x.png')

if __name__ == '__main__':
    main()
