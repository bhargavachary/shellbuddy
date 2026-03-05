/**
 * ShellBuddy — preload.js
 *
 * With contextIsolation: false, this shares the renderer's window object.
 * Sets up window.shellbuddy as the IPC bridge.
 */

const { ipcRenderer } = require('electron');

window.shellbuddy = {
  pty: {
    spawn: (opts) => ipcRenderer.invoke('pty-spawn', opts),
    write: (data) => ipcRenderer.send('pty-write', data),
    resize: (cols, rows) => ipcRenderer.send('pty-resize', { cols, rows }),
    kill: () => ipcRenderer.send('pty-kill'),
    onData: (cb) => { ipcRenderer.on('pty-data', (_e, d) => cb(d)); },
    onExit: (cb) => { ipcRenderer.on('pty-exit', (_e, code) => cb(code)); },
  },
  hints: {
    onUpdate: (cb) => { ipcRenderer.on('hints-update', (_e, c) => cb(c)); },
  },
  stats: {
    collect: () => ipcRenderer.invoke('stats-collect'),
  },
  config: {
    read: () => ipcRenderer.invoke('config-read'),
    write: (cfg) => ipcRenderer.invoke('config-write', cfg),
    checkSetup: () => ipcRenderer.invoke('check-setup'),
    getSbDir: () => ipcRenderer.invoke('sb-dir'),
  },
  shellIntegration: {
    isInstalled: () => ipcRenderer.invoke('shell-is-installed'),
    install: () => ipcRenderer.invoke('shell-install'),
    uninstall: () => ipcRenderer.invoke('shell-uninstall'),
  },
  on: (channel, cb) => {
    const ok = ['show-settings', 'toggle-hints', 'toggle-stats', 'clear-terminal'];
    if (ok.includes(channel)) ipcRenderer.on(channel, () => cb());
  },
};
