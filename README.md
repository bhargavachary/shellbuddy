# ShellBuddy (sb)

> **Ambient, multi-layer terminal companion for modern developers.**  
> Real-time system vitals, instant sub-millisecond safety rules, and context-aware LLM suggestions inside `tmux` without disrupting your shell workflow.

[![Tests](https://img.shields.io/badge/tests-139%20passed-brightgreen.svg)](tests/)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12-blue.svg)](requirements.txt)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey.svg)](SETUP.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 1. What ShellBuddy Does

ShellBuddy sits quietly at the top of your `tmux` session, adding two compact, non-intrusive status strips:

1. **Stats Pane (Top, 2 lines):** Real-time CPU, RAM, and GPU utilization sparklines sampled at ~1Hz.
2. **Hints Pane (Below Stats):** Contextual command recommendations, security warnings, and performance upgrades that react to what you run.
3. **`/tip` Command (Interactive):** An on-demand terminal assistant that answers questions using the full context of your recent commands, active directory, and toolchain.

```text
  ◆ shellbuddy  14:32:07  live system stats
  ┤ CPU ████░░░░  22.5%  ┤ RAM ████████ 15.0/36G  ┤ GPU ░░░░░░░░  3.0%  ┤  cpu ▁▁▁▂  ram ████  gpu ░

HINTS  ~/projects/myapp  [14:32:07]  (47 cmds)               ◆ shellbuddy
──────────────────────────────────────────────────────────    ─────────────
!! [1x] DANGER: git push --force — use --force-with-lease
-> [3x] ls → eza -la --git --icons
·
You've pushed twice — consider opening a PR instead
conda env not active — run: conda activate myenv
```

---

## 2. Why It Exists

Modern developers juggle dozens of complex CLI tools (`git`, `docker`, `kubectl`, `ffmpeg`, `cargo`, `pip`, `tar`). Traditional AI coding assistants either:
- Require switching windows to a browser or IDE chat pane, breaking focus.
- Require slow manual prompting for every simple CLI question.
- Try to execute commands automatically without explicit confirmation, introducing security risks.

**ShellBuddy solves this with an ambient, multi-tier design:**
- **Zero latency for critical rules:** Destructive commands (`git push --force`, `rm -rf /`, `chmod 777`) trigger instant warnings in `<0.15ms` from a local 1,835-rule precompiled knowledge base.
- **Asynchronous LLM intelligence:** Deeper workflow advice runs in background threads without blocking shell keystrokes.
- **Strict safety:** ShellBuddy **never** executes commands on your behalf. It advises, you control.

---

## 3. Capability Status: Implemented vs. Experimental

| Feature | Status | Description |
|---|---|---|
| **Local Knowledge Base Engine** | **Production-Ready** | 1,835 curated rules, indexed into 336 command buckets, sub-millisecond evaluation (<0.12ms/cmd). |
| **Safety Redirection & Warnings** | **Production-Ready** | Flags dangerous flags (`--force`, `chmod 777`), common footguns, and modern replacements (`rg`, `eza`, `fd`). |
| **Tmux Panes Integration** | **Production-Ready** | Automated dual-pane layout, dynamic resizing, zero-flicker render loop. |
| **`/tip` On-Demand Assistant** | **Production-Ready** | CLI query tool injecting recent shell history, repo metadata, and matching rules into LLM prompt. |
| **Pluggable Backends** | **Production-Ready** | GitHub Copilot (zero-key macOS integration), Claude, Ollama (local/offline), OpenAI-compatible APIs. |
| **Secret Sanitization** | **Production-Ready** | Automatic pre-exec filtering of tokens, bearer auth, private keys, passwords, and AWS credentials. |
| **Intent Advisor Layer** | *Experimental* | Predictive background heuristics anticipating next developer tasks. |
| **Idle Tips Rotation** | *Experimental* | Displays rotating productivity tips after 90 seconds of terminal inactivity. |
| **Auto Post-Mortem Draft** | *Experimental* | Generates contextual Git commit message drafts based on accumulated session changes. |

---

## 4. Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                      Developer Terminal                     │
│  (zsh preexec hook in scripts/log_cmd.sh)                   │
└───────────────┬─────────────────────────────────────────────┘
                │ Non-blocking append (sanitized)
                ▼
┌─────────────────────────────────────────────────────────────┐
│               ~/.shellbuddy/cmd_log.jsonl                   │
└───────────────┬─────────────────────────────────────────────┘
                │ Monitored by inotify/stat loop
                ▼
┌─────────────────────────────────────────────────────────────┐
│                    scripts/hint_daemon.py                   │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ Layer 1a: Fast KB Dispatcher (kb_engine.py)         │   │
│   │ 1,835 regex rules in 336 buckets (<0.15ms runtime)  │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │                              │
│   ┌──────────────────────────▼──────────────────────────┐   │
│   │ Layer 1b & 2: Asynchronous AI Backends              │   │
│   │ Copilot / Claude / Ollama / OpenAI                  │   │
│   └──────────────────────────┬──────────────────────────┘   │
└──────────────────────────────┼──────────────────────────────┘
                               │ Writes formatted lines
                ┌──────────────┴──────────────┐
                ▼                             ▼
   ┌─────────────────────────┐   ┌─────────────────────────┐
   │    tmux Hints Pane      │   │     tmux Stats Pane     │
   │  (scripts/show_hints.sh)│   │  (scripts/show_stats.sh)│
   └─────────────────────────┘   └─────────────────────────┘
```

---

## 5. Security & Safety Boundaries

ShellBuddy is engineered around strict security constraints:

1. **Read-Only Interception:** Commands are recorded via a `zsh` `preexec` hook. ShellBuddy does not wrap or proxy shell execution.
2. **No Autonomous Execution:** ShellBuddy never runs suggested commands. All output is displayed in status panes or printed to standard output for user review.
3. **Strict Secret Masking:** `scripts/log_cmd.sh` discards commands containing passwords, tokens, API keys (`api_key`, `secret`, `password`, `bearer`, `access_token`, `ghp_`, `id_rsa`, `aws_access_key`, `export *key=`, etc.).
4. **Offline Capability:** If no LLM backend is configured or network is unavailable, Layer 1a (KB Engine) operates entirely offline with 100% functionality.

---

## 6. Quick Start & Installation

### Prerequisites
- **OS:** macOS 12+ (primary) or Linux (Ubuntu/Debian/Fedora with `zsh` + `tmux`)
- **Shell:** `zsh`
- **Python:** 3.9, 3.10, 3.11, or 3.12
- **Multiplexer:** `tmux` (`brew install tmux` or `sudo apt install tmux`)

### Installation

```bash
git clone https://github.com/bhargavachary/shellbuddy.git
cd shellbuddy
./install.sh
```

The interactive installer checks dependencies, copies runtime scripts to `~/.shellbuddy/`, and adds the initialization block to `~/.zshrc`.

### Launching in tmux

```bash
source ~/.zshrc
tmux new -s dev
sb
```

*Press `Ctrl+A H` (or run `sb` again) to toggle the hints pane on or off.*

---

## 7. Interactive Demonstration & Smoke Test

You can benchmark and test the local Knowledge Base Engine immediately without starting a daemon or tmux session:

```bash
make demo
# Or: python3 scripts/demo.py --sample
```

To enter an interactive prompt to test arbitrary commands in real time:

```bash
python3 scripts/demo.py
# shellbuddy> rm -rf /
# [DANGER] !! Never run 'rm -rf /' — it erases your entire filesystem. (gnu-001) [8.5 µs]
```

### Developer Commands (`Makefile`)

```bash
make test      # Run full 139-test suite
make lint      # Syntax-check all Python modules
make demo      # Run standalone KB dispatch engine demo and micro-benchmark
make dist      # Build distribution archive
```

---

## 8. Limitations & Known Issues

- **Shell Support:** Optimized for `zsh`. `bash` and `fish` support are currently not implemented for the `preexec` logger.
- **Copilot Backend:** The automatic VS Code credential extractor is currently tuned for macOS credential stores. On Linux, use Ollama, Claude (`ANTHROPIC_API_KEY`), or OpenAI-compatible backends.
- **Terminal Width:** A minimum width of 80 columns is recommended for the hints and stats panes.

---

## 9. Contributing & Reporting Issues

Contributions are welcome! Please adhere to the following workflow:
1. Fork the repository and create a feature branch (`git checkout -b feat/my-rule`).
2. If adding KB rules, edit the source definitions and run `make build-kb` (do not hand-edit `kb.json`).
3. Ensure all tests pass: `make test && make lint`.
4. Open a Pull Request with a clear description and sample commands tested.

---

## 10. License

Released under the [MIT License](LICENSE). Copyright © D K Bhargav Achary.
