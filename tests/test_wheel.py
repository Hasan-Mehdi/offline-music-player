"""The Wheel / Listen again (player_server/wheel.py).

Run: .venv\\Scripts\\python -m pytest -q tests/test_wheel.py
"""
import sys

sys.path.insert(0, "scripts")

from player_server import wheel as W  # noqa: E402

DAY = 86400.0
NOW = 100 * DAY


def la(*items):
    out = []
    for it in items:
        if isinstance(it, str):
            out.append({"kind": "song", "id": it, "title": it})
        else:
            out.append(it)
    return out


def keys(order):
    return [it["key"] for it in order]


def test_listen_again_leads_in_its_order():
    lib = {"a", "b", "c", "z"}
    order = W.items(la("a", "b", "c"), NOW, [], ["z", "c"], lib, {}, NOW)
    assert keys(order) == ["a", "b", "c", "z"]          # the old history only fills in after


def test_history_never_lifts_a_listen_again_song():
    lib = {"a", "b"}
    order = W.items(la("a", "b"), NOW, [], ["b"], lib, {}, NOW)
    assert keys(order) == ["a", "b"]


def test_what_you_keep_starting_climbs():
    lib = {"a", "b", "c"}
    picks = [("c", NOW - DAY), ("c", NOW - 2 * DAY), ("c", NOW - 3 * DAY)]
    order = W.items(la("a", "b", "c"), NOW, picks, [], lib, {}, NOW)
    assert keys(order)[0] == "c"
    old = [("c", NOW - 90 * DAY)] * 3                     # long ago: faded
    assert keys(W.items(la("a", "b", "c"), NOW, old, [], lib, {}, NOW))[0] == "a"


def test_a_stale_listen_again_fades():
    lib = {"a", "b"}
    fresh = W.items(la("a"), NOW, [("b", NOW - DAY)], [], lib, {}, NOW)
    stale = W.items(la("a"), NOW - 60 * DAY, [("b", NOW - DAY)], [], lib, {}, NOW)
    assert keys(fresh)[0] == "a" and keys(stale)[0] == "b"


def test_albums_and_playlists_are_tiles_of_their_library_songs():
    lib = {"a", "b", "c", "d"}
    album = {"kind": "album", "id": "MPRE1", "title": "LOVELY!!!",
             "tracks": [{"video_id": v} for v in ("a", "x", "b", "c")]}
    small = {"kind": "playlist", "id": "PL2", "title": "two", "tracks": [{"video_id": "d"}, {"video_id": "y"}]}
    order = W.items(la(album, small), NOW, [], [], lib, {}, NOW)
    assert keys(order) == ["list:MPRE1"]                  # under MIN_LIST_SONGS in the library: no tile
    assert order[0]["tracks"] == ["a", "b", "c"] and order[0]["kind"] == "album"


def test_an_artist_tile_plays_their_songs_in_the_library():
    lib = {"a", "b", "c"}
    order = W.items(la({"kind": "artist", "id": "UC1", "title": "jomm"}), NOW, [], [], lib,
                    {"jomm": ["a", "b", "c"]}, NOW)
    assert order[0]["tracks"] == ["a", "b", "c"]


def test_h2_picks_are_starts_you_chose_and_kept():
    rows = [("a", 0, "play", None), ("a", 200, "complete", 200),          # first of a sitting
            ("b", 201, "play", None),                                        # autoplay after a
            ("b", 230, "switch", 29), ("c", 231, "play", None),              # you picked c ...
            ("c", 240, "skip", 9),                                           # ... and left it at 9 s
            ("d", 241, "play", None), ("d", 300, "switch", 59),              # autoplay
            ("e", 301, "play", None), ("e", 400, "complete", 99),            # picked, finished
            ("f", 5000, "play", None), ("f", 5010, "dislike", 10)]           # sitting start, disliked
    assert W.h2_picks(rows) == [("a", 0), ("e", 301)]
