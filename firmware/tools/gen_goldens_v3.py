r"""Golden fixtures for the engine v3 port (firmware/core/omp_engine3.c,
firmware/host/test_engine3.c).

The reference is the web player's own code: server.next_decision's steps (session
rejections, the skip anchor, the decayed session mood, blend_candidates with the LOW_MEM
caps, personalize.rank_next with AUTOPLAY_PARAMS, choose_next_explained with EXPLORE,
outcome_epsilon, cluster_stats), run over an engine-3 device pack and a synthetic history
-- everything server.next_decision reads from the database comes from the pack instead.

  .venv\Scripts\python scripts\export_device_pack.py --out data\device_pack_v3 --engine 3
  .venv\Scripts\python firmware\tools\gen_goldens_v3.py
Writes firmware/host/goldens_v3/{plays.bin,expect.bin}
"""
import json
import os
import random
import struct
import sys

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import personalize  # noqa: E402
import server  # noqa: E402  (pure helpers + AUTOPLAY_PARAMS / EXPLORE / BLEND_LOW_MEM)

PACK = os.environ.get("GOLDENS_PACK") or os.path.join(ROOT, "data", "device_pack_v3")
OUT = os.environ.get("GOLDENS_OUT") or os.path.join(ROOT, "firmware", "host", "goldens_v3")
NOW = 1_790_000_000.0
EV = {"play": 0, "complete": 1, "skip": 2, "like": 3, "dislike": 4, "peek": 5, "unlike": 6,
      "switch": 7}
OUTCOME = {None: 0, "skip": 1, "complete": 2, "switch": 3, "dislike": 4}
PAD = 0xFFFFFFFF
REC = np.dtype([("file", "<u4"), ("title", "<u4"), ("artist", "<u4"),
                ("album", "<u4"), ("genre", "<u4"), ("dur", "<u2"), ("gain", "<i2")])


def load():
    meta = json.load(open(os.path.join(PACK, "pack.json"), encoding="utf-8"))
    assert meta.get("engine") == 3, "build the pack with --engine 3"
    n, k = meta["tracks"], meta["k"]
    recs = np.fromfile(os.path.join(PACK, "tracks.bin"), dtype=REC)
    pool = open(os.path.join(PACK, "strings.bin"), "rb").read()
    blob = open(os.path.join(PACK, "ids.bin"), "rb").read()
    ids = [blob[i * 11:(i + 1) * 11].decode("ascii") for i in range(n)]
    X = np.fromfile(os.path.join(PACK, "embeddings.f16"), dtype=np.float16).reshape(n, 512).astype(np.float32)
    nbr = np.fromfile(os.path.join(PACK, "neighbors.bin"), dtype=np.uint32).reshape(n, k)
    sig = np.fromfile(os.path.join(PACK, "signals.bin"), dtype=[
        ("energy", "u1"), ("pad", "u1"), ("bpm", "<u2"), ("cluster", "<u2"), ("hist", "<u2")])
    th = np.fromfile(os.path.join(PACK, "taste_hist.bin"), dtype="<f4")
    co = open(os.path.join(PACK, "cooc.bin"), "rb").read()
    offs = np.frombuffer(co, dtype="<u4", count=n + 1, offset=8)
    mem = np.frombuffer(co, dtype="<u4", offset=8 + 4 * (n + 1))

    def s(off):
        return pool[off:pool.index(b"\x00", off)].decode("utf-8")
    return n, recs, s, ids, X, nbr, sig, th[:512], float(th[512]), offs, mem


def synth(recs, nbr, rng, n):
    """~40 days of history: a loved neighbourhood, a rejected one, likes undone, and a
    sitting in the last 3 hours with early skips and a dislike (the session rejections)."""
    def ok(i):
        return nbr[i][-1] != PAD and recs["dur"][i] > 0
    a = 2000
    while not ok(a): a += 1
    b = 30000
    while not ok(b): b += 1
    ca = [a] + [int(x) for x in nbr[a][:16]]
    cb = [b] + [int(x) for x in nbr[b][:10]]
    log = []

    def emit(ts, i, ev, frac=None, sec=None):
        dur = float(recs["dur"][i])
        if frac is not None:
            sec = round(frac * dur, 2)
        log.append((int(i), float(ts), ev, sec))
    t = NOW - 40 * 86400
    for k, x in enumerate(ca[:9]):
        t += 210 + int(rng.integers(0, 60)); emit(t, x, "play", sec=0.0)
        t += 160; emit(t, x, "complete", 0.95)
        if k in (1, 4):
            t += 5; emit(t, x, "like", sec=0.0)
    t += 30; emit(t, ca[4], "unlike", sec=0.0)             # a like taken back
    t = NOW - 12 * 86400
    for k, x in enumerate(cb):
        t += 130 + int(rng.integers(0, 40)); emit(t, x, "play", sec=0.0)
        t += 15
        if k < 3: emit(t, x, "skip", 0.03)                  # skip cliff, early session
        elif k < 6: emit(t, x, "skip", 0.10)
        elif k == 6: emit(t, x, "skip", 0.5)
        elif k == 7: emit(t, x, "skip", 0.9)
        else: emit(t, x, "dislike", sec=5.0)
    t = NOW - 2 * 86400
    for x in ca[5:12]:
        t += 200; emit(t, x, "play", sec=0.0)
        t += 150; emit(t, x, "complete", 0.9)
    t = NOW - 2 * 3600                                      # this sitting
    sitting = [ca[12], ca[13], cb[3], ca[14], cb[5], ca[15]]
    for k, x in enumerate(sitting):
        t += 190; emit(t, x, "play", sec=0.0)
        t += 8 if x in cb else 170
        if x == cb[3]: emit(t, x, "skip", sec=4.0)          # early skip -> rejected
        elif x == cb[5]: emit(t, x, "dislike", sec=6.0)     # dislike -> rejected (hard)
        else: emit(t, x, "complete", 0.93)
    emit(t + 20, ca[2], "peek", sec=0.0)
    emit(t + 40, ca[3], "switch", sec=2.0)
    return log, ca, cb, sitting


def main():
    rng = np.random.default_rng(7)
    os.makedirs(OUT, exist_ok=True)
    n, recs, s, ids, X, nbr, sig, th, th_tot, offs, mem = load()
    id2i = {v: i for i, v in enumerate(ids)}
    artist_by_index = [s(int(recs["artist"][i])) for i in range(n)]
    id2artist = {ids[i]: artist_by_index[i] for i in range(n)}
    durations = {ids[i]: (float(recs["dur"][i]) if recs["dur"][i] else None) for i in range(n)}
    energies = {ids[i]: sig["energy"][i] / 254.0 for i in range(n) if sig["energy"][i] != 255}
    bpms = {ids[i]: sig["bpm"][i] / 10.0 for i in range(n) if sig["bpm"][i] > 0}
    clusters = {ids[i]: int(sig["cluster"][i]) for i in range(n) if sig["cluster"][i] != 0xFFFF}
    cooc = {ids[i]: {ids[int(m)] for m in mem[offs[i]:offs[i + 1]]}
            for i in range(n) if offs[i + 1] > offs[i]}
    lib = set(ids)
    E = {"X": X, "id2i": id2i}
    # game franchises (signals.bin's spare byte + franchise.bin), when the pack has them
    fr_of = {ids[i]: int(sig["pad"][i]) for i in range(n) if sig["pad"][i]}
    fr_bias = {}
    fb = os.path.join(PACK, "franchise.bin")
    if os.path.exists(fb):
        raw = open(fb, "rb").read()
        m = struct.unpack("<I", raw[4:8])[0]
        fr_bias = {k: float(b) for k, b in enumerate(np.frombuffer(raw, dtype="<f4", count=m, offset=8))}

    log, ca, cb, sitting = synth(recs, nbr, rng, n)
    with open(os.path.join(OUT, "plays.bin"), "wb") as f:
        f.write(b"OMP1")
        for i, ts, ev, sec in log:
            f.write(struct.pack("<dIfB3x", ts, i, -1.0 if sec is None else float(sec), EV[ev]))
    rows = [(ids[i], ts, ev, sec, None) for i, ts, ev, sec in log]

    # what server.personalization() builds, over the device's view of the history
    prefs = personalize.compute_prefs(rows, durations, id2artist, now=NOW,
                                      neg_halflife_days=14.0, strong_early_skip=True,
                                      explicit_state=True)
    merged = {ids[i]: int(sig["hist"][i]) for i in range(n) if sig["hist"][i]}
    for v, c in prefs["play_counts"].items():
        merged[v] = merged.get(v, 0) + c
    prefs["play_counts"] = merged
    acc = th.astype(np.float32).copy()
    for v, w in prefs["track"].items():                     # build_centroid(hist + app), summed
        acc += np.float32(w) * X[id2i[v]]
    nrm = float(np.linalg.norm(acc))
    taste = (acc / nrm).astype(np.float32) if nrm > 1e-9 else None
    skip = personalize.build_centroid(X, id2i, {v: 1.0 for v in prefs["skip_ids"]})
    heard = {}
    for v, ts, ev, sec, _src in rows:
        if ev in ("play", "complete"):
            heard[v] = max(heard.get(v, 0.0), ts)
    eps = server.outcome_epsilon(rows, durations)
    stats = server.cluster_stats(rows, durations, clusters)

    def rejects(tail):
        tail = [v for v in dict.fromkeys(tail) if v]
        state = {}
        for v, ts, ev, sec, _src in rows:
            if ts <= NOW - server.REJECT_LOOKBACK or v not in tail or ev not in (
                    "skip", "complete", "like", "dislike", "trash"):
                continue
            if ev in ("dislike", "trash"):
                state[v] = "hard"
            elif ev in ("complete", "like"):
                state[v] = None
            elif state.get(v) != "hard":
                state[v] = "skip" if server._is_early(v, sec, durations) else None
        return {v for v, st in state.items() if st}

    def decide(ex_list, cur, outcome, secs, seed, eps_case):
        exclude = set(ex_list) | {cur}
        tail = [v for v in ex_list if v != cur][-11:] + [cur]
        cur_artist = id2artist.get(cur, "")
        rejected = rejects(tail[:-1])
        if outcome in ("skip", "dislike", "trash"):
            if outcome != "skip" or server._is_early(cur, secs, durations):
                rejected.add(cur)
        elif outcome is None and cur in rejects([cur]):
            rejected.add(cur)
        anchor = cur
        if cur in rejected:
            for v in reversed(tail[:-1]):
                if v not in rejected and v in id2i:
                    anchor = v
                    break
        mood_ids = [v for v in tail if v not in rejected] or [anchor]
        recent_ids = tail[-6:]
        base = [ids[int(j)] for j in nbr[id2i[anchor]] if j != PAD]
        cand = server.blend_candidates(anchor, base, lib, exclude,
                                       radio_ids=cooc.get(anchor) or (),
                                       play_counts=prefs["play_counts"], caps=server.BLEND_LOW_MEM)
        rvecs = [X[id2i[v]] for v in recent_ids if v in id2i]
        session_vec = server.session_centroid(E, mood_ids)
        sskip = personalize.build_centroid(X, id2i, {v: 1.0 for v in rejected})
        ra = {id2artist.get(v, "") for v in recent_ids[-4:]}
        ra.discard("")
        if cur_artist:
            ra.add(cur_artist)
        ranked = personalize.rank_next(
            anchor, cand, X, id2i, ids, artist_by_index, prefs=prefs, taste_vec=taste,
            skip_vec=skip, recent_artists=ra, recent_vecs=np.stack(rvecs) if rvecs else None,
            session_vec=session_vec, cooc_members=cooc, last_played=heard, now=NOW,
            energies=energies, bpms=bpms, params=server.AUTOPLAY_PARAMS, explain=True,
            session_skip_vec=sskip, franchise_of=fr_of, franchise_bias=fr_bias,
            recent_franchises=[fr_of[v] for v in tail[-server.FRANCHISE_RECENT:] if v in fr_of])
        pick, info = personalize.choose_next_explained(
            ranked, prefs["play_counts"], epsilon=eps if eps_case < 0 else eps_case,
            rng=random.Random(seed),
            clusters=clusters, cluster_stats=stats, **server.EXPLORE)
        return anchor, cand, ranked, pick, info, rejected

    V = lambda i: ids[i]  # noqa: E731
    sit = [V(i) for i in sitting]
    cases = [
        # (ex_list, cur, outcome, secs, rng seed) -- seeds chosen so some cases explore
        (sit[:-1], sit[-1], "complete", 160.0, 1),
        (sit[:-1], sit[-1], "skip", 3.0, 2),                 # skipped now -> anchor moves back
        (sit[:4], sit[4], None, None, 3),                     # cur was disliked in the log
        ([V(i) for i in ca[:6]], V(ca[6]), "complete", 150.0, 4),
        ([V(i) for i in cb[:5]], V(cb[5]), "dislike", 4.0, 5),
        ([], V(ca[0]), None, None, 6),
    ]
    cases = [c + (-1.0,) for c in cases]
    for seed in range(100, 140):                             # the history's own epsilon
        cases.append((sit[:-1], sit[-1], "switch", 30.0, seed, -1.0))
    for seed in range(200, 240):                             # always explore: Thompson arms,
        ex = [V(i) for i in (ca[:8] if seed % 2 else cb[:6])] # sound budget, unheard chain
        cases.append((ex, V(ca[8] if seed % 2 else cb[6]), "complete", 120.0, seed, 1.0))
    with open(os.path.join(OUT, "expect.bin"), "wb") as f:
        f.write(struct.pack("<dd", NOW, eps))
        tv = taste if taste is not None else np.zeros(512, np.float32)
        sv = skip if skip is not None else np.zeros(512, np.float32)
        f.write(struct.pack("<BB", taste is not None, skip is not None))
        tv.astype("<f4").tofile(f)
        sv.astype("<f4").tofile(f)
        f.write(struct.pack("<I", len(cases)))
        explored = 0
        reasons = {}
        for ex, cur, oc, secs, seed, eps_case in cases:
            anchor, cand, ranked, pick, info, rej = decide(ex, cur, oc, secs, seed, eps_case)
            reasons[info["reason"]] = reasons.get(info["reason"], 0) + 1
            explored += info["explored"]
            f.write(struct.pack("<IIBffIIIII", len(ex), id2i[cur], OUTCOME[oc],
                                -1.0 if secs is None else secs, eps_case, seed, id2i[anchor],
                                id2i[pick] if pick else PAD, len(cand), len(ranked)))
            for v in ex:
                f.write(struct.pack("<I", id2i[v]))
            for v in cand:
                f.write(struct.pack("<I", id2i[v]))
            for vid, score, _t in ranked:
                f.write(struct.pack("<Id", id2i[vid], score))
    print(f"goldens v3 -> {OUT}: {len(log)} events, {len(cases)} cases ({explored} explored), "
          f"eps {eps:.3f}, clusters with history {len(stats)}, reasons {reasons}")


if __name__ == "__main__":
    main()
