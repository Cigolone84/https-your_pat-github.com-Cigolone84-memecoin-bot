@echo off
cd /d "%~dp0"
title Magic Dream 24/7

echo ============================================================
echo  Magic Dream - Avvio
echo ============================================================
echo.

echo Scarico file aggiornati da GitHub...
set BASE=https://raw.githubusercontent.com/Cigolone84/https-your_pat-github.com-Cigolone84-memecoin-bot/claude/explore-repo-structure-vp60l
powershell -NoProfile -Command "& { $base='%BASE%'; $files=@('magic_dream_24_7.py','magic_experiment_lab.py','setup_magic_dream.py','magic_dream_app3.py','agente_desktop.py','app.py','app2.py','AVVIA_MAGIC_DREAM.bat','AGGIORNA.bat'); foreach ($f in $files) { try { Invoke-WebRequest -Uri \"$base/$f\" -OutFile \"$f\" -UseBasicParsing; Write-Host \"OK: $f\" } catch { Write-Host \"Errore: $f\" } } }"
echo File aggiornati.
echo.

echo Setup...
python setup_magic_dream.py
echo.

echo Installo dipendenze agente...
pip install anthropic -q
echo.

echo Avvio agente AI...
if exist agente_desktop.py (
    start "Agente Magic Dream" cmd /c "python agente_desktop.py & pause"
    echo Agente avviato.
) else (
    echo ATTENZIONE: agente_desktop.py non trovato
)
echo.

echo Avvio Magic Dream 24/7...
echo  App 1 -> http://localhost:8601
echo  App 2 -> http://localhost:8602
echo  App 3 -> http://localhost:8603
echo.
python magic_dream_24_7.py
pause
