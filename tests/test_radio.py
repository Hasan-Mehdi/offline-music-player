"""Seed-anchored radio (player_server/radio.py) and the play-together model it ranks
with (player_server/collab.py).

Run: .venv\\Scripts\\python -m pytest -q tests/test_radio.py
"""
import itertools
import sys

import numpy as np

sys.path.insert(0, "scripts")

from player_server import collab as CB  # noqa: E402
from player_server import radio as RD  # noqa: E402


def _ctx(baskets, n=12, dim=8, artist=None, fam=None, own=None, model=None, seed=0):
    rng = np.random.default_rng(seed)
    ids = [f"t{i}" for i in range(n)]
    X = rng.normal(size=(n, dim)).astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    C = CB.Collab(baskets, keep=ids, svd_dim=0)
    return RD.Context(collab=C, X=X, id2i={v: i for i, v in enumerate(ids)}, ids=ids,
                      lib=set(ids), artist=artist or {}, fam=fam or {}, own=own or {},
                      model=model or RD.DEFAULT_MODEL)


ONLY_COLLAB = {"weights": {f: (1.0 if f == "collab" else 0.0) for f in RD.FEATURES},
               "mean": {f: 0.0 for f in RD.FEATURES}, "std": {f: 1.0 for f in RD.FEATURES}}


def test_sittings_split_on_gaps_and_collapse_repeats():
    ev = [(0, "a"), (60, "a"), (120, "b"), (5000, "c"), (5060, "d"), (9999, "e")]
    assert CB.sittings(ev) == [["a", "b"], ["c", "d"]]
    assert CB.sittings(ev, before=5000) == [["a", "b"]]


def test_chunks_overlap_and_cover():
    seq = list(range(20))
    ch = CB.chunks(seq, size=8, stride=4)
    assert ch[0] == list(range(8)) and ch[1][0] == 4
    assert {x for c in ch for x in c} == set(seq)
    assert CB.chunks([1, 2, 3]) == [[1, 2, 3]]


def test_baskets_hold_out_seed_radios():
    radios = [("s1", ["a", "b"]), ("s2", ["c"])]
    b = CB.baskets(radios, playlists=[["a", "c"]], skip_seeds={"s1"})
    assert ("radio", ["s1", "a", "b"]) not in b
    assert ("radio", ["s2", "c"]) in b and ("playlist", ["a", "c"]) in b


def test_an_uploaders_list_is_its_own_source():
    up = [{"videoId": f"v{i}", "artist": "irikachana"} for i in range(9)] +          [{"videoId": "x", "artist": "Someone Else"}]
    mix = [{"videoId": f"v{i}", "artist": f"A{i % 3}"} for i in range(9)]
    assert CB.playlist_kind(up) == "upload"            # 90% one channel: an album, uploads
    assert CB.playlist_kind(mix) == "playlist"
    assert CB.playlist_kind([{"videoId": "a", "artist": "X - Topic"},
                             {"videoId": "b", "artist": "x"}]) == "upload"
    b = CB.baskets(playlists=[("upload", ["a", "b"]), ["c", "d"]])
    assert b == [("upload", ["a", "b"]), ("playlist", ["c", "d"])]
    # an upload list ties its songs less than someone's mix of the same songs would
    C = CB.Collab([("upload", ["a", "b"]), ("playlist", ["a", "c"])], keep="abc", svd_dim=0,
                  source_w={"upload": 0.25})
    idx, val = C.related("a")
    got = {C.vocab[i]: v for i, v in zip(idx, val)}
    assert got["c"] > got["b"] > 0


def test_related_is_cosine_over_shared_baskets():
    C = CB.Collab([("playlist", ["a", "b"]), ("playlist", ["a", "b", "c"]),
                   ("playlist", ["c", "d"])], svd_dim=0)
    idx, val = C.related("a")
    got = {C.vocab[i]: v for i, v in zip(idx, val)}
    assert "a" not in got and "d" not in got          # no self, no non-neighbour
    assert got["b"] > got["c"] > 0                     # b shares 2 baskets, c one


def test_radio_follows_play_together_not_the_last_song():
    # t1..t4 go with t0 (the seed); they never share a basket with each other's
    # unrelated neighbours, so an anchored radio keeps choosing among them.
    bask = [("playlist", ["t0", "t1", "t2"]), ("playlist", ["t0", "t3", "t4"]),
            ("playlist", ["t1", "t9", "t10"]), ("playlist", ["t1", "t9", "t11"])]
    ctx = _ctx(bask, model=ONLY_COLLAB)
    q = RD.radio("t0", 4, ctx)
    assert set(q) == {"t1", "t2", "t3", "t4"}
    # the next pick, after t1 played, still comes from t0's radio (not t1's t9)
    assert RD.next_pick("t0", ctx, played={"t1"}) in {"t2", "t3", "t4"}


def test_candidates_hold_the_seeds_play_together_neighbours():
    # related() returns indices into C.vocab; the pool took positions in its result for
    # them, i.e. whatever songs came first in vocab (10-19: 2 of a Tazmilian Woods radio's
    # 300 play-together slots were real neighbours; the 10x co-plays never got in).
    bask = [("playlist", ["t7", "t8"]), ("playlist", ["t7", "t8"]),
            ("playlist", ["t0", "t3"]), ("playlist", ["t0", "t3", "t4"])]
    ctx = _ctx(bask)
    cands = RD.candidates("t0", ctx, pool={"collab": 2, "s2v": 0, "sound": 0, "fam": 0})
    assert {"t3", "t4"} <= set(cands)        # sound's 1-song minimum can't hold both


def test_sequence_limits_channel_runs_and_seed_channel_share():
    artist = {"t0": "A", "t1": "A", "t2": "A", "t3": "A", "t4": "B", "t5": "C", "t6": "D",
              "t7": "E"}
    ctx = _ctx([("playlist", ["t0", "t1"])], artist=artist)
    ranked = [(v, 1.0) for v in ("t1", "t2", "t3", "t4", "t5", "t6", "t7")]
    q = RD.sequence("t0", ranked, 5, ctx)
    assert len(q) == 5 and q[0] == "t1"
    runs = max(len(list(g)) for _, g in itertools.groupby(artist[v] for v in q))
    assert runs <= RD.MAX_RUN
    assert sum(artist[v] == "A" for v in q) <= round(RD.SEED_ARTIST_SHARE * 5)
    # with nothing else left, the rules give way rather than ending the queue early
    assert len(RD.sequence("t0", ranked[:3], 3, ctx)) == 3


def test_a_channel_that_leads_by_a_lot_cannot_take_the_queue(monkeypatch):
    # 10-19: irikachana songs led a Tazmilian Woods radio by ~2.5 (their own upload
    # playlists on top of same_artist); a 1.5 cost at most let them fill 20 of 30 slots
    artist = {f"t{i}": ("A" if i <= 20 else f"B{i}") for i in range(41)}
    ctx = _ctx([("playlist", ["t0", "t1"])], n=41, artist=artist)
    ranked = [(f"t{i}", 2.5) for i in range(1, 21)] + [(f"t{i}", 0.5) for i in range(21, 41)]
    cap = RD.ARTIST_OVER_CAP

    def share(c):
        monkeypatch.setattr(RD, "ARTIST_OVER_CAP", c)
        return sum(artist[v] == "A" for v in RD.sequence("t0", ranked, 25, ctx)) / 25
    assert share(2.0) > 0.6                    # the old cap: two in a row, one break, ...
    assert share(cap) <= 0.4


def test_credits_split_collaborations():
    assert RD.credits("Shofu, OmarCameUp") == ("shofu", "omarcameup")
    assert RD.credits("Daddyphatsnaps & OmarCameUp - Topic") == ("daddyphatsnaps", "omarcameup")
    assert RD.credits("A, B, C") == ("a", "b")                     # MAX_CREDITS, as on the H2
    assert RD.credits("") == () and RD.credits(None) == ()


def test_collaborations_count_toward_each_artists_run_and_share():
    # 10-15: an OmarCameUp radio came out 13 of 15 OmarCameUp, half of them as features
    artist = {"t0": "A", "t1": "A", "t2": "B, A", "t3": "A & C", "t4": "A", "t5": "D",
              "t6": "E", "t7": "F"}
    ctx = _ctx([("playlist", ["t0", "t1"])], artist=artist)
    ranked = [(v, 1.0) for v in ("t1", "t2", "t3", "t4", "t5", "t6", "t7")]
    q = RD.sequence("t0", ranked, 5, ctx)
    has_a = ["a" in ctx.credits[v] for v in q]
    assert max(len(list(g)) for k, g in itertools.groupby(has_a) if k) <= RD.MAX_RUN
    assert sum(has_a) <= round(RD.SEED_ARTIST_SHARE * 5)


def test_one_version_of_a_song_per_sitting():
    k = RD.work_key
    assert k("HIT THE JACKPOT (ruff house remix)", "OmarCameUp") == \
        k("HIT THE JACKPOT (ruff house remix instrumental)", "OmarCameUp")
    assert k("Lucid", "OmarCameUp") != k("Lucid", "Someone Else")
    assert k("Theme (Act 1)", "A") != k("Theme (Act 2)", "A")
    ctx = _ctx([("playlist", ["t0", "t1", "t2", "t3"])],
               artist={"t0": "A", "t1": "A", "t2": "B", "t3": "C"})
    ctx.work = {"t0": "a|song", "t1": "a|song", "t2": "b|other", "t3": "b|other"}
    assert "t1" not in [v for v, _ in RD.ranked("t0", ctx)]            # the seed's other version
    q = RD.sequence("t9", [("t2", 2.0), ("t3", 1.9), ("t4", 0.5)], 2, ctx)
    assert q == ["t2", "t4"]                                          # not t2's twin next


def test_streak_counts_the_last_songs_turned_down_in_a_row():
    assert RD.streak(["a", "b", "c", "d"], {"b", "c", "d"}) == 3
    assert RD.streak(["a", "b", "c", "d"], {"a", "b", "c"}) == 0      # you kept the last
    assert RD.streak([], {"a"}) == 0


def test_a_fresh_seed_comes_on_each_full_run_of_skips_not_every_skip_after():
    down = {"b", "c", "d", "e", "f", "g"}
    assert not RD.reseed_now(["a", "b", "c"], down)
    assert RD.reseed_now(["a", "b", "c", "d"], down)             # three: move
    assert not RD.reseed_now(["a", "b", "c", "d", "e"], down)    # the fresh seed's first pick
    assert RD.reseed_now(["a", "b", "c", "d", "e", "f", "g"], down)
    assert not RD.reseed_now(["a"], down)


def test_a_turned_down_seed_follows_what_you_kept_since_it_started():
    down = {"s", "x"}
    assert RD.station_anchor(["a", "b", "s", "c", "x"], "s", down) == "c"
    assert RD.station_anchor(["a", "b", "s", "x"], "s", down) is None    # not a, b: before it
    assert RD.station_anchor(["a", "x"], "s", down) == "a"                # seed older than the tail


def test_fresh_seed_is_a_song_you_play_far_from_what_you_turned_down():
    ctx = _ctx([("playlist", ["t0", "t1"])])
    X = np.zeros((12, 8), dtype=np.float32)
    X[:, 0] = 1.0                                      # everything sounds alike ...
    X[7] = 0.0; X[7, 1] = 1.0                          # ... but t7
    ctx.X = X
    ctx.fam_recent = {"t5": 3.0, "t6": 2.0, "t7": 1.0, "t9": 0.5}
    assert RD.fresh_seed({"t1", "t2", "t3"}, "t0", ctx) == "t7"
    assert RD.fresh_seed({"t1"}, "t0", ctx, exclude={"t7"}) in {"t5", "t6", "t9"}
    ctx.fam_recent = {}
    assert RD.fresh_seed({"t1"}, "t0", ctx) is None   # nothing of yours to move to


def test_fresh_seed_keeps_the_sound_of_what_you_kept():
    # 2026-10-18: a gentle radio you'd finished the seed of, three picks turned down -> the
    # fresh seed was your most played far from them and from the seed (a rap remix)
    ctx = _ctx([("playlist", ["t0", "t1"])])
    X = np.zeros((12, 8), dtype=np.float32)
    X[0, 0] = 1.0                                      # the seed you finished: gentle
    X[1:4, 1] = 1.0                                    # what you turned down
    X[5, 2] = 1.0                                      # most played: somewhere else
    X[6, 0], X[6, 3] = .8, .6                          # less played: gentle, like the seed
    X[7, 3] = 1.0
    ctx.X = X
    ctx.fam_recent = {"t5": 3.0, "t6": 2.0, "t7": 1.0}
    down = {"t1", "t2", "t3"}
    assert RD.fresh_seed(down, "t0", ctx, kept=["t0", "t1", "t2", "t3"]) == "t6"
    assert RD.fresh_seed(down, "t0", ctx) == "t5"      # nothing kept: the most played, away
    X[6, 1] = .9                                       # the gentle one is also like the skips
    assert RD.fresh_seed(down, "t0", ctx, kept=["t0"]) in {"t5", "t7"}


def test_sequence_nudges_toward_the_familiar_share():
    fam = {f"t{i}": 1.0 for i in range(1, 8)}                # t1..t7 known, t8..t19 new
    ctx = _ctx([("playlist", ["t0", "t1"])], n=20, fam=fam)
    # nearly tied scores, known songs ranked first: the nudge alone sets the mix
    ranked = [(f"t{i}", 1.0 - 0.001 * i) for i in range(1, 20)]
    q = RD.sequence("t0", ranked, 10, ctx, familiar_share=0.3)
    assert 2 <= sum(v in fam for v in q) <= 4
    assert [v for v in q if v in fam] == sorted((v for v in q if v in fam), key=lambda v: int(v[1:]))
    # off: plain ranking order
    assert RD.sequence("t0", ranked, 4, ctx, familiar_share=-1) == ["t1", "t2", "t3", "t4"]


def test_familiar_nudge_never_forces_a_poor_fit():
    fam = {"t1": 1.0, "t2": 1.0}
    ctx = _ctx([("playlist", ["t0", "t1"])], fam=fam)
    # short of known songs, but the new song is far better: it still wins
    assert RD.sequence("t0", [("t3", 2.0), ("t1", 0.5)], 1, ctx, familiar_share=0.5)[0] == "t3"
    # over the share, but the known song is far better: it still wins
    tail = ["t5", "t1"]
    assert RD.sequence("t0", [("t2", 2.0), ("t4", 0.5)], 1, ctx, tail=tail,
                       familiar_share=0.1)[0] == "t2"


def test_channels_match_however_they_are_spelled():
    ctx = _ctx([("playlist", ["t0", "t1"])],
               artist={"t0": "Theophany", "t1": "ROZEN", "t2": "Rozen", "t3": "Rozen - Topic",
                       "t4": "Other"})
    assert ctx.artist["t1"] == ctx.artist["t2"] == ctx.artist["t3"]
    q = RD.sequence("t0", [(v, 1.0) for v in ("t1", "t2", "t3", "t4")], 4, ctx)
    assert q.index("t4") <= 2                                   # no three Rozens in a row


def test_a_cached_radio_no_longer_leads(monkeypatch):
    # 10-19: June's cached radios are stale (1 of 25 in common with YT Music's radio now)
    bask = [("playlist", ["t0", "t1"]), ("playlist", ["t0", "t2"])]
    ctx = _ctx(bask, model=ONLY_COLLAB, own={"t0": ["t5", "t6"]})
    assert set(RD.radio("t0", 2, ctx)) == {"t1", "t2"}
    monkeypatch.setattr(RD, "OWN_RADIO_W", 3.0)              # the knob still works
    assert RD.radio("t0", 3, ctx)[:2] == ["t5", "t6"]


def test_rejected_song_pushes_its_neighbours_down():
    ctx = _ctx([("playlist", ["t0", "t1", "t2", "t3"])], model=ONLY_COLLAB)
    # make t2 a sound-twin of t1, then reject t1
    ctx.X[2] = ctx.X[1]
    base = [v for v, _ in RD.ranked("t0", ctx, exclude={"t1"})]
    after = [v for v, _ in RD.ranked("t0", ctx, exclude={"t1"}, rejected={"t1"})]
    assert after.index("t2") > base.index("t2") or after[-1] == "t2"


def test_features_columns_line_up():
    ctx = _ctx([("playlist", ["t0", "t1"])], artist={"t0": "A", "t1": "A", "t2": "B"},
               fam={"t2": 1.5})
    F = RD.features("t0", ["t1", "t2"], ctx)
    col = {f: i for i, f in enumerate(RD.FEATURES)}
    assert F[0, col["same_artist"]] == 1 and F[1, col["same_artist"]] == 0
    assert F[1, col["fam"]] == 1.5
    assert F[0, col["collab"]] > 0 and F[1, col["no_collab"]] == 1


def test_a_channel_whose_radios_go_elsewhere_counts_for_less():
    # YT Music's radios on A's songs keep half to A; on B's, one member in twenty
    keeps = [("A", ["A"] * 10 + ["x"] * 10)] * 3
    leaves = [("B", ["B"] + ["y"] * 19)] * 3
    st = RD.stick(keeps + leaves, k=0)
    assert st["A"] > 1 > st["B"]
    assert RD.stick(keeps + leaves)["B"] > st["B"]           # shrunk toward the average
    st = RD.stick(keeps[:1] + [("C", ["C"] * 10 + ["x"] * 10)] * 10 + leaves * 20)
    assert 1 < st["A"] < st["C"]                              # one radio says less than ten
    assert RD.stick([("A", [None, None]), (None, ["A"])]) == {}   # nothing known: no stick

    # the queue's share for the seed's channel / game series goes down with it
    ctx = _ctx([], n=40, artist={f"t{i}": ("A" if i < 20 else f"B{i}") for i in range(40)})
    ctx.franchise = {"t0": "mario"}
    assert RD.shares("t0", ctx) == (RD.SEED_ARTIST_SHARE, RD.SEED_GAME_SHARE)
    ctx.stick = {"artist": {"a": 0.5}, "game": {"mario": 9.0}}
    a, g = RD.shares("t0", ctx)
    assert a == RD.SEED_ARTIST_SHARE * 0.5 and g == RD.SEED_GAME_SHARE     # lowered, never raised
    ranked = [(f"t{i}", 10.0 - i * 0.01) for i in range(1, 40)]     # A's 19 songs rank first
    n_a = lambda q: sum(v in {f"t{i}" for i in range(20)} for v in q)
    ctx.stick = {}
    full = n_a(RD.sequence("t0", ranked, 25, ctx))
    ctx.stick = {"artist": {"a": 0.5}}
    assert n_a(RD.sequence("t0", ranked, 25, ctx)) < full


def test_radio_sticks_hold_out_seeds_and_read_member_channels():
    radios = [("s1", ["m1", "m2"]), ("s2", ["m3", "m4"])]
    names = {"s1": ["Rozen", "Other"], "s2": ["X - Topic", "x"]}
    artist = {"s1": "ROZEN", "s2": "X"}
    st = RD.radio_sticks(radios, names, artist, {}, lib=set())
    assert set(st["artist"]) == {"rozen", "x"} and st["artist"]["x"] > st["artist"]["rozen"]
    assert set(RD.radio_sticks(radios, names, artist, {}, lib=set(), skip={"s2"})["artist"]) == {"rozen"}


# ------------------------------------------------------------------ server wiring

import json as _json  # noqa: E402

from test_server_api import _last_trace, _stub_emb_sim, srv  # noqa: E402,F401


def _radio_srv(srv, tmp_path):  # noqa: F811
    """The server on the 3-track test library, radio on, against temp caches: a cached
    YT Music radio for aaa that holds ccc (the far-sounding track), so a radio on aaa
    must lead with ccc while the sound-nearest track is bbb."""
    srv._EMB = _stub_emb_sim()
    srv._COOC, srv._CLUSTERS = {}, {}
    srv.RADIO_MODE = True
    srv.RADIO_CACHE.mkdir()
    (srv.RADIO_CACHE / "aaa.json").write_text(
        _json.dumps([{"videoId": "aaa"}, {"videoId": "ccc"}]), encoding="utf-8")
    srv.PLAYLIST_CACHE.mkdir()
    return srv


def test_song_radio_endpoint_uses_the_radio_engine(srv, tmp_path):  # noqa: F811
    s = _radio_srv(srv, tmp_path)
    ids = [t["id"] for t in s.app.test_client().get("/api/radio?kind=track&name=aaa").get_json()]
    assert ids[0] == "ccc" and "aaa" not in ids
    assert s.COLLAB_CACHE.exists()                       # the model was cached for next time


def test_autoplay_keeps_choosing_for_the_seed_not_the_current_song(srv, tmp_path):  # noqa: F811
    s = _radio_srv(srv, tmp_path)
    c = s.app.test_client()
    # on ccc, a radio of its own would be anything; seeded on aaa it must not repeat aaa/ccc
    t = c.get("/api/next?id=ccc&exclude=aaa,ccc&seed=aaa&outcome=complete").get_json()
    assert t["id"] == "bbb"
    tr = _last_trace(s)
    assert tr["pick"]["reason"] == "radio" and tr["anchor"] == "aaa"
    # no seed: the radio is on the current song
    c.get("/api/next?id=aaa&exclude=aaa")
    assert _last_trace(s)["pick"]["id"] == "ccc"


def test_walk_still_available_with_the_radio_off(srv, tmp_path):  # noqa: F811
    s = _radio_srv(srv, tmp_path)
    s.RADIO_MODE = False
    s.app.test_client().get("/api/next?id=aaa&exclude=aaa")
    assert _last_trace(s)["pick"]["reason"] != "radio"


def test_game_nudge_spreads_close_calls_but_never_forces_a_poor_fit():
    n = 24
    fr = {f"t{i}": "mario" for i in range(0, 12)}            # t0 = seed, t1..t11 Mario
    artist = {f"t{i}": f"a{i}" for i in range(n)}             # all different channels
    ctx = _ctx([("playlist", ["t0", "t1"])], n=n, artist=artist)
    ctx.franchise = fr
    mario, other = [f"t{i}" for i in range(1, 12)], [f"t{i}" for i in range(12, n)]
    # far better Mario songs: the capped cost (<= GAME_PULL * OVER_CAP) never outweighs it
    ranked = [(v, 3.0) for v in mario] + [(v, -1.0) for v in other]
    q = RD.sequence("t0", ranked, 10, ctx, familiar_share=-1)
    assert sum(v in fr for v in q) == 10
    # close calls: the share decides, and the game spreads through the queue
    ranked = [(v, 1.0) for v in mario] + [(v, 0.95) for v in other]
    q = RD.sequence("t0", ranked, 10, ctx, familiar_share=-1)
    assert 3 <= sum(v in fr for v in q) <= 6
