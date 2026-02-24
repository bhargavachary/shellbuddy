"""
shellbuddy — backends/copilot.py
GitHub Copilot backend — uses your existing VS Code Copilot session.
No separate API key needed. Extracts session token from VS Code's
encrypted local storage automatically.

Requires: pycryptodome (pip install pycryptodome)
macOS only (uses Keychain for decryption key).
"""

import json
import hashlib
import os
import sqlite3
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

TOKEN_CACHE = Path(os.environ.get("SHELLBUDDY_DIR", str(Path.home() / ".shellbuddy"))) / "copilot_token.json"

try:
    from Crypto.Cipher import AES
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False


def _vscode_github_token():
    """Extract GitHub token from VS Code's encrypted local storage (macOS only)."""
    if not _CRYPTO_AVAILABLE:
        return None
    try:
        safe_pwd = subprocess.run(
            ["security", "find-generic-password", "-s", "Code Safe Storage", "-a", "Code Key", "-w"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        if not safe_pwd:
            return None
        db_path = Path.home() / "Library/Application Support/Code/User/globalStorage/state.vscdb"
        if not db_path.exists():
            return None
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT value FROM ItemTable WHERE key = ?",
            ('secret://{"extensionId":"vscode.github-authentication","key":"github.auth"}',))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        encrypted = bytes(json.loads(row[0])["data"])
        key_bytes = hashlib.pbkdf2_hmac("sha1", safe_pwd.encode(), b"saltysalt", 1003, dklen=16)
        cipher = AES.new(key_bytes, AES.MODE_CBC, b" " * 16)
        dec = cipher.decrypt(encrypted[3:])
        dec = dec[:-dec[-1]]
        sessions = json.loads(dec.decode("utf-8"))
        for s in sessions:
            scopes = s.get("scopes", [])
            if "repo" in scopes and "workflow" in scopes:
                return s["accessToken"]
        return sessions[0]["accessToken"] if sessions else None
    except Exception:
        return None


def _refresh_copilot_token(gh_token):
    """Exchange GitHub token for a short-lived Copilot API token."""
    result = subprocess.run([
        "curl", "-s", "https://api.github.com/copilot_internal/v2/token",
        "-H", f"Authorization: Bearer {gh_token}",
        "-H", "Accept: application/json",
        "-H", "editor-version: vscode/1.96.0",
        "-H", "Copilot-Integration-Id: vscode-chat",
    ], capture_output=True, text=True, timeout=10)
    d = json.loads(result.stdout)
    token = d["token"]
    endpoints = d.get("endpoints", {})
    if isinstance(endpoints, str):
        endpoints = json.loads(endpoints)
    api_url = endpoints.get("api", "https://api.individual.githubcopilot.com")
    return token, api_url, int(d.get("expires_at", 0))


def get_copilot_token():
    """Get a valid Copilot API token, refreshing from cache if possible."""
    now = int(time.time())
    if TOKEN_CACHE.exists():
        try:
            cached = json.loads(TOKEN_CACHE.read_text())
            if cached.get("expires_at", 0) > now + 60:
                return cached["token"], cached["api_url"]
        except Exception:
            pass
    gh_token = _vscode_github_token()
    if not gh_token:
        return None, None
    try:
        token, api_url, expires_at = _refresh_copilot_token(gh_token)
        TOKEN_CACHE.write_text(json.dumps({"token": token, "api_url": api_url, "expires_at": expires_at}))
        return token, api_url
    except Exception:
        return None, None


def call_copilot(prompt, model="gpt-4.1"):
    """Send a prompt to the Copilot chat completions API. Returns None on failure."""
    token, api_url = get_copilot_token()
    if not token:
        return None

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 150,
        "temperature": 0.3,
    }).encode()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Copilot-Integration-Id": "vscode-chat",
        "editor-version": "vscode/1.96.0",
        "openai-intent": "conversation-panel",
    }

    try:
        req = urllib.request.Request(f"{api_url}/chat/completions",
            data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            TOKEN_CACHE.unlink(missing_ok=True)
        return None
    except Exception:
        return None


def is_available():
    """Check if Copilot backend is usable (VS Code installed + signed in, pycryptodome available)."""
    if not _CRYPTO_AVAILABLE:
        return False
    db_path = Path.home() / "Library/Application Support/Code/User/globalStorage/state.vscdb"
    return db_path.exists()
