# shellbuddy — Setup Guide

## Prerequisites

- macOS (Linux support partial — Copilot backend is macOS-only)
- zsh (default on macOS)
- Python 3.9+
- tmux (`brew install tmux`)
- At least one AI backend — GitHub Copilot is recommended (zero config if VS Code is installed)


## Install

```bash
git clone https://github.com/bhargavachary/shellbuddy.git
cd shellbuddy
./install.sh
```

The installer will:
1. Check prerequisites (zsh, python3, tmux) — offer to install missing ones via brew
2. Check disk space and internet connectivity
3. Offer curated tool bundles (shell essentials, git, system monitoring, Python, etc.)
4. Auto-detect or let you choose an AI backend (Copilot, Claude, Ollama, OpenAI)
5. Copy all scripts, backends, and `kb.json` to `~/.shellbuddy/`
6. Write `~/.shellbuddy/config.json` with your choices
7. Patch `~/.zshrc` with command logger, daemon auto-start, `sb` / `shellbuddy` commands, and `/tip`
8. Optionally configure tmux and starship
9. Verify everything

### Installer options

```bash
./install.sh                          # interactive (recommended)
./install.sh -y                       # yes to all defaults, no prompts
./install.sh --backend copilot        # force a specific backend
./install.sh --no-tmux                # skip tmux config
./install.sh --no-starship            # skip starship config
./install.sh --no-zshrc               # skip .zshrc patching (manual install)
./install.sh --dir /custom/path       # install to a custom directory
```

### After install

```bash
source ~/.zshrc          # load shellbuddy hooks
tmux new -s dev          # start a tmux session
sb                       # start daemon + open hints pane
# or equivalently:
shellbuddy
```


## Uninstall

```bash
cd shellbuddy
./uninstall.sh           # interactive — asks before each step
./uninstall.sh -y        # non-interactive, removes everything
```

The uninstaller:
- Stops the daemon and kills any orphaned processes
- Deletes `~/.shellbuddy/`
- Removes the shellbuddy block from `~/.zshrc`
- Removes the shellbuddy keybinding from `~/.tmux.conf`
- Optionally restores `~/.config/starship.toml` from backup
- Prints a full list of packages it did **not** remove (brew/pip tools are left in place)


## Backend setup

### GitHub Copilot (recommended — zero config)

Works automatically if VS Code is installed and signed into GitHub with a Copilot subscription.
shellbuddy extracts the session token from VS Code's encrypted local storage. No API key needed.

Requires `pycryptodome` (installed by `install.sh`):
```bash
pip install pycryptodome
```

```json
{
  "hint_backend":      "copilot",
  "hint_model":        "gpt-5-mini",
  "hint_model_chain":  ["gpt-5-mini", "raptor-mini", "gpt-4.1"],
  "tip_backend":       "copilot",
  "tip_model":         "gpt-4.1"
}
```

The `hint_model_chain` makes ambient hints try `gpt-5-mini` first (fastest), fall back to
`raptor-mini`, then `gpt-4.1`. `/tip` always uses `tip_model` directly.

### Ollama (local, private, free)

```bash
brew install ollama
brew services start ollama

ollama pull qwen3:4b        # ambient hints (~2.5GB, fast)
ollama pull qwen3:8b        # /tip queries (~5GB, balanced)
```

```json
{
  "hint_backend": "ollama",
  "hint_model":   "qwen3:4b",
  "tip_backend":  "ollama",
  "tip_model":    "qwen3:8b",
  "ollama_url":   "http://localhost:11434"
}
```

Recommended Ollama models:

| Model | Size | Best for |
|-------|------|----------|
| `qwen3:4b` | ~2.5GB | Ambient hints (fast, default) |
| `qwen3:8b` | ~5GB | /tip queries (balanced) |
| `qwen3:14b` | ~9GB | Best local quality |
| `deepseek-r1:8b` | ~5GB | Strong reasoning |
| `deepcoder:14b` | ~9GB | Code-focused tasks |

### Claude (Anthropic)

```json
{
  "hint_backend": "claude",
  "hint_model":   "claude-haiku-4-5-20251001",
  "tip_backend":  "claude",
  "tip_model":    "claude-sonnet-4-6"
}
```

Set your API key in `.zshrc`:
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or store in macOS Keychain (more secure):
```bash
security add-generic-password -s "anthropic" -a "api_key" -w "sk-ant-..."
```

| Model | Best for |
|-------|----------|
| `claude-haiku-4-5-20251001` | Ambient hints (fast, cheap) |
| `claude-sonnet-4-6` | /tip queries (great quality) |
| `claude-opus-4-6` | Best quality |

### OpenAI / OpenAI-compatible

```json
{
  "tip_backend": "openai",
  "tip_model":   "gpt-4o-mini",
  "openai_url":  "https://api.openai.com/v1"
}
```

```bash
export OPENAI_API_KEY="sk-..."
```

Works with any OpenAI-compatible endpoint (Groq, Together AI, etc.):

```json
{
  "tip_backend": "openai",
  "tip_model":   "llama-3.1-8b-instant",
  "openai_url":  "https://api.groq.com/openai/v1"
}
```

### Mixed setup

Fast model for ambient, stronger model for /tip:

```json
{
  "hint_backend":      "copilot",
  "hint_model":        "gpt-5-mini",
  "hint_model_chain":  ["gpt-5-mini", "raptor-mini", "gpt-4.1"],
  "tip_backend":       "claude",
  "tip_model":         "claude-sonnet-4-6"
}
```

After any config change: `hints-stop && sb`


## Building the knowledge base

The KB (`kb.json`) ships pre-built with ~1,791 rules across 40 categories. To regenerate
or extend it, use `kb_builder.py` — it calls your Copilot backend (gpt-4.1) to generate
rules category by category, validates schema and regex, and saves resumable partials.

```bash
cd ~/repos/shellbuddy

# Full build — all 40 categories (~10 min)
python3 kb_builder.py

# Resume interrupted build
python3 kb_builder.py --resume

# Rebuild one category
python3 kb_builder.py --category pytorch
python3 kb_builder.py --category git

# Audit existing kb.json
python3 kb_builder.py --validate-only

# Install
cp kb.json ~/.shellbuddy/kb.json
hints-stop && sb
```

The builder saves per-category partials to `.kb_partial/` — `--resume` skips already-completed
categories if the build is interrupted.

**Categories:** gnu, text, archive, sysadmin, process, disk, users, network, security,
tls, git, git-advanced, python-pkg, python-dev, jupyter, datascience, mlops, ml,
pytorch, tensorflow, jax, huggingface, gpu, serving, docker, kubernetes, aws,
gcp-azure, terraform, db-sql, db-nosql, node, perf, monitoring, vim, tmux,
pkgmgr, build, fpga, macos


## Configuration reference

All settings live in `~/.shellbuddy/config.json`:

```json
{
  "hint_backend":      "copilot",
  "hint_model":        "gpt-5-mini",
  "hint_model_chain":  ["gpt-5-mini", "raptor-mini", "gpt-4.1"],
  "tip_backend":       "copilot",
  "tip_model":         "gpt-4.1",

  "ollama_url":        "http://localhost:11434",
  "claude_model":      "claude-haiku-4-5-20251001",
  "copilot_model":     "gpt-5-mini",
  "openai_url":        "https://api.openai.com/v1",
  "openai_model":      "gpt-4o-mini"
}
```

| Key | Purpose |
|-----|---------|
| `hint_backend` | Backend for ambient LLM hints and the advisor |
| `hint_model` | Primary model for ambient hints (first in chain) |
| `hint_model_chain` | Fallback model chain for copilot ambient hints |
| `tip_backend` | Backend for `/tip` on-demand queries |
| `tip_model` | Model for `/tip` (used directly, no chain) |

Check current config: `/tip help`
Restart after changes: `hints-stop && sb`


## File reference

### Repository

```
shellbuddy/
├── scripts/
│   ├── hint_daemon.py         # main daemon: KB engine, ambient LLM, advisor, /tip, post-mortem
│   ├── log_cmd.sh             # zsh preexec hook: logs commands to cmd_log.jsonl
│   ├── show_hints.sh          # renders hints + logo in tmux hints pane
│   ├── show_stats.sh          # live stats strip: CPU / RAM / GPU at ~1Hz
│   ├── toggle_hints_pane.sh   # creates/destroys stats pane + hints pane together
│   └── start_daemon.sh        # idempotent daemon launcher
├── backends/
│   ├── copilot.py             # GitHub Copilot (VS Code token extraction, macOS)
│   ├── ollama.py              # Ollama local backend
│   └── openai_compat.py       # OpenAI-compatible API backend
├── kb_builder.py              # generates kb.json via Copilot gpt-4.1, 40 categories
├── kb_engine.py               # dispatcher engine: loads kb.json, buckets by token
├── kb.json                    # pre-built knowledge base (~1,791 rules)
├── config/
│   ├── tmux.conf              # tmux config with hints pane keybinding (Ctrl+A H)
│   ├── starship.toml          # starship prompt config
│   ├── zshrc_additions.zsh    # full zshrc block (reference / manual install)
│   └── envrc.template         # direnv template for conda auto-activate
├── install.sh                 # interactive installer
├── uninstall.sh               # clean uninstaller (leaves brew/pip packages)
├── USAGE.md                   # usage guide
├── SETUP.md                   # this file
├── LICENSE                    # MIT
└── requirements.txt           # pycryptodome (Copilot backend)
```

### Runtime files

Created in `~/.shellbuddy/` (not tracked in repo):

```
~/.shellbuddy/
├── config.json                # backend + model config
├── kb.json                    # active knowledge base
├── hint_daemon.py             # installed daemon
├── kb_engine.py               # installed KB engine
├── show_stats.sh              # live stats strip script
├── backends/                  # installed backend modules
├── cmd_log.jsonl              # rolling log of every command (timestamp + CWD)
├── unified_context.jsonl      # shared context: rules, hints, advisor, /tip Q&A, post-mortem
├── current_hints.txt          # rendered hints read by tmux hints pane
├── post_mortem.txt            # last auto-drafted git commit message
├── daemon.pid                 # daemon process ID
├── daemon.log                 # daemon stdout/stderr
├── tip_query.txt              # pending /tip query (transient)
└── tip_result.txt             # /tip response (transient)
```

**`unified_context.jsonl`** is the central runtime file — a rolling append-only log
(200 entries max) of every event: commands run, rules matched, AI hints shown, advisor
observations, /tip Q&A, and post-mortem drafts. Every AI layer reads this before
generating output so context compounds and nothing is repeated.


## Contributing

PRs welcome. High-value areas:

- **KB entries** — more rules in `kb.json` (run `kb_builder.py --category <slug>`)
- **Linux Copilot backend** — needs a different secret store (libsecret / kwallet)
- **Fish/bash support** — preexec equivalents exist in both
- **Native pane** — Warp, iTerm2, Ghostty to avoid tmux dependency
- **KB categories** — bio/cheminformatics, audio/video (ffmpeg), game dev, embedded


## Licence

MIT. See [LICENSE](LICENSE).

---

Built by [bhargavachary](https://github.com/bhargavachary).
