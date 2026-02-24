#!/usr/bin/env zsh
# shellbuddy — uninstall.sh
# Removes shellbuddy completely:
#   - stops the daemon
#   - deletes ~/.shellbuddy (or custom SHELLBUDDY_DIR)
#   - removes the shellbuddy block from ~/.zshrc
#   - removes the shellbuddy keybinding from ~/.tmux.conf
#   - optionally restores ~/.config/starship.toml from backup
#
# Does NOT remove packages (python3, tmux, brew tools) or shell aliases/tools
# that were already present before install.
#
# Usage:
#   ./uninstall.sh          # interactive (asks before each destructive step)
#   ./uninstall.sh -y       # yes to all (no prompts)

set -euo pipefail

INSTALL_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
ZSHRC="$HOME/.zshrc"
TMUX_CONF="$HOME/.tmux.conf"
STARSHIP_CONF="$HOME/.config/starship.toml"
BACKUP_BASE="$HOME/.shellbuddy_backup"
YES_TO_ALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes) YES_TO_ALL=true; shift ;;
        -h|--help)
            echo "Usage: ./uninstall.sh [-y]"
            echo "  -y, --yes   Accept all prompts (non-interactive)"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Colours ───────────────────────────────────────────────────────────────────
C_RESET='\033[0m'
C_BOLD='\033[1m'
C_RED='\033[1;31m'
C_GREEN='\033[1;32m'
C_YELLOW='\033[1;33m'
C_CYAN='\033[1;36m'
C_DIM='\033[2m'

ok()   { printf "  ${C_GREEN}✓${C_RESET}  %s\n" "$1"; }
skip() { printf "  ${C_DIM}–  %s${C_RESET}\n" "$1"; }
warn() { printf "  ${C_YELLOW}!  %s${C_RESET}\n" "$1"; }
die()  { printf "  ${C_RED}✗  %s${C_RESET}\n" "$1"; exit 1; }

ask() {
    # ask <prompt> — returns 0 (yes) or 1 (no)
    # In -y mode always returns 0
    if $YES_TO_ALL; then return 0; fi
    printf "  ${C_BOLD}%s${C_RESET} ${C_DIM}[y/N]${C_RESET} " "$1"
    read -r ans
    [[ "$ans" =~ ^[Yy]$ ]]
}

# ── Banner ────────────────────────────────────────────────────────────────────
printf "\n${C_CYAN}  shellbuddy — uninstaller${C_RESET}\n"
printf "  ${C_DIM}This will remove shellbuddy from your system.${C_RESET}\n"
printf "  ${C_DIM}Packages and tools installed by brew/pip are left untouched.${C_RESET}\n\n"

# ── 1. Stop daemon ────────────────────────────────────────────────────────────
PID_FILE="$INSTALL_DIR/daemon.pid"
if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null && ok "Daemon stopped (PID $PID)" || warn "Could not stop daemon (PID $PID)"
    else
        skip "Daemon not running"
    fi
    rm -f "$PID_FILE"
else
    skip "No daemon PID file found"
fi

# Kill any orphaned hint_daemon.py processes just in case
pkill -f "hint_daemon.py" 2>/dev/null && ok "Killed orphaned daemon processes" || true

# ── 2. Remove install directory ───────────────────────────────────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    if ask "Delete $INSTALL_DIR?"; then
        rm -rf "$INSTALL_DIR"
        ok "Deleted $INSTALL_DIR"
    else
        skip "Kept $INSTALL_DIR"
    fi
else
    skip "$INSTALL_DIR not found"
fi

# ── 3. Remove shellbuddy block from ~/.zshrc ──────────────────────────────────
if [[ -f "$ZSHRC" ]] && /usr/bin/grep -q "# shellbuddy" "$ZSHRC" 2>/dev/null; then
    if ask "Remove shellbuddy block from $ZSHRC?"; then
        # Back up first
        cp "$ZSHRC" "${ZSHRC}.shellbuddy_uninstall_bak"
        ok "Backed up $ZSHRC → ${ZSHRC}.shellbuddy_uninstall_bak"

        # The block is delimited by lines matching '# ── shellbuddy'
        # Strategy: delete from '# ── shellbuddy' through to the next
        # blank line that follows the closing brace of the last function,
        # OR through the next '# ──' section header that is NOT shellbuddy.
        # Most reliable: delete every line from '# ── shellbuddy' to
        # a line that is either empty after the block or starts another section.
        # Since .zshrc may have the block duplicated, run until clean.

        local before after
        before=$(/usr/bin/grep -c "# shellbuddy" "$ZSHRC" 2>/dev/null || echo 0)

        # Pass 1: remove lines from '# ── shellbuddy' marker to the next
        # line starting with '# ──' that does NOT contain 'shellbuddy'
        sed -i '' '/# ── shellbuddy/,/^# ── [^s][^h]/{ /^# ── [^s][^h]/!d; }' "$ZSHRC" 2>/dev/null || true
        # Pass 2: remove any remaining standalone '# ── shellbuddy' marker lines
        sed -i '' '/# ── shellbuddy/d' "$ZSHRC" 2>/dev/null || true
        # Pass 3: remove the SHELLBUDDY_DIR export line (in case it survived)
        sed -i '' '/export SHELLBUDDY_DIR=/d' "$ZSHRC" 2>/dev/null || true
        # Pass 4: collapse runs of 3+ blank lines to 1 (cosmetic cleanup)
        sed -i '' '/^$/{ N; /^\n$/{ N; /^\n\n$/d; }; }' "$ZSHRC" 2>/dev/null || true

        after=$(/usr/bin/grep -c "# shellbuddy" "$ZSHRC" 2>/dev/null || echo 0)
        if (( after == 0 )); then
            ok "Removed shellbuddy block from $ZSHRC ($before occurrences cleaned)"
        else
            warn "$after shellbuddy reference(s) remain in $ZSHRC — check manually"
            warn "Backup is at ${ZSHRC}.shellbuddy_uninstall_bak"
        fi
    else
        skip "Left $ZSHRC unchanged"
    fi
else
    skip "No shellbuddy block found in $ZSHRC"
fi

# ── 4. Remove shellbuddy keybinding from ~/.tmux.conf ─────────────────────────
if [[ -f "$TMUX_CONF" ]] && /usr/bin/grep -q "shellbuddy\|toggle_hints_pane\|show_stats" "$TMUX_CONF" 2>/dev/null; then
    if ask "Remove shellbuddy lines from $TMUX_CONF?"; then
        cp "$TMUX_CONF" "${TMUX_CONF}.shellbuddy_uninstall_bak"
        ok "Backed up $TMUX_CONF → ${TMUX_CONF}.shellbuddy_uninstall_bak"
        # Remove the comment + bind-key line pair
        sed -i '' '/# ── shellbuddy: Ctrl+A H/d' "$TMUX_CONF" 2>/dev/null || true
        sed -i '' '/toggle_hints_pane/d'          "$TMUX_CONF" 2>/dev/null || true
        sed -i '' '/show_stats/d'                  "$TMUX_CONF" 2>/dev/null || true
        ok "Removed shellbuddy keybinding from $TMUX_CONF"
    else
        skip "Left $TMUX_CONF unchanged"
    fi
else
    skip "No shellbuddy keybinding found in $TMUX_CONF"
fi

# ── 5. Restore starship.toml from backup (optional) ──────────────────────────
STARSHIP_BACKUP=$(ls -t "$BACKUP_BASE"/*/starship.toml 2>/dev/null | head -1 || true)
if [[ -n "$STARSHIP_BACKUP" && -f "$STARSHIP_CONF" ]]; then
    # Only offer if current config is shellbuddy's (has our marker on line 1)
    if /usr/bin/grep -q "# shellbuddy" "$STARSHIP_CONF" 2>/dev/null; then
        if ask "Restore original starship.toml from backup ($STARSHIP_BACKUP)?"; then
            cp "$STARSHIP_BACKUP" "$STARSHIP_CONF"
            ok "Restored $STARSHIP_CONF from backup"
        else
            skip "Left $STARSHIP_CONF unchanged"
        fi
    else
        skip "starship.toml not shellbuddy's — left unchanged"
    fi
else
    skip "No starship.toml backup found (or starship not installed)"
fi

# ── 6. Remove install backups (optional) ─────────────────────────────────────
if [[ -d "$BACKUP_BASE" ]]; then
    if ask "Delete install backups at $BACKUP_BASE?"; then
        rm -rf "$BACKUP_BASE"
        ok "Deleted $BACKUP_BASE"
    else
        skip "Kept $BACKUP_BASE"
    fi
else
    skip "No install backup directory found"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
printf "\n  ${C_GREEN}${C_BOLD}shellbuddy uninstalled.${C_RESET}\n"
printf "  ${C_DIM}Reload your shell: source ~/.zshrc  (or open a new tab)${C_RESET}\n"

# ── Package summary ───────────────────────────────────────────────────────────
printf "\n  ${C_BOLD}Packages not removed${C_RESET} ${C_DIM}(may have been installed by shellbuddy):${C_RESET}\n"
printf "  ${C_DIM}Removing them could break other tools — uninstall manually if needed.${C_RESET}\n\n"

_pkg_row() {
    local category="$1"; shift
    printf "  ${C_CYAN}%-16s${C_RESET}" "$category"
    printf "${C_DIM}%s${C_RESET}\n" "$*"
}

_pkg_row "Prerequisites"  "zsh  python3  tmux  homebrew"
_pkg_row "Shell (Core)"   "zoxide  eza  bat  fd  ripgrep  fzf  starship  atuin  tldr"
_pkg_row "Git & Dev"      "lazygit  git-delta  gh  git-lfs"
_pkg_row "System"         "bottom  dust  duf  procs  bandwhich"
_pkg_row "Python"         "miniconda  jupyterlab  black  ruff  uv"
_pkg_row "Network"        "httpie  jq  yq  mtr  wget  nmap"
_pkg_row "Infra"          "lazydocker  dive  k9s  terraform"
_pkg_row "Mac Tools"      "coreutils  trash  watch  tree  rename  entr  hyperfine  tokei  glow  mas"
_pkg_row "Docs"           "pandoc  glow  pdfgrep"
_pkg_row "AI Backends"    "ollama  pycryptodome (pip)"

printf "\n  ${C_DIM}To remove a brew package:  brew uninstall <name>${C_RESET}\n"
printf "  ${C_DIM}To remove a pip package:   pip uninstall <name>${C_RESET}\n"
printf "  ${C_DIM}To remove ollama:          brew uninstall ollama && rm -rf ~/.ollama${C_RESET}\n\n"
