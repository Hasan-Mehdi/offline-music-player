#!/usr/bin/env python3
"""Download candidate/seed tracks as tagged Opus files via yt-dlp, with a search
fallback for songs whose original video is gone.

Per track:
  1. Try the exact video_id. (yt-dlp's android_vr path goes through YouTube's normal
     backend, so most "unavailable on YT Music" songs download fine here already.)
  2. If the video is truly gone, ytsearch regular YouTube for "<artist> <title>",
     score results by title/artist token overlap (+ duration match when known, minus
     penalties for reaction/nightcore/1-hour-loop junk), and download the best match.
  3. If nothing scores well enough, log it to unresolved.csv for manual review.

Substitutes are tagged with YOUR clean metadata (artist/title/album from the CSV) and
logged to substitutions.csv. Completion is tracked via yt-dlp's download archive, so
re-runs skip what you already have and only retry misses.

Audio: prefers native Opus (format 251, ~144k) so extraction is a remux, not a
re-encode. Default client android_vr needs no PO token and no cookies (guest ceiling).
For the authenticated ~6x ceiling use `--client tv --use-cookies` (needs yt-dlp-ejs +
Node so the tv client's n-challenge can be solved; --js-runtime node is on by default).

Usage:
    .venv\\Scripts\\python scripts/download_tracks.py --input data/strong_seeds.csv
    .venv\\Scripts\\python scripts/download_tracks.py --input data/candidates.csv --min-co-occurrence 2
    .venv\\Scripts\\python scripts/download_tracks.py --input data/seed_tracks.csv --outdir "D:\\OfflineMusic"
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import yt_dlp
from mutagen.oggopus import OggOpus

INVALID = re.compile(r'[\\/:*?"<>|]')
REDFLAGS = ("reaction", "nightcore", "sped up", "slowed", "1 hour", "10 hour",
            "hours", "loop", "lyric video", "lyrics video")


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, default=Path("data/candidates.csv"),
                   help="CSV with video_id/title/artist[/album] columns")
    p.add_argument("--outdir", type=Path, default=Path("music"))
    p.add_argument("--limit", type=int, default=None, help="cap number of tracks (test run)")
    p.add_argument("--min-co-occurrence", type=int, default=1,
                   help="only download candidates appearing in >= this many seed radios")
    p.add_argument("--client", default="android_vr",
                   help="yt-dlp YouTube player_client (default: android_vr — PO-token-free, Opus 144k; "
                        "use 'tv' with --use-cookies for the authenticated higher ceiling)")
    p.add_argument("--js-runtime", default="node",
                   help="JS runtime for n-challenge/signature solving, required by the tv/web clients "
                        "(needs yt-dlp-ejs + Node installed); 'node' (default) or 'none' to disable")
    p.add_argument("--use-cookies", action="store_true",
                   help="send session cookies for the authenticated (~6x higher) rate ceiling; "
                        "pair with '--client tv' (android_vr silently ignores cookies)")
    p.add_argument("--browser-json", type=Path, default=Path("auth/browser.json"))
    p.add_argument("--cookies", type=Path, default=Path("auth/cookies.txt"))
    p.add_argument("--archive", type=Path, default=Path("data/downloaded.txt"))
    p.add_argument("--no-search-fallback", action="store_true",
                   help="disable the ytsearch fallback for missing videos")
    p.add_argument("--search-results", type=int, default=6, help="ytsearch results to score (default: 6)")
    p.add_argument("--match-threshold", type=float, default=0.5,
                   help="min token-overlap score to accept a substitute (default: 0.5)")
    p.add_argument("--min-duration", type=int, default=30,
                   help="skip videos shorter than this many seconds (jingles/SFX/clips); "
                        "0 disables (default: 30)")
    p.add_argument("--sleep", type=float, default=2.0, help="seconds between downloads")
    p.add_argument("--max-sleep", type=float, default=None,
                   help="if set, wait a RANDOM --sleep..--max-sleep seconds between downloads "
                        "(an even beat is easier to flag than a jittered one)")
    p.add_argument("--sleep-requests", type=float, default=2.5,
                   help="seconds between extraction requests (the rate-limit fix; default 2.5)")
    p.add_argument("--backoff", type=float, default=1800,
                   help="max cool-down (s) on rate-limit; waits escalate 120s..backoff (default 1800)")
    p.add_argument("--max-cooldowns", type=int, default=5,
                   help="stop after this many cool-downs with no successful download — the IP is "
                        "likely hard-blocked, so reset it (reboot router / hotspot) and re-run (default 5)")
    return p.parse_args(argv)


# ----------------------------------------------------------------------------- helpers

def write_cookies_txt(browser_json: Path, out: Path) -> None:
    data = json.loads(browser_json.read_text(encoding="utf-8"))
    cookie = next((v for k, v in data.items() if k.lower() == "cookie"), "")
    if not cookie:
        raise SystemExit(f"error: no cookie in {browser_json}")
    lines = ["# Netscape HTTP Cookie File"]
    for part in cookie.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        lines.append("\t".join([".youtube.com", "TRUE", "/", "TRUE", "9999999999", name, value]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_candidates(path: Path, min_co: int, limit):
    """Load rows with a video_id. The co_occurrence filter only applies to inputs
    that have that column (candidates.csv); history files (seed_tracks.csv) keep all."""
    rows = []
    with path.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        has_co = bool(reader.fieldnames) and "co_occurrence" in reader.fieldnames
        for r in reader:
            if not r.get("video_id"):
                continue
            if has_co:
                try:
                    co = int(r.get("co_occurrence") or 0)
                except ValueError:
                    co = 0
                if co < min_co:
                    continue
            rows.append(r)
    return rows[:limit] if limit else rows


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str) -> set:
    return set(normalize(s).split())


def parse_duration(s):
    if not s:
        return None
    s = str(s).strip()
    if s.isdigit():
        return int(s)
    if ":" in s:
        sec = 0
        for p in s.split(":"):
            if not p.isdigit():
                return None
            sec = sec * 60 + int(p)
        return sec or None
    return None


def read_archive_ids(path: Path) -> set:
    ids = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts:
                ids.add(parts[-1])
    return ids


def load_sub_map(path: Path) -> dict:
    m = {}
    if path.exists():
        with path.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if r.get("orig_video_id") and r.get("new_video_id"):
                    m[r["orig_video_id"]] = r["new_video_id"]
    return m


def tag_file(path: Path, row: dict, note: str | None = None) -> None:
    f = OggOpus(str(path))
    if row.get("title"):
        f["title"] = [row["title"]]
    if row.get("artist"):
        f["artist"] = [row["artist"]]
    if row.get("album"):
        f["album"] = [row["album"]]
    if row.get("track_no"):                    # an album's order (soundtrack playlists)
        f["tracknumber"] = [str(row["track_no"])]
    if note:
        f["comment"] = [note]
    f.save()


def safe_name(row: dict, vid: str) -> str:
    base = f"{row.get('artist','')} - {row.get('title','')}".strip(" -") or vid
    base = INVALID.sub("_", base)[:120].strip()
    return f"{base} [{vid}].opus"


def is_rate_limited(e):
    s = str(e).lower()
    return any(x in s for x in ("rate", "isn't available", "try again later", "429",
                                "too many requests", "403", "forbidden"))


def is_bot_check(e):
    """YouTube's guest bot-check ('Sign in to confirm you're not a bot'). Seen
    July 2026 as a PER-VIDEO login requirement (official anime OPs etc.) while the
    rest of the queue downloads fine from the same IP — those are skipped and logged
    to auth_required.csv, with the search fallback still tried (alternate uploads
    often aren't locked). The same message can also mean an IP-level flag, so the
    download loop probes a known-good canary video to tell the two apart."""
    return "not a bot" in str(e).lower()


def signed_in(jar):
    """Does the cookie jar still hold a YouTube sign-in? When YouTube ends the session
    (the browser rotated it, or it was revoked) the responses clear SID/LOGIN_INFO from
    the jar, and from then on every video bot-checks — while the guest canary still
    passes, so the canary logic alone reads it as a run of per-video locks (2026-10-10:
    ~400 tracks skipped as LOGIN-REQ over an hour)."""
    names = {c.name for c in jar if c.domain.lstrip(".").endswith("youtube.com")}
    return bool(names & {"SID", "LOGIN_INFO"})


def is_age_restricted(e):
    """Age-gated videos can't be fetched by the guest android_vr client ('Sign in to
    confirm your age'). They're not dead and not rate-limited — just unfetchable here —
    so we skip them immediately (no search fallback, no retry) and log them for a future
    authenticated/POT run."""
    s = str(e).lower()
    return any(x in s for x in ("confirm your age", "age-restricted", "age restricted",
                                "inappropriate for some users"))


# ids the min-duration filter turned down: a jingle that is too short on purpose, not a dead
# video, so the search fallback must not go looking for a "substitute" (it finds anything)
TOO_SHORT = set()


def download_id(dl, outdir: Path, vid: str):
    """Return 'ok' / 'fail' / 'rate' / 'age' / 'auth' / 'short'."""
    try:
        dl.download([f"https://www.youtube.com/watch?v={vid}"])
    except Exception as e:
        if is_age_restricted(e):
            return "age"
        if is_bot_check(e):
            return "auth"
        return "rate" if is_rate_limited(e) else "fail"
    if (outdir / f"{vid}.opus").exists():
        return "ok"
    return "short" if vid in TOO_SHORT else "fail"


def attempt_download(dl, outdir: Path, vid: str, quick_retries: int = 1, quick_sleep: int = 15):
    """One download with a quick retry for transient 403s — a fresh re-extract often
    yields a working media URL without any long cool-down. Returns 'ok'/'fail'/'rate'."""
    st = download_id(dl, outdir, vid)
    while st == "rate" and quick_retries > 0:
        time.sleep(quick_sleep)
        st = download_id(dl, outdir, vid)
        quick_retries -= 1
    return st


def search_alternate(query: str, expected_seconds, n: int, threshold: float):
    """Find an alternate upload of a song by title/artist. Returns (id, src_title, score)."""
    sopts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(sopts) as s:
            info = s.extract_info(f"ytsearch{n}:{query}", download=False)
    except Exception:
        return None, None, 0.0
    q = tokens(query)
    if not q:
        return None, None, 0.0
    qn = normalize(query)
    best, best_score = None, 0.0
    for e in (info.get("entries") or []):
        if not e or not e.get("id"):
            continue
        text = f"{e.get('title','')} {e.get('channel') or e.get('uploader') or ''}"
        score = len(q & tokens(text)) / len(q)
        dur = e.get("duration")
        if expected_seconds and dur and abs(dur - expected_seconds) / expected_seconds > 0.25:
            score -= 0.3
        ntext = normalize(text)
        if any(f in ntext for f in REDFLAGS if f not in qn):
            score -= 0.25
        if score > best_score:
            best, best_score = e, score
    if best and best_score >= threshold:
        return best.get("id"), best.get("title"), round(best_score, 2)
    return None, None, round(best_score, 2)


def build_opts(args) -> dict:
    opts = {
        "format": "bestaudio[acodec=opus]/bestaudio/best",
        "outtmpl": {"default": str(args.outdir / "%(id)s.%(ext)s")},
        "writethumbnail": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "opus", "preferredquality": "0"},
            {"key": "EmbedThumbnail"},
        ],
        "download_archive": str(args.archive),
        "extractor_args": {"youtube": {"player_client": [args.client]}},
        "ignoreerrors": False,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "sleep_interval": args.sleep,
        **({"max_sleep_interval": args.max_sleep} if args.max_sleep else {}),
        "sleep_interval_requests": args.sleep_requests,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if args.min_duration and args.min_duration > 0:
        # Reject too-short uploads (jingles, SFX, clips) at the METADATA stage, before any
        # media is fetched. Returns a skip-reason string or None to keep (match_filter
        # contract). Age-restricted videos are handled separately in the download loop
        # (status 'age') so they're skipped WITHOUT a search-fallback.
        md = args.min_duration

        def _min_dur(info, *, incomplete=False):
            d = info.get("duration")
            if d is not None and d < md:
                TOO_SHORT.add(info.get("id"))
                return f"too short ({d}s < {md}s)"
            return None

        opts["match_filter"] = _min_dur
    if args.js_runtime and args.js_runtime.lower() != "none":
        opts["js_runtimes"] = {args.js_runtime: {"path": None}}
    if args.use_cookies:
        opts["cookiefile"] = str(args.cookies)
    return opts


# ----------------------------------------------------------------------------- main

def main(argv):
    # Console may be cp1252 (Windows); song titles have é/ñ/ø/CJK. Don't let a print crash the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = parse_args(argv)
    if not args.input.exists():
        print(f"error: {args.input} not found — run a harvest/parse step first.", file=sys.stderr)
        return 1
    if args.use_cookies:
        # Prefer an already-exported Netscape cookie file (e.g. Downloads/cookies.txt).
        # Only regenerate from browser.json when no cookie file is present.
        if args.cookies.exists():
            print(f"using existing cookie file: {args.cookies}", file=sys.stderr)
        elif args.browser_json.exists():
            write_cookies_txt(args.browser_json, args.cookies)
        else:
            print(f"error: no cookie file at {args.cookies} and no {args.browser_json} "
                  f"to generate one — export cookies first.", file=sys.stderr)
            return 1

    rows = load_candidates(args.input, args.min_co_occurrence, args.limit)
    if not rows:
        print("error: no candidates matched the filter.", file=sys.stderr)
        return 1
    args.outdir.mkdir(parents=True, exist_ok=True)
    args.archive.parent.mkdir(parents=True, exist_ok=True)

    done = read_archive_ids(args.archive)
    sub_map = load_sub_map(args.input.parent / "substitutions.csv")
    print(f"Downloading up to {len(rows)} tracks -> {args.outdir}  "
          f"({len(done)} already in archive)")

    subs, unresolved, age_gated, auth_required = [], [], [], []
    got = substituted = failed = skipped = age_skipped = auth_locked = short_skipped = 0

    # ---- global rate-limit handling -------------------------------------------
    # A media-fetch 403 is usually a transient IP throttle / stale URL, not a dead
    # video. Quick-retry per video; if TRIP videos fail in a row it's a global
    # throttle -> escalating cool-down (120,240,480.. capped at --backoff); after
    # --max-cooldowns with no success, abort cleanly (don't sleep for hours on a
    # blocked IP — reset the IP and re-run; the archive resumes).
    state = {"rate_streak": 0, "auth_streak": 0, "cooldowns": 0}
    TRIP = 2
    AUTH_TRIP = 10          # consecutive bot-checks before suspecting an IP-level flag
    CANARY_ID = "dQw4w9WgXcQ"  # known guest-fetchable video

    def canary_ok():
        """Distinguish per-video login-locks from an IP-level guest bot-flag: extract
        a video known to work for guests. Under an IP flag it bot-checks too."""
        copts = {"quiet": True, "no_warnings": True, "skip_download": True,
                 "extractor_args": {"youtube": {"player_client": [args.client]}}}
        if args.use_cookies:
            # same session as the run: a guest canary bot-checks on its own now and
            # would read every cookie-authenticated run as an IP flag
            copts["cookiefile"] = str(args.cookies)
        try:
            with yt_dlp.YoutubeDL(copts) as c:
                c.extract_info(f"https://www.youtube.com/watch?v={CANARY_ID}", download=False)
            return True
        except Exception as e:
            return not is_bot_check(e)

    def cool_down(why):
        """Escalating sleep. Returns False once --max-cooldowns is exhausted."""
        if state["cooldowns"] >= args.max_cooldowns:
            return False
        wait = int(min(args.backoff, 120 * (2 ** state["cooldowns"])))
        state["cooldowns"] += 1
        print(f"  [{why}] cool-down {state['cooldowns']}/{args.max_cooldowns}, "
              f"sleeping {wait}s then resuming...", file=sys.stderr, flush=True)
        time.sleep(wait)
        return True

    def fetch(dl, vid):
        """Download one id. Returns 'ok' / 'fail' / 'age' / 'auth' / 'deferred' / 'abort'."""
        while True:
            st = attempt_download(dl, args.outdir, vid)
            if st == "ok":
                state["rate_streak"] = state["auth_streak"] = state["cooldowns"] = 0
                return "ok"
            if st in ("age", "fail", "short"):
                # A definitive per-video answer — extraction itself works, so no
                # IP-level flag is in effect: clear both streaks.
                state["rate_streak"] = state["auth_streak"] = 0
                return st
            if st == "auth":
                if args.use_cookies and not signed_in(dl.cookiejar):
                    return "signed_out"                      # retrying can't help
                state["rate_streak"] = 0
                state["auth_streak"] += 1
                if state["auth_streak"] >= AUTH_TRIP:
                    state["auth_streak"] = 0
                    if not canary_ok():
                        if not cool_down("bot-flagged: canary blocked too, IP-level guest flag"):
                            return "abort"
                        continue                             # flag may have lifted; retry this video
                return "auth"                                # per-video login-lock
            state["rate_streak"] += 1                        # st == "rate"
            if state["rate_streak"] < TRIP:
                return "deferred"                            # one-off blip; retry next run
            if not cool_down("rate-limited] global IP throttle"):
                return "abort"
            state["rate_streak"] = 0                         # fresh chance; retry this video

    signed_out = False
    with yt_dlp.YoutubeDL(build_opts(args)) as dl:
        if args.use_cookies and not signed_in(dl.cookiejar):
            print(f"error: {args.cookies} holds no YouTube sign-in (no SID/LOGIN_INFO) — "
                  f"export fresh cookies from a private window.", file=sys.stderr)
            return 3
        for i, r in enumerate(rows, 1):
            vid = r["video_id"]
            # Already have it (exact or a known substitute)?
            if vid in done or sub_map.get(vid) in done:
                skipped += 1
                continue

            st = fetch(dl, vid)
            if st == "signed_out":
                signed_out = True
                print(f"\n[stopped] YouTube ended the cookie session at [{i}/{len(rows)}] — every\n"
                      f"          video now bot-checks. Export fresh cookies from a PRIVATE window,\n"
                      f"          close the window, then re-run; the archive resumes.",
                      file=sys.stderr, flush=True)
                break
            if st == "abort":
                print("\n[stopped] YouTube appears to be hard-blocking this IP (repeated cool-downs,\n"
                      "          no progress). Reset your IP — reboot router / phone hotspot / wait ~1h —\n"
                      "          then re-run; the archive resumes where it left off.",
                      file=sys.stderr, flush=True)
                break
            if st == "age":
                age_skipped += 1
                age_gated.append(r)
                print(f"  [{i}/{len(rows)}] AGE-GATED (skipped) {r.get('artist')} - {r.get('title')}")
                continue

            if st == "short":
                short_skipped += 1
                print(f"  [{i}/{len(rows)}] TOO SHORT (skipped) {r.get('artist')} - {r.get('title')}")
                continue

            eff = vid if st == "ok" else None

            # Search fallback for dead videos AND login-locked ones — alternate
            # uploads of a locked official video usually aren't locked themselves.
            if eff is None and st in ("fail", "auth") and not args.no_search_fallback:
                q = f"{r.get('artist','')} {r.get('title','')}".strip()
                new_id, src_title, sc = search_alternate(
                    q, parse_duration(r.get("duration") or r.get("length")),
                    args.search_results, args.match_threshold)
                if new_id and new_id != vid and new_id not in done and fetch(dl, new_id) == "ok":
                    eff = new_id
                    substituted += 1
                    subs.append({"orig_video_id": vid, "new_video_id": new_id,
                                 "score": sc, "source_title": src_title,
                                 "artist": r.get("artist", ""), "title": r.get("title", "")})
                    print(f"  [{i}/{len(rows)}] SUBBED  {r.get('artist')} - {r.get('title')}"
                          f"  ->  {src_title} ({sc})")

            if eff is None:
                if st == "auth":
                    # Video exists but is guest-locked and no substitute was found:
                    # it belongs to the future authenticated run, not unresolved.csv.
                    auth_locked += 1
                    auth_required.append(r)
                    print(f"  [{i}/{len(rows)}] LOGIN-REQ (skipped) {r.get('artist')} - {r.get('title')}")
                    continue
                failed += 1
                unresolved.append(r)
                tag = "deferred(rate)" if st == "deferred" else "MISSING"
                print(f"  [{i}/{len(rows)}] {tag} {r.get('artist')} - {r.get('title')}")
                continue

            try:
                note = f"substituted for {vid}" if eff != vid else None
                src = args.outdir / f"{eff}.opus"
                tag_file(src, r, note)
                dest = args.outdir / safe_name(r, eff)
                if dest != src and not dest.exists():
                    src.replace(dest)
                done.add(eff)
                got += 1
            except Exception as e:
                print(f"  [{i}/{len(rows)}] tag/rename failed for {eff}: {e}", file=sys.stderr)

            if i % 50 == 0:
                print(f"  ...[{i}/{len(rows)}] got {got}, subbed {substituted}, "
                      f"missing {failed}, skipped {skipped}")

    # Write review logs.
    if subs:
        _write_csv(args.input.parent / "substitutions.csv",
                   ["orig_video_id", "new_video_id", "score", "source_title", "artist", "title"],
                   subs, append=(args.input.parent / "substitutions.csv").exists())
    if unresolved:
        _write_csv(args.input.parent / "unresolved.csv",
                   ["video_id", "artist", "title", "url"],
                   [{"video_id": r["video_id"], "artist": r.get("artist", ""),
                     "title": r.get("title", ""), "url": r.get("url", "")} for r in unresolved])
    if age_gated:
        _write_csv(args.input.parent / "age_restricted.csv",
                   ["video_id", "artist", "title", "url"],
                   [{"video_id": r["video_id"], "artist": r.get("artist", ""),
                     "title": r.get("title", ""), "url": r.get("url", "")} for r in age_gated])
    if auth_required:
        _write_csv(args.input.parent / "auth_required.csv",
                   ["video_id", "artist", "title", "url"],
                   [{"video_id": r["video_id"], "artist": r.get("artist", ""),
                     "title": r.get("title", ""), "url": r.get("url", "")} for r in auth_required])

    print()
    print(f"Downloaded   : {got}  (of which substituted: {substituted})")
    print(f"Already had  : {skipped}")
    print(f"Too short    : {short_skipped}  (under --min-duration; no substitute searched)")
    print(f"Age-gated    : {age_skipped}" + ("  -> data/age_restricted.csv (skipped; need auth/POT)"
                                             if age_gated else ""))
    print(f"Login-locked : {auth_locked}" + ("  -> data/auth_required.csv (guest-blocked video, no sub "
                                             "found; needs the authenticated run)" if auth_required else ""))
    print(f"Unresolved   : {failed}" + (f"  -> data/unresolved.csv" if unresolved else ""))
    print(f"Library dir  : {args.outdir.resolve()}")
    return 3 if signed_out else 0


def _write_csv(path: Path, fields, rows, append: bool = False):
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if not append:
            w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
