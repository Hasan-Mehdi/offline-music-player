"""Mockups of Coda on the HiFi Walker H2 (320x240 RGB565), record-shop-poster direction.

Design reference for the native Rockbox app (docs/H2_APP_PLAN.md) -- the C renderer in
firmware/ui must match these. Run: .venv/Scripts/python firmware/tools/mock_h2.py

Renders each screen 4x supersampled then downsamples (what an AA renderer on the device
would produce), saves 1x PNGs + 2x previews + sheets composited onto the Rockbox sim skin.
Real data: library.db plays/tracks + embedded covers.
"""
import base64, io, math, sqlite3, sys, collections
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
import mutagen
from mutagen.flac import Picture

from pathlib import Path
ROOT = Path(__file__).resolve().parents[2].as_posix()
FD, OUT = ROOT + '/firmware/assets/fonts/', ROOT + '/docs/h2/'
# Rockbox simulator skin for the Eros Q / H2 (GPL, not committed): fetched on first run
SKIN_PATH = ROOT + '/data/h2_sim_skin.bmp'
SKIN_URL = 'https://raw.githubusercontent.com/Rockbox/rockbox/master/uisimulator/bitmaps/UI-aigoerosq.bmp'
SS, W, H = 4, 320, 240

PAPER, INK, BLUE, RED = (0xf4, 0xf4, 0xf0), (0x14, 0x14, 0x14), (0x00, 0x2f, 0xa7), (0xe0, 0x30, 0x1e)
SUB, RULE, WASH = (0x6d, 0x6d, 0x66), (0xd9, 0xd8, 0xd0), (0xea, 0xea, 0xe3)
SUB_DK = (0x93, 0x93, 0x8b)

def P(v): return int(round(v * SS))

# ---------------------------------------------------------------- fonts
_cmaps = {n: set(TTFont(FD + n, lazy=True).getBestCmap()) for n in
          ('ArchivoBlack-Regular.ttf', 'Archivo.ttf', 'Inconsolata.ttf', 'NotoSansJP.ttf')}
_fcache = {}
def _font(name, px, wght=None):
    key = (name, px, wght)
    if key not in _fcache:
        f = ImageFont.truetype(FD + name, P(px))
        if wght is not None:
            axes = [wght, 100] if name in ('Archivo.ttf', 'Inconsolata.ttf') else [wght]
            f.set_variation_by_axes(axes)
        _fcache[key] = f
    return _fcache[key]

ROLES = {   # role -> (latin font, wght, CJK fallback wght)
    'poster': ('ArchivoBlack-Regular.ttf', None, 900),
    'bold':   ('Archivo.ttf', 700, 700),
    'semi':   ('Archivo.ttf', 600, 600),
    'body':   ('Archivo.ttf', 450, 500),
    'mono':   ('Inconsolata.ttf', 500, 500),
}
def runs(text, role, px):
    name, w, cjkw = ROLES[role]
    out, cur, curf = [], '', None
    for ch in text:
        f = _font(name, px, w) if ord(ch) in _cmaps[name] or ch == ' ' else _font('NotoSansJP.ttf', px, cjkw)
        if f is not curf and cur:
            out.append((cur, curf)); cur = ''
        cur += ch; curf = f
    if cur: out.append((cur, curf))
    return out

def text_w(text, role, px, track=0.0):
    return sum(f.getlength(t) for t, f in runs(text, role, px)) / SS + track * len(text)

def draw_text(d, x, y_base, text, role, px, fill, track=0.0):
    """Draw at baseline y_base (device px). Returns advance width."""
    cx = P(x)
    for t, f in runs(text, role, px):
        if track:
            for ch in t:
                d.text((cx, P(y_base)), ch, font=f, fill=fill, anchor='ls')
                cx += f.getlength(ch) + P(track)
        else:
            d.text((cx, P(y_base)), t, font=f, fill=fill, anchor='ls')
            cx += f.getlength(t)
    return cx / SS - x

def fit(text, role, px, max_w, track=0.0):
    if text_w(text, role, px, track) <= max_w: return text
    while text and text_w(text + '…', role, px, track) > max_w: text = text[:-1]
    return text.rstrip() + '…'

def wrap(text, role, px, max_w, max_lines, track=0.0):
    words, lines, cur = text.split(), [], ''
    for i, w in enumerate(words):
        t = (cur + ' ' + w).strip()
        if text_w(t, role, px, track) <= max_w: cur = t; continue
        if cur: lines.append(cur)
        cur = w
        if len(lines) == max_lines - 1:
            cur = ' '.join(words[i:]); break
    lines.append(cur)
    lines = lines[:max_lines]
    lines[-1] = fit(lines[-1], role, px, max_w, track)
    return lines

# ---------------------------------------------------------------- data
db = sqlite3.connect(ROOT + '/data/library.db')
db.row_factory = sqlite3.Row
top = db.execute("""select t.video_id, t.title, t.artist, t.duration, t.path, count(*) n from plays p
    join tracks t on t.video_id=p.video_id where p.event in ('play','complete')
    group by t.video_id order by n desc, max(p.ts) desc limit 24""").fetchall()

_covers = {}
def cover(path, size):
    if path not in _covers:
        im = None
        try:
            f = mutagen.File(path)
            for b in (f.tags or {}).get('metadata_block_picture', []):
                im = Image.open(io.BytesIO(Picture(base64.b64decode(b)).data)).convert('RGB'); break
        except Exception as e:
            print('cover fail', path, e)
        if im is None: im = Image.new('RGB', (64, 64), WASH)
        w, h = im.size; s = min(w, h)
        _covers[path] = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    return _covers[path].resize((size, size), Image.LANCZOS)

def clean(t):
    return (t or '').replace('_', ' ')

# ---------------------------------------------------------------- primitives
def canvas(bg=PAPER):
    im = Image.new('RGB', (W * SS, H * SS), bg)
    return im, ImageDraw.Draw(im)

def finish(im, name):
    small = im.resize((W, H), Image.LANCZOS)
    small.save(OUT + name + '.png')
    small.resize((W * 2, H * 2), Image.NEAREST).save(OUT + name + '@2x.png')
    return small

def pt(cx, cy, r, a):
    return (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))

def wedge_poly(cx, cy, r1, r2, a0, a1, step=0.5):
    n = max(2, int((a1 - a0) / step))
    outer = [pt(cx, cy, r2, a0 + (a1 - a0) * i / n) for i in range(n + 1)]
    inner = [pt(cx, cy, r1, a1 - (a1 - a0) * i / n) for i in range(n + 1)]
    return [(P(x), P(y)) for x, y in outer + inner]

def circle(d, cx, cy, r, fill=None, outline=None, width=0):
    d.ellipse([P(cx - r), P(cy - r), P(cx + r), P(cy + r)], fill=fill, outline=outline,
              width=P(width) if width else 0)

def hsl(h, s, l):
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h / 360, l, s)
    return (int(r * 255), int(g * 255), int(b * 255))

SPECTRUM = [0.95, 0.85, 0.9, 0.7, 0.62, 0.55, 0.6, 0.48, 0.4, 0.44, 0.33, 0.28]

# ---------------------------------------------------------------- the wheel
def wheel(im, d, cx, cy, R1, R2, base, pool, s, playing=True, reel=None):
    k = R2 / 300.0
    HALF, SLICE = 13.6, 30
    MID, ART = (R1 + R2) / 2, R2 - R1 + 24 * k
    n, b0 = len(pool), round(s)
    frac = s - b0
    for dd in range(-5, 6):
        idx = (b0 + dd) % n
        ang = base + (dd - frac) * SLICE
        poly = wedge_poly(cx, cy, R1, R2, ang - HALF, ang + HALF)
        d.polygon(poly, fill=WASH)
        # art rides the wedge, upright when it's at the pointer
        a = cover(pool[idx]['path'], P(ART)).rotate(-(ang - base), resample=Image.BICUBIC, expand=True)
        ax, ay = pt(cx, cy, MID, ang)
        layer = Image.new('RGB', im.size, WASH)
        layer.paste(a, (P(ax) - a.width // 2, P(ay) - a.height // 2))
        mask = Image.new('L', im.size, 0)
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        im.paste(layer, (0, 0), mask)
        focused = dd == 0
        if not focused:
            op = min(0.75, 0.28 + abs(ang - base) / 160)
            shade = Image.new('RGB', im.size, PAPER)
            im.paste(shade, (0, 0), mask.point(lambda v: int(v * op)))
        d.polygon(poly, outline=PAPER, width=max(SS, P(5 * k * 0.5)))
        if focused:
            d.polygon(poly, outline=BLUE, width=max(P(1.5), P(4 * k)))
    # pointer: solid ink die-cut triangle reading outward
    t0, t1, hw = R2 + 8 * k, R2 + 30 * k, 14 * k
    ca, sa = math.cos(math.radians(base)), math.sin(math.radians(base))
    tri = [(cx + t0 * ca - hw * sa, cy + t0 * sa + hw * ca), (cx + t1 * ca, cy + t1 * sa),
           (cx + t0 * ca + hw * sa, cy + t0 * sa - hw * ca)]
    d.polygon([(P(x), P(y)) for x, y in tri], fill=INK)
    # hub: black vinyl silhouette + RGB ink sunburst + record label
    hub_r, REC, VIZ0, BAR = R1 * 116 / 128, R1 * 58 / 128, R1 * 68 / 128, R1 * 27 / 128
    circle(d, cx, cy, hub_r, fill=INK)
    vals = SPECTRUM + SPECTRUM[::-1]
    for i in range(24):
        a = -90 + i * 15
        b = vals[i] if playing else 0.08
        x1, y1 = pt(cx, cy, VIZ0, a); x2, y2 = pt(cx, cy, VIZ0 + 2.5 * k + b * BAR, a)
        d.line([P(x1), P(y1), P(x2), P(y2)], fill=hsl(i * 15, 0.78, 0.58), width=max(SS, P(2.6 * R1 / 128)))
    lab = cover(pool[b0 % n]['path'], P(REC * 2))
    m = Image.new('L', lab.size, 0); ImageDraw.Draw(m).ellipse([0, 0, lab.width - 1, lab.height - 1], fill=255)
    im.paste(lab, (P(cx - REC), P(cy - REC)), m)
    circle(d, cx, cy, REC, outline=RED if playing else PAPER, width=max(1.0, 3 * R1 / 128))
    circle(d, cx, cy, 7.5 * R1 / 128, fill=INK, outline=PAPER, width=max(0.6, 2 * R1 / 128))
    circle(d, cx, cy, 2.4 * R1 / 128, fill=PAPER)

def status(d, x_right, y_base, fill=SUB):
    s = '21:42  87%'
    draw_text(d, x_right - text_w(s, 'mono', 10), y_base, s, 'mono', 10, fill)

def name_reel(d, x0, x1, cy, pool, s, row=40):
    n, b0 = len(pool), round(s)
    for dd in (-2, -1, 1, 2):
        t = pool[(b0 + dd) % n]
        y = cy + dd * row
        op = max(0.0, 1 - abs(dd) / 2.8)
        col = tuple(int(c * op + p * (1 - op)) for c, p in zip(SUB, PAPER))
        draw_text(d, x0 + 4, y + 1, fit(clean(t['title']), 'bold', 11, x1 - x0 - 4), 'bold', 11, col)
        draw_text(d, x0 + 4, y + 13, fit(t['artist'], 'body', 9.5, x1 - x0 - 4), 'body', 9.5, col)
    t = pool[b0 % n]
    lines = wrap(clean(t['title']).upper(), 'poster', 14.5, x1 - x0 - 10, 2, track=-0.35)
    y = cy - (len(lines) - 1) * 7 + 5
    for i, ln in enumerate(lines):
        draw_text(d, x0 + 10, y + i * 14, ln, 'poster', 14.5, INK, track=-0.35)
    draw_text(d, x0 + 10, y + (len(lines) - 1) * 14 + 13, fit(t['artist'], 'semi', 11, x1 - x0 - 10), 'semi', 11, BLUE)

def screen_wheel_a(pool):
    im, d = canvas()
    wheel(im, d, 104, 120, 41, 100, 0, pool, 0)
    name_reel(d, 214, 316, 120, pool, 0)
    status(d, 316, 12)
    draw_text(d, 216, 233, '● playing', 'mono', 10, RED)
    draw_text(d, 316 - text_w('1/24', 'mono', 10), 233, '1/24', 'mono', 10, SUB)
    return finish(im, 'wheel_a')

def screen_wheel_b(pool):
    im, d = canvas()
    wheel(im, d, 160, 232, 70, 158, -90, pool, 0)
    t = pool[0]
    title = fit(clean(t['title']).upper(), 'poster', 19, 300, track=-0.45)
    draw_text(d, 160 - text_w(title, 'poster', 19, -0.45) / 2, 24, title, 'poster', 19, INK, track=-0.45)
    a = fit(t['artist'], 'semi', 12, 280)
    draw_text(d, 160 - text_w(a, 'semi', 12) / 2, 41, a, 'semi', 12, BLUE)
    status(d, 316, 12)
    draw_text(d, 4, 12, '01/24', 'mono', 10, SUB)
    return finish(im, 'wheel_b')

def nowbar(d, im, t, nxt=None, frac=0.37, y0=212):
    h = H - y0
    d.rectangle([0, P(y0), P(W), P(H)], fill=INK)
    im.paste(cover(t['path'], P(h)), (0, P(y0)))
    d.rectangle([0, P(y0), P(W * frac), P(y0 + 1.5)], fill=RED)
    d.rectangle([P(h + 6), P(y0 + 9), P(h + 11), P(y0 + 14)], fill=RED)
    draw_text(d, h + 15, y0 + 15, fit(clean(t['title']), 'bold', 11, 200), 'bold', 11, PAPER)
    draw_text(d, h + 6, y0 + 25, fit(t['artist'], 'body', 9.5, 210), 'body', 9.5, SUB_DK)
    tm = '1:42'
    draw_text(d, W - 6 - text_w(tm, 'mono', 10), y0 + 15, tm, 'mono', 10, PAPER)

def mmss(sec):
    sec = int(sec or 0); return f'{sec // 60}:{sec % 60:02d}'

def screen_now(pool):
    im, d = canvas()
    t, nxt = pool[0], pool[1]
    A = 168
    im.paste(cover(t['path'], P(A)), (0, 0))
    x0, x1 = A + 10, W - 8
    d.rectangle([P(x1 - 7), P(10), P(x1), P(17)], fill=RED)     # printer's mark: live
    lines = wrap(clean(t['title']).upper(), 'poster', 17, x1 - x0, 4, track=-0.4)
    y = 40
    for i, ln in enumerate(lines):
        draw_text(d, x0, y + i * 17, ln, 'poster', 17, INK, track=-0.4)
    y += (len(lines) - 1) * 17 + 17
    draw_text(d, x0, y, fit(t['artist'], 'semi', 12, x1 - x0), 'semi', 12, BLUE)
    why = wrap('because you finished azure and keep coming back to Toby Fox', 'body', 10, x1 - x0, 3)
    for i, ln in enumerate(why):
        draw_text(d, x0, y + 20 + i * 12, ln, 'body', 10, SUB)
    # bottom strip
    y0 = A
    d.rectangle([0, P(y0), P(W), P(H)], fill=INK)
    frac = 0.37
    d.rectangle([0, P(y0), P(W * frac), P(y0 + 2)], fill=RED)
    draw_text(d, 8, y0 + 18, mmss(frac * t['duration']), 'mono', 12, PAPER)
    tot = mmss(t['duration'])
    draw_text(d, W - 8 - text_w(tot, 'mono', 12), y0 + 18, tot, 'mono', 12, SUB_DK)
    # next up
    ny = y0 + 28
    im.paste(cover(nxt['path'], P(36)), (P(8), P(ny)))
    draw_text(d, 52, ny + 11, 'next', 'mono', 10, SUB_DK)
    draw_text(d, 52, ny + 24, fit(clean(nxt['title']), 'bold', 11, 250), 'bold', 11, PAPER)
    draw_text(d, 52, ny + 35, fit(nxt['artist'], 'body', 9.5, 250), 'body', 9.5, SUB_DK)
    return finish(im, 'now')

def masthead(d, right):
    w = draw_text(d, 8, 23, 'Coda', 'poster', 21, INK, track=-0.5)
    d.rectangle([P(8 + w + 2), P(17), P(8 + w + 8), P(23)], fill=RED)
    draw_text(d, W - 8 - text_w(right, 'mono', 10), 22, right, 'mono', 10, SUB)
    d.rectangle([0, P(30), P(W), P(30.75)], fill=INK)

def screen_menu(pool):
    im, d = canvas()
    masthead(d, '54,045 tracks')
    items = ['Wheel', 'Now playing', 'Explore', 'Library', 'OST', 'Liked']
    y = 31
    for i, it in enumerate(items):
        foc = i == 3
        if foc: d.rectangle([0, P(y), P(W), P(y + 30)], fill=INK)
        draw_text(d, 8, y + 24, it, 'poster', 22, PAPER if foc else INK, track=-0.6)
        if i == 0:   # current section: blue underline, like the web nav
            wv = text_w(it, 'poster', 22, -0.6)
            d.rectangle([P(8), P(y + 27), P(8 + wv), P(y + 29)], fill=BLUE)
        y += 30
    nowbar(d, im, pool[0])
    return finish(im, 'menu')

def screen_artists(pool):
    im, d = canvas()
    rows = db.execute("select artist, count(*) n, min(path) p from tracks where artist!='' group by lower(artist)").fetchall()
    rows = sorted(rows, key=lambda r: r['artist'].casefold())
    i0 = next(i for i, r in enumerate(rows) if r['artist'].casefold() >= "snail's house") - 2
    draw_text(d, 8, 24, 'Artists', 'poster', 21, INK, track=-0.5)
    cnt = f"{len(rows):,}"
    draw_text(d, W - 8 - text_w(cnt, 'mono', 10), 22, cnt, 'mono', 10, SUB)
    d.rectangle([0, P(30), P(W), P(30.75)], fill=INK)
    y, RH = 31, 30
    for j in range(6):
        r = rows[i0 + j]
        foc = j == 2
        if foc: d.rectangle([0, P(y), P(W), P(y + RH)], fill=INK)
        im.paste(cover(r['p'], P(RH)), (0, P(y)))
        name = fit(r['artist'], 'poster', 14.5, 210, track=-0.3)
        nw = draw_text(d, RH + 8, y + 20, name, 'poster', 14.5, PAPER if foc else INK, track=-0.3)
        c = str(r['n'])
        cw = text_w(c, 'mono', 11)
        # dotted leader
        x = RH + 8 + nw + 5
        while x < W - 10 - cw:
            circle(d, x, y + 18, 0.55, fill=SUB_DK if foc else SUB); x += 3.2
        draw_text(d, W - 6 - cw, y + 20, c, 'mono', 11, PAPER if foc else SUB)
        if not foc: d.rectangle([P(RH), P(y + RH - 0.5), P(W), P(y + RH)], fill=RULE)
        y += RH
    nowbar(d, im, pool[0])
    return finish(im, 'artists')

# ---------------------------------------------------------------- device sheet
import os, urllib.request
if not os.path.exists(SKIN_PATH):
    urllib.request.urlretrieve(SKIN_URL, SKIN_PATH)
SKIN = Image.open(SKIN_PATH).convert('RGBA')
LCD_AT = (40, 62)
def on_device(screen):
    bg = Image.new('RGBA', SKIN.size, (200, 200, 200, 255)); bg.alpha_composite(SKIN)
    bg = bg.convert('RGB'); bg.paste(screen, LCD_AT)
    return bg

def sheet(screens, name, scale=1.25):
    devs = [on_device(s) for s in screens]
    w, h = devs[0].size
    out = Image.new('RGB', (len(devs) * (w + 24) + 24, h + 48), (228, 228, 222))
    for i, dv in enumerate(devs):
        out.paste(dv, (24 + i * (w + 24), 24))
    out.resize((int(out.width * scale), int(out.height * scale)), Image.LANCZOS).save(OUT + name + '.png')

if __name__ == '__main__':
    import os; os.makedirs(OUT, exist_ok=True)
    pool = list(top)
    a, b = screen_wheel_a(pool), screen_wheel_b(pool)
    nw, mn, ar = screen_now(pool), screen_menu(pool), screen_artists(pool)
    sheet([a, b], 'sheet_wheels')
    sheet([nw, mn, ar], 'sheet_screens')
    print('ok', OUT)
