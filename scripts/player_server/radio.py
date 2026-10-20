"""Seed-anchored radio: the autoplay design YouTube Music uses, rebuilt on our data.

Why this replaced the sound-chained walk (measured 2026-10-11 against 1,618 of your
signed-in YT Music radios and 4,983 of your own back-to-back plays):

                                   YTM radio   old walk   your listening
  sound-similarity, neighbours       0.44        0.71          0.36
  sound-similarity to the start   0.55->0.50  0.60->0.40         -
  same channel as the start          19%         0.2%      19% (back to back)
  same game series                   38%          9%       30% (back to back)
  songs you already play             35%          5%           57%

The walk asked "what sounds most like the song that just ended?" at every step, so
it drifted, never played what you know, and needed a cooldown for every way that
went wrong (fatigue, sameness, artist, franchise). A radio asks "what goes with the
song you started on?" once, mostly from what people play together
(player_server/collab.py), and keeps answering it for the whole queue.

Scoring is a weighted sum of a few features per candidate (FEATURES), standardized,
with weights fit by logistic regression to predict membership of YT Music's own
radio for held-out seeds (eval_ytm.py radio --write writes data/radio_weights.json).
A seed's cached YT Music radio is one basket of play-together evidence like any other;
it no longer leads the queue (OWN_RADIO_W).

Pure: no Flask, SQLite or server globals; the server builds `ctx` (see Context).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

import numpy as np

FEATURES = ("collab", "s2v", "sound", "taste", "fam", "fam_recent", "pop",
            "same_artist", "same_fr", "no_collab", "rk_collab", "rk_s2v", "rk_sound",
            "sound_nc", "s2v_nc")
RANKED = (("rk_collab", "collab"), ("rk_s2v", "s2v"), ("rk_sound", "sound"))

# Built-in weights: the all-data fit from eval_ytm.py radio --write (2026-10-19, after the
# candidate-pool fix and with upload lists at a quarter; 1,574 seeds, sound x0.15, pop x0.25).
# data/radio_weights.json overrides them when present, so a refit needs no code change; these
# keep a fresh checkout on the same ranking.
DEFAULT_MODEL = {
    "weights":
        {"collab": 0.1451, "s2v": 0.02515, "sound": 0.09811, "taste": -0.0431, "fam": -0.02864,
         "fam_recent": -0.001959, "pop": 0.1445, "same_artist": 0.2482, "same_fr": 0.1594,
         "no_collab": -0.4017, "rk_collab": 0.1236, "rk_s2v": 0.03875, "rk_sound": 0.01943,
         "sound_nc": 0.1447, "s2v_nc": 0.04992},
    "mean":
        {"collab": 0.05961, "s2v": 0.5688, "sound": 0.5199, "taste": 0.1056, "fam": 0.1657,
         "fam_recent": 0.0544, "pop": 1.366, "same_artist": 0.04248, "same_fr": 0.05459,
         "no_collab": 0.7213, "rk_collab": 0.04657, "rk_s2v": 0.1323, "rk_sound": 0.1323,
         "sound_nc": 0.4102, "s2v_nc": 0.3583},
    "std":
        {"collab": 0.1564, "s2v": 0.3746, "sound": 0.2952, "taste": 0.2286, "fam": 0.4308,
         "fam_recent": 0.1812, "pop": 0.914, "same_artist": 0.2008, "same_fr": 0.2286,
         "no_collab": 0.4484, "rk_collab": 0.0879, "rk_s2v": 0.05347, "rk_sound": 0.05347,
         "sound_nc": 0.3509, "s2v_nc": 0.3967},
    "pop_damp": 0.5,
    "source_w": {"radio": 1.0, "playlist": 1.0, "upload": 0.25, "sitting": 0.5},
}

POOL = {"collab": 300, "s2v": 300, "sound": 300, "fam": 60}
# The H2 runs sequence() and reject_cost() too (firmware/core/omp_radio.c, over radio.bin from
# scripts/radio_pack.py). Change the constants below or either function there as well, then
# rerun firmware/tools/test_radio_parity.py.
OWN_RADIO_W = 0.0       # x 1/log2(rank+2) for members of the seed's own YTM radio. Was 3.0
                         # ("what YouTube would play"): the cache is June's, and by 10-19 YT
                         # Music's Tazmilian Woods radio shared 1 of 25 songs with it; its lead
                         # picks (Ria, Jeanluke pt2) were what you skipped on 10-18. On your
                         # plays after Aug 15 it didn't help either (next song top 10 9.2% off
                         # vs 9.0% on; sittings 1.82 vs 1.79%). Its basket still counts in
                         # collab. A fresh harvest could earn it back: measure first.
STICK_K = 50.0           # stick(): pseudo-members pulling a group's stick toward the average
MAX_RUN = 2              # at most this many songs in a row from one channel
SEED_ARTIST_SHARE = 0.3  # and at most this share of a queue from the seed's channel (less
                         # for one whose YT Music radios go elsewhere: shares())
REJECT_W = 2.0           # standardized-score cost per unit of similarity to a rejected song
FAMILIAR_SHARE = 0.35    # share of a queue from songs you already play (YTM radio: 34%)
FAMILIAR_PULL = 0.3      # score nudge per song the queue is short of (or over) that share
GAME_PULL = 0.5          # score cost per song the seed's game series is over its share
ARTIST_PULL = 0.75       # score cost per song the seed's channel is over its share
SCAN = 300               # how far down the ranking a slot looks
OVER_CAP = 2.0           # game songs-over counted at most this many times
ARTIST_OVER_CAP = 4.0    # channel songs-over likewise. 2.0 (a 1.5 cost at most) let a channel
                         # whose songs lead by more take the queue: 10-19 a Tazmilian Woods radio
                         # was 20 of 30 irikachana, and 21% of radios on your sittings were over
                         # 40% the seed's channel (YT Music's: 10%; your sittings: 12%). At 4:
                         # 0%; P@25 vs YT Music 17.0% either way, on your sittings 1.82 vs
                         # 1.76% (two songs in 3,075: noise).
SEED_GAME_SHARE = 0.45   # most of a queue from the seed's game series (YTM radio: 41%)
SHARE_WINDOW = 12        # how much of the tail counts toward the shares
MAX_CREDITS = 2          # artists counted per song for the run and share rules (radio.bin keeps 2)

# What skips mean within a sitting (2026-10-15, from the H2's own log). Your skips land a
# median 56 s in, two thirds of them past 15% of the song, so "an early skip" missed most of
# them: after one skip the next pick was skipped 53% of the time (12% after a finish), and it
# sounded more like the song you'd just skipped than like the last one you finished. A skip
# is "not this, now" for the rest of the sitting; what your taste learns long-term still only
# counts early skips (personalize.STRONG_SKIP). And a run of them means the direction itself
# is done: you'd gone from rap to city pop to Sonic by hand, each a different place.
KEEP_FRAC = 0.8          # a skip before this share of the song turns it down for the sitting
STREAK = 3               # this many turned down in a row: the radio moves to a fresh seed
                         # (each full run of them: one skip on the fresh seed's first pick
                         # isn't another three)
RESEED_POOL = 200        # the fresh seed: one of this many songs you play most lately ...
AWAY_SIM = 0.25          # ... that sounds no closer than this (centred MuQ cosine; a random
                         # pair ~0, a song's sound neighbours ~0.7) to what you turned down,
                         # and of those the one most like what you kept this sitting.
# 2026-10-18, the H2: a Tazmilian Woods radio (irikachana, a gentle MOTHER 3-inspired piece,
# finished), three of its picks turned down -> the fresh seed was the most played song far
# from them AND from the seed: a rap remix, then (one skip later, four in a row) Coronet
# Highlands and Legends: Arceus. "It didn't match the vibe I started on." The fresh seed now
# keeps the sound of what you kept (Rozen's Kakariko Village there) and moves away only from
# what you turned down.


@dataclass
class Context:
    """Everything a radio needs, built by the caller.
    X/id2i/ids: L2-normalized (centered) MuQ matrix and its index; lib: library ids;
    taste: taste vector or None; fam / fam_recent: {vid: weight} from your listening
    (log1p counts / recency-weighted); artist / franchise: {vid: str}; own: {seed:
    [member ids]} cached YT Music radios to trust as-is ({} when evaluating)."""
    collab: object
    X: np.ndarray
    id2i: dict
    ids: list
    lib: set
    taste: object = None
    fam: dict = field(default_factory=dict)
    fam_recent: dict = field(default_factory=dict)
    artist: dict = field(default_factory=dict)
    franchise: dict = field(default_factory=dict)
    own: dict = field(default_factory=dict)
    model: dict = field(default_factory=lambda: DEFAULT_MODEL)
    credits: dict = field(default_factory=dict)   # {vid: (artist_key, ...)}, from artist if empty
    work: dict = field(default_factory=dict)      # {vid: work_key}: versions of one song share it
    stick: dict = field(default_factory=dict)     # {"artist"|"game": {key: stick}}, see stick()
    _lib_cj: object = None
    _lib_rows: object = None       # cached: MuQ rows / collab rows of library songs
    _lib_ids: list = None
    _hist: list = None

    def __post_init__(self):
        if not self.credits:
            self.credits = {v: credits(a) for v, a in self.artist.items() if a}
        self.artist = {v: artist_key(a) for v, a in self.artist.items() if a}

    def lib_rows(self):
        if self._lib_rows is None:
            ids = [v for v in self.ids if v in self.lib]
            self._lib_ids = ids
            self._lib_rows = np.asarray([self.id2i[v] for v in ids], dtype=np.int64)
            cj = self.collab.id2j
            self._lib_cj = np.asarray([cj.get(v, -1) for v in ids], dtype=np.int64)
            self._hist = [v for v in ids if self.fam.get(v)]
        return self._lib_rows


def artist_key(name):
    """One channel however it is spelled: "ROZEN" and "Rozen", "X - Topic" and "X"."""
    a = " ".join(str(name).split()).casefold()
    for suffix in (" - topic", "vevo"):
        if a.endswith(suffix):
            a = a[: -len(suffix)].strip()
    return a


def credits(name):
    """The artists a song credits, each as artist_key: "Shofu, OmarCameUp" is Shofu and
    OmarCameUp, so a collaboration counts toward each one's run and share (the seed's
    channel cap let 13 of 15 songs of an OmarCameUp radio through as "Shofu, OmarCameUp",
    "Daddyphatsnaps, OmarCameUp", ...). At most MAX_CREDITS."""
    out = []
    for part in re.split(r",\s*|\s+&\s+", str(name or "")):
        k = artist_key(part)
        if k and k not in out:
            out.append(k)
    return tuple(out[:MAX_CREDITS])


_VERSION = re.compile(r"\b(instrumental|inst|slowed|reverb|sped up|nightcore|extended|remastered|"
                      r"remaster|official (music )?(audio|video)|lyrics?( video)?|visuali[sz]er|"
                      r"hq|hd|8d|bass boosted)\b")


def work_key(title, artist):
    """The song under a version: its title without "instrumental", "slowed", "sped up",
    "official audio"... plus its first credited artist. A sitting plays one version of a
    song: 10-15 an OmarCameUp radio led with the instrumental of the song you'd just
    started. None without a title."""
    t = _VERSION.sub(" ", str(title or "").casefold())
    t = " ".join(re.findall(r"\w+", t))
    if not t:
        return None
    c = credits(artist)
    return f"{c[0] if c else ''}|{t}"


def stick(groups, k=None):
    """{group: how much YT Music's radios started on a song of that group (a channel, a game
    series) keep to it, as a multiple of the average group's share}, shrunk toward 1 by
    STICK_K pseudo-members so a group with one radio says little. `groups`: [(the seed's
    group, [each member's group])], None where unknown (a member's None counts as "not this
    group"; a seed's skips the radio). YT Music gives the seed's channel 21% of a radio on
    average, but Shinx's radios 55% and irikachana's 13%, Yoko Shimomura's 3%; a channel's
    other radios predict this one's share well (leave-one-out correlation 0.71), while ours,
    one share for every channel, didn't follow it at all (0.08). shares() uses it."""
    k = STICK_K if k is None else k
    same, tot = {}, {}
    for g, mem in groups:
        if g is None or not mem:
            continue
        same[g] = same.get(g, 0) + sum(m == g for m in mem)
        tot[g] = tot.get(g, 0) + len(mem)
    p = sum(same.values()) / max(1, sum(tot.values()))
    if p <= 0:
        return {}
    return {g: (same[g] + k * p) / (tot[g] + k) / p for g in tot}


def radio_sticks(radios, radio_artists, artist, franchise, lib, skip=()):
    """ctx.stick from YT Music's cached radios ([(seed, [member ids])] and collab's
    load_radio_artists). A seed's channel and game series come from `artist` / `franchise`;
    a member's channel from the radio (every member), its game series from `franchise`
    (library songs only: for the rest it's unknown). `skip`: seeds whose radio must not
    count (an evaluation's held-out seeds)."""
    skip = set(skip)
    ga, gg = [], []
    for seed, mem in radios:
        if seed in skip:
            continue
        a, names = artist.get(seed), radio_artists.get(seed)
        if a and names:
            ga.append((artist_key(a), [artist_key(n) if n else None for n in names]))
        f = franchise.get(seed)
        if f:
            gg.append((f, [franchise.get(v) for v in mem if v in lib]))
    return {"artist": stick(ga), "game": stick(gg)}


def load_model(path):
    try:
        m = json.loads(open(path, encoding="utf-8").read())
        if set(m.get("weights", {})) >= set(FEATURES):
            return m
    except (OSError, ValueError):
        pass
    return DEFAULT_MODEL


def _top(scores, ids, k, exclude):
    k = min(len(ids), k + len(exclude) + 1)
    if k <= 0:
        return []
    idx = np.argpartition(-scores, k - 1)[:k]
    idx = idx[np.argsort(-scores[idx])]
    return [ids[int(j)] for j in idx if ids[int(j)] not in exclude]


def candidates(seed, ctx, exclude=(), pool=None):
    """Library songs worth scoring for a radio on `seed`: its play-together neighbours,
    its song2vec and sound neighbours, and the songs you play that are nearest it."""
    pool = dict(POOL, **(pool or {}))
    ex = set(exclude) | {seed}
    out = {}
    rows = ctx.lib_rows()
    lib_ids = ctx._lib_ids
    C = ctx.collab
    idx, val = C.related(seed, ctx.model.get("pop_damp", 0.5))
    if len(idx):
        n = 0
        for j in idx[np.argsort(-val)]:     # related() indexes C.vocab through idx
            v = C.vocab[int(j)]
            if v in ctx.lib and v not in ex and v in ctx.id2i:
                out.setdefault(v, None)
                n += 1
                if n >= pool["collab"]:
                    break
    sj = C.id2j.get(seed)
    if C.emb is not None and sj is not None:
        has = ctx._lib_cj >= 0
        s = np.full(len(lib_ids), -2.0, dtype=np.float32)
        s[has] = C.emb[ctx._lib_cj[has]] @ C.emb[sj]
        for v in _top(s, lib_ids, pool["s2v"], ex):
            out.setdefault(v, None)
    si = ctx.id2i.get(seed)
    if si is not None:
        snd = np.asarray(ctx.X[rows] @ np.asarray(ctx.X[si], dtype=np.float32), dtype=np.float32)
        for v in _top(snd, lib_ids, pool["sound"], ex):
            out.setdefault(v, None)
        if ctx._hist and pool["fam"]:
            hrows = np.asarray([ctx.id2i[v] for v in ctx._hist], dtype=np.int64)
            hs = np.asarray(ctx.X[hrows] @ np.asarray(ctx.X[si], dtype=np.float32), dtype=np.float32)
            for v in _top(hs, ctx._hist, pool["fam"], ex):
                out.setdefault(v, None)
    return list(out)


def features(seed, cands, ctx):
    """(len(cands), len(FEATURES)) raw feature matrix, columns in FEATURES order."""
    n = len(cands)
    F = np.zeros((n, len(FEATURES)), dtype=np.float32)
    if not n:
        return F
    C = ctx.collab
    col = {f: i for i, f in enumerate(FEATURES)}
    idx, val = C.related(seed, ctx.model.get("pop_damp", 0.5))
    rel = dict(zip(idx.tolist(), val.tolist()))
    cj = np.asarray([C.id2j.get(v, -1) for v in cands], dtype=np.int64)
    F[:, col["collab"]] = [rel.get(int(j), 0.0) if j >= 0 else 0.0 for j in cj]
    F[:, col["no_collab"]] = (F[:, col["collab"]] <= 0).astype(np.float32)
    ok = cj >= 0
    if ok.any():
        F[ok, col["s2v"]] = C.s2v(seed, cj[ok])
        F[ok, col["pop"]] = np.log1p(C.pop[cj[ok]])
    ci = np.asarray([ctx.id2i[v] for v in cands], dtype=np.int64)
    V = np.asarray(ctx.X[ci], dtype=np.float32)
    si = ctx.id2i.get(seed)
    if si is not None:
        F[:, col["sound"]] = V @ np.asarray(ctx.X[si], dtype=np.float32)
    if ctx.taste is not None:
        F[:, col["taste"]] = V @ np.asarray(ctx.taste, dtype=np.float32)
    F[:, col["fam"]] = [ctx.fam.get(v, 0.0) for v in cands]
    F[:, col["fam_recent"]] = [ctx.fam_recent.get(v, 0.0) for v in cands]
    sa = ctx.artist.get(seed)
    F[:, col["same_artist"]] = [1.0 if sa and ctx.artist.get(v) == sa else 0.0 for v in cands]
    sf = ctx.franchise.get(seed)
    F[:, col["same_fr"]] = [1.0 if sf and ctx.franchise.get(v) == sf else 0.0 for v in cands]
    # where each candidate stands in the pool on a signal: 1/log2(2 + rank), the
    # reciprocal-rank view that makes the three lists comparable whatever their scale
    for rk, raw in RANKED:
        order = np.argsort(-F[:, col[raw]], kind="stable")
        r = np.empty(n, dtype=np.float32)
        r[order] = np.arange(n, dtype=np.float32)
        v = 1.0 / np.log2(2.0 + r)
        if raw == "collab":
            v[F[:, col["collab"]] <= 0] = 0.0
        F[:, col[rk]] = v
    # with no play-together evidence for a candidate, how it sounds and its song2vec
    # neighbourhood are all there is: these let the fit lean on them more in that case
    F[:, col["sound_nc"]] = F[:, col["sound"]] * F[:, col["no_collab"]]
    F[:, col["s2v_nc"]] = F[:, col["s2v"]] * F[:, col["no_collab"]]
    return F


def score(F, model):
    w = np.asarray([model["weights"][f] for f in FEATURES], dtype=np.float32)
    mu = np.asarray([model["mean"][f] for f in FEATURES], dtype=np.float32)
    sd = np.asarray([model["std"][f] for f in FEATURES], dtype=np.float32)
    return ((F - mu) / (sd + 1e-9)) @ w


def own_bonus(seed, cands, ctx):
    mem = ctx.own.get(seed) or ()
    rank = {v: r for r, v in enumerate(mem)}
    return np.asarray([OWN_RADIO_W / math.log2(rank[v] + 2) if v in rank else 0.0
                       for v in cands], dtype=np.float32)


def reject_cost(cands, rejected, ctx):
    """Cost of resembling a song you turned down in this sitting: its sound and its
    song2vec neighbourhood, whichever is closer."""
    rej = [v for v in rejected if v in ctx.id2i]
    if not rej or not cands:
        return np.zeros(len(cands), dtype=np.float32)
    ci = np.asarray([ctx.id2i[v] for v in cands], dtype=np.int64)
    R = np.asarray(ctx.X[[ctx.id2i[v] for v in rej]], dtype=np.float32)
    snd = np.max(np.asarray(ctx.X[ci], dtype=np.float32) @ R.T, axis=1)
    C = ctx.collab
    s2 = np.zeros(len(cands), dtype=np.float32)
    if C.emb is not None:
        cj = np.asarray([C.id2j.get(v, -1) for v in cands], dtype=np.int64)
        rj = [C.id2j[v] for v in rej if v in C.id2j]
        if rj:
            ok = cj >= 0
            s2[ok] = np.max(C.emb[cj[ok]] @ C.emb[rj].T, axis=1)
    return REJECT_W * np.maximum(0.0, np.maximum(snd, s2))


def ranked(seed, ctx, exclude=(), rejected=(), explain=False):
    """[(vid, score)] best first for a radio on `seed` (or (vid, score, features)). No other
    version of the seed or of anything excluded (work_key)."""
    cands = candidates(seed, ctx, exclude)
    wk = getattr(ctx, "work", None) or {}
    if wk:
        heard = {wk[v] for v in [*exclude, seed] if wk.get(v)}
        cands = [v for v in cands if wk.get(v) not in heard or not wk.get(v)]
    if not cands:
        return []
    F = features(seed, cands, ctx)
    s = score(F, ctx.model) + own_bonus(seed, cands, ctx) - reject_cost(cands, rejected, ctx)
    order = np.argsort(-s)
    if explain:
        return [(cands[i], float(s[i]), dict(zip(FEATURES, F[i].tolist()))) for i in order]
    return [(cands[i], float(s[i])) for i in order]


def shares(seed, ctx):
    """(artist_share, game_share) for a radio on `seed`: SEED_ARTIST_SHARE and SEED_GAME_SHARE,
    lowered for a channel / game series whose YT Music radios mostly go elsewhere (ctx.stick
    under 1), never raised: at the default share the channels whose radios keep to them
    already got more than YT Music gives them, and raising theirs only added more."""
    st = getattr(ctx, "stick", None) or {}
    a = st.get("artist", {}).get(ctx.artist.get(seed), 1.0)
    g = st.get("game", {}).get(ctx.franchise.get(seed), 1.0)
    return SEED_ARTIST_SHARE * min(1.0, a), SEED_GAME_SHARE * min(1.0, g)


def sequence(seed, ranked_list, n, ctx, tail=(), familiar_share=None, game_share=None,
             artist_share=None):
    """n songs from `ranked_list` ((vid, score, ...) best first), each slot taking the
    best score after three nudges and one rule. Shares count the recent tail (the last
    SHARE_WINDOW songs you heard) plus the new picks, so a queue built at once and one
    built a song at a time come out alike, and a capped kind spreads through the queue
    instead of front-loading:
    - familiar mix: while the queue is short of `familiar_share` (FAMILIAR_SHARE) songs
      you already play (ctx.fam), those get FAMILIAR_PULL per song short; past it, they
      lose it. YT Music's radio is about a third known songs;
    - the seed's game series past `game_share` (~SEED_GAME_SHARE; YT Music plays the start
      song's game 41% of the time, our plain ranking 63%) costs GAME_PULL per song over;
    - the seed's own channel past `artist_share` costs ARTIST_PULL per song over. Either
      share left None comes from shares(): the constant, lower for some channels / series;
    - no more than MAX_RUN in a row from one channel (a rule; it gives way only when
      nothing else is left).
    "Channel" here is every artist a song credits (credits()): a collaboration counts for
    each of them. And never another version (ctx.work) of the seed or of a song in the tail
    or the queue: that one is a rule with no give.
    Nudges, not quotas: as hard caps they made a slot take whatever was left, a J-pop
    song thirty places down in a Pokemon radio, Herb Alpert at rank 172 in a Mario Kart
    one, because the songs that fit were the capped kind. A negative share turns its
    nudge off."""
    fam_share = FAMILIAR_SHARE if familiar_share is None else familiar_share
    a_def, g_def = shares(seed, ctx)
    fr_share = g_def if game_share is None else game_share
    ar_share = a_def if artist_share is None else artist_share
    a_of, f_of, c_of = ctx.artist, ctx.franchise, getattr(ctx, "credits", None) or {}

    def cred(v):
        c = c_of.get(v)
        if c is None:
            a = a_of.get(v)
            c = (a,) if a else ()
        return set(c)

    seed_c, seed_f = cred(seed), f_of.get(seed)
    known = lambda v: ctx.fam.get(v, 0.0) > 0
    wk = getattr(ctx, "work", None) or {}
    works = {wk[v] for v in [*tail, seed] if wk.get(v)}
    recent = list(tail)[-SHARE_WINDOW:]
    hist = [cred(v) for v in recent][-MAX_RUN:]
    shown = len(recent)
    n_known = sum(known(v) for v in recent)
    n_art = sum(1 for v in recent if seed_c & cred(v))
    n_fr = sum(1 for v in recent if seed_f and f_of.get(v) == seed_f)
    rest = [(e[1], e[0]) for e in ranked_list if not (wk.get(e[0]) and wk[e[0]] in works)]
    out = []

    def over(count, share, cap):
        # songs past the share of the slots so far if one more of this kind came now,
        # counted at most `cap` times: uncapped, the cost grows with every song over until
        # it out-weighs any lead, i.e. a hard cap again
        if share < 0:
            return 0.0
        return min(cap, max(0.0, count + 1 - max(1.0, share * (shown + 1))))

    while len(out) < n and rest:
        pull = 0.0
        if fam_share >= 0:
            pull = FAMILIAR_PULL * max(-1.0, min(1.0, fam_share * (shown + 1) - n_known))
        cost_a = ARTIST_PULL * over(n_art, ar_share, ARTIST_OVER_CAP)
        cost_f = GAME_PULL * over(n_fr, fr_share, OVER_CAP)
        run = set.intersection(*hist[-MAX_RUN:]) if len(hist) >= MAX_RUN else set()
        best_i, best_s, fallback = None, -np.inf, None
        for i, (sc, v) in enumerate(rest[:SCAN]):
            if sc + max(pull, 0.0) <= best_s:
                break                                   # sorted: nothing below can win
            cv = cred(v)
            if run & cv:
                fallback = i if fallback is None else fallback
                continue
            eff = sc + (pull if known(v) else 0.0)
            if seed_c & cv:
                eff -= cost_a
            if seed_f and f_of.get(v) == seed_f:
                eff -= cost_f
            if eff > best_s:
                best_i, best_s = i, eff
        if best_i is None:
            best_i = fallback if fallback is not None else 0
        pick = rest.pop(best_i)[1]
        out.append(pick)
        if wk.get(pick):                                # its other versions: not in this queue
            rest = [e for e in rest if wk.get(e[1]) != wk[pick]]
        shown += 1
        n_known += known(pick)
        cp = cred(pick)
        hist = (hist + [cp])[-MAX_RUN:]
        n_art += bool(seed_c & cp)
        n_fr += bool(seed_f and f_of.get(pick) == seed_f)
    return out


def radio(seed, n, ctx, exclude=(), rejected=(), tail=()):
    """An n-song radio on `seed` (seed not included)."""
    return sequence(seed, ranked(seed, ctx, exclude, rejected), n, ctx, tail)


def streak(tail, down):
    """How many of the last songs heard (tail, oldest -> newest) were turned down in a row."""
    n = 0
    for v in reversed(list(tail)):
        if v not in down:
            break
        n += 1
    return n


def reseed_now(tail, down):
    """A full run of STREAK turned down in a row ends here (3, 6, ...): the radio's direction
    is done. The fourth skip is the fresh seed's first pick, not a verdict on it."""
    n = streak(tail, down)
    return n > 0 and n % STREAK == 0


def station_anchor(tail, seed, down):
    """The seed was turned down: the last song you kept since it started (tail, oldest ->
    newest), or None. Songs kept before it belong to the direction you'd left by picking it."""
    t = list(tail)
    after = t[len(t) - 1 - t[::-1].index(seed) + 1:] if seed in t else t
    return next((v for v in reversed(after) if v not in down and v != seed), None)


def fresh_seed(down, seed, ctx, exclude=(), kept=()):
    """The radio's direction is done (STREAK turned down in a row, or its seed turned down
    with nothing kept since): a new seed among the RESEED_POOL songs you've played most
    lately (ctx.fam_recent) that sound no closer than AWAY_SIM to what you turned down, the
    one most like what you kept this sitting (kept: the songs heard and not turned down) --
    the vibe you were in, from somewhere else in your music. With nothing kept, the most
    played of them that's also away from the old seed. Failing all that, the least like what
    you turned down. None when there's nothing to move to."""
    ex = set(exclude) | set(down) | {seed}
    pool = [v for v, _ in sorted(ctx.fam_recent.items(), key=lambda kv: -kv[1])
            if v in ctx.lib and v in ctx.id2i and v not in ex][:RESEED_POOL]
    if not pool:
        return None
    home = [v for v in kept if v in ctx.id2i and v not in down]
    away = [v for v in down if v in ctx.id2i] + ([] if home or seed not in ctx.id2i else [seed])
    P = np.asarray(ctx.X[[ctx.id2i[v] for v in pool]], dtype=np.float32)
    if away:
        A = np.asarray(ctx.X[[ctx.id2i[v] for v in away]], dtype=np.float32)
        near = np.max(P @ A.T, axis=1)
    else:
        near = np.full(len(pool), -1.0, dtype=np.float32)
    ok = np.flatnonzero(near < AWAY_SIM)
    if not len(ok):
        return pool[int(np.argmin(near))]
    if not home:
        return pool[int(ok[0])]
    H = np.asarray(ctx.X[[ctx.id2i[v] for v in home]], dtype=np.float32)
    like = np.max(P[ok] @ H.T, axis=1)
    return pool[int(ok[int(np.argmax(like))])]


def next_pick(seed, ctx, played, rejected=(), tail=()):
    """The next song of `seed`'s radio given what this sitting already played (excluded)
    and turned down (steered away from)."""
    q = radio(seed, 1, ctx, exclude=set(played), rejected=rejected, tail=tail)
    return q[0] if q else None
