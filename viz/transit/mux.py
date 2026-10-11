#!/usr/bin/env python3
"""Assemble the soundtrack from audio_cues.json and mux with rendered frames
-> wayfinding_film.mp4.  Run after `node capture.js render 30`."""
import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
FFMPEG = r"C:\Users\hasan\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
if not os.path.exists(FFMPEG):
    import shutil
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"

DUR = 129
FPS = 30

cues = json.loads((HERE / "audio_cues.json").read_text())
if isinstance(cues, dict):
    cues = cues["cues"]

inputs, filters, tags = [], [], []
for k, c in enumerate(cues):
    clip = HERE / "assets" / f"clip_{c['id']}.m4a"
    assert clip.exists(), clip
    inputs += ["-i", str(clip)]
    d = min(c["dur"], 6.5)
    st = max(0.05, d - 0.3)
    filters.append(
        f"[{k}:a]atrim=0:{d:.2f},volume={c['gain']:.2f},"
        f"afade=t=out:st={st:.2f}:d=0.3,adelay={int(c['at']*1000)}:all=1[a{k}]")
    tags.append(f"[a{k}]")

fc = ";".join(filters) + f";{''.join(tags)}amix=inputs={len(cues)}:normalize=0,apad,atrim=0:{DUR}[out]"
master = HERE / "master.m4a"
subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *inputs,
                "-filter_complex", fc, "-map", "[out]",
                "-c:a", "aac", "-b:a", "160k", str(master)], check=True)
print(f"master: {master.stat().st_size/1e6:.2f} MB")

out = HERE / "wayfinding_film.mp4"
subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                "-framerate", str(FPS), "-i", str(HERE / "frames" / "%05d.png"),
                "-i", str(master),
                "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-c:a", "copy", "-shortest", str(out)], check=True)
print(f"wrote {out}  ({out.stat().st_size/1e6:.1f} MB)")
