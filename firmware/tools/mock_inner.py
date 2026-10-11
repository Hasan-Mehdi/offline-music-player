"""The screens inside the menu, set in menu A's language (docs/h2/menu, firmware/tools/
mock_menu.py): each section keeps its panel's colour and symbol as a tilted header tab; the
cursor is a tilted slab with a hard shadow that slides with a little overshoot; actions are
buttons with symbols, not list rows; Library and Settings open as panel mosaics like the
menu (the most-used thing biggest). Same rule as the menu: only the device renderer's
primitives (rects, discs, rings, convex polygons), no drawings.

Output: docs/h2/inner/<screen>.png, sheet.png, flow.gif (menu -> Explore -> a shelf ->
the track sheet) and lists.gif (the cursor through a track page)
  .venv/Scripts/python firmware/tools/mock_inner.py
"""
import math, sqlite3, sys
from pathlib import Path
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_menu as M
from mock_menu import (W, H, SS, FPS, PAPER, INK, BLUE, RED, SUB, RULE, STRIP_SUB, BAR_Y, POSTER,
                       BODY, MONO, Pen, font, tw, fit, wrap, clamp01, seg, ease_out, ease_back, mix,
                       canvas, down, nowbar, battery, sk, K)

ROOT = M.ROOT
OUT = ROOT / 'docs' / 'h2' / 'inner'

# ------------------------------------------------------------------ more symbols
def sym(p, kind, cx, cy, s, fg, bg, acc=None, u=1.0):
    acc = acc or fg
    if kind == 'songs':                         # a note
        p.disc(cx - .12 * s, cy + .26 * s, .18 * s, fg)
        p.rect(cx - .03 * s, cy - .42 * s, cx + .06 * s, cy + .26 * s, fg)
        p.poly([(cx + .06 * s, cy - .42 * s), (cx + .36 * s, cy - .18 * s), (cx + .36 * s, cy - .02 * s),
                (cx + .06 * s, cy - .26 * s)], fg)
    elif kind == 'artists':                     # a bust
        p.disc(cx, cy - .2 * s, .2 * s, fg)
        p.d.pieslice([p.X(cx - .38 * s), p.Y(cy + .08 * s), p.X(cx + .38 * s), p.Y(cy + .84 * s)], 180, 360, fill=fg)
    elif kind == 'genres':                      # crates
        q, g = .36 * s, .1 * s
        for i, (dx, dy) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):
            x0, y0 = cx - q - g / 2 + dx * (q + g), cy - q - g / 2 + dy * (q + g)
            p.rect(x0, y0, x0 + q, y0 + q, acc if i == 1 else fg)
    elif kind == 'osts':                        # a d-pad: the soundtracks are mostly games
        p.rect(cx - .45 * s, cy - .15 * s, cx + .45 * s, cy + .15 * s, fg)
        p.rect(cx - .15 * s, cy - .45 * s, cx + .15 * s, cy + .45 * s, fg)
        p.disc(cx, cy, .07 * s, bg)
    elif kind == 'history':                     # rewind
        for x in (.02, .44):
            p.poly([(cx + x * s, cy - .32 * s), (cx + x * s, cy + .32 * s), (cx + (x - .44) * s, cy)], fg)
    elif kind == 'shuffle':
        for a, b in (((-.42, .26), (.2, -.26)), ((-.42, -.26), (.2, .26))):
            p.bar(cx + a[0] * s, cy + a[1] * s, cx + b[0] * s, cy + b[1] * s, .11 * s, fg)
        for y in (-.26, .26):
            p.poly([(cx + .14 * s, cy + (y - .17) * s), (cx + .46 * s, cy + y * s), (cx + .14 * s, cy + (y + .17) * s)], fg)
    elif kind == 'station':                     # broadcast
        ox = cx - .32 * s
        p.disc(ox, cy, .11 * s, fg)
        for r in (.32, .56):
            ro = r * s + .05 * s
            p.d.arc([p.X(ox - ro), p.Y(cy - ro), p.X(ox + ro), p.Y(cy + ro)], -48, 48, fill=fg,
                    width=max(1, int(round(.1 * s * SS))))
    elif kind == 'sound':                       # three faders
        for x, k in ((-.3, .15), (0, -.22), (.3, .05)):
            p.rect(cx + (x - .035) * s, cy - .42 * s, cx + (x + .035) * s, cy + .42 * s, fg)
            p.disc(cx + x * s, cy + k * s, .13 * s, fg)
    elif kind == 'screen':                      # the sun
        p.disc(cx, cy, .2 * s, fg)
        for k in range(8):
            a = k * math.pi / 4
            p.bar(cx + math.cos(a) * .31 * s, cy + math.sin(a) * .31 * s, cx + math.cos(a) * .47 * s,
                  cy + math.sin(a) * .47 * s, .09 * s, fg)
    elif kind == 'sleep':                       # a crescent
        p.disc(cx, cy, .4 * s, fg)
        p.disc(cx + .2 * s, cy - .14 * s, .34 * s, bg)
    elif kind == 'power':
        r, w = .33 * s, .11 * s
        ro = r + w / 2
        p.d.arc([p.X(cx - ro), p.Y(cy + .04 * s - ro), p.X(cx + ro), p.Y(cy + .04 * s + ro)], -55, 235,
                fill=fg, width=max(1, int(round(w * SS))))
        p.rect(cx - .06 * s, cy - .46 * s, cx + .06 * s, cy - .02 * s, fg)
    elif kind == 'bt':
        pts = [(0, 3), (6, 7), (3, 10), (3, 0), (6, 3), (0, 7)]
        q = [(cx + (x - 3) / 11 * s * .95, cy + (y - 5) / 11 * s * .95) for x, y in pts]
        for a, b in zip(q, q[1:]):
            p.bar(a[0], a[1], b[0], b[1], .1 * s, fg)
    elif kind == 'clock':
        p.ring(cx, cy, .4 * s, .1 * s, fg)
        p.bar(cx, cy, cx, cy - .26 * s, .09 * s, fg)
        p.bar(cx, cy, cx + .2 * s, cy, .09 * s, fg)
        p.disc(cx, cy, .07 * s, fg)
    elif kind == 'dislike':
        for a in (1, -1):
            p.bar(cx - .34 * s, cy - .34 * s * a, cx + .34 * s, cy + .34 * s * a, .15 * s, fg)
    elif kind == 'next':                        # play next
        p.poly([(cx - .36 * s, cy - .32 * s), (cx - .36 * s, cy + .32 * s), (cx + .16 * s, cy)], fg)
        p.rect(cx + .2 * s, cy - .32 * s, cx + .34 * s, cy + .32 * s, fg)
    elif kind == 'playback':                    # play, then a loop back round
        p.ring(cx, cy, .38 * s, .1 * s, fg)
        p.poly([(cx - .12 * s, cy - .2 * s), (cx - .12 * s, cy + .2 * s), (cx + .2 * s, cy)], fg)
    else:
        M.sym(p, kind, cx, cy, s, fg, bg, acc, u)


# ------------------------------------------------------------------ real content
def latin(s): return s and all(0x20 <= ord(c) < 0x250 for c in s)

_db = sqlite3.connect(f'file:{ROOT / "data" / "library.db"}?mode=ro', uri=True)
_art = {}
def art(path, px):
    k = (path, px)
    if k not in _art:
        _art[k] = M.cover_of(path, px) or Image.new('RGB', (px * SS, px * SS), (0xea, 0xea, 0xe3))
    return _art[k]

def tracks(n, skip=0, where='1'):
    out, seen = [], set()
    for title, artist, path, dur in _db.execute(f"""select t.title, t.artist, t.path, t.duration
            from plays p join tracks t on t.video_id = p.video_id where {where}
            order by p.ts desc limit 3000"""):
        if path in seen or not latin(title) or not latin(artist) or len(title) > 70:
            continue
        seen.add(path)
        if M.cover_of(path, 4) is None:
            continue
        if skip:
            skip -= 1
            continue
        out.append((title, artist, path, dur or 180))
        if len(out) == n:
            break
    return out

def mmss(s): s = int(s); return f'{s // 60}:{s % 60:02d}'

TR = tracks(26)

# ------------------------------------------------------------------ shared pieces
SEC = {  # the menu panel's colours: bg, fg, outlined, accent
    'wheel': (INK, PAPER, False, RED), 'now': (RED, PAPER, False, None),
    'explore': (BLUE, PAPER, False, INK), 'library': (PAPER, INK, True, BLUE),
    'queue': (PAPER, INK, True, RED), 'search': (INK, PAPER, False, None),
    'liked': (BLUE, PAPER, False, None), 'settings': (PAPER, INK, True, None)}

def header_pts(x1, grow=1.0):
    ln = 6
    return [(-8 + ln, 0), (x1 + ln, 0), (x1, 30), (-8, 30)]

def header(p, sec, title, symk=None, right=None, u=1.0):
    bg, fg, outl, acc = SEC[sec]
    f = font(POSTER, 18)
    title = fit(title, f, 190, -.9)
    x1 = 33 + tw(title, f, -.9) + 11
    p.rect(0, 29, W, 31, INK)
    pts = header_pts(x1)
    p.poly(pts, bg)
    if outl:
        p.poly(pts, None, INK, 2)
    sym(p, symk or sec, 17, 15, 18, fg, bg, acc, u)
    p.text(31, 23, title, f, fg, track=-.9)
    battery(p, W - 8, 20)
    if right:
        fm = font(MONO, 10)
        p.text(W - 8 - 19 - 6 - tw('87%', fm) - 10 - tw(right, fm), 20, right, fm, SUB)
    return x1

def slab_pts(y0, h, x0=3, x1=W - 3, ln=None):
    ln = h * K if ln is None else ln
    return [(x0 + ln, y0), (x1, y0), (x1 - ln, y0 + h), (x0, y0 + h)]

def slab(p, y0, h, c, shadow=None, x0=3, x1=W - 3, ln=None, sh=(4, 3)):
    pts = slab_pts(y0, h, x0, x1, ln)
    if shadow:
        p.poly([(x + sh[0], y + sh[1]) for x, y in pts], shadow)
    p.poly(pts, c)
    return pts

def button(p, x0, y0, x1, h, label, symk, bg, fg, focus=0.0, outline=False, f=None, s=None, acc=None):
    """a tilted button: symbol + label; focus 0..1 pops it (blue, hard shadow)"""
    f = f or font(POSTER, 15)
    if focus > 0:
        bg, fg = BLUE, PAPER
        pts = slab(p, y0, h, bg, INK, x0, x1, sh=(4 * focus, 3 * focus))
    else:
        pts = slab(p, y0, h, bg, None, x0, x1)
        if outline:
            p.poly(pts, None, INK, 2)
    s = s or h * .56
    sym(p, symk, x0 + h * K / 2 + 8 + s / 2, y0 + h / 2, s, fg, bg, acc)
    p.text(x0 + h * K / 2 + 16 + s, y0 + h / 2 + 5, label, f, fg, track=-.5)

def track_row(p, y, t, foc=False, live=False, note=None, num=None, dim=False, shadow=BLUE):
    title, artist, path, dur = t
    if live:
        slab(p, y, 30, RED)
    elif foc:
        slab(p, y, 30, INK, shadow)
    else:
        p.rect(0, y + 29, W, y + 30, RULE)
    on = live or foc
    fg, sub = (PAPER, mix(PAPER, RED if live else INK, .35)) if on else ((SUB if dim else INK), SUB)
    x = 12
    if num is not None:
        fn = font(POSTER, 15)
        p.text(10, y + 21, f'{num:02d}', fn, PAPER if on else (RULE if dim else INK), track=-.6)
        x = 38
    p.paste(art(path, 28), x, y + 1)
    tx = x + 34
    right = note if note is not None else mmss(dur)
    fm = font(MONO, 10)
    rw = tw(right, fm) if right else 0
    fb = font(BODY, 11, 'Bold')
    p.text(tx, y + 13, fit(title, fb, W - tx - rw - 18), fb, fg)
    p.text(tx, y + 25, fit(artist, font(BODY, 10), W - tx - rw - 18), font(BODY, 10), sub)
    if right:
        p.text(W - 12 - rw, y + 13, right, fm, PAPER if on else (BLUE if note else SUB))

def panel(im, cell, bg, fg, outlined, draw, pop=0.0, sc=1.06):
    """a menu-A panel: unskewed cell, content drawn by draw(pen); pop 0..1 = focused"""
    x0, y0, x1, y1 = cell
    pts = [sk(x0, y0), sk(x1, y0), sk(x1, y1), sk(x0, y1)]
    bx0 = int(math.floor(min(x for x, _ in pts) * SS)) - 2
    by0 = int(math.floor(min(y for _, y in pts) * SS)) - 2
    bx1 = int(math.ceil(max(x for x, _ in pts) * SS)) + 2
    by1 = int(math.ceil(max(y for _, y in pts) * SS)) + 2
    lay = Image.new('RGB', (bx1 - bx0, by1 - by0), bg)
    lp = Pen(lay, bx0, by0)
    draw(lp, lambda y: sk(x0, y)[0] + 6, lambda y: min(sk(x1, y)[0], W))
    mask = Image.new('L', lay.size, 0)
    mp = [(x * SS - bx0, y * SS - by0) for x, y in pts]
    ImageDraw.Draw(mask).polygon(mp, fill=255)
    if outlined:
        ImageDraw.Draw(lay).polygon(mp, outline=INK, width=int(4 * SS))
    s = 1 + (sc - 1) * pop
    if pop > 0:
        cx, cy = (bx0 + lay.size[0] / 2) / SS, (by0 + lay.size[1] / 2) / SS
        spts = [(cx + (x - cx) * s, cy + (y - cy) * s) for x, y in pts]
        o = 5 * min(1.0, pop)
        Pen(im).poly([(x + o, y + o) for x, y in spts], BLUE if bg == INK else INK)
        nw, nh = int(lay.size[0] * s), int(lay.size[1] * s)
        im.paste(lay.resize((nw, nh), Image.LANCZOS), (int(round(cx * SS - nw / 2)), int(round(cy * SS - nh / 2))),
                 mask.resize((nw, nh), Image.BILINEAR))
    else:
        im.paste(lay, (bx0, by0), mask)


# ------------------------------------------------------------------ the screens
def scr_library(focus='songs'):
    im, p = canvas()
    header(p, 'library', 'Library', right='')
    cells = {
        'songs': ((-40, 35, 120, 211), INK, PAPER, False),
        'artists': ((125, 35, 350, 112), BLUE, PAPER, False),
        'genres': ((125, 117, 236, 164), PAPER, INK, True),
        'osts': ((241, 117, 350, 164), INK, PAPER, False),
        'history': ((125, 169, 350, 211), PAPER, INK, True)}
    def songs(lp, lx, rx):
        sym(lp, 'songs', 52, 104, 96, PAPER, INK)
        lp.text(10, 182, '18,388', font(MONO, 10), STRIP_SUB)
        lp.text(9, 203, 'Songs', font(POSTER, 22), PAPER, track=-1.1)
    def artists(lp, lx, rx):
        lp.text(lx(66), 66, 'Artists', font(POSTER, 22), PAPER, track=-1.1)
        lp.text(lx(80), 80, '419 of them, A to Z', font(MONO, 10), mix(PAPER, BLUE, .3))
        sym(lp, 'artists', rx(70) - 34, 72, 44, PAPER, BLUE)
    def small(kind, label, sub_, bg, fg):
        def d(lp, lx, rx):
            fl = font(POSTER, 15) if tw(label, font(POSTER, 15), -.6) < rx(158) - lx(158) - 6 else font(POSTER, 11)
            lp.text(lx(158), 158, label, fl, fg, track=-.6)
            lp.text(lx(140), 140, sub_, font(MONO, 10), SUB if bg == PAPER else STRIP_SUB)
            sym(lp, kind, rx(132) - 20, 132, 22, fg, bg, BLUE if bg == PAPER else RED)
        return d
    def history(lp, lx, rx):
        sym(lp, 'history', lx(190) + 16, 190, 24, INK, PAPER)
        lp.text(lx(196) + 36, 196, 'History', font(POSTER, 15), INK, track=-.6)
        lp.text(lx(196) + 112, 196, '2 min ago', font(MONO, 10), SUB)
    draws = {'songs': songs, 'artists': artists,
             'genres': small('genres', 'Genres', '16', PAPER, INK),
             'osts': small('osts', 'Soundtracks', '5 games', INK, PAPER), 'history': history}
    for k in [k for k in cells if k != focus] + [focus]:
        (cell, bg, fg, outl) = cells[k]
        panel(im, cell, bg, fg, outl, draws[k], pop=1.0 if k == focus else 0, sc=1.035 if k == 'songs' else 1.06)
    nowbar(p)
    return down(im)

def scr_explore(focus=0, cur_y=None, drop=1.0):
    im, p = canvas()
    header(p, 'explore', 'Explore', right='2 shelves')
    shelves = [('Fresh finds', 'unheard, matched to your taste', '24', TR[:9]),
               ('Deep cuts', 'barely played, the model says yes', '31', TR[9:18])]
    for i, (name, sub_, n, items) in enumerate(shelves):
        y0 = 40 + i * 86 - (1 - drop) * 30 * (i + 1)
        foc = i == focus
        ft = font(POSTER, 18)
        if foc:
            slab(p, y0 - 2, 24, BLUE, INK, 3, 20 + tw(name, ft, -.8) + 10)
        p.text(12, y0 + 16, name, ft, PAPER if foc else INK, track=-.8)
        p.text(W - 12 - tw(n, font(MONO, 10)), y0 + 16, n, font(MONO, 10), SUB)
        p.text(12, y0 + 34, sub_, font(BODY, 10), SUB)
        # the covers, butted, cut on the lean like the panels
        ry, rh = y0 + 40, 40
        row = Image.new('RGB', (W * SS, rh * SS), PAPER)
        for k, t in enumerate(items):
            row.paste(art(t[2], 40), (k * 40 * SS - 6 * SS, 0))
        mask = Image.new('L', row.size, 0)
        ln = rh * K
        ImageDraw.Draw(mask).polygon([(ln * SS, 0), (W * SS, 0), ((W - ln) * SS, rh * SS), (0, rh * SS)], fill=255)
        if foc:
            p.poly([(x + 4, y + ry + 3) for x, y in [(ln, 0), (W, 0), (W - ln, rh), (0, rh)]], INK)
        im.paste(row, (0, int(ry * SS)), mask)
    nowbar(p)
    return down(im)

def scr_tracks(focus=0, slab_y=None, sheet=None, drop=1.0):
    """a shelf / genre page: big action buttons, then the songs; focus 0,1 = buttons"""
    im, p = canvas()
    header(p, 'explore', 'Fresh finds', right='24')
    button(p, 4, 37, 164, 28, 'Play all', 'now', INK, PAPER, focus=1.0 if focus == 0 else 0)
    button(p, 170, 37, 316, 28, 'Shuffle', 'shuffle', PAPER, INK, focus=1.0 if focus == 1 else 0, outline=True)
    rows = TR[:6]
    y_cur = slab_y
    for i, t in enumerate(rows):
        y = 72 + i * 30 + (1 - drop) * 12 * (i + 1)
        if y > BAR_Y:
            break
        foc = focus == i + 2 and slab_y is None
        track_row(p, y, t, foc=foc)
    if slab_y is not None:                       # the cursor between rows (animation)
        slab(p, slab_y, 30, INK, BLUE)
        i = int(round((slab_y - 72) / 30))
        if 0 <= i < len(rows):
            track_row(p, slab_y, rows[i], foc=True, shadow=None)
    nowbar(p)
    if sheet is not None:
        draw_sheet(im, p, rows[1], sheet)
    return down(im)

def draw_sheet(im, p, t, u, focus=0):
    """hold Play on a song: the screen goes dim, its buttons come up from the bottom"""
    a = ease_out(seg(u, 0, .4)) * .55
    if a > 0:
        dim = Image.new('RGB', im.size, INK)
        im.paste(Image.blend(im, dim, a))
        p.d = ImageDraw.Draw(im)
    items = [('Play next', 'next'), ('Add to queue', 'queue'), ('Like', 'liked'),
             ('Dislike, skip it', 'dislike'), ('Go to artist', 'artists')]
    for i, (label, k) in enumerate(items):
        e = ease_back(seg(u, .08 * i, .08 * i + .5), 1.9)
        y = 96 + i * 29 + (1 - e) * 160
        x0 = 10 + i * 0
        foc = i == focus and u > .6
        if foc:
            slab(p, y, 25, BLUE, INK, x0, x0 + 220)
        else:
            slab(p, y, 25, PAPER, None, x0, x0 + 220)
        sym(p, k, x0 + 22, y + 12.5, 15, PAPER if foc else INK, BLUE if foc else PAPER,
            RED if k == 'queue' else None)
        p.text(x0 + 38, y + 18, label, font(POSTER, 15), PAPER if foc else INK, track=-.6)
    e = ease_back(seg(u, 0, .45), 1.6)
    ty = 52 - (1 - e) * 70
    title, artist, path, dur = t
    pts = slab(p, ty, 38, INK, None, 6, 300)
    p.paste(art(path, 30), 18, ty + 4)
    fb = font(BODY, 11, 'Bold')
    p.text(56, ty + 16, fit(title, fb, 230), fb, PAPER)
    p.text(56, ty + 30, fit(artist, font(BODY, 10), 230), font(BODY, 10), STRIP_SUB)

def scr_now():
    im, p = canvas()
    title, artist, path, dur = TR[0]
    A = 168
    cv = art(path, A)
    m = Image.new('L', cv.size, 0)
    ImageDraw.Draw(m).polygon([(0, 0), ((A + 8) * SS, 0), ((A - 8) * SS, A * SS), (0, A * SS)], fill=255)
    im.paste(cv, (0, 0), m)
    x0 = A + 4
    slab(p, 9, 17, RED, None, x0, x0 + 76)
    sym(p, 'now', x0 + 14, 17.5, 10, PAPER, RED)
    p.text(x0 + 24, 22, 'playing', font(POSTER, 11), PAPER, track=-.3)
    battery(p, W - 8, 21)
    fp = font(POSTER, 18)
    lines = wrap(title.upper(), fp, W - 8 - x0 - 6, 4)
    y = 48
    for i, line in enumerate(lines):
        p.text(x0 + 6 - i * 2, y + i * 18, line, fp, INK, track=-1)
    y += (len(lines) - 1) * 18 + 17
    p.text(x0 + 6, y, fit(artist, font(BODY, 12, 'SemiBold'), W - x0 - 14), font(BODY, 12, 'SemiBold'), BLUE)
    for i, line in enumerate(wrap("sounds like what's playing, fits this session's mood", font(BODY, 10), W - x0 - 14, 3)):
        p.text(x0 + 6, y + 20 + i * 12, line, font(BODY, 10), SUB)
    # the strip: a chunky slanted progress slab, the time big, what's next on a card
    p.rect(0, A, W, H, INK)
    prog = .31
    p.poly([(-10, A), (W * prog + 4, A), (W * prog - 4, A + 8), (-10, A + 8)], RED)
    p.text(10, A + 35, '0:41', font(POSTER, 22), PAPER, track=-1.1)
    p.text(64, A + 34, '/ ' + mmss(dur), font(MONO, 10), STRIP_SUB)
    nt = TR[1]
    slab(p, A + 44, 24, mix(INK, PAPER, .12), None, 6, W - 6)
    p.paste(art(nt[2], 20), 14, A + 46)
    p.text(40, A + 55, 'next, autoplay', font(MONO, 10), STRIP_SUB)
    fb = font(BODY, 11, 'Bold')
    p.text(40, A + 66, fit(nt[0], fb, 250), fb, PAPER)
    return down(im)

def scr_queue():
    im, p = canvas()
    header(p, 'queue', 'Queue', right='3 of 24')
    for i, t in enumerate(TR[2:8]):
        y = 31 + i * 30
        n = i + 1
        live, foc, dim = n == 3, n == 5, n < 3
        note = 'playing' if live else ('autoplay' if n > 3 else '')
        track_row(p, y, t, foc=foc, live=live, num=n, dim=dim, note=note)
    nowbar(p)
    return down(im)

def scr_search():
    im, p = canvas()
    header(p, 'search', 'Search', right='12 found')
    fq = font(POSTER, 22)
    x = p.text(12, 60, 'TOBY', fq, INK, track=-1.2)
    p.rect(x + 3, 38, x + 6, 62, RED)
    keys = ['x', 'y', 'z', 'sp', 'del', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
    for i, k in enumerate(keys):
        kx, ky, kw, kh = 6 + i * 24, 70, 21, 24
        foc = k == 'B'
        if foc:
            slab(p, ky + 2, kh, BLUE, INK, kx + 2, kx + 2 + kw, ln=4, sh=(0, 0))
        else:
            slab(p, ky, kh, PAPER, INK, kx, kx + kw, ln=4, sh=(2, 2))
            p.poly(slab_pts(ky, kh, kx, kx + kw, 4), None, INK, 1.5)
        c = PAPER if foc else (INK if k not in 'xyz' else SUB)
        o = 2 if foc else 0
        if k == 'sp':
            p.rect(kx + 6 + o, ky + 15 + o, kx + 16 + o, ky + 18 + o, c)
        elif k == 'del':
            p.poly([(kx + 5 + o, ky + 12 + o), (kx + 11 + o, ky + 7 + o), (kx + 11 + o, ky + 17 + o)], c)
            p.rect(kx + 11 + o, ky + 10 + o, kx + 17 + o, ky + 14 + o, c)
        else:
            f = font(POSTER, 15)
            p.text(kx + 2 + (kw - tw(k, f)) / 2 + o, ky + 17 + o, k, f, c)
    # results: the artist first, then songs
    y = 102
    slab(p, y, 30, INK, BLUE)
    p.disc(26, y + 15, 12, BLUE)
    sym(p, 'artists', 26, y + 16, 15, PAPER, BLUE)
    p.text(46, y + 21, '40Nix', font(POSTER, 15), PAPER, track=-.6)
    p.text(W - 12 - tw('artist, 11 songs', font(MONO, 10)), y + 20, 'artist, 11 songs', font(MONO, 10), STRIP_SUB)
    for i, t in enumerate(TR[10:13]):
        track_row(p, y + 33 + i * 30, t)
    nowbar(p)
    return down(im)

def scr_settings(focus='sleep'):
    im, p = canvas()
    header(p, 'settings', 'Settings')
    cells = {
        'sleep': ((-40, 35, 128, 120), BLUE, PAPER, False, 'Sleep', 'off', 'sleep'),
        'sound': ((133, 35, 350, 120), INK, PAPER, False, 'Sound', 'limit -34 dB, flat', 'sound'),
        'screen': ((-40, 125, 92, 168), PAPER, INK, True, 'Screen', '27%, 30 s', 'screen'),
        'power': ((97, 125, 206, 168), INK, PAPER, False, 'Power', 'idle 10 min', 'power'),
        'wheel': ((211, 125, 350, 168), PAPER, INK, True, 'Wheel', 'A, clicks, peek', 'wheel'),
        'playback': ((-40, 173, 120, 211), BLUE, PAPER, False, 'Playback', 'autoplay on', 'playback'),
        'bt': ((125, 173, 236, 211), INK, PAPER, False, 'Bluetooth', 'WH-1000XM4', 'bt'),
        'clock': ((241, 173, 350, 211), PAPER, INK, True, 'Clock', '12:41', 'clock')}
    def draw_for(k):
        cell, bg, fg, outl, label, val, sk_ = cells[k]
        x0, y0, x1, y1 = cell
        big = y1 - y0 > 60
        subc = mix(fg, bg, .4)
        def d(lp, lx, rx):
            if big:
                lp.text(max(lx(y1 - 12), 10), y1 - 12, label, font(POSTER, 22), fg, track=-1.1)
                lp.text(max(lx(y1 - 36), 10) + 1, y1 - 36, val, font(MONO, 10), subc)
                sym(lp, sk_, rx(y0 + 30) - 30, y0 + 30, 34, fg, bg, RED if sk_ == 'wheel' else None)
            else:
                fl = font(POSTER, 15)
                if tw(label, fl, -.6) > rx(y1 - 8) - lx(y1 - 8) - 4:
                    fl = font(POSTER, 11)
                m = 3 if outl else 0
                lp.text(max(lx(y1 - 8), 9) + m, y1 - 8, label, fl, fg, track=-.6)
                lp.text(max(lx(y1 - 25), 9) + m, y1 - 25, val, font(MONO, 10), subc)
                sym(lp, sk_, rx(y0 + 13) - 16, y0 + 14, 18, fg, bg, RED if sk_ == 'wheel' else None)
        return d
    for k in [k for k in cells if k != focus] + [focus]:
        cell, bg, fg, outl = cells[k][:4]
        panel(im, cell, bg, fg, outl, draw_for(k), pop=1.0 if k == focus else 0)
    nowbar(p)
    return down(im)

def scr_settings_sound():
    im, p = canvas()
    header(p, 'settings', 'Sound', symk='sound', right='turn, then Play')
    rows = [('Volume limit', '-34 dB'), ('Bass', 'flat'), ('Treble', '+2 dB'), ('Headphones out', 'pause')]
    for i, (label, val) in enumerate(rows):
        y = 31 + i * 30
        foc = i == 0
        if foc:
            slab(p, y, 30, BLUE, INK)
            p.text(12, y + 21, label, font(POSTER, 15), PAPER, track=-.6)
            v = f'< {val} >'
            p.text(W - 14 - tw(v, font(MONO, 10)), y + 20, v, font(MONO, 10), PAPER)
        else:
            p.rect(0, y + 29, W, y + 30, RULE)
            p.text(12, y + 21, label, font(POSTER, 15), INK, track=-.6)
            p.text(W - 14 - tw(val, font(MONO, 10)), y + 20, val, font(MONO, 10), BLUE)
    fb = font(BODY, 10)
    for i, line in enumerate(wrap("The volume buttons stop here, to protect your ears. None allows the player's full volume.", fb, W - 16, 2)):
        p.text(8, 175 + i * 12, line, fb, SUB)
    nowbar(p)
    return down(im)


# ------------------------------------------------------------------ motion
def morph(a, b, e):
    return [(xa + (xb - xa) * e, ya + (yb - ya) * e) for (xa, ya), (xb, yb) in zip(a, b)]

def flow():
    """menu (Explore focused) -> Play: the blue panel becomes Explore's header tab and the
    shelves drop in -> down to Deep cuts -> back up, Play -> the shelf's page"""
    fr = []
    n = lambda ms: int(ms * FPS / 1000)
    for j in range(n(700)):
        fr.append(M.a_frame('explore', 'now', j * 1000 / FPS + 300))
    menu = M.a_frame('explore', 'explore', 5000)
    ex = scr_explore()
    (x0, y0, x1, y1) = M.A_SPEC['explore'][0]
    src = [sk(x0, y0), sk(x1, y0), sk(x1, y1), sk(x0, y1)]
    f18 = font(POSTER, 18)
    dst = header_pts(33 + tw('Explore', f18, -.9) + 11)
    for j in range(n(420)):
        t = j * 1000 / FPS
        e = ease_back(seg(t, 0, 240), 1.2)
        im = Image.new('RGB', (W * SS, H * SS), PAPER)
        base = Image.blend(menu, Image.new('RGB', (W, H), PAPER), ease_out(seg(t, 0, 120)))
        im.paste(base.resize((W * SS, H * SS), Image.NEAREST))
        if t > 80:                                     # the page underneath, dropping in
            pg = scr_explore(drop=ease_back(seg(t, 80, 380), 1.6)).resize((W * SS, H * SS), Image.LANCZOS)
            msk = Image.new('L', pg.size, int(255 * ease_out(seg(t, 80, 200))))
            im.paste(pg, (0, 0), msk)
        p = Pen(im)
        if t < 260:
            p.poly(morph(src, dst, e), BLUE)
        fr.append(down(im))
    for j in range(n(500)):
        fr.append(ex)
    for j in range(n(260)):                            # down a shelf
        t = j * 1000 / FPS
        fr.append(scr_explore(focus=1 if t > 60 else 0))
    for j in range(n(500)):
        fr.append(scr_explore(focus=1))
    for j in range(n(400)):
        fr.append(scr_explore(focus=0))
    for j in range(n(360)):                            # Play: the shelf's page
        t = j * 1000 / FPS
        fr.append(scr_tracks(focus=0, drop=ease_back(seg(t, 0, 300), 1.6)))
    return fr

def lists():
    """the cursor down a page: Play all -> Shuffle -> songs (the slab slides, overshooting a
    hair), then hold Play: the sheet comes up"""
    fr = []
    n = lambda ms: int(ms * FPS / 1000)
    for j in range(n(500)):
        fr.append(scr_tracks(focus=0))
    for j in range(n(450)):
        fr.append(scr_tracks(focus=1))
    ys = [72, 102, 132]
    prev = None
    for k, y in enumerate(ys):
        for j in range(n(420)):
            t = j * 1000 / FPS
            if prev is None:
                fr.append(scr_tracks(focus=2) if t > 40 else scr_tracks(focus=1))
                continue
            e = ease_back(seg(t, 0, 150), 2.2)
            fr.append(scr_tracks(focus=k + 2, slab_y=prev + (y - prev) * e))
        prev = y
    for j in range(n(900)):
        t = j * 1000 / FPS
        fr.append(scr_tracks(focus=3, sheet=clamp01(t / 700)))
    for j in range(n(700)):
        fr.append(scr_tracks(focus=3, sheet=1.0))
    return fr

def gif(path, fr):
    big = [f.resize((W * 2, H * 2), Image.NEAREST) for f in fr]
    big[0].save(path, save_all=True, append_images=big[1:], duration=int(1000 / FPS), loop=0)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    shots = {
        'library': scr_library(), 'explore': scr_explore(), 'tracks': scr_tracks(focus=2),
        'sheet': scr_tracks(focus=3, sheet=1.0), 'now': scr_now(), 'queue': scr_queue(),
        'search': scr_search(), 'settings': scr_settings(), 'settings_sound': scr_settings_sound()}
    for k, im in shots.items():
        im.save(OUT / f'{k}.png')
        im.resize((W * 2, H * 2), Image.NEAREST).save(OUT / f'{k}@2x.png')
    order = ['library', 'explore', 'tracks', 'sheet', 'now', 'queue', 'search', 'settings', 'settings_sound']
    g, cols = 10, 3
    sheet = Image.new('RGB', (cols * (W + g) + g, 3 * (H + g) + g), (0xc8, 0xc8, 0xc4))
    for i, k in enumerate(order):
        sheet.paste(shots[k], (g + (i % cols) * (W + g), g + (i // cols) * (H + g)))
    sheet.save(OUT / 'sheet.png')
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(OUT / 'sheet@2x.png')
    if '--still' not in sys.argv:
        gif(OUT / 'flow.gif', flow())
        gif(OUT / 'lists.gif', lists())
    print('ok', OUT)

if __name__ == '__main__':
    main()
