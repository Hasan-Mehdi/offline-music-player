#!/usr/bin/env python3
"""Precompute everything the embedding-space film needs -> viz/film/film_data.json

Real data only:
  * 2D t-SNE "island" layout of a genre-balanced sample of the MuQ-MuLan library
  * a second "interpretable axes" layout (energetic-calm x electronic-acoustic)
  * per-track semantic genre via MuQ text anchors (the model was never told the genres)
  * an on-vibe autoplay walk through the sample (real content-similarity)
  * text->music mood queries: where a typed feeling lands + its true top matches
  * hero tracks: real 6s audio clips (ffmpeg, loudnorm) + real cover art, base64-inlined

Run from repo root:  python viz/film/build_data.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import random
import sqlite3
import subprocess
import sys
import warnings
from collections import Counter, deque
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
ASSETS.mkdir(exist_ok=True)
FFMPEG = r"C:\Users\hasan\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
if not os.path.exists(FFMPEG):
    import shutil
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

N_SAMPLE = 8000
random.seed(7)
np.random.seed(7)


def l2(M):
    return M / (np.linalg.norm(M, axis=-1, keepdims=True) + 1e-9)


def asc(s, n=48):
    s = str(s).strip()
    s2 = s.encode("ascii", "ignore").decode().strip()
    s = s2 or s
    return s if len(s) <= n else s[: n - 1] + "…"


# genre -> (text anchors, spot-ink hex).  muted riso palette, no neon, no purple.
GENRES = [
    ("chiptune",      ["upbeat 8-bit chiptune video game music", "nintendo NES famicom chiptune"], "#ffd23f"),
    ("future funk",   ["nostalgic future funk", "japanese future funk sample house"],             "#ff6f91"),
    ("city pop",      ["70s 80s japanese city pop", "mellow city pop groove"],                     "#ff9e64"),
    ("orchestral VGM",["epic orchestral video game soundtrack", "sweeping cinematic orchestral score"], "#4b8bff"),
    ("piano",         ["solo piano arrangement", "gentle emotional piano cover"],                  "#8ecae6"),
    ("hip-hop",       ["hard hitting hip hop rap with heavy beats", "trap rap vocals 808"],        "#2ec4b6"),
    ("lo-fi / chill", ["lo-fi hip hop chill beats to relax", "warm mellow lofi study"],            "#a3b565"),
    ("ambient",       ["slow ambient atmospheric drone", "calm spacious ambient soundscape"],      "#9aa7b0"),
    ("synth / EDM",   ["energetic electronic dance music synth", "synthwave retro synth arpeggio"],"#e08e45"),
    ("rock / metal",  ["distorted electric guitar rock band", "heavy metal riff drums"],           "#ef5366"),
]
GENRE_NAMES = [g[0] for g in GENRES]
GENRE_COLORS = [g[2] for g in GENRES]

AXIS_X = ("energetic intense fast aggressive music", "calm relaxing slow gentle music")
AXIS_Y = ("electronic synthetic digital chiptune synth music", "acoustic organic orchestral instrumental music")

MOODS = [
    ("nostalgic future funk at night", "future funk"),
    ("epic orchestral boss battle", "orchestral VGM"),
    ("cozy 8-bit town theme", "chiptune"),
]


def load_meta():
    con = sqlite3.connect(str(ROOT / "data" / "library.db"))
    m = {}
    for vid, path, dur, art, tit in con.execute(
        "SELECT video_id, path, duration, artist, title FROM tracks"):
        m[vid] = {"path": path, "dur": float(dur or 0), "artist": art or "", "title": tit or ""}
    con.close()
    return m


def compute_heavy(force=False):
    """Slow stage (embeddings sample + MuQ text anchors + t-SNE). Cached to _cache.npz."""
    cache = OUT / "_cache.npz"
    if cache.exists() and not force:
        print("loading cached heavy stage (_cache.npz) ...")
        c = np.load(str(cache), allow_pickle=False)
        return (c["S"], c["tx"], c["ty"], c["axn"], c["ayn"],
                c["g"], c["per_genre"], c["simm"])

    print("loading embeddings + meta ...")
    d = np.load(str(ROOT / "data" / "muq_embeddings.npz"), allow_pickle=False)
    ids = [str(x) for x in d["ids"]]
    arts = [str(x) for x in d["artists"]]
    X = l2(d["embeddings"].astype(np.float32))
    meta = load_meta()
    print(f"  {len(ids)} embedded, {len(meta)} in library.db")

    elig = [i for i, v in enumerate(ids)
            if v in meta and meta[v]["dur"] >= 30 and arts[i].strip()]
    random.shuffle(elig)
    S = np.array(sorted(elig[:N_SAMPLE]))
    Xs = X[S]
    n = len(S)
    print(f"  sampled {n} tracks")

    print("loading MuQ-MuLan for text anchors ...")
    import torch
    from muq import MuQMuLan
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large").to(dev).eval()

    def enc(texts):
        with torch.no_grad():
            t = torch.nn.functional.normalize(model(texts=list(texts)), dim=-1)
        return t.cpu().numpy().astype(np.float32)

    genre_phrases, genre_owner = [], []
    for gi, (name, phrases, col) in enumerate(GENRES):
        for p in phrases:
            genre_phrases.append(p); genre_owner.append(gi)
    Tg = enc(genre_phrases)
    Ta = enc([AXIS_X[0], AXIS_X[1], AXIS_Y[0], AXIS_Y[1]])
    Tm = enc([m[0] for m in MOODS])
    print("  text anchors encoded")

    simg = Xs @ Tg.T
    owner = np.array(genre_owner)
    per_genre = np.full((n, len(GENRES)), -2.0, dtype=np.float32)
    for gi in range(len(GENRES)):
        per_genre[:, gi] = simg[:, np.where(owner == gi)[0]].max(1)
    g = per_genre.argmax(1).astype(np.int32)
    print("  genre mix:", {GENRE_NAMES[k]: int(v) for k, v in
                           sorted(Counter(g.tolist()).items())})

    ex, ey = Ta[0] - Ta[1], Ta[2] - Ta[3]

    def robust01(v):
        lo, hi = np.percentile(v, 2), np.percentile(v, 98)
        return (np.clip((v - lo) / (hi - lo + 1e-9), 0, 1) * 2 - 1).astype(np.float32)
    axn, ayn = robust01(Xs @ ex), robust01(Xs @ ey)
    simm = (Xs @ Tm.T).astype(np.float32)

    print("PCA -> t-SNE (this is the slow part) ...")
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE
    Xp = PCA(n_components=50, random_state=0).fit_transform(Xs)
    E = TSNE(n_components=2, perplexity=40, init="pca",
             learning_rate="auto", random_state=0).fit_transform(Xp)
    E = E - E.mean(0)
    E = E / (np.percentile(np.linalg.norm(E, axis=1), 99) + 1e-9) * 0.94
    tx, ty = E[:, 0].astype(np.float32), E[:, 1].astype(np.float32)
    print("  t-SNE done")

    np.savez(str(cache), S=S, tx=tx, ty=ty, axn=axn, ayn=ayn,
             g=g, per_genre=per_genre, simm=simm)
    return S, tx, ty, axn, ayn, g, per_genre, simm


def main():
    force = "--force" in sys.argv
    S, tx, ty, axn, ayn, g, per_genre, simm = compute_heavy(force=force)

    d = np.load(str(ROOT / "data" / "muq_embeddings.npz"), allow_pickle=False)
    ids = [str(x) for x in d["ids"]]
    arts = [str(x) for x in d["artists"]]
    tits = [str(x) for x in d["titles"]]
    X = l2(d["embeddings"].astype(np.float32))
    meta = load_meta()
    Xs = X[S]
    n = len(S)

    # ---- autoplay walk (real content similarity over the sample) ----
    ff_gi = GENRE_NAMES.index("future funk")
    seed = int(np.argmax(per_genre[:, ff_gi]))
    path, pset = [seed], {seed}
    recent = deque([arts[S[seed]]], maxlen=4)
    cur = seed
    Sc = Xs @ Xs.T
    for _ in range(17):
        score = Sc[cur].copy()
        for j in pset:
            score[j] = -9
        for j in range(n):
            if arts[S[j]] in recent:
                score[j] -= 0.35
        cand = np.argsort(-score)[:10]
        nxt = int(random.choice(cand)) if random.random() < 0.12 else int(cand[0])
        path.append(nxt); pset.add(nxt); recent.append(arts[S[nxt]]); cur = nxt
    print(f"  autoplay path: {len(path)} tracks")

    # ---- mood queries: landing point + true top matches (simm from cache) ----
    moods = []
    for mi, (text, _) in enumerate(MOODS):
        order = np.argsort(-simm[:, mi])
        top = [int(x) for x in order[:6]]
        land = order[:12]
        moods.append({
            "text": text,
            "x": float(tx[land].mean()), "y": float(ty[land].mean()),
            "matches": top,
            "sims": [round(float(simm[j, mi]), 3) for j in top],
        })
    print(f"  {len(moods)} mood queries")

    # ---- hero tracks: real audio clip + cover art ----
    def sample_meta(j):
        vid = S[j]
        return ids[vid], arts[vid], tits[vid], meta[ids[vid]]

    hero_js = []            # sample indices to feature
    seen = set()
    # one strong, on-disk exemplar per genre
    for gi in range(len(GENRES)):
        order = np.argsort(-per_genre[:, gi])
        for j in order[:40]:
            j = int(j)
            vid, a, t, mm = sample_meta(j)
            if j not in seen and os.path.exists(mm["path"]) and mm["dur"] >= 40:
                hero_js.append(j); seen.add(j); break
    # plus mood #1 top matches + a couple autoplay nodes
    for mi in range(len(moods)):
        for j in moods[mi]["matches"][:1]:
            if j not in seen:
                vid, a, t, mm = sample_meta(j)
                if os.path.exists(mm["path"]):
                    hero_js.append(j); seen.add(j)
    for j in [path[0], path[len(path)//2], path[-2]]:
        if j not in seen:
            vid, a, t, mm = sample_meta(j)
            if os.path.exists(mm["path"]):
                hero_js.append(j); seen.add(j)

    print(f"extracting {len(hero_js)} hero clips + art ...")
    try:
        from PIL import Image
        have_pil = True
    except Exception:
        have_pil = False
    from mutagen.oggopus import OggOpus
    from mutagen.flac import Picture

    def extract_art(path):
        try:
            f = OggOpus(path)
            b64 = f.get("metadata_block_picture", [None])[0]
            if not b64:
                return None
            pic = Picture(base64.b64decode(b64))
            raw = pic.data
            if have_pil:
                im = Image.open(io.BytesIO(raw)).convert("RGB")
                im.thumbnail((160, 160))
                buf = io.BytesIO(); im.save(buf, "JPEG", quality=82)
                raw = buf.getvalue()
            return "data:image/jpeg;base64," + base64.b64encode(raw).decode()
        except Exception as e:
            return None

    def extract_clip(path, dur, out):
        start = min(max(28.0, dur * 0.33), max(1.0, dur - 8.0))
        cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
               "-ss", f"{start:.2f}", "-t", "6.5", "-i", path,
               "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "44100",
               "-af", "loudnorm=I=-15:TP=-1.5:LRA=11,afade=t=in:d=0.35,afade=t=out:st=6.1:d=0.4",
               "-c:a", "aac", "-b:a", "96k", str(out)]
        subprocess.run(cmd, check=True)
        return "data:audio/mp4;base64," + base64.b64encode(out.read_bytes()).decode()

    heroes = []
    for k, j in enumerate(hero_js):
        vid, a, t, mm = sample_meta(j)
        try:
            clipfile = ASSETS / f"clip_{vid}.m4a"
            clip = extract_clip(mm["path"], mm["dur"], clipfile)
        except Exception as e:
            msg = f"  ! clip fail {asc(a)} - {asc(t)}: {type(e).__name__}"
            print(msg.encode("ascii", "ignore").decode())
            continue
        art = extract_art(mm["path"])
        heroes.append({
            "s": int(j), "id": vid, "artist": asc(a, 40), "title": asc(t, 46),
            "genre": GENRE_NAMES[g[j]], "clip": clip, "art": art,
        })
        print(f"  [{k+1}/{len(hero_js)}] {asc(a,26)} - {asc(t,30)}  ({GENRE_NAMES[g[j]]})")

    hero_by_s = {h["s"]: h for h in heroes}

    # labels: artist/title for hero + path + mood matches (bulk points stay anonymous)
    label_js = set(hero_js) | set(path) | {m for md in moods for m in md["matches"]}
    labels, artmap = {}, {}
    for j in label_js:
        j = int(j)
        vid, a, t, mm = sample_meta(j)
        labels[j] = [asc(a, 34), asc(t, 40)]
        hb = hero_by_s.get(j)
        art = hb["art"] if hb else extract_art(mm["path"])
        if art:
            artmap[str(j)] = art
    print(f"  cover art for {len(artmap)}/{len(label_js)} labeled points")

    data = {
        "n": n,
        "genres": [{"name": nm, "color": co} for nm, co in zip(GENRE_NAMES, GENRE_COLORS)],
        "tx": [round(float(v), 4) for v in tx],
        "ty": [round(float(v), 4) for v in ty],
        "ax": [round(float(v), 4) for v in axn],
        "ay": [round(float(v), 4) for v in ayn],
        "g":  [int(v) for v in g],
        "path": [int(v) for v in path],
        "moods": moods,
        "heroes": heroes,
        "labels": labels,
        "arts": artmap,
        "counts": {GENRE_NAMES[k]: int(v) for k, v in Counter(g.tolist()).items()},
        "total_library": len(ids),
    }
    out = OUT / "film_data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    mb = out.stat().st_size / 1e6
    print(f"\nwrote {out}  ({mb:.2f} MB, {len(heroes)} heroes with audio)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
