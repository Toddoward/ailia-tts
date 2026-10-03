@echo off
REM Ailia TTS v3 - Windows Installer
REM Installs Python deps, PyTorch + CUDA, CosyVoice3, and the model.
setlocal enabledelayedexpansion

echo ============================================
echo  Ailia TTS v3 Installer (Windows)
echo ============================================

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)
echo [OK] Python found

REM Check NVIDIA GPU
nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo [WARN] No NVIDIA GPU detected. CPU mode will be very slow.
    echo [WARN] Continue anyway? (Ctrl+C to abort)
    pause
)

REM Create venv
if not exist ".venv" (
    echo [*] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] venv creation failed
        pause
        exit /b 1
    )
)
call .venv\Scripts\activate.bat

REM Upgrade pip and install build tools
echo [*] Upgrading pip and build tools...
python -m pip install --upgrade pip setuptools wheel --quiet
if errorlevel 1 (
    echo [ERROR] pip upgrade failed
    pause
    exit /b 1
)

REM Install PyTorch with CUDA
echo [*] Installing PyTorch (CUDA 12.1)...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet
if errorlevel 1 (
    echo [ERROR] PyTorch install failed
    pause
    exit /b 1
)

REM Install server deps (including huggingface_hub for model download)
echo [*] Installing server dependencies...
pip install websockets numpy soundfile librosa huggingface_hub --quiet
if errorlevel 1 (
    echo [ERROR] Server deps install failed
    pause
    exit /b 1
)

REM Clone official CosyVoice3
if not exist "CosyVoice" (
    echo [*] Cloning CosyVoice3...
    git clone --quiet https://github.com/FunAudioLLM/CosyVoice.git
    if errorlevel 1 (
        echo [ERROR] Git clone failed. Is git installed?
        pause
        exit /b 1
    )
)
cd CosyVoice
echo [*] Installing CosyVoice3 requirements (this may take a while)...
pip install -r requirements.txt
if errorlevel 1 (
    echo [WARN] Some CosyVoice3 deps failed. Trying without whisper (not needed for TTS)...
    pip install --quiet torch torchaudio transformers librosa soundfile numpy
)
cd ..

REM Download model
echo [*] Downloading Fun-CosyVoice3-0.5B-2512...
python -c "from huggingface_hub import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='models/Fun-CosyVoice3-0.5B-2512')"
if errorlevel 1 (
    echo [ERROR] Model download failed
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Installation complete!
echo  Run run_server.bat to start the TTS server.
echo ============================================
pause
