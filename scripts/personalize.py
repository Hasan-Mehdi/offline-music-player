#!/usr/bin/env python3
"""Personalization layer over the MuQ embeddings — turns logged play events into a
recommendation signal. Pure, dependency-light functions so they unit-test without Flask.

Implements the three highest-leverage borrowings from docs/RECSYS_RESEARCH.md:
  (1) Graded, time-thresholded SKIP negatives + completion-weighted positives  -> compute_prefs
  (2) A user TASTE CENTROID in MuQ space (completed pulls in, skipped pushes out) -> build_centroid
  (3) A SKIP-CONTRASTIVE / session term when ranking the next track            -> rank_next
Plus exploration refinements:
  (4a) Context-gated skips: an early-session skip usually means "wrong mood", not "bad
       track", so its negative weight is halved                                -> compute_prefs
  (4b) Novelty bonus decaying with play count, and exploration slots that go to the
       best-ranked UNHEARD candidate instead of a random re-pick     -> rank_next / choose_next
  (5)  Clustered THOMPSON SAMPLING for those exploration slots: pick the region to
       explore by its posterior, not by whatever ranked highest       -> choose_next_explained

Everything degrades gracefully: with no play history the taste/skip vectors are None and
rank_next reduces to the old pure content-similarity behaviour. Every signal added after
the first release is opt-in — omit its argument and the arithmetic is bit-identical to
the version before it landed, because the firmware goldens (firmware/tools/gen_goldens.py)
are generated from the default call.
"""
from __future__ import annotations

import math
import random as _random
from collections import defaultdict

import numpy as np

# --- signal thresholds (mirrors the RecSys skip-grading: <15% completion = strong
# negative; a "skip" after 80% is basically a finish, so it is NOT a negative). ---
STRONG_SKIP = 0.15
LATE_OK = 0.80
DEFAULT_HALFLIFE_DAYS = 30.0

# --- session gating: a skip within the first few tracks of a listening session usually
# means "wrong mood for this session", not "I dislike this track" -> soften the negative.
SESSION_GAP_SECONDS = 30 * 60      # >30 min between events starts a new session
EARLY_SESSION_TRACKS = 3           # first N distinct tracks of a session count as "early"
EARLY_SKIP_FACTOR = 0.5            # negatives in that window are halved

# --- already-heard recency: past this age the penalty is <1e-4 of the weight, so the
# lookup is skipped outright rather than computed and thrown away.
HEARD_MAX_AGE_SECONDS = 14 * 86400

# --- tempo continuity (DJ/MIR practice): tempo is perceived logarithmically and
# octave-equivalently — 80 and 160 BPM feel like the same pulse, so the distance is folded
# over half/double time. Inside ±5% two tracks beat-match; past ±15% the change is a
# deliberate gear shift, and the penalty saturates there rather than growing without bound.
BPM_FREE_RATIO = 1.05
BPM_FULL_RATIO = 1.15

# --- the strongest published skip signal lives in the first seconds of a track (the
# "skip cliff"): a listener who bails inside ~10s never gave it a chance at all.
EARLY_SKIP_COMPLETION = 0.05
EARLY_SKIP_SECONDS = 10.0
EARLY_SKIP_WEIGHT = -1.5

# --- browsing is not a verdict. Before the client told the two apart, starting another
# track by clicking it logged the abandoned one as a 'skip' — and on the real log 59 of
# 131 skips came in under 3 s, 103 of 216 track changes inside 10 s: clicking through
# search results, not rejecting music. The client now logs that case as 'switch'
# (weight 0); for the legacy rows (no `source`, written by the old client) a sub-3 s skip
# is treated the same way.
BROWSE_SECONDS = 3.0

# explicit, deliberate judgements: never softened as "early-session mood hunting"
EXPLICIT_EVENTS = ("like", "unlike", "dislike", "trash")


def is_browse_skip(event, seconds, source, browse_seconds=BROWSE_SECONDS):
    """True for a legacy (source-less) skip too short to have been a judgement."""
    return (bool(browse_seconds) and event == "skip" and source is None
            and seconds is not None and seconds < browse_seconds)


def center_embeddings(X, mean=None, chunk=8192):
    """Subtract the library-mean direction and re-normalize, IN PLACE (chunked, so a fp16
    matrix never needs a full fp32 copy). Returns (X, mean).

    MuQ vectors share one dominant direction: the mean of the unit vectors has norm 0.53
    and two random tracks sit at cosine 0.275 instead of 0. Any centroid of many tracks
    (taste, skip, session mood) collapses onto that shared direction and ends up scoring
    how TYPICAL a track is rather than how much it resembles the listener's picks —
    measured: on raw vectors the taste centroid predicts next-months' discoveries at
    AUC 0.54 (random 0.52); centered, 0.67. Nearest-neighbour quality is unchanged
    (artist@10 0.077 -> 0.079, 88% top-50 overlap), so the whole ranker runs centered."""
    if mean is None:
        acc = np.zeros(X.shape[1], dtype=np.float64)
        for a in range(0, len(X), chunk):
            acc += np.asarray(X[a:a + chunk], dtype=np.float64).sum(0)
        mean = (acc / max(1, len(X))).astype(np.float32)
    for a in range(0, len(X), chunk):
        z = np.asarray(X[a:a + chunk], dtype=np.float32) - mean
        z /= np.linalg.norm(z, axis=1, keepdims=True) + 1e-9
        X[a:a + chunk] = z.astype(X.dtype, copy=False)
    return X, mean


def history_weights(rows, now, halflife_days=365.0):
    """Taste weights from the YouTube Music listening history (data/seed_tracks.csv rows:
    video_id, play_count, last_played as YYYY-MM-DD): log1p(plays) x a one-year recency
    half-life. That is the best of the schemes tried on a temporal holdout (train on
    listens before 2026-07-26, predict the 410 library tracks first heard after it):
    log-plays beats raw plays and uniform; shorter half-lives did not help. At a TWO-WEEK
    horizon (5 cuts, predict the next 14 days' first listens) a 14-day half-life ties it,
    AUC 0.716 vs 0.698 — the Home "Recommended" shelf uses that one (mixture_shelf)."""
    out = {}
    for r in rows:
        vid = r.get("video_id")
        try:
            n = float(r.get("play_count") or 0)
            last = _date_epoch(r.get("last_played"))
        except (TypeError, ValueError):
            continue
        if not vid or n <= 0:
            continue
        age = max(0.0, (now - last) / 86400.0) if last else 365.0
        out[vid] = math.log1p(n) * 0.5 ** (age / halflife_days)
    return out


def mixture_shelf(X, id2i, ids_by_index, weights, cluster_of, eligible, n,
                  artist_of=None, cap=2, min_share=0.04):
    """Up to n eligible track ids for a recommendation shelf, ONE SHARE PER STYLE you have
    been listening to rather than the nearest tracks to a single taste centroid.

    `weights` {vid: taste weight} (e.g. history_weights with a short half-life) are
    pooled by `cluster_of` {vid: cluster}; every cluster holding at least `min_share` of
    the weight is a mode and gets that share of the n slots (largest remainder). Within
    a mode, eligible members of the same cluster rank by cosine to the mode's own
    weighted centroid. Modes are interleaved least-filled first (so row one mixes styles), and a
    mode that runs dry hands its slots to the rest. `artist_of(vid)` + `cap` keep any
    one channel to `cap` tracks across the whole shelf.

    Why not the centroid: a centroid of several styles is a point between them — on the
    real history the top 48 came from ~4 clusters and covered 43% of where the next two
    weeks' first listens went; the mixture spans ~9 and covers 74%, with as many hits."""
    W = {}
    for v, w in weights.items():
        c = cluster_of.get(v)
        if c is not None and v in id2i and w > 0:
            W[c] = W.get(c, 0.0) + w
    tot = sum(W.values())
    if n <= 0 or tot <= 0:
        return []
    ranked_modes = sorted(W.items(), key=lambda kv: -kv[1])
    modes = [c for c, w in ranked_modes if w / tot >= min_share] or [ranked_modes[0][0]]
    share = {c: W[c] for c in modes}
    s = sum(share.values())
    quota = {c: share[c] / s * n for c in modes}
    alloc = {c: int(q) for c, q in quota.items()}
    for c in sorted(modes, key=lambda c: -(quota[c] - alloc[c]))[:n - sum(alloc.values())]:
        alloc[c] += 1

    members = {c: [] for c in modes}                    # eligible candidates per mode
    for j, v in enumerate(ids_by_index):
        c = cluster_of.get(v)
        if c in members and eligible(v):
            members[c].append(j)

    def ranked(c):
        mw = {v: w for v, w in weights.items() if cluster_of.get(v) == c}
        cen = build_centroid(X, id2i, mw)
        idx = np.asarray(members[c], dtype=np.int64)
        if cen is None or not len(idx):
            return iter(())
        sims = np.asarray(X[idx], dtype=np.float32) @ cen
        return (ids_by_index[int(idx[k])] for k in np.argsort(-sims))

    streams = {c: ranked(c) for c in modes}
    per, out, taken = {}, [], {c: 0 for c in modes}
    def filled(c):
        return taken[c] / alloc[c] if alloc[c] else float("inf")

    while len(out) < n and streams:
        # the least-filled mode goes next (ties: the bigger one), so the first row of the
        # shelf already shows several styles instead of the biggest mode's whole quota
        c = min(streams, key=lambda c: (filled(c), -share[c]))
        for v in streams[c]:
            a = artist_of(v) if artist_of else None
            if a is not None and per.get(a, 0) >= cap:
                continue
            if a is not None:
                per[a] = per.get(a, 0) + 1
            out.append(v)
            taken[c] += 1
            break
        else:
            del streams[c]                                  # ran dry
    return out


def _date_epoch(date_str):
    """Epoch seconds (UTC midnight) of a YYYY-MM-DD string, None for blank."""
    if not date_str:
        return None
    import datetime as _dt
    d = _dt.date.fromisoformat(str(date_str)[:10])
    return _dt.datetime(d.year, d.month, d.day, tzinfo=_dt.timezone.utc).timestamp()


def _completion(seconds, duration):
    if not duration or duration <= 0 or seconds is None:
        return None
    return max(0.0, min(1.0, seconds / duration))


def event_weight(event, completion):
    """Signed value of one interaction. Positive = liked, negative = disliked, 0 = neutral.

    - like/dislike: explicit, strongest.
    - unlike: the exact retraction of a like (-3.0), so a like->unlike pair nets ~0 once
      both have decayed by the same amount. It is a correction, not a verdict.
    - trash: the strongest verdict there is — the listener threw the track OUT of the
      collection. Weighted like a dislike, and deliberately kept in the log after the
      track is gone so it keeps shaping the skip vector and the artist score.
    - complete: positive, scaled by how much was actually heard (replays sum -> stronger).
    - skip: strong negative only if abandoned early (<15%); a late skip (>80%) is a
      near-finish (mild positive); a mid skip is ambiguous -> neutral (discarded).
    - play: a track was merely started -> tiny positive.
    """
    if event == "like":
        return 3.0
    if event == "unlike":
        return -3.0
    if event == "dislike":
        return -3.0
    if event == "trash":
        return -3.0
    if event == "complete":
        return max(0.25, completion if completion is not None else 1.0)
    if event == "skip":
        if completion is None:
            return 0.0
        if completion < STRONG_SKIP:
            return -1.0
        if completion > LATE_OK:
            return 0.5
        return 0.0
    if event == "play":
        return 0.05
    return 0.0


def session_positions(plays, gap=SESSION_GAP_SECONDS):
    """Track-position of each event within its inferred listening session.

    plays: iterable of (video_id, ts, event, seconds). Sessions are split on gaps of
    more than `gap` seconds between consecutive events (time-sorted). Position is the
    1-based index of the *distinct track* within its session, so all events for the
    2nd track of a session get position 2. Events without a timestamp get position
    None (no gating applied). Returns {(vid, ts): position}.
    """
    timed = sorted((p for p in plays if p[1]), key=lambda p: p[1])
    pos = {}
    last_ts, session_tracks = None, []
    for vid, ts, *_rest in timed:
        if last_ts is None or ts - last_ts > gap:
            session_tracks = []
        if vid not in session_tracks:
            session_tracks.append(vid)
        pos[(vid, ts)] = session_tracks.index(vid) + 1
        last_ts = ts
    return pos


def compute_prefs(plays, durations, id2artist, now, halflife_days=DEFAULT_HALFLIFE_DAYS,
                  neg_halflife_days=None, strong_early_skip=False, explicit_state=False,
                  browse_seconds=None):
    """Roll raw play events into recency-decayed preference scores.

    plays: iterable of (video_id, ts, event, seconds[, source]).
    durations: {video_id: seconds}.  id2artist: {video_id: artist}.  now: epoch seconds.
    Negative signals from the first EARLY_SESSION_TRACKS tracks of a session are
    softened (early skips reflect mood-hunting more than dislike).
    Returns {'track': {vid: score}, 'artist': {artist: score}, 'skip_ids': set,
             'play_counts': {vid: n started}}.

    Two refinements are OPT-IN and leave the defaults bit-identical:
    - neg_halflife_days: decay NEGATIVE events on their own (shorter) half-life while
      positives keep `halflife_days`. Dislike is the more perishable judgement — a skip
      from six weeks ago says more about that evening than about the track — whereas a
      track you loved stays loved. None -> both signs share `halflife_days`.
    - strong_early_skip: grade the skip cliff. A skip inside EARLY_SKIP_COMPLETION of the
      track or the first EARLY_SKIP_SECONDS seconds counts EARLY_SKIP_WEIGHT instead of
      the flat -1.0: bailing in the first seconds is a rejection of the track itself,
      while a skip at 12% at least got a listen. Stacks multiplicatively with the
      early-session halving above (mood-hunting still softens it).
    - explicit_state: a like is a STATE, not an event stream — the UI shows a track as
      liked iff its latest like/unlike is a like (/api/likes), and the engine now reads
      it the same way: only the standing like counts (+3.0, aged from when it was given)
      and an unlike simply removes it. Summing them instead left a mis-tapped like that
      was undone at once at +1.5 (the unlike, being negative, got the early-session
      halving) and turned a 90-day-old like that was taken back into a -1.1 "dislike".
      Explicit judgements (like/unlike/dislike/trash) are also exempt from the
      early-session halving, which exists for ambiguous skips.
    - browse_seconds: legacy (source-less) skips shorter than this are navigation, not
      verdicts (see BROWSE_SECONDS) and carry no weight.
    Rows may carry a 5th `source` field (the surface that started the track).
    The returned dict also has 'artist_mass': per artist, the recency-weighted COUNT of
    decided outcomes behind its score, so a caller can use a rate instead of a sum.
    """
    plays = list(plays)
    positions = session_positions(plays)
    standing = {}                      # vid -> row index of its latest like/unlike
    if explicit_state:
        order = sorted(range(len(plays)), key=lambda i: plays[i][1] or 0.0)
        for i in order:                # stable: same-ts rows keep log order
            if plays[i][2] in ("like", "unlike"):
                standing[plays[i][0]] = i
    track = defaultdict(float)
    artist = defaultdict(float)
    artist_mass = defaultdict(float)
    play_counts = defaultdict(int)
    for i, row in enumerate(plays):
        vid, ts, event, seconds = row[0], row[1], row[2], row[3]
        source = row[4] if len(row) > 4 else None
        if event == "play":
            play_counts[vid] += 1
        if explicit_state and event in ("like", "unlike") and (
                event == "unlike" or standing.get(vid) != i):
            continue
        if browse_seconds and is_browse_skip(event, seconds, source, browse_seconds):
            continue
        completion = _completion(seconds, durations.get(vid))
        w = event_weight(event, completion)
        if w == 0.0:
            continue
        if (strong_early_skip and event == "skip" and w == -1.0
                and ((completion is not None and completion < EARLY_SKIP_COMPLETION)
                     or (seconds is not None and seconds < EARLY_SKIP_SECONDS))):
            w = EARLY_SKIP_WEIGHT
        pos = positions.get((vid, ts))
        if (w < 0 and pos is not None and pos <= EARLY_SESSION_TRACKS
                and not (explicit_state and event in EXPLICIT_EVENTS)):
            w *= EARLY_SKIP_FACTOR
        f = 1.0
        if ts and now:
            hl = neg_halflife_days if (neg_halflife_days and w < 0) else halflife_days
            days = max(0.0, (now - ts) / 86400.0)
            f = 0.5 ** (days / hl)
            w *= f
        track[vid] += w
        a = id2artist.get(vid)
        if a:
            artist[a] += w
            if event != "play":
                artist_mass[a] += f
    skip_ids = {v for v, s in track.items() if s < 0}
    return {"track": dict(track), "artist": dict(artist), "skip_ids": skip_ids,
            "play_counts": dict(play_counts), "artist_mass": dict(artist_mass)}


def build_centroid(X, id2i, weights, positive_only=False):
    """Weighted, L2-normalized centroid of track embeddings. `weights` maps vid->float
    (may be negative: disliked tracks push the centroid away). Returns a unit vector or
    None if no usable signal. X is assumed L2-normalized row-wise."""
    if X is None or not weights:
        return None
    acc = np.zeros(X.shape[1], dtype=np.float32)
    total = 0.0
    for vid, w in weights.items():
        if positive_only and w <= 0:
            continue
        i = id2i.get(vid)
        if i is None:
            continue
        acc += w * X[i]
        total += abs(w)
    if total == 0.0:
        return None
    norm = np.linalg.norm(acc)
    if norm < 1e-9:
        return None
    return (acc / norm).astype(np.float32)


WINDOW_COS_TERMS = (("mu", "session"), ("delta", "taste"), ("sigma", "skip"), ("kappa", "sskip"))
WINDOW_FLAT_TERMS = ("gamma", "gamma_artist", "cooldown", "nu", "beta", "heard_w",
                     "energy_w", "bpm_w")
WINDOW_U_DEFAULT = 0.12   # typical vibe std of a centered 400-candidate window (measured)
WINDOW_U_FLOOR = 1e-4     # degeneracy guard only (real windows: ~0.1)


def _window_params(p, candidate_ids, X, id2i, cur_vec, vecs):
    """Effective weights for scale="window" (see rank_next). The unit is u, the spread
    (std) of the vibe cosine across THIS candidate list:
    - each cosine-derived term (mood/taste/skip/session-skip) is rescaled so its spread
      across the list is weight x u — "0.35" now means "a third of vibe's say", however
      dense the neighbourhood or however lopsided that centroid happens to be;
    - flat terms (cooldown, heard, cooc, prefs, novelty, energy, tempo) are given in
      units of u, so "1.0" is one standard deviation of vibe;
    - the band slopes (rho, same_w) are already relative to vibe's slope and stay put.
    Why: at 20k tracks the vibe range inside a candidate window was ~0.35; at 56k it is
    ~0.13 (std ~0.03), and every fixed-magnitude term had silently tripled in relative
    weight — the tempo term out-voted sounding alike."""
    idx = [id2i[v] for v in candidate_ids if v in id2i]
    if not idx:
        return p
    V = np.asarray(X[idx], dtype=np.float32)
    # no vibe to measure (current track unembedded, or a single candidate): fall back to
    # the typical spread, so flat weights never get applied as raw cosines
    u = WINDOW_U_DEFAULT
    if cur_vec is not None and len(idx) >= 2:
        u = max(float(np.std(V @ cur_vec)), WINDOW_U_FLOOR)
    q = dict(p)
    for key, name in WINDOW_COS_TERMS:
        vec = vecs.get(name)
        if vec is None or not p[key]:
            continue
        s = V @ np.asarray(vec, dtype=np.float32)
        if key in ("sigma", "kappa"):       # these two only ever charge positive alignment
            s = np.maximum(s, 0.0)
        sd = float(np.std(s))
        q[key] = p[key] * u / sd if sd > 1e-6 else 0.0   # a constant term orders nothing
    for key in WINDOW_FLAT_TERMS:
        q[key] = p[key] * u
    q["_u"] = u
    return q


def rank_next(current_id, candidate_ids, X, id2i, ids_by_index, artist_by_index,
              prefs=None, taste_vec=None, skip_vec=None, recent_artists=(), params=None,
              recent_vecs=None, session_vec=None, cooc_members=None, last_played=None,
              now=None, energies=None, bpms=None, explain=False, session_skip_vec=None):
    """Score candidate tracks and return them ordered best-first as (vid, score).

    Blends: content vibe to current track + taste-centroid affinity + logged preference
    + a tanh-capped artist preference (saturates at ±gamma_artist: a channel-level
    "you love this uploader" signal is unbounded in prefs, and letting it grow past the
    ~0.35 vibe spread of a candidate window let a completed-twice channel add +0.63 and
    override the mood — chill session, boss-battle pick)
    - skip-contrastive similarity - artist-cooldown penalty
    - neighborhood fatigue: similarity above `rho_floor` to ANY of `recent_vecs` (the
    last few played tracks' embeddings, current included) costs `rho` per unit. Without
    it the walk is greedy nearest-neighbor: seeded on a chiptune it played 15 straight
    8-bit clones at 0.97+ consecutive sim, because nothing said "you've been here".
    Because the current track is among the recents, net reward for sim s to it is
    s below rho_floor but (alpha - rho)·s above it — the score peaks AT the band edge,
    so dense clone-clusters get medium steps outward while sparse neighborhoods (nothing
    over the floor) are untouched. Retrieval still bounds each step to the current
    track's neighborhood, so drift stays gradual — adjacent territory, never a teleport.
    + session-mood affinity: `mu` x sim to `session_vec` (centroid of the last ~dozen
    played). Fatigue alone escaped the clone-cluster but then band-edge-surfed AWAY in
    a straight line (seed-sim 0.80 -> 0.29 in five steps — the other failure mode). The
    session centroid is the slow inward anchor that turns the march into an orbit: out
    of the 8-bit micro-cluster, around the session's macro-mood. A deliberate user pivot
    re-centers it within a few tracks since it is rebuilt from the recent tail each call.
    + a novelty bonus that halves with each past listen (unheard tracks get the full
    `nu`; well-worn tracks get ~nothing), keeping the queue from orbiting favourites.
    With prefs/taste_vec/skip_vec/recent_vecs all None it is exactly the old
    content-only ranking.

    Three further terms are opt-in and contribute EXACTLY zero when their input is
    absent, so the content-only / no-history behaviour (and the firmware goldens) is
    untouched:
    + collaborative co-occurrence: `cooc_members` is {seed_id: set(member ids)} from the
    YT-Music song radios (data/radio_cache). A candidate that shares a radio with the
    current track — either direction, the relation is symmetric — gets a flat +beta.
    This is raw radio co-membership — the BASELINE of docs/EXPERIMENTS.md; the +32% r@50
    measured there is the pos+song2vec hybrid OVER this baseline, which is not wired in.
    - already-heard recency: `last_played` is {vid: last play/complete epoch seconds} and
    `now` the current epoch. A track heard recently is damped by heard_w, halving every
    heard_halflife seconds, so an hour-old track does not come back the moment it falls
    off the client's exclude window. Ignored past HEARD_MAX_AGE_SECONDS.
    - energy continuity: `energies` is {vid: 0..1 energy percentile}. Candidates within
    `energy_band` of the current track are free; beyond it the gap costs energy_w per
    unit, so the walk does not cut from a lullaby to a breakdown. Zero unless BOTH the
    candidate and the current track have an energy.
    - tempo continuity: `bpms` is {vid: bpm}. Distance is measured in OCTAVE-FOLDED log
    tempo (a 160 BPM track next to an 80 BPM one is a perfect double-time match, not a
    catastrophe), free inside ±BPM_FREE_RATIO and ramping to the full `bpm_w` at
    ±BPM_FULL_RATIO, where it saturates — beyond "different tempo" there is nothing more
    to say. Zero unless BOTH tracks have a usable (>0) bpm.
    - sameness hill: `same_w` (default 0.0 = OFF, so this is a no-op by construction)
    costs `same_w` per unit of similarity to the CURRENT track above `same_floor`.
    Everything else here rewards similarity — vibe, mood and taste all pull the same
    way — and fatigue only answers the *recent tail*, so a candidate that is a near-copy
    of the track playing was never charged for it ("all the songs kinda sound the same in
    the autoplay"). Above the floor the net vibe reward is (alpha - same_w)·s, i.e. the
    score peaks just under `same_floor`: a clone is still a legal step, just no longer the
    automatic one, and anything below the floor is untouched.
    - session rejection: `session_skip_vec` is the centroid of tracks rejected in THIS
    listening session (early skips, dislikes); similarity to it costs `kappa` per unit
    (positive alignment only). The long-term skip vector answers "what do you dislike";
    this answers "not that, not now" — the thing a listener means by pressing Next.

    Further opt-in params (all off by default):
    - track_tanh: squash the per-track preference through tanh like the artist term
    (one like is +3.0 in prefs; unsquashed that is +1.5 against a vibe spread of ~0.03,
    so any liked track in the pool won regardless of mood — the chill->boss bug again).
    - artist_prior: score a channel by its RATE, sum / (decided outcomes + prior), using
    prefs["artist_mass"], instead of its sum — a sum saturates for any channel you have
    simply heard a lot of, whatever fraction of it you skipped.
    - scale="window": density-independent weights, see _window_params.

    recent_vecs: optional (K, D) float array of recent track embeddings (L2-normalized,
    most-recent-last). explain=True turns each element into (vid, score, terms) where
    `terms` is the signed per-component breakdown (vibe/taste/pref_track/pref_artist/
    cooldown/skip/fatigue/novelty/cooc/heard/energy/bpm/sameness) that sums to score —
    for the /api/next trace and trace_next.py. Default shape is unchanged.
    """
    p = {"alpha": 1.0, "delta": 0.6, "gamma": 0.5, "gamma_artist": 0.3,
         "sigma": 0.7, "cooldown": 0.5, "nu": 0.1, "rho": 2.0, "rho_floor": 0.80,
         "mu": 0.6, "beta": 0.3, "heard_w": 0.6, "heard_halflife": 24 * 3600.0,
         "energy_w": 0.8, "energy_band": 0.35, "bpm_w": 0.25,
         "same_w": 0.0, "same_floor": 0.92,
         "kappa": 0.0, "track_tanh": 0, "artist_prior": 0.0, "scale": None}
    if params:
        p.update(params)
    R = None
    if recent_vecs is not None and len(recent_vecs):
        R = np.asarray(recent_vecs, dtype=np.float32)
    prefs = prefs or {"track": {}, "artist": {}}
    play_counts = prefs.get("play_counts") or {}
    cur_i = id2i.get(current_id)
    # fp32 view of the current row so dots stay fp32 even when X is stored fp16
    cur_vec = np.asarray(X[cur_i], dtype=np.float32) if (cur_i is not None and X is not None) else None
    recent = set(recent_artists)
    cur_members = (cooc_members or {}).get(current_id) or ()
    heard = last_played if (last_played and now) else None   # both halves required
    cur_energy = energies.get(current_id) if energies else None
    cur_bpm = bpms.get(current_id) if bpms else None
    if not cur_bpm or cur_bpm <= 0:
        cur_bpm = None
    free = math.log2(BPM_FREE_RATIO)
    span = math.log2(BPM_FULL_RATIO) - free
    if p["scale"] == "window":
        p = _window_params(p, candidate_ids, X, id2i, cur_vec,
                           {"session": session_vec, "taste": taste_vec, "skip": skip_vec,
                            "sskip": session_skip_vec})
    artist_mass = prefs.get("artist_mass") or {}

    out = []
    for vid in candidate_ids:
        j = id2i.get(vid)
        if j is None:
            continue
        # signed per-term contributions (sum == score); kept even when not explaining so
        # the arithmetic below is identical to the old inline accumulation.
        t = {"vibe": 0.0, "taste": 0.0, "pref_track": 0.0, "pref_artist": 0.0,
             "cooldown": 0.0, "skip": 0.0, "fatigue": 0.0, "mood": 0.0, "novelty": 0.0,
             "cooc": 0.0, "heard": 0.0, "energy": 0.0, "bpm": 0.0, "sameness": 0.0}
        if cur_vec is not None:
            cos_cur = float(X[j] @ cur_vec)
            t["vibe"] = p["alpha"] * cos_cur
            if p["same_w"]:      # off by default -> not even evaluated -> exact parity
                t["sameness"] = -p["same_w"] * max(0.0, cos_cur - p["same_floor"])
        if session_vec is not None:
            t["mood"] = p["mu"] * float(X[j] @ session_vec)
        if taste_vec is not None:
            t["taste"] = p["delta"] * float(X[j] @ taste_vec)
        if p["track_tanh"]:
            t["pref_track"] = p["gamma"] * math.tanh(prefs["track"].get(vid, 0.0))
        else:
            t["pref_track"] = p["gamma"] * prefs["track"].get(vid, 0.0)
        art = artist_by_index[j] if artist_by_index is not None else None
        if art:
            # tanh-squashed: caps at ±gamma_artist so a beloved channel nudges, never
            # out-shouts the vibe ordering (an unbounded +0.63 here once turned a chill
            # session into a boss battle); ~linear for small scores, symmetric for dislikes.
            a_score = prefs["artist"].get(art, 0.0)
            if p["artist_prior"]:
                a_score = a_score / (artist_mass.get(art, 0.0) + p["artist_prior"])
            t["pref_artist"] = p["gamma_artist"] * math.tanh(a_score)
            if art in recent:
                t["cooldown"] = -p["cooldown"]
        if skip_vec is not None:
            t["skip"] = -p["sigma"] * max(0.0, float(X[j] @ skip_vec))
        if R is not None:
            t["fatigue"] = -p["rho"] * max(
                0.0, float(np.max(R @ np.asarray(X[j], dtype=np.float32))) - p["rho_floor"])
        t["novelty"] = p["nu"] * 0.5 ** play_counts.get(vid, 0)
        if cooc_members and (vid in cur_members or current_id in (cooc_members.get(vid) or ())):
            t["cooc"] = p["beta"]
        if heard is not None:
            ts = heard.get(vid)
            if ts is not None:
                age = max(0.0, now - ts)
                if age < HEARD_MAX_AGE_SECONDS:
                    t["heard"] = -p["heard_w"] * 0.5 ** (age / p["heard_halflife"])
        if cur_energy is not None:
            e = energies.get(vid)
            if e is not None:
                t["energy"] = -p["energy_w"] * max(0.0, abs(e - cur_energy) - p["energy_band"])
        if cur_bpm is not None:
            b = bpms.get(vid)
            if b and b > 0:
                # octave fold: half/double time is the same pulse, so measure the log
                # ratio against the nearest of {half, same, double} the candidate tempo
                r = math.log2(b / cur_bpm)
                d = min(abs(r - 1.0), abs(r), abs(r + 1.0))
                if d > free:
                    t["bpm"] = -p["bpm_w"] * min(1.0, (d - free) / span)
        if session_skip_vec is not None:   # key only exists when armed -> default parity
            t["sskip"] = -p["kappa"] * max(0.0, float(X[j] @ session_skip_vec))
        s = sum(t.values())
        out.append((vid, s, t) if explain else (vid, s))
    out.sort(key=lambda e: e[1], reverse=True)
    return out


CLUSTER_WINDOW = 40      # ranked candidates considered when sampling a cluster to explore
SOUND_TERMS = ("vibe", "mood", "fatigue", "sameness")   # "does it sound right next"


def choose_next(ranked, play_counts=None, epsilon=0.15, top_k=12, rng=_random,
                clusters=None, cluster_stats=None, sound_budget=None, prior_n=None):
    """Pick the next track from a best-first `ranked` list of (vid, score).

    Exploit by default (the top-ranked track). With probability `epsilon`, spend the
    slot on EXPLORATION — but instead of a random re-pick among the top few (which
    mostly re-surfaces already-known tracks), take the best-ranked track within the
    top_k window that has never been played. If everything in the window has history,
    fall back to a random pick from the top 4 (the old behaviour). Returns a vid or
    None for an empty list.
    """
    return choose_next_explained(ranked, play_counts, epsilon, top_k, rng,
                                 clusters, cluster_stats, sound_budget, prior_n)[0]


def choose_next_explained(ranked, play_counts=None, epsilon=0.15, top_k=12, rng=_random,
                          clusters=None, cluster_stats=None, sound_budget=None,
                          prior_n=None):
    """Like choose_next but also reports the exploration decision, as
    (vid, {"explored": bool, "reason": "exploit"|"explore_cluster"|"explore_unheard"|
    "explore_random"}), so callers can log WHY the pick differs from rank 1. `ranked`
    elements may be (vid, score) or the explain=True (vid, score, terms). vid is None
    for an empty list.

    CLUSTERED THOMPSON SAMPLING (opt-in; both `clusters` {vid: cluster_id} and
    `cluster_stats` {cluster_id: (accepts, skips)} required, else this is byte-for-byte
    the old flat exploration). A flat epsilon spends every exploration slot on whatever
    unheard track happens to rank highest, which is almost always another sample of the
    region already being exploited. Instead, treat each CLUSTER as an arm: draw
    theta_c ~ Beta(accepts+1, skips+1) per cluster represented in the top
    CLUSTER_WINDOW, and explore the winner's best-ranked unheard track. Clusters you
    have accepted from get sampled high (exploit what works); clusters with little
    history keep a wide posterior and therefore keep getting a turn (that is the
    exploration); clusters you consistently skip fall away on their own. If the sampled
    cluster has nothing unheard on offer, fall through to the flat chain below rather
    than forcing a re-listen.

    `sound_budget` (opt-in, needs explain=True terms): an explore pick may give up at
    most this many standard deviations of SOUND_TERMS against the best-sounding
    candidate in the list. Without it the winning arm's best unheard track can sit at
    rank 35 of the window, a different sound entirely (Gusty Garden -> lounge jazz). It
    bounds the unheard-chain too; the all-heard random tail is left as it was.

    `prior_n` (opt-in): arms start from the POOLED accept rate with this many outcomes'
    worth of weight instead of a uniform Beta(1,1), so a cluster needs about prior_n
    verdicts before its own record outweighs everyone's. Under the uniform prior 2
    accepts out of 2 drew from Beta(3,1) and beat a cluster with 9 accepts out of 21.
    """
    if not ranked:
        return None, {"explored": False, "reason": "exploit"}
    if rng.random() >= epsilon:
        return ranked[0][0], {"explored": False, "reason": "exploit"}
    counts = play_counts or {}
    ok = _sound_ok(ranked, sound_budget, max(CLUSTER_WINDOW, top_k))
    if clusters is not None and cluster_stats is not None:
        # an EMPTY stats map is still armed: with no history every arm holds the flat
        # prior, which is exactly the cold-start behaviour Thompson sampling prescribes.
        window = [e for i, e in enumerate(ranked[:CLUSTER_WINDOW]) if ok is None or ok[i]]
        arms = []                                  # first-appearance order == deterministic
        for e in window:
            c = clusters.get(e[0])
            if c is not None and c not in arms:
                arms.append(c)
        if arms:
            prior = _pooled_prior(cluster_stats, prior_n)
            best = max(arms, key=lambda c: _beta_sample(rng, cluster_stats.get(c), prior))
            for e in window:
                if clusters.get(e[0]) == best and counts.get(e[0], 0) == 0:
                    return e[0], {"explored": True, "reason": "explore_cluster"}
    for i, e in enumerate(ranked[:top_k]):
        if counts.get(e[0], 0) == 0 and (ok is None or ok[i]):
            return e[0], {"explored": True, "reason": "explore_unheard"}
    return rng.choice(ranked[:4])[0], {"explored": True, "reason": "explore_random"}


def _sound_ok(ranked, budget, n):
    """[bool] for ranked[:n]: within `budget` sd of the list's best SOUND_TERMS sum. The
    sd is over the whole list, as in eval_autoplay's "sound given up". None when there
    is no budget or no per-term breakdown to measure it with."""
    if budget is None or len(ranked[0]) < 3:
        return None
    keys = [k for k in SOUND_TERMS if k in ranked[0][2]]
    if not keys:
        return None
    snd = np.array([sum(e[2][k] for k in keys) for e in ranked], dtype=np.float64)
    floor = snd.max() - budget * (snd.std() + 1e-9)
    return [bool(x >= floor) for x in snd[:n]]


def _pooled_prior(stats, prior_n):
    """Beta prior (a0, b0) for every arm: uniform (1, 1) by default, else prior_n
    outcomes at the pooled accept rate (itself smoothed, so no history -> 0.5)."""
    if not prior_n:
        return 1.0, 1.0
    acc = sum(max(0.0, a) for a, s in stats.values())
    tot = acc + sum(max(0.0, s) for a, s in stats.values())
    rate = (acc + 1.0) / (tot + 2.0)
    return prior_n * rate, prior_n * (1.0 - rate)


def _beta_sample(rng, stats, prior=(1.0, 1.0)):
    """One Thompson draw for an arm with (accepts, skips) history — Beta(a+a0, s+b0);
    the default (1, 1) is a uniform prior, so an arm with no history samples anywhere
    in [0,1]."""
    a, s = stats if stats else (0.0, 0.0)
    return rng.betavariate(max(0.0, a) + prior[0], max(0.0, s) + prior[1])
