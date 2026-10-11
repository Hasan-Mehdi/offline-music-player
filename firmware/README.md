# firmware/ — the embedded player's software

The "Game Boy build" (docs/EMBEDDED_PLAN.md): a palm-sized ESP32-S3 player with
no OS and no browser. Everything here is written so the **brain is hardware-free
portable C**, developed and *proven on the PC* against the Python reference
before any hardware exists.

```
core/    portable C11, no dependencies — compiles for the PC host AND ESP-IDF
  omp_pack.*      device-pack reader (RAM or SD-streaming mode)
  omp_fp16.h      half->float, bit-exact with numpy
  omp_brain.*     personalize.py port: event weights, prefs, centroids,
                  rank_next, epsilon-explore, full /api/next step
  omp_speeddial.* /api/speeddial port (feeds the Wheel)
  omp_playlog.*   append-only binary play log (synced back to the PC later)
  omp_gain.h      R128 Q7.8 -> linear gain (-14 LUFS attenuate-only)
  omp_map.*       tiny u32->f32 hash map (artist prefs)
host/    PC-side tests + simulator (built with zig cc; VS here has no C++ toolchain)
  test_pack.c     pack integrity, LOAD_ALL==STREAM, brute-force neighbor check
  test_brain.c    GOLDEN PARITY: C must reproduce scripts/personalize.py
  sim_autoplay.c  run the device brain over the real 55k pack, watch it think
tools/
  gen_goldens.py  builds host/goldens/ fixtures using the REAL personalize.py
esp/     ESP-IDF project — UNTESTED SCAFFOLD (no hardware yet): SD bring-up +
         pack open + one brain decision; audio/LVGL land in milestones 1/3/4
```

## Build & test (PC)

```powershell
.venv\Scripts\python -m pip install ziglang        # one-time (bundled clang)
.venv\Scripts\python scripts\export_device_pack.py # if the pack is stale
.venv\Scripts\python firmware\tools\gen_goldens.py
powershell -File firmware\host\build.ps1
firmware\host\build\test_pack.exe  data\device_pack
firmware\host\build\test_brain.exe data\device_pack firmware\host\goldens
firmware\host\build\sim_autoplay.exe data\device_pack --seed VdylkNCz3ic --steps 20 --skip-every 5
```

All tests pass as of 2026-07-11 (55,432-track pack): `test_brain: OK — C brain
== Python brain`.

## The parity contract

`test_brain.c` holds the C port to the Python reference on generated fixtures:
track/artist preference scores (|Δ| < 1e-4), taste/skip centroids (per-component
< 1e-3, dot > 0.99999), full next-track rankings including the server's session
assembly — mood tail 12 / fatigue tail 6 / cooldown tail 4 + current artist —
(per-candidate score |Δ| < 5e-4, order equivalent within float tolerance), and
exact speed-dial tile sequences in both modes. Rerun `gen_goldens.py` whenever
`personalize.py` or the pack format changes, and keep this suite green — it is
the only thing standing between "the device feels exactly like the desktop
player" and subtle drift.

Known deliberate deviations (documented in headers): durations are u16 seconds
(goldens use the same truncation); speed-dial's per-artist cap keys on exact
artist bytes, not Unicode str.lower(); play-log events must be appended in
chronological order (they naturally are).

## What runs where

| | PC (now) | device (when hardware arrives) |
|---|---|---|
| embeddings/neighbors | data/device_pack (91.5MB) | same files on SD, STREAM mode (~124KB reads per decision) |
| brain | sim_autoplay / tests | same .c files, core 1 task |
| play history | goldens / simulated | /sd/plays.omp, appended on every transition |
| audio | n/a | esp_audio_codec opus -> gain -> I2S1 -> PCM5102A (milestone 1) |
| UI | n/a | LVGL: NowPlaying, windowed lists, the Wheel (milestones 3-4) |
