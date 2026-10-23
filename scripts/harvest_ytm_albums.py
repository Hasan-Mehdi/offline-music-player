#!/usr/bin/env python3
"""Whole soundtracks that ARE on YouTube Music as albums -> a download list, one album each.

harvest_ost_playlists.py covers games whose official music isn't on YouTube Music (fan rips
on plain YouTube). Some are there properly -- Death Stranding's scores and song albums come
from Sony / the artists -- so this reads the albums themselves (no cookies needed), gives
each the album name the H2's Soundtracks list shows and the track numbers, and writes the
same columns as data/ost_playlists.csv. A track YouTube Music lists without a video (not
playable here) is looked up by artist + title among its songs.

  .venv\\Scripts\\python scripts\\harvest_ytm_albums.py                 # -> data/ost_ytm_albums.csv
  powershell -File scripts\\download.ps1 -InputCsv data\\ost_ytm_albums.csv -Cookies auth\\yt_cookies.txt
  .venv\\Scripts\\python scripts\\harvest_ytm_albums.py --append      # the rows onto ost_playlists.csv
        # (the card export puts those albums first, whole; autosync retags from it)
"""
import argparse
import csv
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["video_id", "title", "artist", "album", "track_no", "curated_freq", "playlist_freq", "url", "source_title"]

# (album as the card shows it, YouTube Music album browse id)
ALBUMS = [
    # 2026-10-19: "death stranding 1 and 2 soundtracks"
    ("Death Stranding", "MPREb_zNyZ0kY1Lyk"),                              # Original Score
    ("Death Stranding: Original Score Vol. 2", "MPREb_tF0YXU3maBx"),
    ("Death Stranding: Timefall", "MPREb_QBkhUva84t6"),                    # the songs album
    ("Death Stranding 2: On the Beach", "MPREb_p5SPAaQ0wW0"),              # Original Video Game Score
    ("Death Stranding 2: Songs", "MPREb_wZdu1oc5AhP"),                     # Songs from the Video Game
    ("Woodkid for Death Stranding 2", "MPREb_3lTvRYWGmpj"),
]
# "(From "Death Stranding" Score)", "feat. X (feat. X)" -- the album says it already
FROM = re.compile(r'\s*\((from|From) "[^"]*"[^)]*\)')


def clean(title):
    t = FROM.sub("", title)
    t = re.sub(r"\s+feat\. [^()]+(?=\s*\(feat\.)", "", t)          # "X feat. Y (feat. Y)" -> "X (feat. Y)"
    return t.strip()


def find_song(yt, artist, title, secs):
    """a track the album lists without a video: the same song by the same artist, near its length"""
    for r in yt.search(f"{artist} {title}", filter="songs")[:10]:
        names = [a["name"].lower() for a in r.get("artists") or []]
        if r.get("videoId") and artist.lower() in names and r["title"].lower().startswith(title.lower()) \
                and abs((r.get("duration_seconds") or 0) - secs) <= 10:
            return r["videoId"]
    return None


def harvest():
    from ytmusicapi import YTMusic
    yt = YTMusic()
    rows, seen = [], set()
    for album, bid in ALBUMS:
        a = yt.get_album(bid)
        n = 0
        for k, t in enumerate(a["tracks"], 1):
            artists = [x["name"] for x in t.get("artists") or [] if x["name"] != "Death Stranding: Timefall"]
            artist = ", ".join(artists) or a["artists"][0]["name"]
            vid = t.get("videoId") or find_song(yt, artists[0] if artists else artist, t["title"],
                                                t.get("duration_seconds") or 0)
            if not vid:
                print(f"  {album} #{k}: {artist} - {t['title']}: not playable here, skipped")
                continue
            if vid in seen:                                   # Woodkid's "feat. Elle Fanning" is track 1 again
                continue
            seen.add(vid)
            rows.append({"video_id": vid, "title": clean(t["title"]), "artist": artist, "album": album,
                         "track_no": t.get("trackNumber") or k, "curated_freq": 0, "playlist_freq": 0,
                         "url": f"https://music.youtube.com/watch?v={vid}", "source_title": t["title"]})
            n += 1
        print(f"{album}: {n} of {len(a['tracks'])}")
    return rows


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "ost_ytm_albums.csv"))
    ap.add_argument("--append", action="store_true", help="add --out's rows to data/ost_playlists.csv")
    a = ap.parse_args()
    out = Path(a.out)
    if a.append:
        main_csv = ROOT / "data" / "ost_playlists.csv"
        with main_csv.open(encoding="utf-8-sig") as fh:
            have = {r["video_id"] for r in csv.DictReader(fh)}
        with out.open(encoding="utf-8-sig") as fh:
            new = [r for r in csv.DictReader(fh) if r["video_id"] not in have]
        shutil.copy2(main_csv, main_csv.with_name("ost_playlists.pre_ytm_albums.csv"))
        with main_csv.open("a", encoding="utf-8", newline="") as fh:
            csv.DictWriter(fh, fieldnames=FIELDS).writerows(new)
        print(f"{len(new)} rows added to {main_csv}")
        return
    rows = harvest()
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} tracks -> {out}")


if __name__ == "__main__":
    main()
