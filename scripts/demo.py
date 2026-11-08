#!/usr/bin/env python3
"""
scripts/demo.py — Interactive and benchmark demo for ShellBuddy.

Demonstrates the sub-millisecond regex dispatch engine without requiring
a full tmux or shell daemon installation. Zero external dependencies.
"""

from __future__ import annotations
import sys
import os
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from kb_engine import KBEngine, SEVERITY_PREFIX

# Terminal ANSI styling (graceful degradation)
USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

def c(text: str, code: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

SEV_COLORS = {
    "danger":  "1;31",  # Bold Red
    "warn":    "1;33",  # Bold Yellow
    "tip":     "1;36",  # Bold Cyan
    "upgrade": "1;32",  # Bold Green
}

SAMPLE_COMMANDS = [
    ("rm -rf /", "High-severity destructive command"),
    ("git push --force origin main", "Potentially destructive remote push"),
    ("git pull", "Sub-optimal default git workflow"),
    ("chmod 777 /var/www/html", "Excessively permissive permission risk"),
    ("curl -k https://internal.corp/data", "Insecure SSL verification bypass"),
    ("docker run --privileged ubuntu", "High-risk container privilege escalation"),
    ("ssh user@prod -o StrictHostKeyChecking=no", "Insecure host validation bypass"),
    ("git add .", "Bulk staging advice"),
]


def display_match(entry: dict, scan_us: float) -> None:
    sev = entry.get("severity", "tip")
    color_code = SEV_COLORS.get(sev, "0")
    prefix = SEVERITY_PREFIX.get(sev, "-> ")
    
    header = c(f"[{sev.upper()}] {prefix}{entry.get('hint')}", color_code)
    rule_id = c(f"({entry.get('id', 'rule')})", "2;37")
    latency = c(f"[{scan_us:.1f} µs]", "2;32")
    
    print(f"    {header} {rule_id} {latency}")
    detail = entry.get("detail", "")
    if detail:
        print(f"      {c(detail, '2;37')}")


def run_command_scan(engine: KBEngine, cmd: str) -> None:
    t0 = time.perf_counter()
    matches = engine.scan(cmd)
    elapsed_us = (time.perf_counter() - t0) * 1_000_000

    print(f"\n  {c('$', '1;32')} {c(cmd, '1;37')}")
    if not matches:
        print(f"    {c('✓ No warnings or upgrade suggestions found.', '2;37')} {c(f'[{elapsed_us:.1f} µs]', '2;32')}")
    else:
        for m in matches:
            display_match(m, elapsed_us)


def run_samples(engine: KBEngine) -> None:
    print(c("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "1;34"))
    print(c("  ShellBuddy Knowledge Base Engine — Live Demonstration", "1;37"))
    print(c(f"  Loaded {engine.count} rules across {len(engine._buckets)} token buckets in {engine.load_time:.1f}ms", "2;37"))
    print(c("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", "1;34"))

    for cmd, description in SAMPLE_COMMANDS:
        print(f"\n  {c('Scenario:', '1;33')} {description}")
        run_command_scan(engine, cmd)

    # Benchmark run
    print(c("\n─────────────────────────────────────────────────────────────", "2;37"))
    print(c("  Micro-Benchmark: 1,000 scans across representative commands...", "1;36"))
    t0 = time.perf_counter()
    iterations = 1000
    for _ in range(iterations):
        for cmd, _ in SAMPLE_COMMANDS:
            engine.scan(cmd)
    total_time = time.perf_counter() - t0
    scans_done = iterations * len(SAMPLE_COMMANDS)
    us_per_scan = (total_time / scans_done) * 1_000_000

    print(f"  {c('Scans Completed:', '1;37')} {scans_done:,}")
    print(f"  {c('Average Latency:', '1;32')} {us_per_scan:.2f} µs per command scan")
    print(f"  {c('Throughput:', '1;32')} {scans_done / total_time:,.0f} scans / second")
    print(c("─────────────────────────────────────────────────────────────\n", "2;37"))


def interactive_loop(engine: KBEngine) -> None:
    print(c("\n  ShellBuddy Interactive Demo Mode", "1;37"))
    print("  Type any shell command to test proactive feedback.")
    print("  Type 'sample' to run standard suite, 'benchmark' to measure speed, 'exit' to quit.\n")

    while True:
        try:
            prompt = c("shellbuddy> ", "1;34")
            line = input(prompt).strip()
            if not line:
                continue
            if line in ("exit", "quit", ":q"):
                print("Bye!")
                break
            if line == "sample":
                run_samples(engine)
                continue
            if line == "benchmark":
                run_samples(engine)
                continue
            run_command_scan(engine, line)
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break


def main():
    engine = KBEngine()
    if len(sys.argv) > 1 and sys.argv[1] in ("--sample", "-s", "--benchmark", "-b"):
        run_samples(engine)
    elif sys.stdin.isatty():
        run_samples(engine)
        try:
            interactive_loop(engine)
        except KeyboardInterrupt:
            pass
    else:
        run_samples(engine)


if __name__ == "__main__":
    main()
