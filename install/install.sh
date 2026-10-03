#!/bin/bash
# Ailia TTS - Local Server Installer (Linux / macOS)
# Installs Python, downloads CosyVoice3 ONNX models, sets up the streaming TTS server.
# Safe to re-run: skips existing files, updates server files to the repo version.

set -e

INSTALL_DIR="$HOME/.ailia-tts"
MODEL_DIR="$INSTALL_DIR/models"
PYTHON_MIN="3.10"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VERSION_FILE="$REPO_DIR/VERSION"

REPO_VERSION="unknown"
if [ -f "$VERSION_FILE" ]; then
    REPO_VERSION=$(cat "$VERSION_FILE" | tr -d '[:space:]')
fi

echo "=========================================="
echo " Ailia TTS - Local Server Installer"
echo "=========================================="
echo ""
echo "[INFO] Repo version: $REPO_VERSION"
echo ""

# --- Check Python ---
if command -v python3 &> /dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    echo "[OK] Python $PY_VER found"
else
    echo "[ERROR] Python 3 is not installed."
    echo "Please install Python 3.10+ from https://www.python.org/downloads/"
    exit 1
fi

# --- Create directories ---
mkdir -p "$INSTALL_DIR" "$MODEL_DIR"
echo "[OK] Install directory: $INSTALL_DIR"

# --- Copy server files (always refresh to repo version) ---
echo "Copying server files..."
cp -f "$REPO_DIR/server/tts_streaming_server.py" "$INSTALL_DIR/"
cp -f "$REPO_DIR/server/ailia_prompt.wav" "$INSTALL_DIR/"
cp -f "$REPO_DIR/server/prompt_info.txt" "$INSTALL_DIR/"
cp -f "$VERSION_FILE" "$INSTALL_DIR/VERSION"
echo "[OK] Server files updated to v$REPO_VERSION"

# --- Create virtual environment ---
if [ ! -d "$INSTALL_DIR/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"
fi
VENV_PY="$INSTALL_DIR/venv/bin/python"
echo "[OK] Virtual environment ready"

# --- Install Python packages ---
echo "Installing Python packages (onnxruntime, numpy, websockets, soundfile)..."
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet onnxruntime numpy websockets soundfile
echo "[OK] Python packages installed"

# --- Download models ---
echo ""
echo "Downloading CosyVoice3 ONNX models (~2.9GB)..."
echo "This may take a while depending on your connection."
echo ""

BASE_URL="https://huggingface.co/ayousanz/cosy-voice3-onnx/resolve/main"
FILES=(
    "campplus.onnx"
    "flow.decoder.estimator.fp16.onnx"
    "flow_pre_lookahead_fp16.onnx"
    "flow_speaker_projection_fp16.onnx"
    "flow_token_embedding_fp16.onnx"
    "hift_decoder_fp32.onnx"
    "hift_f0_predictor_fp32.onnx"
    "hift_source_generator_fp32.onnx"
    "llm_backbone_decode_fp16.onnx"
    "llm_backbone_initial_fp16.onnx"
    "llm_decoder_fp16.onnx"
    "llm_speech_embedding_fp16.onnx"
    "speech_tokenizer_v3.onnx"
    "text_embedding_fp32.onnx"
    "merges.txt"
    "vocab.json"
    "tokenizer_config.json"
)

for f in "${FILES[@]}"; do
    if [ -f "$MODEL_DIR/$f" ]; then
        echo "  [skip] $f (already exists)"
    else
        echo "  [downloading] $f..."
        curl -sL -o "$MODEL_DIR/$f" "$BASE_URL/$f"
        echo "  [done] $f"
    fi
done

echo ""
echo "=========================================="
echo " Installation complete! (v$REPO_VERSION)"
echo "=========================================="
echo ""
echo "To start the server, run:"
echo "  ./install/run_server.sh"
echo ""
echo "The server will listen on 127.0.0.1:18766"
echo "Configure the Chrome extension to connect to localhost:18766"
