#!/usr/bin/env bash
# shellbuddy — bundle-python.sh
#
# Downloads a standalone Python 3.12 framework and strips it down
# for embedding inside the ShellBuddy.app bundle.
#
# Usage: ./scripts/bundle-python.sh [output_dir]
#
# Output: output_dir/python/ containing a minimal Python 3.12 install
# with pycryptodome pre-installed (~30MB total).

set -euo pipefail

PYTHON_VERSION="3.12.8"
PYTHON_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-macos11.pkg"
OUTPUT_DIR="${1:-$(dirname "$0")/../python}"

C_CYAN='\033[1;36m'
C_GREEN='\033[0;32m'
C_DIM='\033[2m'
C_RESET='\033[0m'
info()  { printf "  ${C_CYAN}->  ${C_RESET}%s\n" "$*"; }
ok()    { printf "  ${C_GREEN} +  ${C_RESET}%s\n" "$*"; }

TMPDIR_WORK="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_WORK"' EXIT

# ── Step 1: Download Python framework ─────────────────────────────────────
info "Downloading Python ${PYTHON_VERSION} framework..."
PKG_FILE="${TMPDIR_WORK}/python.pkg"
curl -fsSL "$PYTHON_URL" -o "$PKG_FILE"
ok "Downloaded $(du -h "$PKG_FILE" | awk '{print $1}')"

# ── Step 2: Extract framework from .pkg ──────────────────────────────────
info "Extracting framework..."
EXTRACT_DIR="${TMPDIR_WORK}/extracted"
pkgutil --expand "$PKG_FILE" "$EXTRACT_DIR"

# Find the framework payload
PAYLOAD=$(find "$EXTRACT_DIR" -name 'Payload' -path '*/Python_Framework*' | head -1)
if [[ -z "$PAYLOAD" ]]; then
    echo "Error: Could not find Python framework payload in .pkg"
    exit 1
fi

FRAMEWORK_DIR="${TMPDIR_WORK}/framework"
mkdir -p "$FRAMEWORK_DIR"
cd "$FRAMEWORK_DIR"
cat "$PAYLOAD" | gunzip | cpio -id 2>/dev/null || true
ok "Extracted framework"

# ── Step 3: Set up minimal Python in output dir ───────────────────────────
info "Building minimal Python installation..."
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/bin" "$OUTPUT_DIR/lib"

# Find the Python.framework
FW_ROOT=$(find "$FRAMEWORK_DIR" -name 'Python.framework' -type d | head -1)
PY_VER_SHORT="3.12"

if [[ -n "$FW_ROOT" ]]; then
    # Copy the interpreter binary
    cp "$FW_ROOT/Versions/${PY_VER_SHORT}/bin/python${PY_VER_SHORT}" "$OUTPUT_DIR/bin/python3"
    chmod +x "$OUTPUT_DIR/bin/python3"
    ln -sf python3 "$OUTPUT_DIR/bin/python3.12"

    # Copy the standard library
    cp -R "$FW_ROOT/Versions/${PY_VER_SHORT}/lib/python${PY_VER_SHORT}" "$OUTPUT_DIR/lib/"

    # Copy the dylib
    cp "$FW_ROOT/Versions/${PY_VER_SHORT}/lib/libpython${PY_VER_SHORT}.dylib" "$OUTPUT_DIR/lib/" 2>/dev/null || true
else
    echo "Error: Python.framework not found in extracted package"
    exit 1
fi
ok "Python binary + stdlib copied"

# ── Step 4: Strip unnecessary modules (~saves 50MB) ──────────────────────
info "Stripping unnecessary modules..."
PY_LIB="$OUTPUT_DIR/lib/python${PY_VER_SHORT}"

# Remove test suites
rm -rf "$PY_LIB/test" "$PY_LIB/tests" "$PY_LIB/unittest/test"
rm -rf "$PY_LIB/lib2to3/tests" "$PY_LIB/distutils/tests"

# Remove unnecessary modules
rm -rf "$PY_LIB/tkinter" "$PY_LIB/turtledemo" "$PY_LIB/turtle.py"
rm -rf "$PY_LIB/idlelib" "$PY_LIB/idle_test"
rm -rf "$PY_LIB/ensurepip" "$PY_LIB/venv"
rm -rf "$PY_LIB/pydoc_data" "$PY_LIB/pydoc.py"
rm -rf "$PY_LIB/lib2to3"

# Remove __pycache__ (we'll regenerate what we need)
find "$OUTPUT_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

# Remove .pyc files
find "$OUTPUT_DIR" -name '*.pyc' -delete 2>/dev/null || true

ok "Stripped $(du -sh "$PY_LIB" | awk '{print $1}') stdlib"

# ── Step 5: Install pycryptodome ──────────────────────────────────────────
info "Installing pycryptodome..."
"$OUTPUT_DIR/bin/python3" -m pip install --target="$PY_LIB/site-packages" \
    pycryptodome --quiet --no-warn-script-location 2>/dev/null || {
    # If pip isn't available, try downloading wheel directly
    info "pip not available, downloading pycryptodome wheel..."
    WHEEL_URL="https://files.pythonhosted.org/packages/cp312/p/pycryptodome/pycryptodome-3.21.0-cp35-abi3-macosx_10_9_universal2.whl"
    WHEEL_FILE="${TMPDIR_WORK}/pycryptodome.whl"
    curl -fsSL "$WHEEL_URL" -o "$WHEEL_FILE" 2>/dev/null || true
    if [[ -f "$WHEEL_FILE" ]]; then
        mkdir -p "$PY_LIB/site-packages"
        cd "$PY_LIB/site-packages"
        python3 -m zipfile -e "$WHEEL_FILE" . 2>/dev/null || unzip -q "$WHEEL_FILE" 2>/dev/null || true
    fi
}
ok "pycryptodome installed"

# ── Step 6: Report ────────────────────────────────────────────────────────
TOTAL_SIZE=$(du -sh "$OUTPUT_DIR" | awk '{print $1}')
info "Output: $OUTPUT_DIR ($TOTAL_SIZE)"
info "Binary: $OUTPUT_DIR/bin/python3"
ok "Python ${PYTHON_VERSION} bundled successfully"
