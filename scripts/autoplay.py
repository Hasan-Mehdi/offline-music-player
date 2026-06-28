#!/usr/bin/env python3
"""Hybrid autoplay over MuQ-MuLan embeddings.

Each next-track score blends:
  * audio "vibe"      - MuQ cosine similarity to the current track (carry the mood)
  * collaborative     - +boost if the candidate is in the current track's radio
  * diversity         - artist-cooldown penalty (no same-artist runs)
  * exploration       - epsilon chance to jump within the top candidates

Seed from a track substring or a mood phrase (text -> MuQ-MuLan -> nearest track).
Reads data/muq_embeddings.npz and data/radio_cache/.

Usage:
  python scripts/autoplay.py --text "rainy late-night lo-fi" --n 20
  python scripts/autoplay.py --seed-contains "Flying Battery" --n 20
"""
from __future__ import annotations

import argparse
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


def main():
    cfgp = Path("data/autoplay_config.json")
    cfg = json.loads(cfgp.read_text()) if cfgp.exists() else {}    # tuned defaults
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--text", default=None, help="mood phrase to seed from")
    ap.add_argument("--seed-contains", default=None, help="seed from first track matching this")
    ap.add_argument("--alpha", type=float, default=cfg.get("alpha", 1.0), help="audio vibe weight")
    ap.add_argument("--beta", type=float, default=cfg.get("beta", 0.6), help="collaborative boost weight")
    ap.add_argument("--cooldown", type=int, default=cfg.get("cooldown", 4), help="artist cooldown steps")
    ap.add_argument("--epsilon", type=float, default=cfg.get("epsilon", 0.12), help="exploration rate")
    args = ap.parse_args()

    d = np.load(NPZ, allow_pickle=False)
    X = l2(d["embeddings"].astype(np.float32))
    ids, arts, titles = list(d["ids"]), d["artists"], d["titles"]
    n = len(ids)
    idset = set(ids)

    # collaborative: radio membership (intersected with our universe) for seed tracks
    members = {}
    for s in ids:
        f = CACHE / f"{s}.json"
        if f.exists():
            try:
                tr = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            members[s] = {t.get("videoId") for t in tr if t.get("videoId")} & idset

    # choose start
    if args.text:
        import torch
        from muq import MuQMuLan
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        m = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large").to(dev).eval()
        with torch.no_grad():
            t = torch.nn.functional.normalize(m(texts=[args.text]), dim=-1).cpu().numpy()[0]
        start = int(np.argmax(X @ t))
        print(f'TEXT SEED: "{args.text}"  ->  {arts[start]} - {titles[start]}\n')
    elif args.seed_contains:
        q = args.seed_contains.lower()
        cand = [i for i in range(n) if q in (str(arts[i]) + " " + str(titles[i])).lower()]
        start = cand[0] if cand else 0
    else:
        start = random.randrange(n)

    played, pset = [start], {start}
    recent = deque([arts[start]], maxlen=args.cooldown)
    cur = start
    for _ in range(args.n - 1):
        score = args.alpha * (X @ X[cur])
        if ids[cur] in members and members[ids[cur]]:
            mem = members[ids[cur]]
            for j in range(n):
                if ids[j] in mem:
                    score[j] += args.beta
        for j in pset:
            score[j] = -1e9
        for j in range(n):
            if arts[j] in recent:
                score[j] -= 0.5
        if random.random() < args.epsilon:
            nxt = int(random.choice(np.argsort(-score)[:12]))
        else:
            nxt = int(np.argmax(score))
        played.append(nxt); pset.add(nxt); recent.append(arts[nxt]); cur = nxt

    print("AUTOPLAY:")
    for k, i in enumerate(played):
        print(f"  {k+1:>2}. {arts[i]} - {titles[i]}"[:82])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
