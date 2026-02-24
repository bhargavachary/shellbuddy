# shellbuddy — zshrc_additions.zsh
# Copy this block into your ~/.zshrc (or source this file from it).
# All sections are independently useful — adopt as many or few as you want.
#
# ORDER MATTERS in some sections (noted inline).

# ══════════════════════════════════════════════════════════════════════════════
# HISTORY
# ══════════════════════════════════════════════════════════════════════════════
HISTFILE="$HOME/.zsh_history"
HISTSIZE=100000
SAVEHIST=100000
setopt SHARE_HISTORY        # sync history across all open terminals instantly
setopt HIST_IGNORE_DUPS     # skip consecutive duplicates
setopt HIST_IGNORE_SPACE    # prefix a command with space → not saved to history
setopt HIST_REDUCE_BLANKS
setopt HIST_VERIFY          # show expanded history substitution before running

# ══════════════════════════════════════════════════════════════════════════════
# SHELL BEHAVIOUR
# ══════════════════════════════════════════════════════════════════════════════
setopt AUTO_CD              # typing a directory name alone cds into it
setopt EXTENDED_GLOB        # enables ^pat, pat#, pat~ etc.
setopt CORRECT              # suggest corrections for mistyped commands
setopt CORRECT_ALL          # correct arguments too, not just the command
setopt PUSHD_IGNORE_DUPS    # don't push duplicate dirs onto the stack
setopt NO_BEEP

# ══════════════════════════════════════════════════════════════════════════════
# COMPLETION
# ══════════════════════════════════════════════════════════════════════════════
autoload -Uz compinit && compinit
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-zA-Z}={A-Za-z}'  # case-insensitive tab complete
zstyle ':completion:*' list-colors ''

# ══════════════════════════════════════════════════════════════════════════════
# VI MODE
# ══════════════════════════════════════════════════════════════════════════════
bindkey -v
KEYTIMEOUT=1   # 10ms: snappy Esc for mode switch (default 40ms feels sluggish)

# Edit current command in vim (Ctrl+E any mode, v in normal mode)
autoload -z edit-command-line
zle -N edit-command-line
bindkey -M vicmd 'v' edit-command-line
bindkey '^E' edit-command-line

# Preserve familiar readline bindings in insert mode
bindkey -M viins '^P' up-history         # Ctrl+P — history up
bindkey -M viins '^N' down-history       # Ctrl+N — history down
bindkey -M viins '^W' backward-kill-word # Ctrl+W — delete word back
bindkey -M viins '^H' backward-delete-char
bindkey -M viins '^A' beginning-of-line
bindkey -M viins '^E' end-of-line

# Esc+Esc in insert mode — run thefuck to fix last command
# (requires thefuck: brew install thefuck)
function _run_thefuck { eval "$(thefuck --alias fuck)"; fuck }
bindkey -M viins '\e\e' _run_thefuck 2>/dev/null || true

# Vi mode indicator: [N] in red shows when in normal mode
function zle-line-init zle-keymap-select {
    case $KEYMAP in
        vicmd)      VI_MODE="%F{red}[N]%f " ;;
        viins|main) VI_MODE="" ;;
    esac
    zle reset-prompt
}
zle -N zle-line-init
zle -N zle-keymap-select

# ══════════════════════════════════════════════════════════════════════════════
# PROMPT — starship
# Install: brew install starship  |  config: ~/.config/starship.toml
# The VI_MODE variable above prepends [N] to the starship prompt in normal mode.
# ══════════════════════════════════════════════════════════════════════════════
eval "$(starship init zsh)"
PROMPT='${VI_MODE}'"$PROMPT"

# ══════════════════════════════════════════════════════════════════════════════
# MODERN COMMAND REPLACEMENTS
# Having these as aliases means:
#  - shellbuddy hints tell you to switch
#  - once you do, the new command is immediately available
#  - you can still type the old command name if you want
# ══════════════════════════════════════════════════════════════════════════════
alias ls='eza --icons'
alias ll='eza -la --icons --git --time-style=relative'
alias lt='eza --tree --level=2 --icons'
alias cat='bat --style=plain --paging=never'
alias less='bat --style=full'
alias grep='rg'
alias find='fd'
alias du='dust'
alias top='btm'
alias htop='btm'

# ══════════════════════════════════════════════════════════════════════════════
# GIT SHORTCUTS
# ══════════════════════════════════════════════════════════════════════════════
alias g='git'
alias gs='git status -sb'
alias gd='git diff'
alias ga='git add'
alias gc='git commit'
alias gp='git push'
alias gl='git log --oneline --graph --decorate -20'
alias lg='lazygit'

# ══════════════════════════════════════════════════════════════════════════════
# DIRECTORY / NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'
alias cls='clear'

# ══════════════════════════════════════════════════════════════════════════════
# ZOXIDE — smart cd
# Must come AFTER any existing cd aliases.
# z <query>  → jump to best matching frecent directory
# zi         → interactive picker (requires fzf)
# ══════════════════════════════════════════════════════════════════════════════
eval "$(zoxide init zsh --cmd cd)"   # replaces cd transparently

# ══════════════════════════════════════════════════════════════════════════════
# ATUIN — smart history
# Ctrl+R now shows ranked, fuzzy, deduped history via atuin.
# --disable-up-arrow keeps arrow keys for normal history navigation.
# Must come AFTER fzf sourcing so atuin wins the Ctrl+R binding.
# ══════════════════════════════════════════════════════════════════════════════
eval "$(atuin init zsh --disable-up-arrow)"

# ══════════════════════════════════════════════════════════════════════════════
# FZF — fuzzy finder
# Ctrl+T = file picker, Alt+C = directory picker, Ctrl+R = history (atuin override)
# ══════════════════════════════════════════════════════════════════════════════
export FZF_DEFAULT_COMMAND='fd --type f --hidden --follow --exclude .git'
export FZF_DEFAULT_OPTS='--height=40% --layout=reverse --border --info=inline'
export FZF_CTRL_T_COMMAND="$FZF_DEFAULT_COMMAND"
export FZF_ALT_C_COMMAND='fd --type d --hidden --follow --exclude .git'
[ -f ~/.fzf.zsh ] && source ~/.fzf.zsh

# ══════════════════════════════════════════════════════════════════════════════
# THEFUCK
# eval the alias; Esc+Esc binding above calls it via the zle function
# ══════════════════════════════════════════════════════════════════════════════
eval "$(thefuck --alias)"

# ══════════════════════════════════════════════════════════════════════════════
# SHELLBUDDY — hints daemon
# ══════════════════════════════════════════════════════════════════════════════
export SHELLBUDDY_DIR="${SHELLBUDDY_DIR:-$HOME/.shellbuddy}"

# Log every command (preexec fires before the command runs)
function _shellbuddy_log() { SHELLBUDDY_DIR="$SHELLBUDDY_DIR" zsh "$SHELLBUDDY_DIR/log_cmd.sh" "$1" }
autoload -Uz add-zsh-hook
add-zsh-hook preexec _shellbuddy_log

# Start daemon on shell open (idempotent — silent if already running)
(SHELLBUDDY_DIR="$SHELLBUDDY_DIR" source "$SHELLBUDDY_DIR/start_daemon.sh" &>/dev/null &)

# sb — start daemon + toggle hints pane
function sb() {
    local PID_FILE="$SHELLBUDDY_DIR/daemon.pid"
    local HINTS_FILE="$SHELLBUDDY_DIR/current_hints.txt"
    local TOGGLE="$SHELLBUDDY_DIR/toggle_hints_pane.sh"

    local pid="" already_running=false
    if [[ -f "$PID_FILE" ]]; then
        pid=$(cat "$PID_FILE" 2>/dev/null)
        [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && already_running=true
    fi

    if $already_running; then
        echo "shellbuddy: active (PID $pid)"
    else
        echo "shellbuddy: starting daemon..."
        SHELLBUDDY_DIR="$SHELLBUDDY_DIR" source "$SHELLBUDDY_DIR/start_daemon.sh"
        sleep 0.8
        pid=$(cat "$PID_FILE" 2>/dev/null)
        if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
            echo "shellbuddy: failed to start — check: hints-log"
            return 1
        fi
        echo "shellbuddy: started (PID $pid)"
    fi

    if [[ -n "$TMUX" ]]; then
        SHELLBUDDY_DIR="$SHELLBUDDY_DIR" zsh "$TOGGLE"
        echo "shellbuddy: hints pane toggled (Ctrl+A H to toggle again)"
    else
        echo "shellbuddy: not in tmux — showing hints inline:"
        echo ""
        [[ -f "$HINTS_FILE" ]] && cat "$HINTS_FILE" || echo "(no hints yet)"
        echo ""
        echo "tip: run 'tmux new -s dev' then 'sb' for the persistent hints pane"
    fi
}

alias shellbuddy='sb'

alias hints-stop='{ [[ -f $SHELLBUDDY_DIR/daemon.pid ]] && kill $(cat $SHELLBUDDY_DIR/daemon.pid) && rm -f $SHELLBUDDY_DIR/daemon.pid && echo "shellbuddy: stopped"; } 2>/dev/null'
alias hints-log='tail -f $SHELLBUDDY_DIR/daemon.log'
alias hints-now='[[ -f $SHELLBUDDY_DIR/current_hints.txt ]] && cat $SHELLBUDDY_DIR/current_hints.txt || echo "No hints yet"'
alias hints-status='{ [[ -f $SHELLBUDDY_DIR/daemon.pid ]] && kill -0 $(cat $SHELLBUDDY_DIR/daemon.pid) 2>/dev/null && echo "shellbuddy: running (PID $(cat $SHELLBUDDY_DIR/daemon.pid))"; } || echo "shellbuddy: stopped"'

# /tip — ask any CLI/terminal question, get instant answer from AI
# Usage: /tip how to undo last git commit
#        /tip tar extract .gz file
#        /tip set default editor to vim
function /tip() {
    local query="$*"
    if [[ -z "$query" ]]; then
        printf '\033[36m  usage: /tip <question>\033[0m\n'
        printf '\033[2m  e.g.  /tip how to undo last git commit\033[0m\n'
        return 1
    fi
    local QUERY_FILE="$SHELLBUDDY_DIR/tip_query.txt"
    local RESULT_FILE="$SHELLBUDDY_DIR/tip_result.txt"

    # Write query for the daemon to pick up
    echo "$query" > "$QUERY_FILE"

    # Wait for result (daemon polls every 3s, but tip is handled on every cycle)
    printf '\033[36m  [>_] thinking...\033[0m'
    local waited=0
    while [[ -f "$QUERY_FILE" ]] && (( waited < 30 )); do
        sleep 0.5
        waited=$((waited + 1))
    done
    printf '\r\033[K'

    if [[ -f "$RESULT_FILE" ]]; then
        echo ""
        printf '\033[1;36m  [>_] /tip\033[0m \033[2m%s\033[0m\n' "$query"
        printf '\033[2m  ────────────────────────────────────────\033[0m\n'
        while IFS= read -r line; do
            printf '\033[32m  %s\033[0m\n' "$line"
        done < "$RESULT_FILE"
        echo ""
        rm -f "$RESULT_FILE"
    else
        echo "  [timeout — daemon may not be running. Try: hints-start]"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# EDITOR
# ══════════════════════════════════════════════════════════════════════════════
export EDITOR='vim'
export VISUAL='vim'

# ══════════════════════════════════════════════════════════════════════════════
# FILE DESCRIPTOR LIMIT
# Node.js and Python file watchers can hit the default limit (256 on macOS).
# ══════════════════════════════════════════════════════════════════════════════
ulimit -n 65536 2>/dev/null || true
