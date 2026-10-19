#!/usr/bin/env python3
"""After a skip, what does autoplay play next? A replay of the H2's own sittings (the plays
table, source 'h2'). At every moment right after a skip it compares what the H2 actually
played with what the radio (player_server/radio.py) would pick, reading the sitting's skips
the old way (a dislike or a skip in the first 15%) and the current way (any skip short of
radio.KEEP_FRAC; radio.STREAK in a row, or the seed turned down with nothing kept since, move
it to radio.fresh_seed). Per method: how much the pick sounds like the song just skipped and
like the last one finished (centred MuQ cosine; a random pair ~0), how often it's a song you
already play, and how often it shares an artist with the skipped one.

  .venv\\Scripts\\python scripts\\eval_h2_skips.py
  .venv\\Scripts\\python scripts\\eval_h2_skips.py --show "2026-10-14 19:30" "2026-10-14 19:40"

2026-10-15, 37 moments: the older walk 0.68 like the skipped song / 19% known; the radio with
the old reading 0.34 / 38%; with the current one 0.04 / 65% (a fresh seed in 17).
"""
import argparse
import collections
import csv
import datetime
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import server  # noqa: E402
from player_server import radio as RD  # noqa: E402

SITTING_GAP = 1800        # songs further apart than this are another sitting


def load():
    con = sqlite3.connect(f"file:{ROOT / 'data' / 'library.db'}?mode=ro", uri=True)
    meta = {v: (t or "", a or "", d or 0) for v, t, a, d in
            con.execute("SELECT video_id, title, artist, duration FROM tracks")}
    known = collections.Counter(r["video_id"] for r in
                                csv.DictReader(open(ROOT / "data" / "listens.csv", encoding="utf-8-sig")))
    ev = con.execute("SELECT ts, event, seconds, video_id FROM plays WHERE source='h2' ORDER BY ts, rowid").fetchall()
    starts = []                   # (ts, vid, you picked it, how it ended, seconds in)
    for i, (ts, e, s, v) in enumerate(ev):
        if e != "play":
            continue
        end, secs = None, 0
        for ts2, e2, s2, v2 in ev[i + 1:]:
            if v2 == v and e2 in ("complete", "skip", "switch", "dislike"):
                end, secs = e2, s2 or 0
                break
            if e2 == "play":
                break
        starts.append((float(ts), v, i > 0 and ev[i - 1][1] == "switch", end, secs))
    return meta, known, starts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", nargs=2, metavar=("FROM", "TO"), help="list the picks in this window")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    meta, known, starts = load()

    def frac(v, s):
        d = meta.get(v, ("", "", 0))[2]
        return s / d if d else 0.0

    rules = {"radio, old skips": lambda x: x[3] == "dislike" or (x[3] == "skip" and frac(x[1], x[4]) < 0.15),
             "radio, now": lambda x: x[3] == "dislike" or (x[3] == "skip" and frac(x[1], x[4]) < RD.KEEP_FRAC)}
    with server.app.app_context():
        ctx = server.radio_ctx()
    X, id2i = ctx.X, ctx.id2i

    def sim(p, q):
        if p not in id2i or q not in id2i:
            return None
        return float(np.asarray(X[id2i[p]], np.float32) @ np.asarray(X[id2i[q]], np.float32))

    lo = hi = None
    if a.show:
        lo, hi = (datetime.datetime.fromisoformat(t) for t in a.show)
    rows, shown, fresh_n = collections.defaultdict(list), [], 0
    for k in range(1, len(starts)):
        prev, nxt = starts[k - 1], starts[k]
        if prev[3] != "skip" or nxt[2] or nxt[0] - prev[0] > SITTING_GAP:
            continue
        sit, j = [prev], k - 1
        while j > 0 and starts[j][0] - starts[j - 1][0] < SITTING_GAP:
            j -= 1
            sit.insert(0, starts[j])
        seed0 = next((x[1] for x in reversed(sit) if x[2]), sit[0][1])
        tail = [x[1] for x in sit][-12:]
        heard = {x[1] for x in sit}
        fin = next((x[1] for x in reversed(sit) if x[3] == "complete"), None)
        out = {"what played": nxt[1]}
        for name, rule in rules.items():
            down, seed = {x[1] for x in sit if rule(x)}, seed0
            if name == "radio, now":                    # server._radio_decision
                kept = RD.station_anchor(tail, seed, down) if seed in down else None
                fresh = None
                if RD.reseed_now(tail, down) or (seed in down and not kept):
                    fresh = RD.fresh_seed(down, seed, ctx, exclude=heard, kept=[v for v in tail if v not in down])
                if fresh:
                    seed = fresh
                    fresh_n += 1
                elif seed in down:
                    seed = kept or seed
            elif seed in down:                          # the old rule: the last song kept
                seed = next((x[1] for x in reversed(sit) if x[1] not in down), seed)
            q = RD.sequence(seed, RD.ranked(seed, ctx, exclude=heard | {seed}, rejected=down), 1, ctx, tail=tail)
            out[name] = q[0] if q else None
        for name, p in out.items():
            if p:
                rows[name].append((sim(p, prev[1]), sim(p, fin) if fin else None, known[p] > 0,
                                   bool(set(RD.credits(meta[p][1])) & set(RD.credits(meta[prev[1]][1])))))
        when = datetime.datetime.fromtimestamp(prev[0])
        if lo and lo <= when <= hi:
            shown.append((when, meta[prev[1]][:2], {n: meta.get(p, ("?", "?"))[:2] for n, p in out.items()}))

    print(f"{len(rows['what played'])} moments right after a skip; the current radio moved to a fresh seed in {fresh_n}\n")
    print(f"{'':<18}{'like the song':>15}{'like the last':>15}{'a song':>9}{'skipped':>9}")
    print(f"{'':<18}{'skipped':>15}{'finished':>15}{'you know':>9}{'artist':>9}")
    for name, r in rows.items():
        m = lambda col: np.mean([x[col] for x in r if x[col] is not None])
        print(f"{name:<18}{m(0):>15.2f}{m(1):>15.2f}{np.mean([x[2] for x in r]):>9.0%}{np.mean([x[3] for x in r]):>9.0%}")
    for when, sk, o in shown:
        print(f"\n  {when:%m-%d %H:%M} skipped {sk[1][:20]} - {sk[0][:32]}")
        for n, (t, ar) in o.items():
            print(f"      {n:<18} {ar[:22]:<22} | {t[:44]}")


if __name__ == "__main__":
    main()
