r"""Battery life on the H2, from the log Coda writes (/.coda/battery.csv, one line every 5 min
and on every charger change: epoch, level %, mV, mA, charger, charging, playing, screen;
newer firmware adds, for the 5 min before each line: CPU busy, screen lit and music playing
in per mille, then Bluetooth 0 off / 1 on / 2 connected / 3 streaming and the earbuds' %;
from 2026-10-15 the figure Coda shows, which carries on from the last one instead of
jumping up after a rest the way the gauge does).

  .venv\Scripts\python scripts\h2_battery.py --card E:\         # after a test run

The test: charge to full, unplug, play with autoplay (screen off, the way it'd be in a
pocket), and leave it running -- several hours, or until it shuts down. Then put the card
in the reader and run this. It reports the drain rate per state from the unplugged
stretches and what that means for a full charge (1300 mAh cell), and, from the newer
columns, how busy the CPU was in each state (/.coda/cpu.log says which threads it was).

The level is the power chip's own gauge (Rockbox doesn't give it the cell's model), so the
mV columns are worth reading next to it: about 4.1 V is full, 3.4 V is where it shuts off.
"""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

BT = {0: "bt off", 1: "bt on", 2: "bt connected", 3: "bt streaming"}


def load(path):
    rows = []
    for r in csv.reader(open(path, encoding="ascii", errors="replace")):
        if len(r) < 8:
            continue
        try:
            v = [int(x) for x in r]
        except ValueError:
            continue
        ts, lvl, mv, ma, ch, chg, play, scr = v[:8]
        row = dict(ts=ts, lvl=lvl, mv=mv, ma=ma, charger=ch, charging=chg, playing=play, screen=scr,
                   busy=-1, lit=-1, play_pm=-1, bt=-1, buds=-1, shown=-1)
        if len(v) >= 13:
            row.update(busy=v[8], lit=v[9], play_pm=v[10], bt=v[11], buds=v[12])
        if len(v) >= 14:
            row.update(shown=v[13])
        rows.append(row)
    return rows


def state_of(p, q):
    """what the stretch from p to q was mostly like (the newer columns describe the 5 min
    before q; the old ones only the moment of p)"""
    if q["lit"] >= 0:
        s = ("playing" if q["play_pm"] >= 500 else "idle") + (", screen on" if q["lit"] >= 500 else ", screen off")
        return s + (", " + BT[q["bt"]] if q["bt"] in BT else "")
    return ("playing" if p["playing"] else "idle") + (", screen on" if p["screen"] else ", screen off")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", default="E:\\")
    ap.add_argument("--file", default=None, help="a copied battery.csv instead of the card")
    ap.add_argument("--since", default=None, help="only lines from this date on (YYYY-MM-DD)")
    a = ap.parse_args()
    path = Path(a.file) if a.file else Path(a.card) / ".coda" / "battery.csv"
    if not path.exists():
        raise SystemExit(f"{path}: no battery log yet (Coda writes it while it runs)")
    rows = load(path)
    if a.since:
        t0 = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc).timestamp()
        rows = [r for r in rows if r["ts"] >= t0]
    if not rows:
        raise SystemExit("no samples")
    # the device keeps local wall time as if it were UTC
    when = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M")
    print(f"{len(rows)} samples, {when(rows[0]['ts'])} .. {when(rows[-1]['ts'])}")
    # unplugged stretches: consecutive samples with no charger
    by_state = {}
    for p, q in zip(rows, rows[1:]):
        if p["charger"] or q["charger"]:
            continue
        hours = (q["ts"] - p["ts"]) / 3600.0
        if hours <= 0 or hours > 1:                       # gaps = device off / log restarts
            continue
        key = state_of(p, q)
        d = by_state.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0])
        d[0] += hours
        d[1] += p["lvl"] - q["lvl"]
        d[2] += p["mv"] - q["mv"]
        if q["busy"] >= 0:
            d[3] += q["busy"]
            d[4] += 1
    if not by_state:
        print("no unplugged stretch logged yet")
        return
    print(f"{'state':44s} {'hours':>6s} {'%/h':>6s} {'mV/h':>6s} {'cpu':>6s}  full charge ~")
    for k, (h, dl, dmv, busy, nb) in sorted(by_state.items(), key=lambda kv: -kv[1][0]):
        rate = dl / h if h else 0.0
        full = f"{100.0 / rate:5.1f} h" if rate > 0 else "  n/a"
        cpu = f"{busy / nb / 10:5.1f}%" if nb else "     -"
        print(f"{k:44s} {h:6.2f} {rate:6.2f} {dmv / h if h else 0:6.1f} {cpu}  {full}")
    cur = [r["ma"] for r in rows if r["ma"] > 0 and not r["charger"]]
    if cur and len(set(cur)) > 1:                         # a constant is Rockbox's guess, not a reading
        avg = sum(cur) / len(cur)
        print(f"reported current (unplugged): avg {avg:.0f} mA -> 1300 mAh / avg ~ {1300 / avg:.1f} h")


if __name__ == "__main__":
    main()
