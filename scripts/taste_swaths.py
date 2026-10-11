#!/usr/bin/env python3
"""Taste swaths — which big stretches of the library aren't your taste. READ-ONLY.

Every unheard library track gets a "like you" score from two signals on centered MuQ:
  * taste   cosine to your listening-history centroid (log1p(plays) x 1-year half-life,
            autoplay's taste profile)
  * near    similarity-weighted share of its 50 nearest tracks that you've played
averaged as ranks. A track whose artist you've played (YouTube Music history or the
player) is never flagged, whatever it scores — counting the credits in its title too
("My Mind (feat. Vxlious)", "PE$O PETE x SHOFU - GAME OVER!"). Nor is anything matching
a line of data/taste_keep.txt (regexes over "artist - title": styles you want kept
that the history doesn't show yet, e.g. anime rap), or listed by id in
data/taste_keep_ids.txt (tracks hand-picked back out of a purge).

Holdout (--validate; cuts 30/60/90/120 days before the export's newest listen, positives =
library tracks first heard after the cut):

  tier (score percentile among unheard, artist never played) | share of the unheard pool | share of the new listens
  10                                                         | 8.5%                      | 0.0-0.2%
  20                                                         | 16.4%                     | 1.4-1.9%
  30                                                         | 24%                       | 3.1-3.6%

The artist guard is what makes it trustworthy: tracks by artists you'd already played
are a third of the unheard pool and take two thirds of the new listens. Sound alone put
Night Tempo, 2 Mello and AZALI tracks in the bottom tier. Mixtures of per-style centroids
did worse than the single centroid (AUC .53-.58 vs .64-.69).

Flagged tracks are grouped for reading: 400 k-means sound regions over the whole library,
regions merged into families by centroid similarity.

Outputs:
  data/taste_swaths.csv   one row per flagged track: family, tier, percentile, artist,
                          title, genre, MB, path (feed a chosen subset to purge_apply.py)
  terminal                families by size: tiers, GB, top artists, sample titles

Usage:
  .venv\\Scripts\\python scripts\\taste_swaths.py [--tier 30] [--validate]
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.stats import rankdata
from sklearn.cluster import MiniBatchKMeans

sys.path.insert(0, str(Path(__file__).resolve().parent))
import personalize  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "library.db"
NPZ = ROOT / "data" / "muq_embeddings.npz"
LISTENS = ROOT / "data" / "listens.csv"
OUT_CSV = ROOT / "data" / "taste_swaths.csv"
KEEP_FILE = ROOT / "data" / "taste_keep.txt"
KEEP_IDS = ROOT / "data" / "taste_keep_ids.txt"

NEAR_K = 50
REGIONS = 400
FAMILY_DIST = 0.55        # cosine distance between region centroids that still merges
TIERS = (10, 20, 30)
HALFLIFE_DAYS = 365.0


def norm_artist(a):
    a = (a or "").lower().replace(" - topic", "")
    return re.sub(r"[^0-9a-z぀-ヿ一-鿿가-힯]+", "", a)


def artist_parts(a):
    """'GameChops, Mipsick & Coffee Date feat. X' -> each credited name, normalized."""
    return {norm_artist(p) for p in re.split(r",|&|\bfeat\.?\s|\bft\.?\s|\sx\s", (a or "").lower())
            if norm_artist(p)}


def credits(artist, title):
    """Every credited name: the artist field, "(feat. X)" / "ft. X" in the title, and an
    "A x B - Song" prefix (channels re-uploading other people's tracks)."""
    names = artist_parts(artist)
    t = title or ""
    for m in re.finditer(r"[(\[]\s*(?:feat|ft|with)\.?\s+([^)\]]+)", t, re.I):
        names |= artist_parts(m.group(1))
    m = re.search(r"\b(?:feat|ft)\.?\s+(.+)$", t, re.I)
    if m:
        names |= artist_parts(m.group(1))
    if " - " in t:
        names |= artist_parts(t.split(" - ", 1)[0])
    return names


def keep_patterns():
    if not KEEP_FILE.exists():
        return None
    lines = [ln.strip() for ln in KEEP_FILE.read_text(encoding="utf-8").splitlines()]
    pats = [ln for ln in lines if ln and not ln.startswith("#")]
    return re.compile("|".join(f"(?:{p})" for p in pats), re.I) if pats else None


def load():
    con = sqlite3.connect(DB)
    meta = {r[0]: r[1:] for r in con.execute(
        "SELECT video_id, artist, title, genre, path FROM tracks")}
    d = np.load(NPZ, allow_pickle=False)
    ids = [str(x) for x in d["ids"]]
    keep = [i for i, v in enumerate(ids) if v in meta]
    X = d["embeddings"][keep].astype("float32")
    ids = [ids[i] for i in keep]
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    X, _ = personalize.center_embeddings(X)
    # (video_id, ts, artist): YouTube Music listens + tracks finished/liked in the player
    events = []
    with open(LISTENS, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                events.append((r["video_id"], datetime.fromisoformat(r["time"]).timestamp(),
                               r.get("artist") or ""))
            except (KeyError, ValueError):
                continue
    for vid, ts in con.execute("SELECT video_id, ts FROM plays WHERE event IN ('complete','like')"):
        if vid in meta:
            events.append((vid, ts, meta[vid][0] or ""))
    return meta, ids, X, events


def nearest(X, k=NEAR_K):
    """(idx, sim) of each track's k nearest other tracks; GPU when there is one."""
    try:
        import torch
        dev = "cuda" if torch.cuda.is_available() else None
    except ImportError:
        dev = None
    idx = np.zeros((len(X), k), np.int32)
    sim = np.zeros((len(X), k), np.float32)
    T = torch.from_numpy(X).to(dev).half() if dev else None
    for a in range(0, len(X), 4096):
        b = min(len(X), a + 4096)
        if dev:
            s = T[a:b] @ T.T
            s[torch.arange(b - a), torch.arange(a, b)] = -9
            v, i = torch.topk(s, k, dim=1)
            idx[a:b], sim[a:b] = i.cpu().numpy(), v.float().cpu().numpy()
        else:
            s = X[a:b] @ X.T
            s[np.arange(b - a), np.arange(a, b)] = -9
            i = np.argpartition(-s, k, axis=1)[:, :k]
            idx[a:b], sim[a:b] = i, np.take_along_axis(s, i, 1)
    return idx, sim


def score(X, ids, events, meta, nn, nsim, cut=None):
    """(heard mask, artist-heard mask, percentile among unheard: 0 = least like you)."""
    i_of = {v: i for i, v in enumerate(ids)}
    cnt, last, arts = {}, {}, set()
    for vid, ts, artist in events:
        if cut is not None and ts >= cut:
            continue
        arts |= artist_parts(artist)
        if vid in i_of:
            cnt[vid] = cnt.get(vid, 0) + 1
            last[vid] = max(last.get(vid, 0.0), ts)
    now = max(last.values())
    hi = np.array([i_of[v] for v in cnt])
    heard = np.zeros(len(ids), bool)
    heard[hi] = True
    w = np.array([math.log1p(cnt[v]) * 0.5 ** ((now - last[v]) / 86400 / HALFLIFE_DAYS)
                  for v in cnt], np.float32)
    cen = w @ X[hi]
    cen /= np.linalg.norm(cen)
    near = (heard[nn] * nsim).sum(1) / nsim.sum(1)
    s = rankdata(X @ cen) + rankdata(near)
    pct = np.full(len(ids), 100.0)
    pct[~heard] = 100.0 * rankdata(s[~heard]) / (~heard).sum()
    art_heard = np.array([bool(credits(meta[v][0], meta[v][1]) & arts) for v in ids])
    return heard, art_heard, pct


def validate(X, ids, events, meta, nn, nsim):
    i_of = {v: i for i, v in enumerate(ids)}
    first = {}
    for vid, ts, _a in events:
        if vid in i_of:
            first[vid] = min(first.get(vid, ts), ts)
    end = max(ts for _v, ts, _a in events)
    print("holdout: tier = flagged share of the unheard pool -> share of the next first listens")
    for days in (30, 60, 90, 120):
        cut = end - days * 86400
        heard, ah, pct = score(X, ids, events, meta, nn, nsim, cut)
        pos = np.zeros(len(ids), bool)
        pos[[i_of[v] for v, t in first.items() if t >= cut]] = True
        pool = ~heard
        cells = []
        for t in TIERS:
            fl = pool & (pct <= t) & ~ah
            cells.append(f"{t}: {fl.sum() / pool.sum():5.1%} -> {pos[fl].sum() / pos.sum():4.1%}")
        print(f"  -{days:3d}d ({pos.sum():3d} new)   " + "   ".join(cells))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", type=int, default=30, choices=TIERS,
                    help="flag up to this score percentile (default 30)")
    ap.add_argument("--validate", action="store_true", help="print the time holdout first")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    meta, ids, X, events = load()
    nn, nsim = nearest(X)
    if args.validate:
        validate(X, ids, events, meta, nn, nsim)
    heard, art_heard, pct = score(X, ids, events, meta, nn, nsim)
    keep = keep_patterns()
    keep_ids = set(KEEP_IDS.read_text(encoding="utf-8").split()) if KEEP_IDS.exists() else set()
    kept = np.array([v in keep_ids or bool(keep and keep.search(f"{meta[v][0]} - {meta[v][1]}"))
                     for v in ids])
    flag = ~heard & ~art_heard & ~kept & (pct <= args.tier)
    tier = np.array([next((t for t in TIERS if p <= t), 0) for p in pct])

    region = MiniBatchKMeans(n_clusters=REGIONS, batch_size=4096, n_init=5,
                             random_state=0).fit_predict(X)
    C = np.stack([X[region == r].mean(0) for r in range(REGIONS)])
    C /= np.linalg.norm(C, axis=1, keepdims=True) + 1e-9
    fam_of_region = fcluster(linkage(C, "average", metric="cosine"), FAMILY_DIST, "distance")
    family = fam_of_region[region]

    def mb(i):
        try:
            return os.path.getsize(meta[ids[i]][3]) / 1e6
        except (OSError, TypeError):
            return 0.0

    rows, report = [], []
    for f in np.unique(family[flag]):
        members = np.where(flag & (family == f))[0]
        sizes = [mb(i) for i in members]
        report.append((f, members, sum(sizes) / 1e3, (family == f).sum(), heard[family == f].sum()))
        for i, m in zip(members, sizes):
            a, t, g, p = meta[ids[i]]
            rows.append((int(f), int(tier[i]), round(float(pct[i]), 1), ids[i], a, t, g, round(m, 1), p))
    report.sort(key=lambda r: -len(r[1]))
    rank = {f: n for n, (f, *_r) in enumerate(report, 1)}
    rows.sort(key=lambda r: (rank[r[0]], r[2]))
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["family", "tier", "pct", "video_id", "artist", "title", "genre", "mb", "path"])
        w.writerows((rank[r[0]], *r[1:]) for r in rows)

    unheard = (~heard).sum()
    print(f"\n{len(ids)} tracks, {heard.sum()} played, {unheard} unheard; {art_heard[~heard].sum()} "
          f"unheard by artists you've played (kept); {(kept & ~heard & ~art_heard & (pct <= args.tier)).sum()} "
          f"more kept by {KEEP_FILE.name} / {KEEP_IDS.name}")
    for t in TIERS:
        n = (flag & (tier <= t) & (tier > 0)).sum()
        print(f"  tier {t:2d}: {n:6d} tracks")
    print(f"flagged {flag.sum()} tracks, {sum(r[7] for r in rows) / 1e3:.1f} GB -> {OUT_CSV}")
    rng = np.random.default_rng(0)
    for f, members, gb, fam_size, fam_heard in report:
        if len(members) < 100:
            continue
        tiers = Counter(tier[members])
        print(f"\nfamily {rank[f]}: {len(members)} flagged ({'/'.join(str(tiers[t]) for t in TIERS)} "
              f"by tier) of {fam_size}, {fam_heard} played; {gb:.1f} GB")
        g = Counter(meta[ids[i]][2] or "-" for i in members).most_common(5)
        print("   genres:", ", ".join(f"{k} {v}" for k, v in g))
        a = Counter(meta[ids[i]][0] or "?" for i in members).most_common(12)
        print("   artists:", ", ".join(f"{k} {v}" for k, v in a))
        for i in rng.choice(members, min(8, len(members)), replace=False):
            print(f"     · {meta[ids[i]][0]} - {meta[ids[i]][1]}"[:110])


if __name__ == "__main__":
    main()
