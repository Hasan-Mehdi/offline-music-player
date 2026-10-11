# Handheld device build (palm-sized player)

The whole runtime is: **Flask server + SQLite + one npz + a browser in kiosk mode**.
No ML models run on the device — embeddings/neighbors are computed on the PC and copied over.

## Hardware targets
- **Option 1 (recommended):** Radxa Zero 3W (2–4GB) + USB-C dongle DAC + small HDMI touchscreen.
- **Option 2:** Pi Zero 2 W (512MB) + Waveshare 2.8" GPIO touchscreen + PCM5102A I2S DAC —
  needs the low-memory mode below; use a lightweight WPE/cog kiosk, not Chromium.

## Prepare artifacts on the PC
```powershell
.venv\Scripts\python scripts\build_library_db.py     # after new downloads
.venv\Scripts\python scripts\muq_run.py              # embed new tracks (GPU)
.venv\Scripts\python scripts\build_neighbors.py      # neighbors table + data/muq_fp16.npz
cd web; npm run build                                # bakes UI into web/dist
```

## Copy to the device
- the repo (or just `scripts/`, `web/dist/`, `data/library.db`, `data/muq_fp16.npz`,
  `data/artist_genre.csv`)
- the music itself (update the `path` column of `tracks` for the device mount, or keep
  the same drive letter/mount layout and rebuild library.db on-device with mutagen)

Device Python deps (no GPU/ML): `flask numpy mutagen`.

## Run on the device
```sh
PLAYER_LOW_MEM=1 python scripts/server.py
```
`PLAYER_LOW_MEM=1` switches the server to fp16 embeddings (~half RAM) and retrieval via
the precomputed `neighbors` SQLite table instead of a full-matrix matmul. At 50k tracks
this keeps the ranking runtime under ~60MB. Without the flag behavior is unchanged
(desktop default).

Kiosk browser pointed at `http://127.0.0.1:5000`:
- Radxa / anything ≥1GB: `chromium --kiosk --noerrdialogs --disable-translate http://127.0.0.1:5000`
- Pi Zero 2 W: `cog -P fdo http://127.0.0.1:5000` (WPE WebKit, far lighter than Chromium)

## UI: handheld mode
The Svelte app self-adapts via CSS (no separate build):
- ≤820px wide or ≤520px tall: top bar hides (Search view grows its own input), the
  sidebar becomes a bottom tab bar, the now-bar goes compact (art/title + prev/play/next).
- Tapping the now-bar art/title opens the full-screen **Now Playing** view (big art,
  seek, shuffle/repeat, like/dislike, queue) — the primary surface on the device.
- Touch screens (`hover: none`): all hover-revealed controls are always visible.
- Very small panels (480×320 class): artwork hides in Now Playing; lists drop columns.

Test on the desktop by shrinking the browser window or with devtools device emulation.
