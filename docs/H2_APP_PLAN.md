# Coda on the HiFi Walker H2 — native app plan

## Status (2026-10-11 night)

| stage | state |
|---|---|
| 0 repo committed | done |
| 1 app features | done, host + simulator verified: Explore shelves, Search (letter rail on the wheel), Soundtracks (franchise dividers), Genres (+ genre station), Queue, Now Playing sheet (Menu), track sheet (hold Play on a row), wheel peek, background autoplay after leaving (sim-verified) |
| 2 Coda OS | built + simulator-verified; firmware staged at `firmware/rockbox/out/coda-os.zip`, **not on the card** until the boot animation is approved (`docs/h2/boot/boot.gif`) |
| 3 strip Rockbox UI | `build_os.sh strip-target` -> `out/coda-os-strip.zip`: no Rockbox UI reachable, no escape, no database scan, Coda USB screen. The UI code is still linked (settings table references it); removal needs a settings-table rewrite |
| 4 card / sync / engine / battery | card: full 18,388-song selection, verified. Play-log sync (`scripts/h2_sync.py`, inside `export_h2.py`). Engine **v3** (the web's current; supersedes v2.2) ported + golden-tested (`firmware/core/omp_engine3.c`, 86/86). Battery log + `scripts/h2_battery.py`; the measurement itself needs a device run |

Morning handoff: `docs/h2/MORNING.md`.

**Coda OS** (`firmware/rockbox/os/`): our Rockbox build (pinned 7d090f24b9) with Coda linked
into the firmware as the root app. `build_os.sh sim|target` syncs the Coda sources, applies
`patch_core.py` (every hook `#ifdef CODA_OS`) and builds in its own dirs (`build-os`,
`build-os-sim`). Coda is compiled with the plugin flags and its `rb` pointer aims at the
core's own API table (`plugin_get_api()`), so the plugin code runs unchanged; all of Coda is
linked into one object whose symbols are local except `coda_os_run` / `coda_os_logo`.
- Boot: Coda's boot frame replaces the Rockbox logo during init; the animation plays while
  the library loads on its own thread; then Coda. No Rockbox screen on the way.
- Memory: 8 MiB static heap (was the 2 MiB plugin buffer), 64 KB UI thread stack. Audio
  buffer stays ~19.8 MB.
- Hidden way out: **hold Menu + Back for 1.5 s** -> Rockbox's menu (Plugins removed, "Coda" on
  top). Back at its root, or the Coda item, returns. Autoplay keeps running while out.
- USB mass storage: everything Coda opened is closed (its API-table copy tracks open/close)
  and the library reloads afterwards, since the card may have changed.
- Install (after approval): unzip `coda-os.zip` onto the card root (it is a `.rockbox`
  folder). The bootloader is not touched; the stock Rockbox zip is in the same folder to go
  back.

**Queue semantics now match the web player:** Coda owns a queue mirrored into Rockbox's
playlist; lists that are sequences (artist, soundtrack, likes) queue in order, lookups
(songs, search, genre list, Explore, wheel) play the pick and autoplay carries on. Autoplay
only adds when the queue runs out (it used to hijack an album after its first track).

**Decision (2026-10-10):** keep the H2 (bought, FW V2.3 = hw4; Rockbox daily build staged on the
bundled card) and rebuild the Coda player as a **native full-screen app on top of Rockbox**.
The web player itself cannot run there (no browser, ~1GHz MIPS, tens of MB of RAM), so the
device gets the same design, the same Wheel and the same autoplay brain, rewritten in C.

Design reference: `docs/h2/` (rendered by `firmware/tools/mock_h2.py` from real covers and
plays). Direction is unchanged from the web app (`docs/DESIGN_NOTES.md`, record-shop poster):
paper `#f4f4f0`, ink `#141414`, Klein blue `#002fa7`, signal red `#e0301e` for live only,
Archivo Black display type, art butted edge-to-edge, focus = print inversion.

| sheet | what |
|---|---|
| `docs/h2/sheet_wheels.png` | Wheel, two layouts: **A** full wheel + name reel (web-faithful), **B** dial arc + big title (bigger covers) |
| `docs/h2/sheet_screens.png` | Now playing (with the brain's "why"), Coda menu (poster nav words), Artists (crate rows) |

The physical click wheel under the screen drives the on-screen Wheel directly — the thing the
web version imitated with a mouse.

## What runs where

```
Rockbox (installed, our own build at a pinned commit)
  decoding, gapless, buffering, ReplayGain, battery, USB, settings
  └── coda.rock  — our plugin, full screen; Rockbox "Start Screen = Plugin" boots into it
        firmware/ui     portable C: 320x240 RGB565 renderer, AA glyph atlases, Wheel,
                        lists, Now playing, menu (no Rockbox includes)
        firmware/core   existing: brain (engine v1), pack, speeddial, playlog, gain
        firmware/plat   rockbox.c — lcd, buttons, files, playlist/audio control, events
                        host.c    — zig cc on this PC: frames -> PNG, scripted input
```

Rockbox plugin API facts this relies on (checked in Rockbox master source, API 285):
`playlist_create / playlist_insert_track / playlist_start`, `audio_play/pause/resume/next`,
`audio_current_track`, `add_event(PLAYBACK_EVENT_TRACK_CHANGE)` + `plugin_tsr` (autoplay keeps
going after leaving the app), `beep_play` (wheel detent ticks), `mixer_channel_get_buffer`
(live PCM for the hub visualizer), `get_time` (RTC: evening negative-print mode),
`start_in_screen = plugin` (boot straight into Coda). Plugin buffer on this target is 2 MiB
for code + working data; the 54k-track data stays on the SD card and is streamed.

## Web feature → device

| web | device |
|---|---|
| Wheel: speed-dial pool, detents, tick sfx, record label, sunburst visualizer | yes — physical wheel; ticks via `beep_play`; visualizer from the playback PCM |
| Auto-peek (preview at ~35% with main track ducked) | changed — Rockbox has one decoder, so peek = briefly switch playback and return; no ducked mix. Try it, keep it only if it feels right |
| Autoplay brain + "why this song" | yes — `firmware/core` (engine v1 today; v2.2 port = M6) |
| Now playing, queue | yes |
| Library: Songs / Artists / Genres, OST crates, Explore shelves, Liked, History | yes (lists; Explore shelves precomputed at export, refreshed on device later) |
| Search | yes — letter picking with the wheel |
| Like / dislike | yes — button mapping below |
| −14 LUFS attenuate-only loudness | yes — ReplayGain tags written at export (see below) |
| Evening negative-print theme | yes — RTC |
| Hum-to-search, map, films, MuQ analysis | no — PC only (no microphone, no GPU) |

## Buttons (proposal, settle on device)

Wheel = spin / scroll. Play (centre) = select; on Now playing = play/pause.
Back = back. Menu = Coda menu (long press = Rockbox's own menu). Prev/Next = skip
(long = seek). Vol ± = volume. Like/dislike: Menu on Now playing opens a short action list
(Like, Dislike, Go to artist, Queue). Every wheel action also works from buttons (owner
reviews: H2 wheels wear).

## Card layout

```
/.rockbox/          Rockbox + /.rockbox/rocks/apps/coda.rock
/.coda/             app data (hidden from Rockbox's browser)
    pack/           device pack (embeddings/neighbors, STREAM mode, ~92MB)
    tracks.bin      index -> title, artist, duration, genre/OST, relpath
    art/            pre-rendered cover thumbnails at the sizes the UI draws
    glyphs/         AA glyph atlases (Archivo Black / Archivo / Inconsolata / Noto Sans JP,
                    subset to the characters the library actually uses)
    plays.omp       on-device play log -> synced back into the PC plays table
    manifest.tsv    export state (what's on the card, checksums for read-back verify)
/Music/<Letter>/<Artist>/<Title> [video_id].opus
```

Music copy rules (verified against Rockbox source):
- Audio bit-identical; the 1280×720 base64 PNG cover (20.7% of library bytes) is replaced by a
  small baseline JPEG — Rockbox reads the first `METADATA_BLOCK_PICTURE`, JPEG/BMP only.
- Rockbox applies Opus `R128_TRACK_GAIN` **and gives it priority over REPLAYGAIN tags**, so the
  card copy drops `R128_*` and writes `REPLAYGAIN_TRACK_GAIN = min(0, r128 + 9)` (album:
  `min(0, album_gain_db + 9)`) — the web player's −14 LUFS attenuate-only level.
- 16,335 artists (11,852 with one track) → letter buckets keep every folder under Rockbox's
  default 5,000-entries-per-folder browser limit. Names: FAT-safe, ≤ 255-byte UTF-8 paths
  (MAX_PATH 260), no leading dots (Rockbox hides them), case-insensitive collision safe.
- Full library ≈ 182GB → 256GB card (not bought yet). The bundled 64GB card takes a slice
  (~17k tracks) for testing.

## Milestones

| | | needs |
|---|---|---|
| **M0** | Toolchain: build Rockbox at a pinned commit + a hello `coda.rock` (full-screen poster test pattern, wheel ticks). Install our build on the card. Proves ABI, LCD, input | **WSL** (admin + reboot, user) |
| **M1** | `firmware/ui` + host platform: Wheel + Now playing rendered in C from real data, matching the mockups pixel-for-pixel-ish | nothing |
| **M2** | `scripts/export_h2.py`: music copy + `/.coda` data, resumable, read-back verify (doubles as a fake-card check) | nothing (64GB card for the test slice) |
| **M3** | On device: Wheel + Now playing + autoplay + play log; boots into Coda | M0–M2 |
| **M4** | Library / OST / Explore / Liked / History, search, like/dislike | M3 |
| **M5** | Visualizer, peek, sfx, evening theme, play-log sync back to the PC | M3 |
| **M6** | Engine v2.2 port to C with extended goldens (cooc, energy/bpm, cluster explore, …) + pack v2 | nothing |

M1, M2 and M6 need no hardware or toolchain and can run while WSL is pending.

## Open questions

- Wheel layout A vs B (user's call from `docs/h2/sheet_wheels.png`).
- Peek feel without a ducked mix.
- CJK font size budget: ~3–4k distinct glyphs in titles/artists × 2–3 sizes.
- Rockbox's database is not needed by Coda (it has its own index), but keep it usable for
  Rockbox's own browser; initial scan of 54k files may take hours — run once, overnight.
