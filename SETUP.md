# shellbuddy — Setup Guide

## Prerequisites

- macOS (Linux support partial — Copilot backend is macOS-only)
- zsh (default on macOS)
- Python 3.9+ (stdlib only — no pip dependencies required)
- tmux (`brew install tmux`)
- At least one AI backend (Ollama recommended)


## Install

```bash
git clone https://github.com/bhargavachary/shellbuddy.git
cd shellbuddy
./install.sh
```

The installer will:
1. Check prerequisites (zsh, python3, tmux) — offer to install missing ones via brew
2. Check disk space and internet connectivity
3. Auto-detect or let you choose an AI backend (Copilot, Claude, Ollama)
4. If Ollama: let you pick two models (ambient hints + /tip queries)
5. Pull the selected Ollama models
6. Copy scripts to `~/.shellbuddy/`
7. Write `~/.shellbuddy/config.json` with your choices
8. Patch `~/.zshrc` with command logger, daemon auto-start, and `/tip` function
9. Optionally configure tmux and starship
10. Verify everything

### Installer options

```bash
./install.sh                          # interactive (recommended)
./install.sh -y                       # yes to all — accept defaults, no prompts
./install.sh --backend ollama         # force a specific backend
./install.sh --no-tmux                # skip tmux config
./install.sh --no-starship            # skip starship config
./install.sh --no-zshrc               # skip .zshrc patching (do it manually)
./install.sh --dir /custom/path       # install to a custom directory
./install.sh -y --backend ollama      # non-interactive with specific backend
```

The `-y` / `--yes` flag accepts all defaults without prompting: qwen3:4b for ambient hints, qwen3:8b for /tip, append tmux keybinding, etc. Useful for scripted or remote installs.

### After install

```bash
source ~/.zshrc                       # load shellbuddy hooks
brew services start ollama            # if using ollama
tmux new -s dev                       # start a tmux session
sb                                    # toggle hints pane
```


## Ollama setup (recommended, local + free)

```bash
brew install ollama
brew services start ollama            # auto-start on login
```

The installer will offer to pull models. You can also do it manually:

```bash
ollama pull qwen3:4b                  # ~2.5GB — ambient hints (fast)
ollama pull qwen3:8b                  # ~5GB   — /tip queries (balanced)
```

### Model options

During install, you choose two models:

**Ambient hints** — runs continuously, pick something light:

| Model | Size | RAM | Notes |
|-------|------|-----|-------|
| `qwen3:4b` | ~2.5GB | 8GB+ | Fast, good with thinking mode (default) |
| `qwen3:8b` | ~5GB | 16GB+ | Better quality, still fast |
| `deepseek-r1:8b` | ~5GB | 16GB+ | Strong reasoning, good for code |

**/tip queries** — on-demand, can be heavier:

| Model | Size | RAM | Notes |
|-------|------|-----|-------|
| `qwen3:8b` | ~5GB | 16GB+ | Balanced (default) |
| `qwen3:14b` | ~9GB | 32GB+ | Best qwen3 quality |
| `deepseek-r1:8b` | ~5GB | 16GB+ | Strong reasoning |
| `deepseek-r1:14b` | ~9GB | 32GB+ | Best local reasoning |

Custom models: enter any model name from `ollama list` or [ollama.com/library](https://ollama.com/library).


## Configuration — config.json

All backend and model settings live in `~/.shellbuddy/config.json`:

```json
{
  "hint_backend": "ollama",
  "hint_model":   "qwen3:4b",
  "tip_backend":  "ollama",
  "tip_model":    "qwen3:8b",
  "ollama_url":   "http://localhost:11434"
}
```

After editing, restart the daemon:
```bash
hints-stop && sb
```

Check current config anytime:
```bash
/tip help
```


## Cloud backend setup

You can use cloud AI backends instead of (or alongside) Ollama. Edit `config.json` and set the appropriate environment variables.

### Claude (Anthropic)

```json
{
  "hint_backend": "ollama",
  "hint_model":   "qwen3:4b",
  "tip_backend":  "claude",
  "tip_model":    "claude-sonnet-4-5-20250514"
}
```

Set your API key — either in `.zshrc`:
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or store it in macOS Keychain (more secure):
```bash
security add-generic-password -s "anthropic" -a "api_key" -w "sk-ant-..."
```

Available Claude models:
| Model | Cost | Best for |
|-------|------|----------|
| `claude-haiku-4-5-20251001` | Cheapest | Ambient hints (fast, cheap) |
| `claude-sonnet-4-5-20250514` | Mid | /tip queries (great quality) |
| `claude-opus-4-6` | Highest | Best quality (if budget allows) |

### GitHub Copilot

Works automatically if VS Code is installed and signed into GitHub with a Copilot subscription. No API key needed — shellbuddy extracts the session token from VS Code's encrypted storage.

```json
{
  "hint_backend": "copilot",
  "hint_model":   "gpt-4.1",
  "tip_backend":  "copilot",
  "tip_model":    "gpt-4.1"
}
```

Requires `pycryptodome`:
```bash
pip install pycryptodome
```

### OpenAI

```json
{
  "tip_backend":  "openai",
  "tip_model":    "gpt-4o-mini",
  "openai_url":   "https://api.openai.com/v1"
}
```

```bash
export OPENAI_API_KEY="sk-..."
```

### Groq (fast, free tier)

Uses the OpenAI-compatible endpoint:

```json
{
  "tip_backend":  "openai",
  "tip_model":    "llama-3.1-8b-instant",
  "openai_url":   "https://api.groq.com/openai/v1"
}
```

```bash
export OPENAI_API_KEY="gsk-..."    # Groq API key
```

### Together AI

```json
{
  "tip_backend":  "openai",
  "tip_model":    "meta-llama/Llama-3.2-3B-Instruct-Turbo",
  "openai_url":   "https://api.together.xyz/v1"
}
```

### Mixed setup (recommended)

Use a fast local model for ambient hints (free, private) and a cloud model for /tip (higher quality):

```json
{
  "hint_backend": "ollama",
  "hint_model":   "qwen3:4b",
  "tip_backend":  "claude",
  "tip_model":    "claude-sonnet-4-5-20250514"
}
```


## File reference

### Repository

```
shellbuddy/
├── scripts/
│   ├── hint_daemon.py         # main daemon: polling, rules, AI, /tip handler
│   ├── log_cmd.sh             # zsh preexec hook: logs commands to JSONL
│   ├── show_hints.sh          # renders hints with colour in tmux pane
│   ├── toggle_hints_pane.sh   # creates/destroys tmux hints pane (top)
│   └── start_daemon.sh        # idempotent daemon launcher
├── backends/
│   ├── copilot.py             # GitHub Copilot backend (VS Code token)
│   ├── ollama.py              # Ollama local backend
│   └── openai_compat.py       # OpenAI-compatible API backend
├── config/
│   ├── tmux.conf              # tmux config with hints pane keybinding
│   ├── starship.toml          # starship prompt config
│   ├── zshrc_additions.zsh    # full zshrc block (reference/manual install)
│   └── envrc.template         # direnv template for conda auto-activate
├── install.sh                 # interactive installer
├── USAGE.md                   # usage guide (you're here → see USAGE.md)
├── SETUP.md                   # this file
├── LICENSE                    # MIT
└── requirements.txt           # Python deps (stdlib only; pycryptodome optional)
```

### Runtime files

Created in `~/.shellbuddy/` (not in the repo):

```
~/.shellbuddy/
├── config.json                # backend + model config (edit this to change models)
├── hint_daemon.py             # installed copy of daemon
├── log_cmd.sh                 # installed copy
├── show_hints.sh              # installed copy
├── toggle_hints_pane.sh       # installed copy
├── start_daemon.sh            # installed copy
├── backends/                  # installed backend modules
├── cmd_log.jsonl              # rolling log of commands
├── current_hints.txt          # rendered hints (read by tmux pane)
├── daemon.pid                 # daemon process ID
├── daemon.log                 # daemon stdout/stderr
├── tip_query.txt              # pending /tip query (transient)
└── tip_result.txt             # /tip response (transient)
```


## Uninstall

```bash
hints-stop                            # stop daemon
rm -rf ~/.shellbuddy                  # remove all files
```

Then remove the `# ── shellbuddy ──` block from your `~/.zshrc`.


## Contributing

PRs welcome. Most valuable areas:
- **More upgrade rules** (Docker, K8s, AWS, ffmpeg, Terraform)
- **Linux support** for Copilot backend (needs different secret store)
- **Fish/bash support** (preexec equivalents exist)
- **Native terminal pane** (Warp, iTerm2, Ghostty — avoid tmux dependency)


## Licence

MIT. See [LICENSE](LICENSE).

---

Built by [bhargavachary](https://github.com/bhargavachary).
