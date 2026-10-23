#!/usr/bin/env python3
r"""Keep the H2's card up to date on its own: whatever has been downloaded gets ready for
the card in the background (tags, loudness, the index, MuQ, analysis), and the moment the
card is in the reader it's synced (scripts/export_h2.py), then ejected -- plug it in, wait
for "Card updated", take it out. Stays running until the soundtrack downloads are done and
the card has had everything, then exits.

  .venv\Scripts\python scripts\h2_autosync.py              # run (detached: see below)
  .venv\Scripts\python scripts\h2_autosync.py --prepare    # just the preparation, once

Start it so it outlives the terminal:
  Start-Process .venv\Scripts\python.exe -ArgumentList scripts\h2_autosync.py -WindowStyle Hidden

State: data/h2_autosync.json (what was prepared and what the card last got); log:
data/logs/h2_autosync.log. A failed sync isn't retried for the same state (the card stays
in, the log says why).
"""
import argparse
import json
import shutil
import string
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
LIB = Path(r"D:\OfflineMusic")
DB = ROOT / "data" / "library.db"
STATE = ROOT / "data" / "h2_autosync.json"
LOG = ROOT / "data" / "logs" / "h2_autosync.log"
OST_CSV = ROOT / "data" / "ost_playlists.csv"
PREPARE_EVERY = 30 * 60          # while downloads run, get new songs ready this often
COLOSSEUM_NEW = "Pokémon Colosseum"
COLOSSEUM_OLD = "Pokémon Colosseum (OST)"     # the chapter-cut rip it replaces


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(args, timeout=4 * 3600):
    log("  $ " + " ".join(str(a) for a in args))
    env = dict(__import__("os").environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", HF_HUB_DISABLE_PROGRESS_BARS="1")
    with LOG.open("a", encoding="utf-8") as fh:
        try:
            p = subprocess.run(args, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, env=env, timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = -9
    if rc:
        log(f"  exit {rc}")
    return rc


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(st):
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def running(pattern):
    """is a python process with `pattern` in its command line running?"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          f"Where-Object {{ $_.CommandLine -match '{pattern}' }} | Measure-Object | Select-Object -ExpandProperty Count")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
        return int((out.stdout or "0").strip() or 0) > 0
    except (subprocess.SubprocessError, ValueError):
        return False


def n_files():
    return sum(1 for _ in LIB.glob("*.opus"))


def find_card():
    """the H2's card in a reader: a drive with Coda's library and Coda OS on it"""
    for d in string.ascii_uppercase[3:]:
        root = Path(f"{d}:\\")
        try:
            if (root / ".coda" / "pack" / "pack.json").exists() and (root / ".rockbox" / "rockbox.erosq").exists():
                return root
        except OSError:
            continue
    return None


def colosseum_swap():
    """the full Colosseum rip is in: the chapter-cut one goes to _purged (rows logged)"""
    import sqlite3
    con = sqlite3.connect(DB, timeout=60)
    new = con.execute("SELECT count(*) FROM tracks WHERE album=?", (COLOSSEUM_NEW,)).fetchone()[0]
    old = con.execute("SELECT video_id, path, title, artist, album FROM tracks WHERE album=?", (COLOSSEUM_OLD,)).fetchall()
    if new < 40 or not old:
        con.close()
        return
    dest = LIB / "_purged"
    dest.mkdir(exist_ok=True)
    with (ROOT / "data" / "purged_rows.jsonl").open("a", encoding="utf-8") as fh:
        for vid, path, title, artist, album in old:
            p = Path(path)
            if p.exists():
                shutil.move(str(p), str(dest / p.name))
            fh.write(json.dumps({"video_id": vid, "path": path, "title": title, "artist": artist, "album": album,
                                 "why": "replaced by the full Colosseum rip (2026-10-15)"}, ensure_ascii=False) + "\n")
            con.execute("DELETE FROM tracks WHERE video_id=?", (vid,))
            try:
                con.execute("DELETE FROM tracks_fts WHERE video_id=?", (vid,))
            except sqlite3.Error:
                pass
    con.commit()
    con.close()
    log(f"Colosseum: {len(old)} chapter-cut tracks moved to _purged ({new} from the full rip)")


def prepare(st):
    while running("muq_run.py"):                          # one started by hand: let it finish first
        log("waiting for a running muq_run.py")
        time.sleep(120)
    files = n_files()
    log(f"prepare: {files} files in the library folder")
    if OST_CSV.exists():
        run([PY, "scripts/harvest_ost_playlists.py", "--retag", str(LIB)])
    run([PY, "scripts/scan_loudness.py"])
    run([PY, "scripts/build_library_db.py"])
    colosseum_swap()
    run([PY, "scripts/backfill_genre.py"])
    run([PY, "scripts/album_gain.py"])
    run([PY, "scripts/muq_run.py"])
    run([PY, "scripts/scan_analysis.py"])
    st["prepared_files"] = files
    st["prepared_at"] = time.time()
    st["prepared_sig"] = f"{files}@{int(st['prepared_at'])}"
    save_state(st)
    log("prepare: done")


def popup(text):
    ps = ("Add-Type -AssemblyName PresentationFramework; "
          f"[System.Windows.MessageBox]::Show('{text}', 'Coda: H2 card') | Out-Null")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps])


def eject(card):
    d = str(card)[:2]
    ps = f"(New-Object -ComObject Shell.Application).Namespace(17).ParseName('{d}').InvokeVerb('Eject')"
    for _ in range(3):                                 # something may still have a file open
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=60)
        time.sleep(5)
        if not (card / ".coda").exists():
            return True
        time.sleep(15)
    return False


def install_firmware(card, bak):
    """the newest Coda OS build onto the card, when it isn't there yet (settings carried)"""
    import hashlib
    import zipfile
    zp = ROOT / "firmware" / "rockbox" / "out" / "coda-os-bt.zip"
    if not zp.exists():
        return
    with zipfile.ZipFile(zp) as z:
        new = hashlib.sha256(z.read(".rockbox/rockbox.erosq")).hexdigest()
    cur = card / ".rockbox" / "rockbox.erosq"
    old = hashlib.sha256(cur.read_bytes()).hexdigest() if cur.exists() else ""
    if new == old:
        log(f"firmware: already {new[:8]}")
        return
    if cur.exists():
        shutil.copy2(cur, bak / ".rockbox" / "rockbox.erosq")
    rc = run([PY, "scripts/install_coda_os.py", "--card", str(card), "--zip", "coda-os-bt.zip"])
    now = hashlib.sha256(cur.read_bytes()).hexdigest() if cur.exists() else ""
    log(f"firmware: {old[:8]} -> {now[:8]} ({'ok' if rc == 0 and now == new else 'NOT as built'})")


def sync(st, card):
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    bak = ROOT / "data" / "h2_device" / f"{stamp}_pre_autosync"
    log(f"sync: card {card}, backing up its settings and logs to {bak}")
    (bak / ".coda").mkdir(parents=True, exist_ok=True)
    (bak / ".rockbox").mkdir(parents=True, exist_ok=True)
    for f in (card / ".coda").glob("*"):
        if f.is_file() and f.stat().st_size < 5_000_000:
            shutil.copy2(f, bak / ".coda" / f.name)
    for f in (card / ".rockbox").glob("*"):
        if f.is_file() and f.suffix != ".erosq" and f.stat().st_size < 1_000_000:
            shutil.copy2(f, bak / ".rockbox" / f.name)
    t0 = time.time()
    # the Wheel starts from YT Music's Listen again (scripts/ytm_sync.py, signed in, read-only):
    # fresh for this sync, with a few radios for what's new on it
    run([PY, "scripts/ytm_sync.py", "listen_again", "liked", "radios", "--max", "40"], timeout=3600)
    install_firmware(card, bak)
    # --rock: no plugin (or the plugin-era config lines): the card runs Coda OS
    rc = run([PY, "scripts/export_h2.py", "--card", str(card), "--rock", str(ROOT / "no-plugin.rock")], timeout=6 * 3600)
    if rc:
        st["failed_sig"] = st.get("prepared_sig")
        save_state(st)
        log(f"sync FAILED (exit {rc}) after {(time.time() - t0) / 60:.0f} min; the card stays in")
        popup("The card sync failed - leave the card in; the log is data\\logs\\h2_autosync.log")
        return False
    st["synced_sig"] = st.get("prepared_sig")
    st["synced_at"] = time.time()
    save_state(st)
    log(f"sync: done in {(time.time() - t0) / 60:.0f} min")
    ok = eject(card)
    log("ejected" if ok else "eject didn't take: eject it from the taskbar")
    popup("Card updated" + (" and ejected - you can take it out." if ok else " - eject it from the taskbar."))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true", help="prepare once and exit")
    a = ap.parse_args()
    st = load_state()
    if a.prepare:
        prepare(st)
        return
    log("autosync: started")
    card_seen = None
    while True:
        downloading = running("download_tracks.py")
        files = n_files()
        stale = files != st.get("prepared_files")
        if stale and (not downloading or time.time() - st.get("prepared_at", 0) > PREPARE_EVERY):
            prepare(st)
            continue
        card = find_card()
        fresh = card is not None and card != card_seen
        if fresh:
            log(f"card in: {card}")
            time.sleep(10)                                 # let Windows finish mounting it
        card_seen = card
        todo = bool(st.get("prepared_sig")) and st.get("synced_sig") != st.get("prepared_sig") \
            and st.get("failed_sig") != st.get("prepared_sig")
        if card and todo:
            popup("Updating the H2 card with the new songs and firmware - leave it in. "
                  "It takes about half an hour and ejects itself when done.")
            if n_files() != st.get("prepared_files"):
                prepare(st)                                # what came in since, onto this sync too
            ejected = sync(st, card)
            card_seen = None if ejected else card          # still in: not a new plug-in
            continue
        if fresh and not todo:
            popup("The H2 card already has everything that is ready so far - nothing to do.")
        if not downloading and not stale and st.get("synced_sig") == st.get("prepared_sig"):
            log("autosync: everything downloaded is on the card; done")
            return
        time.sleep(60)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8", errors="replace")
    main()
