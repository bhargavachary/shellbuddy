# shellbuddy — Usage Guide

## What it does

A persistent strip at the top of your tmux session shows contextual hints as you work:

```
HINTS  ~/projects/myapp  [14:32:07]  (12 cmds)
──────────────────────────────────────────────────────────
[5x] cd → z myapp  (zoxide: learns your paths)
[3x] ls → eza -la --git --icons
·
thinking ...
```

Once the AI finishes reasoning:

```
HINTS  ~/projects/myapp  [14:32:12]  (12 cmds)
──────────────────────────────────────────────────────────
[5x] cd → z myapp  (zoxide: learns your paths)
[3x] ls → eza -la --git --icons
·
Python project — try: fd -e py | xargs rg 'def '
conda env not active — run: conda activate myenv
```

- **Yellow hints** — instant regex pattern matching, zero latency, no AI
- **Green hints** — local LLM reads your last 10 commands + current directory, thinks about your workflow, gives situation-specific advice
- **`[3x]` counter** — how many times you've used the suboptimal command this session
- **`thinking ...`** — shown while the AI model reasons (stripped from final output)


## Commands

| Command | What it does |
|---------|-------------|
| `sb` | Start daemon + toggle hints pane in tmux |
| `/tip <question>` | Ask any CLI/terminal question |
| `/tip help` | Show help, config, daemon status |
| `/tip status` | Full diagnostic (config, backends, hints age, logs) |
| `/tip test` | Force ambient hint generation and show result |
| `hints-stop` | Stop the daemon |
| `hints-log` | Tail daemon logs |
| `hints-status` | Check if daemon is running |
| `Ctrl+A H` | Toggle hints pane in tmux (if tmux.conf installed) |


## /tip — on-demand CLI help

Ask any terminal question without leaving your shell:

```bash
/tip how to undo last git commit
/tip find files larger than 100mb
/tip tar extract .tar.gz to specific dir
/tip ssh tunnel port 5432 to localhost
/tip diff two directories recursively
/tip set vim as default git editor
```

The query uses your configured /tip backend (which can be a larger, more capable model). Response appears directly in your terminal.

### /tip subcommands

**`/tip help`** (or `-h`, `--help`, `h`, or no args)

Shows usage, current config (which backend + model for hints and /tip), daemon status, cloud backend setup guide, and all available commands.

**`/tip status`**

Full diagnostic output:
```
[>_] shellbuddy status
────────────────────────────────────────
Daemon:        running (PID 12345)
Config:        ~/.shellbuddy/config.json
Hint backend:  ollama / qwen3:4b
/tip backend:  ollama / qwen3:8b
Ambient hints: updated 12s ago
·
HINTS  ~/repos/shellbuddy  [14:23:01]  (8 cmds)
──────────────────────────────────────────────────────────
[2x] grep → rg 'pattern'  (10x faster, .gitignore aware)
·
Python project — try: ruff check instead of flake8
Command log:   42 commands logged
·
Recent daemon log:
  shellbuddy daemon started (PID 12345)
  available backends: ollama
  hint: ollama / qwen3:4b
  /tip: ollama / qwen3:8b
```

Checks: daemon alive, config loaded, hints freshness (age in seconds), command log size, and last 5 daemon log lines.

**`/tip test`**

Forces an ambient hint cycle by injecting test commands into the log, then waits up to 60 seconds for the hints file to update. Shows the result inline. Useful for verifying the full pipeline works end-to-end.


## How ambient hints work

```
zsh preexec hook → cmd_log.jsonl → hint_daemon.py → current_hints.txt → tmux pane
                                        ↑
                               /tip queries also handled here
```

1. Every command is logged (with timestamp + CWD) to `~/.shellbuddy/cmd_log.jsonl`
2. The daemon polls every 1 second (for /tip responsiveness)
3. Every 5 seconds, it checks for new commands and runs rule matching instantly
4. Every 25 seconds (or on CWD change), it sends last 10 commands to the AI hint backend with thinking enabled
5. While the AI thinks, `thinking ...` is shown in the hints pane
6. Once done, rule hints (yellow) and AI hints (green) are rendered
7. `/tip` queries are handled on each poll cycle with the /tip backend

### Intent detection

The daemon analyses your recent commands to detect what you're doing:
- Committing/pushing code (git add, commit, push)
- Running tests (pytest, npm test, cargo test)
- Working with containers (docker, kubectl)
- Installing dependencies (pip, conda, npm, brew)
- Working with remote servers (ssh, scp, rsync)
- Retrying a failing command (same command repeated)

This context is passed to the AI so hints are relevant to your current workflow.

### Thinking mode

Models that support chain-of-thought reasoning (qwen3, deepseek-r1) will think internally before responding. The `<think>...</think>` blocks are stripped — you only see the final answer. This produces significantly better hints at a small speed cost.


## Two-model architecture

shellbuddy uses two separate AI backends:

| Role | Purpose | Default |
|------|---------|---------|
| **Ambient** | Always-on hints pane, runs every 25s | `ollama / qwen3:4b` |
| **/tip** | On-demand queries, quality matters | `ollama / qwen3:8b` |

Pick a small, fast model for ambient (it runs continuously). Pick a larger or cloud model for /tip (only runs when you ask).

You can mix backends — e.g. ollama for ambient hints, Claude for /tip queries.

Configuration is in `~/.shellbuddy/config.json` (see SETUP.md for details).


## Customising rules

Edit `~/.shellbuddy/hint_daemon.py` — the `UPGRADE_RULES` list near the top:

```python
UPGRADE_RULES = [
    (r"^cd\s+",        "cd → z {arg}  (zoxide)"),
    (r"^docker ps\b",  "docker ps → lazydocker  (full TUI)"),
    # Add your own:
    (r"^kubectl get\b", "kubectl → k9s  (live k8s TUI)"),
]
```

`{arg}` is replaced with the actual argument from the matched command. Rules match via regex against each command, and hints show a `[Nx]` counter for how many times the pattern was hit.

Rules have a cooldown of 120 seconds — the same rule won't be re-shown within that window.


## Recommended tools

shellbuddy teaches you to use these modern replacements. Install them so hints are actionable:

```bash
brew install zoxide eza bat fd ripgrep lazygit git-delta fzf atuin starship dust bottom thefuck tldr
```

| Tool | Replaces | Why |
|------|----------|-----|
| `zoxide` | `cd` | Learns your directories. `z proj` jumps anywhere. |
| `eza` | `ls` | Git status, icons, tree view |
| `bat` | `cat` | Syntax highlighting, git diff |
| `fd` | `find` | 5-10x faster, respects .gitignore |
| `ripgrep` | `grep` | 10-100x faster, sane defaults |
| `lazygit` | git CLI | Full TUI for staging, log, branches |
| `git-delta` | git pager | Side-by-side diffs, syntax highlighting |
| `fzf` | fuzzy finding | Used by atuin, zoxide, and standalone |
| `atuin` | `history` | SQLite-backed, ranked fuzzy search |
| `starship` | PS1 prompt | Git, conda, language versions, zero config |
| `dust` | `du` | Visual disk usage tree |
| `bottom` | `top`/`htop` | Multi-panel system monitor, vim keys |
| `thefuck` | retyping | Esc+Esc after a typo auto-corrects it |
| `tldr` | `man` | Example-first command reference |


## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Waiting for hints..." | Run a few commands first (MIN_COMMANDS=2). Check: `/tip status` |
| Daemon won't start | Check `hints-log`. Common: Ollama not running, wrong Python path |
| AI hints show error | `[ollama: connection refused]` → run `ollama serve` or `brew services start ollama` |
| Stale hints | `hints-stop && sb` to restart |
| /tip times out | Model may be cold-loading (first query takes 30-90s). Check `hints-log` |
| /tip returns empty | Check `/tip status` — backend may not be available |
| tmux pane flickers | Increase sleep in show_hints.sh loop (default 3s) |
| Wrong model | Check `/tip help` to see current config, edit `~/.shellbuddy/config.json` |


## The design rationale

**Working memory externalisation.** When you're deep in a problem, your working memory is full. Remembering "use `rg` instead of `grep`" requires a context switch. shellbuddy puts the reminder in peripheral vision — a persistent strip you can glance at without breaking flow.

**Habit formation at point-of-use.** The most effective habit triggers are contextual cues at the moment of the old behaviour. Showing a hint after you type `ls` for the third time is more effective than a cheat sheet you read once.

**Frequency signals reduce decision fatigue.** The `[3x]` counter gives you a concrete signal — "I've done this three times" has more weight than "you should use eza".

**Low-interruption.** The pane doesn't pop up or flash. It's there when you glance up — like a sticky note, not a notification.
