#!/usr/bin/env python3
"""Download a full-OST YouTube video and split it into one tagged Opus file PER CHAPTER.

Some official game soundtracks (Pokémon Colosseum, Mario & Luigi: Bowser's Inside Story /
Dream Team, ...) aren't on YT Music as albums — they live on regular YouTube as single
1-2 hour "Full OST" uploads. The good uploads have CHAPTER MARKERS (one per track), so
yt-dlp --split-chapters turns them into a clean per-track library.

For each entry in OSTS below it: downloads via android_vr (Opus 251), splits on chapters,
tags each piece (title = chapter name, album = game), drops chapters under --min-duration
(jingles), and skips a video whose pieces are already present. Re-runnable.

    .venv\\Scripts\\python scripts/grab_chaptered_ost.py                 # all entries
    .venv\\Scripts\\python scripts/grab_chaptered_ost.py --only colosseum

ADD MORE: find a full-OST upload WITH chapters (probe several — pick one whose TITLE
matches the game, not a compilation/wrong game), then add (key, video_id, album, artist).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yt_dlp
from mutagen.oggopus import OggOpus

INVALID = re.compile(r'[\\/:*?"<>|]')

# (key, video_id, album, artist) — title-matched chaptered uploads (verified 2026-06-29)
OSTS = [
    ("colosseum",   "sRr9aarnCc8", "Pokémon Colosseum (OST)",                 "Game Freak"),
    ("bis",         "-1VKuue4N9o", "Mario & Luigi: Bowser's Inside Story (OST)", "Yoko Shimomura"),
    ("dreamteam",   "g7YykToUYdw", "Mario & Luigi: Dream Team (OST)",         "Yoko Shimomura"),
]


def safe(s):
    return INVALID.sub("_", s).strip()[:120]


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default="D:\\OfflineMusic")
    ap.add_argument("--min-duration", type=int, default=30)
    ap.add_argument("--only", default=None, help="only this key (e.g. colosseum)")
    ap.add_argument("--client", default="android_vr")
    ap.add_argument("--sleep-requests", type=float, default=3.0)
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    entries = [o for o in OSTS if not args.only or o[0] == args.only]

    total = 0
    for key, vid, album, artist in entries:
        # Skip if we already split this video before (any tagged piece on disk).
        if list(outdir.glob(f"*[[]{vid}-*].opus")):
            print(f"[{key}] already present (pieces found) — skipping")
            continue

        # Split-chapter file template: keep video id + chapter number so we can find &
        # tag the pieces afterward and so re-runs detect them.
        chap_tmpl = str(outdir / f"%(section_number)03d - %(section_title)s [{vid}-%(section_number)03d].%(ext)s")
        opts = {
            "format": "bestaudio[acodec=opus]/bestaudio/best",
            "outtmpl": {"default": str(outdir / f"%(id)s.%(ext)s"), "chapter": chap_tmpl},
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "opus", "preferredquality": "0"},
                {"key": "FFmpegSplitChapters", "force_keyframes": False},
            ],
            "extractor_args": {"youtube": {"player_client": [args.client]}},
            "sleep_interval_requests": args.sleep_requests,
            "retries": 5, "fragment_retries": 5,
            "quiet": True, "no_warnings": True, "noprogress": True,
        }
        print(f"[{key}] downloading + splitting {vid} -> {album}")
        try:
            with yt_dlp.YoutubeDL(opts) as dl:
                dl.download([f"https://www.youtube.com/watch?v={vid}"])
        except Exception as e:
            print(f"[{key}] FAILED: {str(e)[:120]}", file=sys.stderr)
            continue

        # Remove the un-split full-length leftover (the %(id)s.opus the chapters came from).
        whole = outdir / f"{vid}.opus"
        if whole.exists():
            whole.unlink()

        # Tag each chapter piece; drop ones under the min-duration cutoff.
        kept = dropped = 0
        for f in sorted(outdir.glob(f"*[[]{vid}-*].opus")):
            try:
                au = OggOpus(str(f))
                if au.info.length < args.min_duration:
                    f.unlink(); dropped += 1; continue
                # chapter title = filename between "NNN - " and " [vid-"
                m = re.match(r"\d+ - (.*) \[" + re.escape(vid), f.stem)
                title = m.group(1) if m else f.stem
                au["title"] = [title]
                au["artist"] = [artist]
                au["album"] = [album]
                au.save()
                # rename to the library's "Artist - Title [id]" convention
                dest = f.with_name(f"{safe(artist)} - {safe(title)} [{vid}-{f.stem.split('-')[-1].strip(' []')}].opus")
                if dest != f and not dest.exists():
                    f.rename(dest)
                kept += 1
            except Exception as e:
                print(f"   tag failed {f.name}: {str(e)[:80]}", file=sys.stderr)
        print(f"[{key}] {kept} tracks tagged, {dropped} dropped (<{args.min_duration}s)")
        total += kept

    print(f"\nDone. {total} OST tracks added to {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
