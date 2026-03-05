/**
 * ShellBuddy — terminal.js
 *
 * xterm.js terminal connected to node-pty via IPC.
 * require() works because nodeIntegration: true + contextIsolation: false.
 */

const { Terminal } = require('@xterm/xterm');
const { FitAddon } = require('@xterm/addon-fit');

// ── Theme Presets ────────────────────────────────────────────────────────────
const THEME_PRESETS = {
  'catppuccin-mocha': {
    background: '#1e1e2e', foreground: '#cdd6f4',
    cursor: '#89dceb', cursorAccent: '#1e1e2e', selectionBackground: '#31324480',
    black: '#45475a', red: '#f38ba8', green: '#a6e3a1', yellow: '#f9e2af',
    blue: '#89b4fa', magenta: '#cba6f7', cyan: '#89dceb', white: '#bac2de',
    brightBlack: '#585b70', brightRed: '#f38ba8', brightGreen: '#a6e3a1', brightYellow: '#f9e2af',
    brightBlue: '#89b4fa', brightMagenta: '#cba6f7', brightCyan: '#89dceb', brightWhite: '#a6adc8',
  },
  'catppuccin-latte': {
    background: '#eff1f5', foreground: '#4c4f69',
    cursor: '#04a5e5', cursorAccent: '#eff1f5', selectionBackground: '#acb0be80',
    black: '#5c5f77', red: '#d20f39', green: '#40a02b', yellow: '#df8e1d',
    blue: '#1e66f5', magenta: '#8839ef', cyan: '#04a5e5', white: '#acb0be',
    brightBlack: '#6c6f85', brightRed: '#d20f39', brightGreen: '#40a02b', brightYellow: '#df8e1d',
    brightBlue: '#1e66f5', brightMagenta: '#8839ef', brightCyan: '#04a5e5', brightWhite: '#bcc0cc',
  },
  'dracula': {
    background: '#282a36', foreground: '#f8f8f2',
    cursor: '#f8f8f2', cursorAccent: '#282a36', selectionBackground: '#44475a80',
    black: '#21222c', red: '#ff5555', green: '#50fa7b', yellow: '#f1fa8c',
    blue: '#bd93f9', magenta: '#ff79c6', cyan: '#8be9fd', white: '#f8f8f2',
    brightBlack: '#6272a4', brightRed: '#ff6e6e', brightGreen: '#69ff94', brightYellow: '#ffffa5',
    brightBlue: '#d6acff', brightMagenta: '#ff92df', brightCyan: '#a4ffff', brightWhite: '#ffffff',
  },
  'nord': {
    background: '#2e3440', foreground: '#d8dee9',
    cursor: '#d8dee9', cursorAccent: '#2e3440', selectionBackground: '#434c5e80',
    black: '#3b4252', red: '#bf616a', green: '#a3be8c', yellow: '#ebcb8b',
    blue: '#81a1c1', magenta: '#b48ead', cyan: '#88c0d0', white: '#e5e9f0',
    brightBlack: '#4c566a', brightRed: '#bf616a', brightGreen: '#a3be8c', brightYellow: '#ebcb8b',
    brightBlue: '#81a1c1', brightMagenta: '#b48ead', brightCyan: '#8fbcbb', brightWhite: '#eceff4',
  },
  'solarized-dark': {
    background: '#002b36', foreground: '#839496',
    cursor: '#839496', cursorAccent: '#002b36', selectionBackground: '#073642',
    black: '#073642', red: '#dc322f', green: '#859900', yellow: '#b58900',
    blue: '#268bd2', magenta: '#d33682', cyan: '#2aa198', white: '#eee8d5',
    brightBlack: '#586e75', brightRed: '#cb4b16', brightGreen: '#586e75', brightYellow: '#657b83',
    brightBlue: '#839496', brightMagenta: '#6c71c4', brightCyan: '#93a1a1', brightWhite: '#fdf6e3',
  },
  'tokyonight': {
    background: '#1a1b26', foreground: '#c0caf5',
    cursor: '#c0caf5', cursorAccent: '#1a1b26', selectionBackground: '#33467c80',
    black: '#15161e', red: '#f7768e', green: '#9ece6a', yellow: '#e0af68',
    blue: '#7aa2f7', magenta: '#bb9af7', cyan: '#7dcfff', white: '#a9b1d6',
    brightBlack: '#414868', brightRed: '#f7768e', brightGreen: '#9ece6a', brightYellow: '#e0af68',
    brightBlue: '#7aa2f7', brightMagenta: '#bb9af7', brightCyan: '#7dcfff', brightWhite: '#c0caf5',
  },
  'gruvbox': {
    background: '#282828', foreground: '#ebdbb2',
    cursor: '#ebdbb2', cursorAccent: '#282828', selectionBackground: '#3c383680',
    black: '#282828', red: '#cc241d', green: '#98971a', yellow: '#d79921',
    blue: '#458588', magenta: '#b16286', cyan: '#689d6a', white: '#a89984',
    brightBlack: '#928374', brightRed: '#fb4934', brightGreen: '#b8bb26', brightYellow: '#fabd2f',
    brightBlue: '#83a598', brightMagenta: '#d3869b', brightCyan: '#8ec07c', brightWhite: '#ebdbb2',
  },
};

// ── Defaults ─────────────────────────────────────────────────────────────────
const TERMINAL_DEFAULTS = {
  terminal_font_family: 'SF Mono',
  terminal_font_size: 13,
  terminal_line_height: 1.2,
  terminal_letter_spacing: 0,
  terminal_cursor_style: 'bar',
  terminal_cursor_blink: true,
  terminal_scrollback: 1000,
  terminal_bell: 'none',
  terminal_theme: 'catppuccin-mocha',
};

const FONT_MAP = {
  'SF Mono': "'SF Mono', monospace",
  'JetBrains Mono': "'JetBrains Mono', monospace",
  'Menlo': "'Menlo', monospace",
  'Fira Code': "'Fira Code', monospace",
  'Cascadia Code': "'Cascadia Code', monospace",
  'Monaco': "'Monaco', monospace",
};

class ShellTerminal {
  constructor(container) {
    this.container = container;
    this.term = null;
    this.fitAddon = null;
  }

  async init() {
    // Load saved preferences
    let cfg = {};
    try { cfg = await window.shellbuddy.config.read() || {}; } catch (_) {}
    const prefs = { ...TERMINAL_DEFAULTS };
    for (const k of Object.keys(TERMINAL_DEFAULTS)) {
      if (cfg[k] !== undefined) prefs[k] = cfg[k];
    }

    const themeName = prefs.terminal_theme;
    const theme = THEME_PRESETS[themeName] || THEME_PRESETS['catppuccin-mocha'];

    this.term = new Terminal({
      fontFamily: FONT_MAP[prefs.terminal_font_family] || FONT_MAP['SF Mono'],
      fontSize: prefs.terminal_font_size,
      lineHeight: prefs.terminal_line_height,
      letterSpacing: prefs.terminal_letter_spacing,
      cursorStyle: prefs.terminal_cursor_style,
      cursorBlink: prefs.terminal_cursor_blink,
      scrollback: prefs.terminal_scrollback,
      bellStyle: prefs.terminal_bell,
      theme,
    });

    this.fitAddon = new FitAddon();
    this.term.loadAddon(this.fitAddon);
    this.term.open(this.container);
    this.fitAddon.fit();

    // Update app background to match terminal theme
    this._syncAppBackground(theme);

    // Spawn PTY in main process
    const { cols, rows } = this.term;
    await window.shellbuddy.pty.spawn({ cols, rows });

    // Wire data flow
    this.term.onData((data) => window.shellbuddy.pty.write(data));
    window.shellbuddy.pty.onData((data) => this.term.write(data));
    window.shellbuddy.pty.onExit((code) => {
      this.term.write(`\r\n\x1b[90m[Process exited: ${code}]\x1b[0m\r\n`);
    });

    // Resize sync
    this.term.onResize(({ cols, rows }) => window.shellbuddy.pty.resize(cols, rows));
    new ResizeObserver(() => requestAnimationFrame(() => this.fitAddon && this.fitAddon.fit()))
      .observe(this.container);

    this.term.focus();
  }

  applySettings(cfg) {
    if (!this.term) return;
    const prefs = { ...TERMINAL_DEFAULTS };
    for (const k of Object.keys(TERMINAL_DEFAULTS)) {
      if (cfg[k] !== undefined) prefs[k] = cfg[k];
    }

    this.term.options.fontFamily = FONT_MAP[prefs.terminal_font_family] || FONT_MAP['SF Mono'];
    this.term.options.fontSize = prefs.terminal_font_size;
    this.term.options.lineHeight = prefs.terminal_line_height;
    this.term.options.letterSpacing = prefs.terminal_letter_spacing;
    this.term.options.cursorStyle = prefs.terminal_cursor_style;
    this.term.options.cursorBlink = prefs.terminal_cursor_blink;
    this.term.options.scrollback = prefs.terminal_scrollback;
    this.term.options.bellStyle = prefs.terminal_bell;

    const theme = THEME_PRESETS[prefs.terminal_theme] || THEME_PRESETS['catppuccin-mocha'];
    this.term.options.theme = theme;
    this._syncAppBackground(theme);

    // Recalculate cols/rows after font changes
    if (this.fitAddon) this.fitAddon.fit();
  }

  _syncAppBackground(theme) {
    // Keep the terminal container background in sync with the theme
    if (theme.background) {
      this.container.style.background = theme.background;
    }
  }

  clear() { if (this.term) this.term.clear(); }
}

window.ShellTerminal = ShellTerminal;
window.THEME_PRESETS = THEME_PRESETS;
window.TERMINAL_DEFAULTS = TERMINAL_DEFAULTS;
