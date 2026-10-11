# Embedded player plan — "the Game Boy build"

> **2026-10-10: superseded by `docs/H2_APP_PLAN.md`.** HiFi Walker H2 bought (FW V2.3, Rockbox
> staged on its card); Coda is being rebuilt as a native full-screen Rockbox app on it. Hardware
> reasoning: `docs/HARDWARE_RELOOK.md`. This doc stays as the reference for the DIY ESP32 build.

A dedicated palm-sized device: no OS, no browser, instant-on, ~week of standby.
The ML stays on the PC and ships to the device as flat files ("device pack");
the brain is portable C (`firmware/core/`, parity-tested) that runs on ANY path
below. Researched 2026-07-10/11 + user deep-research 2026-07-11.

## The fork: two viable paths (decision pending)

**Path 1 — buy + port (Surfans F20 / Aigo Eros Q / HiFi Walker H2, ~$100–130).**
Same OEM device under three brands: Ingenic X1000 1GHz MIPS + 32MB RAM, ES9018K2M
Sabre stereo DAC + HT97220 amp, CNC aluminum body, **mechanical scroll wheel +
tactile buttons**, 512GB microSD, battery solved — and an official
[Rockbox port](https://www.rockbox.org/wiki/AIGOErosQK). Our brain becomes a
Rockbox plugin: C, file IO, and `playlist_insert_track(position, queue)` gives
queue control. 100% of the hardware problem disappears; zero soldering, zero
enclosure. Trades: UI = Rockbox themes + custom plugin screens, not our LVGL
wheel; no malloc in plugin land (bounded arena shim over the plugin buffer +
switch dense pref arrays to the sparse map — small refactor); MIPS cross-compile.
Verify before buying: current price/stock per rebrand; port maturity threads.

**Path 2 — build (Waveshare S3 AMOLED + DAC/amp + printed case).** Everything
below this section. Full custom UI (our wheel in LVGL), instant-on, exactly the
device we imagine — at the cost of the DAC wiring, the enclosure (the hardest
20%), and the full firmware roadmap.

They compose: Path 1 is ~2 weeks of software for a pocketable player; Path 2
stays the endgame build informed by it. The brain, pack, exporter, and play-log
sync are identical across both.

## Decision

**Build DIY on an ESP32-S3 board. Tangara (the obvious buy-and-hack candidate) is out**, for
two independent reasons:
1. **Not purchasable** (July 2026): the ~1300 campaign units are done, team is on a
   production break, no preorders, Mouser stock gone
   ([Crowd Supply updates](https://www.crowdsupply.com/cool-tech-zone/tangara/updates)).
2. **Its firmware can't take our library anyway**: the on-device LevelDB tag indexer
   crashes/bootloops from ~7–9k tracks (documented to 41k, unfixed through fw 3.0,
   [tangara-fw #413](https://codeberg.org/cool-tech-zone/tangara-fw/issues/413)). We have 55k.
   A fork would have to replace its whole database layer — at that point the hardware
   (older LX6 ESP32, weaker than S3) isn't worth the premium. Our architecture sidesteps
   the entire failure class: **no on-device scanning, ever** — the index is built on the PC.

Feasibility facts that make DIY safe (see Risks for the open ones):
- Opus 48kHz stereo decode ≈ **6–9% of one S3 core** (Espressif
  [esp_audio_codec](https://github.com/espressif/esp-adf-libs) benchmark: 5.86% CPU / ~27KB
  heap; [micro-opus](https://components.espressif.com/components/esphome/micro-opus): ~8%,
  6.1× real-time). ~150–170KB RAM per decoder instance (PSRAM).
- The brain is tiny: one next-track decision = read current + 120 candidate fp16 vectors
  (~124KB) + a 120-row dot-product rerank. Even over slow SPI-mode SD (~0.5–0.7MB/s)
  that's ~0.2s, and it can be prefetched during playback.
- LVGL on S3 does 30–60fps at small resolutions with SRAM partial buffers + DMA
  ([Espressif perf whitepaper](https://files.waveshare.com/wiki/ESP32-S3-Touch-LCD-7/Performance.pdf));
  avoid PSRAM-framebuffer-without-DMA (7–12fps).

## Hardware (BOM ≈ $60–75 + battery + case)

**Primary: Waveshare ESP32-S3-Touch-AMOLED-2.16** (~$37–42,
[docs](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-2.16)) — the only surveyed board
combining: 8MB octal PSRAM + 16MB flash, microSD on dedicated pins (SPI mode), AXP2101
PMU + MX1.25 LiPo connector with charging, 480×480 AMOLED + CST9217 touch, ES8311 codec
(mono, speaker-only — fine, see audio path). Palm-sized bare PCB.

| Part | ~Price | Note |
|---|---|---|
| Waveshare ESP32-S3-Touch-AMOLED-2.16 | $37–42 | schematic verified 2026-07-11 (see below) |
| PCM5102A I2S DAC breakout | ~$5 | 112dB SNR line-out; [Adafruit #6250](https://www.adafruit.com/product/6250) or GY-PCM5102 clone; SCK→GND (internal PLL) |
| TPA6132A2 headphone amp breakout | ~$5–8 | the actual 32Ω drive; 2.1mA quiescent; same pairing as [Sonatino](https://sonatino.com/docs/v2.6/); AliExpress modules exist, availability mushy — see research prompts |
| 3.5mm TRS jack breakout + tactile switches | ~$4 | buttons are a wire from a pad to GND |
| LiPo 3.7V 2000–3000mAh, **GH1.25 2-pin** connector | ~$8–12 | polarity IS silkscreened on the board (+/− at J1/BAT) — still check the pack's wiring |
| 512GB microSD (already owned?) | — | format FAT32 (see Storage) |

- **Schematic facts (verified from the downloaded Waveshare schematic, Rev2):**
  labeled solder pads = VBUS, 3V3, GND, GPIO19/20 (native USB pair), GPIO14/15
  (shared I2C — occupied), **TX=GPIO43 / RX=GPIO44 (the only free GPIO pads;
  reclaimable — console moves to USB-Serial-JTAG)**; speaker out pads (P10);
  battery GH1.25 with marked polarity. Buttons onboard: **PWR** (AXP2101 — short-press
  readable over I2C, natural play/pause), **BOOT** (GPIO0, usable as input after boot),
  **Key3 = GPIO18, a dedicated user button**. **The I2S bus is NOT broken out** —
  BCLK(9)/LRCK(45)/DIN(8)/MCLK(42) run chip-to-chip only.
- **Audio wiring, two options:**
  **(A) tap the onboard I2S bus** at the series passives by the codec (fine-pitch but
  static signals; PCM5102A listens in parallel with the mono ES8311, SCK grounded →
  no new GPIOs, keeps Key3 + both free pads for buttons); or
  **(B) big-pad route:** I2S1 out on GPIO43 + GPIO44 + GPIO18 (Key3's pad) — easy
  soldering, costs the user button (inputs left: PWR short-press, BOOT, touch).
  Decide after holding the board; A is the plan-of-record, B the chicken exit.
- **Buttons plan (first-class):** Key3 (GPIO18) + up to 2 external tactiles on 43/44
  under option A; PWR short-press = play/pause everywhere. Pin famine escape hatch:
  a PCF8574-class I2C GPIO expander on the shared bus (pads 14/15) = 8 button inputs
  for zero ESP32 pins (poll at 50Hz; fine for buttons, NOT for encoder quadrature).

### Controls & enclosure (from deep-research 2026-07-11)

- **Physical wheel option (recreates the Wheel UI in hardware):** Cirque GlidePoint
  circular trackpad over I2C on the shared bus — TM023023 (23mm, Gen6, 1.8–3.3V) or
  TM040040 (40mm, Gen2; desolder R1 to switch SPI→I2C; no internal pullups — the
  board's shared bus already has them). ~$27 from keyboard vendors; `CirquePinnacle`
  library; needs one GPIO for data-ready (pad 43). Case gets a debossed circular
  groove over it so the thumb finds it blind.
- **Encoder option:** Bourns **PEC11R-4015F-S0024** (smooth, no detents, push-switch,
  <$3) or PEC11L (low-profile, 100k cycles). Gotcha: encoders can REST with a contact
  closed → ~0.25mA standby drain through pullups — pick PEC11L or power-gate the
  encoder ground in sleep. Quadrature needs 2 interrupt-capable pins (43/44) — so
  encoder and Cirque are either/or on this board's pads.
- **Buttons that feel right:** Alps **SKRRAAE010** (100gf, the GBA-SP switch) under
  Game Boy Color silicone membranes (~$5, Hand Held Legend/FunnyPlaying) with rigid
  printed caps — the Pi Tin project documents the exact stackup. Avoid bare tacts
  under hard caps (rattly, harsh).
- **Enclosure:** final shell in **MJF PA12 nylon** (JLC3DP/PCBWay) — isotropic,
  impact-tough, matte commercial finish; 2.0–2.4mm walls, 0.5mm clearance around the
  PCB (never press-fit — thermal bowing cracks AMOLEDs), M2.5 heat-set inserts
  (3.5mm holes), chamfered port cutouts, bezel overlaps the AMOLED inactive border
  ≥0.5mm. Interim/prototype: **OKW Soft-Case A9050209** (82×51×14mm, TPE bumper
  ring) is nearly our exact footprint. Reference builds: Tangara (FreeCAD files,
  AT42QT2120 touchwheel), Pi Tin (button stackup), Walkmp3rson (RP2040 player).
- Alternative one-chip audio if we ever spin a PCB: ES8327 (stereo codec + real headphone
  driver, 16–60Ω tested — [Music32-V2](https://hackaday.io/project/192376)).
- **Fallback board:** M5Stack CoreS3 SE (~$39 + $10 battery base) — enclosed from day 1,
  but quad (not octal) PSRAM, SD sharing the LCD SPI bus, and the same need for an
  external DAC with fewer free pins. Choose it only if the enclosure problem outweighs all else.
- Rejected: every other all-in-one (no storage, 2MB PSRAM, no battery, or no audio);
  ESP32-P4 boards (T-Display-P4 ~$104+) are overkill and young.

## Storage

- 268GB today → ~340GB at final ~72k tracks; a 512GB card fits.
- **FAT32, not exFAT** — ESP-IDF has no exFAT support (feature requests closed "Won't Do";
  a vendored-ffconf patch exists but re-breaks every IDF upgrade). FAT32 is valid to 2TB
  volumes; the 4GB file cap is irrelevant for opus. Windows GUI won't format FAT32 >32GB —
  use Rufus or guiformat, 64KB clusters.
- **>256GB on ESP32 has no public confirmation** — we validate ourselves in Milestone 0
  (fill test + read-throughput). 256GB is confirmed working by others.
- **Directory sharding is mandatory:** FAT32 caps a directory at 65,534 entries and each
  long filename consumes several; a flat 55k-file dir does not fit. The pack's file paths
  are already `V/basename.opus` (V = first char of the video_id → ~40 dirs, ~1.4k files
  each). The SD copy script must shard identically (PowerShell: extract `[id]` from each
  filename, copy to `$id[0]/`).

## Audio path & loudness

SD → opus decode (esp_audio_codec or ESP-ADF pipeline) → software gain → I2S1 →
PCM5102A → TPA6132A2 → jack.

Loudness: pack carries `gain_q78` (R128 gain, dB×256, re −23 LUFS — same value as
`tracks.r128_gain_db`). Firmware replicates the web player exactly: target −14 LUFS,
attenuate-only → linear gain = `min(1, 10^((gain_db + 9)/20))`, applied to PCM samples
(or via libopus `OPUS_SET_GAIN`, which takes the same Q7.8 format natively).

## Firmware stack

- **ESP-IDF 5.x** + `esp_lvgl_port` (actively maintained, LVGL 8/9). Start on LVGL 9;
  if fps disappoints, LVGL 8.4 is a known ~1.5× faster fallback on S3
  ([esp-bsp perf doc](https://github.com/espressif/esp-bsp/blob/master/components/esp_lvgl_port/docs/performance.md)).
- **Decode:** `esp_audio_codec` (prebuilt, benchmarked) first; `micro-opus` as the
  open-source fallback.
- Task layout: core 0 = LVGL/UI + input; core 1 = audio pipeline (SD read → decode →
  gain → I2S DMA) + brain reranks + FFT for the spectrum ring (esp-dsp).
- Scaffolds to mine: ESP-ADF `examples/display/music_player` (LVGL+touch+SD player,
  official), [Melody Machine](https://github.com/wadadawadada/melody_machine) (LVGL 9.3
  + SD browser, MIT), [squeezelite-esp32](https://github.com/sle118/squeezelite-esp32)
  (mature audio output layer incl. opus). Nobody has shipped an S3 LVGL+SD+opus local
  DAP — the components are all proven but the synthesis is ours.
- Power: DFS to 80MHz during playback (decode needs <10%), screen off = AMOLED win
  (dark theme = real mA), light sleep only when paused (I2S holds a PM lock — no sleep
  while streaming, [esp-idf #12773](https://github.com/espressif/esp-idf/issues/12773)).
  Estimated 8–17h on 2000mAh, 12–25h on 3000mAh depending on screen-on ratio.

## Device pack (the data contract) — BUILT ✅

`scripts/export_device_pack.py` (done, self-tested) reads `library.db` (read-only) +
`data/muq_embeddings.npz` and writes `data/device_pack/` — **91.5MB for 55,432 tracks**.
It computes neighbors fresh from the fp32 embeddings every run, so it can never go
stale the way `neighbors`/`muq_fp16.npz` did (those were 20k-era on 2026-07-10).

| File | Size | Contents |
|---|---|---|
| `pack.json` | — | counts, dim=512, K=120, format v1, layouts |
| `tracks.bin` | 1.3MB | N×24B records (5×u32 string offsets, u16 dur, i16 gain Q7.8), sorted by (artist,title) casefold → artist browsing = binary-search ranges, no on-device sort |
| `strings.bin` | ~6MB | NUL-terminated UTF-8 pool (deduped); file paths pre-sharded `V/basename.opus` |
| `ids.bin` | 0.6MB | N×11B video_id — stable key for play-log sync |
| `embeddings.f16` | 57MB | N×512 fp16, L2-normalized (dot = cosine) |
| `neighbors.bin` | 27MB | N×120 u32 best-first (0xFFFFFFFF pad) |

Device RAM budget: tracks.bin + ids in PSRAM (~2MB); strings.bin ideally memory-mapped
from a **flash partition** (16MB flash − ~3MB app leaves room) or PSRAM (6MB — tight
next to decoder + UI); embeddings + neighbors stay on SD (read per rerank, ~124KB).
fp16→f32 conversion in software (S3 has no half-float FPU; 62k converts/rerank ≈ free).

## Brain port (C, host-testable before hardware arrives)

Port `personalize.py` verbatim — it's ~100 lines of arithmetic. Constants from the code:
weights `alpha=1.0 mu=0.6 delta=0.6 gamma=0.5 gamma_artist=0.3 (tanh-capped) sigma=0.7
cooldown=0.5 nu=0.1 rho=2.0 rho_floor=0.80`; prefs: skip<15%→−1.0, >80%→+0.5,
like=+3/dislike=−3, complete=max(0.25,completion), 30-day half-life, first-3-tracks
skip softening ×0.5; ε=0.15 explore over top-12. Retrieval = neighbors.bin row (≤120)
minus exclusions → rank → pick.

- Device keeps its own append-only `plays.log` (ts, video_id idx, event, seconds);
  prefs/taste/skip centroids recomputed incrementally like the server does.
- **Parity gate:** build the brain as a portable C component, compile it on the PC, and
  assert it reproduces Python `rank_next` orderings on golden traces (generate goldens
  with the existing `trace_next` tooling). This whole milestone needs no hardware.
- Latency mask: when a track starts, immediately pre-rank "next if skipped now" in the
  background so skip → next is instant.

## UI mapping (Svelte → LVGL)

Carry the existing design direction (docs/DESIGN_NOTES.md) — this is a port, not a
redesign. True-black AMOLED background is both on-brand and a battery feature.

| Web | Device |
|---|---|
| Wheel.svelte (24-slot speeddial ring, 30°/detent, spectrum ring, hub tap) | custom LVGL widget, arc-drawn wedges; spectrum via esp-dsp FFT tap on PCM; speeddial logic (recency-weighted freq + fresh-first) ported — pure arithmetic over plays.log |
| NowPlaying/NowBar | main screen: art-less v1 (big type), seek/like/skip |
| Songs/Artists/Genres | windowed list over sorted tracks.bin (render ±30 rows); first-letter jump via binary search |
| Search (Songs view) | linear substring scan of title/artist pool (~6MB in ~tens of ms) — no FTS needed |
| Peek (hook preview at 35%) | v2: second opus decoder instance (2×9% CPU, 2×170KB — fits), duck main, same UX |
| Explore shelves | later; simple queries over plays.log |
| Genre map, VGM space, hum-to-search, mood text search | **not coming** — desktop-only (need MuQ/CREPE/t-SNE) |

Album art: none in pack v1 (wheel uses genre-coded wedges + type). v2 exporter addition:
`thumbs.bin` of 64×64 JPEGs (~3KB × 55k ≈ 170MB on SD, decode via esp_jpeg).

## Sync workflow (PC ↔ device)

1. After new downloads/embeddings: `python scripts/export_device_pack.py` (16s).
2. Sharded robocopy of `D:\OfflineMusic` → SD `\music\` + copy `data/device_pack` → SD `\pack\`.
3. Pull device `plays.log` → future `scripts/import_device_plays.py` merges into the
   `plays` table (video_id keyed) so desktop and device share one taste history.

## Milestones

0. **Bench bring-up** (de-risks the two real unknowns): 512GB FAT32 fill + read-throughput
   on the board; LVGL demo fps on this exact AMOLED; INA-measured current draw.
1. **Audio path:** one opus file SD→jack via I2S1/PCM5102A, R128 gain applied. Gapless next.
2. **Brain — DONE 2026-07-11 ✅** (`firmware/`): pack-reader + full personalize.py port in
   portable C, golden-trace parity vs Python green (`test_brain: OK`), autoplay simulator
   + speed-dial port included, ESP-IDF bring-up scaffold authored (untested, no hardware).
3. **Core UI:** NowPlaying + windowed library + play/skip/like logging. It's a usable
   player at the end of this milestone.
4. **The Wheel** + spectrum ring + peek.
5. **Power tuning:** 80MHz DFS, screen-off policy, battery curve calibration (AXP2101 fuel gauge).
6. **Enclosure** (honestly the hardest 20% — budget 2–3 print iterations; precedent:
   [Retro-Audio](https://github.com/CoretechR/Retro-Audio) STLs) + plays-log import script.

## Risks / open verifications

| Risk | Status / mitigation |
|---|---|
| 512GB SD on ESP32 unproven publicly | Milestone 0 fill test; 256GB is the confirmed floor — worst case: curated 250GB subset (exporter `--limit` exists) |
| ~~Spare GPIO pad count~~ RESOLVED via schematic: only 43/44 free | I2S tap option A (passives) or option B (sacrifice Key3); fallback board if soldering is a no: M5Stack CoreS3 SE (M-Bus header — verify its free pins first, see research prompts) |
| Round/odd AMOLED LVGL fps has no published benchmark | Milestone 0; music UI needs partial redraws, not 60fps full-screen |
| SPI-mode SD ≈ 0.5–0.7MB/s | 25× real-time for one opus stream; peek doubles it — still fine; brain reads prefetched |
| Naked PCB until Milestone 6 | it's a bench device until the case lands |
| 5 tracks have no embedding | listed by exporter; re-run muq_run.py picks them up eventually |
