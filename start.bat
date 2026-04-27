@echo off
chcp 65001 > nul
cd /d "%~dp0"
python binaural_player.py
if %errorlevel% neq 0 (
    echo.
    echo エラーが発生しました。Python がインストールされているか確認してください。
    echo https://www.python.org/downloads/
    pause
)
