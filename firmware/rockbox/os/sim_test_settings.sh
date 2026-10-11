#!/usr/bin/env bash
# Coda OS sim test: device settings, volume limit, clean power-off, resume after boot.
set -uo pipefail
REPO=/mnt/c/Users/hasan/code/apps/offline-music-player
OUT=${1:-$HOME/simtest}
export SIM=${SIM:-$HOME/rockbox/build-os-sim}
rm -rf "$OUT"; mkdir -p "$OUT"
D="down down down down down"
# session 1: play a song, change settings, hit the volume limit, power off (hold Power)
bash "$REPO/firmware/rockbox/sim_run.sh" "$OUT/s1" wait:3000 shot:menu \
    $D play play play wait:4000 shot:playing \
    menu down down play shot:settings \
    down down down down down down down down down play up up up up up shot:bright_adjust play \
    down down play up up up up up up up up up up up up up up up up shot:volmax play \
    KP_Subtract KP_Subtract KP_Subtract KP_Subtract KP_Subtract KP_Subtract shot:vol_limit \
    wait:3000 hold:Escape:3500 wait:5000
echo "--- s1 log"; cat "$HOME/simcard/.coda/coda.log" | tail -12
echo "--- config.cfg"; grep -E "brightness|volume|backlight|idle|bass|treble|unplug" "$SIM/simdisk/.rockbox/config.cfg"
echo "--- boot.txt"; cat "$HOME/simcard/.coda/boot.txt"
# session 2: boot again -> the queue comes back, paused
bash "$REPO/firmware/rockbox/sim_run.sh" "$OUT/s2" wait:3000 shot:menu down play shot:now
echo "--- s2 log"; tail -8 "$HOME/simcard/.coda/coda.log"
