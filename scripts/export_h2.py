r"""Fill the HiFi Walker H2's card: songs + everything Coda needs (docs/H2_APP_PLAN.md).

  .venv\Scripts\python scripts\export_h2.py --card E:\                    # fill the card
  .venv\Scripts\python scripts\export_h2.py --card D:\h2stage --budget-gb 2   # small test
  .venv\Scripts\python scripts\export_h2.py --card E:\ --verify            # read everything back

Steps (each resumable; re-running only does what changed):
  1. select   which songs fit: everything if the card is big enough, else your played
              songs first, then their sonic neighbours outward (autoplay's candidates),
              then the rest. Estimate = audio without the big PNG cover + app data.
  2. pack     /.coda/pack: the device pack for exactly that subset, card-layout paths
              (scripts/h2_layout.py), neighbours recomputed inside the subset so autoplay
              never reaches a song that isn't on the card.
  3. assets   /.coda: fonts, covers, artist index, play log (scripts/h2_assets.py), Explore
              shelves, soundtracks, genres and the search index (scripts/h2_crates.py).
  4. music    /Music/<Letter>/<Artist>/<Title> [id].opus -- the audio bit-identical, the
              1280x720 PNG cover swapped for a 240px baseline JPEG (Rockbox reads JPEG
              only), R128 tags replaced by REPLAYGAIN = min(0, r128 + 9) dB (Rockbox gives
              R128 priority, and this is the web player's -14 LUFS attenuate-only level).
  5. prune    songs from an earlier run that are no longer selected (our folders only).
Manifest /.coda/music.tsv records what's on the card; --verify re-reads every file
(also exposes fake-capacity cards, which silently wrap writes).
"""
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")   # workers each load numpy; a thread pool per
                                                    # worker exhausted RAM and hung the copy
import argparse
import base64
import csv
import hashlib
import struct
from datetime import datetime
import io
import os
import shutil
import sqlite3
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_device_pack as edp  # noqa: E402
import h2_assets  # noqa: E402
import h2_crates  # noqa: E402
import h2_sync  # noqa: E402
from h2_layout import short_id  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "library.db"
EMB = ROOT / "data" / "muq_embeddings.npz"
FULL_PACK = ROOT / "data" / "device_pack"
LISTENS = ROOT / "data" / "listens.csv"          # every YouTube Music listen (merge_takeout.py)
WHEEL_MAX = 512
ART_FRACTION_KEPT = 0.80        # measured: the PNG cover is ~20.7% of library bytes
APPDATA_PER_TRACK = 85_000      # cover store 82KB + pack ~2KB
COVER_PX = 240
LETTER_DIRS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ") | {"0-9", "#"}


# ----------------------------------------------------------------------------- 1. select
def load_rows():
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=15)
    rows = con.execute("SELECT video_id, path, r128_gain_db, album_gain_db FROM tracks").fetchall()
    plays = con.execute("""SELECT video_id, count(*) FROM plays
                           WHERE event IN ('play','complete','like') GROUP BY video_id
                           ORDER BY count(*) DESC, max(ts) DESC""").fetchall()
    con.close()
    return rows, plays


def ytm_recent():
    """What you played on YouTube Music, newest first, each song once: the web's
    /api/speeddial order (its Wheel and Home's Listen again). [] without a Takeout."""
    try:
        with open(LISTENS, encoding="utf-8-sig", newline="") as f:
            ev = []
            for r in csv.DictReader(f):
                try:
                    ev.append((datetime.fromisoformat(r["time"]).timestamp(), r["video_id"]))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    ev.sort(reverse=True)
    seen, out = set(), []
    for _ts, v in ev:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def build_wheel(coda, vids, recent):
    """/.coda/wheel.bin: the Wheel's songs, newest first, as pack indices of this card."""
    idx = {v: i for i, v in enumerate(vids)}
    order = [idx[short_id(v)] for v in recent if short_id(v) in idx][:WHEEL_MAX]
    (coda / "wheel.bin").write_bytes(b"CWH1" + struct.pack(f"<I{len(order)}I", len(order), *order))
    print(f"  wheel: {len(order)} songs from your YouTube Music history (newest first)")


def neighbor_lists(vids_wanted):
    """vid -> neighbour vids (best first) from the full device pack, if present."""
    try:
        meta = __import__("json").loads((FULL_PACK / "pack.json").read_text())
        n, k = meta["tracks"], meta["k"]
        ids = (FULL_PACK / "ids.bin").read_bytes()
        pvid = [ids[i * 11:(i + 1) * 11].decode() for i in range(n)]
        nb = np.fromfile(FULL_PACK / "neighbors.bin", dtype="<u4").reshape(n, k)
    except (OSError, KeyError, ValueError):
        return {}
    out = {}
    for i, v in enumerate(pvid):
        if v in vids_wanted:
            out[v] = [pvid[j] for j in nb[i] if j != 0xFFFFFFFF]
    return out


def select(rows, plays, budget, recent=()):
    size = {}
    for vid, path, *_ in rows:
        try:
            size[vid] = int(os.path.getsize(path) * ART_FRACTION_KEPT) + APPDATA_PER_TRACK
        except OSError:
            pass
    total = sum(size.values())
    if total <= budget:
        print(f"select: everything fits ({len(size)} songs, ~{total / 1e9:.1f} GB)")
        return set(size), total
    nbrs = neighbor_lists(set(size))
    chosen, used = [], 0
    have = set()

    def take(v):
        nonlocal used
        if v in have or v not in size or used + size[v] > budget:
            return False
        have.add(v)
        chosen.append(v)
        used += size[v]
        return True

    for v in recent:                                     # 1) your YouTube Music, newest first
        take(v)
    for v, _ in plays:                                   #    and what you play here
        take(v)
    frontier = list(chosen)
    while frontier and used < budget * 0.995:            # 2) their neighbours, rank by rank
        new = []
        for r in range(120):
            for u in frontier:
                lst = nbrs.get(u, [])
                if r < len(lst) and take(lst[r]):
                    new.append(lst[r])
            if used >= budget * 0.995:
                break
        frontier = new
    rest = [v for v in size if v not in have]            # 3) the rest, shuffled
    np.random.default_rng(7).shuffle(rest)
    for v in rest:
        if used >= budget * 0.995:
            break
        take(v)
    print(f"select: {len(chosen)} of {len(size)} songs (~{used / 1e9:.1f} GB; "
          f"{sum(1 for v in recent if v in have)} from your YouTube Music history, "
          f"{sum(1 for v, _ in plays if v in have)} played here, rest by sonic neighbourhood)")
    return have, used


# ----------------------------------------------------------------------------- 4. music
def transform(args):
    """Card copy of one file: same audio packets, small JPEG cover, ReplayGain tags."""
    src, gain_db, album_gain_db = args
    from mutagen.flac import Picture
    from mutagen.oggopus import OggOpus
    from PIL import Image
    data = open(src, "rb").read()
    bio = io.BytesIO(data)
    f = OggOpus(bio)
    tags = f.tags
    newpic = None
    pics = tags.get("metadata_block_picture", [])
    if pics:
        try:
            im = Image.open(io.BytesIO(Picture(base64.b64decode(pics[0])).data)).convert("RGB")
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
            im = im.resize((COVER_PX, COVER_PX), Image.LANCZOS)
            jb = io.BytesIO()
            im.save(jb, "JPEG", quality=85, optimize=True, progressive=False)
            p = Picture()
            p.type, p.mime, p.width, p.height, p.depth = 3, "image/jpeg", COVER_PX, COVER_PX, 24
            p.data = jb.getvalue()
            newpic = base64.b64encode(p.write()).decode("ascii")
        except Exception:
            newpic = None
    drop = {"metadata_block_picture", "r128_track_gain", "r128_album_gain", "replaygain_track_gain",
            "replaygain_album_gain", "replaygain_track_peak", "replaygain_album_peak"}
    for key in list(tags.keys()):
        if key.lower() in drop:
            del tags[key]
    if gain_db is not None:
        tags["REPLAYGAIN_TRACK_GAIN"] = f"{min(0.0, gain_db + 9.0):.2f} dB"
    if album_gain_db is not None:
        tags["REPLAYGAIN_ALBUM_GAIN"] = f"{min(0.0, album_gain_db + 9.0):.2f} dB"
    if newpic:
        tags["METADATA_BLOCK_PICTURE"] = [newpic]
    f.save(bio)
    return bio.getvalue()


def audio_digest(blob):
    """sha1 over every Ogg packet after OpusHead/OpusTags -- must match source and copy."""
    from mutagen.ogg import OggPage
    bio = io.BytesIO(blob)
    h = hashlib.sha1()
    packets, partial = 0, b""
    while True:
        try:
            page = OggPage(bio)
        except Exception:
            break
        for i, pk in enumerate(page.packets):
            if i == 0 and page.continued:
                pk = partial + pk
                partial = b""
            last = i == len(page.packets) - 1
            if last and not page.complete:
                partial = pk
                continue
            packets += 1
            if packets > 2:
                h.update(pk)
        h.update(str(page.position).encode() if page.last else b"")
    return h.hexdigest()


def read_manifest(path):
    m = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                m[parts[0]] = (parts[1], int(parts[2]))
    return m


def write_manifest(path, m):
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(f"{v}\t{r}\t{s}\n" for v, (r, s) in sorted(m.items())), encoding="utf-8")
    os.replace(tmp, path)


def copy_music(card, plan, workers):
    """plan: [(vid, src, relpath, gain, album_gain)] in pack order."""
    man_path = card / ".coda" / "music.tsv"
    man = read_manifest(man_path)
    todo = []
    for vid, src, rel, g, ag in plan:
        dst = card / "Music" / rel
        old = man.get(vid)
        if old and old[0] == rel and dst.exists() and dst.stat().st_size == old[1]:
            continue
        todo.append((vid, src, rel, g, ag))
    print(f"music: {len(plan) - len(todo)} already on the card, {len(todo)} to copy")
    if not todo:
        return man
    t0, done, bytes_out, last_save = time.time(), 0, 0, time.time()
    with Pool(workers) as pool:
        it = pool.imap(transform, [(src, g, ag) for _, src, _, g, ag in todo], chunksize=4)
        for (vid, src, rel, g, ag), blob in zip(todo, it):
            dst = card / "Music" / rel
            if shutil.disk_usage(card).free < len(blob) + 64 * 2**20:
                print("  card full -- stopping (re-run with a smaller --budget-gb)")
                break
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(blob)
            man[vid] = (rel, len(blob))
            done += 1
            bytes_out += len(blob)
            if time.time() - last_save > 30:
                write_manifest(man_path, man)
                last_save = time.time()
                rate = bytes_out / (time.time() - t0)
                left = sum(1 for _ in todo) - done
                print(f"  {done}/{len(todo)}  {rate / 1e6:.1f} MB/s  ~{left * (bytes_out / done) / rate / 60:.0f} min left",
                      flush=True)
    write_manifest(man_path, man)
    print(f"music: wrote {done} files, {bytes_out / 1e9:.2f} GB in {(time.time() - t0) / 60:.1f} min")
    return man


def prune(card, keep_rel):
    keep = {r.casefold() for r in keep_rel}
    music = card / "Music"
    removed = 0
    if not music.exists():
        return 0
    for top in music.iterdir():
        if not top.is_dir() or top.name not in LETTER_DIRS:
            continue                                     # never touch folders we didn't make
        for dirpath, dirnames, filenames in os.walk(top, topdown=False):
            for fn in filenames:
                p = Path(dirpath) / fn
                rel = p.relative_to(music).as_posix()
                if fn.endswith(".opus") and rel.casefold() not in keep:
                    p.unlink()
                    removed += 1
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
    if removed:
        print(f"prune: removed {removed} songs no longer selected")
    return removed


ROCKBOX_SETTINGS = {
    # Rockbox's default is "track shuffle" = album gain when not shuffling; Coda's
    # level is per track (REPLAYGAIN_TRACK_GAIN = the web player's -14 LUFS level)
    "replaygain type": "track",
    # Coda draws its own clock + battery; Rockbox's bar would sit on top of Coda OS's
    # USB screen (and is redundant in its menus)
    "statusbar": "off",
}


def set_rockbox_config(card):
    """Set a few lines in /.rockbox/config.cfg (Rockbox reads it at boot)."""
    cfg = card / ".rockbox" / "config.cfg"
    lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines() if cfg.exists() else []
    keys = set()
    for i, line in enumerate(lines):
        k = line.split(":", 1)[0].strip()
        if k in ROCKBOX_SETTINGS:
            lines[i] = f"{k}: {ROCKBOX_SETTINGS[k]}"
            keys.add(k)
    lines += [f"{k}: {v}" for k, v in ROCKBOX_SETTINGS.items() if k not in keys]
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("rockbox config:", ", ".join(f"{k}={v}" for k, v in ROCKBOX_SETTINGS.items()))


def verify(card, plan):
    man = read_manifest(card / ".coda" / "music.tsv")
    bad = 0
    t0 = time.time()
    for n, (vid, src, rel, g, ag) in enumerate(plan, 1):
        dst = card / "Music" / rel
        if vid not in man or not dst.exists() or dst.stat().st_size != man[vid][1]:
            bad += 1
            continue
        if n % 50 == 1:                                  # audio identity, sampled
            if audio_digest(dst.read_bytes()) != audio_digest(open(src, "rb").read()):
                bad += 1
                print("  audio differs:", rel)
        else:
            from mutagen.oggopus import OggOpus
            try:
                OggOpus(str(dst))
            except Exception:
                bad += 1
                print("  unreadable:", rel)
        if n % 2000 == 0:
            print(f"  verified {n}/{len(plan)} ({time.time() - t0:.0f}s)", flush=True)
    print(f"verify: {len(plan) - bad}/{len(plan)} OK" + ("" if not bad else f", {bad} BAD"))
    return bad


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True, help="card root, e.g. E:\\")
    ap.add_argument("--budget-gb", type=float, default=None,
                    help="cap for songs + app data (default: free space + what we already put there, minus 1GB)")
    ap.add_argument("--workers", type=int, default=4, help="card writes (~17MB/s) are the bottleneck")
    ap.add_argument("--rock", default=None,
                    help="coda.rock to install (default firmware/rockbox/out/coda.rock from build.sh target)")
    ap.add_argument("--verify", action="store_true", help="only re-read what's on the card")
    ap.add_argument("--skip-music", action="store_true", help="pack + assets only")
    ap.add_argument("--only-present", action="store_true",
                    help="make the card consistent with the songs already copied (after an "
                         "interrupted run): pack + assets for exactly those, no copying")
    a = ap.parse_args()
    card = Path(a.card)
    coda = card / ".coda"
    coda.mkdir(parents=True, exist_ok=True)
    rows, plays = load_rows()
    recent = ytm_recent()
    by_vid = {short_id(r[0]): r for r in rows}       # pack ids.bin holds short ids

    if a.budget_gb is not None:
        budget = int(a.budget_gb * 1e9)
    else:
        ours = sum(s for _, s in read_manifest(coda / "music.tsv").values())
        ours += sum(p.stat().st_size for p in coda.glob("art_*.bin"))
        budget = shutil.disk_usage(card).free + ours - 10**9
    print(f"card {card}: budget {budget / 1e9:.1f} GB")

    if a.only_present:
        long_of = {short_id(r[0]): r[0] for r in rows}
        man = read_manifest(coda / "music.tsv")
        chosen = {long_of[v] for v, (rel, size) in man.items()
                  if v in long_of and (card / "Music" / rel).exists()}
        print(f"only-present: {len(chosen)} songs already on the card")
        a.skip_music = True
    if not a.verify:
        print("sync device plays ...")   # before the pack (indexes) and plays.omp are rebuilt
        h2_sync.sync(card)
    if a.verify:
        pass
    elif a.only_present:
        print("pack ...")
        edp.build_pack(str(DB), str(EMB), str(coda / "pack"), 120, only_ids=chosen, layout="h2", engine=3)
    else:
        chosen, _ = select(rows, plays, budget, recent)
        print("pack ...")
        edp.build_pack(str(DB), str(EMB), str(coda / "pack"), 120, only_ids=chosen, layout="h2", engine=3)
    meta, vids, strings = h2_assets.read_pack(coda / "pack")
    recs = np.fromfile(coda / "pack" / "tracks.bin", dtype="<u4").reshape(-1, 6)

    def s_at(off):
        return strings[off:strings.index(b"\0", off)].decode("utf-8")

    plan = [(v, by_vid[v][1], s_at(int(recs[i, 0])), by_vid[v][2], by_vid[v][3])
            for i, v in enumerate(vids) if v in by_vid]
    if a.verify:
        sys.exit(1 if verify(card, plan) else 0)

    print("assets ...")
    h2_assets.build_glyphs(coda, strings)
    h2_assets.build_plays(coda, vids)
    build_wheel(coda, vids, recent)
    h2_assets.build_artists(coda, coda / "pack", meta["tracks"])
    h2_assets.build_art(coda, vids)
    h2_crates.build_all(coda, coda / "pack", DB)      # explore / OSTs / genres / search
    rock = Path(a.rock) if a.rock else ROOT / "firmware" / "rockbox" / "out" / "coda.rock"
    if rock.exists() and (card / ".rockbox").exists():
        dst = card / ".rockbox" / "rocks" / "apps"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(rock, dst / "coda.rock")
        print("installed", dst / "coda.rock")
        set_rockbox_config(card)
    if a.skip_music:
        return
    prune(card, [p[2] for p in plan])
    copy_music(card, plan, a.workers)
    print("done. On the H2: Plugins > Applications > coda")


if __name__ == "__main__":
    main()
