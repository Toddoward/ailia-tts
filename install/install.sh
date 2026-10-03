#!/bin/bash
# Ailia TTS v3 - Linux/macOS Installer
set -e

echo "============================================"
echo " Ailia TTS v3 Installer (Linux/macOS)"
echo "============================================"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 not found"
    exit 1
fi
echo "[OK] Python found"

# Check NVIDIA GPU (Linux only)
if command -v nvidia-smi &> /dev/null; then
    echo "[OK] NVIDIA GPU detected"
else
    echo "[WARN] No NVIDIA GPU. CPU mode will be very slow."
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then exit 1; fi
fi

# Create venv
if [ ! -d ".venv" ]; then
    echo "[*] Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# Upgrade pip and build tools
pip install --upgrade pip "setuptools<81" wheel --quiet

# Install PyTorch
echo "[*] Installing PyTorch..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    pip install torch torchaudio --quiet  # MPS on macOS
else
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet
fi

# Install deps
echo "[*] Installing dependencies..."
pip install websockets numpy soundfile librosa huggingface_hub --quiet

# Clone CosyVoice3
if [ ! -d "CosyVoice" ]; then
    echo "[*] Cloning CosyVoice3..."
    git clone --quiet --recursive https://github.com/FunAudioLLM/CosyVoice.git
fi
cd CosyVoice
echo "[*] Installing CosyVoice3 dependencies (excluding whisper)..."
python3 -c "open('requirements_filtered.txt','w').write(''.join(l for l in open('requirements.txt', encoding='utf-8') if 'whisper' not in l.lower()))"
pip install --quiet -r requirements_filtered.txt || {
    echo "[ERROR] CosyVoice3 deps failed"
    exit 1
}
echo "[*] Installing openai-whisper (no build isolation)..."
pip install --quiet --no-build-isolation openai-whisper || {
    echo "[ERROR] Whisper install failed"
    exit 1
}
cd ..

# Download model
echo "[*] Downloading model..."
python3 -c "from huggingface_hub import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='models/Fun-CosyVoice3-0.5B-2512')"

echo ""
echo "============================================"
echo " Installation complete!"
echo " Run ./run_server.sh to start."
echo "============================================"
