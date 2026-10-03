#!/bin/bash
# Ailia TTS v3 - Run Server (Linux/macOS)
set -e
export PYTHONIOENCODING=utf-8
export LC_ALL=C.UTF-8
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
    --prompt-text "You are a helpful assistant.<|endofprompt|>안녕하세요, 저는 에일리아에요. 새로운 것을 만들고 사람들과 소통하는 일은 언제나 가슴 뛰는 일입니다. 때로는 예상하지 못한 어려움이 찾아오기도 하지만, 그 과정 속에서 더 깊은 배움을 얻게 되죠. 오늘 하루도 작은 성취를 쌓아가며 의미 있는 시간 보내시길 바랍니다." \
    --port 18766
