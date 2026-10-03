#!/bin/bash
# Ailia TTS - Server Launcher (Linux / macOS)
# - Runs install.sh first if the server is not installed
# - Re-runs install.sh if the repo version is newer than the installed version
# - Then starts the streaming TTS server

INSTALL_DIR="$HOME/.ailia-tts"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VERSION_FILE="$REPO_DIR/VERSION"
INSTALLED_VERSION_FILE="$INSTALL_DIR/VERSION"
VENV_PY="$INSTALL_DIR/venv/bin/python"
SERVER_PY="$INSTALL_DIR/tts_streaming_server.py"

echo "=========================================="
echo " Ailia TTS - Server Launcher"
echo "=========================================="
echo ""

REPO_VERSION="unknown"
if [ -f "$VERSION_FILE" ]; then
    REPO_VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
fi

# --- Check installation ---
NEED_INSTALL=0

if [ ! -d "$INSTALL_DIR" ]; then
    echo "[INFO] Not installed yet."
    NEED_INSTALL=1
elif [ ! -f "$VENV_PY" ]; then
    echo "[INFO] Virtual environment missing."
    NEED_INSTALL=1
elif [ ! -f "$SERVER_PY" ]; then
    echo "[INFO] Server file missing."
    NEED_INSTALL=1
elif [ ! -f "$INSTALLED_VERSION_FILE" ]; then
    echo "[INFO] Version info missing."
    NEED_INSTALL=1
fi

# --- Version check (only if installed) ---
if [ "$NEED_INSTALL" -eq 0 ]; then
    INSTALLED_VERSION=$(cat "$INSTALLED_VERSION_FILE" | tr -d '[:space:]')
    if [ "$INSTALLED_VERSION" != "$REPO_VERSION" ]; then
        echo "[INFO] Update available: v$INSTALLED_VERSION -> v$REPO_VERSION"
        NEED_INSTALL=1
    else
        echo "[OK] Installed version v$INSTALLED_VERSION is up to date."
    fi
fi

# --- Run installer if needed ---
if [ "$NEED_INSTALL" -eq 1 ]; then
    echo ""
    echo "Running installer..."
    echo ""
    bash "$SCRIPT_DIR/install.sh"
    if [ $? -ne 0 ]; then
        echo ""
        echo "[ERROR] Installation failed. Server cannot start."
        exit 1
    fi
    echo ""
fi

# --- Ensure Python requirements (idempotent: skips satisfied packages) ---
REQ_FILE="$REPO_DIR/server/requirements.txt"
if [ ! -f "$REQ_FILE" ]; then
    REQ_FILE="$INSTALL_DIR/requirements.txt"
fi
if [ -f "$REQ_FILE" ]; then
    echo "[INFO] Verifying Python packages..."
    if "$VENV_PY" -m pip install --quiet -r "$REQ_FILE"; then
        echo "[OK] Python packages verified."
    else
        echo "[WARN] Some packages may not have installed cleanly. Continuing anyway..."
    fi
else
    echo "[WARN] requirements.txt not found, skipping package check."
fi

# --- Start server ---
echo "=========================================="
echo " Starting Ailia TTS server (v$REPO_VERSION)"
echo " Listening on 127.0.0.1:18766"
echo " Press Ctrl+C to stop."
echo "=========================================="
echo ""

exec "$VENV_PY" "$SERVER_PY"
