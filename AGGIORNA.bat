@echo off
cd /d "%~dp0"
title Aggiorna Magic Dream

echo ============================================================
echo  Magic Dream - Download aggiornamenti da GitHub
echo ============================================================
echo.
echo Scarico i file aggiornati...

set BASE=https://raw.githubusercontent.com/Cigolone84/https-your_pat-github.com-Cigolone84-memecoin-bot/claude/explore-repo-structure-vp60l

powershell -NoProfile -Command "& { $base='%BASE%'; $files=@('magic_dream_24_7.py','magic_experiment_lab.py','setup_magic_dream.py','AVVIA_MAGIC_DREAM.bat','magic_dream_app3.py'); foreach ($f in $files) { Write-Host \"Scarico $f...\"; try { Invoke-WebRequest -Uri \"$base/$f\" -OutFile \"$f\" -UseBasicParsing; Write-Host \"  OK\" } catch { Write-Host \"  ERRORE: $_\" } } }"

echo.
echo Download fatto. Avvio setup...
echo.
python setup_magic_dream.py
echo.
echo ============================================================
echo  Tutto pronto. Avvio Magic Dream...
echo  App 1 -> http://localhost:8601
echo  App 2 -> http://localhost:8602
echo  App 3 -> http://localhost:8603
echo ============================================================
echo.
timeout /t 3 /nobreak >nul
python magic_dream_24_7.py
pause
