#!/usr/bin/env python3
"""Fold a new Google Takeout export into the project's listening history.

Google only exports a rolling ~7 months of YouTube Music history, so every export is
both NEWER and SHORTER than the last one. Rebuilding seed_tracks.csv from just the
latest export silently forgets everything that scrolled out of the window. This script
keeps the history cumulative instead:

  1. every raw watch-history.json it is given is archived under data/takeout/exports/
     (named by its newest event), so later merges can always re-read the full record;
  2. all archived exports are unioned into one event log, deduped on (video_id, time) —
     overlapping windows contribute each listen exactly once;
  3. seed_tracks.csv / strong_seeds.csv are rebuilt from that log with the same
     frequency x recency score parse_takeout_history.py uses. Rows in the previous
     seed_tracks.csv whose listens are not in any archived export are carried over
     unchanged (history older than every export we still hold);
  4. data/takeout_missing.csv lists every listened track that is not in the library and
     not in the download archive, best-first — the download-queue view of the history;
  5. data/listens.csv is the deduped event log itself (video_id, UTC time, oldest first):
     the per-listen view the player's "Listen again" / "Recommended" shelves read.

Usage:
    python scripts/merge_takeout.py C:/path/to/takeout-....zip [more exports...]
    python scripts/merge_takeout.py            # just rebuild from the archive
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import sqlite3
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_takeout_history import (clean_artist, clean_title, is_music_entry,  # noqa: E402
                                   parse_time, video_id_from_url)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXPORTS = DATA / "takeout" / "exports"
SEEDS = DATA / "seed_tracks.csv"
STRONG = DATA / "strong_seeds.csv"
MISSING = DATA / "takeout_missing.csv"
LISTENS = DATA / "listens.csv"
FIELDS = ["video_id", "title", "artist", "play_count", "first_played", "last_played",
          "days_since_last", "source", "score", "url"]
WATCH = "watch-history.json"
LISTEN_FIELDS = ["video_id", "time", "artist", "title"]


def read_export(path: Path) -> list:
    """watch-history.json entries from a .zip, a directory, or the json itself."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith(WATCH)), None)
            if name is None:
                raise SystemExit(f"error: no {WATCH} inside {path}")
            return json.load(io.TextIOWrapper(z.open(name), encoding="utf-8"))
    if path.is_dir():
        hits = sorted(path.rglob(WATCH))
        if not hits:
            raise SystemExit(f"error: no {WATCH} under {path}")
        path = hits[0]
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def archive(entries: list) -> Path:
    """Store a raw export under data/takeout/exports/<newest-event-date>-watch-history.json.
    Identical re-imports land on the same name and are skipped."""
    newest = max((e.get("time", "") for e in entries), default="")
    stamp = (newest[:10] or "undated").replace("-", "")
    EXPORTS.mkdir(parents=True, exist_ok=True)
    dest = EXPORTS / f"{stamp}-{len(entries)}-{WATCH}"
    if not dest.exists():
        dest.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return dest


def music_events(entries: list):
    """(video_id, time_str, datetime, entry) for every YouTube Music listen (ads dropped)."""
    for e in entries:
        if e.get("details") and any(d.get("name") == "From Google Ads" for d in e["details"]):
            continue
        if not is_music_entry(e):
            continue
        vid = video_id_from_url(e.get("titleUrl", ""))
        raw = e.get("time", "")
        t = parse_time(raw)
        if vid and t:
            yield vid, raw, t, e


def aggregate(paths: list, halflife_days: float, now: datetime):
    """Union the exports, dedupe on (video_id, time), roll up per track. Returns
    (rows by video_id, the deduped listens as LISTEN_FIELDS dicts, oldest first)."""
    seen, tracks, events = set(), {}, []
    decay = 0.5 ** (1.0 / halflife_days)
    for p in paths:
        for vid, raw, t, e in music_events(read_export(p)):
            if (vid, raw) in seen:
                continue
            seen.add((vid, raw))
            events.append((t, vid, clean_artist(e), clean_title(e)))
            r = tracks.get(vid)
            if r is None:
                r = tracks[vid] = {"video_id": vid, "plays": 0, "first": t, "last": t,
                                   "title": clean_title(e), "artist": clean_artist(e),
                                   "url": e.get("titleUrl", "")}
            r["plays"] += 1
            r["first"] = min(r["first"], t)
            if t >= r["last"]:              # newest listen names the track
                r["last"] = t
                r["title"], r["artist"] = clean_title(e) or r["title"], clean_artist(e) or r["artist"]
    rows = {}
    for vid, r in tracks.items():
        days = max(0, (now - r["last"]).days)
        rows[vid] = {"video_id": vid, "title": r["title"], "artist": r["artist"],
                     "play_count": r["plays"], "first_played": r["first"].date().isoformat(),
                     "last_played": r["last"].date().isoformat(), "days_since_last": days,
                     "source": "music", "score": round(r["plays"] * decay ** days, 4),
                     "url": r["url"]}
    events.sort(key=lambda x: x[0])
    listens = [{"video_id": v, "time": t.astimezone(timezone.utc).isoformat(timespec="seconds"),
                "artist": a, "title": ti} for t, v, a, ti in events]
    return rows, listens


def read_csv(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list, fields: list) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exports", nargs="*", type=Path, help="new Takeout .zip / folder / watch-history.json")
    ap.add_argument("--halflife-days", type=float, default=365.0)
    ap.add_argument("--min-plays", type=int, default=3, help="strong-seed threshold")
    args = ap.parse_args(argv)

    for p in args.exports:
        if not p.exists():
            print(f"error: not found: {p}", file=sys.stderr)
            return 1
        dest = archive(read_export(p))
        print(f"archived {p.name} -> {dest.relative_to(ROOT)}")
    paths = sorted(EXPORTS.glob(f"*{WATCH}"))
    if not paths:
        print("error: no exports archived yet — pass a Takeout zip", file=sys.stderr)
        return 1

    old = read_csv(SEEDS)
    prev_last = max((r["last_played"] for r in old if r.get("last_played")), default="")
    now = datetime.now(timezone.utc)
    rows, listens = aggregate(paths, args.halflife_days, now)
    n_events = len(listens)
    carried = [r for r in old if r["video_id"] not in rows]
    for r in carried:
        rows[r["video_id"]] = r
    out = sorted(rows.values(), key=lambda r: float(r["score"]), reverse=True)

    if old:
        bak = SEEDS.with_name(f"seed_tracks.{now:%Y-%m-%d}.bak.csv")
        if not bak.exists():
            shutil.copy2(SEEDS, bak)
    write_csv(SEEDS, out, FIELDS)
    write_csv(STRONG, [r for r in out if int(r["play_count"]) >= args.min_plays], FIELDS)
    write_csv(LISTENS, listens, LISTEN_FIELDS)

    con = sqlite3.connect(f"file:{DATA / 'library.db'}?mode=ro", uri=True)
    lib = {r[0] for r in con.execute("SELECT video_id FROM tracks")}
    con.close()
    arch = DATA / "downloaded.txt"
    archived = ({ln.split()[-1] for ln in arch.read_text(encoding="utf-8").splitlines() if ln.strip()}
                if arch.exists() else set())
    missing = [r for r in out if r["video_id"] not in lib and r["video_id"] not in archived]
    write_csv(MISSING, missing, FIELDS)

    new = [r for r in out if prev_last and r["last_played"] > prev_last]
    fresh = [r for r in new if r["first_played"] > prev_last]
    print(f"exports: {len(paths)}  unique listens: {n_events:,}  tracks: {len(out):,} "
          f"(was {len(old):,}; {len(carried)} carried over from older history)")
    dated = [r["first_played"] for r in out if r["first_played"]]
    print(f"history spans {min(dated)} -> {max(r['last_played'] for r in out)}")
    if prev_last:
        print(f"since previous import ({prev_last}): {len(new):,} tracks played, "
              f"{len(fresh):,} first-time; in library {sum(r['video_id'] in lib for r in fresh):,}")
    print(f"in library: {sum(r['video_id'] in lib for r in out):,}   missing (not downloaded, "
          f"not in archive): {len(missing):,} -> {MISSING.relative_to(ROOT)}")
    print(f"wrote {SEEDS.relative_to(ROOT)}, {STRONG.relative_to(ROOT)}, {LISTENS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
