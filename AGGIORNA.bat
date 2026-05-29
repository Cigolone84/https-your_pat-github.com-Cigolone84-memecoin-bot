@echo off
cd /d "%~dp0"
title Aggiorna Magic Dream

echo ============================================================
echo  Magic Dream - Aggiornamento automatico
echo ============================================================
echo.
echo Scarico gli ultimi aggiornamenti da GitHub...

git pull origin claude/explore-repo-structure-vp60l

if errorlevel 1 (
    echo.
    echo ERRORE: aggiornamento fallito.
    echo Controlla la connessione internet e riprova.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Aggiornamento completato!
echo  Ora avvio Magic Dream...
echo ============================================================
echo.

timeout /t 2 /nobreak >nul
call AVVIA_MAGIC_DREAM.bat
