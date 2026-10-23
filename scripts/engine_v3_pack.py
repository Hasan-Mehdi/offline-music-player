r"""Engine v3 data for the device pack (export_device_pack.build_pack(engine=3)).

The web player's autoplay (scripts/server.py next_decision, AUTOPLAY_PARAMS) runs on
CENTERED MuQ vectors and reads per-track signals the v1 pack never had. This writes them,
computed by the server's own functions so the device sees the same numbers:

  embeddings.f16  centered with the FULL library mean (server.emb()), re-normalized;
                  neighbors.bin is computed on these (the caller does both)
  signals.bin     n x 8B: u8 energy (0..254 = percentile x 254, 255 = none) |
                  u8 game franchise (1 + index in franchise.NAMES, 0 = none) |
                  u16 bpm x 10 (0 = none) | u16 cluster (0xFFFF = none) |
                  u16 YouTube Music play count (merged into the novelty/explore counts)
  taste_hist.bin  the history half of the taste centroid, pre-summed: 512 f32
                  sum(history_weight x centered vector) over every history track with an
                  embedding (on the card or not) + f32 sum|w| -- the device adds its own
                  plays and normalizes, which equals build_centroid over the merged weights
  cooc.bin        "COC1" u32 n | (n+1) u32 row offsets | u32 member pack indexes: each
                  seed's in-card radio members, rows sorted by video_id string (the order
                  blend_candidates takes them in)
  franchise.bin   "FRB1" u32 m | m f32: each franchise id's entry bias (server.franchises(),
                  id 0 = none), for rank_next's fr_bias / fr_cool
"""
import json
import struct
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from h2_layout import short_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def library_mean(emb_path):
    """server.emb(): every row L2-normalized, then the mean direction (fp32)."""
    d = np.load(emb_path, allow_pickle=False)
    X = d["embeddings"].astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    acc = np.zeros(X.shape[1], dtype=np.float64)
    for a in range(0, len(X), 8192):
        acc += X[a:a + 8192].astype(np.float64).sum(0)
    return (acc / max(1, len(X))).astype(np.float32), X, [str(x) for x in d["ids"]]


def center(V, mean):
    """personalize.center_embeddings on a copy, with a given mean."""
    Z = V.astype(np.float32) - mean
    Z /= np.linalg.norm(Z, axis=1, keepdims=True) + 1e-9
    return Z


def write_franchise(out, kept_vids):
    """The franchise half of the pack (signals.bin's spare byte + franchise.bin), from
    server.franchises(); also run on its own to update a card's pack in place."""
    import franchise
    import server
    with server.app.app_context():
        of, bias = server.franchises()
    out = Path(out)
    fid = {n: k + 1 for k, n in enumerate(franchise.NAMES)}
    sig = np.fromfile(out / "signals.bin", dtype=np.uint8).reshape(-1, 8)
    assert len(sig) == len(kept_vids), "signals.bin doesn't match the pack"
    sig[:, 1] = [fid.get(of.get(v), 0) for v in kept_vids]
    sig.tofile(out / "signals.bin")
    table = np.zeros(len(franchise.NAMES) + 1, dtype="<f4")
    for n, b in bias.items():
        table[fid[n]] = b
    with open(out / "franchise.bin", "wb") as f:
        f.write(b"FRB1" + struct.pack("<I", len(table)) + table.tobytes())
    return int((sig[:, 1] > 0).sum())


def build_extras(out, kept_vids, emb_path):
    """kept_vids: pack-order LONG video ids (library ids)."""
    t0 = time.time()
    import server  # the web player's backend: energy/bpm/clusters/history/cooc
    out = Path(out)
    n = len(kept_vids)
    idx = {v: i for i, v in enumerate(kept_vids)}
    with server.app.app_context():
        energy = server._energy_ranks()
        bpm = server._bpm_map()
        clusters = server.clusters()
        hist_w, hist_n = server.listen_history()
        cooc = server.cooc_members()

    names = sorted({c for c in clusters.values()}, key=lambda c: (len(c), c))
    cid = {c: k for k, c in enumerate(names)}
    sig = np.zeros(n, dtype=[("energy", "u1"), ("pad", "u1"), ("bpm", "<u2"),
                             ("cluster", "<u2"), ("hist", "<u2")])
    sig["energy"] = 255
    sig["cluster"] = 0xFFFF
    for v, i in idx.items():
        if v in energy:
            sig["energy"][i] = int(round(energy[v] * 254))
        b = bpm.get(v)
        if b and b > 0:
            sig["bpm"][i] = min(65535, int(round(b * 10)))
        if v in clusters:
            sig["cluster"][i] = cid[clusters[v]]
        sig["hist"][i] = min(65535, int(hist_n.get(v, 0)))
    sig.tofile(out / "signals.bin")
    write_franchise(out, kept_vids)

    # taste: history half, over every embedded history track (as the server does)
    mean, Xall, ids = library_mean(emb_path)
    id2row = {v: i for i, v in enumerate(ids)}
    acc = np.zeros(Xall.shape[1], dtype=np.float32)
    tot = 0.0
    rows = [(id2row[v], w) for v, w in hist_w.items() if v in id2row]
    for a in range(0, len(rows), 4096):
        part = rows[a:a + 4096]
        Z = center(Xall[[r for r, _ in part]], mean)
        w = np.array([w for _, w in part], dtype=np.float32)
        acc += (w[:, None] * Z).sum(0, dtype=np.float32)
        tot += float(np.abs(w).sum())
    with open(out / "taste_hist.bin", "wb") as f:
        f.write((server.HISTORY_W * acc).astype("<f4").tobytes())
        f.write(struct.pack("<f", server.HISTORY_W * tot))

    # co-occurrence rows (in-card members only), each sorted by video_id string
    offs, mem = [0], []
    for v in kept_vids:
        ms = sorted(m for m in cooc.get(v, ()) if m in idx)
        mem += [idx[m] for m in ms]
        offs.append(len(mem))
    with open(out / "cooc.bin", "wb") as f:
        f.write(b"COC1" + struct.pack("<I", n))
        f.write(np.asarray(offs, dtype="<u4").tobytes())
        f.write(np.asarray(mem, dtype="<u4").tobytes())

    rep = {"engine": 3, "centered": True, "clusters": len(names),
           "energy": int((sig["energy"] != 255).sum()), "bpm": int((sig["bpm"] > 0).sum()),
           "history_tracks": len(rows), "cooc_seeds": int(sum(1 for a, b in zip(offs, offs[1:]) if b > a)),
           "cooc_members": len(mem)}
    print(f"  engine v3 extras: {rep} ({time.time() - t0:.0f}s)")
    return rep, mean
