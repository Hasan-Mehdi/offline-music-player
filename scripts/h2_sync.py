r"""Bring the H2's play log home: /.coda/plays.omp on the card -> the PC `plays` table.

  .venv\Scripts\python scripts\h2_sync.py --card E:\            # sync (idempotent)
  .venv\Scripts\python scripts\h2_sync.py --card E:\ --dry-run  # just show what's new

The card's log starts as a copy of the PC history (h2_assets.build_plays) and the device
appends to it. A record is "from the device" when no PC row has the same song, event and
timestamp, so re-running never duplicates anything. export_h2.py runs this before it
rebuilds the pack (the indexes in plays.omp only mean something against the card's
current ids.bin) and before it rewrites plays.omp.

Clocks: Rockbox's RTC has no time zone and its mktime() treats the wall clock as UTC, so
a device timestamp is "local wall time as if it were UTC". build_plays writes PC rows in
that convention (to_device_ts) and this undoes it (from_device_ts). Rows from before the
RTC was set (2014 dates) are dropped.
"""
import argparse
import sqlite3
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from h2_layout import short_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "library.db"
EVENT_NAMES = {0: "play", 1: "complete", 2: "skip", 3: "like", 4: "dislike", 5: "peek", 6: "unlike",
               7: "switch"}
RTC_SANE = 1_735_689_600        # 2025-01-01: anything older is an unset clock
SESSION_GAP = 30 * 60


def utc_offset(ts):
    """Local UTC offset (seconds) at epoch ts, DST-aware."""
    return datetime.fromtimestamp(ts).astimezone().utcoffset().total_seconds()


def to_device_ts(ts):
    return ts + utc_offset(ts)


def from_device_ts(ts):
    return ts - utc_offset(ts - utc_offset(ts))


def read_log(path):
    b = Path(path).read_bytes()
    if b[:4] != b"OMP1":
        raise SystemExit(f"{path}: not an OMP1 play log")
    n = (len(b) - 4) // 20
    return [struct.unpack_from("<dIfB3x", b, 4 + 20 * i) for i in range(n)]


def read_ids(pack_dir):
    import json
    n = json.loads((pack_dir / "pack.json").read_text())["tracks"]
    ids = (pack_dir / "ids.bin").read_bytes()
    return [ids[i * 11:(i + 1) * 11].decode() for i in range(n)]


def device_rows(card, con):
    """The card's log records that are not already PC rows, as plays-table tuples."""
    coda = Path(card) / ".coda"
    if not (coda / "plays.omp").exists() or not (coda / "pack" / "ids.bin").exists():
        return []
    vids = read_ids(coda / "pack")
    long_of = {short_id(v): v for (v,) in con.execute("SELECT video_id FROM tracks")}
    known = {}
    for vid, ts, ev in con.execute("SELECT video_id, ts, event FROM plays"):
        known.setdefault((vid, ev), []).append(ts)

    def is_known(vid, ev, *cands):
        return any(abs(t - c) < 0.01 for t in known.get((vid, ev), ()) for c in cands)

    out, dropped = [], 0
    for ts_dev, idx, sec, ev in read_log(coda / "plays.omp"):
        if idx >= len(vids) or ev not in EVENT_NAMES or vids[idx] not in long_of:
            dropped += 1
            continue
        vid, name = long_of[vids[idx]], EVENT_NAMES[ev]
        # cards exported before the clock convention hold raw PC timestamps
        if is_known(vid, name, ts_dev, from_device_ts(ts_dev)):
            continue
        if ts_dev < RTC_SANE:
            dropped += 1
            continue
        out.append((vid, from_device_ts(ts_dev), name, None if sec < 0 else float(sec)))
    if dropped:
        print(f"  sync: dropped {dropped} unusable records (unknown index/event or unset clock)")
    # device sessions: split on 30 min of silence
    rows, sid, last = [], None, None
    for vid, ts, name, sec in sorted(out, key=lambda r: r[1]):
        if last is None or ts - last > SESSION_GAP:
            sid = f"h2-{int(ts)}"
        last = ts
        rows.append((vid, ts, name, sec, "h2", sid))
    return rows


def sync(card, dry_run=False):
    con = sqlite3.connect(DB, timeout=30)
    rows = device_rows(card, con)
    for vid, ts, name, sec, _, sid in rows[:12]:
        print(f"  {datetime.fromtimestamp(ts):%Y-%m-%d %H:%M:%S}  {name:8s} {vid}  {sec}")
    if len(rows) > 12:
        print(f"  ... {len(rows) - 12} more")
    if rows and not dry_run:
        with con:
            con.executemany("INSERT INTO plays(video_id, ts, event, seconds, source, session_id) "
                            "VALUES (?,?,?,?,?,?)", rows)
    con.close()
    print(f"  sync: {len(rows)} device events {'found' if dry_run else 'added to the PC plays table'}")
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    sync(a.card, a.dry_run)
    print(f"  ({time.time() - t0:.1f}s)")


if __name__ == "__main__":
    main()
