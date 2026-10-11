#!/usr/bin/env python3
"""Parse a Google Takeout YouTube/YouTube Music ``watch-history.json`` into a
frequency- and recency-weighted seed list for the music player project.

Usage:
    python scripts/parse_takeout_history.py path/to/watch-history.json

Outputs (written next to the input file by default):
    seed_tracks.csv   - every music track, one row per track, ranked by score
    strong_seeds.csv  - subset with play_count >= --min-plays (radio seeds)

No third-party dependencies; Python 3.8+.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

MUSIC_HEADER = "YouTube Music"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="path to watch-history.json from Takeout")
    p.add_argument("--outdir", type=Path, default=None, help="output dir (default: alongside input)")
    p.add_argument("--halflife-days", type=float, default=365.0,
                   help="recency half-life in days for the score (default: 365)")
    p.add_argument("--min-plays", type=int, default=3,
                   help="min play_count for the strong-seed list (default: 3)")
    p.add_argument("--include-youtube", action="store_true",
                   help="also include plain youtube.com watch entries (noisier; not just the Music app)")
    return p.parse_args(argv)


def video_id_from_url(url: str) -> str | None:
    if not url:
        return None
    q = parse_qs(urlparse(url).query)
    vid = q.get("v", [None])[0]
    return vid


def is_music_entry(entry: dict) -> bool:
    if entry.get("header") == MUSIC_HEADER:
        return True
    host = urlparse(entry.get("titleUrl", "")).netloc
    return host.endswith("music.youtube.com")


def clean_artist(entry: dict) -> str:
    subs = entry.get("subtitles") or []
    if not subs:
        return ""
    name = (subs[0].get("name") or "").strip()
    # YouTube auto-generates "<Artist> - Topic" channels for music.
    if name.endswith(" - Topic"):
        name = name[: -len(" - Topic")].strip()
    return name


def clean_title(entry: dict) -> str:
    title = (entry.get("title") or "").strip()
    for prefix in ("Watched ", "Listened to "):
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title


def parse_time(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        # Takeout uses RFC 3339, e.g. "2024-11-02T19:33:21.004Z"
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.input.exists():
        print(f"error: file not found: {args.input}", file=sys.stderr)
        return 1

    with args.input.open(encoding="utf-8") as fh:
        entries = json.load(fh)

    now = datetime.now(timezone.utc)
    decay = 0.5 ** (1.0 / args.halflife_days)  # per-day multiplier

    tracks: dict[str, dict] = {}
    counts: dict[str, int] = defaultdict(int)
    skipped_ads = music_count = youtube_count = 0

    for e in entries:
        # Ads and removed videos have no usable titleUrl.
        if e.get("details") and any(d.get("name") == "From Google Ads" for d in e["details"]):
            skipped_ads += 1
            continue

        music = is_music_entry(e)
        if music:
            music_count += 1
        else:
            youtube_count += 1
            if not args.include_youtube:
                continue

        vid = video_id_from_url(e.get("titleUrl", ""))
        if not vid:
            continue

        t = parse_time(e.get("time", ""))
        counts[vid] += 1
        rec = tracks.get(vid)
        if rec is None:
            tracks[vid] = {
                "video_id": vid,
                "title": clean_title(e),
                "artist": clean_artist(e),
                "url": e.get("titleUrl", ""),
                "source": "music" if music else "youtube",
                "first_played": t,
                "last_played": t,
            }
        else:
            if t and (rec["first_played"] is None or t < rec["first_played"]):
                rec["first_played"] = t
            if t and (rec["last_played"] is None or t > rec["last_played"]):
                rec["last_played"] = t

    rows = []
    for vid, rec in tracks.items():
        plays = counts[vid]
        last = rec["last_played"]
        days_since = (now - last).days if last else 9999
        recency = decay ** max(days_since, 0)
        score = plays * recency
        rows.append({
            "video_id": vid,
            "title": rec["title"],
            "artist": rec["artist"],
            "play_count": plays,
            "first_played": rec["first_played"].date().isoformat() if rec["first_played"] else "",
            "last_played": last.date().isoformat() if last else "",
            "days_since_last": days_since,
            "source": rec["source"],
            "score": round(score, 4),
            "url": rec["url"],
        })

    rows.sort(key=lambda r: r["score"], reverse=True)

    outdir = args.outdir or args.input.parent
    outdir.mkdir(parents=True, exist_ok=True)
    fields = ["video_id", "title", "artist", "play_count", "first_played",
              "last_played", "days_since_last", "source", "score", "url"]

    seed_path = outdir / "seed_tracks.csv"
    strong_path = outdir / "strong_seeds.csv"
    _write_csv(seed_path, rows, fields)
    strong = [r for r in rows if r["play_count"] >= args.min_plays]
    _write_csv(strong_path, strong, fields)

    _print_summary(entries, music_count, youtube_count, skipped_ads, rows, strong,
                   args, seed_path, strong_path)
    return 0


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _print_summary(entries, music_count, youtube_count, skipped_ads, rows, strong,
                   args, seed_path, strong_path) -> None:
    artist_plays: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["artist"]:
            artist_plays[r["artist"]] += r["play_count"]
    top_artists = sorted(artist_plays.items(), key=lambda kv: kv[1], reverse=True)[:20]
    dated = [r["last_played"] for r in rows if r["last_played"]]

    print(f"Total history entries : {len(entries):,}")
    print(f"  YouTube Music plays : {music_count:,}")
    print(f"  plain YouTube plays : {youtube_count:,} "
          f"({'included' if args.include_youtube else 'excluded — use --include-youtube to add'})")
    print(f"  ads skipped         : {skipped_ads:,}")
    print(f"Unique tracks         : {len(rows):,}")
    print(f"Strong seeds (>= {args.min_plays} plays): {len(strong):,}")
    if dated:
        print(f"Date range            : {min(dated)} -> {max(dated)}")
    print()
    print("Top artists by total plays:")
    for name, n in top_artists:
        print(f"  {n:>5}  {name}")
    print()
    print(f"Wrote {seed_path}")
    print(f"Wrote {strong_path}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
