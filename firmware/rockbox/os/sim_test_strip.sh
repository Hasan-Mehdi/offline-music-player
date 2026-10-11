#!/usr/bin/env bash
# Coda OS strip build in the simulator: boot, play, settings, USB in/out, power off,
# boot again (resume). The things the stripped core still has to do on its own.
set -uo pipefail
REPO=/mnt/c/Users/hasan/code/apps/offline-music-player
OUT=${1:-$HOME/simtest_strip}
export SIM=$HOME/rockbox/build-strip-sim
RUN="bash $REPO/firmware/rockbox/sim_run.sh"
rm -rf "$OUT"; mkdir -p "$OUT"
bash "$REPO/firmware/rockbox/os/sim_card.sh" /mnt/d/h2stage "$SIM" > /dev/null
D="down down down down down"
$RUN "$OUT/s1" wait:2500 shot:menu $D play play play wait:4000 shot:now \
    menu down down play shot:settings back \
    u wait:2500 shot:usb u wait:5000 shot:after_usb \
    wait:9000 hold:Escape:3500 wait:5000 > "$OUT/s1.txt" 2>&1
echo "--- s1"; grep "os: \|coda:" "$HOME/simcard/.coda/coda.log"
echo "--- boot.txt $(cat $HOME/simcard/.coda/boot.txt)"
$RUN "$OUT/s2" wait:2500 down play shot:now wait:2000 shot:now2 > "$OUT/s2.txt" 2>&1
echo "--- s2"; grep "os: " "$HOME/simcard/.coda/coda.log" | tail -4
grep -i "panic\|error\|segfault" "$OUT"/s*/rockboxui.log | head -5
cp -r "$OUT" /mnt/c/Users/hasan/AppData/Local/Temp/claude_simtest/
