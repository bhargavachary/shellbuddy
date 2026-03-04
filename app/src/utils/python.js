/**
 * ShellBuddy — python.js
 *
 * Locates a usable Python 3 interpreter.
 * Priority: bundled (inside .app) > conda > system python3.
 */

const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

/**
 * Find the best available Python 3 interpreter.
 * @param {string} resourceDir - Path to app resources (for bundled Python)
 * @returns {string|null} Absolute path to python3, or null if not found.
 */
function findPython(resourceDir) {
  // 1. Bundled Python inside the .app
  const bundled = path.join(resourceDir, 'python', 'bin', 'python3');
  if (fs.existsSync(bundled)) {
    return bundled;
  }

  // 2. Conda environment
  const condaPrefix = process.env.CONDA_PREFIX;
  if (condaPrefix) {
    const condaPython = path.join(condaPrefix, 'bin', 'python3');
    if (fs.existsSync(condaPython)) return condaPython;
  }

  // 3. System python3 (via PATH)
  try {
    const systemPython = execSync('which python3', { encoding: 'utf-8' }).trim();
    if (systemPython && fs.existsSync(systemPython)) {
      // Verify it's Python 3.9+
      const version = execSync(`${systemPython} -c "import sys; print(sys.version_info[:2])"`, {
        encoding: 'utf-8',
      }).trim();
      const match = version.match(/\((\d+), (\d+)\)/);
      if (match) {
        const [, major, minor] = match.map(Number);
        if (major >= 3 && minor >= 9) return systemPython;
      }
    }
  } catch (_) {
    // python3 not in PATH
  }

  return null;
}

module.exports = { findPython };
