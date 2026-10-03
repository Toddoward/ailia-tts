@echo off
REM Ailia TTS - Local Server Installer (Windows)
REM Installs Python packages, downloads CosyVoice3 ONNX models, sets up the streaming TTS server.
REM Safe to re-run: skips existing files, updates server files to the repo version.

setlocal EnableDelayedExpansion

echo ==========================================
echo  Ailia TTS - Local Server Installer
echo ==========================================
echo.

set INSTALL_DIR=%USERPROFILE%\.ailia-tts
set MODEL_DIR=%INSTALL_DIR%\models
set SCRIPT_DIR=%~dp0
set REPO_DIR=%SCRIPT_DIR%..
set VERSION_FILE=%REPO_DIR%\VERSION

REM --- Read repo version ---
set REPO_VERSION=unknown
if exist "%VERSION_FILE%" (
    set /p REPO_VERSION=<"%VERSION_FILE%"
)
echo [INFO] Repo version: %REPO_VERSION%
echo.

REM --- Check Python ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
echo [OK] Python found
python --version

REM --- Create directories ---
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"
echo [OK] Install directory: %INSTALL_DIR%

REM --- Copy server files (always refresh to repo version) ---
echo Copying server files...
copy /Y "%REPO_DIR%\server\tts_streaming_server.py" "%INSTALL_DIR%\" >nul
copy /Y "%REPO_DIR%\server\requirements.txt" "%INSTALL_DIR%\" >nul
copy /Y "%REPO_DIR%\server\ailia_prompt.wav" "%INSTALL_DIR%\" >nul
copy /Y "%REPO_DIR%\server\prompt_info.txt" "%INSTALL_DIR%\" >nul
copy /Y "%VERSION_FILE%" "%INSTALL_DIR%\VERSION" >nul
echo [OK] Server files updated to v%REPO_VERSION%

REM --- Create virtual environment ---
if not exist "%INSTALL_DIR%\venv" (
    echo Creating virtual environment...
    python -m venv "%INSTALL_DIR%\venv"
)
set VENV_PY=%INSTALL_DIR%\venv\Scripts\python.exe
echo [OK] Virtual environment ready

REM --- Install Python packages ---
echo Installing Python packages from requirements.txt...
"%VENV_PY%" -m pip install --quiet --upgrade pip
"%VENV_PY%" -m pip install --quiet -r "%REPO_DIR%\server\requirements.txt"
echo [OK] Python packages installed

REM --- Download models ---
echo.
echo Downloading CosyVoice3 ONNX models (~2.9GB)...
echo This may take a while depending on your connection.
echo.

set BASE_URL=https://huggingface.co/ayousanz/cosy-voice3-onnx/resolve/main

for %%f in (
    campplus.onnx
    flow.decoder.estimator.fp16.onnx
    flow_pre_lookahead_fp16.onnx
    flow_speaker_projection_fp16.onnx
    flow_token_embedding_fp16.onnx
    hift_decoder_fp32.onnx
    hift_f0_predictor_fp32.onnx
    hift_source_generator_fp32.onnx
    llm_backbone_decode_fp16.onnx
    llm_backbone_initial_fp16.onnx
    llm_decoder_fp16.onnx
    llm_speech_embedding_fp16.onnx
    speech_tokenizer_v3.onnx
    text_embedding_fp32.onnx
    merges.txt
    vocab.json
    tokenizer_config.json
) do (
    if exist "%MODEL_DIR%\%%f" (
        echo   [skip] %%f - already exists
    ) else (
        echo   [downloading] %%f ...
        curl -sL -o "%MODEL_DIR%\%%f" "%BASE_URL%/%%f"
        if errorlevel 1 (
            echo   [ERROR] Failed to download %%f
        ) else (
            echo   [done] %%f
        )
    )
)

echo.
echo ==========================================
echo  Installation complete! (v%REPO_VERSION%)
echo ==========================================
echo.
echo To start the server, run:
echo   install\run_server.bat
echo.
echo The server will listen on 127.0.0.1:18766
echo Configure the Chrome extension to connect to localhost:18766
echo.
pause
