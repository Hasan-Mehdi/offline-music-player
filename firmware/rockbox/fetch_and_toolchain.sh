#!/usr/bin/env bash
# Fetch Rockbox at the commit that is installed on the H2 and build its MIPS toolchain.
#   wsl -d Ubuntu-24.04 -- bash firmware/rockbox/fetch_and_toolchain.sh
# The plugin API must match the installed build exactly, so ROCKBOX_SHA is pinned to the
# daily build on the card (.rockbox/rockbox-info.txt "Version: 7d090f24b9-261009").
# Toolchain build takes a while; it logs to ~/rbdev/toolchain.log.
set -euo pipefail
ROCKBOX_SHA=${ROCKBOX_SHA:-7d090f24b990ef54e3f9dc7eb2edba4865605471}
SRC=${SRC:-$HOME/rockbox}
PREFIX=${PREFIX:-$HOME/rbdev}

if [ ! -d "$SRC/.git" ]; then
    git init -q "$SRC"
    git -C "$SRC" remote add origin https://github.com/Rockbox/rockbox.git
fi
if [ "$(git -C "$SRC" rev-parse HEAD 2>/dev/null)" != "$ROCKBOX_SHA" ]; then
    git -C "$SRC" fetch -q --depth 1 origin "$ROCKBOX_SHA"
    git -C "$SRC" checkout -q --detach "$ROCKBOX_SHA"
fi
echo "rockbox at $(git -C "$SRC" log -1 --format='%h %cs %s')"

mkdir -p "$PREFIX"
if [ "${SKIP_TOOLCHAIN:-0}" = 1 ]; then exit 0; fi
if [ -x "$PREFIX/bin/mipsel-elf-gcc" ]; then
    echo "toolchain present: $("$PREFIX/bin/mipsel-elf-gcc" --version | head -1)"
    exit 0
fi
cd "$SRC/tools"
# rockboxdev.sh: target i = MIPS (mipsel-elf gcc 9.5 / binutils 2.38, what the daily uses; m is m68k!)
./rockboxdev.sh --target=i --prefix="$PREFIX" --builddir="$PREFIX/build" \
    --dlwhere="$PREFIX/dl" --makeflags="-j$(nproc)" > "$PREFIX/toolchain.log" 2>&1 </dev/null
echo "toolchain done: $("$PREFIX/bin/mipsel-elf-gcc" --version | head -1)"
