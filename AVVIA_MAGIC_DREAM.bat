@echo off
cd /d "%~dp0"
title Magic Dream 24/7

echo ============================================================
echo  Magic Dream - Avvio
echo ============================================================
echo.

REM Setup automatico: copia backtest e CSV dalla cartella lotto
echo [1/2] Setup file...
python setup_magic_dream.py
if errorlevel 1 (
    echo.
    echo ATTENZIONE: setup non completato.
    echo Copia manualmente backtest_ml_storico.xlsx e lotto_draws.csv
    echo dentro: app1-app2-dashboard\lotto-dashboard\
    echo.
    pause
    exit /b 1
)

echo.
echo [2/2] Avvio supervisor 24/7...
echo  App 1  -^> http://localhost:8601
echo  App 2  -^> http://localhost:8602
echo  App 3  -^> http://localhost:8603
echo.
echo Il browser si apre automaticamente per tutte e 3 le app.
echo Magic Lab avviera' la prima simulazione entro 2-3 minuti.
echo.
python magic_dream_24_7.py
pause
