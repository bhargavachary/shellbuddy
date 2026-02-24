#!/usr/bin/env python3
"""
shellbuddy — show_stats.sh (actually a Python script, called from zsh)
Live system stats strip: CPU · RAM · GPU  at ~1Hz with animated sparklines.

Run inside a tmux pane (2 lines tall).
Reads CPU/RAM from `top -l 2`, GPU from ioreg IOAccelerator.
No external dependencies — pure stdlib.
"""

import subprocess, re, sys, time, os, signal, threading
from datetime import datetime

# ── ANSI ─────────────────────────────────────────────────────────────────────
R      = '\033[0m'
BOLD   = '\033[1m'
DIM    = '\033[2m'
CYAN   = '\033[1;36m'
CYAN_D = '\033[2;36m'
GREEN  = '\033[32m'
YELLOW = '\033[33m'
RED    = '\033[31m'
WHITE  = '\033[37m'
MAG    = '\033[35m'
MAG_B  = '\033[1;35m'
HIDE_C = '\033[?25l'   # hide cursor
SHOW_C = '\033[?25h'   # show cursor
CLR_L  = '\033[2K\r'   # clear line

# ── Helpers ───────────────────────────────────────────────────────────────────

def bar(pct: float, width: int = 8) -> str:
    """Filled block bar. pct 0-100."""
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * width)
    return '█' * filled + '░' * (width - filled)

def color(pct: float) -> str:
    if pct < 50: return GREEN
    if pct < 80: return YELLOW
    return RED

def _stat_block(label: str, pct: float, value_str: str) -> str:
    c = color(pct)
    return f"{DIM}┤{R}{BOLD}{WHITE} {label} {R}{c}{bar(pct)}{R} {c}{value_str}{R}"

# ── RAM total (static, read once) ─────────────────────────────────────────────

def _ram_total_gb() -> float:
    try:
        import subprocess as sp
        r = sp.run(['sysctl', '-n', 'hw.memsize'], capture_output=True, text=True, timeout=2)
        return int(r.stdout.strip()) / (1024**3)
    except Exception:
        return 0.0

RAM_TOTAL = _ram_total_gb()

# ── CPU + RAM via top ─────────────────────────────────────────────────────────

def _read_cpu_ram():
    """Returns (cpu_pct, ram_used_gb). Blocks ~0.5s (two top samples)."""
    try:
        r = subprocess.run(
            ['top', '-l', '2', '-n', '0', '-s', '0'],
            capture_output=True, text=True, timeout=5
        )
        cpu_pct = 0.0
        ram_used = 0.0
        # Use the LAST occurrence of each line (second sample = accurate)
        for line in r.stdout.splitlines():
            if 'CPU usage' in line:
                m = re.search(r'(\d+\.\d+)%\s+user,\s+(\d+\.\d+)%\s+sys', line)
                if m:
                    cpu_pct = float(m.group(1)) + float(m.group(2))
            elif 'PhysMem' in line:
                m = re.search(r'(\d+(?:\.\d+)?)(G|M)\s+used', line)
                if m:
                    v, unit = float(m.group(1)), m.group(2)
                    ram_used = v if unit == 'G' else v / 1024
        return cpu_pct, ram_used
    except Exception:
        return 0.0, 0.0

# ── GPU via ioreg ─────────────────────────────────────────────────────────────

def _read_gpu():
    """Returns gpu_pct (Device Utilization %). Fast, no sudo needed."""
    try:
        r = subprocess.run(
            ['ioreg', '-r', '-d', '2', '-w', '0', '-c', 'IOAccelerator'],
            capture_output=True, text=True, timeout=2
        )
        for line in r.stdout.splitlines():
            if 'PerformanceStatistics' in line:
                m = re.search(r'"Device Utilization %"=(\d+)', line)
                if m:
                    return float(m.group(1))
        return 0.0
    except Exception:
        return 0.0

# ── Animated sparkline history ─────────────────────────────────────────────────

SPARK_CHARS = '▁▂▃▄▅▆▇█'

class _History:
    def __init__(self, size=20):
        self._buf = [0.0] * size
        self._size = size
    def push(self, v):
        self._buf = self._buf[1:] + [v]
    def spark(self, width=20) -> str:
        buf = self._buf[-width:]
        out = []
        for v in buf:
            if v <= 0.0:
                out.append('░')
            else:
                idx = max(0, min(round(v / 100 * (len(SPARK_CHARS) - 1)), len(SPARK_CHARS) - 1))
                out.append(SPARK_CHARS[idx])
        return ''.join(out)

_cpu_hist = _History()
_ram_hist = _History()
_gpu_hist = _History()

# ── Shared state (updated by background sampler) ───────────────────────────────

_state = {
    'cpu': 0.0, 'ram': 0.0, 'gpu': 0.0,
    'ready': False,
}
_state_lock = threading.Lock()


def _sampler_loop():
    """Background thread: sample CPU/RAM (slow) and GPU (fast) in parallel."""
    def _sample_gpu():
        gpu = _read_gpu()
        with _state_lock:
            _state['gpu'] = gpu
            _gpu_hist.push(gpu)

    while True:
        t_start = time.monotonic()

        # GPU is fast — kick off in its own thread each cycle
        gpu_t = threading.Thread(target=_sample_gpu, daemon=True)
        gpu_t.start()

        # CPU+RAM block ~0.5s
        cpu, ram = _read_cpu_ram()
        with _state_lock:
            _state['cpu'] = cpu
            _state['ram'] = ram
            _state['ready'] = True
            _cpu_hist.push(cpu)
            _ram_hist.push(ram / RAM_TOTAL * 100 if RAM_TOTAL else 0)

        gpu_t.join(timeout=1.0)

        elapsed = time.monotonic() - t_start
        sleep_t = max(0.1, 1.0 - elapsed)
        time.sleep(sleep_t)


# ── Render ─────────────────────────────────────────────────────────────────────

try:
    COLS = os.get_terminal_size().columns
except OSError:
    COLS = int(os.environ.get('COLUMNS', 80))

def _render():
    with _state_lock:
        cpu  = _state['cpu']
        ram  = _state['ram']
        gpu  = _state['gpu']
        cpu_sp = _cpu_hist.spark(16)
        ram_sp = _ram_hist.spark(16)
        gpu_sp = _gpu_hist.spark(16)

    ts = datetime.now().strftime('%H:%M:%S')
    ram_pct = ram / RAM_TOTAL * 100 if RAM_TOTAL else 0

    # Line 1 — branding + timestamp
    line1 = (
        f"  {MAG_B}◆ shellbuddy{R}  "
        f"{CYAN_D}{ts}{R}  "
        f"{DIM}live system stats{R}"
    )

    # Line 2 — stats bars
    cpu_block = _stat_block('CPU', cpu,  f'{cpu:4.1f}%')
    ram_block = _stat_block('RAM', ram_pct, f'{ram:.1f}/{RAM_TOTAL:.0f}G')
    gpu_block = _stat_block('GPU', gpu,  f'{gpu:4.1f}%')

    # Sparkline history (dim, trailing the bars)
    spark_section = (
        f"  {DIM}cpu{R} {color(cpu)}{cpu_sp}{R}"
        f"  {DIM}ram{R} {color(ram_pct)}{ram_sp}{R}"
        f"  {DIM}gpu{R} {color(gpu)}{gpu_sp}{R}"
    )

    line2 = f"  {cpu_block}  {ram_block}  {gpu_block}  {DIM}┤{R}{spark_section}"

    return line1, line2


def _move_to_line(n):
    """Move cursor to line n (1-based) within this pane."""
    sys.stdout.write(f'\033[{n};1H')


def _cleanup():
    sys.stdout.write(SHOW_C)
    sys.stdout.write('\033[2J\033[H')
    sys.stdout.flush()


def main():
    def _sigterm(*_):
        _cleanup()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGHUP, _sigterm)

    # Start background sampler
    t = threading.Thread(target=_sampler_loop, daemon=True)
    t.start()

    # Hide cursor, clear screen
    sys.stdout.write(HIDE_C)
    sys.stdout.write('\033[2J')
    sys.stdout.flush()

    try:
        while True:
            line1, line2 = _render()

            # Redraw in-place (no scroll, no flicker)
            sys.stdout.write('\033[H')              # cursor home
            sys.stdout.write(CLR_L + line1 + '\n')
            sys.stdout.write(CLR_L + line2 + '\n')
            sys.stdout.flush()

            time.sleep(0.1)

    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()


if __name__ == '__main__':
    main()
