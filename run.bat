@echo off
title Clipper Studio AI Server (Port 9999)
cd /d "%~dp0"
echo ===================================================
echo     Starting Clipper Studio AI on Port 9999...
echo ===================================================

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 9999
) else (
    python -m uvicorn backend.main:app --host 0.0.0.0 --port 9999
)
pause
