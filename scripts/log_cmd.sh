#!/usr/bin/env zsh
# shellbuddy — log_cmd.sh
# Called from zsh preexec hook — logs each command to JSONL.
# Pure zsh: no python3 subprocess, no forks beyond the mv.
# Args: $1 = command string

CMD_LOG="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}/cmd_log.jsonl"
CMD="$1"
CWD="$PWD"

# Skip empty, meta, and noisy commands
[[ -z "$CMD" ]]          && return
[[ "$CMD" == hints* ]]   && return
[[ "$CMD" == tmux* ]]    && return
[[ "$CMD" == sb ]]       && return
[[ "$CMD" == sb\ * ]]    && return
[[ "$CMD" == "super-claude"* ]] && return
[[ "$CMD" == "super-copilot"* ]] && return

# JSON-escape a string (handles \, ", control chars)
json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"   # backslash first
    s="${s//\"/\\\"}"   # double-quote
    s="${s//$'\t'/\\t}" # tab
    s="${s//$'\n'/\\n}" # newline
    s="${s//$'\r'/\\r}" # carriage return
    printf '%s' "$s"
}

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
CMD_ESC="$(json_escape "$CMD")"
CWD_ESC="$(json_escape "$CWD")"

printf '{"ts":"%s","cmd":"%s","cwd":"%s"}\n' "$TS" "$CMD_ESC" "$CWD_ESC" >> "$CMD_LOG"

# Keep log to last 500 entries (in-place via tmp file)
if (( $(wc -l < "$CMD_LOG") > 520 )); then
    tail -500 "$CMD_LOG" > "${CMD_LOG}.tmp" && mv "${CMD_LOG}.tmp" "$CMD_LOG"
fi
