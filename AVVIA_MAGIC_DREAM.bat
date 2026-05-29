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

echo [2/3] Avvio agente AI (porta 8604)...
start "Agente Magic Dream" /B python -m streamlit run agente_magic.py --server.port 8604 --server.headless true
echo  Agente  -^> http://localhost:8604
echo.

echo [3/3] Avvio supervisor 24/7...
echo  App 1  -^> http://localhost:8601
echo  App 2  -^> http://localhost:8602
echo  App 3  -^> http://localhost:8603
echo.
echo Il browser si apre automaticamente per tutte e 3 le app.
echo Magic Lab avviera' la prima simulazione entro 2-3 minuti.
echo.
python magic_dream_24_7.py
pause
