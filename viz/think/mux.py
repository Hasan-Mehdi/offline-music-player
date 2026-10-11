#!/usr/bin/env python3
"""Build the soundtrack from audio_cues.json and mux it onto the rendered frames
-> viz/think/think_film.mp4.

Two layers, mixed in numpy so the mp4 and the standalone html sound the same:
  1. MUSIC — the real winning tracks. The snippets in assets/ were already attenuated by
     their own r128_gain_db at build_data time (player rule: R128 -23 -> -14 LUFS,
     attenuate only), so here they are just placed and faded; relative levels are the
     player's, not ffmpeg's.
  2. PRINT-MACHINE SFX — the stamps, ticks and sweeps, synthesised to the same shapes as
     the page's WebAudio nodes, so the dilated act is not a dead silent stretch in the mp4.

Run after `node viz/think/capture.js render 30`:
    .venv\\Scripts\\python viz\\think\\mux.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FFMPEG = r"C:\Users\hasan\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"
FFPROBE = r"C:\Users\hasan\ffmpeg\ffmpeg-7.1.1-essentials_build\bin\ffprobe.exe"
if not os.path.exists(FFMPEG):
    import shutil
    FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
    FFPROBE = shutil.which("ffprobe") or "ffprobe"

SR = 44100
SFX_GAIN = 2.2          # must match think.html's SFXG so page and mp4 sound the same


# --------------------------------------------------------------------------- sfx


def biquad_bandpass(x, f0, q, sr=SR):
    """RBJ cookbook constant-skirt bandpass — the same shape as the page's
    BiquadFilterNode('bandpass'), so the mp4's clicks match the html's."""
    w0 = 2 * np.pi * f0 / sr
    alpha = np.sin(w0) / (2 * q)
    b = np.array([alpha, 0.0, -alpha])
    a = np.array([1 + alpha, -2 * np.cos(w0), 1 - alpha])
    from scipy.signal import lfilter
    return lfilter(b / a[0], a / a[0], x).astype(np.float32)


def decay(n, g0, tau):
    """WebAudio's exponentialRampToValueAtTime(0.0001, t+tau) envelope."""
    t = np.arange(n) / SR
    return (g0 * np.power(1e-4 / max(g0, 1e-6), np.minimum(t / tau, 1.0))).astype(np.float32)


def tone(dur, f0, f1, kind="sine"):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = f0 * np.power(f1 / f0, np.minimum(t / dur, 1.0))
    ph = 2 * np.pi * np.cumsum(f) / SR
    if kind == "triangle":
        return (2 / np.pi * np.arcsin(np.sin(ph))).astype(np.float32)
    return np.sin(ph).astype(np.float32)


def shaped_noise(dur, shape, seed):
    n = int(SR * dur)
    rng = np.random.default_rng(seed)
    return ((rng.random(n) * 2 - 1) * np.power(1 - np.arange(n) / n, shape)).astype(np.float32)


def make_sfx(kind, seed):
    if kind in ("stamp", "lock"):
        f0, f1 = (170, 46) if kind == "lock" else (132, 58)
        g = 0.14 if kind == "lock" else 0.10
        body = tone(0.22, f0, f1) * decay(int(SR * 0.22), g, 0.16)
        n = biquad_bandpass(shaped_noise(0.05, 2.4, seed), 2400, 1.1) * decay(int(SR * 0.05), 0.05, 0.06)
        out = body.copy()
        out[:len(n)] += n
        return out
    if kind == "tick":
        n = biquad_bandpass(shaped_noise(0.02, 2.2, seed), 2100, 1.8)
        return n * decay(len(n), 0.05, 0.05)
    if kind in ("sweep", "shhh"):
        dur = 0.42 if kind == "shhh" else 0.26
        # the page sweeps the filter; approximate with the sweep's geometric centre
        f = np.sqrt(600 * (3200 if kind == "shhh" else 1600))
        n = biquad_bandpass(shaped_noise(dur, 1.0, seed), f, 0.8)
        return n * decay(len(n), 0.035, 0.45 if kind == "shhh" else 0.28)
    if kind in ("shovein", "shoveout"):
        a = (96, 190) if kind == "shovein" else (190, 96)
        return tone(0.3, a[0], a[1], "triangle") * decay(int(SR * 0.3), 0.045, 0.24)
    if kind == "thock":
        return tone(0.26, 112, 44) * decay(int(SR * 0.26), 0.11, 0.2)
    if kind == "slam":
        # the whole field arriving at once — one shove for 400 rows, not 400 ticks
        body = tone(0.44, 150, 34) * decay(int(SR * 0.44), 0.22, 0.36)
        n = biquad_bandpass(shaped_noise(0.26, 1.4, seed), 900, 0.7) * decay(int(SR * 0.26), 0.09, 0.28)
        out = body.copy()
        out[:len(n)] += n
        return out
    return np.zeros(1, dtype=np.float32)


# --------------------------------------------------------------------------- music


def read_clip(path):
    """Decode an assets/*.m4a snippet to mono float32 @44.1k, exactly as encoded
    (its r128 attenuation is already baked in — do not touch the level here)."""
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a:0",
         "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, stdout=subprocess.PIPE).stdout
    return np.frombuffer(raw, dtype="<f4").copy()


def main():
    cues = json.loads((HERE / "audio_cues.json").read_text(encoding="utf-8"))
    fps = cues.get("fps", 30)
    dur = float(cues["dur"])
    n_total = int(SR * (dur + 0.5))
    mix = np.zeros(n_total, dtype=np.float32)

    for i, s in enumerate(cues["sfx"]):
        w = make_sfx(s["kind"], 1000 + i) * SFX_GAIN
        at = int(s["t"] * SR)
        end = min(n_total, at + len(w))
        if end > at:
            mix[at:end] += w[:end - at]
    print(f"sfx: {len(cues['sfx'])} events")

    cache = {}
    for c in cues["audio"]:
        f = HERE / "assets" / c["file"]
        assert f.exists(), f
        if c["file"] not in cache:
            cache[c["file"]] = read_clip(f)
        y = cache[c["file"]].copy()
        n = min(len(y), int(c["dur"] * SR))
        y = y[:n]
        fo = int(0.32 * SR)                      # cue may end before the clip does
        if n > fo:
            y[n - fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
        y *= float(c["gain"])
        at = int(c["at"] * SR)
        end = min(n_total, at + n)
        if end > at:
            mix[at:end] += y[:end - at]
    print(f"music: {len(cues['audio'])} cues over {len(cache)} clips")

    peak = float(np.max(np.abs(mix)))
    # soft clip only where it would actually clip; the mix is already level-matched
    mix = np.tanh(mix * 1.02) * 0.97 if peak > 0.97 else mix
    print(f"peak before limit {peak:.3f} -> {float(np.max(np.abs(mix))):.3f}")

    wav = HERE / "master.wav"
    with wave.open(str(wav), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())
    master = HERE / "master.m4a"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav),
                    "-c:a", "aac", "-b:a", "192k", str(master)], check=True)
    wav.unlink(missing_ok=True)
    print(f"master: {master.stat().st_size / 1e6:.2f} MB, {dur:.1f}s")

    frames = HERE / "frames"
    n_frames = len(list(frames.glob("*.png")))
    assert n_frames > 0, "no frames rendered — run capture.js render first"
    out = HERE / "think_film.mp4"
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                    "-framerate", str(fps), "-i", str(frames / "%05d.png"),
                    "-i", str(master),
                    "-map", "0:v:0", "-map", "1:a:0",          # never leave this to chance
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)], check=True)

    probe = json.loads(subprocess.run(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(out)],
        check=True, stdout=subprocess.PIPE).stdout)
    kinds = {s["codec_type"]: s for s in probe["streams"]}
    v, a = kinds.get("video"), kinds.get("audio")
    print(f"wrote {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    print(f"  video {v['codec_name']} {v['width']}x{v['height']} "
          f"{eval(v['r_frame_rate']):.0f} fps, {n_frames} frames")
    print(f"  audio {a['codec_name']} {a['sample_rate']} Hz {a['channels']}ch")
    print(f"  duration {float(probe['format']['duration']):.2f} s")
    assert v and a, "MISSING STREAM — mp4 must carry both video and audio"
    assert (v["width"], v["height"]) == (1920, 1080), "not 1080p"
    return 0


if __name__ == "__main__":
    sys.exit(main())
