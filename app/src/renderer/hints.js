/**
 * ShellBuddy — hints.js
 *
 * Renders current_hints.txt content in the hints panel.
 * Parses the tab-separated format produced by hint_daemon.py.
 */

class HintsPanel {
  constructor(container) {
    this.container = container;
    this._cleanup = null;
  }

  init() {
    this._cleanup = window.shellbuddy.hints.onUpdate((content) => {
      this.render(content);
    });
  }

  render(content) {
    if (!content || !content.trim()) {
      this.container.innerHTML = '<span class="hint-placeholder">Waiting for hints... run a few commands</span>';
      return;
    }

    const lines = content.split('\n');
    const html = [];

    for (const rawLine of lines) {
      if (!rawLine) continue;
      const fields = rawLine.split('\t');
      const f1 = fields[0] || '';
      const f2 = fields[1] || '';
      const f3 = fields.slice(2).join('\t');

      if (f1.startsWith('HINTS') && !f2) {
        // Header
        html.push(`<div class="hint-line hint-header">[>_] ${this._esc(f1)}</div>`);
      } else if (f1.startsWith('─') && !f2) {
        // Separator
        html.push(`<div class="hint-line hint-separator">${this._esc(f1)}</div>`);
      } else if (f1 === 'LOGO') {
        // Logo line — render logo floated right, hint on left
        const logo = f2;
        const hint = f3;
        if (hint && hint.match(/^\[\d+x\]/)) {
          html.push(`<div class="hint-line"><span class="hint-rule">${this._esc(hint)}</span><span class="hint-logo">${this._esc(logo)}</span></div>`);
        } else if (hint === '·') {
          html.push(`<div class="hint-line hint-divider">·<span class="hint-logo">${this._esc(logo)}</span></div>`);
        } else if (hint) {
          html.push(`<div class="hint-line"><span class="hint-ai">${this._esc(hint)}</span><span class="hint-logo">${this._esc(logo)}</span></div>`);
        } else {
          html.push(`<div class="hint-line"><span class="hint-logo">${this._esc(logo)}</span></div>`);
        }
      } else if (f1 === 'LOGO_TAG') {
        const tag = f2;
        const hint = f3;
        if (hint) {
          html.push(`<div class="hint-line"><span class="hint-ai">${this._esc(hint)}</span><span class="hint-logo" style="color:var(--magenta-bold)">${this._esc(tag)}</span></div>`);
        } else {
          html.push(`<div class="hint-line"><span class="hint-logo" style="color:var(--magenta-bold)">${this._esc(tag)}</span></div>`);
        }
      } else if (f1 === 'IDLE_TIP') {
        html.push(`<div class="hint-line hint-idle-tip"><span class="cmd">${this._esc(f2)}</span><span class="desc">${this._esc(f3)}</span></div>`);
      } else if (f1 === 'IDLE_LABEL') {
        html.push(`<div class="hint-line hint-idle-label">${this._esc(f2)}</div>`);
      } else if (f1.match(/^\[\d+x\]/) && !f2) {
        html.push(`<div class="hint-line hint-rule">${this._esc(f1)}</div>`);
      } else if (f1 === '·' && !f2) {
        html.push(`<div class="hint-line hint-divider">·</div>`);
      } else if (f1.startsWith('thinking') && !f2) {
        html.push(`<div class="hint-line hint-thinking">${this._esc(f1)}</div>`);
      } else if (f1 && !f2) {
        html.push(`<div class="hint-line hint-ai">${this._esc(f1)}</div>`);
      }
    }

    this.container.innerHTML = html.join('') || '<span class="hint-placeholder">No hints yet</span>';
  }

  _esc(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  dispose() {
    if (this._cleanup) this._cleanup();
  }
}

window.HintsPanel = HintsPanel;
