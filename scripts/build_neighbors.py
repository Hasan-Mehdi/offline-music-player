#!/usr/bin/env python3
"""Precompute the audio-similarity neighborhood so the player runs on low-RAM devices.

Writes two artifacts consumed by server.py when PLAYER_LOW_MEM=1:
  1. data/library.db `neighbors` table — top-K MuQ cosine neighbors per track
     (video_id, rank, neighbor_id, sim). /api/next retrieval reads this instead of
     doing a full 50k x 512 matmul against an in-RAM fp32 matrix.
  2. data/muq_fp16.npz — the same embeddings, L2-normalized, stored float16
     (half the RAM; only candidate rows are ever dotted, so precision is plenty).

Rerun after muq_run.py adds embeddings for new downloads.

Run:  .venv\\Scripts\\python scripts\\build_neighbors.py [--k 120]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--emb", type=Path, default=ROOT / "data" / "muq_embeddings.npz")
    p.add_argument("--db", type=Path, default=ROOT / "data" / "library.db")
    p.add_argument("--fp16-out", type=Path, default=ROOT / "data" / "muq_fp16.npz")
    p.add_argument("--k", type=int, default=120, help="neighbors per track (default: 120)")
    p.add_argument("--chunk", type=int, default=1024, help="rows per matmul chunk")
    return p.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    d = np.load(args.emb, allow_pickle=False)
    X = d["embeddings"].astype("float32")
    X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    ids = [str(x) for x in d["ids"]]
    n = len(ids)
    print(f"{n} embeddings, k={args.k}")

    np.savez_compressed(args.fp16_out, ids=np.array(ids), embeddings=X.astype(np.float16))
    print(f"wrote {args.fp16_out} ({args.fp16_out.stat().st_size // 1_048_576} MB)")

    con = sqlite3.connect(args.db)
    con.execute("DROP TABLE IF EXISTS neighbors")
    con.execute("CREATE TABLE neighbors(video_id TEXT, rank INTEGER, neighbor_id TEXT, sim REAL)")

    t0 = time.time()
    k = min(args.k, n - 1)
    for lo in range(0, n, args.chunk):
        hi = min(lo + args.chunk, n)
        sims = X[lo:hi] @ X.T                          # (chunk, n)
        # top k+1 (self included), then drop self and order best-first
        idx = np.argpartition(-sims, k, axis=1)[:, : k + 1]
        rows = []
        for r in range(hi - lo):
            cand = idx[r]
            order = cand[np.argsort(-sims[r, cand])]
            vid = ids[lo + r]
            rank = 0
            for j in order:
                nb = ids[int(j)]
                if nb == vid:
                    continue
                rows.append((vid, rank, nb, float(sims[r, int(j)])))
                rank += 1
                if rank >= k:
                    break
        con.executemany("INSERT INTO neighbors VALUES (?,?,?,?)", rows)
        con.commit()
        print(f"  [{hi}/{n}]  {time.time() - t0:.0f}s")

    con.execute("CREATE INDEX IF NOT EXISTS idx_neighbors ON neighbors(video_id, rank)")
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM neighbors").fetchone()[0]
    print(f"neighbors table: {total} rows in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
