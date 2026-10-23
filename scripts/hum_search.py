"""Hum search v2: match a hummed/sung query against Deep Salience melody peaks.

Why v2 exists: v1 (melody_match.py) reduces every track to ONE monophonic CREPE note line
and DTWs the hum's notes against it. On game/orchestral music that line usually follows the
bass, the pads or an ostinato, so a well-hummed lead melody had nothing to match (measured:
a clean 42 s hum of "Relic Forest" ranked the song #13,652 even with no prefilter).

v2 pieces:
  * index: data/salience_index/ (scripts/build_salience_index.py) - top-3 polyphonic
    melody-salience peaks per 0.1 s frame, so the lead is there even when it's quiet.
  * cost: for a hum frame at pitch p under transposition s, a track frame costs
    1 - (salience of the strongest peak within +/-TOL of p+s) / (that frame's top peak).
    Normalizing by the frame's own top peak makes a quiet lead count as much as a loud one.
  * alignment: LOCAL alignment (Smith-Waterman style) with slope-constrained steps
    (1,1),(1,2),(2,1) - the hummed tempo may be 0.5x-2x the track's - scoring
    sum(TAU - cost). People hum a mix of lead melody and accompaniment figures, so only the
    best-matching stretch of the hum should count, not the whole thing.
  * transposition: every half-semitone shift in SHIFT_RANGE is tried; a track's score is
    its best shift's score minus the mean of nearby shifts ("key contrast"). Dense tracks
    match every key a little; the true song matches one key much better than its neighbours.
  * the whole library is scanned on the GPU with a CUDA kernel (one block per
    track x shift, one thread per hum frame), so there's no lossy prefilter.
"""

from __future__ import annotations

import glob
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

INDEX_DIR = "data/salience_index"
DEFAULT_DB = "data/library.db"
R = 2                            # grid resolution: bins per semitone
TOL = 1                          # +/- grid bins (half-semitones) around the hummed pitch
TAU = 0.5                        # per-frame match threshold for local alignment
FLOOR = 0.15                     # frame-max floor so near-silent frames don't self-normalize
QTAB = 128                       # kernel lookup-table rows: max hum pitch span (half-semitones)
SEG_LEN = 4096                   # long tracks are scanned in overlapping segments of this many frames
CONTRAST_LO, CONTRAST_HI = 1, 6  # key contrast: neighbours 1..6 semitones from the best shift
METER_LO, METER_HI = 1.5, 2.5    # null ratio mapped to the UI's 0..100% match meter
NULL_CANDIDATES = 2000           # per stage-1 criterion, re-scored against the null queries
MAX_QUERY_FRAMES = 1024
QUERY_RATE = 10.0                # Hz; must match the index


_KERNEL_SRC = r"""
#define FULL 0xffffffffu
#define K 32
#define QR 128
#define WPB 4
extern "C" __global__
void hum_align(const unsigned char* __restrict__ qoff, int m,
               const unsigned char* __restrict__ hb, const unsigned char* __restrict__ nv,
               const long long* __restrict__ starts, const int* __restrict__ lens,
               const int* __restrict__ sbase, int n_items, float tau,
               float* __restrict__ out, int* __restrict__ counter,
               float* __restrict__ scratch, int tmax)
{
    // Persistent warps pull track segments off a global counter. Lane = one transposition
    // (sbase[g] - qmin + 2*lane, half-semitone bins), so all lanes read the same track frame.
    // Per frame each lane writes the <= 9 hum pitches its 3 peaks match (+/-1 bin) into a
    // private row of a shared-memory table; a cell's cost is then one table load. Each lane
    // keeps a strip of K hum rows in registers (rows of a column are independent given the
    // previous columns) and sweeps the segment once per strip; the strip's bottom two rows
    // pass to the next strip through an in-place scratch column laid out [frame][2][lane].
    // H before the segment start is -1: (2,1) moves from there can never win, which
    // replaces per-cell boundary predicates.
    __shared__ unsigned char tab[WPB][QR][32];
    const int lane = threadIdx.x & 31;
    const int wib = threadIdx.x >> 5;
    const int gw = blockIdx.x * WPB + wib;
    float* sc = scratch + (size_t)gw * tmax * 64;
    for (int q = 0; q < QR; ++q) tab[wib][q][lane] = 0;
    while (true) {
        int g = 0;
        if (lane == 0) g = atomicAdd(counter, 1);
        g = __shfl_sync(FULL, g, 0);
        if (g >= n_items) break;
        const int s = sbase[g] + 2 * lane;         // track bin = hum offset + s
        const long long a = starts[g];
        const int T = lens[g];
        float best = 0.0f;
        for (int i0 = 0; i0 < m; i0 += K) {
            int qo[K]; float h1[K], h2[K];
            #pragma unroll
            for (int r = 0; r < K; ++r) {
                qo[r] = (i0 + r < m) ? (int)qoff[i0 + r] : QR - 1;   // QR-1 never matches
                h1[r] = -1.0f; h2[r] = -1.0f;
            }
            const int qp = (i0 > 0) ? (int)qoff[i0 - 1] : QR - 1;
            float o1_1 = -1.0f, o1_2 = -1.0f, o2_1 = -1.0f;  // H[i0-1,j-1], H[i0-1,j-2], H[i0-2,j-1]
            int w0 = -1, w1 = -1, w2 = -1;                   // table rows written for this frame
            for (int j = 0; j < T; ++j) {
                const long long f = (a + j) * 3;
                if (w0 >= 0) { tab[wib][w0][lane] = 0; tab[wib][w0 + 1][lane] = 0; tab[wib][w0 + 2][lane] = 0; }
                if (w1 >= 0) { tab[wib][w1][lane] = 0; tab[wib][w1 + 1][lane] = 0; tab[wib][w1 + 2][lane] = 0; }
                if (w2 >= 0) { tab[wib][w2][lane] = 0; tab[wib][w2 + 1][lane] = 0; tab[wib][w2 + 2][lane] = 0; }
                const int e0 = (int)hb[f] - s - 1, e1 = (int)hb[f + 1] - s - 1, e2 = (int)hb[f + 2] - s - 1;
                const unsigned char n0 = nv[f], n1 = nv[f + 1], n2 = nv[f + 2];
                w0 = (n0 && e0 >= 0 && e0 <= QR - 4) ? e0 : -1;
                w1 = (n1 && e1 >= 0 && e1 <= QR - 4) ? e1 : -1;
                w2 = (n2 && e2 >= 0 && e2 <= QR - 4) ? e2 : -1;
                // peaks are sorted by salience (n0 >= n1 >= n2): write weakest first so the
                // strongest wins where windows overlap
                if (w2 >= 0) { tab[wib][w2][lane] = n2; tab[wib][w2 + 1][lane] = n2; tab[wib][w2 + 2][lane] = n2; }
                if (w1 >= 0) { tab[wib][w1][lane] = n1; tab[wib][w1 + 1][lane] = n1; tab[wib][w1 + 2][lane] = n1; }
                if (w0 >= 0) { tab[wib][w0][lane] = n0; tab[wib][w0 + 1][lane] = n0; tab[wib][w0 + 2][lane] = n0; }
                float o1_0 = -1.0f, o2_0 = -1.0f, D = 1.0f;
                if (i0 > 0) {
                    o1_0 = sc[(size_t)j * 64 + lane];
                    o2_0 = sc[(size_t)j * 64 + 32 + lane];
                    D = 1.0f - tab[wib][qp][lane] * (1.0f / 255.0f);
                }
                float A = o1_1, B = o1_2, Cc = o2_1;
                float hlast = 0.0f, hprev = 0.0f;
                #pragma unroll
                for (int r = 0; r < K; ++r) {
                    const float c = 1.0f - tab[wib][qo[r]][lane] * (1.0f / 255.0f);
                    const float p = fmaxf(fmaxf(0.0f, A), fmaxf(B, Cc + tau - D));
                    const float h = fmaxf(0.0f, tau - c + p);
                    best = fmaxf(best, h);
                    Cc = A; A = h1[r]; B = h2[r]; D = c;
                    h2[r] = h1[r]; h1[r] = h;
                    hprev = hlast; hlast = h;
                }
                o1_2 = o1_1; o1_1 = o1_0; o2_1 = o2_0;
                sc[(size_t)j * 64 + lane] = hlast;
                sc[(size_t)j * 64 + 32 + lane] = hprev;
            }
            if (w0 >= 0) { tab[wib][w0][lane] = 0; tab[wib][w0 + 1][lane] = 0; tab[wib][w0 + 2][lane] = 0; }
            if (w1 >= 0) { tab[wib][w1][lane] = 0; tab[wib][w1 + 1][lane] = 0; tab[wib][w1 + 2][lane] = 0; }
            if (w2 >= 0) { tab[wib][w2][lane] = 0; tab[wib][w2 + 1][lane] = 0; tab[wib][w2 + 2][lane] = 0; }
        }
        out[(size_t)g * 32 + lane] = best;
    }
}
"""


class SalienceIndex:
    def __init__(self, index_dir=INDEX_DIR, device=True):
        ids, ptrs, bins, vals = [], [], [], []
        off = 0
        for fp in sorted(glob.glob(os.path.join(index_dir, "shard_*.npz"))):
            with np.load(fp, allow_pickle=False) as z:
                ids.extend(z["ids"].tolist())
                ptrs.append(z["ptr"][:-1] + off)
                off += int(z["ptr"][-1])
                bins.append(z["bins"]); vals.append(z["vals"])
        self.ids = ids
        self.id2i = {v: i for i, v in enumerate(ids)}
        self.ptr = np.concatenate(ptrs + [np.array([off])]).astype(np.int64) if ptrs \
            else np.zeros(1, np.int64)
        # C order matters: the kernel indexes frame*3 + k (np.concatenate keeps F order)
        self.bins = np.ascontiguousarray(np.concatenate(bins)) if bins             else np.zeros((0, 3), np.int16)
        self.vals = np.ascontiguousarray(np.concatenate(vals)) if vals             else np.zeros((0, 3), np.uint8)
        self._gpu = None
        self.compute_centre()

    def compute_centre(self):
        """Each track's mean lead pitch (half-semitone bins, salience-weighted top peaks);
        the hum's transposition search is centred on it."""
        ids = self.ids
        if len(ids):
            hbin = (self.bins[:, 0].astype(np.int64) * 2 + 2) // 5
            w = self.vals[:, 0].astype(np.float64)
            st = self.ptr[:-1]
            nonempty = self.ptr[1:] > st
            sw = np.zeros(len(ids)); swb = np.zeros(len(ids))
            sw[nonempty] = np.add.reduceat(w, st[nonempty])
            swb[nonempty] = np.add.reduceat(w * hbin, st[nonempty])
            self.centre = np.where(sw > 0, swb / np.maximum(sw, 1e-9), 100.0)
        else:
            self.centre = np.zeros(0)

    def __len__(self):
        return len(self.ids)

    def gpu(self):
        """Device copies in kernel form: half-semitone peak bins (uint8) and peak salience
        divided by the frame's top peak (uint8, /255), so cost = 1 - nv/255."""
        if self._gpu is None:
            import cupy as cp
            n = self.bins.shape[0]
            hb = cp.empty((n, 3), cp.uint8)
            nv = cp.empty((n, 3), cp.uint8)
            step = 1 << 22      # chunked so the int32/float32 temporaries stay small
            for a in range(0, n, step):
                b = cp.asarray(np.ascontiguousarray(self.bins[a:a + step])).astype(cp.int32)
                v = cp.asarray(np.ascontiguousarray(self.vals[a:a + step])).astype(cp.float32)
                mx = cp.maximum(v[:, :1] / 255.0, FLOOR)
                hb[a:a + step] = ((b * 2 + 2) // 5).astype(cp.uint8)
                nv[a:a + step] = cp.clip(cp.rint(v / 255.0 / mx * 255.0), 0, 255).astype(cp.uint8)
            del b, v, mx
            self._gpu = (hb, nv, cp.RawKernel(_KERNEL_SRC, "hum_align"))
            cp.get_default_memory_pool().free_all_blocks()
        return self._gpu


def query_bins(contour20):
    """pyin contour at 20 Hz (NaN unvoiced) -> voiced frames at 10 Hz in half-semitone bins
    relative to MIDI 24. Unvoiced frames are dropped: pauses in a hum don't line up with
    anything in the track."""
    c = np.asarray(contour20, dtype=np.float64)[::2]
    c = c[~np.isnan(c)][:MAX_QUERY_FRAMES]
    return np.round((c - 24.0) * R).astype(np.int16)


def _segments(ptr, tidx, m, seg_len):
    """Split long tracks into overlapping segments so per-warp scratch stays bounded. A
    local alignment spans at most 2*m track frames (slope <= 2), so an overlap of 2m+8
    guarantees every alignment lies wholly inside some segment."""
    starts, lens, owner = [], [], []
    ov = 2 * m + 8
    step = max(seg_len - ov, 1)
    for k, t in enumerate(tidx):
        a, b = int(ptr[t]), int(ptr[t + 1])
        if b - a <= seg_len:
            starts.append(a); lens.append(b - a); owner.append(k)
            continue
        for s0 in range(a, b, step):
            e = min(s0 + seg_len, b)
            starts.append(s0); lens.append(e - s0); owner.append(k)
            if e == b:
                break
    return (np.array(starts, np.int64), np.array(lens, np.int32), np.array(owner, np.int64))


def scan(index: SalienceIndex, qbin, track_ids=None, n_warps=512, seg_len=SEG_LEN):
    """Score every track at 32 whole-semitone transpositions on the GPU.

    The 32 shifts are centred (+/-16 semitones) on the one that lines the hum's mean pitch
    up with the track's mean lead pitch, so each track costs one warp sweep.
    Returns (track_idx, shifts[n_tracks, 32] in semitones, scores[n_tracks, 32])."""
    import cupy as cp
    hb, nv, kern = index.gpu()
    tidx = np.arange(len(index)) if track_ids is None else np.asarray(track_ids)
    q = np.asarray(qbin, dtype=np.int32)
    m = int(q.size)
    qmin = int(q.min())
    qoff = np.clip(q - qmin + 2, 0, QTAB - 4).astype(np.uint8)   # +2: room for the +/-1 window
    centre = np.rint((index.centre[tidx] - q.mean()) / R).astype(np.int32)  # semitones
    base = centre - 16                                                      # lane 0's shift
    starts, lens, owner = _segments(index.ptr, tidx, m, seg_len)
    sbase = (base[owner] * R + qmin - 2).astype(np.int32)    # kernel: track bin = qoff + s
    tmax = int(max(1, lens.max()))
    out = cp.zeros(starts.size * 32, cp.float32)
    counter = cp.zeros(1, cp.int32)
    scratch = cp.empty(n_warps * tmax * 64, cp.float32)
    kern((n_warps // 4,), (128,),
         (cp.asarray(qoff), np.int32(m), hb, nv, cp.asarray(starts), cp.asarray(lens),
          cp.asarray(sbase), np.int32(starts.size), np.float32(TAU), out, counter, scratch,
          np.int32(tmax)))
    seg_scores = out.get().reshape(starts.size, 32)
    del scratch, out
    cp.get_default_memory_pool().free_all_blocks()   # a resident server shouldn't sit on VRAM
    scores = np.zeros((tidx.size, 32), np.float32)
    np.maximum.at(scores, owner, seg_scores)
    shifts = base[:, None] + np.arange(32)[None, :]
    return tidx, shifts, scores


def rank(shifts, scores):
    """Per track: (key contrast, best score, best shift, mean score of shifts 1..6 semitones
    from the best). Key contrast = best - that mean."""
    k = scores.argmax(1)
    best = scores[np.arange(scores.shape[0]), k]
    S = scores.shape[1]
    off = np.r_[-np.arange(CONTRAST_LO, CONTRAST_HI + 1)[::-1],
                np.arange(CONTRAST_LO, CONTRAST_HI + 1)]
    nb = k[:, None] + off[None, :]
    valid = (nb >= 0) & (nb < S)
    nbv = np.take_along_axis(scores, np.clip(nb, 0, S - 1), 1)
    mean_nb = (nbv * valid).sum(1) / np.maximum(valid.sum(1), 1)
    return best - mean_nb, best, shifts[np.arange(k.size), k], mean_nb


def null_queries(qbin):
    """Hum-shaped queries that should NOT match the song: the hum time-reversed, mirrored in
    pitch about its median, and both. Same length, range and note durations, but the melody
    is destroyed everywhere - so how well a track scores against them measures how easily
    it matches *anything* hum-like (dense, long, or in a common register).
    Chunk permutations (half-swaps etc.) are NOT valid nulls: they keep stretches of the
    real melody intact and local alignment finds them (measured: using them as nulls sank
    the true Relic Forest from #1 to #101)."""
    q = np.asarray(qbin, dtype=np.int32)
    med = int(np.round(np.median(q)))
    mir = np.clip(2 * med - q, 0, 250)
    return [q[::-1].astype(np.int16), mir.astype(np.int16), mir[::-1].astype(np.int16)]


def score_query(index: SalienceIndex, qbin, n_cand=NULL_CANDIDATES):
    """Two-stage scoring. Stage 1 scans the whole library with the hum. Stage 2 re-scores
    the plausible candidates (top n_cand by raw score, by key contrast and by key ratio)
    against the null queries, and ranks by the null ratio:

        best / (mean(score at shifts 1..6 semitones off, best null-query score) + 1)

    i.e. how much better the track fits this hum than it fits the same hum in a wrong key
    or with its melody destroyed. Measured at 26k tracks (Relic Forest / Agate Village
    hums): gap to the best impostor 0.33 / 0.55, vs 0.08 / 0.42 with two nulls averaged
    and a projected loss at 46k for key contrast alone.
    Returns (track_idx, ratio, best, shift) for the candidates."""
    tidx, shifts, scores = scan(index, qbin)
    contrast, best, shift, mean_nb = rank(shifts, scores)
    cand = set()
    for v in (best, contrast, best / (mean_nb + 1.0)):
        cand.update(np.argsort(-v)[:n_cand].tolist())
    cand = np.array(sorted(cand))
    nulls = []
    for nq in null_queries(qbin):
        _, nsh, nsc = scan(index, nq, track_ids=tidx[cand])
        nulls.append(rank(nsh, nsc)[1])
    null_max = np.max(nulls, axis=0)
    ratio = best[cand] / ((mean_nb[cand] + null_max) / 2.0 + 1.0)
    return tidx[cand], ratio, best[cand], shift[cand]


def match_strength(ratio):
    """Null ratio -> 0..1 for the UI's match meter."""
    return float(np.clip((ratio - METER_LO) / (METER_HI - METER_LO), 0.0, 1.0))


def search(index: SalienceIndex, audio_path, top_n=10) -> dict:
    """Full query pipeline, same result shape as melody_match.search_hum so /api/hum can
    use either: {"results": [{video_id, score 0..1, start_s}], "query": {...}}.
    Raises ValueError on too-short / pitchless input."""
    import melody_match as mm
    audio = mm.decode_audio(audio_path)
    if audio is None or audio.size < mm.SR // 2:
        raise ValueError("audio too short or could not be decoded")
    contour = mm.pyin_contour(audio)
    if mm._voiced_seconds(contour) < mm.MIN_QUERY_VOICED_S:
        raise ValueError(
            f"need at least {mm.MIN_QUERY_VOICED_S:.0f}s of clear pitch; hum a longer, "
            "steadier phrase")
    qb = query_bins(contour)
    tidx, ratio, best, shift = score_query(index, qb)
    order = np.argsort(-ratio)[:top_n]
    results = [{"video_id": index.ids[tidx[o]], "score": round(match_strength(ratio[o]), 4),
                "ratio": round(float(ratio[o]), 3), "raw": round(float(best[o]), 3),
                "shift": int(shift[o]), "start_s": None} for o in order]
    notes = mm.contour_to_notes(contour)
    times = (np.arange(contour.shape[0]) * mm.FRAME_PERIOD).round(3)
    midi_json = [None if np.isnan(v) else round(float(v), 2) for v in contour]
    return {
        "results": results,
        "query": {
            "duration_s": round(len(audio) / mm.SR, 2),
            "n_notes": int(notes.shape[0]),
            "contour": {"times": times.tolist(), "midi": midi_json},
            "engine": "salience-v2",
        },
    }


def _cli(argv):
    import sqlite3
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    t = time.time()
    idx = SalienceIndex()
    t_load = time.time() - t
    for path in argv:
        t = time.time()
        r = search(idx, path)
        dt = time.time() - t
        con = sqlite3.connect(DEFAULT_DB, timeout=30)
        print(f"\n{path}: {len(idx)} tracks | load {t_load:.1f}s search {dt:.1f}s")
        print("rank  ratio   raw  shift  title / artist")
        for n, x in enumerate(r["results"], 1):
            row = con.execute("SELECT title, artist FROM tracks WHERE video_id=?",
                              (x["video_id"],)).fetchone() or ("?", "?")
            print(f"{n:<4} {x['ratio']:6.3f} {x['raw']:5.1f} {x['shift']:+5d}  "
                  f"{(row[0] or '')[:50]:50s} {(row[1] or '')[:25]}")


if __name__ == "__main__":
    _cli(sys.argv[1:])
