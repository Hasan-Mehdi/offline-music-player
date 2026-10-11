#!/usr/bin/env python3
"""Precompute everything the "Night Service" ride film needs -> viz/transit/transit_data.json

Real data only, reusing the heavy stage cached by viz/film/build_data.py (_cache.npz).
The film is one continuous autoplay ride: three legs of the player's REAL formula
(alpha*sound + beta*co-play - artist cooldown, eps exploration), re-seeded twice by
text "request stops" (MuQ mood queries). Every stop gets a real audio clip + art.

Run from repo root:  python viz/transit/build_data.py
"""
from __future__ import annotations

import base64
import io
import json
import os
import random
import sqlite3
import subprocess
from collections import deque
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
ASSETS.mkdir(exist_ok=True)
CACHE = ROOT / "viz" / "film" / "_cache.npz"
FFMPEG = r"C:\Users\hasan\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
if not os.path.exists(FFMPEG):
    import shutil
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

random.seed(31)
np.random.seed(31)

# same genre order as the cache; muted inks for mid-tone paper (no purple, no neon)
DISTRICTS = [
    ("chiptune",       "#c08c0e"),
    ("future funk",    "#c04e70"),
    ("city pop",       "#c85d1c"),
    ("orchestral VGM", "#7c5127"),
    ("piano",          "#5f83a4"),
    ("hip-hop",        "#0f8871"),
    ("lo-fi / chill",  "#848f3f"),
    ("ambient",        "#8f8d80"),
    ("synth / EDM",    "#14789e"),
    ("rock / metal",   "#7e2b36"),
]
GNAMES = [x[0] for x in DISTRICTS]
MOODS = [  # order must match simm columns in the cache
    "nostalgic future funk at night",
    "epic orchestral boss battle",
    "cozy 8-bit town theme",
]
LEGS = (6, 5, 5)          # stops per leg (first stop of legs 2/3 = request target)


def asc(s, n=48):
    s = str(s).strip()
    s2 = s.encode("ascii", "ignore").decode().strip()
    s = s2 or s
    return s if len(s) <= n else s[: n - 1] + "…"


def l2(M):
    return M / (np.linalg.norm(M, axis=-1, keepdims=True) + 1e-9)


def load_meta():
    con = sqlite3.connect(str(ROOT / "data" / "library.db"))
    m = {}
    for vid, path, dur, art, tit in con.execute(
            "SELECT video_id, path, duration, artist, title FROM tracks"):
        m[vid] = {"path": path, "dur": float(dur or 0), "artist": art or "", "title": tit or ""}
    con.close()
    return m


def trimmed(pts):
    """Drop outlier lobes so a district centroid sits in its dense core."""
    for _ in range(2):
        med = np.median(pts, axis=0)
        dist = np.linalg.norm(pts - med, axis=1)
        keep = dist < 2.2 * (np.median(dist) + 1e-9)
        if keep.sum() >= max(30, int(0.55 * len(pts))):
            pts = pts[keep]
    return pts


def main():
    c = np.load(str(CACHE), allow_pickle=False)
    S, tx, ty = c["S"], c["tx"], c["ty"]
    g, per_genre, simm = c["g"], c["per_genre"], c["simm"]
    n = len(S)

    d = np.load(str(ROOT / "data" / "muq_embeddings.npz"), allow_pickle=False)
    ids = [str(x) for x in d["ids"]]
    arts = [str(x) for x in d["artists"]]
    tits = [str(x) for x in d["titles"]]
    X = l2(d["embeddings"].astype(np.float32))
    dims = X.shape[1]
    meta = load_meta()
    Xs = X[S]
    P = np.stack([tx, ty], 1)
    print(f"sample n={n}, dims={dims}, library={len(ids)}")

    def info(j):
        vid = ids[S[j]]
        return vid, arts[S[j]], tits[S[j]], meta.get(vid)

    # playable mask: the ride can only stop where a real file exists
    ok = np.zeros(n, dtype=bool)
    for j in range(n):
        _, _, _, mm = info(j)
        if mm and mm["dur"] >= 40 and os.path.exists(mm["path"]):
            ok[j] = True
    print(f"  playable on disk: {int(ok.sum())}/{n}")

    # ---- districts ----
    districts = []
    for gi, (name, col) in enumerate(DISTRICTS):
        idx = np.where(g == gi)[0]
        core = trimmed(P[idx])
        cen = np.median(core, axis=0)
        districts.append({"name": name, "color": col, "count": int(len(idx)),
                          "x": round(float(cen[0]), 4), "y": round(float(cen[1]), 4)})

    # ---- similarity matrix ----
    Sc = Xs @ Xs.T
    np.fill_diagonal(Sc, -2)

    # duplicate-upload pair
    dupe = None
    flat = np.argsort(-Sc, axis=None)[:400:2]
    for f in flat:
        i, j = int(f // n), int(f % n)
        sim = float(Sc[i, j])
        if sim < 0.975:
            break
        vi, ai, ti, _ = info(i)
        vj, aj, tj, _ = info(j)
        if vi != vj and (ai != aj or ti != tj):
            dupe = {"i": i, "j": j, "sim": round(sim, 4)}
            print(f"  dupe: {asc(ai,20)} - {asc(ti,26)}  ~=  {asc(tj,26)}  ({sim:.4f})")
            break

    # interchange (border station): strong second-district affinity
    top2 = np.argsort(-per_genre, axis=1)[:, :2]
    s1 = per_genre[np.arange(n), top2[:, 0]]
    s2 = per_genre[np.arange(n), top2[:, 1]]
    margin = s1 - s2
    iscore = s2 - 2.0 * margin
    inter = []
    seen_pairs = set()
    for j in np.argsort(-iscore):
        j = int(j)
        a, b = int(top2[j, 0]), int(top2[j, 1])
        if (min(a, b), max(a, b)) in seen_pairs or margin[j] > 0.02 or not ok[j]:
            continue
        seen_pairs.add((min(a, b), max(a, b)))
        inter.append({"i": j, "a": a, "b": b})
        if len(inter) == 3:
            break

    # ---- the ride: three legs of the real autoplay formula ----
    cfgp = ROOT / "data" / "autoplay_config.json"
    cfg = json.loads(cfgp.read_text()) if cfgp.exists() else {}
    alpha = cfg.get("alpha", 1.0); beta = cfg.get("beta", 0.6)
    cool = cfg.get("cooldown", 4); eps = cfg.get("epsilon", 0.12)
    print(f"  autoplay config: alpha={alpha} beta={beta} cooldown={cool} eps={eps}")
    sample_ids = [ids[v] for v in S]
    id2j = {vid: j for j, vid in enumerate(sample_ids)}

    def radio_members(vid):
        f = ROOT / "data" / "radio_cache" / f"{vid}.json"
        if not f.exists():
            return set()
        try:
            tr = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return set()
        return {t.get("videoId") for t in tr if t.get("videoId")} & id2j.keys()

    def mood_target(mi, wset):
        for j in np.argsort(-simm[:, mi]):
            j = int(j)
            if ok[j] and j not in wset:
                return j
        raise RuntimeError("no playable mood target")

    lofi = GNAMES.index("lo-fi / chill")
    seed_scores = per_genre[:, lofi].copy()
    seed_scores[~ok] = -9
    seed = int(np.argmax(seed_scores))

    stops, via = [seed], ["seed"]
    wset = {seed}
    recent = deque([arts[S[seed]]], maxlen=cool)
    cur = seed

    def advance():
        nonlocal cur
        score = alpha * Sc[cur]
        mem = {id2j[v] for v in radio_members(sample_ids[cur])}
        for j in mem:
            score[j] += beta
        score[~ok] = -1e9
        for j in wset:
            score[j] = -1e9
        for j in range(n):
            if arts[S[j]] in recent:
                score[j] -= 0.5
        if random.random() < eps:
            nxt = int(random.choice(np.argsort(-score)[:12]))
            v = "explore"
        else:
            nxt = int(np.argmax(score))
            v = "radio" if nxt in mem else "sound"
        stops.append(nxt); via.append(v); wset.add(nxt)
        recent.append(arts[S[nxt]]); cur = nxt

    requests = []                       # {stop: index-in-stops where reroute happens, text, matches, sims}
    for leg, count in enumerate(LEGS):
        if leg > 0:
            mi = leg - 1
            tgt = mood_target(mi, wset)
            order = np.argsort(-simm[:, mi])
            top = [int(x) for x in order[:5]]
            requests.append({
                "afterStop": len(stops) - 1, "text": MOODS[mi],
                "matches": top,
                "sims": [round(float(simm[j, mi]), 3) for j in top],
            })
            stops.append(tgt); via.append("request"); wset.add(tgt)
            recent.append(arts[S[tgt]]); cur = tgt
            count -= 1
        for _ in range(count if leg == 0 else count):
            advance()

    print("  ride districts: " + "->".join(GNAMES[int(g[j])][:7] for j in stops))
    print("  via: " + ",".join(via))

    # dupe pass-by: nearest stop on the ride
    if dupe:
        dists = [float(np.hypot(P[s, 0] - P[dupe["i"], 0], P[s, 1] - P[dupe["i"], 1]))
                 for s in stops]
        k = int(np.argmin(dists))
        dupe["nearStop"] = k
        dupe["nearDist"] = round(dists[k], 4)
        print(f"  dupe closest to stop {k} (d={dists[k]:.3f})")
    inter_keep = []
    for it in inter:
        dists = [float(np.hypot(P[s, 0] - P[it["i"], 0], P[s, 1] - P[it["i"], 1]))
                 for s in stops]
        k = int(np.argmin(dists))
        if dists[k] < 0.22:
            it["nearStop"] = k
            inter_keep.append(it)
    print(f"  interchanges near route: {len(inter_keep)}")

    # ---- clips + art for every stop (+ request-board rows get labels only) ----
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
        except Exception:
            return None

    def extract_clip(path, dur, out):
        start = min(max(28.0, dur * 0.33), max(1.0, dur - 8.0))
        cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
               "-ss", f"{start:.2f}", "-t", "6.5", "-i", path,
               "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "44100",
               "-af", "loudnorm=I=-15:TP=-1.5:LRA=11,afade=t=in:d=0.6,afade=t=out:st=5.9:d=0.6",
               "-c:a", "aac", "-b:a", "96k", str(out)]
        subprocess.run(cmd, check=True)
        return "data:audio/mp4;base64," + base64.b64encode(out.read_bytes()).decode()

    heroes = []
    print(f"extracting {len(stops)} stop clips ...")
    for k, j in enumerate(stops):
        vid, a, t, mm = info(j)
        try:
            clip = extract_clip(mm["path"], mm["dur"], ASSETS / f"clip_{vid}.m4a")
        except Exception as e:
            print(f"  ! clip fail {asc(a)}: {type(e).__name__}")
            clip = None
        heroes.append({"s": j, "id": vid, "artist": asc(a, 40), "title": asc(t, 46),
                       "genre": GNAMES[int(g[j])], "clip": clip,
                       "art": extract_art(mm["path"])})
        print(f"  [{k+1}/{len(stops)}] {asc(a,26)} - {asc(t,30)}")

    label_js = set(stops) | {m for r in requests for m in r["matches"]} \
        | {it["i"] for it in inter_keep}
    if dupe:
        label_js |= {dupe["i"], dupe["j"]}
    labels = {}
    for j in sorted(label_js):
        vid, a, t, mm = info(j)
        labels[str(j)] = [asc(a, 34), asc(t, 40)]

    data = {
        "n": n, "total": len(ids), "dims": dims,
        "districts": districts,
        "tx": [round(float(v), 4) for v in tx],
        "ty": [round(float(v), 4) for v in ty],
        "g": [int(v) for v in g],
        "stops": [int(v) for v in stops],
        "via": via,
        "legs": list(LEGS),
        "requests": requests,
        "cfg": {"alpha": alpha, "beta": beta, "cooldown": cool, "eps": eps},
        "inter": inter_keep,
        "dupe": dupe,
        "labels": labels,
        "heroes": heroes,
    }
    out = OUT / "transit_data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\nwrote {out}  ({out.stat().st_size/1e6:.2f} MB, {len(heroes)} stop clips)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
