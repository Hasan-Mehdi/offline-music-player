#!/usr/bin/env python3
"""Side-by-side demo of an autoplay walk under the OLD vs NEW rank_next scoring.

The three newest rank_next terms (`cooc` radio co-occurrence, `heard` already-played
recency damping, `energy` continuity) are opt-in: with their inputs omitted rank_next is
bitwise-identical to the formula that has been live until today. This script runs both
formulas against the SAME library, the SAME real preference state and the SAME session
mechanics as scripts/server.py's /api/next, and renders the two walks as a two-column
tape so you can see exactly where — and why — the new signals change the queue.

  A (OLD)  rank_next(..., prefs, taste_vec, skip_vec, recent_artists, recent_vecs, session_vec)
  B (NEW)  same + cooc_members= + last_played=/now= + energies=

Deterministic by construction: epsilon = 0 (always rank 0, no exploration draw) and a
single `now` stamped once at start and reused everywhere, so reruns are identical.

Run:  .venv\\Scripts\\python scripts\\demo_autoplay_ab.py
Out:  viz/autoplay_ab.html (standalone, data inlined)  +  viz/autoplay_ab.json
"""
from __future__ import annotations

import html
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import personalize  # noqa: E402  (sibling module; NOT server.py — that loads the matrix at import)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "library.db"
EMB_NPZ = ROOT / "data" / "muq_embeddings.npz"
RADIO_CACHE = ROOT / "data" / "radio_cache"
OUT_HTML = ROOT / "viz" / "autoplay_ab.html"
OUT_JSON = ROOT / "viz" / "autoplay_ab.json"

STEPS = 20                  # walk length per side
RETRIEVE_SCAN = 800         # server: top-800 by similarity ...
RETRIEVE_KEEP = 400         # ... first 400 eligible become the candidate window

# Three contrasting seeds that exist in the library, chosen so all three new terms get a
# chance to speak: all are radio-cache seeds with 44-50 in-library members (`cooc` fires
# on every walk); the lofi seed sits in the neighbourhood of yesterday's listening session,
# the only place `heard` can fire (only ~14 tracks are inside its 14-day horizon); and the
# VGM seed is one of the ~300 tracks with an `analysis` row, the only way `energy` can fire
# at all at today's coverage (it needs BOTH the current track and the candidate to have one).
SEEDS = [
    ("os1Cj6RYx5U", "lofi/chill — and sits in yesterday's listening neighbourhood"),
    ("Ef3gJ4E6MFY", "future funk / vaporwave — the sample-flip electronic end"),
    ("-GUYHgvuoKo", "big-band VGM cover — top-played artist, and has an energy percentile"),
]

TERMS = ["vibe", "mood", "taste", "pref_track", "pref_artist", "cooldown",
         "skip", "fatigue", "novelty", "cooc", "heard", "energy"]
NEW_TERMS = ["cooc", "heard", "energy"]

FORMULA_OLD = ("vibe + mood + taste + pref_track + tanh(pref_artist) "
               "- cooldown - skip - fatigue + novelty")
FORMULA_NEW = FORMULA_OLD + "  + cooc(beta .3) - heard(w .6, hl 24h) - energy(w .8, band .25)"


# --------------------------------------------------------------------------- data


def load_db():
    c = sqlite3.connect(DB, timeout=60)
    c.row_factory = sqlite3.Row
    return c


def load_embeddings():
    """fp32, L2-normalized rows — same as server.emb() in its non-LOW_MEM path."""
    d = np.load(EMB_NPZ, allow_pickle=False)
    X = d["embeddings"].astype("float32")
    X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    ids = [str(v) for v in d["ids"]]
    return {"X": X, "ids": ids, "id2i": {v: i for i, v in enumerate(ids)}}


def load_cooc(lib):
    """{seed_video_id: set(radio members we own)} — mirrors server.cooc_members()."""
    out, files = {}, 0
    for f in sorted(RADIO_CACHE.glob("*.json")) if RADIO_CACHE.exists() else ():
        files += 1
        try:
            tracks = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        mem = {t.get("videoId") for t in tracks
               if isinstance(t, dict) and t.get("videoId")} & lib
        if mem:
            out[f.stem] = mem
    return out, files


def load_energy(db):
    """{vid: 0..1 percentile of energy_db} — mirrors server._energy_ranks(). Missing
    table or <2 rows -> {} and the energy term is a silent no-op."""
    try:
        rows = db.execute(
            "SELECT video_id, energy_db FROM analysis WHERE energy_db IS NOT NULL").fetchall()
    except sqlite3.Error:
        return {}
    if len(rows) < 2:
        return {}
    order = sorted(rows, key=lambda r: r[1])
    last = len(order) - 1
    return {r[0]: i / last for i, r in enumerate(order)}


# --------------------------------------------------------------------------- walk


class Sim:
    """One autoplay simulator bound to the real library + the real preference state."""

    def __init__(self, now):
        self.now = now
        self.db = load_db()
        self.E = load_embeddings()
        rows = {r["video_id"]: r for r in self.db.execute(
            "SELECT video_id, title, artist, duration FROM tracks")}
        self.lib = set(rows)
        self.title = {v: (r["title"] or "") for v, r in rows.items()}
        self.id2artist = {v: (r["artist"] or "") for v, r in rows.items()}
        self.durations = {v: r["duration"] for v, r in rows.items()}
        self.artist_by_index = [self.id2artist.get(v, "") for v in self.E["ids"]]

        # --- real taste state, exactly as server.personalization() builds it
        plays = [(r["video_id"], r["ts"], r["event"], r["seconds"]) for r in self.db.execute(
            "SELECT video_id, ts, event, seconds FROM plays")]
        self.n_plays = len(plays)
        self.prefs = personalize.compute_prefs(
            plays, self.durations, self.id2artist, now=now)
        self.taste = personalize.build_centroid(self.E["X"], self.E["id2i"], self.prefs["track"])
        self.skip = personalize.build_centroid(
            self.E["X"], self.E["id2i"], {v: 1.0 for v in self.prefs["skip_ids"]})
        self.heard = {r[0]: r[1] for r in self.db.execute(
            "SELECT video_id, MAX(ts) FROM plays WHERE event IN ('play','complete') "
            "AND ts IS NOT NULL GROUP BY video_id")}
        self.cooc, self.radio_files = load_cooc(self.lib)
        self.energy = load_energy(self.db)
        self.n_tracks = len(self.lib)

    # -- retrieval: the current track's content neighbourhood (desktop path)
    def candidates(self, cur, exclude):
        E = self.E
        i = E["id2i"].get(cur)
        if i is None:
            return []
        sims = (E["X"] @ E["X"][i]).astype("float32")
        cand = []
        for j in np.argsort(-sims)[1:RETRIEVE_SCAN]:
            vid = E["ids"][int(j)]
            if vid in exclude or vid not in self.lib:
                continue
            cand.append(vid)
            if len(cand) >= RETRIEVE_KEEP:
                break
        return cand

    # -- session mechanics: identical to /api/next's tails
    def context(self, walk):
        cur = walk[-1]
        exclude = set(walk)
        mood_ids = [v for v in walk if v != cur][-11:] + [cur]     # last 12 incl. current
        recent_ids = mood_ids[-6:]                                 # fatigue window
        rvecs = [np.asarray(self.E["X"][self.E["id2i"][v]], dtype="float32")
                 for v in recent_ids if v in self.E["id2i"]]
        session_vec = personalize.build_centroid(
            self.E["X"], self.E["id2i"], {v: 1.0 for v in mood_ids})
        recent_artists = {self.id2artist.get(v, "") for v in recent_ids[-4:]}
        recent_artists.discard("")
        if self.id2artist.get(cur):
            recent_artists.add(self.id2artist[cur])
        return {
            "cur": cur, "exclude": exclude,
            "recent_vecs": np.stack(rvecs) if rvecs else None,
            "session_vec": session_vec, "recent_artists": recent_artists,
        }

    def rank(self, ctx, cand, new):
        """`new=False` -> the legacy call (opt-in args omitted, bitwise the old formula)."""
        extra = {"cooc_members": self.cooc, "last_played": self.heard,
                 "now": self.now, "energies": self.energy} if new else {}
        return personalize.rank_next(
            ctx["cur"], cand, self.E["X"], self.E["id2i"], self.E["ids"],
            self.artist_by_index,
            prefs=self.prefs, taste_vec=self.taste, skip_vec=self.skip,
            recent_artists=ctx["recent_artists"], recent_vecs=ctx["recent_vecs"],
            session_vec=ctx["session_vec"], explain=True, **extra)

    def meta(self, vid):
        return {"id": vid, "title": self.title.get(vid, vid),
                "artist": self.id2artist.get(vid, "")}

    def ago(self, vid):
        ts = self.heard.get(vid)
        if ts is None:
            return "never played"
        h = (self.now - ts) / 3600.0
        return f"played {h:.0f} h ago" if h < 48 else f"played {h / 24:.1f} days ago"

    def pool_stats(self, ranked, old_ranked):
        """What each new term did to the whole ~400-candidate window, not just the winner.
        `heard` is a PENALTY, so it almost never shows up on the track that wins — its
        visible work is demoting candidates, which the winner's breakdown cannot show.
        Records, per term: how many candidates it touched, the mean signed value, and the
        candidate it moved furthest (best old rank among those it touched, + its new rank)."""
        new_rank = {e[0]: i for i, e in enumerate(ranked)}
        old_rank = {e[0]: i for i, e in enumerate(old_ranked)}
        out = {}
        for t in NEW_TERMS:
            hit = [(vid, terms[t]) for vid, _s, terms in ranked if terms[t]]
            rec = {"n": len(hit), "mean": (sum(v for _, v in hit) / len(hit)) if hit else 0.0}
            if hit:
                vid = min((v for v, _ in hit), key=lambda v: old_rank[v])
                rec["top"] = dict(self.meta(vid), old_rank=old_rank[vid] + 1,
                                  new_rank=new_rank[vid] + 1,
                                  value=round(dict(hit)[vid], 4))
            out[t] = rec
        return out

    def walk(self, seed, new):
        """One deterministic 20-step walk (epsilon = 0: always rank 0)."""
        walk, steps = [seed], []
        for n in range(STEPS):
            ctx = self.context(walk)
            cand = self.candidates(ctx["cur"], ctx["exclude"])
            if not cand:
                break
            ranked = self.rank(ctx, cand, new)
            vid, score, terms = ranked[0]
            step = dict(self.meta(vid), n=n + 1, score=score,
                        terms={k: round(v, 5) for k, v in terms.items()},
                        from_id=ctx["cur"], n_cand=len(cand))
            if new:
                # what the OLD formula would have taken from this very same state, and
                # which single new term (if any) is load-bearing for the difference
                old_ranked = self.rank(ctx, cand, new=False)
                ov, oscore, _ot = old_ranked[0]
                step["old_here"] = dict(self.meta(ov), score=oscore)
                by_id = {e[0]: e for e in ranked}
                step["margin_new"] = score - by_id[ov][1]
                step["margin_old"] = ({e[0]: e[1] for e in old_ranked}[vid] - oscore)
                step["old_terms"] = {k: round(v, 5) for k, v in by_id[ov][2].items()}
                flipped = []
                for t in NEW_TERMS:
                    zeroed = max(ranked, key=lambda e, _t=t: e[1] - e[2][_t])
                    if zeroed[0] != vid:
                        flipped.append({"term": t, "instead": self.meta(zeroed[0])})
                step["flipped_by"] = flipped
                step["pool"] = self.pool_stats(ranked, old_ranked)
            steps.append(step)
            walk.append(vid)
        return steps


# --------------------------------------------------------------------------- prose


def flip_sentence(sim, win, lose, win_terms, lose_terms, margin_old, margin_new):
    """One line explaining a divergence, generated from the signed breakdown: every new
    term that moved in the winner's favour, biggest first, and how far it turned the old
    margin around. `lose` is the track the OLD formula takes from the same state, and
    `lose_terms` is its breakdown under the NEW formula, so the two are comparable."""
    clauses = []
    for t in sorted(NEW_TERMS, key=lambda k: lose_terms.get(k, 0.0) - win_terms.get(k, 0.0)):
        gain = win_terms.get(t, 0.0) - lose_terms.get(t, 0.0)
        if gain <= 0.005:
            continue
        if t == "cooc":
            clauses.append(
                f"cooc {win_terms['cooc']:+.2f} on “{win['title']}” (it shares a YT-Music "
                f"radio with the track playing; “{lose['title']}” does not)")
        elif t == "heard":
            clauses.append(
                f"heard {lose_terms['heard']:+.2f} on “{lose['title']}” "
                f"({sim.ago(lose['id'])}, so it is damped)")
        else:
            clauses.append(
                f"energy {lose_terms['energy']:+.2f} on “{lose['title']}” (outside the "
                f"energy band of the track playing)")
    if not clauses:
        # only reachable once the walks have separated and the windows no longer match
        return (f"the walks have already separated, so the candidate windows differ: "
                f"“{win['title']}” simply outscores everything in B's window "
                f"({win['score']:.3f}).")
    return (" and ".join(clauses) + f" — so “{win['title']}” takes the step instead: "
            f"an old margin of {margin_old:+.3f} became {margin_new:+.3f}.")


def build_payload(sim, now):
    seeds_out, totals = [], {"steps": 0, "diverged": 0}
    cooc_vals, heard_vals, energy_vals, cooc_fires = [], [], [], 0
    pool_all = {t: {"n": 0, "sum": 0.0, "steps": 0} for t in NEW_TERMS}
    parity = True
    for seed_id, why in SEEDS:
        a = sim.walk(seed_id, new=False)
        b = sim.walk(seed_id, new=True)
        n = min(len(a), len(b))
        div = [i for i in range(n) if a[i]["id"] != b[i]["id"]]
        # sanity: before the walks separate the two contexts are identical, so B's
        # "what OLD would take here" must be exactly A's pick.
        for i in range(div[0] if div else n):
            parity &= a[i]["id"] == b[i]["old_here"]["id"]
        first = None
        if div:
            i = div[0]
            first = {
                "step": i + 1,
                "text": flip_sentence(sim, b[i], b[i]["old_here"], b[i]["terms"],
                                      b[i]["old_terms"], b[i]["margin_old"],
                                      b[i]["margin_new"]),
                "flipped_by": [f["term"] for f in b[i]["flipped_by"]],
            }
        pool = {t: {"n": 0, "sum": 0.0, "steps": 0, "top": None} for t in NEW_TERMS}
        for s in b:
            if s["terms"]["cooc"]:
                cooc_fires += 1
                cooc_vals.append(s["terms"]["cooc"])
            if s["terms"]["heard"]:
                heard_vals.append(s["terms"]["heard"])
            if s["terms"]["energy"]:
                energy_vals.append(s["terms"]["energy"])
            for t, rec in s["pool"].items():
                if not rec["n"]:
                    continue
                pool[t]["n"] += rec["n"]
                pool[t]["sum"] += rec["mean"] * rec["n"]
                pool[t]["steps"] += 1
                drop = rec["top"]["new_rank"] - rec["top"]["old_rank"]
                best = pool[t]["top"]
                if best is None or abs(drop) > abs(best["new_rank"] - best["old_rank"]):
                    pool[t]["top"] = dict(rec["top"], step=s["n"])
                pool_all[t]["n"] += rec["n"]
                pool_all[t]["sum"] += rec["mean"] * rec["n"]
                pool_all[t]["steps"] += 1
        for t, rec in pool.items():
            rec["mean"] = rec["sum"] / rec["n"] if rec["n"] else 0.0
            rec["per_step"] = rec["n"] / n if n else 0.0
        totals["steps"] += n
        totals["diverged"] += len(div)
        seeds_out.append({
            "seed": dict(sim.meta(seed_id), why=why,
                         radio_members=len(sim.cooc.get(seed_id, ())),
                         energy=sim.energy.get(seed_id)),
            "old": a, "new": b, "diverged": div,
            "pct": 100.0 * len(div) / n if n else 0.0,
            "first_divergence": first,
            "pool": pool,
            "flips": {t: sum(1 for s in b if any(f["term"] == t for f in s["flipped_by"]))
                      for t in NEW_TERMS},
        })

    def mean(v):
        return sum(v) / len(v) if v else 0.0

    scale = max([abs(v) for s in seeds_out for w in ("old", "new")
                 for st in s[w] for v in st["terms"].values()] + [1.0])
    return {
        "generated": now,
        "generated_human": time.strftime("%Y-%m-%d %H:%M", time.localtime(now)),
        "steps": STEPS, "terms": TERMS, "new_terms": NEW_TERMS,
        "formula_old": FORMULA_OLD, "formula_new": FORMULA_NEW,
        "scale": scale,
        "library": {
            "tracks": sim.n_tracks, "plays": sim.n_plays,
            "radio_seeds": len(sim.cooc), "radio_files": sim.radio_files,
            "radio_members": sum(len(v) for v in sim.cooc.values()),
            "heard_tracks": len(sim.heard), "energy_tracks": len(sim.energy),
            "energy_pct": 100.0 * len(sim.energy) / max(1, sim.n_tracks),
        },
        "parity_ok": bool(parity),
        "stats": {
            "steps": totals["steps"], "diverged": totals["diverged"],
            "pct": 100.0 * totals["diverged"] / max(1, totals["steps"]),
            "cooc_fires": cooc_fires, "cooc_mean": mean(cooc_vals),
            "heard_n": len(heard_vals), "heard_mean": mean(heard_vals),
            "energy_n": len(energy_vals), "energy_mean": mean(energy_vals),
            "flips": {t: sum(s["flips"][t] for s in seeds_out) for t in NEW_TERMS},
            "pool": {t: {"n": v["n"], "steps": v["steps"],
                         "mean": (v["sum"] / v["n"]) if v["n"] else 0.0,
                         "per_step": v["n"] / max(1, totals["steps"])}
                     for t, v in pool_all.items()},
        },
        "seeds": seeds_out,
    }


# --------------------------------------------------------------------------- html

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Autoplay A/B — old vs new scoring</title>
<style>
:root{--paper:#f4f4f0;--ink:#141414;--ikb:#002fa7;--red:#e0301e;--rule:#141414;
      --display:"Archivo Black","Helvetica Neue Black","Arial Black",Helvetica,Arial,sans-serif;
      --body:system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
      --mono:ui-monospace,"Cascadia Mono","Consolas",monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 var(--body);
     -webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px 80px}
h1,h2,h3,.disp{font-family:var(--display);font-weight:900;letter-spacing:-.02em;
     text-transform:uppercase;margin:0}
header{border-bottom:4px solid var(--rule);padding:26px 0 14px;margin-bottom:0}
h1{font-size:clamp(34px,7vw,74px);line-height:.92}
h1 em{font-style:normal;color:var(--ikb)}
.kicker{font:12px/1 var(--mono);text-transform:uppercase;letter-spacing:.14em;
     color:var(--ikb);margin-bottom:10px}
.sub{max-width:62ch;margin:12px 0 18px;font-size:15px}
.formulas{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:0;
     border-top:1px solid var(--rule)}
.formulas div{padding:12px 16px 12px 0;border-right:1px solid var(--rule)}
.formulas div:last-child{border-right:0;padding-left:16px}
.formulas b{font-family:var(--display);font-size:13px;letter-spacing:.02em;display:block;
     text-transform:uppercase}
.formulas code{font:12px/1.5 var(--mono);word-break:break-word}
.side-b b{color:var(--ikb)}
.figs{display:flex;flex-wrap:wrap;border-top:1px solid var(--rule);
     border-bottom:4px solid var(--rule);margin-bottom:34px}
.fig{flex:1 1 150px;padding:12px 16px 12px 0;border-right:1px solid var(--rule)}
.fig:last-child{border-right:0}
.fig .n{font-family:var(--display);font-size:30px;line-height:1;display:block}
.fig .l{font:11px/1.35 var(--mono);text-transform:uppercase;letter-spacing:.08em;
     color:#555;margin-top:6px;display:block}
.fig.blue .n{color:var(--ikb)}
.note{font-size:13px;border-left:4px solid var(--red);padding:8px 0 8px 12px;margin:0 0 30px}
section.seed{margin:0 0 54px}
.seedhead{border-top:4px solid var(--rule);padding-top:10px}
.seedno{font:12px/1 var(--mono);letter-spacing:.14em;color:var(--ikb);text-transform:uppercase}
.seedhead h2{font-size:clamp(24px,4.4vw,44px);line-height:1;margin:6px 0 4px}
.seedhead .by{font-size:14px}
.seedhead .why{font-size:13px;color:#555;margin-top:4px}
.seedmeta{font:11px/1.6 var(--mono);text-transform:uppercase;letter-spacing:.06em;
     color:#555;margin-top:6px}
.callout{border:2px solid var(--ikb);padding:10px 13px;margin:16px 0 0;font-size:14px}
.callout b{font-family:var(--display);text-transform:uppercase;font-size:12px;
     letter-spacing:.05em;color:var(--ikb);display:block;margin-bottom:3px}
.tapewrap{overflow-x:auto;margin-top:20px}
.tape{min-width:760px}
.colhead{display:grid;grid-template-columns:1fr 46px 1fr;border-bottom:2px solid var(--rule);
     position:sticky;top:0;background:var(--paper);z-index:2}
.colhead div{font-family:var(--display);font-size:13px;text-transform:uppercase;padding:6px 8px}
.colhead .b{color:var(--ikb);text-align:right}
.colhead .mid{text-align:center;font:10px/1 var(--mono);padding-top:10px;color:#777}
.row{display:grid;grid-template-columns:1fr 46px 1fr;border-bottom:1px solid #d6d6d0}
.row.flip{border-bottom:1px solid var(--rule);background:#ecebe3}
.row.flip .idx{background:var(--ink);color:#fff;font-weight:700}
.row.first .idx{background:var(--ikb);color:#fff;font-weight:700}
.row.drift .idx{color:var(--red)}
.marks{display:flex;gap:18px;flex-wrap:wrap;font:10px/1.6 var(--mono);text-transform:uppercase;
     letter-spacing:.06em;color:#666;padding:6px 0 0}
.marks i{font-style:normal;display:inline-block;width:16px;height:14px;line-height:14px;
     text-align:center;margin-right:5px;vertical-align:-2px}
.marks i.k{background:var(--ink);color:#fff}
.marks i.f{background:var(--ikb);color:#fff}
.marks i.d{color:var(--red);border:1px solid #d6d6d0}
.cell{padding:9px 10px;min-width:0}
.cell.r{text-align:right}
.ti{font-weight:600;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ar{font-size:12px;color:#555;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sc{font:11px/1.4 var(--mono);color:#777}
.idx{display:flex;align-items:center;justify-content:center;font:12px/1 var(--mono);
     color:#888;border-left:1px solid #d6d6d0;border-right:1px solid #d6d6d0}
.row.div .idx{background:var(--ink);color:#fff;font-weight:700}
.strip{margin-top:7px;width:132px}
.cell.r .strip{margin-left:auto}
.bar{position:relative;height:3px;margin-bottom:1px;background:#dcdcd4}
.bar i{position:absolute;top:0;bottom:0;display:block}
.bar i.p{left:50%;background:var(--ikb)}
.bar i.n{right:50%;background:var(--red)}
.bar.newterm{background:#cfcfc6}
.bar::after{content:"";position:absolute;left:50%;top:-1px;bottom:-1px;width:1px;
     background:rgba(20,20,20,.28)}
.pv{font:11px/1 var(--mono);border:1px solid var(--ink);background:transparent;
     color:var(--ink);padding:3px 6px;cursor:pointer;margin-top:6px}
.pv:hover{background:var(--ink);color:var(--paper)}
.pv.dead{opacity:.25;cursor:default}
body.noserver .pv{display:none}
.flag{font:10px/1.4 var(--mono);text-transform:uppercase;letter-spacing:.06em;
     color:var(--red);margin-top:5px}
.alt{font:10px/1.4 var(--mono);letter-spacing:.04em;color:#777;margin-top:4px}
.legend{display:flex;gap:26px;flex-wrap:wrap;border-top:1px solid var(--rule);
     border-bottom:4px solid var(--rule);padding:14px 0;margin:0 0 30px;font-size:12px}
.legend ol{margin:0;padding:0;list-style:none;columns:2;font:11px/1.42 var(--mono);
     text-transform:uppercase;letter-spacing:.04em}
.legend ol li.nw{color:var(--ikb);font-weight:700}
.legend .key{max-width:34ch;font-size:12px;color:#444}
footer{border-top:1px solid var(--rule);padding-top:12px;font:11px/1.7 var(--mono);color:#666}
@media(max-width:700px){.formulas div{border-right:0;border-bottom:1px solid var(--rule)}
  .formulas div:last-child{padding-left:0;border-bottom:0}}
@media(max-width:640px){.tape{min-width:680px}.strip{width:104px}}
</style>
<div class="wrap">
<header>
  <div class="kicker">offline music player · autoplay · a/b</div>
  <h1>The queue,<br>scored <em>twice</em></h1>
  <p class="sub">__SUB__</p>
  <div class="formulas">
    <div><b>A — old (live until today)</b><code>__FOLD__</code></div>
    <div class="side-b"><b>B — new</b><code>__FNEW__</code></div>
  </div>
</header>
<div class="figs" id="figs"></div>
<div class="note" id="note"></div>
<div class="legend">
  <div><b class="disp" style="font-size:12px">Bar strip — term order</b><ol id="legend"></ol></div>
  <div class="key">Twelve stacked bars per pick, one per scoring term, in the order listed.
    Right of the hairline axis = the term pushed this track up (International Klein Blue);
    left = it pushed the track down (signal red). Bar length is proportional across the
    whole page. Hover any bar for its signed value. The last three are the new terms.</div>
</div>
<div id="seeds"></div>
<footer id="foot"></footer>
</div>
<script>
const D = __DATA__;
const esc = s => { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; };
const NEW = new Set(D.new_terms);

function strip(terms){
  return '<div class="strip">' + D.terms.map(k => {
    const v = terms[k] || 0, w = Math.min(100, Math.abs(v) / D.scale * 100);
    const cls = 'bar' + (NEW.has(k) ? ' newterm' : '');
    const inner = w < 0.4 ? '' :
      `<i class="${v >= 0 ? 'p' : 'n'}" style="width:${(w / 2).toFixed(2)}%"></i>`;
    return `<div class="${cls}" title="${k} ${v >= 0 ? '+' : ''}${v.toFixed(3)}">${inner}</div>`;
  }).join('') + '</div>';
}

// per-seed line: what each new term did across the whole candidate window, since a
// penalty term does its work by demoting tracks that never reach the winner's strip
function NEWLINE_POOL(s){
  return D.new_terms.map(t => {
    const p = s.pool[t];
    if(!p.n) return `<b style="color:#999">${t} never fired</b>`;
    let out = `<b>${t}</b> ${p.per_step.toFixed(1)}/step, mean ${p.mean >= 0 ? '+' : ''}${p.mean.toFixed(2)}`;
    if(p.top && p.top.new_rank !== p.top.old_rank)
      out += ` (biggest move: “${esc(p.top.title)}” rank ${p.top.old_rank}→${p.top.new_rank} at step ${p.top.step})`;
    return out;
  }).join(' &nbsp;·&nbsp; ');
}

function cell(st, side, diverged){
  if(!st) return '<div class="cell"></div>';
  let flag = '', alt = '';
  if(side === 'new'){
    if(st.flipped_by && st.flipped_by.length)
      flag = st.flipped_by.map(f => `zero ${f.term} → “${f.instead.title}”`).join(' · ');
    if(st.old_here && st.old_here.id !== st.id){
      // the runner-up here under A's scoring, with the new terms that cost it the step
      const bits = D.new_terms.filter(t => st.old_terms[t])
        .map(t => `${t} ${st.old_terms[t] >= 0 ? '+' : ''}${st.old_terms[t].toFixed(2)}`);
      alt = `old formula here: “${st.old_here.title}” (${st.old_here.score.toFixed(3)}`
            + (bits.length ? '; ' + bits.join(', ') : '') + ')';
    } else if(diverged){
      alt = 'new terms changed nothing here — drift from an earlier flip';
    }
  }
  return `<div class="cell ${side === 'new' ? 'r' : ''}">
    <div class="ti" title="${esc(st.title)}">${esc(st.title)}</div>
    <div class="ar">${esc(st.artist)}</div>
    <div class="sc">${st.score.toFixed(3)}</div>
    ${strip(st.terms)}
    ${flag ? `<div class="flag">${esc(flag)}</div>` : ''}
    ${alt ? `<div class="alt">${esc(alt)}</div>` : ''}
    <button class="pv" onclick="pv(this,'${st.id}')">▶ play</button>
  </div>`;
}

const f2 = (v, d) => v ? (v >= 0 ? '+' : '') + v.toFixed(d == null ? 2 : d) : '—';
document.getElementById('figs').innerHTML = [
  [D.stats.pct.toFixed(0) + '%', 'steps that diverged (' + D.stats.diverged + '/' + D.stats.steps + ')', 1],
  [D.stats.flips.cooc, 'steps where zeroing cooc alone changes the winner', 1],
  [D.stats.cooc_fires + ' / ' + D.stats.steps, 'B-picks carrying cooc, mean ' + f2(D.stats.cooc_mean), 0],
  [D.stats.pool.heard.n, 'candidates damped by heard across the run, mean ' + f2(D.stats.pool.heard.mean), 0],
  [D.stats.pool.energy.n, 'candidates penalised by energy across the run, mean ' + f2(D.stats.pool.energy.mean), 0],
  [D.library.plays, 'real play events behind the taste state', 0],
].map(([n, l, blue]) =>
  `<div class="fig ${blue ? 'blue' : ''}"><span class="n">${n}</span><span class="l">${esc(l)}</span></div>`).join('');

document.getElementById('legend').innerHTML = D.terms.map((t, i) =>
  `<li class="${NEW.has(t) ? 'nw' : ''}">${i + 1}. ${t}</li>`).join('');

document.getElementById('seeds').innerHTML = D.seeds.map((s, si) => {
  const n = Math.max(s.old.length, s.new.length);
  const dv = new Set(s.diverged);
  const rows = [];
  const firstStep = s.first_divergence ? s.first_divergence.step : -1;
  for(let i = 0; i < n; i++){
    const d = dv.has(i);
    // a new term actually decided this step (bold) vs the tapes merely being elsewhere
    // after an earlier flip (drift) — with 90%+ divergence one marker for both is noise
    const flip = s.new[i] && s.new[i].flipped_by && s.new[i].flipped_by.length;
    const cls = (i + 1 === firstStep ? 'first ' : '') + (flip ? 'flip' : (d ? 'drift' : ''));
    rows.push(`<div class="row ${cls}">
      ${cell(s.old[i], 'old', d)}
      <div class="idx">${i + 1}</div>
      ${cell(s.new[i], 'new', d)}</div>`);
  }
  return `<section class="seed">
    <div class="seedhead">
      <div class="seedno">seed ${String(si + 1).padStart(2, '0')}</div>
      <h2>${esc(s.seed.title)}</h2>
      <div class="by">${esc(s.seed.artist)}</div>
      <div class="why">${esc(s.seed.why)}</div>
      <div class="seedmeta">${s.pct.toFixed(0)}% of steps diverged ·
        ${s.diverged.length}/${Math.min(s.old.length, s.new.length)} ·
        radio members in library: ${s.seed.radio_members} ·
        seed energy: ${s.seed.energy == null ? 'none' : s.seed.energy.toFixed(2)} ·
        winner flipped by cooc ${s.flips.cooc}× / heard ${s.flips.heard}× / energy ${s.flips.energy}×</div>
      <div class="seedmeta">in the candidate window: ${NEWLINE_POOL(s)}</div>
      ${s.first_divergence ? `<div class="callout"><b>first divergence — step ${s.first_divergence.step}</b>${esc(s.first_divergence.text)}</div>` : '<div class="callout"><b>no divergence</b>Both formulas produced the same 20 tracks in the same order.</div>'}
    </div>
    <div class="marks">
      <span><i class="f">${firstStep > 0 ? firstStep : '·'}</i>first divergence</span>
      <span><i class="k">n</i>a new term decided this step</span>
      <span><i class="d">n</i>tapes are elsewhere after an earlier flip</span>
      <span><i style="border:1px solid #d6d6d0">n</i>both formulas agree</span>
    </div>
    <div class="tapewrap"><div class="tape">
      <div class="colhead"><div>A — old</div><div class="mid">step</div><div class="b">B — new</div></div>
      ${rows.join('')}
    </div></div>
  </section>`;
}).join('');

document.getElementById('note').innerHTML =
  `Energy coverage at run time: <b>${D.library.energy_tracks}</b> of ${D.library.tracks} tracks
   (${D.library.energy_pct.toFixed(1)}%) have an <code>analysis.energy_db</code> row, and the
   energy term needs BOTH the current track and the candidate to have one — so it is close to
   dormant here and will get louder as the analysis sweep fills in. Co-occurrence:
   ${D.library.radio_seeds} usable radio seeds / ${D.library.radio_members} in-library members.
   Already-heard: ${D.library.heard_tracks} tracks carry a last-played stamp.`;

document.getElementById('foot').textContent =
  `generated ${D.generated_human} · now=${D.generated.toFixed(0)} · ${D.steps} steps per walk · ` +
  `epsilon=0 (always rank 0) · retrieval: top-800 sims, first 400 eligible · ` +
  `rebuild: .venv\\Scripts\\python scripts\\demo_autoplay_ab.py`;

// --- audio preview through the local player server (same trick as purge_review.html):
// probe once; if the server is not up, the buttons simply disappear.
fetch('http://127.0.0.1:5000/api/stats', {mode: 'no-cors'})
  .catch(() => document.body.classList.add('noserver'));
let cur = null;
function pv(btn, id){
  if(cur){ cur.pause(); cur.remove(); cur = null; }
  cur = document.createElement('audio');
  cur.controls = true; cur.autoplay = true;
  cur.style.cssText = 'display:block;height:26px;max-width:220px;margin-top:6px';
  cur.src = 'http://127.0.0.1:5000/audio/' + id;
  cur.onerror = () => { btn.classList.add('dead'); cur.remove(); };
  btn.after(cur);
}
</script>
"""


def render(payload):
    sub = (f"One seed, two twenty-step autoplay walks. Left is the formula that has been "
           f"live until today; right adds the three opt-in terms — radio co-occurrence, "
           f"already-heard damping and energy continuity. Everything else is held equal: "
           f"the same {payload['library']['tracks']:,} tracks, the same real preference state "
           f"built from {payload['library']['plays']} logged play events, the same session "
           f"mechanics (mood centroid over the last 12, fatigue over the last 6, artist "
           f"cooldown over the last 4), and no exploration (ε = 0, always rank 0), so a "
           f"rerun reproduces this page exactly.")
    page = (PAGE.replace("__SUB__", sub)
                .replace("__FOLD__", html.escape(payload["formula_old"]))
                .replace("__FNEW__", html.escape(payload["formula_new"]))
                .replace("__DATA__", json.dumps(payload, ensure_ascii=False)))
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(page, encoding="utf-8")
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def p(s):
    """Console print that survives a cp1252 terminal."""
    print(str(s).encode(sys.stdout.encoding or "utf-8", "replace")
          .decode(sys.stdout.encoding or "utf-8", "replace"))


def main():
    now = time.time()          # stamped ONCE and reused everywhere -> reproducible
    t0 = now
    sim = Sim(now)
    p(f"[data] {sim.n_tracks} tracks | {sim.n_plays} plays | "
      f"{len(sim.cooc)}/{sim.radio_files} radio seeds usable "
      f"({sum(len(v) for v in sim.cooc.values())} in-library members) | "
      f"{len(sim.heard)} heard-stamped | {len(sim.energy)} energy percentiles "
      f"({100.0 * len(sim.energy) / max(1, sim.n_tracks):.2f}% of library)")
    missing = [s for s, _ in SEEDS if s not in sim.lib or s not in sim.E["id2i"]]
    if missing:
        raise SystemExit(f"seed(s) not in library/embeddings: {missing}")

    payload = build_payload(sim, now)
    render(payload)

    p(f"[parity] pre-divergence steps agree with the legacy walk: "
      f"{'PASS' if payload['parity_ok'] else 'FAIL'}")
    for s in payload["seeds"]:
        p(f"\n== {s['seed']['title']} — {s['seed']['artist']} "
          f"({s['seed']['radio_members']} radio members)")
        p(f"   diverged {len(s['diverged'])}/{min(len(s['old']), len(s['new']))} "
          f"= {s['pct']:.0f}%  | winner flips: "
          + ", ".join(f"{t} {s['flips'][t]}x" for t in NEW_TERMS))
        p("   pool: " + " | ".join(
            f"{t} {s['pool'][t]['per_step']:.1f}/step (mean {s['pool'][t]['mean']:+.2f})"
            if s['pool'][t]['n'] else f"{t} never fired" for t in NEW_TERMS))
        if s["first_divergence"]:
            p(f"   first@{s['first_divergence']['step']}: {s['first_divergence']['text']}")
        for i in s["diverged"][:4]:
            p(f"   step {i + 1}: OLD {s['old'][i]['title'][:44]!r} -> "
              f"NEW {s['new'][i]['title'][:44]!r}"
              + (f"  [flipped by {', '.join(f['term'] for f in s['new'][i]['flipped_by'])}]"
                 if s["new"][i]["flipped_by"] else ""))
    st = payload["stats"]
    p(f"\n[totals] {st['diverged']}/{st['steps']} steps diverged ({st['pct']:.0f}%) | "
      f"cooc fired on {st['cooc_fires']} B-picks (mean {st['cooc_mean']:+.3f}) | "
      f"winner flips: " + ", ".join(f"{t} {st['flips'][t]}x" for t in NEW_TERMS))
    p("[pool]   " + " | ".join(
        f"{t}: {v['n']} candidate hits over {v['steps']} steps "
        f"({v['per_step']:.1f}/step, mean {v['mean']:+.3f})" if v['n'] else f"{t}: never fired"
        for t, v in st["pool"].items()))
    p(f"[out] {OUT_HTML}  ({OUT_HTML.stat().st_size / 1024:.0f} KB)")
    p(f"[out] {OUT_JSON}  ({OUT_JSON.stat().st_size / 1024:.0f} KB)")
    p(f"[time] {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
