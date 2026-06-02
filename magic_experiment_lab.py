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
    "Consensus8",
    "PoolTop8",
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

    # Keep sestine columns (NucleoPool) and ML Top-8 + pool column (PoolTop8)
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

    # ML Top-8 pool (App1 prediction) — used by PoolTop8 strategy
    if "ML Top-8" in df.columns:
        pool_vals = []
        ses_cols_present = [f"Sestina {k}" for k in range(1, 6) if f"Sestina {k}" in df.columns]
        for _, row in df.iterrows():
            if len(parse_nums(row.get("Numeri Reali", ""))) != 6:
                continue
            pool = parse_nums(row.get("ML Top-8", ""))
            for sc in ses_cols_present:
                pool = pool | parse_nums(row.get(sc, ""))
            pool_vals.append(pool)
        if pool_vals:
            result["pool"] = pool_vals

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


def strategy_consensus(history: List[frozenset], n: int = 8, window: int = 100) -> frozenset:
    """
    Vote across all 5 data-driven strategies.
    Each number gets 1 vote per strategy that selects it.
    Top-n numbers by vote count win; ties broken by recent frequency.
    """
    votes: Counter = Counter()
    for cands in [
        strategy_freq_hot(history, n=n, window=window),
        strategy_freq_cold(history, n=n, window=window),
        strategy_hot_cold(history, n=n, window=window),
        strategy_decade(history, n=n, window=window),
        strategy_delay(history, n=n),
    ]:
        for num in cands:
            votes[num] += 1
    recent = history[-window:] if len(history) >= window else history
    freq = Counter(num for draw in recent for num in draw)
    top = sorted(ALL_NUMS, key=lambda x: (-votes.get(x, 0), -freq.get(x, 0), x))[:n]
    return frozenset(top)


def strategy_pool_top8(
    history: List[frozenset],
    pool_history: Optional[List[frozenset]],
    n: int = 8,
    window: int = 100,
) -> frozenset:
    """
    Pick n numbers from the CURRENT App1 pool (ML Top-8 + Sestine union).
    Uses frequency analysis WITHIN the pool to rank candidates.
    Falls back to FreqHot8 if no pool data available.

    Rationale: App1's pool contained 5 winning numbers 35 times and all 6
    once in 7000+ draws. When playing within the pool we maximise the chance
    of hitting 5-6. Here we score each pool number by recency of appearance.
    """
    if not pool_history or len(pool_history) == 0:
        return strategy_freq_hot(history, n=n, window=window)

    current_pool = pool_history[-1]  # pool for the NEXT draw (last known)
    if len(current_pool) < n:
        # pool too small — supplement with FreqHot from ALL_NUMS outside pool
        extra = strategy_freq_hot(history, n=n * 2, window=window) - current_pool
        return current_pool | frozenset(sorted(extra)[:n - len(current_pool)])

    # Score each pool number: frequency in recent draws (higher = better)
    recent = history[-window:] if len(history) >= window else history
    freq = Counter(num for draw in recent for num in draw)
    delay_map = {}
    total = len(history)
    for pos, draw in enumerate(history):
        for num in draw:
            delay_map[num] = pos
    delay = {num: total - delay_map.get(num, -1) for num in current_pool}

    # Rank by: combined score of frequency + delay (balance hot/timing)
    top = sorted(current_pool, key=lambda x: -(freq.get(x, 0) * 0.5 + delay.get(x, 0) * 0.5))[:n]
    return frozenset(top)


def _apply_strategy(
    name: str,
    history: List[frozenset],
    ses_history: Optional[List[List[frozenset]]],
    freq_window: int,
    pool_history: Optional[List[frozenset]] = None,
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
    if name == "Consensus8":
        return strategy_consensus(history, window=freq_window)
    if name == "PoolTop8":
        return strategy_pool_top8(history, pool_history, window=freq_window)
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

    # Build pool history (ML Top-8 ∪ Sestine) for PoolTop8
    has_pool = "pool" in df.columns
    pool_list: List[frozenset] = list(df["pool"]) if has_pool else []

    results: dict[str, list] = {s: [] for s in STRATEGY_NAMES}

    for i in range(warmup, n - 1):  # need at least T0, skip last row (no future)
        history_so_far = actuals[:i]  # strictly before T0
        ses_hist = None
        if has_ses:
            ses_hist = [
                [frozenset(df.iloc[j][sc]) for sc in ses_cols]
                for j in range(i)
            ]
        pool_hist = pool_list[:i] if has_pool else None

        for sname in STRATEGY_NAMES:
            try:
                cands = _apply_strategy(sname, history_so_far, ses_hist, freq_window, pool_hist)
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
    pool_hist = list(df["pool"]) if "pool" in df.columns else None

    last_draw = int(df.iloc[-1]["draw"])
    next_draw = last_draw + 1
    rows = []

    # Always include PoolTop8 regardless of keep_top ranking
    all_strats = list(ranking["Strategia"].head(keep_top)) if len(ranking) else STRATEGY_NAMES[:keep_top]
    if "PoolTop8" not in all_strats and pool_hist:
        all_strats.append("PoolTop8")

    for sname in all_strats:
        try:
            cands = _apply_strategy(sname, actuals, ses_hist, freq_window, pool_hist)
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
        thresholds = [3, 4, 5, 6]

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
        n_valid = len(valid)
        t0_hits3 = int((valid["hit_t0"] >= 3).sum()) if n_valid else 0
        t0_hits4 = int((valid["hit_t0"] >= 4).sum()) if n_valid else 0
        row = {
            "Rank": 0,
            "Strategia": sname,
            "Draw valutati": n_valid,
            "Hit medio T0": round(float(valid["hit_t0"].mean()), 3) if n_valid else 0,
            "Hit >=3 T0": t0_hits3,
            "Hit >=3 T0 %": f"{t0_hits3/n_valid*100:.1f}%" if n_valid else "0%",
            "Hit >=4 T0": t0_hits4,
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
    # Rank by T0 Hit>=3 desc, then T0 hit medio desc
    df_sum = df_sum.sort_values(["Hit >=3 T0", "Hit medio T0"], ascending=False).reset_index(drop=True)
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


def save_backtest_detail(bt: dict[str, pd.DataFrame], out_dir: Path) -> None:
    """
    Save two files:
    1. latest_backtest_detail.csv  — one row per (draw × strategy): draw, strategia, hit_t0, best_hit, candidati
    2. latest_strategy_comparison.csv — pivot: one row per draw, one column per strategy (hit_t0)
    """
    rows = []
    for sname, df_s in bt.items():
        if df_s.empty:
            continue
        for _, row in df_s.iterrows():
            rows.append({
                "draw":      int(row["draw"]),
                "strategia": sname,
                "hit_t0":    int(row["hit_t0"]) if pd.notna(row["hit_t0"]) else 0,
                "hit_t1":    int(row["hit_t1"]) if pd.notna(row.get("hit_t1")) else None,
                "best_hit":  int(row["best_hit"]),
                "candidati": str(row["candidates"]),
            })

    if not rows:
        return

    detail = pd.DataFrame(rows).sort_values(["draw", "strategia"])
    write_csv(detail, out_dir / "latest_backtest_detail.csv")

    # Pivot: draw as index, strategy hit_t0 as columns
    pivot = detail.pivot_table(index="draw", columns="strategia", values="hit_t0", aggfunc="first")
    pivot.columns = [str(c) for c in pivot.columns]
    pivot = pivot.reset_index()

    # Add "winner" column (strategy with highest hit_t0 per draw; ties go to first alphabetically)
    strat_cols = [c for c in pivot.columns if c != "draw"]
    if strat_cols:
        pivot["vincitore"] = pivot[strat_cols].idxmax(axis=1)
        pivot["max_hit"] = pivot[strat_cols].max(axis=1)

    write_csv(pivot, out_dir / "latest_strategy_comparison.csv")


def bootstrap_golden_numbers(
    bt: dict[str, pd.DataFrame],
    draws_df: pd.DataFrame,
    n_iter: int = 500,
    sample_size: int = 100,
    min_hit: int = 4,
    out_dir: Path = OUT_DIR,
) -> None:
    """
    Bootstrap: trova i numeri che appaiono piu spesso nelle previsioni
    dei draw dove il sistema ha azzeccato min_hit+ numeri.

    Per ogni iterazione:
      - Campiona sample_size draw dal backtest storico
      - Identifica i draw con hit_t0 >= min_hit (qualsiasi strategia)
      - Per quei draw: interseca candidati con i numeri reali estratti
      - I numeri che compaiono piu spesso nell'intersezione = golden numbers

    Output: latest_golden_numbers.csv
    """
    # Mappa draw_number -> numeri reali estratti
    actual_by_draw: dict[int, frozenset] = {}
    for _, row in draws_df.iterrows():
        draw_num = int(row.get("draw", 0))
        nums = parse_nums(row.get("Numeri Reali", ""))
        if len(nums) == 6:
            actual_by_draw[draw_num] = nums

    if not actual_by_draw:
        log.warning("bootstrap_golden_numbers: nessun dato 'Numeri Reali' disponibile")
        return

    # Raccoglie tutti i record backtest in memoria
    records: list[dict] = []
    for sname, df_s in bt.items():
        if df_s.empty:
            continue
        for _, row in df_s.iterrows():
            draw_num = int(row["draw"])
            if draw_num not in actual_by_draw:
                continue
            hit = int(row["hit_t0"]) if pd.notna(row.get("hit_t0")) else 0
            cands = parse_nums(str(row.get("candidates", "")))
            records.append({
                "draw":     draw_num,
                "strategy": sname,
                "candidates": cands,
                "hit_t0":   hit,
            })

    if not records:
        log.warning("bootstrap_golden_numbers: nessun record backtest utilizzabile")
        return

    all_draws = sorted({r["draw"] for r in records})
    if len(all_draws) < sample_size:
        log.warning("bootstrap_golden_numbers: solo %d draw disponibili, ne servono %d",
                    len(all_draws), sample_size)
        sample_size = len(all_draws)

    rng = np.random.default_rng(42)

    # Contatori globali
    confirmed_count: Counter = Counter()  # predetto E uscito in draw con 4+ hit
    predicted_count: Counter = Counter()  # predetto in draw con 4+ hit (qualsiasi esito)

    for _ in range(n_iter):
        sampled = set(rng.choice(all_draws, size=sample_size, replace=False).tolist())

        # Draw con 4+ hit in questo campione
        high_hit: set[int] = set()
        for r in records:
            if r["draw"] in sampled and r["hit_t0"] >= min_hit:
                high_hit.add(r["draw"])

        if not high_hit:
            continue

        # Per i draw high-hit: conta numeri predetti e confermati
        for r in records:
            if r["draw"] not in high_hit:
                continue
            actual = actual_by_draw[r["draw"]]
            for n in r["candidates"]:
                predicted_count[n] += 1
            for n in r["candidates"] & actual:
                confirmed_count[n] += 1

    if not confirmed_count:
        log.warning("bootstrap_golden_numbers: nessun numero confermato (forse troppo pochi draw con %d+ hit)", min_hit)
        return

    rows_out = []
    for num in range(1, 50):
        conf = confirmed_count.get(num, 0)
        pred = predicted_count.get(num, 0)
        rate = round(conf / pred, 4) if pred > 0 else 0.0
        rows_out.append({
            "numero":           num,
            "volte_confermato": conf,
            "volte_predetto":   pred,
            "tasso_conferma":   rate,
        })

    df_out = pd.DataFrame(rows_out).sort_values("volte_confermato", ascending=False).reset_index(drop=True)
    df_out["rank"] = range(1, len(df_out) + 1)

    write_csv(df_out, out_dir / "latest_golden_numbers.csv")

    top4 = df_out.head(4)["numero"].tolist()
    log.info(
        "Golden numbers (top 4 su %d iter × %d draw, min_hit=%d): %s",
        n_iter, sample_size, min_hit, top4,
    )


def save_systematic_windows_excel(
    bt: dict[str, pd.DataFrame],
    draws_df: pd.DataFrame,
    window_size: int = 100,
    min_hit: int = 4,
    out_dir: Path = OUT_DIR,
) -> None:
    """
    Divide tutti i draw in finestre consecutive di window_size draw.
    Per ogni finestra: trova draw con 4+ hit, interseca candidati con numeri reali,
    conta quali numeri sono stati correttamente predetti piu spesso.

    Output Excel (golden_analysis.xlsx):
      Foglio "Finestre"      : una riga per finestra — draw range, hit count, top numeri
      Foglio "Numeri_Ranking": ogni numero 1-49 ranked per frequenza nelle finestre
      Foglio "Coppie"        : coppie di numeri che co-appaiono piu spesso nei top-4 per finestra
      Foglio "Golden6"       : raccomandazione finale: top 4 + coppia residua = 6 numeri
    """
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        log.warning("openpyxl non installato — salto Excel. Installa con: pip install openpyxl")
        return

    # ── Lookup: draw_num -> numeri reali ─────────────────────────────────────
    actual_by_draw: dict[int, frozenset] = {}
    for _, row in draws_df.iterrows():
        d = int(row.get("draw", 0))
        nums = parse_nums(row.get("Numeri Reali", ""))
        if len(nums) == 6:
            actual_by_draw[d] = nums

    if not actual_by_draw:
        log.warning("save_systematic_windows_excel: nessun dato 'Numeri Reali'")
        return

    # ── Record dal backtest ──────────────────────────────────────────────────
    records: list[dict] = []
    for sname, df_s in bt.items():
        if df_s.empty:
            continue
        for _, row in df_s.iterrows():
            d = int(row["draw"])
            if d not in actual_by_draw:
                continue
            hit = int(row["hit_t0"]) if pd.notna(row.get("hit_t0")) else 0
            cands = parse_nums(str(row.get("candidates", "")))
            if cands:
                records.append({"draw": d, "strategy": sname, "candidates": cands, "hit_t0": hit})

    if not records:
        log.warning("save_systematic_windows_excel: nessun record backtest")
        return

    all_draws = sorted({r["draw"] for r in records})
    n_draws = len(all_draws)
    log.info("Finestre sistematiche: %d draw totali, finestre da %d = %d finestre",
             n_draws, window_size, n_draws // window_size)

    # ── Raggruppa in finestre consecutive ─────────────────────────────────────
    windows = []
    for w_idx in range(n_draws // window_size):
        w_draws = set(all_draws[w_idx * window_size: (w_idx + 1) * window_size])
        w_recs = [r for r in records if r["draw"] in w_draws]

        # Draw con 4+ hit in questa finestra
        high_hit_draws = {r["draw"] for r in w_recs if r["hit_t0"] >= min_hit}
        n_high = len(high_hit_draws)

        # Numeri confermati (predetti E usciti) nei draw high-hit
        confirmed: Counter = Counter()
        for r in w_recs:
            if r["draw"] in high_hit_draws:
                actual = actual_by_draw[r["draw"]]
                for n in r["candidates"] & actual:
                    confirmed[n] += 1

        top_nums = [n for n, _ in confirmed.most_common(8)]
        top4_w = top_nums[:4]
        top8_w = top_nums[:8]

        windows.append({
            "finestra":       w_idx + 1,
            "draw_start":     min(w_draws),
            "draw_end":       max(w_draws),
            "draw_totali":    len(w_draws),
            "draw_4plus_hit": n_high,
            "top1": top4_w[0] if len(top4_w) > 0 else "",
            "top2": top4_w[1] if len(top4_w) > 1 else "",
            "top3": top4_w[2] if len(top4_w) > 2 else "",
            "top4": top4_w[3] if len(top4_w) > 3 else "",
            "top5": top8_w[4] if len(top8_w) > 4 else "",
            "top6": top8_w[5] if len(top8_w) > 5 else "",
            "top7": top8_w[6] if len(top8_w) > 6 else "",
            "top8": top8_w[7] if len(top8_w) > 7 else "",
            "confirmed_dict": dict(confirmed),
        })

    if not windows:
        log.warning("Nessuna finestra creata")
        return

    # ── Foglio 1: Finestre ────────────────────────────────────────────────────
    df_finestre = pd.DataFrame([{k: v for k, v in w.items() if k != "confirmed_dict"}
                                 for w in windows])

    # ── Foglio 2: Ranking numeri globale ─────────────────────────────────────
    # conta in quante finestre ogni numero e' nel top-4 confermato
    global_in_top4: Counter = Counter()
    global_in_top8: Counter = Counter()
    global_confirmed: Counter = Counter()

    for w in windows:
        top4_w = [w[f"top{i}"] for i in range(1, 5) if w[f"top{i}"] != ""]
        top8_w = [w[f"top{i}"] for i in range(1, 9) if w[f"top{i}"] != ""]
        for n in top4_w:
            global_in_top4[n] += 1
        for n in top8_w:
            global_in_top8[n] += 1
        for n, c in w["confirmed_dict"].items():
            global_confirmed[n] += c

    rows_rank = []
    for num in range(1, 50):
        rows_rank.append({
            "numero":             num,
            "finestre_in_top4":   global_in_top4.get(num, 0),
            "finestre_in_top8":   global_in_top8.get(num, 0),
            "totale_confermato":  global_confirmed.get(num, 0),
        })
    df_numeri = pd.DataFrame(rows_rank).sort_values("finestre_in_top4", ascending=False).reset_index(drop=True)
    df_numeri["rank"] = range(1, len(df_numeri) + 1)

    # ── Foglio 3: Coppie (co-occorrenze nel top-8 per finestra) ──────────────
    pair_count: Counter = Counter()
    for w in windows:
        top8_w = [w[f"top{i}"] for i in range(1, 9) if w[f"top{i}"] != ""]
        for i in range(len(top8_w)):
            for j in range(i + 1, len(top8_w)):
                pair = tuple(sorted([top8_w[i], top8_w[j]]))
                pair_count[pair] += 1

    rows_coppie = []
    for (a, b), cnt in pair_count.most_common(50):
        rows_coppie.append({"num_a": a, "num_b": b, "finestre_insieme": cnt})
    df_coppie = pd.DataFrame(rows_coppie) if rows_coppie else pd.DataFrame()

    # ── Foglio 4: Golden 6 ────────────────────────────────────────────────────
    top4_global = df_numeri.head(4)["numero"].tolist()
    # Coppia residua: tra i numeri non nel top4, quale coppia co-appare piu con top4?
    coppia_score: Counter = Counter()
    for (a, b), cnt in pair_count.items():
        a_in = a in top4_global
        b_in = b in top4_global
        if a_in and not b_in:
            coppia_score[b] += cnt
        elif b_in and not a_in:
            coppia_score[a] += cnt
        elif not a_in and not b_in:
            coppia_score[a] += cnt * 0.3
            coppia_score[b] += cnt * 0.3

    top2_residui = [n for n, _ in coppia_score.most_common(6) if n not in top4_global][:2]
    golden6 = sorted(top4_global + top2_residui)

    df_golden = pd.DataFrame([
        {"posizione": i + 1, "numero": n,
         "ruolo": "CORE (top4)" if n in top4_global else "COPPIA RESIDUA"}
        for i, n in enumerate(golden6)
    ])

    # ── Scrivi Excel ──────────────────────────────────────────────────────────
    out_path = out_dir / "golden_analysis.xlsx"
    try:
        with pd.ExcelWriter(str(out_path), engine="openpyxl") as writer:
            df_finestre.to_excel(writer, sheet_name="Finestre", index=False)
            df_numeri.to_excel(writer, sheet_name="Numeri_Ranking", index=False)
            if not df_coppie.empty:
                df_coppie.to_excel(writer, sheet_name="Coppie", index=False)
            df_golden.to_excel(writer, sheet_name="Golden6", index=False)
        log.info("Excel salvato: %s", out_path)
    except Exception as e:
        log.error("Errore scrittura Excel: %s", e)
        return

    log.info("Golden 6 (top4 + coppia residua): %s", golden6)
    log.info("Top 4 global: %s | Coppia: %s", top4_global, top2_residui)


def run_deep_analysis(args: argparse.Namespace) -> None:
    """
    Modalita' --deep-analysis — RITORNO AL FUTURO:

    Concetto: per ogni shift L in LOOKBACKS, simula "essere indietro di L draw"
    su OGNI estrazione della storia (1957 → oggi). Per ogni draw N:
      - usa le draw [N-L : N-1] come finestra di addestramento
      - predice draw N con tutte le 8 strategie
      - confronta con i numeri reali di draw N (noti)
    Risultato: per ogni shift, sappiamo quante volte avremmo indovinato 4+ numeri.

    "Ritorno al futuro" recente: stesso processo ma SOLO sugli ultimi 100 draw.
    Lo shift con la miglior performance recente e' quello da usare STASERA.

    Output: golden_analysis.xlsx con 8 fogli:
      1. Grid_Hits      — ogni draw × ogni shift → hit_t0 (matrice completa)
      2. Shift_Ranking  — shift ordinati per performance globale E recente
      3. Finestre_100   — ogni 100 draw: shift ottimale + top 8 numeri confermati
      4. Numeri_Ranking — ogni numero 1-49 ranked per volte_confermato nei draw 4+
      5. Coppie         — top 50 coppie co-confermate nelle finestre ad alto hit
      6. Golden6        — top 4 numeri + coppia residua = 6 numeri convergenti
      7. RitornoAlFuturo— per ogni shift: performance sugli ULTIMI 100 draw (recente)
      8. Stasera        — previsione di stasera con lo shift ottimale recente,
                          tutti e 8 i numeri per ogni strategia + Golden6
    """
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        log.error("openpyxl non installato. Installa con: pip install openpyxl")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_draws(limit=args.limit)
    n = len(df)
    log.info("Deep analysis (Ritorno al Futuro) — %d draw totali", n)

    if n < 200:
        log.error("Servono almeno 200 draw.")
        return

    LOOKBACKS   = [80, 90, 100, 110, 120, 130, 150, 175, 200]
    WARMUP      = 60
    RECENT_N    = 100   # ultimi N draw per validazione "ritorno al futuro recente"
    MIN_HIT     = 4

    # ── Mappa draw_num -> numeri reali ────────────────────────────────────────
    # load_draws() restituisce sempre la colonna "actual" (frozenset), non "Numeri Reali"
    actual_by_draw: dict[int, frozenset] = {}
    for _, row in df.iterrows():
        d = int(row.get("draw", 0))
        act = row.get("actual", None)
        if isinstance(act, frozenset) and len(act) == 6:
            actual_by_draw[d] = act
        else:
            # fallback per DataFrame caricati direttamente da Excel con colonna "Numeri Reali"
            nums = parse_nums(row.get("Numeri Reali", ""))
            if len(nums) == 6:
                actual_by_draw[d] = nums

    # ── Esegui backtest per ogni shift (UNA SOLA VOLTA per shift) ────────────
    log.info("Fase 1/3: backtest per %d shift...", len(LOOKBACKS))
    shift_results: dict[int, dict[int, dict]] = {}

    for lb in LOOKBACKS:
        log.info("  Shift %d draw...", lb)
        bt = run_backtest(df, warmup=WARMUP, freq_window=lb)
        per_draw: dict[int, dict] = {}
        for sname, df_s in bt.items():
            if df_s.empty:
                continue
            for _, row in df_s.iterrows():
                d = int(row["draw"])
                hit = int(row["hit_t0"]) if pd.notna(row.get("hit_t0")) else 0
                cands_str = str(row.get("candidates", ""))
                per_draw.setdefault(d, {})
                per_draw[d][f"hit_{sname}"] = hit
                per_draw[d][f"cands_{sname}"] = cands_str
        shift_results[lb] = per_draw

    all_draws = sorted(
        set(d for per in shift_results.values() for d in per)
        & set(actual_by_draw)
    )
    log.info("Draw con dati completi: %d", len(all_draws))
    recent_draws = set(all_draws[-RECENT_N:]) if len(all_draws) >= RECENT_N else set(all_draws)

    # ────────────────── FOGLIO 1: Grid_Hits ───────────────────────────────────
    # Ogni draw × ogni shift → hit_t0 massimo + per-strategia
    log.info("Fase 2/3: costruzione fogli Excel...")
    grid_rows = []
    for d in all_draws:
        row_d: dict = {
            "draw":         d,
            "numeri_reali": " ".join(f"{x:02d}" for x in sorted(actual_by_draw[d])),
            "recente":      "SI" if d in recent_draws else "",
        }
        best_hit_d = 0
        best_shift_d = 0
        for lb in LOOKBACKS:
            per = shift_results.get(lb, {}).get(d, {})
            strat_hits = {s: per[f"hit_{s}"] for s in STRATEGY_NAMES if f"hit_{s}" in per}
            max_hit = max(strat_hits.values(), default=0)
            row_d[f"sh{lb}_maxhit"] = max_hit
            # migliore strategia per questo shift su questo draw
            best_s = max(strat_hits, key=strat_hits.get) if strat_hits else ""
            row_d[f"sh{lb}_bestStrat"] = best_s
            if max_hit > best_hit_d:
                best_hit_d = max_hit
                best_shift_d = lb
        row_d["best_hit"]   = best_hit_d
        row_d["best_shift"] = best_shift_d
        grid_rows.append(row_d)

    df_grid = pd.DataFrame(grid_rows)
    total_draws = len(all_draws)

    # ────────────────── FOGLIO 2: Shift_Ranking ────────────────────────────────
    shift_rank_rows = []
    for lb in LOOKBACKS:
        col = f"sh{lb}_maxhit"
        if col not in df_grid.columns:
            continue
        vals_all    = df_grid[col]
        vals_recent = df_grid[df_grid["recente"] == "SI"][col]

        shift_rank_rows.append({
            "shift_draw":        lb,
            "draw_totali":       total_draws,
            "hit_medio_globale": round(vals_all.mean(), 4),
            "pct_3+_globale":    f"{(vals_all >= 3).mean()*100:.2f}%",
            "pct_4+_globale":    f"{(vals_all >= 4).mean()*100:.2f}%",
            "draw_4+_globale":   int((vals_all >= 4).sum()),
            "draw_5+_globale":   int((vals_all >= 5).sum()),
            "draw_6_globale":    int((vals_all == 6).sum()),
            # RECENTE (ultimi 100 draw) = "ritorno al futuro" recente
            "hit_medio_recente": round(vals_recent.mean(), 4) if len(vals_recent) else 0,
            "pct_4+_recente":    f"{(vals_recent >= 4).mean()*100:.2f}%" if len(vals_recent) else "?",
            "draw_4+_recente":   int((vals_recent >= 4).sum()) if len(vals_recent) else 0,
        })

    df_shift_rank = pd.DataFrame(shift_rank_rows).sort_values("draw_4+_recente", ascending=False)
    best_shift_recent = int(df_shift_rank.iloc[0]["shift_draw"]) if len(df_shift_rank) else 100
    best_shift_global = int(
        df_shift_rank.sort_values("draw_4+_globale", ascending=False).iloc[0]["shift_draw"]
    ) if len(df_shift_rank) else 100
    log.info("Shift ottimale RECENTE: %d | GLOBALE: %d", best_shift_recent, best_shift_global)

    # ────────────────── FOGLIO 3: Finestre_100 ─────────────────────────────────
    fin_rows = []
    for w_idx in range(len(all_draws) // 100):
        w_draws = all_draws[w_idx * 100: (w_idx + 1) * 100]
        w_set   = set(w_draws)
        w_df    = df_grid[df_grid["draw"].isin(w_set)]

        # Shift ottimale per questa finestra
        best_shift_w, best_count_w = 0, -1
        for lb in LOOKBACKS:
            col = f"sh{lb}_maxhit"
            if col in w_df.columns:
                cnt = int((w_df[col] >= MIN_HIT).sum())
                if cnt > best_count_w:
                    best_count_w, best_shift_w = cnt, lb

        # Numeri confermati (predetti E usciti) con lo shift ottimale
        confirmed_w: Counter = Counter()
        for d in w_draws:
            per = shift_results.get(best_shift_w, {}).get(d, {})
            strat_hits = {s: per[f"hit_{s}"] for s in STRATEGY_NAMES if f"hit_{s}" in per}
            if max(strat_hits.values(), default=0) < MIN_HIT:
                continue
            actual = actual_by_draw.get(d, frozenset())
            for s in STRATEGY_NAMES:
                cands = parse_nums(per.get(f"cands_{s}", ""))
                for nn in cands & actual:
                    confirmed_w[nn] += 1

        top8_w = [n for n, _ in confirmed_w.most_common(8)]
        fin_row = {
            "finestra":           w_idx + 1,
            "draw_start":         w_draws[0],
            "draw_end":           w_draws[-1],
            "shift_ottimale":     best_shift_w,
            "draw_con_4+":        best_count_w,
            "pct_4+":             f"{best_count_w / 100 * 100:.1f}%",
            "e_finestra_recente": "SI" if any(d in recent_draws for d in w_draws) else "",
        }
        for i, nn in enumerate(top8_w, 1):
            fin_row[f"num_{i}"] = nn
        fin_rows.append(fin_row)

    df_finestre = pd.DataFrame(fin_rows)

    # ────────────────── FOGLIO 4: Numeri_Ranking ───────────────────────────────
    # Costruito dall'unico set di shift_results (no doppio backtest)
    global_confirmed: Counter = Counter()
    global_predicted: Counter = Counter()

    for lb in LOOKBACKS:
        for d, per in shift_results[lb].items():
            actual = actual_by_draw.get(d, frozenset())
            strat_hits = {s: per[f"hit_{s}"] for s in STRATEGY_NAMES if f"hit_{s}" in per}
            max_hit = max(strat_hits.values(), default=0)
            for s in STRATEGY_NAMES:
                cands = parse_nums(per.get(f"cands_{s}", ""))
                for nn in cands:
                    global_predicted[nn] += 1
                if max_hit >= MIN_HIT:
                    for nn in cands & actual:
                        global_confirmed[nn] += 1

    num_rows = []
    for num in range(1, 50):
        conf = global_confirmed.get(num, 0)
        pred = global_predicted.get(num, 0)
        num_rows.append({
            "rank":              0,
            "numero":            num,
            "volte_confermato":  conf,
            "volte_predetto":    pred,
            "tasso_conferma_%":  round(conf / pred * 100, 2) if pred > 0 else 0,
            "spiegazione":       (
                f"Su {pred} volte predetto da qualche strategia, "
                f"{conf} volte era tra i 4+ numeri realmente usciti"
            ),
        })
    df_numeri = (
        pd.DataFrame(num_rows)
        .sort_values("volte_confermato", ascending=False)
        .reset_index(drop=True)
    )
    df_numeri["rank"] = range(1, len(df_numeri) + 1)
    # riordina colonne
    df_numeri = df_numeri[["rank", "numero", "volte_confermato", "volte_predetto",
                             "tasso_conferma_%", "spiegazione"]]

    # ────────────────── FOGLIO 5: Coppie ──────────────────────────────────────
    pair_count: Counter = Counter()
    for row_f in fin_rows:
        nums_w = [row_f.get(f"num_{i}") for i in range(1, 9) if row_f.get(f"num_{i}")]
        for i in range(len(nums_w)):
            for j in range(i + 1, len(nums_w)):
                pair_count[tuple(sorted([nums_w[i], nums_w[j]]))] += 1

    df_coppie = pd.DataFrame([
        {
            "num_a": a, "num_b": b,
            "finestre_insieme": cnt,
            "pct_finestre": f"{cnt / len(fin_rows) * 100:.1f}%" if fin_rows else "?",
            "spiegazione": f"La coppia {a}-{b} appare insieme nei top-8 di {cnt} finestre su {len(fin_rows)}",
        }
        for (a, b), cnt in pair_count.most_common(50)
    ]) if pair_count else pd.DataFrame()

    # ────────────────── FOGLIO 6: Golden6 ─────────────────────────────────────
    top4 = [int(df_numeri.iloc[i]["numero"]) for i in range(min(4, len(df_numeri)))]
    coppia_score: Counter = Counter()
    for (a, b), cnt in pair_count.items():
        a_in, b_in = a in top4, b in top4
        if a_in and not b_in:
            coppia_score[b] += cnt
        elif b_in and not a_in:
            coppia_score[a] += cnt
        elif not a_in and not b_in:
            coppia_score[a] += cnt * 0.3
            coppia_score[b] += cnt * 0.3

    top2 = [n for n, _ in coppia_score.most_common(10) if n not in top4][:2]
    golden6 = sorted(top4 + top2)

    df_golden = pd.DataFrame([
        {
            "posizione":             i + 1,
            "numero":                n,
            "ruolo":                 "CORE top-4" if n in top4 else "COPPIA RESIDUA",
            "shift_ottimale_recente": best_shift_recent,
            "shift_ottimale_globale": best_shift_global,
            "spiegazione": (
                f"Numero {n} confermato {global_confirmed.get(n, 0)} volte "
                f"nei draw con 4+ hit su tutti gli shift e tutte le finestre storiche"
                if n in top4
                else
                f"Numero {n} co-appare con il top-4 in piu finestre ad alto rendimento"
            ),
        }
        for i, n in enumerate(golden6)
    ])

    # ────────────────── FOGLIO CONVERGENZA ────────────────────────────────────
    # Quante delle ~73 finestre da 100 draw includono ogni numero nel top-8/top-4?
    # Metrica BINARIA per finestra (0 o 1 per finestra, poi somma) = convergenza storica.
    # Concetto "ritorno al futuro": guardando tutti i 57 anni, quali numeri appaiono
    # COSTANTEMENTE nelle finestre dove la strategia indovina 4+ numeri?
    # Questi numeri sono i candidati con la massima certezza storica.
    from_top8_windows: Counter = Counter()
    from_top4_windows: Counter = Counter()
    for row_f in fin_rows:
        top8_w = [row_f.get(f"num_{i}") for i in range(1, 9) if row_f.get(f"num_{i}")]
        top4_w = top8_w[:4]
        for nn in top8_w:
            from_top8_windows[nn] += 1
        for nn in top4_w:
            from_top4_windows[nn] += 1

    n_finestre = len(fin_rows)
    conv_rows = []
    for num in range(1, 50):
        n8 = from_top8_windows.get(num, 0)
        n4 = from_top4_windows.get(num, 0)
        p8 = round(n8 / n_finestre * 100, 1) if n_finestre else 0
        p4 = round(n4 / n_finestre * 100, 1) if n_finestre else 0
        if p8 >= 50:
            stars = "CERTISSIMO"
        elif p8 >= 30:
            stars = "MOLTO STABILE"
        elif p8 >= 15:
            stars = "STABILE"
        else:
            stars = "variabile"
        conv_rows.append({
            "rank":             0,
            "numero":           num,
            "finestre_top8":    n8,
            "finestre_top4":    n4,
            "pct_top8_%":       p8,
            "pct_top4_%":       p4,
            "convergenza":      stars,
            "spiegazione": (
                f"Numero {num}: nel top-8 in {n8}/{n_finestre} finestre ({p8}%), "
                f"nel top-4 in {n4} finestre ({p4}%). "
                + ("← ALTA CONVERGENZA STORICA" if p8 >= 30 else "")
            ),
        })

    df_convergenza = (
        pd.DataFrame(conv_rows)
        .sort_values(["finestre_top8", "finestre_top4"], ascending=False)
        .reset_index(drop=True)
    )
    df_convergenza["rank"] = range(1, len(df_convergenza) + 1)

    top4_conv = [int(df_convergenza.iloc[i]["numero"]) for i in range(min(4, len(df_convergenza)))]
    top6_conv = [int(df_convergenza.iloc[i]["numero"]) for i in range(min(6, len(df_convergenza)))]
    log.info("Top 4 convergenza storica (%d finestre, 57 anni): %s", n_finestre, top4_conv)
    log.info("Top 6 convergenza: %s", top6_conv)

    # ────────────────── FOGLIO Kumulacja ──────────────────────────────────────
    # Kumulacja = draw polacchi dove nessuno vince il jackpot (accumulazione).
    # Se la colonna 'kumulacja' e' presente nel dataset, analisi separata.
    # Altrimenti: foglio con istruzioni per aggiungere i dati.
    kumulacja_col = None
    for col_k in ["kumulacja", "Kumulacja", "KUMULACJA", "jackpot", "accumulation"]:
        if col_k in df.columns:
            kumulacja_col = col_k
            break

    if kumulacja_col:
        # Analisi separata draw kumulacja vs normali
        kum_mask = df[kumulacja_col].astype(str).str.strip().isin(["1", "True", "true", "SI", "si", "yes"])
        kum_draws = set(df[kum_mask]["draw"].astype(int).tolist())
        normal_draws = set(all_draws) - kum_draws
        kum_rows_data = []
        for lb in LOOKBACKS:
            col_g = f"sh{lb}_maxhit"
            if col_g not in df_grid.columns:
                continue
            kum_df = df_grid[df_grid["draw"].isin(kum_draws)][col_g]
            norm_df = df_grid[df_grid["draw"].isin(normal_draws)][col_g]
            kum_rows_data.append({
                "shift_draw":       lb,
                "draw_kumulacja":   len(kum_df),
                "draw_normali":     len(norm_df),
                "hit_medio_kum":    round(kum_df.mean(), 4) if len(kum_df) else 0,
                "hit_medio_norm":   round(norm_df.mean(), 4) if len(norm_df) else 0,
                "draw_4+_kum":      int((kum_df >= 4).sum()) if len(kum_df) else 0,
                "draw_4+_norm":     int((norm_df >= 4).sum()) if len(norm_df) else 0,
                "pct_4+_kum":       f"{(kum_df >= 4).mean()*100:.2f}%" if len(kum_df) else "?",
                "pct_4+_norm":      f"{(norm_df >= 4).mean()*100:.2f}%" if len(norm_df) else "?",
                "kumulacja_migliore": "SI" if (
                    len(kum_df) > 0 and len(norm_df) > 0 and
                    (kum_df >= 4).mean() > (norm_df >= 4).mean()
                ) else "",
            })
        df_kumulacja = pd.DataFrame(kum_rows_data).sort_values("draw_4+_kum", ascending=False)
        log.info("Kumulacja: %d draw kumulacja, %d normali analizzati", len(kum_draws), len(normal_draws))
    else:
        # Foglio informativo: come aggiungere dati kumulacja
        df_kumulacja = pd.DataFrame([
            {"campo": "KUMULACJA — Analisi jackpot accumulation",
             "valore": ""},
            {"campo": "Dati kumulacja non trovati nel dataset",
             "valore": "Aggiungi una colonna 'kumulacja' al tuo file lotto_draws.csv"},
            {"campo": "Valori attesi nella colonna",
             "valore": "1 = draw kumulacja (jackpot accumulato), 0 = draw normale"},
            {"campo": "Fonte dati kumulacja storici",
             "valore": "Disponibili su lotto.pl / totalilotto.pl nella sezione archivio"},
            {"campo": "Dopo aver aggiunto i dati",
             "valore": "Riesegui DEEP_ANALYSIS.bat — verra' generato il foglio kumulacja completo"},
            {"campo": "Cosa mostrera' il foglio kumulacja",
             "valore": "Performance per shift separata: draw kumulacja vs draw normali"},
            {"campo": "Ipotesi statistica",
             "valore": "I draw kumulacja possono avere distribuzioni diverse (jackpot alto = piu giocatori = pattern diversi)"},
            {"campo": "Golden numbers kumulacja",
             "valore": "I numeri che appaiono SOLO nelle kumulacja ad alto rendimento"},
        ])

    # ────────────────── FOGLIO 7: RitornoAlFuturo ─────────────────────────────
    # Per ogni shift: prestazioni SOLO sugli ultimi RECENT_N draw
    # = "torna indietro di RECENT_N draw, come avresti predetto?"
    raf_rows = []
    for lb in LOOKBACKS:
        col = f"sh{lb}_maxhit"
        if col not in df_grid.columns:
            continue
        rec_df = df_grid[df_grid["recente"] == "SI"][col]
        if len(rec_df) == 0:
            continue
        draw_4 = int((rec_df >= 4).sum())
        draw_5 = int((rec_df >= 5).sum())
        draw_6 = int((rec_df == 6).sum())
        raf_rows.append({
            "shift_draw":      lb,
            "draw_analizzati": len(rec_df),
            "hit_medio":       round(rec_df.mean(), 4),
            "draw_3+":         int((rec_df >= 3).sum()),
            "draw_4+":         draw_4,
            "draw_5+":         draw_5,
            "draw_6":          draw_6,
            "pct_4+":          f"{draw_4 / len(rec_df) * 100:.2f}%",
            "migliore_per_stasera": "⭐ USARE STASERA" if lb == best_shift_recent else "",
            "spiegazione": (
                f"Con shift={lb}, negli ultimi {RECENT_N} draw la strategia ha "
                f"indovinato 4+ numeri {draw_4} volte ({draw_4/len(rec_df)*100:.1f}%). "
                + ("← SHIFT OTTIMALE per stasera" if lb == best_shift_recent else "")
            ),
        })
    df_raf = pd.DataFrame(raf_rows).sort_values("draw_4+", ascending=False)

    # ────────────────── FOGLIO 8: Stasera ─────────────────────────────────────
    log.info("Fase 3/3: previsione stasera con shift ottimale recente=%d...", best_shift_recent)
    bt_tonight = run_backtest(df, warmup=WARMUP, freq_window=best_shift_recent)
    ranking_tonight = compute_cycle_summary(bt_tonight)
    pred_tonight = generate_next_predictions(df, best_shift_recent, len(STRATEGY_NAMES), ranking_tonight)

    stasera_rows = []
    consensus_score: Counter = Counter()
    for _, row_p in pred_tonight.iterrows():
        strat = str(row_p.get("Strategia", ""))
        pred_str = str(row_p.get("Predizione", ""))
        nums = list(parse_nums(pred_str))
        for nn in nums:
            consensus_score[nn] += 1
        stasera_rows.append({
            "strategia":  strat,
            "numeri":     pred_str,
            "n_numeri":   len(nums),
            "shift_usato": best_shift_recent,
            "motivo_shift": (
                f"Shift {best_shift_recent} draw = shift con piu draw 4+ "
                f"negli ultimi {RECENT_N} draw (validazione recente)"
            ),
        })

    # Top 4 + coppia stasera per consenso
    top4_s = [n for n, _ in consensus_score.most_common(4)]
    top6_s = [n for n, _ in consensus_score.most_common(6)]

    stasera_rows.append({"strategia": "---", "numeri": "", "n_numeri": 0,
                          "shift_usato": "", "motivo_shift": ""})
    stasera_rows.append({
        "strategia":    "GOLDEN4_STASERA",
        "numeri":       " ".join(f"{n:02d}" for n in sorted(top4_s)),
        "n_numeri":     4,
        "shift_usato":  best_shift_recent,
        "motivo_shift": "Top 4 per voti di consenso tra tutte le strategie",
    })
    stasera_rows.append({
        "strategia":    "GOLDEN6_STASERA",
        "numeri":       " ".join(f"{n:02d}" for n in sorted(top6_s)),
        "n_numeri":     6,
        "shift_usato":  best_shift_recent,
        "motivo_shift": "Top 6 per voti di consenso — previsione completa",
    })
    stasera_rows.append({
        "strategia":    "GOLDEN6_STORICO",
        "numeri":       " ".join(f"{n:02d}" for n in golden6),
        "n_numeri":     6,
        "shift_usato":  best_shift_global,
        "motivo_shift": "Top 4 confermati su 57 anni di storia + coppia residua",
    })
    stasera_rows.append({"strategia": "---", "numeri": "", "n_numeri": 0,
                          "shift_usato": "", "motivo_shift": ""})
    stasera_rows.append({
        "strategia":    "GOLDEN4_CONVERGENZA",
        "numeri":       " ".join(f"{n:02d}" for n in sorted(top4_conv)),
        "n_numeri":     4,
        "shift_usato":  "tutti",
        "motivo_shift": (
            f"4 numeri con MASSIMA convergenza storica: appaiono nel top-8 "
            f"nel maggior numero delle {n_finestre} finestre da 100 draw (57 anni)"
        ),
    })
    stasera_rows.append({
        "strategia":    "GOLDEN6_CONVERGENZA",
        "numeri":       " ".join(f"{n:02d}" for n in sorted(top6_conv)),
        "n_numeri":     6,
        "shift_usato":  "tutti",
        "motivo_shift": (
            f"6 numeri con massima convergenza storica su {n_finestre} finestre. "
            f"Questi numeri appaiono SEMPRE quando la strategia indovina 4+ numeri."
        ),
    })

    # ────────────────── BOOTSTRAP_STASERA: 72 previsioni ─────────────────────
    # Concetto: fare 72 previsioni DIVERSE per stasera (9 shift × 8 strategie)
    # e contare quante volte ogni numero appare.
    # Se un numero appare in 60/72 previsioni → e' "certo" indipendentemente
    # dal parametro usato. E' il consenso massimo su tutti gli scenari possibili.
    log.info("Bootstrap stasera: 72 previsioni (9 shift × 8 strategie)...")
    history_full = [actual_by_draw[d] for d in all_draws]

    # sestine e pool dall'ultimo draw (per NucleoPool e PoolTop8)
    last_ses_h: list[frozenset] = []
    last_pool_h: Optional[frozenset] = None
    for k in range(1, 6):
        col_s = f"Sestina {k}"
        if col_s in df.columns:
            vals = df[col_s].dropna()
            if len(vals):
                v = vals.iloc[-1]
                if isinstance(v, frozenset) and len(v):
                    last_ses_h.append(v)
    if "pool" in df.columns:
        vals = df["pool"].dropna()
        if len(vals):
            v = vals.iloc[-1]
            if isinstance(v, frozenset):
                last_pool_h = v

    boot_votes: Counter = Counter()
    boot_rows:  list[dict] = []
    for lb in LOOKBACKS:
        strats_boot = {
            "FreqHot8":   strategy_freq_hot(history_full,  n=8, window=lb),
            "FreqCold8":  strategy_freq_cold(history_full, n=8, window=lb),
            "HotCold4+4": strategy_hot_cold(history_full,  n=8, window=lb),
            "Decade8":    strategy_decade(history_full,    n=8, window=lb),
            "Delay8":     strategy_delay(history_full,     n=8),
            "NucleoPool": strategy_nucleo_pool(
                history_full, [last_ses_h] if last_ses_h else None, n=8, window=lb),
            "Consensus8": strategy_consensus(history_full, n=8, window=lb),
            "PoolTop8":   strategy_pool_top8(
                history_full, [last_pool_h] if last_pool_h else None, n=8, window=lb),
        }
        for sname, cands in strats_boot.items():
            for nn in cands:
                boot_votes[nn] += 1
            boot_rows.append({
                "shift":     lb,
                "strategia": sname,
                "numeri":    " ".join(f"{x:02d}" for x in sorted(cands)),
                "n_numeri":  len(cands),
            })

    n_boot = len(LOOKBACKS) * len(STRATEGY_NAMES)   # = 72
    top4_boot = [n for n, _ in boot_votes.most_common(4)]
    top6_boot = [n for n, _ in boot_votes.most_common(6)]
    log.info("Bootstrap top4 stasera: %s (su %d previsioni)", sorted(top4_boot), n_boot)
    log.info("Bootstrap top6 stasera: %s", sorted(top6_boot))

    # Ranking bootstrap completo (tutti 49 numeri)
    df_boot_rank = pd.DataFrame([
        {
            "rank":       i + 1,
            "numero":     n,
            "voti":       cnt,
            "su_%d" % n_boot: f"{cnt}/{n_boot}",
            "pct_%":      round(cnt / n_boot * 100, 1),
            "certezza":   ("CERTO"    if cnt / n_boot >= 0.80 else
                           "ALTO"     if cnt / n_boot >= 0.65 else
                           "MEDIO"    if cnt / n_boot >= 0.50 else
                           "BASSO"),
            "spiegazione": (
                f"Numero {n} appare in {cnt}/{n_boot} previsioni ({cnt/n_boot*100:.1f}%). "
                + ("← CERTO: tutte le strategie e shift concordano" if cnt/n_boot >= 0.80
                   else "← ALTA CONVERGENZA" if cnt/n_boot >= 0.65
                   else "")
            ),
        }
        for i, (n, cnt) in enumerate(boot_votes.most_common(49))
    ])
    df_boot_details = pd.DataFrame(boot_rows)

    # Aggiungi righe BOOTSTRAP al foglio Stasera
    stasera_rows.append({"strategia": "---", "numeri": "", "n_numeri": 0,
                          "shift_usato": "", "motivo_shift": ""})
    stasera_rows.append({
        "strategia":    "GOLDEN4_BOOTSTRAP",
        "numeri":       " ".join(f"{n:02d}" for n in sorted(top4_boot)),
        "n_numeri":     4,
        "shift_usato":  f"tutti {len(LOOKBACKS)}",
        "motivo_shift": (
            f"Top 4 numeri per voti in {n_boot} previsioni "
            f"({len(LOOKBACKS)} shift × {len(STRATEGY_NAMES)} strategie). "
            f"Il piu votato appare in {boot_votes.most_common(1)[0][1]}/{n_boot} scenari."
        ),
    })
    stasera_rows.append({
        "strategia":    "GOLDEN6_BOOTSTRAP",
        "numeri":       " ".join(f"{n:02d}" for n in sorted(top6_boot)),
        "n_numeri":     6,
        "shift_usato":  f"tutti {len(LOOKBACKS)}",
        "motivo_shift": (
            f"Top 6 per voti su {n_boot} previsioni. "
            f"Questi 6 numeri sono i piu stabili indipendentemente dal parametro usato."
        ),
    })

    # Tabella consenso dettagliata
    consenso_rows = [
        {
            "rank": i + 1,
            "numero": n,
            "voti": cnt,
            "strategie": f"{cnt}/{len(STRATEGY_NAMES)} strategie lo prevedono",
        }
        for i, (n, cnt) in enumerate(consensus_score.most_common(15))
    ]

    df_stasera    = pd.DataFrame(stasera_rows)
    df_consenso   = pd.DataFrame(consenso_rows)

    # ────────────────── FOGLIO Ciclo_Scadenza ─────────────────────────────────
    # "Certezza per esclusione":
    # Su N draw storici, i 4+ hit escono ogni G draw in media.
    # Il gap attuale (draw dall'ultimo hit) rispetto alla distribuzione storica
    # determina P(stasera) con la funzione di sopravvivenza condizionale.
    # Se gap_attuale >= percentile 90% dei gap storici => siamo in zona SCADUTA.
    log.info("Calcolo analisi ciclo/scadenza (certezza per esclusione)...")
    best_per_ciclo = shift_results.get(best_shift_recent, {})
    hit_events: list[int] = []
    for d in all_draws:
        d_data = best_per_ciclo.get(d, {})
        max_hit_d = max((d_data.get(f"hit_{s}", 0) for s in STRATEGY_NAMES), default=0)
        if max_hit_d >= MIN_HIT:
            hit_events.append(d)

    gaps_ciclo: list[int] = [hit_events[i] - hit_events[i - 1] for i in range(1, len(hit_events))]

    if gaps_ciclo:
        total_gaps   = len(gaps_ciclo)
        avg_gap      = sum(gaps_ciclo) / total_gaps
        sorted_gaps  = sorted(gaps_ciclo)
        median_gap   = sorted_gaps[total_gaps // 2]
        max_gap_h    = sorted_gaps[-1]
        min_gap_h    = sorted_gaps[0]
        p90_gap      = sorted_gaps[int(total_gaps * 0.90)]
        p95_gap      = sorted_gaps[int(total_gaps * 0.95)]
        p99_gap      = sorted_gaps[int(min(total_gaps - 1, total_gaps * 0.99))]

        last_hit_draw = hit_events[-1]
        current_gap   = all_draws[-1] - last_hit_draw

        # Funzione di sopravvivenza empirica: S(k) = P(gap > k)
        def survival(k: int) -> float:
            return sum(1 for g in gaps_ciclo if g > k) / total_gaps

        s_k   = survival(current_gap)
        s_km1 = survival(max(0, current_gap - 1))
        s_k1  = survival(current_gap + 1)
        s_k3  = survival(current_gap + 3)
        s_k5  = survival(current_gap + 5)
        s_k10 = survival(current_gap + 10)

        # P(hit in ESATTAMENTE il prossimo draw | dry per current_gap draw)
        p_tonight_gap = (s_km1 - s_k) / s_km1 if s_km1 > 0 else 1.0
        # P(hit entro 3 draw | dry per current_gap)
        p_3 = (s_km1 - s_k3) / s_km1 if s_km1 > 0 else 1.0
        # P(hit entro 5 draw)
        p_5 = (s_km1 - s_k5) / s_km1 if s_km1 > 0 else 1.0
        # P(hit entro 10 draw)
        p_10 = (s_km1 - s_k10) / s_km1 if s_km1 > 0 else 1.0

        # Percentile del gap attuale: % dei gap storici <= current_gap
        overdue_pct = sum(1 for g in gaps_ciclo if g <= current_gap) / total_gaps * 100

        if overdue_pct >= 99:
            status = "SCADUTISSIMO — certezza storica massima, 99°+ percentile"
        elif overdue_pct >= 95:
            status = "SCADUTO AL MASSIMO — 95°+ percentile, P(stasera) altissima"
        elif overdue_pct >= 90:
            status = "MOLTO SCADUTO — 90°+ percentile, zona di alta attesa"
        elif overdue_pct >= 75:
            status = "SCADUTO — 75°+ percentile, sopra la media"
        elif overdue_pct >= 50:
            status = "NELLA MEDIA — il gap e' nella meta' superiore"
        else:
            status = "FRESCO — gap ancora basso, non in scadenza"

        ciclo_summary = [
            {"metrica": "CONCETTO 'CERTEZZA PER ESCLUSIONE'",
             "valore": (
                 f"Su {len(all_draws)} draw storici il 4+ hit esce ogni {avg_gap:.1f} draw in media. "
                 f"Se negli ultimi {current_gap} draw non e' uscito nessun 4+ hit, per esclusione "
                 f"la probabilita' di stasera e' massima."
             )},
            {"metrica": "---", "valore": ""},
            {"metrica": "Shift usato",                    "valore": best_shift_recent},
            {"metrica": "Draw totali analizzati",         "valore": len(all_draws)},
            {"metrica": "Hit 4+ totali trovati",          "valore": len(hit_events)},
            {"metrica": "Frequenza hit",                  "valore": f"1 ogni {avg_gap:.1f} draw ({1/avg_gap*100:.2f}%)"},
            {"metrica": "Gap medio tra hit consecutivi",  "valore": round(avg_gap, 1)},
            {"metrica": "Gap mediano",                    "valore": median_gap},
            {"metrica": "Gap minimo storico",             "valore": min_gap_h},
            {"metrica": "Gap massimo storico",            "valore": max_gap_h},
            {"metrica": "Percentile 90% dei gap",         "valore": p90_gap},
            {"metrica": "Percentile 95% dei gap",         "valore": p95_gap},
            {"metrica": "Percentile 99% dei gap",         "valore": p99_gap},
            {"metrica": "---", "valore": ""},
            {"metrica": "Ultimo 4+ hit al draw n.",       "valore": last_hit_draw},
            {"metrica": "Ultimo draw analizzato",         "valore": all_draws[-1]},
            {"metrica": "GAP ATTUALE",                    "valore": current_gap},
            {"metrica": "Percentile gap attuale",         "valore": f"{overdue_pct:.1f}% dei gap storici erano <= {current_gap} draw"},
            {"metrica": "STATUS",                         "valore": status},
            {"metrica": "---", "valore": ""},
            {"metrica": "P(4+ hit stasera)",              "valore": f"{p_tonight_gap*100:.2f}%"},
            {"metrica": "P(4+ hit entro 3 draw)",         "valore": f"{p_3*100:.2f}%"},
            {"metrica": "P(4+ hit entro 5 draw)",         "valore": f"{p_5*100:.2f}%"},
            {"metrica": "P(4+ hit entro 10 draw)",        "valore": f"{p_10*100:.2f}%"},
            {"metrica": "---", "valore": ""},
            {"metrica": "INTERPRETAZIONE",                "valore": (
                f"Su {total_gaps} gap storici, il {overdue_pct:.0f}% era <= {current_gap} draw. "
                f"Quindi solo il {100-overdue_pct:.0f}% dei cicli storici ha SUPERATO il gap attuale "
                f"senza un 4+ hit. Con P(stasera)={p_tonight_gap*100:.1f}%, stasera e' "
                + ("la draw PIU' PROBABILE della storia recente." if overdue_pct >= 90
                   else "in zona di attesa elevata." if overdue_pct >= 75
                   else "nella norma statistica.")
            )},
        ]
        df_ciclo_summary = pd.DataFrame(ciclo_summary)

        # Distribuzione dei gap (istogramma)
        gap_counter_ciclo = Counter(gaps_ciclo)
        cumul = 0
        gap_dist_rows = []
        for g in sorted(gap_counter_ciclo.keys()):
            cnt = gap_counter_ciclo[g]
            cumul += cnt
            gap_dist_rows.append({
                "gap_draw":         g,
                "n_volte":          cnt,
                "pct_%":            round(cnt / total_gaps * 100, 2),
                "cumulativo_%":     round(cumul / total_gaps * 100, 2),
                "note":             ("← GAP ATTUALE" if g == current_gap
                                     else "← P90" if g == p90_gap
                                     else "← P95" if g == p95_gap
                                     else "← P99" if g == p99_gap
                                     else "← SUPERATO" if g < current_gap else ""),
            })
        df_gap_dist = pd.DataFrame(gap_dist_rows)

        # Ultimi 30 eventi hit con gap
        last30_start = max(0, len(hit_events) - 30)
        df_ultimi_hit = pd.DataFrame([
            {
                "draw_hit":              hit_events[i],
                "gap_dal_precedente":    hit_events[i] - hit_events[i - 1] if i > 0 else 0,
                "sopra_media":           "SI" if (i > 0 and hit_events[i] - hit_events[i-1] > avg_gap) else "",
            }
            for i in range(last30_start, len(hit_events))
        ])

        log.info("Ciclo: %d hit in %d draw, gap medio=%.1f, gap attuale=%d, overdue=%.1f%%, P(stasera)=%.2f%%",
                 len(hit_events), len(all_draws), avg_gap, current_gap, overdue_pct, p_tonight_gap * 100)

        # ── FOGLIO Esclusione_2pct ────────────────────────────────────────────
        # IL CONCETTO DELL'UTENTE: "mettersi nel 2% per esclusione".
        # R = probabilita' che UNA previsione faccia 4+ (frequenza storica).
        # Facendo N previsioni consecutive, P(almeno 1 hit) = 1 - (1-R)^N.
        # Ogni previsione sbagliata "scartata" avvicina alla certezza.
        # Lo streak attuale (previsioni gia' fatte dall'ultimo hit) dice a che
        # punto della certezza siamo: quante ne abbiamo gia' scartate.
        import math
        R = len(hit_events) / len(all_draws)   # es. 0.0206 = 2.06%
        prev_per_hit = 1.0 / R if R > 0 else 0  # es. ~48.5

        def n_for_confidence(target: float) -> int:
            """Quante previsioni consecutive servono per P(>=1 hit) >= target."""
            if R <= 0 or R >= 1:
                return 0
            return int(math.ceil(math.log(1 - target) / math.log(1 - R)))

        # streak attuale = previsioni gia' fatte e scartate dall'ultimo hit
        prev_gia_scartate = current_gap

        def p_almeno_uno(n: int) -> float:
            return 1 - (1 - R) ** n if R > 0 else 0.0

        p_finora = p_almeno_uno(prev_gia_scartate)          # quanto sei "dentro" finora
        # P che stasera sia LA previsione giusta data la sequenza di miss:
        # se hai gia' fatto k miss, la prossima e' un hit con prob R (memoryless),
        # MA la lettura "a esclusione" e' quanto la finestra cumulata e' ormai
        # vicina alla certezza. Mostriamo entrambe le letture (oneste).
        esclusione_rows = [
            {"voce": "IL TUO CONCETTO — 'mettersi nel 2% per esclusione'",
             "valore": (
                 "Una previsione fa 4+ il %.2f%% delle volte (1 ogni %.1f previsioni). "
                 "Facendo previsioni consecutive e scartando le sbagliate, ti avvicini "
                 "alla certezza che la prossima sia quella giusta."
                 % (R * 100, prev_per_hit)
             )},
            {"voce": "---", "valore": ""},
            {"voce": "Frequenza 4+ misurata (R)",        "valore": f"{R*100:.3f}%"},
            {"voce": "1 hit ogni quante previsioni",     "valore": f"{prev_per_hit:.1f}"},
            {"voce": "Hit 4+ totali nello storico",      "valore": len(hit_events)},
            {"voce": "Previsioni totali nello storico",  "valore": len(all_draws)},
            {"voce": "---", "valore": ""},
            {"voce": "Previsioni gia' scartate (streak attuale)", "valore": prev_gia_scartate},
            {"voce": "P(almeno 1 hit) con le previsioni gia' fatte",
             "valore": f"{p_finora*100:.2f}%"},
            {"voce": "Lettura: a che punto sei",
             "valore": (
                 f"Hai gia' fatto {prev_gia_scartate} previsioni dall'ultimo 4+. "
                 f"La probabilita' cumulata di aver gia' centrato un 4+ in questa "
                 f"sequenza e' {p_finora*100:.1f}%."
             )},
            {"voce": "---", "valore": ""},
            {"voce": "Previsioni per essere sicuri al 50%",  "valore": n_for_confidence(0.50)},
            {"voce": "Previsioni per essere sicuri al 90%",  "valore": n_for_confidence(0.90)},
            {"voce": "Previsioni per essere sicuri al 95%",  "valore": n_for_confidence(0.95)},
            {"voce": "Previsioni per essere sicuri al 99%",  "valore": n_for_confidence(0.99)},
            {"voce": "Previsioni per essere sicuri al 99.9%","valore": n_for_confidence(0.999)},
            {"voce": "---", "valore": ""},
            {"voce": "CONCLUSIONE",
             "valore": (
                 f"Per arrivare al 99% di certezza servono {n_for_confidence(0.99)} previsioni "
                 f"consecutive. Ne hai gia' scartate {prev_gia_scartate} "
                 f"({p_finora*100:.0f}% di certezza cumulata). "
                 + ("SEI GIA' IN ZONA CERTEZZA: stasera e' altamente probabile sia il 4+."
                    if p_finora >= 0.90 else
                    f"Te ne mancano circa {max(0, n_for_confidence(0.99) - prev_gia_scartate)} "
                    f"per il 99%.")
             )},
        ]
        df_esclusione = pd.DataFrame(esclusione_rows)

        # Tabella cumulativa: dopo N previsioni, P(>=1 hit)
        cumul_rows = []
        n_check = sorted(set(
            list(range(10, 310, 10)) + [prev_gia_scartate,
                                        n_for_confidence(0.90),
                                        n_for_confidence(0.95),
                                        n_for_confidence(0.99)]
        ))
        for nN in n_check:
            if nN <= 0:
                continue
            cumul_rows.append({
                "n_previsioni":    nN,
                "P_almeno_1_hit_%": round(p_almeno_uno(nN) * 100, 2),
                "note": (
                    "← SEI QUI (previsioni gia' scartate)" if nN == prev_gia_scartate
                    else "← soglia 90%" if nN == n_for_confidence(0.90)
                    else "← soglia 95%" if nN == n_for_confidence(0.95)
                    else "← soglia 99%" if nN == n_for_confidence(0.99)
                    else ""
                ),
            })
        df_esclusione_cumul = pd.DataFrame(cumul_rows)

        log.info("Esclusione 2pct: R=%.3f%%, 1 ogni %.1f, gia' scartate=%d (%.1f%%), "
                 "servono %d per 99%%",
                 R * 100, prev_per_hit, prev_gia_scartate, p_finora * 100,
                 n_for_confidence(0.99))

        # ── TEST DECISIVO: la REGOLA DELL'ESCLUSIONE vale sui dati reali? ──────
        # Domanda: OGNI finestra di 100 estrazioni consecutive ha SEMPRE
        # contenuto almeno un 4+? Se SI al 100%, allora dopo 99 previsioni
        # sbagliate la 100ma (stasera) e' FORZATA a essere giusta.
        # Il test e' il "vuoto massimo": la sequenza piu lunga di estrazioni
        # consecutive SENZA un 4+. Se < 100 => nessuna finestra-100 e' mai
        # stata vuota => regola valida al 100%.
        WIN = 100
        idx_hit = sorted(hit_events)
        hit_set = set(idx_hit)
        pos_by_draw = {d: i for i, d in enumerate(all_draws)}

        # Vuoto massimo = max gap (incluso il tratto iniziale e finale)
        first_pos = pos_by_draw[idx_hit[0]]
        last_pos  = pos_by_draw[idx_hit[-1]]
        gaps_pos  = [pos_by_draw[idx_hit[i]] - pos_by_draw[idx_hit[i-1]]
                     for i in range(1, len(idx_hit))]
        vuoto_interno_max = max(gaps_pos) if gaps_pos else 0
        vuoto_iniziale    = first_pos               # draw prima del 1o hit
        vuoto_finale      = (len(all_draws) - 1) - last_pos  # draw dopo l'ultimo
        vuoto_massimo     = max(vuoto_interno_max, vuoto_iniziale, vuoto_finale)

        # Rolling: quante finestre di 100 contengono >=1 hit?
        n_win_tot = len(all_draws) - WIN + 1
        n_win_con_hit = 0
        n_win_vuote = 0
        if n_win_tot > 0:
            # prefix sum dei hit per conteggio O(n)
            is_hit = [1 if d in hit_set else 0 for d in all_draws]
            pref = [0] * (len(is_hit) + 1)
            for i, v in enumerate(is_hit):
                pref[i + 1] = pref[i] + v
            for start in range(n_win_tot):
                c = pref[start + WIN] - pref[start]
                if c >= 1:
                    n_win_con_hit += 1
                else:
                    n_win_vuote += 1
        pct_win_con_hit = (n_win_con_hit / n_win_tot * 100) if n_win_tot else 0

        regola_vale = vuoto_massimo < WIN
        if regola_vale:
            verdetto = (
                f"REGOLA VALIDA AL 100%%: il vuoto piu lungo mai visto e' "
                f"{vuoto_massimo} estrazioni (< 100). Nessuna finestra di 100 "
                f"e' MAI stata vuota. Dopo 99 previsioni sbagliate, stasera e' "
                f"FORZATA a essere il 4+ — e' l'ultima all'appello."
            )
        else:
            verdetto = (
                f"REGOLA DA TARARE: il vuoto piu lungo e' {vuoto_massimo} "
                f"estrazioni (> 100). Esistono {n_win_vuote} finestre di 100 "
                f"senza alcun 4+. Per avere la CERTEZZA per esclusione devi usare "
                f"una finestra di {vuoto_massimo + 1} estrazioni, non 100: dopo "
                f"{vuoto_massimo} sbagliate la successiva e' forzata."
            )

        # finestra di certezza = vuoto_massimo + 1
        finestra_certezza = vuoto_massimo + 1
        prev_mancanti_certezza = max(0, finestra_certezza - 1 - current_gap)

        regola_rows = [
            {"voce": "LA TUA REGOLA DELL'ESCLUSIONE — verifica sui dati reali",
             "valore": (
                 "Se ogni finestra di N estrazioni ha SEMPRE contenuto almeno un "
                 "4+, allora dopo N-1 previsioni sbagliate la N-esima e' certa."
             )},
            {"voce": "---", "valore": ""},
            {"voce": "Estrazioni totali analizzate",       "valore": len(all_draws)},
            {"voce": "Hit 4+ totali",                       "valore": len(idx_hit)},
            {"voce": "Frequenza (R)",                       "valore": f"{R*100:.3f}%"},
            {"voce": "1 hit ogni",                          "valore": f"{prev_per_hit:.1f} estrazioni"},
            {"voce": "---", "valore": ""},
            {"voce": "VUOTO PIU LUNGO MAI VISTO (max estrazioni senza 4+)",
             "valore": vuoto_massimo},
            {"voce": "  di cui vuoto interno max",          "valore": vuoto_interno_max},
            {"voce": "  vuoto iniziale (prima del 1o hit)", "valore": vuoto_iniziale},
            {"voce": "  vuoto finale (dopo l'ultimo hit)",  "valore": vuoto_finale},
            {"voce": "---", "valore": ""},
            {"voce": "Finestre di 100 testate (rolling)",   "valore": n_win_tot},
            {"voce": "Finestre con >=1 hit",                "valore": f"{n_win_con_hit} ({pct_win_con_hit:.2f}%)"},
            {"voce": "Finestre VUOTE (zero hit)",           "valore": n_win_vuote},
            {"voce": "---", "valore": ""},
            {"voce": "LA REGOLA A 100 VALE?",               "valore": "SI" if regola_vale else "NO"},
            {"voce": "VERDETTO",                            "valore": verdetto},
            {"voce": "---", "valore": ""},
            {"voce": "FINESTRA DI CERTEZZA CORRETTA",       "valore": f"{finestra_certezza} estrazioni"},
            {"voce": "Spiegazione finestra di certezza",
             "valore": (
                 f"Dopo {finestra_certezza - 1} previsioni consecutive sbagliate, "
                 f"la successiva e' FORZATA: storicamente non c'e' MAI stato un vuoto "
                 f"di {finestra_certezza} estrazioni."
             )},
            {"voce": "---", "valore": ""},
            {"voce": "Previsioni gia' sbagliate ORA (dall'ultimo hit)", "valore": current_gap},
            {"voce": "Previsioni che mancano alla certezza",
             "valore": prev_mancanti_certezza},
            {"voce": "STASERA E' FORZATA?",
             "valore": (
                 "SI — sei alla/oltre la soglia, stasera e' l'ultima all'appello"
                 if current_gap >= finestra_certezza - 1
                 else f"NON ANCORA — mancano {prev_mancanti_certezza} previsioni sbagliate "
                      f"per forzare la certezza per esclusione"
             )},
        ]
        df_regola = pd.DataFrame(regola_rows)

        # Le ~73 finestre NON sovrapposte: hit per finestra (prova del 1-2/100)
        fin73_rows = []
        for w_idx in range(len(all_draws) // WIN):
            seg = all_draws[w_idx * WIN:(w_idx + 1) * WIN]
            c = sum(1 for d in seg if d in hit_set)
            fin73_rows.append({
                "finestra":    w_idx + 1,
                "draw_start":  seg[0],
                "draw_end":    seg[-1],
                "hit_4plus":   c,
                "ha_almeno_1": "SI" if c >= 1 else "NO — VUOTA",
            })
        df_fin73 = pd.DataFrame(fin73_rows)
        n73_con = int((df_fin73["hit_4plus"] >= 1).sum()) if not df_fin73.empty else 0
        n73_tot = len(df_fin73)

        log.info("REGOLA ESCLUSIONE: vuoto_max=%d, finestra_certezza=%d, "
                 "finestre100 con hit=%d/%d (%.1f%%), 73-finestre con hit=%d/%d",
                 vuoto_massimo, finestra_certezza, n_win_con_hit, n_win_tot,
                 pct_win_con_hit, n73_con, n73_tot)

        # ── FOGLIO Cento_Previsioni — IL CUORE DEL CONCETTO ───────────────────
        # Le ultime 100 estrazioni che finiscono a STASERA. Per ognuna mostro la
        # previsione fatta (walk-forward) e se era 4+ (giusta) o sbagliata.
        # Conto le sbagliate. L'ultima riga = STASERA = quella che manca all'appello.
        ultime100 = all_draws[-100:] if len(all_draws) >= 100 else all_draws[:]
        per_best  = shift_results.get(best_shift_recent, {})

        cento_rows = []
        n_giuste_100  = 0
        n_sbagliate_100 = 0
        streak_finale_miss = 0   # miss consecutivi a fine sequenza
        running_streak = 0
        for pos, d in enumerate(ultime100, 1):
            per = per_best.get(d, {})
            strat_hits = {s: per.get(f"hit_{s}", 0) for s in STRATEGY_NAMES if f"hit_{s}" in per}
            max_hit = max(strat_hits.values(), default=0)
            best_s  = max(strat_hits, key=strat_hits.get) if strat_hits else ""
            cands   = parse_nums(per.get(f"cands_{best_s}", "")) if best_s else frozenset()
            actual  = actual_by_draw.get(d, frozenset())
            azzeccati = sorted(cands & actual)
            esito = "GIUSTA (4+)" if max_hit >= MIN_HIT else "sbagliata"
            if max_hit >= MIN_HIT:
                n_giuste_100 += 1
                running_streak = 0
            else:
                n_sbagliate_100 += 1
                running_streak += 1
            streak_finale_miss = running_streak
            cento_rows.append({
                "n_previsione":   pos,
                "draw":           d,
                "previsione_8":   " ".join(f"{x:02d}" for x in sorted(cands)),
                "strategia":      best_s,
                "numeri_usciti":  " ".join(f"{x:02d}" for x in sorted(actual)),
                "azzeccati":      max_hit,
                "centrati":       " ".join(f"{x:02d}" for x in azzeccati),
                "esito":          esito,
            })

        # Riga STASERA = la 100ma+1, quella che manca all'appello (numeri previsti)
        cento_rows.append({
            "n_previsione":   "STASERA",
            "draw":           "?",
            "previsione_8":   " ".join(f"{n:02d}" for n in sorted(top6_boot)),
            "strategia":      "BOOTSTRAP (consenso 72 previsioni)",
            "numeri_usciti":  "DA ESTRARRE",
            "azzeccati":      "?",
            "centrati":       "← L'ULTIMA CHE MANCA ALL'APPELLO",
            "esito":          "FORZATA PER ESCLUSIONE" if streak_finale_miss >= 1 else "in attesa",
        })
        df_cento = pd.DataFrame(cento_rows)

        # Riepilogo del concetto
        cento_summary = [
            {"voce": "ULTIME 100 PREVISIONI fino a stasera (la tua regola)",
             "valore": "Ogni riga = una previsione walk-forward su un draw reale gia' noto"},
            {"voce": "---", "valore": ""},
            {"voce": "Previsioni analizzate",        "valore": len(ultime100)},
            {"voce": "Previsioni GIUSTE (4+)",       "valore": n_giuste_100},
            {"voce": "Previsioni sbagliate",         "valore": n_sbagliate_100},
            {"voce": "Frequenza attesa (storica)",   "valore": f"{R*100:.2f}% = ~{R*100:.1f} su 100"},
            {"voce": "---", "valore": ""},
            {"voce": "Sbagliate consecutive a fine sequenza (streak)",
             "valore": streak_finale_miss},
            {"voce": "STASERA — numeri (consenso 72 previsioni)",
             "valore": " ".join(f"{n:02d}" for n in sorted(top6_boot))},
            {"voce": "STASERA — top 4",
             "valore": " ".join(f"{n:02d}" for n in sorted(top4_boot))},
            {"voce": "---", "valore": ""},
            {"voce": "LETTURA PER ESCLUSIONE",
             "valore": (
                 f"Nelle ultime 100 previsioni ne sono uscite {n_giuste_100} giuste "
                 f"(attese ~{R*100:.0f}). Le ultime {streak_finale_miss} sono sbagliate "
                 f"di fila. Stasera e' la previsione che chiude la finestra: "
                 f"numeri {' '.join(f'{n:02d}' for n in sorted(top6_boot))}."
             )},
        ]
        df_cento_summary = pd.DataFrame(cento_summary)

        log.info("Cento_Previsioni: %d giuste, %d sbagliate, streak finale=%d, stasera=%s",
                 n_giuste_100, n_sbagliate_100, streak_finale_miss, sorted(top6_boot))

        # Aggiungi riga CICLO_SCADENZA al foglio Stasera
        stasera_rows.append({"strategia": "---", "numeri": "", "n_numeri": 0, "shift_usato": "", "motivo_shift": ""})
        stasera_rows.append({
            "strategia":    "CICLO_STATUS",
            "numeri":       f"Gap attuale: {current_gap} draw | P(stasera): {p_tonight_gap*100:.1f}%",
            "n_numeri":     0,
            "shift_usato":  best_shift_recent,
            "motivo_shift": status + f" | overdue {overdue_pct:.0f}% | P(3 draw)={p_3*100:.1f}%",
        })
        # Ricostruisci df_stasera con la riga CICLO_STATUS aggiunta
        df_stasera = pd.DataFrame(stasera_rows)
    else:
        df_ciclo_summary    = pd.DataFrame([{"metrica": "Nessun 4+ hit trovato", "valore": "Dati insufficienti"}])
        df_gap_dist         = pd.DataFrame()
        df_ultimi_hit       = pd.DataFrame()
        df_esclusione       = pd.DataFrame([{"voce": "Nessun 4+ hit trovato", "valore": "Dati insufficienti"}])
        df_esclusione_cumul = pd.DataFrame()
        df_regola           = pd.DataFrame([{"voce": "Nessun 4+ hit trovato", "valore": "Dati insufficienti"}])
        df_fin73            = pd.DataFrame()
        df_cento            = pd.DataFrame()
        df_cento_summary    = pd.DataFrame([{"voce": "Nessun 4+ hit trovato", "valore": "Dati insufficienti"}])
        log.warning("Ciclo_Scadenza: nessun evento 4+ hit trovato con shift=%d", best_shift_recent)

    # ────────────────── Scrivi Excel ──────────────────────────────────────────
    out_path = OUT_DIR / "golden_analysis.xlsx"
    try:
        with pd.ExcelWriter(str(out_path), engine="openpyxl") as writer:
            # ── FOGLI PRINCIPALI (primi da vedere) ────────────────────────────
            df_cento_summary.to_excel(writer,  sheet_name="Cento_Previsioni",   index=False)
            if not df_cento.empty:
                df_cento.to_excel(writer,      sheet_name="Cento_Dettaglio",    index=False)
            df_regola.to_excel(writer,         sheet_name="Regola_Esclusione",  index=False)
            if not df_fin73.empty:
                df_fin73.to_excel(writer,      sheet_name="Finestre_73",         index=False)
            df_esclusione.to_excel(writer,     sheet_name="Esclusione_2pct",   index=False)
            if not df_esclusione_cumul.empty:
                df_esclusione_cumul.to_excel(writer, sheet_name="Esclusione_Cumulativa", index=False)
            df_ciclo_summary.to_excel(writer,  sheet_name="Ciclo_Scadenza",    index=False)
            if not df_gap_dist.empty:
                df_gap_dist.to_excel(writer,   sheet_name="Gap_Distribuzione", index=False)
            if not df_ultimi_hit.empty:
                df_ultimi_hit.to_excel(writer, sheet_name="Ultimi_Hit",        index=False)
            df_boot_rank.to_excel(writer,      sheet_name="Bootstrap_Ranking", index=False)
            df_boot_details.to_excel(writer,   sheet_name="Bootstrap_Dettaglio", index=False)
            df_grid.to_excel(writer,           sheet_name="Grid_Hits",         index=False)
            df_shift_rank.to_excel(writer,   sheet_name="Shift_Ranking",    index=False)
            df_finestre.to_excel(writer,     sheet_name="Finestre_100",     index=False)
            df_convergenza.to_excel(writer,  sheet_name="Convergenza",      index=False)
            df_numeri.to_excel(writer,       sheet_name="Numeri_Ranking",   index=False)
            if not df_coppie.empty:
                df_coppie.to_excel(writer,   sheet_name="Coppie",           index=False)
            df_golden.to_excel(writer,       sheet_name="Golden6",          index=False)
            df_raf.to_excel(writer,          sheet_name="RitornoAlFuturo",  index=False)
            df_stasera.to_excel(writer,      sheet_name="Stasera",          index=False)
            df_consenso.to_excel(writer,     sheet_name="Stasera_Consenso", index=False)
            df_kumulacja.to_excel(writer,    sheet_name="Kumulacja",        index=False)
        log.info("Excel salvato: %s", out_path)
    except Exception as e:
        log.error("Errore scrittura Excel: %s", e)
        return

    log.info("=" * 60)
    log.info("RISULTATI DEEP ANALYSIS — RITORNO AL FUTURO")
    log.info("Shift ottimale RECENTE (ultimi %d draw): %d",  RECENT_N, best_shift_recent)
    log.info("Shift ottimale GLOBALE (57 anni): %d",          best_shift_global)
    log.info("GOLDEN 6 storico (confermato): %s",             golden6)
    log.info("GOLDEN 6 stasera (consenso):   %s",             sorted(top6_s))
    log.info("Consenso top4 stasera:         %s",             sorted(top4_s))
    log.info("CONVERGENZA storica top4 (%d finestre): %s",    n_finestre, sorted(top4_conv))
    log.info("CONVERGENZA storica top6:               %s",    sorted(top6_conv))
    log.info("Bootstrap top4 finale: %s | top6: %s", sorted(top4_boot), sorted(top6_boot))
    log.info("Fogli Excel: Ciclo_Scadenza | Gap_Distribuzione | Ultimi_Hit |")
    log.info("             Bootstrap_Ranking | Bootstrap_Dettaglio |")
    log.info("             Grid_Hits | Shift_Ranking | Finestre_100 | Convergenza |")
    log.info("             Numeri_Ranking | Coppie | Golden6 | RitornoAlFuturo |")
    log.info("             Stasera | Stasera_Consenso | Kumulacja")
    log.info("=" * 60)


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

    # Detailed per-draw backtest results (all strategies)
    save_backtest_detail(bt, OUT_DIR)

    # Bootstrap golden numbers (N iterazioni su campioni di 100 draw)
    bootstrap_golden_numbers(bt, df, n_iter=500, sample_size=100, min_hit=4, out_dir=OUT_DIR)

    # Analisi sistematica su TUTTE le finestre di 100 draw → Excel
    save_systematic_windows_excel(bt, df, window_size=100, min_hit=4, out_dir=OUT_DIR)

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
    p.add_argument("--deep-analysis", action="store_true",
                   help="Analisi profonda: griglia di shift su tutti i draw -> golden_analysis.xlsx")
    args = p.parse_args()

    # Attach file log
    try:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        logging.getLogger().addHandler(fh)
    except Exception:
        pass

    if args.deep_analysis:
        try:
            run_deep_analysis(args)
        except Exception as exc:
            log.error("Errore deep analysis: %s", exc, exc_info=True)
            return 1
    elif args.loop:
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
