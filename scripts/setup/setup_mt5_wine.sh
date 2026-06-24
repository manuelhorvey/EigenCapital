#!/usr/bin/env bash
# ── MT5 Wine Setup Script ──────────────────────────────────────────────────
# Installs Wine, sets up a Wine prefix with Python + MetaTrader5 package,
# and provides instructions for manual MT5 terminal installation.
#
# Usage:
#   chmod +x scripts/setup_mt5_wine.sh
#   sudo ./scripts/setup_mt5_wine.sh
#
# After running this script, you must manually:
#   1. Download and install MT5 terminal
#   2. Log in to your Exness demo account
#   3. Start the bridge server
# ────────────────────────────────────────────────────────────────────────────

set -euo pipefail

WINE_PREFIX="${WINE_PREFIX:-$HOME/.wine_mt5}"
MT5_DIR="$WINE_PREFIX/drive_c/Program Files/MetaTrader 5"
BRIDGE_SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/paper_trading/ops/mt5_bridge.py"
BIN_DIR="$HOME/.local/bin"

echo "=== MT5 Wine Setup ==="
echo "Wine prefix: $WINE_PREFIX"

# ── Step 1: Install system dependencies ────────────────────────────────────
echo ">>> Installing Wine and Xvfb..."
if command -v dnf &>/dev/null; then
    sudo dnf install -y wine xorg-x11-server-Xvfb winetricks
elif command -v apt-get &>/dev/null; then
    sudo dpkg --add-architecture i386
    sudo apt-get update
    sudo apt-get install -y wine32 wine64 xvfb winetricks
else
    echo "WARNING: Unsupported package manager. Install Wine manually."
fi

# ── Step 2: Create and configure Wine prefix ───────────────────────────────
echo ">>> Creating Wine prefix at $WINE_PREFIX..."
export WINEPREFIX="$WINE_PREFIX"
export WINEARCH="win64"

if [ ! -f "$WINE_PREFIX/system.reg" ]; then
    wineboot -u 2>/dev/null || true
    echo "Waiting for Wineboot..."
    sleep 3
fi

# Install core dependencies via winetricks
echo ">>> Installing core fonts and VC++ runtimes..."
winetricks -q corefonts vcrun2022 2>/dev/null || true

# ── Step 3: Install Python in Wine ─────────────────────────────────────────
echo ">>> Installing Python in Wine..."
PYTHON_VERSION="3.12"
PYTHON_INSTALLER="python-${PYTHON_VERSION}-amd64.exe"
PYTHON_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/${PYTHON_INSTALLER}"

if ! wine cmd /c "python --version" 2>/dev/null; then
    echo "Downloading Python ${PYTHON_VERSION}..."
    wget -q "$PYTHON_URL" -O "/tmp/$PYTHON_INSTALLER"
    echo "Installing Python (silent)..."
    wine "/tmp/$PYTHON_INSTALLER" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
    sleep 3
    rm "/tmp/$PYTHON_INSTALLER"
fi

# ── Step 4: Install MetaTrader5 Python package ────────────────────────────
echo ">>> Installing MetaTrader5 Python package in Wine..."
wine python -m pip install --upgrade pip
wine python -m pip install MetaTrader5

# Verify installation
echo ""
echo ">>> Verifying MetaTrader5..."
wine python -c "import MetaTrader5; print(f'MetaTrader5 version: {MetaTrader5.__version__}')" 2>/dev/null || {
    echo "WARNING: MetaTrader5 import failed."
    echo "This usually means the MT5 terminal is not yet installed."
}

# ── Step 5: Create launcher scripts ────────────────────────────────────────
mkdir -p "$BIN_DIR"

cat > "$BIN_DIR/mt5-bridge" << 'BRIDGE_LAUNCHER'
#!/usr/bin/env bash
# Launch the MT5 bridge server under Wine
WINE_PREFIX="${WINE_PREFIX:-$HOME/.wine_mt5}"
PORT="${MT5_BRIDGE_PORT:-9876}"
ACCOUNT="${MT5_ACCOUNT:-}"
PASSWORD="${MT5_PASSWORD:-}"
SERVER="${MT5_SERVER:-}"

ARGS=""
if [ -n "$ACCOUNT" ]; then ARGS="$ARGS --account $ACCOUNT"; fi
if [ -n "$PASSWORD" ]; then ARGS="$ARGS --password $PASSWORD"; fi
if [ -n "$SERVER" ]; then ARGS="$ARGS --server $SERVER"; fi

export WINEPREFIX="$WINE_PREFIX"
BRIDGE_SCRIPT="$(dirname "$0")/../../paper_trading/ops/mt5_bridge.py"

if command -v xvfb-run &>/dev/null; then
    exec xvfb-run wine python "$BRIDGE_SCRIPT" $ARGS
else
    exec wine python "$BRIDGE_SCRIPT" $ARGS
fi
BRIDGE_LAUNCHER
chmod +x "$BIN_DIR/mt5-bridge"

cat > "$BIN_DIR/mt5-terminal" << 'TERM_LAUNCHER'
#!/usr/bin/env bash
# Launch the MT5 terminal GUI
WINE_PREFIX="${WINE_PREFIX:-$HOME/.wine_mt5}"
export WINEPREFIX="$WINE_PREFIX"

MT5_EXE="$WINE_PREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$MT5_EXE" ]; then
    exec wine "$MT5_EXE"
else
    echo "MT5 terminal not found at: $MT5_EXE"
    echo "Please install MT5 first."
    exit 1
fi
TERM_LAUNCHER
chmod +x "$BIN_DIR/mt5-terminal"

cat > "$BIN_DIR/mt5-install" << 'INSTALL_SCRIPT'
#!/usr/bin/env bash
# Download and install the latest MT5 build
WINE_PREFIX="${WINE_PREFIX:-$HOME/.wine_mt5}"
export WINEPREFIX="$WINE_PREFIX"

MT5_URL="${MT5_DOWNLOAD_URL:-https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe}"
INSTALLER="/tmp/mt5setup.exe"

echo "Downloading MT5..."
wget -q "$MT5_URL" -O "$INSTALLER"
echo "Running MT5 installer..."
wine "$INSTALLER" /auto
echo ""
echo "MT5 installation started in silent mode."
echo "If the GUI installer appears, complete the wizard manually."
echo "After installation, launch the terminal and log into your Exness demo account."
INSTALL_SCRIPT
chmod +x "$BIN_DIR/mt5-install"

# ── Step 6: Print instructions ─────────────────────────────────────────────
cat << 'INSTRUCTIONS'

╔══════════════════════════════════════════════════════════════════════════╗
║  MT5 Setup Complete                                                     ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                         ║
║  Commands:                                                              ║
║                                                                         ║
║    mt5-install     → Download and install MT5 terminal                   ║
║    mt5-terminal    → Launch MT5 terminal GUI                             ║
║    mt5-bridge      → Start the MT5 bridge server                        ║
║                                                                         ║
║  Environment variables (add to ~/.zshrc or ~/.bashrc):                  ║
║                                                                         ║
║    export WINEPREFIX="$HOME/.wine_mt5"                                   ║
║    export MT5_ACCOUNT="your_demo_account_number"                         ║
║    export MT5_PASSWORD="your_demo_password"                              ║
║    export MT5_SERVER="Exness-MT5Trial"                                   ║
║    export PATH="$HOME/.local/bin:$PATH"                                  ║
║                                                                         ║
║  Steps to complete:                                                     ║
║                                                                         ║
║  1. Run:  mt5-install                                                   ║
║  2. Run:  mt5-terminal  (log in to your Exness demo account)            ║
║  3. Enable automated trading in MT5 (Tools → Options → Expert Advisors) ║
║  4. Start the bridge:  mt5-bridge                                       ║
║  5. Verify:  python -c "from paper_trading.ops.mt5_client import MT5Client; \
║                          c = MT5Client(); c.connect(); print(c.realtime_mid_price('EURUSD'))"  ║
║                                                                         ║
╚══════════════════════════════════════════════════════════════════════════╝
INSTRUCTIONS
