/**
 * ShellBuddy — settings.js
 *
 * Settings panel UI — reads/writes config.json via IPC.
 * Grouped layout: Terminal appearance + AI backend + daemon config.
 */

class SettingsPanel {
  constructor() {
    this.panel = document.getElementById('settings-panel');
    this.form = document.getElementById('settings-form');
    this.closeBtn = document.getElementById('settings-close');
    this.saveBtn = document.getElementById('settings-save');
    this.cancelBtn = document.getElementById('settings-cancel');
    this._config = {};
    this._onSave = null; // callback after save
  }

  init() {
    this.closeBtn.addEventListener('click', () => this.hide());
    this.cancelBtn.addEventListener('click', () => this.hide());
    this.saveBtn.addEventListener('click', () => this.save());
    window.shellbuddy.on('show-settings', () => this.show());
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !this.panel.classList.contains('hidden')) this.hide();
    });
  }

  onSave(cb) { this._onSave = cb; }

  async show() {
    this._config = await window.shellbuddy.config.read();
    this._renderForm();
    this.panel.classList.remove('hidden');
  }

  hide() { this.panel.classList.add('hidden'); }

  async save() {
    const inputs = this.form.querySelectorAll('input, select');
    for (const input of inputs) {
      const key = input.dataset.key;
      if (!key) continue;
      if (input.dataset.type === 'float') {
        this._config[key] = parseFloat(input.value) || 0;
      } else if (input.type === 'number' || input.type === 'range') {
        this._config[key] = parseInt(input.value, 10) || 0;
      } else if (input.type === 'checkbox') {
        this._config[key] = input.checked;
      } else {
        this._config[key] = input.value;
      }
    }

    // Validate terminal settings
    this._config.terminal_font_size = Math.max(10, Math.min(24, this._config.terminal_font_size || 13));
    this._config.terminal_line_height = Math.max(1.0, Math.min(2.0, this._config.terminal_line_height || 1.2));
    this._config.terminal_letter_spacing = Math.max(-2, Math.min(5, this._config.terminal_letter_spacing || 0));
    this._config.terminal_scrollback = Math.max(100, Math.min(50000, this._config.terminal_scrollback || 1000));

    await window.shellbuddy.config.write(this._config);
    if (this._onSave) this._onSave(this._config);
    this.hide();
  }

  _renderForm() {
    const backend = this._config.hint_backend || 'none';
    const tipBackend = this._config.tip_backend || backend;
    const defaults = window.TERMINAL_DEFAULTS || {};

    const sections = [
      {
        title: 'Terminal',
        desc: 'Font, cursor, scrollback, and color theme.',
        fields: [
          { key: 'terminal_font_family', label: 'Font', type: 'select',
            options: ['SF Mono', 'JetBrains Mono', 'Menlo', 'Fira Code', 'Cascadia Code', 'Monaco'] },
          { key: 'terminal_font_size', label: 'Font size', type: 'range', min: 10, max: 24, unit: 'px' },
          { key: 'terminal_line_height', label: 'Line height', type: 'range-float', min: 1.0, max: 2.0, step: 0.1 },
          { key: 'terminal_letter_spacing', label: 'Letter spacing', type: 'number', min: -2, max: 5, unit: 'px' },
          { key: 'terminal_cursor_style', label: 'Cursor', type: 'select', options: ['bar', 'block', 'underline'] },
          { key: 'terminal_cursor_blink', label: 'Cursor blink', type: 'checkbox' },
          { key: 'terminal_scrollback', label: 'Scrollback', type: 'number', min: 100, max: 50000, unit: 'lines' },
          { key: 'terminal_bell', label: 'Bell', type: 'select', options: ['none', 'sound', 'visual'] },
          { key: 'terminal_theme', label: 'Theme', type: 'theme-select' },
        ],
      },
      {
        title: 'AI Backend',
        desc: 'Choose which AI powers your hints and /tip queries.',
        fields: [
          { key: 'hint_backend', label: 'Hints backend', type: 'select',
            options: ['copilot', 'claude', 'ollama', 'openai', 'none'] },
          { key: 'hint_model', label: 'Hints model', type: 'text',
            placeholder: this._suggestModel(backend, 'hint') },
          { key: 'tip_backend', label: '/tip backend', type: 'select',
            options: ['copilot', 'claude', 'ollama', 'openai', 'none'] },
          { key: 'tip_model', label: '/tip model', type: 'text',
            placeholder: this._suggestModel(tipBackend, 'tip') },
        ],
      },
      {
        title: 'Backend URLs',
        desc: 'Endpoints for self-hosted or custom API providers.',
        fields: [
          { key: 'ollama_url', label: 'Ollama URL', type: 'text', placeholder: 'http://localhost:11434' },
          { key: 'openai_url', label: 'OpenAI-compatible URL', type: 'text', placeholder: 'https://api.openai.com/v1' },
        ],
      },
      {
        title: 'Timing',
        desc: 'Control how often hints refresh and AI calls fire.',
        fields: [
          { key: 'hint_interval_secs', label: 'Hint refresh interval', type: 'number', min: 1, max: 30, unit: 'sec' },
          { key: 'ai_throttle_secs', label: 'AI call throttle', type: 'number', min: 1, max: 120, unit: 'sec' },
          { key: 'rule_cooldown_secs', label: 'Rule repeat cooldown', type: 'number', min: 0, max: 600, unit: 'sec' },
          { key: 'advisor_throttle_secs', label: 'Advisor throttle', type: 'number', min: 1, max: 300, unit: 'sec' },
          { key: 'idle_timeout_secs', label: 'Idle timeout', type: 'number', min: 30, max: 600, unit: 'sec' },
        ],
      },
      {
        title: 'Context',
        desc: 'How much session history the AI sees.',
        fields: [
          { key: 'context_max_entries', label: 'Max context entries', type: 'number', min: 50, max: 500 },
          { key: 'context_inject_entries', label: 'Entries injected per prompt', type: 'number', min: 5, max: 50 },
          { key: 'advisor_window', label: 'Advisor lookback window', type: 'number', min: 10, max: 100 },
        ],
      },
      {
        title: 'Features',
        desc: 'Toggle optional capabilities.',
        fields: [
          { key: 'enable_post_mortem', label: 'Auto-draft commit messages', type: 'checkbox' },
          { key: 'enable_idle_tips', label: 'Show idle tips', type: 'checkbox' },
        ],
      },
      {
        title: 'Shell Integration',
        desc: 'Patch ~/.zshrc so external terminals also log to ShellBuddy.',
        fields: [
          { key: '_shell_integration', type: 'shell-toggle' },
        ],
      },
    ];

    let html = '';
    for (const section of sections) {
      html += `<div class="settings-section">`;
      html += `<div class="settings-section-title">${section.title}</div>`;
      if (section.desc) html += `<div class="settings-section-desc">${section.desc}</div>`;
      for (const field of section.fields) {
        if (field.type === 'shell-toggle') { html += this._renderShellToggle(); continue; }
        if (field.type === 'theme-select') { html += this._renderThemeSelect(field); continue; }
        html += this._renderField(field);
      }
      html += `</div>`;
    }

    this.form.innerHTML = html;

    // Wire up interactive elements
    this._wireShellToggle();
    this._wireRangeSliders();
    this._wireBackendHints(backend, tipBackend);
  }

  _renderField(field) {
    const defaults = window.TERMINAL_DEFAULTS || {};
    const val = this._config[field.key] ?? defaults[field.key] ?? '';
    let input = '';

    if (field.type === 'select') {
      const opts = field.options.map(o =>
        `<option value="${o}"${val === o ? ' selected' : ''}>${o}</option>`
      ).join('');
      input = `<select data-key="${field.key}">${opts}</select>`;
    } else if (field.type === 'checkbox') {
      const checked = val !== '' ? val : true;
      return `<label class="checkbox-label settings-checkbox">
        <input type="checkbox" data-key="${field.key}"${checked ? ' checked' : ''}>
        <span>${field.label}</span>
      </label>`;
    } else if (field.type === 'range') {
      const v = val || field.min;
      const unit = field.unit || '';
      input = `<div class="range-field">
        <input type="range" data-key="${field.key}" value="${v}"
          min="${field.min}" max="${field.max}" step="1">
        <span class="range-value">${v}${unit}</span>
      </div>`;
      return `<label class="settings-field"><span class="field-label">${field.label}</span>${input}</label>`;
    } else if (field.type === 'range-float') {
      const v = val || field.min;
      input = `<div class="range-field">
        <input type="range" data-key="${field.key}" data-type="float" value="${v}"
          min="${field.min}" max="${field.max}" step="${field.step || 0.1}">
        <span class="range-value">${parseFloat(v).toFixed(1)}</span>
      </div>`;
      return `<label class="settings-field"><span class="field-label">${field.label}</span>${input}</label>`;
    } else if (field.type === 'number') {
      const unit = field.unit ? `<span class="field-unit">${field.unit}</span>` : '';
      input = `<div class="number-field">
        <input type="number" data-key="${field.key}" value="${val || ''}"
          min="${field.min || 0}" max="${field.max || 999}"
          placeholder="${field.min || 0}">
        ${unit}
      </div>`;
      return `<label class="settings-field"><span class="field-label">${field.label}</span>${input}</label>`;
    } else {
      input = `<input type="text" data-key="${field.key}" value="${val}"
        placeholder="${field.placeholder || ''}">`;
    }

    return `<label class="settings-field"><span class="field-label">${field.label}</span>${input}</label>`;
  }

  _renderThemeSelect(field) {
    const presets = window.THEME_PRESETS || {};
    const current = this._config[field.key] || 'catppuccin-mocha';
    const names = Object.keys(presets);

    let html = `<label class="settings-field"><span class="field-label">${field.label}</span>`;
    html += `<select data-key="${field.key}">`;
    for (const name of names) {
      html += `<option value="${name}"${name === current ? ' selected' : ''}>${name}</option>`;
    }
    html += `</select></label>`;

    // Color swatch preview
    const theme = presets[current] || {};
    const colors = [theme.red, theme.green, theme.yellow, theme.blue, theme.magenta, theme.cyan].filter(Boolean);
    html += `<div class="theme-preview" id="theme-preview">`;
    html += `<span class="theme-bg" style="background:${theme.background || '#1e1e2e'};color:${theme.foreground || '#cdd6f4'}">Aa</span>`;
    for (const c of colors) {
      html += `<span class="theme-swatch" style="background:${c}"></span>`;
    }
    html += `</div>`;

    return html;
  }

  _renderShellToggle() {
    return `<div class="shell-toggle-row">
      <span class="shell-toggle-status" id="shell-toggle-status">Checking...</span>
      <button id="shell-toggle-btn" class="btn-secondary btn-sm">...</button>
    </div>`;
  }

  _wireShellToggle() {
    const shellBtn = this.form.querySelector('#shell-toggle-btn');
    if (shellBtn) {
      this._updateShellToggle();
      shellBtn.addEventListener('click', () => this._handleShellToggle());
    }
  }

  _wireRangeSliders() {
    const ranges = this.form.querySelectorAll('input[type="range"]');
    for (const range of ranges) {
      const display = range.parentElement.querySelector('.range-value');
      if (!display) continue;
      const isFloat = range.dataset.type === 'float';
      const unit = range.closest('.settings-field')?.querySelector('.field-label')?.textContent.includes('size') ? 'px' : '';
      range.addEventListener('input', () => {
        display.textContent = isFloat ? parseFloat(range.value).toFixed(1) : `${range.value}${unit}`;
      });
    }

    // Theme swatch live update
    const themeSelect = this.form.querySelector('[data-key="terminal_theme"]');
    if (themeSelect) {
      themeSelect.addEventListener('change', () => {
        const presets = window.THEME_PRESETS || {};
        const theme = presets[themeSelect.value] || {};
        const preview = document.getElementById('theme-preview');
        if (!preview) return;
        const colors = [theme.red, theme.green, theme.yellow, theme.blue, theme.magenta, theme.cyan].filter(Boolean);
        let html = `<span class="theme-bg" style="background:${theme.background || '#1e1e2e'};color:${theme.foreground || '#cdd6f4'}">Aa</span>`;
        for (const c of colors) html += `<span class="theme-swatch" style="background:${c}"></span>`;
        preview.innerHTML = html;
      });
    }
  }

  _wireBackendHints() {
    const hintBackendSelect = this.form.querySelector('[data-key="hint_backend"]');
    const tipBackendSelect = this.form.querySelector('[data-key="tip_backend"]');
    const hintModelInput = this.form.querySelector('[data-key="hint_model"]');
    const tipModelInput = this.form.querySelector('[data-key="tip_model"]');
    if (hintBackendSelect && hintModelInput) {
      hintBackendSelect.addEventListener('change', () => {
        hintModelInput.placeholder = this._suggestModel(hintBackendSelect.value, 'hint');
      });
    }
    if (tipBackendSelect && tipModelInput) {
      tipBackendSelect.addEventListener('change', () => {
        tipModelInput.placeholder = this._suggestModel(tipBackendSelect.value, 'tip');
      });
    }
  }

  async _updateShellToggle() {
    const status = document.getElementById('shell-toggle-status');
    const btn = document.getElementById('shell-toggle-btn');
    try {
      const installed = await window.shellbuddy.shellIntegration.isInstalled();
      if (installed) {
        status.textContent = 'Installed';
        status.className = 'shell-toggle-status installed';
        btn.textContent = 'Uninstall';
        btn.dataset.action = 'uninstall';
      } else {
        status.textContent = 'Not installed';
        status.className = 'shell-toggle-status';
        btn.textContent = 'Install';
        btn.dataset.action = 'install';
      }
    } catch (_) {
      status.textContent = 'Unknown';
      btn.textContent = 'Install';
      btn.dataset.action = 'install';
    }
  }

  async _handleShellToggle() {
    const btn = document.getElementById('shell-toggle-btn');
    btn.disabled = true;
    btn.textContent = '...';
    try {
      if (btn.dataset.action === 'uninstall') {
        await window.shellbuddy.shellIntegration.uninstall();
      } else {
        await window.shellbuddy.shellIntegration.install();
      }
    } catch (err) {
      console.error('Shell integration error:', err);
    }
    await this._updateShellToggle();
    btn.disabled = false;
  }

  _suggestModel(backend, role) {
    const hints = {
      copilot: role === 'tip' ? 'gpt-4.1' : 'gpt-4.1-mini',
      claude: role === 'tip' ? 'claude-sonnet-4-6' : 'claude-haiku-4-5-20251001',
      ollama: role === 'tip' ? 'qwen3:8b' : 'qwen3:4b',
      openai: role === 'tip' ? 'gpt-4o' : 'gpt-4o-mini',
      none: '',
    };
    return hints[backend] || '';
  }
}

window.SettingsPanel = SettingsPanel;
