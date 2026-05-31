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

    # 1. Crea cartelle necessarie
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    magic_lab_dir = ROOT_DIR / "magic_lab"
    magic_lab_dir.mkdir(parents=True, exist_ok=True)
    print(f"Cartella magic_lab pronta: {magic_lab_dir}")

    # 2. Deploy App1, App2, App3 (sempre, indipendente dal lotto)
    app3_src = ROOT_DIR / "magic_dream_app3.py"
    app3_lifecycle_dir = ROOT_DIR / "app3-lifecycle"
    app3_dst = app3_lifecycle_dir / "app3.py"
    app3_lifecycle_dir.mkdir(parents=True, exist_ok=True)
    if app3_src.exists():
        try:
            shutil.copy2(str(app3_src), str(app3_dst))
            print(f"App3 installata: {app3_dst}")
        except Exception as e:
            print(f"ERRORE copia App3: {e}")
    else:
        print(f"ATTENZIONE: {app3_src} non trovata — App3 non aggiornata")

    # Deploy App1 e App2 nella cartella dashboard (versioni pulite da GitHub)
    for src_name, dst_name in [("app.py", "app.py"), ("app2.py", "app2.py")]:
        src = ROOT_DIR / src_name
        dst = DASHBOARD_DIR / dst_name
        if src.exists():
            try:
                shutil.copy2(str(src), str(dst))
                print(f"{src_name} installata: {dst}")
            except Exception as e:
                print(f"ERRORE copia {src_name}: {e}")
        else:
            print(f"ATTENZIONE: {src_name} non trovata in {ROOT_DIR}")

    # 3. Copia file lotto (non bloccante se non trovati)
    lotto_dir = find_lotto_dir()
    if lotto_dir is None:
        print("\nATTENZIONE: cartella lotto non trovata (App1/App2 potrebbero non funzionare).")
        print("Cercato in:")
        for p in LOTTO_CANDIDATES:
            print(f"  {p}")
        print(f"Copia manualmente backtest_ml_storico.xlsx e lotto_draws.csv")
        print(f"dentro: {DASHBOARD_DIR}")
        print("\n" + "=" * 60)
        print("SETUP COMPLETATO (App3 pronta, lotto non trovato).")
        print("=" * 60)
        return 0

    print(f"\nCartella lotto trovata: {lotto_dir}")
    copied, skipped, missing = [], [], []
    for fname in FILES_NEEDED:
        src = lotto_dir / fname
        dst = DASHBOARD_DIR / fname
        if not src.exists():
            print(f"  MANCANTE: {fname}")
            missing.append(fname)
            continue
        if dst.exists():
            if src.stat().st_mtime <= dst.stat().st_mtime:
                print(f"  OK (aggiornato): {fname}")
                skipped.append(fname)
                continue
        try:
            shutil.copy2(str(src), str(dst))
            print(f"  COPIATO: {fname}")
            copied.append(fname)
        except Exception as e:
            print(f"  ERRORE copia {fname}: {e}")

    print("\n" + "=" * 60)
    if missing:
        print(f"Attenzione: {missing} non trovati")
    print("SETUP COMPLETATO.")
    print(f"  Copiati: {copied}")
    print(f"  Gia' aggiornati: {skipped}")
    print("\nAdesso puoi avviare: AVVIA_MAGIC_DREAM.bat")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
