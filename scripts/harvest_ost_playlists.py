#!/usr/bin/env python3
"""Whole game soundtracks from YouTube playlists -> a download list, one album per game.

The official Pokémon and Zelda soundtracks aren't on YouTube Music as albums (searching
there finds remixes, lo-fi and piano covers), but full rips sit on plain YouTube as
playlists, one video per track. Each game below names the playlist picked by hand
(2026-10-15: complete, natural-length tracks, no hour loops), the album it becomes and
who it's by. Every entry gets a clean title (the game's name and the uploader's numbering
taken off), the album, and its place in the playlist as the track number, so the H2's
Soundtracks list shows each game as one crate in game order.

  .venv\\Scripts\\python scripts\\harvest_ost_playlists.py                # -> data/ost_playlists.csv
  powershell -File scripts\\download.ps1 -InputCsv data\\ost_playlists.csv -Cookies auth\\yt_cookies.txt
  .venv\\Scripts\\python scripts\\harvest_ost_playlists.py --retag D:\\OfflineMusic
        # album + track number onto files downloaded before (the archive skips them)
  .venv\\Scripts\\python scripts\\harvest_ost_playlists.py --only "Mario & Luigi" --out data\\ost_mario_luigi.csv

Needs a signed-in cookie file (YouTube bot-checks guests): a copy of auth/yt_cookies.txt
is used, never the file itself (yt-dlp rewrites the jar it reads).
"""
import argparse
import csv
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (album, artist, playlist id) in download order: the ones asked for by name first, then
# by how much each game shows up in the YouTube Music history
GAMES = [
    # 10-15 evening: mostly in the library already from other uploads of these playlists,
    # untagged; the DLC album splits off (album_of)
    ("Hollow Knight", "Christopher Larkin", "PLmOldskd2VbL7_t-NE9p6rEboq_v0AHko"),
    ("Hollow Knight: Silksong", "Christopher Larkin", "PLbNT78Q7M14yC4iIN4RaQqGa6q6zY6bqc"),
    ("Pokémon Legends: Arceus", "GAME FREAK", "PLDuK_JKMWsGj6Qj702A3b8q2TGU3hPXOR"),
    ("Pokémon Legends: Z-A", "GAME FREAK", "PL90nj2rNFfbcE2HR8S2TNT_h2DjM1nDGb"),
    ("Pokémon Colosseum", "Genius Sonority", "PLYDdhHVGYrjKWNbIbG61tL7ss1ONauxEr"),
    ("Need for Madness", "Radicalplay", "PLLnLLTtbLRI6wFLjiI5sJaU1mgNWAP90R"),   # 1 and 2: split by title
    ("Pokémon Black & White", "GAME FREAK", "PL4DA9DFA77C8FF491"),
    ("Pokémon Diamond, Pearl & Platinum", "GAME FREAK", "PLQOt6x9a9xdSjsJbKolxZiTMiUjyZm-Xm"),
    ("Pokémon Sword & Shield", "GAME FREAK", "PLlIlOOdWDLMgsED6RXCWN1Uo6aovmGNyr"),
    ("Pokémon HeartGold & SoulSilver", "GAME FREAK", "PL4D041F2804E14B21"),
    ("Pokémon Black 2 & White 2", "GAME FREAK", "PLMNd7l5z4pbieh3OXLc7rnFC5kxO5IlCY"),
    ("The Legend of Zelda: Ocarina of Time", "Koji Kondo", "PLDDC74011619A10AE"),
    ("The Legend of Zelda: The Wind Waker", "Kenta Nagata", "PLgQYCDwtVg4e6zO_OBAIlON1LJLRrXC1y"),
    ("The Legend of Zelda: Breath of the Wild", "Manaka Kataoka", "PLh4Eme5gACZEAazTK1vSZn3DCYJLQ4YHH"),
    ("The Legend of Zelda: Tears of the Kingdom", "Manaka Kataoka", "PL2P_YMgOOlgWUTXdNw3o3UstuN110zGb2"),
    ("The Legend of Zelda: Twilight Princess", "Toru Minegishi", "PL7C6385BCF05B7290"),
    ("The Legend of Zelda: Majora's Mask", "Koji Kondo", "PLWeCcixVkuYZ9Fun16eKi3x72flKKyL1s"),
    # 10-18: the whole Mario & Luigi series, the 3DS remakes as their own albums
    ("Mario & Luigi: Superstar Saga", "Yoko Shimomura", "PLXQMeRR5llU-_b1wHNCo5w2Lbszy9B6dO"),
    ("Mario & Luigi: Superstar Saga + Bowser's Minions", "Yoko Shimomura", "PLXQMeRR5llU9iuIvYgBTMVJWaxfJKE8P5"),
    ("Mario & Luigi: Partners in Time", "Yoko Shimomura", "PLl-vhnGPY7cqQ0b_NXy1qyMVsA9LHiPmv"),
    ("Mario & Luigi: Bowser's Inside Story", "Yoko Shimomura", "PLXQMeRR5llU98dzIq2P_lpaYf9LEcA1qr"),
    ("Mario & Luigi: Bowser's Inside Story + Bowser Jr.'s Journey", "Yoko Shimomura", "PLXQMeRR5llU8jRYzmd05wvoNUS8uLRFMv"),
    ("Mario & Luigi: Dream Team", "Yoko Shimomura", "PL91peE3qJHcJKvLyhF95rIY2JcZsKRd-v"),
    ("Mario & Luigi: Paper Jam", "Yoko Shimomura", "PLTlzTb9fVrYYqDYOdBmNFWUaPQncz85dK"),
    ("Mario & Luigi: Brothership", "Yoko Shimomura", "PLacrXFZ0srRr_GKlAbzqBHvc9h-j2Zchs"),
]
MAX_SECONDS = 15 * 60                    # whole-OST videos and hour loops are not tracks
DROP = re.compile(r"\btrailer\b|full ost|full soundtrack|\b1 ?hour\b|extended", re.I)

# the game's name, the uploader's own numbering and labels, wherever they put them
GAME_WORDS = [
    r"pok[eé]mon legends:? arceus", r"pok[eé]mon legends:? z-a( \+ mega dimension)?", r"super music collection",
    r"pok[eé]mon colosseum", r"pok[eé]mon b/w", r"pok[eé]mon bw2", r"pok[eé]mon diamond, pearl & platinum",
    r"pok[eé]mon platinum", r"pok[eé]mon sword (and|&) shield", r"pok[eé]mon hg/ss",
    r"the legend of zelda:? ?(ocarina of time|the wind ?waker|breath of the wild|tears of the kingdom|majora's mask)",
    r"ocarina of time complete soundtrack", r"twilight princess soundtrack", r"tears of the kingdom",
    r"hollow knight:? (silksong|gods & nightmares)",
    r"mario\s+(&|and)\s+luigi:?\s*(superstar saga( \+ bowser's minions)?|partners in time|"
    r"bowser'?s inside story( \+ bowser jr\.? ?'?s journey)?|dream team|paper jam|brothership|bis \+ bjj)", r"\(3ds\)", r"^\s*hollow knight ost\b", r"original score",
    r"official soundtrack", r"original soundtrack", r"\bost\b", r"\bsoundtrack\b", r"\(n64\)",
]


def clean_title(t, album):
    s = (t or "").replace("‐", "-").replace("–", "-")      # "Moss Grotto ‐ Hollow Knight..."
    s = re.sub(r"^\s*\d+\s*[-.)]\s*", "", s)                       # "12 - ", "12. "
    for w in GAME_WORDS:
        s = re.sub(w, " ", s, flags=re.I)
    s = re.sub(r"\(\s*\)|\[\s*\]", " ", s)
    s = re.sub(r"\s*\|\s*", " | ", s)
    parts = [re.sub(r"^\d+\s+", "", p.strip(" -:|\"'")) for p in re.split(r"\s+[-|:]\s+|\s*\|\s*", s)]
    parts = [p for p in parts if p and not re.fullmatch(r"complete|\d+", p, re.I)]
    s = " - ".join(parts) if parts else (t or "")
    s = re.sub(r"^\d+\s+", "", s)                                   # "01 Opening"
    s = re.sub(r"\s{2,}", " ", s).strip(" -\"'")
    q = re.search(r'"([^"]+)"', t or "")                            # 01 ... OST "Opening"
    if q and len(q.group(1)) > 2:
        s = q.group(1)
    return s or (t or "").strip()


def nfm_album(title):
    return "Need for Madness 2" if re.search(r"madness\s*2|nfm\s*2", title, re.I) else "Need for Madness"


def album_of(album, title, i):
    """the album and track number a playlist entry goes under; None leaves it out"""
    if album == "Need for Madness":
        return nfm_album(title), i
    if album == "Hollow Knight":
        # the DLC singles that Gods & Nightmares collects, and Silksong's teasers
        if re.search(r"hidden dreams|: the grimm troupe\)|ost sample", title, re.I):
            return None
        m = re.match(r"\s*(\d+)\s.*gods & nightmares", title, re.I)
        if m:
            return "Hollow Knight: Gods & Nightmares", int(m.group(1))
    return album, i


def harvest(cookies, only=None):
    import yt_dlp
    jar = Path(tempfile.mkdtemp()) / "cookies.txt"
    shutil.copy(cookies, jar)
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "cookiefile": str(jar),
            "js_runtimes": {"node": {"path": None}}}
    rows, seen = [], set()
    with yt_dlp.YoutubeDL(opts) as y:
        for album, artist, pl in GAMES:
            if only and only.lower() not in album.lower():
                continue
            info = y.extract_info(f"https://www.youtube.com/playlist?list={pl}", download=False)
            n = 0
            for i, e in enumerate([e for e in (info.get("entries") or []) if e and e.get("id")], 1):
                vid, title, dur = e["id"], e.get("title") or "", e.get("duration") or 0
                if vid in seen or (dur and dur > MAX_SECONDS) or DROP.search(title) or not title or title in ("[Private video]", "[Deleted video]"):
                    continue
                placed = album_of(album, title, i)
                if not placed:
                    continue
                seen.add(vid)
                alb, no = placed
                rows.append({"video_id": vid, "title": clean_title(title, alb), "artist": artist, "album": alb,
                             "track_no": no, "curated_freq": 0, "playlist_freq": 0,
                             "url": f"https://www.youtube.com/watch?v={vid}", "source_title": title})
                n += 1
            print(f"  {album}: {n} tracks")
    return rows


def retag(rows, music_dir):
    """album, track number, the clean title and the composer onto files already on disk
    (ones from other uploads of a playlist carry the uploader's name as the artist)"""
    from mutagen.oggopus import OggOpus
    by_id = {r["video_id"]: r for r in rows}
    done = 0
    for p in Path(music_dir).glob("*.opus"):
        m = re.search(r"\[([A-Za-z0-9_-]{11})\]\.opus$", p.name)
        r = by_id.get(m.group(1)) if m else None
        if not r:
            continue
        f = OggOpus(str(p))
        if (f.get("album") or [""])[0] == r["album"] and (f.get("tracknumber") or [""])[0] == str(r["track_no"]) \
                and (f.get("artist") or [""])[0] == r["artist"]:
            continue
        f["album"] = [r["album"]]
        f["tracknumber"] = [str(r["track_no"])]
        f["title"] = [r["title"]]
        f["artist"] = [r["artist"]]
        f.save()
        done += 1
    print(f"retagged {done} files")
    # the library index (build_library_db.py) skips a file it has read before, so new tags on
    # one it already had (another upload of the playlist, a retag) reach it only here
    import sqlite3
    con = sqlite3.connect(ROOT / "data" / "library.db", timeout=120)
    fixed = 0
    for r in rows:
        have = con.execute("SELECT title, artist, album, track_no, genre FROM tracks WHERE video_id=?",
                           (r["video_id"],)).fetchone()
        want = (r["title"], r["artist"], r["album"], int(r["track_no"]))
        if not have or tuple(have[:4]) == want:
            continue
        con.execute("UPDATE tracks SET title=?, artist=?, album=?, track_no=? WHERE video_id=?", (*want, r["video_id"]))
        con.execute("DELETE FROM tracks_fts WHERE video_id=?", (r["video_id"],))
        con.execute("INSERT INTO tracks_fts (video_id, title, artist, album, genre) VALUES (?,?,?,?,?)",
                    (r["video_id"], want[0], want[1], want[2], have[4]))
        fixed += 1
    con.commit()
    con.close()
    print(f"library index: {fixed} songs brought up to date")


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "ost_playlists.csv"))
    ap.add_argument("--cookies", default=str(ROOT / "auth" / "yt_cookies.txt"))
    ap.add_argument("--retag", default=None, help="music folder: tag files already downloaded")
    ap.add_argument("--only", default=None, help="just the games whose album has this in it (e.g. \"Mario & Luigi\")")
    a = ap.parse_args()
    out = Path(a.out)
    if a.retag:
        with out.open(encoding="utf-8-sig") as fh:
            retag(list(csv.DictReader(fh)), a.retag)
        return
    rows = harvest(a.cookies, a.only)
    fields = ["video_id", "title", "artist", "album", "track_no", "curated_freq", "playlist_freq", "url", "source_title"]
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} tracks -> {out}")


if __name__ == "__main__":
    main()
