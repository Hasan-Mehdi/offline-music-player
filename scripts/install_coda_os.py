r"""Put Coda OS on the H2's card -- or take it off again. The bootloader is never touched:
Coda OS is just a different /.rockbox folder (firmware/rockbox/out/coda-os*.zip, built by
firmware/rockbox/os/build_os.sh).

  .venv\Scripts\python scripts\install_coda_os.py --card E:\            # Coda OS
  .venv\Scripts\python scripts\install_coda_os.py --card E:\ --strip    # no Rockbox UI at all
  .venv\Scripts\python scripts\install_coda_os.py --card E:\ --revert   # back to what was there
  .venv\Scripts\python scripts\install_coda_os.py --card E:\ --zip coda-os-bt.zip   # another build

First install: the current /.rockbox becomes /.rockbox.prev (instant, nothing deleted) and
the Coda OS build is unpacked as the new /.rockbox. Later installs (a newer build, or the
other flavour) replace only the Coda OS folder; /.rockbox.prev, the firmware you had before
Coda OS, stays as it is. Your Rockbox settings (config.cfg: volume, ReplayGain, brightness,
the queue to resume...) are carried across every time. Revert swaps /.rockbox.prev back.
"""
import argparse
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "firmware" / "rockbox" / "out"
KEEP = ("config.cfg", ".resume.cfg", ".playlist_control", "playername.txt", "most-recent.bmark",
        "bt_devices.txt", "bt_config.conf")    # Bluetooth builds: paired headphones, keys


def carry(src: Path, dst: Path):
    for k in KEEP:
        if (src / k).exists():
            shutil.copy2(src / k, dst / k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True)
    ap.add_argument("--strip", action="store_true", help="the build with no Rockbox UI left")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--zip", help="a build in firmware/rockbox/out (or a path), e.g. coda-os-bt.zip")
    a = ap.parse_args()
    card = Path(a.card)
    cur, prev, old = card / ".rockbox", card / ".rockbox.prev", card / ".rockbox.old"
    if a.revert:
        if not prev.exists():
            sys.exit("nothing to revert: no /.rockbox.prev on the card")
        shutil.rmtree(cur) if cur.exists() else None
        prev.rename(cur)
        print("reverted: the previous /.rockbox is back")
        return
    z = Path(a.zip) if a.zip and Path(a.zip).exists() else OUT / (a.zip or ("coda-os-strip.zip" if a.strip else "coda-os.zip"))
    if not z.exists():
        sys.exit(f"{z} missing: build it with firmware/rockbox/os/build_os.sh")
    if not cur.exists():
        sys.exit(f"{cur} missing: is this the H2's card?")
    with zipfile.ZipFile(z) as zf:
        if not any(n.startswith(".rockbox/rockbox.") for n in zf.namelist()):
            sys.exit(f"{z} has no .rockbox/rockbox.* firmware file")
        if old.exists():                       # a previous update that didn't finish
            shutil.rmtree(old)
        if prev.exists():
            # Coda OS is already installed: swap only its folder, keep the original firmware
            cur.rename(old)
            zf.extractall(card)
            carry(old, cur)
            shutil.rmtree(old)
            print(f"updated Coda OS to {z.name} (your original firmware is still /.rockbox.prev)")
        else:
            cur.rename(prev)
            zf.extractall(card)
            carry(prev, cur)
            print(f"installed {z.name} -> {cur}  (the old one is {prev})")
    print("Eject the card, put it in the H2, power on: the boot animation, then Coda.")
    if not a.strip:
        print("Way out to Rockbox's menu: hold Menu + Back for 1.5 s.")


if __name__ == "__main__":
    main()
