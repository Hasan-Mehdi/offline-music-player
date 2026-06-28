#!/usr/bin/env python3
"""Curate the playlist candidate pool into a ranked download queue (Option A).

Ranks by CURATED_FREQ = how many genuine curated/diverse playlists a track appears in
(OST / single-artist dumps are ignored), so the queue is real human cross-taste
discovery, not OST-completion. Then: drop owned, version-preserving dedupe, artist cap.

Output: data/download_queue.csv  ->  download_tracks.py --input data/download_queue.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s)).strip()


def geti(r, k):
    try:
        return int(r.get(k, 0) or 0)
    except ValueError:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/playlist_candidates.csv")
    ap.add_argument("--out", default="data/download_queue.csv")
    ap.add_argument("--archive", default="data/downloaded.txt")
    ap.add_argument("--artist-cap", type=int, default=35)
    ap.add_argument("--min-curated-freq", type=int, default=1,
                    help="keep only tracks in >= this many curated (non-OST) playlists; "
                         "1 = drop OST-dump-only tracks (recommended), 0 = keep all")
    ap.add_argument("--max-genre-frac", type=float, default=0.30,
                    help="cap any genre to this fraction of the queue (needs data/artist_genre.csv)")
    ap.add_argument("--rap-cap-frac", type=float, default=0.12, help="tighter cap for rap/hip-hop")
    ap.add_argument("--vgm-cap-frac", type=float, default=0.15,
                    help="cap video-game-music/chiptune/orchestral covers (genre- AND title-detected); "
                         "user wants VGM present but not dominant")
    args = ap.parse_args()

    arch = set()
    if Path(args.archive).exists():
        for l in Path(args.archive).read_text(encoding="utf-8").splitlines():
            if l.strip():
                arch.add(l.split()[-1])

    rows = list(csv.DictReader(open(args.input, encoding="utf-8-sig")))
    n0 = len(rows)
    rows = [r for r in rows if r["video_id"] not in arch
            and str(r.get("is_owned", "")).lower() not in ("true", "1")]
    n1 = len(rows)
    rows = [r for r in rows if geti(r, "curated_freq") >= args.min_curated_freq]
    n2 = len(rows)

    rank = lambda r: (geti(r, "curated_freq"), geti(r, "playlist_freq"))

    best = {}
    for r in sorted(rows, key=rank, reverse=True):
        a, t = norm(r.get("artist", "")), norm(r.get("title", ""))
        key = (a, t) if (a or t) else ("", r["video_id"])
        best.setdefault(key, r)
    deduped = list(best.values())
    n3 = len(deduped)

    by_artist = defaultdict(list)
    for r in sorted(deduped, key=rank, reverse=True):
        by_artist[norm(r.get("artist", "")) or r["video_id"]].append(r)
    capped = [r for lst in by_artist.values() for r in lst[:args.artist_cap]]
    capped.sort(key=rank, reverse=True)
    n4 = len(capped)

    # genre + VGM caps and diverse ordering.
    ag = {}
    if Path("data/artist_genre.csv").exists():
        for r in csv.DictReader(open("data/artist_genre.csv", encoding="utf-8-sig")):
            ag[norm(r["artist"])] = (r.get("genre") or "other").strip().lower()

    # VGM is detected two ways: the artist's labeled genre, OR high-precision title markers
    # (a labeled "(From '<game>')", an explicit OST/chiptune/8-bit tag, or a named franchise).
    # Kept deliberately narrow so generic remixes/covers/"theme" tracks are NOT swept in.
    VGM_GENRE = ("video game", "vgm", "chiptune", "orchestral", "soundtrack")
    VGM_TITLE = re.compile(
        r'(\(from ["\']|from ["\'][^"\']*(zelda|pok|mario|sonic|final fantasy|kirby|undertale|'
        r'deltarune|nintendo|persona|splatoon|smash|metroid|chrono|kingdom hearts|mega ?man|'
        r'castlevania|donkey kong|earthbound|xenoblade)|original soundtrack|\bost\b|\bchiptune\b|'
        r'8-?bit|\bvgm\b|game ?boy|\bnes\b|\bsnes\b|piano collection)', re.I)

    def genre_of(r):
        g = ag.get(norm(r.get("artist", "")), "other")
        if any(x in g for x in VGM_GENRE) or VGM_TITLE.search(f"{r.get('title','')} {r.get('artist','')}"):
            return "video game music"
        if any(x in g for x in ("rap", "hip hop", "hip-hop", "trap")):
            return "hip hop"
        return g

    N = len(capped)
    caps = {"video game music": int(args.vgm_cap_frac * N), "hip hop": int(args.rap_cap_frac * N)}
    dcap = int(args.max_genre_frac * N)
    kept, seen = [], defaultdict(int)
    for r in sorted(capped, key=rank, reverse=True):
        g = genre_of(r)
        if seen[g] < max(caps.get(g, dcap), 1):
            kept.append(r)
            seen[g] += 1
    capped = kept
    n5 = len(capped)

    # Round-robin the genres so the DOWNLOAD ORDER is diverse from the very first track
    # (raw curated_freq otherwise front-loads thousands of VGM covers, which the user
    # explicitly does not want — and many are DRM dead-ends that waste rate budget).
    buckets = defaultdict(list)
    for r in sorted(capped, key=rank, reverse=True):
        buckets[genre_of(r)].append(r)
    blists = sorted(buckets.values(), key=len, reverse=True)
    capped, i = [], 0
    while True:
        added = False
        for b in blists:
            if i < len(b):
                capped.append(b[i])
                added = True
        if not added:
            break
        i += 1

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    fields = ["video_id", "title", "artist", "curated_freq", "playlist_freq", "url"]
    with open(args.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in capped:
            w.writerow({k: r.get(k, "") for k in fields})

    ac = Counter(norm(r.get("artist", "")) for r in capped)
    print(f"input {n0} | drop owned -> {n1} | curated_freq>={args.min_curated_freq} -> {n2} "
          f"| dedupe -> {n3} | artist-cap -> {n4} | genre-cap -> {n5}")
    print(f"distinct artists in queue: {len(ac)}")
    gc = Counter(genre_of(r) for r in capped)
    print("genre mix: " + ", ".join(f"{g}:{c}" for g, c in gc.most_common(12)))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
