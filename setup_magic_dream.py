"""
setup_magic_dream.py — esegui UNA VOLTA prima di avviare Magic Dream.

Copia automaticamente i file necessari dalla cartella lotto principale
alla cartella Magic Dream, in modo che App3 trovi il backtest e il CSV.

Esegui con: python setup_magic_dream.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

DASHBOARD_DIR = ROOT_DIR / "app1-app2-dashboard" / "lotto-dashboard"

# Possibili posizioni del backtest lotto sul Desktop
LOTTO_CANDIDATES = [
    Path(r"C:\Users\serti\OneDrive\Desktop\lotto\lotto-dashboard"),
    Path(r"C:\Users\serti\OneDrive\Desktop\3 ml\lotto-dashboard"),
    Path(r"C:\Users\serti\Desktop\lotto\lotto-dashboard"),
    Path(r"C:\Users\serti\Desktop\3 ml\lotto-dashboard"),
]

FILES_NEEDED = [
    "backtest_ml_storico.xlsx",
    "lotto_draws.csv",
]


def find_lotto_dir() -> Path | None:
    for p in LOTTO_CANDIDATES:
        if p.is_dir():
            return p
    return None


def main() -> int:
    print("=" * 60)
    print("Magic Dream Setup")
    print("=" * 60)
    print(f"Cartella Magic Dream: {ROOT_DIR}")
    print(f"Destinazione dashboard: {DASHBOARD_DIR}")

    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

    lotto_dir = find_lotto_dir()
    if lotto_dir is None:
        print("\nERRORE: cartella lotto non trovata.")
        print("Cercate in:")
        for p in LOTTO_CANDIDATES:
            print(f"  {p}")
        print("\nCopia manualmente i file backtest_ml_storico.xlsx e lotto_draws.csv")
        print(f"dentro: {DASHBOARD_DIR}")
        return 1

    print(f"\nCartella lotto trovata: {lotto_dir}")

    copied, skipped, missing = [], [], []
    for fname in FILES_NEEDED:
        src = lotto_dir / fname
        dst = DASHBOARD_DIR / fname
        if not src.exists():
            print(f"  MANCANTE: {fname} non trovato in {lotto_dir}")
            missing.append(fname)
            continue
        if dst.exists():
            src_mtime = src.stat().st_mtime
            dst_mtime = dst.stat().st_mtime
            if src_mtime <= dst_mtime:
                print(f"  OK (aggiornato): {fname}")
                skipped.append(fname)
                continue
        try:
            shutil.copy2(str(src), str(dst))
            print(f"  COPIATO: {fname}")
            copied.append(fname)
        except Exception as e:
            print(f"  ERRORE copia {fname}: {e}")
            return 1

    # Crea cartella magic_lab se non esiste
    magic_lab_dir = ROOT_DIR / "magic_lab"
    magic_lab_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nCartella magic_lab pronta: {magic_lab_dir}")

    print("\n" + "=" * 60)
    if missing and len(missing) == len(FILES_NEEDED):
        print("SETUP INCOMPLETO — file sorgente mancanti nel lotto folder.")
        return 1

    if missing:
        print(f"Attenzione: {missing} non trovati (non critici se backtest c'e')")

    print("SETUP COMPLETATO.")
    print(f"  Copiati: {copied}")
    print(f"  Gia' aggiornati: {skipped}")
    print("\nAdesso puoi avviare: AVVIA_MAGIC_DREAM.bat")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
