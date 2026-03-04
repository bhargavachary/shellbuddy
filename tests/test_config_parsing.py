"""
tests/test_config_parsing.py
Unit tests for _load_config(): option reading, bounds clamping,
hot-reload detection via mtime, and all 12 new tunable keys.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hint_daemon as hd


class TestLoadConfig(unittest.TestCase):

    # ── original values to restore after each test ────────────────────────────
    _SAVED = {}

    @classmethod
    def setUpClass(cls):
        cls._SAVED = {
            "HINT_BACKEND":      hd.HINT_BACKEND,
            "HINT_MODEL":        hd.HINT_MODEL,
            "HINT_MODEL_CHAIN":  list(hd.HINT_MODEL_CHAIN),
            "TIP_BACKEND":       hd.TIP_BACKEND,
            "TIP_MODEL":         hd.TIP_MODEL,
            "HINT_INTERVAL":     hd.HINT_INTERVAL,
            "AI_THROTTLE":       hd.AI_THROTTLE,
            "RULE_COOLDOWN":     hd.RULE_COOLDOWN,
            "ADVISOR_THROTTLE":  hd.ADVISOR_THROTTLE,
            "ADVISOR_WINDOW":    hd.ADVISOR_WINDOW,
            "CTX_MAX":           hd.CTX_MAX,
            "CTX_INJECT":        hd.CTX_INJECT,
            "IDLE_TIMEOUT":      hd.IDLE_TIMEOUT,
            "SEVERITY_FILTER":   list(hd.SEVERITY_FILTER),
            "TAG_FILTER":        list(hd.TAG_FILTER),
            "ENABLE_POST_MORTEM":hd.ENABLE_POST_MORTEM,
            "ENABLE_IDLE_TIPS":  hd.ENABLE_IDLE_TIPS,
        }

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cfg_file = hd.CONFIG_FILE
        hd.CONFIG_FILE = Path(self.tmpdir) / "config.json"
        hd._config_mtime = 0.0
        # Restore all tunables to original values
        for k, v in self._SAVED.items():
            setattr(hd, k, v)

    def tearDown(self):
        hd.CONFIG_FILE = self._orig_cfg_file
        hd._config_mtime = 0.0

    def _write(self, data: dict):
        hd.CONFIG_FILE.write_text(json.dumps(data))
        hd._config_mtime = 0.0  # force reload on next call

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_missing_file_does_not_crash(self):
        hd.CONFIG_FILE = Path(self.tmpdir) / "nonexistent.json"
        hd._load_config()  # must not raise

    def test_bad_json_does_not_crash(self):
        hd.CONFIG_FILE.write_text("{not: valid json}")
        hd._load_config()  # must not raise

    def test_empty_object_does_not_crash(self):
        self._write({})
        hd._load_config()  # must not raise

    def test_mtime_guard_skips_reload(self):
        """If config file mtime is unchanged, _load_config must skip re-reading."""
        self._write({"hint_interval_secs": 7})
        hd._load_config()
        self.assertEqual(hd.HINT_INTERVAL, 7)

        # Manually clobber the value — _load_config should NOT undo it
        hd.HINT_INTERVAL = 999
        hd._load_config()  # mtime unchanged → should skip
        self.assertEqual(hd.HINT_INTERVAL, 999)

    # ── Backend / model keys ──────────────────────────────────────────────────

    def test_hint_backend_override(self):
        self._write({"hint_backend": "ollama", "hint_model": "llama3"})
        hd._load_config()
        self.assertEqual(hd.HINT_BACKEND, "ollama")
        self.assertEqual(hd.HINT_MODEL,   "llama3")

    def test_tip_backend_override(self):
        self._write({"tip_backend": "claude", "tip_model": "claude-sonnet-4-5-20250514"})
        hd._load_config()
        self.assertEqual(hd.TIP_BACKEND, "claude")
        self.assertEqual(hd.TIP_MODEL,   "claude-sonnet-4-5-20250514")

    def test_hint_model_chain_override(self):
        chain = ["m1", "m2", "m3"]
        self._write({"hint_model_chain": chain})
        hd._load_config()
        self.assertEqual(hd.HINT_MODEL_CHAIN, chain)

    # ── Timing tunables ───────────────────────────────────────────────────────

    def test_hint_interval_secs(self):
        self._write({"hint_interval_secs": 10})
        hd._load_config()
        self.assertEqual(hd.HINT_INTERVAL, 10)

    def test_ai_throttle_secs(self):
        self._write({"ai_throttle_secs": 30})
        hd._load_config()
        self.assertEqual(hd.AI_THROTTLE, 30)

    def test_rule_cooldown_secs(self):
        self._write({"rule_cooldown_secs": 60})
        hd._load_config()
        self.assertEqual(hd.RULE_COOLDOWN, 60)

    def test_rule_cooldown_zero_allowed(self):
        self._write({"rule_cooldown_secs": 0})
        hd._load_config()
        self.assertEqual(hd.RULE_COOLDOWN, 0)

    def test_advisor_throttle_secs(self):
        self._write({"advisor_throttle_secs": 20})
        hd._load_config()
        self.assertEqual(hd.ADVISOR_THROTTLE, 20)

    def test_advisor_window(self):
        self._write({"advisor_window": 200})
        hd._load_config()
        self.assertEqual(hd.ADVISOR_WINDOW, 200)

    def test_context_max_entries(self):
        self._write({"context_max_entries": 500})
        hd._load_config()
        self.assertEqual(hd.CTX_MAX, 500)

    def test_context_inject_entries(self):
        self._write({"context_inject_entries": 50})
        hd._load_config()
        self.assertEqual(hd.CTX_INJECT, 50)

    def test_idle_timeout_secs(self):
        self._write({"idle_timeout_secs": 120})
        hd._load_config()
        self.assertEqual(hd.IDLE_TIMEOUT, 120)

    # ── Bounds clamping ───────────────────────────────────────────────────────

    def test_hint_interval_minimum_1(self):
        self._write({"hint_interval_secs": 0})
        hd._load_config()
        self.assertGreaterEqual(hd.HINT_INTERVAL, 1)

    def test_ai_throttle_minimum_1(self):
        self._write({"ai_throttle_secs": -5})
        hd._load_config()
        self.assertGreaterEqual(hd.AI_THROTTLE, 1)

    def test_advisor_throttle_minimum_1(self):
        self._write({"advisor_throttle_secs": 0})
        hd._load_config()
        self.assertGreaterEqual(hd.ADVISOR_THROTTLE, 1)

    def test_context_max_minimum_50(self):
        self._write({"context_max_entries": 10})
        hd._load_config()
        self.assertGreaterEqual(hd.CTX_MAX, 50)

    def test_context_inject_minimum_5(self):
        self._write({"context_inject_entries": 0})
        hd._load_config()
        self.assertGreaterEqual(hd.CTX_INJECT, 5)

    def test_idle_timeout_minimum_30(self):
        self._write({"idle_timeout_secs": 5})
        hd._load_config()
        self.assertGreaterEqual(hd.IDLE_TIMEOUT, 30)

    def test_advisor_window_minimum_10(self):
        self._write({"advisor_window": 1})
        hd._load_config()
        self.assertGreaterEqual(hd.ADVISOR_WINDOW, 10)

    # ── Filtering / feature flags ─────────────────────────────────────────────

    def test_severity_filter(self):
        self._write({"severity_filter": ["danger", "warn"]})
        hd._load_config()
        self.assertEqual(hd.SEVERITY_FILTER, ["danger", "warn"])

    def test_tag_filter(self):
        self._write({"tag_filter": ["git", "docker"]})
        hd._load_config()
        self.assertEqual(hd.TAG_FILTER, ["git", "docker"])

    def test_severity_filter_empty_list(self):
        self._write({"severity_filter": []})
        hd._load_config()
        self.assertEqual(hd.SEVERITY_FILTER, [])

    def test_enable_post_mortem_false(self):
        self._write({"enable_post_mortem": False})
        hd._load_config()
        self.assertFalse(hd.ENABLE_POST_MORTEM)

    def test_enable_post_mortem_true(self):
        self._write({"enable_post_mortem": True})
        hd._load_config()
        self.assertTrue(hd.ENABLE_POST_MORTEM)

    def test_enable_idle_tips_false(self):
        self._write({"enable_idle_tips": False})
        hd._load_config()
        self.assertFalse(hd.ENABLE_IDLE_TIPS)

    def test_enable_idle_tips_true(self):
        self._write({"enable_idle_tips": True})
        hd._load_config()
        self.assertTrue(hd.ENABLE_IDLE_TIPS)

    # ── Combined config ───────────────────────────────────────────────────────

    def test_combined_overrides(self):
        self._write({
            "hint_backend":       "ollama",
            "hint_model":         "qwen3:4b",
            "hint_interval_secs": 8,
            "rule_cooldown_secs": 90,
            "severity_filter":    ["danger"],
            "enable_post_mortem": False,
        })
        hd._load_config()
        self.assertEqual(hd.HINT_BACKEND,    "ollama")
        self.assertEqual(hd.HINT_MODEL,      "qwen3:4b")
        self.assertEqual(hd.HINT_INTERVAL,   8)
        self.assertEqual(hd.RULE_COOLDOWN,   90)
        self.assertEqual(hd.SEVERITY_FILTER, ["danger"])
        self.assertFalse(hd.ENABLE_POST_MORTEM)


if __name__ == "__main__":
    unittest.main()
