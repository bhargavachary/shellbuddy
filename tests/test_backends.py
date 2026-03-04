"""
tests/test_backends.py
Backend routing tests using mocks — no actual AI calls made.
Tests: call_ai_hint, call_ai_tip, _call_copilot_chain fallback,
       _call_backend routing, ctx_append feedback logging.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hint_daemon as hd


# ── call_ai_hint: backend availability gate ───────────────────────────────────

class TestCallAiHint(unittest.TestCase):

    def setUp(self):
        self._orig_available = set(hd._AVAILABLE_BACKENDS)
        self._orig_backend   = hd.HINT_BACKEND

    def tearDown(self):
        hd._AVAILABLE_BACKENDS.clear()
        hd._AVAILABLE_BACKENDS.update(self._orig_available)
        hd.HINT_BACKEND = self._orig_backend

    def test_returns_empty_when_no_backends_available(self):
        hd._AVAILABLE_BACKENDS.clear()
        self.assertEqual(hd.call_ai_hint("some prompt"), "")

    def test_returns_empty_when_hint_backend_not_in_available(self):
        hd.HINT_BACKEND = "ollama"
        hd._AVAILABLE_BACKENDS = {"copilot"}  # ollama not available
        self.assertEqual(hd.call_ai_hint("some prompt"), "")

    def test_calls_copilot_chain_when_copilot_available(self):
        hd.HINT_BACKEND = "copilot"
        hd._AVAILABLE_BACKENDS = {"copilot"}
        with patch.object(hd, "_call_copilot_chain", return_value="hint text") as mock:
            result = hd.call_ai_hint("prompt")
        mock.assert_called_once()
        self.assertEqual(result, "hint text")

    def test_returns_empty_string_on_none_result(self):
        hd.HINT_BACKEND = "copilot"
        hd._AVAILABLE_BACKENDS = {"copilot"}
        with patch.object(hd, "_call_copilot_chain", return_value=None):
            result = hd.call_ai_hint("prompt")
        self.assertEqual(result, "")


# ── call_ai_tip: backend availability gate ────────────────────────────────────

class TestCallAiTip(unittest.TestCase):

    def setUp(self):
        self._orig_available = set(hd._AVAILABLE_BACKENDS)
        self._orig_backend   = hd.TIP_BACKEND

    def tearDown(self):
        hd._AVAILABLE_BACKENDS.clear()
        hd._AVAILABLE_BACKENDS.update(self._orig_available)
        hd.TIP_BACKEND = self._orig_backend

    def test_returns_empty_when_tip_backend_unavailable(self):
        hd.TIP_BACKEND = "claude"
        hd._AVAILABLE_BACKENDS = set()
        self.assertEqual(hd.call_ai_tip("question"), "")

    def test_delegates_to_call_backend(self):
        hd.TIP_BACKEND = "ollama"
        hd._AVAILABLE_BACKENDS = {"ollama"}
        with patch.object(hd, "_call_backend", return_value="answer") as mock:
            result = hd.call_ai_tip("question")
        mock.assert_called_once()
        self.assertEqual(result, "answer")

    def test_empty_result_from_backend_returns_empty_string(self):
        hd.TIP_BACKEND = "ollama"
        hd._AVAILABLE_BACKENDS = {"ollama"}
        with patch.object(hd, "_call_backend", return_value=None):
            result = hd.call_ai_tip("question")
        self.assertEqual(result, "")


# ── _call_copilot_chain: fallback logic ───────────────────────────────────────

class TestCopilotChainFallback(unittest.TestCase):

    def test_first_model_success_stops_chain(self):
        with patch.object(hd, "_call_copilot", side_effect=["result", "second"]) as mock:
            result = hd._call_copilot_chain("prompt", models=["m1", "m2"])
        self.assertEqual(result, "result")
        self.assertEqual(mock.call_count, 1)

    def test_first_fail_tries_second(self):
        with patch.object(hd, "_call_copilot", side_effect=[None, "fallback"]) as mock:
            result = hd._call_copilot_chain("prompt", models=["m1", "m2"])
        self.assertEqual(result, "fallback")
        self.assertEqual(mock.call_count, 2)

    def test_all_fail_returns_none(self):
        with patch.object(hd, "_call_copilot", return_value=None):
            result = hd._call_copilot_chain("prompt", models=["m1", "m2", "m3"])
        self.assertIsNone(result)

    def test_single_model_chain(self):
        with patch.object(hd, "_call_copilot", return_value="got it"):
            result = hd._call_copilot_chain("prompt", models=["only"])
        self.assertEqual(result, "got it")

    def test_empty_chain_returns_none(self):
        # models=[] is falsy so the function falls back to HINT_MODEL_CHAIN;
        # patch both to empty so the loop never runs.
        with patch.object(hd, "HINT_MODEL_CHAIN", []):
            with patch.object(hd, "_call_copilot", return_value=None):
                result = hd._call_copilot_chain("prompt", models=[])
        self.assertIsNone(result)

    def test_uses_hint_model_chain_when_no_models_arg(self):
        orig_chain = hd.HINT_MODEL_CHAIN
        hd.HINT_MODEL_CHAIN = ["test_model"]
        with patch.object(hd, "_call_copilot", return_value="ok") as mock:
            hd._call_copilot_chain("prompt")
        # model is passed as a keyword arg to _call_copilot
        called_model = mock.call_args.kwargs.get("model") or mock.call_args[1].get("model")
        self.assertEqual(called_model, "test_model")
        hd.HINT_MODEL_CHAIN = orig_chain


# ── _call_backend: routing ────────────────────────────────────────────────────

class TestCallBackendRouting(unittest.TestCase):

    def test_routes_copilot(self):
        with patch.object(hd, "_call_copilot", return_value="cp") as mock:
            result = hd._call_backend("copilot", "prompt", model="m1")
        mock.assert_called_once_with("prompt", model="m1")
        self.assertEqual(result, "cp")

    def test_routes_claude(self):
        with patch.object(hd, "_call_claude", return_value="cl") as mock:
            result = hd._call_backend("claude", "prompt", model="m2")
        mock.assert_called_once_with("prompt", model="m2")
        self.assertEqual(result, "cl")

    def test_routes_ollama(self):
        with patch.object(hd, "_call_ollama", return_value="ol") as mock:
            result = hd._call_backend("ollama", "prompt", model="m3")
        mock.assert_called_once_with("prompt", model="m3")
        self.assertEqual(result, "ol")

    def test_routes_openai(self):
        with patch.object(hd, "_call_openai", return_value="oa") as mock:
            result = hd._call_backend("openai", "prompt", model="m4")
        mock.assert_called_once_with("prompt", model="m4")
        self.assertEqual(result, "oa")

    def test_unknown_backend_returns_none(self):
        result = hd._call_backend("nonexistent_backend", "prompt")
        self.assertIsNone(result)


# ── Feedback logging via /tip helpful ─────────────────────────────────────────

class TestTipFeedbackLogging(unittest.TestCase):
    """Verify that /tip helpful and /tip not-helpful log entries to unified context."""

    def setUp(self):
        self.tmpdir        = tempfile.mkdtemp()
        self._orig_ctx     = hd.UNIFIED_CTX
        self._orig_result  = hd.TIP_RESULT
        self._orig_query   = hd.TIP_QUERY
        self._orig_lq      = hd._last_tip_query
        self._orig_la      = hd._last_tip_answer
        hd.UNIFIED_CTX     = Path(self.tmpdir) / "ctx.jsonl"
        hd.TIP_RESULT      = Path(self.tmpdir) / "tip_result.txt"
        hd.TIP_QUERY       = Path(self.tmpdir) / "tip_query.txt"
        hd._last_tip_query  = "how to rebase"
        hd._last_tip_answer = "Use git rebase -i HEAD~3"

    def tearDown(self):
        hd.UNIFIED_CTX         = self._orig_ctx
        hd.TIP_RESULT          = self._orig_result
        hd.TIP_QUERY           = self._orig_query
        hd._last_tip_query      = self._orig_lq
        hd._last_tip_answer     = self._orig_la

    def _run_tip(self, query_text):
        hd.TIP_QUERY.write_text(query_text)
        hd.handle_tip_query()

    def _ctx_entries(self):
        if not hd.UNIFIED_CTX.exists():
            return []
        lines = hd.UNIFIED_CTX.read_text().strip().splitlines()
        return [json.loads(l) for l in lines if l.strip()]

    def test_helpful_logs_feedback_entry(self):
        self._run_tip("helpful")
        entries = self._ctx_entries()
        feedback = [e for e in entries if e.get("type") == "feedback"]
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0]["rating"], "helpful")
        self.assertEqual(feedback[0]["query"],  "how to rebase")

    def test_not_helpful_logs_feedback_entry(self):
        self._run_tip("not-helpful")
        entries = self._ctx_entries()
        feedback = [e for e in entries if e.get("type") == "feedback"]
        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0]["rating"], "not-helpful")

    def test_helpful_result_file_written(self):
        self._run_tip("helpful")
        self.assertTrue(hd.TIP_RESULT.exists())
        content = hd.TIP_RESULT.read_text()
        self.assertIn("helpful", content)

    def test_helpful_with_no_prior_query(self):
        hd._last_tip_query = ""
        self._run_tip("helpful")
        entries = self._ctx_entries()
        feedback = [e for e in entries if e.get("type") == "feedback"]
        self.assertEqual(len(feedback), 1)
        # Should still log, just without a meaningful query
        self.assertEqual(feedback[0]["rating"], "helpful")


# ── build_tip_prompt: context injection ───────────────────────────────────────

class TestBuildTipPrompt(unittest.TestCase):

    def setUp(self):
        self.tmpdir       = tempfile.mkdtemp()
        self._orig_ctx    = hd.UNIFIED_CTX
        self._orig_cmdlog = hd.CMD_LOG
        hd.UNIFIED_CTX    = Path(self.tmpdir) / "ctx.jsonl"
        hd.CMD_LOG        = Path(self.tmpdir) / "cmd_log.jsonl"

    def tearDown(self):
        hd.UNIFIED_CTX = self._orig_ctx
        hd.CMD_LOG     = self._orig_cmdlog

    def test_prompt_contains_question(self):
        prompt = hd.build_tip_prompt("how to rebase interactively")
        self.assertIn("how to rebase interactively", prompt)

    def test_prompt_contains_environment_header(self):
        prompt = hd.build_tip_prompt("test question")
        self.assertIn("zsh", prompt)

    def test_prompt_includes_recent_cmds(self):
        ts = "2026-03-04T10:00:00Z"
        hd.CMD_LOG.write_text(
            json.dumps({"ts": ts, "cmd": "git status", "cwd": "/tmp"}) + "\n"
        )
        prompt = hd.build_tip_prompt("test")
        self.assertIn("git status", prompt)

    def test_prompt_includes_session_context(self):
        hd.ctx_append({"type": "tip_q", "query": "prior question"})
        prompt = hd.build_tip_prompt("new question")
        self.assertIn("prior question", prompt)

    def test_prompt_has_max_line_limit(self):
        prompt = hd.build_tip_prompt("test")
        self.assertIn("Max 15 lines", prompt)


if __name__ == "__main__":
    unittest.main()
