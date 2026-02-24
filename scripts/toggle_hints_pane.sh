#!/usr/bin/env zsh
# Toggle hints pane in current tmux window
# Creates TOP pane running hints watcher if not open, kills it if open

SB_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
HINTS_PANE_TITLE="HINTS"

# Check if a hints pane already exists in this window
EXISTING=$(tmux list-panes -F "#{pane_id}:#{pane_title}" 2>/dev/null | grep ":$HINTS_PANE_TITLE")

if [[ -n "$EXISTING" ]]; then
    PANE_ID="${EXISTING%%:*}"
    tmux kill-pane -t "$PANE_ID"
else
    # Create top pane, 12 lines tall, run the hints watcher loop
    tmux split-window -v -b -l 12 -c "$HOME" \
        "trap '' INT; while true; do SHELLBUDDY_DIR=$SB_DIR zsh $SB_DIR/show_hints.sh; sleep 3; done"
    tmux select-pane -T "$HINTS_PANE_TITLE"
    # Return focus to main pane (bottom)
    tmux select-pane -t "{bottom}"
fi
