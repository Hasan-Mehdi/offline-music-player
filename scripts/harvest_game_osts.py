#!/usr/bin/env python3
"""Harvest OFFICIAL game soundtracks from YouTube Music — the actual in-game music as
released, not fan arrangements (those already come in via the playlist/radio harvest).

For each game below it searches YT Music albums, keeps albums whose title looks like the
official soundtrack of that game, and pulls every track (videoId + clean title/artist +
duration). Output -> data/game_ost_candidates.csv, ready to merge into the queue or feed
straight to the downloader:

    .venv\\Scripts\\python scripts/harvest_game_osts.py
    powershell -File scripts\\download.ps1 -InputCsv data\\game_ost_candidates.csv

Tracks shorter than --min-duration (default 30s) are dropped here too, matching the
global cutoff. Already-downloaded ids (data/downloaded.txt) are skipped.

ADD MORE GAMES by editing GAMES below: ("display name", "search query", regex the album
title must match). Keep the regex tight so you get the right game's OST, not a remix album.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

try:
    from ytmusicapi import YTMusic
except ImportError:
    print("error: ytmusicapi not installed. Run: .venv\\Scripts\\python -m pip install ytmusicapi",
          file=sys.stderr)
    raise SystemExit(1)

# (display, search query, album-title match regex). The regex guards against pulling a
# fan-remix album that happens to rank for the query.
GAMES = [
    ("Pokémon Legends: Arceus", "Pokémon Legends Arceus Original Soundtrack", r"arceus"),
    ("Pokémon Emerald",          "Pokémon Emerald Original Soundtrack",        r"emerald|ruby.*sapphire|advanced generation"),
    ("Pokémon Diamond/Pearl",    "Pokémon Diamond Pearl Super Music Collection", r"diamond|pearl|platinum|sinnoh"),
    ("Pokémon Platinum",         "Pokémon Platinum Original Soundtrack",       r"platinum|diamond|pearl|sinnoh"),
    ("Pokémon Scarlet/Violet",   "Pokémon Scarlet Violet Original Soundtrack", r"scarlet|violet|paldea"),
    ("Pokémon Colosseum",        "Pokémon Colosseum Original Soundtrack",      r"colosseum|colloseum"),
    ("Mario & Luigi: Bowser's Inside Story", "Mario Luigi Bowser's Inside Story Original Soundtrack", r"bowser.?s? inside story|rpg 3"),
    ("Mario & Luigi: Dream Team", "Mario Luigi Dream Team Original Soundtrack", r"dream team|rpg 4"),
]


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def read_archive_ids(path):
    ids = set()
    if Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts:
                ids.add(parts[-1])
    return ids


def artists_str(track):
    a = track.get("artists") or []
    return ", ".join(x.get("name", "") for x in a if x.get("name")) or "Game Freak"


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", type=Path, default=Path("auth/browser.json"),
                    help="ytmusicapi auth file (optional — public search works unauthenticated)")
    ap.add_argument("--out", default="data/game_ost_candidates.csv")
    ap.add_argument("--archive", default="data/downloaded.txt")
    ap.add_argument("--min-duration", type=int, default=30)
    ap.add_argument("--albums-per-game", type=int, default=4,
                    help="album search results to consider per game (default: 4)")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between API calls")
    args = ap.parse_args(argv)

    yt = YTMusic(str(args.auth)) if args.auth.exists() else YTMusic()
    done = read_archive_ids(args.archive)

    rows, seen = [], set()
    for display, query, pat in GAMES:
        rx = re.compile(pat, re.I)
        try:
            albums = yt.search(query, filter="albums", limit=args.albums_per_game) or []
        except Exception as e:
            print(f"  [{display}] album search failed: {e}", file=sys.stderr)
            time.sleep(args.sleep)
            continue
        time.sleep(args.sleep)
        kept_game = 0
        for al in albums:
            title = al.get("title", "")
            bid = al.get("browseId")
            if not bid or not rx.search(title):
                continue
            try:
                album = yt.get_album(bid)
            except Exception as e:
                print(f"  [{display}] get_album failed for '{title}': {e}", file=sys.stderr)
                time.sleep(args.sleep)
                continue
            time.sleep(args.sleep)
            for tr in (album.get("tracks") or []):
                vid = tr.get("videoId")
                if not vid or vid in seen or vid in done:
                    continue
                dur = tr.get("duration_seconds") or 0
                if args.min_duration and dur and dur < args.min_duration:
                    continue
                seen.add(vid)
                rows.append({
                    "video_id": vid,
                    "title": tr.get("title", ""),
                    "artist": artists_str(tr),
                    "curated_freq": 0,
                    "playlist_freq": 0,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                })
                kept_game += 1
        print(f"  [{display}] kept {kept_game} tracks")

    fields = ["video_id", "title", "artist", "curated_freq", "playlist_freq", "url"]
    with open(args.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {len(rows)} official-OST tracks -> {args.out}")
    print("Merge into the queue, or download directly:")
    print(f"  powershell -File scripts\\download.ps1 -InputCsv {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
