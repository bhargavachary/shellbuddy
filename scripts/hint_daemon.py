#!/usr/bin/env python3
"""
shellbuddy — hint_daemon.py
Ambient terminal coaching daemon. 3-layer architecture:

  Layer 1 — Regex Reflex  (<10ms, instant rule hints)
  Layer 2 — Async Advisor (background thread, every command debounced)
  Layer 3 — /tip Expert   (on-demand, uses full unified session context)

Config: ~/.shellbuddy/config.json
  {
    "hint_backend":       "copilot",
    "hint_model":         "gpt-5-mini",
    "hint_model_chain":   ["gpt-5-mini", "raptor-mini", "gpt-4.1"],
    "tip_backend":        "copilot",
    "tip_model":          "gpt-4.1"
  }

Backends: ollama, claude, copilot, openai
Post-mortem: auto-drafted commit messages on git commit (uses hint_model_chain)
"""

import os, sys, time, json, subprocess, re, urllib.request, urllib.error, threading
from pathlib import Path
from collections import Counter, deque
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

DATA_DIR         = Path(os.environ.get("SHELLBUDDY_DIR", str(Path.home() / ".shellbuddy")))
CONFIG_FILE      = DATA_DIR / "config.json"
CMD_LOG          = DATA_DIR / "cmd_log.jsonl"
HINTS_OUT        = DATA_DIR / "current_hints.txt"
LOCK_FILE        = DATA_DIR / "daemon.pid"
TIP_QUERY        = DATA_DIR / "tip_query.txt"
TIP_RESULT       = DATA_DIR / "tip_result.txt"
UNIFIED_CTX      = DATA_DIR / "unified_context.jsonl"  # single truth: rules+ambient+tips

# Defaults (overridden by config.json)
HINT_BACKEND    = "copilot"
HINT_MODEL      = "gpt-5-mini"
HINT_MODEL_CHAIN = ["gpt-5-mini", "raptor-mini", "gpt-4.1"]  # fallback chain for ambient
TIP_BACKEND     = "copilot"
TIP_MODEL       = "gpt-4.1"
OLLAMA_URL      = "http://localhost:11434"
CLAUDE_MODEL    = "claude-haiku-4-5-20251001"
COPILOT_MODEL   = "gpt-5-mini"
OPENAI_URL      = "https://api.openai.com/v1"
OPENAI_MODEL    = "gpt-4o-mini"

POLL_INTERVAL    = 1      # seconds between tip checks
HINT_INTERVAL    = 5      # seconds between hint log checks
AI_THROTTLE      = 25     # seconds between ambient LLM hint calls
ADVISOR_EVERY    = 1      # advisor fires every new command (debounced)
ADVISOR_THROTTLE = 5      # min seconds between advisor calls
WINDOW           = 50     # commands sent to ambient LLM
ADVISOR_WINDOW   = 100    # commands the advisor sees
MIN_COMMANDS     = 2
MAX_HINT_LINES   = 10
RULE_COOLDOWN    = 120
OLLAMA_TIMEOUT   = 90
CTX_MAX          = 200    # max lines kept in unified_context.jsonl
CTX_INJECT       = 30     # last N unified context entries injected into prompts

# Add repo root to path so we can import backends/ and kb_engine
_SCRIPT_DIR = Path(__file__).resolve().parent
for _candidate in [_SCRIPT_DIR.parent, _SCRIPT_DIR]:
    if (_candidate / "backends").is_dir():
        sys.path.insert(0, str(_candidate))
        break

# KB engine — try to load; falls back to legacy UPGRADE_RULES if kb.json absent
_KB_ENGINE = None
try:
    from kb_engine import KBEngine as _KBEngine
    _KB_ENGINE = _KBEngine()
except Exception as _e:
    print(f"  kb_engine not loaded ({_e}), using legacy rules", flush=True)


def _load_config():
    global HINT_BACKEND, HINT_MODEL, TIP_BACKEND, TIP_MODEL
    global OLLAMA_URL, CLAUDE_MODEL, COPILOT_MODEL, OPENAI_URL, OPENAI_MODEL

    if not CONFIG_FILE.exists():
        return
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except Exception as e:
        print(f"  warning: bad config.json — {e}", flush=True)
        return

    HINT_BACKEND       = cfg.get("hint_backend",       HINT_BACKEND)
    HINT_MODEL         = cfg.get("hint_model",         HINT_MODEL)
    HINT_MODEL_CHAIN   = cfg.get("hint_model_chain",   HINT_MODEL_CHAIN)
    TIP_BACKEND        = cfg.get("tip_backend",        TIP_BACKEND)
    TIP_MODEL          = cfg.get("tip_model",          TIP_MODEL)
    OLLAMA_URL         = cfg.get("ollama_url",         OLLAMA_URL)
    CLAUDE_MODEL       = cfg.get("claude_model",       CLAUDE_MODEL)
    COPILOT_MODEL      = cfg.get("copilot_model",      COPILOT_MODEL)
    OPENAI_URL         = cfg.get("openai_url",         OPENAI_URL)
    OPENAI_MODEL       = cfg.get("openai_model",       OPENAI_MODEL)


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND AVAILABILITY
# ═══════════════════════════════════════════════════════════════════════════════

_AVAILABLE_BACKENDS = set()

def _probe_backends():
    try:
        from backends.copilot import is_available as copilot_available
        if copilot_available():
            _AVAILABLE_BACKENDS.add("copilot")
    except Exception:
        pass

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

    if os.environ.get("OPENAI_API_KEY", ""):
        _AVAILABLE_BACKENDS.add("openai")

    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3)
        _AVAILABLE_BACKENDS.add("ollama")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  LAYER 1 — UPGRADE RULES (regex reflex, <10ms)
# ═══════════════════════════════════════════════════════════════════════════════

UPGRADE_RULES = [
    # ── Safety / precondition warnings ───────────────────────────────────────
    (r"^rm\s+-rf\s+[/~]\s*$",       "DANGER: rm -rf / or ~ — this will destroy your system"),
    (r"^rm\s+-rf\s+\.\s*$",         "DANGER: rm -rf . deletes everything in current dir"),
    (r"^git\s+commit\s+(?!.*-m\b)", "git commit: missing -m flag — add a message"),
    (r"^npm\s+install\b",           "npm install: check package.json exists first (ls package.json)"),
    (r"^pip\s+install\b(?!.*\s-r)", "pip install: outside a conda/venv env? (conda activate <env>)"),
    (r"^git\s+push.*--force\b",     "git push --force: prefer --force-with-lease (safer)"),
    (r"^chmod\s+777\b",             "chmod 777: overly permissive — prefer 755 (dirs) or 644 (files)"),
    (r"^sudo\s+rm\b",               "sudo rm: double-check path before running as root"),

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
    (r"^tar\s+.*xf",         "tip: tar xf auto-detects .gz .bz2 .xz (no flags)"),
    (r"^zip\s+",             "also: tar czf archive.tar.gz dir/  (more unix)"),

    # ── Benchmarking ─────────────────────────────────────────────────────────
    (r"^time\s+",            "time → hyperfine '{arg}'  (statistical benchmark)"),

    # ── macOS-specific ───────────────────────────────────────────────────────
    (r"^open\s+\.",          "open . → lt  (eza tree) or code ."),
    (r"^man\s+",             "man → tldr {arg}  (example-first man pages)"),
    (r"^pbcopy\b",           "tip: echo 'text' | pbcopy  (clipboard from pipe)"),
    (r"^defaults\b",         "defaults → remember: killall cfprefsd after"),
    (r"^sw_vers\b",          "also: system_profiler SPHardwareDataType"),
    (r"^diskutil\b",         "tip: diskutil list for all disks, info for detail"),
    (r"^launchctl\b",        "tip: launchctl list | rg <name> to find services"),

    # ── VHDL / FPGA ──────────────────────────────────────────────────────────
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

def _call_copilot(prompt, model=None, max_tokens=150):
    try:
        from backends.copilot import call_copilot
        return call_copilot(prompt, model=model or COPILOT_MODEL, max_tokens=max_tokens)
    except Exception:
        return None


def _call_copilot_chain(prompt, models=None, max_tokens=150):
    """Try each model in the chain; return first successful result."""
    chain = models or HINT_MODEL_CHAIN
    for model in chain:
        result = _call_copilot(prompt, model=model, max_tokens=max_tokens)
        if result:
            return result
    return None


def _call_claude(prompt, model=None):
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
    model = model or TIP_MODEL
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
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        return text
    except Exception as e:
        print(f"  ollama error: {e}", flush=True)
        return None


def _call_openai(prompt, model=None):
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
    """Call ambient hint model. Uses model chain for copilot (gpt-5-mini → raptor-mini → gpt-4.1)."""
    if HINT_BACKEND not in _AVAILABLE_BACKENDS:
        return ""
    if HINT_BACKEND == "copilot":
        return _call_copilot_chain(prompt, models=HINT_MODEL_CHAIN, max_tokens=300) or ""
    return _call_backend(HINT_BACKEND, prompt, model=HINT_MODEL) or ""


def call_ai_tip(prompt):
    if TIP_BACKEND not in _AVAILABLE_BACKENDS:
        return ""
    return _call_backend(TIP_BACKEND, prompt, model=TIP_MODEL) or ""


# ═══════════════════════════════════════════════════════════════════════════════
#  UNIFIED CONTEXT LOG
#  Single append-only JSONL. Every event written here:
#    {"ts":"18:31","type":"cmd",     "cmd":"git push --force"}
#    {"ts":"18:31","type":"rule",    "severity":"danger","hint":"...","detail":"..."}
#    {"ts":"18:31","type":"ambient", "text":"..."}
#    {"ts":"18:32","type":"advisor", "intent":"...","observation":"...","prediction":"..."}
#    {"ts":"18:33","type":"tip_q",   "query":"..."}
#    {"ts":"18:33","type":"tip_a",   "text":"..."}
#  Both ambient LLM and /tip read this for context. Ring-trimmed to CTX_MAX lines.
# ═══════════════════════════════════════════════════════════════════════════════

_ctx_lock = threading.Lock()


def ctx_append(entry: dict):
    """Append one event to unified_context.jsonl. Thread-safe. Trims to CTX_MAX."""
    entry["ts"] = datetime.now().strftime("%H:%M:%S")
    line = json.dumps(entry, separators=(",", ":"))
    with _ctx_lock:
        try:
            existing = UNIFIED_CTX.read_text().splitlines() if UNIFIED_CTX.exists() else []
            existing.append(line)
            if len(existing) > CTX_MAX:
                existing = existing[-CTX_MAX:]
            tmp = UNIFIED_CTX.with_suffix(".tmp")
            tmp.write_text("\n".join(existing) + "\n")
            tmp.rename(UNIFIED_CTX)
        except Exception as e:
            print(f"  ctx_append error: {e}", flush=True)


def ctx_read(n=CTX_INJECT) -> list[dict]:
    """Return last n entries from unified_context.jsonl as parsed dicts."""
    if not UNIFIED_CTX.exists():
        return []
    try:
        lines = UNIFIED_CTX.read_text().strip().splitlines()
        out = []
        for l in lines[-n:]:
            try:
                out.append(json.loads(l))
            except Exception:
                pass
        return out
    except Exception:
        return []


def ctx_to_prompt_block(entries: list[dict]) -> str:
    """Format unified context entries into a readable prompt block."""
    lines = []
    for e in entries:
        t = e.get("ts", "")
        typ = e.get("type", "")
        if typ == "cmd":
            lines.append(f"[{t}] ran: {e.get('cmd','')}")
        elif typ == "rule":
            lines.append(f"[{t}] rule({e.get('severity','')}) {e.get('hint','')}")
        elif typ == "ambient":
            lines.append(f"[{t}] ambient: {e.get('text','')[:100]}")
        elif typ == "advisor":
            lines.append(f"[{t}] intent: {e.get('intent','')}")
            if e.get("observation"):
                lines.append(f"[{t}] note: {e.get('observation','')}")
            if e.get("prediction"):
                lines.append(f"[{t}] next: {e.get('prediction','')}")
        elif typ == "tip_q":
            lines.append(f"[{t}] /tip asked: {e.get('query','')}")
        elif typ == "tip_a":
            lines.append(f"[{t}] /tip answer: {e.get('text','')[:150]}")
        elif typ == "post_mortem":
            lines.append(f"[{t}] commit drafted: {e.get('text','')[:80]}")
    return "\n".join(lines)


# ── Advisor ───────────────────────────────────────────────────────────────────

def build_advisor_prompt(recent_cmds, cwd, ctx_block):
    last_cmd = recent_cmds[-1].get("cmd", "") if recent_cmds else ""
    cmd_summary = "\n".join(
        f"  {c.get('ts','')[-8:]}  {c.get('cmd','')}" for c in recent_cmds[-ADVISOR_WINDOW:]
    )
    cwd_short = str(Path(cwd)).replace(str(Path.home()), "~")

    prompt = (
        "You are an opinionated terminal session advisor. The user just ran a command.\n"
        "Form a quick view on what they're doing and what comes next — even if guessing.\n\n"
        f"Working directory: {cwd_short}\n"
        f"Last command: {last_cmd}\n"
    )
    if ctx_block:
        prompt += f"\nRecent session context (commands, hints, tips seen):\n{ctx_block}\n"
    prompt += (
        f"\nFull command history (oldest→newest):\n{cmd_summary}\n\n"
        "Output exactly 3 lines, plain text, no labels, no bullets:\n"
        "Line 1: What the user is currently trying to do (≤10 words, specific)\n"
        "Line 2: A pattern, risk, or struggle you notice (direct opinion)\n"
        "Line 3: Your best prediction of their next command or action\n"
    )
    return prompt


def run_advisor(recent_cmds, cwd):
    """Layer 2: background thread. Calls AI, writes to unified context log."""
    try:
        ctx_entries = ctx_read(n=20)
        ctx_block = ctx_to_prompt_block(ctx_entries)
        prompt = build_advisor_prompt(recent_cmds, cwd, ctx_block)
        result = _call_backend(HINT_BACKEND, prompt, model=HINT_MODEL)
        if not result:
            return
        lines = [l.strip() for l in result.strip().splitlines() if l.strip()]
        entry = {
            "type":       "advisor",
            "intent":     lines[0] if len(lines) > 0 else "",
            "observation":lines[1] if len(lines) > 1 else "",
            "prediction": lines[2] if len(lines) > 2 else "",
        }
        ctx_append(entry)
        print(f"  advisor: {entry['intent'][:60]}", flush=True)
    except Exception as e:
        print(f"  advisor error: {e}", flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  POST-MORTEM COMMIT MESSAGE GENERATOR
#  Fires when user runs `git commit ...`. Reads last ~50 commands and session
#  context, drafts a commit message, writes it to post_mortem.txt.
#  Uses hint_model_chain (gpt-5-mini → raptor-mini → gpt-4.1).
# ═══════════════════════════════════════════════════════════════════════════════

POST_MORTEM_OUT = DATA_DIR / "post_mortem.txt"
_POST_MORTEM_WINDOW = 50  # commands to look back


def _is_git_commit(cmd: str) -> bool:
    """Return True if the command is a git commit (not amend, not --no-edit)."""
    return bool(re.match(r"^git\s+commit\b", cmd.strip()))


def build_post_mortem_prompt(recent_cmds, cwd, ctx_block):
    cwd_short = str(Path(cwd)).replace(str(Path.home()), "~")
    cmd_summary = "\n".join(
        f"  {c.get('ts','')[-8:]}  {c.get('cmd','')}" for c in recent_cmds
    )
    prompt = (
        "You are a senior engineer writing a git commit message.\n"
        "Analyze the shell session below and draft the best possible commit message.\n\n"
        f"Working directory: {cwd_short}\n"
    )
    if ctx_block:
        prompt += f"\nSession context (hints, /tip answers, advisor observations):\n{ctx_block}\n"
    prompt += (
        f"\nCommands run in this session (oldest→newest):\n{cmd_summary}\n\n"
        "Output format — exactly 2 parts, plain text:\n"
        "Line 1: Subject line (≤72 chars, imperative mood, no period)\n"
        "Line 2: blank\n"
        "Lines 3+: Body (optional, 2-5 lines max — what changed and why, not how)\n\n"
        "Rules:\n"
        "- Be specific about what changed based on the commands\n"
        "- If tests were run, mention if they passed\n"
        "- If errors were seen and fixed, mention the fix\n"
        "- No 'Update files', 'Make changes', or other vague phrases\n"
        "- No markdown, no code fences\n"
    )
    return prompt


def run_post_mortem(recent_cmds, cwd):
    """Draft a commit message from the session and write to post_mortem.txt."""
    try:
        ctx_entries = ctx_read(n=40)
        ctx_block = ctx_to_prompt_block(ctx_entries)
        prompt = build_post_mortem_prompt(recent_cmds, cwd, ctx_block)

        # Use chain: gpt-5-mini → raptor-mini → gpt-4.1
        if HINT_BACKEND == "copilot":
            result = _call_copilot_chain(prompt, models=HINT_MODEL_CHAIN, max_tokens=300)
        else:
            result = _call_backend(HINT_BACKEND, prompt, model=HINT_MODEL)

        if not result:
            return

        POST_MORTEM_OUT.write_text(result.strip())
        ctx_append({"type": "post_mortem", "text": result[:200]})
        print(f"  post-mortem written ({len(result)} chars)", flush=True)
    except Exception as e:
        print(f"  post-mortem error: {e}", flush=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  LAYER 1 — HINT PROMPT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _detect_intent(cmds):
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

    # Inject unified context — gives LLM awareness of prior hints and /tip Q&A
    ctx_block = ctx_to_prompt_block(ctx_read(n=CTX_INJECT))

    prompt = (
        "You are an ambient terminal coach. A developer is working in their shell.\n"
        "Give 2-3 SPECIFIC, actionable hints. Avoid repeating hints already shown.\n\n"
        f"Directory: {cwd}\n"
        f"Project: {project_ctx}\n"
    )
    if intent:
        prompt += f"Current activity: {intent}\n"
    if ctx_block:
        prompt += f"\nSession history (commands, prior hints, /tip answers):\n{ctx_block}\n"
    prompt += (
        f"\nRecent commands (oldest→newest):\n{cmd_summary}\n\n"
        "Rules:\n"
        "- ONE line per hint, max 70 chars\n"
        "- Use exact filenames/paths from their commands\n"
        "- Prioritise: faster alternatives, missing flags, footguns\n"
        "- Don't repeat what's already in session history above\n"
        "- No bullets, no markdown, no greetings\n"
        "- Max 5 lines total\n"
        "- If workflow looks fine: Good flow — keep going\n"
    )
    return prompt


# ═══════════════════════════════════════════════════════════════════════════════
#  LAYER 3 — /tip QUERY HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

def build_tip_prompt(query):
    cwd = "~"
    shell_info = "zsh on macOS"
    recent_cmds_str = ""
    try:
        if CMD_LOG.exists():
            lines = CMD_LOG.read_text().strip().splitlines()[-5:]
            recent = [json.loads(l) for l in lines if l.strip()]
            if recent:
                cwd = recent[-1].get("cwd", "~")
                recent_cmds_str = "\n".join(f"  {c.get('cmd', '')}" for c in recent)
    except Exception:
        pass

    # Unified context: commands + prior rule hints + ambient answers + past /tip Q&A
    ctx_entries = ctx_read(n=CTX_INJECT)
    ctx_block = ctx_to_prompt_block(ctx_entries)

    # KB detail injection — expert man-page knowledge for recently matched rules
    kb_ctx = ""
    if _KB_ENGINE and _KB_ENGINE.loaded:
        try:
            if CMD_LOG.exists():
                all_lines = CMD_LOG.read_text().strip().splitlines()
                kb_recent = [json.loads(l) for l in all_lines[-20:] if l.strip()]
                kb_ctx = _KB_ENGINE.get_detail_context(kb_recent, n=3)
        except Exception:
            pass

    prompt = (
        "You are a senior terminal/CLI expert. Give a precise, practical answer.\n\n"
        f"Environment: {shell_info}\n"
        f"Working directory: {cwd}\n"
    )
    if ctx_block:
        prompt += f"\nSession history (commands, hints, prior /tip answers):\n{ctx_block}\n"
    if kb_ctx:
        prompt += f"\nKB matched rules (expert context):\n{kb_ctx}\n"
    if recent_cmds_str:
        prompt += f"\nLast 5 commands:\n{recent_cmds_str}\n"
    prompt += (
        "\nRules:\n"
        "- Exact command(s) first, brief explanation after\n"
        "- Number steps for multi-step tasks\n"
        "- Use session history for context — don't repeat advice already given\n"
        "- Max 15 lines, no markdown, no code fences\n"
        "- macOS/zsh conventions\n\n"
        f"Question: {query}\n"
    )
    return prompt


def handle_tip_query():
    if not TIP_QUERY.exists():
        return False
    try:
        query = TIP_QUERY.read_text().strip()
        TIP_QUERY.unlink(missing_ok=True)
        if not query:
            return False

        print(f"  /tip query: {query!r}", flush=True)

        # Special subcommand: /tip postmortem — return last drafted commit message
        if query.strip().lower() in ("postmortem", "post-mortem", "commit message"):
            if POST_MORTEM_OUT.exists():
                msg = POST_MORTEM_OUT.read_text().strip()
                result = f"Last drafted commit message:\n\n{msg}"
            else:
                result = "No post-mortem yet. Run 'git commit ...' to trigger one."
            tmp = TIP_RESULT.with_suffix(".tmp")
            tmp.write_text(result)
            tmp.rename(TIP_RESULT)
            return True

        # Log the question to unified context immediately
        ctx_append({"type": "tip_q", "query": query})

        if TIP_BACKEND not in _AVAILABLE_BACKENDS:
            TIP_RESULT.write_text(
                f"[{TIP_BACKEND} not available — check config.json]"
            )
            return True

        prompt = build_tip_prompt(query)
        result = call_ai_tip(prompt)
        if not result:
            result = f"[{TIP_BACKEND}:{TIP_MODEL} returned empty — check: hints-log]"

        # Log the answer to unified context
        ctx_append({"type": "tip_a", "text": result[:300]})

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
#  LAYER 1 — RULE HINTS
# ═══════════════════════════════════════════════════════════════════════════════

def get_rule_hints(recent_cmds, last_shown):
    # Delegate to KB engine if loaded (dispatcher architecture, sub-ms per cmd)
    if _KB_ENGINE and _KB_ENGINE.loaded:
        results = _KB_ENGINE.get_hints(recent_cmds, last_shown, cooldown=RULE_COOLDOWN)
        # results is list of (rule_id, hint_str, entry) — return (id, hint_str) tuples
        return [(rid, hint_str) for rid, hint_str, _ in results]

    # Legacy fallback: flat UPGRADE_RULES scan
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

    _load_config()
    _probe_backends()

    last_cmd_count        = 0
    last_ai_call          = 0.0
    last_advisor_call     = 0.0
    last_advisor_cmd      = 0
    last_cwd              = ""
    last_ai_text          = ""
    last_hint_check       = 0.0
    rule_last_shown       = {}
    _hint_thread          = None
    _advisor_thread       = None
    _post_mortem_thread   = None
    _last_post_mortem_cmd = 0  # total_count at last post-mortem fire

    ctx_count = len(ctx_read(n=1000))
    chain_str = " → ".join(HINT_MODEL_CHAIN) if HINT_BACKEND == "copilot" else HINT_MODEL
    print(f"shellbuddy daemon started (PID {os.getpid()})", flush=True)
    print(f"  available backends: {', '.join(sorted(_AVAILABLE_BACKENDS)) or 'none'}", flush=True)
    print(f"  hint: {HINT_BACKEND} / {chain_str}"
          f"{'' if HINT_BACKEND in _AVAILABLE_BACKENDS else ' (NOT AVAILABLE)'}", flush=True)
    print(f"  /tip: {TIP_BACKEND} / {TIP_MODEL}"
          f"{'' if TIP_BACKEND in _AVAILABLE_BACKENDS else ' (NOT AVAILABLE)'}", flush=True)
    print(f"  post-mortem: enabled (fires on git commit)", flush=True)
    print(f"  unified context: {ctx_count} entries loaded", flush=True)
    if _KB_ENGINE and _KB_ENGINE.loaded:
        print(f"  kb engine: {_KB_ENGINE.stats}", flush=True)
    if not _AVAILABLE_BACKENDS:
        print(f"  WARNING: no AI backend available", flush=True)

    try:
        while True:
            # Layer 3: /tip has highest priority
            handle_tip_query()

            now = time.time()
            if (now - last_hint_check) < HINT_INTERVAL:
                time.sleep(POLL_INTERVAL)
                continue
            last_hint_check = now

            if not CMD_LOG.exists():
                time.sleep(POLL_INTERVAL)
                continue

            try:
                all_lines = CMD_LOG.read_text().strip().splitlines()
                total_count = len(all_lines)
                recent    = [json.loads(l) for l in all_lines[-WINDOW:]        if l.strip()]
                all_recent = [json.loads(l) for l in all_lines[-ADVISOR_WINDOW:] if l.strip()]
            except Exception:
                time.sleep(POLL_INTERVAL)
                continue

            current_count = total_count
            cwd = recent[-1].get("cwd", str(Path.home())) if recent else str(Path.home())

            has_new     = current_count != last_cmd_count
            cwd_changed = cwd != last_cwd
            ai_ready    = (now - last_ai_call) > AI_THROTTLE

            if (has_new or cwd_changed) and current_count >= MIN_COMMANDS:

                # Layer 1a: regex rules — instant, log matched rules to unified context
                rule_hints = get_rule_hints(recent, rule_last_shown)
                for rid, _ in rule_hints:
                    rule_last_shown[rid] = time.time()
                    # Write matched rule to unified context (with detail if KB engine)
                    if _KB_ENGINE and _KB_ENGINE.loaded:
                        # find entry by id
                        for entry in (_KB_ENGINE._buckets.get(rid.split("-")[0], []) +
                                      _KB_ENGINE._generic):
                            if entry[1].get("id") == rid:
                                ctx_append({
                                    "type": "rule", "id": rid,
                                    "severity": entry[1].get("severity", "tip"),
                                    "hint":   entry[1].get("hint", ""),
                                    "detail": entry[1].get("detail", ""),
                                })
                                break
                    else:
                        ctx_append({"type": "rule", "id": rid, "hint": _})

                # Log new commands to unified context
                if has_new:
                    new_cmds = recent[-(current_count - last_cmd_count):]
                    for c in new_cmds[-5:]:  # cap at 5 to avoid log spam on first run
                        ctx_append({"type": "cmd", "cmd": c.get("cmd", ""),
                                    "cwd": c.get("cwd", "")})

                    # Post-mortem: fire on git commit (once per commit, not on every poll)
                    if (_post_mortem_thread is None or not _post_mortem_thread.is_alive()):
                        for c in new_cmds[-5:]:
                            if _is_git_commit(c.get("cmd", "")) and current_count != _last_post_mortem_cmd:
                                pm_cmds = [json.loads(l) for l in all_lines[-_POST_MORTEM_WINDOW:]
                                           if l.strip()]
                                def _run_pm(r=pm_cmds, d=cwd):
                                    run_post_mortem(r, d)
                                _post_mortem_thread = threading.Thread(target=_run_pm, daemon=True)
                                _post_mortem_thread.start()
                                _last_post_mortem_cmd = current_count
                                break

                # Layer 1b: ambient LLM hint — background thread, non-blocking
                if ai_ready and (_hint_thread is None or not _hint_thread.is_alive()):
                    write_hints(rule_hints, last_ai_text, cwd, current_count, thinking=True)

                    def _run_hint(r=recent, c=cwd, cc=current_count):
                        nonlocal last_ai_text, last_ai_call
                        result = call_ai_hint(build_hint_prompt(r, c))
                        if result:
                            last_ai_text = result
                            ctx_append({"type": "ambient", "text": result[:300]})
                        last_ai_call = time.time()
                        write_hints(get_rule_hints(r, rule_last_shown),
                                    last_ai_text, c, cc)

                    _hint_thread = threading.Thread(target=_run_hint, daemon=True)
                    _hint_thread.start()
                else:
                    write_hints(rule_hints, last_ai_text, cwd, current_count)

                # Layer 2: advisor — debounced, writes intent/prediction to unified context
                cmds_since_advisor = current_count - last_advisor_cmd
                advisor_ready = (now - last_advisor_call) > ADVISOR_THROTTLE
                if (cmds_since_advisor >= ADVISOR_EVERY and advisor_ready and
                        (_advisor_thread is None or not _advisor_thread.is_alive())):

                    def _run_advisor(r=all_recent, c=cwd):
                        run_advisor(r, c)

                    _advisor_thread = threading.Thread(target=_run_advisor, daemon=True)
                    _advisor_thread.start()
                    last_advisor_call = now
                    last_advisor_cmd  = current_count

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
