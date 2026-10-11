#!/usr/bin/env python3
"""Precompute everything viz/coda's film needs -> viz/coda/coda_data.json + assets/.

"How Coda works" (see SCRIPT.md). Real data only, apart from the score bars in the
"each one gets a score" shot, which illustrate the terms:

  * covers.jpg      a 24x14 atlas of real embedded cover art (library sample, seeded)
  * hero            one real track (the V-Ron Media cover on the device screenshots): its
                    cover, plus its nearest and a far song, with all three centered MuQ
                    fingerprints in the hero's sorted order (similar songs follow its ramp)
  * cands.jpg       the 40 songs that sound closest to the hero (real neighbours)
  * lean            320 real fingerprints projected on (mean direction, top PC of the
                    residual), before and after centering, plus |mean| and random cosines
  * listens         every YouTube Music listen in the archived Takeout exports, per day
  * pairs.jpg       real holdout songs (first heard after 2026-07-26) beside random ones
  * engine3         firmware/host/build/test_engine3.exe is RUN here (86/86 ...)
  * code            line counts of Coda's C, per file, counted here
  * screens / boot  renders from the device code (docs/h2/c; the boot frames are split out
                    of docs/h2/boot/boot.gif, the approved animation)
  * themes          the mockup sheets in docs/h2/{menu,inner,pixel,room}, copied
  * web.png         the web player (node viz/coda/capture.js web, with server.py up)
  * clips           three songs the H2 itself has played (plays.source='h2'),
                    level-matched by the player's own r128 rule

Rebuild (repo root, Windows):
    .venv\\Scripts\\python viz\\coda\\build_data.py
    .venv\\Scripts\\python viz\\coda\\bundle.py         # -> coda_film.html (standalone)
    node viz\\coda\\capture.js render 30                # -> frames/ + audio_cues.json
    .venv\\Scripts\\python viz\\coda\\mux.py            # -> coda_film.mp4
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
ASSETS.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "scripts"))

FFMPEG = r"C:\Users\hasan\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
if not os.path.exists(FFMPEG):
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

DB = ROOT / "data" / "library.db"
EMB = ROOT / "data" / "muq_embeddings.npz"
SEED = 20261011

HERO_VID = "U2Rs8h-ShQ8"          # V-Ron Media, "You Can Always Come Home" (on c_now / c_wheel_a)
HOLDOUT_CUT = "2026-07-26"        # docs/EXPERIMENTS.md, the taste holdout

# songs the H2 played (plays where source='h2'), in film order
CLIPS = [
    # key,    video_id,      start s, seconds, film target LUFS
    ("pick",  "eBUp0hj3-jY", 0.0, 82.0, -18.0),    # Travel Journal, M&L Dream Team
    ("build", "KTKdhiy6gbM", 0.0, 240.0, -18.0),   # DPPt Underground, jazz arrangement
    ("boot",  "hRc_QTLPpyA", None, 240.0, -15.0),  # Polytope (start = the hit after ~61 s)
]
LOUDNESS_OFFSET_DB = 9.0      # player rule: R128 -23 reference retargeted to -14
MAKEUP_MAX = 12.0

SCREENS = ["c_now", "c_wheel_a", "c_wheel_a_spin", "c_menu", "c_explore", "c_search_typed",
           "c_osts", "c_genres", "c_now_station", "c_queue_ost", "c_now_night",
           "c_wheel_a_night", "c_artists", "c_settings_v2", "c_now_sheet"]

THEMES = [  # (docs/h2 path, asset name)
    ("menu/A@2x.png", "th_menu_a.png"), ("menu/B@2x.png", "th_menu_b.png"),
    ("menu/C@2x.png", "th_menu_c.png"),
    ("inner/now@2x.png", "th_inner_now.png"), ("inner/explore@2x.png", "th_inner_explore.png"),
    ("inner/library@2x.png", "th_inner_library.png"), ("inner/queue@2x.png", "th_inner_queue.png"),
    ("inner/settings@2x.png", "th_inner_settings.png"),
    ("pixel/jukebox_menu@2x.png", "th_px_jukebox.png"), ("pixel/toybox_menu@2x.png", "th_px_toybox.png"),
    ("pixel/deck_queue@2x.png", "th_px_deck.png"), ("pixel/crate_menu@2x.png", "th_px_crate.png"),
    ("pixel/receiver_menu@2x.png", "th_px_receiver.png"), ("pixel/room_now@2x.png", "th_px_room.png"),
    ("room/menu@2x.png", "th_room_menu.png"),
]


def p(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------- covers


def art_bytes(path):
    """Embedded cover art, the same route as server._extract_art."""
    from mutagen.flac import Picture
    from mutagen.oggopus import OggOpus
    try:
        b64 = (OggOpus(path).tags or {}).get("metadata_block_picture", [None])[0]
        return Picture(base64.b64decode(b64)).data if b64 else None
    except Exception:
        return None


def square(raw, px):
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    return im.resize((px, px), Image.LANCZOS)


def tile_of(con, vid, px):
    row = con.execute("SELECT path FROM tracks WHERE video_id=?", (vid,)).fetchone()
    if not row or not row[0] or not os.path.exists(row[0]):
        return None
    raw = art_bytes(row[0])
    if not raw:
        return None
    try:
        return square(raw, px)
    except Exception:
        return None


def atlas(tiles, cols, px, name):
    from PIL import Image
    rows = (len(tiles) + cols - 1) // cols
    im = Image.new("RGB", (cols * px, rows * px), (233, 230, 220))
    for i, t in enumerate(tiles):
        im.paste(t, ((i % cols) * px, (i // cols) * px))
    im.save(ASSETS / name, "JPEG", quality=84)


def build_covers(con, cols=24, rows=14, px=96):
    rng = np.random.default_rng(SEED)
    vids = [r[0] for r in con.execute("SELECT video_id FROM tracks ORDER BY video_id")]
    tiles, tried = [], 0
    for i in rng.permutation(len(vids)):
        if len(tiles) >= cols * rows:
            break
        tried += 1
        t = tile_of(con, vids[i], px)
        if t is not None:
            tiles.append(t)
    atlas(tiles, cols, px, "covers.jpg")
    p(f"covers: {len(tiles)} tiles from {tried} tried -> assets/covers.jpg")
    return {"file": "covers.jpg", "cols": cols, "rows": rows, "px": px, "n": len(tiles)}


# --------------------------------------------------------------------------- fingerprints


def load_emb(con):
    z = np.load(EMB, allow_pickle=True)
    ids = z["ids"]
    lib = {r[0] for r in con.execute("SELECT video_id FROM tracks")}
    keep = np.array([v in lib for v in ids])
    X = z["embeddings"][keep].astype(np.float64)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
    return X, ids[keep]


def build_lean(X):
    m = X.mean(0)
    mnorm = float(np.linalg.norm(m))
    rng = np.random.default_rng(SEED)
    a = rng.integers(0, len(X), 40000)
    b = rng.integers(0, len(X), 40000)
    ok = a != b
    raw_cos = float(np.mean(np.sum(X[a[ok]] * X[b[ok]], 1)))
    C = X - m
    C /= np.linalg.norm(C, axis=1, keepdims=True) + 1e-12
    cen_cos = float(np.mean(np.sum(C[a[ok]] * C[b[ok]], 1)))

    u1 = m / mnorm
    S = (X - m)[rng.choice(len(X), 8000, replace=False)]
    _, _, vt = np.linalg.svd(S, full_matrices=False)
    u2 = vt[0] - (vt[0] @ u1) * u1
    u2 /= np.linalg.norm(u2)
    pick = rng.choice(len(X), 320, replace=False)
    before = np.stack([X[pick] @ u1, X[pick] @ u2], 1)
    after = before - np.array([mnorm, 0.0])          # subtracting m moves every tip by -|m| u1
    p(f"lean: n={len(X)}  |mean|={mnorm:.3f}  random cos raw={raw_cos:.3f} centered={cen_cos:.3f}")
    return {
        "n": int(len(X)), "mean_norm": round(mnorm, 3),
        "random_cos_raw": round(raw_cos, 3), "random_cos_centered": round(cen_cos, 3),
        "before": np.round(before, 4).tolist(), "after": np.round(after, 4).tolist(),
        "dim": int(X.shape[1]),
    }, C


def norm_title(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())[:24]


def build_neighbours(con, C, vids):
    """The hero, its nearest song and a far one (centered cosine), and its 40 nearest."""
    hi = int(np.where(vids == HERO_VID)[0][0])
    cos = C @ C[hi]
    meta = {v: (t, a) for v, t, a in con.execute("SELECT video_id, title, artist FROM tracks")}
    ht = norm_title(meta[HERO_VID][0])
    seen, cands = {ht}, []
    for j in np.argsort(-cos):
        if j == hi:
            continue
        v = str(vids[j])
        nt = norm_title(meta[v][0])
        if nt in seen:
            continue
        t = tile_of(con, v, 96)
        if t is None:
            continue
        seen.add(nt)
        cands.append((v, float(cos[j]), t))
        if len(cands) >= 40:
            break
    atlas([c[2] for c in cands], 8, 96, "cands.jpg")
    near_v = cands[0][0]
    # far: a song near the 0.5th percentile of similarity, with a cover
    order = np.argsort(cos)
    far_v = None
    for j in order[int(len(order) * 0.005):]:
        if tile_of(con, str(vids[j]), 96) is not None:
            far_v = str(vids[j])
            break
    sort = np.argsort(C[hi])
    out = {}
    for key, v in (("hero", HERO_VID), ("near", near_v), ("far", far_v)):
        j = int(np.where(vids == v)[0][0])
        square(art_bytes(con.execute("SELECT path FROM tracks WHERE video_id=?", (v,)).fetchone()[0]),
               480).save(ASSETS / f"fp_{key}.jpg", "JPEG", quality=88)
        out[key] = {"vid": v, "title": meta[v][0], "artist": meta[v][1], "cos": round(float(cos[j]), 3),
                    "cover": f"fp_{key}.jpg", "sorted": np.round(C[j][sort], 4).tolist()}
    out["order"] = sort.tolist()       # rank r of the sorted bars sits at dimension order[r]
    p(f"neighbours: near {out['near']['cos']:+.3f} {out['near']['artist']} / "
      f"far {out['far']['cos']:+.3f} {out['far']['artist']}; {len(cands)} candidates")
    return out, {"file": "cands.jpg", "cols": 8, "px": 96, "n": len(cands),
                 "top": [{"title": meta[v][0], "artist": meta[v][1], "cos": round(c, 3)}
                         for v, c, _ in cands[:5]]}


# --------------------------------------------------------------------------- listens


def build_listens(con):
    import merge_takeout as mt
    paths = sorted(mt.EXPORTS.glob(f"*{mt.WATCH}"))
    seen, days, first = set(), Counter(), {}
    for path in paths:
        for vid, raw, t, _e in mt.music_events(mt.read_export(path)):
            if (vid, raw) in seen:
                continue
            seen.add((vid, raw))
            first[vid] = min(first.get(vid, t), t)
            days[t.astimezone(timezone.utc).date().isoformat()] += 1
    d0 = datetime.fromisoformat(min(days)).date()
    d1 = datetime.fromisoformat(max(days)).date()
    per = [days.get((d0.fromordinal(d0.toordinal() + i)).isoformat(), 0)
           for i in range((d1 - d0).days + 1)]
    p(f"listens: {len(seen)} listens / {len(first)} tracks, {d0} -> {d1}, busiest day {max(per)}")

    # holdout pairs: songs first heard after the cut (in the library) beside random songs
    cut = datetime.fromisoformat(HOLDOUT_CUT).replace(tzinfo=timezone.utc)
    lib = [r[0] for r in con.execute("SELECT video_id FROM tracks ORDER BY video_id")]
    libset = set(lib)
    later = sorted(v for v, t in first.items() if t > cut and v in libset)
    heard = set(first)
    rng = np.random.default_rng(SEED + 1)
    pos, neg = [], []
    for i in rng.permutation(len(later)):
        if len(pos) >= 12:
            break
        t = tile_of(con, later[i], 96)
        if t is not None:
            pos.append(t)
    for i in rng.permutation(len(lib)):
        if len(neg) >= 12:
            break
        if lib[i] in heard:
            continue
        t = tile_of(con, lib[i], 96)
        if t is not None:
            neg.append(t)
    atlas(pos + neg, 12, 96, "pairs.jpg")
    p(f"pairs: {len(pos)} later-found + {len(neg)} random ({len(later)} later-found in library now)")
    return {"total": len(seen), "tracks": len(first), "first": d0.isoformat(),
            "last": d1.isoformat(), "per_day": per}, {"file": "pairs.jpg", "n": len(pos)}


# --------------------------------------------------------------------------- device facts


def run_engine3():
    exe = ROOT / "firmware" / "host" / "build" / "test_engine3.exe"
    out = subprocess.run([str(exe), str(ROOT / "data" / "device_pack_v3"),
                          str(ROOT / "firmware" / "host" / "goldens_v3")],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=300)
    txt = out.stdout + out.stderr
    m = re.search(r"(\d+) cases, (\d+) picks match, (\d+) explored, worst score diff ([0-9.e+-]+)", txt)
    assert m and out.returncode == 0 and "OK" in txt, f"engine parity did not pass:\n{txt}"
    cases, match, explored, worst = int(m[1]), int(m[2]), int(m[3]), float(m[4])
    p(f"engine3: {match}/{cases} identical, {explored} explored, worst {worst:.2e}")
    return {"cases": cases, "match": match, "explored": explored, "worst": worst}


def code_lines():
    """Coda's C: the UI, the brain (core), the hardware layer (plat) and the Rockbox side."""
    groups = {"ui": "firmware/ui", "core": "firmware/core", "plat": "firmware/plat",
              "rockbox": "firmware/rockbox/coda"}
    files = []
    for g, d in groups.items():
        for f in sorted((ROOT / d).rglob("*")):
            if f.suffix in (".c", ".h"):
                n = sum(1 for _ in f.open(encoding="utf-8", errors="replace"))
                files.append({"name": f.name, "group": g, "lines": n})
    total = sum(f["lines"] for f in files)
    files.sort(key=lambda f: -f["lines"])
    p(f"code: {total} lines of C in {len(files)} files")
    return {"total": total, "files": files[:14], "n_files": len(files)}


def copy_png(src, dst):
    """the device shots are raw PNGs (~0.9 MB a frame); recompress, pixels unchanged."""
    from PIL import Image
    Image.open(src).convert("RGB").save(dst, "PNG", optimize=True)


def copy_media():
    h2 = ROOT / "docs" / "h2"
    for s in SCREENS:
        copy_png(h2 / "c" / f"{s}@2x.png", ASSETS / f"{s}.png")
    # the boot animation the user approved is boot.gif (rendered by the device code); the
    # boot_*.png frames beside it are left over from the first, rejected turntable version
    from PIL import Image, ImageSequence
    for f in ASSETS.glob("boot_*.png"):
        f.unlink()
    boot, boot_ms = [], []
    for i, fr in enumerate(ImageSequence.Iterator(Image.open(h2 / "boot" / "boot.gif"))):
        name = f"boot_{i:02d}.png"
        fr.convert("RGB").save(ASSETS / name, "PNG", optimize=True)
        boot.append(name)
        boot_ms.append(int(fr.info.get("duration", 33)))
    themes = []
    for src, name in THEMES:
        if (h2 / src).exists():
            copy_png(h2 / src, ASSETS / name)
            themes.append(name)
    assert (ASSETS / "web.png").exists(), "assets/web.png missing: run `node viz/coda/capture.js web` with server.py up"
    p(f"media: {len(SCREENS)} device renders, {len(boot)} boot frames ({sum(boot_ms)} ms), "
      f"{len(themes)} theme mockups")
    return {"screens": SCREENS, "boot": boot, "boot_ms": boot_ms, "themes": themes}


# --------------------------------------------------------------------------- audio


def lufs(path):
    err = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path), "-af",
                          "ebur128=framelog=quiet", "-f", "null", os.devnull],
                         stderr=subprocess.PIPE).stderr.decode("utf-8", "ignore")
    m = re.findall(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", err)
    return float(m[-1]) if m else None


def cut(path, start, seconds, gain, out, fade_in):
    af = (f"volume={gain:.4f},alimiter=limit=0.92,afade=t=in:d={fade_in:.2f},"
          f"afade=t=out:st={max(0.1, seconds - 0.8):.2f}:d=0.8")
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{start:.3f}", "-t", f"{seconds:.2f}", "-i", path,
                    "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "44100", "-af", af,
                    "-c:a", "aac", "-b:a", "128k", str(out)], check=True)


def find_hit(path, lo=59.0, hi=64.0):
    """Polytope drops after a near-silent breath at ~61 s: find that onset at 10 ms."""
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{lo}", "-t", f"{hi - lo}", "-i", path,
                          "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
                         stdout=subprocess.PIPE, check=True).stdout
    y = np.frombuffer(raw, "<f4")
    win = 80
    e = np.array([np.sqrt(np.mean(y[i:i + win] ** 2)) + 1e-9 for i in range(0, len(y) - win, win)])
    db = 20 * np.log10(e)
    quiet = int(np.argmin(db))                          # the breath
    rise = quiet + int(np.argmax(db[quiet:quiet + 60] > db.max() - 12))
    return lo + rise * win / 8000.0


def build_clips(con):
    out = {}
    for key, vid, start, secs, target in CLIPS:
        path, dur, g, title, artist = con.execute(
            "SELECT path, duration, r128_gain_db, title, artist FROM tracks WHERE video_id=?",
            (vid,)).fetchone()
        fade_in = 0.6
        if start is None:
            start = find_hit(path) - 0.03
            fade_in = 0.02
        secs = min(secs, float(dur) - start - 0.2)
        mult = 1.0 if g is None else min(1.0, 10 ** ((float(g) + LOUDNESS_OFFSET_DB) / 20.0))
        f = ASSETS / f"clip_{key}.m4a"
        cut(path, start, secs, mult, f, fade_in)
        got = lufs(f)
        makeup = 0.0
        if got is not None and got < target:
            makeup = min(MAKEUP_MAX, target - got)
            if makeup > 0.5:
                cut(path, start, secs, mult * 10 ** (makeup / 20.0), f, fade_in)
        got2 = lufs(f)
        p(f"clip {key}: {artist} - {title[:50]}  start {start:.2f}s  {secs:.0f}s  "
          f"makeup {makeup:+.1f} dB  {got2:.1f} LUFS")
        out[key] = {"file": f.name, "vid": vid, "title": title, "artist": artist,
                    "start": round(start, 3), "len": round(secs, 2), "lufs": got2}
    return out


# --------------------------------------------------------------------------- fonts


def fonts():
    """Archivo Black is copied; Archivo and Inconsolata are variable fonts here, so they
    are instanced at the weights the film uses and subset to Latin + the few symbols."""
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer
    from fontTools import subset
    src = ROOT / "firmware" / "assets" / "fonts"
    shutil.copyfile(ROOT / "viz" / "think" / "assets" / "archivo-black-400.woff2",
                    ASSETS / "archivo-black-400.woff2")
    text = ("".join(chr(c) for c in range(0x20, 0x7f)) +
            "\u2019\u2018\u201c\u201d\u2013\u2014\u2026\u00d7\u2192\u2190\u00b7\u2713\u2212\u00e9\u00a0")
    for name, file, wght in [("archivo-400", "Archivo.ttf", 400),
                             ("archivo-600", "Archivo.ttf", 600),
                             ("inconsolata-500", "Inconsolata.ttf", 500)]:
        f = TTFont(src / file)
        if "fvar" in f:
            axes = {a.axisTag: a.defaultValue for a in f["fvar"].axes}
            axes["wght"] = wght
            if "wdth" in axes:
                axes["wdth"] = 100
            f = instancer.instantiateVariableFont(f, axes)
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["kern", "liga", "tnum", "lnum"]
        sub = subset.Subsetter(opts)
        sub.populate(text=text)
        sub.subset(f)
        f.flavor = "woff2"
        f.save(ASSETS / f"{name}.woff2")
    p("fonts: archivo-black-400, archivo-400, archivo-600, inconsolata-500 (woff2)")


# --------------------------------------------------------------------------- main


def main():
    con = sqlite3.connect(DB)
    n_tracks = con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    X, vids = load_emb(con)
    lean, C = build_lean(X)
    fp, cands = build_neighbours(con, C, vids)
    listens, pairs = build_listens(con)
    data = {
        "built": datetime.now().isoformat(timespec="seconds"),
        "library_tracks": n_tracks,
        "fp": fp, "cands": cands,
        "covers": build_covers(con),
        "lean": lean,
        "listens": listens, "pairs": pairs,
        # docs/EXPERIMENTS.md "Autoplay engine v3" (scripts/eval_autoplay.py), quoted not re-run
        "v3": {"auc_raw": 0.539, "auc_centered": 0.669, "auc_random": 0.515,
               "holdout_tracks": 410, "holdout_cut": HOLDOUT_CUT, "explore_share": 0.18},
        "engine3": run_engine3(),
        "code": code_lines(),
        "device": {"name": "HiFi Walker H2", "price": "$124", "card_songs": 18388, "card_gb": 64,
                   "plugin_mb": 2, "os_heap_mb": 8, "audio_buf_mb": 19.8, "ram_mb": 32},
        "media": copy_media(),
        "clips": build_clips(con),
    }
    fonts()
    (OUT / "coda_data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    p(f"wrote coda_data.json ({(OUT / 'coda_data.json').stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main()
