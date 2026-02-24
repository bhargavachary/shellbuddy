#!/usr/bin/env zsh
# shellbuddy — show_hints.sh
# Renders current_hints.txt in the tmux hints pane with colour and branding.
SB_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
HINTS_FILE="$SB_DIR/current_hints.txt"
DAEMON_PID="$SB_DIR/daemon.pid"

tput clear 2>/dev/null || clear

if [[ ! -f "$HINTS_FILE" ]]; then
    printf '\033[2m  [>_] Waiting for hints... (run a few commands)\033[0m\n'
    sleep 2
    exec "$0"
fi

# Check daemon is alive
if [[ -f "$DAEMON_PID" ]]; then
    PID=$(cat "$DAEMON_PID")
    if ! kill -0 "$PID" 2>/dev/null; then
        printf '\033[31m  [>_] daemon stopped — restart: hints-start\033[0m\n'
    fi
fi

# Display with colour
while IFS= read -r line; do
    if [[ "$line" == HINTS* ]]; then
        # Header — cyan bold with robot icon
        printf '\033[1;36m  [>_] %s\033[0m\n' "$line"
    elif [[ "$line" == ─* ]]; then
        # Separator — dim
        printf '\033[2m  %s\033[0m\n' "$line"
    elif [[ "$line" == \[*x\]* ]]; then
        # Rule hint — yellow
        printf '\033[33m  %s\033[0m\n' "$line"
    elif [[ "$line" == "·" ]]; then
        printf '\033[2m  ·\033[0m\n'
    elif [[ "$line" == thinking* ]]; then
        # Thinking indicator — cyan dim animated
        printf '\033[2;36m  %s\033[0m\n' "$line"
    elif [[ -n "$line" ]]; then
        # AI hint — green
        printf '\033[32m  %s\033[0m\n' "$line"
    else
        echo ""
    fi
done < "$HINTS_FILE"
