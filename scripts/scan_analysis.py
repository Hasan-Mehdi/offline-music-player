#!/usr/bin/env python3
r"""Per-track audio analysis sweep -> the `analysis` table in data/library.db.

One ffmpeg decode per track (mono 22050, same pipe trick as muq_run / build_melody_index,
since librosa/soundfile can't read opus), then six cheap descriptors:

  bpm        librosa tempogram estimate (median-aggregated, so it doesn't wobble per frame)
  key        mean chroma vs Krumhansl-Schmuckler major/minor profiles -> "C", "F#m", ...
  energy_db  20*log10(mean RMS) over frames above a -60 dBFS floor (silence can't drag it down)
  hook_sec   start of the loudest 15 s window -> the player's sneak-peek point
  lead_sec   first moment the track is properly audible (> -35 dBFS for >= 0.3 s)
  tail_sec   last such moment (i.e. where the fade-out/silence begins)

bpm and key run on the centre 120 s only (a chorus-to-chorus slice is as good a tempo/key
witness as the whole file and ~3x cheaper); RMS, energy and the silence bounds always run
over the FULL decode, since hook/lead/tail are positions in the real track.

Resumable: video_ids already in `analysis` are skipped, so it's safe to Ctrl-C, and cheap
to re-run after a download batch. Writes commit in batches with busy_timeout set, so a
running server or a parallel scanner holding the db just delays us instead of erroring.

Run:  .venv\Scripts\python scripts\scan_analysis.py --limit 300      # sample
      .venv\Scripts\python scripts\scan_analysis.py --workers 4      # full sweep
"""
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import time
from multiprocessing import Pool

import numpy as np

SR = 22050
HOP = 512
FRAME = 2048
FRAME_SEC = HOP / SR
CENTER_S = 120.0          # bpm/key window (0 = whole track)
WIN_S = 15.0              # hook window length
SMOOTH_S = 1.5            # RMS smoothing before the hook search
FLOOR_DB = -60.0          # frames below this don't count toward energy_db
SILENCE_DB = -35.0        # "audible" threshold for lead/tail
SUSTAIN_S = 0.3           # ...held this long before it counts
VER = 1

SCHEMA = ("CREATE TABLE IF NOT EXISTS analysis(video_id TEXT PRIMARY KEY, bpm REAL, "
          "key TEXT, energy_db REAL, hook_sec REAL, lead_sec REAL, tail_sec REAL, "
          "ver INTEGER DEFAULT 1)")

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


# ----------------------------------------------------------------------- audio ---------

def decode(path, sr=SR):
    """Decode to mono float32 at `sr` through an ffmpeg pipe. None if empty/unreadable."""
    raw = subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(path), "-ac", "1",
                          "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, timeout=600).stdout
    a = np.frombuffer(raw, dtype=np.float32).copy()
    return a if a.size else None


def center_slice(y, sr=SR, secs=CENTER_S):
    if not secs or y.size <= secs * sr:
        return y
    n = int(secs * sr)
    s = (y.size - n) // 2
    return y[s:s + n]


def rms_frames(y):
    import librosa
    return librosa.feature.rms(y=y, frame_length=FRAME, hop_length=HOP)[0]


# ----------------------------------------------------------------- descriptors ---------

def energy_db(rms, floor_db=FLOOR_DB):
    """Loudness of the parts that are actually playing, in dBFS."""
    rms = np.asarray(rms, dtype=np.float64)
    if rms.size == 0:
        return -120.0
    keep = rms[20 * np.log10(np.maximum(rms, 1e-10)) > floor_db]
    if keep.size == 0:
        keep = rms
    return float(20 * np.log10(max(float(keep.mean()), 1e-10)))


def hook_seconds(rms, duration, frame_sec=FRAME_SEC, win_s=WIN_S, smooth_s=SMOOTH_S):
    """Start of the highest-mean-RMS `win_s` window, clamped to [3, duration-20]."""
    lo = 3.0
    hi = max(3.0, (duration or 0.0) - 20.0)
    rms = np.asarray(rms, dtype=np.float64)
    if rms.size == 0:
        return lo
    k = max(1, int(round(smooth_s / frame_sec)))
    sm = np.convolve(rms, np.ones(k) / k, mode="same")
    w = max(1, int(round(win_s / frame_sec)))
    if sm.size <= w:
        return lo
    c = np.concatenate(([0.0], np.cumsum(sm)))
    means = c[w:] - c[:-w]
    start = float(np.argmax(means)) * frame_sec
    return float(min(max(start, lo), hi))


def silence_bounds(rms, duration, frame_sec=FRAME_SEC, thresh_db=SILENCE_DB,
                   sustain_s=SUSTAIN_S):
    """(lead_sec, tail_sec): first and last audible moments, ignoring blips shorter
    than `sustain_s` so a click in a fade-in doesn't count as the start."""
    dur = float(duration or 0.0)
    rms = np.asarray(rms, dtype=np.float64)
    if rms.size == 0:
        return 0.0, dur
    loud = 20 * np.log10(np.maximum(rms, 1e-10)) > thresh_db
    need = max(1, int(round(sustain_s / frame_sec)))
    edges = np.diff(np.concatenate(([0], loud.view(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    ok = (ends - starts) >= need
    if not ok.any():
        return 0.0, dur or float(rms.size * frame_sec)
    starts, ends = starts[ok], ends[ok]
    lead = float(starts[0]) * frame_sec
    tail = float(ends[-1]) * frame_sec
    if dur:
        tail = min(tail, dur)
        lead = min(lead, dur)
    return lead, tail


def estimate_bpm(y, sr=SR):
    """Median-aggregated tempogram peak — one float, stable across the track."""
    import librosa
    if y.size < sr:
        return None
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    if not np.isfinite(onset).any() or onset.max() <= 0:
        return None
    t = librosa.feature.tempo(onset_envelope=onset, sr=sr, hop_length=HOP,
                              aggregate=np.median)
    v = float(np.atleast_1d(t)[0])
    return v if np.isfinite(v) and v > 0 else None


def key_from_chroma(chroma):
    """Krumhansl-Schmuckler: correlate the mean chroma against all 24 rotated profiles."""
    v = np.asarray(chroma, dtype=np.float64)
    if v.size != 12 or not np.isfinite(v).all() or v.sum() <= 0:
        return None
    v = v - v.mean()
    if not np.any(v):
        return None
    best, best_r = None, -2.0
    for i in range(12):
        for prof, suffix in ((KS_MAJOR, ""), (KS_MINOR, "m")):
            p = np.roll(prof, i)
            p = p - p.mean()
            r = float(np.dot(v, p) / (np.linalg.norm(v) * np.linalg.norm(p)))
            if r > best_r:
                best_r, best = r, NOTES[i] + suffix
    return best


def estimate_key(y, sr=SR):
    import librosa
    if y.size < sr // 2:
        return None
    try:
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP)
    except Exception:
        chroma = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=HOP)
    return key_from_chroma(chroma.mean(axis=1))


def analyze_audio(y, sr=SR, duration=None, center_s=CENTER_S):
    """All six descriptors from a decoded mono signal. Pure — no db, no ffmpeg."""
    y = np.asarray(y, dtype=np.float32)
    dur = float(duration) if duration else y.size / float(sr)
    rms = rms_frames(y)
    frame_sec = HOP / float(sr)
    lead, tail = silence_bounds(rms, dur, frame_sec)
    mid = center_slice(y, sr, center_s)
    return {"bpm": estimate_bpm(mid, sr),
            "key": estimate_key(mid, sr),
            "energy_db": energy_db(rms),
            "hook_sec": hook_seconds(rms, dur, frame_sec),
            "lead_sec": lead,
            "tail_sec": tail}


# ---------------------------------------------------------------------- worker ---------

def analyze_track(job):
    """(video_id, path, duration, center_s) -> (video_id, row_or_None, error_or_None).
    center_s rides along in the job because Windows spawns fresh workers that would not
    see a module global set from argv in the parent."""
    vid, path, duration, center_s = job
    try:
        y = decode(path)
        if y is None or y.size < SR // 2:
            return vid, None, "no audio"
        a = analyze_audio(y, SR, duration, center_s)
        return vid, (vid, a["bpm"], a["key"], a["energy_db"], a["hook_sec"],
                     a["lead_sec"], a["tail_sec"], VER), None
    except Exception as e:
        return vid, None, f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="data/library.db")
    ap.add_argument("--workers", type=int, default=4, help="decode/analysis processes")
    ap.add_argument("--limit", type=int, default=None, help="analyse at most N new tracks")
    ap.add_argument("--batch", type=int, default=100, help="rows per commit")
    ap.add_argument("--center", type=float, default=CENTER_S,
                    help="seconds of centre audio used for bpm/key (0 = whole track)")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA busy_timeout=15000")     # server / other scanners hold this db
    con.execute(SCHEMA)
    con.commit()
    done = {r[0] for r in con.execute("SELECT video_id FROM analysis")}
    rows = con.execute("SELECT video_id, path, duration FROM tracks ORDER BY video_id").fetchall()
    todo = [(v, p, d, args.center) for v, p, d in rows if v not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"analysis: {len(rows)} tracks in db, {len(done)} already analysed, "
          f"{len(todo)} to do  (workers={args.workers})")
    if not todo:
        con.close()
        return 0

    ok = errors = 0
    pending = []
    t0 = time.time()
    with Pool(processes=max(1, args.workers)) as pool:
        for vid, row, err in pool.imap_unordered(analyze_track, todo, chunksize=4):
            if err:
                errors += 1
                print(f"  skip {vid}: {err}")
                continue
            pending.append(row)
            ok += 1
            if len(pending) >= args.batch:
                con.executemany("INSERT OR REPLACE INTO analysis VALUES (?,?,?,?,?,?,?,?)",
                                pending)
                con.commit()
                pending.clear()
            if ok % 50 == 0 or ok == len(todo):
                el = time.time() - t0
                eta = (el / ok) * (len(todo) - ok)
                print(f"  [{ok}/{len(todo)}] {el/ok:.2f}s/track  ETA {eta/60:.1f}m", flush=True)
    if pending:
        con.executemany("INSERT OR REPLACE INTO analysis VALUES (?,?,?,?,?,?,?,?)", pending)
        con.commit()
    wall = time.time() - t0
    con.close()
    print(f"done: +{ok} analysed, {errors} failed in {wall/60:.1f}m "
          f"({wall/max(1, ok):.2f}s/track wall)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
