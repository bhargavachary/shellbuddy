#!/usr/bin/env python3
"""
shellbuddy — show_stats.sh  (Python, launched by toggle_hints_pane.sh)
5-line stats panel:  title bar | metric grid | braille history row
"""

import subprocess, re, sys, time, os, signal, threading
from datetime import datetime

# ── ANSI ──────────────────────────────────────────────────────────────────────
R      = '\033[0m'
BOLD   = '\033[1m'
DIM    = '\033[2m'
CYAN   = '\033[1;36m'
CYAN_D = '\033[2;36m'
GREY   = '\033[38;5;240m'   # light grey for grid lines
GREEN  = '\033[32m'
YELLOW = '\033[33m'
RED    = '\033[31m'
WHITE  = '\033[37m'
MAG_B  = '\033[1;35m'
HIDE_C = '\033[?25l'
SHOW_C = '\033[?25h'

PANE_ROWS = 5   # total lines this pane is sized to

# ── Color by percentage ───────────────────────────────────────────────────────
def pcolor(pct: float) -> str:
    if pct < 50: return GREEN
    if pct < 80: return YELLOW
    return RED

# ── Sub-character smooth bar (only ASCII + block elements, all width-1) ───────
_BAR_FILL = ['·', '▏', '▎', '▍', '▌', '▋', '▊', '▉', '█']

def bar(pct: float, width: int = 10) -> str:
    pct = max(0.0, min(100.0, pct))
    eighths = round(pct / 100 * width * 8)
    full    = eighths // 8
    frac    = eighths  % 8
    empty   = width - full - (1 if frac else 0)
    return '█' * full + (_BAR_FILL[frac] if frac else '') + '·' * empty

# ── Braille waveform ──────────────────────────────────────────────────────────
# Dots: left col bottom→top = 0x01,0x02,0x04,0x08  right col = 0x10,0x20,0x40,0x80
_LC = [0x01, 0x02, 0x04, 0x08]
_RC = [0x10, 0x20, 0x40, 0x80]

def _fill_bits(pct: float, col: list) -> int:
    levels = max(0, min(4, round(pct / 100 * 4)))
    return sum(col[3 - i] for i in range(levels))

def braille_chart(history: list, width: int = 20) -> str:
    n = width * 2
    s = [0.0] * (n - min(n, len(history))) + history[-n:]
    return ''.join(chr(0x2800 | _fill_bits(s[i], _LC) | _fill_bits(s[i+1], _RC))
                   for i in range(0, n, 2))

# ── RAM total ─────────────────────────────────────────────────────────────────
def _ram_total_gb() -> float:
    try:
        r = subprocess.run(['sysctl', '-n', 'hw.memsize'],
                           capture_output=True, text=True, timeout=2)
        return int(r.stdout.strip()) / 1024**3
    except Exception:
        return 0.0

RAM_TOTAL = _ram_total_gb()

# ── Samplers ──────────────────────────────────────────────────────────────────
def _read_cpu_ram():
    try:
        r = subprocess.run(['top', '-l', '2', '-n', '0', '-s', '0'],
                           capture_output=True, text=True, timeout=5)
        cpu = ram = swap_used = swap_total = 0.0
        for line in r.stdout.splitlines():
            if 'CPU usage' in line:
                m = re.search(r'(\d+\.\d+)%\s+user,\s+(\d+\.\d+)%\s+sys', line)
                if m: cpu = float(m.group(1)) + float(m.group(2))
            elif 'PhysMem' in line:
                m = re.search(r'(\d+(?:\.\d+)?)(G|M)\s+used', line)
                if m:
                    v, u = float(m.group(1)), m.group(2)
                    ram = v if u == 'G' else v / 1024
        rs = subprocess.run(['sysctl', '-n', 'vm.swapusage'],
                            capture_output=True, text=True, timeout=2)
        mu = re.search(r'used\s*=\s*([\d.]+)M', rs.stdout)
        mt = re.search(r'total\s*=\s*([\d.]+)M', rs.stdout)
        if mu: swap_used  = float(mu.group(1)) / 1024
        if mt: swap_total = float(mt.group(1)) / 1024
        return cpu, ram, swap_used, swap_total
    except Exception:
        return 0.0, 0.0, 0.0, 0.0

def _read_gpu() -> float:
    try:
        r = subprocess.run(['ioreg', '-r', '-d', '2', '-w', '0', '-c', 'IOAccelerator'],
                           capture_output=True, text=True, timeout=2)
        for line in r.stdout.splitlines():
            if 'PerformanceStatistics' in line:
                m = re.search(r'"Device Utilization %"=(\d+)', line)
                if m: return float(m.group(1))
        return 0.0
    except Exception:
        return 0.0

# ── Shell context (cwd, conda env, python version) ───────────────────────────
_ctx_cache = dict(py_ver='', py_ts=0.0)
_ctx_lock  = threading.Lock()

def _short_path(path: str, levels: int = 5) -> str:
    """~/a/b/.../d/e  — keep first (home-relative) + last (levels-1) components."""
    home = os.path.expanduser('~')
    if path.startswith(home):
        path = '~' + path[len(home):]
    parts = path.split('/')
    if len(parts) <= levels:
        return '/'.join(parts)
    return parts[0] + '/.../' + '/'.join(parts[-(levels - 1):])

def _get_py_version() -> str:
    """Cached python3 --version, refreshed every 30s."""
    now = time.monotonic()
    with _ctx_lock:
        if now - _ctx_cache['py_ts'] < 30 and _ctx_cache['py_ver']:
            return _ctx_cache['py_ver']
    try:
        r = subprocess.run(['python3', '--version'], capture_output=True, text=True, timeout=2)
        ver = r.stdout.strip() or r.stderr.strip()   # Python 3.x.y
        ver = ver.replace('Python ', '')
    except Exception:
        ver = ''
    with _ctx_lock:
        _ctx_cache['py_ver'] = ver
        _ctx_cache['py_ts']  = now
    return ver

def _tmux_main_pane_path() -> str:
    """Get the current path of the bottom (main) tmux pane."""
    try:
        r = subprocess.run(
            ['tmux', 'display-message', '-t', '{bottom}', '-p', '#{pane_current_path}'],
            capture_output=True, text=True, timeout=1
        )
        p = r.stdout.strip()
        return p if p else os.getcwd()
    except Exception:
        return os.getcwd()

def _shell_context() -> str:
    """Returns formatted context string for title bar."""
    cwd  = _short_path(_tmux_main_pane_path())
    env  = os.environ.get('CONDA_DEFAULT_ENV', '') or os.environ.get('VIRTUAL_ENV', '')
    if env:
        env = os.path.basename(env)
    py   = _get_py_version()
    sep  = f'  {GREY}|{R}  '
    parts = [f'{DIM}{cwd}{R}']
    if py:
        parts.append(f'{DIM}python {R}{CYAN_D}{py}{R}')
    if env:
        parts.append(f'{DIM}env: {R}{CYAN_D}{env}{R}')
    return sep.join(parts)


def _read_pressure() -> int:
    try:
        r = subprocess.run(['sysctl', '-n', 'kern.memorystatus_level'],
                           capture_output=True, text=True, timeout=2)
        return int(r.stdout.strip())
    except Exception:
        return 100

# ── History buffers ───────────────────────────────────────────────────────────
class _Hist:
    def __init__(self, n=80): self._b = [0.0] * n
    def push(self, v):        self._b = self._b[1:] + [v]
    def data(self):           return list(self._b)

_cpu_h = _Hist(); _gpu_h = _Hist(); _ram_h = _Hist(); _swp_h = _Hist()

# ── Shared state ──────────────────────────────────────────────────────────────
_st   = dict(cpu=0.0, ram=0.0, gpu=0.0, swap_used=0.0, swap_total=0.0, pressure=100)
_lock = threading.Lock()

def _sampler():
    def _fast():
        gpu = _read_gpu(); p = _read_pressure()
        with _lock:
            _st['gpu'] = gpu; _st['pressure'] = p
            _gpu_h.push(gpu)
    while True:
        t0 = time.monotonic()
        ft = threading.Thread(target=_fast, daemon=True); ft.start()
        cpu, ram, su, st2 = _read_cpu_ram()
        with _lock:
            _st.update(cpu=cpu, ram=ram, swap_used=su, swap_total=st2)
            _cpu_h.push(cpu)
            _ram_h.push(ram / RAM_TOTAL * 100 if RAM_TOTAL else 0)
            _swp_h.push(su / st2 * 100 if st2 else 0)
        ft.join(timeout=1.0)
        time.sleep(max(0.1, 1.0 - (time.monotonic() - t0)))

# ── Render ────────────────────────────────────────────────────────────────────
def _cols() -> int:
    try:    return os.get_terminal_size().columns
    except: return int(os.environ.get('COLUMNS', 120))

def _render(cols: int):
    with _lock:
        cpu = _st['cpu']; ram = _st['ram']; gpu = _st['gpu']
        su  = _st['swap_used']; st2 = _st['swap_total']
        pres = _st['pressure']
        cd = _cpu_h.data(); gd = _gpu_h.data()
        rd = _ram_h.data(); sd = _swp_h.data()

    ram_pct  = ram / RAM_TOTAL * 100 if RAM_TOTAL else 0
    swp_pct  = su / st2 * 100 if st2 else 0

    # ── Line 1: title bar ─────────────────────────────────────────────────────
    title_inner = ' ShellBuddy '
    brand   = f'{CYAN_D}==={R}{MAG_B}{title_inner}{R}{CYAN_D}==={R}'
    brand_v = 3 + len(title_inner) + 3   # 18 visible chars
    ctx     = _shell_context()
    ctx_v   = len(re.sub(r'\033\[[0-9;]*m', '', ctx))
    # Total available for dashes: cols minus margins(2) minus spacers(6) minus brand minus ctx
    total_dash = max(2, cols - 2 - brand_v - ctx_v - 6)
    # Split dashes: half left of brand, remainder right of brand (before ctx)
    dash_l  = total_dash // 2
    dash_r  = total_dash - dash_l
    dl      = f'{GREY}' + '-' * dash_l + f'{R}'
    dr      = f'{GREY}' + '-' * dash_r + f'{R}'
    line1   = f'  {dl} {brand} {dr}  {ctx}'

    # ── Grid geometry ─────────────────────────────────────────────────────────
    # Total line width = 2 (margin) + 1 (|) + N*(cell_w+1) = 3 + N*(cell_w+1)
    # So cell_w = (cols - 3) // N - 1  (the -1 accounts for each inter-cell |)
    N       = 5
    cell_w  = max(12, (cols - 3) // N - 1)
    labels  = ['  CPU', '  GPU', '  RAM', '  SWAP', '  MEM']
    gsep    = f'{GREY}|{R}'

    def pad_cell(s, w):
        vis = len(re.sub(r'\033\[[0-9;]*m', '', s))
        return s + ' ' * max(0, w - vis)

    # ── Line 2: column headers ────────────────────────────────────────────────
    row2_parts = [f'{GREY}{lbl:<{cell_w}}{R}' for lbl in labels]
    line2 = f'  {gsep}' + gsep.join(row2_parts) + gsep

    # ── Line 3: metric values + bars ─────────────────────────────────────────
    bar_w  = max(6, cell_w - 9)   # reserve ~9 chars for value text

    cc = pcolor(cpu);  gc = pcolor(gpu)
    rc = pcolor(ram_pct); sc = pcolor(swp_pct)

    if pres >= 80:   pc_str = f'{GREEN}ok {R}'
    elif pres >= 50: pc_str = f'{YELLOW}med{R}'
    else:            pc_str = f'{RED}hi {R}'

    def cell_bar(c, pct, val_str):
        b = bar(pct, bar_w)
        return f'  {c}{b}{R} {c}{val_str}{R}'

    swap_str = f'{su:.1f}G' if su >= 0.05 else '  -  '
    cells3 = [
        cell_bar(cc, cpu,     f'{cpu:4.1f}%'),
        cell_bar(gc, gpu,     f'{gpu:4.1f}%'),
        cell_bar(rc, ram_pct, f'{ram_pct:4.1f}%'),
        cell_bar(sc, swp_pct, f'{swap_str:<5}'),
        f'  {pc_str}  {DIM}{pres}%{R}      ',
    ]
    line3 = f'  {gsep}' + gsep.join(pad_cell(c, cell_w) for c in cells3) + gsep

    # ── Line 4: divider ───────────────────────────────────────────────────────
    line4 = f'  {GREY}+' + ('+'.join('-' * cell_w for _ in labels)) + f'+{R}'

    # ── Line 5: braille history charts ───────────────────────────────────────
    cw = max(6, cell_w // 2 - 1)   # braille chars per metric
    cpu_ch = braille_chart(cd, cw); gpu_ch = braille_chart(gd, cw)
    ram_ch = braille_chart(rd, cw); swp_ch = braille_chart(sd, cw)

    def hist_cell(label, c, chart):
        inner = f'  {DIM}{label}{R} {c}{chart}{R}'
        return pad_cell(inner, cell_w)

    hist_cells = [
        hist_cell('CPU', cc, cpu_ch),
        hist_cell('GPU', gc, gpu_ch),
        hist_cell('RAM', rc, ram_ch),
        hist_cell('SWP', sc, swp_ch),
        pad_cell(f'  {DIM}PRESSURE{R}', cell_w),
    ]
    line5 = f'  {gsep}' + gsep.join(hist_cells) + gsep

    return [line1, line2, line3, line4, line5]


# ── Main ──────────────────────────────────────────────────────────────────────
def _clear_pane():
    out = ''
    for row in range(1, PANE_ROWS + 1):
        out += f'\033[{row};1H\033[2K'
    sys.stdout.write(out)
    sys.stdout.flush()

def _cleanup():
    _clear_pane()
    sys.stdout.write(SHOW_C)
    sys.stdout.flush()

def main():
    def _sig(*_): _cleanup(); sys.exit(0)
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGHUP,  _sig)

    threading.Thread(target=_sampler, daemon=True).start()

    sys.stdout.write(HIDE_C)
    _clear_pane()

    try:
        while True:
            cols  = _cols()
            lines = _render(cols)
            out   = ''
            for i, line in enumerate(lines[:PANE_ROWS], start=1):
                out += f'\033[{i};1H\033[2K{line}'
            sys.stdout.write(out)
            sys.stdout.flush()
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()

if __name__ == '__main__':
    main()
