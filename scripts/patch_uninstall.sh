#!/usr/bin/env zsh
# shellbuddy — patch_uninstall.sh
# Reverses the changes made by patch_install.sh:
#   • removes the shellbuddy source line from the rc file
#   • removes the shellbuddy block from ~/.tmux.conf
#   • removes $INSTALL_DIR (with confirmation)
#
# Usage:
#   ./scripts/patch_uninstall.sh
#   ./scripts/patch_uninstall.sh -y    # yes to all
#   ./scripts/patch_uninstall.sh --keep-dir  # leave ~/.shellbuddy in place

set -e

INSTALL_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
BACKUP_DIR="$HOME/.shellbuddy_backup/$(date +%Y%m%d_%H%M%S)"
TMUX_CONF="$HOME/.tmux.conf"
YES_TO_ALL=false
KEEP_DIR=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)       YES_TO_ALL=true; shift ;;
        --keep-dir)     KEEP_DIR=true; shift ;;
        -h|--help)
            echo "Usage: ./scripts/patch_uninstall.sh [-y|--yes] [--keep-dir]"
            exit 0 ;;
        *) shift ;;
    esac
done

C_CYAN='\033[1;36m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_RED='\033[0;31m'
C_DIM='\033[2m'
C_BOLD='\033[1m'
C_RESET='\033[0m'

info() { printf "  ${C_CYAN}->  ${C_RESET}%s\n" "$*" }
ok()   { printf "  ${C_GREEN} +  ${C_RESET}%s\n" "$*" }
warn() { printf "  ${C_YELLOW} !  ${C_RESET}%s\n" "$*" }
ask() {
    if $YES_TO_ALL; then
        printf "  ${C_YELLOW} ?  ${C_RESET}%s ${C_DIM}[y/N]${C_RESET} ${C_GREEN}y (--yes)${C_RESET}\n" "$*"
        return 0
    fi
    printf "  ${C_YELLOW} ?  ${C_RESET}%s ${C_DIM}[y/N]${C_RESET} " "$*"
    read -r REPLY
    [[ "$REPLY" =~ ^[Yy]$ ]]
}

backup_file() {
    if [[ -f "$1" ]]; then
        mkdir -p "$BACKUP_DIR"
        cp "$1" "$BACKUP_DIR/$(basename "$1")"
        ok "Backed up $(basename "$1") → $BACKUP_DIR/"
    fi
}

printf "\n  ${C_CYAN}${C_BOLD}"
cat << 'BANNER'
   ┌─────────────────────────────────────────┐
   │  shellbuddy — patch uninstall           │
   └─────────────────────────────────────────┘
BANNER
printf "${C_RESET}\n"

# ── Stop daemon ───────────────────────────────────────────────────────────────
PID_FILE="$INSTALL_DIR/daemon.pid"
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE" 2>/dev/null)
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null && ok "Daemon (PID $PID) stopped" || warn "Could not stop daemon"
    fi
    rm -f "$PID_FILE"
fi

# ── Remove shellbuddy block from rc file ──────────────────────────────────────
CURRENT_SHELL="$(basename "${SHELL:-zsh}")"
if [[ "$CURRENT_SHELL" == "zsh" ]]; then
    RC_FILE="$HOME/.zshrc"
elif [[ "$CURRENT_SHELL" == "bash" ]]; then
    RC_FILE="${BASH_ENV:-$HOME/.bashrc}"
    [[ -f "$HOME/.bash_profile" ]] && RC_FILE="$HOME/.bash_profile"
else
    RC_FILE="$HOME/.zshrc"
fi

if grep -q "shellbuddy" "$RC_FILE" 2>/dev/null; then
    backup_file "$RC_FILE"
    # Remove the source line added by patch_install.sh
    sed -i.bak '/# shellbuddy — source minimal rc patch/d' "$RC_FILE"
    sed -i.bak "/source.*shellbuddy.*rc_patch/d" "$RC_FILE"
    # Also remove any legacy inline shellbuddy block (between '# shellbuddy' and '# end shellbuddy')
    sed -i.bak '/^# shellbuddy$/,/^# end shellbuddy$/d' "$RC_FILE"
    rm -f "${RC_FILE}.bak"
    ok "shellbuddy hooks removed from $RC_FILE"
else
    info "No shellbuddy hooks found in $RC_FILE"
fi

# ── Remove shellbuddy block from tmux.conf ────────────────────────────────────
if grep -q "shellbuddy" "$TMUX_CONF" 2>/dev/null; then
    backup_file "$TMUX_CONF"
    # Remove lines between the minimal-patch marker and the closing separator
    sed -i.bak '/^# ── shellbuddy: minimal patch/,/^# ───.*$/d' "$TMUX_CONF"
    # Also remove any standalone toggle_hints_pane bind lines
    sed -i.bak '/toggle_hints_pane/d' "$TMUX_CONF"
    # Remove orphaned shellbuddy comment lines
    sed -i.bak '/# shellbuddy/d' "$TMUX_CONF"
    rm -f "${TMUX_CONF}.bak"
    ok "shellbuddy block removed from $TMUX_CONF"
    info "Reload tmux config: tmux source-file ~/.tmux.conf"
else
    info "No shellbuddy config found in $TMUX_CONF"
fi

# ── Remove install dir ────────────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    if $KEEP_DIR; then
        info "Keeping $INSTALL_DIR (--keep-dir)"
    elif ask "Remove $INSTALL_DIR? (contains scripts, config, logs)"; then
        rm -rf "$INSTALL_DIR"
        ok "Removed $INSTALL_DIR"
    else
        info "Kept $INSTALL_DIR"
    fi
else
    info "$INSTALL_DIR not found — nothing to remove"
fi

printf "\n  ${C_GREEN}${C_BOLD} ✓  shellbuddy patch uninstall complete${C_RESET}\n"
printf "  ${C_DIM}Reload your shell:  source %s${C_RESET}\n\n" "$RC_FILE"
