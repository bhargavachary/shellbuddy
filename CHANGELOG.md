# Changelog

All notable changes to ShellBuddy will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Two-Layer Credential Scrubbing:** Implemented `scrub_command()` and `is_sensitive_command()` in `scripts/hint_daemon.py`, actively masking secrets, tokens, AWS keys, and Bearer headers in ingested command lines and LLM prompts.
- **Prefix & Wrapper Command Normalization:** Implemented `extract_command_token_and_tail()` in `kb_engine.py`, ensuring commands run via `sudo`, `sudo -u`, `sudo -E`, absolute paths (`/usr/bin/git`), or environment variables (`CUDA_VISIBLE_DEVICES=0 ...`) correctly match knowledge base rules.
- **Security & Dispatcher Unit Tests:** Added 12 new unit tests covering wrapper normalization, prefix parsing, token scrubbing, and sudo safety flags (expanding test suite from 139 to 151 passing tests).
- **Open Source Governance Documentation:** Added comprehensive `CONTRIBUTING.md`, `SECURITY.md`, PR template, and GitHub issue templates.

### Fixed
- Fixed silent rule bypass in `kb_engine.py` where anchored rules (`^git`, `^chmod`) failed to match commands prefixed with `sudo` or environment variable assignments.
- Fixed mock test verification in `test_safety.py` by binding directly to daemon production scrubbing logic.

### Security
- Added explicit `permissions: contents: read` to `.github/workflows/ci.yml`.

---

## [0.2.0] - 2026-11-08

### Added
- Dispatcher-based `kb_engine.py` replacing flat linear rule scans with sub-millisecond bucket indexing (1,835 rules across 336 buckets).
- Standalone interactive demo and microbenchmark runner `scripts/demo.py`.
- Automated GitHub Actions CI workflow supporting Linux and macOS across Python 3.9 through 3.12.
- Common developer `Makefile` targets: `test`, `lint`, `demo`, `dist`, `release`, `clean`.
