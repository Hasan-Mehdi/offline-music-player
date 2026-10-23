"""The door's sounds for Room's and Diorama's power on and off (firmware/ui/th_room.h
door_boot / door_off), from recorded doors: Kenney's RPG Audio (CC0, kenney.nl), laid on
the animation's own timeline so the latch, the creak and the slam land on the frames.

  .venv\\Scripts\\python firmware\\tools\\gen_door_sfx.py

-> firmware/assets/sfx/door_open.pcm, door_close.pcm: raw signed 16-bit little-endian,
mono, 22,050 Hz, starting at the animation's t = 0. The player loads them from
/.coda/sfx/ (scripts/install_coda_os.py copies them) and plays them on the voice
channel, over whatever is playing.
"""
import io
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PACK_URL = "https://kenney.nl/media/pages/assets/rpg-audio/8e99002d76-1677590336/kenney_rpg-audio.zip"
CACHE = ROOT / "data" / "sfx_src" / "kenney_rpg-audio"
OUT = ROOT / "firmware" / "assets" / "sfx"
SR = 22050
PEAK = 0.45                      # of full scale: as loud as the music, not a jump scare

# (clip, where it starts on the animation's clock in s, gain)
OPEN = [("doorOpen_1", .37, 1.0),      # the handle, the latch: its clack at .46, as it swings
        ("creak1", .52, .8)]           # the hinge through the swing (.52 - .98)
CLOSE = [("creak3", .36, .8),          # swinging shut (.34 - .70)
         ("doorClose_4", .60, 1.0)]    # the slam at .69, when the screen shakes


def pack():
    audio = CACHE / "Audio"
    if not audio.exists():
        with urllib.request.urlopen(urllib.request.Request(PACK_URL, headers={"User-Agent": "Mozilla/5.0"})) as r:
            zipfile.ZipFile(io.BytesIO(r.read())).extractall(CACHE)
    return audio


def clip(audio, name):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio / f"{name}.ogg"), "-ac", "1", "-ar", str(SR),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768


def compose(audio, parts):
    clips = [(clip(audio, n), int(t * SR), g) for n, t, g in parts]
    mix = np.zeros(max(len(c) + o for c, o, _ in clips) + SR // 20, dtype=np.float32)
    for c, o, g in clips:
        mix[o:o + len(c)] += c * g
    mix *= PEAK / max(1e-6, float(np.abs(mix).max()))
    fade = min(len(mix), SR // 25)                             # no click at the end
    mix[-fade:] *= np.linspace(1, 0, fade)
    return (mix * 32767).astype("<i2")


def main():
    audio = pack()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, parts in (("door_open", OPEN), ("door_close", CLOSE)):
        pcm = compose(audio, parts)
        (OUT / f"{name}.pcm").write_bytes(pcm.tobytes())
        print(f"{name}.pcm: {len(pcm) / SR:.2f} s, {len(pcm) * 2} bytes")
    (OUT / "LICENSE.txt").write_text(
        "door_open.pcm and door_close.pcm are made from Kenney's RPG Audio (kenney.nl),\n"
        "Creative Commons Zero (CC0): http://creativecommons.org/publicdomain/zero/1.0/\n"
        "(firmware/tools/gen_door_sfx.py)\n", encoding="utf-8")


if __name__ == "__main__":
    main()
