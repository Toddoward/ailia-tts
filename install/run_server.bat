@echo off
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
    --prompt-text "안녕하세요, 저는 에일리아예요." ^
    --port 18766
pause
