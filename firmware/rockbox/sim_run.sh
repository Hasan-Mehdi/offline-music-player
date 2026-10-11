#!/usr/bin/env bash
# One self-contained H2-simulator session: boot rockboxui headless on Xvfb, play a
# sequence of steps, save screenshots, shut down. (Run sim_setup.sh once first.)
#   bash firmware/rockbox/sim_run.sh <out_dir> step...
# steps: up down play back menu prev next volup voldn (H2 buttons; up/down = wheel)
#        combo:<a>+<b>:<ms>  two buttons held together (Coda OS escape: combo:menu+back:1700)
#        hold:<button>:<ms>   long press
#        wait:<ms>            let time pass
#        shot:<name>          save <out_dir>/<name>.png (320x240, the LCD only)
set -euo pipefail
OUT=$1; shift
SIM=${SIM:-$HOME/rockbox/build-sim}
mkdir -p "$OUT"
export DISPLAY=:97
pkill -f "Xvfb :97" 2>/dev/null || true
Xvfb :97 -screen 0 800x600x24 > /tmp/xvfb97.log 2>&1 &
XPID=$!
sleep 1
cd "$SIM"
SDL_AUDIODRIVER=dummy ./rockboxui --nobackground > "$OUT/rockboxui.log" 2>&1 &
RPID=$!
trap 'kill $RPID $XPID 2>/dev/null || true' EXIT
for i in $(seq 1 50); do
    W=$(xdotool search --name . 2>/dev/null | head -1 || true)
    [ -n "$W" ] && break
    sleep 0.2
done
[ -n "${W:-}" ] || { echo "no sim window"; tail -20 "$OUT/rockboxui.log"; exit 1; }
sleep 6                                      # boot to the main menu (slower right after make install)
map() {
    case "$1" in
        up) echo KP_8 ;; down) echo KP_2 ;; play) echo KP_Enter ;; back) echo BackSpace ;;
        menu) echo KP_Decimal ;; prev) echo KP_4 ;; next) echo KP_6 ;;
        volup) echo KP_Add ;; voldn) echo KP_Subtract ;; *) echo "$1" ;;
    esac
}
ms() { awk "BEGIN{print $1/1000}"; }
for s in "$@"; do
    case "$s" in
        wait:*) sleep "$(ms "${s#wait:}")" ;;
        combo:*) IFS=: read -r _ ks t <<< "$s"          # combo:menu+back:1600 = both held
                 k1=${ks%%+*}; k2=${ks##*+}
                 xdotool keydown --window "$W" "$(map "$k1")"; sleep 0.05
                 xdotool keydown --window "$W" "$(map "$k2")"; sleep "$(ms "$t")"
                 xdotool keyup --window "$W" "$(map "$k2")"; xdotool keyup --window "$W" "$(map "$k1")"
                 sleep 0.2 ;;
        hold:*) IFS=: read -r _ k t <<< "$s"
                xdotool keydown --window "$W" "$(map "$k")"; sleep "$(ms "$t")"
                xdotool keyup --window "$W" "$(map "$k")"; sleep 0.2 ;;
        shot:*) sleep 0.3; import -window "$W" "$OUT/${s#shot:}.png"; echo "shot ${s#shot:}" ;;
        *) xdotool keydown --window "$W" "$(map "$s")"; sleep 0.08
           xdotool keyup --window "$W" "$(map "$s")"; sleep 0.25 ;;
    esac
done
grep -i -E "coda|error|panic" "$OUT/rockboxui.log" | tail -5 || true
