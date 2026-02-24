#!/usr/bin/env python3
"""
shellbuddy — kb_engine.py
Dispatcher-based KB engine. Loads kb.json once, compiles all regexes,
routes each command to only its relevant rule bucket — sub-millisecond scan.

Drop-in replacement for the flat UPGRADE_RULES list in hint_daemon.py.
"""

import json
import re
import time
from pathlib import Path
from collections import defaultdict

KB_PATH     = Path(__file__).parent / "kb.json"
INSTALL_KB  = Path.home() / ".shellbuddy" / "kb.json"

# Severity → display prefix (no emoji, terminal-safe)
SEVERITY_PREFIX = {
    "danger":  "!! ",
    "warn":    "!  ",
    "tip":     "-> ",
    "upgrade": "=> ",
}


class KBEngine:
    """
    Dispatcher engine for the shellbuddy knowledge base.

    Architecture:
        self._buckets  : dict[str, list[(compiled_re, entry)]]
            keyed by primary command token (e.g. "git", "docker")
        self._generic  : list[(compiled_re, entry)]
            fallback for patterns that don't start with a clear token
            (pipes, compound commands, env var prefixes, etc.)

    scan(cmd) cost:
        O(B)  where B = rules in that command's bucket (avg ~40-80)
        instead of O(N) over all 10k rules.
    """

    def __init__(self, kb_path=None):
        self._buckets  = defaultdict(list)
        self._generic  = []
        self._count    = 0
        self._load_time = 0.0

        path = kb_path or (INSTALL_KB if INSTALL_KB.exists() else KB_PATH)
        if path and Path(path).exists():
            self.load(path)

    def load(self, path):
        t0 = time.perf_counter()
        try:
            data = json.loads(Path(path).read_text())
        except Exception as e:
            print(f"  kb_engine: failed to load {path}: {e}", flush=True)
            return

        bad = 0
        for entry in data:
            try:
                compiled = re.compile(entry["pattern"])
            except re.error:
                bad += 1
                continue

            cmd_token = entry.get("cmd", "").strip().lower()
            rule = (compiled, entry)

            if cmd_token and cmd_token.isalpha():
                self._buckets[cmd_token].append(rule)
            else:
                # Extract token from pattern itself as fallback
                m = re.match(r'^\^?\(?([a-zA-Z][a-zA-Z0-9_-]*)', entry["pattern"])
                if m:
                    self._buckets[m.group(1).lower()].append(rule)
                else:
                    self._generic.append(rule)

        self._count = sum(len(v) for v in self._buckets.values()) + len(self._generic)
        self._load_time = (time.perf_counter() - t0) * 1000
        print(
            f"  kb_engine: {self._count} rules loaded in {self._load_time:.1f}ms"
            f" ({len(self._buckets)} buckets, {len(self._generic)} generic)",
            flush=True
        )
        if bad:
            print(f"  kb_engine: {bad} invalid patterns skipped", flush=True)

    def scan(self, cmd: str) -> list[dict]:
        """
        Match cmd against relevant rules. Returns list of matched entries,
        ordered: bucket matches first, then generic.
        """
        cmd = cmd.strip()
        if not cmd:
            return []

        first_token = cmd.split()[0].lower()
        # Handle 'sudo git ...' → use second token
        if first_token == "sudo" and len(cmd.split()) > 1:
            first_token = cmd.split()[1].lower()
        # Handle env var prefix: 'CUDA_VISIBLE_DEVICES=0 python ...'
        if "=" in first_token:
            parts = cmd.split()
            for p in parts:
                if "=" not in p:
                    first_token = p.lower()
                    break

        candidates = self._buckets.get(first_token, []) + self._generic
        matches = []
        for compiled, entry in candidates:
            if compiled.search(cmd):
                matches.append(entry)
        return matches

    def get_hints(self, recent_cmds: list[dict], last_shown: dict,
                  cooldown: float = 120.0) -> list[tuple[str, str, dict]]:
        """
        Replaces get_rule_hints() from hint_daemon.py.
        Returns list of (rule_id, formatted_hint_str, entry) for the top 3 matches.
        Respects per-rule cooldown.
        """
        from collections import Counter
        now = time.time()

        freq    = Counter()
        matched = {}  # pattern → (entry, example_cmd)

        for item in recent_cmds:
            cmd = item.get("cmd", "")
            for entry in self.scan(cmd):
                rid = entry["id"]
                freq[rid] += 1
                matched[rid] = (entry, cmd)

        hints = []
        for rid, count in freq.most_common():
            if len(hints) >= 3:
                break
            if now - last_shown.get(rid, 0) < cooldown:
                # danger rules always show (cooldown=0)
                if matched[rid][0].get("severity") != "danger":
                    continue
            entry, example = matched[rid]
            arg = re.sub(r"^\S+\s*", "", example.strip())[:40]
            hint_text = entry["hint"].replace("{arg}", arg or "...")
            prefix = SEVERITY_PREFIX.get(entry["severity"], "   ")
            hints.append((rid, f"{prefix}[{count}x] {hint_text}", entry))

        return hints

    def get_detail_context(self, recent_cmds: list[dict], n: int = 3) -> str:
        """
        For /tip prompt injection: returns detail text of rules that matched
        recently, giving the LLM expert context without it having to infer.
        """
        seen = set()
        lines = []
        for item in recent_cmds[-15:]:
            cmd = item.get("cmd", "")
            for entry in self.scan(cmd):
                rid = entry["id"]
                if rid in seen:
                    continue
                seen.add(rid)
                lines.append(f"[{entry['severity'].upper()}] {entry['hint']}")
                lines.append(f"  {entry['detail']}")
                if len(seen) >= n:
                    break
            if len(seen) >= n:
                break
        return "\n".join(lines)

    @property
    def loaded(self) -> bool:
        return self._count > 0

    @property
    def stats(self) -> dict:
        return {
            "total":    self._count,
            "buckets":  len(self._buckets),
            "generic":  len(self._generic),
            "load_ms":  round(self._load_time, 1),
        }


# ── Singleton for import into hint_daemon ────────────────────────────────────
_engine: KBEngine | None = None

def get_engine(kb_path=None) -> KBEngine:
    global _engine
    if _engine is None:
        _engine = KBEngine(kb_path)
    return _engine


# ── CLI: benchmark / smoke test ───────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    kb = sys.argv[1] if len(sys.argv) > 1 else None
    engine = KBEngine(kb)

    if not engine.loaded:
        print("No kb.json found. Run: python3 kb_builder.py")
        sys.exit(1)

    print(f"\nStats: {engine.stats}\n")

    # Benchmark
    test_cmds = [
        "git commit -am 'wip'",
        "git push --force origin main",
        "python train.py --gpus 2",
        "rm -rf /tmp/test",
        "docker run -it ubuntu bash",
        "kubectl get pods -n production",
        "pip install torch",
        "nvidia-smi",
        "find . -name '*.py' -exec grep -l TODO {} \\;",
        "curl https://api.example.com | python3 -m json.tool",
        "chmod 777 /var/www/html",
        "sudo rm -rf /etc/nginx",
        "CUDA_VISIBLE_DEVICES=0 python3 train.py",
        "ssh -o StrictHostKeyChecking=no user@host",
        "tar xvf archive.tar.gz",
    ]

    print("Smoke test:")
    for cmd in test_cmds:
        matches = engine.scan(cmd)
        if matches:
            top = matches[0]
            pfx = SEVERITY_PREFIX.get(top["severity"], "   ")
            print(f"  {pfx}{cmd[:45]:<45} → {top['hint'][:50]}")
        else:
            print(f"       {cmd[:45]:<45} → (no match)")

    print("\nBenchmark (15 cmds × N runs):")
    for n in [100, 500, 1000]:
        t0 = time.perf_counter()
        for _ in range(n):
            for cmd in test_cmds:
                engine.scan(cmd)
        elapsed = (time.perf_counter() - t0) * 1000
        per_run = elapsed / n
        print(f"  {n:>5} runs: {elapsed:>7.1f}ms total  {per_run:>6.2f}ms/run")
