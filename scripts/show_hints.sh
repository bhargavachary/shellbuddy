#!/usr/bin/env zsh
# shellbuddy — show_hints.sh
# Renders current_hints.txt in the tmux hints pane with colour, logo, and idle tips.
#
# Line format written by hint_daemon.py (tab-separated fields):
#   HINTS  <cwd>  [HH:MM:SS]  (N cmds)         — header
#   ──────...                                    — separator
#   LOGO\t<logo_line>\t<hint_line>              — logo overlay on hint line
#   LOGO_TAG\t<tag>\t<hint_line>               — logo tag line
#   IDLE_TIP\t<cmd>\t<desc>                    — idle usage tip
#   IDLE_LABEL\t<text>                         — idle section label
#   [Nx] <hint>                                — rule hint (yellow)
#   ·                                          — divider dot
#   thinking ...                               — thinking indicator
#   <text>                                     — AI ambient hint (green)

SB_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
HINTS_FILE="$SB_DIR/current_hints.txt"
DAEMON_PID="$SB_DIR/daemon.pid"

# Pane height awareness — read dynamic height set by toggle_hints_pane.sh
PANE_ROWS=${LINES:-16}
if [[ -f "$SB_DIR/hints_pane_rows" ]]; then
    _hr=$(cat "$SB_DIR/hints_pane_rows" 2>/dev/null)
    [[ "$_hr" =~ ^[0-9]+$ ]] && PANE_ROWS=$_hr
fi
_rendered=0

C_RESET='\033[0m'

# Detect color capability — use 256-color palette if supported, else basic ANSI
_NCOLORS=$(tput colors 2>/dev/null || echo 8)
if (( _NCOLORS >= 256 )); then
    C_DIM='\033[38;5;242m'            # mid-grey
    C_CYAN='\033[1;36m'
    C_CYAN_DIM='\033[38;5;73m'        # muted teal
    C_GREEN='\033[38;5;111m'          # soft periwinkle — AI ambient hints
    C_GREEN_DIM='\033[38;5;111m'
    C_YELLOW='\033[38;5;216m'         # light peach — rule hints
    C_YELLOW_DIM='\033[38;5;216m'
    C_MAGENTA='\033[38;5;183m'        # soft lilac
    C_MAGENTA_BOLD='\033[38;5;189m'   # light lavender
    C_BLUE_DIM='\033[38;5;110m'       # steel blue
    C_WHITE_DIM='\033[38;5;250m'      # light grey
else
    # 16-color fallback — readable on any terminal
    C_DIM='\033[2m'
    C_CYAN='\033[1;36m'
    C_CYAN_DIM='\033[36m'
    C_GREEN='\033[32m'
    C_GREEN_DIM='\033[32m'
    C_YELLOW='\033[33m'
    C_YELLOW_DIM='\033[33m'
    C_MAGENTA='\033[35m'
    C_MAGENTA_BOLD='\033[1;35m'
    C_BLUE_DIM='\033[34m'
    C_WHITE_DIM='\033[37m'
fi

printf '\033[2J\033[H'

if [[ ! -f "$HINTS_FILE" ]]; then
    printf "${C_DIM}  [>_] Waiting for hints... (run a few commands)${C_RESET}\n"
    exit 0
fi

# Check daemon alive
if [[ -f "$DAEMON_PID" ]]; then
    PID=$(cat "$DAEMON_PID")
    if ! kill -0 "$PID" 2>/dev/null; then
        printf '\033[31m  [>_] daemon stopped — restart: hints-start\033[0m\n'
    fi
fi

# Terminal width
COLS=$(tput cols 2>/dev/null || echo 80)
# Logo is 46 chars wide; anchor its left edge at COLS-46-2 (2-char right margin)
LOGO_WIDTH=46
LOGO_COL=$(( COLS - LOGO_WIDTH - 2 ))
(( LOGO_COL < 30 )) && LOGO_COL=30

# Print one line with hint on left, logo on right (tracks rendered count)
# $1=hint_text  $2=logo_text  $3=hint_colour  $4=logo_colour
_print_with_logo() {
    local hint="$1" logo="$2" hcol="$3" lcol="${4:-$C_MAGENTA}"
    local max_hint=$(( LOGO_COL - 4 ))
    (( ${#hint} > max_hint )) && hint="${hint:0:$max_hint}"
    local pad=$(( LOGO_COL - ${#hint} - 2 ))
    (( pad < 1 )) && pad=1
    printf "${hcol}  %s${C_RESET}%${pad}s${lcol}%-${LOGO_WIDTH}s${C_RESET}\n" "$hint" "" "$logo"
    (( _rendered++ ))
}

# Print one line and track rendered count
_println() {
    printf "$@"
    (( _rendered++ ))
}

# Item 33: Word-wrapped println for long AI hint lines (>COLS-6 chars)
# Splits at char boundary, shows continuation on next line with indent.
_println_wrap() {
    local col="$1" text="$2"
    local max_w=$(( COLS - 6 ))
    (( max_w < 20 )) && max_w=20
    if (( ${#text} <= max_w )); then
        printf "${col}  %s${C_RESET}\n" "$text"
        (( _rendered++ ))
    else
        # Find last space before max_w for a clean break
        local chunk="${text:0:$max_w}"
        local break_at=$(( max_w ))
        # Walk back to find space
        while (( break_at > max_w / 2 )); do
            [[ "${text:$break_at:1}" == " " ]] && break
            (( break_at-- ))
        done
        (( break_at <= max_w / 2 )) && break_at=$max_w
        printf "${col}  %s${C_RESET}\n" "${text:0:$break_at}"
        (( _rendered++ ))
        local rest="${text:$break_at}"
        rest="${rest# }"   # strip leading space
        if (( _rendered < PANE_ROWS && ${#rest} > 0 )); then
            printf "${C_DIM}      …%s${C_RESET}\n" "$rest"
            (( _rendered++ ))
        fi
    fi
}

# Process line by line
while IFS=$'\t' read -r f1 f2 f3 f4 f5; do
    (( _rendered >= PANE_ROWS )) && break

    # Reassemble f3 in case hint itself contains tabs (IDLE_TIP has 2 more fields)
    [[ -n "$f4" ]] && f3="${f3}"$'\t'"${f4}"
    [[ -n "$f5" ]] && f3="${f3}"$'\t'"${f5}"

    if [[ "$f1" == HINTS* ]] && [[ -z "$f2" ]]; then
        # Header (no tabs — whole line is in f1)
        _println "${C_CYAN}  [>_] %s${C_RESET}\n" "$f1"

    elif [[ "$f1" == ─* ]] && [[ -z "$f2" ]]; then
        # Separator
        _println "${C_DIM}  %s${C_RESET}\n" "$f1"

    elif [[ "$f1" == "LOGO" ]]; then
        # LOGO\t<logo>\t<hint_or_special>
        _logo="$f2" _hint="$f3"
        if [[ "$_hint" == IDLE_TIP$'\t'* ]]; then
            _pad=$(( LOGO_COL - 2 ))
            _println "  %${_pad}s${C_MAGENTA}%-${LOGO_WIDTH}s${C_RESET}\n" "" "$_logo"
            _tip_rest="${_hint#IDLE_TIP$'\t'}"
            _tip_cmd="${_tip_rest%%$'\t'*}"
            _tip_desc="${_tip_rest#*$'\t'}"
            _println "${C_CYAN}  %-28s${C_RESET}${C_WHITE_DIM}%s${C_RESET}\n" "$_tip_cmd" "$_tip_desc"
        elif [[ "$_hint" == IDLE_LABEL$'\t'* ]]; then
            _pad=$(( LOGO_COL - 2 ))
            _println "  %${_pad}s${C_MAGENTA}%-${LOGO_WIDTH}s${C_RESET}\n" "" "$_logo"
            _label="${_hint#IDLE_LABEL$'\t'}"
            _println "${C_BLUE_DIM}%s${C_RESET}\n" "$_label"
        elif [[ "$_hint" == \[*x\]* ]]; then
            _print_with_logo "$_hint" "$_logo" "$C_YELLOW_DIM"
        elif [[ "$_hint" == "·" ]]; then
            _print_with_logo "·" "$_logo" "$C_DIM"
        elif [[ -n "$_hint" ]]; then
            _print_with_logo "$_hint" "$_logo" "$C_GREEN_DIM"
        else
            _pad=$(( LOGO_COL - 2 ))
            (( _pad < 1 )) && _pad=1
            _println "  %${_pad}s${C_MAGENTA}%-${LOGO_WIDTH}s${C_RESET}\n" "" "$_logo"
        fi

    elif [[ "$f1" == "LOGO_TAG" ]]; then
        _tag="$f2" _hint="$f3"
        if [[ -n "$_hint" ]]; then
            _print_with_logo "$_hint" "$_tag" "$C_GREEN_DIM" "$C_MAGENTA_BOLD"
        else
            _pad=$(( LOGO_COL - 2 ))
            (( _pad < 1 )) && _pad=1
            _println "  %${_pad}s${C_MAGENTA_BOLD}%-${LOGO_WIDTH}s${C_RESET}\n" "" "$_tag"
        fi

    elif [[ "$f1" == "IDLE_TIP" ]]; then
        _println "${C_CYAN}  %-28s${C_RESET}${C_WHITE_DIM}%s${C_RESET}\n" "$f2" "$f3"

    elif [[ "$f1" == "IDLE_LABEL" ]]; then
        _println "${C_BLUE_DIM}%s${C_RESET}\n" "$f2"

    elif [[ "$f1" == \[*x\]* ]] && [[ -z "$f2" ]]; then
        _println "${C_YELLOW_DIM}  %s${C_RESET}\n" "$f1"

    elif [[ "$f1" == "·" ]] && [[ -z "$f2" ]]; then
        _println "${C_DIM}  ·${C_RESET}\n"

    elif [[ "$f1" == thinking* ]] && [[ -z "$f2" ]]; then
        _println "${C_CYAN_DIM}  %s${C_RESET}\n" "$f1"

    elif [[ -n "$f1" ]] && [[ -z "$f2" ]]; then
        # Plain AI hint — item 33: word-wrapped for long lines
        _println_wrap "${C_GREEN_DIM}" "$f1"

    else
        _println "\n"
    fi

done < "$HINTS_FILE"
