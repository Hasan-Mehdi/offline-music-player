#!/usr/bin/env python3
"""Remove already-downloaded tracks shorter than --min-duration seconds (jingles, SFX,
stingers, broken stubs). Dry-run by default — pass --apply to actually delete.

Reads Opus duration straight from the file header via mutagen (fast, no ffprobe). Skips
files modified in the last 2 minutes so it never races an in-progress download. Deleted
ids stay in the download archive (data/downloaded.txt) on purpose, so they are NOT
re-fetched on the next run (the downloader's --min-duration filter would reject them
anyway). Also drops the rows from data/library.db if present.

Usage:
    .venv\\Scripts\\python scripts/prune_short.py                     # dry-run report
    .venv\\Scripts\\python scripts/prune_short.py --apply             # delete them
    .venv\\Scripts\\python scripts/prune_short.py --min-duration 45 --apply
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

from mutagen.oggopus import OggOpus

ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]\.opus$")


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="D:\\OfflineMusic")
    ap.add_argument("--min-duration", type=int, default=30)
    ap.add_argument("--db", default="data/library.db")
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry-run)")
    ap.add_argument("--quiet-skip-recent", type=int, default=120,
                    help="ignore files modified in the last N seconds (in-progress dl)")
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    if not outdir.exists():
        print(f"error: {outdir} not found", file=sys.stderr)
        return 1

    now = time.time()
    short, unreadable, scanned = [], 0, 0
    for f in outdir.glob("*.opus"):
        scanned += 1
        if now - f.stat().st_mtime < args.quiet_skip_recent:
            continue
        try:
            dur = OggOpus(str(f)).info.length
        except Exception:
            unreadable += 1
            continue
        if dur < args.min_duration:
            short.append((f, dur))

    short.sort(key=lambda t: t[1])
    print(f"scanned {scanned} opus files | under {args.min_duration}s: {len(short)} "
          f"| unreadable (skipped): {unreadable}")
    for f, dur in short[:40]:
        print(f"  {dur:5.1f}s  {f.name}")
    if len(short) > 40:
        print(f"  ... and {len(short) - 40} more")

    if not args.apply:
        print("\nDRY RUN — nothing deleted. Re-run with --apply to remove these.")
        return 0
    if not short:
        return 0

    ids = {m.group(1) for f, _ in short if (m := ID_RE.search(f.name))}
    deleted = 0
    for f, _ in short:
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            print(f"  could not delete {f.name}: {e}", file=sys.stderr)

    db = Path(args.db)
    if db.exists() and ids:
        con = sqlite3.connect(str(db))
        con.executemany("DELETE FROM tracks WHERE video_id=?", [(i,) for i in ids])
        con.commit()
        con.close()

    print(f"\nDeleted {deleted} short files. (Left their ids in the archive so they "
          f"won't re-download.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
