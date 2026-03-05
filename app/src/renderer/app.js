/**
 * ShellBuddy — app.js
 *
 * Renderer entry point. Boots wizard or main app.
 */

(async function () {
  window.onerror = (msg, src, line) => console.error(`[ShellBuddy] ${msg} at ${src}:${line}`);

  const $ = (id) => document.getElementById(id);
  const hintsPanel = $('hints-panel');
  const statsBar = $('stats-bar');
  let hintsVisible = true, statsVisible = true;

  // ── Boot ──────────────────────────────────────────────────────────────────
  try {
    const wizard = new SetupWizard();
    wizard.init(startApp);
    if (await wizard.shouldShow()) {
      wizard.show();
    } else {
      $('app').classList.remove('hidden');
      startApp();
    }
  } catch (err) {
    console.error('[ShellBuddy] Boot error:', err);
    $('app').classList.remove('hidden');
    $('setup-wizard').classList.add('hidden');
    startApp();
  }

  async function startApp() {
    // Terminal
    let terminal = null;
    try {
      terminal = new ShellTerminal($('terminal-container'));
      await terminal.init();
      terminal.term.write([
        '\x1b[1;36m',
        '  \u256d\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e',
        '  \u2502  [>_] ShellBuddy Terminal                      \u2502',
        '  \u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f\x1b[0m',
        '',
        '\x1b[2m  Type commands here. ShellBuddy shows hints above.',
        '  Cmd+Shift+H hints | Cmd+Shift+S stats | Cmd+, settings | Cmd+K clear\x1b[0m',
        '',
      ].join('\r\n') + '\r\n');
      window.shellbuddy.on('clear-terminal', () => terminal.clear());
    } catch (err) {
      console.error('[ShellBuddy] Terminal error:', err);
      $('terminal-container').innerHTML = `<div style="padding:16px;color:#f38ba8;">
        Terminal failed: ${err.message}<br>
        <small style="color:#6c7086;">Cmd+Alt+I for DevTools</small></div>`;
    }

    // Hints
    try { new HintsPanel($('hints-content')).init(); } catch (e) { console.error('Hints:', e); }

    // Stats
    try { new StatsBar().init(); } catch (e) { console.error('Stats:', e); }

    // Settings — wire live terminal update on save
    try {
      const settings = new SettingsPanel();
      settings.init();
      settings.onSave((cfg) => {
        if (terminal) terminal.applySettings(cfg);
      });
    } catch (e) { console.error('Settings:', e); }

    // Resize handle
    let resizing = false;
    $('hints-resize').addEventListener('mousedown', (e) => { resizing = true; document.body.style.cursor = 'ns-resize'; e.preventDefault(); });
    document.addEventListener('mousemove', (e) => {
      if (!resizing) return;
      const top = $('app').getBoundingClientRect().top + (statsVisible ? statsBar.offsetHeight : 0);
      const h = e.clientY - top;
      if (h >= 60 && h <= 400) hintsPanel.style.height = h + 'px';
    });
    document.addEventListener('mouseup', () => { if (resizing) { resizing = false; document.body.style.cursor = ''; } });

    // Toggles
    window.shellbuddy.on('toggle-hints', () => { hintsVisible = !hintsVisible; hintsPanel.style.display = hintsVisible ? '' : 'none'; });
    window.shellbuddy.on('toggle-stats', () => { statsVisible = !statsVisible; statsBar.style.display = statsVisible ? '' : 'none'; });
  }
})();
