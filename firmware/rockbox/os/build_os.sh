#!/usr/bin/env bash
# Build Coda OS: our own Rockbox (pinned tree, ~/rockbox) with Coda compiled in as the root
# app. Run in WSL:
#   bash firmware/rockbox/os/build_os.sh sim      # ~/rockbox/build-os-sim (installed simdisk)
#   bash firmware/rockbox/os/build_os.sh target   # firmware/rockbox/out/coda-os.zip (.rockbox)
# Uses its own build dirs, so the stock/plugin builds (build.sh) stay as they are.
set -euo pipefail
MODE=${1:-sim}
REPO=${REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}
SRC=${SRC:-$HOME/rockbox}
export PATH=$HOME/rbdev/bin:$PATH

bash "$REPO/firmware/rockbox/sync_plugin.sh" > /dev/null          # Coda sources -> apps/plugins/coda
mkdir -p "$SRC/apps/coda"
cp "$REPO/firmware/rockbox/os/coda_os.make" "$SRC/apps/coda/"
python3 "$REPO/firmware/rockbox/os/patch_core.py" "$SRC"

case "$MODE" in
    sim)    DIR=$SRC/build-os-sim; TYPE=s ;;
    target) DIR=$SRC/build-os;     TYPE=n ;;
    *) echo "usage: build_os.sh sim|target"; exit 2 ;;
esac
mkdir -p "$DIR"
cd "$DIR"
if [ ! -f Makefile ]; then
    ../tools/configure --target=erosqnative --type=$TYPE < /dev/null > configure.log 2>&1
    sed -i 's/^export EXTRA_DEFINES=\(.*\)$/export EXTRA_DEFINES=\1 -DCODA_OS/' Makefile
fi
grep -q -- '-DCODA_OS' Makefile || { echo "Makefile lacks -DCODA_OS"; exit 1; }
make -j"${JOBS:-6}" > make.log 2>&1 || { grep -n -B2 -A6 -E "error|Error|undefined" make.log | head -80; exit 1; }
if [ "$MODE" = sim ]; then
    make install > install.log 2>&1
    ls -la rockboxui
else
    make zip > zip.log 2>&1
    # Coda OS ships no games, demos or plugin menus (Coda is the app)
    zip -q -d rockbox.zip '.rockbox/rocks/games/*' '.rockbox/rocks/demos/*' > /dev/null 2>&1 || true
    OUT="$REPO/firmware/rockbox/out"
    mkdir -p "$OUT" && cp rockbox.zip "$OUT/coda-os.zip"
    ls -la rockbox.erosq "$OUT/coda-os.zip"
fi
grep -E "coda_os|libcoda" make.log | tail -3 || true
