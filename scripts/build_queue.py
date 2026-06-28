#!/usr/bin/env python3
"""Merge the radio-harvest pool (candidates.csv, ranked by co_occurrence — high-confidence,
no OST-dump issue) with the playlist pool (playlist_candidates.csv, curated_freq) into one
unified candidate file for curate.py. Both signals are "appeared in N taste-relevant
sources," so we put them on one scale in a curated_freq column. -> data/unified_candidates.csv
"""
import csv
from pathlib import Path


def geti(r, k):
    try:
        return int(r.get(k, 0) or 0)
    except ValueError:
        return 0


merged = {}

# radio candidates: score = co_occurrence
if Path("data/candidates.csv").exists():
    for r in csv.DictReader(open("data/candidates.csv", encoding="utf-8-sig")):
        v = r["video_id"]
        s = geti(r, "co_occurrence")
        merged[v] = {"video_id": v, "title": r.get("title", ""), "artist": r.get("artist", ""),
                     "curated_freq": s, "playlist_freq": s,
                     "is_owned": str(r.get("is_seed", "")).lower() in ("true", "1"),
                     "url": r.get("url", "")}

# playlist candidates: score = curated_freq (merge, keep max)
if Path("data/playlist_candidates.csv").exists():
    for r in csv.DictReader(open("data/playlist_candidates.csv", encoding="utf-8-sig")):
        v = r["video_id"]
        cf = geti(r, "curated_freq")
        if v in merged:
            merged[v]["curated_freq"] = max(merged[v]["curated_freq"], cf)
            merged[v]["playlist_freq"] = max(merged[v]["playlist_freq"], geti(r, "playlist_freq"))
        else:
            merged[v] = {"video_id": v, "title": r.get("title", ""), "artist": r.get("artist", ""),
                         "curated_freq": cf, "playlist_freq": geti(r, "playlist_freq"),
                         "is_owned": str(r.get("is_owned", "")).lower() in ("true", "1"),
                         "url": r.get("url", "")}

rows = sorted(merged.values(), key=lambda r: r["curated_freq"], reverse=True)
with open("data/unified_candidates.csv", "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["video_id", "title", "artist", "curated_freq",
                                       "playlist_freq", "is_owned", "url"])
    w.writeheader()
    w.writerows(rows)
print(f"merged {len(rows)} unique candidates (radio + playlist) -> data/unified_candidates.csv")
