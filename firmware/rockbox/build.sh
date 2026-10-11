#!/usr/bin/env bash
# Build Coda for the H2 (target) or the H2 simulator (sim). Run in WSL:
#   bash firmware/rockbox/build.sh sim       # ~/rockbox/build-sim/rockboxui + coda.rock
#   bash firmware/rockbox/build.sh target    # ~/rockbox/build-erosq/rockbox.zip (incl. coda.rock)
set -euo pipefail
MODE=${1:-sim}
SRC=${SRC:-$HOME/rockbox}
export PATH=$HOME/rbdev/bin:$PATH
bash "$(dirname "$0")/sync_plugin.sh"
case "$MODE" in
    sim)    DIR=$SRC/build-sim;   TYPE=s ;;
    target) DIR=$SRC/build-erosq; TYPE=n ;;
    *) echo "usage: build.sh sim|target"; exit 2 ;;
esac
mkdir -p "$DIR"
cd "$DIR"
[ -f Makefile ] || ../tools/configure --target=erosqnative --type=$TYPE < /dev/null > configure.log 2>&1
make -j"${JOBS:-6}" > make.log 2>&1 || { grep -n -B2 -A6 -E "error|Error" make.log | head -80; exit 1; }
if [ "$MODE" = sim ]; then
    make install > install.log 2>&1                 # the sim loads plugins from simdisk/
fi
if [ "$MODE" = target ]; then
    make zip > zip.log 2>&1; ls -la rockbox.zip
    OUT="$(cd "$(dirname "$0")" && pwd)/out"          # for scripts/export_h2.py
    mkdir -p "$OUT" && cp apps/plugins/coda/coda.rock rockbox.zip "$OUT/"
fi
ls -la apps/plugins/coda/coda.rock
