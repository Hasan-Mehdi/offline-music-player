#!/usr/bin/env python3
"""Visualization suite for the recommendation system -> viz/*.png

  01_embedding_map.png    - MuQ-MuLan t-SNE: tracks by style + typed moods placed by match
  02_autoplay_journey.png - an autoplay sequence as a trajectory through musical space
  03_collaborative.png    - method comparison + recall@K vs random (the +32% story)
  04_content_models.png   - MuQ vs CLAP: coherence lift + similarity spread
  05_text_to_music.png    - semantic search: top matches per mood prompt
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from sklearn.manifold import TSNE

sys.path.insert(0, "scripts")
from eval_methods import build_scorers, load_radio, read_ids, znorm  # reuse measured methods

VIZ = Path("viz"); VIZ.mkdir(exist_ok=True)
CACHE = Path("data/radio_cache")
random.seed(0); np.random.seed(0)

plt.rcParams.update({
    "figure.dpi": 140, "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white",
})

PROMPTS = [
    ("chiptune battle", "upbeat 8-bit chiptune video game battle theme"),
    ("vaporwave / funk", "nostalgic vaporwave future funk city pop"),
    ("calm piano", "relaxing calm piano music"),
    ("epic orchestral", "epic orchestral video game soundtrack"),
    ("melancholic", "sad melancholic ambient music"),
    ("electronic dance", "energetic electronic dance music"),
    ("hip-hop / rap", "hard-hitting hip hop rap song with vocals and heavy beats"),
]


def l2(M):
    return M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)


def asc(s, n=34):
    s = str(s).encode("ascii", "ignore").decode().strip() or str(s)
    return s if len(s) <= n else s[: n - 1] + "."


# ---------- load embeddings ----------
mq = np.load("data/muq_embeddings.npz", allow_pickle=False)
Xm = l2(mq["embeddings"].astype(np.float64))
ids, arts, titles = list(mq["ids"]), mq["artists"], mq["titles"]
n = len(ids)
labels = [f"{arts[i]} - {titles[i]}" for i in range(n)]
try:
    cl = np.load("data/clap_embeddings.npz", allow_pickle=False)
    Xc, arts_c = l2(cl["embeddings"].astype(np.float64)), cl["artists"]
except Exception:
    Xc, arts_c = None, None

# ---------- MuQ text prompts ----------
import torch
from muq import MuQMuLan
dev = "cuda" if torch.cuda.is_available() else "cpu"
mulan = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large").to(dev).eval()
with torch.no_grad():
    Tp = torch.nn.functional.normalize(
        mulan(texts=[p[1] for p in PROMPTS]), dim=-1).cpu().numpy().astype(np.float64)
prompt_sims = Tp @ Xm.T                                # 6 x n

# ---------- t-SNE (tracks) ----------
print("t-SNE...")
E = TSNE(n_components=2, perplexity=30, init="pca", random_state=0).fit_transform(Xm)
# place each prompt at the centroid of its top-5 audio matches
Ep = np.array([E[np.argsort(-prompt_sims[i])[:5]].mean(0) for i in range(len(PROMPTS))])

cnt = Counter(a for a in arts if a)
top = [a for a, _ in cnt.most_common(12)]
pal = plt.cm.tab20(np.linspace(0, 1, 20))
cm = {a: pal[i] for i, a in enumerate(top)}
cols = [cm.get(a, (0.86, 0.86, 0.86, 1)) for a in arts]


# ============================ 01: embedding map ============================
fig, ax = plt.subplots(figsize=(11, 8))
ax.scatter(E[:, 0], E[:, 1], c=cols, s=22, edgecolors="none")
for (lbl, _), (x, y) in zip(PROMPTS, Ep):
    ax.scatter([x], [y], marker="*", s=360, c="black", zorder=5, edgecolors="white", linewidths=1.3)
    ax.annotate(f'"{lbl}"', (x, y), xytext=(7, 7), textcoords="offset points",
                fontsize=9.5, fontweight="bold", zorder=6,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="0.6", alpha=0.9))
h = [plt.Line2D([0], [0], marker="o", ls="", color=cm[a], label=asc(a, 22)) for a in top]
h.append(plt.Line2D([0], [0], marker="*", ls="", color="black", label="typed mood query"))
ax.legend(handles=h, fontsize=8, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)
ax.set_title("MuQ-MuLan space — tracks cluster by style; typed moods land among their matches")
ax.set_xticks([]); ax.set_yticks([])
fig.tight_layout(); fig.savefig(VIZ / "01_embedding_map.png"); plt.close(fig)
print("01 done")


# ============================ 02: autoplay journey ============================
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

start = int(np.argmax(prompt_sims[1]))                 # seed from "vaporwave / funk"
path, pset = [start], {start}
recent = deque([arts[start]], maxlen=4)
cur = start
for _ in range(15):
    score = (Xm @ Xm[cur]).copy()
    if members.get(ids[cur]):
        mem = members[ids[cur]]
        for j in range(n):
            if ids[j] in mem:
                score[j] += 0.6
    for j in pset:
        score[j] = -1e9
    for j in range(n):
        if arts[j] in recent:
            score[j] -= 0.5
    nxt = int(random.choice(np.argsort(-score)[:12])) if random.random() < 0.12 else int(np.argmax(score))
    path.append(nxt); pset.add(nxt); recent.append(arts[nxt]); cur = nxt

fig = plt.figure(figsize=(13, 7.5))
gs = GridSpec(1, 2, width_ratios=[2.1, 1], figure=fig)
ax = fig.add_subplot(gs[0])
ax.scatter(E[:, 0], E[:, 1], c="0.88", s=16, edgecolors="none")
pe = E[path]
order = np.arange(len(path))
ax.plot(pe[:, 0], pe[:, 1], "-", color="0.5", lw=1.3, alpha=0.7, zorder=2)
ax.scatter(pe[:, 0], pe[:, 1], c=order, cmap="plasma", s=120, zorder=3, edgecolors="white", linewidths=1.2)
for k, (x, y) in enumerate(pe):
    ax.annotate(str(k + 1), (x, y), ha="center", va="center", fontsize=7.5, fontweight="bold",
                color="white", zorder=4)
ax.set_title(f'Autoplay journey  (seed: mood "vaporwave / funk")')
ax.set_xticks([]); ax.set_yticks([])
ax2 = fig.add_subplot(gs[1]); ax2.axis("off")
vir = plt.cm.plasma(np.linspace(0, 1, len(path)))
for k, i in enumerate(path):
    ax2.text(0, 1 - k * (1 / len(path)), f"{k+1:>2}. {asc(labels[i], 40)}",
             fontsize=8.5, color=vir[k], fontweight="bold", transform=ax2.transAxes, va="top")
fig.tight_layout(); fig.savefig(VIZ / "02_autoplay_journey.png"); plt.close(fig)
print("02 done")


# ============================ 03: collaborative eval ============================
strong = read_ids("data/strong_seeds.csv")
baskets = {}
for s in strong:
    r = load_radio(s)
    if r and len(r) > 1:
        baskets[s] = r
seeds = list(baskets)
KS = [50, 100, 200, 500, 1000]


def recalls(score, train_set, test, ks):
    ranked = [c for c in sorted(score, key=score.get, reverse=True) if c not in train_set]
    pos = {c: i for i, c in enumerate(ranked)}
    out = {K: sum(1 for t in test if pos.get(t, 1 << 60) < K) / len(test) for K in ks}
    dcg = sum(1 / math.log2(pos[t] + 2) for t in test if pos.get(t, 1 << 60) < 100)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(test), 100)))
    out["nDCG"] = dcg / idcg if idcg else 0
    out["N"] = len(ranked)
    out["present"] = sum(1 for t in test if t in pos) / len(test)
    return out


methods = ["count", "pos", "hybrid"]
agg = {m: defaultdict(list) for m in methods}
randr = {K: [] for K in KS}
for _ in range(6):
    random.shuffle(seeds)
    nt = int(len(seeds) * 0.2)
    test, train = set(seeds[:nt]), seeds[nt:]
    ts = set(train)
    sc = build_scorers(train, {s: baskets[s] for s in train})
    zs, zp = znorm(sc["s2v_topk"]), znorm(sc["pos"])
    lo_s, lo_p = min(zs.values()), min(zp.values())
    sc["hybrid"] = {c: 0.6 * zs.get(c, lo_s) + 0.4 * zp.get(c, lo_p) for c in set(zs) | set(zp)}
    for m in methods:
        r = recalls(sc[m], ts, test, KS)
        for k in list(KS) + ["nDCG"]:
            agg[m][k].append(r[k])
    base = recalls(sc["count"], ts, test, KS)
    for K in KS:
        randr[K].append(base["present"] * min(K, base["N"]) / base["N"])

fig, (axa, axb) = plt.subplots(1, 2, figsize=(13, 5))
groups = ["r@50", "r@100", "nDCG@100"]
keys = [50, 100, "nDCG"]
x = np.arange(len(groups)); w = 0.26
colors3 = ["#bdbdbd", "#5aa9a3", "#1d6f6a"]
for gi, m in enumerate(methods):
    vals = [np.mean(agg[m][k]) * 100 for k in keys]
    bars = axa.bar(x + (gi - 1) * w, vals, w, label=m, color=colors3[gi])
    for b, v in zip(bars, vals):
        axa.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}", ha="center", va="bottom", fontsize=8)
axa.set_xticks(x); axa.set_xticklabels(groups); axa.set_ylabel("score (%)")
axa.set_title("Collaborative methods (held-out favourites)"); axa.legend(frameon=False)

co = [np.mean(agg["hybrid"][K]) * 100 for K in KS]
rd = [np.mean(randr[K]) * 100 for K in KS]
xx = np.arange(len(KS))
axb.bar(xx - 0.2, co, 0.4, label="hybrid", color="#1d6f6a")
axb.bar(xx + 0.2, rd, 0.4, label="random", color="#cccccc")
axb.set_yscale("log"); axb.set_xticks(xx); axb.set_xticklabels([f"@{k}" for k in KS])
axb.set_ylabel("recall (%)"); axb.set_title("Recall vs random  (lift labelled)")
for i in range(len(KS)):
    axb.text(i, co[i], f"{co[i]/rd[i]:.0f}x", ha="center", va="bottom", fontsize=8, fontweight="bold")
axb.legend(frameon=False)
fig.tight_layout(); fig.savefig(VIZ / "03_collaborative.png"); plt.close(fig)
print("03 done")


# ============================ 04: content models ============================
def coherence_lift(X, A):
    S = X @ X.T
    np.fill_diagonal(S, -1)
    same = tot = 0
    for i in range(len(X)):
        for j in np.argsort(-S[i])[:5]:
            same += bool(A[i]) and A[i] == A[j]
            tot += 1
    nn = len(X)
    base = sum((v / nn) ** 2 for v in Counter(a for a in A if a).values())
    return (same / tot) / base if base else 0


def offdiag(X):
    S = X @ X.T
    return S[np.triu_indices(len(X), 1)]


muq_lift = coherence_lift(Xm, arts)
clap_lift = coherence_lift(Xc, arts_c) if Xc is not None else 0
fig, (axa, axb) = plt.subplots(1, 2, figsize=(13, 5))
bars = axa.bar(["random", "CLAP", "MuQ-MuLan"], [1, clap_lift, muq_lift],
               color=["#cccccc", "#e76f51", "#1d6f6a"])
for b, v in zip(bars, [1, clap_lift, muq_lift]):
    axa.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}x", ha="center", va="bottom", fontweight="bold")
axa.set_ylabel("artist-coherence@5 (x over random)")
axa.set_title("Audio embedding quality")
if Xc is not None:
    axb.hist(offdiag(Xc), bins=60, alpha=0.55, density=True, label="CLAP", color="#e76f51")
axb.hist(offdiag(Xm), bins=60, alpha=0.7, density=True, label="MuQ-MuLan", color="#1d6f6a")
axb.set_xlabel("pairwise cosine similarity"); axb.set_ylabel("density")
axb.set_title("Similarity spread (CLAP collapses ~1.0 = anisotropic)"); axb.legend(frameon=False)
fig.tight_layout(); fig.savefig(VIZ / "04_content_models.png"); plt.close(fig)
print("04 done")


# ============================ 05: text -> music ============================
nrow = math.ceil(len(PROMPTS) / 2)
fig, axes = plt.subplots(nrow, 2, figsize=(13, 3 * nrow))
axflat = axes.ravel()
for ax in axflat[len(PROMPTS):]:
    ax.axis("off")
for ax, (lbl, _), row in zip(axflat, PROMPTS, prompt_sims):
    idx = np.argsort(-row)[:4][::-1]
    vals = row[idx]
    bars = ax.barh(range(4), vals, color=plt.cm.viridis(np.linspace(0.2, 0.85, 4)))
    ax.set_yticks(range(4))
    ax.set_yticklabels([asc(labels[i], 32) for i in idx], fontsize=8)
    ax.set_title(f'"{lbl}"', fontsize=11)
    ax.set_xlim(0, max(0.1, vals.max() * 1.15))
    for b, v in zip(bars, vals):
        ax.text(v, b.get_y() + b.get_height() / 2, f" {v:.2f}", va="center", fontsize=8)
fig.suptitle("Text -> music (MuQ-MuLan): top matches per typed mood", fontsize=13, fontweight="bold")
fig.tight_layout(rect=[0, 0, 1, 0.97]); fig.savefig(VIZ / "05_text_to_music.png"); plt.close(fig)
print("05 done")
print("all figures written to viz/")
