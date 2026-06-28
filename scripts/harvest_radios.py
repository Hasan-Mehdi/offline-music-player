#!/usr/bin/env python3
"""Expand a seed set of tracks into a co-occurrence-ranked candidate pool by
draining YouTube Music song radios, via ytmusicapi.

Each seed track has a "radio" (autoplay queue) of algorithmically-related songs.
We fetch the radio for every seed, then rank every candidate by how many
*distinct* seeds' radios it appears in -- a song surfaced by 15 of your favourites
is far more "you" than one surfaced by a single seed. This reconstructs a personal
relevance ranking out of YouTube's pairwise associations, on your own account.

Auth: requires an ytmusicapi auth file. Easiest is browser auth:
    .venv\\Scripts\\ytmusicapi browser     # paste request headers; writes browser.json
then move it to auth/browser.json (or pass --auth).

Seeds (pick one):
    --seeds data/strong_seeds.csv   # from parse_takeout_history.py (uses video_id col)
    --from-library                  # pull liked songs + library straight from the API

Output:
    data/candidates.csv  ranked by co_occurrence (distinct seed radios containing it)

Resumable: each seed's radio is cached under data/radio_cache/, so a re-run after a
rate-limit interruption skips already-fetched seeds.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

try:
    from ytmusicapi import YTMusic
except ImportError:
    print("error: ytmusicapi not installed. Run: .venv\\Scripts\\python -m pip install ytmusicapi",
          file=sys.stderr)
    raise SystemExit(1)


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--auth", type=Path, default=Path("auth/browser.json"),
                   help="ytmusicapi auth file (default: auth/browser.json)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--seeds", type=Path,
                     help="CSV with a video_id column (e.g. data/strong_seeds.csv)")
    src.add_argument("--from-library", action="store_true",
                     help="seed from liked songs + library instead of a CSV")
    p.add_argument("--per-seed-limit", type=int, default=50,
                   help="tracks to pull per radio (default: 50)")
    p.add_argument("--max-seeds", type=int, default=None,
                   help="cap number of seeds (for a quick test run)")
    p.add_argument("--likes-limit", type=int, default=500,
                   help="liked/library songs to pull with --from-library (default: 500)")
    p.add_argument("--sleep", type=float, default=1.0,
                   help="seconds between API calls (default: 1.0) -- be gentle")
    p.add_argument("--outdir", type=Path, default=Path("data"))
    return p.parse_args(argv)


def connect(auth_path):
    if not auth_path.exists():
        print(f"error: auth file not found: {auth_path}\n"
              f"Set up browser auth:\n"
              f"  .venv\\Scripts\\ytmusicapi browser\n"
              f"then move the generated browser.json to {auth_path}", file=sys.stderr)
        raise SystemExit(1)
    return YTMusic(str(auth_path))


def artists_str(track):
    arts = track.get("artists") or []
    names = [a.get("name", "").strip() for a in arts if isinstance(a, dict) and a.get("name")]
    return ", ".join(names)


def album_str(track):
    alb = track.get("album")
    return alb.get("name", "") if isinstance(alb, dict) else ""


def seeds_from_csv(path):
    seeds = []
    with path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            vid = (row.get("video_id") or "").strip()
            if vid:
                seeds.append({"videoId": vid, "title": row.get("title", ""),
                              "artist": row.get("artist", "")})
    return seeds


def seeds_from_library(yt, likes_limit):
    seeds = {}
    try:
        liked = yt.get_liked_songs(limit=likes_limit)
        for t in liked.get("tracks", []):
            vid = t.get("videoId")
            if vid:
                seeds[vid] = {"videoId": vid, "title": t.get("title", ""),
                              "artist": artists_str(t)}
    except Exception as e:
        print(f"warning: get_liked_songs failed: {e}", file=sys.stderr)
    try:
        for t in yt.get_library_songs(limit=likes_limit):
            vid = t.get("videoId")
            if vid and vid not in seeds:
                seeds[vid] = {"videoId": vid, "title": t.get("title", ""),
                              "artist": artists_str(t)}
    except Exception as e:
        print(f"warning: get_library_songs failed: {e}", file=sys.stderr)
    return list(seeds.values())


def fetch_radio(yt, video_id, limit, cache_dir):
    cache_file = cache_dir / f"{video_id}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8")), True
        except Exception:
            pass  # corrupt cache -> refetch
    res = yt.get_watch_playlist(videoId=video_id, radio=True, limit=limit)
    tracks = res.get("tracks", []) if isinstance(res, dict) else []
    cache_file.write_text(json.dumps(tracks, ensure_ascii=False), encoding="utf-8")
    return tracks, False


def main(argv):
    args = parse_args(argv)
    yt = connect(args.auth)

    if args.from_library:
        print("Pulling seeds from your library (liked songs + library)...")
        seeds = seeds_from_library(yt, args.likes_limit)
    elif args.seeds:
        if not args.seeds.exists():
            print(f"error: seeds file not found: {args.seeds}", file=sys.stderr)
            return 1
        seeds = seeds_from_csv(args.seeds)
    else:
        print("error: choose --seeds <csv> or --from-library", file=sys.stderr)
        return 1

    if args.max_seeds:
        seeds = seeds[: args.max_seeds]
    if not seeds:
        print("error: no seeds found", file=sys.stderr)
        return 1
    print(f"Seeds: {len(seeds)}")

    cache_dir = args.outdir / "radio_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cands = {}                                   # videoId -> aggregate record
    seed_ids = {s["videoId"] for s in seeds}
    fetched = cached = errors = 0

    for i, s in enumerate(seeds, 1):
        try:
            tracks, from_cache = fetch_radio(yt, s["videoId"], args.per_seed_limit, cache_dir)
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(seeds)}] {s['videoId']} radio failed: {e}", file=sys.stderr)
            continue
        cached += from_cache
        fetched += not from_cache
        for t in tracks:
            vid = t.get("videoId")
            if not vid:
                continue
            rec = cands.get(vid)
            if rec is None:
                rec = cands[vid] = {"video_id": vid, "title": t.get("title", ""),
                                    "artist": artists_str(t), "album": album_str(t),
                                    "seeds": set(), "appearances": 0}
            rec["seeds"].add(s["videoId"])
            rec["appearances"] += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(seeds)}] seeds processed; {len(cands)} unique candidates so far")
        if not from_cache:
            time.sleep(args.sleep)

    rows = [{
        "video_id": vid,
        "title": rec["title"],
        "artist": rec["artist"],
        "album": rec["album"],
        "co_occurrence": len(rec["seeds"]),
        "appearances": rec["appearances"],
        "is_seed": vid in seed_ids,
        "url": f"https://music.youtube.com/watch?v={vid}",
    } for vid, rec in cands.items()]
    rows.sort(key=lambda r: (r["co_occurrence"], r["appearances"]), reverse=True)

    args.outdir.mkdir(parents=True, exist_ok=True)
    out = args.outdir / "candidates.csv"
    fields = ["video_id", "title", "artist", "album", "co_occurrence",
              "appearances", "is_seed", "url"]
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    multi = sum(1 for r in rows if r["co_occurrence"] >= 2)
    print()
    print(f"Seeds processed   : {len(seeds)} ({fetched} fetched, {cached} cached, {errors} errors)")
    print(f"Unique candidates : {len(rows)}  (>=2 seed radios: {multi})")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
