#!/usr/bin/env bash
# The Bluetooth Rockbox tree for Coda OS (~/rockbox-bt): our pinned Rockbox, plus Skye
# Green's unmerged Gerrit series (Bluedroid ported to Rockbox, the H2 HW4 HCI driver,
# https://gerrit.rockbox.org/r/c/rockbox/+/7387 and parents), plus our fixes and the
# Bluetooth service (patches/, one commit each). Run in WSL:
#   bash firmware/rockbox/bt/setup_bt_tree.sh
#   SRC=~/rockbox-bt OUTNAME=coda-os-bt bash firmware/rockbox/os/build_os.sh target
# The Bluedroid import itself (pristine ESP-IDF 6.0.1, 330k lines) is fetched from Gerrit
# rather than kept here. Regenerate patches/ after changing the tree:
#   git -C ~/rockbox-bt format-patch -o <repo>/firmware/rockbox/bt/patches <import>..coda-bt
set -euo pipefail
DST=${DST:-$HOME/rockbox-bt}
BASE=7d090f24b9                     # = ~/rockbox, the daily the H2 runs
SERIES=refs/changes/87/7387/6       # Skye's chain, patch set of 2026-05-26
IMPORT=a0f6dbd4                     # "bt: import Bluedroid from esp-idf 6.0.1"
HERE=$(cd "$(dirname "$0")" && pwd)
export GIT_COMMITTER_NAME=${GIT_COMMITTER_NAME:-coda} GIT_COMMITTER_EMAIL=${GIT_COMMITTER_EMAIL:-coda@localhost}

[ -d "$DST/.git" ] || git clone --depth 600 https://github.com/Rockbox/rockbox.git "$DST"
cd "$DST"
git cat-file -e "$BASE^{commit}" 2>/dev/null || git fetch --depth 1200 origin
git fetch --depth 600 https://gerrit.rockbox.org/r/rockbox "$SERIES"
git checkout -q -B coda-bt "$BASE"
git cherry-pick "$IMPORT" > /dev/null
git am -q "$HERE"/patches/*.patch
git log --oneline "$BASE"..coda-bt
