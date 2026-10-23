# Bluetooth headphones on Coda OS (H2)

**Status (2026-10-11): on the real H2, it pairs and connects; sound after the fix is not yet confirmed.**
Build: `firmware/rockbox/out/coda-os-bt.zip`, installed on the card.

- **First hardware test (Galaxy Buds3 Pro).** The chip came up in 3.6 s (139 firmware patch
  records, no UART overruns). Search, pairing, connecting and AVRCP all worked, and the link
  ran SBC at 44.1 kHz, bitpool 52. But there was **no sound**: the H2's ES9018K2M volume
  path never set the software volume the Bluetooth sink uses, so it sent silence. The
  simulator's audio driver does set it, which is why the simulator didn't catch it. Fixed
  in patch 0015 and installed; waiting for the retest. Logs are in
  `data/h2_device/2026-10-11_bt_test1/`.
- The 48 kHz preference reaches Bluedroid after the codec is already configured, so the link
  stays at 44.1 kHz. That's harmless (Rockbox resamples).

## Where the "semi support" came from

- **The hardware.** HW4 H2s carry a Cypress CYW4343W (BCM4343A1, Bluetooth 4.1 class) on
  UART0, with RTS/CTS flow control and a `BT_REG_ON` power pin. The stock HiBy firmware
  uses it, which is the Bluetooth the box advertises.
- **Rockbox.** Nothing has been merged. Skye Green has an unmerged work-in-progress series
  on Gerrit (changes 7384–7387 and 7497/7499, last touched 2026-05-26). It ports
  ESP-IDF's Bluedroid stack to Rockbox, adds an H2 HCI driver that loads the chip's
  firmware patch, and a debug-menu test screen. It could find and connect to headphones,
  but any error panicked the whole player.

We can't change the stock firmware, so "fixing it in software" means making that stack
solid in our own build. That's what this is.

## What was wrong (all fixed, one commit each in `firmware/rockbox/bt/patches/`)

| Bug | What you'd have heard or seen |
|---|---|
| H4 packet length: the ACL high byte was masked to zero, `(x << 8) & 0xFF` | Any packet over 255 bytes (SDP and AVRCP replies) desynced the link, then panicked |
| UART: an RX interrupt released the "TX done" semaphore whenever TX was idle | Sends returned before their bytes were out; two HCI packets could interleave on the wire, garbling them and dropping the connection |
| UART: interrupt-enable register changed from thread and IRQ without masking interrupts | Rare lost or stuck interrupts |
| Bluedroid work queues were Rockbox event queues (16 slots, oldest silently overwritten) | Bursts of radio traffic lost work items, so the stack stalled or desynced |
| Alarms could fire after they were cancelled or freed | Use-after-free crashes and stray timeouts |
| A2DP pacing used the 10 ms tick | Each 30 ms audio tick encoded 2/3 to 4/3 of what it should, i.e. jittery audio |
| The Bluetooth sink's volume type defaulted to "hardware" (enum value 0) after an August upstream change | Bluetooth at **full volume** whatever the volume setting |
| On ES9018K2M units, setting the volume never set the software volume (left at 0) | **Silence** over Bluetooth while the player and visualiser ran (found on the device) |
| `panicf` on every runtime error (connect failed, headphones refused) | The whole player crashed |
| No power-up delay, no wait after the firmware patch, chip init blocked forever with no timeout | Flaky start-up, or a hang |
| A media command whose ack never came | Silence until a reconnect (now retried after 3 s) |
| Switching the audio output between DAC and Bluetooth | A DAC interrupt could land in the Bluetooth sink mid-switch |
| Thread stacks sized for ESP32 | Possible stack overflows (panics) on MIPS |

## What's new

- **Bluetooth service** (`apps/bluetooth/bluetooth.c`, in the BT tree). A control thread
  owns the radio, so Coda never blocks. It handles power on/off (remembered across boots),
  search, pairing ("just works"), connect and disconnect, and forgetting a device.
  The H2 stays connectable, so headphones that are switched back on can reconnect by
  themselves (most do this with the last device they used); if the link drops
  out of range there are three reconnect tries. Audio **pauses** whenever the headphones
  go away, like a phone. Wired and Bluetooth keep **separate volumes** (Bluetooth starts at
  −20 dB), and a crash while on Bluetooth can't leave wired IEMs at the Bluetooth level.
  Codec: SBC at 48 kHz (no resampling of the Opus library), bitpool up to 53 (~330 kbps).
  Headphone buttons (play, pause, next, previous) become Rockbox's media keys, which drive
  the same playlist Coda mirrors. That path isn't exercised in the simulator yet.
- **Coda UI.** Settings → Bluetooth shows the switch, *Your headphones* (remembered),
  *Nearby* (from a search; phones and other non-audio devices are filtered out) and
  *Search for headphones*. Play connects (pairing first if needed) or disconnects; hold
  Play to forget. While connected, a Bluetooth rune sits next to the battery. Shots of each
  state come from `firmware/host/coda_shots.c` (`c_bt_*`).
- **Log:** `/.coda/bt.log` records every state change and error (it rotates at 128 KB).

## Shared volume, earbud batteries, the jack asleep (patch 0016, 2026-10-14)

- **One volume, like a phone.** Headphones that report their volume over AVRCP (absolute
  volume, which Galaxy Buds and most modern headphones support) now share it. Coda asks
  what they report and subscribes to their volume. From their first answer on, the music
  goes out at full scale and the headphones set the loudness. The H2's volume keys step
  that volume (16 steps), and the headphones' own buttons or swipes move the same one;
  either way the bottom strip says "Volume 56%". Before this, the H2 attenuated in software
  and the headphones kept a separate volume of their own, so the two never moved together.
  Each pair keeps its volume (`absvol=` in `/.rockbox/bt_devices.txt`). A pair that is new
  to the H2 starts no louder than half way. Headphones without absolute volume keep the
  old software volume, and their volume buttons (AVRCP passthrough) now act as the H2's
  volume keys. `bt.log`: `avrc-ct: they report ...`, `volume: shared with ..., N%`.
- **Galaxy Buds batteries.** Samsung's buds report their batteries over their own RFCOMM
  service (UUID `2e73a4ad-332d-41fc-90e2-16bef06523f2`). This is the channel Galaxy
  Wearable uses; the format is documented by the open GalaxyBudsClient. The service
  (`apps/bluetooth/buds.c`) waits 3 s after the audio link is up, finds the channel by
  SDP, opens it, and reads messages 0x61/0x60: left, right, case, and where each bud is.
  It only listens; it answers the first message with "manager info", as the phone app
  does. Other headphones don't have the service, so nothing happens with them. Coda shows
  the emptier bud's level next to the Bluetooth mark on every screen, and *L80 R75* on
  the pair's row in Settings → Bluetooth. Diorama has the buds' case on the desk by the
  headphone stand, with its light green/amber/red like the real one.
  RFCOMM runs through Bluedroid's BTA JV layer, without the SPP profile on top (that
  needs FreeRTOS ring buffers and a VFS). `bta_jv_act.c` had every include under the
  L2CAP switch and is fixed. `bt.log`: `buds: Samsung channel N`, `buds: left 80%, ...`.
- **The jack sleeps on Bluetooth.** While audio goes to headphones, the headphone amp is
  shut down (output muted first) and the DAC gets no I2S clocks. Both wake before the jack
  plays again (`audiohw_wired_sleep`, erosqnative). `bt.log` now also records each change
  between sniff and active mode, so the battery log can be read against the radio's state.

## Earbuds out, a stuck stream, the charge screen (patch 0017, 2026-10-15)

- **On the H2, 0016 worked:** the volume is shared (`avrc-ct: they report 2000`) and the
  Galaxy Buds channel opens and reports batteries. Only the right bud was connected all
  day (placement `01`/`02`, left unknown); it drained about 20%/h while streaming.
- **Taking the earbuds out pauses, putting them back plays.** The buds say where each one
  sits (placement in 0x60/0x61: 1 in an ear, 2 out, 3/4 in the case). When the last bud in
  an ear comes out while music plays, the player pauses ("Paused: earbuds out"); one back
  in within 30 minutes and it plays again. `bt.log`: `buds: placement 01 -> 02`,
  `buds: out of your ears, paused`, `buds: back in, playing`.
- **The stream keeps a log.** `a2dp: streaming` when a start is accepted, `a2dp: stopped
  after N s, M short ticks` when it's suspended (a short tick = Bluedroid asked for audio
  and Rockbox had less than that: a stutter). As the audio comes on, the packets the link
  uses: `packets up to 1021 bytes` = 3 Mbit EDR, 679 = 2 Mbit, 339 = basic rate. If it
  says 339, every packet takes up to three times the airtime, on both radios.
- **Stuck streams.** A started stream that gets no media ticks for 3 s is suspended and
  started again. If the headphones stop the stream themselves, or refuse to start it (a
  call; the phone took them), the player pauses instead of "playing" into silence.
  `bt_diag()` gives Coda's playback watchdog the stream's state in a line, and
  `bt_rescue()` turns the radio off and on, reconnects, and plays again once they're back.
  (On day 1 a song stuttered and stopped, and nothing played again until a restart. The
  logs show the stream stopping about 2 minutes in, but not why, so the next log will.)
- **The charge screen.** When plugging in the charger switches the player on, Coda shows
  the charge and the radio waits (`bt: waiting (the charger switched the player on)`): a
  player charging at night doesn't take the earbuds from the phone. The player proper
  (any button) starts it as it was.
- Not yet addressed: on 4 of about 25 boots the chip didn't answer (`hci: controller
  stopped accepting data (CTS stuck)`, three tries); the next boot was fine. (Patch 0018
  retries with the chip held off longer and the UART started afresh.)

## The song on a car's display (patch 0019, 2026-10-15)

- **The car showed "Connected" and nothing else** (a 2013 Corolla; a phone shows the song
  there). A car's head unit is an AVRCP *controller*: it asks the player's *target* for the
  title, artist, ... (GetElementAttributes) and the position (GetPlayStatus), and asks to
  hear when the track or the play state changes (RegisterNotification). ESP-IDF's target
  rejected both requests ("todo"), allowed no notification but volume, and offered none,
  so the car asked, was refused, and showed nothing.
- **Now the stack answers them** from a now-playing copy (`esp_avrc_tg_set_now_playing`):
  title, artist, album, track number, genre, playing time, in UTF-8; the position carried
  forward while playing; InformDisplayCharset accepted. It offers the play state, track and
  position notifications. `bluetooth.c` reads the playing track once a second while
  connected, answers each registration at once and sends CHANGED when the track, play/pause
  or (at the interval the car asked for) the position changes.
- **Why day 1's log never showed the car's remote-control link:** `avrc-ct: up` is only
  logged for devices that are also a *target* (headphones with their own volume). A car
  that's only a controller connects to our target, whose events weren't logged. Now:
  `avrc-tg: up`, `avrc-tg: they are a controller with features ...`, `avrc-tg: they listen
  for the track`, `avrc-tg: they asked what's playing (7 things, 5 answered): title /
  artist`, each once a connection. If the car still shows nothing, these lines say how far
  it got.
- The simulator logs what a car would be told at each change (`np: [title] [artist] ...`).

## A chip that doesn't answer at boot (patch 0020, 2026-10-15)

About one boot in eight, the chip never accepts data at power-on ("CTS stuck"), through every
quick retry (0018's longer off-times included). Switching Bluetooth on by hand a minute later
always brought it up in under 4 s. So the radio now tries again by itself, with the chip off
in between: after 5 s, then 20 s ("Bluetooth didn't start, trying again"). Only after the
third failure does it say "The Bluetooth chip didn't answer". Turning Bluetooth on by hand
starts afresh. `bt.log`: `radio: the chip didn't answer, again in 5 s (try 2 of 3)`,
`radio: the chip answered on try 3`. The cause is still unknown; these lines show how long
it needs. Simulator: `RB_BT_FAKE_FAIL=N`.

## 48 kHz, and Standard / High sound quality (patch 0021, 2026-10-18)

Every link used to run at 44.1 kHz, with your buds and with the car, even though the songs
are 48 kHz Opus and both say they take 48. ESP-IDF's source side offered only 44.1. The app's
request for 48 kHz was refused as unsupported (`pref mcc status 6` in every `bt.log`), so
Rockbox's resampler converted every song first. That resampler is linear interpolation: about
-1.3 dB at 10 kHz and -3 dB at 15 kHz, plus aliasing. The encoder also aimed at a fixed
328 kbps, which only lands on bitpool 53 for 44.1 kHz joint stereo.

The stack now picks each sink's config from what it says it takes: 48 kHz when it can, and
the channel mode from **Settings → Bluetooth → Sound quality** (Play switches it):

| | channel mode | bitpool | Buds3 Pro at 48 kHz |
|---|---|---|---|
| Standard | joint stereo | up to 53 (theirs: 52) | 351 kbps |
| High | dual channel ("SBC XQ") | up to 38 for each channel | 492 kbps |

The encoder now aims at the top of the agreed bitpool. On a basic rate link it still sends no
more than 229 kbps. One media packet now fits one radio packet, as on Android: at most 663
bytes on a 2 Mbit EDR link like the buds' (679-byte packets). Before, a media packet the size
of their MTU went out as two radio packets, the second mostly empty. With dual channel at
bitpool 38, four frames fit each radio packet.

High costs more radio time: some battery on the H2 and on the buds, and less margin when the
signal is weak (a pocket at the gym). Changing it while music plays stops the stream and
starts it again, with a short gap while the link is reconfigured. The setting is remembered
as `quality=` in `bt_devices.txt`. The row shows what the link is carrying now
(`high, 492 kbps`). `bt.log`: `a2dp: configured sbc 48000 Hz dual channel, bitpool 2-38
(492 kbps)`, `quality: high (dual channel)`.

Host test: Bluedroid's own encoder (built as a Windows program, because the encoder needs a
32-bit `long`, as on the H2's MIPS), ffmpeg's SBC decoder, and 30 s of three songs from the
card. The table gives the error against the file, in dB below the music in each band (lower
is better):

| | overall SNR | 8–12 kHz | 12–16 kHz | 16–20 kHz |
|---|---|---|---|---|
| metal: before (44.1 linear + joint 52) | 28.5 | -14.8 | -9.2 | -2.4 |
| metal: Standard (48 joint 52) | 32.0 | -18.8 | -12.6 | -5.0 |
| metal: High (48 dual 38) | 41.8 | -29.3 | -24.0 | -14.6 |
| orchestra: before / Standard / High | 35.6 / 38.5 / 47.9 | -14.7 / -18.6 / -28.2 | -8.7 / -12.9 / -21.8 | -3.1 / -6.8 / -16.2 |

These figures measure error energy, not loudness as you hear it. The direction is the same
for every song and every band.

## The bitrate follows the link; each device keeps its own quality (patch 0022, 2026-10-19)

What happened on High (bt.log, 10-19): in the car, the stream ran with no errors on our side
but nothing came out of the speakers. The car's sink says it takes dual channel, then plays
silence on it, a known problem with "SBC XQ". With the H2 in a knee-level pocket, the buds
cut out often.

- **Each device keeps its own setting.** It's `quality=<address> 0|1` in `bt_devices.txt`,
  set as a link starts (the device's own, or Standard if it was never set). The old setting
  for every device (`quality=1`) is ignored, so the car stays on Standard while the buds can
  be on High. The Sound quality row changes the setting of the device that's connected, or
  of the last one.
- **The bitrate steps down when the radio falls behind.** A radio packet that doesn't get
  through is sent again. In a pocket, those resends use up the airtime the music needed.
  The queue overflows (ours, or bta_av's), and the stack throws music away: a dropout.
  `coda_a2dp_drops` now counts those packets. Each second with drops lowers the SBC bitpool
  one step (85 / 72 / 60 % of the top, no less than 24). The change is live: an SBC frame
  says its own bitpool, so the headphones follow without a reconfigure. After a step, the
  link gets 3 s to settle. A clear half minute raises it one step. If going up brings the
  drops back within 20 s, the wait before the next try doubles, up to 5 minutes.
  Drops in a stream's first 2 s don't count.

  | Standard at 48 kHz (top 52) | bitpool | kbps |
  |---|---|---|
  | clear | 52 | 351 |
  | step 1 | 44 | ~303 |
  | step 2 | 37 | ~261 |
  | step 3 | 31 | ~225 |
- **High that drops falls back to Standard** until the next connection. The player says
  "Weak signal: standard quality for now". The stream is reconfigured (a ~0.1 s gap), and
  after that Standard's steps apply. The setting itself stays High.
- The Sound quality row shows the rate being sent now. While stepped down, its hint says
  "weak signal: fewer kbps". `bt.log` gains `link: behind (N dropped): bitpool 52 -> 44,
  303 kbps`, `link: clear: bitpool 44 -> 52, 351 kbps`, `link: high is dropping ...`, and
  `a2dp: stopped after N s, M short ticks, K packets dropped`.

What this can't catch: a sink that runs dry without our queue backing up (the buds' own
buffer, or a relay between the two buds). The next logs will tell. If a stream drops out
but logs "0 packets dropped", the loss is past our side.

## What the stock firmware does differently (research, 2026-10-19)

- **Battery.** The H2 manual promises "Playback Time >10 hours" from 1500 mAh. Our
  battery.csv for 10-15 to 10-19 shows 7.6 %/h over 6.4 h of Bluetooth streaming with the
  screen off, about 13 h from full. So we already beat the stock claim.
- **Range.** The vendor's own Bluetooth guide says to stay within about 3 m. The manual says
  the metal case limits range and to "ensure the back of the player faces your target
  Bluetooth device". The antenna works through the back, so in a pocket, the back should
  face out from the leg.
- **Chip firmware.** We load `BCM4343A1_001.002.009.0122.0538`
  (`BAW_NM372SM_Generic_BCM43438A1_UART_26MHz_wlbga_eLG_lite`), the module's generic
  patch. No newer patch for this module turned up.
- **Sleep mode (not done).** The HW4 board wires the Broadcom wake lines: `HOST_WAKE_BT`
  on PC19 and `BT_WAKE_HOST` on PC20 (gpio-target.h). Our driver never sends Write Sleep
  Mode (vendor command 0xFC27), so the chip stays fully awake whenever the radio is on.
  Linux's hci_bcm.c does send it (UART sleep mode, 300 ms idle thresholds), and a Linux
  stock firmware probably does too. This would save the most when connected but paused,
  or when on with nothing connected (10-19 log: 6 %/h and 12 %/h, though from short
  samples). It saves little while streaming, when packets keep the chip awake. The risk:
  with a polarity wrong, the chip sleeps and stops answering. So it needs its own build
  and a hardware test.
- **CPU clock (not done).** Rockbox runs the X1000 at 1008 MHz all the time.
  `set_cpu_frequency()` exists in system-x1000.c, but no X1000 player defines
  `HAVE_ADJUSTABLE_CPU_FREQ`. Streaming keeps the CPU about 11 % busy, so ~250–336 MHz
  would do. The gain is uncertain: an idle X1000 waits with its clock gated, and the core
  voltage doesn't change. It's an A/B test on battery.csv.
- **aptX.** The manual advertises aptX. Free encoders exist (libfreeaptx, ffmpeg), but
  neither the Buds3 Pro nor the car takes aptX, so it would change nothing here.

## Testing it on the H2

1. Card in the PC, then
   `.venv\Scripts\python scripts\install_coda_os.py --card E:\ --zip coda-os-bt.zip`.
   This replaces only the Coda OS folder; your settings carry across.
   To undo: run it again without `--zip` (plain Coda OS), or `--revert` (the firmware
   from before Coda OS).
2. On the H2: Settings → Bluetooth → Play on *Bluetooth*. It should say "starting", then
   "on" within a few seconds (loading the chip's firmware at 115200 baud takes about
   3–4 s), then search.
3. Put the headphones in pairing mode, pick them, then play something.
4. Things to try: volume keys, the headphones' play/pause/next buttons, walking out of
   range and back, switching the headphones off and on, and rebooting the H2 with
   Bluetooth on.
5. Bring back `/.coda/bt.log` whatever happens. If the chip doesn't come up, the log names
   the exact step (`hci: reset: no reply`, `patchram write failed, status ..`, and so on).

## What software can't fix

- **Range.** The antenna sits inside an aluminium body. Expect a pocket-to-ears range,
  not across the house.
- **Codecs.** SBC only. The chip and the licences rule out LDAC and aptX, despite what the
  product page says. AAC would need an encoder port, and from a ~140 kbps Opus source it
  wouldn't beat SBC dual channel (the High setting, patch 0021). SBC at bitpool 53 is the
  "high quality" profile most phones use. LE Audio (LC3) needs a Bluetooth 5.2 chip, and the
  CYW4343W is 4.1.
- **Battery.** The radio costs power while it's on. Turn it off when you're on wired.
- **Latency.** About 150–250 ms from the headphones' buffer. That's irrelevant for music;
  wheel peek previews will feel slightly late.

## Building and tests

```
bash firmware/rockbox/bt/setup_bt_tree.sh                               # ~/rockbox-bt
SRC=~/rockbox-bt OUTNAME=coda-os-bt bash firmware/rockbox/os/build_os.sh target
SRC=~/rockbox-bt bash firmware/rockbox/os/build_os.sh sim               # build-os-sim
```

- The simulator build has a **fake HCI controller** (`uisimulator/common/hci-sim.c`).
  The real Bluedroid stack starts on it in about 0.4 s and searches it: three headphones,
  plus a phone that must be filtered out. Connections fail with a page timeout.
  Verified: on, search, the filter, the "Couldn't connect" path, off and on again
  (threads stop and restart), and the radio coming back after a reboot.
- `RB_BT_FAKE_SINK=1` pulls audio through the Bluetooth sink at the negotiated rate with
  no link. Measured: 1,153,920 bytes in 6,010 ms (exactly the 48 kHz rate), real samples
  at the expected level, playback advanced 6.0 s, then back on wired and paused.
- What only the device can prove: the UART driver, the chip's firmware load, the radio
  link, SBC streaming to real headphones, and AVRCP. The first four came up on the device
  on the first try; actual sound and the headphone buttons are still waiting on the retest.
- Gotcha: Rockbox's makefiles keep their source list in `SRC`, so `build_os.sh` runs
  `env -u SRC make`. An exported `SRC=~/rockbox-bt` otherwise ended up on the link line.
