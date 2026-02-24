"""
shellbuddy — backends/ollama.py
Ollama backend for the hints daemon.
Drop-in replacement for the call_ai() function.

Ollama docs: https://github.com/ollama/ollama/blob/main/docs/api.md
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

# ── Config (override via hint_daemon.py) ──────────────────────────────────────
DEFAULT_MODEL = "qwen3:8b"       # /tip model (user-selected at install)
DEFAULT_HINT_MODEL = "qwen3:4b"  # ambient hints (small + thinking)
DEFAULT_URL   = "http://localhost:11434"


def call_ollama(recent_cmds: list, cwd: str, model: str = DEFAULT_MODEL, url: str = DEFAULT_URL) -> str:
    """
    Send recent commands to Ollama and return 2-3 hint lines.

    Args:
        recent_cmds: list of dicts with keys: ts, cmd, cwd
        cwd: current working directory string
        model: ollama model name (e.g. 'qwen2.5:7b')
        url: ollama base URL (default http://localhost:11434)

    Returns:
        str: newline-separated hint lines, max 3, each max 60 chars.
             Returns an error string (starting with '[') on failure.
    """
    cwd_path = Path(cwd)

    # Detect project type from directory contents
    project_signals = []
    for indicator, lang in [
        ("pyproject.toml", "Python"), ("requirements.txt", "Python"),
        ("package.json", "Node.js"), ("Cargo.toml", "Rust"),
        ("go.mod", "Go"), ("Gemfile", "Ruby"), ("Makefile", "Make"),
        ("docker-compose.yml", "Docker"), ("Dockerfile", "Docker"),
        (".git", "git repo"),
    ]:
        if (cwd_path / indicator).exists():
            project_signals.append(lang)
    project_ctx = ", ".join(dict.fromkeys(project_signals)) or "general"

    cmd_summary = "\n".join(
        f"  {c.get('ts', '')[-8:]}  {c.get('cmd', '')}"
        for c in recent_cmds[-10:]
    )

    prompt = (
        "You are an ambient terminal coach. A developer is working in their shell.\n"
        "Look at their recent commands and give 2-3 SPECIFIC, actionable hints.\n\n"
        f"Directory: {cwd}\n"
        f"Project: {project_ctx}\n"
        f"Recent commands (oldest to newest):\n{cmd_summary}\n\n"
        "Requirements:\n"
        "- Output ONLY the hints, one per line, nothing else\n"
        "- Each hint must fit on ONE line, max 70 characters\n"
        "- Use real paths and filenames from their commands above\n"
        "- Focus on the most-repeated suboptimal commands first\n"
        "- If everything is efficient, output: Good flow — keep going\n"
        "- No bullets, no numbering, no markdown, no explanation text\n"
        "- Maximum 5 lines of output total\n\n"
        "Output the hints now:"
    )

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 500,
            "stop": ["\n\n\n"],   # prevent rambling
        }
    }).encode()

    try:
        req = urllib.request.Request(
            f"{url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            text = data.get("response", "").strip()
            # qwen3 may include <think>...</think> reasoning — strip it
            import re
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return text

    except urllib.error.URLError as e:
        reason = str(e.reason) if hasattr(e, "reason") else str(e)
        if "Connection refused" in reason or "Connect call failed" in reason:
            return "[ollama not running — start with: ollama serve]"
        return f"[ollama network error: {reason[:40]}]"

    except Exception as e:
        return f"[ollama: {type(e).__name__}]"


def list_models(url: str = DEFAULT_URL) -> list[str]:
    """Return list of locally available model names."""
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def is_available(url: str = DEFAULT_URL) -> bool:
    """Return True if Ollama is running and reachable."""
    try:
        urllib.request.urlopen(f"{url}/api/tags", timeout=3)
        return True
    except Exception:
        return False
