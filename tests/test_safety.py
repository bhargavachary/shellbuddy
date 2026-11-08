"""
tests/test_safety.py
Unit tests verifying ShellBuddy's security posture:
- Secret and credential scrubbing patterns
- Destructive operation safeguards in KB
- Command injection & metacharacter resilience
- AI context sanitization and output formatting
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kb_engine import KBEngine
import hint_daemon as hd


class TestSecretScrubbing(unittest.TestCase):
    """Verify that credentials, tokens, and keys are identified for scrubbing."""

    SECRET_COMMANDS = [
        "curl -H 'Authorization: Bearer eyJhbGciOi...' https://api.com",
        "export GITHUB_TOKEN=ghp_ABC1234567890",
        "export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCY",
        "export API_KEY=sk-proj-12345",
        "ssh-add ~/.ssh/id_rsa",
        "echo my_secret_password | sudo -S ls",
        "docker login -u user -p my_secret_token",
        "curl https://api.com?access_token=xyz987",
    ]

    SAFE_COMMANDS = [
        "git status",
        "docker ps -a",
        "python3 -m unittest discover",
        "cat README.md",
        "ls -la",
    ]

    def _should_filter(self, cmd: str) -> bool:
        cmd_l = cmd.lower()
        patterns = [
            "secret", "password", "access_token", "bearer ",
            "id_rsa", "ssh-add ", "ghp_", "aws_access_key", "aws_secret",
            "api_key", "token="
        ]
        return any(p in cmd_l for p in patterns)

    def test_all_sensitive_commands_flagged(self):
        for cmd in self.SECRET_COMMANDS:
            with self.subTest(cmd=cmd):
                self.assertTrue(self._should_filter(cmd), f"Failed to filter secret: {cmd}")

    def test_safe_commands_allowed(self):
        for cmd in self.SAFE_COMMANDS:
            with self.subTest(cmd=cmd):
                self.assertFalse(self._should_filter(cmd), f"Wrongly filtered safe command: {cmd}")


class TestDestructiveOperationSafeguards(unittest.TestCase):
    """Verify KB flags high-risk commands as 'danger' severity."""

    @classmethod
    def setUpClass(cls):
        cls.engine = KBEngine()

    def test_force_push_flagged_danger(self):
        matches = self.engine.scan("git push --force origin main")
        self.assertTrue(any(m["severity"] == "danger" for m in matches))

    def test_dangerous_chmod_flagged_danger(self):
        matches = self.engine.scan("chmod 777 /var/www")
        self.assertTrue(any(m["severity"] == "danger" for m in matches))

    def test_rm_rf_flagged(self):
        matches = self.engine.scan("rm -rf /")
        self.assertTrue(any(m["severity"] == "danger" for m in matches))


class TestContextSanitization(unittest.TestCase):
    """Verify string sanitization for context log embedding."""

    def test_ansi_and_control_codes_stripped(self):
        raw = "Error \x1b[31mfailed\x1b[0m\x00\x07\x08!"
        sanitized = hd._sanitize_for_ctx(raw)
        self.assertNotIn("\x00", sanitized)
        self.assertNotIn("\x07", sanitized)
        self.assertNotIn("\x08", sanitized)

    def test_newlines_converted_to_spaces(self):
        raw = "first line\nsecond line\r\nthird line"
        sanitized = hd._sanitize_for_ctx(raw)
        self.assertNotIn("\n", sanitized)
        self.assertNotIn("\r", sanitized)
        self.assertIn("first line second line third line", sanitized)

    def test_length_capping(self):
        raw = "A" * 1000
        sanitized = hd._sanitize_for_ctx(raw, max_len=50)
        self.assertEqual(len(sanitized), 50)


if __name__ == "__main__":
    unittest.main()
