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
  product page says. AAC would need an encoder port; possible later, not done. SBC at
  bitpool 53 is the "high quality" profile most phones use.
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
