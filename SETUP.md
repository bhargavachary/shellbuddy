# shellbuddy — Setup Guide

## Prerequisites

- macOS (Linux support partial — Copilot backend is macOS-only)
- zsh (default on macOS)
- Python 3.9+ (`pycryptodome` required for Copilot backend)
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
3. Auto-detect or let you choose an AI backend (Copilot, Claude, Ollama, OpenAI)
4. Copy all scripts, backends, and `kb.json` to `~/.shellbuddy/`
5. Write `~/.shellbuddy/config.json` with your choices
6. Patch `~/.zshrc` with command logger, daemon auto-start, and `/tip` function
7. Optionally configure tmux and starship
8. Verify everything

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
source ~/.zshrc        # load shellbuddy hooks
tmux new -s dev        # start a tmux session
sb                     # start daemon + toggle hints pane
```


## Backend setup

### GitHub Copilot (recommended — zero config)

Works automatically if VS Code is installed and signed into GitHub with a Copilot subscription.
shellbuddy extracts the session token from VS Code's encrypted local storage. No API key needed.

Requires `pycryptodome` (usually installed by `install.sh`):
```bash
pip install pycryptodome
```

```json
{
  "hint_backend": "copilot",
  "hint_model":   "gpt-4.1",
  "tip_backend":  "copilot",
  "tip_model":    "gpt-4.1"
}
```

### Ollama (local, private, free)

```bash
brew install ollama
brew services start ollama

ollama pull qwen3:4b     # ambient hints (~2.5GB, fast)
ollama pull qwen3:8b     # /tip queries (~5GB, balanced)
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
  "tip_backend":  "openai",
  "tip_model":    "gpt-4o-mini",
  "openai_url":   "https://api.openai.com/v1"
}
```

```bash
export OPENAI_API_KEY="sk-..."
```

Works with any OpenAI-compatible endpoint (Groq, Together AI, etc.):

```json
{
  "tip_backend":  "openai",
  "tip_model":    "llama-3.1-8b-instant",
  "openai_url":   "https://api.groq.com/openai/v1"
}
```

### Mixed setup

Use Copilot or a fast local model for ambient hints, a stronger model for /tip:

```json
{
  "hint_backend": "copilot",
  "hint_model":   "gpt-4.1",
  "tip_backend":  "claude",
  "tip_model":    "claude-sonnet-4-6"
}
```

After any config change: `hints-stop && sb`


## Building the knowledge base

The KB (`kb.json`) ships pre-built with ~1,700 rules. To regenerate or extend it,
use `kb_builder.py` — it calls your configured Copilot backend to generate rules
category by category, validates schema and regex, and saves resumable partials.

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

The builder saves per-category partials to `.kb_partial/` — if the build is interrupted,
`--resume` skips already-completed categories.

**Categories:** gnu, text, archive, sysadmin, process, disk, users, network, security,
tls, git, git-advanced, python-pkg, python-dev, jupyter, datascience, mlops, ml,
pytorch, tensorflow, jax, huggingface, gpu, serving, docker, kubernetes, aws,
gcp-azure, terraform, db-sql, db-nosql, node, perf, monitoring, vim, tmux,
pkgmgr, build, fpga, macos


## Configuration reference

All settings live in `~/.shellbuddy/config.json`:

```json
{
  "hint_backend":   "copilot",
  "hint_model":     "gpt-4.1",
  "tip_backend":    "copilot",
  "tip_model":      "gpt-4.1",

  "ollama_url":     "http://localhost:11434",
  "claude_model":   "claude-haiku-4-5-20251001",
  "copilot_model":  "gpt-4.1",
  "openai_url":     "https://api.openai.com/v1",
  "openai_model":   "gpt-4o-mini"
}
```

| Key | Purpose |
|-----|---------|
| `hint_backend` | Backend for ambient LLM hints and the advisor |
| `hint_model` | Model for ambient LLM hints and the advisor |
| `tip_backend` | Backend for `/tip` on-demand queries |
| `tip_model` | Model for `/tip` on-demand queries |

Check current config: `/tip help`
Restart after changes: `hints-stop && sb`


## File reference

### Repository

```
shellbuddy/
├── scripts/
│   ├── hint_daemon.py         # main daemon: KB engine, ambient LLM, advisor, /tip
│   ├── log_cmd.sh             # zsh preexec hook: logs commands to cmd_log.jsonl
│   ├── show_hints.sh          # renders hints with colour in tmux pane
│   ├── toggle_hints_pane.sh   # creates/destroys tmux hints pane (top strip)
│   └── start_daemon.sh        # idempotent daemon launcher
├── backends/
│   ├── copilot.py             # GitHub Copilot (VS Code token extraction)
│   ├── ollama.py              # Ollama local backend
│   └── openai_compat.py       # OpenAI-compatible API backend
├── kb_builder.py              # generates kb.json via Copilot, 40 categories
├── kb_engine.py               # dispatcher engine: loads kb.json, buckets by token
├── kb.json                    # pre-built knowledge base (~1,700 rules)
├── config/
│   ├── tmux.conf              # tmux config with hints pane keybinding
│   ├── starship.toml          # starship prompt config
│   ├── zshrc_additions.zsh    # full zshrc block (reference / manual install)
│   └── envrc.template         # direnv template for conda auto-activate
├── install.sh                 # interactive installer
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
├── kb.json                    # active knowledge base (copy from repo after build)
├── hint_daemon.py             # installed daemon
├── kb_engine.py               # installed KB engine
├── backends/                  # installed backend modules
├── scripts/                   # installed shell scripts
├── cmd_log.jsonl              # rolling log of every command (with timestamp + CWD)
├── unified_context.jsonl      # shared context: rules, ambient hints, advisor, /tip Q&A
├── current_hints.txt          # rendered hints read by tmux pane
├── daemon.pid                 # daemon process ID
├── daemon.log                 # daemon stdout/stderr
├── tip_query.txt              # pending /tip query (transient)
└── tip_result.txt             # /tip response (transient)
```

**`unified_context.jsonl`** is the most important runtime file. It's a rolling log
(200 entries max) of everything that happened in your session — commands run, rules
matched, AI hints shown, advisor observations, and /tip Q&A. All three AI layers read
this before generating output, so nothing is repeated and context compounds over time.


## Uninstall

```bash
hints-stop                   # stop daemon
rm -rf ~/.shellbuddy         # remove all runtime files
```

Then remove the `# ── shellbuddy ──` block from `~/.zshrc`.


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
