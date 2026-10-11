#!/usr/bin/env python3
"""Index the downloaded Opus library into SQLite (+ FTS5) for the player UI.

Scans the library dir, reads tags via mutagen, and writes data/library.db with:
  - tracks(video_id PK, path, title, artist, album, albumartist, genre, year,
           track_no, duration, r128_gain_db)
  - tracks_fts  (FTS5: title/artist/album/genre)  -> fast full-library search
  - aggregate views the API uses for Albums/Artists/Genres browse.

Idempotent: re-run any time to pick up newly-downloaded tracks (INSERT OR REPLACE).
Keyed by the 11-char YouTube id parsed from the filename, so it lines up with
muq_embeddings.npz / clusters.csv / vgm.csv.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

try:
    from mutagen.oggopus import OggOpus
except ImportError:
    print("error: mutagen not installed (pip install mutagen)", file=sys.stderr)
    raise SystemExit(1)

ID_RE = re.compile(r"\[([\w-]{11})\]\.opus$")


def first(tags, *keys):
    for k in keys:
        v = tags.get(k) or tags.get(k.lower()) or tags.get(k.upper())
        if v:
            return v[0] if isinstance(v, list) else str(v)
    return ""


def track_no(tags):
    raw = first(tags, "TRACKNUMBER", "tracknumber")
    m = re.match(r"\s*(\d+)", raw or "")
    return int(m.group(1)) if m else None


def r128_db(tags):
    """Opus R128 track gain tag (Q7.8 fixed-point dB) -> float dB, if present."""
    raw = first(tags, "R128_TRACK_GAIN")
    try:
        return int(raw) / 256.0 if raw else None
    except ValueError:
        return None


def vid_for(p: Path) -> str:
    m = ID_RE.search(p.name)
    return m.group(1) if m else p.stem


def build(libdir: Path, dbpath: Path):
    dbpath.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(dbpath)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS tracks (
            video_id TEXT PRIMARY KEY, path TEXT NOT NULL,
            title TEXT, artist TEXT, album TEXT, albumartist TEXT,
            genre TEXT, year TEXT, track_no INTEGER, duration REAL, r128_gain_db REAL);
        CREATE INDEX IF NOT EXISTS ix_artist ON tracks(artist);
        CREATE INDEX IF NOT EXISTS ix_album  ON tracks(album);
        CREATE INDEX IF NOT EXISTS ix_genre  ON tracks(genre);
        CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
            video_id UNINDEXED, title, artist, album, genre, tokenize='unicode61');
    """)

    files = sorted(libdir.glob("*.opus"))
    scanned = indexed = skipped = errors = 0
    cur = con.cursor()
    for p in files:
        scanned += 1
        vid = vid_for(p)
        cur.execute("SELECT path, r128_gain_db FROM tracks WHERE video_id=?", (vid,))
        row = cur.fetchone()
        if row and row[0] == str(p) and row[1] is not None:
            skipped += 1
            continue  # already indexed with loudness, unchanged path
        # (rows without r128_gain_db are re-read so a scan_loudness.py pass
        #  after indexing still lands in the DB on the next run)
        try:
            f = OggOpus(str(p))
            t = f.tags or {}
            rec = (vid, str(p),
                   first(t, "TITLE") or p.stem, first(t, "ARTIST"),
                   first(t, "ALBUM"), first(t, "ALBUMARTIST", "ALBUM ARTIST"),
                   first(t, "GENRE"), first(t, "DATE", "YEAR"),
                   track_no(t), round(f.info.length, 1) if f.info else None, r128_db(t))
        except Exception as e:
            errors += 1
            print(f"  tag read failed: {p.name}: {e}", file=sys.stderr)
            continue
        # explicit columns: the table may carry extra ALTER-added columns
        # (album_gain_db, ...) that this indexer doesn't own; REPLACE resets
        # them to NULL for re-read rows — re-run scripts/album_gain.py after.
        cur.execute("INSERT OR REPLACE INTO tracks (video_id,path,title,artist,album,"
                    "albumartist,genre,year,track_no,duration,r128_gain_db) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rec)
        cur.execute("DELETE FROM tracks_fts WHERE video_id=?", (vid,))
        cur.execute("INSERT INTO tracks_fts (video_id,title,artist,album,genre) VALUES (?,?,?,?,?)",
                    (vid, rec[2], rec[3], rec[4], rec[6]))
        indexed += 1
        if indexed % 1000 == 0:
            con.commit()
            print(f"  indexed {indexed}...")
    con.commit()

    n = cur.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    na = cur.execute("SELECT COUNT(DISTINCT artist) FROM tracks WHERE artist<>''").fetchone()[0]
    nal = cur.execute("SELECT COUNT(DISTINCT album) FROM tracks WHERE album<>''").fetchone()[0]
    ng = cur.execute("SELECT COUNT(DISTINCT genre) FROM tracks WHERE genre<>''").fetchone()[0]
    print(f"\nscanned {scanned} files | indexed {indexed} new/changed | skipped {skipped} | errors {errors}")
    print(f"library.db: {n} tracks | {na} artists | {nal} albums | {ng} genres -> {dbpath}")
    con.close()


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--libdir", type=Path, default=Path(r"D:\OfflineMusic"))
    ap.add_argument("--db", type=Path, default=Path("data/library.db"))
    ap.add_argument("--search", help="run a quick FTS test query and exit")
    args = ap.parse_args(argv)
    if args.search:
        con = sqlite3.connect(args.db)
        rows = con.execute(
            "SELECT t.artist, t.title, t.album FROM tracks_fts f JOIN tracks t ON t.video_id=f.video_id "
            "WHERE tracks_fts MATCH ? ORDER BY bm25(tracks_fts) LIMIT 12", (args.search,)).fetchall()
        for a, ti, al in rows:
            print(f"  {a} - {ti}  [{al}]")
        return 0
    if not args.libdir.exists():
        print(f"error: {args.libdir} not found", file=sys.stderr)
        return 1
    build(args.libdir, args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
