#!/usr/bin/env python3
"""Batch predominant-melody extractor -> data/melody_index.npz (+ .meta.json).

Extractor: torchcrepe ('full' CREPE model) on the full mix, GPU. Rationale / ladder:
Spotify's basic-pitch (ladder rung 1) refuses to build on Python 3.13 (its pinned numpy
build hits the removed pkgutil.ImpImporter), so we use rung 2 — torchcrepe. To bias the
predominant-f0 tracker toward the lead line and off the bass, the mix is band-passed to
150-2000 Hz before tracking (measured: lifts the melody-range pitch percentiles and voiced
coverage substantially vs the raw mix). Frames below a periodicity threshold are dropped
(NaN = unvoiced). Output lives on a 20 Hz grid; notes are segmented from the contour.

Per track we store BOTH a frame-level MIDI contour (float16, NaN unvoiced) and segmented
note events (onset_s, dur_s, midi). Incremental + crash-tolerant: re-running skips ids
already in the index and checkpoints periodically (atomic tmp+replace), so a multi-hour /
50k run survives interruption.

Usage: python scripts/build_melody_index.py [--limit N] [--workers N] [--db ...] [--out ...]
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time
import warnings
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys_path_added = os.path.dirname(os.path.abspath(__file__))
import sys
if sys_path_added not in sys.path:
    sys.path.insert(0, sys_path_added)
from melody_match import (SR, HOP, FRAME_PERIOD, FRAME_RATE, decode_audio, hz_to_midi,
                          contour_to_notes)

MODEL = "full"
CREPE_FMIN, CREPE_FMAX = 50.0, 1100.0
BANDPASS = (150.0, 2000.0)
CONF_THRESH = 0.50             # periodicity gate: below this a frame is unvoiced
BATCH = 2048
CHECKPOINT_EVERY = 200

EXTRACTOR_VERSION = "torchcrepe-0.0.24/full"


def bandpass(a, lo=BANDPASS[0], hi=BANDPASS[1], sr=SR):
    from scipy.signal import butter, sosfiltfilt
    if a.shape[0] < 64:
        return a
    sos = butter(4, [lo, hi], btype="band", fs=sr, output="sos")
    return sosfiltfilt(sos, a).astype(np.float32)


MAX_DECODE_S = 900             # cap extraction at 15 min: multi-hour mixes otherwise spike
                               # several GB in decode/bandpass/crepe and can kill the run


def decode_and_filter(path):
    try:
        a = decode_audio(path, max_s=MAX_DECODE_S)
    except Exception:
        return None
    if a is None:
        return None
    try:
        return bandpass(a)
    except Exception:
        return a


def extract_contour(audio, model_ref):
    """torchcrepe predominant-f0 -> float16 MIDI contour on the 20 Hz grid (NaN unvoiced)."""
    import torch
    import torchcrepe
    device = model_ref["device"]
    audio_t = torch.tensor(audio, dtype=torch.float32)[None].to(device)
    f0, pd = torchcrepe.predict(
        audio_t, SR, hop_length=HOP, model=MODEL, fmin=CREPE_FMIN, fmax=CREPE_FMAX,
        batch_size=BATCH, device=device, return_periodicity=True, pad=True)
    pd = torchcrepe.filter.median(pd, 3)
    f0 = torchcrepe.filter.median(f0, 3)
    f0 = f0[0].detach().cpu().numpy()
    pd = pd[0].detach().cpu().numpy()
    midi = hz_to_midi(f0)
    midi[pd < CONF_THRESH] = np.nan
    return midi.astype(np.float16)


def prefetch(items, workers, ahead):
    """Yield (item, filtered_audio) in order, decoding+band-passing up to `ahead` ahead."""
    ex = ThreadPoolExecutor(max_workers=max(1, workers))
    pending = deque()
    it = iter(items)

    def submit():
        try:
            item = next(it)
        except StopIteration:
            return False
        pending.append((item, ex.submit(decode_and_filter, item[1])))
        return True

    for _ in range(max(1, ahead)):
        if not submit():
            break
    while pending:
        item, fut = pending.popleft()
        submit()
        yield item, fut.result()
    ex.shutdown(wait=True)


def _split(concat, ptr):
    return [concat[int(ptr[i]):int(ptr[i + 1])] for i in range(len(ptr) - 1)]


def load_existing(out_path):
    """Return (known_ids->idx, store). store holds per-track numpy arrays (memory-light:
    2-4 bytes/elem vs ~24 for python-list floats, so it scales to 50k)."""
    known = {}
    store = {"ids": [], "dur": [], "onset": [], "ndur": [], "midi": [], "contour": []}
    if not os.path.exists(out_path):
        return known, store
    with np.load(out_path, allow_pickle=False) as z:
        ids = [str(x) for x in z["ids"]]
        store["ids"] = ids
        store["dur"] = list(z["durations"].astype(np.float32))
        store["onset"] = _split(z["note_onset"].astype(np.float32), z["note_ptr"])
        store["ndur"] = _split(z["note_dur"].astype(np.float32), z["note_ptr"])
        store["midi"] = _split(z["note_midi"].astype(np.int16), z["note_ptr"])
        store["contour"] = _split(z["contour_data"].astype(np.float16), z["contour_ptr"])
        for i, v in enumerate(ids):
            known[v] = i
    return known, store


def _concat(arrays, dtype):
    if not arrays:
        return np.zeros(0, dtype), np.zeros(1, np.int64)
    ptr = np.zeros(len(arrays) + 1, np.int64)
    ptr[1:] = np.cumsum([a.shape[0] for a in arrays])
    return np.concatenate(arrays).astype(dtype), ptr


def checkpoint(out_path, store, meta):
    onset, note_ptr = _concat(store["onset"], np.float32)
    ndur, _ = _concat(store["ndur"], np.float32)
    midi, _ = _concat(store["midi"], np.int16)
    contour, contour_ptr = _concat(store["contour"], np.float16)
    tmp = out_path + ".tmp.npz"
    np.savez(tmp,
             ids=np.array(store["ids"]),
             durations=np.asarray(store["dur"], dtype=np.float32),
             note_onset=onset, note_dur=ndur, note_midi=midi, note_ptr=note_ptr,
             contour_data=contour, contour_ptr=contour_ptr)
    os.replace(tmp, out_path)
    with open(os.path.splitext(out_path)[0] + ".meta.json", "w") as f:
        import json
        json.dump(meta, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/library.db")
    ap.add_argument("--out", default="data/melody_index.npz")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4, help="decode/bandpass prefetch threads")
    args = ap.parse_args()
    warnings.filterwarnings("ignore")

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model_ref = {"device": device}

    con = sqlite3.connect(args.db)
    rows = con.execute("select video_id, path, duration from tracks order by video_id").fetchall()
    con.close()

    known, store = load_existing(args.out)
    print(f"melody index: {len(rows)} tracks in db, {len(known)} already indexed  (device={device})")

    todo = [(vid, path, dur) for vid, path, dur in rows if vid not in known]
    if args.limit:
        todo = todo[:args.limit]
    print(f"to extract: {len(todo)}")
    if not todo:
        return 0

    meta = {"extractor": "torchcrepe", "version": EXTRACTOR_VERSION, "model": MODEL,
            "sr": SR, "hop": HOP, "frame_rate": FRAME_RATE, "bandpass_hz": list(BANDPASS),
            "crepe_fmin": CREPE_FMIN, "crepe_fmax": CREPE_FMAX, "conf_thresh": CONF_THRESH,
            "smoothing": "median-3", "notes": "onset_s,dur_s,midi from contour_to_notes"}

    done = 0
    times = []
    t_start = time.time()
    for (vid, path, dur), audio in prefetch(todo, args.workers, ahead=2 * args.workers):
        t0 = time.time()
        if audio is None or audio.size < SR // 2:
            print(f"  skip (no audio): {vid}")
            continue
        try:
            contour = extract_contour(audio, model_ref)
        except Exception as e:   # one bad track (CUDA OOM, codec junk) must not kill the run
            print(f"  skip ({type(e).__name__}: {e}): {vid}")
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            continue
        notes = contour_to_notes(np.asarray(contour, dtype=np.float64))
        dt = time.time() - t0

        store["ids"].append(vid)
        store["dur"].append(float(dur) if dur else len(audio) / SR)
        store["contour"].append(contour)
        store["onset"].append(notes[:, 0].astype(np.float32))
        store["ndur"].append(notes[:, 1].astype(np.float32))
        store["midi"].append(notes[:, 2].astype(np.int16))

        done += 1
        times.append(dt)
        if done % 25 == 0 or done == len(todo):
            avg = np.mean(times[-100:])
            eta = avg * (len(todo) - done)
            print(f"  [{done}/{len(todo)}] {vid} {len(notes)}notes {dt:.2f}s "
                  f"(avg {avg:.2f}s/trk, ETA {eta/60:.1f}m)")
        if done % CHECKPOINT_EVERY == 0:
            checkpoint(args.out, store, meta)
            print(f"  ...checkpointed {len(store['ids'])} tracks")

    checkpoint(args.out, store, meta)
    wall = time.time() - t_start
    print(f"done: +{done} tracks in {wall/60:.1f}m ({wall/max(1,done):.2f}s/track) "
          f"-> {args.out}  ({len(store['ids'])} total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
