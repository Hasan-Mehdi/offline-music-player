#!/usr/bin/env python3
r"""Compute a shared album gain per OST and store it in tracks.album_gain_db.

The player normalizes every track to -14 LUFS (attenuate-only), which is right for a
shuffle of unrelated songs but wrong inside a soundtrack: a composer's hushed menu theme
and a boss battle get pushed to the same loudness, flattening dynamics the album was
written with. Fix: one gain for the whole album, so relative loudness inside it survives.

No audio is decoded — per-track loudness is recovered from the R128 tags already scanned
into the db by scan_loudness.py:  LUFS_i = -23 - r128_gain_db_i. The album's integrated
loudness is the duration-weighted mean energy of its tracks (what a meter would read over
the concatenated album):

    album_LUFS = 10*log10( sum(dur_i * 10**(LUFS_i/10)) / sum(dur_i) )
    album_gain_db = -23 - album_LUFS

Only tracks in a qualifying OST group get a value; everything else stays NULL and the
player keeps using the per-track gain.

Run:  .venv\Scripts\python scripts\album_gain.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R128_REF = -23.0

# --- OST grouping: keep in sync with server.py (_clean_ost / _ost_name / MIN_OST_TRACKS /
# _load_ost_catalog / _ost_index). Copied rather than imported because importing server
# loads 55k embeddings. ----------------------------------------------------------------
MIN_OST_TRACKS = 4
_OST_SUFFIX = re.compile(
    r"\s*[\(\[]?\s*(original game soundtrack|original soundtrack|game soundtrack|"
    r"soundtrack|ost)\s*[\)\]]?\s*$", re.I)


def _clean_ost(base):
    """Strip trailing OST/soundtrack markers and trailing (…)/[…] tags, repeatedly."""
    s, prev = base.strip(), None
    while s and s != prev:
        prev = s
        s = _OST_SUFFIX.sub("", s).strip()
        s = re.sub(r"\s*[\(\[][^\(\)\[\]]*[\)\]]\s*$", "", s).strip()
    return s


def _ost_name(album, title):
    if album and album.strip():
        base = album.strip()
    elif " - " in title:
        base = title.rsplit(" - ", 1)[1]
    else:
        return None
    name = _clean_ost(base)
    return name if len(name) >= 3 else None


def _load_ost_catalog():
    p = ROOT / "data" / "ost_catalog.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def ost_groups(rows, catalog):
    """rows: sqlite3.Row with video_id/title/album. -> {canonical_key: [video_id,...]}
    for groups of at least MIN_OST_TRACKS, merged on the curated canonical name."""
    groups = {}
    for r in rows:
        nm = _ost_name(r["album"] or "", r["title"] or "")
        if not nm:
            continue
        ov = catalog.get(nm.lower())
        if ov is not None and not ov.get("keep", True):
            continue
        disp = (ov.get("canonical") if ov else "") or nm
        groups.setdefault(disp.lower(), []).append(r["video_id"])
    return {k: v for k, v in groups.items() if len(v) >= MIN_OST_TRACKS}


# --- loudness math ---------------------------------------------------------------------

def track_lufs(r128_gain_db):
    return R128_REF - float(r128_gain_db)


def album_lufs(members):
    """members: [(duration_s, lufs), ...] -> duration-weighted integrated loudness."""
    num = tot = 0.0
    for dur, lufs in members:
        d = float(dur or 0.0)
        if d <= 0:
            continue
        num += d * (10.0 ** (float(lufs) / 10.0))
        tot += d
    if tot <= 0:
        return None
    return 10.0 * math.log10(num / tot)


def album_gain(members):
    a = album_lufs(members)
    return None if a is None else R128_REF - a


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(ROOT / "data" / "library.db"))
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA busy_timeout=15000")
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(tracks)")}
    if "album_gain_db" not in cols and not args.dry_run:
        con.execute("ALTER TABLE tracks ADD COLUMN album_gain_db REAL")
        con.commit()
        print("added tracks.album_gain_db")

    rows = con.execute("SELECT video_id, title, album, duration, r128_gain_db "
                       "FROM tracks").fetchall()
    by_id = {r["video_id"]: r for r in rows}
    groups = ost_groups(rows, _load_ost_catalog())
    print(f"{len(rows)} tracks -> {len(groups)} OST groups (>= {MIN_OST_TRACKS} tracks)")

    updates, deltas, skipped = [], [], 0
    for key, vids in sorted(groups.items()):
        members = [(by_id[v]["duration"], track_lufs(by_id[v]["r128_gain_db"]))
                   for v in vids if by_id[v]["r128_gain_db"] is not None]
        g = album_gain(members)
        if g is None:
            skipped += 1
            continue
        for v in vids:
            tr = by_id[v]
            updates.append((g, v))
            if tr["r128_gain_db"] is not None:
                deltas.append(g - float(tr["r128_gain_db"]))

    if not args.dry_run:
        con.executemany("UPDATE tracks SET album_gain_db=? WHERE video_id=?", updates)
        con.commit()
    n = 0 if args.dry_run and "album_gain_db" not in cols else con.execute(
        "SELECT COUNT(*) FROM tracks WHERE album_gain_db IS NOT NULL").fetchone()[0]
    con.close()

    deltas.sort()
    def pct(p):
        return deltas[min(len(deltas) - 1, int(p / 100 * len(deltas)))] if deltas else 0.0
    print(f"updated {len(updates)} tracks ({n} now carry album_gain_db), "
          f"{skipped} groups without loudness")
    print("album_gain_db - r128_gain_db (dB the album gain moves each track):")
    print("  min %+.2f  p05 %+.2f  p25 %+.2f  median %+.2f  p75 %+.2f  p95 %+.2f  max %+.2f"
          % (pct(0), pct(5), pct(25), pct(50), pct(75), pct(95), pct(100)))
    if deltas:
        big = sum(1 for d in deltas if abs(d) >= 3.0)
        print(f"  |delta| >= 3 dB: {big} tracks ({big / len(deltas) * 100:.1f}%) - dynamics "
              f"per-track normalization was flattening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
