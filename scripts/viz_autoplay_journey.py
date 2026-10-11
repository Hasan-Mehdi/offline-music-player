#!/usr/bin/env python3
"""Visualize the NEW personalized autoplay engine vs the OLD content-only walk, as two
trajectories through MuQ-MuLan space. Shows how the personalization layer (taste centroid
from play history + logged preferences + collaborative radios + skip-contrastive) bends
the journey toward the region you actually listen to.

GPU-free (no MuQ text model) so it's safe to run alongside a live embedding job. Snapshots
data/muq_embeddings.npz to a temp copy first (never holds the live .npz open during t-SNE,
which on Windows would break the embed job's atomic checkpoint).  -> viz/08_autoplay_journey_personalized.png
"""
from __future__ import annotations

import json
import random
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter, deque
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from sklearn.manifold import TSNE

sys.path.insert(0, "scripts")
import personalize

VIZ = Path("viz"); VIZ.mkdir(exist_ok=True)
CACHE = Path("data/radio_cache")
DB = "data/library.db"
STEPS = 16
random.seed(0); np.random.seed(0)

plt.rcParams.update({
    "figure.dpi": 140, "font.size": 10, "axes.titlesize": 12.5, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white",
})


def l2(M):
    return M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)


def asc(s, n=38):
    s = str(s).encode("ascii", "ignore").decode().strip() or str(s)
    return s if len(s) <= n else s[: n - 1] + "."


# ---------- snapshot + load embeddings (don't hold the live .npz open) ----------
tmp = Path(tempfile.gettempdir()) / "muq_snapshot.npz"
shutil.copyfile("data/muq_embeddings.npz", tmp)
mq = np.load(tmp, allow_pickle=False)
X = l2(mq["embeddings"].astype(np.float64))
ids, arts, titles = [str(v) for v in mq["ids"]], list(mq["artists"]), list(mq["titles"])
n = len(ids)
id2i = {v: i for i, v in enumerate(ids)}
labels = [f"{arts[i]} - {titles[i]}" for i in range(n)]
print(f"loaded {n} embeddings")

# ---------- play history -> taste ----------
plays = []
if Path(DB).exists():
    con = sqlite3.connect(DB)
    plays = con.execute("SELECT video_id, ts, event, seconds FROM plays").fetchall()
    con.close()
played_ids = [v for v, *_ in plays if v in id2i]
# For a legible demo, treat each historical play as a positive taste signal (you chose it).
weights = Counter(v for v in played_ids)
taste_vec = personalize.build_centroid(X, id2i, dict(weights))
prefs = {"track": {v: float(c) for v, c in weights.items()},
         "artist": {}, "skip_ids": set()}
for v, c in weights.items():
    a = arts[id2i[v]]
    prefs["artist"][a] = prefs["artist"].get(a, 0.0) + c
print(f"taste from {len(weights)} played tracks (embedded); taste_vec={'yes' if taste_vec is not None else 'none'}")

# ---------- collaborative radio membership ----------
idset = set(ids)
members = {}
for s in ids:
    f = CACHE / f"{s}.json"
    if f.exists():
        try:
            tr = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        members[s] = {t.get("videoId") for t in tr if t.get("videoId")} & idset


def seed_index():
    # Start both journeys from the same track: the one most central to your taste
    # (or a random track if there's no history yet).
    if taste_vec is not None:
        return int(np.argmax(X @ taste_vec))
    return random.randrange(n)


def walk_old(start):
    """OLD engine: pure content vibe + artist cooldown + a little exploration."""
    path, pset = [start], {start}
    recent = deque([arts[start]], maxlen=4); cur = start
    for _ in range(STEPS - 1):
        score = (X @ X[cur]).copy()
        for j in pset:
            score[j] = -1e9
        for j in range(n):
            if arts[j] in recent:
                score[j] -= 0.5
        nxt = int(random.choice(np.argsort(-score)[:12])) if random.random() < 0.12 else int(np.argmax(score))
        path.append(nxt); pset.add(nxt); recent.append(arts[nxt]); cur = nxt
    return path


def walk_new(start):
    """NEW engine: content + taste centroid + logged prefs + collaborative + cooldown."""
    A_CONTENT, A_TASTE, A_PREF, A_COLLAB, COOL = 1.0, 0.6, 0.4, 0.6, 0.5
    path, pset = [start], {start}
    recent = deque([arts[start]], maxlen=4); cur = start
    for _ in range(STEPS - 1):
        score = A_CONTENT * (X @ X[cur])
        if taste_vec is not None:
            score = score + A_TASTE * (X @ taste_vec)
        if members.get(ids[cur]):
            mem = members[ids[cur]]
            for j in range(n):
                if ids[j] in mem:
                    score[j] += A_COLLAB
        for j in range(n):
            pv = prefs["track"].get(ids[j], 0.0) + 0.3 * prefs["artist"].get(arts[j], 0.0)
            if pv:
                score[j] += A_PREF * pv
            if arts[j] in recent:
                score[j] -= COOL
        for j in pset:
            score[j] = -1e9
        nxt = int(random.choice(np.argsort(-score)[:12])) if random.random() < 0.12 else int(np.argmax(score))
        path.append(nxt); pset.add(nxt); recent.append(arts[nxt]); cur = nxt
    return path


start = seed_index()
old_path = walk_old(start)
new_path = walk_new(start)

# ---------- 2D projection (subsample background for a fast, legible t-SNE) ----------
special = sorted(set(old_path) | set(new_path) | set(id2i[v] for v in weights))
rng = np.random.default_rng(0)
bg = rng.choice(n, size=min(n, 4500), replace=False)
sel = np.array(sorted(set(bg.tolist()) | set(special)))
pos = {g: k for k, g in enumerate(sel)}
print(f"t-SNE on {len(sel)} points...")
E = TSNE(n_components=2, perplexity=30, init="pca", random_state=0).fit_transform(X[sel])


def P(idxs):
    return np.array([E[pos[i]] for i in idxs])


# ---------- figure ----------
fig = plt.figure(figsize=(15, 8))
gs = GridSpec(1, 2, width_ratios=[2.35, 1], figure=fig)
ax = fig.add_subplot(gs[0])
ax.scatter(E[:, 0], E[:, 1], c="0.9", s=12, edgecolors="none", zorder=1)

# highlight your play history + the taste centroid region
if weights:
    ph = P([id2i[v] for v in weights])
    ax.scatter(ph[:, 0], ph[:, 1], c="#12c48b", s=40, edgecolors="white", linewidths=0.6,
               zorder=3, label="your play history")
    ax.scatter([ph[:, 0].mean()], [ph[:, 1].mean()], marker="*", s=520, c="#0a8f66",
               edgecolors="white", linewidths=1.4, zorder=6, label="taste centroid")

for path, color, name in [(old_path, "#9aa0a6", "old: content-only"),
                          (new_path, "#7c3bff", "new: personalized")]:
    pe = P(path)
    ax.plot(pe[:, 0], pe[:, 1], "-", color=color, lw=2.0, alpha=0.85, zorder=4)
    ax.scatter(pe[:, 0], pe[:, 1], c=color, s=90, zorder=5, edgecolors="white", linewidths=1.1)
    ax.scatter(pe[:1, 0], pe[:1, 1], marker="s", c=color, s=150, zorder=7, edgecolors="white")
    for k, (x, y) in enumerate(pe):
        ax.annotate(str(k + 1), (x, y), ha="center", va="center", fontsize=6.5,
                    fontweight="bold", color="white", zorder=8)
ax.plot([], [], color="#9aa0a6", lw=2.4, label="old: content-only")
ax.plot([], [], color="#7c3bff", lw=2.4, label="new: personalized")
ax.legend(loc="upper left", fontsize=9, frameon=True, framealpha=0.9)
ax.set_title("Autoplay journey — old content-only vs new personalized "
             "(same seed ■)\ntaste centroid + play history + collaborative pull")
ax.set_xticks([]); ax.set_yticks([])

# side-by-side track lists
ax2 = fig.add_subplot(gs[1]); ax2.axis("off")
ax2.text(0.0, 1.0, "OLD  (content-only)", fontsize=9.5, fontweight="bold",
         color="#5f6368", transform=ax2.transAxes, va="top")
ax2.text(0.52, 1.0, "NEW  (personalized)", fontsize=9.5, fontweight="bold",
         color="#7c3bff", transform=ax2.transAxes, va="top")
for k, i in enumerate(old_path):
    ax2.text(0.0, 0.95 - k * 0.058, f"{k+1:>2}. {asc(labels[i], 26)}", fontsize=7,
             color="#5f6368", transform=ax2.transAxes, va="top")
for k, i in enumerate(new_path):
    mark = "*" if arts[i] in prefs["artist"] else " "
    ax2.text(0.52, 0.95 - k * 0.058, f"{k+1:>2}.{mark}{asc(labels[i], 24)}", fontsize=7,
             color="#3b1f8f", transform=ax2.transAxes, va="top")
ax2.text(0.52, 0.95 - STEPS * 0.058 - 0.02, "* artist in your taste", fontsize=6.5,
         color="#7c3bff", style="italic", transform=ax2.transAxes, va="top")

fig.tight_layout()
out = VIZ / "08_autoplay_journey_personalized.png"
fig.savefig(out); plt.close(fig)
print(f"saved -> {out}")
