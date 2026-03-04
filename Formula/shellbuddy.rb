class Shellbuddy < Formula
  desc "AI-powered ambient shell hints, contextual tips and developer intelligence"
  homepage "https://github.com/bhargavachary/shellbuddy"

  # ── Stable release ──────────────────────────────────────────────────────────
  # Update url + sha256 on every release.
  # Run `shasum -a 256 shellbuddy-vX.Y.Z.tar.gz` to get the hash.
  url "https://github.com/bhargavachary/shellbuddy/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "PLACEHOLDER_SHA256_UPDATE_ON_EACH_RELEASE"
  license "MIT"
  version "1.0.0"

  # ── HEAD install (for development) ──────────────────────────────────────────
  head "https://github.com/bhargavachary/shellbuddy.git", branch: "main"

  # ── Runtime dependencies ─────────────────────────────────────────────────────
  # Python 3.12 for the hint daemon + KB engine.
  # tmux for the persistent stats + hints panes.
  depends_on "python@3.12"
  depends_on "tmux"
  depends_on :macos  # macOS-only (used: ioreg, security keychain, VS Code sqlite)

  # pycryptodome is only needed for the Copilot backend.
  # We install it proactively — it's small (~2MB) and avoids a confusing error.
  resource "pycryptodome" do
    url "https://files.pythonhosted.org/packages/source/p/pycryptodome/pycryptodome-3.21.0.tar.gz"
    sha256 "b09b9f5ee72d9cefcac7c9a3f8c1a05bceefa98b2f6b8e0ba0c9bffd7ed88efa"
  end

  def install
    share_dir = share/"shellbuddy"

    # Install all source files into share/shellbuddy/
    # The installer (install.sh) uses REPO_DIR = dirname($0), so this layout is
    # identical to running `./install.sh` from a cloned repo.
    share_dir.install "install.sh"
    share_dir.install "uninstall.sh"
    share_dir.install "kb_engine.py"
    share_dir.install "kb.json"
    share_dir.install "backends"
    share_dir.install "config"

    # Install scripts keeping the scripts/ subdirectory
    (share_dir/"scripts").install Dir["scripts/*"]

    # Install pycryptodome into a private vendor directory
    venv = virtualenv_create(share_dir/"vendor", Formula["python@3.12"].opt_bin/"python3.12")
    venv.pip_install resource("pycryptodome")

    # Create the `shellbuddy` entry point in bin/
    # When the user runs `shellbuddy`, it execs install.sh from the share dir.
    (bin/"shellbuddy").write <<~EOS
      #!/usr/bin/env zsh
      # shellbuddy — Homebrew entry point
      # Delegtes to install.sh, which knows REPO_DIR = its own directory (share/shellbuddy).
      exec zsh "#{share_dir}/install.sh" "$@"
    EOS
    chmod 0755, bin/"shellbuddy"
  end

  def caveats
    <<~EOS
      ShellBuddy requires a one-time setup to patch your ~/.zshrc and ~/.tmux.conf.
      Run the wizard:

        shellbuddy

      For AI-powered hints, you also need a running AI backend:
        • Ollama (local, free):   brew install ollama && ollama serve
        • GitHub Copilot:         VS Code with Copilot extension logged in
        • Claude / OpenAI:        set ANTHROPIC_API_KEY / OPENAI_API_KEY

      To uninstall:
        shellbuddy-uninstall
        brew uninstall shellbuddy
    EOS
  end

  def post_install
    # Uninstall shim
    (bin/"shellbuddy-uninstall").write <<~EOS
      #!/usr/bin/env zsh
      exec zsh "#{share}/shellbuddy/uninstall.sh" "$@"
    EOS
    chmod 0755, bin/"shellbuddy-uninstall"

    ohai "ShellBuddy installed!"
    ohai ""
    ohai "Run the interactive setup wizard:"
    ohai "  shellbuddy"
    ohai ""
    ohai "Or accept all defaults (Ollama backend):"
    ohai "  shellbuddy --yes"
    ohai ""
    ohai "After setup, open a new tmux session and zsh shell."
    ohai "Docs: #{homepage}/blob/main/USAGE.md"
  end

  test do
    # Smoke test: kb.json loads as valid JSON
    system Formula["python@3.12"].opt_bin/"python3.12",
           "-c", "import json; d=json.load(open('#{share}/shellbuddy/kb.json')); assert len(d) > 1000"

    # Smoke test: kb_engine.py parses without error
    system Formula["python@3.12"].opt_bin/"python3.12",
           "-c", "import sys; sys.path.insert(0, '#{share}/shellbuddy'); import kb_engine"
  end
end
