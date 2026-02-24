# shellbuddy — Usage Guide

## What it does

A persistent strip at the top of your tmux session shows contextual hints as you work.
Three layers fire simultaneously — rule matches appear instantly, AI hints follow asynchronously:

```
HINTS  ~/projects/myapp  [14:32:07]  (47 cmds)
──────────────────────────────────────────────────────────
!! [1x] DANGER: git push --force — use --force-with-lease
-> [3x] ls → eza -la --git --icons
·
thinking ...
```

Once the AI finishes:

```
HINTS  ~/projects/myapp  [14:32:10]  (47 cmds)
──────────────────────────────────────────────────────────
!! [1x] DANGER: git push --force — use --force-with-lease
-> [3x] ls → eza -la --git --icons
·
You've pushed twice — consider opening a PR instead
conda env not active — run: conda activate myenv
```

**Hint prefixes:**
| Prefix | Severity | Meaning |
|--------|----------|---------|
| `!! ` | danger | Data loss, irreversible, security risk |
| `!  ` | warn | Silent failure, footgun, common mistake |
| `-> ` | tip | Suboptimal but safe — better idiom exists |
| `=> ` | upgrade | Faster/modern tool replaces this one |

**Hint sources:**
- **Layer 1a — Regex rules** (`!!`/`!`/`->`/`=>`): instant, <10ms, matched from `kb.json`
- **Layer 1b — Ambient LLM**: background thread, fires every ~25s, reads last 50 commands
- **Layer 2 — Advisor**: background thread, fires on every new command (debounced 5s), writes intent/prediction to context log
- **Layer 3 — /tip**: on-demand, reads full session context before answering


## Commands

| Command | What it does |
|---------|-------------|
| `sb` | Start daemon + toggle hints pane in tmux |
| `/tip <question>` | Ask any CLI/terminal question |
| `/tip status` | Full diagnostic (config, backends, hints age, logs) |
| `/tip test` | Force an ambient hint cycle and show result |
| `/tip help` | Show help, config, backend setup guide |
| `hints-stop` | Stop the daemon |
| `hints-log` | Tail daemon logs |
| `hints-status` | Check if daemon is running |
| `Ctrl+A H` | Toggle hints pane in tmux (if tmux.conf installed) |


## /tip — on-demand CLI help

Ask any terminal question without leaving your shell:

```bash
/tip how to undo last git commit
/tip find files larger than 100mb
/tip tar extract to specific directory
/tip ssh tunnel port 5432 to localhost
/tip diff two directories recursively
/tip fix CUDA out of memory in PyTorch
/tip what does FSDP do vs DDP
```

The query is answered using your configured `/tip` backend. Before generating the answer,
the daemon injects the **full unified context log** — every command you ran, every rule
that matched, every ambient hint shown, and every prior `/tip` Q&A — so answers are
situation-aware and non-repetitive.

### /tip subcommands

**`/tip status`** — full diagnostic:
```
[>_] shellbuddy status
────────────────────────────────────────
Daemon:        running (PID 12345)
Config:        ~/.shellbuddy/config.json
Hint backend:  copilot / gpt-4.1
/tip backend:  copilot / gpt-4.1
KB engine:     1680 rules (40 buckets, 8ms load)
Ambient hints: updated 12s ago
·
HINTS  ~/repos/shellbuddy  [14:23:01]  (47 cmds)
──────────────────────────────────────────────────────────
-> [2x] grep → rg 'pattern'  (10x faster, .gitignore aware)
·
You're working on a Python project — ruff is faster than flake8
Command log:   47 commands logged
Context log:   83 entries
```

**`/tip test`** — injects test commands into the log, waits up to 60s for hints to update,
and prints the result inline. Useful for verifying the full pipeline end-to-end.

**`/tip help`** — shows usage, current config, and backend setup guide.


## How it all works

```
zsh preexec hook
      │
      ▼
cmd_log.jsonl ──────────────────────────────────────────────────────────────┐
      │                                                                      │
      ▼                                                                      │
hint_daemon.py                                                               │
      │                                                                      │
      ├─ Layer 1a: KB engine (regex dispatch)  <10ms ──► unified_context.jsonl
      │            matches rule → writes {type:"rule",...}                   │
      │                                                                      │
      ├─ Layer 1b: Ambient LLM (background thread)                           │
      │            every ~25s, reads context log ──────► unified_context.jsonl
      │            writes {type:"ambient",...}                               │
      │                                                                      │
      ├─ Layer 2:  Advisor (background thread)                               │
      │            every new cmd (debounced 5s)                              │
      │            reads context log → writes {type:"advisor",...} ──────────┘
      │
      ├─ Layer 3:  /tip handler (priority, every poll)
      │            reads full context log before answering
      │            writes {type:"tip_q",...} and {type:"tip_a",...}
      │
      ▼
current_hints.txt ──► tmux pane (rendered by show_hints.sh)
```

### The unified context log

`~/.shellbuddy/unified_context.jsonl` is a rolling append-only log (capped at 200 entries)
that every layer reads and writes. Each line is a JSON event:

```jsonl
{"ts":"14:31:05","type":"cmd","cmd":"git push --force","cwd":"~/repos/myapp"}
{"ts":"14:31:05","type":"rule","severity":"danger","hint":"Use --force-with-lease","detail":"..."}
{"ts":"14:31:08","type":"ambient","text":"You've pushed twice — consider opening a PR"}
{"ts":"14:31:10","type":"advisor","intent":"deploying main branch","observation":"force push risk","prediction":"will run tests next"}
{"ts":"14:32:01","type":"tip_q","query":"how do I undo that push"}
{"ts":"14:32:03","type":"tip_a","text":"git push --force-with-lease origin HEAD~1..."}
```

This means `/tip` never repeats advice that was already given, ambient LLM hints
don't duplicate what rules already showed, and the advisor builds a coherent picture
of your session across restarts (log persists on disk).

### KB engine (Layer 1a)

The knowledge base (`kb.json`) contains ~1,700+ entries across 40 categories generated
from Linux man pages, sysadmin best practices, ML/DL workflows, and tool documentation.

Each entry has:
- **pattern** — Python regex matched against the command
- **severity** — `danger / warn / tip / upgrade`
- **hint** — ≤68 chars shown in the pane
- **detail** — 2-3 sentences of expert context, injected into `/tip` prompts when matched
- **tags** — for future filtering

The engine uses a **dispatcher**: rules are bucketed by first command token at load time.
Matching `git push --force` only checks ~60 git rules, not all 1,700. Benchmark: ~0.2ms
for 1,700 rules × 15 commands.

### Advisor (Layer 2)

Fires on every new command (skips if previous call still running — debounced to 5s minimum).
Reads the last 100 commands + unified context, and writes three things to the context log:
- **intent** — what you're currently trying to do
- **observation** — a pattern, risk, or struggle it notices
- **prediction** — your likely next command

This feeds directly into `/tip` so when you ask a question, the model already "knows"
what you've been doing.


## The knowledge base

`kb.json` ships with ~1,700 rules across 40 categories. To regenerate or extend it:

```bash
cd ~/repos/shellbuddy

# Full build (all 40 categories, ~10 min, uses Copilot gpt-4.1)
python3 kb_builder.py

# Rebuild one category
python3 kb_builder.py --category pytorch

# Resume interrupted build (skips cached categories in .kb_partial/)
python3 kb_builder.py --resume

# Audit existing kb.json
python3 kb_builder.py --validate-only

# Install after build
cp kb.json ~/.shellbuddy/kb.json
hints-stop && sb
```

KB categories include: GNU coreutils, sysadmin, networking, security, TLS/PKI, git,
Python packaging, dev tools, Jupyter, data science, MLOps, machine learning, PyTorch,
TensorFlow, JAX, HuggingFace, GPU/CUDA, model serving, Docker, Kubernetes, AWS, GCP/Azure,
Terraform, SQL databases, NoSQL databases, Node.js, profiling, monitoring, vim/neovim,
tmux, package managers, build systems, VHDL/FPGA, macOS.

### Writing custom rules

Add entries directly to `~/.shellbuddy/kb.json`:

```json
{
  "id": "custom-001",
  "pattern": "^kubectl\\s+delete\\s+.*--all",
  "cmd": "kubectl",
  "severity": "danger",
  "hint": "kubectl delete --all: deletes ALL resources in namespace",
  "detail": "Without -n flag this targets the default namespace. With --all-namespaces it is cluster-wide. Always specify -n <namespace> explicitly.",
  "tags": ["kubernetes", "destructive"]
}
```

Restart the daemon to reload: `hints-stop && sb`


## Customising settings

`~/.shellbuddy/config.json`:

```json
{
  "hint_backend": "copilot",
  "hint_model":   "gpt-4.1",
  "tip_backend":  "copilot",
  "tip_model":    "gpt-4.1"
}
```

`hint_backend` / `hint_model` — used by ambient LLM hints and the advisor
`tip_backend` / `tip_model` — used by `/tip` on-demand queries

After editing, restart: `hints-stop && sb`


## Recommended tools

shellbuddy hints teach you to use these. Install them so hints are actionable:

```bash
brew install zoxide eza bat fd ripgrep lazygit git-delta fzf atuin starship \
             dust bottom procs tldr jq httpie hyperfine tokei trash glow
```

| Tool | Replaces | Why |
|------|----------|-----|
| `zoxide` | `cd` | Learns your paths. `z proj` jumps anywhere. |
| `eza` | `ls` | Git status, icons, tree view |
| `bat` | `cat` | Syntax highlighting, git diff inline |
| `fd` | `find` | 5-10x faster, respects .gitignore |
| `ripgrep` | `grep` | 10-100x faster, sane defaults |
| `lazygit` | git CLI | Full TUI: staging, log, branches, stash |
| `git-delta` | git pager | Side-by-side diffs, syntax highlighting |
| `fzf` | fuzzy find | Used by atuin, zoxide, standalone |
| `atuin` | `history` | SQLite-backed, ranked fuzzy search |
| `starship` | PS1 | Git, conda, language versions, zero config |
| `dust` | `du` | Visual disk usage tree |
| `bottom` | `top`/`htop` | Multi-panel monitor, vim keys |
| `procs` | `ps` | Searchable, sortable, tree view |
| `tldr` | `man` | Example-first command reference |
| `jq` | python json | Pipe JSON, filter, transform |
| `trash` | `rm` | Recoverable deletes via macOS Trash |


## Troubleshooting

| Problem | Fix |
|---------|-----|
| Hints not updating | Run a few commands. Check: `/tip test` |
| Daemon won't start | Check `hints-log`. Common: wrong Python path |
| KB engine not loading | Run `python3 kb_builder.py` then `cp kb.json ~/.shellbuddy/kb.json` |
| Stale hints | `hints-stop && sb` |
| /tip times out | Copilot token may have expired — restart VS Code and retry |
| /tip returns empty | Check `/tip status` — backend availability, daemon log |
| Context log growing large | Capped at 200 entries automatically |
| tmux pane flickers | Increase sleep in `show_hints.sh` loop (default 3s) |
| Wrong model | Check `/tip help`, edit `~/.shellbuddy/config.json` |


## Design rationale

**Working memory externalisation.** When deep in a problem, your working memory is full.
Remembering "use `rg` instead of `grep`" requires a context switch. shellbuddy puts the
reminder in peripheral vision — a persistent strip you glance at without breaking flow.

**Habit formation at point-of-use.** The most effective habit triggers are contextual cues
at the moment of the old behaviour. A hint after you type `ls` for the third time is more
effective than a cheat sheet you read once.

**Frequency signals reduce decision fatigue.** The `[3x]` counter gives a concrete signal —
"I've done this three times" has more weight than "you should use eza".

**Shared context makes AI useful.** Every layer (rules, ambient LLM, advisor, /tip) reads
and writes to the same context log. The LLM doesn't need to re-infer your session state
on every call — it's already there.

**Low-interruption.** The pane doesn't pop up or flash. It's there when you glance up —
like a sticky note, not a notification.
