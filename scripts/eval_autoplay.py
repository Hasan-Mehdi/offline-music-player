#!/usr/bin/env python3
"""Measure the autoplay engine instead of eyeballing it. Three modes:

  sim     Chain real /api/next decisions (server.next_decision, in-process, nothing is
          logged) from fixed seeds under one or more scoring configs and report what the
          walk does — how close each step is, how fast it drifts, how often it repeats a
          channel, tempo/energy continuity — and, per scoring term, how often removing
          that term would have changed the pick ("say"). The say table is how the
          v2 problem was found: tempo/taste/skip each out-voted audio similarity.
            python scripts/eval_autoplay.py sim [--seeds 30 --steps 25 --configs v2,v3]

  replay  Join the decision trace (data/next_trace.jsonl) to what happened next in the
          plays log: per pick reason (exploit / explore_*), how often it was skipped vs
          finished, and the mean of each scoring term for kept vs skipped picks. This is
          the evidence any future re-weighting should come from.
            python scripts/eval_autoplay.py replay

  taste   Temporal holdout of the taste model on the YouTube Music history archived by
          merge_takeout.py: build the taste vector from listens before --cut, rank the
          library, and score how well it finds the tracks first heard after --cut.
            python scripts/eval_autoplay.py taste --cut 2026-07-26
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import personalize  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Named scoring configs for `sim`. v2 = the live engine before the 2026-10 audit (raw
# embeddings, absolute weights); v3 = server.AUTOPLAY_PARAMS as it stands.
V2 = {"center": False, "params": {"same_w": 1.5, "same_floor": 0.85, "rho_floor": 0.76}}
SOUND = personalize.SOUND_TERMS                  # the "does it sound right next" terms
V2_EXPLORE = {"sound_budget": None, "prior_n": None}


def configs(names, server):
    """v2 | v3 | v3:key=val:key=val (v3 with overrides, for trying weights; explore_*
    keys set server.EXPLORE instead, e.g. v3:explore_sound_budget=none)."""
    out = {}
    for n in names:
        base, *over = n.split(":")
        if base == "v2":
            cfg = {"center": False, "params": dict(V2["params"]), "explore": dict(V2_EXPLORE)}
        elif base == "v3":
            cfg = {"center": True, "params": dict(server.AUTOPLAY_PARAMS),
                   "explore": dict(server.EXPLORE)}
        else:
            raise SystemExit(f"unknown config {n!r} (v2, v3, v3:key=val...)")
        for kv in over:
            k, v = kv.split("=")
            if k.startswith("explore_"):
                cfg["explore"][k[len("explore_"):]] = None if v == "none" else float(v)
            else:
                cfg["params"][k] = float(v)
        out[n] = cfg
    return out


def _use_space(server, center):
    """Point the server at raw or centered embeddings; everything built in the other
    space (taste/skip vectors, metadata alignment) is invalidated with it."""
    if server._EMB is not None and server.EMB_CENTER == center:
        return
    server.EMB_CENTER = center
    server._EMB = None
    server._META = None
    server._PREF["stamp"] = None


def _fold(a, b):
    r = math.log2(a / b)
    return min(abs(r - 1.0), abs(r), abs(r + 1.0))


def sim(args):
    import server
    raw = np.load(ROOT / "data" / "muq_embeddings.npz", allow_pickle=False)
    R = raw["embeddings"].astype("float32")
    R /= np.linalg.norm(R, axis=1, keepdims=True) + 1e-9
    rid = {str(v): i for i, v in enumerate(raw["ids"])}
    with server.app.app_context():
        con = server.db()
        genre = {r[0]: (r[1] or "") for r in con.execute("SELECT video_id, genre FROM tracks")}
        lib = sorted(server.lib_ids() & set(rid))
        energy = server._energy_ranks()
        bpm = server._bpm_map()
        pool = lib
        if args.seeds_from == "history":      # tracks you actually listen to on YT Music
            hist = set(server.listen_history()[1])
            pool = [v for v in lib if v in hist]
        seeds = random.Random(args.seed).sample(pool, args.seeds)
        cfgs = configs(args.configs.split(","), server)
        live_explore = server.EXPLORE
        for name, cfg in cfgs.items():
            _use_space(server, cfg["center"])
            server.EXPLORE = cfg["explore"]
            say, std = Counter(), defaultdict(list)
            steps = 0
            cons, clones, drift10, drift20, arts, gen, de, tempo = [], 0, [], [], [], [], [], []
            skip_away, deficit = [], []
            reasons, exp_def, exp_clu = Counter(), [], []
            cl = server.clusters()
            t0 = time.time()
            for k, seed in enumerate(seeds):
                rng = random.Random(1000 + k)
                walk = [seed]
                for step in range(args.steps):
                    outcome = "complete"
                    if args.skip_every and step and step % args.skip_every == 0:
                        outcome = "skip"          # reject the track we just landed on
                    d = server.next_decision(walk[-1], walk[:-1][-50:], outcome=outcome,
                                             secs=2.0 if outcome == "skip" else None,
                                             params=cfg["params"], rng=rng, trace=False)
                    pick = d["pick"]
                    if not pick:
                        break
                    if outcome == "skip" and d["anchor"] != walk[-1]:
                        a, s = rid.get(d["anchor"]), rid.get(walk[-1])
                        p = rid.get(pick)
                        if None not in (a, s, p):
                            skip_away.append(float(R[p] @ R[a]) - float(R[p] @ R[s]))
                    ranked = d["ranked"]
                    if ranked:
                        T = np.array([list(t.values()) for _, _, t in ranked])
                        keys = list(ranked[0][2])
                        tot = T.sum(1)
                        top = int(np.argmax(tot))
                        for i, key in enumerate(keys):
                            std[key].append(float(T[:, i].std()))
                            if int(np.argmax(tot - T[:, i])) != top:
                                say[key] += 1
                        # how much "sounds like the last track" the pick gave up for
                        # everything else, in standard deviations of that sound score
                        snd = sum(T[:, keys.index(k)] for k in SOUND if k in keys)
                        pick_i = next(i for i, e in enumerate(ranked) if e[0] == pick)
                        deficit.append(float((snd.max() - snd[pick_i]) / (snd.std() + 1e-9)))
                        steps += 1
                        reasons[d["info"]["reason"]] += 1
                        if d["info"]["explored"]:
                            exp_def.append(deficit[-1])
                            exp_clu.append(cl.get(pick) != cl.get(walk[-1]))
                    prev = walk[-1]
                    walk.append(pick)
                    if prev in rid and pick in rid:
                        c = float(R[rid[prev]] @ R[rid[pick]])
                        cons.append(c)
                        clones += c >= 0.92
                    if genre.get(prev) and genre.get(pick):
                        gen.append(genre[prev] == genre[pick])
                    if prev in energy and pick in energy:
                        de.append(abs(energy[prev] - energy[pick]))
                    if bpm.get(prev) and bpm.get(pick):
                        tempo.append(_fold(bpm[pick], bpm[prev]) <= math.log2(1.05))
                if len(walk) > 10 and walk[10] in rid:
                    drift10.append(float(R[rid[seed]] @ R[rid[walk[10]]]))
                if len(walk) > 20 and walk[20] in rid:
                    drift20.append(float(R[rid[seed]] @ R[rid[walk[20]]]))
                meta = server.track_meta()["id2artist"]
                w20 = walk[1:21]
                arts.append(len({meta.get(v, v) for v in w20}) / max(1, len(w20)))
            n = max(1, len(cons))
            print(f"\n== {name}  ({len(seeds)} seeds x {args.steps} steps, {time.time() - t0:.0f}s)")
            print(f"  step similarity (raw cos)   mean {np.mean(cons):.3f}  p10 {np.percentile(cons, 10):.3f}"
                  f"  p90 {np.percentile(cons, 90):.3f}   clones (>=0.92) {100 * clones / n:.1f}%")
            print(f"  drift from seed (raw cos)   @10 {np.mean(drift10):.3f}   @20 {np.mean(drift20):.3f}")
            print(f"  distinct channels / 20      {np.mean(arts):.2f}")
            print(f"  same genre step-to-step     {100 * np.mean(gen):.0f}%    "
                  f"tempo match (<=5%) {100 * np.mean(tempo):.0f}%    mean |d energy| {np.mean(de):.3f}")
            if skip_away:
                print(f"  after a skip: next pick is closer to the anchor than to the skipped "
                      f"track in {100 * np.mean(np.array(skip_away) > 0):.0f}% of {len(skip_away)}")
            print(f"  sound given up by the pick  median {np.median(deficit):.2f} sd   "
                  f"p90 {np.percentile(deficit, 90):.2f} sd   (0 = the best-sounding continuation)")
            if exp_def:
                print(f"  exploration picks           {len(exp_def)} ({100 * len(exp_def) / max(1, steps):.0f}%)"
                      f"   sound given up median {np.median(exp_def):.2f} / p90 "
                      f"{np.percentile(exp_def, 90):.2f} sd   >0.75 sd {100 * np.mean(np.array(exp_def) > 0.75):.1f}%"
                      f"   other cluster {100 * np.mean(exp_clu):.0f}%")
            print("  pick reasons                " + "  ".join(f"{k} {v}" for k, v in reasons.most_common()))
            print("  term say (pick changes without it) / median spread:")
            for key in sorted(std, key=lambda k: -say[k]):
                print(f"    {key:12s} {100 * say[key] / max(1, steps):5.1f}%   {np.median(std[key]):.4f}")
        server.EXPLORE = live_explore


def replay(args):
    path = ROOT / "data" / "next_trace.jsonl"
    recs = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    con = sqlite3.connect(f"file:{ROOT / 'data' / 'library.db'}?mode=ro", uri=True)
    dur = {r[0]: r[1] for r in con.execute("SELECT video_id, duration FROM tracks")}
    by = defaultdict(list)
    for r in con.execute("SELECT video_id, ts, event, seconds, source FROM plays "
                         "WHERE event IN ('skip','complete','like','dislike','trash','switch') "
                         "ORDER BY ts"):
        by[r[0]].append(r[1:])
    stats = defaultdict(Counter)
    terms = defaultdict(lambda: defaultdict(list))
    for rec in recs:
        pick = rec["pick"]["id"]
        ts = rec["ts"]
        ev = next(((e, s, src) for t, e, s, src in by.get(pick, ()) if ts <= t <= ts + 7200), None)
        if ev is None:
            verdict = "no outcome"
        elif ev[0] in ("complete", "like"):
            verdict = "kept"
        elif ev[0] == "switch" or personalize.is_browse_skip(ev[0], ev[1], ev[2]):
            verdict = "navigated away"
        elif ev[0] == "skip":
            comp = personalize._completion(ev[1], dur.get(pick))
            verdict = "kept" if (comp is not None and comp > personalize.LATE_OK) else "skipped"
        else:
            verdict = "skipped"
        stats[rec["pick"]["reason"]][verdict] += 1
        top = {t["id"]: t["terms"] for t in rec.get("top", [])}
        if pick in top and verdict in ("kept", "skipped"):
            for k, v in top[pick].items():
                terms[k][verdict].append(v)
    print(f"{len(recs)} traced decisions ({path.name})")
    for reason, c in sorted(stats.items()):
        print(f"  {reason:16s} " + "  ".join(f"{k} {v}" for k, v in c.most_common()))
    if terms:
        print("  mean term value of the pick, kept vs skipped:")
        for k, d in terms.items():
            kept, sk = d.get("kept", []), d.get("skipped", [])
            print(f"    {k:12s} kept {np.mean(kept) if kept else float('nan'):+.4f} (n={len(kept)})"
                  f"   skipped {np.mean(sk) if sk else float('nan'):+.4f} (n={len(sk)})")
    if len(recs) < 500:
        print("  (too few decisions to re-weight from yet — keep listening)")


def taste(args):
    import merge_takeout as M
    cut = datetime.fromisoformat(args.cut).replace(tzinfo=timezone.utc)
    d = np.load(ROOT / "data" / "muq_embeddings.npz", allow_pickle=False)
    X = d["embeddings"].astype("float32")
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    ids = [str(x) for x in d["ids"]]
    id2i = {v: i for i, v in enumerate(ids)}
    con = sqlite3.connect(f"file:{ROOT / 'data' / 'library.db'}?mode=ro", uri=True)
    lib_set = {r[0] for r in con.execute("SELECT video_id FROM tracks")}
    seen, ev = set(), defaultdict(list)
    for p in sorted(M.EXPORTS.glob("*watch-history.json")):
        for vid, raw, t, _e in M.music_events(M.read_export(p)):
            if (vid, raw) not in seen:
                seen.add((vid, raw))
                ev[vid].append(t)
    train = {v: [t for t in ts if t < cut] for v, ts in ev.items()}
    train = {v: ts for v, ts in train.items() if ts and v in id2i}
    test = {v for v, ts in ev.items() if min(ts) >= cut and v in id2i and v in lib_set}
    mask = np.array([v in lib_set for v in ids])
    for v in train:
        mask[id2i[v]] = False
    cand = np.where(mask)[0]
    is_te = np.isin(cand, [id2i[v] for v in test])
    if not is_te.any():
        raise SystemExit("no held-out tracks after --cut that are in the library")
    rows = [{"video_id": v, "play_count": len(ts), "last_played": max(ts).date().isoformat()}
            for v, ts in train.items()]
    w = personalize.history_weights(rows, cut.timestamp())
    print(f"train: {len(train)} tracks heard before {args.cut}; test: {int(is_te.sum())} library "
          f"tracks first heard after it (of {len(cand)} candidates)")

    def score(name, s):
        o = np.argsort(-s[cand])
        hit = is_te[o]
        r = np.where(hit)[0]
        print(f"  {name:28s} AUC {1 - r.mean() / len(cand):.3f}   recall@1000 "
              f"{hit[:1000].sum() / hit.sum():.3f}   recall@5000 {hit[:5000].sum() / hit.sum():.3f}")

    score("random", np.random.default_rng(0).random(len(X)))
    for tag, Z in (("raw", X), ("centered", personalize.center_embeddings(X.copy())[0])):
        c = personalize.build_centroid(Z, id2i, w)
        score(f"history centroid, {tag}", Z @ c)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("sim")
    s.add_argument("--seeds", type=int, default=30)
    s.add_argument("--steps", type=int, default=25)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--configs", default="v2,v3")
    s.add_argument("--seeds-from", choices=("library", "history"), default="history",
                   help="start walks from random library tracks or from your listening history")
    s.add_argument("--skip-every", type=int, default=0,
                   help="simulate an early skip of every Nth pick (tests the skip steering)")
    sub.add_parser("replay")
    t = sub.add_parser("taste")
    t.add_argument("--cut", default="2026-07-26")
    args = ap.parse_args(argv)
    {"sim": sim, "replay": replay, "taste": taste}[args.mode](args)


if __name__ == "__main__":
    main()
