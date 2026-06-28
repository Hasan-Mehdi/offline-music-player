#!/usr/bin/env python3
"""Rigorously compare recommendation scoring methods on a leave-out task.

Ground truth = strong seeds (played >=3x). We split them into TRAIN/TEST, score every
candidate from the TRAIN radios only, and measure how highly held-out favourites rank.

Methods (all from the radio co-occurrence graph):
  count     - # training-seed radios containing the track (current baseline)
  idf       - count x IDF (downweight ubiquitous, generically-popular tracks)
  pos       - inverse-rank-weighted co-occurrence (early in a radio = more related)
  song2vec  - PPMI + truncated SVD song embeddings; score = mean cosine to seeds
              (learns dense embeddings from YOUR graph; captures 2nd-order association)
  hybrid    - z(song2vec) + z(pos)

Metrics over held-out favourites: recall@K, MRR, nDCG@100. Averaged over splits.
"""
from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.decomposition import TruncatedSVD

CACHE = Path("data/radio_cache")
STRONG = Path("data/strong_seeds.csv")
KS = [50, 100, 200, 500]
SPLITS = 8
TEST_FRAC = 0.2
SVD_DIM = 64
random.seed(0)
np.random.seed(0)


def read_ids(p, col="video_id"):
    with open(p, encoding="utf-8-sig") as fh:
        return [r[col] for r in csv.DictReader(fh) if r.get(col)]


def load_radio(seed):
    f = CACHE / f"{seed}.json"
    if not f.exists():
        return None
    try:
        tracks = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None
    ids, seen = [], set()
    for t in tracks:
        v = t.get("videoId")
        if v and v not in seen:
            ids.append(v); seen.add(v)
    if seed in seen:
        ids.remove(seed)
    return [seed] + ids                      # seed first (rank 0)


def build_scorers(train, tb):
    df = Counter()
    posw = defaultdict(float)
    for s in train:
        b = tb[s]
        for c in set(b):
            df[c] += 1
        for rank, c in enumerate(b):
            posw[c] += 1.0 / math.log2(rank + 2)
    count = dict(df)
    pos = dict(posw)

    # --- song2vec: PPMI + truncated SVD over the radio "baskets" ---
    vocab = sorted(set(df) | set(train))
    vid = {v: i for i, v in enumerate(vocab)}
    V = len(vocab)
    rows, cols = [], []
    for bi, s in enumerate(train):
        for c in set(tb[s]) | {s}:
            rows.append(bi); cols.append(vid[c])
    M = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(train), V))
    C = (M.T @ M).tocoo()                     # V x V co-occurrence counts
    rowsum = np.asarray(C.sum(axis=1)).ravel()
    T = rowsum.sum()
    with np.errstate(divide="ignore"):
        pmi = np.log((C.data * T) / (rowsum[C.row] * rowsum[C.col]) + 1e-12)
    pmi[pmi < 0] = 0.0
    P = csr_matrix((pmi, (C.row, C.col)), shape=(V, V))
    k = min(SVD_DIM, V - 1)
    emb = TruncatedSVD(n_components=k, random_state=0).fit_transform(P)
    emb /= (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
    seed_idx = [vid[s] for s in train]

    # centroid scoring (multi-cluster taste -> mushy; kept for comparison)
    qc = emb[seed_idx].mean(0)
    qc /= (np.linalg.norm(qc) + 1e-9)
    s2v_cent = emb @ qc

    # top-k per-seed scoring: mean cosine to the m nearest seeds (respects clusters)
    sims = emb @ emb[seed_idx].T              # V x |seeds|
    m = min(10, sims.shape[1])
    s2v_topk = np.sort(sims, axis=1)[:, -m:].mean(axis=1)

    return {
        "count": count, "pos": pos,
        "s2v_cent": {vocab[i]: float(s2v_cent[i]) for i in range(V)},
        "s2v_topk": {vocab[i]: float(s2v_topk[i]) for i in range(V)},
    }


def znorm(d):
    v = np.fromiter(d.values(), dtype=float)
    m, sd = v.mean(), v.std() + 1e-9
    return {k: (val - m) / sd for k, val in d.items()}


def rank_eval(score, train_set, test_set):
    ranked = [c for c in sorted(score, key=score.get, reverse=True) if c not in train_set]
    pos = {c: i for i, c in enumerate(ranked)}
    out = {}
    for K in KS:
        out[f"r@{K}"] = sum(1 for t in test_set if pos.get(t, 1 << 60) < K) / len(test_set)
    out["MRR"] = float(np.mean([1.0 / (pos[t] + 1) if t in pos else 0.0 for t in test_set]))
    K = 100
    dcg = sum(1.0 / math.log2(pos[t] + 2) for t in test_set if pos.get(t, 1 << 60) < K)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(test_set), K)))
    out["nDCG@100"] = dcg / idcg if idcg else 0.0
    return out


def main():
    strong = read_ids(STRONG)
    baskets = {}
    for s in strong:
        r = load_radio(s)
        if r and len(r) > 1:
            baskets[s] = r
    seeds = list(baskets)
    avg = np.mean([len(baskets[s]) for s in seeds])
    print(f"seeds with radios: {len(seeds)} | avg basket: {avg:.1f}\n")

    methods = ["count", "pos", "s2v_cent", "s2v_topk", "hybrid"]
    agg = {m: defaultdict(list) for m in methods}

    for _ in range(SPLITS):
        random.shuffle(seeds)
        nt = int(len(seeds) * TEST_FRAC)
        test = set(seeds[:nt])
        train = seeds[nt:]
        train_set = set(train)
        tb = {s: baskets[s] for s in train}
        sc = build_scorers(train, tb)
        zs, zp = znorm(sc["s2v_topk"]), znorm(sc["pos"])
        lo_s, lo_p = min(zs.values()), min(zp.values())
        keys = set(zs) | set(zp)
        sc["hybrid"] = {c: 0.6 * zs.get(c, lo_s) + 0.4 * zp.get(c, lo_p) for c in keys}
        for m in methods:
            for k, v in rank_eval(sc[m], train_set, test).items():
                agg[m][k].append(v)

    cols = [f"r@{k}" for k in KS] + ["MRR", "nDCG@100"]
    print(f"{'method':<10}" + "".join(f"{c:>10}" for c in cols))
    print("-" * (10 + 10 * len(cols)))
    for m in methods:
        line = f"{m:<10}"
        for c in cols:
            line += f"{np.mean(agg[m][c]) * (100 if c.startswith(('r@', 'nD')) else 1):>10.2f}"
        print(line)
    print("\n(r@K and nDCG in %, MRR raw. Higher is better.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
