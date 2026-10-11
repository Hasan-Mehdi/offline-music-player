#!/usr/bin/env python3
"""Build a radio-harvest seeds CSV from the LOCAL library (data/library.db).

The original harvest mined radios for the Takeout-derived strong seeds; this widens
the net by seeding from the downloaded collection itself. Output is designed to be
passed to harvest_radios.py in ONE run together with the old seeds so co-occurrence
aggregates over everything (cached seeds cost nothing to re-include):

  order = strong_seeds.csv rows first (all cached), then new library seeds:
    1. tracks with positive play signals (like/complete), most-played first
    2. the rest of the library, round-robin by artist (spread, not artist-blocks)
  tracks whose radio is already cached under data/radio_cache/ are NOT counted
  against --max-new (they are free), but are kept in the CSV for aggregation.

Run:  .venv\\Scripts\\python scripts\\make_library_seeds.py
      .venv\\Scripts\\python scripts\\harvest_radios.py --seeds data\\library_seeds.csv --sleep 1.5
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=ROOT / "data" / "library.db")
    p.add_argument("--strong-seeds", type=Path, default=ROOT / "data" / "strong_seeds.csv")
    p.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "radio_cache")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "library_seeds.csv")
    p.add_argument("--max-new", type=int, default=1500,
                   help="cap on NEW (uncached) library seeds (default: 1500)")
    return p.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    cached = {f.stem for f in args.cache_dir.glob("*.json")} if args.cache_dir.exists() else set()

    rows, seen = [], set()

    def add(vid, title, artist):
        if vid and vid not in seen:
            rows.append({"video_id": vid, "title": title or "", "artist": artist or ""})
            seen.add(vid)
            return True
        return False

    # 1) original strong seeds first — cached, free, preserve their co-occurrence votes
    if args.strong_seeds.exists():
        with args.strong_seeds.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                add((r.get("video_id") or "").strip(), r.get("title"), r.get("artist"))
    n_strong = len(rows)

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    # 2) positively-played library tracks (likes + completes), strongest first
    positive = con.execute(
        "SELECT video_id, COUNT(*) n FROM plays WHERE event IN ('like','complete') "
        "GROUP BY video_id ORDER BY n DESC").fetchall()
    lib = {r["video_id"]: r for r in con.execute("SELECT video_id, title, artist FROM tracks")}

    new_used = 0

    def add_counted(vid, title, artist):
        nonlocal new_used
        if vid in seen:
            return
        if vid not in cached and new_used >= args.max_new:
            return
        if add(vid, title, artist) and vid not in cached:
            new_used += 1

    for r in positive:
        t = lib.get(r["video_id"])
        if t:
            add_counted(t["video_id"], t["title"], t["artist"])

    # 3) rest of the library, round-robin by artist so coverage spreads across scenes
    by_artist = defaultdict(list)
    for t in lib.values():
        if t["video_id"] not in seen:
            by_artist[(t["artist"] or "").lower()].append(t)
    queues = sorted(by_artist.values(), key=len, reverse=True)
    i = 0
    while new_used < args.max_new and any(queues):
        q = queues[i % len(queues)]
        if q:
            t = q.pop(0)
            add_counted(t["video_id"], t["title"], t["artist"])
        i += 1
        if i > 10_000_000:  # safety
            break
        if all(not q for q in queues):
            break

    with args.out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["video_id", "title", "artist"])
        w.writeheader()
        w.writerows(rows)

    print(f"strong seeds kept : {n_strong}")
    print(f"library seeds     : {len(rows) - n_strong}  (new/uncached: {new_used})")
    print(f"total             : {len(rows)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
