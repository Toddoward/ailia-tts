@echo off
chcp 65001 >nul
REM Ailia TTS v3 - Run Server (Windows)
setlocal
call .venv\Scripts\activate.bat 2>nul

if not exist "models\Fun-CosyVoice3-0.5B-2512" (
    echo [ERROR] Model not found. Run install.bat first.
    pause
    exit /b 1
)

if not exist "prompt.wav" (
    echo [ERROR] prompt.wav not found. Place your voice prompt as prompt.wav
    pause
    exit /b 1
)

echo Starting Ailia TTS v3 server...
python server\tts_server.py ^
    --model-dir "models\Fun-CosyVoice3-0.5B-2512" ^
    --prompt-wav "prompt.wav" ^
    --prompt-text "You are a helpful assistant.<|endofprompt|>안녕하세요, 저는 에일리아에요. 새로운 것을 만들고 사람들과 소통하는 일은 언제나 가슴 뛰는 일입니다. 때로는 예상하지 못한 어려움이 찾아오기도 하지만, 그 과정 속에서 더 깊은 배움을 얻게 되죠. 오늘 하루도 작은 성취를 쌓아가며 의미 있는 시간 보내시길 바랍니다." ^
    --port 18766
pause
