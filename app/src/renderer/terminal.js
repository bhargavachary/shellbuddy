/**
 * ShellBuddy — terminal.js
 *
 * xterm.js terminal connected to node-pty via IPC.
 */

/* global Terminal, FitAddon, WebLinksAddon, Unicode11Addon */

class ShellTerminal {
  constructor(container) {
    this.container = container;
    this.term = null;
    this.fitAddon = null;
    this._cleanupPtyData = null;
    this._cleanupPtyExit = null;
  }

  async init() {
    // Dynamic import for xterm.js (loaded via node_modules)
    const { Terminal } = require('@xterm/xterm');
    const { FitAddon } = require('@xterm/addon-fit');
    const { WebLinksAddon } = require('@xterm/addon-web-links');
    const { Unicode11Addon } = require('@xterm/addon-unicode11');

    this.term = new Terminal({
      fontFamily: "'SF Mono', 'JetBrains Mono', 'Menlo', monospace",
      fontSize: 13,
      lineHeight: 1.2,
      cursorStyle: 'bar',
      cursorBlink: true,
      allowProposedApi: true,
      theme: {
        background: '#1e1e2e',
        foreground: '#cdd6f4',
        cursor: '#89dceb',
        cursorAccent: '#1e1e2e',
        selectionBackground: '#31324480',
        black: '#45475a',
        red: '#f38ba8',
        green: '#a6e3a1',
        yellow: '#f9e2af',
        blue: '#89b4fa',
        magenta: '#cba6f7',
        cyan: '#89dceb',
        white: '#bac2de',
        brightBlack: '#585b70',
        brightRed: '#f38ba8',
        brightGreen: '#a6e3a1',
        brightYellow: '#f9e2af',
        brightBlue: '#89b4fa',
        brightMagenta: '#cba6f7',
        brightCyan: '#89dceb',
        brightWhite: '#a6adc8',
      },
    });

    this.fitAddon = new FitAddon();
    this.term.loadAddon(this.fitAddon);
    this.term.loadAddon(new WebLinksAddon());
    this.term.loadAddon(new Unicode11Addon());
    this.term.unicode.activeVersion = '11';

    this.term.open(this.container);
    this.fitAddon.fit();

    // Spawn PTY
    const { cols, rows } = this.term;
    await window.shellbuddy.pty.spawn({ cols, rows });

    // Terminal → PTY
    this.term.onData((data) => window.shellbuddy.pty.write(data));

    // PTY → Terminal
    this._cleanupPtyData = window.shellbuddy.pty.onData((data) => {
      this.term.write(data);
    });

    this._cleanupPtyExit = window.shellbuddy.pty.onExit((code) => {
      this.term.write(`\r\n\x1b[90m[Process exited with code ${code}]\x1b[0m\r\n`);
    });

    // Resize handling
    this.term.onResize(({ cols, rows }) => {
      window.shellbuddy.pty.resize(cols, rows);
    });

    // Window resize → refit
    const resizeObserver = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        if (this.fitAddon) this.fitAddon.fit();
      });
    });
    resizeObserver.observe(this.container);

    this.term.focus();
  }

  clear() {
    if (this.term) this.term.clear();
  }

  dispose() {
    if (this._cleanupPtyData) this._cleanupPtyData();
    if (this._cleanupPtyExit) this._cleanupPtyExit();
    if (this.term) this.term.dispose();
    window.shellbuddy.pty.kill();
  }
}

// Export for app.js
window.ShellTerminal = ShellTerminal;
