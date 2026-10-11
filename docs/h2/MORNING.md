# H2 night session: what changed, what to try (2026-10-11)

Everything below is committed (`git log`). The card in the reader (E:) is ready for the
**stock-firmware test** right now. Coda OS is built but **not installed**, waiting on your OK
for the boot animation.

## 1. Try on the H2 now (current firmware + new coda.rock)

The card has all 18,388 songs (verified 18,388/18,388), the new app, and engine v3.
Plugins > Applications > coda, as before.

| what | how |
|---|---|
| **Queue** | Menu > Queue. Picking a song jumps there. Autoplay now only adds when the queue runs out, so an OST plays through in order (before, autoplay took over after its first track). |
| **Explore** | Menu > Explore: Fresh finds / Deep cuts (from your taste model), 12 per visit |
| **Search** | Menu > Search: spin for a letter, Play types it. The rail also has space, ← (delete) and ↓ (go to results). Back deletes a letter. Hold Play = go to results. |
| **Soundtracks** | Library > Soundtracks: 116 OSTs under franchise dividers, Play / Shuffle, album order |
| **Genres** | Library > Genres > a genre: **Start station** (autoplay stays in the genre) or Shuffle all |
| **Now Playing sheet** | Menu on Now Playing: Like/Unlike, Dislike (skips), Go to artist, Queue |
| **Track sheet** | hold Play on any song in a list: Play next, Add to queue, Like, Go to artist |
| **Wheel peek** | land on a slice and wait ~0.6 s: it previews at 35%, then returns you to your song where it was. One decoder, so the swap re-buffers. Settings > Wheel peek turns it off if it feels wrong. |
| **Seeking** | spin on Now Playing: detents now add up (red time while you seek) |
| **Clock** | Settings > Clock (on stock firmware it tells you to use Rockbox's clock setting; Coda OS sets the RTC itself) |
| **Autoplay** | engine v3, the web player's current one (see 4) |

Your device settings file has `theme=1` (night) from your test last night. Settings > Theme
puts it back to day.

## 2. Coda OS: approve the boot animation first

- Look: `docs/h2/boot/boot.gif` (and `contact.png`). A Klein-blue record drops onto the
  platter, spins up, the tonearm swings over and sets down, "Coda." is stamped. 1.6 s, and it
  plays *while* the library loads (in the simulator the library was ready before the record
  landed). Frame 0, the empty platter, replaces the Rockbox logo during startup.
- If it's right: `.venv\Scripts\python scripts\install_coda_os.py --card E:\`
  (renames the current `/.rockbox` to `/.rockbox.prev`, unpacks Coda OS, keeps your
  config.cfg). Undo anytime: `... install_coda_os.py --card E:\ --revert`.
- If it's not right, say what to change; it's one C file (`firmware/ui/boot.c`) and
  `firmware/host/build/boot_shots.exe docs/h2/boot` re-renders the frames from the device
  code.

What Coda OS is: our Rockbox build (pinned commit) with Coda linked into the firmware as
the root app: 8 MiB heap (was 2 MiB), its own 64 KB thread, boots straight into Coda.
**Hidden way out: hold Menu + Back for 1.5 s** to reach Rockbox's menu ("Coda" on top, Plugins
gone); Back at its root returns to Coda. Autoplay keeps running while you're out.
USB: Coda draws the "Plugged in" screen; afterwards it reloads the library.

Verified only in the Rockbox simulator, **not on the device yet.** That's the next test.

## 3. Strip build (stage 3): what it is and isn't

`install_coda_os.py --strip` = Coda OS with no Rockbox UI reachable at all: no menus, no
escape combo, no database scan, no plugins/themes on the card. Kernel, drivers, codecs,
playback, USB and power/charging are untouched (no battery/charger/PMU code was modified).

Honest limit: the binary still contains Rockbox's UI code (only 19 KB dropped), because
Rockbox's settings table references menus and skins, so the linker keeps them even though
nothing can reach them on screen (about 250 KB of the 1.29 MB firmware). Cutting that code out for real means rewriting the
settings table. That's not done. It's unreachable, it isn't running, and it costs about 0.25 MB
of RAM out of 32 MB.

## 4. Autoplay = engine v3 (the web player's current one)

The prompt said "port v2.2"; the web player shipped v3 on 10-10, so v3 is what's ported:
centered embeddings, window-relative weights, your YouTube Music history in the taste,
session rejections and the skip anchor (an early skip re-decides the queued pick and
continues from the last song you kept), song-radio co-occurrence, energy/tempo continuity,
Thompson-sampled exploration with the sound budget. The device even uses CPython's exact
random generator, so it draws the same "fresh" and explore picks the web player would.

Proof: `firmware/host/build/test_engine3.exe data/device_pack_v3 firmware/host/goldens_v3`
compares it with the server's own functions: 86/86 decisions identical (46 of them
exploration), every score within 3e-6. v1 tests still pass too.

Device differences: retrieval is the server's LOW_MEM path (neighbours + radio, no 54k
full-matrix scan); energy/tempo are quantized (1/254, 0.1 BPM).

## 5. Play log and battery

- Your H2 plays sync back automatically: `export_h2.py` (or `scripts\h2_sync.py --card E:\`)
  pulls new device events into the PC `plays` table first. Last night's 13 are already in.
- Battery: Coda now logs level/voltage/current every 5 min to `/.coda/battery.csv`. To
  measure: charge full, unplug, play with autoplay and the screen off for a few hours (or until
  it shuts off), then `.venv\Scripts\python scripts\h2_battery.py --card E:\`.

## 6. Smaller things

- Song titles: 250 characters had no glyph (► alone in 264 titles). Windows' own fonts are
  now fallbacks when building the card, and invisible marks and odd spaces no longer print boxes. About 8
  rare characters remain (Yi, Lisu, a hieroglyph).
- Card config: your volume (-36) etc. were stranded in `config.cfg.new` from an interrupted
  save. Restored. Rockbox's status bar is off (Coda draws its own).
- Backups of what was on the card before tonight: `data/h2_device/2026-10-11_pre_fullcopy/`.
