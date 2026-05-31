"""
confronta.py — Confronto App1 (ML) vs Magic Dream (statistiche)
Esegui: python confronta.py
"""
import sys
import os
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
MAGIC_LAB = ROOT / "magic_lab"

SEP = "=" * 60

def _read_csv(path):
    import csv
    try:
        with open(path, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        return None

def _read_excel(path):
    try:
        import pandas as pd
        return pd.read_excel(path)
    except Exception:
        return None

def main():
    print()
    print(SEP)
    print("  MAGIC DREAM — Confronto App1 (ML) vs Magic Dream (Statistiche)")
    print(SEP)

    # ── Magic Dream: ranking strategie ───────────────────────────────────────
    rank = _read_csv(MAGIC_LAB / "latest_strategy_ranking.csv")
    print()
    if rank:
        print("  MAGIC DREAM — 8 strategie statistiche (hit_t0 = prossima draw):")
        print(f"  {'#':<3} {'Strategia':<14} {'Hit >=3 T0 %':<14} {'Hit medio T0':<13} {'Draw testati'}")
        print("  " + "-" * 58)
        for r in rank:
            strat  = r.get("Strategia", "?")
            pct    = r.get("Hit >=3 T0 %", "?")
            medio  = r.get("Hit medio T0", "?")
            draw_n = r.get("Draw valutati", "?")
            rank_n = r.get("Rank", "?")
            marker = " ← MIGLIORE" if rank_n == "1" else ""
            print(f"  {rank_n:<3} {strat:<14} {pct:<14} {medio:<13} {draw_n}{marker}")
        print(f"  Benchmark random: 2.8%")
    else:
        print("  [Magic Dream] Ranking non disponibile — Magic Lab non ha ancora girato.")

    # ── Magic Dream: chi vince per draw ──────────────────────────────────────
    cmp = _read_csv(MAGIC_LAB / "latest_strategy_comparison.csv")
    print()
    if cmp:
        total = len(cmp)
        print(f"  MAGIC DREAM — Vittorie per draw ({total} draw analizzati):")
        wins = Counter(r.get("vincitore", "") for r in cmp if r.get("vincitore"))
        for strat, n in wins.most_common():
            pct = n / total * 100
            bar = "█" * int(pct / 2)
            print(f"  {strat:<14} {n:>5} draw  ({pct:5.1f}%)  {bar}")

        print()
        print("  Distribuzione hit massimo per draw:")
        for threshold in [3, 4, 5, 6]:
            try:
                n = sum(1 for r in cmp if float(r.get("max_hit", 0)) >= threshold)
                pct = n / total * 100
                flag = " 🔥" if threshold >= 5 else ""
                print(f"  {threshold}+ numeri azzeccati: {n:>5} draw  ({pct:5.2f}%){flag}")
            except Exception:
                pass
    else:
        print("  [Magic Dream] Confronto per draw non disponibile.")

    # ── App1 ML: cerca backtest ───────────────────────────────────────────────
    print()
    print(SEP)
    print("  APP1 — Modello ML (Random Forest sul pool lotto polacco)")
    print(SEP)
    bt_paths = [
        ROOT / "app1-app2-dashboard" / "lotto-dashboard" / "backtest_ml_storico.xlsx",
        ROOT / "app1-app2-dashboard" / "backtest_ml_storico.xlsx",
    ]
    bt_found = False
    for bt_path in bt_paths:
        if bt_path.exists():
            df = _read_excel(bt_path)
            if df is not None:
                print(f"  Backtest ML: {bt_path.name}  ({len(df)} righe)")
                hit_cols = [c for c in df.columns
                            if any(k in str(c).lower() for k in ["hit", "pool", "match", ">="])]
                if hit_cols:
                    print(f"  Colonne trovate: {hit_cols[:6]}")
                    for c in hit_cols[:4]:
                        try:
                            import pandas as pd
                            col = pd.to_numeric(df[c], errors="coerce").dropna()
                            if len(col) > 5:
                                ge3 = (col >= 3).sum()
                                ge4 = (col >= 4).sum()
                                ge5 = (col >= 5).sum()
                                print(f"  {c}:")
                                print(f"    media={col.mean():.3f}  max={int(col.max())}")
                                print(f"    >=3: {ge3} ({ge3/len(col)*100:.1f}%)  >=4: {ge4} ({ge4/len(col)*100:.1f}%)  >=5: {ge5} ({ge5/len(col)*100:.1f}%)")
                        except Exception:
                            pass
                else:
                    print(f"  Colonne disponibili: {list(df.columns[:8])}")
                bt_found = True
                break
    if not bt_found:
        print("  backtest_ml_storico.xlsx non trovato.")
        print()
        print("  Dati storici NOTI del pool di App1 (ML Top-8 + Sestine 1-5):")
        print("  Pool ~18-21 numeri su 7000+ draw storici:")
        print("  ★ 5 numeri vincenti nel pool: 35 volte  (0.50%)")
        print("  ★ 6 numeri vincenti nel pool:  1 volta  (0.01%)")
        print()
        print("  PoolTop8 in Magic Dream usa QUESTO pool => stesso segnale, filtrato a 8.")

    # ── Conclusione ───────────────────────────────────────────────────────────
    print()
    print(SEP)
    print("  VERDETTO")
    print(SEP)
    print()
    if rank:
        best = rank[0]
        best_name = best.get("Strategia", "?")
        best_pct  = best.get("Hit >=3 T0 %", "?")
        best_draw = best.get("Draw valutati", "?")
        print(f"  Strategia Magic Dream migliore: {best_name}  ({best_pct} su {best_draw} draw)")
        print(f"  Benchmark random:                2.8%")
        try:
            pct_val = float(str(best_pct).replace("%", "").strip())
            delta = pct_val - 2.8
            print(f"  Vantaggio su random:            +{delta:.1f} punti percentuali")
        except Exception:
            pass
    print()
    print("  PoolTop8 = ponte diretto App1 ↔ Magic Dream.")
    print("  Migliorare App1 migliora automaticamente PoolTop8 in Magic Dream.")
    print()
    print(SEP)
    print()

if __name__ == "__main__":
    main()
    input("Premi INVIO per chiudere...")
