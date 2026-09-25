@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Instalando a biblioteca Playwright...
python -m pip install --upgrade playwright
echo.
echo Instalacao concluida. O robo usa o Microsoft Edge que ja esta no computador.
pause
