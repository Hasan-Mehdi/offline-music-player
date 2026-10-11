r"""Coda-on-H2 browse data, computed on the PC with the web player's own server code so
the device shows the same shelves, soundtracks and genres (docs/H2_APP_PLAN.md).

  explore.bin   Explore shelves (server.explore's pools, uncapped): fresh finds, deep cuts,
                forgotten favourites. The device draws 12 at random per visit, like the web.
  osts.bin      Soundtrack crates (server._ost_index: curated names, franchise sections,
                album order), restricted to what is on the card.
  genres.bin    Genre crates (server.genre_of), biggest first, 'unlabeled' last; members
                in pack (artist, title) order.
  genre_of.bin  u8 per pack track: index into genres.bin (station fencing), 255 = none.
  search.bin    word-prefix index for letter-by-letter search (see build_search).

CRT1 crate file (little-endian):
  "CRT1" u32 n_crates | u32 n_members | u32 strings_len
  n_crates x 24B { u32 name_off, u32 sub_off, u32 section_off, u32 first, u32 count,
                   u32 seconds }
  n_members x u32 pack index          (crate i = members[first : first + count])
  strings: NUL-terminated UTF-8, offset 0 = ""
The device keeps the header, table and strings in RAM and reads members on demand.

  .venv\Scripts\python scripts\h2_crates.py --out D:\coda-h2card            # full pack
  .venv\Scripts\python scripts\h2_crates.py --out E:\ --pack E:\.coda\pack  # a card
"""
import argparse
import json
import math
import random
import re
import sqlite3
import struct
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from h2_layout import short_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data" / "device_pack"
MIN_OST_ON_CARD = 4               # = server.MIN_OST_TRACKS, counted on what the card has
EXPLORE_POOL = {"fresh": 96, "deep": 96, "forgotten": 48}


def read_pack(pack_dir):
    meta = json.loads((pack_dir / "pack.json").read_text())
    n = meta["tracks"]
    ids = (pack_dir / "ids.bin").read_bytes()
    vids = [ids[i * 11:(i + 1) * 11].decode() for i in range(n)]
    recs = np.fromfile(pack_dir / "tracks.bin", dtype="<u4").reshape(n, 6)
    strings = (pack_dir / "strings.bin").read_bytes()
    return vids, recs, strings


class Strings:
    def __init__(self):
        self.blob, self.at = bytearray(b"\0"), {"": 0}

    def __call__(self, s):
        s = s or ""
        if s not in self.at:
            self.at[s] = len(self.blob)
            self.blob += s.encode("utf-8") + b"\0"
        return self.at[s]


def write_crates(path, crates):
    """crates: list of dict(name, sub, section, members [pack idx], seconds)"""
    st, table, members = Strings(), bytearray(), []
    for c in crates:
        table += struct.pack("<6I", st(c["name"]), st(c.get("sub", "")), st(c.get("section", "")),
                             len(members), len(c["members"]), int(c.get("seconds", 0)))
        members += c["members"]
    out = bytearray(b"CRT1") + struct.pack("<3I", len(crates), len(members), len(st.blob))
    out += table + np.asarray(members, dtype="<u4").tobytes() + st.blob
    path.write_bytes(bytes(out))
    return {"crates": len(crates), "members": len(members), "bytes": len(out)}


def _server():
    import server  # the web player's backend: same genres, OSTs, taste model
    return server


# ----------------------------------------------------------------------------- explore
def build_explore(out_dir, vids):
    srv = _server()
    idx = {v: i for i, v in enumerate(vids)}
    with srv.app.app_context():
        E = srv.emb()
        prefs, taste, _skip = srv.personalization()
        counts = (prefs or {}).get("play_counts", {})
        tpref = (prefs or {}).get("track", {})
        now = time.time()
        last = {r[0]: (r[1] or 0) for r in srv.db().execute(
            "SELECT video_id, MAX(ts) FROM plays GROUP BY video_id")}
        order = None
        if E["X"] is not None and taste is not None:
            order = np.argsort(-np.asarray(E["X"] @ taste, dtype="float32"))

        def taste_pick(pred, cap):            # = server.explore's, but only songs on the card
            out = []
            for j in (order if order is not None else ()):
                v = E["ids"][int(j)]
                if short_id(v) in idx and pred(v):
                    out.append(v)
                    if len(out) >= cap:
                        break
            return out

        fresh = taste_pick(lambda v: counts.get(v, 0) == 0, EXPLORE_POOL["fresh"])
        deep = taste_pick(lambda v: 1 <= counts.get(v, 0) <= 3 and tpref.get(v, 0.0) >= 0,
                          EXPLORE_POOL["deep"])
        forgotten = sorted((v for v, sc in tpref.items()
                            if sc > 0.4 and short_id(v) in idx and now - last.get(v, 0) > 21 * 86400),
                           key=lambda v: -tpref[v])[:EXPLORE_POOL["forgotten"]]
    shelves = [("Fresh finds", "unheard, matched to your taste", fresh),
               ("Deep cuts", "barely played, the model says yes", deep),
               ("Forgotten favorites", "loved, gone quiet for 3+ weeks", forgotten)]
    crates = [{"name": t, "sub": s, "members": [idx[short_id(v)] for v in ids]}
              for t, s, ids in shelves if ids]
    rep = write_crates(out_dir / "explore.bin", crates)
    print(f"  explore: " + ", ".join(f"{c['name']} {len(c['members'])}" for c in crates))
    return rep


# ----------------------------------------------------------------------------- OSTs
def build_osts(out_dir, vids, recs):
    srv = _server()
    idx = {v: i for i, v in enumerate(vids)}
    with srv.app.app_context():
        payload, members = srv._ost_index()
    crates = []
    for o in payload:
        m = [idx[short_id(v)] for v in members.get(o["name"].lower(), []) if short_id(v) in idx]
        if len(m) < MIN_OST_ON_CARD:
            continue
        secs = int(sum(int(recs[i, 5] & 0xFFFF) for i in m))
        crates.append({"name": o["name"], "section": o.get("section", ""), "members": m,
                       "seconds": secs})
    rep = write_crates(out_dir / "osts.bin", crates)
    print(f"  osts: {len(crates)} soundtracks with >= {MIN_OST_ON_CARD} songs on the card "
          f"(of {len(payload)})")
    return rep


# ----------------------------------------------------------------------------- genres
def build_genres(out_dir, vids, recs, strings):
    srv = _server()

    def s_at(off):
        return strings[off:strings.index(b"\0", off)].decode("utf-8")

    by = {}
    for i in range(len(vids)):
        g = srv.genre_of(s_at(int(recs[i, 2]))) or "unlabeled"
        by.setdefault(g, []).append(i)
    names = sorted(by, key=lambda g: (g == "unlabeled", -len(by[g]), g))
    crates = [{"name": g, "members": by[g],
               "seconds": int(sum(int(recs[i, 5] & 0xFFFF) for i in by[g]))} for g in names]
    rep = write_crates(out_dir / "genres.bin", crates)
    gid = np.full(len(vids), 255, dtype="u1")
    for k, g in enumerate(names[:255]):
        gid[by[g]] = k
    (out_dir / "genre_of.bin").write_bytes(gid.tobytes())
    print(f"  genres: {len(names)} (" + ", ".join(f"{g} {len(by[g])}" for g in names[:6]) + " ...)")
    return rep


# ----------------------------------------------------------------------------- search
def fold(s):
    """What letter-picking can type: a-z 0-9, accents stripped, everything else a space."""
    s = unicodedata.normalize("NFKD", s or "").lower()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def build_search(out_dir, vids, recs, strings, db_path):
    r"""SRC1 word-prefix index (little-endian), streamed by firmware/ui/search.c:
      "SRC1" u32 n_words | u32 n_post | u32 n_tracks | u32 words_len | u32 fold_len
      n_words  x 12B { u32 word_off, u32 post_first, u32 post_count }   sorted by word
      n_post   x u32 (pack_idx << 2 | field)  field 0 title, 1 artist, 2 album;
                     per word most-played first
      n_tracks x u16 plays (PC history, capped) for the personal boost; padded to 4 bytes
      n_tracks x u32 fold_off into the fold blob
      words blob: NUL-terminated folded words
      fold blob:  per track "title\x01artist\x01album\0", folded, in pack order
    Folded = what letter-picking can type: a-z 0-9, accents stripped, rest -> space.
    """
    def s_at(off):
        return strings[off:strings.index(b"\0", off)].decode("utf-8")

    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    plays = {}
    for vid, n in con.execute("SELECT video_id, COUNT(*) FROM plays GROUP BY video_id"):
        plays[short_id(vid)] = plays.get(short_id(vid), 0) + n
    con.close()
    pc = np.array([min(65535, plays.get(v, 0)) for v in vids], dtype="<u2")
    words, fold_blob, fold_off = {}, bytearray(), []
    for i in range(len(vids)):
        f3 = [fold(s_at(int(recs[i, k]))) for k in (1, 2, 3)]   # title, artist, album
        fold_off.append(len(fold_blob))
        fold_blob += "\x01".join(f3).encode("ascii") + b"\0"
        for field, f in enumerate(f3):
            for w in f.split():
                words.setdefault(w, {}).setdefault(i, field)   # title > artist > album
    wblob, table, post = bytearray(), bytearray(), []
    for w in sorted(words):
        items = sorted(words[w].items(), key=lambda kv: (-int(pc[kv[0]]), kv[1], kv[0]))
        table += struct.pack("<3I", len(wblob), len(post), len(items))
        wblob += w.encode("ascii") + b"\0"
        post += [(i << 2) | f for i, f in items]
    out = bytearray(b"SRC1") + struct.pack("<5I", len(words), len(post), len(vids), len(wblob),
                                           len(fold_blob))
    out += table + np.asarray(post, dtype="<u4").tobytes()
    out += pc.tobytes() + (b"\0\0" if len(vids) % 2 else b"")
    out += np.asarray(fold_off, dtype="<u4").tobytes() + wblob + fold_blob
    (out_dir / "search.bin").write_bytes(bytes(out))
    print(f"  search: {len(words)} words, {len(post)} postings, {len(out) / 1e6:.1f} MB")
    return {"words": len(words), "postings": len(post), "bytes": len(out)}


def build_all(out_dir, pack_dir, db_path):
    out_dir, pack_dir = Path(out_dir), Path(pack_dir)
    vids, recs, strings = read_pack(pack_dir)
    random.seed(1)
    return {"explore": build_explore(out_dir, vids),
            "osts": build_osts(out_dir, vids, recs),
            "genres": build_genres(out_dir, vids, recs, strings),
            "search": build_search(out_dir, vids, recs, strings, db_path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="card root (writes <out>/.coda/)")
    ap.add_argument("--pack", default=None, help="default: <out>/.coda/pack, else data/device_pack")
    a = ap.parse_args()
    out_dir = Path(a.out) / ".coda"
    pack = Path(a.pack) if a.pack else (out_dir / "pack" if (out_dir / "pack" / "pack.json").exists() else PACK)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rep = build_all(out_dir, pack, ROOT / "data" / "library.db")
    print(json.dumps(rep), f"({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
