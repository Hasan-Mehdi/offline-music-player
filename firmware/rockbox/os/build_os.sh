#!/usr/bin/env bash
# Build Coda OS: our own Rockbox (pinned tree, ~/rockbox) with Coda compiled in as the root
# app. Run in WSL:
#   bash firmware/rockbox/os/build_os.sh sim            # ~/rockbox/build-os-sim (simdisk installed)
#   bash firmware/rockbox/os/build_os.sh target         # firmware/rockbox/out/coda-os.zip
#   bash firmware/rockbox/os/build_os.sh strip-sim      # no Rockbox UI at all (stage 3)
#   bash firmware/rockbox/os/build_os.sh strip-target   # firmware/rockbox/out/coda-os-strip.zip
# Each mode has its own build dir, so the stock/plugin builds (build.sh) stay as they are.
# SRC=~/rockbox-bt OUTNAME=coda-os-bt builds another Rockbox tree into its own zip.
set -euo pipefail
MODE=${1:-sim}
REPO=${REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}
SRC=${SRC:-$HOME/rockbox}
export PATH=$HOME/rbdev/bin:$PATH

bash "$REPO/firmware/rockbox/sync_plugin.sh" > /dev/null          # Coda sources -> apps/plugins/coda
mkdir -p "$SRC/apps/coda"
cp "$REPO/firmware/rockbox/os/coda_os.make" "$REPO/firmware/rockbox/os/gen_api_table.py" "$SRC/apps/coda/"
python3 "$REPO/firmware/rockbox/os/patch_core.py" "$SRC"

DEFS="-DCODA_OS"
case "$MODE" in
    sim)          DIR=$SRC/build-os-sim;    TYPE=s ;;
    target)       DIR=$SRC/build-os;        TYPE=n ;;
    strip-sim)    DIR=$SRC/build-strip-sim; TYPE=s; DEFS="-DCODA_OS -DCODA_OS_STRIP" ;;
    strip-target) DIR=$SRC/build-strip;     TYPE=n; DEFS="-DCODA_OS -DCODA_OS_STRIP" ;;
    *) echo "usage: build_os.sh sim|target|strip-sim|strip-target"; exit 2 ;;
esac
mkdir -p "$DIR"
cd "$DIR"
if [ ! -f Makefile ]; then
    ../tools/configure --target=erosqnative --type=$TYPE < /dev/null > configure.log 2>&1
    sed -i "/^export EXTRA_DEFINES=/ s/\$/ $DEFS/" Makefile
fi
grep -q -- '-DCODA_OS' Makefile || { echo "Makefile lacks -DCODA_OS"; exit 1; }
# Rockbox's makefiles keep their source list in a variable called SRC: an SRC=... passed
# to this script must not reach make's environment (the tree's path became a link input)
env -u SRC make -j"${JOBS:-6}" > make.log 2>&1 || { grep -n -B2 -A6 -E "error|Error|undefined" make.log | head -80; exit 1; }
if [ "$TYPE" = s ]; then
    env -u SRC make install > install.log 2>&1
    ls -la rockboxui
else
    env -u SRC make zip > zip.log 2>&1
    # Coda OS ships no games or demos (Coda is the app)
    zip -q -d rockbox.zip '.rockbox/rocks/games/*' '.rockbox/rocks/demos/*' > /dev/null 2>&1 || true
    NAME=${OUTNAME:-coda-os}
    if [ "$MODE" = strip-target ]; then
        NAME=${OUTNAME:-coda-os-strip}  # no Rockbox UI: no plugins, themes, skins, docs
        zip -q -d rockbox.zip '.rockbox/rocks/*' '.rockbox/themes/*' '.rockbox/wps/*' \
            '.rockbox/backdrops/*' '.rockbox/icons/*' '.rockbox/docs/*' '.rockbox/eqs/*' \
            '.rockbox/tagnavi.config' '.rockbox/viewers.config' > /dev/null 2>&1 || true
    fi
    OUT="$REPO/firmware/rockbox/out"
    mkdir -p "$OUT" && cp rockbox.zip "$OUT/$NAME.zip"
    ls -la rockbox.erosq "$OUT/$NAME.zip"
fi
grep -E "coda_os|libcoda|api table" make.log | tail -4 || true
