"""
shellbuddy — backends/openai_compat.py
OpenAI-compatible backend — works with OpenAI, Groq, Together, Fireworks,
Perplexity, or any endpoint that implements the /chat/completions spec.

To use, set in hint_daemon.py:
    AI_BACKEND = "openai"
    OPENAI_URL   = "https://api.groq.com/openai/v1"
    OPENAI_MODEL = "llama-3.1-8b-instant"
    OPENAI_KEY   = os.environ.get("OPENAI_API_KEY", "")
"""

import json
import os
import urllib.request
import urllib.error
from pathlib import Path


def call_openai_compat(
    recent_cmds: list,
    cwd: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    base_url: str = "https://api.openai.com/v1",
) -> str:
    """
    Call any OpenAI-compatible /chat/completions endpoint.

    Recommended free/cheap options:
    - Groq (groq.com): llama-3.1-8b-instant — very fast, generous free tier
    - Together (together.ai): meta-llama/Llama-3.2-3B-Instruct-Turbo
    - OpenAI: gpt-4o-mini — reliable, $0.15/1M input tokens
    """
    if not api_key:
        return "[openai: OPENAI_API_KEY not set]"

    cwd_path = Path(cwd)
    project_signals = []
    for indicator, lang in [
        ("pyproject.toml", "Python"), ("requirements.txt", "Python"),
        ("package.json", "Node.js"), ("Cargo.toml", "Rust"),
        ("go.mod", "Go"), (".git", "git repo"),
    ]:
        if (cwd_path / indicator).exists():
            project_signals.append(lang)

    cmd_summary = "\n".join(
        f"  {c.get('ts', '')[-8:]}  {c.get('cmd', '')}"
        for c in recent_cmds[-10:]
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are an ambient terminal coach. Give 2-3 short, specific, "
                "actionable hints. One hint per line, max 60 chars each. "
                "No bullets, no markdown. Use real paths from the user's commands."
            )
        },
        {
            "role": "user",
            "content": (
                f"Directory: {cwd}\n"
                f"Project: {', '.join(project_signals) or 'general'}\n"
                f"Recent commands:\n{cmd_summary}"
            )
        }
    ]

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": 120,
        "temperature": 0.3,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()

    except urllib.error.HTTPError as e:
        return f"[openai {e.code}: {e.read().decode()[:40]}]"
    except Exception as e:
        return f"[openai: {type(e).__name__}]"
