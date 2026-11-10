# Contributing to ShellBuddy

Thank you for your interest in improving ShellBuddy. We welcome contributions that maintain our high standards of speed, reliability, and security without adding unnecessary complexity.

---

## Code of Conduct & Principles

1. **Sub-millisecond Performance:** The local Knowledge Base (Layer 1a) must always remain sub-millisecond (<50 µs per scan average). Any changes to pattern compilation or matching must be verified with `make demo`.
2. **Never Break Developer Workflow:** ShellBuddy must never block shell prompt responsiveness or execute commands autonomously.
3. **Defense-in-Depth Security:** Any feature handling command inputs, shell history, or AI prompts must sanitize credentials, passwords, and tokens.
4. **Standard Library First:** Avoid introducing heavyweight third-party dependencies. ShellBuddy relies on the Python standard library for its core dispatcher and tests.

---

## Development Setup

ShellBuddy requires Python 3.9+ and `zsh`.

```bash
# Clone repository
git clone https://github.com/bhargavachary/shellbuddy.git
cd shellbuddy

# Run local syntax check and test suite
make lint
make test

# Run the live KB micro-benchmark and demonstration
make demo
```

---

## Contributing Rules & Knowledge Base

The Knowledge Base (`kb.json`) is precompiled from structured sources.
- **Do not hand-edit `kb.json` directly.**
- Edit the generator source `kb_builder.py`.
- Rebuild the compiled database with:
  ```bash
  make build-kb
  ```
- Run `make test` and `make demo` to ensure patterns compile cleanly and benchmark performance is maintained.

---

## Testing & Validation Requirements

Before submitting a Pull Request:
1. Run syntax validation:
   ```bash
   make lint
   ```
2. Run the unit test suite:
   ```bash
   make test
   ```
3. Run the demonstration microbenchmark:
   ```bash
   make demo
   ```
4. If modifying command matching or security logic, add corresponding unit tests in `tests/test_safety.py` or `tests/test_kb_engine.py`.

---

## Pull Request Guidelines

1. Create a descriptive feature branch:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Keep commits atomic and logically separated.
3. Fill out the Pull Request template completely.
4. Do not include generated local state or private configuration files (`~/.shellbuddy/`, `*.pid`, `*.lock`).
