@echo off
cd /d "%~dp0"
python spatial_dual_player.py
if %errorlevel% neq 0 (
    echo.
    echo Error: Python is required.
    echo https://www.python.org/downloads/
    pause
)
