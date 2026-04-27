@echo off
cd /d "%~dp0"
python binaural_player.py
if %errorlevel% neq 0 (
    echo.
    echo Error: Python is required.
    echo https://www.python.org/downloads/
    pause
)