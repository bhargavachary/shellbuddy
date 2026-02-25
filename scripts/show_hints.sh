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

C_RESET='\033[0m'
C_DIM='\033[38;5;242m'            # mid-grey  (was \033[2m → near-black on dark bg)
C_CYAN='\033[1;36m'
C_CYAN_DIM='\033[38;5;73m'        # muted teal (was dim cyan → near-black)
C_GREEN='\033[38;5;111m'          # soft periwinkle — AI ambient hints
C_GREEN_DIM='\033[38;5;111m'
C_YELLOW='\033[38;5;216m'         # light peach — rule hints
C_YELLOW_DIM='\033[38;5;216m'
C_MAGENTA='\033[38;5;183m'        # soft lilac  (was \033[35m → dark magenta)
C_MAGENTA_BOLD='\033[38;5;189m'   # light lavender
C_BLUE_DIM='\033[38;5;110m'       # steel blue  (was dim blue → near-black)
C_WHITE_DIM='\033[38;5;250m'      # light grey  (was dim white → near-black)

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

# Print one line with hint on left, logo on right
# $1=hint_text  $2=logo_text  $3=hint_colour  $4=logo_colour
_print_with_logo() {
    local hint="$1" logo="$2" hcol="$3" lcol="${4:-$C_MAGENTA}"
    # clamp hint so it never overlaps logo
    local max_hint=$(( LOGO_COL - 4 ))
    (( ${#hint} > max_hint )) && hint="${hint:0:$max_hint}"
    # pad from end-of-hint to LOGO_COL (accounting for the 2-space indent)
    local pad=$(( LOGO_COL - ${#hint} - 2 ))
    (( pad < 1 )) && pad=1
    # left-pad logo to LOGO_WIDTH so all lines align at the right edge
    printf "${hcol}  %s${C_RESET}%${pad}s${lcol}%-${LOGO_WIDTH}s${C_RESET}\n" "$hint" "" "$logo"
}

# Process line by line
while IFS=$'\t' read -r f1 f2 f3 f4 f5; do
    # Reassemble f3 in case hint itself contains tabs (IDLE_TIP has 2 more fields)
    [[ -n "$f4" ]] && f3="${f3}"$'\t'"${f4}"
    [[ -n "$f5" ]] && f3="${f3}"$'\t'"${f5}"

    if [[ "$f1" == HINTS* ]] && [[ -z "$f2" ]]; then
        # Header (no tabs — whole line is in f1)
        printf "${C_CYAN}  [>_] %s${C_RESET}\n" "$f1"

    elif [[ "$f1" == ─* ]] && [[ -z "$f2" ]]; then
        # Separator
        printf "${C_DIM}  %s${C_RESET}\n" "$f1"

    elif [[ "$f1" == "LOGO" ]]; then
        # LOGO\t<logo>\t<hint_or_special>
        # f3 may itself be IDLE_TIP\t<cmd>\t<desc> or IDLE_LABEL\t<text>
        _logo="$f2" _hint="$f3"
        # Detect embedded special markers in hint slot
        if [[ "$_hint" == IDLE_TIP$'\t'* ]]; then
            # Print logo-only line (no hint), then idle tip below
            _pad=$(( LOGO_COL - 2 ))
            printf "  %${_pad}s${C_MAGENTA}%-${LOGO_WIDTH}s${C_RESET}\n" "" "$_logo"
            _tip_rest="${_hint#IDLE_TIP$'\t'}"
            _tip_cmd="${_tip_rest%%$'\t'*}"
            _tip_desc="${_tip_rest#*$'\t'}"
            printf "${C_CYAN}  %-28s${C_RESET}${C_WHITE_DIM}%s${C_RESET}\n" "$_tip_cmd" "$_tip_desc"
        elif [[ "$_hint" == IDLE_LABEL$'\t'* ]]; then
            _pad=$(( LOGO_COL - 2 ))
            printf "  %${_pad}s${C_MAGENTA}%-${LOGO_WIDTH}s${C_RESET}\n" "" "$_logo"
            _label="${_hint#IDLE_LABEL$'\t'}"
            printf "${C_BLUE_DIM}%s${C_RESET}\n" "$_label"
        elif [[ "$_hint" == \[*x\]* ]]; then
            _print_with_logo "$_hint" "$_logo" "$C_YELLOW_DIM"
        elif [[ "$_hint" == "·" ]]; then
            _print_with_logo "·" "$_logo" "$C_DIM"
        elif [[ -n "$_hint" ]]; then
            _print_with_logo "$_hint" "$_logo" "$C_GREEN_DIM"
        else
            _pad=$(( LOGO_COL - 2 ))
            (( _pad < 1 )) && _pad=1
            printf "  %${_pad}s${C_MAGENTA}%-${LOGO_WIDTH}s${C_RESET}\n" "" "$_logo"
        fi

    elif [[ "$f1" == "LOGO_TAG" ]]; then
        # LOGO_TAG\t<tag>\t<hint>
        _tag="$f2" _hint="$f3"
        if [[ -n "$_hint" ]]; then
            _print_with_logo "$_hint" "$_tag" "$C_GREEN_DIM" "$C_MAGENTA_BOLD"
        else
            _pad=$(( LOGO_COL - 2 ))
            (( _pad < 1 )) && _pad=1
            printf "  %${_pad}s${C_MAGENTA_BOLD}%-${LOGO_WIDTH}s${C_RESET}\n" "" "$_tag"
        fi

    elif [[ "$f1" == "IDLE_TIP" ]]; then
        # IDLE_TIP\t<cmd>\t<desc>  (standalone, no logo on this line)
        printf "${C_CYAN}  %-28s${C_RESET}${C_WHITE_DIM}%s${C_RESET}\n" "$f2" "$f3"

    elif [[ "$f1" == "IDLE_LABEL" ]]; then
        # IDLE_LABEL\t<text>
        printf "${C_BLUE_DIM}%s${C_RESET}\n" "$f2"

    elif [[ "$f1" == \[*x\]* ]] && [[ -z "$f2" ]]; then
        # Rule hint — muted amber, dim body
        printf "${C_YELLOW_DIM}  %s${C_RESET}\n" "$f1"

    elif [[ "$f1" == "·" ]] && [[ -z "$f2" ]]; then
        printf "${C_DIM}  ·${C_RESET}\n"

    elif [[ "$f1" == thinking* ]] && [[ -z "$f2" ]]; then
        printf "${C_CYAN_DIM}  %s${C_RESET}\n" "$f1"

    elif [[ -n "$f1" ]] && [[ -z "$f2" ]]; then
        # Plain AI hint — muted sage green, dim
        printf "${C_GREEN_DIM}  %s${C_RESET}\n" "$f1"

    else
        echo ""
    fi

done < "$HINTS_FILE"
