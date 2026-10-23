"""The radio engine (player_server/radio.py) for the H2: radio.bin in a card's pack.

The PC player's autoplay is a radio for the song you started on (docs/RADIO_ENGINE.md).
Its ranking needs the play-together model and the full MuQ matrix, which the H2 can't
hold, but a radio's ranking depends only on its seed. So every song on the card gets its
radio ranked here, over the card's songs (radio.ranked: play-together, song2vec, sound,
the songs you know, the seed's own YT Music radio), and the top K go into radio.bin with
their scores. Alongside: what sequence() needs per song (do you know it, its channel, its
game series) and its song2vec vector, for steering off songs you skip.

The player does the rest per pick (firmware/core/omp_radio.c): drops what this sitting
played and what played in the last 6 hours, subtracts the skip cost, and runs sequence()
for one song.

  .venv\\Scripts\\python scripts\\radio_pack.py --pack E:\\.coda\\pack

radio.bin (little-endian):
  "CRA2" u32 n u32 K u32 dim
  u16 count[n]                     how many of the seed's K slots are filled
  u8  known[n]                     you already play it (radio Context.fam > 0)
  u8  game[n]                      game series id, 0 none (franchise.NAMES order + 1)
  u32 channel[n]                   its first credited artist (radio.credits), 0 unknown
  u32 channel2[n]                  its second, 0 none ("Shofu, OmarCameUp")
  u32 work[n]                      the song under the version (radio.work_key, crc32), 0 none
  {u32 idx, i16 score*1000} [n][K] the seed's radio, best first
  i8  s2v[n][dim]                  song2vec * 127, all zero without one
  "SHR1" u8 ashare[n] u8 gshare[n] each seed's radio's share for its channel / game series
                                   (radio.shares) x SHARE_SCALE. At the end, so firmware from
                                   before 2026-10-19 reads the file as it was and keeps
                                   radio.py's fixed shares
  "FAM1" u8 fshare[n]              each seed's radio's share of songs you know
                                   (radio.seed_familiar_share: from its fresh YT Music radio)
                                   x SHARE_SCALE; firmware without it keeps FAMILIAR_SHARE
"""
import argparse
import dataclasses
import struct
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from h2_layout import short_id  # noqa: E402

K = 200
SHARE_SCALE = 250          # radio.bin's ashare / gshare: a share of 0.3 is 75


def build(pack_dir, k=K, limit=None):
    import franchise
    import server
    from player_server import radio as radio_engine

    pack_dir = Path(pack_dir)
    n = int(__import__("json").loads((pack_dir / "pack.json").read_text())["tracks"])
    raw = (pack_dir / "ids.bin").read_bytes()
    short = [raw[i * 11:(i + 1) * 11].decode() for i in range(n)]
    t0 = time.time()
    with server.app.app_context():
        ctx = server.radio_ctx()
        lib = set(server.lib_ids())
    long_of = {short_id(v): v for v in ctx.ids}
    vids = [long_of.get(s) for s in short]
    pos = {v: i for i, v in enumerate(vids) if v}
    card = {v for v in vids if v and v in lib and v in ctx.id2i}
    print(f"pack {n} songs; {len(card)} in the library with a sound vector "
          f"(context {time.time() - t0:.0f} s)")
    cx = dataclasses.replace(ctx, lib=card, _lib_cj=None, _lib_rows=None, _lib_ids=None, _hist=None)
    cx.lib_rows()

    count = np.zeros(n, dtype="<u2")
    rows = np.zeros((n, k), dtype=[("idx", "<u4"), ("score", "<i2")])
    seeds = [i for i, v in enumerate(vids) if v in card]
    if limit:
        seeds = seeds[:limit]
    t1 = time.time()
    for done, i in enumerate(seeds):
        r = radio_engine.ranked(vids[i], cx)[:k]
        count[i] = len(r)
        for j, (v, s) in enumerate(r):
            rows[i, j] = (pos[v], int(round(max(-32.0, min(32.0, s)) * 1000)))
        if done % 1000 == 999:
            el = time.time() - t1
            print(f"  {done + 1}/{len(seeds)} seeds, {el:.0f} s, ~{el / (done + 1) * (len(seeds) - done - 1):.0f} s left",
                  flush=True)

    known = np.asarray([1 if v and cx.fam.get(v, 0.0) > 0 else 0 for v in vids], dtype="u1")
    gid = {nm: j + 1 for j, nm in enumerate(franchise.NAMES)}
    game = np.asarray([gid.get(cx.franchise.get(v), 0) if v else 0 for v in vids], dtype="u1")
    chan_id = {}

    def credit(v, j):
        c = cx.credits.get(v) if v else None
        return chan_id.setdefault(c[j], len(chan_id) + 1) if c and len(c) > j else 0

    channel = np.asarray([credit(v, 0) for v in vids], dtype="<u4")
    channel2 = np.asarray([credit(v, 1) for v in vids], dtype="<u4")
    work = np.asarray([(zlib.crc32(cx.work[v].encode()) or 1) if v and cx.work.get(v) else 0
                       for v in vids], dtype="<u4")
    sh = np.asarray([radio_engine.shares(v, cx) if v else
                     (radio_engine.SEED_ARTIST_SHARE, radio_engine.SEED_GAME_SHARE) for v in vids])
    ashare, gshare = (np.clip(np.rint(sh[:, j] * SHARE_SCALE), 0, 255).astype("u1") for j in (0, 1))
    fsh = np.asarray([radio_engine.seed_familiar_share(v, cx) if v else radio_engine.FAMILIAR_SHARE
                      for v in vids])
    fshare = np.clip(np.rint(fsh * SHARE_SCALE), 0, 255).astype("u1")
    C = cx.collab
    dim = C.emb.shape[1] if C.emb is not None else 0
    s2v = np.zeros((n, dim), dtype="i1")
    for i, v in enumerate(vids):
        j = C.id2j.get(v) if v else None
        if j is not None and dim:
            s2v[i] = np.clip(np.rint(C.emb[j] * 127), -127, 127)

    out = pack_dir / "radio.bin"
    tmp = out.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        f.write(b"CRA2" + struct.pack("<III", n, k, dim))
        f.write(count.tobytes())
        f.write(known.tobytes())
        f.write(game.tobytes())
        f.write(channel.tobytes())
        f.write(channel2.tobytes())
        f.write(work.tobytes())
        f.write(rows.tobytes())
        f.write(s2v.tobytes())
        f.write(b"SHR1" + ashare.tobytes() + gshare.tobytes())
        f.write(b"FAM1" + fshare.tobytes())
    tmp.replace(out)
    print(f"{out}: {len(seeds)} radios, {int((count > 0).sum())} non-empty, "
          f"{out.stat().st_size / 1e6:.1f} MB, {time.time() - t0:.0f} s")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True, help="the card's pack dir, e.g. E:\\.coda\\pack")
    ap.add_argument("--k", type=int, default=K)
    ap.add_argument("--limit", type=int, default=None, help="only the first N seeds (timing)")
    a = ap.parse_args()
    build(a.pack, a.k, a.limit)


if __name__ == "__main__":
    main()
