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

import os, sys, time, json, subprocess, re, urllib.request, urllib.error, threading, signal
import concurrent.futures
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
SILENCED_RULES   = DATA_DIR / "silenced_rules.json"    # rules suppressed via /tip silence

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
AI_THROTTLE      = 15     # seconds between ambient LLM hint calls
ADVISOR_EVERY    = 1      # advisor fires every new command (debounced)
ADVISOR_THROTTLE = 5      # min seconds between advisor calls
WINDOW           = 50     # commands sent to ambient LLM
ADVISOR_WINDOW   = 100    # commands the advisor sees
MIN_COMMANDS     = 2
MAX_HINT_LINES   = 10  # default; dynamically updated from hints_pane_rows
RULE_COOLDOWN    = 120
OLLAMA_TIMEOUT   = 90
CTX_MAX          = 200    # max lines kept in unified_context.jsonl
CTX_INJECT       = 30     # last N unified context entries injected into prompts

def _parse_jsonl_lines(lines):
    """Parse a list of raw JSONL strings, silently skipping malformed lines."""
    out = []
    for l in lines:
        l = l.strip()
        if not l:
            continue
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return out

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


_config_lock = threading.Lock()
_config_mtime = 0.0  # track config.json mtime for hot-reload


def _load_config():
    global HINT_BACKEND, HINT_MODEL, HINT_MODEL_CHAIN, TIP_BACKEND, TIP_MODEL
    global OLLAMA_URL, CLAUDE_MODEL, COPILOT_MODEL, OPENAI_URL, OPENAI_MODEL
    global _config_mtime

    if not CONFIG_FILE.exists():
        return
    try:
        mtime = CONFIG_FILE.stat().st_mtime
        if mtime == _config_mtime:
            return  # unchanged since last load
        cfg = json.loads(CONFIG_FILE.read_text())
        _config_mtime = mtime
    except Exception as e:
        print(f"  warning: bad config.json — {e}", flush=True)
        return

    with _config_lock:
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


def _load_silenced_rules() -> dict:
    """Load {rule_id: expiry_epoch} from silenced_rules.json. 0 = permanent."""
    if not SILENCED_RULES.exists():
        return {}
    try:
        data = json.loads(SILENCED_RULES.read_text())
        now = time.time()
        return {k: v for k, v in data.items() if v == 0 or v > now}
    except Exception:
        return {}


def _update_pane_height():
    """Read dynamic pane height from hints_pane_rows file (written by toggle_hints_pane.sh)."""
    global MAX_HINT_LINES
    rows_file = DATA_DIR / "hints_pane_rows"
    try:
        if rows_file.exists():
            val = int(rows_file.read_text().strip())
            # pane_rows - 2 (header + separator) = content lines
            MAX_HINT_LINES = max(4, min(val - 2, 30))
    except (ValueError, OSError):
        pass


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
    t0 = time.perf_counter()
    try:
        from backends.copilot import call_copilot
        result = call_copilot(prompt, model=model or COPILOT_MODEL, max_tokens=max_tokens)
        if result:
            ms = (time.perf_counter() - t0) * 1000
            print(f"  backend: copilot/{model or COPILOT_MODEL} {ms:.0f}ms", flush=True)
        return result
    except Exception:
        return None


def _call_copilot_chain(prompt, models=None, max_tokens=150):
    """Try each model in the chain; return first successful result."""
    chain = models or HINT_MODEL_CHAIN
    for i, model in enumerate(chain):
        result = _call_copilot(prompt, model=model, max_tokens=max_tokens)
        if result:
            if i > 0:
                skipped = ", ".join(chain[:i])
                print(f"  chain: fell back to {model} (tried: {skipped})", flush=True)
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
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())["content"][0]["text"].strip()
        ms = (time.perf_counter() - t0) * 1000
        print(f"  backend: claude/{model} {ms:.0f}ms", flush=True)
        return result
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
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
            text = json.loads(resp.read()).get("response", "").strip()
        ms = (time.perf_counter() - t0) * 1000
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        print(f"  backend: ollama/{model} {ms:.0f}ms", flush=True)
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
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        ms = (time.perf_counter() - t0) * 1000
        result = data["choices"][0]["message"]["content"].strip()
        print(f"  backend: openai/{model} {ms:.0f}ms", flush=True)
        return result
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


def _sanitize_for_ctx(text: str, max_len: int = 300) -> str:
    """Strip newlines/control chars and truncate for safe JSONL embedding."""
    text = re.sub(r'[\x00-\x1f\x7f]+', ' ', text)  # control chars → space
    text = text.strip()[:max_len]
    json.dumps(text)  # validate it round-trips cleanly (raises on bad encoding)
    return text


_ctx_append_count = 0  # track appends for periodic compaction


def ctx_append(entry: dict):
    """Append one event to unified_context.jsonl. Thread-safe. O(1) append."""
    global _ctx_append_count
    entry["ts"] = datetime.now().strftime("%H:%M:%S")
    line = json.dumps(entry, separators=(",", ":"))
    with _ctx_lock:
        try:
            with open(UNIFIED_CTX, "a") as f:
                f.write(line + "\n")
            _ctx_append_count += 1
        except Exception as e:
            print(f"  ctx_append error: {e}", flush=True)


def _ctx_compact():
    """Trim unified_context.jsonl to CTX_MAX lines. Called periodically from main loop."""
    global _ctx_append_count
    with _ctx_lock:
        try:
            if not UNIFIED_CTX.exists():
                return
            lines = UNIFIED_CTX.read_text().splitlines()
            if len(lines) <= CTX_MAX:
                _ctx_append_count = 0
                return
            trimmed = lines[-CTX_MAX:]
            tmp = UNIFIED_CTX.with_suffix(".tmp")
            tmp.write_text("\n".join(trimmed) + "\n")
            tmp.rename(UNIFIED_CTX)
            _ctx_append_count = 0
        except Exception as e:
            print(f"  ctx_compact error: {e}", flush=True)


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


_last_advisor_text = ""   # populated by run_advisor(), shown briefly in hints pane
_advisor_text_ts   = 0.0  # when advisor text was set (cleared after 60s)

_last_tip_query  = ""   # last /tip question (used by /tip helpful / not-helpful)
_last_tip_answer = ""   # last /tip answer  (used by /tip helpful / not-helpful)

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
    global _last_advisor_text, _advisor_text_ts
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
        # Surface observation in hints pane (shown for 60s)
        if entry["observation"]:
            _last_advisor_text = entry["observation"][:65]
            _advisor_text_ts = time.time()
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
    """Return True if the command is a git commit that needs a message drafted.
    Skip if user already provided one via -m/--message or --no-edit."""
    cmd = cmd.strip()
    if not re.match(r"^git\s+commit\b", cmd):
        return False
    if re.search(r'\s-[a-zA-Z]*m[\s=]', cmd) or '--message' in cmd:
        return False
    if '--no-edit' in cmd:
        return False
    return True


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
        ctx_append({"type": "post_mortem", "text": _sanitize_for_ctx(result, 200)})
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


_project_cache = {}  # {cwd: (signals_list, timestamp)}
_PROJECT_CACHE_TTL = 30  # seconds


def build_hint_prompt(recent_cmds, cwd):
    cwd_path = Path(cwd)
    # Cached project detection — avoids 10+ stat() calls per hint cycle
    cached = _project_cache.get(cwd)
    if cached and (time.time() - cached[1]) < _PROJECT_CACHE_TTL:
        project_signals = cached[0]
    else:
        project_signals = []
        for indicator, lang in PROJECT_INDICATORS:
            try:
                if (cwd_path / indicator).exists():
                    project_signals.append(lang)
            except (PermissionError, OSError):
                pass
        _project_cache[cwd] = (project_signals, time.time())

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
            recent = _parse_jsonl_lines(lines)
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
                kb_recent = _parse_jsonl_lines(all_lines[-20:])
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
    global _last_tip_query, _last_tip_answer
    if not TIP_QUERY.exists():
        return False
    try:
        if TIP_QUERY.stat().st_size > 10_000:  # 10KB max — reject oversized queries
            TIP_QUERY.unlink(missing_ok=True)
            return False
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

        # ── Item 1: /tip rule <id> — explain a KB rule ────────────────────────
        if re.match(r'^rule\s+\S', query.strip(), re.IGNORECASE):
            rid = query.split(None, 1)[1].strip()
            if _KB_ENGINE and _KB_ENGINE.loaded:
                found = None
                for entries in _KB_ENGINE._buckets.values():
                    for _, entry in entries:
                        if entry.get("id") == rid:
                            found = entry
                            break
                    if found:
                        break
                if not found:
                    for _, entry in _KB_ENGINE._generic:
                        if entry.get("id") == rid:
                            found = entry
                            break
                if found:
                    sev = found.get("severity", "tip").upper()
                    lines = [
                        f"Rule ID:  {found['id']}",
                        f"Severity: {sev}",
                        f"Pattern:  {found.get('pattern', '')}",
                        "",
                        f"Hint:     {found['hint']}",
                        "",
                        f"Detail:   {found.get('detail', '(none)')}",
                    ]
                    if found.get("examples"):
                        lines += ["", "Examples:"]
                        lines += [f"  {ex}" for ex in found["examples"][:3]]
                    result = "\n".join(lines)
                else:
                    result = (
                        f"Rule '{rid}' not found in KB "
                        f"({_KB_ENGINE._count} rules loaded).\n"
                        f"Try: /tip top-rules  to see most-fired rules."
                    )
            else:
                result = "KB engine not loaded — run: python3 kb_builder.py"
            tmp = TIP_RESULT.with_suffix(".tmp")
            tmp.write_text(result)
            tmp.rename(TIP_RESULT)
            return True

        # ── Item 2: /tip top-rules — most-fired rules from history ───────────
        if query.strip().lower() == "top-rules":
            if not CMD_LOG.exists():
                result = "No command log yet — run some commands first."
            elif not (_KB_ENGINE and _KB_ENGINE.loaded):
                result = "KB engine not loaded — run: python3 kb_builder.py"
            else:
                try:
                    all_lines = CMD_LOG.read_text().strip().splitlines()
                    recent_scan = _parse_jsonl_lines(all_lines[-1000:])
                    freq: Counter = Counter()
                    best_entry: dict = {}
                    for item in recent_scan:
                        cmd = item.get("cmd", "")
                        for entry in _KB_ENGINE.scan(cmd):
                            rid = entry["id"]
                            freq[rid] += 1
                            best_entry[rid] = entry
                    if not freq:
                        result = "No rules matched in the last 1000 commands."
                    else:
                        lines = [f"Top rules  (last {len(recent_scan)} commands):", ""]
                        for i, (rid, count) in enumerate(freq.most_common(10), 1):
                            entry = best_entry.get(rid, {})
                            sev  = entry.get("severity", "tip")[:4]
                            hint = entry.get("hint", rid)[:52]
                            lines.append(f"  {i:2d}. [{count:3d}x] {sev:<4}  {rid:<28} {hint}")
                        result = "\n".join(lines)
                except Exception as e:
                    result = f"[top-rules error: {e}]"
            tmp = TIP_RESULT.with_suffix(".tmp")
            tmp.write_text(result)
            tmp.rename(TIP_RESULT)
            return True

        # ── Item 3: /tip history [N] — browse recent /tip Q&A pairs ─────────
        m_hist = re.match(r'^history(?:\s+(\d+))?$', query.strip(), re.IGNORECASE)
        if m_hist:
            n = int(m_hist.group(1)) if m_hist.group(1) else 10
            if not UNIFIED_CTX.exists():
                result = "No session context yet — run some /tip queries first."
            else:
                try:
                    entries = _parse_jsonl_lines(UNIFIED_CTX.read_text().strip().splitlines())
                    pairs = []
                    last_q = None
                    for e in entries:
                        if e.get("type") == "tip_q":
                            last_q = e
                        elif e.get("type") == "tip_a" and last_q:
                            pairs.append((last_q, e))
                            last_q = None
                    if not pairs:
                        result = "No /tip Q&A history yet."
                    else:
                        out = [f"/tip history  ({min(n, len(pairs))} of {len(pairs)} total)", ""]
                        for q_e, a_e in pairs[-n:]:
                            ts = q_e.get("ts", "")
                            out.append(f"[{ts}] Q: {q_e.get('query', '')}")
                            for aline in a_e.get("text", "").splitlines()[:4]:
                                if aline.strip():
                                    out.append(f"       {aline.strip()[:70]}")
                            out.append("")
                        result = "\n".join(out).rstrip()
                except Exception as e:
                    result = f"[history error: {e}]"
            tmp = TIP_RESULT.with_suffix(".tmp")
            tmp.write_text(result)
            tmp.rename(TIP_RESULT)
            return True

        # ── Item 4: /tip context — show session context injected into prompts ─
        if query.strip().lower() == "context":
            ctx_entries = ctx_read(n=CTX_INJECT)
            if not ctx_entries:
                result = "No context yet — run some commands first."
            else:
                block = ctx_to_prompt_block(ctx_entries)
                result = (
                    f"Session context  ({len(ctx_entries)} of last {CTX_INJECT} entries):\n\n"
                    f"{block}"
                )
            tmp = TIP_RESULT.with_suffix(".tmp")
            tmp.write_text(result)
            tmp.rename(TIP_RESULT)
            return True

        # ── Item 5: /tip silence <id> [days] — suppress a rule ───────────────
        m_silence = re.match(r'^silence\s+(\S+)(?:\s+(\d+))?$', query.strip(), re.IGNORECASE)
        if m_silence:
            rid    = m_silence.group(1)
            days   = int(m_silence.group(2)) if m_silence.group(2) else 7
            expiry = int(time.time() + days * 86400) if days < 9999 else 0
            silenced_data: dict = {}
            if SILENCED_RULES.exists():
                try:
                    silenced_data = json.loads(SILENCED_RULES.read_text())
                except Exception:
                    pass
            silenced_data[rid] = expiry
            now_t = time.time()
            silenced_data = {k: v for k, v in silenced_data.items() if v == 0 or v > now_t}
            SILENCED_RULES.write_text(json.dumps(silenced_data, indent=2))
            days_str = "forever" if days >= 9999 else f"for {days} day{'s' if days != 1 else ''}"
            result = (
                f"Rule '{rid}' silenced {days_str}.\n"
                f"  Active silences: {len(silenced_data)}\n"
                f"  File: {SILENCED_RULES}\n"
                f"\nTo un-silence: edit the file above, or:\n"
                f"  /tip silence {rid} 9999   (sets permanent)\n"
                f"Silences take effect on the next hint cycle (live, no restart needed)."
            )
            tmp = TIP_RESULT.with_suffix(".tmp")
            tmp.write_text(result)
            tmp.rename(TIP_RESULT)
            return True

        # ── Item 6: /tip helpful / not-helpful — rate the last answer ────────
        if query.strip().lower() in ("helpful", "not-helpful"):
            rating = query.strip().lower()
            ctx_append({
                "type":   "feedback",
                "rating": rating,
                "query":  _last_tip_query[:100],
                "answer": _last_tip_answer[:200],
            })
            if _last_tip_query:
                result = f"Feedback logged: {rating}\nFor: {_last_tip_query[:80]}"
            else:
                result = f"Feedback logged: {rating}\n(No recent /tip query to associate with)"
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
        ctx_append({"type": "tip_a", "text": _sanitize_for_ctx(result)})

        # Remember for /tip helpful / not-helpful feedback (items 6)
        _last_tip_query  = query
        _last_tip_answer = _sanitize_for_ctx(result, 300)

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
    silenced = _load_silenced_rules()
    # Delegate to KB engine if loaded (dispatcher architecture, sub-ms per cmd)
    if _KB_ENGINE and _KB_ENGINE.loaded:
        results = _KB_ENGINE.get_hints(recent_cmds, last_shown, cooldown=RULE_COOLDOWN)
        # results is list of (rule_id, hint_str, entry) — filter silenced, return (id, hint_str)
        return [(rid, hint_str) for rid, hint_str, _ in results
                if rid not in silenced]

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
        if pattern in silenced:
            continue
        tmpl, example = matches[pattern]
        arg = re.sub(r"^\S+\s*", "", example)[:40]
        hint = tmpl.replace("{arg}", arg or "...").replace("{pattern}", arg or "...")
        hints.append((pattern, f"[{count}x] {hint}"))

    return hints


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGO + IDLE TIPS
# ═══════════════════════════════════════════════════════════════════════════════

IDLE_TIMEOUT = 90   # seconds of no new commands before showing usage tips
IDLE_TIP_ROTATE = 20  # seconds between idle tip rotations


# Rotating usage tips shown when idle
IDLE_TIPS = [
    ("/tip <question>",          "ask any terminal question, get instant expert answer"),
    ("/tip status",              "full diagnostic — backend, model, KB, hints age"),
    ("/tip postmortem",          "show last auto-drafted git commit message"),
    ("/tip test",                "force an ambient hint cycle and verify the pipeline"),
    ("/tip top-rules",           "10 most-fired rules from your recent command history"),
    ("/tip history [N]",         "browse your last N /tip Q&A pairs (default: 10)"),
    ("/tip rule <id>",           "explain any KB rule by ID (hint, detail, pattern)"),
    ("/tip context",             "show session context injected into prompts"),
    ("/tip silence <id> [days]", "suppress a noisy rule for N days (default: 7)"),
    ("/tip helpful",             "rate last /tip answer helpful (logged for analysis)"),
    ("hint prefixes",            "!! danger  !  warn  -> tip  => upgrade"),
    ("kb engine",                "1700+ regex rules across 40 categories — instant match"),
    ("3 hint layers",            "rules (<10ms) + ambient LLM + advisor background"),
    ("unified context",          "rules, hints, /tip Q&A all share one session log"),
    ("model chain",              "gpt-5-mini → raptor-mini → gpt-4.1 for ambient"),
    ("post-mortem",              "commit message auto-drafted on every git commit"),
    ("hints-stop && sb",         "restart daemon (pick up config/kb changes)"),
    ("config: hint_model_chain", "customize fallback models in ~/.shellbuddy/config.json"),
    ("Ctrl+A H",                 "toggle hints pane in tmux (if tmux.conf installed)"),
    ("ctx log cap",              "unified_context.jsonl capped at 200 entries"),
    ("custom rules",             "add entries to ~/.shellbuddy/kb.json, restart daemon"),
]

_idle_tip_index = 0


def _get_idle_tip(ts_rotation: int) -> str:
    """Return one rotating idle tip based on time slot."""
    idx = (ts_rotation // IDLE_TIP_ROTATE) % len(IDLE_TIPS)
    cmd, desc = IDLE_TIPS[idx]
    return f"IDLE_TIP\t{cmd}\t{desc}"


def write_hints(rule_hints, ai_hints, cwd, cmd_count, thinking=False, idle=False):
    ts = datetime.now().strftime("%H:%M:%S")
    ts_epoch = int(time.time())
    cwd_short = str(Path(cwd)).replace(str(Path.home()), "~")

    # Header line — cwd + timestamp + cmd count
    header = f"HINTS  {cwd_short}  [{ts}]  ({cmd_count} cmds)"

    # Separator width = terminal width guess (60 chars safe default)
    sep = "─" * 58

    # Content lines (hints area — lines 3..MAX)
    hint_strs = [h for _, h in rule_hints]
    content = []
    for h in hint_strs[:3]:
        content.append(h)

    if idle:
        # Replace ambient slot with idle usage tip
        tip_line = _get_idle_tip(ts_epoch)
        if hint_strs:
            content.append("·")
        content.append(tip_line)
        content.append("IDLE_LABEL\t  shellbuddy usage  (idle — no new commands)")
    elif thinking and not ai_hints:
        if hint_strs:
            content.append("·")
        content.append("thinking ...")
    elif ai_hints:
        ai_lines = [l.strip() for l in ai_hints.splitlines() if l.strip()][:5]
        if ai_lines:
            if hint_strs:
                content.append("·")
            for h in ai_lines:
                content.append(h[:65])

    # Show advisor observation if fresh (≤60s old)
    if _last_advisor_text and (time.time() - _advisor_text_ts) < 60:
        content.append(f"  ~ {_last_advisor_text}")

    # Build final line list: header + sep + content, padded to MAX_HINT_LINES+2
    lines = [header, sep] + content
    while len(lines) < MAX_HINT_LINES + 2:
        lines.append("")

    HINTS_OUT.write_text("\n".join(lines[:MAX_HINT_LINES + 2]))


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))

    # Clean up PID file on SIGTERM (pkill, system shutdown, etc.)
    def _handle_sigterm(*_):
        LOCK_FILE.unlink(missing_ok=True)
        sys.exit(0)
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)  # don't crash if tmux pane closes

    _load_config()
    _probe_backends()

    last_cmd_count        = 0
    last_ai_call          = 0.0
    last_advisor_call     = 0.0
    last_advisor_cmd      = 0
    last_cwd              = ""
    last_ai_text          = ""
    last_hint_check       = 0.0
    last_activity_time    = time.time()  # tracks when last command was seen
    rule_last_shown       = {}
    _executor             = concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="sb")
    _hint_future          = None  # type: concurrent.futures.Future | None
    _advisor_future       = None  # type: concurrent.futures.Future | None
    _pm_future            = None  # type: concurrent.futures.Future | None
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

            # Periodic compaction of unified context log
            if _ctx_append_count >= 50:
                _ctx_compact()

            # Hot-reload config.json if changed + update pane height
            _load_config()
            _update_pane_height()

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
                recent    = _parse_jsonl_lines(all_lines[-WINDOW:])
                all_recent = _parse_jsonl_lines(all_lines[-ADVISOR_WINDOW:])
            except Exception:
                time.sleep(POLL_INTERVAL)
                continue

            current_count = total_count
            cwd = recent[-1].get("cwd", str(Path.home())) if recent else str(Path.home())

            has_new     = current_count != last_cmd_count
            cwd_changed = cwd != last_cwd
            ai_ready    = (now - last_ai_call) > AI_THROTTLE
            is_idle     = (now - last_activity_time) > IDLE_TIMEOUT and current_count >= MIN_COMMANDS

            if (has_new or cwd_changed) and current_count >= MIN_COMMANDS:
                last_activity_time = now  # reset idle clock on any new activity

                # Layer 1a: regex rules — instant, log matched rules to unified context
                rule_hints = get_rule_hints(recent, rule_last_shown)
                for rid, _ in rule_hints:
                    rule_last_shown[rid] = time.time()
                    if _KB_ENGINE and _KB_ENGINE.loaded:
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
                    for c in new_cmds[-5:]:
                        ctx_append({"type": "cmd", "cmd": c.get("cmd", ""),
                                    "cwd": c.get("cwd", "")})

                    # Post-mortem: fire on git commit (once per commit)
                    if _pm_future is None or _pm_future.done():
                        for c in new_cmds[-5:]:
                            if _is_git_commit(c.get("cmd", "")) and current_count != _last_post_mortem_cmd:
                                pm_cmds = _parse_jsonl_lines(all_lines[-_POST_MORTEM_WINDOW:])
                                _pm_future = _executor.submit(run_post_mortem, pm_cmds, cwd)
                                _last_post_mortem_cmd = current_count
                                break

                # Always render rule hints immediately (sub-ms), even while AI is pending
                write_hints(rule_hints, last_ai_text, cwd, current_count,
                            thinking=(ai_ready and (_hint_future is None or _hint_future.done())))

                # Layer 1b: ambient LLM hint — background future, non-blocking
                if ai_ready and (_hint_future is None or _hint_future.done()):
                    def _run_hint(r=recent, c=cwd, cc=current_count):
                        nonlocal last_ai_text, last_ai_call
                        result = call_ai_hint(build_hint_prompt(r, c))
                        if result:
                            last_ai_text = result
                            ctx_append({"type": "ambient", "text": _sanitize_for_ctx(result)})
                        last_ai_call = time.time()
                        write_hints(get_rule_hints(r, rule_last_shown),
                                    last_ai_text, c, cc)

                    _hint_future = _executor.submit(_run_hint)

                # Layer 2: advisor — debounced
                cmds_since_advisor = current_count - last_advisor_cmd
                advisor_ready = (now - last_advisor_call) > ADVISOR_THROTTLE
                if (cmds_since_advisor >= ADVISOR_EVERY and advisor_ready and
                        (_advisor_future is None or _advisor_future.done())):
                    _advisor_future = _executor.submit(run_advisor, all_recent, cwd)
                    last_advisor_call = now
                    last_advisor_cmd  = current_count

                last_cmd_count = current_count
                last_cwd = cwd

            elif is_idle:
                # No new commands for IDLE_TIMEOUT seconds — show rotating usage tips
                rule_hints = get_rule_hints(recent, rule_last_shown)
                write_hints(rule_hints, "", cwd, current_count, idle=True)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        _executor.shutdown(wait=False, cancel_futures=True)
        LOCK_FILE.unlink(missing_ok=True)
        print("shellbuddy daemon stopped.", flush=True)


if __name__ == "__main__":
    run()
