"""Tests for the personalization layer (scripts/personalize.py) — the three RecSys
borrowings: graded skip negatives, taste centroid, skip-contrastive next-track ranking.
Run: .venv\\Scripts\\python -m pytest -q tests/test_personalize.py
"""
import sys

import numpy as np
import pytest

sys.path.insert(0, "scripts")

NOW = 1_800_000_000.0  # fixed "now" so recency decay is deterministic

# every signed component rank_next(explain=True) must report, always present so a term
# that is switched off is visibly 0.0 rather than missing (the trace/AB tooling reads
# these keys by name).
TERM_KEYS = {"vibe", "taste", "pref_track", "pref_artist", "cooldown", "skip",
             "fatigue", "mood", "novelty", "cooc", "heard", "energy", "bpm", "sameness"}


# ---------------------------------------------------------------- (1) skip negatives

def test_event_weight_grading():
    from personalize import event_weight
    # early skip (<15% heard) is a strong negative
    assert event_weight("skip", 0.02) == -1.0
    # late skip (>80%) is a near-finish, NOT a negative (mild positive)
    assert event_weight("skip", 0.95) > 0
    # mid skip is ambiguous -> neutral / discarded
    assert event_weight("skip", 0.5) == 0.0
    # completes are positive, likes strongest positive, dislikes strong negative
    assert event_weight("complete", 1.0) > 0
    assert event_weight("like", None) > event_weight("complete", 1.0)
    assert event_weight("dislike", None) < event_weight("skip", 0.02)


def test_compute_prefs_signs_and_skip_ids():
    from personalize import compute_prefs
    durations = {"A": 200, "B": 200, "C": 200}
    id2artist = {"A": "ArtistA", "B": "ArtistB", "C": "ArtistA"}
    plays = [
        ("A", NOW, "skip", 4),      # 2% -> strong negative
        ("B", NOW, "complete", 200),  # finished -> positive
        ("C", NOW, "skip", 190),    # 95% -> late skip, not a negative
    ]
    prefs = compute_prefs(plays, durations, id2artist, now=NOW)
    assert prefs["track"]["A"] < 0 < prefs["track"]["B"]
    assert prefs["track"]["C"] > 0                 # late skip didn't become a negative
    assert "A" in prefs["skip_ids"] and "B" not in prefs["skip_ids"]
    # artist score aggregates A (neg) + C (pos) for ArtistA; ArtistB positive
    assert prefs["artist"]["ArtistB"] > 0


def test_recency_decay_downweights_old_plays():
    from personalize import compute_prefs
    dur = {"A": 100}
    old = [("A", NOW - 60 * 86400, "complete", 100)]  # 60 days ago, halflife 30 -> ~1/4
    new = [("A", NOW, "complete", 100)]
    w_old = compute_prefs(old, dur, {}, now=NOW, halflife_days=30)["track"]["A"]
    w_new = compute_prefs(new, dur, {}, now=NOW, halflife_days=30)["track"]["A"]
    assert w_new > w_old > 0
    assert w_old == pytest.approx(w_new * 0.25, rel=0.05)


# ---------------------------------------------------------------- (2) taste centroid

def _emb():
    # 3 orthogonal "taste directions"; rows L2-normalized like the real matrix.
    ids = ["liked1", "liked2", "hated1", "cand_like", "cand_hate", "cur"]
    X = np.array([
        [1, 0, 0],   # liked1
        [1, 0.2, 0], # liked2  (near liked axis)
        [0, 1, 0],   # hated1
        [0.9, 0.1, 0],  # cand_like (near liked cluster)
        [0, 0.9, 0.1],  # cand_hate (near hated cluster)
        [0.5, 0.5, 0.3],  # cur (neutral-ish)
    ], dtype=np.float32)
    X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    id2i = {v: i for i, v in enumerate(ids)}
    return X, id2i, ids


def test_taste_centroid_points_toward_liked():
    from personalize import build_centroid
    X, id2i, _ = _emb()
    weights = {"liked1": 2.0, "liked2": 1.5, "hated1": -2.0}
    taste = build_centroid(X, id2i, weights)
    assert taste is not None
    # centroid should align with the liked axis, not the hated one
    assert float(X[id2i["cand_like"]] @ taste) > float(X[id2i["cand_hate"]] @ taste)
    assert float(X[id2i["liked1"]] @ taste) > 0
    assert float(X[id2i["hated1"]] @ taste) < 0.5


def test_build_centroid_none_without_signal():
    from personalize import build_centroid
    X, id2i, _ = _emb()
    assert build_centroid(X, id2i, {}) is None
    assert build_centroid(None, id2i, {"liked1": 1.0}) is None


# ---------------------------------------------------------------- (3) skip-contrastive rank

def test_rank_prefers_taste_and_penalizes_skip_similarity():
    from personalize import build_centroid, rank_next
    X, id2i, ids = _emb()
    artist_by_index = [None] * len(ids)
    weights = {"liked1": 2.0, "liked2": 1.5, "hated1": -2.0}
    taste = build_centroid(X, id2i, weights)
    skip_vec = build_centroid(X, id2i, {"hated1": 1.0})  # session skip direction
    prefs = {"track": {}, "artist": {}}
    ranked = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                       prefs=prefs, taste_vec=taste, skip_vec=skip_vec)
    assert ranked[0][0] == "cand_like"          # liked-cluster candidate wins
    assert ranked[0][1] > ranked[1][1]


def test_rank_falls_back_to_content_only():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = [None] * len(ids)
    # no prefs / taste / skip -> pure similarity to current; cand_like is closer to cur
    ranked = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index)
    order = [v for v, _ in ranked]
    assert set(order) == {"cand_like", "cand_hate"}
    # deterministic: cand_like has higher cosine to cur than cand_hate
    assert ranked[0][0] == "cand_like"


# ------------------------------------------------- (4a) context-gated early-session skips

def test_session_positions_split_on_gap():
    from personalize import session_positions
    plays = [
        ("A", NOW, "play", 0), ("A", NOW + 60, "skip", 10),        # session 1, track 1
        ("B", NOW + 70, "play", 0),                                 # session 1, track 2
        ("C", NOW + 7200, "play", 0),                               # 2h gap -> session 2, track 1
    ]
    pos = session_positions(plays)
    assert pos[("A", NOW)] == 1 and pos[("A", NOW + 60)] == 1
    assert pos[("B", NOW + 70)] == 2
    assert pos[("C", NOW + 7200)] == 1


def test_early_session_skip_is_softened():
    from personalize import compute_prefs, EARLY_SKIP_FACTOR
    dur = {"A": 200, "B": 200}
    # A: skipped as the 1st track of a session. B: skipped as the 5th track (4 distinct
    # tracks played before it) -> full penalty. Same completion, same recency.
    early = [("A", NOW, "skip", 4)]
    late = [("W", NOW, "play", 0), ("X", NOW + 60, "play", 0),
            ("Y", NOW + 120, "play", 0), ("Z", NOW + 180, "play", 0),
            ("B", NOW + 240, "skip", 4)]
    p_early = compute_prefs(early, dur, {}, now=NOW)
    p_late = compute_prefs(late, dur, {}, now=NOW + 240)
    assert p_early["track"]["A"] < 0 and p_late["track"]["B"] < 0
    assert p_early["track"]["A"] == pytest.approx(
        p_late["track"]["B"] * EARLY_SKIP_FACTOR, rel=0.05)


def test_compute_prefs_counts_plays():
    from personalize import compute_prefs
    plays = [("A", NOW, "play", 0), ("A", NOW + 60, "play", 0), ("B", NOW + 120, "play", 0)]
    prefs = compute_prefs(plays, {}, {}, now=NOW + 120)
    assert prefs["play_counts"] == {"A": 2, "B": 1}


# ------------------------------------------------- (4b) novelty bonus + smart exploration

def test_novelty_bonus_prefers_unheard_on_ties():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = [None] * len(ids)
    # identical candidates score-wise except cand_like has been played many times
    prefs = {"track": {}, "artist": {}, "play_counts": {"cand_like": 6}}
    with_counts = dict(rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids,
                                 artist_by_index, prefs=prefs))
    without = dict(rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids,
                             artist_by_index))
    # the well-worn track lost (almost all of) its novelty bonus; the unheard one kept it
    assert with_counts["cand_like"] < without["cand_like"]
    assert with_counts["cand_hate"] == pytest.approx(without["cand_hate"])


class _FixedRng:
    """rng stub: random() returns a fixed value; choice takes the first element."""
    def __init__(self, r): self._r = r
    def random(self): return self._r
    def choice(self, seq): return seq[0]


def test_choose_next_exploits_by_default():
    from personalize import choose_next
    ranked = [("top", 1.0), ("unheard", 0.9)]
    assert choose_next(ranked, {"top": 3}, epsilon=0.15, rng=_FixedRng(0.99)) == "top"


def test_choose_next_explores_best_unheard():
    from personalize import choose_next
    ranked = [("top", 1.0), ("heard2", 0.95), ("unheard", 0.9)]
    counts = {"top": 3, "heard2": 1}
    assert choose_next(ranked, counts, epsilon=0.15, rng=_FixedRng(0.0)) == "unheard"


def test_choose_next_explore_falls_back_when_all_heard():
    from personalize import choose_next
    ranked = [("a", 1.0), ("b", 0.9)]
    counts = {"a": 2, "b": 5}
    assert choose_next(ranked, counts, epsilon=0.15, rng=_FixedRng(0.0)) == "a"
    assert choose_next([], counts) is None


def test_artist_pref_term_saturates():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = ["Mega" if v == "hated1" else "Other" for v in ids]
    # a binged channel accrues an unbounded artist score; the term must cap at
    # gamma_artist (0.3) so it can't out-shout the vibe ordering (the King Olly bug:
    # channel score +2.1 -> a flat +0.63, flipping a chill session into a boss battle)
    prefs = {"track": {}, "artist": {"Mega": 100.0}}
    ranked = rank_next("liked1", ["liked2", "hated1"], X, id2i, ids, artist_by_index,
                       prefs=prefs, explain=True)
    terms = {v: t for v, _s, t in ranked}
    assert terms["hated1"]["pref_artist"] == pytest.approx(0.3, rel=0.01)   # not 30.0
    # the clearly-better-vibe candidate wins despite the huge channel preference
    assert ranked[0][0] == "liked2"
    # small scores stay ~linear (tanh(x) ~ x)
    small = rank_next("liked1", ["hated1"], X, id2i, ids, artist_by_index,
                      prefs={"track": {}, "artist": {"Mega": 0.1}}, explain=True)
    assert small[0][2]["pref_artist"] == pytest.approx(0.3 * 0.1, rel=0.02)


def test_rank_explain_terms_sum_to_score():
    from personalize import build_centroid, rank_next
    X, id2i, ids = _emb()
    artist_by_index = ["Foo" if v == "cand_like" else "Bar" for v in ids]
    taste = build_centroid(X, id2i, {"liked1": 2.0, "liked2": 1.5, "hated1": -2.0})
    skip_vec = build_centroid(X, id2i, {"hated1": 1.0})
    prefs = {"track": {"cand_like": 0.4}, "artist": {"Foo": 0.3}, "play_counts": {"cand_like": 2}}
    plain = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                      prefs=prefs, taste_vec=taste, skip_vec=skip_vec,
                      recent_artists={"Foo"})
    exp = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                    prefs=prefs, taste_vec=taste, skip_vec=skip_vec,
                    recent_artists={"Foo"}, explain=True)
    # order + scores identical to the default shape; terms sum to the score
    assert [(v, s) for v, s, _t in exp] == plain
    for _v, s, t in exp:
        assert set(t) == TERM_KEYS
        assert sum(t.values()) == pytest.approx(s)
    top = dict((v, t) for v, _s, t in exp)["cand_like"]
    assert top["cooldown"] < 0 and top["skip"] <= 0     # penalties are signed negative


def test_choose_next_explained_reports_reason():
    from personalize import choose_next, choose_next_explained
    ranked = [("top", 1.0), ("heard2", 0.95), ("unheard", 0.9)]
    counts = {"top": 3, "heard2": 1}
    # exploit path
    vid, info = choose_next_explained(ranked, counts, epsilon=0.15, rng=_FixedRng(0.99))
    assert vid == "top" and info == {"explored": False, "reason": "exploit"}
    # explore path lands on the best unheard, and choose_next mirrors the vid
    vid, info = choose_next_explained(ranked, counts, epsilon=0.15, rng=_FixedRng(0.0))
    assert vid == "unheard" and info["explored"] and info["reason"] == "explore_unheard"
    assert choose_next(ranked, counts, epsilon=0.15, rng=_FixedRng(0.0)) == "unheard"
    # explain=True (vid, score, terms) rows also work through the explainer
    exp = [("top", 1.0, {}), ("unheard", 0.9, {})]
    assert choose_next_explained(exp, {"top": 2}, rng=_FixedRng(0.0))[0] == "unheard"


def test_rank_artist_cooldown_penalizes_recent():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = ["Foo" if v == "cand_like" else "Bar" for v in ids]
    base = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index)
    cooled = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                       recent_artists={"Foo"})
    # cand_like's score drops when its artist is on cooldown
    b = dict(base); c = dict(cooled)
    assert c["cand_like"] < b["cand_like"]


# ----------------------------------------- (5) neighborhood fatigue + session mood

def test_fatigue_penalizes_clones_of_recent_tracks():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = [None] * len(ids)
    # cand_like is a near-clone of recently-played liked1 (cos ~0.99, over the floor);
    # cand_hate is far from it (under the floor) -> only the clone loses score
    recent = X[[id2i["liked1"]]]
    base = dict(rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index))
    fat = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                    recent_vecs=recent, explain=True)
    scores = {v: s for v, s, _t in fat}
    terms = {v: t for v, _s, t in fat}
    assert terms["cand_like"]["fatigue"] < 0
    assert terms["cand_hate"]["fatigue"] == 0.0
    assert scores["cand_like"] < base["cand_like"]
    assert scores["cand_hate"] == pytest.approx(base["cand_hate"])


def test_fatigue_none_and_empty_recent_are_noops():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = [None] * len(ids)
    base = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index)
    empty = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                      recent_vecs=np.zeros((0, X.shape[1]), dtype=np.float32))
    assert empty == base


def test_session_mood_pulls_toward_session_centroid():
    from personalize import build_centroid, rank_next
    X, id2i, ids = _emb()
    artist_by_index = [None] * len(ids)
    # session so far lived near the liked axis -> cand_like gains, cand_hate doesn't
    session = build_centroid(X, id2i, {"liked1": 1.0, "liked2": 1.0})
    base = dict(rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index))
    mood = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                     session_vec=session, explain=True)
    terms = {v: t for v, _s, t in mood}
    assert terms["cand_like"]["mood"] > terms["cand_hate"]["mood"]
    scores = {v: s for v, s, _t in mood}
    assert scores["cand_like"] - base["cand_like"] > scores["cand_hate"] - base["cand_hate"]


# ------------- (6) opt-in terms: radio co-occurrence, already-heard recency, energy
# All three must be EXACTLY zero-contribution when their input is missing — the firmware
# goldens and every existing caller pass none of them.

def _rich(X, id2i, ids, artist_by_index):
    """The kwargs every already-shipped term needs, so no-op checks compare a fully
    loaded ranking against itself rather than a bare content-only one."""
    from personalize import build_centroid
    return dict(
        prefs={"track": {"cand_like": 0.4}, "artist": {"Foo": 0.3},
               "play_counts": {"cand_like": 2}},
        taste_vec=build_centroid(X, id2i, {"liked1": 2.0, "hated1": -2.0}),
        skip_vec=build_centroid(X, id2i, {"hated1": 1.0}),
        session_vec=build_centroid(X, id2i, {"liked1": 1.0, "liked2": 1.0}),
        recent_vecs=X[[id2i["liked1"]]], recent_artists={"Foo"})


def test_new_terms_absent_are_exact_noops():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = ["Foo" if v == "cand_like" else "Bar" for v in ids]
    kw = _rich(X, id2i, ids, artist_by_index)
    cands = ["cand_like", "cand_hate"]
    before = rank_next("cur", cands, X, id2i, ids, artist_by_index, **kw)
    # explicit empties/Nones must be bit-identical to omitting the arguments entirely
    after = rank_next("cur", cands, X, id2i, ids, artist_by_index,
                      cooc_members=None, last_played=None, now=None, energies=None, **kw)
    empties = rank_next("cur", cands, X, id2i, ids, artist_by_index,
                        cooc_members={}, last_played={}, now=NOW, energies={}, **kw)
    assert after == before and empties == before
    # a timestamp map with no `now` (and vice versa) can't age anything -> still a no-op
    half = rank_next("cur", cands, X, id2i, ids, artist_by_index,
                     last_played={"cand_like": NOW}, **kw)
    assert half == before
    exp = rank_next("cur", cands, X, id2i, ids, artist_by_index, explain=True, **kw)
    for _v, _s, t in exp:
        assert t["cooc"] == 0.0 and t["heard"] == 0.0 and t["energy"] == 0.0


def test_cooc_boost_is_symmetric():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = [None] * len(ids)
    cands = ["cand_like", "cand_hate"]
    base = dict(rank_next("cur", cands, X, id2i, ids, artist_by_index))
    # forward: the candidate sits in the CURRENT track's radio
    fwd = rank_next("cur", cands, X, id2i, ids, artist_by_index,
                    cooc_members={"cur": {"cand_hate"}}, explain=True)
    terms = {v: t for v, _s, t in fwd}
    scores = {v: s for v, s, _t in fwd}
    assert terms["cand_hate"]["cooc"] == pytest.approx(0.3)
    assert terms["cand_like"]["cooc"] == 0.0
    assert scores["cand_hate"] == pytest.approx(base["cand_hate"] + 0.3)
    assert scores["cand_like"] == pytest.approx(base["cand_like"])
    # reverse: the CURRENT track sits in the candidate's radio — same boost
    rev = rank_next("cur", cands, X, id2i, ids, artist_by_index,
                    cooc_members={"cand_hate": {"cur"}}, explain=True)
    assert {v: t["cooc"] for v, _s, t in rev} == {v: t["cooc"] for v, _s, t in fwd}
    # 0.3 is enough to flip the vibe ordering of these two candidates (that is the point)
    assert rev[0][0] == "cand_hate"


def test_heard_penalty_decays_with_halflife():
    from personalize import HEARD_MAX_AGE_SECONDS, rank_next
    X, id2i, ids = _emb()
    artist_by_index = [None] * len(ids)
    cands = ["cand_like", "cand_hate"]
    base = dict(rank_next("cur", cands, X, id2i, ids, artist_by_index))

    def terms(last):
        return {v: t for v, _s, t in rank_next(
            "cur", cands, X, id2i, ids, artist_by_index,
            last_played=last, now=NOW, explain=True)}

    just_now = terms({"cand_like": NOW})
    assert just_now["cand_like"]["heard"] == pytest.approx(-0.6)      # full heard_w
    assert just_now["cand_hate"]["heard"] == 0.0                      # never played
    day = terms({"cand_like": NOW - 24 * 3600})
    assert day["cand_like"]["heard"] == pytest.approx(-0.3)           # one halflife
    week = terms({"cand_like": NOW - 7 * 24 * 3600})
    assert week["cand_like"]["heard"] == pytest.approx(-0.6 * 0.5 ** 7)
    # beyond the cutoff the lookup is skipped outright, and the score returns to base
    old = rank_next("cur", cands, X, id2i, ids, artist_by_index,
                    last_played={"cand_like": NOW - HEARD_MAX_AGE_SECONDS - 1},
                    now=NOW, explain=True)
    assert {v: t["heard"] for v, _s, t in old} == {"cand_like": 0.0, "cand_hate": 0.0}
    assert dict((v, s) for v, s, _t in old) == base


def test_energy_continuity_band_then_linear():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = [None] * len(ids)
    cands = ["cand_like", "cand_hate"]

    def terms(energies):
        return {v: t for v, _s, t in rank_next(
            "cur", cands, X, id2i, ids, artist_by_index, energies=energies, explain=True)}

    # inside the 0.35 band (widened from 0.25: 0.25 fenced the walk into near-identical
    # loudness and starved the natural rise/fall of a set): free. Beyond it: 0.8 per unit.
    t = terms({"cur": 0.5, "cand_like": 0.7, "cand_hate": 0.95})
    assert t["cand_like"]["energy"] == 0.0
    assert t["cand_hate"]["energy"] == pytest.approx(-0.8 * (0.45 - 0.35))
    # symmetric in direction, and exactly at the band edge it is still free
    edge = terms({"cur": 0.5, "cand_like": 0.15, "cand_hate": 0.85})
    assert edge["cand_like"]["energy"] == 0.0 and edge["cand_hate"]["energy"] == 0.0
    # a gap that used to cost (0.30 > the old 0.25 band) is now inside the band
    assert terms({"cur": 0.5, "cand_hate": 0.8})["cand_hate"]["energy"] == 0.0
    # either side missing -> no penalty at all
    assert terms({"cand_like": 0.0, "cand_hate": 1.0})["cand_hate"]["energy"] == 0.0
    assert terms({"cur": 0.5})["cand_hate"]["energy"] == 0.0


def test_explain_sums_to_score_with_all_new_terms_active():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = ["Foo" if v == "cand_like" else "Bar" for v in ids]
    kw = _rich(X, id2i, ids, artist_by_index)
    cands = ["cand_like", "cand_hate"]
    new = dict(cooc_members={"cur": {"cand_like"}, "cand_hate": {"cur"}},
               last_played={"cand_like": NOW - 3600, "cand_hate": NOW - 5 * 86400},
               now=NOW, energies={"cur": 0.2, "cand_like": 0.9, "cand_hate": 0.3})
    plain = rank_next("cur", cands, X, id2i, ids, artist_by_index, **kw, **new)
    exp = rank_next("cur", cands, X, id2i, ids, artist_by_index, explain=True, **kw, **new)
    assert [(v, s) for v, s, _t in exp] == plain
    for _v, s, t in exp:
        assert set(t) == TERM_KEYS
        assert sum(t.values()) == pytest.approx(s)
    terms = {v: t for v, _s, t in exp}
    assert terms["cand_like"]["cooc"] > 0 and terms["cand_hate"]["cooc"] > 0
    assert terms["cand_like"]["heard"] < terms["cand_hate"]["heard"] < 0   # fresher = worse
    assert terms["cand_like"]["energy"] < 0 and terms["cand_hate"]["energy"] == 0.0


# ------------------------------------------------------------- (7) tempo continuity
# Opt-in like the three above: no `bpms`, no term, byte-identical scores.

def _bpm_terms(bpms):
    from personalize import rank_next
    X, id2i, ids = _emb()
    return {v: t for v, _s, t in rank_next(
        "cur", ["cand_like", "cand_hate"], X, id2i, ids, [None] * len(ids),
        bpms=bpms, explain=True)}


def test_bpm_octave_fold_treats_double_time_as_a_match():
    # 160 against 80 is the same pulse at double time -> free. 160 against 85 misses
    # double time by ~6%, just outside the free band -> a small penalty.
    t = _bpm_terms({"cur": 80.0, "cand_like": 160.0, "cand_hate": 40.0})
    assert t["cand_like"]["bpm"] == 0.0          # 2x
    assert t["cand_hate"]["bpm"] == 0.0          # 1/2x
    t = _bpm_terms({"cur": 85.0, "cand_like": 160.0, "cand_hate": 120.0})
    assert t["cand_like"]["bpm"] < 0
    assert t["cand_hate"]["bpm"] == pytest.approx(-0.25)   # 120 vs 85: far, saturated


def test_bpm_band_edges_and_saturation():
    import math
    from personalize import BPM_FREE_RATIO, BPM_FULL_RATIO
    # inside +-5%: free (120 vs 124 is a beat-match, not a tempo change)
    assert _bpm_terms({"cur": 120.0, "cand_like": 124.0})["cand_like"]["bpm"] == 0.0
    assert _bpm_terms({"cur": 120.0, "cand_like": 120.0 * BPM_FREE_RATIO}
                      )["cand_like"]["bpm"] == pytest.approx(0.0, abs=1e-9)
    # exactly at the far edge the penalty is full, and it stays full past it
    full = _bpm_terms({"cur": 120.0, "cand_like": 120.0 * BPM_FULL_RATIO,
                       "cand_hate": 200.0})
    assert full["cand_like"]["bpm"] == pytest.approx(-0.25)
    assert full["cand_hate"]["bpm"] == pytest.approx(-0.25)
    # halfway across the ramp -> half the penalty
    mid = math.sqrt(BPM_FREE_RATIO * BPM_FULL_RATIO)      # log-midpoint
    assert _bpm_terms({"cur": 120.0, "cand_like": 120.0 * mid}
                      )["cand_like"]["bpm"] == pytest.approx(-0.125, rel=1e-3)


def test_sameness_hill_is_flat_below_the_floor_then_linear():
    import math
    from personalize import rank_next
    # candidates at exact known cosines to `cur` (2-D unit circle: cos == the x-component)
    cos = {"cur": 1.0, "clone": 1.0, "near": 0.95, "far": 0.85}
    ids = list(cos)
    X = np.array([[c, math.sqrt(1.0 - c * c)] for c in cos.values()], dtype=np.float32)
    id2i = {v: i for i, v in enumerate(ids)}
    cands = ["clone", "near", "far"]

    def terms(**params):
        return {v: t for v, _s, t in rank_next(
            "cur", cands, X, id2i, ids, [None] * len(ids), params=params, explain=True)}

    t = terms(same_w=1.5)                                     # default floor 0.92
    assert t["far"]["sameness"] == 0.0                        # 0.85: below the floor, free
    assert t["near"]["sameness"] == pytest.approx(-1.5 * (0.95 - 0.92), abs=1e-6)
    assert t["clone"]["sameness"] == pytest.approx(-1.5 * (1.00 - 0.92), abs=1e-6)
    # the weight scales the hill; the floor moves where it starts to bite
    assert terms(same_w=3.0)["clone"]["sameness"] == pytest.approx(
        2 * t["clone"]["sameness"], abs=1e-6)
    assert terms(same_w=1.5, same_floor=0.80)["far"]["sameness"] == pytest.approx(
        -1.5 * (0.85 - 0.80), abs=1e-6)
    # exactly AT the floor is still free (the hill starts at it, it is not a cliff)
    assert terms(same_w=1.5, same_floor=0.95)["near"]["sameness"] == pytest.approx(0.0, abs=1e-6)
    # the point of the term: a near-copy of the track playing stops being the automatic
    # pick, while the merely-similar one still wins over the distant one.
    off = [v for v, _s, _t in rank_next("cur", cands, X, id2i, ids, [None] * len(ids),
                                        explain=True)]
    on = [v for v, _s, _t in rank_next("cur", cands, X, id2i, ids, [None] * len(ids),
                                       params={"same_w": 1.5}, explain=True)]
    assert off == ["clone", "near", "far"] and on == ["near", "clone", "far"]


def test_sameness_at_the_default_weight_is_an_exact_noop():
    """same_w defaults to 0.0, so every existing caller (and firmware/tools/gen_goldens.py,
    which passes no params at all) scores exactly as it did before the term landed."""
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = ["Foo" if v == "cand_like" else "Bar" for v in ids]
    kw = _rich(X, id2i, ids, artist_by_index)
    new = dict(cooc_members={"cur": {"cand_like"}}, last_played={"cand_like": NOW - 3600},
               now=NOW, energies={"cur": 0.2, "cand_like": 0.9},
               bpms={"cur": 120.0, "cand_like": 160.0})
    before = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                       **kw, **new)
    # bit-identical (==, not approx) with no params, an empty override, and an explicit 0
    for params in (None, {}, {"same_w": 0.0}, {"same_floor": 0.5}):
        assert rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                         params=params, **kw, **new) == before
    exp = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                    explain=True, **kw, **new)
    assert all(t["sameness"] == 0.0 for _v, _s, t in exp)     # present, contributing zero
    # …and turning it on with a floor under the candidates' similarity does change them
    hot = rank_next("cur", ["cand_like", "cand_hate"], X, id2i, ids, artist_by_index,
                    params={"same_w": 1.5, "same_floor": 0.5}, **kw, **new)
    assert dict(hot)["cand_like"] < dict(before)["cand_like"]


def test_bpm_absent_or_unusable_is_an_exact_noop():
    from personalize import rank_next
    X, id2i, ids = _emb()
    artist_by_index = ["Foo" if v == "cand_like" else "Bar" for v in ids]
    kw = _rich(X, id2i, ids, artist_by_index)
    cands = ["cand_like", "cand_hate"]
    before = rank_next("cur", cands, X, id2i, ids, artist_by_index, **kw)
    for bpms in (None, {}, {"cand_like": 200.0},          # current track has no tempo
                 {"cur": 120.0},                          # no candidate has one
                 {"cur": 0.0, "cand_like": 200.0},        # unusable tempo (analysis miss)
                 {"cur": 120.0, "cand_like": 0.0, "cand_hate": -1.0}):
        assert rank_next("cur", cands, X, id2i, ids, artist_by_index,
                         bpms=bpms, **kw) == before
    exp = rank_next("cur", cands, X, id2i, ids, artist_by_index, explain=True, **kw)
    assert all(t["bpm"] == 0.0 for _v, _s, t in exp)      # key present, contributing zero


# ------------------------------------- (8) opt-in preference refinements (compute_prefs)

def _past_early(ts):
    """Three throwaway plays so the event under test is past EARLY_SESSION_TRACKS — the
    early-session halving would otherwise scale every negative in these tests."""
    return [(v, ts - 30 + i, "play", 90.0) for i, v in enumerate(("w1", "w2", "w3"))]


def test_compute_prefs_refinements_absent_are_exact_noops():
    from personalize import compute_prefs
    dur = {"A": 200.0, "B": 200.0, "C": 200.0}
    plays = _past_early(NOW) + [
        ("A", NOW - 10 * 86400, "skip", 4),        # early skip, 10 days ago
        ("B", NOW - 10 * 86400, "complete", 200),
        ("C", NOW - 40 * 86400, "dislike", None),
    ]
    base = compute_prefs(plays, dur, {"A": "Ar"}, now=NOW)
    same = compute_prefs(plays, dur, {"A": "Ar"}, now=NOW,
                         neg_halflife_days=None, strong_early_skip=False)
    assert same == base


def test_neg_halflife_ages_the_negatives_faster():
    from personalize import compute_prefs
    dur = {"A": 100.0, "B": 100.0}
    ts = NOW - 30 * 86400                          # exactly one positive half-life ago
    plays = _past_early(ts) + [("A", ts, "complete", 100), ("B", ts, "dislike", None)]
    base = compute_prefs(plays, dur, {}, now=NOW)
    fast = compute_prefs(plays, dur, {}, now=NOW, neg_halflife_days=14.0)
    # positives are untouched: what you loved stays loved
    assert fast["track"]["A"] == base["track"]["A"] == pytest.approx(0.5)
    # the negative has decayed further towards zero (less negative)
    assert base["track"]["B"] == pytest.approx(-3.0 * 0.5)
    assert fast["track"]["B"] == pytest.approx(-3.0 * 0.5 ** (30 / 14))
    assert fast["track"]["B"] > base["track"]["B"]
    # a fresh negative is not softened at all — only an aging one
    fresh = _past_early(NOW) + [("B", NOW, "dislike", None)]
    assert compute_prefs(fresh, dur, {}, now=NOW, neg_halflife_days=14.0)["track"]["B"] \
        == pytest.approx(compute_prefs(fresh, dur, {}, now=NOW)["track"]["B"])


def test_strong_early_skip_grades_the_skip_cliff():
    from personalize import EARLY_SKIP_FACTOR, compute_prefs

    def w(seconds, duration, strong):
        plays = _past_early(NOW) + [("A", NOW, "skip", seconds)]
        return compute_prefs(plays, {"A": duration}, {}, now=NOW,
                             strong_early_skip=strong)["track"]["A"]

    # trigger 1: under 5% of the track (12s of a 5-minute track)
    assert w(12, 300.0, False) == pytest.approx(-1.0)
    assert w(12, 300.0, True) == pytest.approx(-1.5)
    # trigger 2: under 10 seconds, whatever the fraction (9s of a 100s track = 9%)
    assert w(9, 100.0, True) == pytest.approx(-1.5)
    assert w(9, 100.0, False) == pytest.approx(-1.0)
    # just above BOTH triggers: 12% and 12 seconds is a real listen -> the flat -1.0
    assert w(12, 100.0, True) == pytest.approx(-1.0)
    # a late skip is still not a negative at all, flag or no flag
    assert w(190, 200.0, True) > 0
    # stacks multiplicatively with the early-session halving (mood-hunting still softens)
    early = compute_prefs([("A", NOW, "skip", 2)], {"A": 300.0}, {}, now=NOW,
                          strong_early_skip=True)["track"]["A"]
    assert early == pytest.approx(-1.5 * EARLY_SKIP_FACTOR)


# ------------------------------------------- (9) clustered Thompson-sampling exploration

def _ts_setup():
    """Two clusters interleaved in the ranking: B owns the top rank, A owns the history.
    All four candidates are unheard, so only the arm choice decides the pick."""
    ranked = [("b1", 1.0), ("a1", 0.9), ("b2", 0.8), ("a2", 0.7)]
    clusters = {"b1": "B", "a1": "A", "b2": "B", "a2": "A"}
    stats = {"A": (50, 0), "B": (0, 50)}     # A always lands, B always gets skipped
    return ranked, clusters, stats


def test_cluster_thompson_explores_the_winning_arm():
    import random
    from personalize import choose_next_explained
    ranked, clusters, stats = _ts_setup()
    for seed in range(10):
        vid, info = choose_next_explained(
            ranked, {}, epsilon=1.0, rng=random.Random(seed),
            clusters=clusters, cluster_stats=stats)
        # the posteriors are far enough apart that A wins from any seed; the pick is
        # A's BEST-RANKED unheard track, not the overall rank-1 (which belongs to B)
        assert (vid, info) == ("a1", {"explored": True, "reason": "explore_cluster"})
    # a seeded rng is reproducible, and choose_next mirrors the explained pick
    from personalize import choose_next
    assert choose_next(ranked, {}, epsilon=1.0, rng=random.Random(3),
                       clusters=clusters, cluster_stats=stats) == "a1"


def test_cluster_thompson_falls_through_when_the_arm_has_nothing_unheard():
    import random
    from personalize import choose_next_explained
    ranked, clusters, stats = _ts_setup()
    counts = {"a1": 3, "a2": 1}          # the winning cluster is fully explored already
    vid, info = choose_next_explained(ranked, counts, epsilon=1.0, rng=random.Random(0),
                                      clusters=clusters, cluster_stats=stats)
    assert (vid, info) == ("b1", {"explored": True, "reason": "explore_unheard"})
    # nothing unheard anywhere -> the legacy random-from-the-top-4 tail still runs
    vid, info = choose_next_explained(ranked, {"a1": 1, "a2": 1, "b1": 1, "b2": 1},
                                      epsilon=1.0, rng=random.Random(0),
                                      clusters=clusters, cluster_stats=stats)
    assert info["reason"] == "explore_random" and vid in {"b1", "a1", "b2", "a2"}
    # an unranked/uncovered cluster map (no candidate has a cluster) also falls through
    vid, info = choose_next_explained(ranked, {}, epsilon=1.0, rng=random.Random(0),
                                      clusters={"zzz": "Z"}, cluster_stats=stats)
    assert (vid, info["reason"]) == ("b1", "explore_unheard")


def test_cluster_thompson_absent_is_an_exact_noop():
    import random
    from personalize import choose_next_explained
    ranked = [("top", 1.0), ("heard2", 0.95), ("unheard", 0.9)]
    counts = {"top": 3, "heard2": 1}
    for seed in range(25):
        legacy = choose_next_explained(ranked, counts, epsilon=0.5, rng=random.Random(seed))
        # explicit Nones, and each half on its own, must all be the identical decision —
        # including leaving the rng stream untouched (no Beta draws taken)
        for kw in ({"clusters": None, "cluster_stats": None},
                   {"clusters": {"top": "A", "unheard": "B"}},
                   {"cluster_stats": {"A": (1, 1)}}):
            assert choose_next_explained(ranked, counts, epsilon=0.5,
                                         rng=random.Random(seed), **kw) == legacy


def test_cluster_thompson_favours_the_arm_with_the_better_record():
    """Statistical, not deterministic: an arm with 20 accepts and no skips must win the
    draw far more often than one with 20 skips and no accepts."""
    import random
    from personalize import choose_next_explained
    ranked, clusters, _ = _ts_setup()
    stats = {"A": (8, 2), "B": (2, 8)}
    rng = random.Random(1234)
    picks = [choose_next_explained(ranked, {}, epsilon=1.0, rng=rng,
                                   clusters=clusters, cluster_stats=stats)[0]
             for _ in range(300)]
    assert picks.count("a1") > picks.count("b1") * 2
    # with NO history at all both arms hold a flat prior -> both get real turns
    rng = random.Random(1234)
    even = [choose_next_explained(ranked, {}, epsilon=1.0, rng=rng, clusters=clusters,
                                  cluster_stats={})[0] for _ in range(300)]
    assert 90 < even.count("a1") < 210
