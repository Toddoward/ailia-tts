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
)
call .venv\Scripts\activate.bat

REM Upgrade pip
python -m pip install --upgrade pip --quiet

REM Install PyTorch with CUDA
echo [*] Installing PyTorch (CUDA 12.1)...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 --quiet
if errorlevel 1 (
    echo [ERROR] PyTorch install failed
    pause
    exit /b 1
)

REM Install CosyVoice3 deps
echo [*] Installing CosyVoice3 dependencies...
pip install websockets numpy soundfile librosa --quiet

REM Clone official CosyVoice3
if not exist "CosyVoice" (
    echo [*] Cloning CosyVoice3...
    git clone --quiet https://github.com/FunAudioLLM/CosyVoice.git
)
cd CosyVoice
pip install -r requirements.txt --quiet
cd ..

REM Download model
echo [*] Downloading Fun-CosyVoice3-0.5B-2512...
python -c "from huggingface_hub import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='models/Fun-CosyVoice3-0.5B-2512')" --quiet

echo.
echo ============================================
echo  Installation complete!
echo  Run run_server.bat to start the TTS server.
echo ============================================
pause
