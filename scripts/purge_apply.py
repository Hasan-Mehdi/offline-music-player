#!/usr/bin/env python3
"""Apply a reviewed purge list: QUARANTINE tracks out of the library (reversible).

Takes the drop list exported from data/purge_review.html (a CSV with a video_id
column, or one id per line). For each track:
  * moves the audio file into <music dir>\\_purged\\ (same drive -> instant move)
  * removes its rows from tracks + tracks_fts + neighbors in library.db
  * records the full original row in data/purged_rows.jsonl (this is the undo log)

Deliberately KEPT: the plays log (history stays meaningful) and the id in
downloaded.txt (so the downloader never re-fetches purged tracks). The MuQ NPZ and
neighbors for remaining tracks are untouched — the server gates everything through
library.db, and embeddings get rebuilt by the normal pipeline anyway.

A track's DB row is only removed if its file was moved successfully (or was
already missing) — no ghost rows, no orphan files.

Usage:
  .venv\\Scripts\\python scripts\\purge_apply.py data\\purge_drop.csv          # quarantine
  .venv\\Scripts\\python scripts\\purge_apply.py data\\purge_drop.csv --delete # no quarantine, gone
  .venv\\Scripts\\python scripts\\purge_apply.py --undo                        # restore everything
Stop or pause the player server first if it is mid-stream on a purged track —
Windows will refuse to move an open file (those rows are skipped and reported;
rerun after).
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "library.db"
UNDO_LOG = ROOT / "data" / "purged_rows.jsonl"


def read_ids(path):
    ids = []
    with open(path, encoding="utf-8-sig") as f:
        first = f.readline().strip()
        cols = first.split(",")
        if "video_id" in cols:
            f.seek(0)
            ids = [r["video_id"] for r in csv.DictReader(f) if r.get("video_id")]
        else:
            if first and "," not in first:
                ids.append(first)
            ids += [ln.strip() for ln in f if ln.strip()]
    return list(dict.fromkeys(ids))


def apply(ids, hard_delete):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    moved = skipped = missing = 0
    qdir = None
    log = open(UNDO_LOG, "a", encoding="utf-8")
    for vid in ids:
        r = con.execute("SELECT * FROM tracks WHERE video_id=?", (vid,)).fetchone()
        if not r:
            missing += 1
            continue
        src = Path(r["path"])
        dst = None
        if src.exists():
            if hard_delete:
                try:
                    src.unlink()
                except OSError as e:
                    print(f"  SKIP (file busy?) {r['artist']} - {r['title']}: {e}")
                    skipped += 1
                    continue
            else:
                if qdir is None:
                    qdir = src.parent / "_purged"
                    qdir.mkdir(exist_ok=True)
                dst = qdir / src.name
                try:
                    shutil.move(str(src), str(dst))
                except OSError as e:
                    print(f"  SKIP (file busy?) {r['artist']} - {r['title']}: {e}")
                    skipped += 1
                    continue
        log.write(json.dumps({"ts": time.time(), "row": dict(r),
                              "quarantined_to": str(dst) if dst else None},
                             ensure_ascii=False) + "\n")
        con.execute("DELETE FROM tracks WHERE video_id=?", (vid,))
        con.execute("DELETE FROM tracks_fts WHERE video_id=?", (vid,))
        con.execute("DELETE FROM neighbors WHERE video_id=? OR neighbor_id=?", (vid, vid))
        moved += 1
    con.commit()
    log.close()
    what = "deleted" if hard_delete else f"quarantined to {qdir}"
    print(f"\n{moved} tracks {what}; {skipped} skipped (rerun for those); "
          f"{missing} ids not in library.")
    if moved and not hard_delete:
        print(f"undo anytime:  python scripts\\purge_apply.py --undo")


def undo():
    if not UNDO_LOG.exists():
        print("nothing to undo")
        return
    con = sqlite3.connect(DB)
    entries = [json.loads(ln) for ln in open(UNDO_LOG, encoding="utf-8") if ln.strip()]
    restored = 0
    for e in entries:
        row, q = e["row"], e.get("quarantined_to")
        if q and Path(q).exists() and not Path(row["path"]).exists():
            shutil.move(q, row["path"])
        if not con.execute("SELECT 1 FROM tracks WHERE video_id=?",
                           (row["video_id"],)).fetchone():
            cols = ",".join(row)
            con.execute(f"INSERT INTO tracks({cols}) VALUES({','.join('?'*len(row))})",
                        tuple(row.values()))
            con.execute("INSERT INTO tracks_fts(video_id,title,artist,album,genre) "
                        "VALUES(?,?,?,?,?)",
                        (row["video_id"], row["title"] or "", row["artist"] or "",
                         row["album"] or "", row["genre"] or ""))
            restored += 1
    con.commit()
    UNDO_LOG.rename(UNDO_LOG.with_suffix(".jsonl.done"))
    print(f"restored {restored} tracks (neighbors rows are rebuilt by the pipeline)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("drop_list", nargs="?", help="CSV from the review page")
    ap.add_argument("--delete", action="store_true", help="hard delete, no quarantine")
    ap.add_argument("--undo", action="store_true", help="restore from the undo log")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.undo:
        return undo()
    if not args.drop_list:
        print("usage: purge_apply.py <drop_list.csv>  (or --undo)")
        return 1
    ids = read_ids(args.drop_list)
    print(f"{len(ids)} tracks in drop list")
    apply(ids, args.delete)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
