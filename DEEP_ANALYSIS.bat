@echo off
cd /d "%~dp0"
title Magic Dream — Deep Analysis (griglia 7360 draw)

echo ============================================================
echo  Magic Dream — Deep Analysis — RITORNO AL FUTURO
echo  Griglia completa su tutti i draw storici (57 anni)
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
echo.
echo  Fogli disponibili:
echo    Grid_Hits        — ogni draw x ogni shift (matrice completa)
echo    Shift_Ranking    — shift ordinati per performance globale/recente
echo    Finestre_100     — 73 finestre da 100 draw, shift ottimale per ognuna
echo    Convergenza      — numeri piu STABILI in TUTTE le 73 finestre (CERTISSIMO)
echo    Numeri_Ranking   — ranking 1-49 per volte confermato nei 4+ hit
echo    Coppie           — top 50 coppie co-confermate
echo    Golden6          — top4 + coppia residua storica
echo    RitornoAlFuturo  — shift ottimale per STASERA (validazione recente)
echo    Stasera          — previsione completa + GOLDEN4_CONVERGENZA + GOLDEN6_CONVERGENZA
echo    Stasera_Consenso — top 15 numeri per voti consenso
echo    Kumulacja        — analisi separata draw jackpot accumulation
echo ============================================================
echo.
pause
