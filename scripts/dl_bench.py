#!/usr/bin/env python3
"""Benchmark yt-dlp download configs on small disjoint batches of REAL fresh candidates.
Downloads are kept + tagged + archived, so tests count as real progress (and don't
waste rate-limit budget). Measures throughput and error/rate-limit rates.

Examples:
  python scripts/dl_bench.py --label vr_seq_2  --client android_vr --sleep 2 --sleep-requests 2 --limit 30 --offset 0
  python scripts/dl_bench.py --label vr_fast    --client android_vr --sleep 0.4 --limit 30 --offset 50
  python scripts/dl_bench.py --label vr_conc4   --concurrency 4 --limit 40 --offset 100
  python scripts/dl_bench.py --label aria2c      --downloader aria2c --limit 30 --offset 200
Results append to data/bench_results.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp

sys.path.insert(0, "scripts")
from download_tracks import safe_name, tag_file   # reuse tagging

ARCH = Path("data/downloaded.txt")


def fresh_candidates():
    arch = set()
    if ARCH.exists():
        for l in ARCH.read_text(encoding="utf-8").splitlines():
            if l.strip():
                arch.add(l.split()[-1])
    rows = list(csv.DictReader(open("data/candidates.csv", encoding="utf-8-sig")))
    return [r for r in rows if r["video_id"] not in arch]


def build_opts(args):
    o = {
        "format": "bestaudio[acodec=opus]/bestaudio/best",
        "outtmpl": {"default": str(Path(args.outdir) / "%(id)s.%(ext)s")},
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "opus", "preferredquality": "0"}],
        "extractor_args": {"youtube": {"player_client": [args.client]}},
        "quiet": True, "no_warnings": True, "noprogress": True,
        "retries": 2, "fragment_retries": 2,
        "sleep_interval": args.sleep, "sleep_interval_requests": args.sleep_requests,
    }
    if args.js_runtime and args.js_runtime.lower() != "none":
        o["js_runtimes"] = {args.js_runtime: {"path": None}}
    if args.use_cookies:
        o["cookiefile"] = args.cookies
    if args.downloader == "aria2c":
        o["external_downloader"] = "aria2c"
        o["external_downloader_args"] = {"aria2c": ["-x", "8", "-s", "8", "-k", "1M"]}
    return o


def classify(err):
    e = str(err).lower()
    if any(s in e for s in ("rate", "isn't available", "try again later", "429", "too many")):
        return "rate"
    if "403" in e or "forbidden" in e:
        return "403"
    if "only images" in e or "requested format" in e:
        return "noformat"
    return "other"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--client", default="android_vr")
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--sleep-requests", type=float, default=0.0)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--downloader", default="native")
    ap.add_argument("--use-cookies", action="store_true")
    ap.add_argument("--cookies", default="auth/cookies.txt")
    ap.add_argument("--js-runtime", default="node",
                    help="JS runtime for n-challenge solving (tv/web clients); 'node' or 'none'")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--outdir", default=os.environ.get("MUSIC_DIR", "music"))
    args = ap.parse_args(argv)

    batch = fresh_candidates()[args.offset:args.offset + args.limit]
    if not batch:
        print("no fresh batch at that offset")
        return 1
    Path(args.outdir).mkdir(parents=True, exist_ok=True)
    rowmap = {r["video_id"]: r for r in batch}
    opts = build_opts(args)

    def dl(r):
        vid = r["video_id"]
        try:
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([f"https://www.youtube.com/watch?v={vid}"])
        except Exception as e:
            return ("err", classify(e), vid, 0)
        f = Path(args.outdir) / f"{vid}.opus"
        return ("ok", None, vid, f.stat().st_size) if f.exists() else ("err", "nofile", vid, 0)

    t0 = time.time()
    if args.concurrency > 1:
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            res = list(ex.map(dl, batch))
    else:
        res = [dl(r) for r in batch]
    dt = time.time() - t0

    counts = {"ok": 0, "rate": 0, "403": 0, "noformat": 0, "other": 0, "nofile": 0}
    nbytes = 0
    ok_ids = []
    for status, cat, vid, sz in res:
        if status == "ok":
            counts["ok"] += 1
            nbytes += sz
            ok_ids.append(vid)
            try:
                p = Path(args.outdir) / f"{vid}.opus"
                tag_file(p, rowmap[vid])
                dest = Path(args.outdir) / safe_name(rowmap[vid], vid)
                if dest != p and not dest.exists():
                    p.replace(dest)
            except Exception:
                pass
        else:
            counts[cat] = counts.get(cat, 0) + 1
    if ok_ids:
        with ARCH.open("a", encoding="utf-8") as fh:
            for v in ok_ids:
                fh.write(f"youtube {v}\n")

    tpm = counts["ok"] / dt * 60 if dt else 0
    mbpt = nbytes / 1e6 / counts["ok"] if counts["ok"] else 0
    print(f"{args.label}: {counts['ok']}/{len(batch)} ok in {dt:.0f}s = {tpm:.1f}/min | "
          f"{mbpt:.2f} MB/trk | {counts}")
    new = not Path("data/bench_results.csv").exists()
    with open("data/bench_results.csv", "a", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["label", "client", "conc", "sleep", "sleepreq", "downloader", "cookies",
                        "n", "ok", "rate", "403", "noformat", "other", "wall_s", "per_min", "mb_per_trk"])
        w.writerow([args.label, args.client, args.concurrency, args.sleep, args.sleep_requests,
                    args.downloader, int(args.use_cookies), len(batch), counts["ok"], counts["rate"],
                    counts["403"], counts["noformat"], counts.get("other", 0) + counts.get("nofile", 0),
                    round(dt, 1), round(tpm, 2), round(mbpt, 2)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
