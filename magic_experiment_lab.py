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
    Modalita' --deep-analysis:
    Per ogni shift (lookback) in LOOKBACKS, esegue backtest completo su tutti i draw.
    Per ogni draw N: "se 57 anni fa ero al draw N-shift, cosa prevedevo?"
    Salva golden_analysis.xlsx con:
      Grid_Hits     : ogni draw × ogni shift → hit_t0 (matrice completa)
      Shift_Ranking : quale shift da piu draw con 4+ hit (in media e per periodo)
      Finestre_100  : ogni 100 draw consecutivi → shift migliore + numeri top
      Numeri_Ranking: ogni numero 1-49 ranked su quante volte confermato
      Coppie        : top 50 coppie di numeri co-confermati
      Golden6       : 4 numeri nucleo + 2 coppia residua
    """
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        log.error("openpyxl non installato. Installa con: pip install openpyxl")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_draws(limit=args.limit)
    n = len(df)
    log.info("Deep analysis — %d draw totali", n)

    if n < 200:
        log.error("Servono almeno 200 draw per il deep analysis.")
        return

    LOOKBACKS = [80, 90, 100, 110, 120, 130, 150, 175, 200]
    WARMUP    = 60   # warmup ridotto per usare piu dati storici

    # Mappa draw_num -> numeri reali
    actual_by_draw: dict[int, frozenset] = {}
    for _, row in df.iterrows():
        d = int(row.get("draw", 0))
        nums = parse_nums(row.get("Numeri Reali", ""))
        if len(nums) == 6:
            actual_by_draw[d] = nums

    # ── Esegui backtest per ogni shift ────────────────────────────────────────
    # risultati: shift -> { draw_num -> { strategy -> hit_t0 } }
    shift_results: dict[int, dict[int, dict[str, int]]] = {}

    for lb in LOOKBACKS:
        log.info("Shift %d draw in corso...", lb)
        bt = run_backtest(df, warmup=WARMUP, freq_window=lb)
        per_draw: dict[int, dict[str, int]] = {}
        for sname, df_s in bt.items():
            if df_s.empty:
                continue
            for _, row in df_s.iterrows():
                d = int(row["draw"])
                hit = int(row["hit_t0"]) if pd.notna(row.get("hit_t0")) else 0
                cands = str(row.get("candidates", ""))
                per_draw.setdefault(d, {})[sname] = hit
                per_draw[d][f"cands_{sname}_{lb}"] = cands
        shift_results[lb] = per_draw
        log.info("  Shift %d: %d draw valutati", lb, len(per_draw))

    all_draws = sorted(
        set(d for per in shift_results.values() for d in per.keys())
        & set(actual_by_draw.keys())
    )
    log.info("Draw totali con dati completi: %d", len(all_draws))

    # ── Foglio 1: Grid_Hits ───────────────────────────────────────────────────
    # Una riga per draw, colonne: draw_num, actual, poi per ogni shift la hit_t0 migliore
    grid_rows = []
    for d in all_draws:
        row_d: dict = {"draw": d, "numeri_reali": " ".join(f"{x:02d}" for x in sorted(actual_by_draw[d]))}
        best_overall = 0
        best_shift = 0
        for lb in LOOKBACKS:
            per = shift_results.get(lb, {}).get(d, {})
            # max hit_t0 tra tutte le strategie per questo shift
            hits = {s: v for s, v in per.items() if not s.startswith("cands_")}
            max_hit = max(hits.values(), default=0) if hits else 0
            row_d[f"shift_{lb}"] = max_hit
            if max_hit > best_overall:
                best_overall = max_hit
                best_shift = lb
        row_d["best_hit"]   = best_overall
        row_d["best_shift"] = best_shift
        grid_rows.append(row_d)

    df_grid = pd.DataFrame(grid_rows)

    # ── Foglio 2: Shift_Ranking ───────────────────────────────────────────────
    shift_rank_rows = []
    total = len(all_draws)
    for lb in LOOKBACKS:
        col = f"shift_{lb}"
        if col not in df_grid.columns:
            continue
        vals = df_grid[col]
        shift_rank_rows.append({
            "shift":         lb,
            "draw_valutati": total,
            "hit_medio":     round(vals.mean(), 4),
            "draw_con_3+":   int((vals >= 3).sum()),
            "pct_3+":        f"{(vals >= 3).mean()*100:.2f}%",
            "draw_con_4+":   int((vals >= 4).sum()),
            "pct_4+":        f"{(vals >= 4).mean()*100:.2f}%",
            "draw_con_5+":   int((vals >= 5).sum()),
            "draw_con_6":    int((vals == 6).sum()),
        })
    df_shift_rank = pd.DataFrame(shift_rank_rows).sort_values("draw_con_4+", ascending=False)

    # ── Foglio 3: Finestre_100 ────────────────────────────────────────────────
    # Ogni 100 draw consecutivi: quale shift funziona meglio? Quali numeri top?
    fin_rows = []
    for w_idx in range(len(all_draws) // 100):
        w_draws = all_draws[w_idx * 100: (w_idx + 1) * 100]
        w_df = df_grid[df_grid["draw"].isin(w_draws)]

        best_shift_w = 0
        best_count_w = -1
        for lb in LOOKBACKS:
            col = f"shift_{lb}"
            if col in w_df.columns:
                cnt = int((w_df[col] >= 4).sum())
                if cnt > best_count_w:
                    best_count_w = cnt
                    best_shift_w = lb

        # Numeri piu confermati in questa finestra (con lo shift migliore)
        confirmed_w: Counter = Counter()
        for d in w_draws:
            per = shift_results.get(best_shift_w, {}).get(d, {})
            if not per:
                continue
            hits = {s: v for s, v in per.items() if not s.startswith("cands_")}
            if max(hits.values(), default=0) >= 4:
                actual = actual_by_draw.get(d, frozenset())
                for s in STRATEGY_NAMES:
                    cand_key = f"cands_{s}_{best_shift_w}"
                    if cand_key in per:
                        cands = parse_nums(str(per[cand_key]))
                        for nn in cands & actual:
                            confirmed_w[nn] += 1

        top8_w = [n for n, _ in confirmed_w.most_common(8)]
        fin_row = {
            "finestra":       w_idx + 1,
            "draw_start":     w_draws[0],
            "draw_end":       w_draws[-1],
            "shift_ottimale": best_shift_w,
            "draw_con_4+":    best_count_w,
        }
        for i, n in enumerate(top8_w[:8], 1):
            fin_row[f"num_{i}"] = n
        fin_rows.append(fin_row)

    df_finestre = pd.DataFrame(fin_rows)

    # ── Foglio 4: Numeri_Ranking ──────────────────────────────────────────────
    # Per ogni numero 1-49: quante volte confermato (predetto E uscito) in draw con 4+
    global_confirmed: Counter = Counter()
    global_predicted: Counter = Counter()

    for lb in LOOKBACKS:
        bt_lb = run_backtest(df, warmup=WARMUP, freq_window=lb)
        for sname, df_s in bt_lb.items():
            if df_s.empty:
                continue
            for _, row in df_s.iterrows():
                d = int(row["draw"])
                hit = int(row["hit_t0"]) if pd.notna(row.get("hit_t0")) else 0
                cands = parse_nums(str(row.get("candidates", "")))
                actual = actual_by_draw.get(d, frozenset())
                for nn in cands:
                    global_predicted[nn] += 1
                if hit >= 4:
                    for nn in cands & actual:
                        global_confirmed[nn] += 1

    num_rows = []
    for num in range(1, 50):
        conf = global_confirmed.get(num, 0)
        pred = global_predicted.get(num, 0)
        num_rows.append({
            "numero":            num,
            "volte_confermato":  conf,
            "volte_predetto":    pred,
            "tasso_conferma_%":  round(conf / pred * 100, 2) if pred > 0 else 0,
        })
    df_numeri = pd.DataFrame(num_rows).sort_values("volte_confermato", ascending=False).reset_index(drop=True)
    df_numeri["rank"] = range(1, len(df_numeri) + 1)

    # ── Foglio 5: Coppie ──────────────────────────────────────────────────────
    pair_count: Counter = Counter()
    for row_f in fin_rows:
        nums_w = [row_f.get(f"num_{i}") for i in range(1, 9) if row_f.get(f"num_{i}")]
        for i in range(len(nums_w)):
            for j in range(i + 1, len(nums_w)):
                pair_count[tuple(sorted([nums_w[i], nums_w[j]]))] += 1

    df_coppie = pd.DataFrame(
        [{"num_a": a, "num_b": b, "finestre_insieme": cnt}
         for (a, b), cnt in pair_count.most_common(50)]
    ) if pair_count else pd.DataFrame()

    # ── Foglio 6: Golden6 ─────────────────────────────────────────────────────
    top4 = [int(r["numero"]) for _, r in df_numeri.head(4).iterrows()]
    coppia_score: Counter = Counter()
    for (a, b), cnt in pair_count.items():
        a_in = a in top4
        b_in = b in top4
        if a_in and not b_in:
            coppia_score[b] += cnt
        elif b_in and not a_in:
            coppia_score[a] += cnt
        elif not a_in and not b_in:
            coppia_score[a] += cnt * 0.3
            coppia_score[b] += cnt * 0.3

    top2 = [n for n, _ in coppia_score.most_common(10) if n not in top4][:2]
    golden6 = sorted(top4 + top2)

    best_shift_global = int(df_shift_rank.iloc[0]["shift"]) if len(df_shift_rank) else 100
    df_golden = pd.DataFrame(
        [{"posizione": i + 1, "numero": n,
          "ruolo": "CORE (top4)" if n in top4 else "COPPIA RESIDUA",
          "shift_ottimale_globale": best_shift_global}
         for i, n in enumerate(golden6)]
    )

    # ── Scrivi Excel ──────────────────────────────────────────────────────────
    out_path = OUT_DIR / "golden_analysis.xlsx"
    try:
        with pd.ExcelWriter(str(out_path), engine="openpyxl") as writer:
            df_grid.to_excel(writer,        sheet_name="Grid_Hits",      index=False)
            df_shift_rank.to_excel(writer,  sheet_name="Shift_Ranking",  index=False)
            df_finestre.to_excel(writer,    sheet_name="Finestre_100",   index=False)
            df_numeri.to_excel(writer,      sheet_name="Numeri_Ranking", index=False)
            if not df_coppie.empty:
                df_coppie.to_excel(writer,  sheet_name="Coppie",         index=False)
            df_golden.to_excel(writer,      sheet_name="Golden6",        index=False)
        log.info("Deep analysis salvato: %s", out_path)
    except Exception as e:
        log.error("Errore scrittura Excel: %s", e)
        return

    log.info("GOLDEN 6: %s", golden6)
    log.info("Shift ottimale globale: %d draw", best_shift_global)
    log.info("Top 4: %s | Coppia: %s", top4, top2)
    log.info(
        "Shift ranking (per draw con 4+):\n%s",
        df_shift_rank[["shift", "draw_con_4+", "pct_4+"]].to_string(index=False),
    )


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
