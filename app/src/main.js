/**
 * ShellBuddy — Electron main process
 *
 * Manages the application window, spawns zsh via node-pty,
 * starts the hint daemon, and bridges IPC between renderer panels.
 */

const { app, BrowserWindow, ipcMain, Menu } = require('electron');
const path = require('path');
const os = require('os');
const fs = require('fs');
const { spawn } = require('child_process');

const { DaemonManager } = require('./utils/daemon');
const { findPython } = require('./utils/python');

// ── Paths ────────────────────────────────────────────────────────────────────
const SB_DIR = process.env.SHELLBUDDY_DIR || path.join(os.homedir(), '.shellbuddy');
const HINTS_FILE = path.join(SB_DIR, 'current_hints.txt');
const CONFIG_FILE = path.join(SB_DIR, 'config.json');

// Resource paths differ in dev vs packaged mode
function resourcePath(...parts) {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, ...parts);
  }
  return path.join(__dirname, '..', '..', ...parts);
}

let mainWindow = null;
let daemon = null;
let hintsWatcher = null;
let ptyProcess = null;

// ── Window Creation ──────────────────────────────────────────────────────────
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
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // Hide menu bar (keep system shortcuts)
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: 'ShellBuddy',
      submenu: [
        { role: 'about' },
        { type: 'separator' },
        { label: 'Settings', accelerator: 'Cmd+,', click: () => mainWindow.webContents.send('show-settings') },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' },
      ],
    },
    {
      label: 'View',
      submenu: [
        { label: 'Toggle Hints', accelerator: 'Cmd+Shift+H', click: () => mainWindow.webContents.send('toggle-hints') },
        { label: 'Toggle Stats', accelerator: 'Cmd+Shift+S', click: () => mainWindow.webContents.send('toggle-stats') },
        { type: 'separator' },
        { role: 'toggleDevTools' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Terminal',
      submenu: [
        { label: 'New Tab', accelerator: 'Cmd+T', click: () => mainWindow.webContents.send('new-tab') },
        { label: 'Clear', accelerator: 'Cmd+K', click: () => mainWindow.webContents.send('clear-terminal') },
      ],
    },
  ]));

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── Daemon Management ────────────────────────────────────────────────────────
function startDaemon() {
  const pythonPath = findPython(resourcePath());
  if (!pythonPath) {
    console.error('shellbuddy: Python not found — daemon will not start');
    return;
  }

  daemon = new DaemonManager({
    pythonPath,
    daemonScript: resourcePath('scripts', 'hint_daemon.py'),
    sbDir: SB_DIR,
  });
  daemon.start();
}

// ── Hints File Watcher ───────────────────────────────────────────────────────
function watchHints() {
  if (!fs.existsSync(path.dirname(HINTS_FILE))) {
    fs.mkdirSync(path.dirname(HINTS_FILE), { recursive: true });
  }

  const sendHints = () => {
    if (mainWindow && fs.existsSync(HINTS_FILE)) {
      try {
        const content = fs.readFileSync(HINTS_FILE, 'utf-8');
        mainWindow.webContents.send('hints-update', content);
      } catch (_) { /* file may be mid-write */ }
    }
  };

  // Initial read
  sendHints();

  // Watch for changes (debounced)
  let debounce = null;
  try {
    hintsWatcher = fs.watch(HINTS_FILE, () => {
      clearTimeout(debounce);
      debounce = setTimeout(sendHints, 200);
    });
  } catch (_) {
    // File may not exist yet — poll instead
    setInterval(sendHints, 3000);
  }
}

// ── PTY Management (via IPC) ─────────────────────────────────────────────────
function setupPtyIPC() {
  const pty = require('node-pty');

  ipcMain.handle('pty-spawn', (_event, { cols, rows }) => {
    const shell = process.env.SHELL || '/bin/zsh';
    ptyProcess = pty.spawn(shell, [], {
      name: 'xterm-256color',
      cols: cols || 80,
      rows: rows || 24,
      cwd: os.homedir(),
      env: {
        ...process.env,
        SHELLBUDDY_DIR: SB_DIR,
        TERM: 'xterm-256color',
        COLORTERM: 'truecolor',
      },
    });

    ptyProcess.onData((data) => {
      if (mainWindow) {
        mainWindow.webContents.send('pty-data', data);
      }
    });

    ptyProcess.onExit(({ exitCode }) => {
      if (mainWindow) {
        mainWindow.webContents.send('pty-exit', exitCode);
      }
    });

    return ptyProcess.pid;
  });

  ipcMain.on('pty-write', (_event, data) => {
    if (ptyProcess) ptyProcess.write(data);
  });

  ipcMain.on('pty-resize', (_event, { cols, rows }) => {
    if (ptyProcess) ptyProcess.resize(cols, rows);
  });

  ipcMain.on('pty-kill', () => {
    if (ptyProcess) ptyProcess.kill();
  });
}

// ── Config IPC ───────────────────────────────────────────────────────────────
function setupConfigIPC() {
  ipcMain.handle('config-read', () => {
    try {
      return JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf-8'));
    } catch (_) {
      return {};
    }
  });

  ipcMain.handle('config-write', (_event, config) => {
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2));
    return true;
  });

  ipcMain.handle('sb-dir', () => SB_DIR);
  ipcMain.handle('resource-path', () => resourcePath());

  ipcMain.handle('check-setup', () => {
    return fs.existsSync(CONFIG_FILE) && fs.existsSync(path.join(SB_DIR, 'hint_daemon.py'));
  });
}

// ── App Lifecycle ────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  createWindow();
  setupPtyIPC();
  setupConfigIPC();
  startDaemon();
  watchHints();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (daemon) daemon.stop();
  if (ptyProcess) ptyProcess.kill();
  if (hintsWatcher) hintsWatcher.close();
  app.quit();
});

app.on('before-quit', () => {
  if (daemon) daemon.stop();
  if (ptyProcess) ptyProcess.kill();
});
