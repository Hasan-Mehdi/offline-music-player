import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import harvest_listenbrainz as lb  # noqa: E402


def test_norm_strips_versions_and_feat():
    assert lb.norm("Stay With Me (Saxophone Cover) [Live]") == "stay with me"
    assert lb.norm("Midnight Drive feat. Kylie M Bailey") == "midnight drive"
    assert lb.norm("Miki Matsubara — 真夜中のドア") == lb.norm("Miki Matsubara — 真夜中のドア")
    assert lb.norm("Café Léon") == "cafe leon"
    assert lb.nkey("Rozen", "Gerudo Valley (Remix)") == lb.nkey("ROZEN", "Gerudo Valley")


def test_norm_unbalanced_brackets():
    assert lb.norm("Broken (mix") == "broken"
    assert lb.norm("weird) title") == "weird title"


def test_listens_from_takeout(tmp_path):
    entries = [
        {"header": "YouTube Music", "title": "Watched Boss Battle Theme",
         "titleUrl": "https://music.youtube.com/watch?v=abcdefghijk",
         "subtitles": [{"name": "Rozen - Topic"}],
         "time": "2026-01-02T03:04:05.006Z"},
        {"header": "YouTube Music", "title": "Watched an ad",
         "titleUrl": "https://music.youtube.com/watch?v=advertqqqqq",
         "subtitles": [{"name": "Brand"}],
         "details": [{"name": "From Google Ads"}],
         "time": "2026-01-02T03:05:05.006Z"},
        {"header": "YouTube", "title": "Watched some vlog",
         "titleUrl": "https://www.youtube.com/watch?v=vlogvlogvlo",
         "subtitles": [{"name": "Vlogger"}],
         "time": "2026-01-02T03:06:05.006Z"},
        {"header": "YouTube Music", "title": "Watched No Artist Entry",
         "titleUrl": "https://music.youtube.com/watch?v=noartistvid",
         "time": "2026-01-02T03:07:05.006Z"},
    ]
    p = tmp_path / "watch-history.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    got = lb.listens_from_takeout(p)
    assert len(got) == 1
    ls = got[0]
    assert ls["artist"] == "Rozen" and ls["title"] == "Boss Battle Theme"
    assert ls["vid"] == "abcdefghijk" and ls["service"] == "music.youtube.com"
    assert ls["ts"] == 1767323045


def test_to_payload_shape():
    ls = {"ts": 1767323045, "artist": "Rozen", "title": "Boss Battle Theme",
          "album": "Sins of Hyrule", "duration": 150.6, "vid": "abcdefghijk",
          "service": "local"}
    p = lb.to_payload(ls)
    assert p["listened_at"] == 1767323045
    tm = p["track_metadata"]
    assert tm["artist_name"] == "Rozen" and tm["release_name"] == "Sins of Hyrule"
    assert tm["additional_info"]["duration_ms"] == 150600
    assert tm["additional_info"]["media_player"] == "offline-music-player"
    assert "music_service" not in tm["additional_info"]
