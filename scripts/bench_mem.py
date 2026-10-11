#!/usr/bin/env python3
"""Memory + latency benchmark for the low-mem player path at real 50k scale.

Answers the open question: does the fp16 embeddings + neighbors retrieval fit the
handheld's RAM budget at the 50k-track target (we only have ~20k embedded today)?

Measures process RSS (Windows WorkingSetSize via ctypes — no psutil dependency) at:
  - baseline (interpreter + numpy)
  - after loading the fp16 embedding matrix + id2i (server.emb low-mem path)
  - after one full rank pass over an 800-candidate neighbourhood
and times the rank. Run with --n to set the track count.

  .venv\\Scripts\\python scripts\\bench_mem.py --n 50000
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import time
from pathlib import Path

import numpy as np


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


_psapi = ctypes.WinDLL("psapi")
_k32 = ctypes.WinDLL("kernel32")
_k32.GetCurrentProcess.restype = wt.HANDLE
_psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]
_psapi.GetProcessMemoryInfo.restype = wt.BOOL


def _pmc() -> _PMC:
    pmc = _PMC(); pmc.cb = ctypes.sizeof(_PMC)
    if not _psapi.GetProcessMemoryInfo(_k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        raise ctypes.WinError()
    return pmc


def rss_mb() -> float:
    return _pmc().WorkingSetSize / 1_048_576


def peak_mb() -> float:
    return _pmc().PeakWorkingSetSize / 1_048_576


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50000, help="synthetic track count")
    ap.add_argument("--dim", type=int, default=512)
    ap.add_argument("--real", type=Path, default=Path("data/muq_fp16.npz"),
                    help="also measure the real fp16 file if present")
    args = ap.parse_args()

    base = rss_mb()
    print(f"baseline RSS (numpy loaded)          : {base:6.1f} MB")

    # --- synthesize N L2-normalized fp16 rows, exactly as server.emb() holds them ---
    rng = np.random.default_rng(0)
    t0 = time.time()
    X = rng.standard_normal((args.n, args.dim)).astype("float32")
    X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    X = X.astype("float16")                       # the low-mem in-RAM representation
    ids = [f"{i:011d}"[-11:] for i in range(args.n)]
    id2i = {v: i for i, v in enumerate(ids)}
    after_load = rss_mb()
    print(f"after {args.n} fp16 rows + id2i        : {after_load:6.1f} MB  "
          f"(+{after_load - base:5.1f})   matrix={X.nbytes/1_048_576:.1f}MB, built in {time.time()-t0:.1f}s")

    taste = X[rng.integers(args.n)].astype("float32")
    skip = X[rng.integers(args.n)].astype("float32")

    # (A) DESKTOP / non-low-mem path: full-matrix cosine, top-800, blend.
    lat_full = []
    for _ in range(20):
        q = X[rng.integers(args.n)].astype("float32")
        s0 = time.time()
        sims = (X @ q.astype(X.dtype)).astype("float32")
        cand = np.argpartition(-sims, 800)[:800]
        Xc = X[cand].astype("float32")
        _ = 1.0 * (Xc @ q) + 0.6 * (Xc @ taste) - 0.7 * np.maximum(0, Xc @ skip)
        lat_full.append((time.time() - s0) * 1000)

    # (B) DEVICE / low-mem path: neighbours come from the SQLite `neighbors` table
    #     (a sub-ms indexed lookup, NOT modelled here), then rank_next dots taste/skip
    #     over just ~120 candidate rows. This is the hot path the handheld runs.
    lat_lm = []
    for _ in range(200):
        cand = rng.integers(args.n, size=120)
        s0 = time.time()
        Xc = X[cand].astype("float32")
        _ = 0.6 * (Xc @ taste) - 0.7 * np.maximum(0, Xc @ skip)
        lat_lm.append((time.time() - s0) * 1000)

    after_rank = rss_mb()
    lat_full.sort(); lat_lm.sort()
    print(f"after rank passes                    : {after_rank:6.1f} MB")
    print(f"(A) full-matrix cosine  [desktop]    : median {lat_full[len(lat_full)//2]:6.2f} ms")
    print(f"(B) 120-cand rerank     [device path]: median {lat_lm[len(lat_lm)//2]:6.3f} ms  "
          f"(+ one indexed SQLite lookup)")
    print(f"PEAK working set                     : {peak_mb():6.1f} MB  (delta {peak_mb()-base:+.1f})")

    if args.real.exists():
        d = np.load(args.real, allow_pickle=False)
        rn = len(d["ids"])
        print(f"\n(real data on disk: {args.real.name} holds {rn} embedded tracks)")


if __name__ == "__main__":
    main()
