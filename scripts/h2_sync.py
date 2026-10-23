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


def read_list_ids(path):
    """[YouTube Music id] of each list in wheel_lists.bin (CRT1; the id is its `sub`)."""
    try:
        b = Path(path).read_bytes()
    except OSError:
        return []
    if b[:4] != b"CRT1":
        return []
    n, nm, sl = struct.unpack_from("<3I", b, 4)
    strings = b[16 + 24 * n + 4 * nm:16 + 24 * n + 4 * nm + sl]
    out = []
    for i in range(n):
        sub = struct.unpack_from("<6I", b, 16 + 24 * i)[1]
        out.append(strings[sub:strings.index(b"\0", sub)].decode("utf-8"))
    return out


def device_picks(card, con):
    """The songs and Wheel lists you started yourself on the H2 (/.coda/picks.bin, written by
    firmware/ui/brain.c brain_wheel_pick: "CPK1" then {f64 ts, u32 item, u32 0}; an item is a
    pack index, or 0x80000000 | a wheel_lists.bin index) that aren't PC rows yet, as
    (key, ts, 'h2'): key a video id, or "list:<id>"."""
    coda = Path(card) / ".coda"
    try:
        b = (coda / "picks.bin").read_bytes()
    except OSError:
        return []
    if b[:4] != b"CPK1" or not (coda / "pack" / "ids.bin").exists():
        return []
    vids = read_ids(coda / "pack")
    lists = read_list_ids(coda / "wheel_lists.bin")
    long_of = {short_id(v): v for (v,) in con.execute("SELECT video_id FROM tracks")}
    have = {(k, round(ts, 2)) for k, ts in con.execute("SELECT key, ts FROM picks")}
    out = []
    for o in range(4, len(b) - 15, 16):
        ts_dev, item = struct.unpack_from("<dI", b, o)
        if ts_dev < RTC_SANE:
            continue
        if item & 0x80000000:
            i = item & 0x7FFFFFFF
            key = f"list:{lists[i]}" if i < len(lists) else None
        else:
            key = long_of.get(vids[item]) if item < len(vids) else None
        ts = from_device_ts(ts_dev)
        if key and (key, round(ts, 2)) not in have:
            out.append((key, ts, "h2"))
    return out


def sync(card, dry_run=False):
    con = sqlite3.connect(DB, timeout=30)
    con.execute("CREATE TABLE IF NOT EXISTS picks(key TEXT, ts REAL, source TEXT)")
    picks = device_picks(card, con)
    if picks and not dry_run:
        with con:
            con.executemany("INSERT INTO picks(key, ts, source) VALUES (?,?,?)", picks)
    if picks:
        print(f"  sync: {len(picks)} songs / lists you started on the H2 "
              f"{'found' if dry_run else 'added to the PC picks table'}")
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
