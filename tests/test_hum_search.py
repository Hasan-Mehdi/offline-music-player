"""Hum search v2 (scripts/hum_search.py): the GPU kernel must agree with a plain reference
implementation of the local alignment it claims to compute."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import hum_search as hs  # noqa: E402

try:
    import cupy
    cupy.cuda.runtime.getDeviceCount()
    HAVE_GPU = True
except Exception:
    HAVE_GPU = False

gpu = pytest.mark.skipif(not HAVE_GPU, reason="needs CuPy + a CUDA GPU")


def ref_scores(qbin, bins, vals, shifts_semi, tau=hs.TAU, tol=hs.TOL, floor=hs.FLOOR):
    """Reference: for each shift, local alignment with steps (1,1),(1,2),(2,1) over cost
    1 - (best peak within tol of the shifted hum pitch) / (frame's top peak)."""
    hb = (bins.astype(np.int64) * 2 + 2) // 5
    mx = np.maximum(vals[:, 0] / 255.0, floor)
    nv = np.clip(np.rint(vals / 255.0 / mx[:, None] * 255.0), 0, 255) / 255.0
    m, n = qbin.size, bins.shape[0]
    out = []
    for s in shifts_semi:
        C = np.ones((m, n))
        for i in range(m):
            t = int(qbin[i]) + 2 * int(s)
            hit = (np.abs(hb - t) <= tol) & (vals > 0)
            C[i] = 1.0 - np.where(hit, nv, 0.0).max(1)
        H = np.zeros((m, n))
        for i in range(m):
            for j in range(n):
                p = 0.0
                if i >= 1 and j >= 1:
                    p = max(p, H[i - 1, j - 1])
                    if j >= 2:
                        p = max(p, H[i - 1, j - 2])
                    if i >= 2:
                        p = max(p, H[i - 2, j - 1] + tau - C[i - 1, j])
                H[i, j] = max(0.0, tau - C[i, j] + p)
        out.append(H.max())
    return np.array(out)


def make_index(tracks):
    idx = hs.SalienceIndex.__new__(hs.SalienceIndex)
    idx.ids = [f"t{k}" for k in range(len(tracks))]
    idx.id2i = {v: i for i, v in enumerate(idx.ids)}
    idx.ptr = np.r_[0, np.cumsum([b.shape[0] for b, _ in tracks])].astype(np.int64)
    idx.bins = np.ascontiguousarray(np.concatenate([b for b, _ in tracks]))
    idx.vals = np.ascontiguousarray(np.concatenate([v for _, v in tracks]))
    idx._gpu = None
    idx.compute_centre()
    return idx


def random_track(rng, T):
    bins = (np.cumsum(rng.integers(-3, 4, (T, 3)), 0) % 100 + 100).astype(np.int16)
    vals = np.sort(rng.integers(0, 255, (T, 3)), 1)[:, ::-1].astype(np.uint8).copy()
    return bins, vals


@gpu
@pytest.mark.parametrize("T,m,seg", [(60, 5, 4096), (80, 40, 4096), (400, 37, 120), (7, 3, 4096)])
def test_kernel_matches_reference(T, m, seg):
    rng = np.random.default_rng(T * 31 + m)
    tracks = [random_track(rng, T), random_track(rng, T + 13)]
    idx = make_index(tracks)
    qbin = (np.cumsum(rng.integers(-1, 2, m)) % 20 + 50).astype(np.int16)
    tidx, shifts, scores = hs.scan(idx, qbin, seg_len=seg)
    for k, (b, v) in enumerate(tracks):
        ref = ref_scores(qbin, b, v, shifts[k])
        # nv is quantized to uint8 on the GPU side: allow ~1/255 per aligned frame
        assert np.allclose(scores[k], ref, atol=0.02 + 0.004 * m), (k, scores[k], ref)


@gpu
def test_planted_melody_found_at_its_transposition():
    """A track whose lead line is the hum transposed up 19 semitones (plus distractor
    peaks) must outrank random tracks, with the transposition recovered."""
    rng = np.random.default_rng(7)
    m = 60
    hum = (np.cumsum(rng.integers(-2, 3, m)) % 14 + 40).astype(np.int16)    # half-semis
    tracks = [random_track(rng, 500) for _ in range(30)]
    b, v = random_track(rng, 500)
    lead = (hum.astype(np.int64) + 2 * 19) * 5 // 2                          # -> 0.2-semi bins
    b[200:200 + m, 0] = lead
    v[200:200 + m, 0] = 250
    tracks.append((b, v))
    idx = make_index(tracks)
    tidx, shifts, scores = hs.scan(idx, hum)
    contrast, best, shift, _ = hs.rank(shifts, scores)
    top = int(np.argmax(contrast))
    assert top == len(tracks) - 1
    assert shift[top] == 19
    # the full two-stage null-ratio scoring agrees
    cidx, ratio, best, shift = hs.score_query(idx, hum, n_cand=5)
    assert cidx[np.argmax(ratio)] == len(tracks) - 1
    assert shift[np.argmax(ratio)] == 19


def test_segments_cover_every_alignment():
    ptr = np.array([0, 50, 10050], np.int64)
    starts, lens, owner = hs._segments(ptr, np.array([0, 1]), m=100, seg_len=1000)
    assert owner[0] == 0 and starts[0] == 0 and lens[0] == 50
    long = [(s, s + l) for s, l, o in zip(starts, lens, owner) if o == 1]
    assert long[0][0] == 50 and long[-1][1] == 10050
    # consecutive segments overlap by >= 2m: any alignment (<= 2m frames) fits in one
    for (a0, b0), (a1, b1) in zip(long, long[1:]):
        assert b0 - a1 >= 2 * 100


def test_rank_key_contrast_prefers_a_single_sharp_key():
    shifts = np.tile(np.arange(32), (2, 1))
    flat = np.full(32, 10.0); flat[5] = 12.0          # dense track: matches every key
    sharp = np.full(32, 2.0); sharp[20] = 11.0         # true song: one key, much better
    contrast, best, shift, _ = hs.rank(shifts, np.stack([flat, sharp]))
    assert contrast[1] > contrast[0]
    assert shift[1] == 20


def test_query_bins_drops_unvoiced_and_decimates():
    c = np.array([60.0, np.nan, 61.0, 61.0, np.nan, np.nan, 62.0, 62.0], np.float32)
    q = hs.query_bins(c)      # 20 Hz -> every 2nd frame: 60, 61, nan, 62 -> voiced only
    assert q.tolist() == [72, 74, 76]


def test_null_queries_keep_shape_but_not_melody():
    q = np.array([50, 52, 54, 52, 57, 59], np.int16)
    rev, mir, revmir = hs.null_queries(q)
    assert rev.tolist() == q[::-1].tolist()
    assert revmir.tolist() == mir[::-1].tolist()
    assert sorted(np.abs(np.diff(mir)).tolist()) == sorted(np.abs(np.diff(q)).tolist())
    assert not np.array_equal(np.diff(mir), np.diff(q))
