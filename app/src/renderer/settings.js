/**
 * ShellBuddy — settings.js
 *
 * Settings panel UI — reads/writes config.json via IPC.
 */

class SettingsPanel {
  constructor() {
    this.panel = document.getElementById('settings-panel');
    this.form = document.getElementById('settings-form');
    this.closeBtn = document.getElementById('settings-close');
    this.saveBtn = document.getElementById('settings-save');
    this.cancelBtn = document.getElementById('settings-cancel');
    this._config = {};
  }

  init() {
    this.closeBtn.addEventListener('click', () => this.hide());
    this.cancelBtn.addEventListener('click', () => this.hide());
    this.saveBtn.addEventListener('click', () => this.save());

    // Listen for menu shortcut
    window.shellbuddy.on('show-settings', () => this.show());
  }

  async show() {
    this._config = await window.shellbuddy.config.read();
    this._renderForm();
    this.panel.classList.remove('hidden');
  }

  hide() {
    this.panel.classList.add('hidden');
  }

  async save() {
    // Read values from form
    const inputs = this.form.querySelectorAll('input, select');
    for (const input of inputs) {
      const key = input.dataset.key;
      if (!key) continue;
      if (input.type === 'number') {
        this._config[key] = parseInt(input.value, 10) || 0;
      } else if (input.type === 'checkbox') {
        this._config[key] = input.checked;
      } else {
        this._config[key] = input.value;
      }
    }
    await window.shellbuddy.config.write(this._config);
    this.hide();
  }

  _renderForm() {
    const fields = [
      { key: 'hint_backend', label: 'Hint Backend', type: 'select', options: ['copilot', 'claude', 'ollama', 'openai', 'none'] },
      { key: 'hint_model', label: 'Hint Model', type: 'text' },
      { key: 'tip_backend', label: '/tip Backend', type: 'select', options: ['copilot', 'claude', 'ollama', 'openai', 'none'] },
      { key: 'tip_model', label: '/tip Model', type: 'text' },
      { type: 'separator', label: 'Timing' },
      { key: 'hint_interval_secs', label: 'Hint Interval (sec)', type: 'number', min: 1, max: 30 },
      { key: 'ai_throttle_secs', label: 'AI Throttle (sec)', type: 'number', min: 5, max: 120 },
      { key: 'rule_cooldown_secs', label: 'Rule Cooldown (sec)', type: 'number', min: 10, max: 600 },
      { key: 'idle_timeout_secs', label: 'Idle Timeout (sec)', type: 'number', min: 30, max: 300 },
      { type: 'separator', label: 'Features' },
      { key: 'enable_post_mortem', label: 'Auto-draft commit messages', type: 'checkbox' },
      { key: 'enable_idle_tips', label: 'Show idle tips', type: 'checkbox' },
    ];

    let html = '';
    for (const field of fields) {
      if (field.type === 'separator') {
        html += `<div style="margin-top:8px;color:var(--fg-dim);font-size:11px;text-transform:uppercase;letter-spacing:1px">${field.label}</div>`;
        continue;
      }
      const val = this._config[field.key] ?? '';
      if (field.type === 'select') {
        const opts = field.options.map(o => `<option value="${o}"${val === o ? ' selected' : ''}>${o}</option>`).join('');
        html += `<label>${field.label}<select data-key="${field.key}">${opts}</select></label>`;
      } else if (field.type === 'checkbox') {
        html += `<label class="checkbox-label"><input type="checkbox" data-key="${field.key}"${val ? ' checked' : ''}><span>${field.label}</span></label>`;
      } else if (field.type === 'number') {
        html += `<label>${field.label}<input type="number" data-key="${field.key}" value="${val || ''}" min="${field.min || 0}" max="${field.max || 999}"></label>`;
      } else {
        html += `<label>${field.label}<input type="text" data-key="${field.key}" value="${val}"></label>`;
      }
    }
    this.form.innerHTML = html;
  }
}

window.SettingsPanel = SettingsPanel;
