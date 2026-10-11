#!/usr/bin/env bash
# Coda OS sim test: resume lands on time; the crash screen; the crash-loop guard.
set -uo pipefail
REPO=/mnt/c/Users/hasan/code/apps/offline-music-player
OUT=${1:-$HOME/simtest_crash}
export SIM=${SIM:-$HOME/rockbox/build-os-sim}
RUN="bash $REPO/firmware/rockbox/sim_run.sh"
rm -rf "$OUT"; mkdir -p "$OUT"
$RUN "$OUT/r" wait:1000 down play shot:now > /dev/null 2>&1
grep "resumed" "$HOME/simcard/.coda/coda.log" | tail -1
echo 0 > "$HOME/simcard/.coda/boot.txt"     # the session above was killed, not crashed
touch "$HOME/simcard/.coda/crash_test"
for i in 1 2 3; do
    BOOT_WAIT=1.2 $RUN "$OUT/c$i" wait:900 shot:crash > /dev/null 2>&1
    echo "boot $i: boot.txt=$(cat $HOME/simcard/.coda/boot.txt) $(grep -c PANIC $OUT/c$i/rockboxui.log) panic line(s)"
done
rm -f "$HOME/simcard/.coda/crash_test"
BOOT_WAIT=3 $RUN "$OUT/g" shot:guard play wait:3000 shot:after_play > /dev/null 2>&1
echo "after guard: boot.txt=$(cat $HOME/simcard/.coda/boot.txt)"
grep "os: " "$HOME/simcard/.coda/coda.log" | tail -6
cp -r "$OUT" /mnt/c/Users/hasan/AppData/Local/Temp/claude_simtest/
