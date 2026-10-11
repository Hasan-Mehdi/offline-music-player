#!/usr/bin/env python3
"""Query-by-humming matcher for the offline library.

Two roles:
  1. A pure-logic module (note segmentation, interval n-grams, subsequence DTW) shared
     with scripts/build_melody_index.py and covered by tests/test_hum_match.py.
  2. A query pipeline: decode any audio ffmpeg can read -> pyin monophonic pitch track ->
     match against data/melody_index.npz. Used by a Flask endpoint (search_hum) and as a
     CLI (python scripts/melody_match.py <audiofile>).

Matching is transposition-invariant (we align pitch *intervals*, so the sung key cancels)
and tempo-tolerant (durations are ignored; subsequence DTW warps time freely). An
IDF-cosine inverted index over per-track unique interval bigrams prefilters to ~800
candidates so it scales to 50k tracks; the fine stage is a clipped-L1 subsequence DTW
whose inner loop is numba-compiled.

Public contract (a separate agent builds a Flask endpoint against this — do not change):
    load_index(db_path, index_path) -> MelodyIndex        # fast, <2s
    search_hum(index, audio_path, top_n=10) -> dict
"""
from __future__ import annotations

import json
import os
import subprocess
import sqlite3
import sys
from dataclasses import dataclass, field

import numpy as np

# --- fixed geometry: everything (index + query) lives on a 20 Hz frame grid ------------
SR = 16000
HOP = 800                      # 800 / 16000 = 0.05 s  ->  20 Hz
FRAME_PERIOD = HOP / SR
FRAME_RATE = SR / HOP

# note segmentation
PITCH_TOL = 0.75               # semitones a frame may drift from the running note median
MIN_NOTE_S = 0.10              # notes shorter than this are dropped (2 frames)
MERGE_GAP_S = 0.12             # same-pitch notes across a gap this short are merged

# matching
DTW_CLIP = 3.0                 # cap per-cell |pitch error| so one sloppy/dropped note can't dominate
OFFSET_R = 5                   # +/- semitone key-offset search (matches the spec's +/-5 transposition;
                               # a tight range also stops wrong tracks finding a spurious good key)
PREFILTER_K = 4000             # candidates kept by the bigram prefilter (above BRUTE_MAX);
                               # measured at 20k tracks: true-track recall 0.48@800 ->
                               # 0.83@4000 for ~0.4s of numba DTW — cheap headroom
GRAM_JITTER_W = 0.4            # prefilter credit for a bigram one semitone off (sloppy pitch)
GRAM_MERGE_W = 0.6             # prefilter credit for sum-collapsed bigrams (a note pyin split
                               # in two sings as intervals a,b where the track has a+b)
BRUTE_MAX = 1200               # <= this many tracks -> lossless brute force (still <2s)
MIN_QUERY_NOTES = 4
MIN_QUERY_VOICED_S = 2.0

DEFAULT_INDEX = "data/melody_index.npz"
DEFAULT_DB = "data/library.db"


# ----------------------------------------------------------------- audio / pitch ------

def decode_audio(path, sr=SR, max_s=None):
    """Decode any ffmpeg-readable file to mono float32 at `sr`. Returns None if empty.
    max_s caps the decoded duration (the index build uses it so multi-hour mixes can't
    blow up memory)."""
    cmd = ["ffmpeg", "-v", "quiet", "-i", str(path), "-ac", "1", "-ar", str(sr)]
    if max_s:
        cmd += ["-t", str(max_s)]
    raw = subprocess.run(cmd + ["-f", "f32le", "-"], capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32).copy()
    return a if a.size else None


def hz_to_midi(f0):
    f0 = np.asarray(f0, dtype=np.float64)
    out = np.full(f0.shape, np.nan)
    ok = f0 > 0
    out[ok] = 69.0 + 12.0 * np.log2(f0[ok] / 440.0)
    return out


def pyin_contour(audio, sr=SR, fmin=75.0, fmax=1500.0):
    """Monophonic pitch track of a hum/whistle via librosa pyin, on the 20 Hz grid.

    Returns a float MIDI contour with NaN on unvoiced frames. fmin/fmax bracket the
    expected human range (MIDI ~40-90). frame_length=1024 (64 ms) keeps enough periods for
    fmin=75 Hz while giving better note-onset resolution than the default 2048."""
    import librosa
    f0, voiced, _ = librosa.pyin(
        audio, fmin=fmin, fmax=fmax, sr=sr, frame_length=1024, hop_length=HOP,
        center=True, fill_na=np.nan)
    midi = hz_to_midi(f0)
    midi[~voiced] = np.nan
    return midi.astype(np.float32)


# ----------------------------------------------------------------- note segmentation --

def contour_to_notes(midi, frame_period=FRAME_PERIOD, pitch_tol=PITCH_TOL,
                     min_note_s=MIN_NOTE_S, merge_gap_s=MERGE_GAP_S):
    """Segment a frame-level MIDI contour (NaN = unvoiced) into note events.

    A note is a run of voiced frames whose pitch stays within `pitch_tol` of the run's
    running median; it breaks on an unvoiced frame or a pitch jump. Same-pitch notes
    separated by a gap <= merge_gap_s are merged (bridges brief unvoiced dropouts).
    Returns an (N,3) float array of (onset_s, dur_s, midi) with midi rounded to semitones.
    """
    midi = np.asarray(midi, dtype=np.float64)
    n = midi.shape[0]
    min_frames = max(1, int(round(min_note_s / frame_period)))
    notes = []  # [start_frame, end_frame_exclusive, pitch]
    run = []
    start = 0
    for i in range(n):
        v = midi[i]
        if np.isnan(v):
            if len(run) >= min_frames:
                notes.append([start, i, float(np.median(run))])
            run = []
            continue
        if not run:
            run = [v]
            start = i
        elif abs(v - np.median(run)) <= pitch_tol:
            run.append(v)
        else:
            if len(run) >= min_frames:
                notes.append([start, i, float(np.median(run))])
            run = [v]
            start = i
    if len(run) >= min_frames:
        notes.append([start, n, float(np.median(run))])

    # merge same-(rounded)-pitch neighbours across short gaps
    merged = []
    merge_gap_frames = merge_gap_s / frame_period
    for nt in notes:
        if merged:
            prev = merged[-1]
            gap = nt[0] - prev[1]
            if gap <= merge_gap_frames and round(prev[2]) == round(nt[2]):
                prev[1] = nt[1]
                continue
        merged.append(nt)

    out = np.empty((len(merged), 3), dtype=np.float32)
    for k, (s, e, p) in enumerate(merged):
        out[k, 0] = s * frame_period
        out[k, 1] = (e - s) * frame_period
        out[k, 2] = float(round(p))
    return out


def notes_to_intervals(note_midi):
    """Consecutive semitone intervals, clipped to +/-12 (octave). int16."""
    m = np.asarray(note_midi, dtype=np.int32)
    if m.size < 2:
        return np.zeros(0, dtype=np.int16)
    d = np.diff(m)
    return np.clip(d, -12, 12).astype(np.int16)


def collapse_repeats(note_midi, note_onset=None):
    """Merge runs of consecutive same-pitch notes into one (keeping the earliest onset).

    Critical for query-by-humming: a held/re-articulated note shows up as several
    same-pitch notes in the polyphonic index but as ONE note when a person hums it (and
    when pyin tracks that hum). Collapsing both sides removes those spurious 0-intervals so
    the interval sequences line up. Returns (pitch:int32, onset:float32)."""
    m = np.asarray(note_midi, dtype=np.int32)
    if m.size == 0:
        return m, (np.zeros(0, np.float32) if note_onset is not None else None)
    keep = np.concatenate([[True], m[1:] != m[:-1]])
    pitch = m[keep]
    if note_onset is None:
        return pitch, None
    return pitch, np.asarray(note_onset, dtype=np.float32)[keep]


def melody_seq(note_midi, note_onset=None):
    """Repeat-collapsed absolute-pitch melody sequence used by the matcher.

    Matching is on ABSOLUTE (repeat-collapsed) semitone pitch, not first-order intervals: a
    single sloppy/dropped note then corrupts only one alignment cell instead of two, which
    measurably improves robustness (esp. the hard tier). Transposition is handled at match
    time by an integer key-offset search. Returns (pitch:int16, onset:float32)."""
    pitch, onset = collapse_repeats(note_midi, note_onset)
    return pitch.astype(np.int16), onset


def interval_bigrams(intervals):
    """Encode overlapping interval bigrams (pairs) as ints. Bigrams survive per-note pitch
    errors better than trigrams, so the prefilter keeps recall high under sloppy humming."""
    iv = np.asarray(intervals, dtype=np.int32) + 12
    return [int(iv[k] * 25 + iv[k + 1]) for k in range(iv.size - 1)]


# ----------------------------------------------------------------- subsequence DTW ----

try:
    from numba import njit
except Exception:  # numba is a hard dep but degrade to pure python if unavailable
    def njit(*a, **k):
        def deco(f):
            return f
        return deco if a and callable(a[0]) is False else (a[0] if a else deco)


@njit(cache=True)
def _subseq_dtw(q, t, clip):
    """Subsequence DTW of full query intervals q against any contiguous run of t.

    Free start (first row = local cost) and free end (min over last row). Local cost is
    clipped L1 on intervals, so pitch is transposition-invariant and one blown interval
    (a dropped note) is capped. Returns (avg_cost_per_query_interval, start_index_in_t).
    """
    m = q.shape[0]
    n = t.shape[0]
    if m == 0 or n == 0:
        return 1e9, 0
    INF = 1e18
    d_prev = np.empty(n, dtype=np.float64)
    d_cur = np.empty(n, dtype=np.float64)
    s_prev = np.empty(n, dtype=np.int64)
    s_cur = np.empty(n, dtype=np.int64)

    # row 0: query interval 0 may align to any t[j] for free (subsequence start)
    for j in range(n):
        c = abs(q[0] - t[j])
        if c > clip:
            c = clip
        d_prev[j] = c
        s_prev[j] = j

    for i in range(1, m):
        for j in range(n):
            c = abs(q[i] - t[j])
            if c > clip:
                c = clip
            # predecessors: diag (match), left (skip a track note), up (skip a query note)
            best = d_prev[j]            # up  (i-1, j)
            sbest = s_prev[j]
            if j > 0:
                if d_prev[j - 1] < best:
                    best = d_prev[j - 1]  # diag (i-1, j-1)
                    sbest = s_prev[j - 1]
                if d_cur[j - 1] < best:
                    best = d_cur[j - 1]   # left (i, j-1)
                    sbest = s_cur[j - 1]
            if best >= INF:
                d_cur[j] = INF
                s_cur[j] = j
            else:
                d_cur[j] = c + best
                s_cur[j] = sbest
        for j in range(n):
            d_prev[j] = d_cur[j]
            s_prev[j] = s_cur[j]

    best = d_prev[0]
    start = s_prev[0]
    for j in range(1, n):
        if d_prev[j] < best:
            best = d_prev[j]
            start = s_prev[j]
    return best / m, start


@njit(cache=True)
def _dtw_transpose(q, t, clip, R):
    """Transposition-invariant subsequence DTW on absolute pitch: try integer key offsets
    -R..R and keep the best. The query is the same recording's melody shifted only by the
    singer's mis-keying, so the offset that re-aligns it is small (undo the transposition) and
    independent of the track's median register -> a fixed search around 0, not a median guess.
    Returns (best_avg_cost, start_index)."""
    best = 1e18
    bstart = 0
    for d in range(-R, R + 1):
        cost, start = _subseq_dtw(q + float(d), t, clip)
        if cost < best:
            best = cost
            bstart = start
    return best, bstart


# ----------------------------------------------------------------- index -------------

@dataclass
class MelodyIndex:
    ids: list
    id2i: dict
    durations: np.ndarray
    note_midi: list           # per-track int32 note-pitch arrays
    note_onset: list          # per-track float32 onset arrays
    pitch: list               # per-track repeat-collapsed absolute pitch (float64, for DTW)
    pitch_onset: list         # per-track float32 onset aligned to `pitch`
    contour_ptr: np.ndarray = None
    contour_data: np.ndarray = None
    gram_index: dict = field(default_factory=dict)      # bigram key -> list of track indices
    gram_postings: dict = None      # bigram key -> unique int32 track indices (built lazily)
    gram_idf: dict = None           # bigram key -> idf weight
    gram_norm: np.ndarray = None    # per-track vector norm for cosine scoring
    titles: dict = field(default_factory=dict)
    artists: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)

    def __len__(self):
        return len(self.ids)


def _load_npz(index_path):
    z = np.load(index_path, allow_pickle=False)
    ids = [str(x) for x in z["ids"]]
    durations = z["durations"].astype(np.float32)
    n_ptr = z["note_ptr"]
    onset_all = z["note_onset"]
    midi_all = z["note_midi"]
    note_midi, note_onset, pitch, pitch_onset = [], [], [], []
    for i in range(len(ids)):
        a, b = int(n_ptr[i]), int(n_ptr[i + 1])
        m = midi_all[a:b].astype(np.int32)
        o = onset_all[a:b].astype(np.float32)
        note_midi.append(m)
        note_onset.append(o)
        p, po = melody_seq(m, o)
        pitch.append(p.astype(np.float64))
        pitch_onset.append(po if po is not None else np.zeros(0, np.float32))
    c_ptr = z["contour_ptr"] if "contour_ptr" in z.files else None
    c_data = z["contour_data"] if "contour_data" in z.files else None
    z.close()
    return ids, durations, note_midi, note_onset, pitch, pitch_onset, c_ptr, c_data


def _db_meta(db_path, ids):
    titles, artists = {}, {}
    if not (db_path and os.path.exists(db_path)):
        return titles, artists
    # generous busy timeout: batch writers (e.g. scan_loudness.py) hold long write locks
    # and a hum search must not 500 because of one
    con = sqlite3.connect(db_path, timeout=30)
    idset = set(ids)
    for vid, title, artist in con.execute("select video_id, title, artist from tracks"):
        if vid in idset:
            titles[vid] = title or ""
            artists[vid] = artist or ""
    con.close()
    return titles, artists


def load_index(db_path=DEFAULT_DB, index_path=DEFAULT_INDEX) -> MelodyIndex:
    """Load the melody index + titles/artists and build the trigram inverted index. <2s."""
    (ids, durations, note_midi, note_onset, pitch, pitch_onset,
     c_ptr, c_data) = _load_npz(index_path)
    id2i = {v: i for i, v in enumerate(ids)}
    gram_postings, gram_idf, gram_norm = _build_gram_scoring(pitch)
    titles, artists = _db_meta(db_path, ids)
    meta = {}
    meta_path = os.path.splitext(index_path)[0] + ".meta.json"
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    return MelodyIndex(ids=ids, id2i=id2i, durations=durations, note_midi=note_midi,
                       note_onset=note_onset, pitch=pitch, pitch_onset=pitch_onset,
                       contour_ptr=c_ptr, contour_data=c_data,
                       gram_postings=gram_postings, gram_idf=gram_idf, gram_norm=gram_norm,
                       titles=titles, artists=artists, meta=meta)


# ----------------------------------------------------------------- matching ----------

def _build_gram_scoring(pitch_list):
    """Postings + IDF weights + per-track norms for the bigram prefilter.

    Set semantics (a bigram counts once per track however often it repeats) with
    IDF^2-cosine scoring. Raw occurrence counts made the prefilter a track-length contest:
    with only 25^2 possible bigram keys, a multi-hour mix holds thousands of tokens spanning
    nearly every key, so compilations crowded the true match out of the candidate pool
    (measured recall 0.12 at 20k tracks). Cosine normalization is what cancels that -- a
    track containing *every* key has a large norm, so containing the query keys by sheer
    bulk no longer scores. Returns (postings, idf, norm)."""
    n = len(pitch_list)
    track_keys = []
    df = {}
    for p in pitch_list:
        ks = set(interval_bigrams(notes_to_intervals(p)))
        track_keys.append(ks)
        for key in ks:
            df[key] = df.get(key, 0) + 1
    idf = {key: float(np.log1p(n / d)) for key, d in df.items()}
    postings = {key: [] for key in df}
    norm = np.zeros(n, dtype=np.float64)
    for i, ks in enumerate(track_keys):
        s = 0.0
        for key in ks:
            postings[key].append(i)
            s += idf[key] ** 2
        norm[i] = np.sqrt(s) if s > 0 else 1.0
    postings = {key: np.asarray(v, dtype=np.int32) for key, v in postings.items()}
    return postings, idf, norm.astype(np.float32)


def _expand_query_grams(q_intervals):
    """Weighted bigram keys for a query: exact bigrams at weight 1, one-semitone neighbours
    at GRAM_JITTER_W (sloppy pitch moves a bigram to an adjacent key, losing it entirely
    under exact lookup), and sum-collapsed variants at GRAM_MERGE_W (pyin splitting one held
    note in two turns the track's interval a+b into the query's a,b). Max weight wins when
    variants collide. Returns {key: weight}."""
    iv = np.clip(np.asarray(q_intervals, dtype=np.int32), -12, 12)
    w = {}

    def add(a, b, wt):
        if a < -12 or a > 12 or b < -12 or b > 12:
            return
        key = int((a + 12) * 25 + (b + 12))
        if wt > w.get(key, 0.0):
            w[key] = wt

    n = iv.size
    for k in range(n - 1):
        a, b = int(iv[k]), int(iv[k + 1])
        add(a, b, 1.0)
        for da, db in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            add(a + da, b + db, GRAM_JITTER_W)
    for k in range(n - 2):
        a, b, c = int(iv[k]), int(iv[k + 1]), int(iv[k + 2])
        add(a + b, c, GRAM_MERGE_W)
        add(a, b + c, GRAM_MERGE_W)
    return w


def _prefilter_scores(index: MelodyIndex, q_intervals):
    """IDF^2-cosine prefilter scores for every track (0 = shares nothing)."""
    if index.gram_postings is None:
        index.gram_postings, index.gram_idf, index.gram_norm = _build_gram_scoring(index.pitch)
    qw = _expand_query_grams(q_intervals)
    scores = np.zeros(len(index), dtype=np.float32)
    for key, wt in qw.items():
        arr = index.gram_postings.get(key)
        if arr is not None:
            scores[arr] += wt * index.gram_idf[key] ** 2
    scores /= index.gram_norm
    return scores


def prefilter(index: MelodyIndex, q_intervals, k=PREFILTER_K):
    """Candidate track indices for the fine DTW stage.

    At/below BRUTE_MAX tracks the DTW over everything is <2s, so we skip filtering entirely
    (lossless). Above that, rank tracks by IDF^2-cosine over shared unique interval bigrams
    (with fuzzy query expansion, see _expand_query_grams) and keep the top k; bigrams are
    error-tolerant enough to keep the true track in the candidate pool under sloppy humming,
    which trigrams often drop."""
    if len(index) <= BRUTE_MAX:
        return range(len(index))
    if np.asarray(q_intervals).size == 0:
        return range(len(index))
    scores = _prefilter_scores(index, q_intervals)
    nz = np.nonzero(scores)[0]
    if nz.size <= k:
        return nz.tolist()
    return nz[np.argpartition(scores[nz], -k)[-k:]].tolist()


def match_query(index: MelodyIndex, q_pitch, candidates=None, clip=DTW_CLIP, r=OFFSET_R,
                top_n=10):
    """Score candidates by transposition-invariant subsequence DTW on absolute pitch.
    q_pitch is the repeat-collapsed query melody (semitones). Returns a best-first list of
    (track_index, score, start_s); score = 1/(1+avg_cost) in (0,1].

    DTW ties are broken by the prefilter's bigram cosine: a short query is often a perfect
    subsequence of many tracks (every such track scores exactly 1.0), and whole-track gram
    evidence is what separates the real source from a chance submatch."""
    q = np.asarray(q_pitch, dtype=np.float64)
    pscores = None
    if candidates is None:
        q_iv = notes_to_intervals(q)
        candidates = prefilter(index, q_iv)
        if len(index) > BRUTE_MAX and np.asarray(q_iv).size:
            pscores = _prefilter_scores(index, q_iv)
    results = []
    for i in candidates:
        t = index.pitch[i]
        if t.size == 0:
            continue
        cost, start = _dtw_transpose(q, t, clip, r)
        onsets = index.pitch_onset[i]
        start_s = float(onsets[start]) if start < onsets.size else 0.0
        cos = float(pscores[i]) if pscores is not None else 0.0
        results.append((i, 1.0 / (1.0 + cost), start_s, cos))
    results.sort(key=lambda r: (r[1], r[3]), reverse=True)
    return [(i, s, st) for i, s, st, _ in results[:top_n]]


# ----------------------------------------------------------------- query pipeline ----

def _voiced_seconds(midi):
    return float(np.sum(~np.isnan(midi))) * FRAME_PERIOD


def search_hum(index: MelodyIndex, audio_path, top_n=10) -> dict:
    """Full hum-query pipeline: decode -> pyin -> notes -> match. See module docstring
    for the returned dict shape. Raises ValueError on too-short / pitchless input."""
    audio = decode_audio(audio_path)
    if audio is None or audio.size < SR // 2:
        raise ValueError("audio too short or could not be decoded")
    contour = pyin_contour(audio)
    if _voiced_seconds(contour) < MIN_QUERY_VOICED_S:
        raise ValueError(
            f"need at least {MIN_QUERY_VOICED_S:.0f}s of clear pitch; hum a longer, "
            "steadier phrase")
    notes = contour_to_notes(contour)
    if notes.shape[0] < MIN_QUERY_NOTES:
        raise ValueError("could not find a clear melody (too few distinct notes)")
    q_pitch, _ = melody_seq(notes[:, 2], notes[:, 0])
    if q_pitch.size < 2:
        raise ValueError("could not find a clear melody (no pitch movement)")

    matched = match_query(index, q_pitch, top_n=top_n)
    results = [{"video_id": index.ids[i], "score": round(float(s), 4),
                "start_s": round(float(st), 2)} for i, s, st in matched]

    times = (np.arange(contour.shape[0]) * FRAME_PERIOD).round(3)
    midi_json = [None if np.isnan(v) else round(float(v), 2) for v in contour]
    return {
        "results": results,
        "query": {
            "duration_s": round(len(audio) / SR, 2),
            "n_notes": int(notes.shape[0]),
            "contour": {"times": times.tolist(), "midi": midi_json},
        },
    }


# ----------------------------------------------------------------- CLI ---------------

def _cli(argv):
    import argparse
    # library titles are full of CJK / emoji; force UTF-8 so the Windows cp1252 console
    # doesn't crash on them.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Hum-to-search the melody index.")
    ap.add_argument("audio", help="any audio file ffmpeg can read (hum/whistle/wav/webm)")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args(argv)

    import time
    t0 = time.time()
    index = load_index(args.db, args.index)
    t1 = time.time()
    out = search_hum(index, args.audio, top_n=args.top)
    t2 = time.time()

    q = out["query"]
    print(f"query: {q['duration_s']}s, {q['n_notes']} notes | "
          f"load {t1 - t0:.2f}s  match {t2 - t1:.2f}s  ({len(index)} tracks)")
    print(f"{'rank':<5}{'score':<8}{'start':<8}{'title':<45}{'artist'}")
    for r, res in enumerate(out["results"], 1):
        vid = res["video_id"]
        title = (index.titles.get(vid, "") or "")[:43]
        artist = (index.artists.get(vid, "") or "")[:30]
        print(f"{r:<5}{res['score']:<8.3f}{res['start_s']:<8.1f}{title:<45}{artist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
