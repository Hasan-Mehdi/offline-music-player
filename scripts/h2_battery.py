r"""Battery life on the H2, from the log Coda writes (/.coda/battery.csv, one line every 5 min
and on every charger change: epoch, level %, mV, mA, charger, charging, playing, screen).

  .venv\Scripts\python scripts\h2_battery.py --card E:\         # after a test run

The test: charge to full, unplug, play with autoplay (screen off, the way it'd be in a
pocket), and leave it running -- several hours, or until it shuts down. Then put the card
in the reader and run this. It reports the drain rate per state from the unplugged
stretches and what that means for a full charge (1300 mAh cell).
"""
import argparse
import csv
from datetime import datetime
from pathlib import Path


def load(path):
    rows = []
    for r in csv.reader(open(path, encoding="ascii", errors="replace")):
        if len(r) < 8:
            continue
        try:
            ts, lvl, mv, ma, ch, chg, play, scr = (int(x) for x in r[:8])
        except ValueError:
            continue
        rows.append(dict(ts=ts, lvl=lvl, mv=mv, ma=ma, charger=ch, charging=chg, playing=play,
                         screen=scr))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", default="E:\\")
    ap.add_argument("--file", default=None, help="a copied battery.csv instead of the card")
    a = ap.parse_args()
    path = Path(a.file) if a.file else Path(a.card) / ".coda" / "battery.csv"
    if not path.exists():
        raise SystemExit(f"{path}: no battery log yet (Coda writes it while it runs)")
    rows = load(path)
    print(f"{len(rows)} samples, {datetime.fromtimestamp(rows[0]['ts'])} .. "
          f"{datetime.fromtimestamp(rows[-1]['ts'])}")
    # unplugged stretches: consecutive samples with no charger
    by_state = {}
    for p, q in zip(rows, rows[1:]):
        if p["charger"] or q["charger"]:
            continue
        hours = (q["ts"] - p["ts"]) / 3600.0
        if hours <= 0 or hours > 1:                       # gaps = device off / log restarts
            continue
        key = ("playing" if p["playing"] else "idle") + (", screen on" if p["screen"] else ", screen off")
        d = by_state.setdefault(key, [0.0, 0.0, 0.0])
        d[0] += hours
        d[1] += p["lvl"] - q["lvl"]
        d[2] += (p["mv"] - q["mv"])
    if not by_state:
        print("no unplugged stretch logged yet")
        return
    print(f"{'state':28s} {'hours':>6s} {'%/h':>6s} {'mV/h':>6s}  full charge ~")
    for k, (h, dl, dmv) in sorted(by_state.items(), key=lambda kv: -kv[1][0]):
        rate = dl / h if h else 0.0
        full = f"{100.0 / rate:5.1f} h" if rate > 0 else "  n/a"
        print(f"{k:28s} {h:6.2f} {rate:6.2f} {dmv / h if h else 0:6.1f}  {full}")
    cur = [r["ma"] for r in rows if r["ma"] > 0 and not r["charger"]]
    if cur:
        avg = sum(cur) / len(cur)
        print(f"reported current (unplugged): avg {avg:.0f} mA -> 1300 mAh / avg ~ {1300 / avg:.1f} h")


if __name__ == "__main__":
    main()
