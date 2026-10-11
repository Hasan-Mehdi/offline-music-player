#!/usr/bin/env python3
"""Merge Haiku artist-genre chunk outputs -> data/artist_genre.csv (artist,genre)."""
import collections
import csv
import json
from pathlib import Path

recs = {}
for f in sorted(Path("data/artist_chunks").glob("out_*.json")):
    try:
        for o in json.loads(f.read_text(encoding="utf-8")):
            a = o.get("artist")
            if a:
                recs[a] = (o.get("genre") or "other").strip().lower()
    except Exception as e:
        print("bad", f.name, str(e)[:60])

with open("data/artist_genre.csv", "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["artist", "genre"])
    for a, g in recs.items():
        w.writerow([a, g])

print(f"{len(recs)} artists labeled")
for g, c in collections.Counter(recs.values()).most_common():
    print(f"  {c:>4}  {g}")
print("wrote data/artist_genre.csv")
