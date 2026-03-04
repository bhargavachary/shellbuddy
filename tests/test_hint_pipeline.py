"""
tests/test_hint_pipeline.py
Integration tests for the hint pipeline:
  - get_rule_hints: silencing, severity filter, tag filter
  - unified context: ctx_append, ctx_read, ctx_compact, ctx_to_prompt_block
  - _load_silenced_rules: expiry logic
  - _sanitize_for_ctx: control chars, truncation
  - _is_git_commit: trigger detection
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hint_daemon as hd
from kb_engine import KBEngine


# ── Fixture KB ────────────────────────────────────────────────────────────────

FIXTURE_KB = [
    {"id": "git-001",    "pattern": r"^git\s+push\s+--force(\s|$)", "cmd": "git",
     "severity": "danger",  "hint": "Use --force-with-lease",
     "detail": "Safer force push.", "tags": ["push", "safety"]},
    {"id": "gnu-002",    "pattern": r"^cat\s+", "cmd": "cat",
     "severity": "upgrade", "hint": "cat → bat {arg}",
     "detail": "bat adds color.", "tags": ["cat", "modernize"]},
    {"id": "docker-001", "pattern": r"^docker\s+ps\b", "cmd": "docker",
     "severity": "tip",     "hint": "docker ps → lazydocker",
     "detail": "Use lazydocker.", "tags": ["docker", "tui"]},
    {"id": "gnu-safe",   "pattern": r"^rm\s+-rf\s+\.\s*$", "cmd": "rm",
     "severity": "danger",  "hint": "rm -rf . deletes CWD",
     "detail": "Dangerous.", "tags": ["rm", "danger"]},
]


def _engine(rules=None):
    td = tempfile.mkdtemp()
    p = os.path.join(td, "kb.json")
    json.dump(rules or FIXTURE_KB, open(p, "w"))
    return KBEngine(p)


def _cmds(*texts):
    return [{"cmd": t, "ts": "12:00:00", "cwd": "~"} for t in texts]


# ── get_rule_hints filtering ──────────────────────────────────────────────────

class TestGetRuleHintsFiltering(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        hd._KB_ENGINE = _engine()
        hd.SEVERITY_FILTER = []
        hd.TAG_FILTER      = []
        hd.RULE_COOLDOWN   = 0
        hd.SILENCED_RULES  = Path(self.tmpdir) / "silenced_rules.json"

    def tearDown(self):
        hd.SEVERITY_FILTER = []
        hd.TAG_FILTER      = []

    def _ids(self, *cmds_txt, **kw):
        return [h[0] for h in hd.get_rule_hints(_cmds(*cmds_txt), {})]

    # No filter — all matches must come through
    def test_no_filter_passes_everything(self):
        ids = self._ids("git push --force", "cat file.txt", "docker ps")
        self.assertIn("git-001",    ids)
        self.assertIn("gnu-002",    ids)

    # Severity filter
    def test_severity_filter_danger_only(self):
        hd.SEVERITY_FILTER = ["danger"]
        ids = self._ids("git push --force", "cat file.txt", "docker ps")
        self.assertIn("git-001",    ids)
        self.assertNotIn("gnu-002",    ids)  # upgrade
        self.assertNotIn("docker-001", ids)  # tip

    def test_severity_filter_upgrade_only(self):
        hd.SEVERITY_FILTER = ["upgrade"]
        ids = self._ids("cat file.txt", "docker ps")
        self.assertIn("gnu-002", ids)
        self.assertNotIn("docker-001", ids)

    def test_severity_filter_empty_passes_all(self):
        hd.SEVERITY_FILTER = []
        ids = self._ids("cat file.txt", "docker ps")
        self.assertIn("gnu-002",    ids)
        self.assertIn("docker-001", ids)

    # Tag filter by cmd field
    def test_tag_filter_by_cmd_field(self):
        hd.TAG_FILTER = ["git"]
        ids = self._ids("git push --force", "cat file.txt", "docker ps")
        self.assertIn("git-001",       ids)
        self.assertNotIn("gnu-002",    ids)
        self.assertNotIn("docker-001", ids)

    # Tag filter by entry tags list
    def test_tag_filter_by_tags_list(self):
        hd.TAG_FILTER = ["tui"]  # "tui" is in docker-001 tags, not in git-001
        ids = self._ids("git push --force", "cat file.txt", "docker ps")
        self.assertIn("docker-001",  ids)
        self.assertNotIn("git-001",  ids)
        self.assertNotIn("gnu-002",  ids)

    def test_tag_filter_empty_passes_all(self):
        hd.TAG_FILTER = []
        ids = self._ids("cat file.txt", "docker ps")
        self.assertIn("gnu-002",    ids)
        self.assertIn("docker-001", ids)

    # Combined severity + tag
    def test_severity_and_tag_combined(self):
        hd.SEVERITY_FILTER = ["danger"]
        hd.TAG_FILTER      = ["git"]
        ids = self._ids("git push --force", "rm -rf .")
        self.assertIn("git-001",   ids)
        self.assertNotIn("gnu-safe", ids)  # danger but cmd=rm not in TAG_FILTER

    # Silencing
    def test_active_silence_suppresses(self):
        hd.SILENCED_RULES.write_text(json.dumps({"gnu-002": int(time.time() + 9999)}))
        ids = self._ids("cat file.txt")
        self.assertNotIn("gnu-002", ids)

    def test_expired_silence_allows_through(self):
        hd.SILENCED_RULES.write_text(json.dumps({"gnu-002": int(time.time() - 1)}))
        ids = self._ids("cat file.txt")
        self.assertIn("gnu-002", ids)

    def test_permanent_silence_suppresses(self):
        hd.SILENCED_RULES.write_text(json.dumps({"gnu-002": 0}))
        ids = self._ids("cat file.txt")
        self.assertNotIn("gnu-002", ids)

    def test_silence_only_affects_named_rule(self):
        hd.SILENCED_RULES.write_text(json.dumps({"gnu-002": int(time.time() + 9999)}))
        ids = self._ids("git push --force")
        self.assertIn("git-001", ids)


# ── _load_silenced_rules ──────────────────────────────────────────────────────

class TestLoadSilencedRules(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        hd.SILENCED_RULES = Path(self.tmpdir) / "silenced.json"

    def test_missing_file_returns_empty(self):
        self.assertEqual(hd._load_silenced_rules(), {})

    def test_bad_json_returns_empty(self):
        hd.SILENCED_RULES.write_text("not json {]")
        self.assertEqual(hd._load_silenced_rules(), {})

    def test_permanent_zero_expiry_kept(self):
        hd.SILENCED_RULES.write_text(json.dumps({"rule-001": 0}))
        self.assertIn("rule-001", hd._load_silenced_rules())

    def test_future_expiry_kept(self):
        hd.SILENCED_RULES.write_text(json.dumps({"rule-001": int(time.time() + 3600)}))
        self.assertIn("rule-001", hd._load_silenced_rules())

    def test_past_expiry_filtered(self):
        hd.SILENCED_RULES.write_text(json.dumps({"rule-001": int(time.time() - 1)}))
        self.assertNotIn("rule-001", hd._load_silenced_rules())

    def test_mixed_expiry(self):
        data = {
            "active":   int(time.time() + 3600),
            "expired":  int(time.time() - 1),
            "permanent": 0,
        }
        hd.SILENCED_RULES.write_text(json.dumps(data))
        result = hd._load_silenced_rules()
        self.assertIn("active",    result)
        self.assertIn("permanent", result)
        self.assertNotIn("expired", result)


# ── Unified context ───────────────────────────────────────────────────────────

class TestCtxAppendAndRead(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_ctx = hd.UNIFIED_CTX
        hd.UNIFIED_CTX = Path(self.tmpdir) / "ctx.jsonl"
        hd._ctx_append_count = 0

    def tearDown(self):
        hd.UNIFIED_CTX = self._orig_ctx

    def test_append_and_read_back(self):
        hd.ctx_append({"type": "cmd", "cmd": "git status"})
        hd.ctx_append({"type": "tip_q", "query": "how to rebase"})
        entries = hd.ctx_read(n=10)
        types = [e["type"] for e in entries]
        self.assertIn("cmd",   types)
        self.assertIn("tip_q", types)

    def test_timestamp_added(self):
        hd.ctx_append({"type": "cmd", "cmd": "echo"})
        entries = hd.ctx_read(n=5)
        self.assertIn("ts", entries[0])

    def test_read_n_limits_to_n_entries(self):
        for i in range(10):
            hd.ctx_append({"type": "cmd", "cmd": f"cmd_{i}"})
        entries = hd.ctx_read(n=3)
        self.assertEqual(len(entries), 3)

    def test_read_returns_newest_last(self):
        for i in range(5):
            hd.ctx_append({"type": "cmd", "cmd": f"cmd_{i}"})
        entries = hd.ctx_read(n=3)
        self.assertEqual(entries[-1]["cmd"], "cmd_4")

    def test_compact_trims_to_ctx_max(self):
        orig_max = hd.CTX_MAX
        hd.CTX_MAX = 5
        for i in range(15):
            hd.ctx_append({"type": "cmd", "cmd": f"cmd_{i}"})
        hd._ctx_compact()
        entries = hd.ctx_read(n=100)
        self.assertLessEqual(len(entries), 5)
        hd.CTX_MAX = orig_max

    def test_compact_keeps_most_recent(self):
        orig_max = hd.CTX_MAX
        hd.CTX_MAX = 3
        for i in range(10):
            hd.ctx_append({"type": "cmd", "cmd": f"cmd_{i}"})
        hd._ctx_compact()
        entries = hd.ctx_read(n=100)
        cmds = [e["cmd"] for e in entries if e.get("type") == "cmd"]
        self.assertIn("cmd_9", cmds)
        self.assertNotIn("cmd_0", cmds)
        hd.CTX_MAX = orig_max

    def test_empty_context_returns_empty_list(self):
        self.assertEqual(hd.ctx_read(n=10), [])

    def test_malformed_line_skipped_gracefully(self):
        hd.UNIFIED_CTX.write_text('{"type":"cmd","cmd":"ok","ts":"10:00"}\nnot json\n{"type":"cmd","cmd":"ok2","ts":"10:01"}\n')
        entries = hd.ctx_read(n=10)
        self.assertEqual(len(entries), 2)


class TestCtxToPromptBlock(unittest.TestCase):

    def test_cmd_entry_formatted(self):
        entries = [{"type": "cmd", "cmd": "git push", "ts": "10:00"}]
        block = hd.ctx_to_prompt_block(entries)
        self.assertIn("ran: git push", block)

    def test_tip_q_formatted(self):
        entries = [{"type": "tip_q", "query": "how to rebase", "ts": "10:01"}]
        block = hd.ctx_to_prompt_block(entries)
        self.assertIn("asked: how to rebase", block)

    def test_advisor_entry_formatted(self):
        entries = [{"type": "advisor", "intent": "pushing code",
                    "observation": "often force-pushing", "prediction": "git push", "ts": "10:02"}]
        block = hd.ctx_to_prompt_block(entries)
        self.assertIn("intent: pushing code", block)
        self.assertIn("note: often force-pushing", block)

    def test_empty_entries_returns_empty_string(self):
        self.assertEqual(hd.ctx_to_prompt_block([]), "")


# ── _sanitize_for_ctx ─────────────────────────────────────────────────────────

class TestSanitizeForCtx(unittest.TestCase):

    def test_strips_null_bytes(self):
        self.assertNotIn("\x00", hd._sanitize_for_ctx("hello\x00world"))

    def test_strips_control_chars(self):
        dirty = "".join(chr(i) for i in range(0, 32))
        clean = hd._sanitize_for_ctx(dirty)
        for c in clean:
            self.assertGreater(ord(c), 31)

    def test_truncates_to_max_len(self):
        s = "a" * 500
        self.assertLessEqual(len(hd._sanitize_for_ctx(s, max_len=100)), 100)

    def test_normal_string_unchanged(self):
        s = "git push --force origin main"
        self.assertEqual(hd._sanitize_for_ctx(s), s)

    def test_round_trips_json(self):
        # _sanitize_for_ctx guarantees the result is JSON-safe
        result = hd._sanitize_for_ctx("hello 'world' \"test\"")
        json.dumps(result)  # should not raise


# ── _is_git_commit ────────────────────────────────────────────────────────────

class TestIsGitCommit(unittest.TestCase):

    def _t(self, cmd): return hd._is_git_commit(cmd)

    def test_plain_git_commit_triggers(self):
        self.assertTrue(self._t("git commit"))
        self.assertTrue(self._t("git commit -a"))
        self.assertTrue(self._t("git commit -av"))

    def test_commit_with_m_flag_skipped(self):
        self.assertFalse(self._t("git commit -m 'fix bug'"))
        self.assertFalse(self._t("git commit -am 'fix'"))
        self.assertFalse(self._t("git commit --message='test'"))

    def test_commit_no_edit_skipped(self):
        self.assertFalse(self._t("git commit --no-edit"))

    def test_non_commit_commands_skipped(self):
        self.assertFalse(self._t("git push origin main"))
        self.assertFalse(self._t("git status"))
        self.assertFalse(self._t("echo hello"))
        self.assertFalse(self._t("git add ."))
        self.assertFalse(self._t(""))

    def test_whitespace_tolerant(self):
        self.assertTrue(self._t("  git commit  "))


# ── _parse_jsonl_lines ────────────────────────────────────────────────────────

class TestParseJsonlLines(unittest.TestCase):

    def test_valid_lines(self):
        lines = ['{"a":1}', '{"b":2}']
        result = hd._parse_jsonl_lines(lines)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["a"], 1)

    def test_bad_lines_skipped(self):
        lines = ['{"a":1}', 'not json', '{"b":2}']
        result = hd._parse_jsonl_lines(lines)
        self.assertEqual(len(result), 2)

    def test_empty_lines_skipped(self):
        lines = ['', '   ', '{"a":1}']
        result = hd._parse_jsonl_lines(lines)
        self.assertEqual(len(result), 1)

    def test_all_bad_returns_empty(self):
        self.assertEqual(hd._parse_jsonl_lines(["bad", "also bad"]), [])


if __name__ == "__main__":
    unittest.main()
