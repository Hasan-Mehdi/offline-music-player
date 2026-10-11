#!/usr/bin/env bash
# A throwaway sim card for Coda OS tests: a private copy of a card's /.coda (the sim writes
# its play log, settings and boot count there) + the card's Music folder linked read-only.
#   bash firmware/rockbox/os/sim_card.sh <card_dir> [sim_build_dir]
set -euo pipefail
CARD=${1:-/mnt/d/h2stage}
SIM=${2:-$HOME/rockbox/build-os-sim}
PRIV=$HOME/simcard
rm -rf "$PRIV" && mkdir -p "$PRIV"
cp -r "$CARD/.coda" "$PRIV/.coda"
rm -f "$PRIV/.coda/coda.log" "$PRIV/.coda/boot.txt" "$PRIV/.coda/battery.csv"
cd "$SIM"
for d in .coda Music; do
    [ -L "simdisk/$d" ] || rm -rf "simdisk/$d"
done
ln -sfn "$PRIV/.coda" simdisk/.coda
ln -sfn "$CARD/Music" simdisk/Music
rm -f simdisk/.rockbox/.playlist_control simdisk/.rockbox/.resume.cfg
ls -la simdisk/
