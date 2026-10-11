r"""Generate golden parity fixtures for the C brain (firmware/host/test_brain.c).

Runs the REAL scripts/personalize.py over the REAL device pack with a synthetic
play history, and dumps binary fixtures (prefs, centroids, ranked orderings,
speed-dial tiles) that the C port must reproduce within float tolerances.
Also replicates the server.py /api/next session-context assembly (mood tail 12,
fatigue tail 6, cooldown tail 4 + current artist) so a fixture case checks the
WHOLE next-track step, not just the scoring loop.

Usage:  .venv\Scripts\python firmware\tools\gen_goldens.py
Writes: firmware/host/goldens/{plays.bin,prefs.bin,centroids.bin,ranks.bin,speeddial.bin}
"""
import os
import struct
import sys
from collections import Counter

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import personalize  # noqa: E402

PACK = os.path.join(ROOT, "data", "device_pack")
OUT = os.path.join(ROOT, "firmware", "host", "goldens")
NOW = 1_783_000_000.0  # fixed "now" so fixtures are deterministic
EV = {"play": 0, "complete": 1, "skip": 2, "like": 3, "dislike": 4, "peek": 5}

REC = np.dtype([("file", "<u4"), ("title", "<u4"), ("artist", "<u4"),
                ("album", "<u4"), ("genre", "<u4"), ("dur", "<u2"), ("gain", "<i2")])


def load_pack():
    recs = np.fromfile(os.path.join(PACK, "tracks.bin"), dtype=REC)
    n = len(recs)
    pool = open(os.path.join(PACK, "strings.bin"), "rb").read()
    ids_blob = open(os.path.join(PACK, "ids.bin"), "rb").read()
    ids = [ids_blob[i * 11:(i + 1) * 11].decode("ascii") for i in range(n)]
    X = np.fromfile(os.path.join(PACK, "embeddings.f16"), dtype=np.float16).reshape(n, 512)
    X32 = X.astype(np.float32)
    with open(os.path.join(PACK, "pack.json"), encoding="utf-8") as f:
        import json
        k = json.load(f)["k"]
    nbr = np.fromfile(os.path.join(PACK, "neighbors.bin"), dtype=np.uint32).reshape(n, k)

    def s(off):
        return pool[off:pool.index(b"\x00", off)].decode("utf-8")

    return recs, ids, X32, nbr, s


def synth_log(recs, nbr, rng):
    """Three sessions over ~45 days exercising every event type + gating path."""
    a = 1000
    while nbr[a][-1] == 0xFFFFFFFF or recs["dur"][a] == 0:
        a += 1
    b = 30000
    while nbr[b][-1] == 0xFFFFFFFF or recs["dur"][b] == 0:
        b += 1
    ca = [a] + [int(x) for x in nbr[a][:14]]          # cluster A: loved
    cb = [b] + [int(x) for x in nbr[b][:9]]           # cluster B: rejected
    log = []  # (idx, ts, event, seconds) chronological, all ts distinct

    def emit(ts, idx, event, frac=None):
        dur = float(recs["dur"][idx])
        sec = None if frac is None else round(frac * dur, 2)
        log.append((int(idx), float(ts), event, sec))

    t = NOW - 45 * 86400
    for i, x in enumerate(ca[:8]):                     # session 1: build taste
        t += 200 + int(rng.integers(0, 60))
        emit(t, x, "play", None)
        t += 150
        emit(t, x, "complete", 0.92)
        if i in (2, 5):
            t += 5
            emit(t, x, "like")
    t = NOW - 10 * 86400
    for i, x in enumerate(cb):                         # session 2: reject cluster B
        t += 120 + int(rng.integers(0, 45))
        emit(t, x, "play", None)
        t += 20
        if i < 3:
            emit(t, x, "skip", 0.05)                  # early-session strong skips (halved)
        elif i < 6:
            emit(t, x, "skip", 0.06)                  # post-window strong skips (full)
        elif i == 6:
            emit(t, x, "skip", 0.40)                  # mid skip -> neutral
        elif i == 7:
            emit(t, x, "skip", 0.85)                  # late skip -> mild positive
        else:
            emit(t, x, "dislike")
    t = NOW - 2 * 86400
    for rep in range(2):                               # session 3: this week (speed-dial)
        for x in ca[3:10]:
            t += 180 + int(rng.integers(0, 90))
            emit(t, x, "play", None)
            t += 140
            emit(t, x, "complete", 0.88)
        t += 400
    emit(t + 60, ca[1], "peek", 0.0)                   # peek: 0 pref weight, 0.5 dial val
    emit(t + 130, ca[2], "like")
    return log, ca, cb


def w_playlog(path, log):
    with open(path, "wb") as f:
        f.write(b"OMP1")
        for idx, ts, event, sec in log:
            f.write(struct.pack("<dIfB3x", ts, idx,
                                -1.0 if sec is None else float(sec), EV[event]))


def server_assembly(played, cur, ids, X32, id2i, artist_by_index, prefs, taste, skip):
    """Mirror server.py /api/next context building + candidate retrieval."""
    ex = [ids[i] for i in played]
    cur_vid = ids[cur]
    mood_ids = [v for v in ex if v != cur_vid][-11:] + [cur_vid]
    recent_ids = mood_ids[-6:]
    rvecs = [np.asarray(X32[id2i[v]], dtype="float32") for v in recent_ids]
    session_vec = personalize.build_centroid(X32, id2i, {v: 1.0 for v in mood_ids})
    recent_artists = {artist_by_index[id2i[v]] for v in recent_ids[-4:]}
    recent_artists.discard("")
    if artist_by_index[cur]:
        recent_artists.add(artist_by_index[cur])
    return mood_ids, session_vec, np.stack(rvecs), recent_artists


def main():
    rng = np.random.default_rng(42)
    os.makedirs(OUT, exist_ok=True)
    recs, ids, X32, nbr, s = load_pack()
    n = len(recs)
    id2i = {v: i for i, v in enumerate(ids)}
    artist_by_index = [s(recs["artist"][i]) for i in range(n)]
    artist_off_of = {}
    for i in range(n):
        artist_off_of[artist_by_index[i]] = int(recs["artist"][i])
    durations = {ids[i]: (float(recs["dur"][i]) if recs["dur"][i] else None)
                 for i in range(n)}
    id2artist = {ids[i]: artist_by_index[i] for i in range(n)}

    log, ca, cb = synth_log(recs, nbr, rng)
    w_playlog(os.path.join(OUT, "plays.bin"), log)

    plays_py = [(ids[i], ts, ev, sec) for i, ts, ev, sec in log]
    prefs = personalize.compute_prefs(plays_py, durations, id2artist, now=NOW)
    taste = personalize.build_centroid(X32, id2i, prefs["track"])
    skipv = personalize.build_centroid(X32, id2i, {v: 1.0 for v in prefs["skip_ids"]})

    with open(os.path.join(OUT, "prefs.bin"), "wb") as f:
        f.write(struct.pack("<d", NOW))
        items = [(id2i[v], w) for v, w in prefs["track"].items()]
        f.write(struct.pack("<I", len(items)))
        for i, w in items:
            f.write(struct.pack("<If", i, w))
        arts = [(artist_off_of[a], w) for a, w in prefs["artist"].items() if a]
        f.write(struct.pack("<I", len(arts)))
        for off, w in arts:
            f.write(struct.pack("<If", off, w))
        cnts = [(id2i[v], c) for v, c in prefs["play_counts"].items()]
        f.write(struct.pack("<I", len(cnts)))
        for i, c in cnts:
            f.write(struct.pack("<IH", i, c))

    with open(os.path.join(OUT, "centroids.bin"), "wb") as f:
        for vec in (taste, skipv):
            f.write(struct.pack("<B", 0 if vec is None else 1))
            (vec if vec is not None else np.zeros(512, np.float32)).astype("<f4").tofile(f)

    # rank cases: (played, cur, personalized?) — case 0 = fresh boot, no history
    cases = [([], ca[0], False),
             (cb[:4] + ca[:4], ca[0], True),
             ([int(x) for x in nbr[cb[0]][:20]] + cb + ca[:5], cb[0], True)]
    with open(os.path.join(OUT, "ranks.bin"), "wb") as f:
        f.write(struct.pack("<dI", NOW, len(cases)))
        for played, cur, pers in cases:
            p = prefs if pers else personalize.compute_prefs([], durations, id2artist, now=NOW)
            tv = taste if pers else None
            sv = skipv if pers else None
            mood_ids, session_vec, rvecs, recent_artists = server_assembly(
                played, cur, ids, X32, id2i, artist_by_index, p, tv, sv)
            exclude = {ids[i] for i in played} | {ids[cur]}
            cand = [ids[int(x)] for x in nbr[cur]
                    if x != 0xFFFFFFFF and ids[int(x)] not in exclude]
            ranked = personalize.rank_next(
                ids[cur], cand, X32, id2i, ids, artist_by_index,
                prefs=p, taste_vec=tv, skip_vec=sv, recent_artists=recent_artists,
                recent_vecs=rvecs, session_vec=session_vec)
            f.write(struct.pack("<BIII", 1 if pers else 0, cur, len(played), len(ranked)))
            for i in played:
                f.write(struct.pack("<I", i))
            for vid, score in ranked:
                f.write(struct.pack("<Id", id2i[vid], score))

    # speed-dial goldens (C semantics: artist key = interned offset; the synthetic
    # log has no case-colliding artists so this equals the server's str.lower())
    def dial(fresh, nout=12):
        scores, latest, latest_pcl, latest_any = {}, {}, {}, {}
        val = {"like": 2.0, "complete": 1.5, "play": 1.0, "skip": 0.1, "dislike": -3.0}
        for i, ts, ev, _sec in log:
            latest_any[i] = max(latest_any.get(i, 0.0), ts)
            if ev in ("play", "complete", "like"):
                latest_pcl[i] = max(latest_pcl.get(i, 0.0), ts)
            if ts <= NOW - 8 * 86400:
                continue
            scores[i] = scores.get(i, 0.0) + val.get(ev, 0.5) * 0.5 ** ((NOW - ts) / (3 * 86400))
            latest[i] = max(latest.get(i, 0.0), ts)
        out, seen, per_artist = [], set(), Counter()

        def add(i, cap):
            a = int(recs["artist"][i])
            if per_artist[a] >= cap:
                return
            out.append(i); seen.add(i); per_artist[a] += 1
        if fresh:
            for i in sorted(latest_pcl, key=lambda i: (-latest_pcl[i], i))[:nout * 3]:
                if len(out) >= nout:
                    break
                if i not in seen:
                    add(i, 5)
        for i in sorted((i for i in scores if scores[i] > 0),
                        key=lambda i: (-scores[i], -latest[i], i)):
            if len(out) >= nout:
                break
            if i not in seen:
                add(i, 3)
        if len(out) < nout:
            for i in sorted(latest_any, key=lambda i: (-latest_any[i], i))[:nout * 4]:
                if len(out) >= nout:
                    break
                if i not in seen:
                    out.append(i); seen.add(i)
        return out[:nout]

    with open(os.path.join(OUT, "speeddial.bin"), "wb") as f:
        f.write(struct.pack("<d", NOW))
        for mode in (0, 1):
            got = dial(mode)
            f.write(struct.pack("<I", len(got)))
            for i in got:
                f.write(struct.pack("<I", i))

    print(f"goldens written to {OUT}")
    print(f"  log events: {len(log)}, pref tracks: {len(prefs['track'])}, "
          f"artists: {len(prefs['artist'])}, skip_ids: {len(prefs['skip_ids'])}")
    print(f"  taste: {'yes' if taste is not None else 'no'}, "
          f"skip: {'yes' if skipv is not None else 'no'}, rank cases: {len(cases)}")


if __name__ == "__main__":
    main()
