@echo off
echo ===================================================
echo     X Gen Clips - 1-Click Setup (Windows)
echo ===================================================

where ffmpeg >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [!] FFmpeg nahi mila. Winget se install kar rahe hain...
    winget install Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
)

where uv >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [!] uv package manager install kar rahe hain...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
)

if not exist ".venv" (
    echo [*] Creating virtual environment (.venv)...
    uv venv .venv --python 3.10
)

echo [*] Installing dependencies...
uv pip install -U fastapi uvicorn yt-dlp faster-whisper google-genai pydantic requests

echo ===================================================
echo Setup Complete! Ab 'run.bat' chala kar app shuru karein.
echo ===================================================
pause
