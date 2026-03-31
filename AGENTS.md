# AGENTS.md — shellbuddy

AI-powered shell assistant — natural language → shell command suggestions with a local knowledge base.

---

## Structure

```
app/                ← core application code
backends/           ← LLM backend connectors
config/             ← configuration files
scripts/            ← helper scripts
tests/              ← test suite
kb.json             ← compiled knowledge base (generated — do not hand-edit)
kb_builder.py       ← builds kb.json from raw sources
kb_engine.py        ← runtime KB lookup engine
requirements.txt    ← Python deps
install.sh          ← installation script
uninstall.sh        ← uninstall script
Makefile            ← common dev tasks
```

---

## Environment

```bash
conda activate base
pip install -r requirements.txt
```

---

## Commands

```bash
make install        # install shellbuddy locally
make test           # run test suite
make build-kb       # rebuild kb.json from sources
```

---

## Rules

- `kb.json` is **generated** — do not manually edit it; rebuild with `kb_builder.py`
- Rate limiting must be preserved in all backend connectors — do not add tight loops
- Keep backends modular — each backend in its own file under `backends/`
- Tests must pass before any commit: `make test`
- No API keys hardcoded anywhere — use config files or env vars
- `install.sh` and `uninstall.sh` must remain idempotent

---

## Owner

**D K Bhargav Achary** — sole maintainer.
