# Security Policy

ShellBuddy is designed around strict privacy, safety, and defensive engineering principles. Because ShellBuddy monitors terminal command activity to provide relevant assistance, security and privacy boundaries are treated with the highest priority.

---

## Supported Versions

| Version | Supported |
|---|---|
| `main` (v0.2.x) | Yes |
| < v0.2.0 | No |

---

## Security Architecture & Defenses

1. **Passive Read-Only Monitoring:**
   - Commands are intercepted via a non-blocking `zsh` `preexec` hook.
   - ShellBuddy **never executes commands autonomously** or modifies your shell environment without explicit user action.

2. **Multi-Tier Secret Sanitization:**
   - **Layer 1 (Shell-Level):** `scripts/log_cmd.sh` filters out commands matching known secret patterns (e.g., `api_key`, `secret`, `password`, `bearer `, `access_token`, `ghp_`, `aws_access_key`, `aws_secret`, `id_rsa`, `export *key=`, etc.) before they are ever written to disk.
   - **Layer 2 (Daemon-Level):** `scripts/hint_daemon.py` applies `scrub_command()` across all ingested JSONL lines and context logs, redacting API keys, Bearer tokens, GitHub PATs, AWS access keys, and passwords to `[REDACTED]`.
   - **Layer 3 (Backend Defense):** Remote LLM backends receive only sanitized summaries, ensuring that credentials cannot be transmitted over external network connections.

3. **Offline Knowledge Base:**
   - The core dispatch engine (`kb_engine.py`) operates entirely offline with zero network calls, zero external API keys, and microsecond-scale execution.

---

## Reporting a Vulnerability

If you discover a security vulnerability or credential leak within ShellBuddy, please do **not** open a public issue.

Instead, please send a responsible disclosure report to:
- **Email:** `contact@bhargavachary.com` or via the private contact form at [`https://bhargav.work/contact/`](https://bhargav.work/contact/).

Please include:
- A description of the vulnerability.
- Steps or a minimal reproducible command sequence to trigger the issue.
- The version or git commit hash of ShellBuddy tested.
- Your assessment of potential impact.

We will acknowledge receipt of your report within 48 hours and work with you to test and deploy a fix prior to public disclosure.
