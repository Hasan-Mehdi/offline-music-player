#!/usr/bin/env python3
"""Run the full evaluation/test suite and write docs/REPORT.md. One command = all tests.

Each step runs as a subprocess; failures are recorded but don't stop the run.
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

PY = r".venv\Scripts\python.exe"
STEPS = [
    ("MuQ embedding (incremental)", [PY, "scripts/muq_run.py"]),
    ("Collaborative method eval", [PY, "scripts/eval_methods.py"]),
    ("Genre map + clustering", [PY, "scripts/genre_map.py"]),
    ("VGM sub-space (app /vgm tab)", [PY, "scripts/vgm_space.py"]),
    ("Playlists (m3u)", [PY, "scripts/make_playlists.py"]),
    ("Autoplay tuning", [PY, "scripts/tune_autoplay.py"]),
    ("Visualizations", [PY, "scripts/visualize.py"]),
    ("Unit tests (pytest)", [PY, "-m", "pytest", "-q", "tests"]),
]


def run(cmd):
    env = dict(os.environ, PYTHONUTF8="1", HF_HUB_DISABLE_PROGRESS_BARS="1")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    body = (p.stdout or "")
    if p.returncode:
        body += "\n[stderr]\n" + (p.stderr or "")[-3000:]
    return p.returncode, body.strip()


def main():
    out = ["# Suite report", "", f"_generated {datetime.datetime.now():%Y-%m-%d %H:%M}_", ""]
    summary = []
    ok_all = True
    for name, cmd in STEPS:
        print(f">>> {name}", flush=True)
        rc, body = run(cmd)
        ok = rc == 0
        ok_all &= ok
        summary.append((name, ok))
        out += [f"## {name} — {'OK' if ok else f'FAIL (exit {rc})'}", "", "```",
                body[:6000] if body else "(no output)", "```", ""]
    Path("docs").mkdir(exist_ok=True)
    Path("docs/REPORT.md").write_text("\n".join(out), encoding="utf-8")
    print("\n=== summary ===")
    for name, ok in summary:
        print(f"  [{'OK' if ok else 'FAIL'}] {name}")
    print("wrote docs/REPORT.md")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
