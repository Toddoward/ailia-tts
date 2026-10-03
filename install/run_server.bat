@echo off
REM Ailia TTS - Server Launcher (Windows)
REM - Runs install.bat first if the server is not installed
REM - Re-runs install.bat if the repo version is newer than the installed version
REM - Then starts the streaming TTS server

setlocal EnableDelayedExpansion

set INSTALL_DIR=%USERPROFILE%\.ailia-tts
set SCRIPT_DIR=%~dp0
set REPO_DIR=%SCRIPT_DIR%..
set VERSION_FILE=%REPO_DIR%\VERSION
set INSTALLED_VERSION_FILE=%INSTALL_DIR%\VERSION
set VENV_PY=%INSTALL_DIR%\venv\Scripts\python.exe
set SERVER_PY=%INSTALL_DIR%\tts_streaming_server.py

echo ==========================================
echo  Ailia TTS - Server Launcher
echo ==========================================
echo.

REM --- Read repo version ---
set REPO_VERSION=unknown
if exist "%VERSION_FILE%" (
    set /p REPO_VERSION=<"%VERSION_FILE%"
)

REM --- Check installation ---
set NEED_INSTALL=0

if not exist "%INSTALL_DIR%" (
    echo [INFO] Not installed yet.
    set NEED_INSTALL=1
) else if not exist "%VENV_PY%" (
    echo [INFO] Virtual environment missing.
    set NEED_INSTALL=1
) else if not exist "%SERVER_PY%" (
    echo [INFO] Server file missing.
    set NEED_INSTALL=1
) else if not exist "%INSTALLED_VERSION_FILE%" (
    echo [INFO] Version info missing.
    set NEED_INSTALL=1
)

REM --- Version check (only if installed) ---
if "%NEED_INSTALL%"=="0" (
    set /p INSTALLED_VERSION=<"%INSTALLED_VERSION_FILE%"
    if not "!INSTALLED_VERSION!"=="%REPO_VERSION%" (
        echo [INFO] Update available: v!INSTALLED_VERSION! -^> v%REPO_VERSION%
        set NEED_INSTALL=1
    ) else (
        echo [OK] Installed version v!INSTALLED_VERSION! is up to date.
    )
)

REM --- Run installer if needed ---
if "%NEED_INSTALL%"=="1" (
    echo.
    echo Running installer...
    echo.
    call "%SCRIPT_DIR%install.bat"
    if errorlevel 1 (
        echo.
        echo [ERROR] Installation failed. Server cannot start.
        pause
        exit /b 1
    )
    echo.
)

REM --- Ensure Python requirements (idempotent: skips satisfied packages) ---
set REQ_FILE=%REPO_DIR%\server\requirements.txt
if not exist "%REQ_FILE%" set REQ_FILE=%INSTALL_DIR%\requirements.txt
if exist "%REQ_FILE%" (
    echo [INFO] Verifying Python packages...
    "%VENV_PY%" -m pip install --quiet -r "%REQ_FILE%"
    if errorlevel 1 (
        echo [WARN] Some packages may not have installed cleanly. Continuing anyway...
    ) else (
        echo [OK] Python packages verified.
    )
) else (
    echo [WARN] requirements.txt not found, skipping package check.
)

REM --- Start server ---
echo ==========================================
echo  Starting Ailia TTS server (v%REPO_VERSION%)
echo  Listening on 127.0.0.1:18766
echo  Press Ctrl+C to stop.
echo ==========================================
echo.

"%VENV_PY%" "%SERVER_PY%"
