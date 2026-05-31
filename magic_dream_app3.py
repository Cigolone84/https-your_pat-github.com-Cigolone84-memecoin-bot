"""
magic_dream_app3.py -- Magic Dream App3
Dashboard principale: Strategie, Previsioni, Semaforo, Stato.
Non richiede backtest per avviarsi.
"""

import time
import urllib.request
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Paths ─────────────────────────────────────────────────────────────────────
APP_DIR        = Path(__file__).resolve().parent
ROOT_DIR       = APP_DIR.parent
MAGIC_LAB_DIR  = ROOT_DIR / "magic_lab"
DASHBOARD_DIR  = ROOT_DIR / "app1-app2-dashboard" / "lotto-dashboard"
BACKTEST_PATH  = DASHBOARD_DIR / "backtest_ml_storico.xlsx"
LOG_PATH       = ROOT_DIR / "magic_dream_24_7.log"

LAB_RANKING  = MAGIC_LAB_DIR / "latest_strategy_ranking.csv"
LAB_NEXT     = MAGIC_LAB_DIR / "latest_next_predictions.csv"
LAB_GAPS     = MAGIC_LAB_DIR / "latest_event_gaps.csv"
LAB_RANGE    = MAGIC_LAB_DIR / "latest_range_positions.csv"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Magic Dream",
    layout="wide",
    page_icon="🎯",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stSidebar"] { background: #111827; }
[data-testid="stSidebar"] * { color: #e5e7eb !important; }

.num-ball {
    display: inline-block;
    width: 40px; height: 40px;
    border-radius: 50%;
    line-height: 40px;
    text-align: center;
    font-weight: 700;
    font-size: 0.9rem;
    margin: 3px;
    color: #fff;
}
.c1 { background: #dc2626; }
.c2 { background: #ea580c; }
.c3 { background: #1d4ed8; }
.c4 { background: #16a34a; }
.c5 { background: #7c3aed; }
.c6 { background: #0891b2; }
.c7 { background: #059669; border: 3px solid #fbbf24; }

.semaforo-verde  { color: #16a34a; font-size: 2rem; font-weight: 700; }
.semaforo-blu    { color: #1d4ed8; font-size: 2rem; font-weight: 700; }
.semaforo-giallo { color: #d97706; font-size: 2rem; font-weight: 700; }
.semaforo-rosso  { color: #dc2626; font-size: 2rem; font-weight: 700; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ────────────────────────────────────────────────────────────────────
STRATEGY_COLORS = {
    "FreqHot8":    "c1",
    "FreqCold8":   "c2",
    "HotCold4+4":  "c3",
    "Decade8":     "c4",
    "Delay8":      "c5",
    "NucleoPool":  "c6",
    "Consensus8":  "c7",
}

AZIONE_EMOJI = {
    "attivare":        ("🟢", "ATTIVARE",        "semaforo-verde"),
    "monitorare forte":("🔵", "MONITORARE FORTE","semaforo-blu"),
    "preparare":       ("🟡", "PREPARARE",        "semaforo-giallo"),
    "non inseguire":   ("🔴", "NON INSEGUIRE",    "semaforo-rosso"),
    "osservare soltanto":("⚪","OSSERVARE",        "semaforo-rosso"),
}
AZIONE_ORDER = {"attivare": 4, "monitorare forte": 3, "preparare": 2,
                "non inseguire": 1, "osservare soltanto": 0}


def balls_html(nums_str: str, css: str = "c1") -> str:
    try:
        nums = [int(x) for x in str(nums_str).split() if x.strip().isdigit()]
        return "".join(f'<span class="num-ball {css}">{n:02d}</span>' for n in sorted(nums))
    except Exception:
        return str(nums_str)


def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://localhost:{port}/_stcore/health", timeout=2
        ) as r:
            return r.status == 200
    except Exception:
        return False


def lab_age() -> str:
    if not MAGIC_LAB_DIR.exists():
        return None
    csvs = list(MAGIC_LAB_DIR.glob("*.csv"))
    if not csvs:
        return None
    latest = max(csvs, key=lambda f: f.stat().st_mtime)
    age = (time.time() - latest.stat().st_mtime) / 60
    return f"{age:.0f} min fa"


@st.cache_data(ttl=60, show_spinner=False)
def read_csv_safe(path_str: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path_str)
    except Exception:
        return pd.DataFrame()


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🎯 Magic Dream")
    st.markdown("---")

    for port, name in [(8601, "App 1"), (8602, "App 2"), (8603, "App 3")]:
        ok = _health(port)
        icon = "✅" if ok else "❌"
        st.markdown(f"{icon} **{name}** — porta {port}")

    st.markdown("---")

    age = lab_age()
    if age is None:
        st.error("⏳ Magic Lab non ha ancora girato")
    elif int(age.split()[0]) < 200:
        st.success(f"✅ Magic Lab aggiornato ({age})")
    else:
        st.warning(f"⚠️ Magic Lab fermo ({age})")

    st.markdown("---")
    if st.button("🔄 Ricarica dati", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ── Main ───────────────────────────────────────────────────────────────────────
st.title("🎯 Magic Dream — Centro Operativo")

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Strategie",
    "🔢 Previsioni",
    "🚦 Semaforo",
    "⚙️ Stato",
])

# ─────────────────────────────── TAB 1: Strategie ────────────────────────────
with tab1:
    st.subheader("Classifica delle 6 strategie")
    st.caption("Ranking aggiornato da Magic Lab. Hit rate = % di volte con 3+ numeri indovinati su 8 giocati.")

    rank_df = read_csv_safe(str(LAB_RANKING))

    if rank_df.empty:
        st.warning(
            "⏳ **Magic Lab non ha ancora prodotto risultati.**\n\n"
            "Soluzione: assicurati che `lotto_draws.csv` sia nella cartella "
            "`app1-app2-dashboard/lotto-dashboard/` e riavvia Magic Dream.\n\n"
            "Il primo calcolo richiede 3-5 minuti."
        )
    else:
        best_row = rank_df.iloc[0]
        best_name = str(best_row.get("Strategia", "?"))
        draw_n = int(best_row.get("Draw valutati", 0))

        # Prefer T0 metrics if available (honest: play once for next draw)
        has_t0 = "Hit >=3 T0" in rank_df.columns
        if has_t0:
            best_hit3 = int(best_row.get("Hit >=3 T0", 0))
            best_medio = float(best_row.get("Hit medio T0", 0))
            best_pct = str(best_row.get("Hit >=3 T0 %", "?"))
            st.success(f"**Strategia migliore: {best_name}** — {best_pct} delle volte indovina 3+ numeri al draw T+0 (prossima estrazione)")
        else:
            best_hit3 = int(best_row.get("Hit >=3", 0))
            best_medio = float(best_row.get("Hit medio", 0))
            pct = best_hit3 / draw_n * 100 if draw_n else 0
            st.success(f"**Strategia migliore: {best_name}** — {pct:.1f}% su {draw_n} draw testati")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Strategia top", best_name)
        c2.metric("Hit medio T0", f"{best_medio:.3f}")
        pct_val = best_hit3 / draw_n * 100 if draw_n else 0
        c3.metric("Hit >=3 prossima draw", f"{pct_val:.1f}%", delta=f"+{pct_val - 2.8:.1f}% vs random")
        c4.metric("Draw testati", draw_n)

        st.markdown("---")

        # T0 columns first (honest metric), then best_hit columns
        t0_cols = [c for c in ["Rank", "Strategia", "Draw valutati",
                               "Hit medio T0", "Hit >=3 T0", "Hit >=3 T0 %", "Hit >=4 T0"] if c in rank_df.columns]
        best_cols = [c for c in ["Hit medio", "Hit >=3", "Hit >=4", "Max Hit"] if c in rank_df.columns]
        cols_show = t0_cols + best_cols if t0_cols else [c for c in [
            "Rank", "Strategia", "Draw valutati", "Hit medio", "Hit >=2", "Hit >=3", "Hit >=4", "Max Hit"
        ] if c in rank_df.columns]

        st.dataframe(rank_df[cols_show], use_container_width=True, hide_index=True)

        st.caption(
            "**T0** = prossima estrazione (metrica onesta). "
            "**Hit medio** = miglior risultato tra le 4 draw successive. "
            "Benchmark casuale: ~2.8% (3+ su 8 numeri da 1-49). "
            "**Consensus8** = voto di tutte le strategie insieme."
        )

# ─────────────────────────────── TAB 2: Previsioni ───────────────────────────
with tab2:
    st.subheader("Numeri previsti per la prossima estrazione")
    st.caption("Ogni strategia seleziona 8 numeri basandosi su metodi diversi.")

    next_df = read_csv_safe(str(LAB_NEXT))

    if next_df.empty:
        st.warning("⏳ Previsioni non ancora disponibili. Attendi che Magic Lab completi il primo ciclo.")
    else:
        # Show draw target if available
        if "Draw target" in next_df.columns and len(next_df):
            draw_target = int(next_df.iloc[0]["Draw target"])
            st.info(f"**Target: Draw #{draw_target}**")

        strat_col = "Strategia" if "Strategia" in next_df.columns else None
        pred_col  = "Predizione" if "Predizione" in next_df.columns else None

        if strat_col and pred_col:
            # Find Consensus8 prediction to highlight
            consensus_nums: set = set()
            for _, row in next_df.iterrows():
                if str(row[strat_col]) == "Consensus8":
                    consensus_nums = set(int(x) for x in str(row[pred_col]).split() if x.strip().isdigit())

            # Count how many strategies pick each number
            vote_count: Counter = Counter()
            for _, row in next_df.iterrows():
                if str(row[strat_col]) != "Consensus8":
                    for x in str(row[pred_col]).split():
                        if x.strip().isdigit():
                            vote_count[int(x)] += 1

            # Show consensus / "play these" box first
            if consensus_nums:
                st.markdown("### 🎯 Gioca questi — Consensus8")
                st.markdown(
                    "Numeri scelti da **tutte le strategie insieme** (voto di maggioranza):",
                )
                st.markdown(balls_html(" ".join(str(n) for n in consensus_nums), "c7"), unsafe_allow_html=True)
                st.markdown("---")

            # Show all strategies
            st.markdown("### Tutte le strategie")
            for _, row in next_df.iterrows():
                strat = str(row[strat_col])
                pred  = str(row[pred_col])
                css   = STRATEGY_COLORS.get(strat, "c6")
                with st.container():
                    col1, col2 = st.columns([1, 4])
                    col1.markdown(f"**{strat}**")
                    col2.markdown(balls_html(pred, css), unsafe_allow_html=True)
        else:
            st.dataframe(next_df, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.caption(
            "**FreqHot8** = caldi | "
            "**FreqCold8** = freddi | "
            "**HotCold4+4** = mix | "
            "**Decade8** = decadi | "
            "**Delay8** = massimo ritardo | "
            "**NucleoPool** = co-occorrenze | "
            "**Consensus8** = voto di tutte le strategie"
        )

# ─────────────────────────────── TAB 3: Semaforo ─────────────────────────────
with tab3:
    st.subheader("Semaforo — Quando giocare")
    st.caption(
        "Verde = ATTIVARE (momento ottimale) | "
        "Blu = MONITORARE | Giallo = PREPARARE | Rosso = NON INSEGUIRE"
    )

    range_df = read_csv_safe(str(LAB_RANGE))

    if range_df.empty:
        st.warning("⏳ Semaforo non disponibile. Magic Lab deve ancora produrre i dati.")
    else:
        eventi = [">=3", ">=4", ">=5", "=6"]
        labels = ["3 numeri", "4 numeri", "5 numeri", "6 numeri"]
        cols = st.columns(4)

        for col, ev, lbl in zip(cols, eventi, labels):
            with col:
                st.markdown(f"**{lbl} ({ev})**")
                sub = range_df[range_df["Evento"] == ev] if "Evento" in range_df.columns else pd.DataFrame()
                if len(sub):
                    sub = sub.copy()
                    sub["_rank"] = sub["Azione"].map(AZIONE_ORDER).fillna(0)
                    best = sub.sort_values("_rank", ascending=False).iloc[0]
                    azione = str(best.get("Azione", "?")).lower()
                    emoji, label, css_cls = AZIONE_EMOJI.get(azione, ("⚪", azione.upper(), "semaforo-rosso"))

                    st.markdown(f'<div class="{css_cls}">{emoji} {label}</div>', unsafe_allow_html=True)
                    st.markdown(f"Gap attuale: **{best.get('Gap attuale', '?')}** draw")
                    st.markdown(f"Gap medio: {best.get('Gap medio', '?')} draw")
                    st.caption(f"Strategia: {best.get('Strategia', '?')}")
                else:
                    st.markdown("⚪ **DATI MANCANTI**")

        st.markdown("---")

        with st.expander("Dettaglio cicli completo", expanded=False):
            gaps_df = read_csv_safe(str(LAB_GAPS))
            if not gaps_df.empty:
                st.dataframe(gaps_df, use_container_width=True, hide_index=True)
            else:
                st.info("Dati cicli non disponibili.")

# ─────────────────────────────── TAB 4: Stato ────────────────────────────────
with tab4:
    st.subheader("Stato sistema Magic Dream")

    c1, c2, c3 = st.columns(3)
    for col, port, name in [(c1, 8601, "App 1"), (c2, 8602, "App 2"), (c3, 8603, "App 3 (questa)")]:
        ok = _health(port)
        col.metric(name, "ONLINE" if ok else "OFFLINE", f"porta {port}")

    st.markdown("---")

    # Magic Lab files
    st.subheader("File Magic Lab")
    if MAGIC_LAB_DIR.exists():
        csvs = sorted(MAGIC_LAB_DIR.glob("*.csv"))
        if csvs:
            for f in csvs:
                age_sec = time.time() - f.stat().st_mtime
                age_str = f"{age_sec/60:.0f} min fa" if age_sec < 3600 else f"{age_sec/3600:.1f}h fa"
                st.markdown(f"- `{f.name}` — {f.stat().st_size:,} bytes — {age_str}")
        else:
            st.warning("Nessun CSV ancora prodotto da Magic Lab.")
    else:
        st.error("Cartella `magic_lab/` non trovata.")

    st.markdown("---")

    # Backtest
    st.subheader("File backtest (facoltativo)")
    if BACKTEST_PATH.exists():
        st.success(f"✅ Trovato: `{BACKTEST_PATH.name}`")
    else:
        st.warning(
            f"⚠️ Backtest non trovato: `{BACKTEST_PATH}`\n\n"
            "Per abilitare le analisi avanzate copia:\n"
            "- `backtest_ml_storico.xlsx`\n"
            "- `lotto_draws.csv`\n\n"
            f"Nella cartella: `{DASHBOARD_DIR}`"
        )

    st.markdown("---")

    # Log
    if LOG_PATH.exists():
        with st.expander("Log Magic Dream 24/7 (ultime 30 righe)", expanded=False):
            try:
                log_lines = LOG_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-30:]
                st.code("\n".join(log_lines), language="text")
            except Exception as e:
                st.warning(f"Log non leggibile: {e}")
    else:
        st.info("Log 24/7 non ancora creato (avvia Magic Dream 24/7).")
