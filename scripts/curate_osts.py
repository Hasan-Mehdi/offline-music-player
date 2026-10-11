#!/usr/bin/env python3
"""Dump the raw OST groups (name, count, sample tracks) to data/ost_groups_raw.json so an
LLM pass can flag nonsense groups and hand back clean canonical names in data/ost_catalog.json
(consumed by server._ost_index: it drops keep=false groups, renames to canonical, and merges
groups that share a canonical name). Re-run after big download batches shift the groupings.

Run:  PYTHONPATH=scripts .venv\\Scripts\\python scripts\\curate_osts.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from server import _ost_name, MIN_OST_TRACKS   # reuse the EXACT grouping the server uses

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "library.db"
OUT = ROOT / "data" / "ost_groups_raw.json"


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT title, album, artist, duration FROM tracks").fetchall()
    groups = {}
    for r in rows:
        nm = _ost_name(r["album"] or "", r["title"] or "")
        if not nm:
            continue
        g = groups.setdefault(nm.lower(), {"name": nm, "count": 0, "sec": 0.0, "samples": []})
        g["count"] += 1
        g["sec"] += r["duration"] or 0.0
        if len(g["samples"]) < 8:
            g["samples"].append({"title": r["title"], "artist": r["artist"]})
    out = [{"key": k, "name": g["name"], "count": g["count"],
            "minutes": round(g["sec"] / 60), "samples": g["samples"]}
           for k, g in groups.items() if g["count"] >= MIN_OST_TRACKS]
    out.sort(key=lambda o: -o["count"])
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT} — {len(out)} groups (>= {MIN_OST_TRACKS} tracks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
