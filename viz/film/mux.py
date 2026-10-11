#!/usr/bin/env python3
"""Build the film's master audio from real clips + cues, then mux with rendered frames.

  python viz/film/mux.py audio          # build assets/master.m4a only (fast, testable)
  python viz/film/mux.py video [fps]    # frames/ + master -> embedding_space_film.mp4
"""
import json, os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FF = r"C:\Users\hasan\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
if not os.path.exists(FF):
    import shutil; FF = shutil.which("ffmpeg") or "ffmpeg"


def build_audio():
    c = json.loads((HERE / "audio_cues.json").read_text())
    dur, cues = c["dur"], c["cues"]
    ins, filt, mixn = [], [], []
    for i, q in enumerate(cues):
        f = HERE / "assets" / f"clip_{q['id']}.m4a"
        if not f.exists():
            print("  ! missing", f.name); continue
        ins += ["-i", str(f)]
        ms = int(q["at"] * 1000)
        d = q["dur"]
        k = len(mixn)
        filt.append(
            f"[{k}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"atrim=0:{d:.2f},volume={q['gain']:.2f},"
            f"afade=t=in:d=0.35,afade=t=out:st={max(0.4,d-0.5):.2f}:d=0.5,"
            f"adelay={ms}:all=1[a{k}]")
        mixn.append(f"[a{k}]")
    fc = ";".join(filt) + ";" + "".join(mixn) + \
        f"amix=inputs={len(mixn)}:normalize=0:dropout_transition=0[mx];" \
        f"[mx]apad,atrim=0:{dur:.2f},alimiter=limit=0.92,aresample=44100[out]"
    out = HERE / "assets" / "master.m4a"
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "error", *ins,
           "-filter_complex", fc, "-map", "[out]", "-c:a", "aac", "-b:a", "256k", str(out)]
    subprocess.run(cmd, check=True)
    print(f"built {out}  ({out.stat().st_size/1e6:.2f} MB, {len(mixn)} clips over {dur}s)")
    return out


def build_video(fps):
    master = HERE / "assets" / "master.m4a"
    if not master.exists():
        build_audio()
    frames = HERE / "frames"
    nf = len(list(frames.glob("*.png")))
    if nf == 0:
        print("no frames — run: node viz/film/capture.js render", fps); return
    out = HERE / "embedding_space_film.mp4"
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", str(fps), "-i", str(frames / "%05d.png"),
           "-i", str(master),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
           "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(out)]
    print(f"muxing {nf} frames @ {fps}fps + audio ...")
    subprocess.run(cmd, check=True)
    print(f"wrote {out}  ({out.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "audio"
    if mode == "audio":
        build_audio()
    else:
        build_video(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
