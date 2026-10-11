"""Boot + power-off animation mockups for Coda OS, round 2 (the turntable drawing of round 1
read as clip art). Three directions inside the record-shop poster language, each a boot
(1.6 s, plays while the library loads) and a power-off (~0.9 s, replaces Rockbox's
"Shutting down"):

  A  print pull   a Klein-blue ink field pulled across the paper, "Coda" knocked out of it
  B  grooves      arcs cut like grooves around a red spindle, Muller-Brockmann style
  C  your crate   your most-played covers flip in, butted edge to edge; a paper band stamps

Frames are drawn the way the device's renderer can (flat fills, AA edges, the same fonts),
2x supersampled. Output: docs/h2/boot/v2/<dir>_boot.gif, <dir>_off.gif, <dir>_sheet.png.
The GIFs end in / start from real Coda screens when firmware/host shots are given:
  .venv/Scripts/python firmware/tools/mock_boot_v2.py [shots_dir]
"""
import base64, io, math, sqlite3, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import mutagen
from mutagen.flac import Picture

ROOT = Path(__file__).resolve().parents[2]
FD = ROOT / 'firmware' / 'assets' / 'fonts'
OUT = ROOT / 'docs' / 'h2' / 'boot' / 'v2'
SHOTS = Path(sys.argv[1]) if len(sys.argv) > 1 else None
W, H, SS, FPS = 320, 240, 2, 30
PAPER, INK, BLUE, RED = (0xf4, 0xf4, 0xf0), (0x14, 0x14, 0x14), (0x00, 0x2f, 0xa7), (0xe0, 0x30, 0x1e)
SUB = (0x6d, 0x6d, 0x66)
BLACK = (0, 0, 0)

_fc = {}
def font(name, px):
    k = (name, px)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(str(FD / name), int(round(px * SS)))
    return _fc[k]

POSTER, MONO = 'ArchivoBlack-Regular.ttf', 'Inconsolata.ttf'

def tw(text, name, px, track=0.0):
    f = font(name, px)
    return sum(f.getlength(c) for c in text) / SS + track * (len(text) - 1)

def text(d, x, y_base, s, name, px, fill, track=0.0):
    f = font(name, px)
    cx = x * SS
    for c in s:
        d.text((cx, y_base * SS), c, font=f, fill=fill, anchor='ls')
        cx += f.getlength(c) + track * SS
    return cx / SS

def rect(d, x0, y0, x1, y1, fill):
    a, b, c, e = int(round(x0 * SS)), int(round(y0 * SS)), int(round(x1 * SS)) - 1, int(round(y1 * SS)) - 1
    if c >= a and e >= b:
        d.rectangle([a, b, c, e], fill=fill)

def canvas(bg=PAPER):
    im = Image.new('RGB', (W * SS, H * SS), bg)
    return im, ImageDraw.Draw(im)

def down(im):
    return im.resize((W, H), Image.LANCZOS)

def clamp01(v): return 0.0 if v < 0 else 1.0 if v > 1 else v
def ease_out(t): t = clamp01(t); return 1 - (1 - t) ** 3
def ease_in(t): t = clamp01(t); return t ** 3
def ease_io(t): t = clamp01(t); return 4 * t ** 3 if t < .5 else 1 - (-2 * t + 2) ** 3 / 2
def seg(t, a, b): return clamp01((t - a) / (b - a))

def wordmark(d, x, y_base, px, ink=INK, dot=RED, dot_scale=1.0):
    """'Coda' + the square red full stop (the masthead's mark), at any size."""
    x1 = text(d, x, y_base, 'Coda', POSTER, px, ink, track=-px * 0.04)
    s = px * 0.19 * dot_scale
    cx, cy = x1 + px * 0.04 + px * 0.095, y_base - px * 0.095
    if s > 0.3:
        rect(d, cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2, dot)
    return x1 + px * 0.04 + px * 0.19


# --------------------------------------------------------------------- A: print pull
A_PX = 102

def a_frame(t, under=None):
    """t in ms; under = what the field is pulled over (paper, or a screen)."""
    im = (under.resize((W * SS, H * SS), Image.NEAREST) if under else Image.new('RGB', (W * SS, H * SS), PAPER))
    d = ImageDraw.Draw(im)
    p = ease_io(seg(t, 120, 640))
    edge = p * (W + 6)
    # the field and the letters, clipped to what the pull has covered so far
    layer = Image.new('RGB', (W * SS, H * SS), BLUE)
    ld = ImageDraw.Draw(layer)
    stamp = seg(t, 760, 880)
    wordmark(ld, 6, 214, A_PX, ink=PAPER, dot=RED,
             dot_scale=(0 if t < 760 else 1.0 + 0.45 * (1 - ease_out(stamp))))
    text(ld, 9, 24, 'music, offline', MONO, 12, PAPER)
    mask = Image.new('L', (W * SS, H * SS), 0)
    ImageDraw.Draw(mask).rectangle([0, 0, int(edge * SS), H * SS], fill=255)
    im.paste(layer, (0, 0), mask)
    if 0 < p < 1:                                  # the squeegee blade
        rect(d, edge, 0, edge + 3, H, INK)
    return down(im)

def a_off(t, start):
    """power-off: the blue field pulls back over the screen, then ink, then the dot goes."""
    if t < 380:
        p = ease_io(seg(t, 0, 380))
        base = start.resize((W * SS, H * SS), Image.NEAREST)
        layer = Image.new('RGB', (W * SS, H * SS), BLUE)
        ld = ImageDraw.Draw(layer)
        wordmark(ld, 6, 214, A_PX, ink=PAPER)
        text(ld, 9, 24, 'music, offline', MONO, 12, PAPER)
        edge = W - p * (W + 6)
        mask = Image.new('L', (W * SS, H * SS), 0)
        ImageDraw.Draw(mask).rectangle([int(edge * SS), 0, W * SS, H * SS], fill=255)
        base.paste(layer, (0, 0), mask)
        d = ImageDraw.Draw(base)
        if 0 < p < 1:
            rect(d, edge - 3, 0, edge, H, INK)
        return down(base)
    im, d = canvas(BLUE)
    x_end = wordmark(d, 6, 214, A_PX, ink=PAPER)
    text(d, 9, 24, 'music, offline', MONO, 12, PAPER)
    p = ease_io(seg(t, 520, 820))
    edge = p * (W + 6)
    rect(d, 0, 0, edge, H, BLACK)                  # lights out, left to right
    s = A_PX * 0.19 * (1 - ease_in(seg(t, 820, 940)))
    cx, cy = x_end - A_PX * 0.095, 214 - A_PX * 0.095
    if s > 0.5:
        rect(d, cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2, RED)
    if 0 < p < 1:
        rect(d, edge, 0, edge + 3, H, INK)
    return down(im)


# --------------------------------------------------------------------- B: grooves
B_C = (236, 150)                                    # the spindle
B_RINGS = []                                        # (radius, width, colour, start deg, sweep deg, delay ms)
_w = [3, 9, 3, 5, 14, 3, 7, 3, 11, 4, 6, 3]
_sweep = [300, 250, 330, 200, 280, 160, 310, 230, 190, 270, 140, 240]
_start = [200, 120, 260, 30, 180, 300, 90, 210, 0, 150, 240, 60]
r = 16
for i in range(12):
    a0, sw = _start[i], _sweep[i]
    if r > 84:                      # outer arcs: start after the type's window, end before it
        a0 = 252 + (_start[i] % 40)
        sw = min(sw, 296 - (_start[i] % 40))
    B_RINGS.append((r + _w[i] / 2, _w[i], BLUE if i == 4 else INK, a0, sw, 40 * i))
    r += _w[i] + 6

def arc(d, cx, cy, radius, width, a0, sweep, fill):
    if sweep <= 0.5 or width <= 0:
        return
    box = [(cx - radius) * SS, (cy - radius) * SS, (cx + radius) * SS, (cy + radius) * SS]
    d.arc(box, a0, a0 + sweep, fill=fill, width=max(1, int(round(width * SS))))

def b_scene(d, t, rings_p, type_p, dot_s, rot=0.0):
    cx, cy = B_C
    for (rad, wd, col, a0, sw, delay) in B_RINGS:
        p = rings_p(delay)
        arc(d, cx, cy, rad, wd, a0 + rot, sw * p, col)
    s = 9 * dot_s
    if s > 0.3:
        d.ellipse([(cx - s / 2) * SS, (cy - s / 2) * SS, (cx + s / 2) * SS, (cy + s / 2) * SS], fill=RED)

def b_frame(t):
    im, d = canvas(PAPER)
    rings_p = lambda delay: ease_out(seg(t, 80 + delay, 80 + delay + 520))
    rot = -40 * (1 - ease_out(seg(t, 80, 1100)))   # the arcs are cut while the disc turns
    b_scene(d, t, rings_p, 0, ease_out(seg(t, 0, 160)), rot)
    tp = seg(t, 820, 1080)
    if tp > 0:
        x = 10 - 12 * (1 - ease_out(tp))
        mask = Image.new('L', (W * SS, H * SS), 0)
        md = ImageDraw.Draw(mask)
        md.rectangle([0, 0, int((10 + ease_out(tp) * 200) * SS), H * SS], fill=255)
        layer = Image.new('RGB', (W * SS, H * SS), PAPER)
        im2 = im.copy()
        d2 = ImageDraw.Draw(im2)
        wordmark(d2, x, 58, 50, dot_scale=(0 if t < 1120 else 1 + 0.45 * (1 - ease_out(seg(t, 1120, 1240)))))
        text(d2, x + 2, 76, 'music, offline', MONO, 12, SUB)
        im.paste(im2, (0, 0), mask)
    return down(im)

def b_off(t, start):
    if t < 160:                                     # the screen gives way to the grooves
        im = b_frame(1600).convert('RGB')
        a = ease_io(seg(t, 0, 160))
        return Image.blend(start.convert('RGB'), im, a)
    im, d = canvas(PAPER)
    n = len(B_RINGS)
    rings_p = lambda delay: 1 - ease_in(seg(t, 160 + (n - 1) * 40 - delay, 160 + (n - 1) * 40 - delay + 300))
    b_scene(d, t, rings_p, 0, 1.0, rot=50 * ease_in(seg(t, 160, 800)))
    wipe = ease_io(seg(t, 160, 420))
    tmp = Image.new('RGB', (W * SS, H * SS), PAPER)
    td = ImageDraw.Draw(tmp)
    wordmark(td, 10, 58, 50)
    text(td, 12, 76, 'music, offline', MONO, 12, SUB)
    mask = Image.new('L', (W * SS, H * SS), 0)
    ImageDraw.Draw(mask).rectangle([0, 0, int((1 - wipe) * 220 * SS), 100 * SS], fill=255)
    im.paste(tmp, (0, 0), mask)
    # lights out: the paper goes to black, the spindle last
    dark = ease_io(seg(t, 620, 840))
    if dark > 0:
        im = Image.blend(im, Image.new('RGB', im.size, BLACK), dark)
        d = ImageDraw.Draw(im)
        s = 9 * (1 - ease_in(seg(t, 840, 960)))
        cx, cy = B_C
        if s > 0.3:
            d.ellipse([(cx - s / 2) * SS, (cy - s / 2) * SS, (cx + s / 2) * SS, (cy + s / 2) * SS], fill=RED)
    return down(im)


# --------------------------------------------------------------------- C: your crate
TILE = 80
def crate_covers():
    db = sqlite3.connect(f'file:{ROOT / "data" / "library.db"}?mode=ro', uri=True)
    rows = db.execute("""select t.path from plays p join tracks t on t.video_id = p.video_id
        where p.event in ('play','complete') group by t.video_id order by count(*) desc,
        max(p.ts) desc limit 40""").fetchall()
    out = []
    for (path,) in rows:
        try:
            f = mutagen.File(path)
            for b in (f.tags or {}).get('metadata_block_picture', []):
                im = Image.open(io.BytesIO(Picture(base64.b64decode(b)).data)).convert('RGB')
                w, h = im.size
                s = min(w, h)
                im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
                out.append(im.resize((TILE * SS, TILE * SS), Image.LANCZOS))
                break
        except Exception:
            pass
        if len(out) == 12:
            break
    while len(out) < 12:
        out.append(Image.new('RGB', (TILE * SS, TILE * SS), (0xea, 0xea, 0xe3)))
    return out

COVERS = None
ORDER = [(c, r) for c in range(4) for r in range(3)]     # flipped through column by column

def c_tiles(im, d, p_of):
    for k, (c, r) in enumerate(ORDER):
        p = p_of(k)
        if p <= 0:
            continue
        x0, y0 = c * TILE, r * TILE
        h = int(TILE * p * SS)                           # a sleeve pulled up out of the crate
        if h <= 0:
            continue
        im.paste(COVERS[k].crop((0, 0, TILE * SS, h)), (x0 * SS, (y0 + TILE) * SS - h))

BAND_Y, BAND_H = 86, 68

def c_band(d, x_off, dot_scale=1.0, count='18,388 songs'):
    rect(d, x_off, BAND_Y, x_off + W, BAND_Y + BAND_H, PAPER)
    wordmark(d, x_off + 10, BAND_Y + 50, 50, dot_scale=dot_scale)
    text(d, x_off + W - 10 - tw(count, MONO, 12), BAND_Y + 50, count, MONO, 12, INK)

def c_frame(t):
    im, d = canvas(BLACK)
    c_tiles(im, d, lambda k: ease_out(seg(t, 60 + 55 * k, 60 + 55 * k + 200)))
    bp = ease_out(seg(t, 980, 1220))
    if bp > 0:
        c_band(d, -W * (1 - bp), dot_scale=(0 if t < 1260 else 1 + 0.45 * (1 - ease_out(seg(t, 1260, 1380)))))
    return down(im)

def c_off(t, start):
    if t < 140:
        a = ease_io(seg(t, 0, 140))
        return Image.blend(start.convert('RGB'), c_frame(1600).convert('RGB'), a)
    im, d = canvas(BLACK)
    n = len(ORDER)
    c_tiles(im, d, lambda k: 1 - ease_in(seg(t, 300 + 40 * (n - 1 - k), 300 + 40 * (n - 1 - k) + 160)))
    bp = ease_in(seg(t, 140, 340))
    if bp < 1:
        c_band(d, W * bp)
    return down(im)


# --------------------------------------------------------------------- output
def frames(fn, total_ms, *a):
    return [fn(i * 1000 / FPS, *a) for i in range(int(total_ms * FPS / 1000) + 1)]

def gif(path, fr, tail=None, tail_ms=900, head=None, head_ms=700):
    seq, dur = [], []
    if head is not None:
        seq.append(head); dur.append(head_ms)
    for f in fr:
        seq.append(f); dur.append(int(1000 / FPS))
    seq[-1:] and dur.__setitem__(-1, 500)
    if tail is not None:
        seq.append(tail); dur.append(tail_ms)
    big = [s.convert('RGB').resize((W * 2, H * 2), Image.NEAREST) for s in seq]
    big[0].save(path, save_all=True, append_images=big[1:], duration=dur, loop=0, optimize=False)

def sheet(path, boot, off, picks_boot, picks_off, label):
    cols = max(len(picks_boot), len(picks_off))
    g = 8
    im = Image.new('RGB', (cols * (W + g) + g, 2 * (H + g) + g), (0xc8, 0xc8, 0xc4))
    for i, k in enumerate(picks_boot):
        im.paste(boot[min(k, len(boot) - 1)], (g + i * (W + g), g))
    for i, k in enumerate(picks_off):
        im.paste(off[min(k, len(off) - 1)], (g + i * (W + g), H + 2 * g))
    im.save(path)

def main():
    global COVERS
    OUT.mkdir(parents=True, exist_ok=True)
    menu = Image.open(SHOTS / 'c_menu.png').convert('RGB') if SHOTS else None
    now = Image.open(SHOTS / 'c_now.png').convert('RGB') if SHOTS else Image.new('RGB', (W, H), PAPER)
    COVERS = crate_covers()
    for key, boot_fn, off_fn, off_ms in (('A', a_frame, a_off, 960), ('B', b_frame, b_off, 980),
                                          ('C', c_frame, c_off, 1000)):
        boot = frames(boot_fn, 1600)
        off = frames(off_fn, off_ms, now)
        gif(OUT / f'{key}_boot.gif', boot, tail=menu)
        gif(OUT / f'{key}_off.gif', off, head=now)
        n, m = len(boot), len(off)
        sheet(OUT / f'{key}_sheet.png', boot, off, [int(n * f) for f in (.06, .16, .26, .4, .6, 1)],
              [int(m * f) for f in (0, .2, .4, .6, .8, .95)], key)
        print(key, len(boot), 'boot frames,', len(off), 'power-off frames')

if __name__ == '__main__':
    main()
