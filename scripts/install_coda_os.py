r"""Put Coda OS on the H2's card -- or take it off again. The bootloader is never touched:
Coda OS is just a different /.rockbox folder (firmware/rockbox/out/coda-os*.zip, built by
firmware/rockbox/os/build_os.sh).

  .venv\Scripts\python scripts\install_coda_os.py --card E:\            # Coda OS
  .venv\Scripts\python scripts\install_coda_os.py --card E:\ --strip    # no Rockbox UI at all
  .venv\Scripts\python scripts\install_coda_os.py --card E:\ --revert   # back to what was there

Install renames the current /.rockbox to /.rockbox.prev (instant, nothing deleted), unpacks
the Coda OS build as the new /.rockbox, and carries your Rockbox settings across
(config.cfg: volume, ReplayGain, clock format...). Revert swaps the two folders back.
"""
import argparse
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "firmware" / "rockbox" / "out"
KEEP = ("config.cfg", ".resume.cfg", ".playlist_control", "playername.txt", "most-recent.bmark")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True)
    ap.add_argument("--strip", action="store_true", help="the build with no Rockbox UI left")
    ap.add_argument("--revert", action="store_true")
    a = ap.parse_args()
    card = Path(a.card)
    cur, prev = card / ".rockbox", card / ".rockbox.prev"
    if a.revert:
        if not prev.exists():
            sys.exit("nothing to revert: no /.rockbox.prev on the card")
        shutil.rmtree(cur) if cur.exists() else None
        prev.rename(cur)
        print("reverted: the previous /.rockbox is back")
        return
    z = OUT / ("coda-os-strip.zip" if a.strip else "coda-os.zip")
    if not z.exists():
        sys.exit(f"{z} missing: build it with firmware/rockbox/os/build_os.sh")
    if not cur.exists():
        sys.exit(f"{cur} missing: is this the H2's card?")
    if prev.exists():
        sys.exit("/.rockbox.prev already exists (Coda OS installed?). --revert first.")
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
        if not any(n.startswith(".rockbox/rockbox.") for n in names):
            sys.exit(f"{z} has no .rockbox/rockbox.* firmware file")
        cur.rename(prev)
        zf.extractall(card)
    for k in KEEP:
        if (prev / k).exists():
            shutil.copy2(prev / k, cur / k)
    print(f"installed {z.name} -> {cur}  (the old one is {prev})")
    print("Eject the card, put it in the H2, power on: the boot animation, then Coda.")
    print("Way out to Rockbox's menu (not in --strip): hold Menu + Back for 1.5 s.")


if __name__ == "__main__":
    main()
