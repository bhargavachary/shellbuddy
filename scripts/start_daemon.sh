#!/usr/bin/env zsh
# shellbuddy — start_daemon.sh
# Idempotent daemon launcher. Safe to call on every shell open.
# Uses kill-0 on the stored PID; if stale, removes the PID file and relaunches.

SB_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
DAEMON_PY="$SB_DIR/hint_daemon.py"
DAEMON_PID="$SB_DIR/daemon.pid"
DAEMON_LOG="$SB_DIR/daemon.log"

# Use conda python if available, else fall back to system python3
PYTHON="${SHELLBUDDY_PYTHON:-$(command -v python3)}"
[[ -f "$CONDA_PREFIX/bin/python3" ]] && PYTHON="$CONDA_PREFIX/bin/python3"

# Check if already running
if [[ -f "$DAEMON_PID" ]]; then
    PID=$(cat "$DAEMON_PID" 2>/dev/null)
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        return 0 2>/dev/null || exit 0  # already running, silent
    fi
    # Stale PID — remove it
    rm -f "$DAEMON_PID"
fi

# Launch daemon (detached, not a child of this shell)
nohup "$PYTHON" "$DAEMON_PY" >> "$DAEMON_LOG" 2>&1 &
disown $!
echo $! > "$DAEMON_PID"
