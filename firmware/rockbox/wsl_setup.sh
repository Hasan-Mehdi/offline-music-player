#!/usr/bin/env bash
# One-time WSL (Ubuntu 24.04) setup for building Rockbox + the coda plugin.
#   wsl -d Ubuntu-24.04 -- bash firmware/rockbox/wsl_setup.sh
# Needs sudo once for apt; pass the password via SUDOPW or type it when asked.
set -euo pipefail
pkgs="build-essential git perl curl wget zip unzip texinfo bison flex gawk patch file
      libgmp-dev libmpfr-dev libmpc-dev zlib1g-dev libsdl2-dev pkg-config automake
      autoconf libtool python3 ccache xvfb xdotool imagemagick"
if [ -n "${SUDOPW:-}" ]; then
    printf '%s\n' "$SUDOPW" | sudo -S -p '' env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    printf '%s\n' "$SUDOPW" | sudo -S -p '' env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pkgs
else
    sudo env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq $pkgs
fi
gcc --version | head -1
echo "sdl2 $(sdl2-config --version)"
