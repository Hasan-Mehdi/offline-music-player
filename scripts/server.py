#!/usr/bin/env python3
"""Player backend API for the Svelte UI.

Serves the library (browse + FTS5 search) from data/library.db, range-audio, and play
tracking. MuQ-backed semantic-search / map endpoints are loaded lazily on first use so
the server starts instantly for normal browsing.

Run:  .venv\\Scripts\\python scripts\\server.py      -> http://127.0.0.1:5000
In dev the Vite server (web/) proxies /api + /audio here.
"""
from __future__ import annotations

import csv
import difflib
import json
import math
import os
import re
import shutil
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, g, jsonify, request, send_file, send_from_directory

ROOT = Path(__file__).resolve().parent.parent
# PLAYER_DB lets a test (or a second instance) point the whole app at another library
# without touching the real one — everything below reads this single constant.
DB = Path(os.environ.get("PLAYER_DB") or (ROOT / "data" / "library.db"))
GENRE_CSV = ROOT / "data" / "artist_genre.csv"
WEB_DIST = ROOT / "web" / "dist"
TRASH_LOG = ROOT / "data" / "trashed_rows.jsonl"   # undo log for /api/trash (see purge_apply.py)
TRASH_DIRNAME = "_trash"

app = Flask(__name__)

# artist -> broad genre (from the Haiku labels; files have no genre tag)
ARTIST_GENRE: dict[str, str] = {}
if GENRE_CSV.exists():
    for r in csv.DictReader(open(GENRE_CSV, encoding="utf-8-sig")):
        if r.get("artist"):
            ARTIST_GENRE[r["artist"].strip().lower()] = r.get("genre", "")

# one-time: plays table for tracking. Generous busy timeouts throughout: batch writers
# (scan_loudness.py, build_library_db.py) hold long write locks and the player must not
# crash or 500 while one runs.
with sqlite3.connect(DB, timeout=60) as _c:
    _c.execute("CREATE TABLE IF NOT EXISTS plays(video_id TEXT, ts REAL, event TEXT, seconds REAL)")
    # provenance, added after the table shipped: `source` = the surface a track was
    # started from, `session_id` = the client's listening session. Lazily migrated in
    # the same spirit as the CREATE above, so an existing log keeps working untouched.
    _pcols = {r[1] for r in _c.execute("PRAGMA table_info(plays)")}
    for _col in ("source", "session_id"):
        if _col not in _pcols:
            _c.execute(f"ALTER TABLE plays ADD COLUMN {_col} TEXT")
    _c.execute("CREATE INDEX IF NOT EXISTS ix_plays_vid_ts ON plays(video_id, ts)")


def db() -> sqlite3.Connection:
    c = getattr(g, "_db", None)
    if c is None:
        c = g._db = sqlite3.connect(DB, timeout=30)
        c.row_factory = sqlite3.Row
    return c


@app.teardown_appcontext
def _close(exc):
    c = getattr(g, "_db", None)
    if c is not None:
        c.close()


def genre_of(artist: str) -> str:
    return ARTIST_GENRE.get((artist or "").strip().lower(), "")


# hook points come from the `analysis` table, which a background sweep is still filling.
# Cache the whole (small) map and re-read it periodically so newly analysed tracks light
# up without a restart; a missing table / empty map just means no hooks (null everywhere).
_HOOKS = {"t": -1.0, "map": {}}
HOOK_TTL = 60.0


def hooks() -> dict:
    if time.time() - _HOOKS["t"] > HOOK_TTL:
        _HOOKS["t"] = time.time()
        try:
            _HOOKS["map"] = {r[0]: r[1] for r in db().execute(
                "SELECT video_id, hook_sec FROM analysis WHERE hook_sec IS NOT NULL")}
        except sqlite3.Error:
            _HOOKS["map"] = {}
    return _HOOKS["map"]


def trow(r: sqlite3.Row) -> dict:
    keys = r.keys()
    return {"id": r["video_id"], "title": r["title"], "artist": r["artist"],
            "album": r["album"], "duration": r["duration"], "genre": genre_of(r["artist"]),
            # R128 track gain (dB to -23 LUFS); player normalizes with it. album_gain_db is
            # a newer column (may not exist yet) — the player prefers it in album mode so
            # within-album dynamics survive.
            "gain": r["r128_gain_db"],
            "album_gain_db": r["album_gain_db"] if "album_gain_db" in keys else None,
            # audition point for the wheel's peek; null until the analysis sweep gets here
            "hook_sec": hooks().get(r["video_id"])}


# --------------------------------------------------------------------------- API

@app.get("/api/stats")
def stats():
    c = db()
    return jsonify({
        "tracks": c.execute("SELECT COUNT(*) FROM tracks").fetchone()[0],
        "artists": c.execute("SELECT COUNT(DISTINCT artist) FROM tracks WHERE artist<>''").fetchone()[0],
        "albums": c.execute("SELECT COUNT(DISTINCT album) FROM tracks WHERE album<>''").fetchone()[0],
        "genres": len(set(ARTIST_GENRE.values())),
    })


@app.get("/api/tracks")
def tracks():
    sort = {"title": "title", "artist": "artist", "album": "album",
            "duration": "duration"}.get(request.args.get("sort", "artist"), "artist")
    limit = min(int(request.args.get("limit", 200)), 2000)
    offset = int(request.args.get("offset", 0))
    rows = db().execute(
        f"SELECT * FROM tracks ORDER BY {sort} COLLATE NOCASE, title COLLATE NOCASE "
        f"LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return jsonify([trow(r) for r in rows])


@app.get("/api/artists")
def artists():
    rows = db().execute(
        "SELECT artist, COUNT(*) n, MIN(video_id) vid FROM tracks WHERE artist<>'' "
        "GROUP BY artist ORDER BY n DESC, artist COLLATE NOCASE").fetchall()
    return jsonify([{"artist": r["artist"], "count": r["n"], "vid": r["vid"],
                     "genre": genre_of(r["artist"])} for r in rows])


@app.get("/api/artist")
def artist():
    name = request.args.get("name", "")
    rows = db().execute("SELECT * FROM tracks WHERE artist=? ORDER BY album COLLATE NOCASE, "
                        "track_no, title COLLATE NOCASE", (name,)).fetchall()
    return jsonify({"artist": name, "genre": genre_of(name), "tracks": [trow(r) for r in rows]})


@app.get("/api/genres")
def genres():
    rows = db().execute("SELECT artist FROM tracks WHERE artist<>''").fetchall()
    c = Counter(genre_of(r["artist"]) or "unlabeled" for r in rows)
    return jsonify([{"genre": g, "count": n} for g, n in c.most_common()])


@app.get("/api/genre")
def genre():
    name = request.args.get("name", "")
    rows = db().execute("SELECT * FROM tracks WHERE artist<>'' ORDER BY artist COLLATE NOCASE, "
                        "title COLLATE NOCASE").fetchall()
    want = name.lower()
    out = [trow(r) for r in rows if (genre_of(r["artist"]) or "unlabeled").lower() == want]
    return jsonify({"genre": name, "tracks": out})


# --------------------------------------------------------------------------- soundtracks (OST)
# This collection is mostly game music, but album metadata is sparse (most rows have
# album=''), so a soundtrack's identity usually lives in the title: "Track - GAME [OST]".
# Group by album when present, else by the game name parsed off the title, cleaned of
# soundtrack suffixes. A minimum group size kills the long tail of title-parse noise
# (stray "- Composer" / mis-split parens that only ever hit once or twice).
MIN_OST_TRACKS = 4
_OST_SUFFIX = re.compile(
    r"\s*[\(\[]?\s*(original game soundtrack|original soundtrack|game soundtrack|"
    r"soundtrack|ost)\s*[\)\]]?\s*$", re.I)
_OST_INDEX = None   # (payload list, {name_lower: [video_id ordered]}) — static within a run


def _clean_ost(base):
    """Strip trailing OST/soundtrack markers and trailing (…)/[…] tags, repeatedly."""
    s, prev = base.strip(), None
    while s and s != prev:
        prev = s
        s = _OST_SUFFIX.sub("", s).strip()
        s = re.sub(r"\s*[\(\[][^\(\)\[\]]*[\)\]]\s*$", "", s).strip()
    return s


def _ost_name(album, title):
    if album and album.strip():
        base = album.strip()
    elif " - " in title:
        base = title.rsplit(" - ", 1)[1]
    else:
        return None
    name = _clean_ost(base)
    return name if len(name) >= 3 else None


def _load_ost_catalog():
    """LLM curation (scripts/curate_osts.py + a Haiku pass) keyed by the heuristic group
    key -> {keep, canonical, franchise}: drop nonsense groups, fix mangled names, merge
    duplicates, and supply a franchise for ordering. Absent file -> raw heuristic behaviour."""
    p = ROOT / "data" / "ost_catalog.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _ost_index():
    global _OST_INDEX
    if _OST_INDEX is None:
        cat = _load_ost_catalog()
        rows = db().execute(
            "SELECT video_id, title, album, duration, track_no FROM tracks").fetchall()
        groups = {}
        for r in rows:
            nm = _ost_name(r["album"] or "", r["title"] or "")
            if not nm:
                continue
            ov = cat.get(nm.lower())
            if ov is not None and not ov.get("keep", True):
                continue                                    # curation flagged it as nonsense
            disp = (ov.get("canonical") if ov else "") or nm
            fr = ov.get("franchise", "") if ov else ""
            # merge on the canonical name so duplicate rips of one OST collapse together
            g = groups.setdefault(disp.lower(),
                                  {"name": disp, "franchise": fr, "items": [], "sec": 0.0})
            if fr and not g["franchise"]:
                g["franchise"] = fr
            g["items"].append((r["track_no"] if r["track_no"] is not None else 9999,
                               (r["title"] or "").lower(), r["video_id"]))
            g["sec"] += r["duration"] or 0.0
        payload, members = [], {}
        for key, g in groups.items():
            if len(g["items"]) < MIN_OST_TRACKS:
                continue
            g["items"].sort()
            vids = [it[2] for it in g["items"]]
            members[key] = vids
            payload.append({"name": g["name"], "franchise": g["franchise"],
                            "count": len(vids), "seconds": round(g["sec"]), "covers": vids[:6]})
        # order: cluster franchises that actually have >=2 soundtracks under a section
        # (Sonic, Mario…), biggest franchise first and biggest OST first within it; lone
        # games + standalone fall into a trailing "" section by size. Reads like a sorted
        # crate, and one-off games don't each get a lonely header.
        fr_groups = Counter(o["franchise"] for o in payload if o["franchise"])
        for o in payload:
            fr = o["franchise"]
            o["section"] = fr if (fr and fr_groups[fr] >= 2) else ""
        sec_total = Counter()
        for o in payload:
            sec_total[o["section"]] += o["count"]
        payload.sort(key=lambda o: (0 if o["section"] else 1, -sec_total[o["section"]],
                                    o["section"].lower(), -o["count"], o["name"].lower()))
        _OST_INDEX = (payload, members)
    return _OST_INDEX


@app.get("/api/osts")
def osts():
    """The soundtrack index: game/OST 'sleeves' with track count, runtime, cover vids."""
    return jsonify(_ost_index()[0])


@app.get("/api/ost")
def ost():
    """One soundtrack's tracks, in album order."""
    name = request.args.get("name", "")
    members = _ost_index()[1]
    vids = members.get(name.lower(), [])
    if not vids:
        return jsonify({"name": name, "tracks": []})
    qs = ",".join("?" * len(vids))
    rows = {r["video_id"]: r for r in db().execute(
        f"SELECT * FROM tracks WHERE video_id IN ({qs})", vids)}
    return jsonify({"name": name, "tracks": [trow(rows[v]) for v in vids if v in rows]})


def _fts(c, match, limit=80):
    try:
        return c.execute(
            "SELECT t.*, bm25(tracks_fts) AS fts_rank FROM tracks_fts f "
            "JOIN tracks t ON t.video_id=f.video_id WHERE tracks_fts MATCH ? "
            "ORDER BY bm25(tracks_fts) LIMIT ?", (match, limit)).fetchall()
    except sqlite3.OperationalError:
        return []


@app.get("/api/search")
def search():
    """Tiered search: exact AND-prefix > any-term prefix > substring > one-typo variants,
    then re-ranked with a personal boost from the plays log (a track you actually play
    outranks a cold metadata match) and query-shape boosts (title/artist starts-with)."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    toks = [t for t in q.replace('"', " ").lower().split() if t]
    if not toks:
        return jsonify([])
    c = db()
    seen, cand = set(), []

    def add(rows, tier):
        for r in rows:
            vid = r["video_id"]
            if vid in seen:
                continue
            seen.add(vid)
            fts = r["fts_rank"] if "fts_rank" in r.keys() else 0.0
            cand.append((r, tier - 0.4 * float(fts or 0.0)))   # bm25: lower = better

    # 1) all terms as prefixes (FTS5 AND)
    add(_fts(c, " ".join(f'"{t}"*' for t in toks)), 10.0)
    # 2) any term as prefix
    if len(cand) < 30 and len(toks) > 1:
        add(_fts(c, " OR ".join(f'"{t}"*' for t in toks)), 6.0)
    # 3) substring (catches mid-word: "tale" -> UnderTALE)
    if len(cand) < 30:
        for t in toks:
            like = f"%{t}%"
            add(c.execute(
                "SELECT * FROM tracks WHERE title LIKE ? OR artist LIKE ? OR album LIKE ? "
                "LIMIT 40", (like, like, like)).fetchall(), 4.0)
    # 4) one-edit typo variants (deletions + adjacent swaps) as prefixes
    if len(cand) < 12:
        variants = set()
        for t in toks:
            if len(t) < 4:
                continue
            for i in range(len(t)):
                variants.add(t[:i] + t[i + 1:])                      # deletion
                if i < len(t) - 1:
                    variants.add(t[:i] + t[i + 1] + t[i] + t[i + 2:])  # swap
        if variants:
            add(_fts(c, " OR ".join(f'"{v}"*' for v in list(variants)[:30]), 40), 2.0)

    # personal boost: what you actually play wins ties (and some non-ties)
    plays_n = {r[0]: r[1] for r in c.execute(
        "SELECT video_id, COUNT(*) FROM plays GROUP BY video_id")}
    ql = q.lower()
    out = []
    for r, score in cand:
        n = plays_n.get(r["video_id"], 0)
        if n:
            score += min(3.0, 1.0 + 0.6 * math.log2(1 + n))
        title, artist = (r["title"] or "").lower(), (r["artist"] or "").lower()
        if title.startswith(ql):
            score += 4.0
        if artist.startswith(ql):
            score += 3.0
        if all(t in title or t in artist for t in toks):
            score += 1.5
        # per-token word-prefix credit + fuzzy whole-query similarity to the artist,
        # so "toby fx" still puts Toby Fox on top
        words = title.split() + artist.split()
        score += 0.8 * sum(1 for t in toks if any(w.startswith(t) for w in words))
        ra = difflib.SequenceMatcher(None, ql, artist).ratio()
        rt = difflib.SequenceMatcher(None, ql, title).ratio()
        fz = max(ra, rt)
        if fz > 0.6:
            score += 4.0 * fz
        out.append((score, r))
    out.sort(key=lambda x: -x[0])
    return jsonify([trow(r) for _s, r in out[:100]])


# --------------------------------------------------------------------------- hum-to-search
# Query-by-humming: the browser records a short clip and POSTs the raw bytes here; we match
# its pitch contour against a prebuilt melody index (scripts/build_melody_index.py, owned by
# a separate module). Heavy deps + the index load lazily on first call, like the map/radio
# endpoints — normal browsing never pays for them.
MELODY_INDEX = ROOT / "data" / "melody_index.npz"
_MELODY = None   # cached (index file mtime, melody_match index) — reloads when the npz is rebuilt
_NO_INDEX = {"error": "Melody index not built yet — run scripts/build_melody_index.py"}
HUM_DEBUG_DIR = ROOT / "data" / "hum_debug"
HUM_DEBUG_KEEP = 20   # queries (each = one audio file + one .json)


def _save_hum_debug(data, suffix, outcome):
    """Keep the last N raw hum uploads + what we answered, so a bad match can be replayed
    offline:  python scripts/melody_match.py data/hum_debug/<file>.  Never fatal."""
    try:
        HUM_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        base = HUM_DEBUG_DIR / time.strftime("hum_%Y%m%d_%H%M%S")
        n = 0
        while base.with_suffix(suffix).exists() and n < 100:   # same-second uploads
            n += 1
            base = base.with_name(f"{base.name.split('~')[0]}~{n}")
        base.with_suffix(suffix).write_bytes(data)
        base.with_suffix(".json").write_text(
            json.dumps(outcome, ensure_ascii=False, indent=1), encoding="utf-8")
        old = sorted(HUM_DEBUG_DIR.glob("hum_*.json"))
        for p in old[:-HUM_DEBUG_KEEP]:
            for f in HUM_DEBUG_DIR.glob(p.stem + ".*"):
                f.unlink(missing_ok=True)
    except OSError:
        pass


@app.post("/api/hum")
def hum():
    """Match a hummed/whistled melody to the library. Body: the raw recorded audio
    (audio/webm;codecs=opus from MediaRecorder, or wav/ogg). ?top=N (default 10)."""
    global _MELODY
    if not MELODY_INDEX.exists():
        return jsonify(_NO_INDEX), 503
    try:
        from melody_match import load_index, search_hum
    except ImportError:
        # the matcher module isn't present yet — treat it as "not built" so the endpoint
        # keeps working (503, no crash) and lights up automatically once it lands.
        return jsonify(_NO_INDEX), 503
    mt = MELODY_INDEX.stat().st_mtime
    if _MELODY is None or _MELODY[0] != mt:
        _MELODY = (mt, load_index(db_path=str(DB), index_path=str(MELODY_INDEX)))

    data = request.get_data()
    if not data:
        return jsonify({"error": "No audio received — hold the mic and hum a few notes."}), 400
    try:
        top = max(1, min(int(request.args.get("top", 10)), 50))
    except ValueError:
        top = 10

    import tempfile
    suffix = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav",
              "audio/x-wav": ".wav", "audio/wave": ".wav"}.get(
                  (request.content_type or "").split(";")[0].strip().lower(), ".webm")
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(data)
        tmp.close()
        try:
            result = search_hum(_MELODY[1], tmp.name, top_n=top)
        except ValueError as e:
            _save_hum_debug(data, suffix, {"error": str(e)})
            return jsonify({"error": str(e)}), 400
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    hits = result.get("results", [])
    vids = [h["video_id"] for h in hits]
    rows = {}
    if vids:
        qs = ",".join("?" * len(vids))
        rows = {r["video_id"]: r for r in db().execute(
            f"SELECT * FROM tracks WHERE video_id IN ({qs})", vids)}
    out = []
    for h in hits:
        r = rows.get(h["video_id"])
        if not r:
            continue
        item = trow(r)                          # {id,title,artist,album,duration,genre}
        item["video_id"] = h["video_id"]        # contract alias (UI plays via .id)
        item["score"] = h.get("score")
        item["start_s"] = h.get("start_s")
        out.append(item)
    q = result.get("query", {})
    _save_hum_debug(data, suffix, {
        "n_notes": q.get("n_notes"), "duration_s": q.get("duration_s"),
        "results": [{"video_id": t["video_id"], "title": t.get("title"),
                     "artist": t.get("artist"), "score": t.get("score")} for t in out[:5]]})
    return jsonify({"results": out, "query": q})


@app.post("/api/play")
def play():
    """Log one interaction. Optional `source` (which surface started the track) and
    `session_id` (the client's listening session) are stored verbatim — they turn the
    flat log into something you can read back as sessions, and tell taste-from-the-wheel
    apart from taste-from-search."""
    d = request.get_json(force=True, silent=True) or {}
    vid = d.get("id")
    if not vid:
        return jsonify({"ok": False}), 400
    log_event(vid, d.get("event", "play"), d.get("seconds"),
              source=d.get("source"), session_id=d.get("session_id"))
    return jsonify({"ok": True})


def log_event(vid, event, seconds=None, source=None, session_id=None, ts=None):
    """Append one row to `plays` (named columns — the table gained provenance columns)."""
    db().execute(
        "INSERT INTO plays(video_id, ts, event, seconds, source, session_id) VALUES (?,?,?,?,?,?)",
        (vid, time.time() if ts is None else ts, event, seconds,
         source if source is None else str(source),
         session_id if session_id is None else str(session_id)))
    db().commit()


# --------------------------------------------------------------------------- likes
# A "like" is only ever a row in the plays log — there is no likes table. The current
# state of a track is therefore its LATEST like/unlike event, which keeps the taste
# model (personalize.event_weight) and the UI reading the exact same history.

@app.get("/api/likes")
def likes():
    """Tracks whose latest like/unlike event is a like, newest first, with metadata."""
    latest = {}
    for r in db().execute(
            "SELECT video_id, event, ts FROM plays WHERE event IN ('like','unlike') "
            "ORDER BY ts, rowid"):
        latest[r["video_id"]] = (r["event"], r["ts"] or 0.0)
    liked = sorted(((v, ts) for v, (ev, ts) in latest.items() if ev == "like"),
                   key=lambda e: -e[1])
    out = []
    for vid, ts in liked:
        t = track_by_id(vid)          # tracks-join: a trashed/purged track drops out
        if t:
            t["liked_at"] = ts
            out.append(t)
    return jsonify(out)


# --------------------------------------------------------------------------- history
# Listening sessions, reconstructed from the log. Rows written by the current client
# carry a session_id; everything logged before that lands in the NULL bucket and gets
# the engine's 30-minute-gap convention applied instead (personalize.SESSION_GAP_SECONDS).
SESSION_GAP = 30 * 60
HISTORY_SCAN = 6000        # newest plays rows considered (a session is ~dozens of rows)


@app.get("/api/history")
def history():
    try:
        limit = max(1, min(int(request.args.get("limit", 30) or 30), 200))
    except ValueError:
        limit = 30
    rows = [dict(r) for r in db().execute(
        "SELECT video_id, ts, event, session_id FROM plays "
        "WHERE event <> 'peek' AND ts IS NOT NULL ORDER BY ts DESC LIMIT ?", (HISTORY_SCAN,))]
    rows.reverse()                                   # oldest -> newest for grouping

    # bucket: explicit session_id when present, else gap-inferred over the legacy rows
    legacy_n, legacy_last = 0, None
    for r in rows:
        sid = r.get("session_id")
        if sid:
            r["_key"] = f"s:{sid}"
            continue
        if legacy_last is None or r["ts"] - legacy_last > SESSION_GAP:
            legacy_n += 1
        legacy_last = r["ts"]
        r["_key"] = f"g:{legacy_n}"

    sessions = {}
    for r in rows:
        s = sessions.setdefault(r["_key"], {"session_id": r.get("session_id"),
                                            "started": r["ts"], "ended": r["ts"],
                                            "order": [], "events": {}})
        s["started"] = min(s["started"], r["ts"])
        s["ended"] = max(s["ended"], r["ts"])
        if r["event"] == "play" and r["video_id"] not in s["events"]:
            s["order"].append(r["video_id"])
        s["events"].setdefault(r["video_id"], []).append((r["event"], r["ts"]))

    picked = sorted((s for s in sessions.values() if s["order"]),
                    key=lambda s: -s["started"])[:limit]
    need = {v for s in picked for v in s["order"]}
    meta = {}
    if need:
        ids = list(need)
        for chunk in (ids[i:i + 400] for i in range(0, len(ids), 400)):
            for r in db().execute("SELECT * FROM tracks WHERE video_id IN (%s)"
                                  % ",".join("?" * len(chunk)), chunk):
                meta[r["video_id"]] = trow(r)

    def outcome(evs):
        """One badge per track: an explicit like outrules everything, then how it ended."""
        names = {e for e, _ts in evs}
        if "like" in names:
            return "liked"
        if "complete" in names:
            return "completed"
        if "skip" in names:
            return "skipped"
        return "played"

    out = []
    for s in picked:
        tracks = []
        for vid in s["order"]:
            t = meta.get(vid)            # trashed tracks fall out of the join
            if not t:
                continue
            at = min(ts for e, ts in s["events"][vid] if e == "play")
            tracks.append({**t, "at": at, "outcome": outcome(s["events"][vid])})
        if not tracks:
            continue
        out.append({"session_id": s["session_id"], "started": s["started"],
                    "ended": s["ended"], "count": len(tracks), "tracks": tracks})
    return jsonify(out)


# --------------------------------------------------------------------------- trash
# Quarantine, not deletion — the same mechanics as scripts/purge_apply.py, one track at
# a time and reversible from the UI: the file moves to <library root>\_trash\, the tracks
# + tracks_fts rows go away, and the FULL original row is appended to
# data/trashed_rows.jsonl as the undo log. `neighbors` rows are deliberately LEFT behind
# (every consumer joins through tracks, so orphans are invisible — and restore is cheap).
# The 'trash' play event is logged FIRST and never removed: a thrown-away track is one of
# the strongest taste signals there is, and it must keep feeding the skip vector after
# the track itself is gone.

def _trash_entries():
    """Live trash manifest from the jsonl, oldest first. Restores/clears rewrite the
    file, so what is in it IS what is in the trash; the last entry per id wins."""
    if not TRASH_LOG.exists():
        return []
    by_id = {}
    try:
        for ln in TRASH_LOG.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            vid = (e.get("row") or {}).get("video_id")
            if vid:
                by_id[vid] = e
    except OSError:
        return []
    return list(by_id.values())


def _write_trash_entries(entries):
    TRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(TRASH_LOG, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _fsize(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


@app.post("/api/trash")
def trash_add():
    d = request.get_json(force=True, silent=True) or {}
    vid = d.get("id")
    if not vid:
        return jsonify({"ok": False, "error": "no id"}), 400
    # log the verdict before touching anything — it must survive even if the move fails
    log_event(vid, "trash", d.get("seconds"), source=d.get("source"),
              session_id=d.get("session_id"))
    r = db().execute("SELECT * FROM tracks WHERE video_id=?", (vid,)).fetchone()
    if not r:
        return jsonify({"ok": False, "error": "not in library"}), 404
    row = dict(r)
    src = Path(row["path"])
    dst = None
    if src.exists():
        qdir = src.parent / TRASH_DIRNAME
        try:
            qdir.mkdir(exist_ok=True)
            dst = qdir / src.name
            shutil.move(str(src), str(dst))
        except OSError as e:
            # Windows refuses to move a file that is still open (usually the very track
            # the player is streaming). Say so plainly; nothing else has changed yet.
            return jsonify({"ok": False, "locked": True,
                            "error": f"Couldn't move the file — it may still be playing. ({e})"}), 409
    TRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(TRASH_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "row": row,
                            "quarantined_to": str(dst) if dst else None},
                           ensure_ascii=False) + "\n")
    db().execute("DELETE FROM tracks WHERE video_id=?", (vid,))
    db().execute("DELETE FROM tracks_fts WHERE video_id=?", (vid,))
    db().commit()
    _forget(vid)
    return jsonify({"ok": True, "id": vid, "quarantined_to": str(dst) if dst else None})


@app.get("/api/trash")
def trash_list():
    out = []
    for e in _trash_entries():
        row, q = e.get("row") or {}, e.get("quarantined_to")
        out.append({"id": row.get("video_id"), "title": row.get("title"),
                    "artist": row.get("artist"), "album": row.get("album"),
                    "duration": row.get("duration"), "trashed_at": e.get("ts"),
                    "bytes": _fsize(q) if q else 0})
    out.sort(key=lambda t: -(t["trashed_at"] or 0))
    return jsonify(out)


@app.post("/api/trash/restore")
def trash_restore():
    d = request.get_json(force=True, silent=True) or {}
    vid = d.get("id")
    entries = _trash_entries()
    hit = next((e for e in entries if (e.get("row") or {}).get("video_id") == vid), None)
    if not hit:
        return jsonify({"ok": False, "error": "not in trash"}), 404
    row, q = hit["row"], hit.get("quarantined_to")
    if q and Path(q).exists() and not Path(row["path"]).exists():
        try:
            Path(row["path"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(q, row["path"])
        except OSError as e:
            return jsonify({"ok": False, "error": f"Couldn't move the file back. ({e})"}), 409
    if not db().execute("SELECT 1 FROM tracks WHERE video_id=?", (vid,)).fetchone():
        cols = ",".join(row)
        db().execute(f"INSERT INTO tracks({cols}) VALUES({','.join('?' * len(row))})",
                     tuple(row.values()))
        db().execute("INSERT INTO tracks_fts(video_id,title,artist,album,genre) VALUES(?,?,?,?,?)",
                     (row["video_id"], row.get("title") or "", row.get("artist") or "",
                      row.get("album") or "", row.get("genre") or ""))
        db().commit()
    _write_trash_entries([e for e in entries if e is not hit])
    _forget(vid)
    return jsonify({"ok": True, "id": vid})


@app.post("/api/trash/clear")
def trash_clear():
    """Permanent: delete the quarantined files for good and drop their now-pointless
    neighbors rows. The UI arms this behind a two-step confirm."""
    entries = _trash_entries()
    deleted, freed, failed, kept = 0, 0, [], []
    has_nb = has_neighbors_table()
    for e in entries:
        row, q = e.get("row") or {}, e.get("quarantined_to")
        vid = row.get("video_id")
        if q and Path(q).exists():
            n = _fsize(q)
            try:
                os.unlink(q)
            except OSError as err:
                failed.append({"id": vid, "error": str(err)})
                kept.append(e)
                continue
            freed += n
        if has_nb and vid:
            db().execute("DELETE FROM neighbors WHERE video_id=? OR neighbor_id=?", (vid, vid))
        deleted += 1
    db().commit()
    _write_trash_entries(kept)
    return jsonify({"ok": not failed, "deleted": deleted, "bytes": freed, "failed": failed})


def _forget(vid):
    """Drop per-process caches that could still name a track we just moved in or out."""
    global _OST_INDEX
    _OST_INDEX = None
    _ART.pop(vid, None)
    _HOOKS["t"] = -1.0


@app.get("/audio/<vid>")
def audio(vid):
    row = db().execute("SELECT path FROM tracks WHERE video_id=?", (vid,)).fetchone()
    if not row:
        return ("not found", 404)
    return send_file(row["path"], mimetype="audio/ogg", conditional=True)


# --------------------------------------------------------------------------- radio / autoplay
import random  # noqa: E402
import numpy as np  # noqa: E402

import personalize  # noqa: E402
from player_server.retrieval import (DEFAULT_BLEND, DEFAULT_BLEND_LOW_MEM,
                                     blend_candidates as _blend_candidates,
                                     session_centroid as _session_centroid,
                                     top_ids as _top_ids_impl)

# Low-memory mode for the handheld build: fp16 embeddings + the precomputed
# `neighbors` table (scripts/build_neighbors.py) instead of a full fp32 matmul.
LOW_MEM = os.environ.get("PLAYER_LOW_MEM") == "1"
EMB_CENTER = os.environ.get("PLAYER_EMB_RAW") != "1"

TRACE_PATH = ROOT / "data" / "next_trace.jsonl"   # one JSON line per /api/next decision
SEEDS_CSV = ROOT / "data" / "seed_tracks.csv"     # YouTube Music history (merge_takeout.py)
# The listening history outweighs the in-app log by two orders of magnitude (thousands
# of real listens vs a few hundred player events), so it is the backbone of the taste
# model; in-app events add on top with their own (larger, explicit) weights.
HISTORY_W = 1.0
LISTENS_CSV = ROOT / "data" / "listens.csv"       # every YT Music listen (merge_takeout.py)
# Recommended starts from your recent listening — mostly YouTube Music, the in-app log is
# a few hundred events. That history only moves when a Takeout is merged, so its recency
# is counted from the newest listen in it, not from the wall clock (a month without a new
# export must not empty the shelf).
RECENT_HALFLIFE_DAYS = 14.0        # Recommended: taste weights (see history_weights)
# Listen again / the Wheel: each YT Music listen counts 0.5^(age / 21 days), summed per song,
# so a song replayed this week outranks one played once yesterday. Backtest over 29 cuts
# (which of the 18 tiles you replay in the next 7 days): newest-first 1.7, all-time
# count 5.2, half-life 7d 6.8, 14d 8.0, 21d 8.8 (best), 30d 8.6, 90d 7.6.
LISTEN_AGAIN_HALFLIFE_DAYS = 21.0
RADIO_CACHE = ROOT / "data" / "radio_cache"       # <seed_video_id>.json -> YT song radio
CLUSTERS_CSV = ROOT / "data" / "clusters.csv"     # video_id,artist,title,cluster,genre,x,y

_EMB = None
_META = None                       # per-embedding track metadata (artist/duration)
_COOC = None                       # {seed_id: set(member ids in the library)}
_CLUSTERS = None                   # {video_id: cluster id} from clusters.csv
# cached personalization; `heard`/`energy`/`bpm`, the adaptive exploration rate and the
# per-cluster accept/skip tallies all ride the same refresh cycle as the prefs.
_PREF = {"stamp": None, "prefs": None, "taste": None, "skip": None,
         "heard": None, "energy": None, "energy_n": None, "bpm": None,
         "epsilon": None, "cluster_stats": None}

# --- exploration rate (VDBE-style adaptive epsilon). A fixed 15% explores exactly as
# hard when the listener is skipping everything as when they are completing everything;
# the whole point of exploring is that the current policy is not landing. `m` is an EMA
# over the last OUTCOME_WINDOW outcomes (1 = the track landed, 0 = it did not) and the
# rate leans up when m falls, down when the session is going well.
EPS_BASE, EPS_GAIN, EPS_LO, EPS_HI = 0.15, 0.3, 0.05, 0.30
EPS_EMA_GAMMA = 0.3
OUTCOME_WINDOW = 10
# What an exploration slot may cost (personalize.choose_next_explained). sound_budget:
# at most 0.5 sd of sound given up against the best-sounding candidate — on 750 sim
# decisions that took explore picks giving up >0.75 sd from 2.8% to 0 while 45% (was
# 48%) still came from another cluster. prior_n: arms shrink to the pooled accept rate
# until they have ~10 verdicts of their own. eval_autoplay.py sim reports both.
EXPLORE = {"sound_budget": 0.5, "prior_n": 10.0}
MOOD_DECAY = 0.85          # session-mood weight per track back (newest = 1.0)


def emb():
    """Lazy-load the MuQ audio embeddings (numpy only — no model). For track->track 'vibe'.
    In LOW_MEM mode prefers the pre-normalized fp16 copy (half the RAM); dot products
    against fp32 centroids upcast automatically, and only candidate rows are touched.
    The matrix is CENTERED (library-mean direction removed, re-normalized — see
    personalize.center_embeddings) unless PLAYER_EMB_RAW=1: every consumer here is the
    ranker, and on raw MuQ vectors its taste/skip/mood centroids score typicality."""
    global _EMB
    if _EMB is None:
        fp16 = ROOT / "data" / "muq_fp16.npz"
        full = ROOT / "data" / "muq_embeddings.npz"
        X = None
        if LOW_MEM and fp16.exists():
            d = np.load(fp16, allow_pickle=False)
            X = d["embeddings"]                     # already L2-normalized fp16
            ids = [str(x) for x in d["ids"]]
        elif full.exists():
            d = np.load(full, allow_pickle=False)
            X = d["embeddings"].astype("float16" if LOW_MEM else "float32")
            X /= (np.linalg.norm(X.astype("float32"), axis=1, keepdims=True) + 1e-9).astype(X.dtype)
            ids = [str(x) for x in d["ids"]]
        if X is None:
            _EMB = {"X": None, "ids": [], "id2i": {}, "mean": None}
        else:
            mean = None
            if EMB_CENTER:
                X, mean = personalize.center_embeddings(X)
            _EMB = {"X": X, "ids": ids, "id2i": {v: i for i, v in enumerate(ids)}, "mean": mean}
    return _EMB


def has_neighbors_table():
    return bool(db().execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='neighbors'").fetchone())


def lib_ids():
    return {r[0] for r in db().execute("SELECT video_id FROM tracks")}


def track_meta():
    """Track artist/duration aligned to the embedding order (for the personalization
    layer). Cached against the loaded embedding object."""
    global _META
    E = emb()
    if _META is not None and _META.get("_for") is E:
        return _META
    rows = {r["video_id"]: r for r in db().execute("SELECT video_id, artist, duration FROM tracks")}
    id2artist = {v: (r["artist"] or "") for v, r in rows.items()}
    durations = {v: r["duration"] for v, r in rows.items()}
    artist_by_index = [id2artist.get(v, "") for v in E["ids"]]
    _META = {"_for": E, "id2artist": id2artist, "durations": durations,
             "artist_by_index": artist_by_index}
    return _META


def cooc_members():
    """{seed_video_id: set(radio member ids that we own)} from data/radio_cache — the
    collaborative signal behind rank_next's `cooc` term. ~2k small JSONs, read once per
    process on first /api/next; seeds whose radio has no in-library member are dropped."""
    global _COOC
    if _COOC is None:
        t0 = time.time()
        lib, m, files = lib_ids(), {}, 0
        for f in RADIO_CACHE.glob("*.json") if RADIO_CACHE.exists() else ():
            files += 1
            try:
                tr = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            mem = {t.get("videoId") for t in tr if isinstance(t, dict) and t.get("videoId")} & lib
            if mem:
                m[f.stem] = mem
        _COOC = m
        print(f"[cooc] radio cache: {len(m)}/{files} seeds usable, "
              f"{sum(len(v) for v in m.values())} in-library members, {time.time() - t0:.2f}s")
    return _COOC


def _energy_ranks():
    """{video_id: 0..1 percentile rank of energy_db} from the `analysis` table (filled by
    a later analysis sweep). Absent table / no rows -> {} and the energy term is a no-op."""
    try:
        rows = db().execute(
            "SELECT video_id, energy_db FROM analysis WHERE energy_db IS NOT NULL").fetchall()
    except sqlite3.Error:
        return {}
    if len(rows) < 2:
        return {}
    order = sorted(rows, key=lambda r: r[1])
    last = len(order) - 1
    return {r[0]: i / last for i, r in enumerate(order)}


def _bpm_map():
    """{video_id: bpm} from the `analysis` table (same sweep that fills energy_db).
    Non-positive / NULL tempos are dropped so rank_next's tempo term simply stays off for
    them. Absent table -> {}."""
    try:
        rows = db().execute(
            "SELECT video_id, bpm FROM analysis WHERE bpm IS NOT NULL").fetchall()
    except sqlite3.Error:
        return {}
    return {r[0]: float(r[1]) for r in rows if r[1] and r[1] > 0}


def clusters():
    """{video_id: cluster id} from data/clusters.csv (the genre-map clustering:
    video_id,artist,title,cluster,genre,x_energetic,y_electronic). Read once per process;
    an absent/unreadable file just means the clustered-Thompson explore is never armed."""
    global _CLUSTERS
    if _CLUSTERS is None:
        m = {}
        try:
            if CLUSTERS_CSV.exists():
                with open(CLUSTERS_CSV, encoding="utf-8-sig") as f:
                    for r in csv.DictReader(f):
                        vid, c = r.get("video_id"), r.get("cluster")
                        if vid and c not in (None, ""):
                            m[vid] = c
        except (OSError, csv.Error):
            m = {}
        _CLUSTERS = m
    return _CLUSTERS


def outcome_epsilon(plays, durations, base=EPS_BASE, gain=EPS_GAIN,
                    gamma=EPS_EMA_GAMMA, window=OUTCOME_WINDOW):
    """Adaptive exploration rate from how the last `window` decided tracks actually went.

    An outcome is 1 when the track landed (completed / liked / skipped so late it was
    effectively finished) and 0 when it did not (early or mid skip, dislike, trash).
    'play' and 'peek' say nothing yet and are ignored, and 'unlike' is a retraction of an
    earlier verdict rather than a fresh one. `m` is an EMA seeded on the oldest outcome in
    the window; with no history at all m = 0.5 and epsilon is exactly `base`, i.e. the old
    hard-coded 0.15. A pure skip streak pushes it to EPS_HI, a pure accept streak to
    EPS_LO. Pure function — takes rows, returns a float."""
    xs = []
    for row in sorted(plays, key=lambda r: r[1] or 0.0):
        vid, event, seconds = row[0], row[2], row[3]
        if personalize.is_browse_skip(event, seconds, row[4] if len(row) > 4 else None):
            continue                                   # navigation, not an outcome
        if event in ("complete", "like"):
            xs.append(1.0)
        elif event in ("dislike", "trash"):
            xs.append(0.0)
        elif event == "skip":
            comp = personalize._completion(seconds, durations.get(vid))
            xs.append(1.0 if (comp is not None and comp > personalize.LATE_OK) else 0.0)
    xs = xs[-window:]
    if not xs:
        m = 0.5
    else:
        m = xs[0]
        for x in xs[1:]:
            m = gamma * x + (1.0 - gamma) * m
    return min(EPS_HI, max(EPS_LO, base + gain * (0.5 - m)))


def cluster_stats(plays, durations, cl):
    """{cluster id: (accepts, skips)} — the arm history behind the clustered Thompson
    explore. Accept = a completion or a like; skip = an EARLY skip (the graded negative
    personalize already treats as a real verdict), a dislike or a trash. Mid/late skips
    are ambiguous and count as neither, exactly as in the preference weighting."""
    out = {}
    for row in plays:
        vid, event, seconds = row[0], row[2], row[3]
        c = cl.get(vid)
        if c is None or personalize.is_browse_skip(
                event, seconds, row[4] if len(row) > 4 else None):
            continue
        a, s = out.get(c, (0, 0))
        if event in ("complete", "like"):
            out[c] = (a + 1, s)
        elif event in ("dislike", "trash"):
            out[c] = (a, s + 1)
        elif event == "skip":
            comp = personalize._completion(seconds, durations.get(vid))
            if comp is not None and comp < personalize.STRONG_SKIP:
                out[c] = (a, s + 1)
    return out


def personalization():
    """Compute (and cache) preference scores + taste/skip centroids from the plays log.
    Recomputes only when the number of logged plays changes. Returns (prefs, taste, skip);
    all None-safe so ranking degrades to content-only with no history. The same pass
    refreshes the already-heard timestamps, the energy percentiles and tempos (see
    signals()), the adaptive exploration rate and the per-cluster arm stats — all of it
    is O(log) work that must not happen per request."""
    E, meta = emb(), track_meta()
    # (count, max ts): count alone misses same-size mutations (delete+insert); the history
    # file's mtime makes a fresh Takeout import refresh the taste model too
    stamp = tuple(db().execute("SELECT COUNT(*), MAX(ts) FROM plays").fetchone()) + (
        SEEDS_CSV.stat().st_mtime if SEEDS_CSV.exists() else None,)
    if _PREF["stamp"] != stamp:
        plays = db().execute("SELECT video_id, ts, event, seconds, source FROM plays").fetchall()
        rows = [(r["video_id"], r["ts"], r["event"], r["seconds"], r["source"]) for r in plays]
        now = time.time()
        prefs = personalize.compute_prefs(
            rows, meta["durations"], meta["id2artist"], now=now,
            # dislike is the more perishable judgement (14d vs the 30d positives keep),
            # and the skip cliff in the first seconds is a stronger negative than a
            # skip at 12% — both opt-in, both off by default in the engine. A like is
            # its latest like/unlike state, and legacy sub-3 s skips were browsing.
            neg_halflife_days=14.0, strong_early_skip=True, explicit_state=True,
            browse_seconds=personalize.BROWSE_SECONDS)
        hist, hist_counts = listen_history()
        # taste = YouTube Music history (the bulk of the evidence) + the in-app log
        tw = {v: HISTORY_W * w for v, w in hist.items()}
        for v, w in prefs["track"].items():
            tw[v] = tw.get(v, 0.0) + w
        taste = personalize.build_centroid(E["X"], E["id2i"], tw)
        skip = personalize.build_centroid(E["X"], E["id2i"], {v: 1.0 for v in prefs["skip_ids"]})
        # "heard before" includes YouTube Music: a track played twenty times there is not
        # a discovery, whatever the in-app log says (novelty, fresh slice, explore picks)
        prefs["app_play_counts"] = prefs["play_counts"]
        merged = dict(hist_counts)
        for v, n in prefs["play_counts"].items():
            merged[v] = merged.get(v, 0) + n
        prefs["play_counts"] = merged
        # heard = when a track was last actually LISTENED to: 'peek' (a hover preview) is
        # not listening, and 'skip' displeasure is already carried by the skip vector.
        heard = {r[0]: r[1] for r in db().execute(
            "SELECT video_id, MAX(ts) FROM plays WHERE event IN ('play','complete') "
            "AND ts IS NOT NULL GROUP BY video_id")}
        _PREF.update(stamp=stamp, prefs=prefs, taste=taste, skip=skip, heard=heard,
                     epsilon=outcome_epsilon(rows, meta["durations"]),
                     cluster_stats=cluster_stats(rows, meta["durations"], clusters()))
        try:
            an = db().execute("SELECT COUNT(*) FROM analysis").fetchone()[0]
        except sqlite3.Error:
            an = None
        if an != _PREF["energy_n"]:
            _PREF.update(energy=_energy_ranks(), bpm=_bpm_map(), energy_n=an)
    return _PREF["prefs"], _PREF["taste"], _PREF["skip"]


_HIST = {"mtime": None, "weights": {}, "counts": {}}
_LISTENS = {"mtime": None, "events": [], "end": None}
_REC = {"key": None, "ids": []}
_CLUSTER_ALL = {"emb": None, "map": {}}


def recent_listens():
    """([(video_id, ts)] oldest first, newest ts) from data/listens.csv, cached on its
    mtime; ([], None) without one."""
    try:
        mtime = LISTENS_CSV.stat().st_mtime
    except OSError:
        return [], None
    if _LISTENS["mtime"] != mtime:
        ev = []
        try:
            with open(LISTENS_CSV, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    try:
                        ts = datetime.fromisoformat(r["time"]).timestamp()
                    except (KeyError, TypeError, ValueError):
                        continue
                    if r.get("video_id"):
                        ev.append((r["video_id"], ts))
        except (OSError, csv.Error):
            ev = []
        ev.sort(key=lambda e: e[1])
        _LISTENS.update(mtime=mtime, events=ev, end=ev[-1][1] if ev else None)
    return _LISTENS["events"], _LISTENS["end"]


def cluster_all():
    """clusters() for EVERY embedded track. clusters.csv only covers the library as of
    the last genre_map.py run, which the refresh pipeline doesn't include, so newer
    tracks join the cluster whose mean embedding is nearest."""
    E = emb()
    if _CLUSTER_ALL["emb"] is E:
        return _CLUSTER_ALL["map"]
    known = clusters()
    out = {}
    if E["X"] is not None and known:
        labels = sorted(set(known.values()))
        k_of = {c: k for k, c in enumerate(labels)}
        C = np.zeros((len(labels), E["X"].shape[1]), dtype=np.float32)
        for v, c in known.items():
            i = E["id2i"].get(v)
            if i is not None:
                C[k_of[c]] += np.asarray(E["X"][i], dtype=np.float32)
                out[v] = c
        C /= np.linalg.norm(C, axis=1, keepdims=True) + 1e-9
        rest = [i for v, i in E["id2i"].items() if v not in out]
        if rest:
            near = np.argmax(np.asarray(E["X"][rest], dtype=np.float32) @ C.T, axis=1)
            for i, k in zip(rest, near):
                out[E["ids"][i]] = labels[int(k)]
    _CLUSTER_ALL.update(emb=E, map=out)
    return out


def recommended_ids(n):
    """Unheard library tracks for Home's "Recommended for you": your last two weeks,
    one share per style (personalize.mixture_shelf). Taste weights are log1p(plays) x a
    RECENT_HALFLIFE_DAYS half-life over the YT listens plus the tracks you finished in
    the player, aged from the newest of them. Cached until any of that changes."""
    prefs, _taste, _skip = personalization()
    events, end = recent_listens()
    key = (_PREF["stamp"], _LISTENS["mtime"], n)
    if _REC["key"] == key:
        return _REC["ids"]
    E = emb()
    ids = []
    if E["X"] is not None:
        agg = {}
        for v, ts in events:
            c, last = agg.get(v, (0, 0.0))
            agg[v] = (c + 1, max(last, ts))
        for v, c, ts in db().execute(
                "SELECT video_id, COUNT(*), MAX(ts) FROM plays WHERE event='complete' "
                "AND ts IS NOT NULL GROUP BY video_id"):
            c0, last = agg.get(v, (0, 0.0))
            agg[v] = (c0 + c, max(last, ts))
        if agg:
            ref = max(last for _c, last in agg.values())
            rows = [{"video_id": v, "play_count": c,
                     "last_played": datetime.fromtimestamp(last, timezone.utc).date().isoformat()}
                    for v, (c, last) in agg.items()]
            w = personalize.history_weights(rows, ref, halflife_days=RECENT_HALFLIFE_DAYS)
            lib = lib_ids()
            counts = (prefs or {}).get("play_counts") or {}
            artist = track_meta()["id2artist"]
            ids = personalize.mixture_shelf(
                E["X"], E["id2i"], E["ids"], w, cluster_all(),
                lambda v: v in lib and counts.get(v, 0) == 0, n,
                artist_of=lambda v: artist.get(v, "").lower())
    _REC.update(key=key, ids=ids)
    return ids


@app.get("/api/recommend")
def recommend():
    """"Recommended for you" (Home): unheard tracks matched to the last two weeks of
    listening, one share per style. [] without any listening history."""
    n = max(1, min(60, int(request.args.get("n", 24))))
    return jsonify([t for t in (track_by_id(v) for v in recommended_ids(n)) if t])


def listen_history():
    """({vid: taste weight}, {vid: play count}) from data/seed_tracks.csv — the YouTube
    Music listening history merge_takeout.py maintains. Cached on the file's mtime; an
    absent file means an empty history (the in-app log alone, as before)."""
    try:
        mtime = SEEDS_CSV.stat().st_mtime
    except OSError:
        return {}, {}
    if _HIST["mtime"] != mtime:
        try:
            with open(SEEDS_CSV, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
        except (OSError, csv.Error):
            rows = []
        counts = {}
        for r in rows:
            try:
                counts[r["video_id"]] = int(float(r.get("play_count") or 0))
            except (KeyError, ValueError):
                continue
        _HIST.update(mtime=mtime, weights=personalize.history_weights(rows, time.time()),
                     counts=counts)
    return _HIST["weights"], _HIST["counts"]


def signals():
    """(last-heard {vid: ts}, energy {vid: 0..1}, bpm {vid: tempo}) for rank_next's
    `heard` / `energy` / `bpm` terms. Filled by personalization(), which every ranking
    path calls first; any of them may be empty, in which case its term contributes
    nothing."""
    return _PREF["heard"] or {}, _PREF["energy"] or {}, _PREF["bpm"] or {}


def explore_epsilon():
    """The current adaptive exploration rate (cached by personalization()). Falls back to
    the historical fixed rate before the first refresh / with no history at all."""
    e = _PREF["epsilon"]
    return EPS_BASE if e is None else e


def track_by_id(vid):
    r = db().execute("SELECT * FROM tracks WHERE video_id=?", (vid,)).fetchone()
    return trow(r) if r else None


def trace_next(cur, cur_artist, exclude, ranked, pick, info, prefs, epsilon, recent=None,
               anchor=None, rejected=()):
    """Append one JSON line to next_trace.jsonl explaining this /api/next decision: the
    current track, the pick (with its rank + exploration reason), and the top-12 scored
    candidates with their per-term breakdown. Best-effort — never breaks the endpoint.
    `ranked` is the explain=True form: (vid, score, terms). Fallback picks (no candidates)
    log the same shape with ranked=[] -> pick.rank null, top empty, reason "fallback_*",
    so the least-explainable picks are the ones guaranteed to leave a trail."""
    try:
        counts = (prefs or {}).get("play_counts") or {}
        rank_of = {vid: i for i, (vid, *_rest) in enumerate(ranked)}
        top = ranked[:12]
        need = {vid for vid, *_rest in top} | {pick, cur}
        titles = {r["video_id"]: (r["title"], r["artist"]) for r in db().execute(
            "SELECT video_id, title, artist FROM tracks WHERE video_id IN (%s)"
            % ",".join("?" * len(need)), tuple(need))}
        rec = {
            "ts": time.time(),
            "current": {"id": cur, "artist": cur_artist,
                        "title": titles.get(cur, ("", ""))[0]},
            "exclude_n": len(exclude), "epsilon": epsilon,
            "recent": list(recent) if recent else [],   # fatigue/cooldown context tail
            "anchor": anchor if anchor and anchor != cur else None,   # set when cur was rejected
            "rejected": sorted(rejected or ()),
            "pick": {"id": pick, "title": titles.get(pick, ("", ""))[0],
                     "rank": rank_of.get(pick),
                     "explored": info["explored"], "reason": info["reason"]},
            "top": [{"id": vid, "title": titles.get(vid, ("", ""))[0],
                     "artist": titles.get(vid, ("", ""))[1], "score": round(s, 4),
                     "terms": {k: round(v, 4) for k, v in terms.items()},
                     "play_count": counts.get(vid, 0)}
                    for vid, s, terms in top],
        }
        with open(TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- retrieval
# One candidate source is one theory of what could come next, and a single cosine list is
# a narrow one: the only thing it can ever propose is more of the current track, and the
# ranker's taste/cooc/novelty terms then re-order a set that never contained an
# alternative. The blend keeps that neighbourhood as the backbone and adds three other
# openings — what you like in general, what the crowd plays alongside this track, and
# things you have never heard at all — so the ranking is a choice between KINDS of
# continuation. Priority order below is also dedupe order.
# The taste and never-played slices were widened (60->80, 15->25) alongside the sameness
# hill below: a ranker told to stop picking clones needs non-clones to pick FROM, and
# those are the two sources that do not come out of the current track's cosine order.
# Only the backbone gives ground for them (see the trim at the end of blend_candidates).
BLEND = dict(DEFAULT_BLEND)
# LOW_MEM has no full-matrix sims to spend: the backbone is the precomputed neighbours
# row and the never-played picks are sampled out of that same short list.
BLEND_LOW_MEM = dict(DEFAULT_BLEND_LOW_MEM)


def _top_ids(sims, ids, k):
    """The k best-scoring ids, best first. argpartition + a sort of just that slice —
    a full argsort of 55k rows per request is waste when only the head is ever read."""
    return _top_ids_impl(sims, ids, k)


def blend_candidates(cur, base, lib, exclude, taste_ids=(), radio_ids=(),
                     play_counts=None, caps=None, rng=None):
    """Multi-source candidate retrieval for /api/next — pure, so it tests without Flask.

    base:      ids ordered by similarity to the current track (full-matrix sims, or the
               precomputed neighbours row in LOW_MEM). Also the pool the fresh picks are
               drawn from, so an unheard track is never absurdly far from the vibe.
    taste_ids: ids ordered by similarity to the taste centroid ((), or empty, when there
               is no taste model yet).
    radio_ids: in-library members of the current track's YT song radio (the cooc map).
    A candidate is eligible only if it is in `lib` and not in `exclude` (the client's
    last-50 window plus the current track). Sources are taken in priority order and
    deduped, so a track that several sources propose costs one slot, not four.
    `rng` defaults to one seeded on the current video id: the never-played sample is then
    random ACROSS tracks but reproducible FOR a track, which is what makes a trace
    replayable. Returns the candidate ids, capped at ~`total`.
    """
    if rng is None:
        # Keep the old server-level random hook available to tests and callers.
        rng = random.Random(cur)
    return _blend_candidates(cur, base, lib, exclude, taste_ids=taste_ids,
                             radio_ids=radio_ids, play_counts=play_counts,
                             caps=caps, rng=rng, defaults=BLEND)


def session_centroid(E, mood_ids, decay=MOOD_DECAY):
    """Exponentially-weighted centroid of the recent tail: the newest track weighs 1.0
    and each step further back x`decay` (the STAN session-decay result). The uniform mean
    this replaces let a track from twelve plays ago pull on the session mood exactly as
    hard as the one that just finished, so a deliberate pivot took a full window to
    register; weighted, the anchor re-centres in about three tracks while still being a
    mood rather than a single track. Weights are normalized to sum 1 and build_centroid
    L2-normalizes the result, as before."""
    return _session_centroid(E, mood_ids, personalize.build_centroid, decay=decay)


# --------------------------------------------------------------------------- ranking
# Scoring overrides the LIVE autoplay paths (/api/next and vibe_walk) use on top of
# personalize.rank_next's defaults. User feedback, 2026-07-26: "all the songs kinda sound
# the same in the autoplay" — vibe, mood and taste all reward similarity, and the only
# term pushing back (neighborhood fatigue) fired at 0.80 against the recent TAIL, so a
# near-copy of the track playing was never charged for being a near-copy.
#   same_w     turns on the sameness hill: a cost per unit of cosine to the current track
#              above same_floor (0.92), so a clone stops being the automatic pick.
#   rho_floor  drops the fatigue threshold 0.80 -> 0.76, so the last-6 window starts
#              pushing back a little earlier instead of only inside clone-clusters.
# personalize keeps its own defaults (same_w 0.0 / rho_floor 0.80): the firmware goldens
# and every non-server caller are generated from the default call and stay exact.
# same_floor 0.85 ≈ 78th percentile of real consecutive-pick similarity (measured
# 2026-07-26); at the personalize default 0.92 the hill fires on ~2% of picks and
# is dominated by the fatigue ramp.
#
# v3 (2026-10-10), after an audit measured which term actually decides the pick:
# inside a 300-candidate window, removing tempo / taste / skip changed the pick for
# 56 / 75 / 72% of seeds and removing VIBE only 37%. The library had grown 20k -> 56k,
# the vibe spread inside a window had shrunk ~3x, and every fixed-magnitude term had
# grown with it. So:
#   scale="window"  weights are relative to vibe's spread in the current list (see
#                   personalize._window_params): cosine terms by their own spread, flat
#                   terms in vibe standard deviations — the balance no longer drifts
#                   as the library grows or as a neighbourhood gets denser.
#   floors          the July floors carried into the CENTERED space emb() now serves
#                   (raw 0.76 -> 0.67, raw 0.85 -> 0.78, matched on 0.5M window pairs).
#   kappa           session rejections (next_decision) steer away from what you skipped.
#   track_tanh /    a liked track nudges instead of winning outright; a channel is
#   artist_prior    scored by its accept RATE, not by how much of it you've heard.
# The weights below were calibrated with scripts/eval_autoplay.py (sim mode, walks
# seeded from the listening history): taste 0.2 keeps the walk near where it started
# (seed-sim @20 0.57 vs 0.49 at 0.35 — centered taste really pulls toward your history,
# raw taste only ever pulled toward "typical"); tempo 0.7 / energy 6 hold tempo matches
# at ~71% without costing how-it-sounds; skips: the next pick is nearer the anchor than
# the rejected track 99-100% of the time.
AUTOPLAY_PARAMS = {
    "scale": "window",
    # cosine-derived terms: their spread across the list = weight x vibe's spread
    "mu": 0.6, "delta": 0.2, "sigma": 0.25, "kappa": 1.0,
    # flat terms, in vibe standard deviations
    "cooldown": 3.0, "heard_w": 3.0, "beta": 1.0, "nu": 0.3, "gamma": 1.0,
    "gamma_artist": 0.5, "energy_w": 6.0, "bpm_w": 0.7,
    "track_tanh": 1, "artist_prior": 3.0,
    # similarity band, centered cosine
    "same_w": 1.5, "same_floor": 0.78, "rho_floor": 0.67,
}


@app.get("/api/next")
def api_next():
    """Pick the next on-vibe track (audio-similarity + artist diversity + a little
    exploration). Query: id (the track being left), exclude (the client's last 50 queue
    ids, oldest->newest), and — from the current client — outcome/secs: how the track
    being left ended ('skip' | 'complete' | 'switch'), sent WITH the request because the
    outcome's own /api/play log races it."""
    cur = request.args.get("id", "")
    ex_list = [v for v in request.args.get("exclude", "").split(",") if v]
    try:
        secs = float(request.args.get("secs", ""))
    except ValueError:
        secs = None
    d = next_decision(cur, ex_list, outcome=request.args.get("outcome") or None, secs=secs)
    if d["pick"]:
        r = db().execute("SELECT * FROM tracks WHERE video_id=?", (d["pick"],)).fetchone()
        if r:
            return jsonify(trow(r))
    return jsonify(None)


REJECT_LOOKBACK = 3 * 3600   # a verdict older than this belongs to another sitting


def session_rejects(tail_ids, now=None):
    """The ids in the recent tail turned down within REJECT_LOOKBACK: an early skip
    (completion < personalize.STRONG_SKIP, not browsing), a dislike or a trash. A later
    completion or like clears it; a dislike/trash is not cleared by the 'skip' the
    client logs right after it (disliking advances the track)."""
    tail = [v for v in dict.fromkeys(tail_ids) if v]
    if not tail:
        return set()
    now = time.time() if now is None else now
    durations = track_meta()["durations"]
    state = {}
    for r in db().execute(
            "SELECT video_id, event, seconds, source FROM plays WHERE ts > ? AND event IN "
            "('skip','complete','like','dislike','trash') AND video_id IN (%s) ORDER BY ts, rowid"
            % ",".join("?" * len(tail)), (now - REJECT_LOOKBACK, *tail)):
        vid, event = r["video_id"], r["event"]
        if event in ("dislike", "trash"):
            state[vid] = "hard"
        elif event in ("complete", "like"):
            state[vid] = None
        elif state.get(vid) != "hard" and not personalize.is_browse_skip(
                event, r["seconds"], r["source"]):
            state[vid] = "skip" if _is_early(vid, r["seconds"], durations) else None
    return {v for v, s in state.items() if s}


def _is_early(vid, seconds, durations):
    """An early skip: under personalize.STRONG_SKIP of the track (or, with no duration,
    under EARLY_SKIP_SECONDS)."""
    comp = personalize._completion(seconds, durations.get(vid))
    if comp is not None:
        return comp < personalize.STRONG_SKIP
    return seconds is not None and seconds < personalize.EARLY_SKIP_SECONDS


def next_decision(cur, ex_list, outcome=None, secs=None, params=None, rng=None, trace=True):
    """The whole /api/next decision as a function (the endpoint and
    scripts/eval_autoplay.py both call it). Returns {"pick", "ranked", "info", "anchor",
    "rejected", "epsilon"}; pick None only for an empty library.

    Skips steer the walk. `rejected` = the tracks of this sitting you turned down (the
    outcome of `cur` as sent by the client, plus earlier verdicts in the plays log). When
    `cur` itself was rejected, the walk does NOT continue from it — the old behaviour
    answered "Next" on a track with that track's nearest neighbours. It continues from the
    ANCHOR, the most recent track of the tail you did not reject; the rejected tracks
    drop out of the session mood and form a session-skip vector the ranker steers away
    from (rank_next's `kappa`). Fatigue and cooldown still see them: they were heard."""
    params = AUTOPLAY_PARAMS if params is None else params
    exclude = set(ex_list)
    exclude.add(cur)
    tail = [v for v in ex_list if v != cur][-11:] + [cur]
    E = emb()
    lib = lib_ids()
    meta = track_meta()
    cur_artist = meta["id2artist"].get(cur, "")

    prefs, taste, skip = personalization()
    counts = (prefs or {}).get("play_counts")
    eps = explore_epsilon()

    rejected = session_rejects(tail[:-1])
    if outcome in ("skip", "dislike", "trash"):
        if outcome != "skip" or _is_early(cur, secs, meta["durations"]):
            rejected.add(cur)
    elif outcome is None and cur in session_rejects([cur]):
        rejected.add(cur)           # an older client: fall back to the logged verdict
    anchor = cur
    if cur in rejected:
        for v in reversed(tail[:-1]):
            if v not in rejected and v in E["id2i"]:
                anchor = v
                break
    mood_ids = [v for v in tail if v not in rejected] or [anchor]
    recent_ids = tail[-6:]

    # Retrieval: a blend of four openings around the anchor (blend_candidates). In
    # LOW_MEM mode the backbone is the precomputed neighbors row instead of a full-matrix
    # matmul, and there is no taste-similarity pass to spend RAM on.
    cand = []
    if LOW_MEM and has_neighbors_table():
        base = [r[0] for r in db().execute(
            "SELECT neighbor_id FROM neighbors WHERE video_id=? ORDER BY rank", (anchor,))]
        cand = blend_candidates(anchor, base, lib, exclude,
                                radio_ids=cooc_members().get(anchor) or (),
                                play_counts=counts, caps=BLEND_LOW_MEM, rng=rng)
    elif E["X"] is not None and anchor in E["id2i"]:
        sims = (E["X"] @ np.asarray(E["X"][E["id2i"][anchor]], dtype=E["X"].dtype)).astype("float32")
        base = _top_ids(sims, E["ids"], BLEND["fresh_pool"] + 1)   # +1: the anchor heads it
        taste_ids = ()
        if taste is not None:
            # a generous slice: the blend still only keeps BLEND["taste"] eligible ones,
            # but most of the head is usually already in the exclude window
            taste_ids = _top_ids(np.asarray(E["X"] @ taste, dtype="float32"),
                                 E["ids"], 4 * BLEND["taste"])
        cand = blend_candidates(anchor, base, lib, exclude, taste_ids=taste_ids,
                                radio_ids=cooc_members().get(anchor) or (),
                                play_counts=counts, rng=rng)
    if cand:
        heard, energy, bpm = signals()
        rvecs = [np.asarray(E["X"][E["id2i"][v]], dtype="float32")
                 for v in recent_ids if v in E["id2i"]]
        session_vec = session_centroid(E, mood_ids)
        sskip = personalize.build_centroid(E["X"], E["id2i"], {v: 1.0 for v in rejected})
        recent_artists = {meta["id2artist"].get(v, "") for v in recent_ids[-4:]}
        recent_artists.discard("")
        if cur_artist:
            recent_artists.add(cur_artist)
        ranked = personalize.rank_next(
            anchor, cand, E["X"], E["id2i"], E["ids"], meta["artist_by_index"],
            prefs=prefs, taste_vec=taste, skip_vec=skip,
            recent_artists=recent_artists,
            recent_vecs=np.stack(rvecs) if rvecs else None,
            session_vec=session_vec, cooc_members=cooc_members(),
            last_played=heard, now=time.time(), energies=energy, bpms=bpm,
            params=params, explain=True, session_skip_vec=sskip)
        # Exploit the top pick; an exploration slot goes to a Thompson-sampled cluster's
        # best unheard track, falling back to the flat best-unheard chain — either way
        # within EXPLORE's sound budget.
        pick, info = personalize.choose_next_explained(
            ranked, counts, epsilon=eps, rng=rng or random,
            clusters=clusters(), cluster_stats=_PREF["cluster_stats"], **EXPLORE)
        if trace:
            trace_next(cur, cur_artist, exclude, ranked, pick, info, prefs, epsilon=eps,
                       recent=tail, anchor=anchor, rejected=rejected)
        if pick in lib:
            return {"pick": pick, "ranked": ranked, "info": info, "anchor": anchor,
                    "rejected": rejected, "epsilon": eps}

    # fallback: random library track, preferring the current genre
    g = genre_of(cur_artist)
    rows = db().execute("SELECT video_id, artist FROM tracks ORDER BY RANDOM() LIMIT 120").fetchall()
    pick, reason = None, "fallback_random"
    for r in rows:
        if r["video_id"] not in exclude and (not g or genre_of(r["artist"]) == g):
            pick, reason = r["video_id"], "fallback_genre" if g else "fallback_random"
            break
    if pick is None:
        pick = next((r["video_id"] for r in rows if r["video_id"] not in exclude), None)
    info = {"explored": False, "reason": reason}
    if pick and trace:
        trace_next(cur, cur_artist, exclude, [], pick, info, None, epsilon=eps,
                   anchor=anchor, rejected=rejected)
    return {"pick": pick, "ranked": [], "info": info, "anchor": anchor,
            "rejected": rejected, "epsilon": eps}


@app.get("/api/explore")
def explore():
    """Personalized discovery shelves from the taste model + play log:
    fresh finds (unheard, closest to your taste centroid), deep cuts (barely-played
    tracks the model thinks you'd love), forgotten favorites (loved, gone quiet)."""
    E = emb()
    prefs, taste, _skip = personalization()
    lib = lib_ids()
    counts = (prefs or {}).get("play_counts", {})
    tpref = (prefs or {}).get("track", {})
    now = time.time()
    last = {r[0]: (r[1] or 0) for r in db().execute(
        "SELECT video_id, MAX(ts) FROM plays GROUP BY video_id")}

    order = None
    if E["X"] is not None and taste is not None:
        sims = np.asarray(E["X"] @ taste, dtype="float32")
        order = np.argsort(-sims)

    def taste_pick(pred, cap=48):
        out = []
        if order is None:
            return out
        for j in order:
            vid = E["ids"][int(j)]
            if vid in lib and pred(vid):
                out.append(vid)
                if len(out) >= cap:
                    break
        return out

    fresh = taste_pick(lambda v: counts.get(v, 0) == 0)
    if not fresh:   # no taste model yet -> serve random unheard
        fresh = [r[0] for r in db().execute(
            "SELECT video_id FROM tracks ORDER BY RANDOM() LIMIT 80")
            if counts.get(r[0], 0) == 0][:48]
    deep = taste_pick(lambda v: 1 <= counts.get(v, 0) <= 3 and tpref.get(v, 0.0) >= 0)
    forgotten = sorted(
        (v for v, sc in tpref.items()
         if sc > 0.4 and v in lib and now - last.get(v, 0) > 21 * 86400),
        key=lambda v: -tpref[v])[:24]

    def shelf(key, title, sub, ids, n=12):
        random.shuffle(ids)   # rotate what surfaces on each visit
        rows = [track_by_id(v) for v in ids[:n]]
        return {"key": key, "title": title, "sub": sub,
                "tracks": [t for t in rows if t]}

    return jsonify([s for s in (
        shelf("fresh", "Fresh finds", "unheard · matched to your taste", fresh),
        shelf("deep", "Deep cuts", "barely played · the model says yes", deep),
        shelf("forgotten", "Forgotten favorites", "loved, gone quiet for 3+ weeks", forgotten),
    ) if s["tracks"]])


def vibe_walk(seed, n, pool=None, avoid=()):
    """Chain the /api/next ranking (vibe + fatigue + session-mood + personalization +
    exploration) from `seed` into an ordered queue of up to n tracks, seed first — so a
    station FLOWS instead of lottery-balling its bucket. Each step retrieves the current
    track's neighborhood (neighbors table in LOW_MEM, else full-matrix sims), optionally
    fenced inside `pool` (a genre station's promise), ranks it with the same terms as
    /api/next over the growing walk history, and picks with epsilon exploration. Two
    things stay deliberately unlike /api/next: retrieval is the fenced neighbourhood
    only (a station promises a bucket — see seed_neighborhood), and epsilon stays the
    fixed 0.15, because a station is built in one shot and there is no stream of
    outcomes to adapt to. Returns [] when the seed has no embedding — callers fall back
    to shuffle. `avoid` ids never enter the walk (a station re-planned mid-queue must not
    replay what the queue already holds)."""
    E = emb()
    if E["X"] is None or seed not in E["id2i"]:
        return []
    allowed = (pool & lib_ids()) if pool is not None else lib_ids()
    meta = track_meta()
    prefs, taste, skip = personalization()
    heard, energy, bpm = signals()
    cooc = cooc_members()
    now = time.time()
    counts = (prefs or {}).get("play_counts")
    use_neighbors = LOW_MEM and has_neighbors_table()
    played, pset, cur = [seed], {seed} | set(avoid), seed
    while len(played) < n:
        cand = []
        if use_neighbors:
            for r in db().execute(
                    "SELECT neighbor_id FROM neighbors WHERE video_id=? ORDER BY rank", (cur,)):
                if r[0] not in pset and r[0] in allowed:
                    cand.append(r[0])
        else:
            sims = (E["X"] @ np.asarray(E["X"][E["id2i"][cur]], dtype=E["X"].dtype)).astype("float32")
            # scan the whole similarity order: a tight genre fence may need to reach
            # far past the top-800 window /api/next uses on the open library
            for j in np.argsort(-sims)[1:]:
                vid = E["ids"][int(j)]
                if vid in pset or vid not in allowed:
                    continue
                cand.append(vid)
                if len(cand) >= 400:
                    break
        if not cand:
            break
        mood_ids = played[-12:]
        recent_ids = mood_ids[-6:]
        rvecs = [np.asarray(E["X"][E["id2i"][v]], dtype="float32")
                 for v in recent_ids if v in E["id2i"]]
        session_vec = session_centroid(E, mood_ids)
        recent_artists = {meta["id2artist"].get(v, "") for v in recent_ids[-4:]}
        recent_artists.discard("")
        ranked = personalize.rank_next(
            cur, cand, E["X"], E["id2i"], E["ids"], meta["artist_by_index"],
            prefs=prefs, taste_vec=taste, skip_vec=skip,
            recent_artists=recent_artists,
            recent_vecs=np.stack(rvecs) if rvecs else None,
            session_vec=session_vec, cooc_members=cooc,
            last_played=heard, now=now, energies=energy, bpms=bpm,
            params=AUTOPLAY_PARAMS)
        pick = personalize.choose_next(ranked, counts, epsilon=0.15)
        if pick is None:
            break
        played.append(pick)
        pset.add(pick)
        cur = pick
    return [t for t in (track_by_id(v) for v in played) if t]


SONG_RADIO_POOL = 1000   # a song radio may only tour the seed's nearest this-many tracks


def seed_neighborhood(vid, m=SONG_RADIO_POOL):
    """The seed's m nearest tracks (plus itself) as a set — the fence for a song radio.
    Without it the walk re-centers every hop and can tunnel arbitrarily far: a rap seed
    chained rap -> reggaeton -> Brazilian forró in five steps, ending somewhere the
    LISTENER never goes even though every single hop was locally adjacent. None with no
    embeddings (callers pass pool=None -> vibe_walk returns [] anyway)."""
    E = emb()
    if E["X"] is None or vid not in E["id2i"]:
        return None
    if LOW_MEM and has_neighbors_table():
        near = {r[0] for r in db().execute(
            "SELECT neighbor_id FROM neighbors WHERE video_id=?", (vid,))}
    else:
        sims = (E["X"] @ np.asarray(E["X"][E["id2i"][vid]], dtype=E["X"].dtype)).astype("float32")
        near = {E["ids"][int(j)] for j in np.argsort(-sims)[:m + 1]}
    near.add(vid)
    return near


@app.get("/api/radio")
def api_radio():
    """Build a starting station of ~30 tracks for a Home tile / genre page / track.

    genre: vibe-walk fenced inside the genre from a random in-genre seed — an ordered
    journey through the bucket instead of a flat shuffle (which followed orchestral
    with 8-bit with lofi). Falls back to the old shuffle with no embeddings.
    track: vibe-walk continuation from ?name=<video_id>, seed EXCLUDED — the client is
    already playing it and appends this behind it ("play one song anywhere" -> station).
    Fenced to the seed's neighborhood: a song radio promises seed-adjacency throughout,
    not just hop-to-hop smoothness.
    recent / shuffle: unchanged (shuffle's whole promise is randomness).
    """
    kind = request.args.get("kind", "shuffle")
    name = request.args.get("name", "")
    n = 30
    if kind == "track":
        avoid = [v for v in request.args.get("exclude", "").split(",") if v]
        return jsonify(vibe_walk(name, n + 1, pool=seed_neighborhood(name), avoid=avoid)[1:])
    if kind == "genre":
        want = name.lower()
        rows = db().execute("SELECT * FROM tracks WHERE artist<>''").fetchall()
        pool = [r for r in rows if (genre_of(r["artist"]) or "unlabeled").lower() == want]
        vids = [r["video_id"] for r in pool]
        random.shuffle(vids)
        pool_set = set(vids)
        for seed in vids[:5]:          # tolerate a seed that has no embedding yet
            walk = vibe_walk(seed, n, pool=pool_set)
            if len(walk) > 1:
                return jsonify(walk)
        random.shuffle(pool)
        return jsonify([trow(r) for r in pool[:n]])
    if kind == "recent":
        ids = [r[0] for r in db().execute(
            "SELECT video_id FROM plays WHERE event='play' GROUP BY video_id "
            "ORDER BY MAX(ts) DESC LIMIT ?", (n,))]
        return jsonify([t for t in (track_by_id(v) for v in ids) if t])
    rows = db().execute("SELECT * FROM tracks ORDER BY RANDOM() LIMIT ?", (n,)).fetchall()
    return jsonify([trow(r) for r in rows])


# --------------------------------------------------------------------------- cover art + speed dial
import base64  # noqa: E402
from mutagen.oggopus import OggOpus  # noqa: E402
from mutagen.flac import Picture  # noqa: E402

_ART = {}  # vid -> (mime, bytes) | None  (small in-process cache)


def _extract_art(path):
    try:
        f = OggOpus(path)
        b = (f.tags or {}).get("metadata_block_picture", [None])[0]
        if not b:
            return None
        pic = Picture(base64.b64decode(b))
        return (pic.mime or "image/jpeg", bytes(pic.data))
    except Exception:
        return None


@app.get("/art/<vid>")
def art(vid):
    if vid not in _ART:
        if len(_ART) > 1500:
            _ART.clear()
        row = db().execute("SELECT path FROM tracks WHERE video_id=?", (vid,)).fetchone()
        _ART[vid] = _extract_art(row["path"]) if row else None
    a = _ART[vid]
    if not a:
        return ("", 404)
    return Response(a[1], mimetype=a[0], headers={"Cache-Control": "public, max-age=2592000"})


@app.get("/api/speeddial")
def speeddial():
    """Home's "Listen again" row and the Wheel — one list, like YouTube Music's: the songs
    you've been replaying lately. Every YT Music listen adds 0.5^(age / 21 days) to its
    song (age from the export's newest listen), so repeats this week rank first, then
    lighter and older ones, all the way back; ties go to the latest listen. One tile per
    song, library tracks only; ?offset=k pages on (the Wheel keeps loading as you spin;
    Home shows the first 18).

    In-app and H2 plays stay out while there is a Takeout: the H2 log had put a track you
    skipped twice (each start counted as a play) fourth on the Wheel. Without one, the
    in-app ranking below stands in (first page only)."""
    n = max(1, min(int(request.args.get("n", 12)), 200))
    offset = max(0, int(request.args.get("offset", 0)))
    events, end = recent_listens()
    if events:
        lib, score, latest = lib_ids(), {}, {}
        for vid, ts in events:
            if vid in lib:
                score[vid] = score.get(vid, 0.0) + 0.5 ** ((end - ts) / (LISTEN_AGAIN_HALFLIFE_DAYS * 86400))
                latest[vid] = ts
        order = sorted(score, key=lambda v: (score[v], latest[v]), reverse=True)
        return jsonify([t for t in map(track_by_id, order[offset:offset + n]) if t])
    if offset:
        return jsonify([])

    # no Takeout: a recency-weighted FREQUENCY ranking over the past ~week of the player
    # — tracks you keep coming back to rank highest, lighter one-offs fill the tail.
    # Completions/likes lift, skips barely count; a soft per-artist cap keeps it varied;
    # falls back to recent + random if sparse.
    now = time.time()
    WINDOW = 8 * 86400        # look back ~a week (plus a bit)
    HALFLIFE = 3.0 * 86400    # emphasize the last few days
    # unlike/trash are the retractions: a track you un-hearted or threw away must not keep
    # riding the tile row on the strength of the plays that earned it a slot.
    EVENT_VAL = {"like": 2.0, "complete": 1.5, "play": 1.0, "skip": 0.1,
                 "dislike": -3.0, "unlike": -2.0, "trash": -3.0}
    lib = lib_ids()

    scores, latest = {}, {}
    for vid, ts, event, _sec in db().execute(
            "SELECT video_id, ts, event, seconds FROM plays WHERE ts > ?", (now - WINDOW,)):
        if vid not in lib:
            continue
        v = EVENT_VAL.get(event, 0.5) * (0.5 ** ((now - ts) / HALFLIFE))
        scores[vid] = scores.get(vid, 0.0) + v
        latest[vid] = max(latest.get(vid, 0.0), ts or 0.0)

    # net-positive tracks, best score first; ties broken by most-recent play.
    ranked = sorted((v for v in scores if scores[v] > 0),
                    key=lambda v: (scores[v], latest[v]), reverse=True)

    out, seen, per_artist = [], set(), Counter()
    def add(t, cap=3):
        a = (t["artist"] or "").lower()
        if per_artist[a] >= cap:        # soft variety cap
            return False
        out.append(t); seen.add(t["id"]); per_artist[a] += 1
        return True

    for vid in ranked:
        if len(out) >= n:
            break
        t = track_by_id(vid)
        if t and t["id"] not in seen:
            add(t)
    # pad with most-recent plays we skipped (e.g. capped), then random library tracks.
    if len(out) < n:
        for r in db().execute("SELECT video_id FROM plays GROUP BY video_id "
                              "ORDER BY MAX(ts) DESC LIMIT ?", (n * 4,)):
            if len(out) >= n:
                break
            if r[0] in seen or r[0] not in lib:
                continue
            t = track_by_id(r[0])
            if t:
                out.append(t); seen.add(r[0])
    if len(out) < n:
        for r in db().execute("SELECT * FROM tracks ORDER BY RANDOM() LIMIT ?", (n * 4,)):
            if r["video_id"] in seen:
                continue
            out.append(trow(r)); seen.add(r["video_id"])
            if len(out) >= n:
                break
    return jsonify(out[:n])


# --------------------------------------------------------------------------- static (built Svelte app)

@app.get("/")
def index():
    if (WEB_DIST / "index.html").exists():
        return send_from_directory(WEB_DIST, "index.html")
    return ("<h3>Player API is up.</h3><p>Run the Vite dev server in web/ "
            "(npm run dev), or build it (npm run build) to serve from here.</p>")


# Something on this machine (not the player UI) spams POST / at localhost:5000 —
# swallow it quietly, keep it out of the access log, and print WHO it is once a
# minute so it can be identified.
import logging  # noqa: E402


class _DropRootPost(logging.Filter):
    def filter(self, record):
        return "POST / " not in record.getMessage()


logging.getLogger("werkzeug").addFilter(_DropRootPost())

_root_post = {"n": 0, "t": 0.0}


@app.post("/")
def root_post_probe():
    _root_post["n"] += 1
    now = time.time()
    if now - _root_post["t"] > 60:
        _root_post["t"] = now
        print(f"[probe] {_root_post['n']} stray POST / so far; latest from "
              f"UA={request.headers.get('User-Agent')!r} "
              f"CT={request.headers.get('Content-Type')!r} "
              f"len={request.content_length} origin={request.headers.get('Origin')!r}")
    return ("", 204)


@app.get("/<path:p>")
def assets(p):
    if (WEB_DIST / p).exists():
        return send_from_directory(WEB_DIST, p)
    if (WEB_DIST / "index.html").exists():
        return send_from_directory(WEB_DIST, "index.html")  # SPA fallback
    return ("not found", 404)


if __name__ == "__main__":
    # PLAYER_HOST=0.0.0.0 exposes the player on the LAN (phone/other devices)
    app.run(host=os.environ.get("PLAYER_HOST", "127.0.0.1"), port=5000, threaded=True)
