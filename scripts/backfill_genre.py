#!/usr/bin/env python3
"""Backfill tracks.genre from data/artist_genre.csv (Haiku-labeled artist -> broad
genre). The opus files rarely carry GENRE tags, so the DB column has been empty and
genre never participated in FTS search; the UI reads the CSV at serve time instead.
Idempotent; only touches rows with an empty genre. Re-run after build_library_db.py
re-reads rows (INSERT OR REPLACE restores tag genre, i.e. empty).

Usage: python scripts/backfill_genre.py [--force]   (--force also overwrites non-empty)
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "library.db"
GENRE_CSV = ROOT / "data" / "artist_genre.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="overwrite non-empty genres too (default: fill blanks only)")
    args = ap.parse_args()

    amap = {}
    with open(GENRE_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            a, g = (r.get("artist") or "").strip().lower(), (r.get("genre") or "").strip()
            if a and g:
                amap[a] = g

    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=15000")
    where = "" if args.force else " AND (genre IS NULL OR genre='')"
    updated = 0
    for a, g in amap.items():
        cur = con.execute(
            f"UPDATE tracks SET genre=? WHERE lower(trim(artist))=?{where}", (g, a))
        updated += cur.rowcount
    con.commit()

    # full FTS rebuild so genre is searchable; cheap at this scale
    con.execute("DELETE FROM tracks_fts")
    con.execute("INSERT INTO tracks_fts (video_id,title,artist,album,genre) "
                "SELECT video_id,title,artist,album,genre FROM tracks")
    con.commit()

    n_genre = con.execute(
        "SELECT COUNT(*) FROM tracks WHERE genre IS NOT NULL AND genre!=''").fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    print(f"csv artists mapped: {len(amap)} | rows updated: {updated} | "
          f"tracks with genre: {n_genre}/{total} | FTS rebuilt")
    con.close()


if __name__ == "__main__":
    main()
