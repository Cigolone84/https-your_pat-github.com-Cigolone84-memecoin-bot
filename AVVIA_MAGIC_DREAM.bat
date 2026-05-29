@echo off
cd /d "%~dp0"
title Magic Dream 24/7

echo ============================================================
echo  Magic Dream - Avvio
echo ============================================================
echo.

echo [1/3] Setup file...
python setup_magic_dream.py
echo.

echo [2/3] Avvio agente AI (finestra desktop)...
start "Agente Magic Dream" pythonw agente_desktop.py
echo  Agente avviato in background.
echo.

echo [3/3] Avvio supervisor 24/7...
echo  App 1  -^> http://localhost:8601
echo  App 2  -^> http://localhost:8602
echo  App 3  -^> http://localhost:8603
echo.
python magic_dream_24_7.py
pause
