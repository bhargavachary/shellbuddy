/**
 * ShellBuddy — app.js
 *
 * Main renderer entry point. Orchestrates terminal, hints, stats, and settings.
 */

(async function () {
  // Global error handler — log but don't crash the UI
  window.onerror = (msg, src, line, col, err) => {
    console.error(`[ShellBuddy] ${msg} at ${src}:${line}:${col}`, err);
  };

  // ── Panel toggle state ────────────────────────────────────────────────────
  let hintsVisible = true;
  let statsVisible = true;
  const hintsPanel = document.getElementById('hints-panel');
  const statsBar = document.getElementById('stats-bar');

  // ── Setup Wizard ──────────────────────────────────────────────────────────
  try {
    const wizard = new SetupWizard();
    wizard.init(startApp);

    const needsSetup = await wizard.shouldShow();
    if (needsSetup) {
      wizard.show();
    } else {
      document.getElementById('app').classList.remove('hidden');
      startApp();
    }
  } catch (err) {
    console.error('[ShellBuddy] Wizard error, starting app directly:', err);
    document.getElementById('app').classList.remove('hidden');
    document.getElementById('setup-wizard').classList.add('hidden');
    startApp();
  }

  async function startApp() {
    // ── Terminal ───────────────────────────────────────────────────────────
    try {
      const termContainer = document.getElementById('terminal-container');
      const terminal = new ShellTerminal(termContainer);
      await terminal.init();

      // Print a welcome banner into the terminal
      const welcome = [
        '\x1b[1;36m',
        '  \u256d\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256e',
        '  \u2502  [>_] ShellBuddy Terminal                      \u2502',
        '  \u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u256f\x1b[0m',
        '',
        '\x1b[2m  This is your terminal. Type commands here as usual.',
        '  ShellBuddy watches what you type and shows hints above.',
        '',
        '  Try:  ls -la          git status          /tip help',
        '',
        '  Shortcuts:',
        '    Cmd+Shift+H   toggle hints panel',
        '    Cmd+Shift+S   toggle stats bar',
        '    Cmd+,         open settings',
        '    Cmd+K         clear terminal\x1b[0m',
        '',
      ];
      terminal.term.write(welcome.join('\r\n') + '\r\n');

      // ── Menu Event Handlers ─────────────────────────────────────────────
      window.shellbuddy.on('clear-terminal', () => terminal.clear());
    } catch (err) {
      console.error('[ShellBuddy] Terminal init error:', err);
      const termContainer = document.getElementById('terminal-container');
      termContainer.innerHTML = `<div style="padding:16px;color:#f38ba8;">
        Terminal failed to initialize: ${err.message}<br>
        <small style="color:#6c7086;">Check DevTools console (Cmd+Alt+I) for details.</small>
      </div>`;
    }

    // ── Hints Panel ───────────────────────────────────────────────────────
    try {
      const hintsContent = document.getElementById('hints-content');
      const hints = new HintsPanel(hintsContent);
      hints.init();
    } catch (err) {
      console.error('[ShellBuddy] Hints init error:', err);
    }

    // ── Stats Bar ─────────────────────────────────────────────────────────
    try {
      const stats = new StatsBar();
      stats.init();
    } catch (err) {
      console.error('[ShellBuddy] Stats init error:', err);
    }

    // ── Settings ──────────────────────────────────────────────────────────
    try {
      const settings = new SettingsPanel();
      settings.init();
    } catch (err) {
      console.error('[ShellBuddy] Settings init error:', err);
    }

    // ── Resize Handle ─────────────────────────────────────────────────────
    const resizeHandle = document.getElementById('hints-resize');
    let isResizing = false;

    resizeHandle.addEventListener('mousedown', (e) => {
      isResizing = true;
      document.body.style.cursor = 'ns-resize';
      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (!isResizing) return;
      const appRect = document.getElementById('app').getBoundingClientRect();
      const statsHeight = statsVisible ? statsBar.offsetHeight : 0;
      const newHeight = e.clientY - appRect.top - statsHeight;
      if (newHeight >= 60 && newHeight <= 400) {
        hintsPanel.style.height = newHeight + 'px';
      }
    });

    document.addEventListener('mouseup', () => {
      if (isResizing) {
        isResizing = false;
        document.body.style.cursor = '';
      }
    });

    // ── Toggle Handlers ─────────────────────────────────────────────────
    window.shellbuddy.on('toggle-hints', () => {
      hintsVisible = !hintsVisible;
      hintsPanel.style.display = hintsVisible ? '' : 'none';
    });

    window.shellbuddy.on('toggle-stats', () => {
      statsVisible = !statsVisible;
      statsBar.style.display = statsVisible ? '' : 'none';
    });
  }
})();
