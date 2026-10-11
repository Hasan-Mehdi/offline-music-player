#!/usr/bin/env python3
"""Offline replay of an /api/next autoplay pick, with a per-term score breakdown.

Resolves a "current" track from library.db by title/artist substring, reruns the exact
server ranking pipeline (neighbors-table retrieval if present, else a full fp32 matmul,
then the personalization layer over the whole plays log), and prints the ranked
candidates with every scoring term broken out — so you can see WHY a hop happened.
Optionally highlights the track that was actually --picked and says which mechanism
(pure exploit / explore-unheard slot / explore-random) could have surfaced it.

Usage:
  .venv\\Scripts\\python scripts\\trace_next.py --cur Blimport --artist Shimomura \\
      --picked "King Olly" --exclude "Bloo Bay Beach" --exclude "Shopping in Wakeport" \\
      --exclude "Cherry Lake" --before "2026-07-02 23:13:41" --full
  .venv\\Scripts\\python scripts\\trace_next.py --cur "Bloo Bay" --top 20

--artist disambiguates duplicate rips (the library has the same title on several
channels); --before makes the replay TIME-CORRECT: prefs from plays strictly before
that local-time moment, recency-decayed to it — not to now; --full forces the desktop
full-matrix retrieval (top-800 sims -> 400 candidates) even when the neighbors table
exists, mirroring a non-LOW_MEM server; --recent (repeatable, oldest->newest) rebuilds
the session context — fatigue term, session-mood centroid, artist cooldown — from the
played tail, matching a trace line's "recent" field. Without it the replay behaves like
a fresh session (tail = the current track only).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import personalize  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "library.db"
EPSILON = 0.15          # mirrors /api/next
EXPLORE_TOPK = 12       # choose_next window for the explore-unheard slot
# term display columns (key -> header), in the same left-to-right order server blends them.
# cooc/heard/energy always read 0.000 here: the replay does not yet feed rank_next the
# radio-cache membership, last-heard timestamps or energy percentiles the server passes
# (nor tempo, the listening history or session rejections). For a decision-faithful
# replay call server.next_decision — scripts/eval_autoplay.py does.
TERMS = [("vibe", "vibe"), ("mood", "mood"), ("taste", "taste"), ("pref_track", "prefT"),
         ("pref_artist", "prefA"), ("cooldown", "cooldn"), ("skip", "skip"),
         ("fatigue", "fatig"), ("novelty", "novel"), ("cooc", "cooc"),
         ("heard", "heard"), ("energy", "energy")]


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cur", required=True, help="title/artist substring for the current track")
    p.add_argument("--artist", default=None,
                   help="artist substring filter for --cur/--picked (duplicate-rip safety)")
    p.add_argument("--exclude", action="append", default=[],
                   help="title/artist substring to exclude (repeatable)")
    p.add_argument("--recent", action="append", default=[],
                   help="title/artist substring of a recently played track, oldest->newest "
                        "(repeatable, ordered). Feeds the fatigue term, the session-mood "
                        "centroid and the artist cooldown exactly like the live /api/next "
                        "recent tail (a trace line's \"recent\" field, in order). Recents "
                        "are auto-excluded.")
    p.add_argument("--picked", default=None,
                   help="title/artist substring of the track actually chosen (to highlight)")
    p.add_argument("--before", default=None, metavar="YYYY-MM-DD HH:MM:SS",
                   help="time-correct replay: prefs only from plays before this local time")
    p.add_argument("--full", action="store_true",
                   help="force full-matrix retrieval (non-LOW_MEM server) over the neighbors table")
    p.add_argument("--top", type=int, default=15, help="rows to print (default: 15)")
    return p.parse_args(argv)


def load_emb():
    """Full fp32 MuQ matrix, L2-normalized and centered like the server's (emb()) — the
    ranking always needs the vectors even when retrieval uses the neighbors table."""
    d = np.load(ROOT / "data" / "muq_embeddings.npz", allow_pickle=False)
    X = d["embeddings"].astype("float32")
    X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    personalize.center_embeddings(X)
    ids = [str(x) for x in d["ids"]]
    return {"X": X, "ids": ids, "id2i": {v: i for i, v in enumerate(ids)}}


def _autoplay_params():
    """The live overrides (server.AUTOPLAY_PARAMS), so the terms print at the server's
    weights. Imported lazily: server.py builds a Flask app on import."""
    import server
    return server.AUTOPLAY_PARAMS


def resolve(con, substr, artist=None):
    """video_ids whose title or artist contains `substr` (case-insensitive), optionally
    restricted to artists containing `artist` — duplicate rips make title-only matching
    dangerous (same OST on several channels)."""
    like = f"%{substr}%"
    sql = "SELECT video_id, artist, title FROM tracks WHERE (title LIKE ? OR artist LIKE ?)"
    params = [like, like]
    if artist:
        sql += " AND artist LIKE ?"
        params.append(f"%{artist}%")
    return [(r["video_id"], r["artist"], r["title"]) for r in con.execute(
        sql + " ORDER BY title COLLATE NOCASE", params)]


def main(argv):
    args = parse_args(argv)
    try:                                    # track titles carry arbitrary unicode
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    E = load_emb()

    matches = resolve(con, args.cur, args.artist)
    if not matches:
        print(f"no track matches --cur {args.cur!r}"
              + (f" with --artist {args.artist!r}" if args.artist else ""))
        return 1
    cur, cur_artist, cur_title = matches[0]
    if len(matches) > 1:
        print(f"note: --cur {args.cur!r} matched {len(matches)} tracks (using the first; "
              f"disambiguate with --artist):")
        for _v, a, t in matches:
            print(f"  {a} - {t}")

    # recents: first match of each --recent substring, in the given (oldest->newest)
    # order — mirrors the ordered tail /api/next derives from the client's exclude list.
    recent_hist = []
    for substr in args.recent:
        m = resolve(con, substr, args.artist) or resolve(con, substr)
        if not m:
            print(f"note: --recent {substr!r} matched nothing (skipped)")
            continue
        recent_hist.append(m[0][0])

    # excludes: every match of every --exclude substring, the recents, and the current
    # track itself.
    exclude = {cur} | set(recent_hist)
    for substr in args.exclude:
        exclude.update(v for v, _a, _t in resolve(con, substr))
    picked = set()
    if args.picked:
        pmatches = resolve(con, args.picked, args.artist)
        if not pmatches and args.artist:   # picked is often by a DIFFERENT artist than cur
            pmatches = resolve(con, args.picked)
        if len(pmatches) > 1:
            print(f"note: --picked {args.picked!r} matched {len(pmatches)} tracks "
                  f"(highlighting all):")
            for _v, a, t in pmatches:
                print(f"  {a} - {t}")
        picked = {v for v, _a, _t in pmatches}

    # --- meta aligned to embedding order (mirrors server.track_meta) ---
    rows = {r["video_id"]: r for r in con.execute(
        "SELECT video_id, artist, duration FROM tracks")}
    id2artist = {v: (r["artist"] or "") for v, r in rows.items()}
    durations = {v: r["duration"] for v, r in rows.items()}
    id2title = {r["video_id"]: r["title"] for r in con.execute(
        "SELECT video_id, title FROM tracks")}
    artist_by_index = [id2artist.get(v, "") for v in E["ids"]]
    lib = set(rows)

    # --- personalization over the plays log (mirrors server.personalization). With
    # --before, replay the prefs AS OF that moment: only earlier plays, decayed to it. ---
    now = time.time()
    plays = con.execute("SELECT video_id, ts, event, seconds FROM plays").fetchall()
    if args.before:
        now = time.mktime(time.strptime(args.before, "%Y-%m-%d %H:%M:%S"))
        plays = [r for r in plays if (r["ts"] or 0) < now]
    prefs = personalize.compute_prefs(
        [(r["video_id"], r["ts"], r["event"], r["seconds"]) for r in plays],
        durations, id2artist, now=now)
    taste = personalize.build_centroid(E["X"], E["id2i"], prefs["track"])
    skip = personalize.build_centroid(E["X"], E["id2i"], {v: 1.0 for v in prefs["skip_ids"]})
    counts = prefs.get("play_counts") or {}

    # --- candidate retrieval: neighbors table if present (LOW_MEM server), else the
    # full-matrix top sims; --full forces the latter (the desktop/non-LOW_MEM path). ---
    has_neighbors = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='neighbors'").fetchone()
    cand = []
    if has_neighbors and not args.full:
        for r in con.execute(
                "SELECT neighbor_id FROM neighbors WHERE video_id=? ORDER BY rank", (cur,)):
            vid = r[0]
            if vid not in exclude and vid in lib:
                cand.append(vid)
    if not cand and cur in E["id2i"]:
        sims = (E["X"] @ E["X"][E["id2i"][cur]]).astype("float32")
        for j in np.argsort(-sims)[1:800]:
            vid = E["ids"][int(j)]
            if vid in exclude or vid not in lib:
                continue
            cand.append(vid)
            if len(cand) >= 400:
                break

    # --- recent tails, exactly as /api/next derives them from the ordered exclude list:
    # session-mood centroid over the last 12 (current included), fatigue over the last 6,
    # artist cooldown over the last 4 + current. ---
    mood_ids = [v for v in recent_hist if v != cur][-11:] + [cur]
    recent_ids = mood_ids[-6:]
    rvecs = [E["X"][E["id2i"][v]] for v in recent_ids if v in E["id2i"]]
    session_vec = personalize.build_centroid(E["X"], E["id2i"], {v: 1.0 for v in mood_ids})
    recent_artists = {id2artist.get(v, "") for v in recent_ids[-4:]}
    recent_artists.discard("")
    if cur_artist:
        recent_artists.add(cur_artist)

    ranked = personalize.rank_next(
        cur, cand, E["X"], E["id2i"], E["ids"], artist_by_index,
        prefs=prefs, taste_vec=taste, skip_vec=skip,
        recent_artists=recent_artists,
        recent_vecs=np.stack(rvecs) if rvecs else None,
        session_vec=session_vec, explain=True, params=_autoplay_params())

    # --- print ---
    src = "neighbors table (LOW_MEM)" if (has_neighbors and not args.full and cand) \
        else "full-matrix sims (top-800 -> 400)"
    when = f", prefs as of {args.before}" if args.before else ""
    print(f"\ncurrent : {cur_artist} - {cur_title}  [{cur}]")
    print(f"retrieval: {src}, {len(cand)} candidates  (exclude {len(exclude)}, "
          f"epsilon {EPSILON}{when})\n")

    hdr = f"{'#':>3}  {'artist - title':<44} {'total':>7} " + \
        " ".join(f"{h:>6}" for _k, h in TERMS) + f" {'plays':>5}  "
    print(hdr)
    print("-" * len(hdr))
    for i, (vid, s, t) in enumerate(ranked[:args.top]):
        name = f"{id2artist.get(vid, '')} - {id2title.get(vid, vid)}"
        if len(name) > 44:
            name = name[:43] + "~"
        mark = " <-- picked" if vid in picked else ""
        cols = " ".join(f"{t[k]:>6.3f}" for k, _h in TERMS)
        print(f"{i:>3}  {name:<44} {s:>7.3f} {cols} {counts.get(vid, 0):>5}{mark}")

    # --- interpretation of where the picked track sits ---
    if picked:
        prank = next((i for i, (vid, *_r) in enumerate(ranked) if vid in picked), None)
        pvid = next((vid for vid, *_r in ranked if vid in picked), None)
        print()
        if prank is None:
            print(f"picked ({args.picked!r}) is NOT in the candidate set — it was excluded "
                  f"or not retrieved as a neighbour of the current track.")
        else:
            pc = counts.get(pvid, 0)
            # the explore-unheard slot takes the *best-ranked* unheard track in the window
            first_unheard = next(
                (i for i, (vid, *_r) in enumerate(ranked[:EXPLORE_TOPK])
                 if counts.get(vid, 0) == 0), None)
            print(f"picked  : {id2artist.get(pvid, '')} - {id2title.get(pvid, pvid)} "
                  f"@ rank {prank}, {pc} plays")
            if prank == 0:
                print("=> rank 1: a PURE EXPLOIT pick (no exploration needed).")
            elif prank < EXPLORE_TOPK and pc == 0 and first_unheard == prank:
                print(f"=> unheard & top-ranked-unheard within top {EXPLORE_TOPK}: reachable via "
                      f"the epsilon={EPSILON} EXPLORE-UNHEARD slot (~1-in-{round(1/EPSILON)} hops).")
            elif prank < 4:
                print(f"=> within top 4: reachable via the rare EXPLORE-RANDOM fallback "
                      f"(only when every top-{EXPLORE_TOPK} track is already heard).")
            else:
                print("=> neither rank 1, the top explore-unheard, nor top 4: this exact replay "
                      "would not pick it — prefs/plays have drifted since the live hop.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
