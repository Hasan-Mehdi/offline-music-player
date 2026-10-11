#!/usr/bin/env python3
r"""Measure EBU R128 loudness for every library track and write R128_TRACK_GAIN tags.

This is the "measure" half of YouTube-style volume normalization. Each .opus file
gets its integrated loudness measured with ffmpeg's ebur128 filter, and the gain
needed to reach the -23 LUFS R128 reference is written as the spec-standard
R128_TRACK_GAIN tag (Q7.8 fixed-point dB, RFC 7845). Nothing is re-encoded — a
tag rewrite only. The playback target (-14 LUFS, attenuate-only) is applied in
the player, not baked into the files, so analysis pipelines (MuQ, melody index)
keep seeing bit-identical audio.

Resumable: files that already carry the tag are skipped, so it's safe to Ctrl-C
and re-run, and cheap to re-run after every download batch. After a scan,
re-run build_library_db.py to pull the tags into library.db.

Run:  .venv\Scripts\python scripts\scan_loudness.py            # full library
      .venv\Scripts\python scripts\scan_loudness.py --limit 20 # smoke test
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mutagen.oggopus import OggOpus

R128_REF = -23.0                      # LUFS reference the tag is relative to (spec)
SUMMARY_I = re.compile(r"I:\s+(-?[\d.]+)\s+LUFS")


def measure_lufs(path: Path) -> float | None:
    """Integrated loudness via ffmpeg ebur128. framelog=verbose demotes the
    per-frame spam below the default log level, leaving just the summary."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-map", "0:a:0", "-af", "ebur128=framelog=verbose", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
        encoding="utf-8", errors="replace")   # ffmpeg echoes CJK filenames; cp1252 dies
    hits = SUMMARY_I.findall(r.stderr or "")
    return float(hits[-1]) if hits else None


def scan_one(path: Path) -> tuple[str, str]:
    """Returns (status, detail). status: ok | skip | error"""
    try:
        f = OggOpus(path)
        if f.tags and f.tags.get("R128_TRACK_GAIN"):
            return "skip", ""
        lufs = measure_lufs(path)
        if lufs is None:
            return "error", "no loudness in ffmpeg output"
        q78 = round((R128_REF - lufs) * 256)
        q78 = max(-32768, min(32767, q78))         # tag is int16 per RFC 7845
        f["R128_TRACK_GAIN"] = str(q78)
        f.save()
        return "ok", f"{lufs:+.1f} LUFS -> gain {q78 / 256:+.1f} dB"
    except Exception as e:
        return "error", f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--libdir", type=Path, default=Path(r"D:\OfflineMusic"))
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel ffmpeg processes (default 4)")
    ap.add_argument("--limit", type=int, help="scan at most N untagged files (smoke test)")
    args = ap.parse_args()

    if not args.libdir.exists():
        print(f"error: {args.libdir} not found", file=sys.stderr)
        raise SystemExit(1)

    files = sorted(args.libdir.glob("*.opus"))
    print(f"{len(files)} opus files in {args.libdir}")
    if args.limit:
        files = files[: args.limit * 50]   # headroom: most may already be tagged

    done = skipped = errors = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(scan_one, p): p for p in files}
        for fut in as_completed(futs):
            p = futs[fut]
            status, detail = fut.result()
            if status == "ok":
                done += 1
                if done <= 20 or done % 250 == 0:
                    rate = done / max(time.time() - t0, 1e-9)
                    print(f"  [{done}] {p.name}: {detail}  ({rate * 60:.0f}/min)")
                if args.limit and done >= args.limit:
                    for f2 in futs:
                        f2.cancel()
                    break
            elif status == "skip":
                skipped += 1
            else:
                errors += 1
                print(f"  ERROR {p.name}: {detail}", file=sys.stderr)

    mins = (time.time() - t0) / 60
    print(f"\ntagged {done}, already-tagged {skipped}, errors {errors} in {mins:.1f} min")
    if done:
        print("now re-run:  .venv\\Scripts\\python scripts\\build_library_db.py")


if __name__ == "__main__":
    main()
