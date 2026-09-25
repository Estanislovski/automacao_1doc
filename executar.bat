@echo off
chcp 65001 >nul
cd /d "%~dp0"
python robo_1doc.py %*
echo.
pause
