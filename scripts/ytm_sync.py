#!/usr/bin/env python3
"""Keep up with your YouTube Music account, signed in, read-only.

  listen_again  the Listen again page (what the app's "More" opens: ~65 songs, albums,
                playlists, artists, in YT Music's order) -> data/ytm_listen_again.json, with
                each album / playlist's tracks (cached a day per list). The Wheel is built from it.
  radios        YT Music's radio for a song, signed in so it's the radio YOU get (~100 songs),
                -> data/radio_cache/<vid>.json (what collab.load_radios reads), and the genres YT
                Music files the song under (the chips over its queue: "Indian indie", "Video game
                music") -> data/ytm_genres.json. Seeds, most useful first: the Listen again songs
                and their lists' songs, then songs you started on the H2 / in the web player, then
                the rest of what you play that no radio or playlist covers, your liked songs, and
                what you've played TAIL_MIN_PLAYS times or more. A radio is refetched once it's
                RADIO_MAX_AGE_DAYS old.
  liked         Liked Music in like order (newest first) -> data/ytm_liked.json.

  .venv\\Scripts\\python scripts\\ytm_sync.py listen_again liked radios --max 80
  .venv\\Scripts\\python scripts\\ytm_sync.py radios              (the long tail; slow)

Slow on purpose (8-14 s between requests), resumable, and it stops -- never carries on as a
guest -- once the account stops answering as signed in. Auth: auth/ytm_headers.json (the
browser headers ytmusicapi reads; any "authorization" value works, it's recomputed from the
SAPISID cookie).

Why (2026-10-22): a radio on "Glow" (Kushagra) played Pokemon Z-A and AZALI on the H2. We had
no YT Music radio or playlist for it, only your own listening, and that was your Liked list
played in order. YT Music's own radio for it is ~150 Hindi/Urdu indie songs.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil
from ytmusicapi import YTMusic
from ytmusicapi.parsers.watch import parse_watch_playlist

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from player_server import collab  # noqa: E402

DATA = ROOT / "data"
AUTH = ROOT / "auth" / "ytm_headers.json"
RADIO_CACHE = DATA / "radio_cache"
PLAYLIST_CACHE = DATA / "playlist_cache"
STATE = DATA / "ytm_sync_state.json"
GENRES = DATA / "ytm_genres.json"
LIKED = DATA / "ytm_liked.json"
LISTEN_AGAIN = DATA / "ytm_listen_again.json"
LIST_CACHE = DATA / "ytm_lists"
LISTENS = DATA / "listens.csv"
LIBRARY_DB = DATA / "library.db"
LOCK = DATA / "ytm_sync.lock"

PACE = (8.0, 14.0)            # seconds between requests
CHECK_EVERY = 50              # radios between "still signed in?" checks
MAX_ERRORS = 3                # failures in a row: stop
RADIO_SONGS = 100             # a radio's first page is ~50, each continuation ~50 more:
                              # 2 requests, 5-6 hours of listening
RADIO_MAX_AGE_DAYS = 14
TAIL_MIN_PLAYS = 3            # the long tail: songs you've played at least this often
LIST_MAX_AGE_HOURS = 20
# the chips over every radio's queue that aren't genres
NOT_GENRES = {"All", "Familiar", "Popular", "Discover", "Deep cuts", "Save",
              "Romance", "Chill", "Upbeat", "Party", "Focus", "Workout", "Pump-up", "Sad",
              "Feel good", "Energize", "Relax", "Sleep", "Commute", "Instrumental"}


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, obj, indent=None):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
    tmp.replace(path)


def walk(o, key):
    """Every dict under `o` that has `key`, depth first, in document order."""
    if isinstance(o, dict):
        if key in o:
            yield o[key]
            return
        for v in o.values():
            yield from walk(v, key)
    elif isinstance(o, list):
        for x in o:
            yield from walk(x, key)


def runs_text(o):
    return "".join(r.get("text", "") for r in (o or {}).get("runs", []))


class SignedOut(Exception):
    pass


class Client:
    """ytmusicapi over our headers, one request at a time at PACE."""

    def __init__(self):
        self.yt = YTMusic(str(AUTH))
        self.last = 0.0
        self.n = 0

    def wait(self):
        gap = random.uniform(*PACE) - (time.time() - self.last)
        if gap > 0 and self.last:
            time.sleep(gap)
        self.last = time.time()
        self.n += 1

    def signed_in(self):
        self.wait()
        try:
            info = self.yt.get_account_info()
        except Exception as e:                   # a signed-out page has no account menu
            raise SignedOut(f"not signed in ({type(e).__name__})") from e
        if not info or not info.get("accountName"):
            raise SignedOut("not signed in")
        return info["accountName"]

    def call(self, fn, *args, **kw):
        self.wait()
        return fn(*args, **kw)

    def send(self, endpoint, body, extra=""):
        self.wait()
        return self.yt._send_request(endpoint, body, extra)


# ---------------------------------------------------------------- listen again

def _item(it):
    """One Listen again tile -> {kind, id, title, subtitle}."""
    ne = it.get("navigationEndpoint", {})
    title, sub = runs_text(it.get("title")), runs_text(it.get("subtitle"))
    if "watchEndpoint" in ne:
        return {"kind": "song", "id": ne["watchEndpoint"].get("videoId"), "title": title, "subtitle": sub}
    be = ne.get("browseEndpoint", {})
    page = (be.get("browseEndpointContextSupportedConfigs", {}).get("browseEndpointContextMusicConfig", {})
            .get("pageType", "")).replace("MUSIC_PAGE_TYPE_", "")
    bid = be.get("browseId", "")
    if page == "PLAYLIST":
        return {"kind": "playlist", "id": bid[2:] if bid.startswith("VL") else bid, "title": title, "subtitle": sub}
    if page == "ALBUM":
        return {"kind": "album", "id": bid, "title": title, "subtitle": sub}
    if page in ("ARTIST", "USER_CHANNEL"):
        return {"kind": "artist", "id": bid, "title": title, "subtitle": sub}
    # a podcast-style track page ("NON_MUSIC_AUDIO_TRACK_PAGE"): its play button has the video
    vid = next((w.get("videoId") for w in walk(it.get("thumbnailOverlay", {}), "watchEndpoint")), None)
    return {"kind": "song", "id": vid, "title": title, "subtitle": sub} if vid else None


def list_tracks(cl, item):
    """[{video_id, title, artist}] of an album / playlist tile, cached LIST_MAX_AGE_HOURS."""
    LIST_CACHE.mkdir(parents=True, exist_ok=True)
    fn = LIST_CACHE / f"{item['kind']}_{item['id']}.json"
    old = load_json(fn, None)
    if old and datetime.now() - datetime.fromisoformat(old["pulled"]) < timedelta(hours=LIST_MAX_AGE_HOURS):
        return old["tracks"]
    if item["kind"] == "album":
        tracks = cl.call(cl.yt.get_album, item["id"]).get("tracks", [])
    else:
        tracks = cl.call(cl.yt.get_playlist, item["id"], limit=None).get("tracks", [])
    out = [{"video_id": t["videoId"], "title": t.get("title", ""),
            "artist": ", ".join(a.get("name", "") for a in t.get("artists") or [] if a.get("name"))}
           for t in tracks if t.get("videoId")]
    save_json(fn, {"pulled": datetime.now().isoformat(timespec="seconds"), "tracks": out})
    return out


def pull_listen_again(cl):
    r = cl.send("browse", {"browseId": "FEmusic_listen_again", "params": "ggMEgAKgAw%3D%3D"})
    items = [x for x in map(_item, walk(r, "musicTwoRowItemRenderer")) if x and x.get("id")]
    if not items:
        raise RuntimeError("Listen again came back empty")
    for it in items:
        if it["kind"] in ("album", "playlist"):
            try:
                it["tracks"] = list_tracks(cl, it)
            except Exception as e:
                log(f"listen again: {it['kind']} {it['title']!r} failed ({type(e).__name__}: {str(e)[:100]})")
                it["tracks"] = []
    save_json(LISTEN_AGAIN, {"pulled": datetime.now().isoformat(timespec="seconds"), "items": items}, indent=1)
    kinds = {}
    for it in items:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    log(f"listen again: {len(items)} items {kinds} -> {LISTEN_AGAIN.name}")


def pull_liked(cl):
    tracks = cl.call(cl.yt.get_liked_songs, limit=None).get("tracks", [])
    rows = [{"video_id": t["videoId"], "title": t.get("title", ""),
             "artist": ", ".join(a.get("name", "") for a in t.get("artists") or [] if a.get("name"))}
            for t in tracks if t.get("videoId")]
    save_json(LIKED, {"pulled": datetime.now().isoformat(timespec="seconds"), "tracks": rows}, indent=1)
    log(f"liked: {len(rows)} songs -> {LIKED.name}")


# ---------------------------------------------------------------- radios

def fetch_radio(cl, vid):
    """(tracks, genres) of `vid`'s signed-in radio: what get_watch_playlist(radio=True) returns,
    from the raw `next` response so the genre chips come with it."""
    body = {"enablePersistentPlaylistPanel": True, "isAudioOnly": True,
            "tunerSettingValue": "AUTOMIX_SETTING_NORMAL", "videoId": vid,
            "playlistId": "RDAMVM" + vid, "params": "wAEB"}
    r = cl.send("next", body)
    panel = next(walk(r, "playlistPanelRenderer"), None)
    if not panel:
        raise RuntimeError("no queue in the response")
    tracks = parse_watch_playlist(panel.get("contents", []))
    genres = [runs_text(c.get("text")) for c in walk(r, "chipCloudChipRenderer")]
    genres = [g for g in genres if g and g not in NOT_GENRES and not re.fullmatch(r"\d{4}s", g)]
    cont = panel
    while len(tracks) < RADIO_SONGS and cont.get("continuations"):
        token = cont["continuations"][0].get("nextRadioContinuationData", {}).get("continuation")
        if not token:
            break
        rr = cl.send("next", body, f"&ctoken={token}&continuation={token}")
        cont = next(walk(rr, "playlistPanelContinuation"), None)
        if not cont:
            break
        tracks += parse_watch_playlist(cont.get("contents", []))
    return tracks, genres


def library_ids():
    con = sqlite3.connect(f"file:{LIBRARY_DB}?mode=ro", uri=True)
    try:
        return {v for (v,) in con.execute("SELECT video_id FROM tracks")}
    finally:
        con.close()


def play_counts():
    """{vid: plays}: the Takeout plus the players' own log."""
    n = {}
    try:
        with LISTENS.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("video_id"):
                    n[r["video_id"]] = n.get(r["video_id"], 0) + 1
    except OSError:
        pass
    con = sqlite3.connect(f"file:{LIBRARY_DB}?mode=ro", uri=True)
    try:
        for v, c in con.execute("SELECT video_id, COUNT(*) FROM plays WHERE event='play' GROUP BY video_id"):
            n[v] = n.get(v, 0) + c
    finally:
        con.close()
    return n


def started_recently(days=30):
    """Songs you started yourself on the H2 or in the web player lately, latest first."""
    con = sqlite3.connect(f"file:{LIBRARY_DB}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT video_id, MAX(ts) FROM plays WHERE event='play' AND ts > ? "
                           "GROUP BY video_id ORDER BY MAX(ts) DESC", (time.time() - days * 86400,)).fetchall()
    finally:
        con.close()
    return [v for v, _ in rows]


def radio_seeds(st):
    """Songs whose radio is worth having, most useful first, minus those fetched within
    RADIO_MAX_AGE_DAYS."""
    fetched = st.get("radios", {})
    fresh = {v for v, t in fetched.items()
             if datetime.now() - datetime.fromisoformat(t) < timedelta(days=RADIO_MAX_AGE_DAYS)}
    lib, plays = library_ids(), play_counts()
    la = load_json(LISTEN_AGAIN, {}).get("items", [])
    wheel = [it["id"] for it in la if it["kind"] == "song"]
    for it in la:
        wheel += [t["video_id"] for t in it.get("tracks", [])][:30]
    outside = set()
    for seed, mem in collab.load_radios(str(RADIO_CACHE)):
        outside.add(seed)
        outside.update(mem)
    for _kind, ids in collab.load_playlists(str(PLAYLIST_CACHE)):
        outside.update(ids)
    liked = [t["video_id"] for t in load_json(LIKED, {}).get("tracks", [])]
    played = sorted((v for v in plays if v in lib), key=lambda v: -plays[v])
    tiers = [wheel, started_recently(),
             [v for v in played if v not in outside], liked,
             [v for v in played if plays[v] >= TAIL_MIN_PLAYS]]
    out, seen = [], set(fresh)
    for tier in tiers:
        for v in tier:
            if v and v not in seen:
                seen.add(v)
                out.append(v)
    return out


def pull_radios(cl, st, max_n):
    seeds = radio_seeds(st)
    if max_n:
        seeds = seeds[:max_n]
    log(f"radios: {len(seeds)} to fetch")
    RADIO_CACHE.mkdir(parents=True, exist_ok=True)
    done, genres = st.setdefault("radios", {}), load_json(GENRES, {})
    errors = 0
    for i, v in enumerate(seeds, 1):
        if i % CHECK_EVERY == 0:
            log(f"radios: {i - 1}/{len(seeds)}; still signed in as {cl.signed_in()}")
        try:
            tracks, g = fetch_radio(cl, v)
            errors = 0
        except SignedOut:
            raise
        except Exception as e:
            errors += 1
            log(f"radios: {v} failed ({type(e).__name__}: {str(e)[:120]})")
            if errors >= MAX_ERRORS:
                cl.signed_in()                   # SignedOut says why; else it's the errors
                raise RuntimeError(f"{MAX_ERRORS} failures in a row; stopping") from e
            time.sleep(60)
            continue
        if tracks:
            save_json(RADIO_CACHE / f"{v}.json", tracks)
        genres[v] = g
        done[v] = datetime.now().isoformat(timespec="seconds")
        if i % 10 == 0 or i == len(seeds):
            save_json(STATE, st, indent=1)
            save_json(GENRES, genres)
    save_json(STATE, st, indent=1)
    save_json(GENRES, genres)
    log(f"radios: finished ({cl.n} requests this run)")


def take_lock():
    """One radio fetch at a time (autosync's short runs and the long overnight one share the
    account). Listen again and Liked are a dozen requests: they don't wait for it."""
    try:
        pid = int(LOCK.read_text())
        # (not os.kill(pid, 0): on Windows that terminates the process)
        if psutil.pid_exists(pid) and "python" in psutil.Process(pid).name().lower():
            return False
    except (OSError, ValueError, psutil.Error):
        pass
    LOCK.write_text(str(os.getpid()))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="+", choices=["listen_again", "liked", "radios"])
    ap.add_argument("--max", type=int, default=0, help="radios: at most this many this run")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    radios = "radios" in a.what
    if radios and not take_lock():
        if a.what == ["radios"]:
            log("another ytm_sync is fetching radios; not starting")
            return 3
        log("another ytm_sync is fetching radios; only " + ", ".join(w for w in a.what if w != "radios"))
        radios = False
    st = load_json(STATE, {})
    try:
        cl = Client()
        log(f"signed in as {cl.signed_in()}")
        if "listen_again" in a.what:
            pull_listen_again(cl)
        if "liked" in a.what:
            pull_liked(cl)
        if radios:
            pull_radios(cl, st, a.max)
    except SignedOut as e:
        save_json(STATE, st, indent=1)
        log(f"STOPPED: {e}. Export fresh YouTube cookies to auth/yt_cookies.txt, then rebuild "
            f"auth/ytm_headers.json from them.")
        return 2
    finally:
        if radios:
            LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
