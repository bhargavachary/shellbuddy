/**
 * ShellBuddy — Electron main process
 *
 * Window management, PTY spawning, daemon lifecycle,
 * stats collection, hints watching, config I/O.
 */

const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const path = require('path');
const os = require('os');
const fs = require('fs');
const { execSync } = require('child_process');

const { DaemonManager } = require('./utils/daemon');
const { findPython } = require('./utils/python');
const shellIntegration = require('./utils/shell-integration');

const SB_DIR = process.env.SHELLBUDDY_DIR || path.join(os.homedir(), '.shellbuddy');
const HINTS_FILE = path.join(SB_DIR, 'current_hints.txt');
const CONFIG_FILE = path.join(SB_DIR, 'config.json');

function resourcePath(...parts) {
  if (app.isPackaged) return path.join(process.resourcesPath, ...parts);
  return path.join(__dirname, '..', '..', ...parts);
}

let mainWindow = null;
let daemon = null;
let hintsWatcher = null;
let hintsPoller = null;
let ptyProcess = null;

// ── Window ────────────────────────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1000,
    height: 700,
    minWidth: 600,
    minHeight: 400,
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 12, y: 12 },
    backgroundColor: '#1e1e2e',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: true,
      contextIsolation: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  if (!app.isPackaged) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: 'ShellBuddy',
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { label: 'Settings', accelerator: 'Cmd+,', click: () => send('show-settings') },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
        { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { label: 'Toggle Hints', accelerator: 'Cmd+Shift+H', click: () => send('toggle-hints') },
        { label: 'Toggle Stats', accelerator: 'Cmd+Shift+S', click: () => send('toggle-stats') },
        { type: 'separator' },
        { role: 'toggleDevTools' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Terminal',
      submenu: [
        { label: 'Clear', accelerator: 'Cmd+K', click: () => send('clear-terminal') },
      ],
    },
  ]));

  mainWindow.on('closed', () => { mainWindow = null; });
}

function send(channel, ...args) {
  if (mainWindow) mainWindow.webContents.send(channel, ...args);
}

// ── PTY ───────────────────────────────────────────────────────────────────────
function setupPTY() {
  const pty = require('node-pty');

  ipcMain.handle('pty-spawn', (_e, { cols, rows }) => {
    if (ptyProcess) { try { ptyProcess.kill(); } catch (_) {} }

    // When launched from Finder, env is minimal. Ensure shell + PATH exist.
    const shell = process.env.SHELL || '/bin/zsh';
    const defaultPath = '/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin';
    const env = {
      ...process.env,
      SHELL: shell,
      PATH: process.env.PATH || defaultPath,
      HOME: os.homedir(),
      SHELLBUDDY_DIR: SB_DIR,
      TERM: 'xterm-256color',
      COLORTERM: 'truecolor',
    };

    ptyProcess = pty.spawn(shell, ['--login'], {
      name: 'xterm-256color',
      cols: cols || 80,
      rows: rows || 24,
      cwd: os.homedir(),
      env,
    });

    ptyProcess.onData((data) => send('pty-data', data));
    ptyProcess.onExit(({ exitCode }) => send('pty-exit', exitCode));
    return ptyProcess.pid;
  });

  ipcMain.on('pty-write', (_e, data) => { if (ptyProcess) ptyProcess.write(data); });
  ipcMain.on('pty-resize', (_e, { cols, rows }) => { if (ptyProcess) ptyProcess.resize(cols, rows); });
  ipcMain.on('pty-kill', () => { if (ptyProcess) ptyProcess.kill(); });
}

// ── Stats ─────────────────────────────────────────────────────────────────────
function setupStats() {
  let prevIdle = 0, prevTotal = 0;

  ipcMain.handle('stats-collect', () => {
    const r = {};

    // CPU
    try {
      const cpus = os.cpus();
      let idle = 0, total = 0;
      for (const c of cpus) {
        for (const t in c.times) total += c.times[t];
        idle += c.times.idle;
      }
      idle /= cpus.length; total /= cpus.length;
      if (prevTotal > 0) {
        const d = total - prevTotal;
        r.cpu = d > 0 ? Math.round((1 - (idle - prevIdle) / d) * 100) : 0;
      }
      prevIdle = idle; prevTotal = total;
    } catch (_) {}

    // RAM
    try { r.ram = Math.round(((os.totalmem() - os.freemem()) / os.totalmem()) * 100); } catch (_) {}

    // GPU
    try {
      const out = execSync("ioreg -r -d 1 -c IOAccelerator 2>/dev/null | grep '\"Device Utilization %\"' | head -1", { encoding: 'utf-8', timeout: 1000 });
      const m = out.match(/= (\d+)/);
      r.gpu = m ? parseInt(m[1], 10) : 0;
    } catch (_) { r.gpu = null; }

    // Git (throttled — only refresh every 15s, cache in closure)
    try {
      const branch = execSync('git branch --show-current 2>/dev/null', { encoding: 'utf-8', timeout: 1000, cwd: os.homedir() }).trim();
      r.git = { branch, dirty: false };
      if (branch) {
        const s = execSync('git status --porcelain 2>/dev/null | head -1', { encoding: 'utf-8', timeout: 1000, cwd: os.homedir() }).trim();
        r.git.dirty = s.length > 0;
      }
    } catch (_) { r.git = null; }

    return r;
  });
}

// ── Config & Shell Integration ────────────────────────────────────────────────
function setupConfig() {
  ipcMain.handle('config-read', () => {
    try { return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8')); } catch (_) { return {}; }
  });
  ipcMain.handle('config-write', (_e, cfg) => {
    if (!fs.existsSync(SB_DIR)) fs.mkdirSync(SB_DIR, { recursive: true });
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(cfg, null, 2));
    return true;
  });
  ipcMain.handle('sb-dir', () => SB_DIR);
  ipcMain.handle('check-setup', () => {
    return fs.existsSync(CONFIG_FILE) && fs.existsSync(path.join(SB_DIR, 'hint_daemon.py'));
  });
  ipcMain.handle('shell-is-installed', () => shellIntegration.isInstalled());
  ipcMain.handle('shell-install', () => shellIntegration.install(SB_DIR));
  ipcMain.handle('shell-uninstall', () => shellIntegration.uninstall());
}

// ── Hints Watcher ─────────────────────────────────────────────────────────────
function watchHints() {
  if (!fs.existsSync(SB_DIR)) fs.mkdirSync(SB_DIR, { recursive: true });

  const push = () => {
    if (!mainWindow || !fs.existsSync(HINTS_FILE)) return;
    try { send('hints-update', fs.readFileSync(HINTS_FILE, 'utf-8')); } catch (_) {}
  };

  push();
  let debounce = null;
  try {
    hintsWatcher = fs.watch(HINTS_FILE, () => { clearTimeout(debounce); debounce = setTimeout(push, 200); });
  } catch (_) {
    hintsPoller = setInterval(push, 3000);
  }
}

// ── Daemon ────────────────────────────────────────────────────────────────────
function startDaemon() {
  const py = findPython(resourcePath());
  if (!py) { console.error('shellbuddy: Python not found'); return; }
  daemon = new DaemonManager({ pythonPath: py, daemonScript: resourcePath('scripts', 'hint_daemon.py'), sbDir: SB_DIR });
  daemon.start();
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  setupPTY();
  setupStats();
  setupConfig();
  createWindow();
  startDaemon();
  watchHints();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => {
  if (daemon) daemon.stop();
  if (ptyProcess) { try { ptyProcess.kill(); } catch (_) {} }
  if (hintsWatcher) hintsWatcher.close();
  if (hintsPoller) clearInterval(hintsPoller);
  app.quit();
});

app.on('before-quit', () => {
  if (daemon) daemon.stop();
  if (ptyProcess) { try { ptyProcess.kill(); } catch (_) {} }
});
