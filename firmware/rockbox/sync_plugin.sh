#!/usr/bin/env bash
# Copy the Coda plugin sources from this repo into the pinned Rockbox tree and register
# the plugin (idempotent). Run in WSL:
#   bash firmware/rockbox/sync_plugin.sh            # then build (build.sh)
set -euo pipefail
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
SRC=${SRC:-$HOME/rockbox}
DST=$SRC/apps/plugins/coda

rm -rf "$DST"
mkdir -p "$DST/core" "$DST/ui" "$DST/plat" "$DST/rb"
cp "$REPO"/firmware/core/*.[ch] "$DST/core/"
cp "$REPO"/firmware/ui/*.[ch] "$DST/ui/"
cp "$REPO"/firmware/plat/plat.h "$DST/plat/"
cp "$REPO"/firmware/rockbox/coda/rb/*.[ch] "$DST/rb/"
cp "$REPO"/firmware/rockbox/coda/coda.make "$DST/"

SUB=$SRC/apps/plugins/SUBDIRS
if ! grep -q '^coda$' "$SUB"; then
    printf '\n/* Coda (offline-music-player): 16-bit colour screens */\n#if defined(HAVE_LCD_COLOR) && (LCD_DEPTH == 16)\ncoda\n#endif\n' >> "$SUB"
fi
CAT=$SRC/apps/plugins/CATEGORIES
grep -q '^coda,' "$CAT" || echo 'coda,apps' >> "$CAT"
echo "synced -> $DST"
