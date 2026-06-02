@echo off
cd /d "%~dp0"
title Magic Dream — Deep Analysis (griglia 7360 draw)

echo ============================================================
echo  Magic Dream — Deep Analysis
echo  Griglia completa su tutti i draw storici
echo  Shift testati: 80, 90, 100, 110, 120, 130, 150, 175, 200
echo  Output: magic_lab\golden_analysis.xlsx
echo ============================================================
echo.
echo Installo openpyxl se mancante...
pip install openpyxl -q
echo.
echo Avvio analisi (puo' richiedere 5-15 minuti)...
echo.
python magic_experiment_lab.py --deep-analysis
echo.
echo ============================================================
echo  COMPLETATO!
echo  Apri: magic_lab\golden_analysis.xlsx
echo  Fogli: Grid_Hits | Shift_Ranking | Finestre_100
echo         Numeri_Ranking | Coppie | Golden6
echo ============================================================
echo.
pause
