# shellbuddy — Makefile
#
# Targets:
#   make dist         Build a distribution tarball for the current version
#   make release      Run tests + dist, then print tagging instructions
#   make test         Run the full test suite
#   make lint         Syntax-check all Python files
#   make clean        Remove built tarballs

VERSION  ?= $(shell git describe --tags --exact-match 2>/dev/null || git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0-dev")
DIST_NAME = shellbuddy-$(VERSION)
DIST_FILE = $(DIST_NAME).tar.gz

PYTHON    ?= $(shell command -v .venv/bin/python 2>/dev/null || echo python3)
GIT       ?= git

.DEFAULT_GOAL := help

# ── Help ──────────────────────────────────────────────────────────────────────
.PHONY: help
help:
	@echo ""
	@echo "  shellbuddy build targets"
	@echo "  ────────────────────────────"
	@echo "  make test      Run 131-test suite"
	@echo "  make lint      Syntax-check Python files"
	@echo "  make dist      Build $(DIST_FILE)"
	@echo "  make release   test + dist + tagging instructions"
	@echo "  make clean     Remove built .tar.gz files"
	@echo ""
	@echo "  Releasing a new version:"
	@echo "    git tag v1.2.3 -m 'Release v1.2.3'"
	@echo "    git push origin v1.2.3"
	@echo "    (GitHub Actions will build + publish the release automatically)"
	@echo ""

# ── Test ──────────────────────────────────────────────────────────────────────
.PHONY: test
test:
	@echo ""
	@echo "  Running shellbuddy test suite..."
	@$(PYTHON) -m unittest discover -s tests 2>&1 | tail -5
	@echo ""

# ── Lint (syntax only) ────────────────────────────────────────────────────────
.PHONY: lint
lint:
	@echo "  Checking Python syntax..."
	@$(PYTHON) -m py_compile scripts/hint_daemon.py    && echo "  OK  scripts/hint_daemon.py"
	@$(PYTHON) -m py_compile kb_engine.py              && echo "  OK  kb_engine.py"
	@$(PYTHON) -m py_compile kb_builder.py             && echo "  OK  kb_builder.py"
	@$(PYTHON) -m py_compile backends/copilot.py       && echo "  OK  backends/copilot.py"
	@$(PYTHON) -m py_compile backends/ollama.py        && echo "  OK  backends/ollama.py"
	@$(PYTHON) -m py_compile backends/openai_compat.py && echo "  OK  backends/openai_compat.py"
	@echo "  All syntax checks passed."

# ── Dist tarball ──────────────────────────────────────────────────────────────
# Uses `git archive` — produces a perfectly clean tarball:
#   - No .git history
#   - No .venv or __pycache__
#   - No test files (tests/ is not included in releases)
#   - Preserves file permissions
.PHONY: dist
dist: lint
	@echo ""
	@echo "  Building distribution tarball: $(DIST_FILE)"
	@$(GIT) archive \
		--format=tar.gz \
		--prefix=$(DIST_NAME)/ \
		--output=$(DIST_FILE) \
		HEAD \
		-- \
		install.sh \
		uninstall.sh \
		kb_engine.py \
		kb.json \
		requirements.txt \
		LICENSE \
		USAGE.md \
		SETUP.md \
		backends/__init__.py \
		backends/copilot.py \
		backends/ollama.py \
		backends/openai_compat.py \
		scripts/hint_daemon.py \
		scripts/log_cmd.sh \
		scripts/show_hints.sh \
		scripts/show_stats.sh \
		scripts/start_daemon.sh \
		scripts/toggle_hints_pane.sh \
		scripts/verify.sh \
		scripts/bootstrap.sh \
		config/
	@echo ""
	@echo "  Created: $(DIST_FILE)"
	@echo "  SHA256:  $$(shasum -a 256 $(DIST_FILE) | awk '{print $$1}')"
	@echo ""

# ── Release ───────────────────────────────────────────────────────────────────
.PHONY: release
release: test dist
	@echo "  ─────────────────────────────────────────────────"
	@echo "  Ready to release $(VERSION)"
	@echo ""
	@echo "  1. Tag and push to trigger GitHub Actions:"
	@echo "       git tag $(VERSION) -m 'Release $(VERSION)'"
	@echo "       git push origin $(VERSION)"
	@echo ""
	@echo "  2. After the release is created, update the Homebrew formula:"
	@echo "       Formula/shellbuddy.rb — url + sha256"
	@echo "       Then push to github.com/bhargavachary/homebrew-shellbuddy"
	@echo "  ─────────────────────────────────────────────────"
	@echo ""

# ── Clean ─────────────────────────────────────────────────────────────────────
.PHONY: clean
clean:
	@rm -f shellbuddy-*.tar.gz
	@echo "  Cleaned dist artifacts."
