#!/usr/bin/env python3
"""How much is our autoplay like YouTube Music's? Two benchmarks on your own data.

  radio   YT Music's signed-in radios (data/radio_cache, fetched 2026-06-27..07-01) are
          the answer key. Seeds are split into folds; for each fold the play-together
          model is rebuilt WITHOUT that fold's radios, so a seed's own radio never leaks
          into its features. Reports, per method, how much of the first 25 songs is in
          YT Music's radio for that seed (P@25) and what the queue looks like next to
          YT Music's (stays near the start, neighbours alike, same channel / game,
          songs you already play). Feature weights for player_server/radio.py are fit
          here by cross-validated logistic regression; --write saves the all-data fit to
          data/radio_weights.json.
  next    Your own plays after --cut (default 2026-08-15) are the answer key: given the
          song you were on, where does the song you played next rank? The model sees
          only sittings before the cut.

    python scripts/eval_ytm.py radio [--old 150] [--write]
    python scripts/eval_ytm.py next [--pairs 600]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import personalize  # noqa: E402
from player_server import collab as CB  # noqa: E402
from player_server import radio as RD  # noqa: E402

RADIO_T = datetime(2026, 6, 27, tzinfo=timezone.utc).timestamp()   # radios fetched from here
WEIGHTS_PATH = ROOT / "data" / "radio_weights.json"
N_QUEUE = 25
FOLDS = 5
MIN_MEMBERS = 8
TAKEOVER = 0.4     # a radio "taken over" by its seed's channel (YT Music's: 10% of them)


def pct(x):
    return f"{100 * np.mean(x):5.1f}%" if len(x) else "   n/a"


def mean(x):
    return f"{np.mean(x):.3f}" if len(x) else "  n/a"


class Data:
    """Library, embeddings and metadata via the server module (read-only)."""

    def __init__(self):
        import server
        self.server = server
        with server.app.app_context():
            E = server.emb()
            self.X, self.id2i, self.ids = E["X"], E["id2i"], E["ids"]
            self.lib = {v for v in server.lib_ids() if v in self.id2i}
            self.artist = server.track_meta()["id2artist"]
            self.franchise, _ = server.franchises()
        self.radios = CB.load_radios(str(ROOT / "data" / "radio_cache"))
        self.radio_artists = CB.load_radio_artists(str(ROOT / "data" / "radio_cache"))
        self.playlists = CB.load_playlists(str(ROOT / "data" / "playlist_cache"))
        self.listens = CB.load_listens(str(ROOT / "data" / "listens.csv"))
        self.heard_ever = {v for _, v in self.listens}

    def cos(self, a, b):
        return float(np.asarray(self.X[self.id2i[a]], dtype=np.float32)
                     @ np.asarray(self.X[self.id2i[b]], dtype=np.float32))

    def personal(self, before):
        """(taste vector, fam, fam_recent) from your listening before `before`."""
        cnt, rec, last = Counter(), defaultdict(float), {}
        for ts, v in self.listens:
            if ts >= before:
                break
            cnt[v] += 1
            rec[v] += 0.5 ** ((before - ts) / (30 * 86400))
            last[v] = ts
        fam = {v: math.log1p(c) for v, c in cnt.items()}
        fam_recent = {v: math.log1p(r) for v, r in rec.items()}
        rows = [{"video_id": v, "play_count": c,
                 "last_played": datetime.fromtimestamp(last[v], timezone.utc).date().isoformat()}
                for v, c in cnt.items() if v in self.id2i]
        w = personalize.history_weights(rows, before)
        taste = personalize.build_centroid(self.X, self.id2i, w)
        return taste, fam, fam_recent

    def context(self, model, before, own=None, rmodel=None, skip=(), stick=True):
        """`skip`: seeds whose radios the channel / game stick must not see (held out)."""
        taste, fam, fam_recent = self.personal(before)
        st = (RD.radio_sticks(self.radios, self.radio_artists, self.artist, self.franchise, self.lib,
                              skip=skip) if stick else {})
        return RD.Context(collab=model, X=self.X, id2i=self.id2i, ids=self.ids, lib=self.lib,
                          taste=taste, fam=fam, fam_recent=fam_recent, artist=self.artist,
                          franchise=self.franchise, own=own or {},
                          model=rmodel or RD.DEFAULT_MODEL, stick=st)


def shape(D, seed, queue):
    """Per-queue numbers comparable with the YT Music radio."""
    q = [v for v in queue if v in D.id2i]
    art = [RD.artist_key(D.artist.get(v, v)) for v in q]
    sa = RD.artist_key(D.artist.get(seed, seed))
    out = {"sim_seed": [D.cos(seed, v) for v in q],
           "adj": [D.cos(a, b) for a, b in zip(q, q[1:])],
           "same_artist": [a == sa for a in art],
           "top_artist": [Counter(art).most_common(1)[0][1] / len(q)] if q else [],
           "seed_takeover": [sum(a == sa for a in art) / len(q) > TAKEOVER] if q else [],
           "familiar": [v in D.heard_ever for v in q]}
    sf = D.franchise.get(seed)
    if sf:
        out["same_fr"] = [D.franchise.get(v) == sf for v in q]
    if sf != "sonic":
        out["sonic"] = [D.franchise.get(v) == "sonic" for v in q]
    return out


def report_shape(name, shapes, p25=None, pool=None, queues=None):
    """One method's line: P@25, then the shape numbers, then (with `queues`) how much it
    leans on a few songs across ALL radios — a song in every queue is how Sonic got into
    every autoplay; YT Music's radios: 44% distinct, top 1% of songs = 16% of slots."""
    agg = defaultdict(list)
    pos = defaultdict(list)
    for sh in shapes:
        for k, v in sh.items():
            if k == "sim_seed":
                for i, x in enumerate(v):
                    pos["01-05" if i < 5 else ("06-10" if i < 10 else "11-25")].append(x)
            else:
                agg[k].extend(v)
    line = f"  {name:22s}"
    if p25 is not None:
        line += f" P@25 {pct(p25)}"
    if pool is not None:
        line += f"  (pool holds {pct(pool)} of radio)"
    print(line)
    print(f"      near start 1-5/6-10/11-25 {mean(pos['01-05'])} {mean(pos['06-10'])} {mean(pos['11-25'])}"
          f"   neighbours {mean(agg['adj'])}   same channel {pct(agg['same_artist'])}"
          f"   same game {pct(agg['same_fr'])}   familiar {pct(agg['familiar'])}"
          f"   sonic (non-sonic seeds) {pct(agg['sonic'])}"
          f"   one channel's share {pct(agg['top_artist'])}"
          f"   seed channel > {TAKEOVER:.0%} of the queue {pct(agg['seed_takeover'])}")
    if queues:
        cnt = Counter(v for q in queues for v in q)
        slots = sum(len(q) for q in queues)
        top = sum(c for _, c in cnt.most_common(max(1, len(cnt) // 100)))
        print(f"      across radios: distinct {100 * len(cnt) / max(1, slots):.0f}% of slots"
              f"   top 1% of songs take {100 * top / max(1, slots):.1f}%"
              f"   most-served song in {cnt.most_common(1)[0][1]} of {len(queues)} radios")


SOUND_FEATURES = ("sound", "rk_sound")
SOUND_SCALE = 0.15
POP_SCALE = 0.25


def fit_lr(F, y, C=1.0, sound_scale=1.0, pop_scale=1.0):
    """Logistic regression on standardized features -> a radio.py model. The fit alone
    leans on sound (in-radio songs that sound like the seed are the easiest to find), and
    the queue it ranks sounds samey: neighbours 0.63 alike vs YT Music's 0.47.
    `sound_scale` shrinks the sound weights after the fit; 0.25 lands on YT Music's
    numbers for a small cost in P@25 (19.3% -> 17.1% with the share rules on).
    The fit's biggest weight is then `pop` (how many baskets hold a song): YT Music's
    radios do favour popular songs, but at full weight our few hubs crowd every radio
    (one Macross 82-99 song in 18% of all radios; YT Music's most-served song is in 10%).
    `pop_scale` 0.25 with sound 0.15 matches YT Music's spread (top 1% of songs 14.7% of
    slots vs 16.4%) and its shape, at P@25 16.4%."""
    from sklearn.linear_model import LogisticRegression
    mu, sd = F.mean(0), F.std(0) + 1e-9
    lr = LogisticRegression(C=C, max_iter=3000)
    lr.fit((F - mu) / sd, y)
    w = dict(zip(RD.FEATURES, map(float, lr.coef_[0])))
    for f in SOUND_FEATURES:
        w[f] *= sound_scale
    w["pop"] *= pop_scale
    return {"weights": w,
            "mean": dict(zip(RD.FEATURES, map(float, mu))),
            "std": dict(zip(RD.FEATURES, map(float, sd)))}


def radio_bench(args):
    D = Data()
    sits = CB.sittings(D.listens, before=RADIO_T)
    R = {s: [v for v in m if v in D.lib] for s, m in D.radios}
    seeds = [s for s in R if s in D.lib and len(R[s]) >= MIN_MEMBERS]
    random.Random(0).shuffle(seeds)
    fold = {s: i % FOLDS for i, s in enumerate(seeds)}
    print(f"{len(seeds)} seeds with >= {MIN_MEMBERS} radio members in the library; "
          f"{len(D.playlists)} playlists; {len(sits)} sittings before the radios")
    rows = {}          # seed -> (cands, F, y)
    ctxs = {}
    t0 = time.time()
    for k in range(FOLDS):
        test = [s for s in seeds if fold[s] == k]
        model = CB.Collab(CB.baskets(D.radios, D.playlists, sits, skip_seeds=test), keep=D.lib,
                          source_w=_sw(args))
        ctx = D.context(model, RADIO_T, rmodel=dict(RD.DEFAULT_MODEL, pop_damp=args.pop_damp),
                        skip=test)
        ctxs[k] = ctx
        for s in test:
            cands = RD.candidates(s, ctx)
            F = RD.features(s, cands, ctx)
            rs = set(R[s])
            rows[s] = (cands, F, np.asarray([c in rs for c in cands], dtype=np.int8))
        print(f"  fold {k + 1}/{FOLDS}: {len(model.vocab)} songs, {model.M.shape[0]} baskets "
              f"({time.time() - t0:.0f}s)")

    # Sequencing sees every song you have heard as "known", as the live server does (its
    # fam comes from the whole history); the features above only saw the pre-radio part.
    seq_ctx = RD.Context(collab=None, X=D.X, id2i=D.id2i, ids=D.ids, lib=D.lib,
                         artist=D.artist, franchise=D.franchise,
                         fam={v: 1.0 for v in D.heard_ever})

    def seed_share(s, chans):
        sa = RD.artist_key(D.artist.get(s, s))
        return sum(c is not None and RD.artist_key(c) == sa for c in chans) / max(1, len(chans))

    # YT Music's seed-channel share on its whole radio (every member, not just the library's)
    ytm_share = {s: seed_share(s, (D.radio_artists.get(s) or [])[:N_QUEUE]) for s in seeds}

    def evaluate(name, scorer, rules=True):
        p25, pool, shapes, queues, gap, ggap = [], [], [], [], [], []
        off = {} if rules else {"familiar_share": -1, "game_share": -1}
        for s in seeds:
            cands, F, y = rows[s]
            sc = scorer(s, F)
            order = np.argsort(-sc)
            ranked = [(cands[i], float(sc[i])) for i in order]
            a_sh, g_sh = RD.shares(s, ctxs[fold[s]])       # the stick from the other folds
            if args.no_stick:
                a_sh, g_sh = RD.SEED_ARTIST_SHARE, RD.SEED_GAME_SHARE
            q = RD.sequence(s, ranked, N_QUEUE, seq_ctx, **{"artist_share": a_sh, "game_share": g_sh,
                                                           **off})
            rs = set(R[s])
            p25.append(sum(v in rs for v in q) / N_QUEUE)
            pool.append(y.sum() / max(1, len(rs)))
            shapes.append(shape(D, s, q))
            queues.append(q)
            st = ctxs[fold[s]].stick
            gap.append((seed_share(s, [D.artist.get(v) for v in q]), ytm_share[s],
                        st["artist"].get(RD.artist_key(D.artist.get(s, s)), 1.0)))
            sf = D.franchise.get(s)
            if sf:
                same = lambda m: sum(D.franchise.get(v) == sf for v in m) / max(1, len(m))
                ggap.append((same(q), same(R[s][:N_QUEUE]), st["game"].get(sf, 1.0)))
        report_shape(name, shapes, p25, pool, queues)
        # per seed, against YT Music's radio for it: the seed's channel (its whole radio) and
        # game series (its songs in the library), split by how much the channel's / series'
        # other radios keep to it (radio.stick, from the other folds)
        for what, g in (("channel", gap), ("game series", ggap)):
            o, y, t = (np.asarray(x) for x in zip(*g))
            print(f"      seed's {what} vs YT Music's radio for that seed: off by {np.mean(abs(o - y)):.3f}"
                  f" of the queue, ours - theirs {np.mean(o - y):+.3f}, corr {np.corrcoef(o, y)[0, 1]:.2f}")
            for lo, hi in ((0, 0.8), (0.8, 1.25), (1.25, 99)):
                m = (t >= lo) & (t < hi)
                if m.any():
                    print(f"        its radios keep to it x{lo:.2f}-{hi:.2f} ({m.sum():4} seeds): ours "
                          f"{100 * o[m].mean():4.1f}%  YT Music {100 * y[m].mean():4.1f}%")
        return np.mean(p25)

    print("\n== YT Music's own radio (the answer key), same seeds")
    report_shape("YT Music radio", [shape(D, s, R[s][:N_QUEUE]) for s in seeds],
                 queues=[R[s][:N_QUEUE] for s in seeds])

    col = {f: i for i, f in enumerate(RD.FEATURES)}
    print("\n== single signals (each ranks the same candidate pool; share rules off)")
    for f in ("sound", "collab", "s2v", "fam", "taste"):
        evaluate(f, lambda s, F, f=f: F[:, col[f]] + 1e-6 * F[:, col["collab"]], rules=False)

    print("\n== fitted (5-fold: weights fit on the other folds' seeds)")
    for ss, ps in ((1.0, 1.0), (args.sound_scale, args.pop_scale)):
        models = {}
        for k in range(FOLDS):
            tr = [s for s in seeds if fold[s] != k]
            F = np.vstack([rows[s][1] for s in tr])
            y = np.concatenate([rows[s][2] for s in tr])
            models[k] = fit_lr(F, y, C=args.C, sound_scale=ss, pop_scale=ps)
        tag = f"fit, sound x{ss} pop x{ps}"
        evaluate(f"{tag}, no rules", lambda s, F: RD.score(F, models[fold[s]]), rules=False)
        evaluate(tag, lambda s, F: RD.score(F, models[fold[s]]))

    if args.old:
        print(f"\n== old engine (sound-chained walk, server.next_decision), {args.old} seeds,"
              f" the seed's own radio hidden from its cooc term")
        old_bench(D, seeds[:args.old], R)

    F = np.vstack([rows[s][1] for s in seeds])
    y = np.concatenate([rows[s][2] for s in seeds])
    full = fit_lr(F, y, C=args.C, sound_scale=args.sound_scale, pop_scale=args.pop_scale)
    full["pop_damp"] = args.pop_damp
    full["source_w"] = _sw(args)
    full["fit"] = {"seeds": len(seeds), "rows": int(len(y)), "positives": int(y.sum()),
                   "date": datetime.now().isoformat(timespec="seconds")}
    print("\nall-data weights (standardized features):")
    for f in RD.FEATURES:
        print(f"    {f:12s} {full['weights'][f]:+.3f}")
    if args.write:
        WEIGHTS_PATH.write_text(json.dumps(full, indent=1), encoding="utf-8")
        print(f"wrote {WEIGHTS_PATH}")


def _sw(args):
    return {"radio": args.w_radio, "playlist": args.w_playlist, "upload": args.w_upload,
            "sitting": args.w_sitting}


def old_bench(D, seeds, R):
    server = D.server
    p25, shapes, queues = [], [], []
    with server.app.app_context():
        full = server.cooc_members()
        orig = server.cooc_members
        try:
            for k, s in enumerate(seeds):
                masked = dict(full)
                masked.pop(s, None)
                server.cooc_members = lambda m=masked: m
                rng = random.Random(1000 + k)
                walk = [s]
                for _ in range(N_QUEUE):
                    d = server.next_decision(walk[-1], walk[:-1][-50:], outcome="complete",
                                             rng=rng, trace=False, engine="walk")
                    if not d["pick"]:
                        break
                    walk.append(d["pick"])
                q = walk[1:]
                rs = set(R[s])
                p25.append(sum(v in rs for v in q) / N_QUEUE)
                shapes.append(shape(D, s, q))
                queues.append(q)
        finally:
            server.cooc_members = orig
    report_shape("old walk", shapes, p25, queues=queues)


def next_bench(args):
    D = Data()
    cut = datetime.fromisoformat(args.cut).replace(tzinfo=timezone.utc).timestamp()
    sits = CB.sittings(D.listens, before=cut)
    model = CB.Collab(CB.baskets(D.radios, D.playlists, sits), keep=D.lib, source_w=_sw(args))
    rmodel = RD.load_model(WEIGHTS_PATH)
    own = {s: m for s, m in D.radios}
    ctx = D.context(model, cut, own=own, rmodel=rmodel, stick=not args.no_stick)
    pairs = []          # (a, b, tail, sitting start)
    after = [(ts, v) for ts, v in D.listens if ts >= cut]
    for st in CB.sittings(after):
        st = [v for v in st if v in D.lib]
        for i in range(1, len(st)):
            if st[i] != st[i - 1]:
                pairs.append((st[i - 1], st[i], st[:i - 1][-50:], st[0]))
    rng = random.Random(3)
    pairs = rng.sample(pairs, min(args.pairs, len(pairs)))
    print(f"{len(pairs)} back-to-back pairs after {args.cut} (model: {len(sits)} sittings before)")

    def hits(rank_of):
        r = np.asarray(rank_of)
        return f"top10 {pct(r < 10)}  top50 {pct(r < 50)}  top200 {pct(r < 200)}"

    snd, new_a, new_s = [], [], []
    for a, b, tail, start in pairs:
        sims = np.asarray(D.X @ np.asarray(D.X[D.id2i[a]], dtype=np.float32), dtype=np.float32)
        snd.append(int((sims > sims[D.id2i[b]]).sum()) - 1)
        for out, seed in ((new_a, a), (new_s, start)):
            ids = [v for v, _ in RD.ranked(seed, ctx, exclude=set(tail) | {a})]
            out.append(ids.index(b) if b in ids else 10 ** 6)
    old = []
    server = D.server
    with server.app.app_context():
        for a, b, tail, _ in pairs:
            d = server.next_decision(a, tail, outcome="complete", rng=random.Random(5),
                                     trace=False, engine="walk")
            ids = [e[0] for e in d["ranked"]]
            old.append(ids.index(b) if b in ids else 10 ** 6)
    print(f"  pure sound            {hits(snd)}")
    print(f"  old walk              {hits(old)}")
    print(f"  radio, seed = prev    {hits(new_a)}")
    print(f"  radio, seed = start   {hits(new_s)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("radio", "next"):
        p = sub.add_parser(name)
        p.add_argument("--w-radio", type=float, default=CB.SOURCE_W["radio"])
        p.add_argument("--w-playlist", type=float, default=CB.SOURCE_W["playlist"])
        p.add_argument("--w-upload", type=float, default=CB.SOURCE_W["upload"])
        p.add_argument("--w-sitting", type=float, default=CB.SOURCE_W["sitting"])
        p.add_argument("--pop-damp", type=float, default=0.5)
        p.add_argument("--no-stick", action="store_true",
                       help="the fixed channel / game shares for every seed (radio.shares off)")
    r = sub.choices["radio"]
    r.add_argument("--old", type=int, default=0, help="also run the old walk on this many seeds")
    r.add_argument("--C", type=float, default=1.0)
    r.add_argument("--sound-scale", type=float, default=SOUND_SCALE)
    r.add_argument("--pop-scale", type=float, default=POP_SCALE)
    r.add_argument("--write", action="store_true")
    n = sub.choices["next"]
    n.add_argument("--cut", default="2026-08-15")
    n.add_argument("--pairs", type=int, default=600)
    args = ap.parse_args(argv)
    {"radio": radio_bench, "next": next_bench}[args.mode](args)


if __name__ == "__main__":
    main()
