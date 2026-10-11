"""Tests for the player API surfaces added on top of the plays log: play provenance
(source + session_id), likes (latest-wins over like/unlike), listening history
(session grouping, with the 30-minute-gap fallback for legacy NULL rows) and the
trash quarantine/restore/clear round-trip.

Everything runs against a throwaway SQLite file + throwaway .opus files in tmp_path;
the real data/library.db and D:\\OfflineMusic are never opened (PLAYER_DB points the
server module elsewhere before it is imported, and TRASH_LOG is monkeypatched).

Run: .venv\\Scripts\\python -m pytest -q tests/test_server_api.py
"""
import importlib
import json
import random
import sqlite3
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, "scripts")

import personalize  # noqa: E402


# ------------------------------------------------------------------ fixtures

TRACKS = [
    # video_id, title, artist, album
    ("aaa", "Hopes and Dreams", "Toby Fox", "Undertale"),
    ("bbb", "Megalovania", "Toby Fox", "Undertale"),
    ("ccc", "Green Hill Zone", "Masato Nakamura", "Sonic"),
]


def _build_db(path, music_dir):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE tracks (
        video_id TEXT PRIMARY KEY, path TEXT NOT NULL,
        title TEXT, artist TEXT, album TEXT, albumartist TEXT,
        genre TEXT, year TEXT, track_no INTEGER, duration REAL,
        r128_gain_db REAL, album_gain_db REAL)""")
    con.execute("""CREATE VIRTUAL TABLE tracks_fts USING fts5(
        video_id UNINDEXED, title, artist, album, genre, tokenize='unicode61')""")
    con.execute("CREATE TABLE neighbors(video_id TEXT, rank INTEGER, neighbor_id TEXT, sim REAL)")
    con.execute("""CREATE TABLE analysis(video_id TEXT PRIMARY KEY, bpm REAL, key TEXT,
        energy_db REAL, hook_sec REAL, lead_sec REAL, tail_sec REAL, ver INTEGER DEFAULT 1)""")
    for i, (vid, title, artist, album) in enumerate(TRACKS):
        f = music_dir / f"{artist} - {title} [{vid}].opus"
        f.write_bytes(b"OggS-not-really-audio-" + vid.encode() * 4)
        con.execute("INSERT INTO tracks(video_id,path,title,artist,album,genre,track_no,"
                    "duration,r128_gain_db,album_gain_db) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (vid, str(f), title, artist, album, "", i + 1, 100.0 + i, -9.0, -7.5))
        con.execute("INSERT INTO tracks_fts(video_id,title,artist,album,genre) VALUES(?,?,?,?,?)",
                    (vid, title, artist, album, ""))
        con.execute("INSERT INTO neighbors VALUES(?,?,?,?)", (vid, 1, "zzz", 0.9))
        con.execute("INSERT INTO neighbors VALUES(?,?,?,?)", ("zzz", 1, vid, 0.9))
    # only ONE track is analysed: the sweep is still running in real life, so every
    # consumer has to be fine with a missing hook point.
    con.execute("INSERT INTO analysis(video_id, hook_sec, energy_db) VALUES(?,?,?)",
                ("aaa", 42.5, -8.0))
    con.commit()
    con.close()


@pytest.fixture
def srv(tmp_path, monkeypatch):
    """A freshly-imported server module bound to a temp library + temp trash log."""
    music = tmp_path / "OfflineMusic"
    music.mkdir()
    dbp = tmp_path / "library.db"
    _build_db(dbp, music)
    monkeypatch.setenv("PLAYER_DB", str(dbp))
    import server
    importlib.reload(server)                       # re-reads PLAYER_DB, resets caches
    server.TRASH_LOG = tmp_path / "trashed_rows.jsonl"
    server.TRACE_PATH = tmp_path / "next_trace.jsonl"   # never append to the real trace
    server.SEEDS_CSV = tmp_path / "seed_tracks.csv"      # no real listening history
    server.LISTENS_CSV = tmp_path / "listens.csv"
    server.app.config["TESTING"] = True
    server.music_dir = music
    return server


@pytest.fixture
def client(srv):
    return srv.app.test_client()


def _plays(srv):
    con = sqlite3.connect(srv.DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM plays ORDER BY rowid")]
    con.close()
    return rows


def _insert_plays(srv, rows):
    """rows: (video_id, ts, event, seconds, source, session_id)"""
    con = sqlite3.connect(srv.DB)
    con.executemany("INSERT INTO plays(video_id,ts,event,seconds,source,session_id) "
                    "VALUES(?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


# ------------------------------------------------------------------ event weights

def test_event_weight_unlike_mirrors_like():
    assert personalize.event_weight("like", None) == 3.0
    assert personalize.event_weight("unlike", None) == -3.0


def test_event_weight_trash_is_a_strong_negative():
    assert personalize.event_weight("trash", None) == -3.0
    assert personalize.event_weight("trash", 1.0) == -3.0      # completion is irrelevant


def test_like_then_unlike_nets_out_in_prefs():
    """A like taken back leaves no residue. (The pair sits past the early-session window
    so the existing "early negatives are mood, not dislike" halving doesn't apply.)"""
    now = 1_700_000_000.0
    warmup = [(v, now - 100 + i, "play", 90.0)
              for i, v in enumerate(("w1", "w2", "w3"))]
    plays = warmup + [("aaa", now, "like", None), ("aaa", now + 1, "unlike", None)]
    prefs = personalize.compute_prefs(plays, {"aaa": 100.0}, {"aaa": "Toby Fox"}, now=now + 1)
    assert prefs["track"]["aaa"] == pytest.approx(0.0, abs=1e-6)
    assert prefs["artist"]["Toby Fox"] == pytest.approx(0.0, abs=1e-6)


def test_trash_signal_survives_the_track():
    """A trashed track keeps a negative score (and drags its artist down) — that is the
    whole point of logging the event before the row is deleted."""
    now = 1_700_000_000.0
    prefs = personalize.compute_prefs([("bbb", now, "trash", None)],
                                      {}, {"bbb": "Toby Fox"}, now=now)
    assert prefs["track"]["bbb"] < 0
    assert "bbb" in prefs["skip_ids"]
    assert prefs["artist"]["Toby Fox"] < 0


# ------------------------------------------------------------------ provenance

def test_play_stores_source_and_session(client, srv):
    r = client.post("/api/play", json={"id": "aaa", "event": "play", "seconds": 3,
                                       "source": "wheel", "session_id": "sess-1"})
    assert r.json == {"ok": True}
    row = _plays(srv)[-1]
    assert (row["video_id"], row["event"], row["source"], row["session_id"]) == \
           ("aaa", "play", "wheel", "sess-1")


def test_play_without_provenance_still_works(client, srv):
    client.post("/api/play", json={"id": "bbb"})
    row = _plays(srv)[-1]
    assert row["event"] == "play" and row["source"] is None and row["session_id"] is None


def test_track_payload_carries_hook_and_album_gain(client):
    tracks = {t["id"]: t for t in client.get("/api/tracks").json}
    assert tracks["aaa"]["hook_sec"] == 42.5
    assert tracks["bbb"]["hook_sec"] is None          # not analysed yet -> null, not an error
    assert tracks["aaa"]["album_gain_db"] == -7.5
    assert tracks["aaa"]["gain"] == -9.0


# ------------------------------------------------------------------ likes

def test_likes_latest_event_wins(client):
    client.post("/api/play", json={"id": "aaa", "event": "like"})
    client.post("/api/play", json={"id": "bbb", "event": "like"})
    client.post("/api/play", json={"id": "bbb", "event": "unlike"})
    liked = client.get("/api/likes").json
    assert [t["id"] for t in liked] == ["aaa"]
    assert liked[0]["title"] == "Hopes and Dreams"
    assert liked[0]["liked_at"] > 0


def test_likes_relike_after_unlike(client):
    for ev in ("like", "unlike", "like"):
        client.post("/api/play", json={"id": "ccc", "event": ev})
    assert [t["id"] for t in client.get("/api/likes").json] == ["ccc"]


def test_likes_newest_first_and_ignores_missing_tracks(client, srv):
    _insert_plays(srv, [("aaa", 100.0, "like", None, None, None),
                        ("ccc", 200.0, "like", None, None, None),
                        ("gone", 300.0, "like", None, None, None)])
    assert [t["id"] for t in client.get("/api/likes").json] == ["ccc", "aaa"]


# ------------------------------------------------------------------ history

def test_history_groups_by_session_id(client, srv):
    t0 = 1_700_000_000.0
    _insert_plays(srv, [
        ("aaa", t0 + 0, "play", None, "wheel", "S1"),
        ("aaa", t0 + 90, "complete", 100, "wheel", "S1"),
        ("bbb", t0 + 91, "play", None, "autoplay", "S1"),
        ("bbb", t0 + 95, "skip", 4, "autoplay", "S1"),
        ("ccc", t0 + 100, "play", None, "library", "S2"),   # different session, same minute
        ("ccc", t0 + 101, "like", None, None, "S2"),
    ])
    sessions = client.get("/api/history").json
    assert [s["session_id"] for s in sessions] == ["S2", "S1"]        # newest first
    s1 = sessions[1]
    assert [t["id"] for t in s1["tracks"]] == ["aaa", "bbb"]          # play order
    assert [t["outcome"] for t in s1["tracks"]] == ["completed", "skipped"]
    assert s1["started"] == t0 and s1["ended"] == t0 + 95 and s1["count"] == 2
    assert sessions[0]["tracks"][0]["outcome"] == "liked"


def test_history_falls_back_to_thirty_minute_gaps_for_legacy_rows(client, srv):
    t0 = 1_700_000_000.0
    _insert_plays(srv, [
        ("aaa", t0, "play", None, None, None),
        ("bbb", t0 + 300, "play", None, None, None),          # same session (5 min later)
        ("ccc", t0 + 300 + 3600, "play", None, None, None),   # an hour later -> new session
    ])
    sessions = client.get("/api/history").json
    assert len(sessions) == 2
    assert [t["id"] for t in sessions[0]["tracks"]] == ["ccc"]
    assert [t["id"] for t in sessions[1]["tracks"]] == ["aaa", "bbb"]
    assert all(s["session_id"] is None for s in sessions)


def test_history_ignores_peeks_and_respects_limit(client, srv):
    t0 = 1_700_000_000.0
    rows = [("aaa", t0 + i * 4000, "play", None, None, f"S{i}") for i in range(5)]
    rows.append(("bbb", t0 + 1, "peek", None, "wheel", "S0"))
    _insert_plays(srv, rows)
    sessions = client.get("/api/history?limit=2").json
    assert len(sessions) == 2
    assert [t["id"] for t in sessions[-1]["tracks"]] == ["aaa"]       # the peek never shows


# ------------------------------------------------------------------ trash

def test_trash_quarantines_and_logs_the_verdict(client, srv):
    path = srv.music_dir / "Toby Fox - Megalovania [bbb].opus"
    assert path.exists()
    r = client.post("/api/trash", json={"id": "bbb", "session_id": "S9"})
    assert r.json["ok"] is True

    quarantined = srv.music_dir / "_trash" / path.name
    assert quarantined.exists() and not path.exists()

    con = sqlite3.connect(srv.DB)
    assert con.execute("SELECT COUNT(*) FROM tracks WHERE video_id='bbb'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM tracks_fts WHERE video_id='bbb'").fetchone()[0] == 0
    # neighbors rows stay behind on purpose (orphans are invisible through the tracks join)
    assert con.execute("SELECT COUNT(*) FROM neighbors WHERE video_id='bbb'").fetchone()[0] == 1
    con.close()

    ev = [p for p in _plays(srv) if p["event"] == "trash"]
    assert len(ev) == 1 and ev[0]["video_id"] == "bbb" and ev[0]["session_id"] == "S9"

    entry = json.loads(srv.TRASH_LOG.read_text(encoding="utf-8").splitlines()[0])
    assert entry["row"]["video_id"] == "bbb" and entry["row"]["path"] == str(path)
    assert entry["quarantined_to"] == str(quarantined)


def test_trashed_track_disappears_from_the_library(client):
    client.post("/api/trash", json={"id": "bbb"})
    assert "bbb" not in [t["id"] for t in client.get("/api/tracks").json]
    assert "bbb" not in [t["id"] for t in client.get("/api/search?q=megalovania").json]


def test_trash_listing_reports_size_and_time(client, srv):
    before = time.time()
    client.post("/api/trash", json={"id": "aaa"})
    items = client.get("/api/trash").json
    assert len(items) == 1
    it = items[0]
    assert it["id"] == "aaa" and it["title"] == "Hopes and Dreams" and it["artist"] == "Toby Fox"
    assert it["bytes"] > 0 and it["trashed_at"] >= before


def test_trash_restore_round_trip(client, srv):
    path = srv.music_dir / "Masato Nakamura - Green Hill Zone [ccc].opus"
    original = path.read_bytes()
    client.post("/api/trash", json={"id": "ccc"})
    assert not path.exists()

    r = client.post("/api/trash/restore", json={"id": "ccc"})
    assert r.json["ok"] is True
    assert path.exists() and path.read_bytes() == original
    assert client.get("/api/trash").json == []

    back = {t["id"]: t for t in client.get("/api/tracks").json}
    assert back["ccc"]["title"] == "Green Hill Zone"
    assert back["ccc"]["album_gain_db"] == -7.5                   # full row came back
    assert "ccc" in [t["id"] for t in client.get("/api/search?q=green hill").json]
    # the trash verdict stays in the log even after a restore: it happened.
    assert [p["event"] for p in _plays(srv) if p["video_id"] == "ccc"] == ["trash"]


def test_trash_restore_unknown_id_is_404(client):
    assert client.post("/api/trash/restore", json={"id": "nope"}).status_code == 404


def test_trash_clear_is_permanent(client, srv):
    client.post("/api/trash", json={"id": "aaa"})
    client.post("/api/trash", json={"id": "bbb"})
    qdir = srv.music_dir / "_trash"
    assert len(list(qdir.iterdir())) == 2

    r = client.post("/api/trash/clear")
    assert r.json["ok"] is True and r.json["deleted"] == 2 and r.json["bytes"] > 0
    assert list(qdir.iterdir()) == []
    assert client.get("/api/trash").json == []
    assert srv.TRASH_LOG.read_text(encoding="utf-8").strip() == ""

    con = sqlite3.connect(srv.DB)
    # clearing is the point at which the orphan neighbors rows are finally dropped
    assert con.execute("SELECT COUNT(*) FROM neighbors WHERE video_id IN ('aaa','bbb') "
                       "OR neighbor_id IN ('aaa','bbb')").fetchone()[0] == 0
    con.close()


def test_trash_missing_id_is_rejected(client):
    assert client.post("/api/trash", json={}).status_code == 400
    assert client.post("/api/trash", json={"id": "nope"}).status_code == 404


def test_trash_reports_a_locked_file_instead_of_half_doing_it(client, srv, monkeypatch):
    """Windows refuses to move a file that is still being streamed. The endpoint must say
    so (409) and leave the library exactly as it was."""
    def boom(*a, **k):
        raise OSError(32, "The process cannot access the file because it is being used")
    monkeypatch.setattr(srv.shutil, "move", boom)

    r = client.post("/api/trash", json={"id": "aaa"})
    assert r.status_code == 409 and r.json["locked"] is True
    assert "may still be playing" in r.json["error"]
    assert (srv.music_dir / "Toby Fox - Hopes and Dreams [aaa].opus").exists()
    assert "aaa" in [t["id"] for t in client.get("/api/tracks").json]
    assert client.get("/api/trash").json == []


# ------------------------------------------------------------------ retrieval blend
# blend_candidates is pure — it takes ordered id lists, not a matrix or a request — so
# these run on stub data with no embeddings and no Flask context.

BASE = ["cur"] + [f"n{i}" for i in range(11)]      # ordered by similarity to "cur"
LIB = set(BASE) | {"ta1", "ta2", "r1", "r2"}
CAPS = {"cur": 3, "taste": 2, "radio": 50, "fresh": 2, "fresh_pool": 0, "total": 400}
# everything has been played except these — the never-played pool the fresh slots draw on
UNHEARD = {"n7", "n8", "n9", "ta2"}
COUNTS = {v: 2 for v in LIB if v not in UNHEARD}


def _blend(srv, **kw):
    kw.setdefault("taste_ids", ["n1", "ta1", "ta2"])   # n1 also sits in BASE -> dedupe
    kw.setdefault("radio_ids", {"r2", "r1", "gone"})   # a set, and one non-library id
    kw.setdefault("play_counts", COUNTS)
    kw.setdefault("caps", CAPS)
    return srv.blend_candidates("cur", BASE, LIB, {"cur", "n0"}, **kw)


def test_blend_draws_from_every_source_and_dedupes(srv):
    out = _blend(srv)
    assert out[:3] == ["n1", "n2", "n3"]                  # backbone, in similarity order
    assert out[3:5] == ["ta1", "ta2"]                     # taste centroid hits
    assert out[5:7] == ["r1", "r2"]                       # radio members, sorted
    assert len(out) == len(set(out)) == 9                 # + 2 fresh, nothing twice
    assert set(out[7:]) <= {"n7", "n8", "n9"}             # fresh = never played, on-vibe
    # exclusions and library membership are honoured everywhere
    assert "cur" not in out and "n0" not in out and "gone" not in out


def test_blend_never_played_sample_is_reproducible_per_track(srv):
    # same current track -> same fresh picks (a trace can be replayed); a different
    # track (= a different seed) is free to land elsewhere
    assert _blend(srv) == _blend(srv)
    other = srv.blend_candidates("n5", BASE, LIB, {"cur", "n0"},
                                 play_counts=COUNTS, caps=CAPS)
    assert set(other[3:]) <= {"n7", "n8", "n9"}
    # an explicit rng overrides the per-track seed
    seeded = [srv.blend_candidates("cur", BASE, LIB, {"cur", "n0"}, play_counts=COUNTS,
                                   caps=CAPS, rng=random.Random(7)) for _ in range(2)]
    assert seeded[0] == seeded[1]


def test_blend_respects_the_total_cap_and_protects_the_other_sources(srv):
    caps = dict(CAPS, cur=8, total=6)
    out = _blend(srv, caps=caps)
    assert len(out) == 6
    # the trim came out of the similarity backbone; taste/radio/fresh all survived
    assert "ta1" in out and "r1" in out
    assert len([v for v in out if v.startswith("n") and v not in UNHEARD]) == 1


def test_blend_caps_give_the_wildcard_sources_more_room(srv):
    """User feedback ("all the songs kinda sound the same in the autoplay"): a ranker told
    to stop picking clones needs non-clones to pick FROM. The two sources that do NOT come
    out of the current track's cosine order were widened, and only the backbone pays."""
    assert (srv.BLEND["taste"], srv.BLEND["fresh"]) == (80, 25)
    assert (srv.BLEND["cur"] + srv.BLEND["taste"] + srv.BLEND["radio"]
            + srv.BLEND["fresh"]) > srv.BLEND["total"]      # the trim is what makes room
    base = [f"b{i}" for i in range(400)]
    taste_ids = [f"t{i}" for i in range(120)]
    radio = {f"r{i}" for i in range(60)}
    lib = set(base) | set(taste_ids) | radio

    played = srv.blend_candidates("cur", base, lib, set(), taste_ids=taste_ids,
                                  radio_ids=radio, play_counts={v: 1 for v in lib})
    assert len(played) == srv.BLEND["total"] == 400
    assert len([v for v in played if v[0] == "t"]) == 80     # was 60
    assert len([v for v in played if v[0] == "r"]) == 50     # untouched
    assert len([v for v in played if v[0] == "b"]) == 270    # the backbone gave the ground

    # with never-played tracks around, the fresh slice grows too — and comes out of the
    # backbone as well, not out of taste/radio
    out = srv.blend_candidates("cur", base, lib, set(), taste_ids=taste_ids,
                               radio_ids=radio, play_counts={})
    fresh = [v for v in out if v[0] == "b" and int(v[1:]) >= srv.BLEND["cur"]]
    assert len(fresh) == 25                                 # was 15
    assert len(out) == 400
    assert len([v for v in out if v[0] == "t"]) == 80 and len([v for v in out if v[0] == "r"]) == 50


def test_blend_degrades_to_the_backbone_alone(srv):
    # no taste model, no radio, everything already played -> exactly the old behaviour
    out = srv.blend_candidates("cur", BASE, LIB, {"cur"},
                               play_counts={v: 1 for v in LIB}, caps=CAPS)
    assert out == ["n0", "n1", "n2"]
    assert srv.blend_candidates("cur", [], LIB, {"cur"}, caps=CAPS) == []


# ------------------------------------------------------------------ adaptive epsilon

def test_adaptive_epsilon_reacts_to_how_tracks_land(srv):
    dur = {"a": 100.0}
    skips = [("a", 100.0 + i, "skip", 5.0) for i in range(10)]
    accepts = [("a", 100.0 + i, "complete", 100.0) for i in range(10)]
    # nothing decided yet -> exactly the historical fixed rate
    assert srv.outcome_epsilon([], dur) == pytest.approx(0.15)
    # a skip streak explores harder (capped), an accept streak barely explores (floored)
    assert srv.outcome_epsilon(skips, dur) == pytest.approx(0.30)
    assert srv.outcome_epsilon(accepts, dur) == pytest.approx(0.05)
    # starts / hover previews carry no verdict at all
    assert srv.outcome_epsilon([("a", 1.0, "play", None), ("a", 2.0, "peek", None)],
                               dur) == pytest.approx(0.15)
    # a late skip is a finish, not a rejection
    assert srv.outcome_epsilon([("a", 100.0 + i, "skip", 95.0) for i in range(10)],
                               dur) == pytest.approx(0.05)
    # only the last window counts, and out-of-order rows are sorted by ts first
    later_accepts = [("a", 200.0 + i, "complete", 100.0) for i in range(10)]
    later_skips = [("a", 200.0 + i, "skip", 5.0) for i in range(10)]
    assert srv.outcome_epsilon(skips + later_accepts, dur) == pytest.approx(0.05)
    assert srv.outcome_epsilon(accepts + later_skips, dur) == pytest.approx(0.30)
    assert srv.outcome_epsilon(list(reversed(accepts + later_skips)), dur) \
        == pytest.approx(0.30)
    # a mixed record lands between the two rails
    mixed = [("a", 100.0 + i, "complete" if i % 2 else "skip", 100.0 if i % 2 else 5.0)
             for i in range(10)]
    assert 0.05 < srv.outcome_epsilon(mixed, dur) < 0.30
    # legacy (source-less) sub-3 s skips were clicking through results: no outcome at all;
    # the same quick skip from the current client (it carries a source) is a real verdict
    browse = [("a", 100.0 + i, "skip", 1.0) for i in range(10)]
    assert srv.outcome_epsilon(browse, dur) == pytest.approx(0.15)
    verdicts = [("a", 100.0 + i, "skip", 1.0, "autoplay") for i in range(10)]
    assert srv.outcome_epsilon(verdicts, dur) == pytest.approx(0.30)


def test_explore_epsilon_defaults_before_any_refresh(srv):
    assert srv.explore_epsilon() == pytest.approx(0.15)
    srv._PREF["epsilon"] = 0.05
    assert srv.explore_epsilon() == pytest.approx(0.05)    # 0.05 is falsy-adjacent, not None


# ------------------------------------------------------------------ session mood decay

def _stub_emb(ids):
    X = np.eye(len(ids), dtype=np.float32)     # orthogonal: weights read straight off
    return {"X": X, "ids": ids, "id2i": {v: i for i, v in enumerate(ids)}}


def test_session_mood_leans_on_the_newest_track(srv):
    E = _stub_emb(["a", "b", "c"])
    v = srv.session_centroid(E, ["a", "b"])
    assert float(E["X"][1] @ v) > float(E["X"][0] @ v)          # newest pulls hardest
    assert v[0] / v[1] == pytest.approx(srv.MOOD_DECAY)          # one step back = x0.85
    # two steps back is decayed twice, and the order genuinely matters
    v3 = srv.session_centroid(E, ["a", "b", "c"])
    assert v3[0] / v3[2] == pytest.approx(srv.MOOD_DECAY ** 2)
    assert srv.session_centroid(E, ["b", "a"])[0] > srv.session_centroid(E, ["a", "b"])[0]
    # a repeat in the tail accumulates its weights; an empty tail has no mood at all
    rep = srv.session_centroid(E, ["a", "a", "b"])
    assert rep[0] / rep[1] == pytest.approx(srv.MOOD_DECAY + srv.MOOD_DECAY ** 2)
    assert srv.session_centroid(E, []) is None
    assert float(np.linalg.norm(v)) == pytest.approx(1.0)       # still L2-normalized


# ------------------------------------------------------------------ cluster arms

def test_cluster_stats_counts_accepts_and_early_skips(srv):
    cl = {"aaa": "1", "bbb": "1", "ccc": "2"}
    dur = {"aaa": 100.0, "bbb": 100.0, "ccc": 100.0}
    plays = [("aaa", 1.0, "complete", 100.0),      # accept
             ("bbb", 2.0, "skip", 5.0),            # early skip -> reject
             ("bbb", 2.5, "skip", 1.0),            # legacy sub-3 s skip: browsing, neither
             ("ccc", 3.0, "skip", 50.0),           # mid skip -> ambiguous, neither
             ("ccc", 4.0, "trash", None),          # reject
             ("aaa", 5.0, "play", None),           # a start is not an outcome
             ("bbb", 6.0, "like", None),           # accept
             ("zzz", 7.0, "like", None)]           # unclustered track: ignored
    assert srv.cluster_stats(plays, dur, cl) == {"1": (2, 1), "2": (0, 1)}
    assert srv.cluster_stats(plays, dur, {}) == {}


def test_clusters_csv_is_read_when_present(srv, tmp_path):
    srv.CLUSTERS_CSV = tmp_path / "clusters.csv"
    srv._CLUSTERS = None
    assert srv.clusters() == {}                    # absent file -> feature simply off
    srv.CLUSTERS_CSV.write_text(
        "video_id,artist,title,cluster,genre,x_energetic,y_electronic\n"
        "aaa,Toby Fox,Hopes,6,ambient,-0.2,0.8\n"
        "bbb,Toby Fox,Mega,2,chiptune,0.9,0.1\n"
        "ccc,Nakamura,Green,,,,\n", encoding="utf-8-sig")
    srv._CLUSTERS = None
    assert srv.clusters() == {"aaa": "6", "bbb": "2"}   # blank cluster -> no arm


# ------------------------------------------------------------------ /api/next wiring

@pytest.fixture
def nextsrv(srv):
    """The autoplay endpoint on stub embeddings — the real 55k matrix is never loaded."""
    srv._EMB = _stub_emb_sim()
    srv._COOC = {"aaa": {"ccc"}}
    srv._CLUSTERS = {"aaa": "1", "bbb": "1", "ccc": "2"}
    return srv


def _stub_emb_sim():
    ids = ["aaa", "bbb", "ccc"]
    X = np.array([[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    return {"X": X, "ids": ids, "id2i": {v: i for i, v in enumerate(ids)}}


def _last_trace(srv):
    return json.loads(srv.TRACE_PATH.read_text(encoding="utf-8").splitlines()[-1])


def test_api_next_traces_the_adaptive_epsilon(nextsrv):
    client = nextsrv.app.test_client()
    r = client.get("/api/next?id=aaa&exclude=aaa")
    assert r.json["id"] in ("bbb", "ccc")
    assert _last_trace(nextsrv)["epsilon"] == pytest.approx(0.15)   # no history yet

    # a streak of early skips must show up as a WIDER exploration rate in the trace
    _insert_plays(nextsrv, [("bbb", 1000.0 + i, "skip", 5.0, None, None) for i in range(10)])
    r = client.get("/api/next?id=aaa&exclude=aaa")
    assert r.status_code == 200
    assert _last_trace(nextsrv)["epsilon"] == pytest.approx(0.30)


def test_api_next_low_mem_blends_off_the_neighbors_table(tmp_path, monkeypatch):
    """The handheld build has no full-matrix sims: the backbone is the precomputed
    neighbours row, and the blend still adds radio members + a never-played pick."""
    music = tmp_path / "OfflineMusic"
    music.mkdir()
    dbp = tmp_path / "library.db"
    _build_db(dbp, music)
    con = sqlite3.connect(dbp)
    con.execute("DELETE FROM neighbors")
    con.execute("INSERT INTO neighbors VALUES('aaa', 1, 'bbb', 0.99)")   # only ONE neighbour
    con.commit()
    con.close()
    monkeypatch.setenv("PLAYER_DB", str(dbp))
    monkeypatch.setenv("PLAYER_LOW_MEM", "1")
    import server
    importlib.reload(server)
    server.TRACE_PATH = tmp_path / "next_trace.jsonl"
    server._EMB = _stub_emb_sim()
    server._COOC = {"aaa": {"ccc"}}          # ccc is NOT a neighbour — the radio adds it
    server._CLUSTERS = {}
    server.app.config["TESTING"] = True

    assert server.LOW_MEM is True
    r = server.app.test_client().get("/api/next?id=aaa&exclude=aaa")
    assert r.json["id"] in ("bbb", "ccc")
    assert {t["id"] for t in _last_trace(server)["top"]} == {"bbb", "ccc"}


def test_api_next_charges_a_near_clone_for_being_one(nextsrv):
    """The autoplay overrides reach the ranker: `bbb` is a manufactured near-clone of the
    playing track (cos ~0.994), so it must show a NEGATIVE sameness in the trace, while
    the unrelated `ccc` shows exactly 0.0. Fatigue is computed at the server's floor
    (centered space), and personalize's own defaults stay where they were."""
    P = nextsrv.AUTOPLAY_PARAMS
    assert P["scale"] == "window" and P["same_floor"] < 0.85 and P["rho_floor"] < 0.76
    X = _stub_emb_sim()["X"]
    cos = float(X[1] @ X[0])                       # bbb vs aaa
    assert cos > P["same_floor"]                   # the clone is over the hill's floor

    client = nextsrv.app.test_client()
    assert client.get("/api/next?id=aaa&exclude=aaa").status_code == 200
    terms = {t["id"]: t["terms"] for t in _last_trace(nextsrv)["top"]}
    # band slopes are relative to vibe's and are not rescaled by the window
    assert terms["bbb"]["sameness"] == pytest.approx(-P["same_w"] * (cos - P["same_floor"]), abs=5e-4)
    assert terms["ccc"]["sameness"] == 0.0         # orthogonal: nothing to charge for
    rho = P.get("rho", 2.0)                        # the slope is personalize's default
    assert terms["bbb"]["fatigue"] == pytest.approx(-rho * (cos - P["rho_floor"]), abs=5e-4)
    # the override is a call-site argument only — the library default stays OFF, which is
    # what keeps the firmware goldens (generated from the default call) exact
    plain = personalize.rank_next("aaa", ["bbb"], X, _stub_emb_sim()["id2i"],
                                  ["aaa", "bbb", "ccc"], [None] * 3, explain=True)
    assert plain[0][2]["sameness"] == 0.0


def test_vibe_walk_ranks_with_the_autoplay_params(nextsrv, monkeypatch):
    """The station builder shares /api/next's scoring, so it must share the overrides."""
    seen = []
    real = personalize.rank_next

    def spy(*a, **kw):
        seen.append(kw.get("params"))
        return real(*a, **kw)

    monkeypatch.setattr(nextsrv.personalize, "rank_next", spy)
    with nextsrv.app.app_context():                 # vibe_walk hits db() directly
        out = nextsrv.vibe_walk("aaa", 3)
    assert [t["id"] for t in out][0] == "aaa" and len(out) > 1
    assert seen and all(p == nextsrv.AUTOPLAY_PARAMS for p in seen)


def test_api_next_scores_the_tempo_term(nextsrv):
    con = sqlite3.connect(nextsrv.DB)
    con.execute("INSERT OR REPLACE INTO analysis(video_id, bpm) VALUES('aaa', 120.0)")
    con.execute("INSERT OR REPLACE INTO analysis(video_id, bpm) VALUES('bbb', 240.0)")
    con.execute("INSERT OR REPLACE INTO analysis(video_id, bpm) VALUES('ccc', 160.0)")
    con.commit()
    con.close()
    client = nextsrv.app.test_client()
    assert client.get("/api/next?id=aaa&exclude=aaa").status_code == 200
    terms = {t["id"]: t["terms"] for t in _last_trace(nextsrv)["top"]}
    assert terms["bbb"]["bpm"] == 0.0                      # 240 vs 120: double time
    # 160 vs 120 is a real gear change: the full tempo weight, in units of the vibe
    # spread across this candidate list (scale="window")
    X = _stub_emb_sim()["X"]
    u = float(np.std([X[1] @ X[0], X[2] @ X[0]]))
    assert terms["ccc"]["bpm"] == pytest.approx(-nextsrv.AUTOPLAY_PARAMS["bpm_w"] * u, abs=5e-4)


# ------------------------------------------------------------------ migration

def test_plays_table_is_migrated_in_place(tmp_path, monkeypatch):
    """An existing 4-column plays log gains the provenance columns without losing rows."""
    music = tmp_path / "OfflineMusic"
    music.mkdir()
    dbp = tmp_path / "library.db"
    _build_db(dbp, music)
    con = sqlite3.connect(dbp)
    con.execute("CREATE TABLE plays(video_id TEXT, ts REAL, event TEXT, seconds REAL)")
    con.execute("INSERT INTO plays VALUES('aaa', 1.0, 'play', 12.0)")
    con.commit()
    con.close()

    monkeypatch.setenv("PLAYER_DB", str(dbp))
    import server
    importlib.reload(server)

    con = sqlite3.connect(dbp)
    con.row_factory = sqlite3.Row
    cols = [r[1] for r in con.execute("PRAGMA table_info(plays)")]
    assert cols == ["video_id", "ts", "event", "seconds", "source", "session_id"]
    old = dict(con.execute("SELECT * FROM plays").fetchone())
    con.close()
    assert old["video_id"] == "aaa" and old["seconds"] == 12.0
    assert old["source"] is None and old["session_id"] is None
