#!/usr/bin/env zsh
# shellbuddy — toggle_hints_pane.sh
# Toggles both panes in the current tmux window:
#   STATS pane  — 2 lines, live CPU/RAM/GPU at 0.1s (show_stats.sh)
#   HINTS pane  — 12 lines, ambient hints + logo (show_hints.sh)
#
# Both are created/destroyed together as a unit.
# Keybind: Ctrl+A H (if tmux.conf installed)

SB_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
HINTS_TITLE="SHELLBUDDY_HINTS"
STATS_TITLE="SHELLBUDDY_STATS"

# Detect existing panes by title
HINTS_PANE=$(tmux list-panes -F "#{pane_id}:#{pane_title}" 2>/dev/null \
    | /usr/bin/grep ":${HINTS_TITLE}" | cut -d: -f1)
STATS_PANE=$(tmux list-panes -F "#{pane_id}:#{pane_title}" 2>/dev/null \
    | /usr/bin/grep ":${STATS_TITLE}" | cut -d: -f1)

if [[ -n "$HINTS_PANE" || -n "$STATS_PANE" ]]; then
    # Tear down both
    [[ -n "$HINTS_PANE" ]] && tmux kill-pane -t "$HINTS_PANE" 2>/dev/null
    [[ -n "$STATS_PANE" ]] && tmux kill-pane -t "$STATS_PANE" 2>/dev/null
else
    # ── Create HINTS pane (12 lines, just above main) ──────────────────────
    tmux split-window -v -b -l 12 -c "$HOME" \
        "trap '' INT; while true; do SHELLBUDDY_DIR=$SB_DIR zsh $SB_DIR/show_hints.sh; sleep 3; done"
    tmux select-pane -T "$HINTS_TITLE"
    HINTS_PANE_ID=$(tmux display-message -p "#{pane_id}")

    # ── Create STATS pane (2 lines, above hints) ───────────────────────────
    tmux split-window -v -b -l 2 -t "$HINTS_PANE_ID" -c "$HOME" \
        "trap '' INT TERM; python3 $SB_DIR/show_stats.sh"
    tmux select-pane -T "$STATS_TITLE"

    # Return focus to main (bottom) pane
    tmux select-pane -t "{bottom}"
fi
