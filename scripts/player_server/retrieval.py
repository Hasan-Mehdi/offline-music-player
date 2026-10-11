"""Candidate retrieval helpers used by the autoplay server.

These functions do not know about Flask, SQLite, or the server's module globals.
Keeping the retrieval policy here makes the boundary explicit and lets the
entrypoint retain compatibility wrappers for callers that import ``server``.
"""

import random


DEFAULT_BLEND = {"cur": 300, "taste": 80, "radio": 50, "fresh": 25,
                 "fresh_pool": 2000, "total": 400}
DEFAULT_BLEND_LOW_MEM = {"cur": 120, "taste": 0, "radio": 50, "fresh": 10,
                         "fresh_pool": 0, "total": 180}


def top_ids(sims, ids, k):
    """Return the ``k`` highest-scoring ids, in descending score order."""
    import numpy as np

    n = len(ids)
    k = max(1, min(k, n))
    idx = np.argpartition(-sims, k - 1)[:k] if k < n else np.arange(n)
    idx = idx[np.argsort(-sims[idx])]
    return [ids[int(j)] for j in idx]


def blend_candidates(cur, base, lib, exclude, taste_ids=(), radio_ids=(),
                     play_counts=None, caps=None, rng=None, defaults=None):
    """Build a deduplicated, multi-source candidate list for autoplay.

    ``base`` is the similarity-ordered backbone.  ``taste_ids`` and ``radio_ids``
    open additional sources, while the fresh slice samples unheard tracks from
    the backbone.  The backbone is the only source trimmed when the total cap is
    exceeded.  ``defaults`` is supplied by the server compatibility wrapper so
    its module-level tuning remains authoritative.
    """
    if defaults is None:
        defaults = DEFAULT_BLEND
    c = dict(defaults)
    if caps:
        c.update(caps)
    counts = play_counts or {}
    rng = rng or random.Random(cur)
    out, src, seen = [], [], set()

    def take(vids, name, cap):
        n = 0
        for v in vids:
            if n >= cap:
                break
            if v in seen or v in exclude or v not in lib:
                continue
            seen.add(v)
            out.append(v)
            src.append(name)
            n += 1

    take(base, "cur", c["cur"])
    take(taste_ids, "taste", c["taste"])
    take(sorted(radio_ids), "radio", c["radio"])
    pool_src = base[:c["fresh_pool"]] if c["fresh_pool"] else base
    pool = [v for v in pool_src
            if v not in seen and v not in exclude and v in lib and not counts.get(v)]
    if pool and c["fresh"]:
        take(rng.sample(pool, min(c["fresh"], len(pool))), "fresh", c["fresh"])
    if len(out) > c["total"]:
        drop, kill = len(out) - c["total"], set()
        for i in range(len(out) - 1, -1, -1):
            if drop <= 0:
                break
            if src[i] == "cur":
                kill.add(i)
                drop -= 1
        out = [v for i, v in enumerate(out) if i not in kill][:c["total"]]
    return out


def session_centroid(embedding, mood_ids, build_centroid, decay=0.85):
    """Return an exponentially weighted centroid of the recent listening tail."""
    if not mood_ids:
        return None
    n = len(mood_ids)
    weights, total = {}, 0.0
    for i, video_id in enumerate(mood_ids):
        weight = decay ** (n - 1 - i)
        weights[video_id] = weights.get(video_id, 0.0) + weight
        total += weight
    if total:
        weights = {video_id: weight / total
                   for video_id, weight in weights.items()}
    return build_centroid(embedding["X"], embedding["id2i"], weights)
