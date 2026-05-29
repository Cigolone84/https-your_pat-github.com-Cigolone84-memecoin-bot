"""
magic_experiment_lab.py — Magic Dream background worker.

Runs walk-forward backtests with alternative number-selection strategies
that do NOT rely on the pool-based ML predictions used in App1/App2/App3.
Works purely from historical draw numbers.

Strategies tested:
  FreqHot8    — 8 numbers drawn most often in last freq_window draws
  FreqCold8   — 8 numbers drawn least often (maximum delay)
  HotCold4+4  — 4 most frequent + 4 most delayed
  Decade8     — balanced selection across 5 decades (1-9, 10-19…40-49)
  Delay8      — 8 numbers with the largest gap since last appearance
  NucleoPool  — 4-5 numbers that appear in 4+ sestine of the last prediction
                plus cold numbers to fill to 8

Output (magic_lab/ directory, relative to this script):
  latest_strategy_ranking.csv
  latest_next_predictions.csv
  latest_cycle_summary.csv
  latest_cycle_windows.csv
  latest_event_gaps.csv
  latest_range_positions.csv

CLI:
  python magic_experiment_lab.py [--loop] [--interval-minutes N]
       [--limit N] [--warmup N] [--freq-window N] [--keep-top N]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import sys
import time
from collections import Counter
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

# ── Paths ───────────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = ROOT_DIR / "app1-app2-dashboard" / "lotto-dashboard"
BACKTEST_PATH = DASHBOARD_DIR / "backtest_ml_storico.xlsx"
DRAWS_CSV_PATH = DASHBOARD_DIR / "lotto_draws.csv"
OUT_DIR = ROOT_DIR / "magic_lab"

LOG_PATH = ROOT_DIR / "magic_lab_worker.log"

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("magic_lab")

# ── Constants ────────────────────────────────────────────────────────────────

ALL_NUMS = list(range(1, 50))
DECADES = [(1, 9), (10, 19), (20, 29), (30, 39), (40, 49)]
STRATEGY_NAMES = [
    "FreqHot8",
    "FreqCold8",
    "HotCold4+4",
    "Decade8",
    "Delay8",
    "NucleoPool",
]

# ── Data helpers ─────────────────────────────────────────────────────────────

def parse_nums(s) -> frozenset:
    if not s or (isinstance(s, float) and np.isnan(s)):
        return frozenset()
    return frozenset(int(x) for x in str(s).split() if x.isdigit() and 1 <= int(x) <= 49)


def load_draws(limit: int = 0) -> pd.DataFrame:
    """Load historical draw data from backtest excel or CSV fallback."""
    df: Optional[pd.DataFrame] = None

    if BACKTEST_PATH.exists():
        try:
            df = pd.read_excel(BACKTEST_PATH)
            log.info("Caricati %d draw da %s", len(df), BACKTEST_PATH)
        except Exception as exc:
            log.warning("Errore lettura xlsx: %s", exc)

    if df is None and DRAWS_CSV_PATH.exists():
        try:
            raw = pd.read_csv(DRAWS_CSV_PATH)
            rows = []
            for _, r in raw.iterrows():
                try:
                    draw_n = int(r["draw"])
                    nums = frozenset(int(r[f"n{k}"]) for k in range(1, 7) if not pd.isna(r.get(f"n{k}")))
                    if len(nums) == 6:
                        rows.append({"Draw": draw_n, "Data": r.get("date", ""), "Numeri Reali": " ".join(f"{n:02d}" for n in sorted(nums))})
                except Exception:
                    continue
            df = pd.DataFrame(rows)
            log.info("Caricati %d draw da CSV", len(df))
        except Exception as exc:
            log.warning("Errore lettura CSV: %s", exc)

    if df is None or len(df) == 0:
        raise FileNotFoundError(f"Nessun dato storico trovato. Cercato: {BACKTEST_PATH}")

    # Keep only rows with real draw numbers
    actuals = []
    draw_nums = []
    for _, row in df.iterrows():
        nums = parse_nums(row.get("Numeri Reali", ""))
        if len(nums) == 6:
            actuals.append(frozenset(nums))
            draw_nums.append(int(row["Draw"]))

    result = pd.DataFrame({
        "draw": draw_nums,
        "actual": actuals,
    })

    # Also keep sestine columns for NucleoPool strategy
    for k in range(1, 6):
        col = f"Sestina {k}"
        if col in df.columns:
            ses_vals = []
            for _, row in df.iterrows():
                nums = parse_nums(row.get(col, ""))
                if len(parse_nums(row.get("Numeri Reali", ""))) == 6:
                    ses_vals.append(frozenset(nums))
            if ses_vals:
                result[col] = ses_vals

    if limit > 0:
        result = result.tail(limit).reset_index(drop=True)

    return result


# ── Strategy implementations ─────────────────────────────────────────────────

def strategy_freq_hot(history: List[frozenset], n: int = 8, window: int = 100) -> frozenset:
    """8 most frequent numbers in last `window` draws."""
    recent = history[-window:] if len(history) >= window else history
    counts = Counter(num for draw in recent for num in draw)
    top = sorted(counts, key=lambda x: (-counts[x], x))[:n]
    if len(top) < n:
        # fill with cold numbers
        missing = [x for x in ALL_NUMS if x not in top]
        top = top + missing[: n - len(top)]
    return frozenset(top[:n])


def strategy_freq_cold(history: List[frozenset], n: int = 8, window: int = 100) -> frozenset:
    """8 least frequent (coldest / most delayed) in last `window` draws."""
    recent = history[-window:] if len(history) >= window else history
    counts = Counter(num for draw in recent for num in draw)
    # Numbers never drawn get max delay
    cold = sorted(ALL_NUMS, key=lambda x: (counts.get(x, 0), x))[:n]
    return frozenset(cold)


def strategy_hot_cold(history: List[frozenset], n: int = 8, window: int = 100) -> frozenset:
    """4 hottest + 4 coldest numbers."""
    recent = history[-window:] if len(history) >= window else history
    counts = Counter(num for draw in recent for num in draw)
    hot4 = sorted(counts, key=lambda x: (-counts[x], x))[:4]
    cold4 = sorted(ALL_NUMS, key=lambda x: (counts.get(x, 0), x))
    # avoid overlap
    cold4_clean = [x for x in cold4 if x not in hot4][:4]
    return frozenset(hot4 + cold4_clean)


def strategy_decade(history: List[frozenset], n: int = 8, window: int = 100) -> frozenset:
    """
    Balanced across 5 decades: pick top 2 per decade (by frequency),
    prefer decades that are underrepresented in recent draws.
    """
    recent = history[-window:] if len(history) >= window else history
    counts = Counter(num for draw in recent for num in draw)

    # How often each decade was hit
    decade_counts = []
    for lo, hi in DECADES:
        dc = sum(counts.get(n, 0) for n in range(lo, hi + 1))
        decade_counts.append(dc)

    # Normalize: each decade contributes 2 numbers (total = 10 numbers, pick 8)
    chosen: List[int] = []
    # Sort decades by underrepresentation (least hits first)
    decade_order = sorted(range(5), key=lambda d: decade_counts[d])
    per_decade = {0: 2, 1: 2, 2: 2, 3: 1, 4: 1}  # give more slots to cold decades
    for rank, d_idx in enumerate(decade_order):
        lo, hi = DECADES[d_idx]
        candidates = sorted(range(lo, hi + 1), key=lambda x: (counts.get(x, 0), x))
        slots = per_decade.get(rank, 1)
        chosen.extend(candidates[:slots])

    chosen = list(dict.fromkeys(chosen))  # dedup preserve order
    if len(chosen) < n:
        extras = [x for x in ALL_NUMS if x not in chosen]
        chosen += extras[: n - len(chosen)]
    return frozenset(chosen[:n])


def strategy_delay(history: List[frozenset], n: int = 8) -> frozenset:
    """8 numbers with the largest gap since their last appearance."""
    total = len(history)
    last_seen = {}
    for pos, draw in enumerate(history):
        for num in draw:
            last_seen[num] = pos
    # Numbers never seen have delay = total
    delay = {num: total - last_seen.get(num, -1) for num in ALL_NUMS}
    top = sorted(ALL_NUMS, key=lambda x: (-delay[x], x))[:n]
    return frozenset(top)


def strategy_nucleo_pool(
    history: List[frozenset],
    ses_history: Optional[List[List[frozenset]]],
    n: int = 8,
    window: int = 100,
) -> frozenset:
    """
    Nucleo: pick numbers that appear in 4+ sestine of the latest prediction.
    Fill remaining slots with cold numbers from history.
    """
    nucleo: frozenset = frozenset()
    if ses_history and len(ses_history) > 0:
        last_ses = ses_history[-1]
        cnt = Counter(num for s in last_ses for num in s)
        nucleo = frozenset(num for num, c in cnt.items() if c >= 4)

    if len(nucleo) >= n:
        return frozenset(sorted(nucleo)[:n])

    # Fill with cold numbers
    recent = history[-window:] if len(history) >= window else history
    counts = Counter(num for draw in recent for num in draw)
    cold = sorted(ALL_NUMS, key=lambda x: (counts.get(x, 0), x))
    cold_fill = [x for x in cold if x not in nucleo][: n - len(nucleo)]
    return nucleo | frozenset(cold_fill)


def _apply_strategy(
    name: str,
    history: List[frozenset],
    ses_history: Optional[List[List[frozenset]]],
    freq_window: int,
) -> frozenset:
    if name == "FreqHot8":
        return strategy_freq_hot(history, window=freq_window)
    if name == "FreqCold8":
        return strategy_freq_cold(history, window=freq_window)
    if name == "HotCold4+4":
        return strategy_hot_cold(history, window=freq_window)
    if name == "Decade8":
        return strategy_decade(history, window=freq_window)
    if name == "Delay8":
        return strategy_delay(history)
    if name == "NucleoPool":
        return strategy_nucleo_pool(history, ses_history, window=freq_window)
    raise ValueError(f"Strategia sconosciuta: {name}")


# ── Walk-forward backtest ─────────────────────────────────────────────────────

def run_backtest(
    df: pd.DataFrame,
    warmup: int = 50,
    freq_window: int = 100,
) -> dict[str, pd.DataFrame]:
    """
    Walk-forward: for each draw T0 (after warmup), generate 8-number candidates
    using each strategy (using only draws BEFORE T0), then check hits at T0..T+3.

    Returns dict strategy_name → DataFrame with columns:
        draw, hit_t0, hit_t1, hit_t2, hit_t3, best_hit, best_t, candidates
    """
    n = len(df)
    actuals: List[frozenset] = list(df["actual"])

    # Build sestine history (for NucleoPool)
    ses_cols = [f"Sestina {k}" for k in range(1, 6) if f"Sestina {k}" in df.columns]
    has_ses = len(ses_cols) == 5

    results: dict[str, list] = {s: [] for s in STRATEGY_NAMES}

    for i in range(warmup, n - 1):  # need at least T0, skip last row (no future)
        history_so_far = actuals[:i]  # strictly before T0
        ses_hist = None
        if has_ses:
            ses_hist = [
                [frozenset(df.iloc[j][sc]) for sc in ses_cols]
                for j in range(i)
            ]

        for sname in STRATEGY_NAMES:
            try:
                cands = _apply_strategy(sname, history_so_far, ses_hist, freq_window)
            except Exception:
                cands = frozenset()

            hits = []
            for t in range(4):
                j = i + t
                if j < n:
                    hits.append(len(cands & actuals[j]))
                else:
                    hits.append(None)

            valid_hits = [h for h in hits if h is not None]
            best_hit = max(valid_hits) if valid_hits else 0
            best_t = hits.index(best_hit) if best_hit in hits else 0

            results[sname].append({
                "draw": int(df.iloc[i]["draw"]),
                "hit_t0": hits[0],
                "hit_t1": hits[1] if len(hits) > 1 else None,
                "hit_t2": hits[2] if len(hits) > 2 else None,
                "hit_t3": hits[3] if len(hits) > 3 else None,
                "best_hit": best_hit,
                "best_t": best_t,
                "candidates": " ".join(f"{x:02d}" for x in sorted(cands)),
            })

    return {s: pd.DataFrame(v) for s, v in results.items()}


# ── Generate last-prediction candidates (for latest draw) ────────────────────

def generate_next_predictions(
    df: pd.DataFrame,
    freq_window: int,
    keep_top: int,
    ranking: pd.DataFrame,
) -> pd.DataFrame:
    """Generate candidate numbers for the NEXT draw using all strategies."""
    actuals: List[frozenset] = list(df["actual"])
    ses_cols = [f"Sestina {k}" for k in range(1, 6) if f"Sestina {k}" in df.columns]
    has_ses = len(ses_cols) == 5
    ses_hist = None
    if has_ses:
        ses_hist = [
            [frozenset(df.iloc[j][sc]) for sc in ses_cols]
            for j in range(len(df))
        ]

    last_draw = int(df.iloc[-1]["draw"])
    next_draw = last_draw + 1
    rows = []

    top_strategies = list(ranking["Strategia"].head(keep_top)) if len(ranking) else STRATEGY_NAMES[:keep_top]

    for sname in top_strategies:
        try:
            cands = _apply_strategy(sname, actuals, ses_hist, freq_window)
        except Exception:
            cands = frozenset()
        rows.append({
            "Draw target": next_draw,
            "Strategia": sname,
            "Predizione": " ".join(f"{x:02d}" for x in sorted(cands)),
            "N candidati": len(cands),
        })

    return pd.DataFrame(rows)


# ── Build event-gap tables ────────────────────────────────────────────────────

def compute_event_gaps(bt: pd.DataFrame, thresholds: list = None) -> pd.DataFrame:
    """For each strategy and threshold, compute gaps between events (best_hit >= thr)."""
    if thresholds is None:
        thresholds = [3, 4, 5]

    rows = []
    for sname in STRATEGY_NAMES:
        if sname not in bt:
            continue
        df_s = bt[sname]
        ev_draws = df_s["draw"].values
        for thr in thresholds:
            ev = df_s[df_s["best_hit"] >= thr]["draw"].values.astype(int)
            if len(ev) < 2:
                continue
            gaps = np.diff(ev)
            rows.append({
                "Strategia": sname,
                "Evento": f">={thr}",
                "N eventi": len(ev),
                "Gap min": int(gaps.min()),
                "Gap max": int(gaps.max()),
                "Gap medio": round(float(gaps.mean()), 1),
                "Gap mediana": float(np.median(gaps)),
                "Gap p25": float(np.percentile(gaps, 25)),
                "Gap p75": float(np.percentile(gaps, 75)),
                "Ultimo evento draw": int(ev[-1]),
                "Gap attuale": int(ev_draws[-1] - ev[-1]) if len(ev_draws) else 0,
            })
    return pd.DataFrame(rows)


def compute_range_positions(
    bt: dict[str, pd.DataFrame],
    event_gaps: pd.DataFrame,
) -> pd.DataFrame:
    """
    Determine current cycle position for each strategy+event combination.
    Maps gap percentile to an action recommendation (semaforo).
    """
    rows = []
    for _, gap_row in event_gaps.iterrows():
        sname = gap_row["Strategia"]
        evento = gap_row["Evento"]
        gap_att = float(gap_row["Gap attuale"])
        gap_med = float(gap_row["Gap medio"])
        p25 = float(gap_row["Gap p25"])
        p75 = float(gap_row["Gap p75"])
        n_ev = int(gap_row["N eventi"])

        # Percentile position of current gap
        if gap_att >= p75:
            azione = "attivare"
            fase = "oltre p75 — finestra attiva"
            semaforo = "verde"
        elif gap_att >= gap_med:
            azione = "monitorare forte"
            fase = "sopra mediana"
            semaforo = "blu"
        elif gap_att >= p25:
            azione = "preparare"
            fase = "nel quartile centrale"
            semaforo = "giallo"
        else:
            azione = "non inseguire"
            fase = "troppo presto"
            semaforo = "rosso"

        rows.append({
            "Evento": evento,
            "Strategia": sname,
            "N eventi": n_ev,
            "Gap attuale": int(gap_att),
            "Gap medio": gap_med,
            "Gap p25": p25,
            "Gap p75": p75,
            "Azione": azione,
            "Fase range": fase,
            "Semaforo": semaforo,
        })

    return pd.DataFrame(rows)


def compute_cycle_summary(bt: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Summary stats per strategy."""
    rows = []
    for sname in STRATEGY_NAMES:
        if sname not in bt:
            continue
        df_s = bt[sname]
        if len(df_s) == 0:
            continue
        valid = df_s[df_s["hit_t0"].notna()]
        row = {
            "Rank": 0,
            "Strategia": sname,
            "Draw valutati": len(valid),
            "Hit medio": round(float(df_s["best_hit"].mean()), 3),
            "Hit >=2": int((df_s["best_hit"] >= 2).sum()),
            "Hit >=3": int((df_s["best_hit"] >= 3).sum()),
            "Hit >=4": int((df_s["best_hit"] >= 4).sum()),
            "Hit >=5": int((df_s["best_hit"] >= 5).sum()),
            "Max Hit": int(df_s["best_hit"].max()),
            "Top N": 8,
        }
        rows.append(row)
    df_sum = pd.DataFrame(rows)
    # Rank by Hit >=3 desc, then Hit medio desc
    df_sum = df_sum.sort_values(["Hit >=3", "Hit medio"], ascending=False).reset_index(drop=True)
    df_sum["Rank"] = range(1, len(df_sum) + 1)
    return df_sum


def compute_cycle_windows(bt: dict[str, pd.DataFrame], event_gaps: pd.DataFrame) -> pd.DataFrame:
    """Per strategy+event: how long is the typical 'window' (gap within which event is expected)?"""
    rows = []
    for _, gap_row in event_gaps.iterrows():
        sname = gap_row["Strategia"]
        evento = gap_row["Evento"]
        rows.append({
            "Strategia": sname,
            "Evento": evento,
            "Finestra tipica (draw)": int(gap_row["Gap medio"]),
            "Finestra breve (p25)": int(gap_row["Gap p25"]),
            "Finestra lunga (p75)": int(gap_row["Gap p75"]),
            "Ultimo evento draw": int(gap_row["Ultimo evento draw"]),
            "Draw da aspettare": max(0, int(gap_row["Gap p25"]) - int(gap_row["Gap attuale"])),
        })
    return pd.DataFrame(rows)


# ── Write CSVs ───────────────────────────────────────────────────────────────

def write_csv(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False, encoding="utf-8")
    log.info("Scritto: %s (%d righe)", path.name, len(df))


def run_once(args: argparse.Namespace) -> None:
    log.info("=" * 60)
    log.info("Magic Lab run — %s", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    df = load_draws(limit=args.limit)
    n = len(df)
    log.info("Draw con numeri reali: %d", n)

    if n < args.warmup + 5:
        log.error("Dati insufficienti (%d draw). Warmup richiede almeno %d.", n, args.warmup)
        return

    # Run backtest
    log.info("Backtest walk-forward su %d draw (warmup=%d, freq_window=%d)…",
             n, args.warmup, args.freq_window)
    bt = run_backtest(df, warmup=args.warmup, freq_window=args.freq_window)

    # Strategy ranking
    ranking = compute_cycle_summary(bt)
    write_csv(ranking, OUT_DIR / "latest_strategy_ranking.csv")

    # Event gaps
    event_gaps = compute_event_gaps(bt)
    write_csv(event_gaps, OUT_DIR / "latest_event_gaps.csv")

    # Range positions (semaforo)
    range_pos = compute_range_positions(bt, event_gaps)
    write_csv(range_pos, OUT_DIR / "latest_range_positions.csv")

    # Cycle summary = same as ranking (already has full stats)
    write_csv(ranking, OUT_DIR / "latest_cycle_summary.csv")

    # Cycle windows
    cycle_windows = compute_cycle_windows(bt, event_gaps)
    write_csv(cycle_windows, OUT_DIR / "latest_cycle_windows.csv")

    # Next predictions
    next_preds = generate_next_predictions(df, args.freq_window, args.keep_top, ranking)
    write_csv(next_preds, OUT_DIR / "latest_next_predictions.csv")

    log.info("Magic Lab completato. Output in: %s", OUT_DIR)
    log.info(
        "Miglior strategia: %s (hit>=3: %d, hit medio: %.3f)",
        ranking.iloc[0]["Strategia"] if len(ranking) else "n/d",
        ranking.iloc[0]["Hit >=3"] if len(ranking) else 0,
        ranking.iloc[0]["Hit medio"] if len(ranking) else 0,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Magic Dream — background experiment lab")
    p.add_argument("--loop", action="store_true", help="Riesegui ogni --interval-minutes minuti")
    p.add_argument("--interval-minutes", type=int, default=180, help="Pausa tra run in loop")
    p.add_argument("--limit", type=int, default=0, help="Limita a ultimi N draw (0=tutti)")
    p.add_argument("--warmup", type=int, default=120, help="Draw iniziali di riscaldamento da saltare")
    p.add_argument("--freq-window", type=int, default=100, help="Finestra draw per calcolo frequenza")
    p.add_argument("--keep-top", type=int, default=5, help="Tieni top N strategie per prossima previsione")
    args = p.parse_args()

    # Attach file log
    try:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        logging.getLogger().addHandler(fh)
    except Exception:
        pass

    if args.loop:
        while True:
            try:
                run_once(args)
            except Exception as exc:
                log.error("Errore run: %s", exc, exc_info=True)
            log.info("Prossima run tra %d minuti.", args.interval_minutes)
            time.sleep(args.interval_minutes * 60)
    else:
        try:
            run_once(args)
        except Exception as exc:
            log.error("Errore fatale: %s", exc, exc_info=True)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
