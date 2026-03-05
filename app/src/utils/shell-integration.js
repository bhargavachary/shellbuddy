/**
 * ShellBuddy — shell-integration.js
 *
 * Handles .zshrc patching for command logging (preexec hook).
 * The embedded terminal injects hooks automatically, but for the user's
 * other terminals (iTerm2, Terminal.app) to also log commands, we need
 * to patch .zshrc.
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const MARKER_START = '# ══ SHELLBUDDY ══';
const MARKER_END = '# ══ END SHELLBUDDY ══';
// Also detect the marker used by install.sh (# ── shellbuddy ──) to avoid double-patching
const MARKER_LEGACY = '# ── shellbuddy';

/**
 * Generate the zshrc block that enables command logging.
 * @param {string} sbDir - Path to ~/.shellbuddy
 */
function generateZshrcBlock(sbDir) {
  return `${MARKER_START}
export SHELLBUDDY_DIR="${sbDir}"
function _shellbuddy_log() { SHELLBUDDY_DIR="$SHELLBUDDY_DIR" zsh "$SHELLBUDDY_DIR/log_cmd.sh" "$1" }
autoload -Uz add-zsh-hook
add-zsh-hook preexec _shellbuddy_log
(SHELLBUDDY_DIR="$SHELLBUDDY_DIR" source "$SHELLBUDDY_DIR/start_daemon.sh" &>/dev/null &)
function /tip() {
  local q="$*" qf="$SHELLBUDDY_DIR/tip_query.txt" rf="$SHELLBUDDY_DIR/tip_result.txt"
  [[ -z "$q" ]] && q="help"
  rm -f "$rf"; echo "$q" > "$qf"
  local i=0; while [[ ! -f "$rf" ]] && (( i++ < 120 )); do sleep 0.5; done
  [[ -f "$rf" ]] && cat "$rf" || echo "shellbuddy: timeout waiting for response"
}
function /configure() { /tip configure "$@"; }
${MARKER_END}`;
}

/**
 * Check if .zshrc already has a ShellBuddy block (either format).
 */
function isInstalled() {
  const zshrc = path.join(os.homedir(), '.zshrc');
  if (!fs.existsSync(zshrc)) return false;
  const content = fs.readFileSync(zshrc, 'utf-8');
  // Detect both the app-wizard block and the install.sh block
  return content.includes(MARKER_START) || content.includes(MARKER_LEGACY);
}

/**
 * Add or update the ShellBuddy block in .zshrc.
 * @param {string} sbDir
 */
function install(sbDir) {
  const zshrc = path.join(os.homedir(), '.zshrc');
  let content = fs.existsSync(zshrc) ? fs.readFileSync(zshrc, 'utf-8') : '';

  // If the full install.sh block is already present, don't add a second block.
  // The install.sh block is more complete (contains all sb/hints-* functions).
  if (content.includes(MARKER_LEGACY)) {
    return false; // already handled by install.sh
  }

  // Remove existing app-wizard block if present
  const startIdx = content.indexOf(MARKER_START);
  const endIdx = content.indexOf(MARKER_END);
  if (startIdx !== -1 && endIdx !== -1) {
    content = content.slice(0, startIdx) + content.slice(endIdx + MARKER_END.length + 1);
  }

  // Append new block
  content = content.trimEnd() + '\n\n' + generateZshrcBlock(sbDir) + '\n';
  fs.writeFileSync(zshrc, content);
  return true;
}

/**
 * Remove the ShellBuddy block from .zshrc (app-wizard format only).
 * The install.sh block is left for uninstall.sh to handle.
 */
function uninstall() {
  const zshrc = path.join(os.homedir(), '.zshrc');
  if (!fs.existsSync(zshrc)) return false;
  let content = fs.readFileSync(zshrc, 'utf-8');
  const startIdx = content.indexOf(MARKER_START);
  const endIdx = content.indexOf(MARKER_END);
  if (startIdx === -1 || endIdx === -1) return false;
  content = content.slice(0, startIdx) + content.slice(endIdx + MARKER_END.length + 1);
  fs.writeFileSync(zshrc, content.trimEnd() + '\n');
  return true;
}

module.exports = { isInstalled, install, uninstall, generateZshrcBlock };
