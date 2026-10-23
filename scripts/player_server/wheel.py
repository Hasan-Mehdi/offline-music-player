"""The Wheel (and Home's Listen again): what you start from and keep coming back to.

YT Music's Listen again (2026-10-22, read signed in) is ~65 songs, albums, playlists and an
artist or two: the things you go back to and start from, not just your most heard songs
(only about half its songs are in its own Replay Mix). That is how you use it: tap something,
listen to its radio as long as you like, come back and tap something else. So:

  - YT Music's Listen again (scripts/ytm_sync.py listen_again) leads, in its order, fading
    by HALFLIFE_DAYS since it was read (a sync that stops doesn't freeze the Wheel);
  - every song or list you START yourself on the H2 (a pick, not autoplay, kept PICK_KEEP_S
    or longer) adds 0.5 ** (age / HALFLIFE_DAYS), so what you keep starting climbs;
  - after those, the songs you replayed in your YT Music history (the old Wheel), below
    them and never adding to them, so spinning on still goes back through your listening.

Pure: no Flask, SQLite or server globals.
"""
from __future__ import annotations

import json
from datetime import datetime

HALFLIFE_DAYS = 21.0      # the Listen again backtest's best (server.LISTEN_AGAIN_HALFLIFE_DAYS)
LA_TOP, LA_END = 2.0, 1.0  # Listen again's first item counts this much, its last this much
TAIL_W = 0.5              # the old history order, at most this much (under Listen again)
PICK_KEEP_S = 30.0        # a start counts once you've stayed this long (or it finished)
SITTING_GAP = 30 * 60     # the H2's sittings: a start this long after the last song is a pick
MIN_LIST_SONGS = 3        # a list needs this many songs in the library to be a tile


def decay(age_s):
    return 0.5 ** (max(0.0, age_s) / (HALFLIFE_DAYS * 86400))


def load_listen_again(path):
    """(read at epoch, [items]) from ytm_sync.py's file, or (None, [])."""
    try:
        d = json.load(open(path, encoding="utf-8"))
        return datetime.fromisoformat(d["pulled"]).timestamp(), d.get("items", [])
    except (OSError, ValueError, KeyError, TypeError):
        return None, []


def h2_picks(rows):
    """Songs you started yourself on the H2, from its play log as synced into `plays`
    (rows: (video_id, ts, event, seconds), source 'h2', in time order) -> [(vid, ts)].
    The log has no "you picked this" mark (picks.bin carries one from 2026-10-22's firmware
    on), so: a play right after a switch (you chose something while a song played) or at the
    start of a sitting, kept PICK_KEEP_S or more (finished, or left past that)."""
    out = []
    prev_event, prev_ts = None, None
    for i, (vid, ts, ev, _sec) in enumerate(rows):
        if ev == "play":
            picked = prev_event == "switch" or prev_ts is None or ts - prev_ts > SITTING_GAP
            if picked:
                kept = False
                for vid2, _ts2, ev2, sec2 in rows[i + 1:]:
                    if vid2 != vid:
                        continue
                    if ev2 == "complete":
                        kept = True
                        break
                    if ev2 in ("skip", "switch", "dislike"):
                        kept = ev2 != "dislike" and (sec2 or 0.0) >= PICK_KEEP_S
                        break
                    if ev2 == "play":
                        break
                if kept:
                    out.append((vid, ts))
        if ev != "peek":
            prev_event, prev_ts = ev, ts
    return out


def items(listen_again, la_read, picks, tail, lib, by_artist, now):
    """The Wheel in order: [{kind, key, id, title, sub, tracks, score, last}].
    listen_again: ytm_sync.py's items; la_read: when they were read (epoch);
    picks: [(key, ts)] -- key a video id, or "list:<id>" for a list tile you started;
    tail: the old history order (video ids, most replayed first);
    lib: library video ids; by_artist: {casefolded artist name: [library ids]}."""
    out = {}

    def add(key, kind, ident, title, sub, tracks, score, last=0.0):
        it = out.get(key)
        if it is None:
            out[key] = {"kind": kind, "key": key, "id": ident, "title": title, "sub": sub,
                        "tracks": tracks, "score": score, "last": last}
        else:
            it["score"] += score
            it["last"] = max(it["last"], last)

    n = max(1, len(listen_again))
    fade = decay(now - la_read) if la_read else 0.0
    for pos, it in enumerate(listen_again):
        w = fade * (LA_TOP - (LA_TOP - LA_END) * pos / n)
        kind, ident = it.get("kind"), it.get("id")
        if kind == "song":
            if ident in lib:
                add(ident, "song", ident, it.get("title", ""), it.get("subtitle", ""), [ident], w, la_read)
            continue
        if kind in ("album", "playlist"):
            tracks = [t["video_id"] for t in it.get("tracks", []) if t.get("video_id") in lib]
        elif kind == "artist":
            tracks = list(by_artist.get(" ".join(it.get("title", "").split()).casefold(), []))
        else:
            continue
        if len(tracks) >= MIN_LIST_SONGS:
            add(f"list:{ident}", kind, ident, it.get("title", ""), it.get("subtitle", ""), tracks, w, la_read)
    for key, ts in picks:
        if key.startswith("list:"):
            if key in out:                          # a list tile you started from
                add(key, None, None, None, None, None, decay(now - ts), ts)
        elif key in lib:
            add(key, "song", key, "", "", [key], decay(now - ts), ts)
    m = max(1, len(tail))
    for rank, v in enumerate(tail):
        if v in lib and v not in out:           # fills in after; never lifts what's there
            add(v, "song", v, "", "", [v], TAIL_W * (1 - rank / m), 0.0)
    return sorted(out.values(), key=lambda it: (it["score"], it["last"]), reverse=True)
