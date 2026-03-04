#!/usr/bin/env zsh
# shellbuddy — bootstrap installer
#
# One-liner install (no Homebrew required):
#   curl -fsSL https://raw.githubusercontent.com/bhargavachary/shellbuddy/main/scripts/bootstrap.sh | zsh
#
# Or with flags passed through to install.sh:
#   curl -fsSL .../bootstrap.sh | zsh -s -- --yes --backend ollama
#
# What this does:
#   1. Checks prerequisites (git, zsh)
#   2. If Homebrew is present, hints at `brew install shellbuddy` (cleaner)
#   3. Clones shellbuddy to a temp dir (shallow clone for speed)
#   4. Executes install.sh from the cloned repo, forwarding all args

set -euo pipefail

# ── Colours ───────────────────────────────────────────────────────────────────
C_CYAN='\033[1;36m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_RED='\033[0;31m'
C_BOLD='\033[1m'
C_DIM='\033[2m'
C_RESET='\033[0m'

info()  { printf "  ${C_CYAN}->  ${C_RESET}%s\n" "$*" }
ok()    { printf "  ${C_GREEN} +  ${C_RESET}%s\n" "$*" }
warn()  { printf "  ${C_YELLOW} !  ${C_RESET}%s\n" "$*" }
fail()  { printf "  ${C_RED} x  ${C_RESET}%s\n" "$*"; exit 1 }

# ── Banner ────────────────────────────────────────────────────────────────────
printf "\n"
printf "  ${C_CYAN}${C_BOLD}"
cat <<'BANNER'
   ◆ shellbuddy bootstrap
   ─────────────────────────────────────────
     AI-powered ambient hints for your shell
BANNER
printf "${C_RESET}\n"

# ── macOS check ───────────────────────────────────────────────────────────────
if [[ "$(uname -s)" != "Darwin" ]]; then
    warn "Non-macOS detected ($(uname -s))"
    warn "shellbuddy is macOS-focused — some features may not work"
fi

# ── zsh check ─────────────────────────────────────────────────────────────────
# We're already running in zsh (shebang), so this is mainly informational
ok "zsh $(zsh --version 2>/dev/null | awk '{print $2}')"

# ── git check ─────────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    fail "git not found — install Xcode Command Line Tools first:\n     xcode-select --install"
fi
ok "git $(git --version 2>/dev/null | awk '{print $3}')"

# ── Homebrew shortcut hint ─────────────────────────────────────────────────────
if command -v brew &>/dev/null; then
    printf "\n"
    printf "  ${C_GREEN} +  Homebrew is available${C_RESET}\n"
    printf "  ${C_DIM}     For the cleanest install with auto-updates via \`brew upgrade\`:${C_RESET}\n"
    printf "\n"
    printf "         brew tap bhargavachary/shellbuddy\n"
    printf "         brew install shellbuddy\n"
    printf "         shellbuddy   # run the setup wizard\n"
    printf "\n"
    printf "  ${C_CYAN}->  Continuing with direct install (works fine too)...${C_RESET}\n\n"
fi

# ── Clone to temp dir ─────────────────────────────────────────────────────────
REPO_URL="https://github.com/bhargavachary/shellbuddy.git"
CLONE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/shellbuddy-bootstrap.XXXXXX")"

# Cleanup on exit (success or failure)
trap 'rm -rf "$CLONE_DIR"' EXIT

info "Cloning shellbuddy (shallow)..."
git clone --depth=1 --quiet "$REPO_URL" "$CLONE_DIR/shellbuddy" \
    || fail "Clone failed — check your internet connection and try again"
ok "Cloned to $CLONE_DIR/shellbuddy"

# ── Run install.sh (forward all args) ────────────────────────────────────────
printf "\n"
info "Launching shellbuddy installer...\n"

cd "$CLONE_DIR/shellbuddy"
exec zsh install.sh "$@"
