"""purge_apply: quarantine, then put back only some tracks."""
import sqlite3
import sys

sys.path.insert(0, "scripts")
import purge_apply  # noqa: E402


def _lib(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    db = tmp_path / "library.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tracks(video_id TEXT PRIMARY KEY, path TEXT, title TEXT, "
                "artist TEXT, album TEXT, genre TEXT)")
    con.execute("CREATE VIRTUAL TABLE tracks_fts USING fts5(video_id UNINDEXED, title, artist, "
                "album, genre)")
    con.execute("CREATE TABLE neighbors(video_id TEXT, rank INTEGER, neighbor_id TEXT, sim REAL)")
    for v in ("aaa", "bbb", "ccc"):
        f = music / f"{v}.opus"
        f.write_bytes(b"x")
        con.execute("INSERT INTO tracks VALUES(?,?,?,?,?,?)", (v, str(f), "T " + v, "A", "", ""))
        con.execute("INSERT INTO tracks_fts VALUES(?,?,?,?,?)", (v, "T " + v, "A", "", ""))
    con.commit()
    con.close()
    return music, db


def test_restore_puts_back_only_the_listed_tracks(tmp_path, monkeypatch):
    music, db = _lib(tmp_path)
    monkeypatch.setattr(purge_apply, "DB", db)
    monkeypatch.setattr(purge_apply, "UNDO_LOG", tmp_path / "purged_rows.jsonl")
    purge_apply.apply(["aaa", "bbb"], hard_delete=False)
    assert not (music / "aaa.opus").exists() and (music / "_purged" / "aaa.opus").exists()

    keep = tmp_path / "keep.csv"
    keep.write_text("video_id\nbbb\n", encoding="utf-8")
    purge_apply.restore(keep)

    con = sqlite3.connect(db)
    assert {r[0] for r in con.execute("SELECT video_id FROM tracks")} == {"bbb", "ccc"}
    assert {r[0] for r in con.execute("SELECT video_id FROM tracks_fts")} == {"bbb", "ccc"}
    assert (music / "bbb.opus").exists() and (music / "_purged" / "aaa.opus").exists()
    # aaa is still quarantined, so a full undo later brings it back too
    purge_apply.undo()
    assert {r[0] for r in con.execute("SELECT video_id FROM tracks")} == {"aaa", "bbb", "ccc"}
    assert (music / "aaa.opus").exists()
