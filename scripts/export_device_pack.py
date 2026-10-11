r"""Export a flat-file "device pack" for the embedded (ESP32-class) player.

The embedded firmware has no Python/SQLite/numpy — it mmap-reads fixed-layout
binary files from the SD card. This script builds those files on the PC from
library.db + the full fp32 MuQ embeddings (it does NOT depend on the neighbors
table or muq_fp16.npz, which can go stale; neighbors are recomputed here so the
pack is always internally consistent).

Pack layout (all little-endian, written to --out):
  pack.json        counts, dim, K, format version, byte layouts (human-readable)
  tracks.bin       N x 24-byte records, sorted by (artist, title) casefold:
                     u32 file_off, u32 title_off, u32 artist_off,
                     u32 album_off, u32 genre_off   (offsets into strings.bin)
                     u16 duration_s                 (0 = unknown)
                     i16 gain_q78                   (R128 gain dB * 256 re -23 LUFS;
                                                     32767 = no measurement)
  strings.bin      NUL-terminated UTF-8 pool. File strings are relative paths
                   "V/basename.opus" where V = video_id[0]: the SD copy must be
                   sharded into per-character subdirs because FAT32 caps a
                   directory at 65,534 entries and each long filename burns
                   several — a flat 55k-file dir does not fit. Firmware
                   prepends its music-root mount path.
  ids.bin          N x 11 ASCII bytes, the YouTube video_id per track (row i
                   matches tracks.bin row i) — stable key for play-log sync
  embeddings.f16   N x 512 float16, L2-normalized (dot product == cosine sim)
  neighbors.bin    N x K u32 track indices, best-first (0xFFFFFFFF = padding)

Usage:
  .venv\Scripts\python scripts\export_device_pack.py            # full build
  .venv\Scripts\python scripts\export_device_pack.py --limit 2000 --self-test
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import unicodedata

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from h2_layout import short_id  # noqa: E402

DIM = 512
REC_SIZE = 24
NO_GAIN = 32767
PAD = 0xFFFFFFFF
FORMAT_VERSION = 1


def load_tracks(db_path):
    con = sqlite3.connect(f"file:{db_path.replace(os.sep, '/')}?mode=ro", uri=True, timeout=15)
    con.execute("PRAGMA busy_timeout=10000")
    rows = con.execute(
        "SELECT video_id, path, title, artist, album, genre, duration, r128_gain_db FROM tracks"
    ).fetchall()
    con.close()
    return rows


def sort_key(s):
    # casefold + strip accents so ordering matches what a browse list expects
    s = unicodedata.normalize("NFKD", s or "").casefold()
    return "".join(c for c in s if not unicodedata.combining(c))


def build_pack(db, emb, out, k, limit=None, only_ids=None, layout="shard", engine=1):
    """only_ids: restrict to these video_ids (a card-sized subset; neighbors are then
    recomputed within it, so autoplay never reaches a track that isn't on the card).
    layout: 'shard' = V/basename (ESP32 plan), 'h2' = scripts/h2_layout.py paths.
    engine: 3 = the web player's current autoplay (scripts/engine_v3_pack.py): centered
    embeddings (neighbors computed on them) + signals / history taste / co-occurrence."""
    t0 = time.time()
    rows = load_tracks(db)
    npz = np.load(emb)
    emb_ids = npz["ids"]
    X = npz["embeddings"].astype(np.float32)
    id2row = {vid: i for i, vid in enumerate(emb_ids)}

    kept, skipped = [], []
    for r in rows:
        if only_ids is not None and r[0] not in only_ids:
            continue
        if r[0] in id2row:
            kept.append(r)
        else:
            skipped.append(r[0])
    kept.sort(key=lambda r: (sort_key(r[3]), sort_key(r[2])))
    if limit:
        kept = kept[:limit]
    n = len(kept)
    if n == 0:
        sys.exit("no tracks with embeddings — check --db/--emb")

    # embedding matrix in pack order, L2-normalized
    V = X[[id2row[r[0]] for r in kept]]
    V /= np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)
    if engine >= 3:
        from engine_v3_pack import center
        Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
        acc = np.zeros(X.shape[1], dtype=np.float64)
        for a in range(0, len(Xn), 8192):
            acc += Xn[a:a + 8192].astype(np.float64).sum(0)
        V = center(V, (acc / max(1, len(Xn))).astype(np.float32))   # = server.emb()
        del Xn

    # strings pool + fixed records
    pool = bytearray(b"\x00")  # offset 0 = empty string
    seen = {"": 0}

    def intern(s):
        s = (s or "").strip()
        if s not in seen:
            seen[s] = len(pool)
            pool.extend(s.encode("utf-8") + b"\x00")
        return seen[s]

    recs = np.zeros(n, dtype=np.dtype(
        [("file", "<u4"), ("title", "<u4"), ("artist", "<u4"),
         ("album", "<u4"), ("genre", "<u4"), ("dur", "<u2"), ("gain", "<i2")]))
    ids_blob = bytearray()
    if layout == "h2":
        from h2_layout import Layout
        lay = Layout()
        relpath = lambda vid, path, title, artist: lay.path(short_id(vid), title, artist)
    else:
        relpath = lambda vid, path, title, artist: vid[0] + "/" + os.path.basename(path or "")
    for i, (vid, path, title, artist, album, genre, dur, gain) in enumerate(kept):
        recs[i] = (intern(relpath(vid, path, title, artist)), intern(title), intern(artist),
                   intern(album), intern(genre),
                   min(65535, int(dur)) if dur else 0,
                   NO_GAIN if gain is None else max(-32768, min(32766, round(gain * 256))))
        ids_blob += short_id(vid).encode("ascii")   # 11 bytes; long chapter ids hashed

    # neighbors: chunked cosine top-K over the pack's own matrix
    kk = min(k, n - 1)
    nbrs = np.full((n, k), PAD, dtype=np.uint32)
    chunk = max(1, min(2048, int(2e9 / (4 * n))))  # ~2 GB per sims block
    for lo in range(0, n, chunk):
        hi = min(n, lo + chunk)
        sims = V[lo:hi] @ V.T
        sims[np.arange(hi - lo), np.arange(lo, hi)] = -np.inf  # drop self
        part = np.argpartition(-sims, kk - 1, axis=1)[:, :kk]
        order = np.take_along_axis(sims, part, axis=1).argsort(axis=1)[:, ::-1]
        nbrs[lo:hi, :kk] = np.take_along_axis(part, order, axis=1)
        print(f"  neighbors {hi}/{n}  ({time.time() - t0:.0f}s)", flush=True)

    os.makedirs(out, exist_ok=True)
    recs.tofile(os.path.join(out, "tracks.bin"))
    with open(os.path.join(out, "strings.bin"), "wb") as f:
        f.write(pool)
    with open(os.path.join(out, "ids.bin"), "wb") as f:
        f.write(bytes(ids_blob))
    V.astype(np.float16).tofile(os.path.join(out, "embeddings.f16"))
    nbrs.tofile(os.path.join(out, "neighbors.bin"))
    meta = {
        "format_version": FORMAT_VERSION, "built": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tracks": n, "dim": DIM, "k": k, "record_size": REC_SIZE,
        "strings_bytes": len(pool), "skipped_no_embedding": len(skipped),
        "gain_reference_lufs": -23.0, "gain_encoding": "Q7.8 dB, 32767=none",
        "order": "artist,title casefold", "id_bytes": 11,
        "file_layout": ("Music/<Letter>/<Artist>/<Title> [video_id].opus (scripts/h2_layout.py)"
                        if layout == "h2" else
                        "relative path video_id[0]/basename (FAT32 dir-entry cap)"),
        "subset": only_ids is not None,
    }
    if engine >= 3:
        from engine_v3_pack import build_extras
        rep, _ = build_extras(out, [r[0] for r in kept], emb)
        meta.update(rep)
    with open(os.path.join(out, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    total = sum(os.path.getsize(os.path.join(out, p)) for p in
                ("tracks.bin", "strings.bin", "ids.bin", "embeddings.f16", "neighbors.bin"))
    print(f"pack: {n} tracks, {len(skipped)} skipped (no embedding), "
          f"{total / 1e6:.1f} MB total, {time.time() - t0:.0f}s")
    if skipped:
        print("  skipped ids:", ", ".join(skipped[:10]) + ("..." if len(skipped) > 10 else ""))
    return meta


def self_test(out):
    meta = json.load(open(os.path.join(out, "pack.json"), encoding="utf-8"))
    n, k = meta["tracks"], meta["k"]
    recs = np.fromfile(os.path.join(out, "tracks.bin"), dtype=np.dtype(
        [("file", "<u4"), ("title", "<u4"), ("artist", "<u4"),
         ("album", "<u4"), ("genre", "<u4"), ("dur", "<u2"), ("gain", "<i2")]))
    pool = open(os.path.join(out, "strings.bin"), "rb").read()
    V = np.fromfile(os.path.join(out, "embeddings.f16"), dtype=np.float16).reshape(n, DIM)
    nbrs = np.fromfile(os.path.join(out, "neighbors.bin"), dtype=np.uint32).reshape(n, k)
    assert len(recs) == n

    def s(off):
        return pool[off:pool.index(b"\x00", off)].decode("utf-8")

    ids_blob = open(os.path.join(out, "ids.bin"), "rb").read()
    assert len(ids_blob) == n * 11
    norms = np.linalg.norm(V.astype(np.float32), axis=1)
    assert abs(float(norms.mean()) - 1.0) < 1e-2, norms.mean()
    rng = np.random.default_rng(0)
    Vf = V.astype(np.float32)
    for i in rng.integers(0, n, 5):
        sims = Vf @ Vf[i]
        sims[i] = -np.inf
        brute = int(np.argmax(sims))
        assert nbrs[i, 0] == brute, (i, nbrs[i, 0], brute)
        fname = s(recs[i]["file"])
        vid = ids_blob[i * 11:(i + 1) * 11].decode("ascii")
        assert fname.endswith(".opus") and f"[{vid}]" in fname, (fname, vid)
    i = int(rng.integers(0, n))
    print(f"self-test OK — sample: {s(recs[i]['artist'])} — {s(recs[i]['title'])} "
          f"(gain {recs[i]['gain'] / 256:.1f} dB, top nbr: {s(recs[nbrs[i, 0]]['title'])})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/library.db")
    ap.add_argument("--emb", default="data/muq_embeddings.npz")
    ap.add_argument("--out", default="data/device_pack")
    ap.add_argument("--k", type=int, default=120)
    ap.add_argument("--limit", type=int, default=None, help="smoke-test on first N tracks")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--engine", type=int, default=1, help="3 = centered + v3 signals")
    a = ap.parse_args()
    build_pack(a.db, a.emb, a.out, a.k, a.limit, engine=a.engine)
    if a.self_test:
        self_test(a.out)
