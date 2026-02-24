#!/usr/bin/env python3
"""
shellbuddy — hint_daemon.py
Ambient terminal coaching daemon.

Watches your command log, matches patterns against upgrade rules,
and periodically queries an AI backend for contextual hints.

Supports per-role backend configuration via ~/.shellbuddy/config.json:
  {
    "hint_backend": "ollama",   "hint_model": "qwen3:4b",
    "tip_backend":  "claude",   "tip_model":  "claude-sonnet-4-5-20250514"
  }

Backends: ollama, claude, copilot, openai (any OpenAI-compatible endpoint)
"""

import os, sys, time, json, subprocess, re, urllib.request, urllib.error
from pathlib import Path
from collections import Counter
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

DATA_DIR    = Path(os.environ.get("SHELLBUDDY_DIR", str(Path.home() / ".shellbuddy")))
CONFIG_FILE = DATA_DIR / "config.json"
CMD_LOG     = DATA_DIR / "cmd_log.jsonl"
HINTS_OUT   = DATA_DIR / "current_hints.txt"
LOCK_FILE   = DATA_DIR / "daemon.pid"
TIP_QUERY   = DATA_DIR / "tip_query.txt"
TIP_RESULT  = DATA_DIR / "tip_result.txt"

# Defaults (overridden by config.json)
HINT_BACKEND    = "ollama"
HINT_MODEL      = "qwen3:4b"
TIP_BACKEND     = "ollama"
TIP_MODEL       = "qwen3:8b"
OLLAMA_URL      = "http://localhost:11434"
CLAUDE_MODEL    = "claude-haiku-4-5-20251001"   # fallback for hint if claude chosen
COPILOT_MODEL   = "gpt-4.1"
OPENAI_URL      = "https://api.openai.com/v1"
OPENAI_MODEL    = "gpt-4o-mini"

POLL_INTERVAL   = 1     # seconds between tip checks (fast response)
HINT_INTERVAL   = 5     # seconds between hint log checks (background)
AI_THROTTLE     = 25    # seconds between AI hint calls (not /tip)
WINDOW          = 15    # last N commands to analyse
MIN_COMMANDS    = 2     # don't hint until this many commands seen
MAX_HINT_LINES  = 10    # lines in tmux pane (excluding header + separator)
RULE_COOLDOWN   = 120   # seconds before re-showing the same rule hint
OLLAMA_TIMEOUT  = 90    # seconds for ollama generate (cold model load is slow)

# Add repo root to path so we can import backends/
_SCRIPT_DIR = Path(__file__).resolve().parent
for _candidate in [_SCRIPT_DIR.parent, _SCRIPT_DIR]:
    if (_candidate / "backends").is_dir():
        sys.path.insert(0, str(_candidate))
        break


def _load_config():
    """Load config.json and override defaults."""
    global HINT_BACKEND, HINT_MODEL, TIP_BACKEND, TIP_MODEL
    global OLLAMA_URL, CLAUDE_MODEL, COPILOT_MODEL, OPENAI_URL, OPENAI_MODEL

    if not CONFIG_FILE.exists():
        return

    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except Exception as e:
        print(f"  warning: bad config.json — {e}", flush=True)
        return

    HINT_BACKEND = cfg.get("hint_backend", HINT_BACKEND)
    HINT_MODEL   = cfg.get("hint_model",   HINT_MODEL)
    TIP_BACKEND  = cfg.get("tip_backend",  TIP_BACKEND)
    TIP_MODEL    = cfg.get("tip_model",    TIP_MODEL)
    OLLAMA_URL   = cfg.get("ollama_url",   OLLAMA_URL)
    CLAUDE_MODEL = cfg.get("claude_model", CLAUDE_MODEL)
    COPILOT_MODEL = cfg.get("copilot_model", COPILOT_MODEL)
    OPENAI_URL   = cfg.get("openai_url",   OPENAI_URL)
    OPENAI_MODEL = cfg.get("openai_model", OPENAI_MODEL)


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND AVAILABILITY (probe once at startup)
# ═══════════════════════════════════════════════════════════════════════════════

_AVAILABLE_BACKENDS = set()

def _probe_backends():
    """Check which backends are actually reachable."""
    # Copilot
    try:
        from backends.copilot import is_available as copilot_available
        if copilot_available():
            _AVAILABLE_BACKENDS.add("copilot")
    except Exception:
        pass

    # Claude — check for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-s", "anthropic", "-a", "api_key", "-w"],
                capture_output=True, text=True, timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                api_key = result.stdout.strip()
        except Exception:
            pass
    if api_key:
        _AVAILABLE_BACKENDS.add("claude")
        os.environ["_SB_CLAUDE_KEY"] = api_key

    # OpenAI-compatible — check for API key
    if os.environ.get("OPENAI_API_KEY", ""):
        _AVAILABLE_BACKENDS.add("openai")

    # Ollama — check if server responds
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
        _AVAILABLE_BACKENDS.add("ollama")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  UPGRADE RULES — (regex, hint_template)
#  {arg} is replaced with the first argument the user passed.
# ═══════════════════════════════════════════════════════════════════════════════

UPGRADE_RULES = [
    # ── Navigation ───────────────────────────────────────────────────────────
    (r"^cd\s+",              "cd → z {arg}  (zoxide: learns your paths)"),
    (r"^pushd\b",            "pushd → z -  (zoxide: go back)"),

    # ── File viewing ─────────────────────────────────────────────────────────
    (r"^cat\s+",             "cat → bat {arg}  (syntax highlighting + git diff)"),
    (r"^less\s+",            "less → bat {arg}  (bat -p for raw paging)"),
    (r"^head\s+",            "head → bat --line-range :20 {arg}"),
    (r"^tail\s+-f\s+",       "tail -f → bat --paging never {arg}  (live + colour)"),

    # ── Listing ──────────────────────────────────────────────────────────────
    (r"^ls\b",               "ls → eza -la --git --icons"),
    (r"^ls -la?\b",          "ls -l → eza -la --git --icons --time-style=relative"),

    # ── Search ───────────────────────────────────────────────────────────────
    (r"^grep\s+",            "grep → rg '{arg}'  (10x faster, .gitignore aware)"),
    (r"^grep -r\s+",         "grep -r → rg '{arg}'  (recursive by default)"),
    (r"^find\s+",            "find → fd '{arg}'  (simpler syntax, auto .gitignore)"),
    (r"^ack\s+",             "ack → rg '{arg}'  (ripgrep is faster)"),
    (r"^locate\b",           "locate → fd '{arg}'  (no updatedb needed)"),

    # ── Disk / system ────────────────────────────────────────────────────────
    (r"^du\s+",              "du → dust  (visual tree, human-readable)"),
    (r"^df\b",               "df → duf  (colourful disk free overview)"),
    (r"^top\b",              "top → btm  (vim keys, multiple panels)"),
    (r"^htop\b",             "htop → btm  (vim keys, more panels)"),
    (r"^ps aux\b",           "ps aux → procs  (searchable, sortable, tree)"),
    (r"^kill -9\s+",         "kill -9 → kill -TERM first (graceful shutdown)"),
    (r"^rm -rf\s+",          "rm -rf → trash {arg}  (recoverable via Trash)"),
    (r"^rm\s+",              "rm → trash {arg}  (recoverable via macOS Trash)"),

    # ── Git ──────────────────────────────────────────────────────────────────
    (r"^git log\b",          "git log → lazygit  (TUI: full log, diff, branch)"),
    (r"^git add\b",          "git add → lazygit  (space to stage hunks)"),
    (r"^git diff\b",         "git diff → delta pager active — just: git diff"),
    (r"^git status\b",       "git status → gs  (alias) or lazygit"),
    (r"^git stash\b",        "git stash → lazygit  (stash tab: s/space)"),
    (r"^git commit -m\b",    "git commit -m → lazygit  (write in editor)"),
    (r"^git checkout\b",     "git checkout → git switch / git restore"),
    (r"^git branch -a\b",    "git branch -a → lazygit  (branch panel: b)"),
    (r"^git push origin\b",  "git push origin → gp  (alias, or lazygit: P)"),
    (r"^git pull\b",         "git pull → gp (rebase set in .gitconfig)"),
    (r"^git clone\b",        "after clone → gh repo clone (GitHub CLI)"),
    (r"^git reset --hard\b", "git reset --hard → git uncommit  (alias, safer)"),

    # ── GitHub ───────────────────────────────────────────────────────────────
    (r"^hub\s+",             "hub → gh {arg}  (official GitHub CLI)"),

    # ── History ──────────────────────────────────────────────────────────────
    (r"^history\b",          "history → atuin search  (Ctrl+R: ranked fuzzy)"),
    (r"^!!\b",               "!! → Esc+Esc (thefuck) or Ctrl+R to find it"),

    # ── Python / conda ───────────────────────────────────────────────────────
    (r"^pip\s+install",      "pip install → conda install {arg}  (env-safe)"),
    (r"^pip3\s+install",     "pip3 install → conda install {arg}  (env-safe)"),
    (r"^pip\s+",             "pip → uv pip {arg}  (10x faster, or conda)"),
    (r"^python3?\s+(?!-)",   "python → conda activate <env> first?"),
    (r"^ipython\b",          "ipython → jupyter console  (or: jupyter lab)"),
    (r"^flake8\b",           "flake8 → ruff check  (100x faster linting)"),
    (r"^pylint\b",           "pylint → ruff check  (100x faster, drop-in)"),
    (r"^autopep8\b",         "autopep8 → black {arg}  (zero-config formatter)"),
    (r"^yapf\b",             "yapf → black {arg}  (opinionated, consistent)"),
    (r"^virtualenv\b",       "virtualenv → conda create -n {arg}"),
    (r"^python3? -m venv\b", "venv → conda create -n <name>  (isolated)"),
    (r"^pytest\b.*-v",       "try: pytest --tb=short  (concise tracebacks)"),
    (r"^jupyter notebook\b", "jupyter notebook → jupyter lab  (better UI)"),

    # ── Node / JS ────────────────────────────────────────────────────────────
    (r"^npm install\b",      "npm install → pnpm install  (faster + saves disk)"),
    (r"^npm run\b",          "npm run → use: just <task>  (if justfile exists)"),
    (r"^npx\b",              "npx → pnpm dlx {arg}  (faster, cached)"),

    # ── Editors ──────────────────────────────────────────────────────────────
    (r"^nano\s+",            "nano → vim {arg}  (or: code {arg})"),
    (r"^vi\s+",              "vi → vim {arg}  (modern vim has syntax, undo tree)"),

    # ── Network & API ────────────────────────────────────────────────────────
    (r"^curl\s+.*json",      "curl + json → http {arg}  (httpie: auto-format)"),
    (r"^curl\s+",            "curl → http {arg}  (httpie: more readable)"),
    (r"^wget\s+",            "wget → curl -LO {arg}  (curl is more portable)"),
    (r"^ssh\s+",             "ssh → mosh {arg}  (reconnects on flaky networks)"),
    (r"^dig\s+",             "dig → dog {arg}  (colourful DNS, or: drill)"),
    (r"^nslookup\b",         "nslookup → dig {arg}  (more detail, scriptable)"),
    (r"^traceroute\b",       "traceroute → mtr {arg}  (live, combined view)"),
    (r"^ping\s+-c",          "also try: mtr {arg}  (traceroute + ping in one)"),

    # ── JSON / data ──────────────────────────────────────────────────────────
    (r"^python3? -c.*json",  "json parsing → jq  (pipe: curl | jq '.')"),
    (r"^python3? -m json",   "python json → jq '.'  (faster, no Python needed)"),

    # ── Docker ───────────────────────────────────────────────────────────────
    (r"^docker ps\b",        "docker ps → lazydocker  (full TUI)"),
    (r"^docker logs\b",      "docker logs → lazydocker  (live log + filter)"),
    (r"^docker-compose\b",   "docker-compose → docker compose  (v2 built-in)"),
    (r"^docker images\b",    "docker images → dive <img>  (inspect layers)"),
    (r"^docker build\b",     "also try: docker buildx  (multi-platform builds)"),

    # ── Kubernetes ───────────────────────────────────────────────────────────
    (r"^kubectl get\b",      "kubectl get → k9s  (live TUI, press : to filter)"),
    (r"^kubectl logs\b",     "kubectl logs → k9s  (logs pane: l key)"),
    (r"^kubectl exec\b",     "kubectl exec → k9s  (shell pane: s key)"),
    (r"^kubectl apply\b",    "kubectl apply → k9s  (YAML tab: y key)"),

    # ── Infrastructure ───────────────────────────────────────────────────────
    (r"^aws s3\b",           "aws s3 → s5cmd  (50-100x faster for S3 ops)"),
    (r"^terraform plan\b",   "tf plan → terraform plan -out=plan.tfplan"),
    (r"^terraform apply\b",  "tf apply → terraform apply plan.tfplan (safer)"),

    # ── File operations ──────────────────────────────────────────────────────
    (r"^wc -l\b",            "wc -l → tokei  (counts code lines by language)"),
    (r"^cloc\b",             "cloc → tokei  (10x faster, same output)"),
    (r"^sed\s+",             "sed → sd '{arg}'  (simpler regex replace)"),
    (r"^rename\b.*\.",       "try: rename with regex — rename 's/old/new/' *"),
    (r"^tar\s+.*xf",        "tip: tar xf auto-detects .gz .bz2 .xz (no flags)"),
    (r"^zip\s+",             "also: tar czf archive.tar.gz dir/  (more unix)"),

    # ── Benchmarking & profiling ─────────────────────────────────────────────
    (r"^time\s+",            "time → hyperfine '{arg}'  (statistical benchmark)"),

    # ── macOS-specific ───────────────────────────────────────────────────────
    (r"^open\s+\.",          "open . → lt  (eza tree) or code ."),
    (r"^man\s+",             "man → tldr {arg}  (example-first man pages)"),
    (r"^pbcopy\b",           "tip: echo 'text' | pbcopy  (clipboard from pipe)"),
    (r"^defaults\b",         "defaults → remember: killall cfprefsd after"),
    (r"^sw_vers\b",          "also: system_profiler SPHardwareDataType"),
    (r"^diskutil\b",         "tip: diskutil list for all disks, info for detail"),
    (r"^launchctl\b",        "tip: launchctl list | rg <name> to find services"),

    # ── VHDL / FPGA ─────────────────────────────────────────────────────────
    (r"^ghdl\s+",            "ghdl → make  (Makefile for reproducible GHDL runs)"),
    (r"^gtkwave\s+",         "gtkwave → add sim target to Makefile"),
    (r"^vivado\b",           "vivado → Tcl batch mode for repeatable builds"),

    # ── Documentation ────────────────────────────────────────────────────────
    (r"^cat\s+.*\.md\b",     "cat .md → glow {arg}  (rendered Markdown in terminal)"),
    (r"^pdftotext\b",        "pdftotext → pdfgrep {arg}  (search inside PDFs)"),
]

# ═══════════════════════════════════════════════════════════════════════════════
#  PROJECT TYPE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

PROJECT_INDICATORS = [
    ("pyproject.toml",     "Python"),
    ("requirements.txt",   "Python"),
    ("setup.py",           "Python"),
    ("package.json",       "Node.js"),
    ("Cargo.toml",         "Rust"),
    ("go.mod",             "Go"),
    ("Gemfile",            "Ruby"),
    ("Makefile",           "Make"),
    ("justfile",           "just"),
    ("docker-compose.yml", "Docker"),
    ("Dockerfile",         "Docker"),
    (".git",               "git repo"),
]

# ═══════════════════════════════════════════════════════════════════════════════
#  AI BACKENDS
# ═══════════════════════════════════════════════════════════════════════════════

def _call_copilot(prompt, model=None):
    """Call Copilot backend."""
    try:
        from backends.copilot import call_copilot
        return call_copilot(prompt, model=model or COPILOT_MODEL)
    except Exception:
        return None


def _call_claude(prompt, model=None):
    """Call Claude API backend."""
    api_key = os.environ.get("_SB_CLAUDE_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None

    model = model or CLAUDE_MODEL
    max_tokens = 1024 if "sonnet" in model or "opus" in model else 500

    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["content"][0]["text"].strip()
    except Exception as e:
        print(f"  claude error: {e}", flush=True)
        return None


def _call_ollama(prompt, model=None):
    """Call Ollama backend with thinking support."""
    model = model or TIP_MODEL
    # Enable thinking for qwen3/deepseek-r1 models
    think = any(t in model for t in ["qwen3", "deepseek-r1"])
    options = {"temperature": 0.7 if think else 0.3, "num_predict": 800 if think else 500}

    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": options,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            text = json.loads(resp.read()).get("response", "").strip()

        # Strip <think>...</think> reasoning blocks (qwen3, deepseek-r1)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return text
    except Exception as e:
        print(f"  ollama error: {e}", flush=True)
        return None


def _call_openai(prompt, model=None):
    """Call any OpenAI-compatible endpoint (OpenAI, Groq, Together, etc.)."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None

    model = model or OPENAI_MODEL
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
        "temperature": 0.3,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{OPENAI_URL}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  openai error: {e}", flush=True)
        return None


def _call_backend(backend, prompt, model=None):
    """Route a prompt to the specified backend."""
    if backend == "copilot":
        return _call_copilot(prompt, model=model)
    elif backend == "claude":
        return _call_claude(prompt, model=model)
    elif backend == "ollama":
        return _call_ollama(prompt, model=model)
    elif backend == "openai":
        return _call_openai(prompt, model=model)
    return None


def call_ai_hint(prompt):
    """Call the hint backend (ambient hints in tmux pane)."""
    if HINT_BACKEND not in _AVAILABLE_BACKENDS:
        return ""
    return _call_backend(HINT_BACKEND, prompt, model=HINT_MODEL) or ""


def call_ai_tip(prompt):
    """Call the tip backend (/tip on-demand queries)."""
    if TIP_BACKEND not in _AVAILABLE_BACKENDS:
        return ""
    return _call_backend(TIP_BACKEND, prompt, model=TIP_MODEL) or ""


# ═══════════════════════════════════════════════════════════════════════════════
#  HINT PROMPT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _detect_intent(cmds):
    """Infer what the user is trying to do from recent commands."""
    texts = [c.get("cmd", "") for c in cmds[-6:]]
    joined = " ".join(texts).lower()

    if any(w in joined for w in ["git add", "git commit", "git push", "git diff"]):
        return "committing/pushing code"
    if any(w in joined for w in ["pytest", "test", "npm test", "cargo test"]):
        return "running tests"
    if any(w in joined for w in ["docker", "compose", "kubectl"]):
        return "working with containers/infra"
    if any(w in joined for w in ["pip install", "conda install", "npm install", "brew install"]):
        return "installing dependencies"
    if any(w in joined for w in ["ssh", "scp", "rsync"]):
        return "working with remote servers"
    if any(w in joined for w in ["vim", "nano", "code", "edit"]):
        return "editing files"
    if texts.count(texts[-1]) >= 2 if texts else False:
        return "retrying a failing command"
    return None


def build_hint_prompt(recent_cmds, cwd):
    cwd_path = Path(cwd)
    project_signals = []
    for indicator, lang in PROJECT_INDICATORS:
        if (cwd_path / indicator).exists():
            project_signals.append(lang)

    cmd_summary = "\n".join(
        f"  {c.get('ts', '')[-8:]}  {c.get('cmd', '')}" for c in recent_cmds[-10:]
    )

    project_ctx = ", ".join(dict.fromkeys(project_signals)) or "general"
    intent = _detect_intent(recent_cmds)

    prompt = (
        "You are an ambient terminal coach. A developer is working in their shell.\n"
        "Analyse their recent commands, understand what they're trying to do, "
        "and give 2-3 SPECIFIC, actionable hints to help them work faster.\n\n"
        f"Directory: {cwd}\n"
        f"Project: {project_ctx}\n"
    )
    if intent:
        prompt += f"They appear to be: {intent}\n"
    prompt += (
        f"Recent commands (oldest to newest):\n{cmd_summary}\n\n"
        "Rules:\n"
        "- Each hint on ONE line, max 70 chars\n"
        "- Use exact paths/filenames from their commands\n"
        "- Prioritise: faster alternatives, missing flags, common mistakes\n"
        "- If they're retrying something, suggest what might fix it\n"
        "- No bullets, no markdown, no greetings\n"
        "- Max 5 lines total\n"
        "- If workflow looks fine: Good flow — keep going\n"
    )
    return prompt


# ═══════════════════════════════════════════════════════════════════════════════
#  /tip QUERY HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

def build_tip_prompt(query):
    # Gather context for richer answers
    cwd = "~"
    shell_info = "zsh on macOS"
    recent_ctx = ""
    try:
        if CMD_LOG.exists():
            lines = CMD_LOG.read_text().strip().splitlines()[-5:]
            recent = [json.loads(l) for l in lines if l.strip()]
            if recent:
                cwd = recent[-1].get("cwd", "~")
                recent_ctx = "\n".join(f"  {c.get('cmd', '')}" for c in recent)
    except Exception:
        pass

    prompt = (
        "You are a senior terminal/CLI expert. Think carefully about the question, "
        "then give a precise, practical answer.\n\n"
        f"Environment: {shell_info}\n"
        f"Working directory: {cwd}\n"
    )
    if recent_ctx:
        prompt += f"Recent commands (for context):\n{recent_ctx}\n"
    prompt += (
        "\nRules:\n"
        "- Give the exact command(s) first, then a brief explanation\n"
        "- For multi-step tasks, number the steps\n"
        "- Show common flags and variations when relevant\n"
        "- If the question relates to the recent commands above, use that context\n"
        "- Max 15 lines total\n"
        "- No markdown formatting, no code fences\n"
        "- Use macOS/zsh conventions\n\n"
        f"Question: {query}\n"
    )
    return prompt


def handle_tip_query():
    """Check for a pending /tip query and process it."""
    if not TIP_QUERY.exists():
        return False
    try:
        query = TIP_QUERY.read_text().strip()
        TIP_QUERY.unlink(missing_ok=True)
        if not query:
            return False

        print(f"  /tip query: {query!r}", flush=True)

        # Check if backend is available
        if TIP_BACKEND not in _AVAILABLE_BACKENDS:
            TIP_RESULT.write_text(
                f"[{TIP_BACKEND} not available — check config.json or start ollama]"
            )
            return True

        prompt = build_tip_prompt(query)
        result = call_ai_tip(prompt)
        if not result:
            result = f"[{TIP_BACKEND}:{TIP_MODEL} returned empty — check: hints-log]"

        # Atomic write: tmp → rename
        tmp = TIP_RESULT.with_suffix(".tmp")
        tmp.write_text(result)
        tmp.rename(TIP_RESULT)
        print(f"  /tip result written ({len(result)} chars)", flush=True)
        return True
    except Exception as e:
        print(f"  /tip error: {e}", flush=True)
        TIP_RESULT.write_text(f"[error: {e}]")
        return True


# ═══════════════════════════════════════════════════════════════════════════════
#  RULE HINTS
# ═══════════════════════════════════════════════════════════════════════════════

def get_rule_hints(recent_cmds, last_shown):
    cmd_texts = [c.get("cmd", "") for c in recent_cmds]
    freq = Counter()
    matches = {}

    for cmd in cmd_texts:
        for pattern, hint_tmpl in UPGRADE_RULES:
            if re.match(pattern, cmd.strip()):
                freq[pattern] += 1
                matches[pattern] = (hint_tmpl, cmd.strip())

    now = time.time()
    hints = []
    for pattern, count in sorted(freq.items(), key=lambda x: -x[1]):
        if len(hints) >= 3:
            break
        if now - last_shown.get(pattern, 0) < RULE_COOLDOWN:
            continue
        tmpl, example = matches[pattern]
        arg = re.sub(r"^\S+\s*", "", example)[:40]
        hint = tmpl.replace("{arg}", arg or "...").replace("{pattern}", arg or "...")
        hints.append((pattern, f"[{count}x] {hint}"))

    return hints


# ═══════════════════════════════════════════════════════════════════════════════
#  HINTS OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

def write_hints(rule_hints, ai_hints, cwd, cmd_count, thinking=False):
    ts = datetime.now().strftime("%H:%M:%S")
    cwd_short = str(Path(cwd)).replace(str(Path.home()), "~")
    lines = [f"HINTS  {cwd_short}  [{ts}]  ({cmd_count} cmds)", "─" * 58]

    hint_strs = [h for _, h in rule_hints]
    for h in hint_strs[:3]:
        lines.append(h)

    if thinking and not ai_hints:
        # Show thinking indicator while AI is processing
        if hint_strs:
            lines.append("·")
        lines.append("thinking ...")
    elif ai_hints:
        ai_lines = [l.strip() for l in ai_hints.splitlines() if l.strip()][:5]
        if ai_lines:
            if hint_strs:
                lines.append("·")
            for h in ai_lines:
                lines.append(h[:65])

    while len(lines) < MAX_HINT_LINES + 2:
        lines.append("")

    HINTS_OUT.write_text("\n".join(lines[:MAX_HINT_LINES + 2]))


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))

    # Load config and probe available backends
    _load_config()
    _probe_backends()

    last_cmd_count  = 0
    last_ai_call    = 0.0
    last_cwd        = ""
    last_ai_text    = ""
    last_hint_check = 0.0
    rule_last_shown = {}

    print(f"shellbuddy daemon started (PID {os.getpid()})", flush=True)
    print(f"  available backends: {', '.join(sorted(_AVAILABLE_BACKENDS)) or 'none'}", flush=True)
    print(f"  hint: {HINT_BACKEND} / {HINT_MODEL}"
          f"{'' if HINT_BACKEND in _AVAILABLE_BACKENDS else ' (NOT AVAILABLE)'}", flush=True)
    print(f"  /tip: {TIP_BACKEND} / {TIP_MODEL}"
          f"{'' if TIP_BACKEND in _AVAILABLE_BACKENDS else ' (NOT AVAILABLE)'}", flush=True)
    if not _AVAILABLE_BACKENDS:
        print(f"  WARNING: no AI backend available — /tip will not work", flush=True)
        print(f"  start ollama:  brew services start ollama", flush=True)
        print(f"  or configure:  edit {CONFIG_FILE}", flush=True)

    try:
        while True:
            # Handle /tip queries with priority — check every POLL_INTERVAL
            handle_tip_query()

            # Hint generation runs less frequently
            now = time.time()
            if (now - last_hint_check) < HINT_INTERVAL:
                time.sleep(POLL_INTERVAL)
                continue
            last_hint_check = now

            if not CMD_LOG.exists():
                time.sleep(POLL_INTERVAL)
                continue

            try:
                lines = CMD_LOG.read_text().strip().splitlines()[-WINDOW:]
                recent = [json.loads(l) for l in lines if l.strip()]
            except Exception:
                time.sleep(POLL_INTERVAL)
                continue

            current_count = len(recent)
            cwd = recent[-1].get("cwd", str(Path.home())) if recent else str(Path.home())

            has_new     = current_count != last_cmd_count
            cwd_changed = cwd != last_cwd
            ai_ready    = (time.time() - last_ai_call) > AI_THROTTLE

            if (has_new or cwd_changed) and current_count >= MIN_COMMANDS:
                rule_hints = get_rule_hints(recent, rule_last_shown)

                for pattern, _ in rule_hints:
                    rule_last_shown[pattern] = time.time()

                if ai_ready and (has_new or cwd_changed):
                    # Show rules + "thinking..." immediately
                    write_hints(rule_hints, "", cwd, current_count, thinking=True)

                    prompt = build_hint_prompt(recent, cwd)
                    last_ai_text = call_ai_hint(prompt)
                    last_ai_call = time.time()

                write_hints(rule_hints, last_ai_text, cwd, current_count)
                last_cmd_count = current_count
                last_cwd = cwd

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        LOCK_FILE.unlink(missing_ok=True)
        print("shellbuddy daemon stopped.", flush=True)


if __name__ == "__main__":
    run()
