/**
 * ShellBuddy — daemon.js
 *
 * Manages the hint_daemon.py lifecycle: start, stop, health check.
 * Works with both bundled Python (inside .app) and system Python.
 */

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

class DaemonManager {
  constructor({ pythonPath, daemonScript, sbDir }) {
    this.pythonPath = pythonPath;
    this.daemonScript = daemonScript;
    this.sbDir = sbDir;
    this.pidFile = path.join(sbDir, 'daemon.pid');
    this.logFile = path.join(sbDir, 'daemon.log');
    this.process = null;
  }

  /** Check if daemon is already running (from PID file). */
  isRunning() {
    if (!fs.existsSync(this.pidFile)) return false;
    try {
      const pid = parseInt(fs.readFileSync(this.pidFile, 'utf-8').trim(), 10);
      if (isNaN(pid)) return false;
      process.kill(pid, 0); // signal 0 = check if alive
      return true;
    } catch (_) {
      // Process not running — stale PID file
      this._cleanPid();
      return false;
    }
  }

  /** Start the hint daemon if not already running. */
  start() {
    if (this.isRunning()) {
      console.log('shellbuddy: daemon already running');
      return;
    }

    // Ensure sbDir exists
    if (!fs.existsSync(this.sbDir)) {
      fs.mkdirSync(this.sbDir, { recursive: true });
    }

    // Copy daemon files to sbDir if not present (first-run from .app)
    this._ensureFiles();

    const logFd = fs.openSync(this.logFile, 'a');
    const daemonPath = path.join(this.sbDir, 'hint_daemon.py');

    this.process = spawn(this.pythonPath, [daemonPath], {
      cwd: this.sbDir,
      env: {
        ...process.env,
        SHELLBUDDY_DIR: this.sbDir,
        PYTHONPATH: this.sbDir,
      },
      stdio: ['ignore', logFd, logFd],
      detached: true,
    });

    this.process.unref();
    fs.writeFileSync(this.pidFile, String(this.process.pid));
    fs.closeSync(logFd);

    console.log(`shellbuddy: daemon started (PID ${this.process.pid})`);
  }

  /** Stop the daemon. */
  stop() {
    if (!fs.existsSync(this.pidFile)) return;
    try {
      const pid = parseInt(fs.readFileSync(this.pidFile, 'utf-8').trim(), 10);
      if (!isNaN(pid)) {
        process.kill(pid, 'SIGTERM');
        console.log(`shellbuddy: daemon stopped (PID ${pid})`);
      }
    } catch (_) {
      // Already dead
    }
    this._cleanPid();
  }

  /** Copy essential files from app resources to ~/.shellbuddy/ on first run. */
  _ensureFiles() {
    const resourceBase = path.dirname(this.daemonScript);

    const filesToCopy = [
      { src: this.daemonScript, dst: path.join(this.sbDir, 'hint_daemon.py') },
      { src: path.join(resourceBase, '..', 'kb_engine.py'), dst: path.join(this.sbDir, 'kb_engine.py') },
      { src: path.join(resourceBase, '..', 'kb.json'), dst: path.join(this.sbDir, 'kb.json') },
    ];

    // Copy backends directory
    const backendsDir = path.join(resourceBase, '..', 'backends');
    const dstBackends = path.join(this.sbDir, 'backends');
    if (fs.existsSync(backendsDir) && !fs.existsSync(dstBackends)) {
      fs.mkdirSync(dstBackends, { recursive: true });
      for (const f of fs.readdirSync(backendsDir)) {
        fs.copyFileSync(path.join(backendsDir, f), path.join(dstBackends, f));
      }
    }

    // Copy scripts
    const scriptsDir = path.join(resourceBase);
    const dstScripts = this.sbDir; // scripts go directly into sbDir
    for (const { src, dst } of filesToCopy) {
      if (fs.existsSync(src) && !fs.existsSync(dst)) {
        fs.copyFileSync(src, dst);
      }
    }

    // Copy shell scripts
    const shellScripts = ['log_cmd.sh', 'show_hints.sh', 'show_stats.sh', 'start_daemon.sh', 'toggle_hints_pane.sh'];
    for (const script of shellScripts) {
      const src = path.join(scriptsDir, script);
      const dst = path.join(this.sbDir, script);
      if (fs.existsSync(src) && !fs.existsSync(dst)) {
        fs.copyFileSync(src, dst);
      }
    }
  }

  _cleanPid() {
    try { fs.unlinkSync(this.pidFile); } catch (_) { /* ok */ }
  }
}

module.exports = { DaemonManager };
