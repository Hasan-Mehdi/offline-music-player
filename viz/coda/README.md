# How Coda works (film #4)

A 5:52 explainer, narrated as on-screen text in Hasan's words (`SCRIPT.md`). It covers how
Coda picks songs, why the H2, what's inside it, the rewrite in C, Coda OS, the themes,
Bluetooth, and what's next.

- `coda_film.mp4`: 1080p30 with the soundtrack. A copy for GitHub is at `docs/media/how-coda-works.mp4`.
- `coda_film.html`: standalone (~17 MB, everything inlined). Double-click it, then press Play.
  Space pauses, `[` and `]` step between chapters, and `m` mutes.

The timeline is built from the words: each sentence gets 0.75 s + 0.255 s per word, and every
visual cue hangs off a sentence's start (`S(id,i)`) or the moment a given word is read
(`Wd(id,i,k)`). Edit a line in `script()` in `coda.html` and everything after it retimes.

## What's real

| on screen | source |
|---|---|
| 18,388 songs on the card, 42,850 in the library | `data/library.db`; the card count is the export to card E: |
| the 512-number fingerprints, the near and far song | centered MuQ vectors from `data/muq_embeddings.npz`, sorted by the hero song's values |
| the 40 songs around "playing now" | the hero's real nearest neighbours |
| **the score bars** | **illustrated**: the terms are the engine's, but the values are made up (and labelled so) |
| 10,941 listens, per day | `data/takeout/exports/*` via `merge_takeout.music_events` |
| the lean: 320 arrows, 0.27 → 0.00 | real MuQ vectors projected on (mean direction, top PC of the residual) |
| the test pairs | real songs first heard after 2026-07-26, next to random library songs |
| 54% → 67% | `docs/EXPERIMENTS.md`, "Autoplay engine v3" (AUC 0.539 raw → 0.669 centered) |
| lines of C, per file | counted by `build_data.py` (`firmware/ui`, `core`, `plat`, `rockbox/coda`) |
| 86 / 86 same pick | `firmware/host/build/test_engine3.exe`, **run by build_data.py** |
| device screens, theme mockups | `docs/h2/c`, `docs/h2/{menu,inner,pixel,room}` |
| boot animation | the frames of `docs/h2/boot/boot.gif` (the approved one; the `boot_*.png` beside it are the old turntable) |
| the web player | `node viz/coda/capture.js web` with `scripts/server.py` running |
| Bluetooth facts | `docs/h2/BLUETOOTH.md` and the first device test (no retest yet) |
| music | three songs the H2 has played (`plays.source='h2'`) |

The exploded board in "What's inside" is a diagram: the parts are real, but the layout isn't.

## Rebuild (repo root)

```
node viz\coda\capture.js web                  # assets/web.png (needs scripts\server.py up)
.venv\Scripts\python viz\coda\build_data.py   # coda_data.json + assets/ (~2 min)
.venv\Scripts\python viz\coda\bundle.py       # coda_film.html
node viz\coda\capture.js render 30            # frames/ + audio_cues.json (~10 min)
.venv\Scripts\python viz\coda\mux.py          # coda_film.mp4
```

`node viz\coda\capture.js preview 26 44 258` writes stills to `preview/`, and `smoke` prints
every page's timing. Delete `frames/` after muxing (it's several GB).

Gotchas: the device shots are raw PNGs (0.9 MB a frame), so build_data recompresses them. The
library changes under the film (the purge took it from 54,045 to 42,850 songs), so the counts
are read at build time, not typed in.
