#!/usr/bin/env python3
"""Measure how much of each game franchise autoplay serves on its own, for autoplay's
franchise bias (scripts/franchise.py, personalize.rank_next fr_bias).

Walks --steps from --seeds tracks of your YouTube Music history with the live engine but
the franchise terms OFF (server.next_decision, in-process, nothing logged) and counts,
per franchise, the share of picks that land in it from a seed of ANOTHER franchise --
what turns up in sessions that weren't about it. Writes data/franchise_exposure.json;
server.franchises() then sets each franchise's bias from your listening share against
this (not the library share, which mis-predicts the engine: measured 2026-10-11, Sonic
got 2.0x its library share, Zelda 1.1x). Rerun after the library changes a lot.

    python scripts/franchise_calibrate.py [--seeds 120 --steps 10]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import franchise  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "franchise_exposure.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=120)
    ap.add_argument("--steps", type=int, default=10)
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args(argv)
    import server
    t0 = time.time()
    with server.app.app_context():
        of = {r[0]: franchise.franchise_of(r[1], r[2], r[3]) for r in server.db().execute(
            "SELECT video_id, title, artist, album FROM tracks")}
        lib = server.lib_ids()
        hist = sorted(v for v in set(server.listen_history()[1]) if v in lib)
        seeds = random.Random(args.seed).sample(hist, min(args.seeds, len(hist)))
        params = dict(server.AUTOPLAY_PARAMS, fr_bias=0.0, fr_cool=0.0)
        away, n = Counter(), 0
        for k, seed in enumerate(seeds):
            rng = random.Random(900 + k)
            walk = [seed]
            for _ in range(args.steps):
                d = server.next_decision(walk[-1], walk[:-1][-50:], outcome="complete", params=params,
                                         rng=rng, trace=False)
                if not d["pick"]:
                    break
                n += 1
                f = of.get(d["pick"])
                if f and f != of.get(seed):
                    away[f] += 1
                walk.append(d["pick"])
    out = {"picks": n, "seeds": len(seeds), "steps": args.steps,
           "made": time.strftime("%Y-%m-%d %H:%M"),
           "share": {f: round(away[f] / max(1, n), 5) for f in franchise.NAMES}}
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    top = sorted(out["share"].items(), key=lambda kv: -kv[1])[:8]
    print(f"{n} picks from {len(seeds)} seeds in {time.time() - t0:.0f}s -> {OUT}")
    print("  " + "  ".join(f"{f} {100 * s:.1f}%" for f, s in top))


if __name__ == "__main__":
    main()
