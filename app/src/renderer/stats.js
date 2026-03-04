/**
 * ShellBuddy — stats.js
 *
 * System stats bar rendered natively via Node.js APIs.
 * Replaces show_stats.sh — no Python subprocess needed.
 */

class StatsBar {
  constructor() {
    this.cpuEl = document.getElementById('stat-cpu');
    this.ramEl = document.getElementById('stat-ram');
    this.gpuEl = document.getElementById('stat-gpu');
    this.gitEl = document.getElementById('stat-git');
    this._interval = null;
    this._history = { cpu: [], ram: [], gpu: [] };
    this._gitCache = { branch: '', dirty: false, ts: 0 };
  }

  init() {
    this._update();
    this._interval = setInterval(() => this._update(), 1500);
  }

  _update() {
    this._updateCPU();
    this._updateRAM();
    this._updateGPU();
    this._updateGit();
  }

  _updateCPU() {
    // Use os.cpus() to compute CPU usage
    const os = require('os');
    const cpus = os.cpus();
    let totalIdle = 0, totalTick = 0;
    for (const cpu of cpus) {
      for (const type in cpu.times) totalTick += cpu.times[type];
      totalIdle += cpu.times.idle;
    }
    const idle = totalIdle / cpus.length;
    const total = totalTick / cpus.length;

    if (this._lastCpuIdle !== undefined) {
      const idleDelta = idle - this._lastCpuIdle;
      const totalDelta = total - this._lastCpuTotal;
      const pct = totalDelta > 0 ? Math.round((1 - idleDelta / totalDelta) * 100) : 0;
      this._history.cpu.push(pct);
      if (this._history.cpu.length > 16) this._history.cpu.shift();
      const trend = this._trend(this._history.cpu);
      this.cpuEl.innerHTML = `CPU ${this._bar(pct)} <span class="value">${pct}%</span> ${trend}`;
    }
    this._lastCpuIdle = idle;
    this._lastCpuTotal = total;
  }

  _updateRAM() {
    const os = require('os');
    const total = os.totalmem();
    const free = os.freemem();
    const pct = Math.round(((total - free) / total) * 100);
    this._history.ram.push(pct);
    if (this._history.ram.length > 16) this._history.ram.shift();
    const trend = this._trend(this._history.ram);
    this.ramEl.innerHTML = `RAM ${this._bar(pct)} <span class="value">${pct}%</span> ${trend}`;
  }

  _updateGPU() {
    // macOS only: ioreg for GPU utilization
    try {
      const { execSync } = require('child_process');
      const out = execSync(
        "ioreg -r -d 1 -c IOAccelerator 2>/dev/null | grep '\"Device Utilization %\"' | head -1",
        { encoding: 'utf-8', timeout: 2000 }
      );
      const match = out.match(/= (\d+)/);
      const pct = match ? parseInt(match[1], 10) : 0;
      this._history.gpu.push(pct);
      if (this._history.gpu.length > 16) this._history.gpu.shift();
      const trend = this._trend(this._history.gpu);
      this.gpuEl.innerHTML = `GPU ${this._bar(pct)} <span class="value">${pct}%</span> ${trend}`;
    } catch (_) {
      this.gpuEl.innerHTML = 'GPU <span class="value">n/a</span>';
    }
  }

  _updateGit() {
    const now = Date.now();
    if (now - this._gitCache.ts < 15000) {
      this._renderGit();
      return;
    }
    try {
      const { execSync } = require('child_process');
      const branch = execSync('git branch --show-current 2>/dev/null', {
        encoding: 'utf-8',
        timeout: 2000,
        cwd: require('os').homedir(),
      }).trim();
      let dirty = false;
      if (branch) {
        const status = execSync('git status --porcelain 2>/dev/null | head -1', {
          encoding: 'utf-8',
          timeout: 2000,
          cwd: require('os').homedir(),
        }).trim();
        dirty = status.length > 0;
      }
      this._gitCache = { branch, dirty, ts: now };
    } catch (_) {
      this._gitCache = { branch: '', dirty: false, ts: now };
    }
    this._renderGit();
  }

  _renderGit() {
    const { branch, dirty } = this._gitCache;
    if (branch) {
      this.gitEl.className = `stat-cell git-state${dirty ? ' dirty' : ''}`;
      this.gitEl.textContent = `git:${branch}${dirty ? '*' : ''}`;
    } else {
      this.gitEl.textContent = '';
    }
  }

  _bar(pct, width = 6) {
    const filled = Math.round((pct / 100) * width);
    const empty = width - filled;
    return `<span class="bar">${'█'.repeat(filled)}${'░'.repeat(empty)}</span>`;
  }

  _trend(history) {
    if (history.length < 4) return '';
    const recent = history.slice(-4);
    const prior = history.slice(-8, -4);
    if (prior.length === 0) return '';
    const avg = (arr) => arr.reduce((a, b) => a + b, 0) / arr.length;
    const diff = avg(recent) - avg(prior);
    if (diff > 3) return '<span class="trend-up">↑</span>';
    if (diff < -3) return '<span class="trend-down">↓</span>';
    return '<span class="trend-flat">→</span>';
  }

  dispose() {
    if (this._interval) clearInterval(this._interval);
  }
}

window.StatsBar = StatsBar;
