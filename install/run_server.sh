#!/bin/bash
# Ailia TTS v3 - Run Server (Linux/macOS)
set -e
source .venv/bin/activate 2>/dev/null || true

if [ ! -d "models/Fun-CosyVoice3-0.5B-2512" ]; then
    echo "[ERROR] Model not found. Run install.sh first."
    exit 1
fi

if [ ! -f "prompt.wav" ]; then
    echo "[ERROR] prompt.wav not found."
    exit 1
fi

echo "Starting Ailia TTS v3 server..."
python3 server/tts_server.py \
    --model-dir "models/Fun-CosyVoice3-0.5B-2512" \
    --prompt-wav "prompt.wav" \
    --prompt-text "안녕하세요, 저는 에일리아예요." \
    --port 18766
