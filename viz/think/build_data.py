#!/usr/bin/env python3
# =============================================================================
# STRUCTURE COMMITMENT — written before a line of the film was built.
# (docs/DESIGN_NOTES.md principle 1: decide the direction first, then obey it.)
#
#   Film 1  viz/film/     = chaptered explainer. Chapter card -> scene -> chapter card.
#   Film 2  viz/transit/  = one continuous ride. No chapters, but still a camera
#                           travelling across a static 2-D atlas of the library.
#   Both are "a camera moving over a map". This film has NO map and NO camera move.
#
#   Film 3  viz/think/    = ONE DECISION, DILATED.  Structure: DILATE -> SNAP -> CHAIN.
#
#     Act 0  THE GAP        A track ends. The hairline runs out, the sound stops, and
#                           the film freezes in the silence between two songs, on the
#                           real measured wall-clock of one decision on this machine.
#     Act 1  THE DILATION   That single real decision stretched ~1e4x. Retrieval prints
#                           54,045 -> 800 -> 400. THREE of the 400 then lift out of the
#                           band and are taught one term at a time: the winner, the row a
#                           guardrail bars, the row fatigue strikes out. The page picks
#                           those three out of the decision itself — see DIRECTION.md —
#                           out of this same payload, so nothing here had to change for
#                           the third cut. Only then do the other 397 slam in around them,
#                           keeping their positions on the axis, and the whole cascade
#                           replays at field scale with nothing explained: IKB shoves
#                           right, signal red shoves left, a caret follows the running
#                           leader. At argmax the field re-sorts by score — the only thing
#                           in the film that "moves" — and the winner locks.
#     Act 2  THE SNAP       Time returns to x1. Same anatomy, three seconds a decision,
#                           ten in a row, winners dropping onto a tape of sleeves. One
#                           step is a real epsilon draw under 0.15: argmax struck through
#                           in red, the first never-played track in the top twelve taken
#                           instead. The only red-dominant frame in the film.
#     Act 3  THE LOG        A printed excerpt of a REAL epsilon swerve from
#                           data/next_trace.jsonl, timestamp and all. Closing slug.
#
#   The sheet never pans or zooms. Nothing glows. Everything on screen is a number this
#   script read or measured — see viz/think/DIRECTION.md.
# =============================================================================
"""Precompute everything viz/think's film needs -> viz/think/think_data.json + assets/.

Real data only. The engine is imported, not reimplemented: scripts/personalize.rank_next
scores through scripts/demo_autoplay_ab.Sim, which builds the same library, the same real
preference state and the same session mechanics as scripts/server.py's /api/next.
(server.py itself is never imported — it loads the 55k matrix at import time.)

What it produces:
  * one warm-up session (5 tracks) so mood / fatigue / cooldown have real history,
  * THE hero decision, with the full signed 12-term breakdown of all 400 candidates,
  * a 10-decision chain at epsilon 0.15 containing at least one genuine exploration,
  * a measured wall-clock for one decision (median of N runs) — the film's dilation factor,
  * a real epsilon swerve lifted out of data/next_trace.jsonl,
  * a 5-8 s audio snippet + embedded cover for every track that appears, each attenuated
    by its own r128_gain_db to the player's -14 LUFS target (web/src/lib/player.svelte.js).

Rebuild (from repo root, Windows):
    .venv\\Scripts\\python viz\\think\\build_data.py
    .venv\\Scripts\\python viz\\think\\bundle.py        # -> think_film.html (standalone)
    node viz\\think\\capture.js render 30               # -> frames/ + audio_cues.json
    .venv\\Scripts\\python viz\\think\\mux.py           # -> think_film.mp4
"""
from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import io
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "assets"
ASSETS.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "scripts"))

import demo_autoplay_ab as ab          # noqa: E402  (Sim + retrieval, NOT server.py)
import personalize                     # noqa: E402

FFMPEG = r"C:\Users\hasan\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
if not os.path.exists(FFMPEG):
    import shutil
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

TRACE = ROOT / "data" / "next_trace.jsonl"

# --- film shape ---------------------------------------------------------------
WARMUP = 5           # decisions before the hero one, so the session has real history
CHAIN = 10           # decisions after it, at tempo
EPSILON = 0.15       # the live default (scripts/server.py /api/next)
TOP_K = 12           # exploration window
LOUDNESS_OFFSET_DB = 9.0   # -14 LUFS target sits 9 dB above the R128 -23 reference
FILM_GAIN = 1.75     # one master trim for the whole soundtrack, applied after r128
FILM_TARGET_LUFS = -14.0   # where a snippet should sit in the film mix
MAKEUP_MAX = 12.0    # the most the film may lift a snippet the attenuate-only rule left low

# formula order: the six that can push a track up, then the six that can push it down.
TERM_ORDER = ["vibe", "mood", "taste", "pref_track", "pref_artist", "cooc",
              "novelty", "cooldown", "skip", "fatigue", "heard", "energy"]


def params_from_source():
    """Read rank_next's weight defaults out of scripts/personalize.py so the weights
    printed on screen cannot drift from the weights the engine actually uses."""
    src = inspect.getsource(personalize.rank_next)
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and getattr(node.targets[0], "id", None) == "p"):
            # not literal_eval: one value is written as `24 * 3600.0`
            return eval(compile(ast.Expression(body=node.value), "<params>", "eval"),
                        {"__builtins__": {}}, {})
    raise RuntimeError("could not read rank_next's default params")


P = params_from_source()


def term_cards():
    """The twelve terms as the film prints them: name, weight, what it reads."""
    def f(v):                       # 1.0 -> "1.0", 0.25 -> "0.25" (never a bare "1")
        return f"{v:.1f}" if abs(v * 10 - round(v * 10)) < 1e-9 else f"{v:g}"

    return [
        {"k": "vibe", "sign": 1, "w": f"+{f(P['alpha'])}",
         "rule": "cos(candidate, the track that just ended)",
         "gloss": "sound-alikeness to what is playing right now"},
        {"k": "mood", "sign": 1, "w": f"+{f(P['mu'])}",
         "rule": "cos(candidate, centroid of the last 12 played)",
         "gloss": "where this listening session has been sitting"},
        {"k": "taste", "sign": 1, "w": f"+{f(P['delta'])}",
         "rule": "cos(candidate, taste vector)",
         "gloss": "one vector built from every logged play, like and skip"},
        {"k": "pref_track", "sign": 1, "w": f"+{f(P['gamma'])}",
         "rule": "this track's own recency-decayed preference score",
         "gloss": "completed it, liked it, skipped it — the track's own record"},
        {"k": "pref_artist", "sign": 1, "w": f"+{f(P['gamma_artist'])}",
         "rule": f"tanh(artist preference), capped at \u00b1{f(P['gamma_artist'])}",
         "gloss": "a beloved uploader nudges; it is not allowed to shout"},
        {"k": "cooc", "sign": 1, "w": f"+{f(P['beta'])}",
         "rule": "flat, if it shares a YouTube-Music radio with the current track",
         "gloss": "the only signal here that comes from other listeners"},
        {"k": "novelty", "sign": 1, "w": f"+{f(P['nu'])}",
         "rule": f"{f(P['nu'])} \u00d7 0.5^(times played)",
         "gloss": "never-played tracks get all of it; worn ones get nothing"},
        {"k": "cooldown", "sign": -1, "w": f"\u2212{f(P['cooldown'])}",
         "rule": "flat, if this artist is in the last 4 played",
         "gloss": "an artist has to sit out four tracks"},
        {"k": "skip", "sign": -1, "w": f"\u2212{f(P['sigma'])}",
         "rule": "max(0, cos(candidate, skip centroid))",
         "gloss": "the shape of everything abandoned in the first 15%"},
        {"k": "fatigue", "sign": -1, "w": f"\u2212{f(P['rho'])}",
         "rule": f"max(0, closest sim to the last 6 \u2212 {f(P['rho_floor'])})",
         "gloss": "the anti-clone spring: nearer than 0.80 to a recent track hurts, hard"},
        {"k": "heard", "sign": -1, "w": f"\u2212{f(P['heard_w'])}",
         "rule": "0.5^(hours since last play / 24), inside 14 days",
         "gloss": "you heard it this week; let it cool off"},
        {"k": "energy", "sign": -1, "w": f"\u2212{f(P['energy_w'])}",
         "rule": f"max(0, |\u0394 energy percentile| \u2212 {f(P['energy_band'])})",
         "gloss": "no cut from a lullaby to a breakdown"},
    ]


# --- walking the real engine ---------------------------------------------------


def decide(sim, walk, rng, epsilon):
    """One /api/next decision. Returns the ranked window + the exploration draw.

    Mirrors personalize.choose_next_explained, but inlined so the raw uniform draw can be
    recorded and printed on screen (the film shows the actual number the die came up)."""
    ctx = sim.context(walk)
    cand = sim.candidates(ctx["cur"], ctx["exclude"])
    ranked = sim.rank(ctx, cand, new=True)          # [(vid, score, terms)] best-first
    draw = rng.random()
    counts = sim.prefs.get("play_counts") or {}
    if draw >= epsilon:
        pick, reason = ranked[0][0], "exploit"
    else:
        pick, reason = None, None
        for e in ranked[:TOP_K]:
            if counts.get(e[0], 0) == 0:
                pick, reason = e[0], "explore_unheard"
                break
        if pick is None:
            pick, reason = rng.choice(ranked[:4])[0], "explore_random"
    rank_taken = next(i for i, e in enumerate(ranked) if e[0] == pick)
    return {"ctx": ctx, "ranked": ranked, "pick": pick, "reason": reason,
            "draw": draw, "rank_taken": rank_taken}


def leader_changes(ranked):
    """How many times the running argmax changes hands as the 12 terms are applied in
    formula order — the film's whole premise, so it is also the seed-picking metric."""
    T = np.array([[e[2][k] for k in TERM_ORDER] for e in ranked], dtype=np.float64)
    run = np.zeros(len(T))
    leader, changes = None, 0
    for c in range(T.shape[1]):
        run += T[:, c]
        top = int(np.argmax(run))
        if leader is not None and top != leader:
            changes += 1
        leader = top
    return changes, T


def richness(ranked):
    """Score a candidate hero decision: leadership drama first, then how many of the
    twelve terms are actually awake in this candidate window."""
    changes, T = leader_changes(ranked)
    live = [k for i, k in enumerate(TERM_ORDER) if np.any(T[:, i] != 0)]
    busy = sum(1 for i in range(T.shape[1]) if int(np.sum(T[:, i] != 0)) >= 5)
    negs = sum(1 for i, k in enumerate(TERM_ORDER)
               if k in ("cooldown", "skip", "fatigue", "heard", "energy")
               and np.any(T[:, i] != 0))
    return changes * 6 + len(live) * 2 + busy + negs * 3, changes, live


def run_walk(sim, seed_id, rng_seed, steps, epsilon=EPSILON):
    rng = random.Random(rng_seed)
    walk, out = [seed_id], []
    for _ in range(steps):
        d = decide(sim, walk, rng, epsilon)
        out.append(d)
        walk.append(d["pick"])
    return walk, out


# --- payload ------------------------------------------------------------------


def pack_step(sim, d, name_top=None, dp=4):
    """One decision as flat parallel arrays: compact, and the film can index straight in.

    name_top=None keeps every candidate's title (the hero field is hoverable); an int
    keeps names for the top N only and blanks the tail (the chain fields are texture)."""
    ranked = d["ranked"]
    counts = sim.prefs.get("play_counts") or {}
    n = len(ranked)
    keep = n if name_top is None else min(name_top, n)
    T = [[round(e[2][k], dp) for k in TERM_ORDER] for e in ranked]
    return {
        "from": sim.meta(d["ctx"]["cur"]),
        "n_cand": n,
        "ids": [e[0] for e in ranked],
        "titles": [sim.title.get(ranked[i][0], "") if i < keep else "" for i in range(n)],
        "artists": [sim.id2artist.get(ranked[i][0], "") if i < keep else ""
                    for i in range(n)],
        "plays": [int(counts.get(e[0], 0)) for e in ranked],
        "scores": [round(e[1], dp) for e in ranked],
        "T": T,
        "winner": d["rank_taken"],
        "reason": d["reason"],
        "draw": round(d["draw"], 4),
        "epsilon": EPSILON,
        "recent_artists": sorted(a for a in d["ctx"]["recent_artists"] if a),
        # why a silent term is silent — the film prints the reason, not a shrug
        "diag": {
            "cur_energy": sim.energy.get(d["ctx"]["cur"]),
            "cand_energy": sum(1 for e in ranked if e[0] in sim.energy),
            "cand_heard": sum(1 for e in ranked if e[0] in sim.heard),
            "cand_pref": sum(1 for e in ranked if sim.prefs["track"].get(e[0])),
            "cur_radio": len(sim.cooc.get(d["ctx"]["cur"], ())),
            "first_unheard": next((i for i, e in enumerate(ranked[:TOP_K])
                                   if counts.get(e[0], 0) == 0), None),
            "topk_unheard": sum(1 for e in ranked[:TOP_K] if counts.get(e[0], 0) == 0),
        },
    }


def slug_id(vid):
    """Stable, filesystem-safe asset name (video ids contain spaces, brackets, quotes;
    Python's str hash is salted per process, so md5 is the reproducible choice)."""
    return hashlib.md5(vid.encode("utf-8")).hexdigest()[:12]


def cover(sim, vid, px=240):
    """Embedded cover art, same route as server._extract_art."""
    from mutagen.flac import Picture
    from mutagen.oggopus import OggOpus
    row = sim.db.execute("SELECT path FROM tracks WHERE video_id=?", (vid,)).fetchone()
    if not row or not row["path"] or not os.path.exists(row["path"]):
        return None
    try:
        b64 = (OggOpus(row["path"]).tags or {}).get("metadata_block_picture", [None])[0]
        if not b64:
            return None
        raw = Picture(base64.b64decode(b64)).data
    except Exception:
        return None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        im.thumbnail((px, px))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=84)
        raw = buf.getvalue()
    except Exception:
        pass
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def lufs(path):
    """Integrated loudness of a rendered snippet (ffmpeg ebur128)."""
    err = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path),
                          "-af", "ebur128=framelog=quiet", "-f", "null", os.devnull],
                         stderr=subprocess.PIPE).stderr.decode("utf-8", "ignore")
    m = re.findall(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", err)
    return float(m[-1]) if m else None


def cut(path, start, seconds, gain, out):
    af = (f"volume={gain:.4f},alimiter=limit=0.92,"
          f"afade=t=in:d=0.35,afade=t=out:st={max(0.1, seconds - 0.55):.2f}:d=0.55")
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{start:.2f}", "-t", f"{seconds:.2f}", "-i", path,
                    "-vn", "-map", "0:a:0", "-ac", "1", "-ar", "44100", "-af", af,
                    "-c:a", "aac", "-b:a", "112k", str(out)], check=True)


def clip(sim, vid, seconds, tail=False):
    """A level-matched snippet cut with ffmpeg.

    Pass 1 applies the PLAYER's own rule (web/src/lib/player.svelte.js): retarget the R128
    -23 LUFS reference to -14 and only ever attenuate, so loud masters come down and
    nothing clips. That rule is faithful but deliberately never boosts, so a very quiet
    master stays very quiet — three of this film's tracks land near -31 LUFS, 20 dB under
    the rest, which is fine in a player and useless in a soundtrack. Pass 2 measures what
    pass 1 produced and adds a bounded make-up (at most MAKEUP_MAX dB) to bring stragglers
    up to the film target. The r128 gain is still what sets the relative levels; the
    make-up only lifts what the attenuate-only clamp left behind."""
    row = sim.db.execute(
        "SELECT path, duration, r128_gain_db FROM tracks WHERE video_id=?", (vid,)).fetchone()
    if not row or not row["path"] or not os.path.exists(row["path"]):
        return None, None
    path, dur = row["path"], float(row["duration"] or 0)
    g = row["r128_gain_db"]
    mult = 1.0 if g is None else min(1.0, 10 ** ((float(g) + LOUDNESS_OFFSET_DB) / 20.0))
    hook = sim.db.execute(
        "SELECT hook_sec FROM analysis WHERE video_id=?", (vid,)).fetchone()
    if tail:                       # the track that is ending: play it out
        start = max(0.0, dur - seconds - 1.0)
    elif hook and hook[0] is not None and 0 < float(hook[0]) < max(1.0, dur - seconds):
        start = float(hook[0])     # the analysis sweep's audition point
    else:
        start = min(max(24.0, dur * 0.33), max(1.0, dur - seconds - 1.0))
    out = ASSETS / f"clip_{slug_id(vid)}.m4a"
    cut(path, start, seconds, mult * FILM_GAIN, out)
    got = lufs(out)
    makeup = 0.0
    if got is not None and got < FILM_TARGET_LUFS:
        makeup = min(MAKEUP_MAX, FILM_TARGET_LUFS - got)
        if makeup > 0.5:
            cut(path, start, seconds, mult * FILM_GAIN * 10 ** (makeup / 20.0), out)
    return ("data:audio/mp4;base64," + base64.b64encode(out.read_bytes()).decode()), {
        "file": out.name, "gain_db": g, "mult": round(mult, 4),
        "lufs": got, "makeup_db": round(makeup, 1),
        "start": round(start, 2), "dur": seconds}


def epsilon_bite(sim, limit=80):
    """A REAL decision where the exploration rule actually changes the answer.

    In this library it is rare on purpose: 436 logged plays over 54,045 tracks means the
    argmax is nearly always already unheard, so "take the best never-played track in the
    top 12" resolves to the argmax. It bites only when a worn favourite is sitting at
    rank 1 — so probe by starting a station from the most-played tracks themselves."""
    counts = sim.prefs.get("play_counts") or {}
    for vid in sorted(counts, key=lambda v: -counts[v])[:limit]:
        if vid not in sim.E["id2i"] or vid not in sim.lib:
            continue
        d = decide(sim, [vid], random.Random(0), 0.0)
        top = d["ranked"][:TOP_K]
        if counts.get(top[0][0], 0) == 0:
            continue
        j = next((i for i, e in enumerate(top) if counts.get(e[0], 0) == 0), None)
        if not j:                                    # None, or 0 = no swerve
            continue
        return {
            "from": dict(sim.meta(vid), plays=counts.get(vid, 0)),
            "argmax": dict(sim.meta(top[0][0]), score=round(top[0][1], 3),
                           plays=counts.get(top[0][0], 0)),
            "taken": dict(sim.meta(top[j][0]), score=round(top[j][1], 3),
                          plays=0, rank=j),
            "worn_in_topk": sum(1 for e in top if counts.get(e[0], 0)),
            "top_k": TOP_K,
        }
    return None


def log_excerpt():
    """The genuine exploration events in the live /api/next trace (data/next_trace.jsonl),
    written by scripts/server.py while music was actually playing. Features the most
    recent one in full, and counts how many of them changed the answer — which is the
    film's punchline, so it is measured rather than asserted."""
    if not TRACE.exists():
        return None
    rows, feat, n_expl, n_changed = 0, None, 0, 0
    t_lo, t_hi = None, None
    for line in TRACE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        rows += 1
        t_lo = o["ts"] if t_lo is None else min(t_lo, o["ts"])
        t_hi = o["ts"] if t_hi is None else max(t_hi, o["ts"])
        if not o.get("pick", {}).get("explored"):
            continue
        top = o.get("top") or []
        taken = next((c for c in top if c["id"] == o["pick"]["id"]), None)
        if taken is None:
            continue
        n_expl += 1
        idx = top.index(taken)
        if idx:
            n_changed += 1
        feat = {
            "ts": o["ts"],
            "ts_human": time.strftime("%d %b %Y, %H:%M", time.localtime(o["ts"])),
            "epsilon": o.get("epsilon", EPSILON),
            "current": o["current"],
            "reason": o["pick"]["reason"],
            "argmax": {"title": top[0]["title"], "artist": top[0]["artist"],
                       "score": top[0]["score"], "plays": top[0].get("play_count", 0)},
            "taken": {"title": taken["title"], "artist": taken["artist"],
                      "score": taken["score"], "plays": taken.get("play_count", 0),
                      "rank": idx},
            "runner_up": {"title": top[1]["title"], "artist": top[1]["artist"],
                          "score": top[1]["score"]} if len(top) > 1 else None,
            "n_top": len(top),
            "topk_unheard": sum(1 for c in top if not c.get("play_count", 0)),
        }
    if feat is None:
        return None
    feat.update({
        "n_decisions": rows, "n_explore": n_expl, "n_changed": n_changed,
        "span": (time.strftime("%d %b", time.localtime(t_lo)) + " – "
                 + time.strftime("%d %b %Y", time.localtime(t_hi))),
    })
    return feat


def measure(sim, walk, reps=7):
    """Wall-clock of ONE decision on this machine: retrieval (54k cosines + the eligible
    filter) and the 12-term scoring of the 400 survivors, timed separately, median of reps.
    This is the number the film dilates."""
    ctx = sim.context(walk)
    ret, sco = [], []
    for _ in range(reps):
        t0 = time.perf_counter()
        cand = sim.candidates(ctx["cur"], ctx["exclude"])
        t1 = time.perf_counter()
        sim.rank(ctx, cand, new=True)
        t2 = time.perf_counter()
        ret.append(t1 - t0)
        sco.append(t2 - t1)
    med = lambda v: float(np.median(v))  # noqa: E731
    return {"retrieve_ms": round(med(ret) * 1000, 3), "score_ms": round(med(sco) * 1000, 3),
            "total_ms": round((med(ret) + med(sco)) * 1000, 3), "reps": reps}


def p(s):
    enc = sys.stdout.encoding or "utf-8"
    print(str(s).encode(enc, "replace").decode(enc, "replace"), flush=True)


def main():
    now = time.time()
    t0 = time.time()
    sim = ab.Sim(now)
    p(f"[data] {sim.n_tracks} tracks | {sim.n_plays} plays | {len(sim.cooc)} radio seeds | "
      f"{len(sim.heard)} heard-stamped | {len(sim.energy)} energy percentiles "
      f"({100.0 * len(sim.energy) / sim.n_tracks:.1f}%)  [{time.time() - t0:.1f}s]")

    # ---- pick the hero seed: the decision with the most leadership changes -----------
    # Candidate seeds are real, playable tracks that give every term a chance to speak:
    # a radio-cache seed (cooc), an energy percentile (energy), and a top-preference
    # artist (pref_artist). The three demo_autoplay_ab seeds are always in the running.
    pool = [s for s, _ in ab.SEEDS]
    for vid in sim.cooc:
        if vid in sim.E["id2i"] and vid in sim.energy and vid not in pool:
            pool.append(vid)
        if len(pool) >= 26:
            break
    p(f"[seeds] evaluating {len(pool)} candidate seeds at step {WARMUP + 1} ...")

    # The seed the richness search picked on 2026-07-26 (10 of the 12 terms fire, the lead
    # changes hands 5 times, and the winner only takes it on the LAST term). Pinned so a
    # rebuild reproduces this film even though the analysis sweep is still filling in
    # energy rows underneath it; set to None to re-run the search.
    SEED_PIN = "os1Cj6RYx5U"

    best = None
    for vid in pool:
        if vid not in sim.E["id2i"]:
            continue
        try:
            walk, ds = run_walk(sim, vid, 12345, WARMUP + 1, epsilon=0.0)
        except (StopIteration, IndexError):
            continue
        r, changes, live = richness(ds[-1]["ranked"])
        if best is None or r > best[0]:
            best = (r, vid, changes, live)
            p(f"  * {sim.title.get(vid, vid)[:44]!r}  richness {r}  "
              f"leader changes {changes}  live terms {len(live)}")
    assert best, "no usable seed"
    _r, SEED, _c, _l = best
    if SEED_PIN and SEED_PIN != SEED:
        p(f"[seed] search picked {SEED}; using the pinned seed {SEED_PIN} instead")
        SEED = SEED_PIN
    p(f"[seed] {sim.id2artist.get(SEED)} - {sim.title.get(SEED)}  ({SEED})")

    # ---- pick the rng seed: the first integer that keeps the warm-up and the hero
    # decision on argmax and puts exactly one genuine epsilon swerve in the ten-step
    # chain. The seed is chosen; the draws are the engine's.
    RNG_SEED, plan = None, None
    for s in range(4000):
        rng = random.Random(s)
        draws = [rng.random() for _ in range(WARMUP + 1 + CHAIN)]
        head, tail = draws[:WARMUP + 1], draws[WARMUP + 1:]
        if any(d < EPSILON for d in head):
            continue
        hits = [i for i, d in enumerate(tail) if d < EPSILON]
        if len(hits) == 1 and 1 <= hits[0] <= CHAIN - 2:
            RNG_SEED, plan = s, hits
            break
    assert RNG_SEED is not None, "no rng seed with a single mid-chain exploration"
    p(f"[rng] seed {RNG_SEED} -> exploration planned at chain step {plan[0] + 1}")

    walk, decs = run_walk(sim, SEED, RNG_SEED, WARMUP + 1 + CHAIN)
    for i, d in enumerate(decs):
        tag = "warmup" if i < WARMUP else ("HERO" if i == WARMUP else f"chain {i - WARMUP}")
        p(f"  {tag:<9} draw {d['draw']:.3f} {d['reason']:<15} rank {d['rank_taken']:>2}  "
          f"{sim.id2artist.get(d['pick'], '')[:22]} - {sim.title.get(d['pick'], '')[:40]}")
    assert decs[WARMUP]["reason"] == "exploit", "hero decision must be an argmax"
    explores = [i - WARMUP for i, d in enumerate(decs)
                if i > WARMUP and d["reason"] != "exploit"]
    assert explores, "chain has no exploration"
    p(f"[chain] exploration(s) at chain step(s) {explores}")

    timing = measure(sim, walk[:WARMUP + 1])
    p(f"[timing] retrieve {timing['retrieve_ms']} ms + score {timing['score_ms']} ms "
      f"= {timing['total_ms']} ms per decision (median of {timing['reps']})")

    hero = pack_step(sim, decs[WARMUP], name_top=None, dp=4)
    hero_changes, _ = leader_changes(decs[WARMUP]["ranked"])
    chain = [pack_step(sim, d, name_top=16, dp=3) for d in decs[WARMUP + 1:]]

    # ---- session tape: the five tracks already played when the hero decision happens
    session = [sim.meta(v) for v in walk[:WARMUP + 1]]

    # ---- audio + covers for every track the film names out loud
    media, order = {}, []
    order.append((walk[WARMUP], 9.0, True))                       # the track that ends
    order.append((decs[WARMUP]["pick"], 9.0, False))              # the hero winner
    for d in decs[WARMUP + 1:]:
        order.append((d["pick"], 5.0, False))
    for v in walk[:WARMUP]:
        order.append((v, 0.0, False))                             # sleeves only
    p(f"[media] extracting {len(order)} covers / clips ...")
    for vid, secs, tail in order:
        if vid in media:
            continue
        art = cover(sim, vid)
        if secs <= 0:                       # session sleeves: cover only, no ffmpeg cut
            media[vid] = dict(sim.meta(vid), art=art, clip=None, audio=None)
            continue
        snip, m = clip(sim, vid, secs, tail)
        media[vid] = dict(sim.meta(vid), art=art, clip=snip, audio=m)
        p(f"  {'tail' if tail else 'hook'} {secs:.0f}s  r128 {m['gain_db']:+.1f} dB "
          f"-> x{m['mult']:.3f}  {m['lufs']:.1f} LUFS  makeup {m['makeup_db']:+.1f} dB  "
          f"{sim.id2artist.get(vid, '')[:20]} - {sim.title.get(vid, '')[:34]}")

    log = log_excerpt()
    if log:
        p(f"[log] {log['n_decisions']} live decisions ({log['span']}), "
          f"{log['n_explore']} of them exploration draws, {log['n_changed']} changed the "
          f"pick. featured: {log['ts_human']} — {log['reason']}, took rank "
          f"{log['taken']['rank'] + 1}")
    bite = epsilon_bite(sim)
    if bite:
        p(f"[bite] epsilon does swerve from {bite['from']['title'][:34]!r}: rank 1 "
          f"{bite['argmax']['title'][:30]!r} (played {bite['argmax']['plays']}x) -> rank "
          f"{bite['taken']['rank'] + 1} {bite['taken']['title'][:30]!r}")
    else:
        p("[bite] no epsilon swerve found in the probe window")

    payload = {
        "generated": now,
        "generated_human": time.strftime("%Y-%m-%d %H:%M", time.localtime(now)),
        "meta": {
            "tracks": sim.n_tracks, "plays": sim.n_plays,
            "dims": int(sim.E["X"].shape[1]),
            "retrieve_scan": ab.RETRIEVE_SCAN, "retrieve_keep": ab.RETRIEVE_KEEP,
            "epsilon": EPSILON, "top_k": TOP_K,
            "rng_seed": RNG_SEED, "seed_id": SEED,
            "radio_seeds": len(sim.cooc), "heard_tracks": len(sim.heard),
            "energy_tracks": len(sim.energy),
            "timing": timing, "hero_leader_changes": hero_changes,
            "loudness": {"reference_db": -23, "target_db": -14,
                         "offset_db": LOUDNESS_OFFSET_DB, "film_gain": FILM_GAIN},
        },
        "terms": term_cards(),
        "term_order": TERM_ORDER,
        "session": session,
        "hero": hero,
        "chain": chain,
        "log": log,
        "bite": bite,
        "media": media,
    }
    out = OUT / "think_data.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    p(f"[out] {out}  ({out.stat().st_size / 1e6:.2f} MB)  in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
