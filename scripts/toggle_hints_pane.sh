#!/usr/bin/env zsh
# shellbuddy — toggle_hints_pane.sh
# Toggles both panes in the current tmux window:
#   STATS pane  — 5 lines, live CPU/RAM/GPU at 0.1s (show_stats.sh)
#   HINTS pane  — dynamic, ambient hints (show_hints.sh)
#
# Layout adapts to terminal height:
#   - Main console always gets at least 15 lines
#   - STATS is fixed at 5 lines
#   - HINTS gets remaining space (min 8, max 20)
#   - On very small terminals (<30 lines), STATS is hidden to save space
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
    # ── Dynamic sizing based on terminal height ───────────────────────────
    TOTAL_LINES=$(tmux display-message -p "#{window_height}" 2>/dev/null)
    [[ -z "$TOTAL_LINES" || "$TOTAL_LINES" -eq 0 ]] && TOTAL_LINES=$(tput lines 2>/dev/null || echo 40)

    MIN_CONSOLE=15    # user's shell must keep at least this many lines
    STATS_ROWS=5
    MIN_HINTS=8
    MAX_HINTS=20

    # Calculate available space for shellbuddy panes
    AVAILABLE=$(( TOTAL_LINES - MIN_CONSOLE ))

    if (( AVAILABLE < MIN_HINTS )); then
        # Terminal too small — don't create panes at all
        echo "shellbuddy: terminal too small (${TOTAL_LINES} lines, need ≥$((MIN_CONSOLE + MIN_HINTS)))"
        return 1 2>/dev/null || exit 1
    fi

    # Decide whether to include STATS pane
    SHOW_STATS=1
    if (( AVAILABLE < MIN_HINTS + STATS_ROWS )); then
        # Not enough room for both — drop STATS to give HINTS more space
        SHOW_STATS=0
        HINTS_ROWS=$(( AVAILABLE ))
    else
        HINTS_ROWS=$(( AVAILABLE - STATS_ROWS ))
    fi

    # Clamp HINTS between MIN and MAX
    (( HINTS_ROWS > MAX_HINTS )) && HINTS_ROWS=$MAX_HINTS
    (( HINTS_ROWS < MIN_HINTS )) && HINTS_ROWS=$MIN_HINTS

    # Write computed hint height so daemon + show_hints.sh can adapt content
    echo "$HINTS_ROWS" > "$SB_DIR/hints_pane_rows"

    # ── Create HINTS pane (dynamic height, just above main) ───────────────
    tmux split-window -v -b -l "$HINTS_ROWS" -c "$HOME" \
        "trap '' INT; while true; do SHELLBUDDY_DIR=$SB_DIR zsh $SB_DIR/show_hints.sh; sleep 3; done"
    tmux select-pane -T "$HINTS_TITLE"
    HINTS_PANE_ID=$(tmux display-message -p "#{pane_id}")

    if (( SHOW_STATS )); then
        # ── Create STATS pane (5 lines, above hints) ─────────────────────
        tmux split-window -v -b -l "$STATS_ROWS" -t "$HINTS_PANE_ID" -c "$HOME" \
            "trap '' INT TERM; LINES=$STATS_ROWS python3 $SB_DIR/show_stats.sh"
        tmux select-pane -T "$STATS_TITLE"
    fi

    # Return focus to main (bottom) pane
    tmux select-pane -t "{bottom}"
fi
