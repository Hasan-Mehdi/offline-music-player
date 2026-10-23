"""Game mockups for Coda on the H2: little games that live next to the music and use the
click wheel the way a game would -- a spinner, a dial, a reel, a turntable -- drawn in the
device's own looks (Sakurai's print poster: paper, ink, Klein blue, red only for what's
live; Room's pixel desk with Bubloo) and with the listener's real covers.

  breaker   Cover Breaker: Breakout in a ring. The wheel is an Arkanoid spinner, the bricks
            are the playing song's cover
  orbit     Beat Orbit: walls close in on the beat of the playing song; the wheel moves you
            round the ring, Prev/Next dash to the far side
  scratch   Scratch: notes ride the record's rim to the needle; turn the wheel the way the
            arrows point, Play on the dots
  fishing   Bubloo's Fishing Hole: Play casts, the wheel is the reel (too fast snaps the
            line); every catch is a song you've never played
  laser     Laser Pointer: the wheel moves the dot along the desk, Bubloo stalks and pounces;
            keep him off the mug
  safe      Treat Tin: a combination dial; the clicks get louder near the number
  tune      Name That Tune: five seconds of a song you've been replaying; the wheel picks a
            cover, Play guesses

Output: docs/h2/games/<name>.gif (2x), <name>.png, sheet.png
  .venv/Scripts/python firmware/tools/mock_games.py [name ...]
"""
import csv
import math
import random
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_menu as M  # noqa: E402
from mock_menu import (W, H, SS, PAPER, INK, BLUE, RED, SUB, RULE, STRIP_SUB,  # noqa: E402
                       POSTER, BODY, MONO, font, tw, fit, Pen, clamp01, seg, ease_out,
                       ease_back, mix)

ROOT = M.ROOT
OUT = ROOT / 'docs' / 'h2' / 'games'
FD = ROOT / 'firmware' / 'assets' / 'fonts'
FPS = 25
GH = 212                                    # the game; below it, the controls strip
TAU = math.tau
PAPER2 = (0xec, 0xeb, 0xe4)


# --------------------------------------------------------------------- the listener's songs
_cov = {}
def cov(path, px):
    """the cover, px screen px square, at SS"""
    k = (path, px)
    if k not in _cov:
        _cov[k] = M.cover_of(path, px)
    return _cov[k]


def songs():
    """(top, fresh): Listen again order (21-day replays, one per artist) and songs by those
    artists the listener has never played (what the fishing hole catches)"""
    ev = [(r['video_id'], datetime.fromisoformat(r['time']).timestamp())
          for r in csv.DictReader(open(ROOT / 'data' / 'listens.csv', encoding='utf-8-sig'))]
    end = max(t for _, t in ev)
    score = {}
    for v, t in ev:
        score[v] = score.get(v, 0.0) + 0.5 ** ((end - t) / (21 * 86400))
    db = sqlite3.connect(f'file:{ROOT / "data" / "library.db"}?mode=ro', uri=True)
    top, arts = [], set()
    for v in sorted(score, key=score.get, reverse=True):
        r = db.execute('select title, artist, path from tracks where video_id=?', (v,)).fetchone()
        if not r or r[1] in arts or 'sonic' in (r[0] + r[1]).lower() or cov(r[2], 8) is None:
            continue
        arts.add(r[1])
        top.append(r)
        if len(top) >= 10:
            break
    fresh = []
    for _, artist, _ in top:
        for v, t2, a2, p2 in db.execute('select video_id, title, artist, path from tracks '
                                        'where artist=? order by video_id limit 60', (artist,)):
            if v not in score and 'sonic' not in t2.lower() and cov(p2, 8) is not None:
                fresh.append((t2, a2, p2))
                break
        if len(fresh) >= 3:
            break
    return top, fresh


TOP, FRESH = songs()


# --------------------------------------------------------------------- shared drawing
def canvas(col=PAPER):
    im = Image.new('RGB', (W * SS, H * SS), col)
    return im, Pen(im)


def down(im):
    return im.resize((W, H), Image.BOX)


def pt(cx, cy, r, a):
    """angle a: 0 = up, clockwise"""
    return cx + r * math.sin(a), cy - r * math.cos(a)


def band(p, cx, cy, r0, r1, a0, a1, c, n=None):
    """a ring segment from angle a0 to a1 (clockwise), radii r0..r1"""
    if a1 < a0:
        a0, a1 = a1, a0
    n = n or max(4, int((a1 - a0) / TAU * 96))
    outer = [pt(cx, cy, r1, a0 + (a1 - a0) * i / n) for i in range(n + 1)]
    inner = [pt(cx, cy, r0, a1 - (a1 - a0) * i / n) for i in range(n + 1)]
    p.poly(outer + inner, c)


def disc_img(img):
    """a circular mask for a square image"""
    m = Image.new('L', img.size, 0)
    ImageDraw.Draw(m).ellipse([0, 0, img.size[0] - 1, img.size[1] - 1], fill=255)
    return m


def keyglyph(p, kind, x, yc, c):
    """the H2's controls as the strip draws them; returns the x after it"""
    if kind == 'wheel':
        p.ring(x + 6, yc, 5, 1.6, c)
        p.disc(x + 6 + 5 * math.sin(.9), yc - 5 * math.cos(.9), 1.9, c)
        return x + 13
    if kind == 'play':
        p.poly([(x, yc - 5), (x + 8, yc), (x, yc + 5)], c)
        return x + 9
    if kind in ('prev', 'next'):
        s = -1 if kind == 'prev' else 1
        x0 = x if s > 0 else x + 12
        for k in (0, 6):
            p.poly([(x0 + s * k, yc - 4.5), (x0 + s * (k + 6), yc), (x0 + s * k, yc + 4.5)], c)
        return x + 13
    if kind == 'pair':
        x = keyglyph(p, 'prev', x, yc, c) + 2
        return keyglyph(p, 'next', x, yc, c)
    if kind == 'back':
        p.bar(x + 1, yc, x + 10, yc, 2, c)
        p.poly([(x - 1, yc), (x + 4, yc - 4.5), (x + 4, yc + 4.5)], c)
        return x + 11
    if kind == 'menu':
        for k in (-4, 0, 4):
            p.rect(x, yc + k - 1, x + 10, yc + k + 1, c)
        return x + 11
    return x


def strip(p, keys, bg=INK, fg=PAPER, sub=STRIP_SUB):
    p.rect(0, GH, W, H, bg)
    x, yc = 9, GH + 14
    f = font(BODY, 11, 'Bold')
    for k, label in keys:
        x = keyglyph(p, k, x, yc, fg) + 5
        x = p.text(x, yc + 4, label, f, sub) + 13


def header(p, title, right=None, sub=None, col=INK):
    p.text(8, 17, title, font(POSTER, 15), col, track=-.6)
    if right:
        f = font(POSTER, 15)
        p.text(W - 8 - tw(right, f, -.4), 17, right, f, col, track=-.4)
    if sub:
        f = font(BODY, 10)
        p.text(8, 30, fit(sub, f, 220), f, SUB)


def slab(p, cx, cy, text, u, bg=BLUE, fg=PAPER, px=17, lean=-.08):
    """Sakurai's tilted slab with a hard ink shadow, popping in with u (0..1+)"""
    f = font(POSTER, px)
    w = tw(text, f, -.5) + 18
    h = px + 12
    s = ease_back(u)
    w2, h2 = w * s / 2, h * s / 2

    def quad(dx, dy):
        return [(cx - w2 + dx - h2 * lean, cy - h2 + dy), (cx + w2 + dx - h2 * lean, cy - h2 + dy),
                (cx + w2 + dx + h2 * lean, cy + h2 + dy), (cx - w2 + dx + h2 * lean, cy + h2 + dy)]
    p.poly(quad(3, 3), INK)
    p.poly(quad(0, 0), bg)
    if s > .6:
        p.text(cx - tw(text, f, -.5) / 2, cy + px * .36, text, f, fg, track=-.5)


# --------------------------------------------------------------------- Bubloo (from the C)
def _sprites():
    src = (ROOT / 'firmware' / 'ui' / 'th_room.h').read_text(encoding='utf-8') + \
        (ROOT / 'firmware' / 'ui' / 'th_dio.h').read_text(encoding='utf-8')
    out = {}
    for name, body in re.findall(r'static const char \*const (\w+)\[\d+\] = \{(.*?)\};', src, re.S):
        out[name] = re.findall(r'"([^"]*)"', body)
    pal = {}
    for ch, r, g, b in re.findall(r"case '(.)': return C565\(0x(..), 0x(..), 0x(..)\)",
                                  src.split('static const char *const CAT_BODY')[0]):
        pal[ch] = (int(r, 16), int(g, 16), int(b, 16))
    return out, pal


SPR, CATPAL = _sprites()


def sprite(gd, rows, x, y, mir=False, pal=None, sub=None):
    pal = pal or CATPAL
    w = max(len(r) for r in rows)
    for r, row in enumerate(rows):
        for q, ch in enumerate(row):
            if sub:
                ch = sub(r, q, ch)
            if ch in '. ' or ch not in pal:
                continue
            gd.point((x + (w - 1 - q if mir else q), y + r), fill=pal[ch])


def head_eyes(mode):
    """CAT_HEAD's E cells: 'open' (looking at you), 'shut', 'up'"""
    def sub(r, q, ch):
        if ch != 'E':
            return ch
        right = q >= 8
        c, e = q - (11 if right else 3), r - 6
        if mode == 'shut':
            return 'o' if e else 'm'
        pr = 0
        pc = (0 if right else 1) if mode == 'open' else (1 if right else 0)
        if mode == 'up':
            pc = 1 if not right else 0
        return 'k' if (c == pc and e == pr) else 'e'
    return sub


def tail(gd, pts, w=4):
    gd.line(pts, fill=CATPAL['o'], width=w + 2, joint='curve')
    gd.line(pts, fill=CATPAL['d'], width=w, joint='curve')
    gd.line(pts[-2:], fill=CATPAL['D'], width=w)


def bubloo_sit(gd, x, y, eyes='open', mir=False, t=0.0, bob=0):
    """sitting, x = left edge of the body (cells), y = the row he sits on"""
    body = SPR['DB_SIT']
    top = y - len(body)
    sw = math.sin(t * 2.4)
    tx = x + (1 if mir else 20)
    d = -1 if mir else 1
    tail(gd, [(tx, y - 2), (tx + d * 4, y - 1), (tx + d * (8 + sw), y - 4), (tx + d * (9 + 2 * sw), y - 9)])
    sprite(gd, body, x, top + bob)
    sprite(gd, SPR['CAT_HEAD'], x + 3, top - 9 + bob, mir=mir, sub=head_eyes(eyes))


def bubloo_walk(gd, x, y, frame, mir=False):
    """walking along a surface whose top is row y"""
    body, legs = SPR['DB_WB'], [SPR['DB_WL'][k] if 'DB_WL' in SPR else None for k in range(1)]
    legs = WL[frame % 4]
    w = 27
    top = y - 10
    tx = x + (w - 2 if mir else 1)
    d = 1 if mir else -1
    tail(gd, [(tx, top + 3), (tx + d * 4, top + 1), (tx + d * 7, top - 3), (tx + d * 8, top - 7)])
    sprite(gd, body, x, top, mir=mir)
    sprite(gd, legs, x, top + 7, mir=mir)
    hx = x + (-1 if mir else 13)
    sprite(gd, SPR['CAT_HEAD'], hx, top - 9, mir=mir, sub=head_eyes('open'))


def bubloo_leap(gd, x, y, mir=False):
    body = SPR['DB_LEAP']
    sprite(gd, body, x, y, mir=mir)
    hx = x + (-2 if mir else 16)
    sprite(gd, SPR['CAT_HEAD'], hx, y - 8, mir=mir, sub=head_eyes('open'))


def _wl():
    src = (ROOT / 'firmware' / 'ui' / 'th_dio.h').read_text(encoding='utf-8')
    body = re.search(r'DB_WL\[4\]\[3\] = \{(.*?)\};', src, re.S).group(1)
    s = re.findall(r'"([^"]*)"', body)
    return [s[k * 3:k * 3 + 3] for k in range(4)]


WL = _wl()


def silk(px):
    return ImageFont.truetype(str(FD / 'Silkscreen.ttf'), px)


def grid_onto(g, im, y0=0):
    """a 2x2-pixel layer onto the SS canvas"""
    im.paste(g.resize((g.size[0] * 2 * SS, g.size[1] * 2 * SS), Image.NEAREST), (0, y0 * SS))


# ===================================================================== 1. Cover Breaker
class Breaker:
    CX, CY, R = 160, 123, 72
    N, CELL = 18, 6
    HALF = .34                                # the paddle's half-width, rad

    def __init__(self, song):
        self.song = song
        img = cov(song[2], 64).resize((self.N, self.N), Image.LANCZOS)
        rnd = random.Random(4)
        o = self.CELL * self.N / 2
        self.bricks = {}
        for i in range(self.N):
            for j in range(self.N):
                x = self.CX - o + (i + .5) * self.CELL
                y = self.CY - o + (j + .5) * self.CELL
                d = math.hypot(x - self.CX, y - self.CY)
                if d > 54 or (d > 44 and rnd.random() < .7) or (d > 36 and rnd.random() < .25):
                    continue
                self.bricks[(i, j)] = img.getpixel((i, j))
        self.total = 224
        self.broken = self.total - len(self.bricks)
        self.frames = []
        self.sim()

    def cell(self, x, y):
        o = self.CELL * self.N / 2
        return int((x - self.CX + o) // self.CELL), int((y - self.CY + o) // self.CELL)

    def sim(self):
        x, y = self.CX + 12, self.CY + 58
        sp = 170.0
        vx, vy = math.sin(.5) * sp, -math.cos(.5) * sp
        pa = math.atan2(x - self.CX, -(y - self.CY))
        shards, n = [], 0
        sub = 4
        dt = 1 / (FPS * sub)
        for f in range(int(6.0 * FPS)):
            for _ in range(sub):
                nx, ny = x + vx * dt, y + vy * dt
                c0, c1 = self.cell(x, y), self.cell(nx, ny)
                if c1 in self.bricks:
                    col = self.bricks.pop(c1)
                    n += 1
                    for k in range(5):
                        a = random.Random(n * 7 + k).uniform(0, TAU)
                        shards.append([nx, ny, math.cos(a) * 60 + vx * .2, math.sin(a) * 60 + vy * .2,
                                       f / FPS, col, a])
                    if c1[0] != c0[0]:
                        vx = -vx
                    if c1[1] != c0[1]:
                        vy = -vy
                    if c1[0] == c0[0] and c1[1] == c0[1]:
                        vx, vy = -vx, -vy
                    nx, ny = x + vx * dt, y + vy * dt
                x, y = nx, ny
                dx, dy = x - self.CX, y - self.CY
                d = math.hypot(dx, dy)
                ba = math.atan2(dx, -dy)
                if d > self.R - 5 and (vx * dx + vy * dy) > 0:
                    # Arkanoid's rule: where it meets the paddle sets where it goes -- the
                    # middle sends it straight back in, the edges send it off at an angle
                    off = (ba - pa + math.pi) % TAU - math.pi
                    a = math.atan2(-dx, dy) + off / self.HALF * .65
                    vx, vy = math.sin(a) * sp, -math.cos(a) * sp
                # the wheel: the paddle chases where the ball will meet the ring
                lead = ba + (.25 if (vx * dy - vy * dx) < 0 else -.25) * 0
                diff = (lead - pa + math.pi) % TAU - math.pi
                step = 5.2 * dt
                pa += max(-step, min(step, diff))
            self.frames.append((x, y, pa, dict(self.bricks), [s for s in shards if f / FPS - s[4] < .6],
                                self.broken + n))

    def frame(self, f):
        x, y, pa, bricks, shards, broken = self.frames[f]
        t = f / FPS
        im, p = canvas()
        cx, cy, R = self.CX, self.CY, self.R
        # the ring, with the wheel's detents on it
        p.ring(cx, cy, R + 4, 1.2, RULE)
        for k in range(48):
            a = k / 48 * TAU
            x0, y0 = pt(cx, cy, R + 8, a)
            x1, y1 = pt(cx, cy, R + 11 + (2 if k % 4 == 0 else 0), a)
            p.bar(x0, y0, x1, y1, 1.1, RULE if k % 4 else SUB)
        o = self.CELL * self.N / 2
        for (i, j), col in bricks.items():
            bx, by = cx - o + i * self.CELL, cy - o + j * self.CELL
            p.rect(bx + .5, by + .5, bx + self.CELL - .5, by + self.CELL - .5, col)
        for sx, sy, svx, svy, t0, col, a in shards:
            u = t - t0
            px_, py_ = sx + svx * u, sy + svy * u
            s = 3.2 * (1 - u / .6)
            p.poly([(px_ + s * math.cos(a + k * TAU / 4), py_ + s * math.sin(a + k * TAU / 4)) for k in range(4)], col)
        # the paddle: a blue slab on the ring with its ink shadow
        band(p, cx + 2, cy + 2, R - 1, R + 6, pa - self.HALF, pa + self.HALF, INK)
        band(p, cx, cy, R - 1, R + 6, pa - self.HALF, pa + self.HALF, BLUE)
        p.disc(x + 1.2, y + 1.2, 3.6, INK)
        p.disc(x, y, 3.6, RED)
        header(p, 'Cover Breaker', f'{broken}/{self.total}', f'{self.song[0]} — {self.song[1]}')
        strip(p, [('wheel', 'move the paddle'), ('play', 'launch'), ('pair', 'flip to the far side')])
        return down(im)


# ===================================================================== 2. Beat Orbit
class Orbit:
    CX, CY = 160, 118
    BPM = 124.0

    def __init__(self, song):
        self.song = song
        self.beat = 60 / self.BPM
        rnd = random.Random(9)
        self.waves = []
        g = .4
        for k in range(-6, 22):
            kind = 'one' if k % 3 else 'two'
            g += rnd.choice([-1.4, -.9, .9, 1.4, math.pi])
            self.waves.append((k * self.beat * 2, g % TAU, kind))
        self.dash = 7                          # this wave's gap is across: Prev/Next
        self.waves[self.dash + 6] = (self.waves[self.dash + 6][0], (self.waves[self.dash + 5][1] + math.pi) % TAU, 'one')
        self.path = self.sim()

    SPEED, R0, RP = 58.0, 150.0, 34.0

    def r_of(self, t0, t):
        return self.R0 - self.SPEED * (t - t0)

    def gaps(self, kind, g):
        return [g] if kind == 'one' else [g, (g + math.pi) % TAU]

    def sim(self):
        a, out, dashes = self.waves[6][1], [], []
        for f in range(int(5.6 * FPS)):
            t = f / FPS
            # the next wave to reach the ring
            nxt = min((w for w in self.waves if self.r_of(w[0], t) > self.RP + 6), key=lambda w: w[0])
            tg = min(self.gaps(nxt[2], nxt[1]), key=lambda g: abs((g - a + math.pi) % TAU - math.pi))
            diff = (tg - a + math.pi) % TAU - math.pi
            if abs(diff) > 2.4:
                a = tg
                dashes.append(t)
            else:
                a += max(-6.5 / FPS, min(6.5 / FPS, diff))
            out.append((a, list(dashes)))
        return out

    def frame(self, f):
        t = f / FPS
        a, dashes = self.path[f]
        im, p = canvas()
        cx, cy = self.CX, self.CY
        # six sectors turning slowly, paper and a shade darker
        rot = -t * .35
        for k in range(6):
            if k % 2:
                band(p, cx, cy, 0, 230, rot + k * TAU / 6, rot + (k + 1) * TAU / 6, PAPER2)
        ph = (t % self.beat) / self.beat
        pulse = 1 + .12 * (1 - ease_out(ph * 2.2))
        for t0, g, kind in self.waves:
            r = self.r_of(t0, t)
            if r < self.RP - 4 or r > 230:
                continue
            gaps = self.gaps(kind, g)
            half = .55
            a0 = 0.0
            cuts = sorted(((gg - half) % TAU, (gg + half) % TAU) for gg in gaps)
            # draw the ring except the gaps
            segs, start = [], cuts[0][1]
            for k in range(len(cuts)):
                end = cuts[(k + 1) % len(cuts)][0]
                if end < start:
                    end += TAU
                segs.append((start, end))
                start = cuts[(k + 1) % len(cuts)][1]
            for s0, s1 in segs:
                band(p, cx, cy, r, r + 7, s0, s1, INK)
        # the song at the centre, kicking on the beat
        rr = 22 * pulse
        c = cov(self.song[2], 48)
        cs = c.resize((int(rr * 2 * SS), int(rr * 2 * SS)), Image.LANCZOS)
        p.disc(cx + 2, cy + 2, rr + 2, INK)
        p.paste(cs, cx - rr, cy - rr, disc_img(cs))
        p.ring(cx, cy, self.RP, 1.4, SUB)
        # a dash leaves a blue smear across the ring
        for td in dashes:
            u = (t - td) / .35
            if 0 <= u < 1:
                p.ring(cx, cy, self.RP + 6, 3 * (1 - u), mix(BLUE, PAPER, u))
        tip = pt(cx, cy, self.RP + 12, a)
        l, r_ = pt(cx, cy, self.RP + 2, a - .2), pt(cx, cy, self.RP + 2, a + .2)
        p.poly([(tip[0] + 1.5, tip[1] + 1.5), (l[0] + 1.5, l[1] + 1.5), (r_[0] + 1.5, r_[1] + 1.5)], INK)
        p.poly([tip, l, r_], RED)
        sec = 72 + t
        p.rect(0, 0, W, 36, PAPER)
        p.rect(0, 36, W, 37.2, RULE)
        header(p, 'Beat Orbit', f'{int(sec // 60)}:{int(sec % 60):02d}', f'{self.song[0]} — {self.song[1]}')
        strip(p, [('wheel', 'move round'), ('pair', 'dash to the far side'), ('play', 'pause')])
        return down(im)


# ===================================================================== 3. Scratch
class Scratch:
    CX, CY = 160, 124
    RV, RL, RT = 62.0, 26.0, 76.0             # vinyl, label, the note track
    SPEED = 1.5                               # rad/s along the rim

    def __init__(self, song):
        self.song = song
        beat = 60 / 112
        seq = ['cw', 'cw', 'tap', 'ccw', 'cw', 'hold', None, 'tap', 'ccw', 'ccw', 'tap', 'cw', 'hold',
               None, 'cw', 'tap', 'ccw', 'cw']
        self.notes = [(1.0 + k * beat, kind) for k, kind in enumerate(seq) if kind]
        self.rot = []
        ang = 0.0
        for f in range(int(6.4 * FPS)):
            t = f / FPS
            v = 3.5                            # the record turning with the song
            for th, kind in self.notes:
                if kind in ('cw', 'ccw') and 0 <= th - t < .22:
                    v = 9 if kind == 'cw' else -9
                if kind == 'hold' and 0 <= t - th < .5:
                    v = 7
            ang += v / FPS
            self.rot.append(ang)

    def frame(self, f):
        t = f / FPS
        im, p = canvas()
        cx, cy = self.CX, self.CY
        # the track the notes ride, and the needle at the top
        band(p, cx, cy, self.RT - 7, self.RT + 7, 0, TAU, PAPER2)
        p.ring(cx, cy, self.RT + 7, 1, RULE)
        p.ring(cx, cy, self.RT - 7, 1, RULE)
        band(p, cx, cy, self.RT - 9, self.RT + 9, -.13, .13, mix(RED, PAPER, .75))
        # the record
        p.disc(cx + 3, cy + 3, self.RV, INK)
        p.disc(cx, cy, self.RV, (0x1b, 0x1b, 0x1a))
        for r in range(36, int(self.RV) - 2, 4):
            p.ring(cx, cy, r, .6, (0x2e, 0x2e, 0x2c))
        ang = self.rot[f]
        c = cov(self.song[2], 64).resize((int(self.RL * 2 * SS),) * 2, Image.LANCZOS)
        c = c.rotate(-math.degrees(ang), resample=Image.BICUBIC)
        p.paste(c, cx - self.RL, cy - self.RL, disc_img(c))
        p.disc(cx, cy, 2.4, PAPER)
        # a glint that shows it turning
        # notes
        hit = None
        for th, kind in self.notes:
            a = (th - t) * self.SPEED
            if kind == 'hold':
                a0, a1 = a, a + .5 * self.SPEED
                if a1 < -.05 or a0 > TAU * .8:
                    continue
                band(p, cx, cy, self.RT - 4, self.RT + 4, max(a0, 0), a1, BLUE)
                if a0 <= 0 <= a1:
                    hit = hit or (th, kind)
                continue
            if a < -.25 or a > TAU * .8:
                if -.6 < a < -.25:
                    pass
                continue
            if abs(a) < .05:
                hit = (th, kind)
            x, y = pt(cx, cy, self.RT, a)
            if kind == 'tap':
                p.disc(x + 1, y + 1, 5.2, INK)
                p.disc(x, y, 5.2, RED)
            else:
                s = 1 if kind == 'cw' else -1   # chevrons point the way to turn
                col = BLUE if kind == 'cw' else INK
                for k in (-1, 1):
                    ab = a + k * .085
                    tip = pt(cx, cy, self.RT, ab + s * .085)
                    b1 = pt(cx, cy, self.RT - 8, ab - s * .06)
                    b2 = pt(cx, cy, self.RT + 8, ab - s * .06)
                    notch = pt(cx, cy, self.RT, ab + s * .005)
                    p.poly([(x_ + 1.2, y_ + 1.2) for x_, y_ in (b1, tip, b2, notch)], INK)
                    p.poly([b1, tip, b2, notch], col if kind == 'cw' else PAPER)
                    if kind == 'ccw':
                        p.poly([b1, tip, b2, notch, b1], None, outline=INK, width=1.2)
        p.poly([(cx - 6, cy - self.RT - 15), (cx + 6, cy - self.RT - 15), (cx, cy - self.RT - 6)], RED)
        # judgements
        done = [th for th, _ in self.notes if th <= t]
        combo = 21 + len(done)
        if done and t - done[-1] < .45:
            u = (t - done[-1]) / .16
            word = 'Perfect' if len(done) % 3 else 'Great'
            slab(p, cx + 92, 58, word, u, BLUE if word == 'Perfect' else INK)
        header(p, f'x{combo}', '98%')
        fs = font(BODY, 10)
        p.text(8, 30, fit(self.song[0], fs, 120), fs, SUB)
        p.text(8, 42, fit(self.song[1], fs, 120), fs, SUB)
        p.text(8 + tw(f'x{combo}', font(POSTER, 15), -.6) + 6, 17, 'combo', font(BODY, 10), SUB)
        strip(p, [('wheel', 'turn the way the arrows point'), ('play', 'the red dots')])
        return down(im)


# ===================================================================== pixel scenes
WATER, WATER_D, WATER_L = (0x5a, 0x8b, 0x93), (0x47, 0x72, 0x7b), (0x8c, 0xb8, 0xb6)
SKY = [(0xe9, 0xc9, 0x9d), (0xe2, 0xb8, 0x8b), (0xd9, 0xa7, 0x7c)]
C = dict(walnut=(0x4d, 0x33, 0x22), walnut_d=(0x3a, 0x26, 0x19), walnut_l=(0x60, 0x42, 0x2d),
         walnut_hi=(0x82, 0x5c, 0x3c), ink=(0x2e, 0x1f, 0x15), cream=(0xf4, 0xee, 0xe2),
         sub=(0x7c, 0x68, 0x52), leaf=(0x4b, 0x8a, 0x36), leaf_l=(0x74, 0xb1, 0x4b),
         leaf_d=(0x2f, 0x5e, 0x24), sage=(0x66, 0x73, 0x3f), sage_d=(0x54, 0x60, 0x31),
         key=(0xea, 0xa2, 0x2c), key_d=(0xc3, 0x7c, 0x1b), wall=(0xd6, 0xc2, 0xa3),
         wall_sh=(0xb8, 0xa0, 0x80), silver=(0xc9, 0xca, 0xc6), silver_d=(0x9c, 0x9d, 0x99),
         silver_l=(0xe7, 0xe8, 0xe4), felt=(0xb7, 0xb5, 0xaf), red=(0xc8, 0x3a, 0x2a))


def room_strip(p, keys):
    strip(p, keys, bg=C['walnut_d'], fg=C['cream'], sub=(0xc9, 0xb3, 0x96))


def pix_header(p, title, right=None):
    f = font(POSTER, 14)
    p.text(9, 17, title, f, C['ink'], track=-.5)
    if right:
        p.text(W - 9 - tw(right, f, -.4), 17, right, f, C['ink'], track=-.4)


# ===================================================================== 4. Fishing Hole
class Fishing:
    def __init__(self, catch):
        self.catch = catch
        self.T = 7.2

    def bg(self, gd, t):
        for k, col in enumerate(SKY):
            gd.rectangle([0, k * 9, 160, k * 9 + 9], fill=col)
        # far bank: trees in two greens
        rnd = random.Random(3)
        for x in range(0, 160, 6):
            h = rnd.randint(6, 13)
            gd.ellipse([x - 4, 34 - h, x + 7, 34 + 3], fill=C['leaf_d'])
        for x in range(3, 160, 9):
            h = rnd.randint(3, 8)
            gd.ellipse([x - 3, 36 - h, x + 5, 37], fill=C['sage_d'])
        gd.rectangle([0, 35, 160, 37], fill=C['sage'])
        gd.rectangle([0, 37, 160, 106], fill=WATER)
        # light on the water, drifting
        for k in range(14):
            y = 42 + k * 4 + (k % 3)
            x0 = (k * 37 + int(t * 6 * (1 + k % 2))) % 190 - 20
            gd.line([x0, y, x0 + 6 + k % 4, y], fill=WATER_L if k % 2 else WATER_D)
        # the dock
        gd.rectangle([0, 60, 46, 64], fill=C['walnut_l'])
        for x in range(0, 46, 8):
            gd.line([x, 60, x, 64], fill=C['walnut_d'])
        gd.line([0, 60, 46, 60], fill=C['walnut_hi'])
        gd.rectangle([0, 65, 46, 66], fill=C['walnut_d'])
        for x in (4, 40):
            gd.rectangle([x, 66, x + 3, 80], fill=C['walnut'])
            gd.line([x - 2, 80, x + 5, 80], fill=WATER_L)

    def frame(self, f):
        t = f / FPS
        g = Image.new('RGB', (160, 106))
        gd = ImageDraw.Draw(g)
        self.bg(gd, t)
        tipx, tipy = 72, 24
        hand = (40, 50)
        # phases: cast 0-1.1, wait -2.6, bite -3.1, reel -5.4, catch
        cast, bite, reel, caught = 1.1, 2.6, 3.1, 5.4
        bob = (118, 72)
        if t < cast:
            u = ease_out(t / cast)
            sw = math.sin(min(1, t / .35) * math.pi) * -.9 * (1 - u)
            tipx = 40 + 32 * math.cos(-.62 + sw)
            tipy = 50 - 32 * math.sin(.82 - sw)
            bob = (tipx + (118 - tipx) * u, tipy + (72 - tipy) * u - 30 * math.sin(u * math.pi))
        elif t < reel:
            dip = 0
            if t > bite:
                dip = 2 if int((t - bite) * 8) % 2 == 0 else 0
            bob = (118, 72 + dip + (math.sin(t * 3) > .6))
        elif t < caught:
            u = (t - reel) / (caught - reel)
            bob = (118 - 66 * ease_out(u), 72 - 4 * u + math.sin(t * 25) * .8)
            tipy = 24 + 4 * math.sin(t * 9)
        else:
            bob = None
        gd.line([hand, (tipx, tipy)], fill=C['walnut_d'], width=2)
        gd.point((tipx, tipy), fill=C['key'])
        if bob:
            sag = 10 if t < reel else 2
            mx, my = (tipx + bob[0]) / 2, max(tipy, bob[1]) + sag - (8 if t < cast else 0)
            pts = [(tipx + (bob[0] - tipx) * k / 12, (1 - k / 12) ** 2 * tipy + 2 * (1 - k / 12) * k / 12 * my + (k / 12) ** 2 * bob[1]) for k in range(13)]
            gd.line(pts, fill=C['cream'], width=1)
            bx, by = int(bob[0]), int(bob[1])
            if t >= cast:
                for k in range(3):
                    ph = ((t - cast) * .9 + k / 3) % 1
                    rw = 3 + ph * 14
                    gd.ellipse([bx - rw, by + 2 - rw * .28, bx + rw, by + 2 + rw * .28],
                               outline=WATER_L if ph < .6 else mix(WATER_L, WATER, (ph - .6) / .4))
            gd.rectangle([bx - 1, by - 3, bx + 1, by - 1], fill=C['red'])
            gd.rectangle([bx - 1, by, bx + 1, by + 1], fill=C['cream'])
        if reel <= t < caught:   # the fish, a shadow coming in
            u = (t - reel) / (caught - reel)
            fx, fy = bob[0] + 6, 80 - 6 * u
            gd.ellipse([fx - 7, fy - 2, fx + 7, fy + 2], fill=WATER_D)
            gd.polygon([(fx + 6, fy), (fx + 11, fy - 3), (fx + 11, fy + 3)], fill=WATER_D)
        # Bubloo on the end of the dock
        eyes = 'up' if bite <= t < caught else 'open'
        if t >= caught:
            eyes = 'shut'
        jump = -2 if bite <= t < bite + .25 or (t >= caught and int(t * 6) % 2) else 0
        bubloo_sit(g and gd, 18, 60, eyes=eyes, t=t, bob=jump)
        im, p = canvas(C['wall'])
        grid_onto(g, im)
        if bite <= t < reel:
            fb = font(POSTER, 26)
            p.text(70, 62 + (2 if int(t * 10) % 2 else 0), '!', fb, C['key'])
        if reel <= t < caught:
            # the reel: tension needle in its band; the wheel crank turning
            gx, gy, gh = 296, 54, 120
            p.rect(gx - 1, gy - 1, gx + 13, gy + gh + 1, C['ink'])
            p.rect(gx, gy, gx + 12, gy + gh, C['cream'])
            p.rect(gx, gy + 28, gx + 12, gy + 70, (0xa9, 0xc4, 0x6c))
            nv = gy + 48 + 22 * math.sin(t * 3.1) + 9 * math.sin(t * 7.7)
            p.rect(gx - 4, nv - 1.5, gx + 16, nv + 1.5, C['red'])
            ccx, ccy = 262, 182
            p.ring(ccx, ccy, 14, 3, C['cream'])
            a = t * 9
            p.bar(ccx, ccy, ccx + 14 * math.sin(a), ccy - 14 * math.cos(a), 3, C['cream'])
            p.disc(ccx + 14 * math.sin(a), ccy - 14 * math.cos(a), 4, C['key'])
            ft = font(BODY, 11, 'Bold')
            p.text(ccx - 46, ccy + 4, 'reel!', ft, C['cream'])
        if t >= caught:
            u = (t - caught) / .35
            s = ease_back(u)
            cw, ch = 214 * s, 92 * s
            x0, y0 = 160 - cw / 2 + 20, 104 - ch / 2
            if s > .05:
                p.rect(x0 + 3, y0 + 3, x0 + cw + 3, y0 + ch + 3, C['ink'])
                p.rect(x0, y0, x0 + cw, y0 + ch, C['cream'])
                p.rect(x0, y0, x0 + cw, y0 + 3, C['walnut'])
            if s > .9:
                c = cov(self.catch[2], 70)
                p.paste(c, x0 + 11, y0 + 11)
                fx = x0 + 92
                p.text(fx, y0 + 26, 'New catch', font(BODY, 10, 'Bold'), C['key_d'])
                ft = font(POSTER, 12)
                lines = M.wrap(self.catch[0], ft, cw - 104, 2)
                for k, ln in enumerate(lines):
                    p.text(fx, y0 + 44 + k * 15, ln, ft, C['ink'])
                p.text(fx, y0 + 46 + len(lines) * 15, fit(self.catch[1], font(BODY, 10), cw - 104), font(BODY, 10), C['sub'])
                p.poly([(fx, y0 + 74), (fx + 7, y0 + 78.5), (fx, y0 + 83)], C['red'])
                p.text(fx + 11, y0 + 83, 'playing now', font(BODY, 10, 'Bold'), C['ink'])
        pix_header(p, "Bubloo's Fishing Hole", '3 caught')
        room_strip(p, [('play', 'cast'), ('wheel', 'reel, not too fast'), ('back', 'let it go')])
        return down(im)


# ===================================================================== 5. Laser Pointer
class Laser:
    DESK = 84                                  # the desk top, grid rows

    def __init__(self):
        self.T = 6.8
        # the dot's path (grid x on the desk) and what he does
        self.keys = [(0, 112), (.8, 86), (1.5, 98), (2.2, 70), (3.0, 72), (3.8, 112), (4.6, 108),
                     (5.4, 126), (6.0, 120), (6.8, 112)]

    def dot(self, t):
        for (t0, x0), (t1, x1) in zip(self.keys, self.keys[1:]):
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0)
                return x0 + (x1 - x0) * (u * u * (3 - 2 * u))
        return self.keys[-1][1]

    def cat(self, t):
        """(state, x, mir): stalking behind the dot, a pounce at 2.6 s and 4.9 s"""
        for t0 in (2.5, 5.0):
            if t0 <= t < t0 + .5:
                u = (t - t0) / .5
                x_from = self.dot(t0) - 28
                return 'leap', x_from + (self.dot(t0 + .5) - 14 - x_from) * u, False, u
            if t0 - .5 <= t < t0:
                return 'crouch', self.dot(t0) - 28, False, (t - t0 + .5) / .5
        lag = self.dot(max(0, t - .7)) - 30
        return 'walk', lag, False, 0

    def frame(self, f):
        t = f / FPS
        g = Image.new('RGB', (160, 106), C['wall'])
        gd = ImageDraw.Draw(g)
        # the wall: the shelf, a poster, the light bar
        gd.rectangle([0, 28, 160, 31], fill=C['walnut'])
        gd.line([0, 28, 160, 28], fill=C['walnut_hi'])
        gd.line([0, 32, 160, 32], fill=C['silver_l'])
        for x, h, col in ((64, 6, C['leaf']), (80, 4, C['leaf_d']), (98, 5, C['leaf'])):
            gd.rectangle([x, 28 - h, x + 6, 27], fill=C['walnut_l'])
            gd.ellipse([x - 3, 28 - h - 6, x + 9, 28 - h + 1], fill=col)
        # the monitor
        gd.rectangle([40, 42, 86, 70], fill=C['ink'])
        gd.rectangle([42, 44, 84, 68], fill=(0x2b, 0x37, 0x48))
        gd.rectangle([60, 70, 66, 78], fill=C['silver_d'])
        gd.rectangle([54, 78, 72, 80], fill=C['silver_d'])
        # the desk
        gd.rectangle([0, self.DESK, 160, self.DESK + 5], fill=C['walnut_l'])
        gd.line([0, self.DESK, 160, self.DESK], fill=C['walnut_hi'])
        gd.rectangle([0, self.DESK + 6, 160, 106], fill=C['walnut_d'])
        gd.rectangle([20, self.DESK - 3, 52, self.DESK - 1], fill=C['felt'])   # keyboard
        for x in range(22, 51, 3):
            gd.point((x, self.DESK - 3), fill=C['silver_l'])
        # the mug, wobbling when he gets close
        mx = 138
        st, cx_, mir, u = self.cat(t)
        near = st == 'leap' and abs(cx_ + 14 - mx) < 26
        tilt = math.sin(t * 30) * 1.2 if near or (5.0 <= t < 5.7) else 0
        mug = [(mx + tilt, self.DESK - 10), (mx + 9 + tilt, self.DESK - 10), (mx + 9, self.DESK - 1), (mx, self.DESK - 1)]
        gd.polygon(mug, fill=C['cream'])
        gd.rectangle([mx + 9, self.DESK - 8, mx + 11, self.DESK - 4], outline=C['cream'])
        gd.line([mx + tilt, self.DESK - 10, mx + 9 + tilt, self.DESK - 10], fill=C['walnut'])
        for k in range(2):
            sy = self.DESK - 13 - ((t * 7 + k * 4) % 8)
            gd.point((mx + 3 + k * 3 + int(math.sin(t * 3 + k) * 1.5), sy), fill=C['silver_l'])
        # Bubloo
        if st == 'walk':
            bubloo_walk(gd, int(cx_), self.DESK, int(t * 9))
        elif st == 'crouch':
            wig = 1 if int(t * 18) % 2 else 0
            body = SPR['DB_WB']
            top = self.DESK - 7
            tail(gd, [(cx_ + 1, top + 3), (cx_ - 3, top), (cx_ - 5 - wig, top - 3)])
            sprite(gd, body, int(cx_) + wig, top)
            sprite(gd, SPR['CAT_HEAD'], int(cx_) + 13, top - 8, sub=head_eyes('open'))
        else:
            hgt = math.sin(u * math.pi) * 18
            bubloo_leap(gd, int(cx_), int(self.DESK - 9 - hgt))
        dx = self.dot(t)
        im, p = canvas(C['wall'])
        grid_onto(g, im)
        sx, sy = dx * 2, self.DESK * 2 - 2
        p.disc(sx, sy, 4.2, mix(C['red'], C['wall'], .6))
        p.disc(sx, sy, 2.8, (0xe8, 0x2a, 0x1f))
        pounces = 6 + (t >= 3.0) + (t >= 5.5)
        if 3.0 <= t < 3.6 or 5.5 <= t < 6.1:
            slab(p, 160, 112, 'Pounce!', (t - (3.0 if t < 4 else 5.5)) / .16, bg=C['key'], fg=C['ink'], px=15)
        pix_header(p, 'Laser Pointer', f'{pounces} pounces')
        room_strip(p, [('wheel', 'move the dot'), ('play', 'wiggle it'), ('pair', 'shelf / floor')])
        return down(im)


# ===================================================================== 6. Treat Tin
class Safe:
    CX, CY, R = 118, 122, 74
    N = 40

    def __init__(self):
        self.code = [12, 31, 7]
        self.T = 6.4
        # the dial's number at the notch over time: right to 12, Play; left to 31 (slow near it)
        self.keys = [(0, 2.0), (1.1, 13.0), (1.5, 12.0), (2.1, 12.0), (3.3, 30.0 - 40), (3.9, 31.0 - 40),
                     (4.5, 31.0 - 40), (5.6, 7.0 - 80 + 40), (6.4, 7.0 - 80 + 40)]
        self.locks = [(1.7, 0), (4.1, 1)]

    def num(self, t):
        for (t0, a), (t1, b) in zip(self.keys, self.keys[1:]):
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0)
                return a + (b - a) * (u * u * (3 - 2 * u))
        return self.keys[-1][1]

    def frame(self, f):
        t = f / FPS
        im, p = canvas()
        cx, cy, R = self.CX, self.CY, self.R
        n = self.num(t)
        rot = -n / self.N * TAU                # the dial turns so n sits under the notch
        p.disc(cx + 4, cy + 4, R + 6, INK)
        p.disc(cx, cy, R + 6, BLUE)
        p.disc(cx, cy, R - 2, PAPER)
        for k in range(self.N):
            a = rot + k / self.N * TAU
            big = k % 5 == 0
            x0, y0 = pt(cx, cy, R - 4, a)
            x1, y1 = pt(cx, cy, R - (14 if big else 9), a)
            p.bar(x0, y0, x1, y1, 2.2 if big else 1.1, INK)
            if big:
                s = str(k)
                f2 = font(POSTER, 13)
                lx, ly = pt(cx, cy, R - 25, a)
                p.text(lx - tw(s, f2) / 2, ly + 5, s, f2, INK)
        p.disc(cx, cy, 22, INK)
        p.disc(cx, cy, 19, mix(INK, PAPER, .12))
        gx, gy = pt(cx, cy, 15, rot + .4)
        p.bar(cx, cy, gx, gy, 3, mix(INK, PAPER, .3))
        # the notch, and the clicks: louder (more rings) the nearer the number
        p.poly([(cx - 7, cy - R - 19), (cx + 7, cy - R - 19), (cx, cy - R - 7)], RED)
        k_cur = min(2, sum(1 for tl, _ in self.locks if t >= tl))
        target = [12, 31 - 40, 7 - 40][k_cur]
        d = abs(n - target)
        loud = 0 if d > 6 else 3 if d < .6 else 2 if d < 2.5 else 1
        if abs(self.num(t + 1 / FPS) - n) > .02:
            for k in range(loud):
                p.ring(cx + 14, cy - R - 13, 4 + k * 4, 1.4, mix(RED, PAPER, k * .25))
        # the combination, three slabs
        sx = 232
        for k in range(3):
            y = 64 + k * 40
            locked = [tl for tl, i in self.locks if i == k and t >= tl]
            cur = k == k_cur
            lean = .12
            box = [(sx + 6, y), (sx + 74, y), (sx + 68, y + 30), (sx, y + 30)]
            p.poly([(x + 3, y_ + 3) for x, y_ in box], INK)
            if locked:
                u = ease_back((t - locked[0]) / .25)
                p.poly(box, BLUE)
                s = f'{self.code[k]:02d}'
                f3 = font(POSTER, 22)
                p.text(sx + 37 - tw(s, f3) / 2, y + 24 - (1 - min(u, 1)) * 10, s, f3, PAPER)
            else:
                p.poly(box, PAPER)
                p.poly(box + [box[0]], None, outline=RED if cur else INK, width=1.6)
                f3 = font(POSTER, 22)
                s = f'{int(round(n)) % 40:02d}' if cur else '--'
                p.text(sx + 37 - tw(s, f3) / 2, y + 24, s, f3, RED if cur else RULE)
        # Bubloo, waiting by the tin
        g = Image.new('RGBA', (16, 13), (0, 0, 0, 0))
        sprite(ImageDraw.Draw(g), SPR['CAT_HEAD'], 0, 0, sub=head_eyes('up' if loud else 'open'))
        big = g.resize((16 * 3 * SS, 13 * 3 * SS), Image.NEAREST)
        p.paste(big, 262, 176 - (2 if loud == 3 else 0), big)
        header(p, 'Treat Tin', f'{k_cur}/3')
        strip(p, [('wheel', 'turn the dial'), ('play', 'set the number'), ('back', 'start over')])
        return down(im)


# ===================================================================== 7. Name That Tune
class Tune:
    def __init__(self, songs_):
        self.opts = songs_[:4]
        self.answer = 2
        self.T = 6.0
        # focus over time: 0 -> 1 -> 2 -> 3 -> 2, Play at 3.9
        self.keys = [(0, 0.0), (.9, 0.0), (1.2, 1.0), (1.9, 1.0), (2.2, 2.0), (2.7, 2.0), (3.0, 3.0),
                     (3.4, 3.0), (3.7, 2.0), (6.0, 2.0)]
        self.guess = 4.0

    def foc(self, t):
        for (t0, a), (t1, b) in zip(self.keys, self.keys[1:]):
            if t0 <= t <= t1:
                u = ease_out((t - t0) / (t1 - t0)) if t1 > t0 else 1
                return a + (b - a) * u
        return self.keys[-1][1]

    def frame(self, f):
        t = f / FPS
        im, p = canvas()
        fo = self.foc(t)
        # the clip: five seconds
        el = min(5.0, t * 1.15)
        p.rect(8, 40, W - 8, 44, RULE)
        p.rect(8, 40, 8 + (W - 16) * el / 5, 44, RED)
        fm = font(MONO, 11)
        p.text(W - 8 - tw(f'0:0{int(el)}', fm), 58, f'0:0{int(el)}', fm, SUB)
        p.text(8, 58, 'what is this?', font(BODY, 11, 'Bold'), INK)
        # four covers; the focused one comes forward and leans
        order = sorted(range(4), key=lambda k: -abs(k - fo))
        for k in order:
            d = k - fo
            near = max(0.0, 1 - abs(d))
            size = 58 + 22 * near
            x = 160 + d * 74
            y = 118 - 6 * near
            c = cov(self.opts[k][2], 80).resize((int(size * SS),) * 2, Image.LANCZOS)
            if near > .01:
                c = c.rotate(4 * near, resample=Image.BICUBIC, expand=False)
            sh = 2 + 3 * near
            p.rect(x - size / 2 + sh, y - size / 2 + sh, x + size / 2 + sh, y + size / 2 + sh, INK)
            p.paste(c, x - size / 2, y - size / 2)
            if t >= self.guess and k == self.answer:
                u = (t - self.guess) / .3
                p.ring(x, y, size * .72 + 6 * (1 - clamp01(u)), 3, BLUE)
        k = int(round(fo))
        title, artist, _ = self.opts[k]
        ft = font(POSTER, 14)
        p.text(160 - tw(fit(title, ft, 290), ft) / 2, 182, fit(title, ft, 290), ft, INK)
        fa = font(BODY, 11)
        p.text(160 - tw(fit(artist, fa, 290), fa) / 2, 198, fit(artist, fa, 290), fa, SUB)
        streak = 4 + (t >= self.guess)
        if t >= self.guess:
            slab(p, 160, 84, 'Got it', (t - self.guess) / .16)
        header(p, 'Name That Tune', f'x{streak}')
        lab, fl = 'streak, best 11', font(BODY, 10)
        p.text(W - 8 - tw(f'x{streak}', font(POSTER, 15), -.4) - 6 - tw(lab, fl), 17, lab, fl, SUB)
        strip(p, [('wheel', 'choose'), ('play', 'guess'), ('next', 'skip')])
        return down(im)


# ===================================================================== round two
# 8. Tube: Tempest, the game a spinner knob was made for, on the beat
class Tube:
    CX, CY, N = 160, 124, 12
    RO, RI = 84.0, 15.0
    CLIMB = .42                                # depth per second (1 = the rim)

    def __init__(self, song):
        self.song = song
        beat = 60 / 120
        rnd = random.Random(5)
        self.enemies = [(-1.6 + k * beat, rnd.randrange(self.N)) for k in range(16)]
        self.sim()

    def P(self, k, z):
        a = (k % self.N) / self.N * TAU
        return pt(self.CX, self.CY, self.RI + (self.RO - self.RI) * z ** 1.35, a)

    def sim(self):
        lane, shots, dead, last_fire = 0.0, [], {}, -1.0
        self.frames = []
        for f in range(int(6.0 * FPS)):
            t = f / FPS
            alive = [(t0, k) for t0, k in self.enemies
                     if (t0, k) not in dead and 0 <= (t - t0) * self.CLIMB < 1]
            if alive:
                t0, k = max(alive, key=lambda e: (t - e[0]))
                d = (k - lane + self.N / 2) % self.N - self.N / 2
                lane += max(-.45, min(.45, d))
                if abs(d) < .3 and t - last_fire > .16:
                    shots.append((t, int(round(lane)) % self.N))
                    last_fire = t
            for ts, k in shots:
                z = 1 - (t - ts) * 2.6
                for e in alive:
                    if e[1] == k and (t - e[0]) * self.CLIMB >= z and e not in dead:
                        dead[e] = t
            shots = [(ts, k) for ts, k in shots if 1 - (t - ts) * 2.6 > 0 and
                     not any(e[1] == k and dead.get(e) == t for e in self.enemies)]
            self.frames.append((lane, list(shots), dict(dead)))

    def frame(self, f):
        t = f / FPS
        lane, shots, dead = self.frames[f]
        im, p = canvas()
        cur = int(round(lane)) % self.N
        # the lane you're on, lit
        p.poly([self.P(cur, 0), self.P(cur + 1, 0), self.P(cur + 1, 1), self.P(cur, 1)], mix(BLUE, PAPER, .86))
        for z in (.35, .65):
            p.poly([self.P(k, z) for k in range(self.N)] + [self.P(0, z)], None, outline=RULE, width=1)
        for k in range(self.N):
            a, b = self.P(k, 0), self.P(k, 1)
            p.bar(a[0], a[1], b[0], b[1], 1.1, INK)
        p.poly([self.P(k, 1) for k in range(self.N)] + [self.P(0, 1)], None, outline=INK, width=2.2)
        p.poly([self.P(k, 0) for k in range(self.N)] + [self.P(0, 0)], None, outline=INK, width=1.2)
        beat = 60 / 120
        pulse = 1 + .1 * (1 - ease_out(((t + 1.6) % beat) / beat * 2.2))
        rr = (self.RI - 2) * pulse
        c = cov(self.song[2], 32).resize((int(rr * 2 * SS),) * 2, Image.LANCZOS)
        p.paste(c, self.CX - rr, self.CY - rr, disc_img(c))
        # what climbs: ink bow-ties the width of their lane
        for e in self.enemies:
            t0, k = e
            z = (t - t0) * self.CLIMB
            if e in dead:
                u = (t - dead[e]) / .4
                if 0 <= u < 1:
                    zc = (dead[e] - t0) * self.CLIMB
                    m = self.P(k + .5, zc)
                    for q in range(6):
                        a = q / 6 * TAU + .3
                        r = 4 + 14 * u
                        s = 2.6 * (1 - u)
                        x, y = m[0] + r * math.cos(a), m[1] + r * math.sin(a)
                        p.rect(x - s, y - s, x + s, y + s, INK)
                continue
            if not 0 <= z < 1:
                continue
            a0, a1 = self.P(k + .06, z), self.P(k + .94, z)
            b0, b1 = self.P(k + .06, min(1, z + .07)), self.P(k + .94, min(1, z + .07))
            m0, m1 = self.P(k + .5, max(0, z - .03)), self.P(k + .5, min(1, z + .1))
            p.poly([a0, m0, a1, b1, m1, b0], INK)
        for ts, k in shots:
            z = 1 - (t - ts) * 2.6
            a, b = self.P(k + .5, z), self.P(k + .5, min(1, z + .08))
            p.bar(a[0], a[1], b[0], b[1], 2.4, BLUE)
        # you: a red claw on the rim
        l, r_ = self.P(lane, 1), self.P(lane + 1, 1)
        o = pt(self.CX, self.CY, self.RO + 10, (lane + .5) / self.N * TAU)
        n = pt(self.CX, self.CY, self.RO - 4, (lane + .5) / self.N * TAU)
        p.poly([(x + 1.5, y + 1.5) for x, y in (l, o, r_, n)], INK)
        p.poly([l, o, r_, n], RED)
        score = 2400 + 150 * len(dead)
        header(p, 'Tube', f'{score:,}', f'{self.song[0]} — {self.song[1]}')
        strip(p, [('wheel', 'run the rim'), ('play', 'fire'), ('pair', 'clear the lane')])
        return down(im)


# 9. Capsule Machine: the wheel is the crank of a capsule toy; every capsule is a song
class Capsule:
    DX, DY, DR = 104, 86, 56                   # the dome
    CRX, CRY = 104, 172                        # the crank

    def __init__(self, song):
        self.song = song
        rnd = random.Random(12)
        cols = [BLUE, RED, (0xf2, 0xc2, 0x3a), (0x2f, 0x8f, 0x5b), INK, (0xe5, 0x8a, 0x9e)]
        self.caps = []
        tries = 0
        while len(self.caps) < 17 and tries < 4000:
            tries += 1
            x = self.DX + rnd.uniform(-46, 46)
            y = self.DY + rnd.uniform(-10, 44)
            if math.hypot(x - self.DX, y - self.DY) > self.DR - 12:
                continue
            if any(math.hypot(x - a, y - b) < 19 for a, b, _, _ in self.caps):
                continue
            self.caps.append((x, y, rnd.choice(cols), rnd.uniform(-.8, .8)))
        self.turn_end, self.drop, self.pop = 2.1, 2.1, 3.0

    def frame(self, f):
        t = f / FPS
        im, p = canvas()
        dx, dy, dr = self.DX, self.DY, self.DR
        # the body, the dome on it
        body = [(dx - 50, 140), (dx + 50, 140), (dx + 56, 206), (dx - 56, 206)]
        p.poly([(x + 4, y + 4) for x, y in body], INK)
        p.poly(body, BLUE)
        p.disc(dx + 4, dy + 4, dr + 3, INK)
        p.disc(dx, dy, dr + 3, INK)
        p.disc(dx, dy, dr, PAPER2)
        jig = math.sin(t * 40) * 1.2 if t < self.turn_end else 0
        for k, (x, y, col, a) in enumerate(self.caps):
            x += jig * (1 if k % 2 else -1)
            p.disc(x, y, 9.4, INK)
            p.disc(x, y, 8, PAPER)
            band(p, x, y, 0, 8, a - math.pi / 2, a + math.pi / 2, col, n=16)
        p.ring(dx, dy, dr - 10, 1.2, mix(PAPER2, PAPER, .5))
        # the crank: turns with the wheel, a click per detent
        ang = TAU * 1.0 * ease_out(min(1, t / self.turn_end)) - .3
        p.disc(self.CRX, self.CRY, 19, INK)
        p.disc(self.CRX, self.CRY, 17, PAPER)
        for k in range(12):
            a = ang + k / 12 * TAU
            x0, y0 = pt(self.CRX, self.CRY, 12, a)
            x1, y1 = pt(self.CRX, self.CRY, 16, a)
            p.bar(x0, y0, x1, y1, 1.2, SUB)
        hx, hy = pt(self.CRX, self.CRY, 26, ang)
        p.bar(self.CRX, self.CRY, hx, hy, 6, INK)
        p.disc(hx, hy, 6.5, RED)
        p.disc(self.CRX, self.CRY, 4, INK)
        if t < self.turn_end and int(t * 12) % 2 == 0:
            p.text(self.CRX + 28, self.CRY - 18, 'click', font(BODY, 9, 'Bold'), SUB)
        # the chute, and the capsule that comes out of it
        p.rect(dx + 30, 184, dx + 50, 202, INK)
        if t >= self.drop:
            u = t - self.drop
            x = dx + 40 + min(u, .5) * 90
            y = 194 + (math.sin(min(u / .5, 1) * math.pi) * -26 if u < .5 else math.sin(min((u - .5) / .3, 1) * math.pi) * -8)
            x = min(x, dx + 85)
            top = 0.0
            if t >= self.pop:
                top = ease_out((t - self.pop) / .3) * 30
            p.disc(x, y, 11, INK)
            p.disc(x, y, 9.5, PAPER)
            band(p, x, y - top, 0, 9.5, -math.pi / 2, math.pi / 2, RED, n=16)
        # the reveal: a tilted card with the song, Smash-spirit style
        if t >= self.pop + .15:
            u = (t - self.pop - .15) / .3
            s = ease_back(u)
            cx, cy, cw, ch = 248, 112, 112 * s, 150 * s
            card = [(cx - cw / 2 + 6, cy - ch / 2), (cx + cw / 2 + 6, cy - ch / 2),
                    (cx + cw / 2 - 6, cy + ch / 2), (cx - cw / 2 - 6, cy + ch / 2)]
            p.poly([(x + 4, y + 4) for x, y in card], INK)
            p.poly(card, PAPER)
            p.poly(card + [card[0]], None, outline=INK, width=2)
            if s > .9:
                c = cov(self.song[2], 86)
                p.paste(c, cx - 43 + 2, cy - 66)
                slab(p, cx, cy - 66, 'Never played', 1, bg=RED, px=10, lean=-.1)
                ft = font(POSTER, 11)
                lines = M.wrap(self.song[0], ft, 100, 2)
                for k, ln in enumerate(lines):
                    p.text(cx - tw(ln, ft) / 2, cy + 34 + k * 13, ln, ft, INK)
                fa = font(BODY, 9)
                a_ = fit(self.song[1], fa, 100)
                p.text(cx - tw(a_, fa) / 2, cy + 36 + len(lines) * 13, a_, fa, SUB)
        else:
            f9 = font(BODY, 10, 'Bold')
            for k, s in enumerate(('3 coins', 'one for every', '20 minutes', 'you listen')):
                p.text(196, 92 + k * 14, s, f9 if k == 0 else font(BODY, 10), INK if k == 0 else SUB)
            for k in range(3):
                p.disc(203 + k * 16, 70, 6.5, INK)
                p.disc(203 + k * 16, 70, 5, (0xf2, 0xc2, 0x3a))
        header(p, 'Capsule Machine', '23/150')
        strip(p, [('wheel', 'turn the crank'), ('play', 'open it'), ('menu', 'your album')])
        return down(im)


# 10. Bubloo Surf: the sea is the playing song's waveform
class Surf:
    def __init__(self, song):
        self.song = song

    def h(self, u):
        """the song's loudness as a wave: beats on top of a phrase swell"""
        beat = (math.sin(u * .23) * .5 + .5) ** 3
        return 9 + 13 * beat * (.7 + .3 * math.sin(u * .041)) + 1.2 * math.sin(u * .45)

    def frame(self, f):
        t = f / FPS
        g = Image.new('RGB', (160, 106))
        gd = ImageDraw.Draw(g)
        for k, col in enumerate(SKY):
            gd.rectangle([0, k * 12, 160, k * 12 + 12], fill=col)
        gd.ellipse([112, 18, 136, 42], fill=(0xf3, 0xd0, 0x8a))
        gd.rectangle([0, 38, 160, 106], fill=WATER_D)
        for k in range(10):
            x0 = (k * 29 + int(t * 4)) % 180 - 10
            gd.line([x0, 44 + k * 2, x0 + 5, 44 + k * 2], fill=WATER)
        scroll = t * 46
        surf = [70 - self.h(x + scroll) for x in range(161)]
        for x in range(160):
            y = int(surf[x])
            gd.line([x, y, x, 106], fill=WATER)
            gd.point((x, y), fill=C['cream'])
            gd.point((x, y + 1), fill=WATER_L)
            if (x + int(scroll)) % 11 == 0:
                gd.point((x, y + 6 + (x % 5)), fill=WATER_D)
        # notes to collect, floating over the crests
        got = 0
        for k in range(12):
            nx = k * 37 + 20 - scroll
            if nx < 38:
                got += 1
                continue
            if nx > 165:
                continue
            ny = 70 - self.h(nx + scroll) - 14 - (k % 3) * 4
            gd.rectangle([nx, ny, nx + 2, ny + 2], fill=C['ink'])
            gd.line([nx + 2, ny - 6, nx + 2, ny], fill=C['ink'])
            gd.line([nx + 3, ny - 6, nx + 5, ny - 4], fill=C['ink'])
        # Bubloo on his board, riding where the wheel leans him
        bx = 30
        hop = 0.0
        if 3.2 <= t < 3.9:
            hop = math.sin((t - 3.2) / .7 * math.pi) * 16
        by = surf[bx + 9] - hop
        slope = (surf[bx + 16] - surf[bx]) / 16
        a = math.atan(slope)
        board = [(bx - 2, by), (bx + 20, by + 22 * math.sin(a) * .5), (bx + 20, by + 2 + 22 * math.sin(a) * .5), (bx - 2, by + 2)]
        gd.polygon(board, fill=C['key'])
        gd.line([board[0], board[1]], fill=C['cream'])
        bubloo_sit(gd, bx - 3, int(by), eyes='shut' if hop > 4 else 'open', t=t)
        if hop > 0:
            for k in range(4):
                gd.point((bx + 4 + k * 4, int(surf[bx + 4 + k * 4]) - 2 - (k % 2)), fill=C['cream'])
        im, p = canvas(C['wall'])
        grid_onto(g, im)
        dist = int(180 + t * 9)
        pix_header(p, 'Bubloo Surf', f'{dist} m')
        fs = font(BODY, 10)
        p.text(9, 31, fit(f'{self.song[0]} — {self.song[1]}', fs, 230), fs, C['ink'])
        p.text(W - 9 - tw(f'{12 + got} notes', font(BODY, 10, 'Bold')), 31, f'{12 + got} notes', font(BODY, 10, 'Bold'), C['ink'])
        room_strip(p, [('wheel', 'lean into the wave'), ('play', 'hop')])
        return down(im)


# 11. Kite Day: the wheel is the spool; the wind comes on the bass
class Kite:
    def __init__(self):
        self.T = 6.8

    def band_y(self, t):
        return 22 if t < 3.6 else 22 - 10 * ease_out((t - 3.6) / 1.2)

    def kite_y(self, t):
        if t < 1.2:
            return 46 - 18 * ease_out(t / 1.2)
        if t < 4.0:
            return 28 + 1.5 * math.sin(t * 3)
        return 28 - 12 * ease_out((t - 4.0) / 1.6) + 1.5 * math.sin(t * 3)

    def frame(self, f):
        t = f / FPS
        g = Image.new('RGB', (160, 106), (0xbf, 0xd8, 0xdc))
        gd = ImageDraw.Draw(g)
        gd.rectangle([0, 0, 160, 14], fill=(0xb0, 0xcf, 0xd5))
        for k, (x0, y0, w) in enumerate(((10, 14, 22), (70, 8, 30), (128, 22, 18))):
            x = (x0 - t * (3 + k)) % 190 - 20
            gd.ellipse([x, y0, x + w, y0 + 6], fill=C['cream'])
            gd.ellipse([x + w * .25, y0 - 3, x + w * .75, y0 + 4], fill=C['cream'])
        # the wind: a band of streaks, thicker on the beat
        by = self.band_y(t)
        beat = 60 / 118
        gust = 1 - ((t % beat) / beat)
        for k in range(16):
            y = by + (k * 7) % 12
            x = (k * 41 - t * (90 + k * 7)) % 200 - 30
            L = 8 + int(10 * gust * (k % 2))
            gd.line([x, y, x + L, y], fill=(0xe8, 0xf1, 0xf1))
        # the hill and Bubloo on it
        gd.ellipse([-40, 76, 90, 140], fill=C['sage'])
        gd.ellipse([60, 88, 220, 150], fill=C['sage_d'])
        for x in range(4, 80, 7):
            gd.line([x, 80 + abs(x - 25) // 9, x + 1, 77 + abs(x - 25) // 9], fill=C['leaf'])
        bubloo_sit(gd, 14, 80, eyes='up', t=t)
        hand = (34, 70)
        kx = 112 + 6 * math.sin(t * 1.3)
        ky = self.kite_y(t)
        # the line, with a little sag
        pts = []
        for k in range(13):
            u = k / 12
            pts.append((hand[0] + (kx - hand[0]) * u, hand[1] + (ky + 8 - hand[1]) * u + math.sin(u * math.pi) * 6))
        gd.line(pts, fill=C['ink'], width=1)
        # the kite: four panels and its spars, a tail of bows
        top, left, right, bot = (kx, ky - 9), (kx - 7, ky - 1), (kx + 7, ky - 1), (kx, ky + 10)
        gd.polygon([top, left, (kx, ky - 1)], fill=C['red'])
        gd.polygon([top, right, (kx, ky - 1)], fill=C['cream'])
        gd.polygon([left, bot, (kx, ky - 1)], fill=C['cream'])
        gd.polygon([right, bot, (kx, ky - 1)], fill=C['red'])
        gd.line([top, bot], fill=C['walnut'])
        gd.line([left, right], fill=C['walnut'])
        tx, ty = bot
        for k in range(5):
            tx2 = tx - 3 - k * 3
            ty2 = ty + 3 + k * 2 + math.sin(t * 6 + k) * 2
            gd.line([tx, ty, tx2, ty2], fill=C['ink'])
            gd.rectangle([tx2 - 1, ty2 - 1, tx2 + 1, ty2], fill=C['key'] if k % 2 else C['red'])
            tx, ty = tx2, ty2
        im, p = canvas(C['wall'])
        grid_onto(g, im)
        # the altitude ruler, the wind band on it, the kite's mark
        rx = 300
        p.rect(rx, 40, rx + 10, 200, C['cream'])
        p.rect(rx, by * 2 - 2, rx + 10, by * 2 + 26, (0x9f, 0xc6, 0xcc))
        for k in range(9):
            p.rect(rx, 40 + k * 20, rx + 4, 41 + k * 20, C['ink'])
        p.poly([(rx - 8, ky * 2 - 5), (rx - 1, ky * 2), (rx - 8, ky * 2 + 5)], C['red'])
        # the spool, turning when line goes out
        sx, sy = 262, 182
        out_ = 3.9 <= t < 5.7
        a = (t - 3.9) * 8 if out_ else 0
        p.ring(sx, sy, 13, 3, C['ink'])
        p.disc(sx, sy, 9, C['key'])
        hx, hy = pt(sx, sy, 13, a)
        p.disc(hx, hy, 3.5, C['ink'])
        if out_:
            p.text(sx - 60, sy + 4, 'let out', font(BODY, 11, 'Bold'), C['ink'])
        alt = int((60 - ky) * 1.5)
        pix_header(p, 'Kite Day', f'{alt} m up')
        room_strip(p, [('wheel', 'wind in, let out'), ('play', 'tug'), ('pair', 'lean')])
        return down(im)


# 12. Where's Bubloo?: the wheel pans the room; follow the purr
class Hide:
    WIDE = 400                                  # the room, grid cells across
    SPOT = 262                                  # where he is (behind the curtain)

    def __init__(self):
        self.room = self.draw_room()

    def draw_room(self):
        g = Image.new('RGB', (self.WIDE, 106), C['wall'])
        gd = ImageDraw.Draw(g)
        gd.rectangle([0, 84, self.WIDE, 106], fill=C['felt'])
        gd.line([0, 84, self.WIDE, 84], fill=C['wall_sh'])
        for x in range(0, self.WIDE, 9):
            gd.point((x + (x // 9) % 3, 95), fill=C['felt'] if x % 2 else (0xa8, 0xa6, 0xa0))
        # the door
        gd.rectangle([12, 26, 44, 84], fill=C['cream'])
        gd.rectangle([14, 28, 42, 84], fill=(0xec, 0xe6, 0xda))
        gd.rectangle([18, 32, 38, 52], outline=(0xd8, 0xd0, 0xc0))
        gd.rectangle([18, 58, 38, 80], outline=(0xd8, 0xd0, 0xc0))
        gd.ellipse([36, 56, 39, 59], fill=C['key_d'])
        # the leather chair
        gd.rectangle([70, 50, 104, 70], fill=C['walnut_d'])
        gd.rectangle([66, 62, 108, 76], fill=(0xb2, 0x6a, 0x35))
        gd.rectangle([70, 50, 104, 66], fill=(0x91, 0x53, 0x28))
        gd.rectangle([74, 76, 77, 84], fill=C['ink'])
        gd.rectangle([97, 76, 100, 84], fill=C['ink'])
        # the desk wall: shelf, plants, clock, monitor, case
        gd.rectangle([130, 30, 226, 33], fill=C['walnut'])
        gd.line([130, 34, 226, 34], fill=C['silver_l'])
        for x, col in ((136, C['leaf']), (150, C['leaf_d'])):
            gd.rectangle([x, 24, x + 6, 29], fill=C['walnut_l'])
            gd.ellipse([x - 3, 17, x + 9, 25], fill=col)
        gd.ellipse([196, 18, 208, 30], fill=C['cream'])
        gd.line([202, 24, 202, 20], fill=C['ink'])
        gd.line([202, 24, 205, 24], fill=C['ink'])
        gd.rectangle([138, 46, 182, 70], fill=C['ink'])
        gd.rectangle([140, 48, 180, 68], fill=(0x2b, 0x37, 0x48))
        gd.rectangle([156, 70, 162, 74], fill=C['silver_d'])
        gd.rectangle([126, 74, 230, 78], fill=C['walnut_l'])
        gd.rectangle([128, 78, 132, 84], fill=C['walnut_d'])
        gd.rectangle([224, 78, 228, 84], fill=C['walnut_d'])
        gd.rectangle([196, 52, 216, 74], fill=C['silver'])
        for y in range(56, 72, 3):
            gd.line([200, y, 212, y], fill=C['silver_d'])
        # the window and its sage curtains (he's behind the right one)
        gd.rectangle([246, 22, 302, 66], fill=(0xbf, 0xd8, 0xdc))
        gd.rectangle([246, 22, 302, 24], fill=C['cream'])
        gd.line([274, 22, 274, 66], fill=C['cream'])
        gd.rectangle([238, 18, 310, 20], fill=C['walnut_d'])
        # posters
        gd.rectangle([330, 28, 352, 58], fill=(0x30, 0x2a, 0x2a))
        gd.rectangle([333, 31, 349, 55], fill=(0x8a, 0x2f, 0x24))
        gd.rectangle([360, 30, 380, 56], fill=(0x1f, 0x26, 0x33))
        gd.ellipse([365, 36, 375, 46], fill=C['cream'])
        # the pothos trailing down
        for k in range(10):
            gd.ellipse([388 + (k % 2) * 3, 20 + k * 6, 393 + (k % 2) * 3, 24 + k * 6], fill=C['leaf'] if k % 3 else C['leaf_d'])
        return g

    def cam(self, t):
        keys = [(0, 0.0), (1.8, 210.0), (2.3, 210.0), (3.2, 150.0), (3.6, 150.0), (4.0, 186.0), (6.4, 186.0)]
        for (t0, a), (t1, b) in zip(keys, keys[1:]):
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0) if t1 > t0 else 1
                return a + (b - a) * (u * u * (3 - 2 * u))
        return keys[-1][1]

    def frame(self, f):
        t = f / FPS
        found = 4.4
        g = self.room.copy()
        gd = ImageDraw.Draw(g)
        s = self.SPOT
        # the curtains; the right one bulges round him, his tail out under it
        sway = math.sin(t * 2) * .8
        gd.polygon([(240, 20), (252, 20), (250 + sway, 84), (238, 84)], fill=C['sage'])
        if t < found:
            gd.polygon([(296, 20), (308, 20), (312, 84), (290 - 3, 84)], fill=C['sage'])
            gd.line([(292, 84), (288, 87), (284 + math.sin(t * 5) * 2, 84 - 2)], fill=CATPAL['o'], width=4)
            gd.line([(292, 84), (288, 87), (284 + math.sin(t * 5) * 2, 84 - 2)], fill=CATPAL['d'], width=2)
        else:
            u = ease_out((t - found) / .4)
            gd.polygon([(296 + 8 * u, 20), (308, 20), (312, 84), (298 + 6 * u, 84)], fill=C['sage'])
            bubloo_sit(gd, 280, 84, eyes='shut' if int(t * 3) % 4 == 0 else 'open', t=t, mir=True)
            gd.polygon([(296 + 8 * u, 20), (308, 20), (312, 84), (306, 84)], fill=C['sage_d'])
        for x in (243, 247):
            gd.line([x, 21, x - 1, 83], fill=C['sage_d'])
        if t < found:
            for x in (299, 303):
                gd.line([x, 21, x + 2, 83], fill=C['sage_d'])
        cx = int(self.cam(t))
        view = g.crop((cx, 0, cx + 160, 106))
        im, p = canvas(C['wall'])
        grid_onto(view, im)
        # the purr: rings at the edge, more the nearer he is
        d = abs((cx + 80) - (s + 24))
        n = 0 if d > 120 else 1 if d > 70 else 2 if d > 30 else 3
        if t < found:
            for k in range(n):
                p.ring(W - 20, 120, 6 + k * 7, 2, mix(C['key'], C['wall'], k * .2))
            p.text(W - 44, 158, 'purr' if n else '', font(BODY, 10, 'Bold'), C['ink'])
        else:
            slab(p, 160, 64, 'Found him!', (t - found) / .16, bg=C['key'], fg=C['ink'], px=15)
        # the room's map: where you're looking
        mx0, mw = 96, 128
        p.rect(mx0, 40, mx0 + mw, 44, C['cream'])
        p.rect(mx0 + cx / self.WIDE * mw, 40, mx0 + (cx + 160) / self.WIDE * mw, 44, C['ink'])
        pix_header(p, "Where's Bubloo?", '4/5 today')
        room_strip(p, [('wheel', 'look around the room'), ('play', 'there!')])
        return down(im)


# 13. Beat Match: tune the next song to this one's beat, then drop it
class Match:
    def __init__(self, a, b):
        self.a, self.b = a, b
        self.bpm_a = 124.0
        self.drop = 3.8

    def pitch(self, t):
        keys = [(0, 3.2), (.6, 3.2), (1.6, -.8), (2.2, .4), (2.8, 0.0), (6.4, 0.0)]
        for (t0, x0), (t1, x1) in zip(keys, keys[1:]):
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0)
                return x0 + (x1 - x0) * ease_out(u)
        return 0.0

    def deck(self, p, cx, cy, song, ang, live):
        p.disc(cx + 3, cy + 3, 46, INK)
        p.disc(cx, cy, 46, (0x1b, 0x1b, 0x1a))
        for r in range(22, 44, 4):
            p.ring(cx, cy, r, .6, (0x2e, 0x2e, 0x2c))
        c = cov(song[2], 40).resize((int(36 * SS),) * 2, Image.LANCZOS).rotate(-math.degrees(ang), resample=Image.BICUBIC)
        p.paste(c, cx - 18, cy - 18, disc_img(c))
        p.disc(cx, cy, 2, PAPER)
        if live:
            p.rect(cx - 20, cy + 54, cx + 20, cy + 57, RED)

    def frame(self, f):
        t = f / FPS
        im, p = canvas()
        pitch = self.pitch(t)
        bpm_b = 128.0 * (1 + pitch / 100) * 124 / 128 * 128 / 124  # what B plays at
        bpm_b = 124.0 * (1 + pitch / 100)
        fade = clamp01((t - self.drop) / 1.4)
        self.deck(p, 72, 128, self.a, t * 3.5 * (1 - fade * .8), fade < .5)
        self.deck(p, 248, 128, self.b, t * 3.5 * bpm_b / self.bpm_a, fade >= .5)
        # two rows of beats running into the hairline; tuned, they meet it together
        y1, y2 = 52, 66
        p.rect(8, y1 - 5, W - 8, y1 + 5, PAPER2)
        p.rect(8, y2 - 5, W - 8, y2 + 5, PAPER2)
        for row, bpm, y, col in ((0, self.bpm_a, y1, INK), (1, bpm_b, y2, BLUE)):
            per = 60 / bpm
            sp = 70.0                            # px per second
            off = 0.13 if row else 0.0
            for k in range(-2, 12):
                tb = (math.floor((t - off) / per) + k) * per + off
                x = 160 + (tb - t) * sp
                if 8 <= x <= W - 8:
                    w = 3.2 if k % 4 == 0 else 1.8
                    p.rect(x - w / 2, y - 5, x + w / 2, y + 5, col)
        p.rect(159.2, y1 - 9, 160.8, y2 + 9, RED)
        sync = max(0, 100 - abs(pitch) * 30)
        f9 = font(BODY, 10, 'Bold')
        p.text(8, 86, f'{self.bpm_a:.0f} bpm', f9, INK)
        s_ = f'{bpm_b:.1f} bpm  {pitch:+.1f}%'
        p.text(W - 8 - tw(s_, f9), 86, s_, f9, BLUE)
        s2 = f'in sync {sync:.0f}%'
        p.text(160 - tw(s2, f9) / 2, 86, s2, f9, INK if sync < 99 else RED)
        # the crossfader
        p.rect(110, 196, 210, 199, RULE)
        kx = 112 + 96 * ease_out(fade)
        p.rect(kx - 5, 191, kx + 5, 204, INK)
        if t >= self.drop:
            slab(p, 160, 128, 'Drop', (t - self.drop) / .16, bg=RED)
        header(p, 'Beat Match', 'mix 7', f'next: {self.b[0]} — {self.b[1]}')
        strip(p, [('wheel', 'the next song’s tempo'), ('play', 'drop it'), ('pair', 'nudge')])
        return down(im)


# ===================================================================== output
GAMES = {
    'breaker': (lambda: Breaker(TOP[0]), 6.0, 'Cover Breaker', 'the wheel is the paddle; the bricks are the cover'),
    'orbit': (lambda: Orbit(TOP[1]), 5.6, 'Beat Orbit', 'walls close in on the beat; dash with Prev/Next'),
    'scratch': (lambda: Scratch(TOP[2]), 6.4, 'Scratch', 'turn the wheel the way the arrows point'),
    'fishing': (lambda: Fishing(FRESH[0] if FRESH else TOP[3]), 7.2, "Bubloo's Fishing Hole",
                'the wheel reels in songs you’ve never played'),
    'laser': (lambda: Laser(), 6.8, 'Laser Pointer', 'the wheel moves the dot; Bubloo pounces'),
    'safe': (lambda: Safe(), 6.4, 'Treat Tin', 'a combination dial you feel through the clicks'),
    'tune': (lambda: Tune(TOP[3:7]), 6.0, 'Name That Tune', 'five seconds; the wheel picks a cover'),
}
# round two, after the two the listener liked (Beat Orbit: the song is the level; the
# Fishing Hole: the wheel is a real tool, Bubloo, and new songs as the reward)
GAMES2 = {
    'tube': (lambda: Tube(TOP[4]), 6.0, 'Tube', 'Tempest on the beat: the wheel runs the rim'),
    'capsule': (lambda: Capsule(FRESH[1] if len(FRESH) > 1 else TOP[5]), 6.4, 'Capsule Machine',
                'crank the wheel; every capsule is a new song'),
    'surf': (lambda: Surf(TOP[2]), 6.0, 'Bubloo Surf', 'ride the song’s own waveform'),
    'kite': (lambda: Kite(), 6.8, 'Kite Day', 'the wheel is the spool; gusts come on the bass'),
    'hide': (lambda: Hide(), 6.4, "Where's Bubloo?", 'the wheel pans the room; follow the purr'),
    'match': (lambda: Match(TOP[1], TOP[6]), 6.4, 'Beat Match', 'tune the next song’s tempo, drop it'),
}
BATCHES = {'sheet': GAMES, 'sheet2': GAMES2}
ALL = {**GAMES, **GAMES2}


def gif(path, fr):
    big = [f.resize((W * 2, H * 2), Image.NEAREST) for f in fr]
    big[0].save(path, save_all=True, append_images=big[1:], duration=int(1000 / FPS), loop=0)


def sheet(stills, out='sheet'):
    g, cap = 12, 40
    cols = 4 if len(stills) > 6 else 3
    rows = (len(stills) + cols - 1) // cols
    im = Image.new('RGB', (cols * W + (cols + 1) * g, rows * (H + cap) + (rows + 1) * g), (0xd8, 0xd7, 0xd0))
    d = ImageDraw.Draw(im)
    ft = ImageFont.truetype(str(FD / POSTER), 15)
    fs = ImageFont.truetype(str(FD / BODY), 12)
    for k, (name, img) in enumerate(stills):
        r, c = divmod(k, cols)
        x, y = g + c * (W + g), g + r * (H + cap + g)
        im.paste(img, (x, y))
        _, _, title, line = ALL[name]
        d.text((x, y + H + 6), f'{k + 1}  {title}', font=ft, fill=INK)
        d.text((x, y + H + 25), line, font=fs, fill=SUB)
    im.save(OUT / f'{out}.png')


def main():
    """mock_games.py [name ...] | [--batch 1|2]"""
    OUT.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    if args[:1] == ['--batch']:
        names = list(GAMES if args[1] == '1' else GAMES2)
    else:
        names = [a for a in args if a in ALL] or list(GAMES)
    stills = []
    for name in names:
        make, secs, _, _ = ALL[name]
        g = make()
        fr = [g.frame(f) for f in range(int(secs * FPS))]
        gif(OUT / f'{name}.gif', fr)
        still = fr[int(len(fr) * .55)]
        still.save(OUT / f'{name}.png')
        stills.append((name, still))
        print(name, len(fr), 'frames')
    for out, batch in BATCHES.items():
        if names == list(batch):
            sheet(stills, out)


if __name__ == '__main__':
    main()
