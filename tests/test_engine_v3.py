"""Engine v3 (2026-10 audit): like/unlike as state, browsing vs verdict skips, capped
track preference, channel accept-rate, session rejections, density-independent
("window") weights, centered embeddings, listening-history taste, the skip-anchored
/api/next, and the cumulative Takeout merge.

Run: .venv\\Scripts\\python -m pytest -q tests/test_engine_v3.py
"""
import json
import sqlite3
import sys

import numpy as np
import pytest

sys.path.insert(0, "scripts")

import personalize as P  # noqa: E402
from test_server_api import _insert_plays, _last_trace, _stub_emb_sim, srv  # noqa: E402,F401

NOW = 1_700_000_000.0
DAY = 86400.0


def prefs(rows, **kw):
    return P.compute_prefs(rows, {"a": 200.0, "b": 200.0}, {"a": "X", "b": "Y"}, now=NOW, **kw)


# ------------------------------------------------------------------ like / unlike state

def test_mis_tapped_like_undone_leaves_nothing():
    rows = [("a", NOW - 10, "like", 0), ("a", NOW - 5, "unlike", 0)]
    assert prefs(rows)["track"]["a"] == pytest.approx(1.5, rel=1e-3)   # the old sum: residue
    assert prefs(rows, explicit_state=True)["track"].get("a", 0.0) == 0.0


def test_unliking_an_old_like_is_not_a_dislike():
    rows = [("a", NOW - 90 * DAY, "like", 0), ("a", NOW, "unlike", 0)]
    old = prefs(rows)
    assert old["track"]["a"] < 0 and "a" in old["skip_ids"]       # the bug
    new = prefs(rows, explicit_state=True)
    assert new["track"].get("a", 0.0) == 0.0 and "a" not in new["skip_ids"]


def test_standing_like_counts_once_and_relike_restores_it():
    twice = [("a", NOW - 2, "like", 0), ("a", NOW - 1, "like", 0)]
    assert prefs(twice, explicit_state=True)["track"]["a"] == pytest.approx(3.0, rel=1e-4)
    back = [("a", NOW - 3, "like", 0), ("a", NOW - 2, "unlike", 0), ("a", NOW - 1, "like", 0)]
    assert prefs(back, explicit_state=True)["track"]["a"] == pytest.approx(3.0, rel=1e-4)


def test_explicit_dislike_is_not_softened_as_early_session_mood():
    rows = [("a", NOW, "dislike", 0)]                  # first track of a session
    assert prefs(rows)["track"]["a"] == pytest.approx(-1.5)
    assert prefs(rows, explicit_state=True)["track"]["a"] == pytest.approx(-3.0)


# ------------------------------------------------------------------ browsing vs verdict

def test_legacy_sub_three_second_skips_are_browsing():
    warm = [(v, NOW - 100 + i, "play", None) for i, v in enumerate("wxyz")]
    rows = warm + [("a", NOW, "skip", 1.0)]                       # legacy: no source
    assert "a" in prefs(rows)["skip_ids"]
    assert "a" not in prefs(rows, browse_seconds=P.BROWSE_SECONDS)["skip_ids"]
    # the same quick skip from the current client carries a source: a real verdict
    tagged = warm + [("a", NOW, "skip", 1.0, "autoplay")]
    assert "a" in prefs(tagged, browse_seconds=P.BROWSE_SECONDS)["skip_ids"]


def test_switch_is_navigation_not_a_signal():
    assert P.event_weight("switch", 0.01) == 0.0
    p = prefs([("a", NOW, "switch", 2.0, "search")], browse_seconds=3.0)
    assert p["track"] == {} and p["skip_ids"] == set()


def test_five_field_rows_keep_the_default_arithmetic():
    four = [("a", NOW - 50, "play", None), ("a", NOW - 10, "complete", 180.0)]
    five = [r + ("library",) for r in four]
    assert prefs(four) == prefs(five)


# ------------------------------------------------------------------ prefs in the ranker

def _space():
    ids = ["cur", "c1", "c2", "c3"]
    X = np.array([[1, 0, 0], [0.95, 0.31, 0], [0.9, 0, 0.44], [0.2, 0.98, 0]], dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    return X, ids, {v: i for i, v in enumerate(ids)}


def test_track_preference_can_be_capped():
    X, ids, id2i = _space()
    pr = {"track": {"c3": 3.0}, "artist": {}}
    raw = P.rank_next("cur", ["c1", "c3"], X, id2i, ids, None, prefs=pr, explain=True)
    cap = P.rank_next("cur", ["c1", "c3"], X, id2i, ids, None, prefs=pr, explain=True,
                      params={"track_tanh": 1})
    t_raw = {v: t for v, _, t in raw}["c3"]["pref_track"]
    t_cap = {v: t for v, _, t in cap}["c3"]["pref_track"]
    assert t_raw == pytest.approx(1.5) and t_cap == pytest.approx(0.5 * np.tanh(3.0))


def test_channel_scored_by_accept_rate_not_volume():
    rows = [("a", NOW - i, "complete", 200.0) for i in range(30)]       # 30 finishes
    rows += [("a", NOW - 100 - i, "skip", 20.0) for i in range(30)]      # 30 early skips
    rows += [("b", NOW - 200, "complete", 200.0)]                        # one finish
    p = prefs(rows, explicit_state=True)
    assert p["artist_mass"]["X"] == pytest.approx(60, rel=0.01)
    X, ids, id2i = _space()
    abi = ["", "X", "Y", ""]
    pr = {**p, "track": {}}
    rate = {v: t["pref_artist"] for v, _, t in P.rank_next(
        "cur", ["c1", "c2"], X, id2i, ids, abi, prefs=pr, explain=True,
        params={"artist_prior": 3.0})}
    # summed, the heavy-but-skipped channel X saturates ABOVE the one-finish channel Y;
    # as a rate it does not
    summed = {v: t["pref_artist"] for v, _, t in P.rank_next(
        "cur", ["c1", "c2"], X, id2i, ids, abi, prefs=pr, explain=True)}
    assert summed["c1"] > summed["c2"]
    assert rate["c1"] < rate["c2"]


def test_session_skip_vector_steers_away_and_is_absent_by_default():
    X, ids, id2i = _space()
    plain = P.rank_next("cur", ["c1", "c2"], X, id2i, ids, None, explain=True)
    assert "sskip" not in plain[0][2]
    rej = X[1]                                     # c1's direction was just rejected
    out = P.rank_next("cur", ["c1", "c2"], X, id2i, ids, None, explain=True,
                      session_skip_vec=rej, params={"kappa": 1.0})
    terms = {v: t for v, _, t in out}
    assert terms["c1"]["sskip"] < terms["c2"]["sskip"] <= 0.0


# ------------------------------------------------------------------ window scaling

def _cloud(n=200, spread=0.3, seed=0):
    rng = np.random.default_rng(seed)
    X = np.zeros((n, 8), dtype=np.float32)
    X[:, 0] = 1.0
    X[:, 1:] = rng.normal(0, spread, (n, 7))
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    ids = [f"t{i}" for i in range(n)]
    return X, ids, {v: i for i, v in enumerate(ids)}


def test_window_scale_expresses_flat_terms_in_vibe_spreads():
    X, ids, id2i = _cloud()
    cand = ids[1:]
    u = float(np.std(X[1:] @ X[0]))
    abi = ["A"] * 2 + [""] * (len(ids) - 2)
    out = P.rank_next("t0", cand, X, id2i, ids, abi, recent_artists={"A"}, explain=True,
                      params={"scale": "window", "cooldown": 3.0})
    cd = {v: t["cooldown"] for v, _, t in out}
    assert cd["t1"] == pytest.approx(-3.0 * u, rel=1e-4)


def test_window_scale_gives_a_centroid_term_exactly_its_weight_of_say():
    X, ids, id2i = _cloud(seed=1)
    cand = ids[1:]
    taste = X[5] + 0.3 * X[9]
    taste /= np.linalg.norm(taste)
    out = P.rank_next("t0", cand, X, id2i, ids, None, taste_vec=taste, explain=True,
                      params={"scale": "window", "delta": 0.35})
    T = np.array([[t["vibe"], t["taste"]] for _, _, t in out])
    assert T[:, 1].std() == pytest.approx(0.35 * T[:, 0].std(), rel=1e-3)


def test_window_scale_is_density_independent():
    """One neighbourhood at two densities: candidate A sounds most like the current track
    but is off-tempo, B is next-closest and on-tempo. Packed 10x tighter, every vibe gap
    shrinks 10x. Absolute weights flip the pick (the fixed tempo cost out-votes the now
    tiny vibe gap — the v2 failure); window weights shrink with the gaps and do not."""
    def pick(k, params):
        steps = [0.0, 1.0, 1.5, 2.0, 2.5]              # vibe rank of each candidate
        cos = [0.9 - k * s for s in steps]
        n = len(cos)
        X = np.zeros((n + 1, n + 1), dtype=np.float32)
        X[0, 0] = 1.0
        for i, c in enumerate(cos):
            X[i + 1, 0], X[i + 1, i + 1] = c, np.sqrt(1 - c * c)
        ids = ["cur"] + [f"c{i}" for i in range(n)]
        bpms = {v: 120.0 for v in ids}
        bpms["c0"] = 150.0                             # A: best vibe, wrong tempo
        return P.rank_next("cur", ids[1:], X, {v: i for i, v in enumerate(ids)}, ids, None,
                           bpms=bpms, params=params)[0][0]
    absolute = {"bpm_w": 0.25}
    assert pick(0.35, absolute) == "c0" and pick(0.035, absolute) == "c1"
    window = {"scale": "window", "bpm_w": 0.7}
    assert pick(0.35, window) == pick(0.035, window)


def test_window_scale_never_applies_flat_weights_raw():
    X, ids, id2i = _space()
    out = P.rank_next("cur", ["c1"], X, id2i, ids, ["", "A", "", ""], recent_artists={"A"},
                      explain=True, params={"scale": "window", "cooldown": 3.0})
    assert out[0][2]["cooldown"] == pytest.approx(-3.0 * P.WINDOW_U_DEFAULT)


# ------------------------------------------------------------------ centering / history

def test_center_embeddings_removes_the_shared_direction_in_place():
    rng = np.random.default_rng(0)
    X = (rng.normal(0, 1, (500, 16)) + 3.0).astype(np.float16)    # strongly anisotropic
    X /= np.linalg.norm(X.astype(np.float32), axis=1, keepdims=True).astype(np.float16)
    before = float(np.mean(X[:250].astype(np.float32) @ X[250:].astype(np.float32).T))
    Y, mean = P.center_embeddings(X, chunk=64)
    assert Y is X and Y.dtype == np.float16
    after = float(np.mean(Y[:250].astype(np.float32) @ Y[250:].astype(np.float32).T))
    assert before > 0.8 and abs(after) < 0.05
    assert np.allclose(np.linalg.norm(Y.astype(np.float32), axis=1), 1.0, atol=2e-3)


def test_history_weights_log_plays_and_age():
    rows = [{"video_id": "a", "play_count": "20", "last_played": "2023-11-14"},
            {"video_id": "b", "play_count": "1", "last_played": "2023-11-14"},
            {"video_id": "c", "play_count": "20", "last_played": "2022-11-14"},
            {"video_id": "d", "play_count": "0", "last_played": "2023-11-14"}]
    w = P.history_weights(rows, NOW)
    assert w["a"] > w["c"] > 0 and w["a"] > w["b"] > 0 and "d" not in w
    assert w["a"] / w["b"] == pytest.approx(np.log1p(20) / np.log1p(1), rel=1e-6)
    assert w["c"] == pytest.approx(w["a"] / 2, rel=0.01)           # one half-life older


# ------------------------------------------------------------------ exploration cost

def _explore_list():
    """Four unheard candidates. Cluster A's only one ranks 3rd on total score but sounds
    nothing like the others; A also holds the far better record, so an unbounded
    Thompson draw goes there every time."""
    def e(vid, score, vibe):
        return (vid, score, {"vibe": vibe, "mood": 0.0, "fatigue": 0.0, "sameness": 0.0,
                             "taste": score - vibe})
    ranked = [e("b1", 1.00, 0.90), e("b2", 0.98, 0.88), e("a1", 0.97, 0.40),
              e("b3", 0.96, 0.86)]
    return ranked, {"b1": "B", "b2": "B", "a1": "A", "b3": "B"}, {"A": (50, 0), "B": (0, 50)}


def test_explore_pick_stays_within_the_sound_budget():
    import random
    ranked, clusters, stats = _explore_list()
    for seed in range(10):
        kw = dict(epsilon=1.0, clusters=clusters, cluster_stats=stats)
        free = P.choose_next_explained(ranked, {}, rng=random.Random(seed), **kw)
        assert free == ("a1", {"explored": True, "reason": "explore_cluster"})
        assert P.choose_next_explained(ranked, {}, rng=random.Random(seed), sound_budget=None,
                                       prior_n=None, **kw) == free       # explicit off == legacy
        # a1 gives up ~2.4 sd of sound; with a 0.5 sd budget A is not on offer at all
        assert P.choose_next_explained(ranked, {}, rng=random.Random(seed), sound_budget=0.5,
                                       **kw) == ("b1", {"explored": True, "reason": "explore_cluster"})
    # the flat unheard chain is bounded the same way
    heard = {"b1": 1, "b2": 1}
    assert P.choose_next_explained(ranked, heard, epsilon=1.0, rng=random.Random(0))[0] == "a1"
    assert P.choose_next_explained(ranked, heard, epsilon=1.0, rng=random.Random(0),
                                   sound_budget=0.5) == ("b3", {"explored": True,
                                                                "reason": "explore_unheard"})
    # without a per-term breakdown there is nothing to measure: the budget is a no-op
    bare = [(v, s) for v, s, _ in ranked]
    assert P.choose_next_explained(bare, heard, epsilon=1.0, rng=random.Random(0),
                                   sound_budget=0.5)[0] == "a1"


def test_pooled_prior_stops_a_two_play_cluster_outbidding_the_main_one():
    """The live numbers: a cluster with 2 accepts out of 2 against one with 9 out of 21,
    in a log whose pooled accept rate is about a third."""
    import random
    ranked = [("main", 1.0), ("thin", 0.9)]
    clusters = {"main": "M", "thin": "T"}
    stats = {"M": (9, 12), "T": (2, 0), "rest": (11, 31)}

    def thin_share(prior_n):
        rng = random.Random(5)
        return sum(P.choose_next_explained(ranked, {}, epsilon=1.0, rng=rng, clusters=clusters,
                                           cluster_stats=stats, prior_n=prior_n)[0] == "thin"
                   for _ in range(4000)) / 4000

    uniform, pooled = thin_share(None), thin_share(10.0)
    assert uniform > 0.8            # Beta(3,1) vs Beta(10,13): the 2-play arm nearly always wins
    assert pooled < 0.7             # shrunk toward ~0.34 it is a coin flip with a lean, not a lock
    assert P._pooled_prior({}, 10.0) == (5.0, 5.0)         # no history: centred on 0.5
    assert P._pooled_prior(stats, None) == (1.0, 1.0)


# ------------------------------------------------------------------ server wiring

@pytest.fixture
def v3srv(srv):  # noqa: F811
    srv._EMB = _stub_emb_sim()
    srv._COOC = {}
    srv._CLUSTERS = {}
    return srv


def test_an_early_skip_moves_the_walk_off_the_skipped_track(v3srv):
    client = v3srv.app.test_client()
    r = client.get("/api/next?id=bbb&exclude=aaa,bbb&outcome=skip&secs=2")
    assert r.status_code == 200
    t = _last_trace(v3srv)
    assert t["anchor"] == "aaa" and t["rejected"] == ["bbb"]
    # a finish (or a late skip) continues from the track itself, as before
    client.get("/api/next?id=bbb&exclude=aaa,bbb&outcome=complete&secs=101")
    assert _last_trace(v3srv)["anchor"] is None
    client.get("/api/next?id=bbb&exclude=aaa,bbb&outcome=skip&secs=90")
    assert _last_trace(v3srv)["anchor"] is None


def test_dislike_stays_rejected_through_the_skip_that_follows_it(v3srv):
    import time
    now = time.time()
    _insert_plays(v3srv, [("aaa", now - 20, "dislike", 60.0, "autoplay", "s"),
                          ("aaa", now - 19, "skip", 60.0, "autoplay", "s"),
                          ("bbb", now - 10, "skip", 5.0, "autoplay", "s"),
                          ("bbb", now - 5, "complete", 101.0, "autoplay", "s")])
    with v3srv.app.app_context():
        assert v3srv.session_rejects(["aaa", "bbb", "ccc"], now=now) == {"aaa"}


def test_listening_history_feeds_taste_and_counts_as_heard(v3srv, tmp_path):
    v3srv.SEEDS_CSV.write_text(
        "video_id,title,artist,play_count,first_played,last_played,days_since_last,source,score,url\n"
        "ccc,Green Hill,Nakamura,12,2026-01-01,2026-10-01,3,music,11.9,u\n", encoding="utf-8-sig")
    with v3srv.app.app_context():
        p, taste, _skip = v3srv.personalization()
    assert p["play_counts"]["ccc"] == 12 and p["app_play_counts"] == {}
    X = v3srv._EMB["X"]
    assert float(X[2] @ taste) == pytest.approx(1.0, abs=1e-5)       # all history -> ccc


def test_next_decision_explores_within_the_server_budget(v3srv, monkeypatch):
    seen = {}
    real = P.choose_next_explained

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(v3srv.personalize, "choose_next_explained", spy)
    assert v3srv.app.test_client().get("/api/next?id=aaa&exclude=aaa").status_code == 200
    assert seen["sound_budget"] == v3srv.EXPLORE["sound_budget"] == 0.5
    assert seen["prior_n"] == v3srv.EXPLORE["prior_n"] == 10.0


def test_track_radio_avoids_what_the_queue_holds(v3srv):
    client = v3srv.app.test_client()
    r = client.get("/api/radio?kind=track&name=aaa&exclude=bbb")
    assert "bbb" not in [t["id"] for t in r.json]


# ------------------------------------------------------------------ takeout merge

def _export(path, events):
    path.write_text(json.dumps([
        {"header": "YouTube Music", "title": f"Listened to {t}",
         "titleUrl": f"https://music.youtube.com/watch?v={vid}",
         "subtitles": [{"name": "Artist - Topic"}], "time": ts} for vid, t, ts in events]),
        encoding="utf-8")


def test_merge_takeout_dedupes_overlap_and_keeps_old_history(tmp_path, monkeypatch):
    import merge_takeout as M
    data = tmp_path / "data"
    (data / "takeout").mkdir(parents=True)
    monkeypatch.setattr(M, "DATA", data)
    monkeypatch.setattr(M, "EXPORTS", data / "takeout" / "exports")
    monkeypatch.setattr(M, "SEEDS", data / "seed_tracks.csv")
    monkeypatch.setattr(M, "STRONG", data / "strong_seeds.csv")
    monkeypatch.setattr(M, "MISSING", data / "takeout_missing.csv")
    monkeypatch.setattr(M, "ROOT", tmp_path)
    con = sqlite3.connect(data / "library.db")
    con.execute("CREATE TABLE tracks(video_id TEXT)")
    con.execute("INSERT INTO tracks VALUES('own')")
    con.commit()
    con.close()
    (data / "seed_tracks.csv").write_text(
        "video_id,title,artist,play_count,first_played,last_played,days_since_last,source,score,url\n"
        "ancient,Old,A,5,2024-01-01,2024-02-01,600,music,1.0,u\n", encoding="utf-8-sig")
    june, octo = tmp_path / "june.json", tmp_path / "oct.json"
    _export(june, [("own", "Own", "2026-06-01T10:00:00Z"), ("x", "X", "2026-06-02T10:00:00Z")])
    _export(octo, [("x", "X", "2026-06-02T10:00:00Z"),               # overlap: same listen
                   ("x", "X", "2026-09-02T10:00:00Z"), ("new", "N", "2026-10-01T10:00:00Z")])
    assert M.main([str(june), str(octo)]) == 0
    rows = {r["video_id"]: r for r in M.read_csv(data / "seed_tracks.csv")}
    assert int(rows["x"]["play_count"]) == 2                          # not 3
    assert "ancient" in rows                                          # carried over
    missing = {r["video_id"] for r in M.read_csv(data / "takeout_missing.csv")}
    assert missing == {"x", "new", "ancient"}                         # 'own' is in the library
    assert M.main([str(octo)]) == 0                                   # re-import: idempotent
    assert len(list((data / "takeout" / "exports").glob("*"))) == 2
