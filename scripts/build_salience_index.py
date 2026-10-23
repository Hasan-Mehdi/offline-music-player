#!/usr/bin/env python3
"""Batch Deep Salience melody extraction -> data/salience_index/ (shards) for hum search.

Second-generation hum index (see scripts/hum_search.py). The first one
(build_melody_index.py) ran monophonic CREPE on the mix and reduced each track to one note
line; in game/orchestral music that line usually follows the bass or pads, and CREPE's
1100 Hz ceiling hides high leads entirely. Here a polyphonic melody-salience net
(scripts/deep_salience.py) runs on the GPU and we keep the top-3 salience peaks per 0.1 s
frame, so the matcher can still follow the lead when it isn't the loudest voice.

Storage: ~6 bytes/frame. Shards of SHARD_SIZE tracks are written atomically to
data/salience_index/shard_NNNNN.npz (ids, ptr, bins int16 (T,3), vals uint8 (T,3));
re-running skips ids already present in any shard, so the multi-hour run is resumable.

Usage: python scripts/build_salience_index.py [--limit N] [--workers N] [--ids a,b,...]
"""
from __future__ import annotations

import argparse
import glob
import os
import sqlite3
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deep_salience as ds
from melody_match import decode_audio

DEFAULT_DB = "data/library.db"
OUT_DIR = "data/salience_index"
SHARD_SIZE = 500
MAX_DECODE_S = 900


def indexed_ids(out_dir=OUT_DIR):
    done = set()
    for fp in glob.glob(os.path.join(out_dir, "shard_*.npz")):
        with np.load(fp, allow_pickle=False) as z:
            done.update(z["ids"].tolist())
    return done


def write_shard(out_dir, ids, bins, vals):
    n = len(glob.glob(os.path.join(out_dir, "shard_*.npz")))
    while os.path.exists(os.path.join(out_dir, f"shard_{n:05d}.npz")):
        n += 1
    ptr = np.zeros(len(ids) + 1, dtype=np.int64)
    ptr[1:] = np.cumsum([b.shape[0] for b in bins])
    fp = os.path.join(out_dir, f"shard_{n:05d}.npz")
    tmp = fp + ".tmp.npz"
    np.savez(tmp, ids=np.array(ids), ptr=ptr,
             bins=np.concatenate(bins) if bins else np.zeros((0, ds.PEAK_K), np.int16),
             vals=np.concatenate(vals) if vals else np.zeros((0, ds.PEAK_K), np.uint8))
    os.replace(tmp, fp)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--ids", default="", help="comma-separated video ids to (re)index first")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    con = sqlite3.connect(args.db, timeout=30)
    rows = con.execute("SELECT video_id, path FROM tracks").fetchall()
    con.close()
    done = indexed_ids(args.out)
    first = set(filter(None, args.ids.split(",")))
    todo = [r for r in rows if r[0] not in done and os.path.exists(r[1])]
    todo.sort(key=lambda r: r[0] not in first)
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(done)} indexed, {len(todo)} to do", flush=True)

    import torch
    model = ds.load_model()
    ids, bins, vals = [], [], []
    t0 = time.time()
    t_wait = t_gpu = 0.0                        # time blocked on decode vs on the GPU
    def decoded():
        # bounded prefetch: pool.map would queue (and hold) every decoded file at once
        with ThreadPoolExecutor(args.workers) as pool:
            q = deque()
            it = iter(todo)
            for r in it:
                q.append((r, pool.submit(decode_audio, r[1], ds.SR, MAX_DECODE_S)))
                if len(q) >= args.workers * 2:
                    break
            while q:
                r, fut = q.popleft()
                nxt = next(it, None)
                if nxt is not None:
                    q.append((nxt, pool.submit(decode_audio, nxt[1], ds.SR, MAX_DECODE_S)))
                try:
                    yield r, fut.result()
                except Exception:
                    yield r, None

    tw = time.time()
    for n, (row, audio) in enumerate(decoded(), 1):
        t_wait += time.time() - tw
        tg = time.time()
        try:
            if audio is None or audio.size < ds.SR:
                b = np.zeros((0, ds.PEAK_K), np.int16)
                v = np.zeros((0, ds.PEAK_K), np.uint8)
            else:
                b, v = ds.melody_peaks(model, audio)
        except Exception as e:  # one bad file (or an OOM on a huge one) must not kill the run
            print(f"ERR {row[0]}: {e}", flush=True)
            torch.cuda.empty_cache()
            b = None
        t_gpu += time.time() - tg
        if b is not None:
            ids.append(row[0]); bins.append(b); vals.append(v)
        if len(ids) >= SHARD_SIZE:
            write_shard(args.out, ids, bins, vals)
            ids, bins, vals = [], [], []
        if n % 100 == 0:
            el = time.time() - t0
            print(f"{n}/{len(todo)}  {el / n:.2f}s/track  eta {(len(todo) - n) * el / n / 3600:.1f}h"
                  f"  (decode wait {t_wait / n:.2f}s, gpu {t_gpu / n:.2f}s)", flush=True)
        tw = time.time()
    if ids:
        write_shard(args.out, ids, bins, vals)
    print("done", flush=True)


if __name__ == "__main__":
    main()
