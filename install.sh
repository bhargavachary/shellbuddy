#!/usr/bin/env zsh
# shellbuddy — install.sh
# Interactive installer with dependency checks, safe config merging, and backups.
# Idempotent — safe to re-run.
#
# Usage:
#   ./install.sh                                    # interactive (recommended)
#   ./install.sh -y                                 # yes to all, accept defaults
#   ./install.sh --backend ollama --no-starship     # non-interactive overrides
#
# Options:
#   --backend <copilot|claude|ollama|none>   AI backend (default: auto-detect)
#   --dir <path>                             Install dir (default: ~/.shellbuddy)
#   --no-tmux                                Skip tmux config
#   --no-starship                            Skip starship config
#   --no-zshrc                               Skip .zshrc patching
#   -y, --yes                                Accept all defaults (no prompts)

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"
ZSHRC="$HOME/.zshrc"
TMUX_CONF="$HOME/.tmux.conf"
STARSHIP_CONF="$HOME/.config/starship.toml"
BACKUP_DIR="$HOME/.shellbuddy_backup/$(date +%Y%m%d_%H%M%S)"

# ── Parse args ────────────────────────────────────────────────────────────────
BACKEND="auto"
SKIP_TMUX=false
SKIP_STARSHIP=false
SKIP_ZSHRC=false
YES_TO_ALL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend)     BACKEND="$2"; shift 2 ;;
        --dir)         INSTALL_DIR="$2"; shift 2 ;;
        --no-tmux)     SKIP_TMUX=true; shift ;;
        --no-starship) SKIP_STARSHIP=true; shift ;;
        --no-zshrc)    SKIP_ZSHRC=true; shift ;;
        -y|--yes)      YES_TO_ALL=true; shift ;;
        -h|--help)
            echo "Usage: ./install.sh [--backend <copilot|claude|ollama|none>] [--dir <path>]"
            echo "                    [--no-tmux] [--no-starship] [--no-zshrc] [-y|--yes]"
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

info()    { printf "  ${C_CYAN}->  ${C_RESET}%s\n" "$*" }
ok()      { printf "  ${C_GREEN} +  ${C_RESET}%s\n" "$*" }
warn()    { printf "  ${C_YELLOW} !  ${C_RESET}%s\n" "$*" }
fail()    { printf "  ${C_RED} x  ${C_RESET}%s\n" "$*"; exit 1 }
step()    { printf "\n  ${C_CYAN}${C_BOLD}[$1/${TOTAL_STEPS}]${C_RESET} %s\n" "$2" }
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
        ok "Backed up $(basename "$1") -> $BACKUP_DIR/"
    fi
}

# Check network reachability (fast — just TCP to 1.1.1.1:443)
has_internet() {
    nc -z -w 3 1.1.1.1 443 &>/dev/null 2>&1
}

# Free disk space in GB at a given path
free_disk_gb() {
    df -Pk "$1" 2>/dev/null | awk 'NR==2 {printf "%.0f", $4/1024/1024}'
}

TOTAL_STEPS=8

# ── Banner ────────────────────────────────────────────────────────────────────
printf "\n"
printf "  ${C_CYAN}${C_BOLD}"
cat << 'BANNER'
   ┌─────────────────────────────────────────┐
   │                                         │
   │   ╔═╗╦ ╦╔═╗╦  ╦  ╔╗ ╦ ╦╔╦╗╔╦╗╦ ╦     │
   │   ╚═╗╠═╣║╣ ║  ║  ╠╩╗║ ║ ║║ ║║╚╦╝     │
   │   ╚═╝╩ ╩╚═╝╩═╝╩═╝╚═╝╚═╝═╩╝═╩╝ ╩      │
   │                                         │
   │   [>_] ambient terminal coaching        │
   │                                         │
   └─────────────────────────────────────────┘
BANNER
printf "${C_RESET}\n"
printf "  ${C_DIM}Watches your commands. Shows better alternatives.${C_RESET}\n"
printf "  ${C_DIM}Designed for developers with high knowledge, unreliable recall.${C_RESET}\n\n"

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 1: PREREQUISITES
# ═══════════════════════════════════════════════════════════════════════════════

step 1 "Checking prerequisites"

# ── sudo guard ────────────────────────────────────────────────────────────────
if [[ "$EUID" == "0" ]] || [[ "$(id -u)" == "0" ]]; then
    printf "  ${C_RED} x  ${C_RESET}Do not run this installer with sudo.\n"
    printf "  ${C_DIM}      sudo changes \$HOME to /var/root, breaking all install paths.\n"
    printf "        Run as your normal user:  ./install.sh${C_RESET}\n"
    exit 1
fi

# ── Write permissions ─────────────────────────────────────────────────────────
if [[ ! -w "$HOME" ]]; then
    fail "Cannot write to $HOME — check permissions"
fi

# ── Disk space (need at least 1GB free for scripts; model checked later) ──────
DISK_FREE_GB="$(free_disk_gb "$HOME")"
if (( DISK_FREE_GB < 1 )); then
    fail "Less than 1GB free in $HOME (have ${DISK_FREE_GB}GB) — free up space and re-run"
fi
ok "disk: ${DISK_FREE_GB}GB free"

# ── Shell detection ───────────────────────────────────────────────────────────
CURRENT_SHELL="$(basename "${SHELL:-unknown}")"
SHELL_SUPPORTED=false
SHELL_RC=""

case "$CURRENT_SHELL" in
    zsh)
        SHELL_SUPPORTED=true
        SHELL_RC="$HOME/.zshrc"
        ok "shell: zsh (fully supported)"
        ;;
    bash)
        SHELL_SUPPORTED=true
        if [[ -f "$HOME/.bashrc" ]]; then
            SHELL_RC="$HOME/.bashrc"
        else
            SHELL_RC="$HOME/.bash_profile"
        fi
        warn "shell: bash — supported, but shellbuddy is optimised for zsh"
        info "  hint: switch with:  chsh -s \$(which zsh)"
        ;;
    fish)
        SHELL_SUPPORTED=false
        SHELL_RC="$HOME/.config/fish/config.fish"
        warn "shell: fish — not fully supported"
        info "  shellbuddy hooks use zsh syntax; fish users must add hooks manually"
        info "  hint: switch with:  chsh -s \$(which zsh)"
        ;;
    csh|tcsh)
        SHELL_SUPPORTED=false
        warn "shell: $CURRENT_SHELL — not supported"
        info "  shellbuddy requires zsh or bash"
        info "  hint: switch with:  chsh -s \$(which zsh)"
        ;;
    *)
        SHELL_SUPPORTED=false
        warn "shell: $CURRENT_SHELL — unrecognised"
        info "  shellbuddy is tested on zsh and bash"
        info "  hint: switch with:  chsh -s \$(which zsh)"
        ;;
esac

if [[ -n "$SHELL_RC" ]]; then
    ZSHRC="$SHELL_RC"
fi

if ! $SHELL_SUPPORTED; then
    if ! ask "Continue anyway? (shell integration step will be skipped)"; then
        fail "Aborted — switch to zsh or bash and re-run"
    fi
    SKIP_ZSHRC=true
fi

# ── Homebrew (needed early — used to install zsh, python3, tmux if missing) ───
HAS_BREW=false
if command -v brew &>/dev/null; then
    HAS_BREW=true
fi

# ── zsh ───────────────────────────────────────────────────────────────────────
if ! command -v zsh &>/dev/null; then
    warn "zsh not found (required for shellbuddy scripts)"
    if $HAS_BREW; then
        if ask "Install zsh via Homebrew?"; then
            brew install zsh && ok "zsh installed" || fail "Failed to install zsh"
        else
            fail "zsh is required — install it and re-run"
        fi
    else
        fail "zsh not found and Homebrew not available — install zsh manually and re-run"
    fi
fi
ok "zsh $(zsh --version 2>/dev/null | head -1 | awk '{print $2}')"

# ── python3 ───────────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    warn "python3 not found (required)"
    if $HAS_BREW; then
        if ask "Install Python 3 via Homebrew?"; then
            brew install python3 && ok "python3 installed" || fail "Failed to install python3"
        else
            fail "python3 is required — install it and re-run"
        fi
    else
        fail "python3 not found and Homebrew not available — install python3 manually and re-run"
    fi
fi
ok "python3 $(python3 --version 2>/dev/null | awk '{print $2}')"

# ── Python version (3.9+) ─────────────────────────────────────────────────────
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 9) )); then
    warn "Python $PY_VERSION found — 3.9+ required"
    if $HAS_BREW; then
        if ask "Install Python 3.12 via Homebrew? (will not affect system python)"; then
            brew install python@3.12 || fail "Failed to install python@3.12"
            # Prefer the brew-managed python
            export PATH="$(brew --prefix)/opt/python@3.12/bin:$PATH"
            ok "python3 $(python3 --version 2>/dev/null | awk '{print $2}')"
        else
            fail "Python 3.9+ required — install it and re-run"
        fi
    else
        fail "Python 3.9+ required (found $PY_VERSION) — install a newer Python and re-run"
    fi
fi

# ── tmux ──────────────────────────────────────────────────────────────────────
HAS_TMUX=false
if command -v tmux &>/dev/null; then
    ok "tmux $(tmux -V 2>/dev/null | awk '{print $2}')"
    HAS_TMUX=true
else
    warn "tmux not found — hints pane requires tmux"
    if $HAS_BREW; then
        if ask "Install tmux now? (recommended — needed for the hints pane)"; then
            brew install tmux && HAS_TMUX=true && ok "tmux installed" || warn "tmux install failed — continuing without it"
        else
            info "Install tmux later: brew install tmux"
        fi
    else
        info "Install tmux later, then re-run: brew install tmux"
    fi
fi

# ── Network check (advisory — warn but don't block) ───────────────────────────
HAS_INTERNET=false
if has_internet; then
    HAS_INTERNET=true
else
    warn "No internet connection detected"
    info "  Some steps (Homebrew installs, model pulls) will be skipped or fail"
    if ! ask "Continue anyway?"; then
        fail "Aborted — connect to the internet and re-run"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 2: TOOL BUNDLES
#  Categorized by role — users pick what's relevant. All free & open source.
# ═══════════════════════════════════════════════════════════════════════════════

step 2 "Tool bundles"

# ── Homebrew install if still missing ─────────────────────────────────────────
if ! $HAS_BREW; then
    warn "Homebrew not found"
    if $HAS_INTERNET; then
        if ask "Install Homebrew? (required for tool installation)"; then
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
                || fail "Homebrew installation failed"
            # Pick up brew in PATH for Apple Silicon or Intel
            if [[ -x /opt/homebrew/bin/brew ]]; then
                eval "$(/opt/homebrew/bin/brew shellenv)"
            elif [[ -x /usr/local/bin/brew ]]; then
                eval "$(/usr/local/bin/brew shellenv)"
            fi
            command -v brew &>/dev/null && HAS_BREW=true && ok "Homebrew installed" \
                || fail "Homebrew installed but 'brew' not in PATH — open a new shell and re-run"
        else
            warn "Skipping tool installation — install Homebrew later and re-run"
        fi
    else
        warn "Skipping Homebrew install — no internet connection"
    fi
fi

# ── Bundle definitions ────────────────────────────────────────────────────────
# Format: "cmd:brew_pkg" — cmd is what we check, brew_pkg is what we install.

BUNDLE_CORE=(
    "tmux:tmux"             # terminal multiplexer (hints pane lives here)
    "zoxide:zoxide"         # smart cd — learns your directories
    "eza:eza"               # modern ls — git status, icons, tree
    "bat:bat"               # modern cat — syntax highlighting
    "fd:fd"                 # modern find — 10x faster, .gitignore aware
    "rg:ripgrep"            # modern grep — 100x faster
    "fzf:fzf"               # fuzzy finder — used everywhere
    "starship:starship"     # cross-shell prompt — git, conda, versions
    "atuin:atuin"           # shell history in SQLite — ranked fuzzy Ctrl+R
    "tldr:tldr"             # community man pages — example-first
)

BUNDLE_GIT=(
    "lazygit:lazygit"       # full git TUI — stage hunks, log, branches
    "delta:git-delta"       # side-by-side diffs with syntax highlighting
    "gh:gh"                 # GitHub CLI — PRs, issues, actions from terminal
    "git-lfs:git-lfs"       # large file storage for git
)

BUNDLE_SYSTEM=(
    "btm:bottom"            # system monitor — CPU, mem, disk, net panels
    "dust:dust"             # visual disk usage tree
    "duf:duf"               # modern df — disk free with colour
    "procs:procs"           # modern ps — searchable, sortable, tree view
    "bandwhich:bandwhich"   # per-process bandwidth monitor
)

BUNDLE_PYTHON=(
    "conda:miniconda"       # package + env manager (cask)
    "jupyter:jupyterlab"    # notebooks in browser
    "black:black"           # Python formatter — opinionated, zero config
    "ruff:ruff"             # Python linter — 100x faster than flake8
    "uv:uv"                 # ultra-fast pip/venv replacement
)

BUNDLE_NETWORK=(
    "http:httpie"           # human-friendly HTTP client (replaces curl)
    "jq:jq"                 # JSON processor — pipe curl output through it
    "yq:yq"                 # YAML/TOML/XML processor (like jq for YAML)
    "mtr:mtr"               # traceroute + ping combined — network debugging
    "wget:wget"             # file downloader (macOS doesn't ship it)
    "nmap:nmap"             # network scanner — port scanning, host discovery
)

BUNDLE_INFRA=(
    "lazydocker:lazydocker" # Docker TUI — containers, images, logs
    "dive:dive"             # explore Docker image layers — find bloat
    "k9s:k9s"               # Kubernetes TUI — pods, logs, exec
    "terraform:terraform"   # infrastructure as code
)

BUNDLE_MACTOOLS=(
    "coreutils:coreutils"   # GNU coreutils (gdate, gstat, gsed, etc.)
    "trash:trash"           # move to Trash instead of rm (safer)
    "watch:watch"           # repeat command every N seconds
    "tree:tree"             # directory tree
    "rename:rename"         # bulk file rename with regex
    "entr:entr"             # run command when files change — live reload
    "hyperfine:hyperfine"   # CLI benchmarking — compare command speeds
    "tokei:tokei"           # count lines of code by language
    "glow:glow"             # render Markdown in terminal
    "mas:mas"               # Mac App Store CLI
)

BUNDLE_DOCS=(
    "pandoc:pandoc"         # universal document converter
    "glow:glow"             # Markdown renderer in terminal
    "pdfgrep:pdfgrep"       # grep through PDF files
)

# ── Bundle selection ──────────────────────────────────────────────────────────
if $HAS_BREW; then
    printf "\n"
    printf "  ${C_BOLD}Select tool bundles to install:${C_RESET}\n\n"
    printf "  ${C_DIM}Each bundle is a curated set of free, open-source tools.${C_RESET}\n"
    printf "  ${C_DIM}Already-installed tools are skipped automatically.${C_RESET}\n\n"

    install_bundle() {
        local bundle_name="$1"
        local bundle_desc="$2"
        shift 2
        local entries=("$@")

        local missing=()
        local present=0
        for entry in "${entries[@]}"; do
            local cmd="${entry%%:*}"
            local pkg="${entry##*:}"
            if command -v "$cmd" &>/dev/null; then
                (( present++ )) || true
            else
                missing+=("$pkg")
            fi
        done

        local total=${#entries[@]}
        if (( ${#missing[@]} == 0 )); then
            ok "${bundle_name}: all $total tools installed"
            return
        fi

        printf "  ${C_YELLOW} ?  ${C_RESET}${C_BOLD}%-18s${C_RESET} %s ${C_DIM}(%d/%d installed, %d to add)${C_RESET}\n" \
            "$bundle_name" "$bundle_desc" "$present" "$total" "${#missing[@]}"

        local missing_names=""
        for pkg in "${missing[@]}"; do
            missing_names+="$pkg "
        done
        printf "  ${C_DIM}      add: %s${C_RESET}\n" "$missing_names"

        if ! $HAS_INTERNET; then
            warn "  Skipping — no internet connection"
            echo ""
            return
        fi

        if ask "Install?"; then
            local brew_pkgs=()
            local cask_pkgs=()
            for pkg in "${missing[@]}"; do
                if [[ "$pkg" == "miniconda" ]]; then
                    cask_pkgs+=("$pkg")
                else
                    brew_pkgs+=("$pkg")
                fi
            done

            if (( ${#brew_pkgs[@]} > 0 )); then
                brew install "${brew_pkgs[@]}" 2>&1 | while IFS= read -r line; do
                    printf "  ${C_DIM}      %s${C_RESET}\n" "$line"
                done
            fi
            if (( ${#cask_pkgs[@]} > 0 )); then
                brew install --cask "${cask_pkgs[@]}" 2>&1 | while IFS= read -r line; do
                    printf "  ${C_DIM}      %s${C_RESET}\n" "$line"
                done
            fi
            ok "${bundle_name}: installed"
        fi
        echo ""
    }

    install_bundle "Core"        "shell essentials"                  "${BUNDLE_CORE[@]}"
    install_bundle "Git & Dev"   "version control power tools"      "${BUNDLE_GIT[@]}"
    install_bundle "System"      "monitoring, disk, processes"       "${BUNDLE_SYSTEM[@]}"
    install_bundle "Python"      "conda, jupyter, linting"          "${BUNDLE_PYTHON[@]}"
    install_bundle "Network"     "HTTP, JSON, DNS, scanning"        "${BUNDLE_NETWORK[@]}"
    install_bundle "Infra"       "Docker, K8s, Terraform"           "${BUNDLE_INFRA[@]}"
    install_bundle "Mac Tools"   "macOS productivity & utilities"   "${BUNDLE_MACTOOLS[@]}"
    install_bundle "Docs"        "Markdown, LaTeX, PDF tools"       "${BUNDLE_DOCS[@]}"

else
    warn "Homebrew not available — skipping tool installation"
    info "Install Homebrew: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 3: AI BACKEND
# ═══════════════════════════════════════════════════════════════════════════════

step 3 "Configuring AI backend"

if [[ "$BACKEND" == "auto" ]]; then
    info "Detecting available backends..."

    # Check Copilot
    if [[ -f "$HOME/Library/Application Support/Code/User/globalStorage/state.vscdb" ]]; then
        if python3 -c "from Crypto.Cipher import AES" 2>/dev/null; then
            BACKEND="copilot"
            ok "GitHub Copilot detected (VS Code + pycryptodome)"
        else
            info "VS Code found but pycryptodome not installed"
            if ask "Install pycryptodome for Copilot backend?"; then
                python3 -m pip install --quiet pycryptodome 2>/dev/null && {
                    BACKEND="copilot"
                    ok "pycryptodome installed — Copilot backend enabled"
                } || {
                    warn "pip install failed — trying next backend"
                }
            fi
        fi
    fi

    # Check Claude API
    if [[ "$BACKEND" == "auto" ]]; then
        HAS_CLAUDE_KEY=false
        if [[ -n "$ANTHROPIC_API_KEY" ]]; then
            HAS_CLAUDE_KEY=true
        elif security find-generic-password -s "anthropic" -a "api_key" -w &>/dev/null 2>&1; then
            HAS_CLAUDE_KEY=true
        fi
        if $HAS_CLAUDE_KEY; then
            BACKEND="claude"
            ok "Anthropic API key found"
        fi
    fi

    # Check Ollama
    if [[ "$BACKEND" == "auto" ]]; then
        if command -v ollama &>/dev/null; then
            BACKEND="ollama"
            ok "Ollama found"
        elif $HAS_BREW && $HAS_INTERNET; then
            if ask "No AI backend found. Install Ollama (local, free, offline)?"; then
                brew install ollama 2>&1 | while IFS= read -r line; do
                    printf "  ${C_DIM}    %s${C_RESET}\n" "$line"
                done
                command -v ollama &>/dev/null && { BACKEND="ollama"; ok "Ollama installed"; } \
                    || warn "Ollama install appeared to succeed but 'ollama' not in PATH — open new shell and re-run"
            fi
        elif $HAS_BREW && ! $HAS_INTERNET; then
            warn "Ollama not found and no internet — skipping install"
        fi
    fi

    if [[ "$BACKEND" == "auto" ]]; then
        BACKEND="none"
        warn "No AI backend configured — rule-based hints only"
        info "Add later: brew install ollama, or set ANTHROPIC_API_KEY"
    fi
fi

ok "Backend: $BACKEND"

# ── Ollama: ensure server is running, then pull model ────────────────────────
OLLAMA_MODEL="qwen3:8b"
if [[ "$BACKEND" == "ollama" ]]; then
    RAM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 8589934592) / 1024 / 1024 / 1024 ))
    if   (( RAM_GB >= 32 )); then RECOMMENDED="qwen3:14b"
    elif (( RAM_GB >= 16 )); then RECOMMENDED="qwen3:8b"
    else                          RECOMMENDED="qwen3:4b"
    fi

    # List already-pulled models so user can see what they have
    PULLED_DISPLAY=""
    if ollama list &>/dev/null 2>&1; then
        PULLED_DISPLAY=$(ollama list 2>/dev/null | awk 'NR>1 {print $1}' | tr '\n' ', ' | sed 's/,$//')
    fi

    # ── Model menu (shared for both choices) ────────────────────────────────
    _print_model_menu() {
        printf "  ${C_DIM}  ── qwen3 (general + thinking) ──${C_RESET}\n"
        printf "      ${C_DIM}1)${C_RESET} qwen3:4b           ${C_DIM}~2.5GB  (fast, 8GB+ RAM)${C_RESET}\n"
        printf "      ${C_DIM}2)${C_RESET} qwen3:8b           ${C_DIM}~5GB   (balanced, 16GB+ RAM)${C_RESET}\n"
        printf "      ${C_DIM}3)${C_RESET} qwen3:14b          ${C_DIM}~9GB   (best qwen3, 32GB+ RAM)${C_RESET}\n"
        printf "  ${C_DIM}  ── deepseek-r1 (reasoning + code) ──${C_RESET}\n"
        printf "      ${C_DIM}4)${C_RESET} deepseek-r1:8b     ${C_DIM}~5GB   (strong reasoning, 16GB+ RAM)${C_RESET}\n"
        printf "      ${C_DIM}5)${C_RESET} deepseek-r1:14b    ${C_DIM}~9GB   (best reasoning, 32GB+ RAM)${C_RESET}\n"
        printf "  ${C_DIM}  ── other ──${C_RESET}\n"
        printf "      ${C_DIM}6)${C_RESET} custom              ${C_DIM}(enter any ollama model name)${C_RESET}\n"
    }

    _resolve_model_choice() {
        local choice="$1" default="$2"
        case "$choice" in
            1) echo "qwen3:4b" ;;
            2) echo "qwen3:8b" ;;
            3) echo "qwen3:14b" ;;
            4) echo "deepseek-r1:8b" ;;
            5) echo "deepseek-r1:14b" ;;
            6)
                printf "  ${C_YELLOW} ?  ${C_RESET}Model name ${C_DIM}(e.g. llama3.3:8b, gemma3:12b)${C_RESET}: "
                read -r CUSTOM_MODEL
                if [[ -n "$CUSTOM_MODEL" ]]; then
                    echo "$CUSTOM_MODEL"
                else
                    info "No input — using default: $default"
                    echo "$default"
                fi
                ;;
            *) echo "$default" ;;
        esac
    }

    echo ""
    printf "  ${C_BOLD}shellbuddy uses two models:${C_RESET}\n"
    printf "  ${C_DIM}  Ambient — small model for the always-on hints pane (with thinking)${C_RESET}\n"
    printf "  ${C_DIM}  /tip    — larger model for on-demand questions (with thinking)${C_RESET}\n"
    echo ""
    info "${RAM_GB}GB RAM detected — recommended: $RECOMMENDED"
    if [[ -n "$PULLED_DISPLAY" ]]; then
        info "already pulled: $PULLED_DISPLAY"
    fi

    # ── Ambient model selection ───────────────────────────────────────────
    if $YES_TO_ALL; then
        HINT_MODEL="qwen3:4b"
        ok "Ambient model: $HINT_MODEL (--yes default)"
    else
        echo ""
        printf "  ${C_BOLD}1/2  Ambient hints model${C_RESET} ${C_DIM}(runs continuously, pick something light)${C_RESET}\n\n"
        _print_model_menu
        echo ""
        printf "  ${C_YELLOW} ?  ${C_RESET}Ambient model ${C_DIM}[1-6, default=1 → qwen3:4b]${C_RESET}: "
        read -r AMBIENT_CHOICE
        HINT_MODEL=$(_resolve_model_choice "$AMBIENT_CHOICE" "qwen3:4b")
        ok "Ambient model: $HINT_MODEL"
    fi

    # ── /tip model selection ──────────────────────────────────────────────
    if $YES_TO_ALL; then
        OLLAMA_MODEL="qwen3:8b"
        ok "/tip model: $OLLAMA_MODEL (--yes default)"
    else
        echo ""
        printf "  ${C_BOLD}2/2  /tip query model${C_RESET} ${C_DIM}(on-demand, can be heavier)${C_RESET}\n\n"
        _print_model_menu
        echo ""
        printf "  ${C_YELLOW} ?  ${C_RESET}/tip model ${C_DIM}[1-6, default=2 → qwen3:8b]${C_RESET}: "
        read -r TIP_CHOICE
        OLLAMA_MODEL=$(_resolve_model_choice "$TIP_CHOICE" "qwen3:8b")
        ok "/tip model: $OLLAMA_MODEL"
    fi

    # Model size estimates for disk check
    _model_size_gb() {
        case "$1" in
            *14b*) echo 9  ;;
            *8b*|*7b*) echo 5  ;;
            *4b*)  echo 3  ;;
            *)     echo 5  ;;
        esac
    }
    HINT_MODEL_GB=$(_model_size_gb "$HINT_MODEL")
    TIP_MODEL_GB=$(_model_size_gb "$OLLAMA_MODEL")

    # Ensure ollama server is running before attempting list/pull
    if ! ollama list &>/dev/null 2>&1; then
        warn "Ollama server is not running"
        if ask "Start ollama server now? (needed to pull/use models)"; then
            ollama serve &>/dev/null &
            OLLAMA_SERVER_PID=$!
            info "Waiting for server to start..."
            local waited=0
            while ! ollama list &>/dev/null 2>&1 && (( waited < 10 )); do
                sleep 1
                (( waited++ )) || true
            done
            if ollama list &>/dev/null 2>&1; then
                ok "Ollama server started (PID $OLLAMA_SERVER_PID)"
                info "To start automatically at login: brew services start ollama"
            else
                warn "Ollama server did not respond in time"
                info "Start it manually:  brew services start ollama"
                info "Then re-run the installer to pull models"
            fi
        else
            warn "Skipping model pull — start ollama with: brew services start ollama"
            info "Then pull manually:  ollama pull $HINT_MODEL && ollama pull $OLLAMA_MODEL"
        fi
    fi

    # Pull models if server is now up
    _pull_model() {
        local model="$1" label="$2" size_gb="$3"
        local PULLED=$(ollama list 2>/dev/null | awk 'NR>1 {print $1}')
        if echo "$PULLED" | grep -q "$model"; then
            ok "$label model $model already available"
            return 0
        fi
        local DISK_FREE_NOW="$(free_disk_gb "$HOME")"
        if (( DISK_FREE_NOW < size_gb + 1 )); then
            warn "Only ${DISK_FREE_NOW}GB free — $model requires ~${size_gb}GB"
            info "Free up space, then run:  ollama pull $model"
        elif ! $HAS_INTERNET; then
            warn "No internet — cannot pull $model"
            info "Pull manually when online:  ollama pull $model"
        elif ask "Pull $model now? (~${size_gb}GB download)"; then
            ollama pull "$model" && ok "$label model ready" \
                || warn "Pull failed — try manually:  ollama pull $model"
        else
            warn "Skipped — pull manually when ready:  ollama pull $model"
        fi
    }

    if ollama list &>/dev/null 2>&1; then
        _pull_model "$HINT_MODEL" "Ambient" "$HINT_MODEL_GB"
        if [[ "$OLLAMA_MODEL" != "$HINT_MODEL" ]]; then
            _pull_model "$OLLAMA_MODEL" "/tip" "$TIP_MODEL_GB"
        fi
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 4: INSTALL SCRIPTS
# ═══════════════════════════════════════════════════════════════════════════════

step 4 "Installing shellbuddy scripts"

# Verify all source files exist before touching the install dir
MISSING_FILES=()
for f in \
    "$REPO_DIR/scripts/hint_daemon.py" \
    "$REPO_DIR/scripts/log_cmd.sh" \
    "$REPO_DIR/scripts/show_hints.sh" \
    "$REPO_DIR/scripts/toggle_hints_pane.sh" \
    "$REPO_DIR/scripts/start_daemon.sh" \
    "$REPO_DIR/scripts/verify.sh"
do
    [[ -f "$f" ]] || MISSING_FILES+=("$f")
done
if (( ${#MISSING_FILES[@]} > 0 )); then
    printf "  ${C_RED} x  ${C_RESET}Missing source files:\n"
    for f in "${MISSING_FILES[@]}"; do
        printf "  ${C_DIM}      %s${C_RESET}\n" "$f"
    done
    fail "Re-clone the repo and re-run"
fi

if ! ls "$REPO_DIR/backends/"*.py &>/dev/null 2>&1; then
    fail "No backend .py files found in $REPO_DIR/backends/ — re-clone the repo and re-run"
fi

mkdir -p "$INSTALL_DIR" || fail "Cannot create install dir $INSTALL_DIR — check permissions"
mkdir -p "$INSTALL_DIR/backends" || fail "Cannot create $INSTALL_DIR/backends — check permissions"

cp "$REPO_DIR/scripts/hint_daemon.py"       "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/log_cmd.sh"           "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/show_hints.sh"        "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/toggle_hints_pane.sh" "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/start_daemon.sh"      "$INSTALL_DIR/"
cp "$REPO_DIR/scripts/verify.sh"            "$INSTALL_DIR/"
cp "$REPO_DIR/backends/"*.py               "$INSTALL_DIR/backends/"

chmod +x "$INSTALL_DIR"/*.sh

# Write config.json with chosen backends/models
CONFIG_JSON="$INSTALL_DIR/config.json"
if [[ "$BACKEND" == "ollama" ]]; then
    cat > "$CONFIG_JSON" <<CFGEOF
{
  "hint_backend": "ollama",
  "hint_model":   "$HINT_MODEL",
  "tip_backend":  "ollama",
  "tip_model":    "$OLLAMA_MODEL",
  "ollama_url":   "http://localhost:11434",

  "_comment": "To use a cloud backend instead of ollama, change hint_backend/tip_backend",
  "_comment2": "and set the matching model. Available backends: ollama, claude, copilot, openai",
  "_examples": {
    "claude":  { "tip_backend": "claude",  "tip_model": "claude-sonnet-4-5-20250514" },
    "copilot": { "tip_backend": "copilot", "tip_model": "gpt-4.1" },
    "openai":  { "tip_backend": "openai",  "tip_model": "gpt-4o-mini", "openai_url": "https://api.openai.com/v1" }
  }
}
CFGEOF
elif [[ "$BACKEND" == "claude" ]]; then
    cat > "$CONFIG_JSON" <<CFGEOF
{
  "hint_backend": "claude",
  "hint_model":   "claude-haiku-4-5-20251001",
  "tip_backend":  "claude",
  "tip_model":    "claude-sonnet-4-5-20250514"
}
CFGEOF
elif [[ "$BACKEND" == "copilot" ]]; then
    cat > "$CONFIG_JSON" <<CFGEOF
{
  "hint_backend": "copilot",
  "hint_model":   "gpt-4.1",
  "tip_backend":  "copilot",
  "tip_model":    "gpt-4.1"
}
CFGEOF
else
    cat > "$CONFIG_JSON" <<CFGEOF
{
  "hint_backend": "ollama",
  "hint_model":   "qwen3:4b",
  "tip_backend":  "ollama",
  "tip_model":    "qwen3:8b"
}
CFGEOF
fi
ok "Config written to $CONFIG_JSON"

ok "Scripts installed"
info "hint_daemon.py, log_cmd.sh, show_hints.sh, toggle_hints_pane.sh"
info "backends/copilot.py, backends/ollama.py, backends/openai_compat.py"

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 5: TMUX CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

step 5 "tmux configuration"

if $SKIP_TMUX; then
    warn "Skipped (--no-tmux)"
elif ! $HAS_TMUX; then
    warn "tmux not installed — skipping config"
    info "Install tmux later: brew install tmux"
elif [[ -f "$TMUX_CONF" ]]; then
    if grep -q "toggle_hints_pane" "$TMUX_CONF" 2>/dev/null; then
        ok "tmux config already has shellbuddy keybinding"
    else
        info "Existing ~/.tmux.conf found"
        if $YES_TO_ALL; then
            TMUX_CHOICE="1"
            info "Appending keybinding (--yes)"
        else
            echo ""
            printf "  ${C_YELLOW} ?  ${C_RESET}How should we handle tmux config?\n"
            printf "      ${C_DIM}1)${C_RESET} Append shellbuddy keybinding to existing config ${C_DIM}(safe)${C_RESET}\n"
            printf "      ${C_DIM}2)${C_RESET} Replace with shellbuddy's full tmux config ${C_DIM}(backup first)${C_RESET}\n"
            printf "      ${C_DIM}3)${C_RESET} Skip — I'll configure tmux myself\n"
            printf "  ${C_YELLOW} ?  ${C_RESET}Choice ${C_DIM}[1/2/3]${C_RESET}: "
            read -r TMUX_CHOICE
        fi
        case "$TMUX_CHOICE" in
            1)
                printf '\n# ── shellbuddy: Ctrl+A H toggles hints pane ──────────────────\n' >> "$TMUX_CONF"
                printf 'bind H run-shell "%s/toggle_hints_pane.sh"\n' "$INSTALL_DIR" >> "$TMUX_CONF"
                ok "Keybinding appended to ~/.tmux.conf"
                ;;
            2)
                backup_file "$TMUX_CONF"
                cp "$REPO_DIR/config/tmux.conf" "$TMUX_CONF"
                ok "tmux config replaced (backup saved)"
                ;;
            *)
                warn "Skipped — add manually:"
                info "  bind H run-shell \"$INSTALL_DIR/toggle_hints_pane.sh\""
                ;;
        esac
    fi
else
    cp "$REPO_DIR/config/tmux.conf" "$TMUX_CONF"
    ok "tmux config installed"
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 6: STARSHIP CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

step 6 "Starship prompt"

if $SKIP_STARSHIP; then
    warn "Skipped (--no-starship)"
elif ! command -v starship &>/dev/null; then
    info "Starship not installed — skipping"
    info "Install later: brew install starship"
elif [[ -f "$STARSHIP_CONF" ]]; then
    if ask "~/.config/starship.toml exists. Replace? (backup first)"; then
        backup_file "$STARSHIP_CONF"
        cp "$REPO_DIR/config/starship.toml" "$STARSHIP_CONF"
        ok "Starship config updated (backup saved)"
    else
        ok "Kept existing starship config"
    fi
else
    mkdir -p "$(dirname "$STARSHIP_CONF")"
    cp "$REPO_DIR/config/starship.toml" "$STARSHIP_CONF"
    ok "Starship config installed"
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 7: SHELL INTEGRATION (.zshrc)
# ═══════════════════════════════════════════════════════════════════════════════

step 7 "Shell integration ($(basename "$ZSHRC"))"

ZSHRC_MARKER="# shellbuddy"
if $SKIP_ZSHRC; then
    warn "Skipped (--no-zshrc)"
    [[ "$CURRENT_SHELL" != "zsh" && "$CURRENT_SHELL" != "bash" ]] && \
        info "Add hooks manually for $CURRENT_SHELL — see config/zshrc_additions.zsh as reference"
elif grep -q "$ZSHRC_MARKER" "$ZSHRC" 2>/dev/null; then
    ok "$(basename "$ZSHRC") already has shellbuddy hooks"
    if ask "Update shellbuddy block in $(basename "$ZSHRC")? (replaces existing block)"; then
        backup_file "$ZSHRC"
        sed -i '' '/# ── shellbuddy/,/^# ── [^s]/{ /# ── [^s]/!d; }' "$ZSHRC" 2>/dev/null || true
        sed -i '' '/# ── shellbuddy/d' "$ZSHRC" 2>/dev/null || true
    else
        ok "Kept existing shellbuddy block"
        SKIP_ZSHRC=true
    fi
fi

if ! $SKIP_ZSHRC && ! grep -q "$ZSHRC_MARKER" "$ZSHRC" 2>/dev/null; then
    if [[ -f "$ZSHRC" ]]; then
        backup_file "$ZSHRC"
    fi
    if ask "Add shellbuddy to ~/${ZSHRC##*/}?"; then
        cat >> "$ZSHRC" << ZSHRC_BLOCK

# ── shellbuddy ────────────────────────────────────────────────────────────────
export SHELLBUDDY_DIR="$INSTALL_DIR"

# Command logger — feeds the hints daemon
function _shellbuddy_log() { SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" zsh "\$SHELLBUDDY_DIR/log_cmd.sh" "\$1" }
autoload -Uz add-zsh-hook
add-zsh-hook preexec _shellbuddy_log

# Auto-start daemon on shell open (idempotent — silent if already running)
(SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" source "\$SHELLBUDDY_DIR/start_daemon.sh" &>/dev/null &)

# sb — main command: starts daemon + toggles hints pane
function sb() {
    local PID_FILE="\$SHELLBUDDY_DIR/daemon.pid"
    local HINTS_FILE="\$SHELLBUDDY_DIR/current_hints.txt"
    local TOGGLE="\$SHELLBUDDY_DIR/toggle_hints_pane.sh"

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
            echo "shellbuddy: failed to start — check: hints-log"
            return 1
        fi
        echo "shellbuddy: started (PID \$pid)"
    fi

    if [[ -n "\$TMUX" ]]; then
        SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" zsh "\$TOGGLE"
        echo "shellbuddy: hints pane toggled (Ctrl+A H to toggle again)"
    else
        echo "shellbuddy: not in tmux — showing hints inline:"
        echo ""
        [[ -f "\$HINTS_FILE" ]] && cat "\$HINTS_FILE" || echo "(no hints yet)"
        echo ""
        echo "tip: run 'tmux new -s dev' then 'sb' for the persistent hints pane"
    fi
}

alias hints-stop='{ [[ -f \$SHELLBUDDY_DIR/daemon.pid ]] && kill \$(cat \$SHELLBUDDY_DIR/daemon.pid) && rm -f \$SHELLBUDDY_DIR/daemon.pid && echo "shellbuddy: stopped"; } 2>/dev/null'
alias hints-log='tail -f \$SHELLBUDDY_DIR/daemon.log'
alias hints-now='[[ -f \$SHELLBUDDY_DIR/current_hints.txt ]] && cat \$SHELLBUDDY_DIR/current_hints.txt || echo "No hints yet"'
alias hints-status='{ [[ -f \$SHELLBUDDY_DIR/daemon.pid ]] && kill -0 \$(cat \$SHELLBUDDY_DIR/daemon.pid) 2>/dev/null && echo "shellbuddy: running (PID \$(cat \$SHELLBUDDY_DIR/daemon.pid))"; } || echo "shellbuddy: stopped"'

# /tip — ask any CLI/terminal question from your prompt
# Usage: /tip how to undo last git commit
# noglob prevents zsh from expanding ? * [ ] in the query before the function sees it
alias /tip='noglob /tip'
function /tip() {
    local query="\$*"

    # ── Helper: read config.json fields ──────────────────────────────
    _sb_cfg() {
        local cfg="\$SHELLBUDDY_DIR/config.json"
        [[ -f "\$cfg" ]] && python3 -c "import json; c=json.load(open('\$cfg')); print(c.get('\$1',''))" 2>/dev/null
    }

    # ── Helper: check daemon is alive ─────────────────────────────────
    _sb_daemon_pid() {
        local PID_FILE="\$SHELLBUDDY_DIR/daemon.pid"
        if [[ -f "\$PID_FILE" ]]; then
            local dpid=\$(cat "\$PID_FILE" 2>/dev/null)
            [[ -n "\$dpid" ]] && kill -0 "\$dpid" 2>/dev/null && echo "\$dpid" && return 0
        fi
        return 1
    }

    # ── /tip status — quick diagnostic ────────────────────────────────
    if [[ "\$query" == "status" ]]; then
        local cfg="\$SHELLBUDDY_DIR/config.json"
        local hints_file="\$SHELLBUDDY_DIR/current_hints.txt"
        local log_file="\$SHELLBUDDY_DIR/daemon.log"
        echo ""
        printf '\033[1;36m  [>_] shellbuddy status\033[0m\n'
        printf '\033[2m  ────────────────────────────────────────\033[0m\n'

        # Daemon
        local dpid=\$(_sb_daemon_pid)
        if [[ -n "\$dpid" ]]; then
            printf '\033[32m  Daemon:       \033[0m running (PID %s)\n' "\$dpid"
        else
            printf '\033[31m  Daemon:       \033[0m not running\n'
        fi

        # Config
        if [[ -f "\$cfg" ]]; then
            printf '\033[36m  Config:       \033[0m %s\n' "\$cfg"
            printf '\033[33m  Hint backend: \033[0m %s / %s\n' "\$(_sb_cfg hint_backend)" "\$(_sb_cfg hint_model)"
            printf '\033[33m  /tip backend: \033[0m %s / %s\n' "\$(_sb_cfg tip_backend)" "\$(_sb_cfg tip_model)"
        else
            printf '\033[31m  Config:       \033[0m not found (using defaults)\n'
        fi

        # Ambient hints file
        if [[ -f "\$hints_file" ]]; then
            local age=\$(( \$(date +%s) - \$(stat -f%m "\$hints_file" 2>/dev/null || echo 0) ))
            if (( age < 60 )); then
                printf '\033[32m  Ambient hints:\033[0m updated %ds ago\n' "\$age"
            elif (( age < 300 )); then
                printf '\033[33m  Ambient hints:\033[0m updated %ds ago (may be stale)\n' "\$age"
            else
                printf '\033[31m  Ambient hints:\033[0m last updated %ds ago (stale)\n' "\$age"
            fi
            printf '\033[2m  ·\033[0m\n'
            while IFS= read -r line; do
                [[ -n "\$line" ]] && printf '\033[2m  %s\033[0m\n' "\$line"
            done < "\$hints_file"
        else
            printf '\033[31m  Ambient hints:\033[0m no hints file yet (run a few commands)\n'
        fi

        # Command log
        local cmd_log="\$SHELLBUDDY_DIR/cmd_log.jsonl"
        if [[ -f "\$cmd_log" ]]; then
            local n_cmds=\$(wc -l < "\$cmd_log" | tr -d ' ')
            printf '\033[36m  Command log:  \033[0m %s commands logged\n' "\$n_cmds"
        else
            printf '\033[31m  Command log:  \033[0m empty (log_cmd.sh not hooked?)\n'
        fi

        # Last few daemon log lines
        if [[ -f "\$log_file" ]]; then
            printf '\033[2m  ·\033[0m\n'
            printf '\033[36m  Recent daemon log:\033[0m\n'
            tail -5 "\$log_file" | while IFS= read -r line; do
                printf '\033[2m    %s\033[0m\n' "\$line"
            done
        fi
        echo ""
        return 0
    fi

    # ── /tip test — force a hint generation and display result ────────
    if [[ "\$query" == "test" ]]; then
        echo ""
        printf '\033[1;36m  [>_] shellbuddy ambient test\033[0m\n'
        printf '\033[2m  ────────────────────────────────────────\033[0m\n'

        # Check daemon
        local dpid=\$(_sb_daemon_pid)
        if [[ -z "\$dpid" ]]; then
            printf '\033[33m  Daemon not running — starting...\033[0m\n'
            SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" source "\$SHELLBUDDY_DIR/start_daemon.sh"
            sleep 2
            dpid=\$(_sb_daemon_pid)
            if [[ -z "\$dpid" ]]; then
                printf '\033[31m  Failed to start daemon — check: hints-log\033[0m\n'
                return 1
            fi
            printf '\033[32m  Daemon started (PID %s)\033[0m\n' "\$dpid"
        else
            printf '\033[32m  Daemon running (PID %s)\033[0m\n' "\$dpid"
        fi

        # Log a test command so the daemon has something to process
        local cmd_log="\$SHELLBUDDY_DIR/cmd_log.jsonl"
        local ts=\$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        echo "{\"ts\":\"\$ts\",\"cmd\":\"echo shellbuddy test\",\"cwd\":\"\$PWD\"}" >> "\$cmd_log"
        echo "{\"ts\":\"\$ts\",\"cmd\":\"ls -la\",\"cwd\":\"\$PWD\"}" >> "\$cmd_log"
        printf '\033[2m  Logged test commands\033[0m\n'

        # Wait for hints file to update
        local hints_file="\$SHELLBUDDY_DIR/current_hints.txt"
        local before_mtime=0
        [[ -f "\$hints_file" ]] && before_mtime=\$(stat -f%m "\$hints_file" 2>/dev/null || echo 0)

        printf '\033[36m  Waiting for ambient hints'
        local waited=0
        while (( waited < 60 )); do
            sleep 1
            waited=\$((waited + 1))
            if [[ -f "\$hints_file" ]]; then
                local now_mtime=\$(stat -f%m "\$hints_file" 2>/dev/null || echo 0)
                if (( now_mtime > before_mtime )); then
                    break
                fi
            fi
            (( waited % 5 == 0 )) && printf '.'
        done
        printf '\033[0m\n'

        if [[ -f "\$hints_file" ]]; then
            local now_mtime=\$(stat -f%m "\$hints_file" 2>/dev/null || echo 0)
            if (( now_mtime > before_mtime )); then
                printf '\033[32m  Ambient hints updated!\033[0m\n\n'
                while IFS= read -r line; do
                    if [[ "\$line" == HINTS* ]]; then
                        printf '\033[1;36m  %s\033[0m\n' "\$line"
                    elif [[ "\$line" == ─* ]]; then
                        printf '\033[2m  %s\033[0m\n' "\$line"
                    elif [[ "\$line" == \[*x\]* ]]; then
                        printf '\033[33m  %s\033[0m\n' "\$line"
                    elif [[ "\$line" == thinking* ]]; then
                        printf '\033[2;36m  %s\033[0m\n' "\$line"
                    elif [[ -n "\$line" ]]; then
                        printf '\033[32m  %s\033[0m\n' "\$line"
                    fi
                done < "\$hints_file"
            else
                printf '\033[31m  Hints file not updated in 60s\033[0m\n'
                printf '\033[2m  Check daemon log: hints-log\033[0m\n'
            fi
        else
            printf '\033[31m  No hints file created\033[0m\n'
            printf '\033[2m  Check daemon log: hints-log\033[0m\n'
        fi
        echo ""
        return 0
    fi

    # ── Help ──────────────────────────────────────────────────────────
    if [[ "\$query" == "help" || "\$query" == "-h" || "\$query" == "--help" || "\$query" == "h" || -z "\$query" ]]; then
        local cfg="\$SHELLBUDDY_DIR/config.json"
        echo ""
        printf '\033[1;36m  [>_] shellbuddy /tip\033[0m\n'
        printf '\033[2m  ────────────────────────────────────────\033[0m\n'
        printf '\033[36m  Usage:\033[0m  /tip <question>\n'
        printf '\033[36m  Examples:\033[0m\n'
        printf '\033[2m    /tip how to undo last git commit\033[0m\n'
        printf '\033[2m    /tip find large files in current dir\033[0m\n'
        printf '\033[2m    /tip diff two branches in git\033[0m\n'
        echo ""

        # Show current config
        if [[ -f "\$cfg" ]]; then
            printf '\033[36m  Current config:\033[0m  %s\n' "\$cfg"
            printf '\033[33m    Ambient hints:\033[0m  %s / %s\n' "\$(_sb_cfg hint_backend)" "\$(_sb_cfg hint_model)"
            printf '\033[33m    /tip queries: \033[0m  %s / %s\n' "\$(_sb_cfg tip_backend)" "\$(_sb_cfg tip_model)"
        else
            printf '\033[33m  Config:\033[0m  %s (not found — using defaults)\n' "\$cfg"
            printf '\033[2m    defaults: ollama / qwen3:4b (hints), ollama / qwen3:8b (/tip)\033[0m\n'
        fi

        # Daemon status
        local dpid=\$(_sb_daemon_pid)
        if [[ -n "\$dpid" ]]; then
            printf '\033[32m  Daemon:\033[0m  running (PID %s)\n' "\$dpid"
        else
            printf '\033[31m  Daemon:\033[0m  not running\n'
        fi
        echo ""

        printf '\033[36m  Subcommands:\033[0m\n'
        printf '\033[2m    /tip status     full diagnostic (daemon, config, hints, logs)\033[0m\n'
        printf '\033[2m    /tip test       force ambient hint generation and show result\033[0m\n'
        printf '\033[2m    /tip help       this help\033[0m\n'
        echo ""
        printf '\033[36m  Configure models:\033[0m\n'
        printf '\033[2m    Edit %s\033[0m\n' "\$cfg"
        printf '\033[2m    Available backends: ollama, claude, copilot, openai\033[0m\n'
        printf '\033[2m    Then restart daemon: hints-stop && sb\033[0m\n'
        echo ""
        printf '\033[36m  Cloud backend setup:\033[0m\n'
        printf '\033[2m    Claude:   export ANTHROPIC_API_KEY=sk-...  (in .zshrc)\033[0m\n'
        printf '\033[2m    OpenAI:   export OPENAI_API_KEY=sk-...     (in .zshrc)\033[0m\n'
        printf '\033[2m    Copilot:  sign into VS Code with Copilot subscription\033[0m\n'
        printf '\033[2m    Groq:     export OPENAI_API_KEY=gsk-...    + openai_url in config\033[0m\n'
        echo ""
        printf '\033[36m  Other commands:\033[0m\n'
        printf '\033[2m    sb             toggle hints pane\033[0m\n'
        printf '\033[2m    hints-stop     stop daemon\033[0m\n'
        printf '\033[2m    hints-log      tail daemon logs\033[0m\n'
        printf '\033[2m    hints-status   check daemon status\033[0m\n'
        echo ""
        return 0
    fi

    local PID_FILE="\$SHELLBUDDY_DIR/daemon.pid"
    local QUERY_FILE="\$SHELLBUDDY_DIR/tip_query.txt"
    local RESULT_FILE="\$SHELLBUDDY_DIR/tip_result.txt"

    # Verify daemon is running — start it if not
    local daemon_ok=false
    if [[ -f "\$PID_FILE" ]]; then
        local dpid=\$(cat "\$PID_FILE" 2>/dev/null)
        [[ -n "\$dpid" ]] && kill -0 "\$dpid" 2>/dev/null && daemon_ok=true
    fi
    if ! \$daemon_ok; then
        printf '\033[33m  [>_] daemon not running — starting...\033[0m\n'
        SHELLBUDDY_DIR="\$SHELLBUDDY_DIR" source "\$SHELLBUDDY_DIR/start_daemon.sh"
        sleep 1
        if [[ -f "\$PID_FILE" ]]; then
            local dpid=\$(cat "\$PID_FILE" 2>/dev/null)
            if [[ -n "\$dpid" ]] && kill -0 "\$dpid" 2>/dev/null; then
                daemon_ok=true
            fi
        fi
        if ! \$daemon_ok; then
            printf '\033[31m  [>_] failed to start daemon — check: hints-log\033[0m\n'
            return 1
        fi
    fi

    # Clean any stale result, write query
    rm -f "\$RESULT_FILE" "\${RESULT_FILE}.tmp"
    echo "\$query" > "\$QUERY_FILE"
    printf '\033[36m  [>_] thinking...\033[0m'

    # Wait up to 120s for the result file (cold model load can be slow)
    local waited=0
    while [[ ! -f "\$RESULT_FILE" ]] && (( waited < 240 )); do
        sleep 0.5
        waited=\$((waited + 1))
        # Show dots every 5 seconds so user knows it's alive
        if (( waited % 10 == 0 )); then
            printf '.'
        fi
    done
    printf '\r\033[K'

    if [[ -f "\$RESULT_FILE" ]]; then
        echo ""
        printf '\033[1;36m  [>_] /tip\033[0m \033[2m%s\033[0m\n' "\$query"
        printf '\033[2m  ────────────────────────────────────────\033[0m\n'
        while IFS= read -r line; do
            printf '\033[32m  %s\033[0m\n' "\$line"
        done < "\$RESULT_FILE"
        echo ""
        rm -f "\$RESULT_FILE"
    else
        printf '\033[31m  [>_] timeout — model may still be loading\033[0m\n'
        printf '\033[2m  check: hints-log  |  retry: /tip %s\033[0m\n' "\$query"
    fi
}
ZSHRC_BLOCK
        ok "$(basename "$ZSHRC") updated with shellbuddy hooks"
    else
        warn "Skipped — add hooks manually (see config/zshrc_additions.zsh)"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 8: VERIFICATION
# ═══════════════════════════════════════════════════════════════════════════════

step 8 "Verifying installation"

VERIFY_PASS=0
VERIFY_FAIL=0

_check() {
    if eval "$2" &>/dev/null 2>&1; then
        ok "$1"
        (( VERIFY_PASS++ )) || true
    else
        warn "$1"
        (( VERIFY_FAIL++ )) || true
    fi
}

_check "Scripts installed"            "[[ -f '$INSTALL_DIR/hint_daemon.py' ]]"
_check "Config file"                 "[[ -f '$INSTALL_DIR/config.json' ]]"
_check "Backends installed"           "[[ -f '$INSTALL_DIR/backends/copilot.py' ]]"
_check "log_cmd.sh executable"        "[[ -x '$INSTALL_DIR/log_cmd.sh' ]]"
_check "show_hints.sh executable"     "[[ -x '$INSTALL_DIR/show_hints.sh' ]]"
_check "toggle_hints_pane executable" "[[ -x '$INSTALL_DIR/toggle_hints_pane.sh' ]]"
_check "start_daemon.sh executable"   "[[ -x '$INSTALL_DIR/start_daemon.sh' ]]"
_check "Python can run daemon"        "python3 -c 'import sys; sys.path.insert(0,\"$INSTALL_DIR\"); exec(open(\"$INSTALL_DIR/hint_daemon.py\").read().split(\"def run\")[0])'"
_check "Data dir writable"            "[[ -w '$INSTALL_DIR' ]]"

if ! $SKIP_ZSHRC && [[ -f "$ZSHRC" ]]; then
    _check "shellbuddy in $(basename "$ZSHRC")" "grep -q 'shellbuddy' '$ZSHRC'"
    _check "/tip function in $(basename "$ZSHRC")" "grep -q '/tip' '$ZSHRC'"
fi

if $HAS_TMUX; then
    _check "tmux available" "command -v tmux"
    if [[ -f "$TMUX_CONF" ]]; then
        _check "Hints keybinding in tmux.conf" "grep -q 'toggle_hints_pane\|shellbuddy' '$TMUX_CONF'"
    fi
fi

case "$BACKEND" in
    copilot) _check "pycryptodome available" "python3 -c 'from Crypto.Cipher import AES'" ;;
    claude)  _check "Anthropic API key"      "[[ -n \"\$ANTHROPIC_API_KEY\" ]] || security find-generic-password -s anthropic -a api_key -w" ;;
    ollama)  _check "Ollama binary"          "command -v ollama"
             _check "Ollama server responds" "ollama list" ;;
esac

printf "\n"
if (( VERIFY_FAIL == 0 )); then
    ok "Verification: all $VERIFY_PASS checks passed"
else
    warn "Verification: $VERIFY_PASS passed, $VERIFY_FAIL warnings — review items above"
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  DONE
# ═══════════════════════════════════════════════════════════════════════════════

printf "\n"
printf "  ${C_CYAN}${C_BOLD}"
cat << 'DONE_BANNER'
   ┌─────────────────────────────────────────┐
   │                                         │
   │   [>_] shellbuddy installed             │
   │                                         │
   └─────────────────────────────────────────┘
DONE_BANNER
printf "${C_RESET}"

ok "Location: $INSTALL_DIR"
ok "Backend:  $BACKEND"
if [[ "$BACKEND" == "ollama" ]]; then
    ok "Ambient:  $HINT_MODEL  |  /tip: $OLLAMA_MODEL"
fi
if [[ -d "$BACKUP_DIR" ]]; then
    ok "Backups:  $BACKUP_DIR"
fi

printf "\n"
printf "  ${C_BOLD}Next steps:${C_RESET}\n\n"

printf "  Run these commands now:\n\n"

STEP_N=1
printf "  ${C_CYAN}%d.${C_RESET} ${C_BOLD}source %s${C_RESET}\n" $STEP_N "$ZSHRC"
(( STEP_N++ )) || true

if [[ "$BACKEND" == "ollama" ]]; then
    printf "  ${C_CYAN}%d.${C_RESET} ${C_BOLD}brew services start ollama${C_RESET}\n" $STEP_N
    (( STEP_N++ )) || true
fi

printf "  ${C_CYAN}%d.${C_RESET} ${C_BOLD}tmux new -s dev${C_RESET}\n" $STEP_N
(( STEP_N++ )) || true

printf "  ${C_CYAN}%d.${C_RESET} ${C_BOLD}sb${C_RESET}  ${C_DIM}(or Ctrl+A H inside tmux)${C_RESET}\n" $STEP_N

printf "\n"
printf "  ${C_BOLD}Commands:${C_RESET}\n\n"
printf "  ${C_CYAN}sb${C_RESET}               start daemon + toggle hints pane\n"
printf "  ${C_CYAN}/tip${C_RESET} <question>  ask any CLI question\n"
printf "  ${C_CYAN}hints-stop${C_RESET}       stop the daemon\n"
printf "  ${C_CYAN}hints-log${C_RESET}        tail daemon logs\n"
printf "  ${C_CYAN}hints-status${C_RESET}     check daemon status\n"
printf "\n"
printf "  ${C_BOLD}Want to use a cloud AI backend?${C_RESET}\n"
printf "  ${C_DIM}Edit ${C_RESET}${C_CYAN}$INSTALL_DIR/config.json${C_RESET}${C_DIM} and set hint_backend/tip_backend:${C_RESET}\n\n"
printf "  ${C_DIM}Claude:  set ANTHROPIC_API_KEY in .zshrc, backend=\"claude\", model=\"claude-sonnet-4-5-20250514\"${C_RESET}\n"
printf "  ${C_DIM}Copilot: just sign into VS Code with Copilot, backend=\"copilot\", model=\"gpt-4.1\"${C_RESET}\n"
printf "  ${C_DIM}OpenAI:  set OPENAI_API_KEY in .zshrc, backend=\"openai\", model=\"gpt-4o-mini\"${C_RESET}\n"
printf "  ${C_DIM}Groq:    set OPENAI_API_KEY, backend=\"openai\", openai_url=\"https://api.groq.com/openai/v1\"${C_RESET}\n"
printf "  ${C_DIM}You can mix backends — e.g. ollama for hints, claude for /tip${C_RESET}\n"
printf "\n"
printf "  ${C_DIM}Run full verification anytime: zsh $INSTALL_DIR/verify.sh${C_RESET}\n"
printf "\n"
