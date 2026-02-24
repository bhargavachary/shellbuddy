#!/usr/bin/env zsh
# shellbuddy — verify.sh
# Dry-run verification of the entire setup. Run after install.sh to check health.
# Usage: zsh scripts/verify.sh           (from repo)
#    or: zsh ~/.shellbuddy/verify.sh      (from install dir)

SB_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
ZSHRC="$HOME/.zshrc"
TMUX_CONF="$HOME/.tmux.conf"

C_CYAN='\033[1;36m'  C_GREEN='\033[0;32m'  C_YELLOW='\033[0;33m'
C_RED='\033[0;31m'   C_DIM='\033[2m'       C_BOLD='\033[1m'
C_RESET='\033[0m'

PASS=0  FAIL=0  WARN=0

pass()    { printf "  ${C_GREEN} +  ${C_RESET}%s\n" "$*";   PASS=$((PASS + 1)); }
skip()    { printf "  ${C_YELLOW} ~  ${C_RESET}%s\n" "$*";  WARN=$((WARN + 1)); }
bad()     { printf "  ${C_RED} x  ${C_RESET}%s\n" "$*";     FAIL=$((FAIL + 1)); }
dim()     { printf "  ${C_DIM} .  %s${C_RESET}\n" "$*"; }
section() { printf "\n  ${C_CYAN}${C_BOLD}%s${C_RESET}\n" "$*"; }

# check "label" "command" — runs command silently, pass/bad based on exit code
chk() {
    if eval "$2" >/dev/null 2>&1; then pass "$1"; else bad "$1"; fi
}

printf "\n"
printf "  ${C_CYAN}${C_BOLD}"
printf "   ┌─────────────────────────────────────────┐\n"
printf "   │   [>_] shellbuddy verification          │\n"
printf "   └─────────────────────────────────────────┘\n"
printf "${C_RESET}\n"

# ═════════════════════════════════════════════════════════════════════════════
section "Core prerequisites"
# ═════════════════════════════════════════════════════════════════════════════

chk "zsh available"      "command -v zsh"
chk "python3 available"  "command -v python3"
chk "git available"      "command -v git"
chk "Python 3.9+"        "python3 -c 'import sys; assert sys.version_info >= (3,9)'"

# Show versions
ZSH_V=$(zsh --version 2>/dev/null | head -1 | awk '{print $2}')
PY_V=$(python3 --version 2>/dev/null | awk '{print $2}')
GIT_V=$(git --version 2>/dev/null | awk '{print $3}')
dim "versions: zsh $ZSH_V, python $PY_V, git $GIT_V"

# ═════════════════════════════════════════════════════════════════════════════
section "shellbuddy installation"
# ═════════════════════════════════════════════════════════════════════════════

chk "Install dir exists"            "test -d '$SB_DIR'"
chk "hint_daemon.py"                "test -f '$SB_DIR/hint_daemon.py'"
chk "log_cmd.sh (executable)"       "test -x '$SB_DIR/log_cmd.sh'"
chk "show_hints.sh (executable)"    "test -x '$SB_DIR/show_hints.sh'"
chk "toggle_hints_pane (executable)" "test -x '$SB_DIR/toggle_hints_pane.sh'"
chk "start_daemon.sh (executable)"  "test -x '$SB_DIR/start_daemon.sh'"
chk "backends/copilot.py"           "test -f '$SB_DIR/backends/copilot.py'"
chk "backends/ollama.py"            "test -f '$SB_DIR/backends/ollama.py'"
chk "backends/openai_compat.py"     "test -f '$SB_DIR/backends/openai_compat.py'"
chk "hint_daemon.py compiles"       "python3 -c \"import py_compile; py_compile.compile('$SB_DIR/hint_daemon.py', doraise=True)\""

# ═════════════════════════════════════════════════════════════════════════════
section "Shell integration (.zshrc)"
# ═════════════════════════════════════════════════════════════════════════════

if [[ -f "$ZSHRC" ]]; then
    chk "shellbuddy block"    "grep -q 'shellbuddy' '$ZSHRC'"
    chk "preexec logger hook" "grep -q '_shellbuddy_log' '$ZSHRC'"
    chk "daemon auto-start"   "grep -q 'start_daemon' '$ZSHRC'"
    chk "sb() function"       "grep -q 'function sb' '$ZSHRC'"
    chk "/tip function"       "grep -q '/tip' '$ZSHRC'"
    chk "hints-stop alias"    "grep -q 'hints-stop' '$ZSHRC'"
else
    bad ".zshrc not found"
fi

# ═════════════════════════════════════════════════════════════════════════════
section "tmux configuration"
# ═════════════════════════════════════════════════════════════════════════════

if command -v tmux >/dev/null 2>&1; then
    pass "tmux $(tmux -V 2>/dev/null | awk '{print $2}')"
    if [[ -f "$TMUX_CONF" ]]; then
        if grep -q "toggle_hints_pane\|shellbuddy" "$TMUX_CONF" 2>/dev/null; then
            pass "Hints keybinding in tmux.conf"
        else
            skip "No shellbuddy keybinding in tmux.conf"
        fi
    else
        skip "No ~/.tmux.conf found"
    fi
else
    skip "tmux not installed (brew install tmux)"
fi

# ═════════════════════════════════════════════════════════════════════════════
section "AI backends"
# ═════════════════════════════════════════════════════════════════════════════

AI_FOUND=false

# Copilot
if [[ -f "$HOME/Library/Application Support/Code/User/globalStorage/state.vscdb" ]]; then
    if python3 -c "from Crypto.Cipher import AES" 2>/dev/null; then
        pass "Copilot: VS Code + pycryptodome ready"
        AI_FOUND=true
    else
        skip "Copilot: VS Code found but pycryptodome missing"
    fi
else
    dim "Copilot: VS Code not found"
fi

# Claude
if [[ -n "$ANTHROPIC_API_KEY" ]]; then
    pass "Claude: ANTHROPIC_API_KEY set"
    AI_FOUND=true
elif security find-generic-password -s "anthropic" -a "api_key" -w >/dev/null 2>&1; then
    pass "Claude: API key in macOS Keychain"
    AI_FOUND=true
else
    dim "Claude: no API key found"
fi

# Ollama
if command -v ollama >/dev/null 2>&1; then
    pass "Ollama: installed"
    AI_FOUND=true
    if curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
        pass "Ollama: running"
        MODELS=$(curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
    for m in d.get('models',[]):
        print(f'      {m[\"name\"]}')
except: pass
" 2>/dev/null)
        if [[ -n "$MODELS" ]]; then
            dim "Available models:"
            echo "$MODELS"
        fi
    else
        skip "Ollama: installed but not running (ollama serve)"
    fi
else
    dim "Ollama: not installed"
fi

if ! $AI_FOUND; then
    skip "No AI backend — rule-based hints only"
fi

# ═════════════════════════════════════════════════════════════════════════════
section "Daemon status"
# ═════════════════════════════════════════════════════════════════════════════

if [[ -f "$SB_DIR/daemon.pid" ]]; then
    DPID=$(cat "$SB_DIR/daemon.pid" 2>/dev/null)
    if [[ -n "$DPID" ]] && kill -0 "$DPID" 2>/dev/null; then
        pass "Daemon running (PID $DPID)"
    else
        skip "Stale PID file (daemon not running)"
    fi
else
    skip "Daemon not running"
fi

if [[ -f "$SB_DIR/cmd_log.jsonl" ]]; then
    LINES=$(wc -l < "$SB_DIR/cmd_log.jsonl" 2>/dev/null | tr -d ' ')
    pass "Command log: $LINES entries"
else
    skip "No command log yet"
fi

if [[ -f "$SB_DIR/current_hints.txt" ]]; then
    pass "Hints file exists"
else
    skip "No hints file yet"
fi

# ═════════════════════════════════════════════════════════════════════════════
section "Recommended tools"
# ═════════════════════════════════════════════════════════════════════════════

TOOL_CMDS=(tmux zoxide eza bat fd rg fzf starship atuin lazygit delta gh dust btm procs tldr jq http hyperfine tokei trash glow entr duf)
TOOL_PKGS=(tmux zoxide eza bat fd ripgrep fzf starship atuin lazygit git-delta gh dust bottom procs tldr jq httpie hyperfine tokei trash glow entr duf)

T_OK=0  T_MISS=0  MISS_LIST=""
for i in {1..${#TOOL_CMDS[@]}}; do
    if command -v "${TOOL_CMDS[$i]}" >/dev/null 2>&1; then
        T_OK=$((T_OK + 1))
    else
        T_MISS=$((T_MISS + 1))
        MISS_LIST+="${TOOL_PKGS[$i]} "
    fi
done

TOTAL=$((T_OK + T_MISS))
pass "$T_OK/$TOTAL tools installed"
if [[ $T_MISS -gt 0 ]]; then
    skip "$T_MISS missing: $MISS_LIST"
    dim "Install: brew install $MISS_LIST"
fi

# ═════════════════════════════════════════════════════════════════════════════
section "Results"
# ═════════════════════════════════════════════════════════════════════════════

printf "\n"
printf "  ${C_GREEN}${C_BOLD} +  $PASS passed${C_RESET}"
[[ $WARN -gt 0 ]] && printf "   ${C_YELLOW} ~  $WARN warnings${C_RESET}"
[[ $FAIL -gt 0 ]] && printf "   ${C_RED} x  $FAIL failed${C_RESET}"
printf "\n"

if [[ $FAIL -eq 0 ]]; then
    printf "\n  ${C_GREEN}${C_BOLD}[>_] shellbuddy is ready.${C_RESET}\n"
    printf "  ${C_DIM}Start: tmux new -s dev && sb${C_RESET}\n"
else
    printf "\n  ${C_RED}${C_BOLD}[>_] Fix failures above, then re-run verify.${C_RESET}\n"
fi
printf "\n"
