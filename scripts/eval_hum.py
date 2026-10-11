#!/usr/bin/env python3
"""Synthetic-hum evaluation for the query-by-humming pipeline.

Nobody can hum during development, so we fake it: sample N indexed tracks, pull a
voiced-dense 8-15 s phrase from each track's *extracted* melody, render it as a tone
(triangle wave following the pitch, with humanising perturbations), write a wav, and run
it through the FULL public pipeline (melody_match.search_hum on the rendered wav — no
shortcuts). Reports top-1/5/10 hit rate + MRR@10 per perturbation tier and dumps JSON.

Tiers (progressively harder, as specified):
  easy   : exact melody, light vibrato (+/-30 cents @5Hz), original key/tempo
  medium : transpose +/-1..5 st, tempo x0.8-1.25, pitch jitter +/-50 cents, 10% dropout
  hard   : medium + 20% dropout + +/-1 st interval error on 20% of notes

Usage: python scripts/eval_hum.py [--tracks 60] [--seed 0] [--tiers easy,medium,hard]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import melody_match as mm

RENDER_SR = 16000
WINDOW_CHOICES = (12.0, 10.0, 8.0)   # try longest first, shrink if too sparse
MIN_VOICED_FRAC = 0.35


def track_contour(index, i):
    a, b = int(index.contour_ptr[i]), int(index.contour_ptr[i + 1])
    return index.contour_data[a:b].astype(np.float64)


def pick_phrase(contour, rng):
    """Densest voiced window in a frame-level MIDI contour. Tries 12/10/8 s windows and
    returns the first with enough voiced coverage, else None."""
    fp = mm.FRAME_PERIOD
    voiced = ~np.isnan(contour)
    csum = np.concatenate([[0], np.cumsum(voiced.astype(np.int32))])
    for win_s in WINDOW_CHOICES:
        w = min(int(round(win_s / fp)), contour.shape[0])
        if w < int(round(8.0 / fp)) and win_s != WINDOW_CHOICES[-1]:
            continue
        best_j, best_v = 0, -1
        for j in range(0, max(1, contour.shape[0] - w + 1), max(1, w // 8)):
            v = csum[j + w] - csum[j]
            if v > best_v:
                best_v, best_j = v, j
        if best_v >= w * MIN_VOICED_FRAC:
            return contour[best_j:best_j + w]
    return None


def perturb_notes(notes, tier, rng):
    """Apply a tier's humanising perturbations at the note level. notes: (N,3)
    (onset_s, dur_s, midi). Returns a new list of (dur_s, midi_float) note events."""
    out = []
    transpose = 0.0
    tempo = 1.0
    if tier in ("medium", "hard"):
        transpose = rng.choice([-5, -4, -3, -2, -1, 1, 2, 3, 4, 5])
        tempo = rng.uniform(0.8, 1.25)
    drop_p = {"easy": 0.0, "medium": 0.10, "hard": 0.20}[tier]
    jitter = {"easy": 0.0, "medium": 0.50, "hard": 0.50}[tier]   # cents/100 (semitone amp)
    interval_err_p = 0.20 if tier == "hard" else 0.0
    for onset, dur, midi in notes:
        if rng.random() < drop_p:
            continue
        p = float(midi) + transpose
        if jitter:
            p += rng.uniform(-jitter, jitter)
        if interval_err_p and rng.random() < interval_err_p:
            p += rng.choice([-1.0, 1.0])
        out.append((float(dur) / tempo, p))
    return out


def render_hum(pert_notes, tier, rng, sr=RENDER_SR):
    """Render perturbed notes to a mono waveform: triangle-ish tone per note with
    +/-30 cent 5 Hz vibrato and short envelopes; ~60 ms silence between notes ('na-na').
    (60 ms > one 50 ms analysis frame, so pyin resolves each articulated note.)"""
    gap = np.zeros(int(0.06 * sr), dtype=np.float32)
    vib_hz, vib_semi = 5.0, 0.30
    chunks = []
    for dur, midi in pert_notes:
        n = max(int(dur * sr), int(0.06 * sr))
        t = np.arange(n) / sr
        vib = vib_semi * np.sin(2 * np.pi * vib_hz * t + rng.uniform(0, 6.28))
        f = 440.0 * 2.0 ** ((midi - 69.0 + vib) / 12.0)
        phase = 2 * np.pi * np.cumsum(f) / sr
        # triangle wave (odd harmonics -> voice-like, tracks well under pyin)
        w = 2.0 / np.pi * np.arcsin(np.sin(phase))
        env = np.ones(n, dtype=np.float32)
        a = max(1, int(0.01 * sr))
        env[:a] = np.linspace(0, 1, a)
        env[-a:] = np.linspace(1, 0, a)
        chunks.append((0.6 * w * env).astype(np.float32))
        chunks.append(gap)
    if not chunks:
        return np.zeros(sr, dtype=np.float32)
    y = np.concatenate(chunks)
    y += (0.003 * rng.standard_normal(y.shape[0])).astype(np.float32)  # faint noise floor
    return y


def run_tier(index, sample_ids, tier, rng, tmpdir):
    import soundfile as sf
    ranks = []
    used = 0
    for vid in sample_ids:
        i = index.id2i[vid]
        phrase = pick_phrase(track_contour(index, i), rng)
        if phrase is None:
            continue
        notes = mm.contour_to_notes(phrase)
        if notes.shape[0] < mm.MIN_QUERY_NOTES + 1:
            continue
        pert = perturb_notes(notes, tier, rng)
        if len(pert) < mm.MIN_QUERY_NOTES:
            continue
        y = render_hum(pert, tier, rng)
        wav = os.path.join(tmpdir, f"hum_{vid}_{tier}.wav")
        sf.write(wav, y, RENDER_SR)
        try:
            out = mm.search_hum(index, wav, top_n=10)
        except ValueError:
            ranks.append(0)   # pipeline rejected the query -> a miss
            used += 1
            continue
        rank = 0
        for r, res in enumerate(out["results"], 1):
            if res["video_id"] == vid:
                rank = r
                break
        ranks.append(rank)
        used += 1
        os.remove(wav)
    ranks = np.array(ranks)
    n = len(ranks)
    hit = lambda k: float(np.mean((ranks >= 1) & (ranks <= k))) if n else 0.0
    mrr = float(np.mean([1.0 / r if r >= 1 else 0.0 for r in ranks])) if n else 0.0
    return {"n": int(n), "top1": hit(1), "top5": hit(5), "top10": hit(10), "mrr": mrr}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=mm.DEFAULT_DB)
    ap.add_argument("--index", default=mm.DEFAULT_INDEX)
    ap.add_argument("--tracks", type=int, default=60)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--out", default="data/hum_eval.json")
    args = ap.parse_args()

    index = mm.load_index(args.db, args.index)
    rng = np.random.default_rng(args.seed)
    pool = list(index.ids)
    rng.shuffle(pool)
    sample_ids = pool[:args.tracks]
    print(f"eval: {len(index)} indexed tracks, sampling {len(sample_ids)} queries per tier")

    results = {}
    tmpdir = tempfile.mkdtemp(prefix="hum_eval_")
    for tier in args.tiers.split(","):
        tier = tier.strip()
        # re-seed per tier so tiers are comparable (same tracks, same base phrase choices)
        res = run_tier(index, sample_ids, tier, np.random.default_rng(args.seed + 1), tmpdir)
        results[tier] = res

    print(f"\n{'tier':<8}{'n':<5}{'top1':<8}{'top5':<8}{'top10':<8}{'MRR@10'}")
    for tier, r in results.items():
        print(f"{tier:<8}{r['n']:<5}{r['top1']*100:<8.1f}{r['top5']*100:<8.1f}"
              f"{r['top10']*100:<8.1f}{r['mrr']:.3f}")

    with open(args.out, "w") as f:
        json.dump({"n_indexed": len(index), "sample": args.tracks, "seed": args.seed,
                   "tiers": results}, f, indent=2)
    print(f"\nsaved -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
