/**
 * ShellBuddy — app.js
 *
 * Main renderer entry point. Orchestrates terminal, hints, stats, and settings.
 */

(async function () {
  // ── Panel toggle state ────────────────────────────────────────────────────
  let hintsVisible = true;
  let statsVisible = true;
  const hintsPanel = document.getElementById('hints-panel');
  const statsBar = document.getElementById('stats-bar');

  // ── Setup Wizard ──────────────────────────────────────────────────────────
  const wizard = new SetupWizard();
  wizard.init(startApp);

  const needsSetup = await wizard.shouldShow();
  if (needsSetup) {
    wizard.show();
  } else {
    document.getElementById('app').classList.remove('hidden');
    startApp();
  }

  async function startApp() {
    // ── Terminal ───────────────────────────────────────────────────────────
    const termContainer = document.getElementById('terminal-container');
    const terminal = new ShellTerminal(termContainer);
    await terminal.init();

    // ── Hints Panel ───────────────────────────────────────────────────────
    const hintsContent = document.getElementById('hints-content');
    const hints = new HintsPanel(hintsContent);
    hints.init();

    // ── Stats Bar ─────────────────────────────────────────────────────────
    const stats = new StatsBar();
    stats.init();

    // ── Settings ──────────────────────────────────────────────────────────
    const settings = new SettingsPanel();
    settings.init();

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

    // ── Menu Event Handlers ───────────────────────────────────────────────
    window.shellbuddy.on('toggle-hints', () => {
      hintsVisible = !hintsVisible;
      hintsPanel.style.display = hintsVisible ? '' : 'none';
    });

    window.shellbuddy.on('toggle-stats', () => {
      statsVisible = !statsVisible;
      statsBar.style.display = statsVisible ? '' : 'none';
    });

    window.shellbuddy.on('clear-terminal', () => {
      terminal.clear();
    });
  }
})();
