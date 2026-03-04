#!/usr/bin/env zsh
# shellbuddy — patch_install.sh
# Minimal-patch installer: copies core scripts and makes the smallest possible
# changes to the running system (tmux config, rc file, terminal settings).
#
# No Homebrew, no optional-tool installs, no full config replacements.
# Safe to run on any system that has zsh and python3.
#
# Usage:
#   ./scripts/patch_install.sh                # interactive
#   ./scripts/patch_install.sh -y             # yes to all defaults
#   ./scripts/patch_install.sh --backend ollama
#   ./scripts/patch_install.sh --dir ~/.local/shellbuddy
#
# Options:
#   --backend <copilot|claude|ollama|openai|none>  AI backend (default: auto-detect)
#   --dir <path>                                   Install dir (default: ~/.shellbuddy)
#   --no-tmux                                      Skip tmux keybinding patch
#   --no-rc                                        Skip rc file patch
#   --no-term                                      Skip terminal settings patch
#   -y, --yes                                      Accept all defaults (no prompts)

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INSTALL_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
BACKUP_DIR="$HOME/.shellbuddy_backup/$(date +%Y%m%d_%H%M%S)"

# ── Parse args ────────────────────────────────────────────────────────────────
BACKEND="auto"
SKIP_TMUX=false
SKIP_RC=false
SKIP_TERM=false
YES_TO_ALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend) BACKEND="$2"; shift 2 ;;
        --dir)     INSTALL_DIR="$2"; shift 2 ;;
        --no-tmux) SKIP_TMUX=true; shift ;;
        --no-rc)   SKIP_RC=true; shift ;;
        --no-term) SKIP_TERM=true; shift ;;
        -y|--yes)  YES_TO_ALL=true; shift ;;
        -h|--help)
            echo "Usage: ./scripts/patch_install.sh [--backend <copilot|claude|ollama|openai|none>]"
            echo "                                   [--dir <path>] [--no-tmux] [--no-rc] [--no-term] [-y]"
            exit 0 ;;
        *) shift ;;
    esac
done

# ── Colours & helpers ─────────────────────────────────────────────────────────
C_CYAN='\033[1;36m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_RED='\033[0;31m'
C_DIM='\033[2m'
C_BOLD='\033[1m'
C_RESET='\033[0m'

info()  { printf "  ${C_CYAN}->  ${C_RESET}%s\n" "$*" }
ok()    { printf "  ${C_GREEN} +  ${C_RESET}%s\n" "$*" }
warn()  { printf "  ${C_YELLOW} !  ${C_RESET}%s\n" "$*" }
fail()  { printf "  ${C_RED} x  ${C_RESET}%s\n" "$*"; exit 1 }
step()  { printf "\n  ${C_CYAN}${C_BOLD}[$1/5]${C_RESET} %s\n" "$2" }
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

# ── Banner ────────────────────────────────────────────────────────────────────
printf "\n  ${C_CYAN}${C_BOLD}"
cat << 'BANNER'
   ┌─────────────────────────────────────────┐
   │  shellbuddy — minimal patch install     │
   │  patches: scripts · tmux · rc · term    │
   └─────────────────────────────────────────┘
BANNER
printf "${C_RESET}\n"

# ── Step 1: Prerequisites ─────────────────────────────────────────────────────
step 1 "Checking prerequisites"

if ! command -v python3 &>/dev/null; then
    fail "python3 not found — install it first (e.g. brew install python3 or apt install python3)"
fi
ok "python3 $(python3 --version 2>&1 | awk '{print $2}')"

if ! python3 -c "import asyncio, json, subprocess, threading, time" 2>/dev/null; then
    fail "python3 missing standard library modules (asyncio, json, subprocess, threading, time)"
fi
ok "python3 standard library OK"

HAS_TMUX=false
if command -v tmux &>/dev/null; then
    HAS_TMUX=true
    ok "tmux $(tmux -V 2>/dev/null | awk '{print $2}')"
else
    warn "tmux not found — hints pane requires tmux (install later)"
fi

# Detect shell rc file
CURRENT_SHELL="$(basename "${SHELL:-zsh}")"
if [[ "$CURRENT_SHELL" == "zsh" ]]; then
    RC_FILE="$HOME/.zshrc"
elif [[ "$CURRENT_SHELL" == "bash" ]]; then
    RC_FILE="${BASH_ENV:-$HOME/.bashrc}"
    [[ -f "$HOME/.bash_profile" ]] && RC_FILE="$HOME/.bash_profile"
else
    RC_FILE="$HOME/.zshrc"
    warn "Unknown shell ($CURRENT_SHELL) — defaulting rc file to ~/.zshrc"
fi
ok "Shell rc file: $RC_FILE"

TMUX_CONF="${HOME}/.tmux.conf"

# ── Step 2: AI backend ────────────────────────────────────────────────────────
step 2 "AI backend"

if [[ "$BACKEND" == "auto" ]]; then
    if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
        BACKEND="copilot"
    elif [[ -n "$ANTHROPIC_API_KEY" ]]; then
        BACKEND="claude"
    elif [[ -n "$OPENAI_API_KEY" ]]; then
        BACKEND="openai"
    elif curl -sf http://localhost:11434/api/tags &>/dev/null 2>&1; then
        BACKEND="ollama"
    else
        BACKEND="ollama"
        warn "No backend detected — defaulting to ollama (localhost:11434)"
        info "Start ollama: ollama serve  |  pull a model: ollama pull qwen3:4b"
    fi
fi

case "$BACKEND" in
    copilot) ok "Backend: GitHub Copilot (gpt-4.1)" ;;
    claude)  ok "Backend: Anthropic Claude" ;;
    openai)  ok "Backend: OpenAI-compatible" ;;
    ollama)  ok "Backend: Ollama (local)" ;;
    none)    ok "Backend: none (hints disabled until configured)" ;;
    *)       warn "Unknown backend '$BACKEND' — will be written to config as-is" ;;
esac

# ── Step 3: Install scripts ───────────────────────────────────────────────────
step 3 "Installing shellbuddy scripts to $INSTALL_DIR"

for f in \
    "$REPO_DIR/scripts/hint_daemon.py" \
    "$REPO_DIR/scripts/log_cmd.sh" \
    "$REPO_DIR/scripts/show_hints.sh" \
    "$REPO_DIR/scripts/show_stats.sh" \
    "$REPO_DIR/scripts/toggle_hints_pane.sh" \
    "$REPO_DIR/scripts/start_daemon.sh" \
    "$REPO_DIR/scripts/verify.sh"
do
    [[ -f "$f" ]] || fail "Missing source file: $f — re-clone the repo and re-run"
done
[[ -d "$REPO_DIR/backends" ]] || fail "Missing backends/ directory — re-clone the repo and re-run"

mkdir -p "$INSTALL_DIR" || fail "Cannot create $INSTALL_DIR — check permissions"
mkdir -p "$INSTALL_DIR/backends" || fail "Cannot create $INSTALL_DIR/backends"

cp "$REPO_DIR/scripts/hint_daemon.py"       "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/log_cmd.sh"           "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/show_hints.sh"        "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/show_stats.sh"        "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/toggle_hints_pane.sh" "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/start_daemon.sh"      "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/verify.sh"            "$INSTALL_DIR/"
cp "$REPO_DIR/backends/"*.py               "$INSTALL_DIR/backends/"
chmod +x "$INSTALL_DIR"/*.sh

# Install Python deps if pip3 available
if command -v pip3 &>/dev/null && [[ -f "$REPO_DIR/requirements.txt" ]]; then
    info "Installing Python dependencies..."
    pip3 install -q -r "$REPO_DIR/requirements.txt" 2>/dev/null \
        && ok "Python dependencies installed" \
        || warn "pip3 install failed — some features may need manual: pip3 install -r requirements.txt"
fi

# Write config.json
CONFIG_JSON="$INSTALL_DIR/config.json"
if [[ "$BACKEND" == "ollama" ]]; then
    cat > "$CONFIG_JSON" << 'CFGEOF'
{
  "hint_backend": "ollama",
  "hint_model":   "qwen3:4b",
  "tip_backend":  "ollama",
  "tip_model":    "qwen3:8b",
  "ollama_url":   "http://localhost:11434"
}
CFGEOF
elif [[ "$BACKEND" == "claude" ]]; then
    cat > "$CONFIG_JSON" << 'CFGEOF'
{
  "hint_backend": "claude",
  "hint_model":   "claude-haiku-4-5-20251001",
  "tip_backend":  "claude",
  "tip_model":    "claude-sonnet-4-5-20250514"
}
CFGEOF
elif [[ "$BACKEND" == "copilot" ]]; then
    cat > "$CONFIG_JSON" << 'CFGEOF'
{
  "hint_backend": "copilot",
  "hint_model":   "gpt-4.1",
  "tip_backend":  "copilot",
  "tip_model":    "gpt-4.1"
}
CFGEOF
elif [[ "$BACKEND" == "openai" ]]; then
    cat > "$CONFIG_JSON" << 'CFGEOF'
{
  "hint_backend": "openai",
  "hint_model":   "gpt-4o-mini",
  "tip_backend":  "openai",
  "tip_model":    "gpt-4o"
}
CFGEOF
else
    cat > "$CONFIG_JSON" << 'CFGEOF'
{
  "hint_backend": "ollama",
  "hint_model":   "qwen3:4b",
  "tip_backend":  "ollama",
  "tip_model":    "qwen3:8b",
  "ollama_url":   "http://localhost:11434"
}
CFGEOF
fi
ok "Config written → $CONFIG_JSON"
ok "Scripts installed → $INSTALL_DIR"

# ── Step 4: Minimal tmux patch ────────────────────────────────────────────────
step 4 "tmux configuration (minimal patch)"

if $SKIP_TMUX; then
    warn "Skipped (--no-tmux)"
elif ! $HAS_TMUX; then
    warn "tmux not installed — skipping (install tmux, then re-run to add keybinding)"
elif grep -q "toggle_hints_pane\|shellbuddy" "$TMUX_CONF" 2>/dev/null; then
    ok "tmux config already has shellbuddy keybinding"
else
    if [[ -f "$TMUX_CONF" ]]; then
        if ! ask "Append shellbuddy keybinding to existing ~/.tmux.conf?"; then
            warn "Skipped — add manually:  bind H run-shell \"$INSTALL_DIR/toggle_hints_pane.sh\""
            SKIP_TMUX=true
        else
            backup_file "$TMUX_CONF"
        fi
    fi

    if ! $SKIP_TMUX; then
        # Append only the minimal shellbuddy tmux block
        cat >> "$TMUX_CONF" << TMUXEOF

# ── shellbuddy: minimal patch ─────────────────────────────────────────────────
# True colour (required for 256-color hints display)
set -g default-terminal "screen-256color"
set -ga terminal-overrides ",xterm-256color:Tc"
# Zero escape-time (prevents Esc lag in vim/nvim inside tmux)
set -sg escape-time 0
# Ctrl+A H — toggle shellbuddy hints pane
bind H run-shell 'zsh "\${SHELLBUDDY_DIR:-\$HOME/.shellbuddy}/toggle_hints_pane.sh"'
# ─────────────────────────────────────────────────────────────────────────────
TMUXEOF
        ok "shellbuddy block appended → $TMUX_CONF"
        info "Reload tmux config: Ctrl+B r  (or Ctrl+A r if you use Ctrl+A as prefix)"
    fi
fi

# ── Step 5: Minimal rc file patch ─────────────────────────────────────────────
step 5 "Shell rc file patch ($RC_FILE)"

SB_MARKER="# shellbuddy"

if $SKIP_RC; then
    warn "Skipped (--no-rc)"
elif grep -q "$SB_MARKER" "$RC_FILE" 2>/dev/null; then
    ok "$(basename "$RC_FILE") already has shellbuddy hooks"
else
    if ! ask "Append shellbuddy hooks to $RC_FILE?"; then
        warn "Skipped — source manually:"
        info "  source $INSTALL_DIR/rc_patch.zsh"
    else
        backup_file "$RC_FILE"

        # Write the minimal rc snippet to a standalone file in INSTALL_DIR
        cat > "$INSTALL_DIR/rc_patch.zsh" << RCEOF
# shellbuddy — minimal rc patch
# Generated by patch_install.sh — safe to remove if you uninstall shellbuddy.
# To undo: remove from ${RC_FILE} (or run scripts/patch_uninstall.sh).

export SHELLBUDDY_DIR="\${SHELLBUDDY_DIR:-\$HOME/.shellbuddy}"
export PATH="\$SHELLBUDDY_DIR:\$PATH"

# Log every command (preexec fires before the command runs)
function _shellbuddy_log() { SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" zsh "\$SHELLBUDDY_DIR/log_cmd.sh" "\$1" }
autoload -Uz add-zsh-hook
add-zsh-hook preexec _shellbuddy_log

# Auto-start daemon when a shell opens (idempotent — silent if already running)
(SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" source "\$SHELLBUDDY_DIR/start_daemon.sh" &>/dev/null &)

# sb — toggle hints pane (starts daemon if not running)
function sb() {
    local PID_FILE="\$SHELLBUDDY_DIR/daemon.pid"
    local pid="" already_running=false
    if [[ -f "\$PID_FILE" ]]; then
        pid=\$(cat "\$PID_FILE" 2>/dev/null)
        [[ -n "\$pid" ]] && kill -0 "\$pid" 2>/dev/null && already_running=true
    fi
    if \$already_running; then
        echo "shellbuddy: active (PID \$pid)"
    else
        echo "shellbuddy: starting daemon..."
        SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" source "\$SHELLBUDDY_DIR/start_daemon.sh"
        sleep 0.8
        pid=\$(cat "\$PID_FILE" 2>/dev/null)
        if [[ -z "\$pid" ]] || ! kill -0 "\$pid" 2>/dev/null; then
            echo "shellbuddy: failed to start — check: hints-log"; return 1
        fi
        echo "shellbuddy: started (PID \$pid)"
    fi
    if [[ -n "\$TMUX" ]]; then
        SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" zsh "\$SHELLBUDDY_DIR/toggle_hints_pane.sh"
    else
        echo "shellbuddy: not in tmux — run 'tmux new -s dev' then 'sb'"
    fi
}
alias shellbuddy='sb'
alias hints-stop='{ [[ -f \$SHELLBUDDY_DIR/daemon.pid ]] && kill \$(cat \$SHELLBUDDY_DIR/daemon.pid) && rm -f \$SHELLBUDDY_DIR/daemon.pid && echo "shellbuddy: stopped"; } 2>/dev/null'
alias hints-log='tail -f \$SHELLBUDDY_DIR/daemon.log'
alias hints-now='[[ -f \$SHELLBUDDY_DIR/current_hints.txt ]] && cat \$SHELLBUDDY_DIR/current_hints.txt || echo "No hints yet"'
alias hints-status='{ [[ -f \$SHELLBUDDY_DIR/daemon.pid ]] && kill -0 \$(cat \$SHELLBUDDY_DIR/daemon.pid) 2>/dev/null && echo "shellbuddy: running (PID \$(cat \$SHELLBUDDY_DIR/daemon.pid))"; } || echo "shellbuddy: stopped"'
alias hints-start='SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" source "\$SHELLBUDDY_DIR/start_daemon.sh"'

# /tip — ask any CLI question, get instant AI answer
function /tip() {
    local query="\$*"
    if [[ -z "\$query" ]]; then
        printf '\\033[36m  usage: /tip <question>\\033[0m\\n'
        return 1
    fi
    local QUERY_FILE="\$SHELLBUDDY_DIR/tip_query.txt"
    local RESULT_FILE="\$SHELLBUDDY_DIR/tip_result.txt"
    echo "\$query" > "\$QUERY_FILE"
    printf '\\033[36m  [>_] thinking...\\033[0m'
    local waited=0
    while [[ -f "\$QUERY_FILE" ]] && (( waited < 30 )); do
        sleep 0.5; waited=\$((waited + 1))
    done
    printf '\\r\\033[K'
    if [[ -f "\$RESULT_FILE" ]]; then
        echo ""
        printf '\\033[1;36m  [>_] /tip\\033[0m \\033[2m%s\\033[0m\\n' "\$query"
        printf '\\033[2m  ────────────────────────────────────────\\033[0m\\n'
        while IFS= read -r line; do printf '\\033[32m  %s\\033[0m\\n' "\$line"; done < "\$RESULT_FILE"
        echo ""; rm -f "\$RESULT_FILE"
    else
        echo "  [timeout — daemon may not be running. Try: hints-start]"
    fi
}
# end shellbuddy
RCEOF

        # Source the patch file from the rc file
        printf '\n# shellbuddy — source minimal rc patch (added by patch_install.sh)\n' >> "$RC_FILE"
        printf 'source "%s/rc_patch.zsh"\n' "$INSTALL_DIR" >> "$RC_FILE"
        ok "shellbuddy hooks appended → $RC_FILE"
        info "Reload shell: source $RC_FILE"
    fi
fi

# ── Terminal settings patch (macOS only) ──────────────────────────────────────
if ! $SKIP_TERM && [[ "$OSTYPE" == darwin* ]]; then
    if [[ "$TERM_PROGRAM" == "Apple_Terminal" ]]; then
        info "Setting Terminal.app background to pure black for best hint display..."
        if osascript -e '
            tell application "Terminal"
                set background color of settings set "Basic" to {0, 0, 0, 65535}
            end tell' 2>/dev/null; then
            ok "Terminal.app background → pure black"
        else
            warn "Could not set Terminal.app background (non-critical)"
        fi
    elif [[ "$TERM_PROGRAM" == "iTerm.app" ]]; then
        info "iTerm2 detected — configure background color in Preferences → Profiles → Colors"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
printf "\n  ${C_GREEN}${C_BOLD} ✓  shellbuddy minimal patch complete${C_RESET}\n"
printf "\n"
printf "  ${C_CYAN}Next steps:${C_RESET}\n"
if ! $SKIP_RC; then
    printf "  ${C_DIM}  1. Reload your shell:${C_RESET}  source %s\n" "$RC_FILE"
fi
if $HAS_TMUX && ! $SKIP_TMUX; then
    printf "  ${C_DIM}  2. Open tmux:${C_RESET}          tmux new -s dev\n"
fi
printf "  ${C_DIM}  3. Start shellbuddy:${C_RESET}   sb\n"
printf "\n"
printf "  ${C_DIM}To verify:    zsh %s/verify.sh${C_RESET}\n" "$INSTALL_DIR"
printf "  ${C_DIM}To uninstall: zsh %s/patch_uninstall.sh${C_RESET}\n" "$REPO_DIR/scripts"
printf "\n"
