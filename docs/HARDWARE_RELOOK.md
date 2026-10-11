# Hardware relook — 2026-10-09 (round 2: 2026-10-10)

## Round 2 — the brief changes: pocketable, looks like an MP3 player (not a Game Boy)

User feedback on round 1: "really want it to be more pocketable and more of an MP3 player
look rather than Game Boy." That rules out the retro handhelds (options A and B below)
and puts MP3-player shapes back on the table. Re-surveyed 2026-10-10.

### Programmable devices that look like MP3 players

| | **HiFi Walker H2 / Aigo Eros Q / Surfans F20** (one device, three brands) | **HiBy R1** | **DIY ESP32 in a candybar case** |
|---|---|---|---|
| Look / size | classic candybar: screen on top, **mechanical scroll wheel** + buttons below, aluminum. ~9×5.5×1.5cm, ~150g | slim modern slab, 8.4×5.1×1.2cm, **70g** | whatever we design (July plan, re-shaped) |
| Screen | 2" 320×240 | 3" 800×480 **touch** | 1.8" 368×448 or 2.16" 480×480 AMOLED |
| Buttons | wheel + full button set | power, volume rocker, play/next rocker (**no previous button**). Mostly touch | what you choose |
| Audio | ES9018K2M DAC | CS43131 DAC | PCM5102A + amp (we wire it) |
| Battery | 1300mAh; vendor says ~10h | 1150mAh; ~15h claimed | est. 8–25h |
| Wi-Fi | no (sync over USB) | yes | yes (slow for bulk) |
| Rockbox | **official since 4.0**. The vendor publishes its own install guide. The only change is a bootloader; stock firmware stays | **"unstable" port** (2025-12-28). Users report 2 themes and patchy BT (Apr 2026) | n/a (our firmware) |
| Price | ~$110–125 | ~$69–85 | ~$30 board + parts + printed case |
| Effort to run our engine | Rockbox plugin (verified pattern, below) | Rockbox plugin on an unstable port, or our own Linux binary (unverified) | full firmware + hardware build |

**Closed devices that can't run our engine:** FiiO Snowsky Disc (round 360×360
touchscreen, 68×68mm, ~$80–99; it's the closest match to our wheel UI, but runs FiiO's closed Linux),
Snowsky Echo Mini (theme files only), HiFi Walker H2 Mini (45g, 1.54" touch, no Rockbox),
Innioasis Y1/Y2 (iPod-classic look; Y1 Rockbox fork archived, no Y2 port).

### Recommendation: HiFi Walker H2 (or whichever of the three brands is cheapest)

The H2 is the only one that is pocketable, looks like an MP3 player, is button-first, *and* has a
mature open firmware. Our engine fits inside it. Verified from Rockbox source and docs (2026-10-10):

- **Our engine plugs in as a resident plugin.** Rockbox's `announce_status` plugin already
  does what we need: `rb->plugin_tsr(...)` stays resident,
  `rb->add_event(PLAYBACK_EVENT_TRACK_CHANGE, cb)` hooks every track change, and a
  `rb->create_thread` worker does the work. Ours would be: on each track change, run the C brain,
  then `playlist_insert_track` the next pick. Endless autoplay with the July brain, unchanged
  in spirit.
- **Memory budget:** `erosqnative.h` sets `PLUGIN_BUFFER_SIZE 0x200000` (2 MiB) while music plays.
  That's enough for the brain in SD-streaming mode (120 candidate vectors ≈ 120KB, sparse prefs,
  centroids). tracks.bin, strings and ids stay on SD and are read on demand. This needs the
  arena shim from the July plan, plus a pack-v2 path→index hash file, because Rockbox
  hands us a file path, not a video_id.
- **Play log for free:** the Rockbox core now writes its own playback log as
  `timestamp:elapsed:length:path`. That is exactly our skip/complete signal (elapsed ÷ length).
  The device has a real-time clock (`CONFIG_RTC RTC_X1000`), so timestamps are real.
  Sync = plug in over USB, then a PC script imports the log into `plays` and pushes pack and music deltas.
- **The Wheel becomes physical:** `HAVE_SCROLLWHEEL`. The speed-dial wheel UI maps onto a
  real wheel. The UI is a Rockbox theme in our poster language plus a plugin screen.
  The heavy typography of the poster design suits 320×240.
- **Current units are covered:** hw4 = H2 V1.9–V2.3, Eros Q V2.2, F20 V3.4. Check
  *About → Version* on arrival before flashing. FAT32 is required; our pack is already sharded.

Costs and unknowns: 150g of aluminum (heavier than the R1). No Wi-Fi. Likes and dislikes need a button
mapping. **Building Rockbox plugins needs a Linux toolchain, and WSL is not installed on this
PC** (`wsl --install` needs admin and a reboot; a GitHub Actions build is the alternative).

Pick the **R1** instead only if being slim and light matters more than physical controls and a
stable port. Pick **DIY** if you want the look to be 100% yours and you're willing to
build the case. The July plan stays valid; only its enclosure brief changes.

### Round 3 — final checks on the H2 (2026-10-10)

| Question | Answer | Source / how |
|---|---|---|
| Still the only new Rockbox hardware? | Yes. Rockbox's Solomon Peachy called the Eros Q/K "the only compatible hardware still being manufactured and sold" | Hackaday on Rockbox 4.0, 2025-04 |
| Can the autoplay plugin be built from the public API? | **Yes, no core patch needed.** `plugin.h` (API v285) has `playlist_insert_track(playlist, filename, position, queue, sync)`, `add_event/remove_event`, `plugin_tsr`, `create_thread`, `audio_current_track`, `get_metadata`, `open/read/lseek`, `button_get` | Rockbox master source |
| Is the port maintained? | Yes. erosqnative commits run through 2026-09 (ES9018K2M hardware volume, sound init fix, hw4 fuel gauge). No new hardware revision (hw5) seen | Rockbox git log |
| Bluetooth | **Not supported in official Rockbox** (port notes put it under "Someday"; owners boot stock firmware for BT and USB audio). A community A2DP attempt for H2 hw4 appeared 2026-05 in a hosted-Linux variant; it's unmerged and unverified. **Treat this as a wired-only player** | port commit notes; Lobsters owner report; git mirror |
| Battery | Anecdotal **~24h under Rockbox** (Rockbox wiki runtime page, which an owner says matches their use). Vendor claims vary from 10h to 36h | Lobsters thread |
| Album art | Rockbox reads embedded art in Opus since 2025-02, **JPEG only, no progressive**. Our files: **94% PNG** (1280×720 YouTube thumbs), avg 657KB stored as base64 → **art = 20.7% of library bytes ≈ 47GB** | Rockbox manual + commit; measured on 800 of our files |
| Card size | Audio alone ≈ **181GB**. Device copy = same opus audio, bit-exact, plus a ~200×200 baseline JPEG ≈ **182GB → 256GB card, no audio re-encode**, ~55GB headroom (~16k more tracks). The 128k transcode becomes the growth lever, not step one | measured |
| Loudness | All sampled files carry `R128_TRACK_GAIN`. Whether Rockbox applies it to Opus is **unverified**, so the device copy also gets `REPLAYGAIN_TRACK_GAIN` (attenuate-only, −14 LUFS target, like the web player). Check on day 1 | measured; Rockbox source inconclusive |
| 54k-track database | No hard track limit (the old 10k cap was removed). The "max files in dir" setting goes up to 100k on ≥16MB-RAM devices. Building the database runs in the background and can take **hours** on large libraries (Tangara: 20–30k opus files took 2.5–5h; an iPod with Rockbox: ~32k files in 15–20 min). The 876KB of base64 art per file inflates scan I/O, which is another reason to shrink it. Device layout should use **Artist folders** so the file browser is usable, not video_id shards (pack v2 path change) | Rockbox commits; forum reports |
| Which unit to buy | Any brand. On arrival, check **About → Version is in the hw4 list** (H2 V1.9–V2.3, Eros Q V2.2, F20 V3.4) before flashing. **Buy somewhere returnable.** H2 ~$119 sale / $149 list (2026-04). The vendor's own blog contradicts itself on specs (touchscreen, battery), so trust Rockbox's `erosqnative.h` instead (320×240, scroll wheel, RTC) | Rockbox install manual; vendor blog |
| Toolchain | Rockbox's own mipsel gcc (`tools/rockboxdev.sh`) on Linux. **WSL not installed here**: `wsl --install` (admin + reboot) or build on a GitHub Actions Ubuntu runner. Build the plugin in-tree at a pinned Rockbox commit and install *our* build to the SD, so the plugin API version always matches | checked this PC |

**Final verdict: HiFi Walker H2, if you listen on wired headphones.** If Bluetooth is a
requirement, the H2 under Rockbox can't do it today, and the answer changes. A Bluetooth-capable
programmable player would be the HiBy R1 (stock BT, LDAC; Rockbox port unstable) or a small Android DAP.
Note that the DIY ESP32-**S3** has no Bluetooth Classic, so no A2DP either.

**Amazon owner reviews (read 2026-10-10, ~45 reviews from 2017 to Sep 2026):**
- **Current stock is Rockbox-compatible.** A June 2026 buyer received "firmware 2.3 … corresponds
  to hardware revision 4", and that version is in the hw4 list. Four 2024–2026 owners installed Rockbox
  and recommend it ("any and all UI issues are resolved", including a song-start stutter).
- **Wheel wear:** two owners say the wheel degraded or wore out within months (Aug 2026, 2024).
  Others call it stiff or say it catches. One F20 owner says the **F20's wheel is textured metal** while the H2's is
  rubbery. **Design rule: every wheel action must also work from the buttons.**
- **Jack fragility:** three reports of the headphone jack's solder joint failing under cable strain
  in tight pockets. Use an L-shaped (right-angle) plug.
- **Unit lottery:** one dead left channel (Jul 2026), one stock-firmware distortion glitch. Test both
  channels and the volume inside the 30-day window.
- **Paths:** stock firmware crashes on filenames over ~158 characters or paths over ~221. YouTube titles can
  exceed that, so the device copy truncates names (keep paths well under 200).
- **Transfers:** USB transfer is slow and only works with the included cable. One owner saw corruption copying
  through Rockbox's USB mode. Do bulk copies with a USB microSD card reader.
- **Cards:** 512GB and 1TB reported working on stock firmware.
- **Battery:** owner reports range 7–30h (screen use dominates).
- **Weight:** "too heavy and bulky for a run"; "pulls a shirt pocket down". Fine for normal pockets.

Open design detail: like/dislike on Rockbox. Options are a WPS hotkey that launches our plugin
screen, Rockbox's database ratings exported via its changelog, or buttons on our Wheel plugin
screen. Decide during the plugin build. Skips and completes need nothing new: the core
playback log already has them.

### Unchanged from round 1 (applies to every option)

- 256GB card. Round 3 superseded the 128k-transcode idea: shrinking the art alone gets the copy to ~182GB with bit-exact audio.
- Pack v2 + port the engine v2.2 terms to the C brain (all options).
- Commit the repo. Use Tailscale meanwhile so the brain gets listening data.

---

## Round 1 (2026-10-09) — retro-handheld survey (A/B rejected by user on look)

Nothing has been bought since the July plan (`docs/EMBEDDED_PLAN.md`), so this is a
from-scratch re-evaluation: what changed in the market, what changed on our side, and
which device to actually buy. Facts are marked with sources/measurements; guesses are
labeled as guesses.

## TL;DR

- **The DIY ESP32 build stops being the first device.** It's still a valid endgame, but
  a ~$65 Linux retro handheld now covers the parts the July plan had to engineer:
  buttons, battery, case and headphone jack.
- **Recommended first device: Anbernic RG SP** (Aug 2026, $64.99). It's a GBA-SP clamshell
  with a D-pad, buttons, a 3.5mm jack, two microSD slots, Wi-Fi, and sleep when you close
  the lid. On it we write **one native app**: our existing C brain plus an LVGL UI. That
  same LVGL code later moves to the ESP32 unchanged, so no work is thrown away.
- **Alternative if you want your current web UI and engine unchanged:** an Android handheld
  shaped like a Game Boy (Retroid Pocket Classic, $149+), running the existing `server.py`
  and Svelte app on the device. It's the fastest way to get it in your pocket and costs the most.
- **Storage:** 512GB microSD prices have roughly doubled. Transcode the *device copy* to
  Opus 128k (~168GB) and use a 256GB card.
- **Our side:** the player hasn't been used since late July (plays: Jun 36, Jul 418,
  Aug 0, Sep 2). The brain is learning from about 450 events. Whatever device we pick,
  its first job is to make the player the thing you actually reach for.

## What changed since July

### Market

| Item | July plan assumed | Now (Oct 2026) |
|---|---|---|
| Tangara | not buyable | still no restock news found |
| Rockbox | Eros Q port verified | **Rockbox 4.0** (2025-04-01) officially supports Eros Q/K. New in 2025: **PortMaster build for Linux retro handhelds** (09-25), Anbernic RG Nano (unstable, 07-30), HiBy R1/R3ProII (unstable, 12-28) |
| Innioasis Y1/Y2 | Y1 Rockbox via vendor tool | the Y1 Rockbox fork repo was **archived 2026-01-14**; Y2 owners were still waiting for Rockbox in Jul 2026 |
| Waveshare S3-AMOLED-2.16 | $37–42 | **$29.99** at Waveshare (EU resellers out of stock) |
| 512GB microSD | "already owned?" | **~$35 → $70–100** (NAND shortage; 512GB TLC hit hardest; stockouts reported; relief predicted late 2027) |
| Handheld prices | — | "RAMpocalypse": Retroid Pocket Classic $129 → **$149** (2026-03); one mid-2026 guide lists it at $219 |
| ESP-IDF exFAT | none | docs now describe a *manual* FatFs config edit (no menuconfig option, licensing caveat). Still effectively FAT32 |
| ESP32-P4 handhelds | "overkill, young" | LilyGo T-Display-P4 has a jack, SD and battery management, but costs $119–160 and is often out of stock |
| **Anbernic RG SP** | didn't exist | released **2026-08-05, $64.99**. H700 (4×A53 1.5GHz), 1GB RAM, 3.4" 720×480 IPS, **D-pad + ABXY + L1/L2/R1/R2, no sticks**, **3.5mm jack**, **2× microSD (≤512GB each)**, Wi-Fi 5, BT 4.2, 3300mAh, **hall-sensor lid sleep**, 168g. A flashing guide for muOS/KNULLI/ROCKNIX exists (2026-08-26). Custom firmware was not ready at launch, so check status before ordering |

### Our side (measured 2026-10-09)

- **Library:** 54,045 tracks, 2,917 h, **225 GB** (4.16 MB/track, ~171 kbps average including embedded art).
- **Brain:** I re-ran `gen_goldens.py` and `test_brain` today. The C brain still matches the Python brain
  at default parameters. But it is **engine v1**. Everything added on 07-26 is opt-in, so
  the goldens never exercise it, and the C port lacks all of it: `cooc`, `heard`, `energy`, `bpm`,
  `same_w` (the AUTOPLAY_PARAMS sameness fix), decay-weighted session mood, cluster-Thompson
  exploration, adaptive ε, multi-source retrieval, `neg_halflife`/`strong_early_skip`.
  **Pack v1 also lacks the data those terms need** (energy and bpm from `analysis`, radio
  co-occurrence membership, cluster ids, `hook_sec`, `album_gain_db`). That means a pack v2
  plus a C catch-up port with goldens that turn those terms on. This is needed for every path except
  Android-with-`server.py`.
- **Usage:** see the TL;DR. The personalization has almost no data to learn from.
- **Repo:** `master` has **zero commits**. Months of work exist only on this disk. Commit
  before starting a port.

## What the device has to do (the July requirements, re-weighted)

1. Physical buttons as the main controls ("Game Boy feel"). *Hard requirement.*
2. The full library offline, with our brain choosing what plays next. *Hard requirement.*
3. Instant-on and long battery. These were the reasons for "no OS". The real test is
   wake-to-music in about 1s, not cold boot. A lid-sleep or Android-sleep device passes.
4. The play log syncs back to the PC, giving one shared taste history.
5. Design matters (docs/DESIGN_NOTES.md). The UI has to be ours, not a stock theme.
6. **New, inferred from the stall:** low activation energy. Since July the plan has needed
   fine-pitch soldering and an enclosure before it could play a single song.

## Options

| | **A. Linux handheld** (RG SP) + native app | **B. Android handheld** (RP Classic) + existing app | **C. Rockbox DAP** (Eros Q / H2 / F20) | **D. DIY ESP32-S3** (July plan) |
|---|---|---|---|---|
| Hardware cost | **$65** + card | $149–219 + card | ~$80–130 + card | ~$30 board + ~$30 audio/buttons + battery + printed case, plus tools |
| Soldering / enclosure | none | none | none | fine-pitch I2S tap or give up a button; 2–3 case print iterations |
| Buttons | D-pad, ABXY, 4 shoulders, start/select, lid | D-pad, ABXY, shoulders, plus touch | scroll wheel + buttons | whatever you build |
| Our code reused | C brain as-is; UI rewritten in LVGL (**that UI ports to D later**) | **everything**: server.py v2.2 + the Svelte UI, wheel and peek included | C brain, after a no-malloc/sparse-prefs refactor; UI limited to Rockbox screens | C brain; UI rewritten in LVGL |
| Engine on device | v1 now; v2.2 after the catch-up port | **v2.2 on day one** | v1 → v2.2 after the catch-up port | v1 → v2.2 after the catch-up port |
| Time to pocket | day 1 as a plain player (Rockbox via PortMaster); a few weeks to our app | **a weekend** (Termux route) | day 1 as a plain player; weeks for the brain plugin | months |
| Wake-to-music | lid open → resume (verify) | phone-style sleep and wake | fast | true instant-on |
| Audio | H700 built-in codec, **unmeasured** (hiss risk on sensitive IEMs) | Qualcomm phone-class | **ES9018K2M, best of the four** | PCM5102A + TPA6132A2, good |
| Battery (music, screen off) | **unknown**; my guess 12–20h, to be measured on day 1 | **unknown**; 5000mAh phone SoC, probably the best of the four | vendor claims ~10h (H2) | July estimate 8–25h |
| Sync | **Wi-Fi + SSH/HTTP** (automatic plays upload) | Wi-Fi | pull the SD card | Wi-Fi possible but slow for bulk |
| Filesystem | exFAT/ext4, so no FAT32 and no sharding | Android handles it | FAT32 | FAT32 + sharding |
| Main risk | CFW maturity on a new model; H700 audio and battery | it's Android: battery and process-killing quirks, less "device-like" | constrained UI; MIPS plugin ABI | the whole hardware build |

**Parked:** Tangara (not buyable). Innioasis Y1/Y2 (Rockbox fork archived, no Y2 port).
HiBy R1 (Rockbox port marked unstable). ESP32-P4 boards (cost, stock, immaturity). Phone-only
(already free via Tailscale, but needs the PC on and isn't a dedicated device).

## Cross-cutting: shrink the card, not the library

- Device copy = **Opus 128k transcode** of `D:\OfflineMusic`, art stripped: about
  2,917h × 128kbps ≈ **168 GB**. At 112k it's ~147 GB; at 96k ~126 GB. That fits a **256GB card**
  with room for the remaining queue. Originals on D:\ are untouched. Opus→Opus generation
  loss at 128k is inaudible on portable gear (this is a claim, so A/B it on your IEMs before the full run).
- On A and B the FAT32/sharding workaround disappears. Keep the sharded layout anyway,
  because it is harmless and keeps D possible.
- The thumbnails idea (`thumbs.bin`, 64×64 JPEG, ~170MB) becomes cheap on A and B.

## Recommendation

**A, the Anbernic RG SP**, unless you value "my exact app tomorrow" more than a native,
device-like player. In that case pick **B**.

Why A over the July plan: it delivers requirements 1–4 for $65 with zero hardware work, and
nothing built on it is thrown away. The C brain cross-compiles to a static aarch64
binary with the zig toolchain we already use (`zig cc -target aarch64-linux-musl`).
LVGL 9 has Linux framebuffer and evdev drivers, so the UI we write here is the UI the
ESP32 build would run, with only the display, input and audio drivers swapped. That moves
D from "first device" to "optional sequel".

Why A over B: it's cheaper, has no Android, and fits requirement 5 and the July "no
browser" intent. B is better on day-one completeness (the wheel, peek and v2.2 all come free).
Decision rule: if rebuilding the UI natively sounds like fun, choose A. If it sounds like a chore
standing between you and listening, choose B.

Why not C: it has the best audio, but our UI can't live there. You'd get Rockbox screens
plus a plugin, and the brain needs a no-malloc refactor for MIPS.

## If A: the sequence

0. **Today, free:** turn on Tailscale and listen through the existing player from your phone,
   so the brain starts collecting events before any hardware exists. Commit the repo.
1. **Before ordering:** check the current muOS/KNULLI release notes for RG SP support. If it's
   still missing, the RG35XX SP is the mature H700 clamshell fallback. Order the RG SP and a 256GB card.
2. **Day-1 bench** (replaces July Milestone 0): flash the custom firmware and install Rockbox via
   PortMaster as a baseline player. Then **measure**: screen-off playback current or hours,
   hiss on your IEMs, lid-close behavior while playing, whether `/dev/fb0` and evdev are usable
   under the CFW (or whether we need SDL2), and SSH access.
3. **Pack v2 + brain catch-up:** add energy, bpm, cooc membership, cluster and hook to the
   exporter; port the v2.2 terms to `firmware/core`; extend `gen_goldens.py` so they are
   switched on (the parity contract keeps holding).
4. **App v0:** static binary using LVGL + libopus/opusfile + ALSA (tinyalsa) + the brain. It
   covers NowPlaying, a windowed library list, autoplay, play/skip/like logging, and button mapping.
   That makes it a usable player.
5. **Wi-Fi sync:** the device posts `plays.omp` to a new `server.py` import endpoint and pulls
   pack updates. Bulk music still goes by moving the card to the PC.
6. **The Wheel + peek** on the D-pad (left/right = detents, A = play, the shoulder buttons = jump).
