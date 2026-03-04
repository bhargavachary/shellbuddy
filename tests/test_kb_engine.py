"""
tests/test_kb_engine.py
Unit tests for kb_engine.KBEngine: loading, scanning, hint ranking.
Runs with: python3 -m pytest tests/ -v
        or: python3 -m unittest discover tests/
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kb_engine import KBEngine, SEVERITY_PREFIX


# ── Minimal KB fixture ────────────────────────────────────────────────────────

SAMPLE_KB = [
    {
        "id":       "git-001",
        "pattern":  r"^git\s+push\s+--force(\s|$)",
        "cmd":      "git",
        "severity": "danger",
        "hint":     "Use --force-with-lease instead of --force",
        "detail":   "Safer force push that checks upstream for changes.",
        "tags":     ["push", "safety", "collaboration"],
    },
    {
        "id":       "gnu-001",
        "pattern":  r"^rm\s+-rf\s+/$",
        "cmd":      "rm",
        "severity": "danger",
        "hint":     "Never run rm -rf / — erases entire filesystem",
        "detail":   "Destroys all files on the system.",
        "tags":     ["rm", "danger", "filesystem"],
    },
    {
        "id":       "gnu-002",
        "pattern":  r"^cat\s+",
        "cmd":      "cat",
        "severity": "upgrade",
        "hint":     "cat → bat {arg}  (syntax highlighting + git diff)",
        "detail":   "bat is a cat clone with syntax highlighting.",
        "tags":     ["cat", "modernize", "fileview"],
    },
    {
        "id":       "docker-001",
        "pattern":  r"^docker\s+ps\b",
        "cmd":      "docker",
        "severity": "tip",
        "hint":     "docker ps → lazydocker  (full TUI)",
        "detail":   "lazydocker provides an interactive TUI for Docker.",
        "tags":     ["docker", "tui"],
    },
    {
        "id":       "docker-002",
        "pattern":  r"^docker\s+logs\b",
        "cmd":      "docker",
        "severity": "tip",
        "hint":     "docker logs → lazydocker  (live log + filter)",
        "detail":   "View logs interactively with filtering.",
        "tags":     ["docker", "logs"],
    },
]


def _make_kb(rules=None):
    """Write SAMPLE_KB (or given rules) to a temp file and return a loaded engine."""
    td = tempfile.mkdtemp()
    path = os.path.join(td, "kb.json")
    with open(path, "w") as f:
        json.dump(rules if rules is not None else SAMPLE_KB, f)
    return KBEngine(path)


def _cmds(*texts):
    return [{"cmd": t, "ts": "12:00:00", "cwd": "~"} for t in texts]


# ── Load tests ────────────────────────────────────────────────────────────────

class TestKBEngineLoad(unittest.TestCase):

    def test_loads_all_rules(self):
        e = _make_kb()
        self.assertEqual(e._count, len(SAMPLE_KB))

    def test_loaded_flag_true(self):
        self.assertTrue(_make_kb().loaded)

    def test_none_path_uses_default(self):
        # KBEngine(None) falls back to the real KB path; loaded iff the file exists.
        e = KBEngine(None)
        self.assertIsInstance(e.loaded, bool)  # True when real KB present, False when not

    def test_missing_file_not_loaded(self):
        self.assertFalse(KBEngine("/nonexistent/kb.json").loaded)

    def test_invalid_json_not_loaded(self):
        td = tempfile.mkdtemp()
        bad = os.path.join(td, "bad.json")
        open(bad, "w").write("not json at all {]")
        self.assertFalse(KBEngine(bad).loaded)

    def test_invalid_regex_skipped(self):
        bad_entry = {"id": "bad-001", "pattern": r"[invalid",
                     "cmd": "bad", "severity": "tip",
                     "hint": "bad", "detail": "bad", "tags": []}
        e = _make_kb(SAMPLE_KB + [bad_entry])
        # valid rules loaded, bad regex silently skipped
        self.assertEqual(e._count, len(SAMPLE_KB))

    def test_buckets_keyed_by_cmd(self):
        e = _make_kb()
        self.assertIn("git",    e._buckets)
        self.assertIn("rm",     e._buckets)
        self.assertIn("cat",    e._buckets)
        self.assertIn("docker", e._buckets)

    def test_docker_has_two_rules(self):
        e = _make_kb()
        self.assertEqual(len(e._buckets["docker"]), 2)

    def test_stats_dict_has_expected_keys(self):
        e = _make_kb()
        s = e.stats
        self.assertIn("total",   s)
        self.assertIn("buckets", s)
        self.assertIn("generic", s)
        self.assertIn("load_ms", s)


# ── Scan tests ────────────────────────────────────────────────────────────────

class TestKBEngineScan(unittest.TestCase):

    def setUp(self):
        self.e = _make_kb()

    def test_scan_danger_match(self):
        m = self.e.scan("git push --force origin main")
        ids = [e["id"] for e in m]
        self.assertIn("git-001", ids)

    def test_scan_no_match(self):
        self.assertEqual(self.e.scan("echo hello world"), [])

    def test_scan_empty_string(self):
        self.assertEqual(self.e.scan(""), [])

    def test_scan_whitespace_only(self):
        self.assertEqual(self.e.scan("   "), [])

    def test_scan_sudo_prefix_resolves_token(self):
        # "sudo git push --force" → first_token becomes "git" bucket
        # Use non-anchored pattern so regex matches inside the full command string.
        extra = [{
            "id": "git-sudo-t", "pattern": r"git\s+push\s+--force",
            "cmd": "git", "severity": "danger",
            "hint": "Use --force-with-lease", "detail": "", "tags": [],
        }]
        e = _make_kb(extra)
        m = e.scan("sudo git push --force origin main")
        ids = [x["id"] for x in m]
        self.assertIn("git-sudo-t", ids)

    def test_scan_env_var_prefix(self):
        # "MY_VAR=1 cat file.txt" → first_token becomes "cat" bucket
        extra = [{
            "id": "cat-env-t", "pattern": r"cat\s+",
            "cmd": "cat", "severity": "upgrade",
            "hint": "cat → bat", "detail": "", "tags": [],
        }]
        e = _make_kb(extra)
        m = e.scan("MY_VAR=1 cat file.txt")
        ids = [x["id"] for x in m]
        self.assertIn("cat-env-t", ids)

    def test_scan_returns_entry_fields(self):
        m = self.e.scan("docker ps -a")
        self.assertTrue(any(e["cmd"] == "docker" for e in m))
        self.assertTrue(any("severity" in e for e in m))
        self.assertTrue(any("tags" in e for e in m))

    def test_scan_bucket_miss_fallback_catches_nothing(self):
        # A command not in any bucket should return no matches
        self.assertEqual(self.e.scan("zzz_unknown_command --foo"), [])


# ── Hint ranking tests ────────────────────────────────────────────────────────

class TestKBEngineGetHints(unittest.TestCase):

    def setUp(self):
        self.e = _make_kb()

    def test_single_match_returns_hint(self):
        cmds = _cmds("git push --force origin main")
        results = self.e.get_hints(cmds, {})
        self.assertTrue(len(results) > 0)
        rid, hint_str, entry = results[0]
        self.assertEqual(rid, "git-001")
        self.assertIn("force-with-lease", hint_str)

    def test_danger_prefix_in_hint(self):
        cmds = _cmds("git push --force origin main")
        rid, hint_str, entry = self.e.get_hints(cmds, {})[0]
        self.assertTrue(hint_str.startswith(SEVERITY_PREFIX["danger"]))

    def test_upgrade_prefix_in_hint(self):
        cmds = _cmds("cat file.txt")
        results = self.e.get_hints(cmds, {}, cooldown=0)
        self.assertTrue(any(hs.startswith(SEVERITY_PREFIX["upgrade"]) for _, hs, _ in results))

    def test_max_three_hints(self):
        cmds = _cmds("git push --force", "cat file.txt", "docker ps", "rm -rf /")
        results = self.e.get_hints(cmds, {}, cooldown=0)
        self.assertLessEqual(len(results), 3)

    def test_cooldown_suppresses_non_danger(self):
        cmds = _cmds("cat file.txt")
        last_shown = {"gnu-002": time.time() - 10}  # shown 10s ago
        results = self.e.get_hints(cmds, last_shown, cooldown=120)
        ids = [r[0] for r in results]
        self.assertNotIn("gnu-002", ids)

    def test_danger_bypasses_cooldown(self):
        cmds = _cmds("git push --force origin")
        last_shown = {"git-001": time.time() - 10}  # shown 10s ago
        results = self.e.get_hints(cmds, last_shown, cooldown=120)
        ids = [r[0] for r in results]
        self.assertIn("git-001", ids)  # danger always shows

    def test_frequency_affects_ordering(self):
        # cat appears 3×, git appears 1× — cat should rank higher
        cmds = _cmds("cat f1", "cat f2", "cat f3", "git push --force")
        results = self.e.get_hints(cmds, {}, cooldown=0)
        self.assertEqual(results[0][0], "gnu-002")

    def test_no_cmds_returns_empty(self):
        self.assertEqual(self.e.get_hints([], {}), [])

    def test_hint_contains_count(self):
        cmds = _cmds("cat a", "cat b")
        results = self.e.get_hints(cmds, {}, cooldown=0)
        # Hint should contain "[2x]"
        self.assertTrue(any("[2x]" in hs for _, hs, _ in results))


# ── Detail context tests ──────────────────────────────────────────────────────

class TestKBEngineDetailContext(unittest.TestCase):

    def setUp(self):
        self.e = _make_kb()

    def test_returns_hint_and_detail(self):
        cmds = _cmds("git push --force origin main")
        ctx = self.e.get_detail_context(cmds, n=1)
        self.assertIn("force-with-lease", ctx)
        self.assertIn("DANGER", ctx)

    def test_no_match_returns_empty_string(self):
        cmds = _cmds("echo hello world")
        ctx = self.e.get_detail_context(cmds, n=3)
        self.assertEqual(ctx, "")

    def test_n_limits_results(self):
        cmds = _cmds("git push --force", "cat file.txt", "docker ps")
        ctx = self.e.get_detail_context(cmds, n=1)
        # Only 1 rule's detail should appear
        self.assertEqual(ctx.count("[DANGER]") + ctx.count("[UPGRADE]") + ctx.count("[TIP]"), 1)


if __name__ == "__main__":
    unittest.main()
