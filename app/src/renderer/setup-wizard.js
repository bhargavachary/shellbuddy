/**
 * ShellBuddy — setup-wizard.js
 *
 * First-run setup wizard. Handles backend selection, shell integration,
 * and initial config.json creation.
 */

class SetupWizard {
  constructor() {
    this.wizard = document.getElementById('setup-wizard');
    this.finishBtn = document.getElementById('wizard-finish');
    this._onComplete = null;
  }

  init(onComplete) {
    this._onComplete = onComplete;
    this.finishBtn.addEventListener('click', () => this._finish());
  }

  async shouldShow() {
    const isSetup = await window.shellbuddy.config.checkSetup();
    return !isSetup;
  }

  show() {
    this.wizard.classList.remove('hidden');
    document.getElementById('app').classList.add('hidden');
  }

  async _finish() {
    const backend = document.querySelector('input[name="backend"]:checked')?.value || 'ollama';
    const patchZshrc = document.getElementById('patch-zshrc')?.checked ?? true;

    // Build config
    const config = {
      hint_backend: backend,
      tip_backend: backend,
      hint_model: this._defaultModel(backend),
      tip_model: this._defaultTipModel(backend),
      hint_interval_secs: 5,
      ai_throttle_secs: 15,
      rule_cooldown_secs: 120,
      enable_post_mortem: true,
      enable_idle_tips: true,
    };

    if (backend === 'copilot') {
      config.hint_model_chain = ['gpt-5-mini', 'raptor-mini', 'gpt-4.1'];
    }
    if (backend === 'ollama') {
      config.ollama_url = 'http://localhost:11434';
    }

    // Save config
    await window.shellbuddy.config.write(config);

    // Patch .zshrc if requested
    if (patchZshrc) {
      // This will be handled by shell-integration.js via IPC
      // For now, the daemon start in main.js handles file copying
    }

    // Hide wizard, show app
    this.wizard.classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');

    if (this._onComplete) this._onComplete();
  }

  _defaultModel(backend) {
    switch (backend) {
      case 'copilot': return 'gpt-5-mini';
      case 'claude': return 'claude-haiku-4-5-20251001';
      case 'ollama': return 'qwen3:4b';
      case 'openai': return 'gpt-4o-mini';
      default: return '';
    }
  }

  _defaultTipModel(backend) {
    switch (backend) {
      case 'copilot': return 'gpt-4.1';
      case 'claude': return 'claude-sonnet-4-6';
      case 'ollama': return 'qwen3:8b';
      case 'openai': return 'gpt-4o';
      default: return '';
    }
  }
}

window.SetupWizard = SetupWizard;
