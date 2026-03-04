/**
 * ShellBuddy — preload.js
 *
 * Exposes a safe API to the renderer via contextBridge.
 * The renderer never has direct access to Node.js APIs.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('shellbuddy', {
  // ── Terminal PTY ─────────────────────────────────────────────────────────
  pty: {
    spawn: (opts) => ipcRenderer.invoke('pty-spawn', opts),
    write: (data) => ipcRenderer.send('pty-write', data),
    resize: (cols, rows) => ipcRenderer.send('pty-resize', { cols, rows }),
    kill: () => ipcRenderer.send('pty-kill'),
    onData: (cb) => {
      const listener = (_event, data) => cb(data);
      ipcRenderer.on('pty-data', listener);
      return () => ipcRenderer.removeListener('pty-data', listener);
    },
    onExit: (cb) => {
      const listener = (_event, code) => cb(code);
      ipcRenderer.on('pty-exit', listener);
      return () => ipcRenderer.removeListener('pty-exit', listener);
    },
  },

  // ── Hints ────────────────────────────────────────────────────────────────
  hints: {
    onUpdate: (cb) => {
      const listener = (_event, content) => cb(content);
      ipcRenderer.on('hints-update', listener);
      return () => ipcRenderer.removeListener('hints-update', listener);
    },
  },

  // ── Stats (collected in main process) ────────────────────────────────────
  stats: {
    collect: () => ipcRenderer.invoke('stats-collect'),
  },

  // ── Config ───────────────────────────────────────────────────────────────
  config: {
    read: () => ipcRenderer.invoke('config-read'),
    write: (config) => ipcRenderer.invoke('config-write', config),
    checkSetup: () => ipcRenderer.invoke('check-setup'),
    getSbDir: () => ipcRenderer.invoke('sb-dir'),
  },

  // ── Shell Integration (.zshrc patching) ──────────────────────────────────
  shellIntegration: {
    isInstalled: () => ipcRenderer.invoke('shell-is-installed'),
    install: () => ipcRenderer.invoke('shell-install'),
    uninstall: () => ipcRenderer.invoke('shell-uninstall'),
  },

  // ── Menu Events ──────────────────────────────────────────────────────────
  on: (channel, cb) => {
    const allowed = ['show-settings', 'toggle-hints', 'toggle-stats', 'clear-terminal'];
    if (allowed.includes(channel)) {
      const listener = () => cb();
      ipcRenderer.on(channel, listener);
      return () => ipcRenderer.removeListener(channel, listener);
    }
  },
});
