#!/usr/bin/env python3
"""Tune autoplay weights. Sweeps (beta, cooldown, epsilon) over a grid, generates
playlists from several seeds, and scores each config on a smoothness/diversity/
exploration objective. Writes the best config to data/autoplay_config.json.

  smoothness  = mean cosine between consecutive tracks (want a moderate band ~0.5)
  diversity   = unique artists / length
  coverage    = unique clusters visited / length (uses data/clusters.csv if present)
"""
from __future__ import annotations

import csv
import json
import random
from collections import deque
from pathlib import Path

import numpy as np

NPZ = "data/muq_embeddings.npz"
CACHE = Path("data/radio_cache")
random.seed(0)


def l2(M):
    return M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)


d = np.load(NPZ, allow_pickle=False)
X = l2(d["embeddings"].astype(np.float64))
ids = list(d["ids"])
arts = [str(a) for a in d["artists"]]
n = len(ids)
idset = set(ids)

clusters = {}
if Path("data/clusters.csv").exists():
    for r in csv.DictReader(open("data/clusters.csv", encoding="utf-8-sig")):
        clusters[r["video_id"]] = r["cluster"]

members = {}
for s in ids:
    f = CACHE / f"{s}.json"
    if f.exists():
        try:
            tr = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        members[s] = {t.get("videoId") for t in tr if t.get("videoId")} & idset


def autoplay(start, N, beta, cooldown, eps):
    played, pset = [start], {start}
    recent = deque([arts[start]], maxlen=cooldown)
    cur = start
    for _ in range(N - 1):
        score = (X @ X[cur]).copy()
        if members.get(ids[cur]):
            mem = members[ids[cur]]
            for j in range(n):
                if ids[j] in mem:
                    score[j] += beta
        for j in pset:
            score[j] = -1e9
        for j in range(n):
            if arts[j] in recent:
                score[j] -= 0.5
        nxt = int(random.choice(np.argsort(-score)[:12])) if random.random() < eps else int(np.argmax(score))
        played.append(nxt); pset.add(nxt); recent.append(arts[nxt]); cur = nxt
    return played


def metrics(path):
    trans = float(np.mean([X[path[i]] @ X[path[i + 1]] for i in range(len(path) - 1)]))
    adiv = len({arts[i] for i in path}) / len(path)
    cdiv = (len({clusters.get(ids[i]) for i in path}) / len(path)) if clusters else adiv
    return trans, adiv, cdiv


def main():
    seeds = random.sample(range(n), min(8, n))
    grid = [(b, cd, ep) for b in (0.0, 0.3, 0.6, 1.0) for cd in (2, 4, 6) for ep in (0.0, 0.1, 0.2)]
    rows = []
    for (b, cd, ep) in grid:
        ms = [metrics(autoplay(s, 16, b, cd, ep)) for s in seeds]
        trans, adiv, cdiv = (float(np.mean([m[k] for m in ms])) for k in range(3))
        smooth = 1 - abs(np.clip(trans, 0, 1) - 0.5) * 2          # peaks at 0.5
        obj = 0.5 * smooth + 0.3 * adiv + 0.2 * cdiv
        rows.append((obj, trans, adiv, cdiv, b, cd, ep))
    rows.sort(reverse=True)
    print(f"{'obj':>5}{'smooth':>8}{'adiv':>6}{'cdiv':>6}   beta cd eps")
    for r in rows[:10]:
        print(f"{r[0]:5.2f}{r[1]:8.2f}{r[2]:6.2f}{r[3]:6.2f}    {r[4]:.1f}  {r[5]}  {r[6]}")
    best = rows[0]
    cfg = {"alpha": 1.0, "beta": best[4], "cooldown": best[5], "epsilon": best[6]}
    Path("data/autoplay_config.json").write_text(json.dumps(cfg, indent=2))
    print("\nbest ->", cfg, "(written to data/autoplay_config.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
