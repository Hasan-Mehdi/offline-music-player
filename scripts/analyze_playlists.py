#!/usr/bin/env python3
"""Classify the verified public playlists we harvested as OST/single-source dumps vs
genuine curated/diverse mixes. Tell = artist diversity within the playlist
(an OST or one-artist discography is dominated by a single artist; a real "favourites"
mix has many). Reads data/playlist_cache/*.json.
"""
from collections import Counter
from pathlib import Path
import json

playlists = {}
for f in Path("data/playlist_cache").glob("*.json"):
    try:
        for pl in json.loads(f.read_text(encoding="utf-8")):
            if pl.get("id") and pl["id"] not in playlists:
                playlists[pl["id"]] = [t for t in pl.get("tracks", []) if t.get("videoId")]
    except Exception:
        pass


def primary(t):
    return (t.get("artist") or "").split(",")[0].strip().lower()


buckets = {"ost": 0, "curated": 0}
ex = {"ost": [], "curated": []}
track_curated, track_ost = set(), set()
small = 0
for pid, tracks in playlists.items():
    if len(tracks) < 4:
        small += 1
        continue
    arts = Counter(primary(t) for t in tracks if primary(t))
    if not arts:
        continue
    dom, dom_n = arts.most_common(1)[0]
    top_share = dom_n / len(tracks)
    is_ost = top_share >= 0.5 or len(arts) <= 2
    key = "ost" if is_ost else "curated"
    buckets[key] += 1
    for t in tracks:
        (track_ost if is_ost else track_curated).add(t["videoId"])
    if len(ex[key]) < 8:
        ex[key].append(f"{len(tracks)}trk top={dom[:20]}({top_share:.0%}) uniq_artists={len(arts)}")

total = buckets["ost"] + buckets["curated"] or 1
only_ost = track_ost - track_curated
print(f"unique verified playlists: {len(playlists)} (skipped {small} with <4 tracks)\n")
print(f"OST / single-artist dumps : {buckets['ost']:>4}  ({buckets['ost']/total:.0%})")
print(f"curated / diverse mixes   : {buckets['curated']:>4}  ({buckets['curated']/total:.0%})\n")
print(f"candidate tracks reachable via a CURATED mix : {len(track_curated)}")
print(f"candidate tracks ONLY from OST/1-artist dumps : {len(only_ost)}")
print("\n-- example OST/single-source playlists --")
for e in ex["ost"]:
    print("  " + e)
print("\n-- example curated/diverse playlists --")
for e in ex["curated"]:
    print("  " + e)
