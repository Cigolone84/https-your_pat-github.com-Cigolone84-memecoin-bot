@echo off
cd /d "%~dp0"
title Aggiorna Magic Dream

echo ============================================================
echo  Magic Dream - Download aggiornamenti da GitHub
echo ============================================================
echo.
echo Scarico i file aggiornati...
echo.

set BASE=https://raw.githubusercontent.com/Cigolone84/https-your_pat-github.com-Cigolone84-memecoin-bot/claude/explore-repo-structure-vp60l

powershell -NoProfile -Command "& { $base='%BASE%'; $files=@('magic_dream_24_7.py','magic_experiment_lab.py','setup_magic_dream.py','AVVIA_MAGIC_DREAM.bat','AGGIORNA.bat','magic_dream_app3.py','agente_desktop.py','app.py','app2.py','confronta.py'); foreach ($f in $files) { Write-Host \"Scarico $f...\"; try { Invoke-WebRequest -Uri \"$base/$f\" -OutFile \"$f\" -UseBasicParsing; Write-Host \"  OK\" } catch { Write-Host \"  ERRORE: $_\" } } }"

echo.
echo Installo App3...
python setup_magic_dream.py

echo.
echo ============================================================
echo  AGGIORNAMENTO COMPLETATO.
echo  Per il confronto App1 vs Magic Dream: python confronta.py
echo  Ora avvia: AVVIA_MAGIC_DREAM.bat
echo ============================================================
echo.
pause
