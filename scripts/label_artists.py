#!/usr/bin/env python3
"""Prep distinct candidate ARTISTS for Haiku genre-labeling (for genre balancing).
Genre is ~an artist property, so we label artists (cheap) not tracks. Ranks artists by
total curated_freq, writes the top ones (covering most of the queue) to
data/artist_chunks/in_NN.jsonl with a sample title for context.
Then: launch a Haiku agent per chunk -> out_NN.json, then merge_artist_genre.py.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

CH = 200
TOP = 1500
out = Path("data/artist_chunks")
out.mkdir(parents=True, exist_ok=True)
for f in list(out.glob("in_*.jsonl")) + list(out.glob("out_*.json")):
    f.unlink()


def cf(r):
    try:
        return int(r.get("curated_freq", 0) or 0)
    except ValueError:
        return 0


rows = list(csv.DictReader(open("data/playlist_candidates.csv", encoding="utf-8-sig")))
agg = defaultdict(lambda: {"score": 0, "sample": "", "n": 0})
for r in rows:
    a = (r.get("artist") or "").strip()
    if not a:
        continue
    g = agg[a]
    g["score"] += cf(r) + 1
    g["n"] += 1
    if not g["sample"]:
        g["sample"] = r.get("title", "")

artists = sorted(agg.items(), key=lambda kv: kv[1]["score"], reverse=True)[:TOP]
k = 0
for i in range(0, len(artists), CH):
    lines = [json.dumps({"artist": a, "sample": g["sample"]}, ensure_ascii=False)
             for a, g in artists[i:i + CH]]
    (out / f"in_{k:02d}.jsonl").write_text("\n".join(lines), encoding="utf-8")
    k += 1
print(f"{len(agg)} distinct artists; labeling top {len(artists)} in {k} chunks (in_00..in_{k-1:02d})")
