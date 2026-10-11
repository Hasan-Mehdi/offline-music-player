#!/usr/bin/env bash
# Point the H2 simulator's virtual card (build-sim/simdisk) at a card folder made by
# scripts/export_h2.py, so the sim sees exactly what the device will:
#   simdisk/.coda -> <card>/.coda      simdisk/Music -> <card>/Music
#   bash firmware/rockbox/sim_setup.sh /mnt/d/h2stage
# (then drive it with sim_run.sh)
set -euo pipefail
CARD=${1:-/mnt/d/h2stage}
SIM=${SIM:-$HOME/rockbox/build-sim}
cd "$SIM"
make install > install.log 2>&1
for d in .coda Music; do
    [ -L "simdisk/$d" ] || rm -rf "simdisk/$d"
    ln -sfn "$CARD/$d" "simdisk/$d"
done
ls -la simdisk/.coda simdisk/Music
