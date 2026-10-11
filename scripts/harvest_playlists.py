#!/usr/bin/env python3
"""Find public playlists that CONTAIN your songs, then harvest their full tracklists.

Since YouTube has no "which playlists contain video X" lookup, we reconstruct it:
  for each seed song -> search community playlists for "<artist> <title>"
  -> fetch each candidate playlist -> VERIFY the seed is actually in it
  -> collect the whole playlist's tracks.
Tracks are ranked by playlist_freq (how many of your verified playlists they appear in)
= the human-curation co-occurrence signal. Output feeds download_tracks.py.

Resumable: per-seed results cached under data/playlist_cache/.
Auth: auth/browser.json (ytmusicapi). Be gentle (--sleep) — the API rate-limits too.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

try:
    from ytmusicapi import YTMusic
except ImportError:
    print("error: ytmusicapi not installed", file=sys.stderr)
    raise SystemExit(1)

CACHE = Path("data/playlist_cache")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s)).strip()


def tokens(s):
    return set(norm(s).split())


def is_ost_playlist(tracks):
    """OST / single-artist dump? (dominated by one artist). Small playlists -> curated."""
    tt = [t for t in tracks if t.get("videoId")]
    if len(tt) < 4:
        return False
    arts = Counter((t.get("artist") or "").split(",")[0].strip().lower()
                   for t in tt if (t.get("artist") or "").strip())
    if not arts:
        return False
    return arts.most_common(1)[0][1] / len(tt) >= 0.5 or len(arts) <= 2


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seeds", type=Path, default=Path("data/seed_tracks.csv"),
                   help="CSV with video_id/title/artist[/play_count] (default: seed_tracks.csv)")
    p.add_argument("--auth", type=Path, default=Path("auth/browser.json"))
    p.add_argument("--max-seeds", type=int, default=300, help="how many of your top songs to mine")
    p.add_argument("--playlists-per-seed", type=int, default=5)
    p.add_argument("--playlist-limit", type=int, default=150, help="max tracks to pull per playlist")
    p.add_argument("--sleep", type=float, default=1.0)
    p.add_argument("--out", type=Path, default=Path("data/playlist_candidates.csv"))
    return p.parse_args(argv)


def load_seeds(path, n):
    rows = []
    with path.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r.get("video_id"):
                rows.append(r)
    rows.sort(key=lambda r: int(r.get("play_count", 0) or 0), reverse=True)
    return rows[:n]


def matches_seed(seed, tracks):
    """True if the seed song appears in the playlist (by videoId or artist+title tokens)."""
    vid = seed["video_id"]
    want = tokens(seed.get("artist", "")) | tokens(seed.get("title", ""))
    if not want:
        return False
    for t in tracks:
        if t.get("videoId") == vid:
            return True
        have = tokens(" ".join(a.get("name", "") for a in (t.get("artists") or []))) | tokens(t.get("title", ""))
        if want and len(want & have) / len(want) >= 0.7:
            return True
    return False


def harvest_seed(yt, seed, ppl, plimit):
    """Return list of verified playlists [{id, tracks:[{videoId,title,artist}]}]."""
    q = f"{seed.get('artist','')} {seed.get('title','')}".strip()
    try:
        results = yt.search(q, filter="community_playlists", limit=ppl * 3)
    except Exception:
        try:
            results = yt.search(q, filter="playlists", limit=ppl * 3)
        except Exception:
            return []
    out = []
    for item in results:
        if len(out) >= ppl:
            break
        pid = item.get("playlistId") or item.get("browseId") or ""
        pid = pid[2:] if pid.startswith("VL") else pid
        if not pid:
            continue
        try:
            pl = yt.get_playlist(pid, limit=plimit)
            tracks = pl.get("tracks", []) or []
        except Exception:
            continue
        if not matches_seed(seed, tracks):
            continue
        out.append({"id": pid, "tracks": [
            {"videoId": t.get("videoId"),
             "title": t.get("title", ""),
             "artist": ", ".join(a.get("name", "") for a in (t.get("artists") or []) if a.get("name"))}
            for t in tracks if t.get("videoId")]})
    return out


def main(argv):
    args = parse_args(argv)
    if not args.auth.exists():
        print(f"error: {args.auth} not found — run setup_auth.py", file=sys.stderr)
        return 1
    yt = YTMusic(str(args.auth))
    seeds = load_seeds(args.seeds, args.max_seeds)
    CACHE.mkdir(parents=True, exist_ok=True)
    owned = {s["video_id"] for s in load_seeds(args.seeds, 10**9)}
    print(f"Mining playlists for {len(seeds)} seed songs...")

    cand = defaultdict(lambda: {"title": "", "artist": "", "playlists": set(), "cur": set()})
    verified_playlists = set()
    fetched = cached = errors = 0

    for i, s in enumerate(seeds, 1):
        cf = CACHE / f"{s['video_id']}.json"
        if cf.exists():
            try:
                pls = json.loads(cf.read_text(encoding="utf-8"))
                cached += 1
            except Exception:
                pls = []
        else:
            try:
                pls = harvest_seed(yt, s, args.playlists_per_seed, args.playlist_limit)
            except Exception as e:
                errors += 1
                print(f"  [{i}/{len(seeds)}] {s['video_id']} failed: {e}", file=sys.stderr)
                pls = []
            cf.write_text(json.dumps(pls, ensure_ascii=False), encoding="utf-8")
            fetched += 1
            time.sleep(args.sleep)

        for pl in pls:
            verified_playlists.add(pl["id"])
            ost = is_ost_playlist(pl["tracks"])
            for t in pl["tracks"]:
                vid = t.get("videoId")
                if not vid:
                    continue
                rec = cand[vid]
                rec["playlists"].add(pl["id"])
                if not ost:
                    rec["cur"].add(pl["id"])
                if not rec["title"]:
                    rec["title"], rec["artist"] = t["title"], t["artist"]
        if i % 25 == 0:
            print(f"  [{i}/{len(seeds)}] verified playlists: {len(verified_playlists)} | "
                  f"unique tracks: {len(cand)}")

    rows = [{"video_id": v, "title": r["title"], "artist": r["artist"],
             "playlist_freq": len(r["playlists"]), "curated_freq": len(r["cur"]),
             "is_owned": v in owned,
             "url": f"https://music.youtube.com/watch?v={v}"} for v, r in cand.items()]
    rows.sort(key=lambda r: (r["curated_freq"], r["playlist_freq"]), reverse=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["video_id", "title", "artist", "playlist_freq", "curated_freq", "is_owned", "url"])
        w.writeheader()
        w.writerows(rows)

    new = sum(1 for r in rows if not r["is_owned"])
    print(f"\nseeds: {len(seeds)} ({fetched} fetched, {cached} cached, {errors} errors)")
    print(f"verified playlists containing your songs: {len(verified_playlists)}")
    print(f"unique candidate tracks: {len(rows)}  ({new} new / not already owned)")
    print(f"  in >=1 curated (non-OST) mix: {sum(1 for r in rows if r['curated_freq'] >= 1)}")
    print(f"  in >=2 curated mixes:         {sum(1 for r in rows if r['curated_freq'] >= 2)}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
