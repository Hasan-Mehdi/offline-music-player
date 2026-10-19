"""Play-together model: which songs people put next to each other.

YouTube Music's radio is built mostly from co-listening, not from how songs sound,
and the 2026-10-11 comparison showed what that buys: its radio stays with the song
you started on (0.55 -> 0.50 sound-similarity to it across 50 songs) while a
sound-chained walk drifts (0.60 -> 0.40 in 15). We have three records of what goes
together, all already on disk:

  radios     data/radio_cache/<seed>.json: YT Music's own signed-in "Up next" list for a
             seed (harvest_radios.py, June 2026), seed first, then ~50 members in order.
  playlists  data/playlist_cache/<seed>.json: public playlists that contain a seed
             (harvest_playlists.py), deduplicated by playlist id. One that is mostly one
             channel (UPLOAD_SHARE) is an uploader's list, an album or a channel's uploads,
             and is its own source, "upload": it says "same channel", which the radio
             already knows, more than "played together".
  sittings   data/listens.csv: your own YT Music listening, split into sittings at gaps
             over SITTING_GAP and cut into overlapping chunks, so a four-hour sitting
             does not tie its first song to its last.

Each record is a basket. An item is a vector over baskets (the basket's weight where it
appears), and two items' relation is the cosine of those vectors, computed per request
from the sparse incidence matrix: no pair table is stored. `song2vec` (PPMI of the same
co-occurrences + truncated SVD) adds a dense vector per song, so songs that never share
a basket but share neighbours still relate.

Pure: nothing here touches Flask, SQLite or the server's globals.
"""
from __future__ import annotations

import csv
import glob
import json
import math
import os
from datetime import datetime

import numpy as np
from scipy.sparse import csr_matrix

SITTING_GAP = 12 * 60          # seconds between plays that end a sitting
CHUNK, STRIDE = 8, 4           # sitting chunks: 8 songs, overlapping by half
# Basket weights by source; a basket's entries are further divided by sqrt(size) so a
# 300-song playlist does not out-vote a 9-song one by 33x. Sittings at half weight: they
# also tie together songs you only happened to play back to back (OmarCameUp after a
# Pokemon theme), and 0.5 scored best on both benchmarks (scripts/eval_ytm.py: P@25
# 17.4 -> 17.6%, your next song in the top 10 8.8 -> 10.0%; 0.25 lost the second).
# Upload lists (an album, a channel's uploads: half the playlist cache) at a quarter: at full
# weight a channel's own lists tied all its songs together on top of same_artist, and 10-19 a
# Tazmilian Woods radio was 20 of 30 irikachana. Measured (eval_ytm.py, 10-19; upload 0 / 0.25 /
# 0.5 / 1): your next song from the sitting's first, top 50: 8.7 / 9.8 / 9.3 / 8.8%; your
# sittings' songs in its radio: 1.43 / 1.98 / 1.92 / 1.85%; P@25 vs YT Music 17.2 / 16.9 /
# 16.9 / 17.0%. At 0 many songs lose their only link (top 200: 12% vs 19%).
SOURCE_W = {"radio": 1.0, "playlist": 1.0, "upload": 0.25, "sitting": 0.5}
SVD_DIM = 96
UPLOAD_SHARE = 0.8             # one channel this share of a playlist's tracks: an "upload" list


def load_radios(dirpath):
    """[(seed, [member ids in radio order, seed excluded])] from the radio cache."""
    out = []
    for fn in sorted(glob.glob(os.path.join(dirpath, "*.json"))):
        seed = os.path.basename(fn)[:-5]
        try:
            items = json.load(open(fn, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        seen, mem = {seed}, []
        for it in items if isinstance(items, list) else []:
            v = it.get("videoId") if isinstance(it, dict) else None
            if v and v not in seen:
                seen.add(v)
                mem.append(v)
        if mem:
            out.append((seed, mem))
    return out


def _channel(name):
    a = " ".join(str(name or "").split()).casefold()
    return a[:-len(" - topic")].strip() if a.endswith(" - topic") else a


def playlist_kind(tracks):
    """"upload" when one channel holds UPLOAD_SHARE of the tracks that name one (an
    album, a channel's uploads: half the cache), else "playlist" (someone's mix)."""
    ch = [_channel(t.get("artist")) for t in tracks if isinstance(t, dict)]
    ch = [c for c in ch if c]
    if len(ch) < 2:
        return "playlist"
    top = max(ch.count(c) for c in set(ch))
    return "upload" if top >= UPLOAD_SHARE * len(ch) else "playlist"


def load_playlists(dirpath):
    """[(kind, [track ids])] — every distinct playlist in the playlist cache, in playlist
    order; kind "upload" or "playlist" (playlist_kind)."""
    pl = {}
    for fn in sorted(glob.glob(os.path.join(dirpath, "*.json"))):
        try:
            data = json.load(open(fn, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in data if isinstance(data, list) else []:
            pid = p.get("id") if isinstance(p, dict) else None
            if not pid or pid in pl:
                continue
            ids = list(dict.fromkeys(t.get("videoId") for t in p.get("tracks", [])
                                     if isinstance(t, dict) and t.get("videoId")))
            if len(ids) >= 2:
                pl[pid] = (playlist_kind(p.get("tracks", [])), ids)
    return list(pl.values())


def load_listens(path):
    """[(epoch, video_id)] oldest first from data/listens.csv ([] without one)."""
    ev = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                try:
                    ev.append((datetime.fromisoformat(r["time"]).timestamp(), r["video_id"]))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    ev.sort()
    return [e for e in ev if e[1]]


def sittings(listens, gap=SITTING_GAP, before=None):
    """Split [(ts, vid)] into sittings (lists of vids, immediate repeats collapsed),
    optionally keeping only plays before `before`."""
    out, cur, last = [], [], None
    for ts, v in listens:
        if before is not None and ts >= before:
            break
        if last is not None and ts - last > gap:
            if len(cur) >= 2:
                out.append(cur)
            cur = []
        if not cur or cur[-1] != v:
            cur.append(v)
        last = ts
    if len(cur) >= 2:
        out.append(cur)
    return out


def chunks(seq, size=CHUNK, stride=STRIDE):
    if len(seq) <= size:
        return [seq]
    return [seq[i:i + size] for i in range(0, len(seq) - size + stride, stride)
            if len(seq[i:i + size]) >= 2]


def baskets(radios=(), playlists=(), sitting_list=(), source_w=None, skip_seeds=()):
    """[(source, [ids])]. Radio baskets are seed + members; `skip_seeds` drops the
    radios of those seeds (held-out evaluation). A playlist is [ids] or (kind, [ids])."""
    skip = set(skip_seeds)
    out = [("radio", [s] + m) for s, m in radios if s not in skip]
    out += [p if isinstance(p, tuple) else ("playlist", p) for p in playlists]
    for st in sitting_list:
        out += [("sitting", c) for c in chunks(st)]
    return out


class Collab:
    """Incidence model over baskets. `vocab` is every song in at least two baskets plus
    every song in `keep` (the library), so songs off the library still link two that
    are on it."""

    def __init__(self, basket_list, keep=(), source_w=None, svd_dim=SVD_DIM, seed=0):
        sw = dict(SOURCE_W, **(source_w or {}))
        df = {}
        for _, b in basket_list:
            for v in set(b):
                df[v] = df.get(v, 0) + 1
        keep = set(keep)
        self.vocab = [v for v, c in df.items() if c >= 2 or v in keep]
        self.id2j = {v: j for j, v in enumerate(self.vocab)}
        rows, cols, vals = [], [], []
        nb = 0
        for src, b in basket_list:
            js = sorted({self.id2j[v] for v in b if v in self.id2j})
            if len(js) < 2:
                continue
            w = sw.get(src, 1.0) / math.sqrt(len(js))
            rows += [nb] * len(js)
            cols += js
            vals += [w] * len(js)
            nb += 1
        V = len(self.vocab)
        self.M = csr_matrix((np.asarray(vals, dtype=np.float32), (rows, cols)), shape=(nb, V))
        self.Mt = self.M.T.tocsr()
        self.sq = np.asarray(self.M.multiply(self.M).sum(axis=0)).ravel()   # ||item||^2
        self.pop = np.diff(self.Mt.indptr).astype(np.float32)                  # baskets per song
        self.emb = self._song2vec(svd_dim, seed) if svd_dim else None

    def _song2vec(self, dim, seed):
        from sklearn.decomposition import TruncatedSVD
        B = (self.M > 0).astype(np.float32)
        C = (B.T @ B).tocoo()
        rs = np.asarray(C.sum(axis=1)).ravel()
        T = rs.sum()
        with np.errstate(divide="ignore", invalid="ignore"):
            pmi = np.log((C.data * T) / (rs[C.row] * rs[C.col]) + 1e-12)
        keep = (pmi > 0) & (C.row != C.col)
        P = csr_matrix((pmi[keep].astype(np.float32), (C.row[keep], C.col[keep])),
                       shape=C.shape)
        k = min(dim, P.shape[0] - 1)
        if k < 1 or P.nnz == 0:
            return None
        E = TruncatedSVD(n_components=k, random_state=seed).fit_transform(P).astype(np.float32)
        E /= np.linalg.norm(E, axis=1, keepdims=True) + 1e-9
        return E

    def related(self, vid, pop_damp=0.5):
        """(indices, scores) of every song sharing a basket with `vid`: the weighted
        co-occurrence divided by ||vid|| * ||other||^(2*pop_damp) — 0.5 is the cosine;
        higher damps songs that are in everything."""
        j = self.id2j.get(vid)
        if j is None:
            return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float32)
        row = (self.Mt[j] @ self.M).tocsr()
        idx, val = row.indices, row.data
        sel = idx != j
        idx, val = idx[sel], val[sel]
        den = math.sqrt(self.sq[j]) * np.power(self.sq[idx], pop_damp) + 1e-9
        return idx, (val / den).astype(np.float32)

    def s2v(self, vid, idx):
        """song2vec cosine of `vid` to the songs at `idx` (zeros without the vector)."""
        j = self.id2j.get(vid)
        if self.emb is None or j is None or not len(idx):
            return np.zeros(len(idx), dtype=np.float32)
        return self.emb[idx] @ self.emb[j]
