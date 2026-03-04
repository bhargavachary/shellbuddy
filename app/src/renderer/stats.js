/**
 * ShellBuddy — stats.js
 *
 * System stats bar. Data collected in main process via IPC
 * to avoid blocking the renderer with execSync calls.
 */

class StatsBar {
  constructor() {
    this.cpuEl = document.getElementById('stat-cpu');
    this.ramEl = document.getElementById('stat-ram');
    this.gpuEl = document.getElementById('stat-gpu');
    this.gitEl = document.getElementById('stat-git');
    this._interval = null;
    this._history = { cpu: [], ram: [], gpu: [] };
  }

  init() {
    this._update();
    this._interval = setInterval(() => this._update(), 2000);
  }

  async _update() {
    try {
      const data = await window.shellbuddy.stats.collect();

      if (data.cpu != null) {
        this._history.cpu.push(data.cpu);
        if (this._history.cpu.length > 16) this._history.cpu.shift();
        const trend = this._trend(this._history.cpu);
        this.cpuEl.innerHTML = `CPU ${this._bar(data.cpu)} <span class="value">${data.cpu}%</span> ${trend}`;
      }

      if (data.ram != null) {
        this._history.ram.push(data.ram);
        if (this._history.ram.length > 16) this._history.ram.shift();
        const trend = this._trend(this._history.ram);
        this.ramEl.innerHTML = `RAM ${this._bar(data.ram)} <span class="value">${data.ram}%</span> ${trend}`;
      }

      if (data.gpu != null) {
        this._history.gpu.push(data.gpu);
        if (this._history.gpu.length > 16) this._history.gpu.shift();
        const trend = this._trend(this._history.gpu);
        this.gpuEl.innerHTML = `GPU ${this._bar(data.gpu)} <span class="value">${data.gpu}%</span> ${trend}`;
      } else {
        this.gpuEl.innerHTML = 'GPU <span class="value">n/a</span>';
      }

      if (data.git && data.git.branch) {
        this.gitEl.className = `stat-cell git-state${data.git.dirty ? ' dirty' : ''}`;
        this.gitEl.textContent = `git:${data.git.branch}${data.git.dirty ? '*' : ''}`;
      } else {
        this.gitEl.textContent = '';
      }
    } catch (err) {
      console.error('Stats update error:', err);
    }
  }

  _bar(pct, width = 6) {
    const filled = Math.round((pct / 100) * width);
    const empty = width - filled;
    return `<span class="bar">${'\u2588'.repeat(filled)}${'\u2591'.repeat(empty)}</span>`;
  }

  _trend(history) {
    if (history.length < 4) return '';
    const recent = history.slice(-4);
    const prior = history.slice(-8, -4);
    if (prior.length === 0) return '';
    const avg = (arr) => arr.reduce((a, b) => a + b, 0) / arr.length;
    const diff = avg(recent) - avg(prior);
    if (diff > 3) return '<span class="trend-up">\u2191</span>';
    if (diff < -3) return '<span class="trend-down">\u2193</span>';
    return '<span class="trend-flat">\u2192</span>';
  }

  dispose() {
    if (this._interval) clearInterval(this._interval);
  }
}

window.StatsBar = StatsBar;
