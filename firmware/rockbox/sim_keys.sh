#!/usr/bin/env bash
# Drive the headless H2 simulator and grab its screen.
#   bash firmware/rockbox/sim_keys.sh <out.png> [key ...]
# keys (H2 sim mapping): up=KP_8 (wheel back) down=KP_2 (wheel fwd) play=KP_Enter
#   back=BackSpace menu=KP_Decimal prev=KP_4 next=KP_6 volup=KP_Add voldn=KP_Subtract
#   hold:<key>:<ms> for long presses, wait:<ms> to let time pass
set -euo pipefail
OUT=$1; shift
export DISPLAY=:99
W=$(xdotool search --name . | head -1)
xdotool windowfocus --sync "$W" 2>/dev/null || true
map() {
    case "$1" in
        up) echo KP_8 ;; down) echo KP_2 ;; play) echo KP_Enter ;; back) echo BackSpace ;;
        menu) echo KP_Decimal ;; prev) echo KP_4 ;; next) echo KP_6 ;;
        volup) echo KP_Add ;; voldn) echo KP_Subtract ;; *) echo "$1" ;;
    esac
}
for k in "$@"; do
    case "$k" in
        wait:*) sleep "$(awk "BEGIN{print ${k#wait:}/1000}")" ;;
        hold:*)
            IFS=: read -r _ key ms <<< "$k"
            xdotool keydown --window "$W" "$(map "$key")"
            sleep "$(awk "BEGIN{print $ms/1000}")"
            xdotool keyup --window "$W" "$(map "$key")" ;;
        *) xdotool key --window "$W" --delay 60 "$(map "$k")"; sleep 0.15 ;;
    esac
done
sleep 0.4
import -window "$W" "$OUT"
echo "shot $OUT"
