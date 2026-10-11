r"""Build the Coda-on-H2 app data that sits next to the device pack on the card (/.coda/).

  glyphs.cgp          all UI fonts in one file (Rockbox caps open files at 31, shared with
                      playback): "CGP1" u32 count, count x (u32 offset, u32 length), then
                      the CGF1 atlases in FONT_TABLE order.
  glyphs/<font>.cgf   the same atlases one per file (kept for inspection),
                      anti-aliased, subset to the characters
                      the library actually uses (titles/artists/albums/genres, upper-cased
                      too) + UI text. Latin from Archivo Black / Archivo / Inconsolata,
                      fallback Noto Sans JP then KR; compatibility forms that NFKC-fold to
                      one covered character (math-styled 𝓽𝓮𝔁𝓽, fullwidth) reuse that glyph.
  art.idx             u32 per pack track -> art slot (0xFFFFFFFF = no cover)
  art_<s|m|l>_<n>.bin slot-indexed square covers, RGB565 little-endian, ordered-dithered:
                      32px (list rows), 112px (wheel wedge texture), 168px (now playing).
                      Sharded below 2GB (Rockbox off_t is a signed 32-bit long):
                      shard n holds slots [n*cap, (n+1)*cap), cap = 2e9 // record bytes.
  artists.bin         u32 per artist: first pack index of each run of equal artist_off
                      (pack order is artist,title), so the device needn't scan tracks.bin
  plays.omp           the PC play log in the device's OMP1 format (firmware/core/omp_playlog.h)
  coda.json           what was built (sizes, counts, font table) -- read by humans + tests

CGF1 glyph atlas (little-endian):
  "CGF1" u16 px | i16 ascent | i16 descent | u16 0 | u32 n | u32 data_off
  n x 16B glyph table sorted by codepoint:
     u32 cp | i8 bx | i8 by (top, rel. baseline, negative = up) | u8 w | u8 h |
     u16 adv_q4 (advance * 16) | u16 0 | u32 bitmap offset (rel. data_off)
  4bpp alpha bitmaps, rows padded to whole bytes, high nibble = left pixel.
Glyphs are rendered 4x and box-downsampled, which is what the mockups
(firmware/tools/mock_h2.py) do, so device text matches them.

Usage:
  .venv\Scripts\python scripts\h2_assets.py --out D:\coda-h2card               # everything
  .venv\Scripts\python scripts\h2_assets.py --out D:\coda-h2card --only glyphs
"""
import argparse
import base64
import io
import json
import os
import sqlite3
import struct
import sys
import time
import unicodedata
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from h2_layout import short_id  # noqa: E402
from h2_sync import to_device_ts  # noqa: E402  (device clock = local wall time as UTC)

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "firmware" / "assets" / "fonts"
PACK = ROOT / "data" / "device_pack"
DB = ROOT / "data" / "library.db"

# Must match firmware/ui/theme.h FONT_* order.
FONT_TABLE = [
    # name        latin file                   wght  px   cjk fallback wght (None = no CJK)
    ("poster22", "ArchivoBlack-Regular.ttf", None, 22, 900),
    ("poster18", "ArchivoBlack-Regular.ttf", None, 18, 900),
    ("poster15", "ArchivoBlack-Regular.ttf", None, 15, 900),
    ("bold11",   "Archivo.ttf",              700,  11, 700),
    ("semi12",   "Archivo.ttf",              600,  12, 600),
    ("semi11",   "Archivo.ttf",              600,  11, 600),
    ("body10",   "Archivo.ttf",              450,  10, 500),
    ("mono10",   "Inconsolata.ttf",          500,  10, None),
    ("mono12",   "Inconsolata.ttf",          500,  12, None),
]
FALLBACKS = ["NotoSansJP.ttf", "NotoSansKR.ttf"]
UI_EXTRA = "…●·•×♥←→↑↓▲▼►◄ "
SS = 4

ART_SIZES = {"s": 32, "m": 112, "l": 168}
NO_SLOT = 0xFFFFFFFF
SHARD_BYTES = 2_000_000_000


def shard_cap(px):
    return SHARD_BYTES // (px * px * 2)


class ShardWriter:
    """Append fixed-size records, rolling to art_<k>_<n>.bin every shard_cap records."""
    def __init__(self, out_dir, k, px):
        self.out_dir, self.k, self.cap = out_dir, k, shard_cap(px)
        self.n, self.f = 0, None
        for old in out_dir.glob(f"art_{k}_*.bin"):
            old.unlink()

    def write(self, rec):
        if self.n % self.cap == 0:
            if self.f:
                self.f.close()
            self.f = open(self.out_dir / f"art_{self.k}_{self.n // self.cap}.bin", "wb")
        self.f.write(rec)
        self.n += 1

    def close(self):
        if self.f:
            self.f.close()


# ----------------------------------------------------------------------------- pack
def read_pack(pack_dir):
    meta = json.loads((pack_dir / "pack.json").read_text())
    n = meta["tracks"]
    ids = (pack_dir / "ids.bin").read_bytes()
    vids = [ids[i * 11:(i + 1) * 11].decode() for i in range(n)]
    strings = (pack_dir / "strings.bin").read_bytes()
    return meta, vids, strings


def pack_texts(strings):
    return [s.decode("utf-8", "replace") for s in strings.split(b"\0") if s]


# ----------------------------------------------------------------------------- glyphs
def _cmap(name):
    from fontTools.ttLib import TTFont
    return set(TTFont(FONTS / name, lazy=True).getBestCmap())


def _font(name, px, wght):
    f = ImageFont.truetype(str(FONTS / name), px * SS)
    try:
        n_axes = len(f.get_variation_axes())
    except OSError:            # static font (Archivo Black)
        n_axes = 0
    if n_axes and wght is not None:
        f.set_variation_by_axes([wght] + [100] * (n_axes - 1))   # (wght[, wdth=100])
    return f


def charset(texts):
    cs = set(UI_EXTRA)
    cs.update(chr(c) for c in range(0x20, 0x7F))
    cs.update("ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝàáâãäåæçèéêëìíîïñòóôõöøùúûüýÿ")
    for t in texts:
        cs.update(t)
        cs.update(t.upper())
    return sorted(ch for ch in cs if ch.isprintable() or ch == " ")


def render_font(spec, chars, cmaps, out_path):
    name, latin, wght, px, cjk_w = spec
    chain = [(latin, _font(latin, px, wght), cmaps[latin])]
    if cjk_w is not None:
        chain += [(fb, _font(fb, px, cjk_w), cmaps[fb]) for fb in FALLBACKS]
    asc, desc = chain[0][1].getmetrics()
    pad, base = px * 2, px * 3
    canvas_w, canvas_h = (px * 6) * SS, (px * 5) * SS
    glyphs, blob = [], bytearray()
    for ch in chars:
        cp = ord(ch)
        src = ch
        pick = next((f for _, f, cm in chain if cp in cm), None)
        if pick is None:
            folded = unicodedata.normalize("NFKC", ch)
            if len(folded) == 1:
                pick = next((f for _, f, cm in chain if ord(folded) in cm), None)
                src = folded
        if pick is None:
            continue
        adv = pick.getlength(src) / SS
        im = Image.new("L", (canvas_w, canvas_h), 0)
        ImageDraw.Draw(im).text((pad * SS, base * SS), src, font=pick, fill=255, anchor="ls")
        small = im.reduce(SS)
        bbox = small.getbbox()
        if bbox is None:            # space and friends: metrics only
            bx = by = w = h = 0
            bits = b""
        else:
            x0, y0, x1, y1 = bbox
            g = np.asarray(small.crop(bbox), dtype=np.uint16)
            h, w = g.shape
            q = ((g * 15 + 127) // 255).astype(np.uint8)
            if w % 2:
                q = np.pad(q, ((0, 0), (0, 1)))
            bits = ((q[:, 0::2] << 4) | q[:, 1::2]).astype(np.uint8).tobytes()
            bx, by = x0 - pad, y0 - base
        if not (-128 <= bx < 128 and -128 <= by < 128 and w < 256 and h < 256):
            continue
        glyphs.append((cp, bx, by, w, h, int(round(adv * 16)), len(blob)))
        blob += bits
    hdr_size = 4 + 2 * 4 + 4 + 4
    data_off = hdr_size + 16 * len(glyphs)
    with open(out_path, "wb") as f:
        f.write(b"CGF1")
        f.write(struct.pack("<HhhH", px, int(round(asc / SS)), int(round(desc / SS)), 0))
        f.write(struct.pack("<II", len(glyphs), data_off))
        for cp, bx, by, w, h, adv, off in glyphs:
            f.write(struct.pack("<IbbBBHHI", cp, bx, by, w, h, adv, 0, off))
        f.write(blob)
    return len(glyphs), len(blob)


def build_glyphs(out_dir, strings):
    texts = pack_texts(strings)
    chars = charset(texts)
    cmaps = {n: _cmap(n) for n in {s[1] for s in FONT_TABLE} | set(FALLBACKS)}
    gdir = out_dir / "glyphs"
    gdir.mkdir(parents=True, exist_ok=True)
    report = {}
    latin_only = [c for c in chars if ord(c) < 0x2000 or c in UI_EXTRA]
    blobs = []
    for spec in FONT_TABLE:
        t0 = time.time()
        use = chars if spec[4] is not None else latin_only
        n, nb = render_font(spec, use, cmaps, gdir / f"{spec[0]}.cgf")
        blobs.append((gdir / f"{spec[0]}.cgf").read_bytes())
        report[spec[0]] = {"glyphs": n, "bitmap_bytes": nb}
        print(f"  {spec[0]:9s} {n:5d} glyphs {nb / 1024:7.1f} KiB  ({time.time() - t0:.1f}s)")
    head = 8 + 8 * len(blobs)
    with open(out_dir / "glyphs.cgp", "wb") as f:
        f.write(b"CGP1" + struct.pack("<I", len(blobs)))
        off = head
        for b in blobs:
            f.write(struct.pack("<II", off, len(b)))
            off += len(b)
        for b in blobs:
            f.write(b)
    return report


# ----------------------------------------------------------------------------- art
BAYER4 = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
                   dtype=np.float32) + 0.5) / 16.0 - 0.5


def to_rgb565(im):
    """Ordered-dithered RGB565, little-endian bytes."""
    a = np.asarray(im, dtype=np.float32)
    h, w, _ = a.shape
    th = np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]
    r = np.clip(np.floor((a[..., 0] + th * 8) / 8 + 0.5), 0, 31).astype(np.uint16)
    g = np.clip(np.floor((a[..., 1] + th * 4) / 4 + 0.5), 0, 63).astype(np.uint16)
    b = np.clip(np.floor((a[..., 2] + th * 8) / 8 + 0.5), 0, 31).astype(np.uint16)
    return ((r << 11) | (g << 5) | b).astype("<u2").tobytes()


def _art_job(args):
    i, path = args
    try:
        import mutagen
        from mutagen.flac import Picture
        f = mutagen.File(path)
        pics = (f.tags or {}).get("metadata_block_picture", []) if f is not None else []
        if not pics:
            return i, None
        im = Image.open(io.BytesIO(Picture(base64.b64decode(pics[0])).data)).convert("RGB")
        w, h = im.size
        s = min(w, h)
        im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
        return i, {k: to_rgb565(im.resize((px, px), Image.LANCZOS)) for k, px in ART_SIZES.items()}
    except Exception:
        return i, None


def build_art(out_dir, vids, limit_to=None, workers=None):
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    path_of = {short_id(v): p for v, p in con.execute("SELECT video_id, path FROM tracks")}
    con.close()
    jobs = [(i, path_of[v]) for i, v in enumerate(vids) if v in path_of
            and (limit_to is None or i in limit_to)]
    slots = np.full(len(vids), NO_SLOT, dtype="<u4")
    files = {k: ShardWriter(out_dir, k, px) for k, px in ART_SIZES.items()}
    slot, t0 = 0, time.time()
    with Pool(workers or max(1, os.cpu_count() - 2)) as pool:
        for n_done, (i, recs) in enumerate(pool.imap_unordered(_art_job, jobs, chunksize=16), 1):
            if recs:
                for k, f in files.items():
                    f.write(recs[k])
                slots[i] = slot
                slot += 1
            if n_done % 2000 == 0:
                rate = n_done / (time.time() - t0)
                print(f"  art {n_done}/{len(jobs)}  {rate:.0f}/s  eta {(len(jobs) - n_done) / rate / 60:.1f} min",
                      flush=True)
    for f in files.values():
        f.close()
    (out_dir / "art.idx").write_bytes(slots.tobytes())
    print(f"  art: {slot} covers of {len(vids)} tracks ({time.time() - t0:.0f}s)")
    return {"covers": int(slot), "sizes": ART_SIZES,
            "shard_cap": {k: shard_cap(px) for k, px in ART_SIZES.items()}}


# ----------------------------------------------------------------------------- artists
def build_artists(out_dir, pack_dir, n):
    rec = np.fromfile(pack_dir / "tracks.bin", dtype="<u4").reshape(n, 6)
    artist = rec[:, 2]
    starts = np.flatnonzero(np.r_[True, artist[1:] != artist[:-1]]).astype("<u4")
    (out_dir / "artists.bin").write_bytes(starts.tobytes())
    print(f"  artists: {len(starts)} runs")
    return {"artists": int(len(starts))}


# ----------------------------------------------------------------------------- plays
EVENTS = {"play": 0, "complete": 1, "skip": 2, "like": 3, "dislike": 4, "peek": 5, "unlike": 6}


def build_plays(out_dir, vids):
    idx = {v: i for i, v in enumerate(vids)}
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    rows = con.execute("SELECT video_id, ts, event, seconds FROM plays ORDER BY ts, rowid").fetchall()
    con.close()
    out = bytearray(b"OMP1")
    kept = 0
    for vid, ts, ev, sec in rows:
        vid = short_id(vid)
        if vid in idx and ev in EVENTS and ts is not None:
            out += struct.pack("<dIfB3x", to_device_ts(float(ts)), idx[vid],
                               -1.0 if sec is None else float(sec), EVENTS[ev])
            kept += 1
    (out_dir / "plays.omp").write_bytes(bytes(out))
    print(f"  plays: {kept}/{len(rows)} events")
    return {"events": kept}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="card root (writes <out>/.coda/)")
    ap.add_argument("--pack", default=str(PACK))
    ap.add_argument("--only", choices=["glyphs", "art", "plays", "artists"], action="append")
    ap.add_argument("--art-limit", type=int, default=0, help="dev: only the first N played/random tracks")
    args = ap.parse_args()
    out_dir = Path(args.out) / ".coda"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta, vids, strings = read_pack(Path(args.pack))
    print(f"pack: {meta['tracks']} tracks, built {meta['built']}")
    report = {"pack_built": meta["built"], "tracks": meta["tracks"],
              "fonts": [s[0] for s in FONT_TABLE]}
    todo = args.only or ["glyphs", "plays", "artists", "art"]
    if "glyphs" in todo:
        report["glyphs"] = build_glyphs(out_dir, strings)
    if "plays" in todo:
        report["plays"] = build_plays(out_dir, vids)
    if "artists" in todo:
        report["artists"] = build_artists(out_dir, Path(args.pack), meta["tracks"])
    if "art" in todo:
        limit = None
        if args.art_limit:
            rng = np.random.default_rng(1)
            limit = set(rng.choice(len(vids), size=min(args.art_limit, len(vids)), replace=False).tolist())
        report["art"] = build_art(out_dir, vids, limit)
    rp = out_dir / "coda.json"
    old = json.loads(rp.read_text()) if rp.exists() else {}
    old.update(report)
    rp.write_text(json.dumps(old, indent=1))
    print("ok ->", out_dir)


if __name__ == "__main__":
    main()
