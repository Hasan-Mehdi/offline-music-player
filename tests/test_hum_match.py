"""Tests for the pure hum-matching logic (scripts/melody_match.py): note segmentation,
transposition-invariant intervals, and the subsequence-DTW matcher. No audio / GPU / index
files are touched — a tiny in-memory MelodyIndex is built by hand.
Run: .venv\\Scripts\\python -m pytest -q tests/test_hum_match.py
"""
import sys

import numpy as np

sys.path.insert(0, "scripts")

import melody_match as mm  # noqa: E402


# ------------------------------------------------------------------ segmentation

def _contour(segments, fp=mm.FRAME_PERIOD):
    """Build a frame contour from (midi_or_None, seconds) segments."""
    frames = []
    for midi, secs in segments:
        k = int(round(secs / fp))
        frames += [np.nan if midi is None else float(midi)] * k
    return np.array(frames, dtype=np.float64)


def test_contour_to_notes_basic():
    # two clear notes separated by a silence -> exactly two notes at the right pitches
    c = _contour([(60, 0.5), (None, 0.3), (67, 0.4)])
    notes = mm.contour_to_notes(c)
    assert notes.shape[0] == 2
    assert round(notes[0, 2]) == 60 and round(notes[1, 2]) == 67
    assert notes[0, 0] == 0.0                      # first onset at t=0
    assert notes[1, 0] > notes[0, 0] + notes[0, 1]  # second starts after the gap


def test_short_notes_dropped():
    # a 1-frame blip (50 ms) is below MIN_NOTE_S and must be dropped
    c = _contour([(60, 0.4), (80, 0.05), (60, 0.4)])
    notes = mm.contour_to_notes(c)
    assert all(round(m) != 80 for m in notes[:, 2])


def test_notes_to_intervals_transposition_invariant():
    a = mm.notes_to_intervals([60, 64, 67, 65])
    b = mm.notes_to_intervals([48, 52, 55, 53])   # same melody, down an octave
    assert np.array_equal(a, b)
    assert list(a) == [4, 3, -2]


def test_interval_bigrams_encoding():
    keys = mm.interval_bigrams([4, 3, -2, 5])
    assert len(keys) == 3                          # 4 intervals -> 3 bigrams
    assert keys[0] != keys[1] != keys[2]
    # transposition-invariant tokens: same intervals -> same keys
    assert mm.interval_bigrams([4, 3, -2, 5]) == keys


# ------------------------------------------------------------------ subsequence DTW

def test_subseq_dtw_exact_subsequence():
    track = np.array([2, 2, 4, 3, -2, 5, -1, 0], dtype=np.float64)
    query = track[3:7].copy()                      # a contiguous slice
    cost, start = mm._subseq_dtw(query, track, mm.DTW_CLIP)
    assert cost < 1e-6
    assert start == 3                              # alignment begins where the slice does


def test_subseq_dtw_transposition_free():
    # intervals are already transposition-free; a phrase transposed +7 st yields
    # identical intervals, so DTW cost stays ~0.
    notes = np.array([60, 62, 65, 64, 67], dtype=np.int32)
    q_notes = notes + 7
    t_iv = mm.notes_to_intervals(notes).astype(np.float64)
    q_iv = mm.notes_to_intervals(q_notes).astype(np.float64)
    cost, _ = mm._subseq_dtw(q_iv, t_iv, mm.DTW_CLIP)
    assert cost < 1e-6


def test_subseq_dtw_dropout_tolerance():
    track = np.array([3, -1, 2, 4, -2, 1, 5, -3], dtype=np.float64)
    # drop the middle element of a slice (a merged note) -> still a low cost, not blown up
    q = np.array([3, -1, 4, -2, 1], dtype=np.float64)   # note: 2 dropped after -1
    cost, start = mm._subseq_dtw(q, track, mm.DTW_CLIP)
    assert cost < 1.5
    assert start == 0


def test_dtw_transpose_absolute_invariant():
    # absolute-pitch DTW: a phrase transposed within +/-OFFSET_R still aligns at ~0 cost via
    # the integer key-offset search (this is where transposition invariance now lives).
    track = np.array([60, 62, 65, 64, 67, 69, 67, 65], dtype=np.float64)
    q = track[2:6] + float(mm.OFFSET_R)        # a slice, transposed to the search edge
    cost, start = mm._dtw_transpose(q, track, mm.DTW_CLIP, mm.OFFSET_R)
    assert cost < 1e-6
    assert start == 2
    # beyond the search range the offset can't be undone -> no longer ~0 cost
    q_far = track[2:6] + float(mm.OFFSET_R + 3)
    cost_far, _ = mm._dtw_transpose(q_far, track, mm.DTW_CLIP, mm.OFFSET_R)
    assert cost_far > 0.5


# ------------------------------------------------------------------ match_query end-to-end

def _mini_index(seqs):
    """Build a MelodyIndex from {id: [midi,...]} with no db/contour."""
    ids = list(seqs)
    note_midi, note_onset, pitch, pitch_onset = [], [], [], []
    for vid in ids:
        m = np.array(seqs[vid], dtype=np.int32)
        o = np.arange(m.size, dtype=np.float32) * 0.5
        p, po = mm.melody_seq(m, o)            # collapse repeats -> absolute pitch
        note_midi.append(m); note_onset.append(o)
        pitch.append(p.astype(np.float64)); pitch_onset.append(po)
    gram = {}
    for i, p in enumerate(pitch):
        for key in mm.interval_bigrams(mm.notes_to_intervals(p)):
            gram.setdefault(key, []).append(i)
    return mm.MelodyIndex(ids=ids, id2i={v: i for i, v in enumerate(ids)},
                          durations=np.zeros(len(ids), np.float32),
                          note_midi=note_midi, note_onset=note_onset, pitch=pitch,
                          pitch_onset=pitch_onset, gram_index=gram)


def test_match_query_ranks_true_track_first():
    idx = _mini_index({
        "AAA": [60, 62, 64, 65, 67, 69, 71, 72, 70, 68],
        "BBB": [50, 55, 53, 58, 60, 55, 52, 57, 59, 61],
        "CCC": [72, 71, 69, 67, 65, 64, 62, 60, 59, 57],
    })
    # a transposed 5-note phrase out of AAA (down 3 semitones)
    q_pitch = np.array([64, 65, 67, 69, 71], dtype=np.float64) - 3
    res = mm.match_query(idx, q_pitch, candidates=list(range(len(idx))), top_n=3)
    assert idx.ids[res[0][0]] == "AAA"
    assert res[0][1] > res[1][1]                   # winner strictly ahead
    # start_s maps to the note where the phrase begins (index 2 -> 2*0.5s)
    assert abs(res[0][2] - 1.0) < 1e-6


def test_match_query_returns_start_and_score_range():
    idx = _mini_index({"X": [60, 64, 67, 72, 67, 64, 60, 62, 64, 65]})
    q_pitch = np.array([60, 64, 67, 72], dtype=np.float64)
    res = mm.match_query(idx, q_pitch, candidates=[0], top_n=1)
    i, score, start = res[0]
    assert 0.0 < score <= 1.0
    assert start == 0.0


# ------------------------------------------------------------------ prefilter at scale

def test_prefilter_not_fooled_by_giant_tracks():
    # Regression: ranking candidates by raw shared-bigram occurrences let long, note-dense
    # tracks (10-hour mixes hold nearly every possible bigram, many times) crowd the true
    # match out of the pool. IDF-cosine over unique bigrams must keep the true track in a
    # small candidate set even against every-bigram giants.
    rng = np.random.default_rng(3)
    phrase = [60, 62, 64, 62, 60, 65, 67, 64, 60, 59, 60, 67]
    seqs = {}
    filler = [int(60 + v) for v in rng.integers(-7, 8, size=30)]
    seqs["TRUE"] = filler[:15] + phrase + filler[15:]
    for g in range(5):   # giants: ~3000-note walks containing almost every bigram key
        walk = 60 + (np.cumsum(rng.integers(-6, 7, size=3000)) % 24)
        seqs[f"GIANT{g}"] = [int(v) for v in walk]
    for j in range(1250):  # filler pool pushes the index past BRUTE_MAX
        seqs[f"F{j}"] = [int(60 + v) for v in rng.integers(-9, 10, size=25)]
    idx = _mini_index(seqs)
    assert len(idx) > mm.BRUTE_MAX
    q_pitch, _ = mm.melody_seq(np.array(phrase, dtype=np.int32))
    cands = mm.prefilter(idx, mm.notes_to_intervals(q_pitch), k=50)
    assert idx.id2i["TRUE"] in set(cands)
