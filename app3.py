"""
App3 — Lifecycle Previsioni & Copertura verso il 6
"""
import os
from math import comb
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ═══════════════════════════════════════════════════════════════════════════
BACKTEST_PATH = Path(
    r"C:\Users\serti\OneDrive\Desktop\lotto\lotto-dashboard\backtest_ml_storico.xlsx"
)
# ═══════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="App3 — Lifecycle 🎯",
    layout="wide",
    page_icon="🎯",
    initial_sidebar_state="expanded",
)

# ── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Sfondo sidebar più scuro */
[data-testid="stSidebar"] { background: #1a1a2e; }
[data-testid="stSidebar"] * { color: #e0e0e0 !important; }

/* Card metriche */
div[data-testid="metric-container"] {
    background: #1e2a3a;
    border: 1px solid #2d4060;
    border-radius: 8px;
    padding: 10px 14px;
}
div[data-testid="metric-container"] label { font-size: 0.78rem; color: #8ba0b8 !important; }
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    font-size: 1.3rem; font-weight: 700; color: #e8f0fe !important;
}

/* Badge numero — usato con st.markdown HTML */
.num-ball {
    display: inline-block;
    width: 34px; height: 34px;
    border-radius: 50%;
    line-height: 34px;
    text-align: center;
    font-weight: 700;
    font-size: 0.82rem;
    margin: 2px;
    color: #fff;
}
.nb-nucleo { background: #c62828; }
.nb-forte  { background: #e65100; }
.nb-cand   { background: #f9a825; color: #333; }
.nb-pool   { background: #1565c0; }
.nb-gray   { background: #555; }

/* Sezione card */
.card-box {
    background: #1e2a3a;
    border: 1px solid #2d4060;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 12px;
}
.card-title {
    font-size: 0.9rem;
    color: #8ba0b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
}

/* Divider sottile */
hr { border-color: #2d4060 !important; margin: 6px 0 !important; }

/* Tab labels */
button[data-baseweb="tab"] { font-size: 0.9rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_nums(s) -> frozenset:
    if pd.isna(s) or not str(s).strip():
        return frozenset()
    return frozenset(int(x) for x in str(s).split())

def fmt(nums) -> str:
    return "  ".join(f"{n:02d}" for n in sorted(nums))

def balls_html(nums, cls="nb-pool") -> str:
    """Render a list of numbers as colored circular badges."""
    return "".join(f'<span class="num-ball {cls}">{n:02d}</span>' for n in sorted(nums))

def series_get(series: pd.Series, key, default=0):
    """Safe .get() for a pandas Series (works with integer index)."""
    try:
        return series.loc[key]
    except (KeyError, TypeError):
        return default

# ── Load + cache ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_bt(_mtime):
    return pd.read_excel(BACKTEST_PATH)

@st.cache_data(ttl=300, show_spinner=False)
def build_lifecycle(_mtime):
    df_l = pd.read_excel(BACKTEST_PATH)
    n = len(df_l)

    actuals_l = [parse_nums(df_l.iloc[i]["Numeri Reali"]) for i in range(n)]
    top8s_l   = [parse_nums(df_l.iloc[i]["ML Top-8"])     for i in range(n)]
    ses_l     = [[parse_nums(df_l.iloc[i][f"Sestina {k}"]) for k in range(1, 6)] for i in range(n)]
    pools_l   = [
        top8s_l[i] | ses_l[i][0] | ses_l[i][1] | ses_l[i][2] | ses_l[i][3] | ses_l[i][4]
        for i in range(n)
    ]

    records = []
    for i in range(n):
        pool = pools_l[i]
        ses  = ses_l[i]
        row  = df_l.iloc[i]
        rec  = {
            "i": i,
            "draw": int(row["Draw"]),
            "date": str(row["Data"])[:10],
            "pool_size": len(pool),
        }
        best_pool, best_ses, best_t_pool, best_t_ses = 0, 0, 0, 0
        for t in range(4):
            j = i + t
            if j < n:
                actual = actuals_l[j]
                ph = len(pool & actual)
                sh = max(len(s & actual) for s in ses)
                rec[f"pool_hit_t{t}"] = ph
                rec[f"ses_hit_t{t}"]  = sh
                rec[f"actual_t{t}"]   = fmt(actual)
                rec[f"draw_t{t}"]     = int(df_l.iloc[j]["Draw"])
                if ph > best_pool: best_pool, best_t_pool = ph, t
                if sh > best_ses:  best_ses,  best_t_ses  = sh, t
            else:
                rec[f"pool_hit_t{t}"] = None
                rec[f"ses_hit_t{t}"]  = None
                rec[f"actual_t{t}"]   = None
                rec[f"draw_t{t}"]     = None
        rec["best_pool_hit"] = best_pool
        rec["best_ses_hit"]  = best_ses
        rec["best_t_pool"]   = best_t_pool
        rec["best_t_ses"]    = best_t_ses
        records.append(rec)

    return pd.DataFrame(records), actuals_l, pools_l, ses_l

# Sorgente autorevole (allineata a lotto.pl) per verificare il backtest
DRAWS_CSV_PATH = Path(
    r"C:\Users\serti\OneDrive\Desktop\lotto\lotto-dashboard\lotto_draws.csv"
)

@st.cache_data(ttl=300, show_spinner=False)
def check_alignment(_bt_mtime, _csv_mtime):
    """
    Confronta i 'Numeri Reali' del backtest con lotto_draws.csv (verità lotto.pl).
    Ritorna (ok, messaggi, ultime_righe_confronto).
    """
    if not DRAWS_CSV_PATH.exists():
        return None, ["CSV sorgente non trovato — impossibile verificare l'allineamento."], []

    bt = pd.read_excel(BACKTEST_PATH)
    csv = pd.read_csv(DRAWS_CSV_PATH)

    # Mappa draw → set di numeri dal CSV (la colonna 'draw' è affidabile)
    csv_map = {}
    for _, r in csv.iterrows():
        try:
            d = int(r["draw"])
        except (ValueError, TypeError):
            continue
        nums = frozenset(int(r[f"n{k}"]) for k in range(1, 7) if not pd.isna(r[f"n{k}"]))
        if len(nums) == 6:
            csv_map[d] = nums

    mismatches, phantoms, rows_cmp = [], [], []
    max_csv_draw = max(csv_map) if csv_map else 0
    futures = []
    for _, r in bt.iterrows():
        d = int(r["Draw"])
        bt_nums = parse_nums(r["Numeri Reali"])
        csv_nums = csv_map.get(d)
        if csv_nums is None:
            # Riga senza risultato reale oltre l'ultimo estratto = target futuro (legittimo)
            if not bt_nums and d > max_csv_draw:
                futures.append(d)
                status = "🔮 target futuro"
            else:
                phantoms.append(d)
                status = "👻 non nel CSV"
        elif bt_nums != csv_nums:
            mismatches.append(d)
            status = "❌ DIVERSO"
        else:
            status = "✅"
        rows_cmp.append({
            "Draw": d,
            "Backtest": fmt(bt_nums) if bt_nums else "— (futuro)",
            "CSV (lotto.pl)": fmt(csv_nums) if csv_nums else "—",
            "Stato": status,
        })

    msgs = []
    if mismatches:
        msgs.append(f"{len(mismatches)} draw con numeri DIVERSI dal CSV: {mismatches[-5:]}")
    if phantoms:
        msgs.append(f"{len(phantoms)} draw nel backtest ma non nel CSV: {phantoms[-5:]}")

    ok = (not mismatches and not phantoms)
    return ok, msgs, rows_cmp[-8:]

def auto_sync_backtest_from_csv():
    """
    Sincronizza i 'Numeri Reali' e gli Hit del backtest col CSV (verità lotto.pl).
    Fix automatico: ogni volta che App 1 aggiunge una draw al CSV ma l'auto-update
    del backtest non scatta, app3 ripara silenziosamente le righe disallineate.

    Logica:
    - Per ogni riga del backtest il cui draw è nel CSV e i numeri reali differiscono,
      sovrascrive 'Numeri Reali' col valore CSV e ricalcola ML Hit, Hit 1-5, Max Hit
      dalle previsioni già presenti (deterministico, niente fabbricazione).
    - Le righe future (draw oltre l'ultimo CSV, real vuoti) restano intatte.
    - Scrive il file solo se ci sono cambiamenti.
    Ritorna lista dei draw sincronizzati.
    """
    if not DRAWS_CSV_PATH.exists():
        return []

    bt = pd.read_excel(BACKTEST_PATH, sheet_name="Storico ML")
    csv = pd.read_csv(DRAWS_CSV_PATH)

    csv_map = {}
    for _, r in csv.iterrows():
        try:
            d = int(r["draw"])
        except (ValueError, TypeError):
            continue
        nums = frozenset(int(r[f"n{k}"]) for k in range(1, 7) if not pd.isna(r[f"n{k}"]))
        if len(nums) == 6:
            csv_map[d] = nums

    hit_cols = ["ML Hit", "Hit 1", "Hit 2", "Hit 3", "Hit 4", "Hit 5", "Max Hit"]
    for c in hit_cols:
        if c in bt.columns:
            bt[c] = bt[c].astype("object")

    synced = []
    for idx, row in bt.iterrows():
        d = int(row["Draw"])
        csv_nums = csv_map.get(d)
        if csv_nums is None:
            continue
        bt_nums = parse_nums(row["Numeri Reali"])
        if bt_nums == csv_nums:
            continue

        # Mismatch → fix
        real_str = "  ".join(f"{n:02d}" for n in sorted(csv_nums))
        bt.at[idx, "Numeri Reali"] = real_str

        top8 = parse_nums(row["ML Top-8"])
        bt.at[idx, "ML Hit"] = len(top8 & csv_nums)
        hits = []
        for k in range(1, 6):
            h = len(parse_nums(row[f"Sestina {k}"]) & csv_nums)
            bt.at[idx, f"Hit {k}"] = h
            hits.append(h)
        bt.at[idx, "Max Hit"] = max(hits)
        synced.append(d)

    if not synced:
        return []

    # Salva preservando il nome del foglio
    from openpyxl.styles import PatternFill, Font, Alignment
    with pd.ExcelWriter(BACKTEST_PATH, engine="openpyxl") as w:
        bt.to_excel(w, sheet_name="Storico ML", index=False)
        ws = w.sheets["Storico ML"]
        for cell in ws[1]:
            cell.font = Font(bold=True, color="F0A500")
            cell.fill = PatternFill("solid", fgColor="161B22")
            cell.alignment = Alignment(horizontal="center")
        for cn in hit_cols:
            if cn not in bt.columns:
                continue
            ci = bt.columns.get_loc(cn) + 1
            for ri, val in enumerate(bt[cn], start=2):
                try:
                    v = int(val)
                except (ValueError, TypeError):
                    continue
                cell = ws.cell(row=ri, column=ci)
                if v >= 4:
                    cell.fill = PatternFill("solid", fgColor="0D3B1E")
                    cell.font = Font(color="2ECC71", bold=True)
                elif v >= 3:
                    cell.fill = PatternFill("solid", fgColor="2A2A0D")
                    cell.font = Font(color="F0A500", bold=True)
                elif v >= 2:
                    cell.fill = PatternFill("solid", fgColor="1A1A2E")
                    cell.font = Font(color="3498DB")
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(
                max(len(str(c.value or "")) for c in col) + 2, 28
            )

    return synced

# ── File check ───────────────────────────────────────────────────────────────

if not BACKTEST_PATH.exists():
    st.error(f"❌ File non trovato: `{BACKTEST_PATH}`")
    st.stop()

# Auto-sync col CSV PRIMA di caricare (fix il bug "ogni volta che aggiungo una draw")
try:
    synced_draws = auto_sync_backtest_from_csv()
except PermissionError:
    synced_draws = None
    st.warning("⚠️ Backtest aperto in Excel — chiudilo per permettere l'auto-sync col CSV.")
except Exception as e:
    synced_draws = None
    st.warning(f"⚠️ Auto-sync fallito: {e}")

if synced_draws:
    st.toast(f"🔄 Backtest auto-sincronizzato dal CSV — draw: {synced_draws}", icon="✅")

mtime = os.path.getmtime(BACKTEST_PATH)

csv_mtime = os.path.getmtime(DRAWS_CSV_PATH) if DRAWS_CSV_PATH.exists() else 0

with st.spinner("Caricamento e calcolo lifecycle…"):
    df               = load_bt(mtime)
    lc, actuals, pools, ses_all = build_lifecycle(mtime)
    align_ok, align_msgs, align_rows = check_alignment(mtime, csv_mtime)

N      = len(df)
lc_full = lc[lc["pool_hit_t3"].notna()].copy()

last_draw = int(df.iloc[-1]["Draw"])
last_date = str(df.iloc[-1]["Data"])[:10]
next_draw = last_draw + 1

# ── Precompute last-prediction consensus ─────────────────────────────────────

last_row  = df.iloc[-1]
top8_last = parse_nums(last_row["ML Top-8"])
ses_sets_last = [parse_nums(last_row[f"Sestina {k}"]) for k in range(1, 6)]
num_in_ses_last = Counter()
for s in ses_sets_last:
    for num in s:
        num_in_ses_last[num] += 1

core_4plus = sorted(n for n, c in num_in_ses_last.items() if c >= 4)
core_3     = sorted(n for n, c in num_in_ses_last.items() if c == 3)
nucleus_op = sorted(set(core_4plus) | (set(core_3) & top8_last))

# ── SIDEBAR ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🎯 App3 — Lifecycle")
    st.markdown(f"**Draw analizzati:** {N}")
    st.markdown(f"**Ultimo:** #{last_draw} `{last_date}`")
    st.markdown(f"**Prossimo target:** #{next_draw}")
    st.divider()

    st.markdown("### Nucleo attuale")
    if core_4plus:
        st.markdown(
            f'<div style="margin:4px 0"><span style="font-size:0.75rem;color:#f48fb1">🔴 in 4-5 sestine</span><br>'
            + balls_html(core_4plus, "nb-nucleo") + "</div>",
            unsafe_allow_html=True
        )
    if core_3:
        st.markdown(
            f'<div style="margin:4px 0"><span style="font-size:0.75rem;color:#ffcc80">🟠 in 3 sestine</span><br>'
            + balls_html(core_3, "nb-forte") + "</div>",
            unsafe_allow_html=True
        )
    if nucleus_op:
        st.markdown(
            f'<div style="margin:4px 0"><span style="font-size:0.75rem;color:#80deea">🟢 Top-8 ∩ nucleo</span><br>'
            + balls_html(nucleus_op, "nb-pool") + "</div>",
            unsafe_allow_html=True
        )
    st.divider()

    # Timing quick-status
    n_full = len(lc_full)
    n_ses3 = int((lc_full["best_ses_hit"] >= 3).sum())
    ev3_draws = lc_full[lc_full["best_ses_hit"] >= 3]["draw"].values.astype(int)
    gap3 = (last_draw - ev3_draws[-1]) if len(ev3_draws) else 0
    gaps3_hist = np.diff(ev3_draws) if len(ev3_draws) >= 2 else np.array([0])
    pct3 = (gaps3_hist <= gap3).mean() * 100 if len(gaps3_hist) else 0

    ev4_draws = lc_full[lc_full["best_ses_hit"] >= 4]["draw"].values.astype(int)
    gap4 = (last_draw - ev4_draws[-1]) if len(ev4_draws) else 0

    color3 = "#4caf50" if pct3 < 50 else "#ff9800" if pct3 < 80 else "#f44336"
    st.markdown("### ⏱️ Timing sestina ≥ 3")
    st.markdown(
        f'<div class="card-box">'
        f'<div class="card-title">Ultimo evento</div>'
        f'<b>Draw #{ev3_draws[-1] if len(ev3_draws) else "—"}</b><br>'
        f'Gap attuale: <b style="color:{color3}">{gap3} draw</b><br>'
        f'Posizione storica: <b style="color:{color3}">{pct3:.0f}° percentile</b>'
        f'</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        f'<div class="card-box">'
        f'<div class="card-title">Ultimo ses ≥ 4</div>'
        f'<b>Draw #{ev4_draws[-1] if len(ev4_draws) else "—"}</b><br>'
        f'Gap attuale: <b>{gap4} draw</b>'
        f'</div>',
        unsafe_allow_html=True
    )

    if st.button("🔄 Ricarica dati", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── HEADER ───────────────────────────────────────────────────────────────────

st.title("🎯 Lifecycle Previsioni & Copertura Verso il 6")

# ── Banner integrità dati ────────────────────────────────────────────────────
if align_ok is None:
    st.warning("⚠️ " + " · ".join(align_msgs))
elif not align_ok:
    st.error(
        "🚨 **Backtest DISALLINEATO rispetto a lotto_draws.csv (lotto.pl)**\n\n"
        + "\n".join(f"- {m}" for m in align_msgs)
        + "\n\n**Il CSV è la verità.** Il backtest è stantio: rigeneralo da **App 1** "
          "(che legge il CSV corretto). Finché non lo rigeneri, le ultime righe qui sotto "
          "mostrano numeri sbagliati."
    )
    with st.expander("🔍 Confronto ultime 8 righe  (Backtest vs CSV)", expanded=True):
        st.dataframe(pd.DataFrame(align_rows), use_container_width=True, hide_index=True)
else:
    st.success("✅ Backtest allineato con lotto_draws.csv (lotto.pl) — dati verificati.")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Previsioni totali", N)
c2.metric("Sestina ≥ 3  (T0–T3)", f"{n_ses3}  ({n_ses3/n_full*100:.0f}%)")
c3.metric("Sestina ≥ 4  (T0–T3)", f"{int((lc_full['best_ses_hit']>=4).sum())}  ({int((lc_full['best_ses_hit']>=4).sum())/n_full*100:.1f}%)")
c4.metric("Pool ≥ 5  (T0–T3)",    f"{int((lc_full['best_pool_hit']>=5).sum())}  ({int((lc_full['best_pool_hit']>=5).sum())/n_full*100:.1f}%)")
c5.metric("Pool = 6  (T0–T3)",    f"{int((lc_full['best_pool_hit']>=6).sum())}")

st.divider()

# ════════════════════════════════════════════════════════════════════════════
tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🏠  Riepilogo",
    "📊  Storico Lifecycle",
    "⏱️  Timing & Finestra",
    "🎯  Previsione Attuale",
    "📈  Convergenze & Probabilità",
    "🥊  Confronto strategie",
])

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  TAB 0 — RIEPILOGO                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

with tab0:

    # ── Calcoli ───────────────────────────────────────────────────────────────
    def _evento(lc_df, col, thresh):
        evs = lc_df.loc[lc_df[col] >= thresh, "draw"].values.astype(int)
        if len(evs) < 2:
            return evs, np.array([999]), 999, 999
        g = np.diff(evs)
        return evs, g, float(np.median(g)), float(np.mean(g))

    ev3,  gaps3,  med3,  avg3  = _evento(lc_full, "best_ses_hit",  3)
    ev4,  gaps4,  med4,  avg4  = _evento(lc_full, "best_ses_hit",  4)
    ev5p, gaps5p, med5p, avg5p = _evento(lc_full, "best_pool_hit", 5)

    gap3_now  = int(last_draw - ev3[-1])  if len(ev3)  else 999
    gap4_now  = int(last_draw - ev4[-1])  if len(ev4)  else 999
    gap5p_now = int(last_draw - ev5p[-1]) if len(ev5p) else 999

    mancano3  = max(0, int(med3)  - gap3_now)
    mancano4  = max(0, int(med4)  - gap4_now)
    mancano5p = max(0, int(med5p) - gap5p_now)

    pct3 = float((gaps3 <= gap3_now).mean() * 100) if len(gaps3) else 0

    # ── Titolo ────────────────────────────────────────────────────────────────
    st.markdown(
        f"<h2 style='margin-bottom:4px'>🎯 Prossima finestra — Draw #{next_draw}</h2>"
        f"<p style='color:#8ba0b8;margin-top:0'>Ultima estrazione: <b>#{last_draw}</b> · "
        f"La finestra dura <b>4 draw</b> (T0 → T+1 → T+2 → T+3)</p>",
        unsafe_allow_html=True
    )
    st.divider()

    # ── 3 CARD ────────────────────────────────────────────────────────────────
    def _card(col, emoji, title, gap_now, mancano, med, avg):
        if mancano == 0:
            bg, border = "#0d2a0d", "#2e7d32"
            stato = "🟢 SEI IN FINESTRA"
            big, bigcol = "ORA", "#4caf50"
            msg = (f"Sei oltre la mediana storica ({int(med)} draw).<br>"
                   f"Hai <b>3 estrazioni</b> per coglierlo (T+1 T+2 T+3).")
        else:
            bg, border = "#1e2a3a", "#2d4060"
            stato = f"⏳ Mancano ~{mancano} draw"
            big, bigcol = f"~{mancano}", "#5ea8f5"
            msg = (f"Finestra attesa intorno a draw <b>#{next_draw + mancano}</b>.<br>"
                   f"Poi hai <b>3 estrazioni</b> per coglierlo.<br>"
                   f"Storico: ogni <b>{avg:.0f}</b> draw in media · mediana <b>{int(med)}</b>.")
        col.markdown(
            f'<div style="background:{bg};border:2px solid {border};border-radius:14px;'
            f'padding:20px 16px;min-height:190px">'
            f'<div style="font-size:.95rem;font-weight:700;color:#e8f0fe">{emoji} {title}</div>'
            f'<div style="font-size:3rem;font-weight:900;color:{bigcol};margin:10px 0 2px;line-height:1">{big}</div>'
            f'<div style="font-size:.82rem;font-weight:600;color:{border};margin-bottom:8px">{stato}</div>'
            f'<div style="font-size:.78rem;color:#aaa;line-height:1.55">{msg}</div>'
            f'<div style="font-size:.7rem;color:#555;margin-top:10px">Gap attuale: {gap_now} draw</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    c1, c2, c3 = st.columns(3)
    _card(c1, "🎯", "Sestina prende 3+ numeri", gap3_now,  mancano3,  med3,  avg3)
    _card(c2, "⭐", "Sestina prende 4+ numeri", gap4_now,  mancano4,  med4,  avg4)
    _card(c3, "🔥", "Pool contiene 5+ numeri",  gap5p_now, mancano5p, med5p, avg5p)

    st.divider()

    # ── Spiegazione ───────────────────────────────────────────────────────────
    st.markdown(
        '<div class="card-box" style="border-left:4px solid #5ea8f5;padding:14px 20px">'
        '<b>💡 Come leggere:</b> ogni card dice <b>quante draw mancano</b> prima che l\'evento '
        'diventi probabile (basato sulla storia). Quando diventa '
        '<span style="color:#4caf50"><b>ORA</b></span> sei in finestra: '
        'la previsione resta valida per <b>3 estrazioni consecutive</b>. Non cambiare nulla — aspetta e monitora.'
        '</div>',
        unsafe_allow_html=True
    )

    st.divider()

    # ── Timeline gap sestina ≥3 ────────────────────────────────────────────────
    st.markdown("#### 📊 Storico gap tra eventi sestina ≥3")
    st.caption("Ogni barra = draw passate tra un evento e il successivo. Verde = rapido, rosso = lungo.")
    if len(ev3) >= 3:
        show_n  = min(15, len(gaps3))
        g_show  = gaps3[-show_n:]
        e_show  = ev3[-show_n:]
        c_bars  = ["#4caf50" if g <= med3 * 0.8 else "#ff9800" if g <= med3 * 1.5 else "#f44336"
                   for g in g_show]
        fig_tl  = go.Figure(go.Bar(
            x=[f"#{d}" for d in e_show], y=g_show,
            marker_color=c_bars,
            text=[str(int(g)) for g in g_show], textposition="outside",
        ))
        fig_tl.add_hline(y=med3, line_dash="dot", line_color="#ffd54f",
                         annotation_text=f"mediana {int(med3)} draw",
                         annotation_position="top right")
        fig_tl.add_annotation(
            xref="paper", yref="paper", x=1.0, y=-0.22,
            text=f"Gap attuale: <b>{gap3_now} draw</b> dall'ultimo evento (#{ev3[-1]})",
            showarrow=False, font=dict(color="#5ea8f5", size=12), xanchor="right",
        )
        fig_tl.update_layout(
            height=300, margin=dict(l=10, r=20, t=30, b=70),
            plot_bgcolor="#0f1923", paper_bgcolor="#0f1923",
            font=dict(color="#c0cfe0", size=11),
            yaxis=dict(title="Draw tra eventi", gridcolor="#1e2a3a"),
            xaxis=dict(tickangle=-35), showlegend=False,
        )
        st.plotly_chart(fig_tl, use_container_width=True)
        st.caption("🟢 breve  🟠 nella norma  🔴 lungo")

    st.divider()

    # ── Numeri da monitorare ───────────────────────────────────────────────────
    st.markdown(f"#### 🧭 Numeri da monitorare — Draw #{next_draw} fino a #{next_draw+3}")
    cn1, cn2 = st.columns(2)
    with cn1:
        if core_4plus:
            st.markdown(
                '<span style="color:#f48fb1;font-size:.8rem">🔴 NUCLEO — in 4-5 sestine</span><br>'
                + balls_html(core_4plus, "nb-nucleo"), unsafe_allow_html=True)
        if core_3:
            st.markdown(
                '<span style="color:#ffcc80;font-size:.8rem">🟠 FORTI — in 3 sestine</span><br>'
                + balls_html(core_3, "nb-forte"), unsafe_allow_html=True)
    with cn2:
        st.markdown(
            '<span style="color:#80deea;font-size:.8rem">🔵 ML TOP-8</span><br>'
            + balls_html(top8_last, "nb-pool"), unsafe_allow_html=True)
    st.caption(
        f"La previsione non cambia per le prossime 3 estrazioni — "
        f"monitora su **#{next_draw}**, **#{next_draw+1}**, **#{next_draw+2}**, **#{next_draw+3}**."
    )

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  TAB 1 — STORICO LIFECYCLE                                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

with tab1:
    st.markdown(
        "**Pool** = Top-8 ∪ 5 sestine (~15–16 numeri unici).  "
        "**Best** = massimo ottenuto in una qualsiasi delle 4 estrazioni T0→T+3."
    )

    # ── Maturazione per T ─────────────────────────────────────────────────────
    st.subheader("A quale T matura l'evento?")
    cols_t = st.columns(3)
    for ci, (thr, label, color) in enumerate([
        (3, "Pool ≥ 3", "#1565c0"),
        (4, "Pool ≥ 4", "#e65100"),
        (5, "Pool ≥ 5", "#c62828"),
    ]):
        sub = lc_full[lc_full["best_pool_hit"] >= thr]
        total = len(sub)
        if total == 0:
            cols_t[ci].write(f"**{label}** — nessun evento")
            continue
        dist = sub["best_t_pool"].value_counts().sort_index()
        fig_t = px.bar(
            x=[f"T+{t}" for t in range(4)],
            y=[series_get(dist, t, 0) for t in range(4)],
            title=f"{label}  ({total} eventi)",
            labels={"x": "", "y": ""},
            color_discrete_sequence=[color],
            text=[f"{series_get(dist,t,0)/total*100:.0f}%" for t in range(4)],
        )
        fig_t.update_traces(textposition="outside")
        fig_t.update_layout(height=220, margin=dict(l=10, r=10, t=40, b=20), showlegend=False)
        cols_t[ci].plotly_chart(fig_t, use_container_width=True)

    # ── Timeline ─────────────────────────────────────────────────────────────
    st.subheader("Timeline")
    col_sl, _ = st.columns([1, 3])
    pool_thr = col_sl.slider("Pool hit da evidenziare ≥", 2, 6, 3, key="thr_pool")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=lc["draw"], y=lc["pool_hit_t0"],
        mode="lines", name="Pool hit T0",
        line=dict(color="rgba(100,160,220,0.35)", width=1),
    ))
    fig.add_trace(go.Scatter(
        x=lc_full["draw"], y=lc_full["best_pool_hit"],
        mode="lines", name="Best pool T0→T+3",
        line=dict(color="#5ea8f5", width=1.8),
    ))
    hi = lc_full[lc_full["best_pool_hit"] >= pool_thr]
    fig.add_trace(go.Scatter(
        x=hi["draw"], y=hi["best_pool_hit"], mode="markers",
        name=f"Pool ≥ {pool_thr}",
        marker=dict(
            color=hi["best_pool_hit"].astype(float),
            colorscale=[[0, "gold"], [0.5, "orange"], [1, "red"]],
            cmin=float(pool_thr), cmax=6.0,
            size=10, line=dict(width=1, color="white"),
        ),
        text=hi["date"] + "<br>Draw #" + hi["draw"].astype(str),
        hovertemplate="%{text}<br>Pool hit: %{y}<extra></extra>",
    ))
    ses4 = lc_full[lc_full["best_ses_hit"] >= 4]
    fig.add_trace(go.Scatter(
        x=ses4["draw"], y=ses4["best_ses_hit"], mode="markers",
        name="Sestina ≥ 4",
        marker=dict(symbol="star", size=15, color="red", line=dict(width=1, color="white")),
        hovertemplate="Draw %{x}<br>Sestina: %{y}<extra></extra>",
    ))
    fig.update_layout(
        xaxis_title="Draw #", yaxis_title="Numeri corretti",
        height=380, plot_bgcolor="#0f1923", paper_bgcolor="#0f1923",
        font=dict(color="#c0cfe0"),
        xaxis=dict(gridcolor="#1e2a3a", color="#7a90a8"),
        yaxis=dict(gridcolor="#1e2a3a", color="#7a90a8"),
        legend=dict(orientation="h", y=1.02, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=40, r=20, t=30, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Distribuzione ─────────────────────────────────────────────────────────
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.markdown("**Distribuzione best pool hit**")
        dist_p = lc_full["best_pool_hit"].value_counts().sort_index()
        fig2 = px.bar(
            x=dist_p.index.astype(str), y=dist_p.values,
            color=dist_p.index.astype(float),
            color_continuous_scale=["#2196f3", "gold", "orange", "red"],
            text=dist_p.values,
        )
        fig2.update_traces(textposition="outside")
        fig2.update_layout(
            height=260, showlegend=False, coloraxis_showscale=False,
            plot_bgcolor="#0f1923", paper_bgcolor="#0f1923",
            font=dict(color="#c0cfe0"),
            margin=dict(l=10, r=10, t=10, b=30),
        )
        st.plotly_chart(fig2, use_container_width=True)
    with col_d2:
        st.markdown("**Distribuzione best sestina hit**")
        dist_s = lc_full["best_ses_hit"].value_counts().sort_index()
        fig3 = px.bar(
            x=dist_s.index.astype(str), y=dist_s.values,
            color=dist_s.index.astype(float),
            color_continuous_scale=["#2196f3", "gold", "orange", "red"],
            text=dist_s.values,
        )
        fig3.update_traces(textposition="outside")
        fig3.update_layout(
            height=260, showlegend=False, coloraxis_showscale=False,
            plot_bgcolor="#0f1923", paper_bgcolor="#0f1923",
            font=dict(color="#c0cfe0"),
            margin=dict(l=10, r=10, t=10, b=30),
        )
        st.plotly_chart(fig3, use_container_width=True)

    # ── Tabella eventi ────────────────────────────────────────────────────────
    st.subheader("Tabella eventi")
    col_f, _ = st.columns([1, 3])
    min_hit_tab = col_f.selectbox("Best pool hit ≥", [2, 3, 4, 5, 6], index=1, key="tab_filter")

    sig = lc_full[lc_full["best_pool_hit"] >= min_hit_tab].copy()
    sig["best_ses"] = sig["best_ses_hit"]
    display_cols = {
        "draw": "Draw", "date": "Data", "pool_size": "Pool",
        "pool_hit_t0": "T0", "pool_hit_t1": "T+1",
        "pool_hit_t2": "T+2", "pool_hit_t3": "T+3",
        "best_pool_hit": "Best pool", "best_ses": "Best ses",
        "best_t_pool": "Matura",
    }
    tbl = sig[[c for c in display_cols if c in sig.columns]].rename(columns=display_cols)
    tbl = tbl.sort_values("Draw", ascending=False).reset_index(drop=True)

    def _style_cell(val):
        try:
            v = int(val)
        except (TypeError, ValueError):
            return ""
        if v >= 5: return "background-color:#7b1f1f; color:#fff; font-weight:bold"
        if v == 4: return "background-color:#6d3700; color:#fff; font-weight:bold"
        if v == 3: return "background-color:#5c4c00; color:#fff"
        return ""

    # pandas ≥ 2.1 usa .map(); versioni precedenti .applymap()
    try:
        styled = tbl.style.map(_style_cell, subset=["Best pool", "Best ses"])
    except AttributeError:
        styled = tbl.style.applymap(_style_cell, subset=["Best pool", "Best ses"])

    st.dataframe(styled, use_container_width=True, height=380)

    # ── Casi quintina espansi ─────────────────────────────────────────────────
    q5 = lc_full[lc_full["best_pool_hit"] >= 5]
    if len(q5):
        with st.expander(f"🔴  {len(q5)} casi pool ≥ 5 nel lifecycle — espandi per dettagli"):
            for _, row in q5.iterrows():
                idx   = int(row["i"])
                bt    = int(row["best_t_pool"])
                ph    = int(row["best_pool_hit"])
                dq    = int(row["draw"])
                dm    = row.get(f"draw_t{bt}", dq) or dq
                actual_set = actuals[idx + bt] if (idx + bt) < N else frozenset()
                pool_q  = pools[idx]
                in_p    = pool_q & actual_set
                miss    = actual_set - pool_q

                freq_q = Counter()
                for s in ses_all[idx]:
                    for num in s: freq_q[num] += 1
                hf = sorted(n for n, c in freq_q.items() if c >= 4)

                st.markdown(
                    f"**Draw #{dq} → #{dm}** (T+{bt}) — "
                    f"pool hit **{ph}/6** — "
                    f"✅ in pool: `{fmt(in_p)}` — "
                    f"❌ fuori: `{fmt(miss)}` — "
                    f"🔥 4+sestine: `{fmt(hf) if hf else '—'}`"
                )

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  TAB 2 — TIMING & FINESTRA                                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝

with tab2:

    col_ctrl1, col_ctrl2, _ = st.columns([1, 1, 2])
    gap_thr  = col_ctrl1.selectbox("Soglia sestina hit ≥", [3, 4], key="gap_thr")
    win_type = col_ctrl2.radio("Finestra", ["T0→T+3", "T0 solo"], key="gap_win", horizontal=True)

    if win_type == "T0→T+3":
        ev_df   = lc_full[lc_full["best_ses_hit"] >= gap_thr]
    else:
        ev_df   = lc[lc["ses_hit_t0"].fillna(0) >= gap_thr]

    if len(ev_df) < 2:
        st.warning("Troppo pochi eventi per l'analisi gap.")
        st.stop()

    ev_draws = ev_df["draw"].values.astype(int)
    gaps     = np.diff(ev_draws)

    # ── Metriche timing ───────────────────────────────────────────────────────
    last_ev      = int(ev_draws[-1])
    current_gap  = last_draw - last_ev
    pct_pos      = float((gaps <= current_gap).mean() * 100)
    gap_median   = float(np.median(gaps))
    gap_p25      = float(np.percentile(gaps, 25))
    gap_p75      = float(np.percentile(gaps, 75))

    urgency_color = "#4caf50" if pct_pos < 40 else "#ff9800" if pct_pos < 70 else "#f44336"

    cc1, cc2, cc3, cc4 = st.columns(4)
    cc1.metric("N eventi totali", len(ev_df))
    cc2.metric("Gap medio", f"{gaps.mean():.1f}")
    cc3.metric("Mediana gap", f"{gap_median:.0f}")
    cc4.metric("Gap attuale", f"{current_gap} draw")

    st.markdown(
        f'<div class="card-box" style="border-left: 4px solid {urgency_color}; margin-top:8px">'
        f'<span class="card-title">Posizione nel ciclo storico</span><br>'
        f'Ultimo evento: <b>Draw #{last_ev}</b>  ·  '
        f'Gap corrente: <b style="color:{urgency_color}">{current_gap} draw</b>  ·  '
        f'Percentile storico: <b style="color:{urgency_color}">{pct_pos:.0f}°</b>  ·  '
        f'IQR storico: <b>{gap_p25:.0f}–{gap_p75:.0f}</b>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Grafici affiancati ─────────────────────────────────────────────────────
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown("**Distribuzione gap**")
        fig_gap = px.histogram(
            x=gaps, nbins=25,
            labels={"x": "Gap (draw)", "y": "Frequenza"},
            color_discrete_sequence=["#4472c4"],
        )
        fig_gap.add_vline(x=current_gap, line_dash="dash", line_color="red",
                          annotation_text=f"Ora: {current_gap}", annotation_position="top right")
        fig_gap.add_vline(x=gap_median, line_dash="dot", line_color="gold",
                          annotation_text=f"Mediana: {gap_median:.0f}", annotation_position="top left")
        fig_gap.update_layout(
            height=300, plot_bgcolor="#0f1923", paper_bgcolor="#0f1923",
            font=dict(color="#c0cfe0"), margin=dict(l=30, r=20, t=10, b=40),
        )
        st.plotly_chart(fig_gap, use_container_width=True)

    with col_r:
        st.markdown("**CDF storica — dove siamo ora**")
        gap_sorted = np.sort(gaps)
        cdf = np.arange(1, len(gap_sorted) + 1) / len(gap_sorted) * 100
        fig_cdf = go.Figure()
        fig_cdf.add_trace(go.Scatter(
            x=gap_sorted, y=cdf, mode="lines",
            line=dict(color="#5ea8f5", width=2), name="CDF",
            fill="tozeroy", fillcolor="rgba(94,168,245,0.1)",
        ))
        fig_cdf.add_vline(x=current_gap, line_dash="dash", line_color="red",
                          annotation_text=f"{pct_pos:.0f}%", annotation_position="top right")
        fig_cdf.update_layout(
            xaxis_title="Gap (draw)", yaxis_title="% accaduti entro",
            height=300, plot_bgcolor="#0f1923", paper_bgcolor="#0f1923",
            font=dict(color="#c0cfe0"), margin=dict(l=40, r=20, t=10, b=40),
            showlegend=False,
        )
        st.plotly_chart(fig_cdf, use_container_width=True)

    # ── Tabella probabilità sperimentali ──────────────────────────────────────
    st.subheader("Probabilità sperimentali")
    prob_rows = []
    for w in [1, 2, 3, 4, 5, 7, 10, 15, 20]:
        n_w = int((gaps <= w).sum())
        prob_rows.append({
            "Entro N draw": w,
            "Casi": n_w,
            "Totale gap": len(gaps),
            "% storica": f"{n_w/len(gaps)*100:.1f}%",
            "Freq. attesa": f"1 ogni {len(ev_draws)/n_w:.1f} previsioni" if n_w else "—",
        })
    st.dataframe(pd.DataFrame(prob_rows), use_container_width=True, hide_index=True)

    # ── Storico gap nel tempo ─────────────────────────────────────────────────
    st.subheader("Storico gap nel tempo")
    fig_bar = go.Figure(go.Bar(
        x=ev_draws[1:], y=gaps,
        marker_color=["#f44336" if g <= 3 else "#ff9800" if g <= 7 else "#4472c4" for g in gaps],
        name="Gap",
    ))
    fig_bar.add_hline(y=gap_median, line_dash="dot", line_color="gold",
                      annotation_text=f"Mediana {gap_median:.0f}", annotation_position="top right")
    fig_bar.update_layout(
        xaxis_title="Draw #", yaxis_title="Gap",
        height=280, plot_bgcolor="#0f1923", paper_bgcolor="#0f1923",
        font=dict(color="#c0cfe0"),
        xaxis=dict(gridcolor="#1e2a3a"), yaxis=dict(gridcolor="#1e2a3a"),
        margin=dict(l=40, r=20, t=20, b=40),
        showlegend=False,
    )
    st.caption("🔴 ≤3 draw  🟠 4–7  🔵 >7")
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── Cluster ───────────────────────────────────────────────────────────────
    st.subheader("Analisi cluster")
    for thr2 in [3, 4]:
        ev2 = lc_full[lc_full["best_ses_hit"] >= thr2]["draw"].values.astype(int)
        if len(ev2) < 2: continue
        g2 = np.diff(ev2)
        c2 = int((g2 <= 2).sum()); c3 = int((g2 <= 3).sum())
        st.markdown(
            f"**Ses ≥ {thr2}** ({len(ev2)} eventi) — "
            f"cluster ≤2 draw: **{c2}/{len(g2)}** ({c2/len(g2)*100:.0f}%) | "
            f"cluster ≤3 draw: **{c3}/{len(g2)}** ({c3/len(g2)*100:.0f}%)"
        )

# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  TAB 3 — PREVISIONE ATTUALE                                            ║
# ╚══════════════════════════════════════════════════════════════════════════╝

with tab3:

    # ── Selector ─────────────────────────────────────────────────────────────
    col_ns, _ = st.columns([1, 3])
    n_last = col_ns.slider("Ultime N previsioni per consensus", 1, 10, 1, key="n_last")
    last_rows = df.tail(n_last)

    # Ricalcola consensus per le N righe selezionate
    cnt_ses  = Counter()
    cnt_top8 = Counter()
    for _, row in last_rows.iterrows():
        t8 = parse_nums(row["ML Top-8"])
        for num in t8: cnt_top8[num] += 1
        n_ses_map = Counter()
        for k in range(1, 6):
            for num in parse_nums(row[f"Sestina {k}"]): n_ses_map[num] += 1
        for num, c in n_ses_map.items(): cnt_ses[num] += c

    rows_cons = [
        {
            "Numero": num,
            "In sestine": cnt_ses.get(num, 0),
            "In Top-8": cnt_top8.get(num, 0),
            "Score": cnt_ses.get(num, 0) * 2 + cnt_top8.get(num, 0) * 3,
        }
        for num in range(1, 50)
    ]
    df_cons = pd.DataFrame(rows_cons).sort_values("Score", ascending=False)
    df_cons = df_cons[df_cons["Score"] > 0].reset_index(drop=True)

    top_sc = int(df_cons["Score"].max()) if len(df_cons) else 1

    def tier_label(sc):
        if sc >= top_sc * 0.85: return "⭐⭐⭐ NUCLEO"
        if sc >= top_sc * 0.60: return "⭐⭐ FORTE"
        if sc >= top_sc * 0.35: return "⭐ CANDIDATO"
        return "— debole"

    df_cons["Tier"] = df_cons["Score"].apply(tier_label)
    df_cons["Num"] = df_cons["Numero"].apply(lambda x: f"{x:02d}")
    df_cons = df_cons[["Num", "In sestine", "In Top-8", "Score", "Tier"]]

    nucleo_n = df_cons[df_cons["Tier"].str.contains("NUCLEO")]["Num"].tolist()
    forte_n  = df_cons[df_cons["Tier"].str.contains("FORTE")]["Num"].tolist()
    cand_n   = df_cons[df_cons["Tier"].str.contains("CANDIDATO")]["Num"].tolist()

    # ── Balls display ─────────────────────────────────────────────────────────
    st.subheader(f"Consensus core  —  Draw #{last_draw}")
    if nucleo_n:
        st.markdown(
            f'<div style="margin:8px 0"><span style="color:#f48fb1;font-size:0.85rem">⭐⭐⭐ NUCLEO</span><br>'
            + "".join(f'<span class="num-ball nb-nucleo">{n}</span>' for n in nucleo_n)
            + "</div>",
            unsafe_allow_html=True,
        )
    if forte_n:
        st.markdown(
            f'<div style="margin:8px 0"><span style="color:#ffcc80;font-size:0.85rem">⭐⭐ FORTE</span><br>'
            + "".join(f'<span class="num-ball nb-forte">{n}</span>' for n in forte_n)
            + "</div>",
            unsafe_allow_html=True,
        )
    if cand_n:
        st.markdown(
            f'<div style="margin:8px 0"><span style="color:#fff9c4;font-size:0.85rem">⭐ CANDIDATO</span><br>'
            + "".join(f'<span class="num-ball nb-cand">{n}</span>' for n in cand_n)
            + "</div>",
            unsafe_allow_html=True,
        )

    # ── Consensus table ────────────────────────────────────────────────────────
    def _style_tier(val):
        if "NUCLEO" in str(val): return "background-color:#4a0000; color:#ffaaaa; font-weight:bold"
        if "FORTE"  in str(val): return "background-color:#4a2000; color:#ffcc88; font-weight:bold"
        if "CANDIDATO" in str(val): return "background-color:#3a3000; color:#ffe082"
        return "color:#666"

    try:
        styled_cons = df_cons.style.map(_style_tier, subset=["Tier"])
    except AttributeError:
        styled_cons = df_cons.style.applymap(_style_tier, subset=["Tier"])

    with st.expander("Tabella completa consensus", expanded=False):
        st.dataframe(styled_cons, use_container_width=True, height=380)

    # ── Bar chart ──────────────────────────────────────────────────────────────
    top20 = df_cons.head(20)
    tier_color_map = {
        "⭐⭐⭐ NUCLEO": "#c62828",
        "⭐⭐ FORTE":   "#e65100",
        "⭐ CANDIDATO": "#f9a825",
        "— debole":    "#555",
    }
    fig_bar2 = go.Figure(go.Bar(
        x=top20["Num"], y=top20["Score"],
        marker_color=[tier_color_map.get(t, "#555") for t in top20["Tier"]],
        text=top20["Score"], textposition="outside",
    ))
    fig_bar2.update_layout(
        title="Top 20 — Score consensus",
        xaxis_title="Numero", yaxis_title="Score",
        height=300, plot_bgcolor="#0f1923", paper_bgcolor="#0f1923",
        font=dict(color="#c0cfe0"),
        xaxis=dict(gridcolor="#1e2a3a"), yaxis=dict(gridcolor="#1e2a3a"),
        margin=dict(l=30, r=20, t=40, b=30),
    )
    st.plotly_chart(fig_bar2, use_container_width=True)

    # ── Sestine detail ──────────────────────────────────────────────────────────
    st.subheader(f"Sestine  —  Draw #{last_draw}")
    col_s, col_h = st.columns([3, 2])

    with col_s:
        ses_tbl = []
        for k, s in enumerate(ses_sets_last, 1):
            in_t8 = s & top8_last
            ses_tbl.append({
                "S": f"S{k}",
                "Numeri": fmt(s),
                "∩ Top-8": fmt(in_t8),
                "N hit": len(in_t8),
            })
        st.dataframe(pd.DataFrame(ses_tbl), use_container_width=True, hide_index=True)
        st.markdown(f"**Top-8:** " + balls_html(top8_last, "nb-pool"), unsafe_allow_html=True)

    with col_h:
        # Heatmap 7×7
        grid = np.zeros((7, 7))
        for num2, cnt2 in num_in_ses_last.items():
            r = (num2 - 1) // 7; cc2 = (num2 - 1) % 7
            grid[r, cc2] = cnt2
        labels_h = [[f"{r2*7+c2+1:02d}" for c2 in range(7)] for r2 in range(7)]
        vals_h   = [[int(grid[r2, c2]) for c2 in range(7)] for r2 in range(7)]
        fig_hm = go.Figure(go.Heatmap(
            z=vals_h, text=labels_h, texttemplate="%{text}",
            colorscale="YlOrRd", zmin=0, zmax=5, showscale=False,
        ))
        fig_hm.update_layout(
            title="Freq. per numero (5 sestine)",
            height=280, margin=dict(l=10, r=10, t=40, b=10),
            plot_bgcolor="#0f1923", paper_bgcolor="#0f1923",
            font=dict(color="#c0cfe0", size=10),
            xaxis=dict(showticklabels=False), yaxis=dict(showticklabels=False, autorange="reversed"),
        )
        st.plotly_chart(fig_hm, use_container_width=True)

    # ── Nucleo operativo ────────────────────────────────────────────────────────
    st.subheader(f"🧭 Nucleo operativo  →  Draw #{next_draw}")
    nuc_html = balls_html(nucleus_op, "nb-nucleo") if nucleus_op else balls_html(core_4plus[:5], "nb-nucleo")
    pool_html = balls_html(top8_last, "nb-pool")

    cn_a, cn_b = st.columns(2)
    cn_a.markdown(
        '<div class="card-box">'
        '<div class="card-title">Top-8 (pool base)</div>'
        + pool_html + "</div>",
        unsafe_allow_html=True,
    )
    cn_b.markdown(
        '<div class="card-box">'
        '<div class="card-title">Nucleo (4-5 ses + top8∩3-ses)</div>'
        + (nuc_html if nuc_html else "<i>—</i>") + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"**Previsione congelata** → monitorare su draw "
        f"**#{next_draw}** · **#{next_draw+1}** · **#{next_draw+2}** · **#{next_draw+3}**"
    )

    # ── Copertura ────────────────────────────────────────────────────────────────
    st.subheader("📐 Copertura verso il 6")
    cover_data = []
    for fixed in range(3, 6):
        remaining = 49 - fixed
        missing   = 6 - fixed
        for residui in [5, 8, 10, 12, 15]:
            if residui <= remaining:
                cover_data.append({
                    "Nucleo fisso": fixed,
                    "Da trovare": missing,
                    "Residui": residui,
                    "Sestine": comb(residui, missing),
                    "Costo ~3 PLN": f"{comb(residui, missing) * 3} PLN",
                })
    df_cov = pd.DataFrame(cover_data)

    def _style_cost(val):
        try:
            v = int(str(val).replace(" PLN", ""))
            if v <= 90:  return "background-color:#1a3a1a; color:#a5d6a7; font-weight:bold"
            if v <= 150: return "background-color:#3a2a00; color:#ffe082"
            return ""
        except (ValueError, TypeError):
            return ""

    try:
        styled_cov = df_cov.style.map(_style_cost, subset=["Costo ~3 PLN"])
    except AttributeError:
        styled_cov = df_cov.style.applymap(_style_cost, subset=["Costo ~3 PLN"])

    st.dataframe(styled_cov, use_container_width=True, hide_index=True)

    # ── Casi storici quintina ────────────────────────────────────────────────────
    st.subheader("🔬 Casi storici pool ≥ 5  —  Pattern nucleo")
    q5c = lc_full[lc_full["best_pool_hit"] >= 5].copy()
    if len(q5c) == 0:
        st.info("Nessun caso pool ≥ 5.")
    else:
        with st.expander(f"{len(q5c)} casi pool ≥ 5 — clicca per espandere"):
            for _, qr in q5c.iterrows():
                idx_q  = int(qr["i"]); bt = int(qr["best_t_pool"])
                actual_q = actuals[idx_q + bt] if (idx_q + bt) < N else frozenset()
                pool_q   = pools[idx_q]
                in_p     = pool_q & actual_q
                miss_q   = actual_q - pool_q
                fq = Counter()
                for sq in ses_all[idx_q]:
                    for nq in sq: fq[nq] += 1
                hfq = sorted(n for n, c in fq.items() if c >= 4)

                st.markdown(
                    f"**#{int(qr['draw'])} → #{int(qr.get(f'draw_t{bt}', qr['draw']) or qr['draw'])}** "
                    f"(T+{bt}) — "
                    f"✅ `{fmt(in_p)}` — ❌ `{fmt(miss_q)}` — "
                    f"🔥 4+ses: `{fmt(hfq) if hfq else '—'}` — "
                    f"Reali in nucleo: `{fmt(actual_q & set(hfq)) if hfq else '—'}`"
                )

    # ── Registro T+k ────────────────────────────────────────────────────────────
    st.subheader("Registro T+k")
    st.caption("Aggiornato automaticamente quando backtest_ml_storico.xlsx viene aggiornato.")
    mon_df = pd.DataFrame({
        "Finestra":     [f"T+0  (#{next_draw})", f"T+1  (#{next_draw+1})",
                         f"T+2  (#{next_draw+2})", f"T+3  (#{next_draw+3})"],
        "Data":         ["—"] * 4,
        "Numeri reali": ["—"] * 4,
        "Pool hit":     ["—"] * 4,
        "Best sestina": ["—"] * 4,
    })
    st.dataframe(mon_df, use_container_width=True, hide_index=True)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  TAB 4 — CONVERGENZE & PROBABILITÀ SPERIMENTALI                         ║
# ╚══════════════════════════════════════════════════════════════════════════╝

with tab4:
    st.header("📈 Convergenze & Probabilità Sperimentali")
    st.caption(
        "Tutto calcolato su dati reali (500 walk-forward draw). Ogni numero "
        "viene confrontato con la baseline random e mostra IC 95% (Wilson). "
        "Niente promesse, solo evidenza."
    )

    from math import comb as _comb, sqrt as _sqrt

    # ── Helpers statistici ──────────────────────────────────────────────────────
    def wilson_ci(k, n, z=1.96):
        if n == 0:
            return (0.0, 0.0)
        p = k / n
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        half = (z * _sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
        return (max(0, center - half), min(1, center + half))

    def hypergeom_p(K, n, k):
        if k < 0 or k > min(K, n) or K > 49 or n > 49:
            return 0.0
        return _comb(K, k) * _comb(49 - K, n - k) / _comb(49, n)

    def hypergeom_ge(K, n, k):
        return sum(hypergeom_p(K, n, j) for j in range(k, min(K, n) + 1))

    def max_sestine_random_ge(k, m=5):
        p_single_lt = 1 - hypergeom_ge(6, 6, k)
        return 1 - p_single_lt ** m

    # ─── 1. PROBABILITÀ BASE  (Sestina e Pool, T0 + lifecycle) ─────────────────
    st.subheader("1. Probabilità sperimentali  vs  baseline random")

    n_full = len(lc_full)

    rows_prob = []
    metrics = [
        ("Sestina ≥ 3  (T0 secco)",  lc["ses_hit_t0"].dropna(),   3, max_sestine_random_ge(3)),
        ("Sestina ≥ 4  (T0 secco)",  lc["ses_hit_t0"].dropna(),   4, max_sestine_random_ge(4)),
        ("Sestina ≥ 5  (T0 secco)",  lc["ses_hit_t0"].dropna(),   5, max_sestine_random_ge(5)),
        ("Sestina ≥ 3  (lifecycle T0–T3)",  lc_full["best_ses_hit"], 3, 1 - (1 - max_sestine_random_ge(3))**4),
        ("Sestina ≥ 4  (lifecycle T0–T3)",  lc_full["best_ses_hit"], 4, 1 - (1 - max_sestine_random_ge(4))**4),
        ("Pool ≥ 4  (lifecycle, pool=15)",  lc_full["best_pool_hit"], 4, 1 - (1 - hypergeom_ge(15, 6, 4))**4),
        ("Pool ≥ 5  (lifecycle, pool=15)",  lc_full["best_pool_hit"], 5, 1 - (1 - hypergeom_ge(15, 6, 5))**4),
        ("Pool = 6  (lifecycle, pool=15)",  lc_full["best_pool_hit"], 6, 1 - (1 - hypergeom_ge(15, 6, 6))**4),
    ]
    for lbl, series, k, baseline in metrics:
        vals = series.values
        n = len(vals)
        hits = int((vals >= k).sum())
        p = hits / n if n else 0
        lo, hi = wilson_ci(hits, n)
        lift = p - baseline
        if lo > baseline:
            signif = "✅"
        elif hi < baseline:
            signif = "⚠️"
        else:
            signif = "—"
        rows_prob.append({
            "Metrica": lbl,
            "N": n,
            "Eventi": hits,
            "P sperimentale": f"{p*100:.2f}%",
            "IC 95%": f"[{lo*100:.2f}%, {hi*100:.2f}%]",
            "Baseline random": f"{baseline*100:.2f}%",
            "Lift": f"{lift*100:+.2f}%",
            "Significativo": signif,
        })

    st.dataframe(pd.DataFrame(rows_prob), use_container_width=True, hide_index=True)
    st.caption(
        "✅ = IC inferiore > baseline → meglio del caso al 95%. "
        "⚠️ = IC superiore < baseline → peggio del caso. "
        "— = indistinguibile dal caso."
    )

    # ─── 2. CURVA WALK-FORWARD — ROLLING MAX HIT ───────────────────────────────
    st.subheader("2. Curva di apprendimento  (rolling Max Hit)")
    st.caption("Il modello migliora o degrada nel tempo? Confronto con baseline random.")

    s = lc["ses_hit_t0"].dropna().astype(float).reset_index(drop=True)
    fig_roll = go.Figure()
    for win, color in [(20, "#90caf9"), (50, "#42a5f5"), (100, "#1565c0")]:
        if len(s) >= win:
            roll = s.rolling(win, min_periods=win).mean()
            fig_roll.add_trace(go.Scatter(
                x=lc["draw"].iloc[:len(roll)], y=roll, mode="lines",
                name=f"rolling {win}",
                line=dict(color=color, width=2 if win == 50 else 1.5),
            ))
    exp_max = sum(k * (max_sestine_random_ge(k) - max_sestine_random_ge(k + 1)) for k in range(7))
    fig_roll.add_hline(
        y=exp_max, line_dash="dash", line_color="#e74c3c",
        annotation_text=f"Baseline random ({exp_max:.3f})",
        annotation_position="right",
    )
    fig_roll.update_layout(
        xaxis_title="Draw #", yaxis_title="Max Hit medio (T0)",
        height=360, margin=dict(l=40, r=20, t=20, b=40),
        legend=dict(orientation="h", y=1.05),
    )
    st.plotly_chart(fig_roll, use_container_width=True)

    cur_mean = float(s.tail(50).mean()) if len(s) >= 50 else float(s.mean())
    delta = cur_mean - exp_max
    cA, cB, cC = st.columns(3)
    cA.metric("Media ultimi 50 draw", f"{cur_mean:.3f}")
    cB.metric("Baseline random", f"{exp_max:.3f}")
    cC.metric("Edge", f"{delta:+.3f}", delta=f"{delta/exp_max*100:+.1f}%" if exp_max else "—")

    # ─── 3. SCATTER: CONSENSUS vs MAX HIT ──────────────────────────────────────
    st.subheader("3. Consensus intensity  vs  Max Hit")
    st.caption(
        "X = quanti numeri stanno in 4-5 sestine in quella previsione. "
        "Y = Max Hit realizzato. Se il modello 'sa quando è sicuro' → correlazione positiva."
    )

    cons_intensity = []
    max_hits_t0 = []
    for i in range(N):
        s_list = ses_all[i]
        cnt = Counter()
        for ss in s_list:
            for nu in ss:
                cnt[nu] += 1
        cons_intensity.append(sum(1 for v in cnt.values() if v >= 4))
        v0 = lc.iloc[i].get("ses_hit_t0")
        max_hits_t0.append(v0 if pd.notna(v0) else None)

    df_scat = pd.DataFrame({
        "consensus": cons_intensity,
        "maxhit_t0": max_hits_t0,
    }).dropna(subset=["maxhit_t0"])

    cor_t0 = df_scat["consensus"].corr(df_scat["maxhit_t0"]) if len(df_scat) >= 2 else None
    # Jitter manuale per separare punti sovrapposti
    rng = np.random.default_rng(42)
    df_scat = df_scat.copy()
    df_scat["x_jit"] = df_scat["consensus"] + rng.uniform(-0.25, 0.25, len(df_scat))
    df_scat["y_jit"] = df_scat["maxhit_t0"] + rng.uniform(-0.15, 0.15, len(df_scat))
    fig_sc = px.scatter(
        df_scat, x="x_jit", y="y_jit",
        labels={"x_jit": "# numeri in 4-5 sestine", "y_jit": "Max Hit T0"},
        color="maxhit_t0",
        color_continuous_scale=["#5b86b3", "#90caf9", "#ffd54f", "#ff8a65", "#e53935"],
        range_color=[0, 5],
    )
    fig_sc.update_traces(marker=dict(size=6, opacity=0.55))
    if cor_t0 is not None:
        fig_sc.add_annotation(
            xref="paper", yref="paper", x=0.02, y=0.98,
            text=f"<b>Correlazione Pearson: {cor_t0:.3f}</b>",
            showarrow=False, bgcolor="#1e2a3a", bordercolor="#90caf9",
            font=dict(color="#e8f0fe"),
        )
    fig_sc.update_layout(height=360, margin=dict(l=40, r=20, t=20, b=40), showlegend=False)
    st.plotly_chart(fig_sc, use_container_width=True)

    st.markdown("**P(Max Hit ≥ 3 | consensus intensity ≥ X)**")
    base_rate_3 = (df_scat["maxhit_t0"] >= 3).mean()
    cond_rows = []
    for thr in range(0, 7):
        sub = df_scat[df_scat["consensus"] >= thr]
        n_s = len(sub)
        if n_s < 10:
            continue
        hits3 = int((sub["maxhit_t0"] >= 3).sum())
        p3 = hits3 / n_s
        lo3, hi3 = wilson_ci(hits3, n_s)
        cond_rows.append({
            "Condizione": f"consensus ≥ {thr}",
            "N": n_s,
            "P(≥3)": f"{p3*100:.1f}%",
            "IC 95%": f"[{lo3*100:.1f}%, {hi3*100:.1f}%]",
            "vs Base": f"{(p3 - base_rate_3)*100:+.1f}%",
        })
    if cond_rows:
        st.dataframe(pd.DataFrame(cond_rows), use_container_width=True, hide_index=True)

    # ─── 4. CONVERGENZA TRA LE 5 SESTINE ───────────────────────────────────────
    st.subheader("4. Convergenza interna delle 5 sestine  (Jaccard)")
    st.caption(
        "Jaccard medio fra coppie di sestine. Alto = sestine simili → modello deciso. "
        "Basso = coprono aree diverse → modello incerto."
    )

    def jaccard(a, b):
        u = len(a | b)
        return len(a & b) / u if u else 0

    jaccard_avg = []
    pairs = [(a, b) for a in range(5) for b in range(a + 1, 5)]
    for i in range(N):
        s_list = ses_all[i]
        if not pairs:
            jaccard_avg.append(0)
            continue
        avg = sum(jaccard(s_list[a], s_list[b]) for a, b in pairs) / len(pairs)
        jaccard_avg.append(avg)

    df_jac = pd.DataFrame({
        "draw": lc["draw"],
        "jaccard": jaccard_avg,
        "max_hit_t0": lc["ses_hit_t0"],
    }).dropna(subset=["max_hit_t0"])

    fig_jac = go.Figure()
    fig_jac.add_trace(go.Scatter(
        x=df_jac["draw"], y=df_jac["jaccard"], mode="lines",
        line=dict(color="#90caf9", width=1), name="Jaccard medio",
    ))
    fig_jac.add_trace(go.Scatter(
        x=df_jac["draw"], y=df_jac["jaccard"].rolling(30, min_periods=10).mean(),
        mode="lines", line=dict(color="#1565c0", width=2.5), name="rolling 30",
    ))
    fig_jac.update_layout(
        xaxis_title="Draw #", yaxis_title="Jaccard medio",
        height=320, margin=dict(l=40, r=20, t=20, b=40),
        legend=dict(orientation="h", y=1.05),
    )
    st.plotly_chart(fig_jac, use_container_width=True)

    cor_j = df_jac["jaccard"].corr(df_jac["max_hit_t0"])
    msg_j = ("Sicurezza interna NON correla con esito reale → non è un segnale predittivo."
             if abs(cor_j) < 0.10
             else "Esiste una correlazione misurabile fra sicurezza interna ed esito.")
    st.info(f"**Correlazione Jaccard ↔ Max Hit T0: {cor_j:+.3f}**  →  {msg_j}")

    # ─── 5. STABILITÀ DEL NUCLEO TEMPORALMENTE ─────────────────────────────────
    st.subheader("5. Stabilità del nucleo tra previsioni consecutive")
    st.caption("Quanto il nucleo (4-5 sestine) cambia da una previsione alla successiva.")

    nuclei = []
    for i in range(N):
        cnt = Counter()
        for ss in ses_all[i]:
            for nu in ss:
                cnt[nu] += 1
        nuclei.append(frozenset(n for n, c in cnt.items() if c >= 4))

    nucl_jac = []
    for i in range(1, N):
        u = len(nuclei[i] | nuclei[i - 1])
        nucl_jac.append(len(nuclei[i] & nuclei[i - 1]) / u if u else 0)

    fig_nuc = go.Figure()
    fig_nuc.add_trace(go.Scatter(
        x=lc["draw"][1:], y=nucl_jac, mode="lines",
        line=dict(color="#7e57c2", width=1),
        name="Jaccard nucleo n vs n-1",
    ))
    if len(nucl_jac) >= 30:
        roll_nuc = pd.Series(nucl_jac).rolling(30, min_periods=10).mean()
        fig_nuc.add_trace(go.Scatter(
            x=lc["draw"][1:], y=roll_nuc, mode="lines",
            line=dict(color="#311b92", width=2.5),
            name="rolling 30",
        ))
    fig_nuc.update_layout(
        xaxis_title="Draw #", yaxis_title="Jaccard",
        height=320, margin=dict(l=40, r=20, t=20, b=40),
        legend=dict(orientation="h", y=1.05),
    )
    st.plotly_chart(fig_nuc, use_container_width=True)

    avg_nuc = float(np.mean(nucl_jac)) if nucl_jac else 0
    st.info(
        f"**Stabilità media nucleo: {avg_nuc:.3f}**  "
        f"(0 = ogni previsione cambia tutto, 1 = mai cambia). "
        f"Il modello rigenera in media ~{(1 - avg_nuc) * 100:.0f}% del nucleo ad ogni draw."
    )

    # ─── 6. HEATMAP CALENDARIO ─────────────────────────────────────────────────
    st.subheader("6. Calendario  —  Quando esce ≥3?")
    st.caption("Distribuzione temporale degli eventi sestina ≥ 3 (T0).")

    try:
        lc_dates = pd.to_datetime(lc["date"])
        lc_with = pd.DataFrame({
            "date": lc_dates,
            "hit": lc["ses_hit_t0"].fillna(0),
        }).dropna(subset=["date"])
        lc_with["year"] = lc_with["date"].dt.year
        lc_with["week"] = lc_with["date"].dt.isocalendar().week
        lc_with["dow"] = lc_with["date"].dt.dayofweek

        years = sorted(lc_with["year"].unique())
        if years:
            sel_year = st.selectbox("Anno", years, index=len(years) - 1, key="cal_year")
            yr = lc_with[lc_with["year"] == sel_year]
            pivot = yr.pivot_table(index="dow", columns="week", values="hit",
                                   aggfunc="max", fill_value=0)
            fig_cal = go.Figure(go.Heatmap(
                z=pivot.values,
                x=[f"W{w}" for w in pivot.columns],
                y=["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"][:len(pivot)],
                colorscale=[[0, "#1e2a3a"], [0.3, "#90caf9"], [0.6, "#ffd54f"], [0.8, "#ff8a65"], [1, "#e53935"]],
                zmin=0, zmax=4,
                showscale=True,
                hovertemplate="%{x} %{y}<br>Max Hit: %{z}<extra></extra>",
            ))
            fig_cal.update_layout(height=260, margin=dict(l=40, r=20, t=20, b=40),
                                  title=f"Max Hit T0 — Anno {sel_year}")
            st.plotly_chart(fig_cal, use_container_width=True)
    except Exception as _e:
        st.caption(f"(Calendario non disponibile: {_e})")

    # ─── 7. AUTO-DISCOVERY  (osservazione sperimentale pura) ───────────────────
    st.subheader("7. Auto-discovery sperimentale  —  Quali condizioni hanno P(≥3) più alta?")
    st.caption(
        "Si testano K condizioni binarie e si misura P(Max Hit ≥ 3 | condizione). "
        "Mostro IC Wilson 95% grezzo, niente correzioni teoriche. "
        "Decidi tu cosa ti convince: quello che vedi è quello che ha fatto il dato."
    )

    base_rate = (lc["ses_hit_t0"].dropna() >= 3).mean()
    cond_tests = []

    rolling_mh = lc["ses_hit_t0"].rolling(10, min_periods=10).mean().shift(1)
    rolling_5 = lc["ses_hit_t0"].rolling(5, min_periods=5).mean().shift(1)

    gaps_since_3 = []
    last_idx = -999
    for i, v in enumerate(lc["ses_hit_t0"]):
        gaps_since_3.append(i - last_idx if last_idx >= 0 else 999)
        if pd.notna(v) and v >= 3:
            last_idx = i
    gaps_since_3 = np.array(gaps_since_3)

    def add_cond(label, mask):
        m = mask & lc["ses_hit_t0"].notna()
        n_ = int(m.sum())
        if n_ < 20:
            return
        hits = int((lc.loc[m, "ses_hit_t0"] >= 3).sum())
        p = hits / n_
        lo, hi = wilson_ci(hits, n_)
        cond_tests.append({
            "Condizione": label, "N": n_, "Hits": hits,
            "P": p, "Lo": lo, "Hi": hi, "Lift": p - base_rate,
        })

    cons_series = pd.Series(cons_intensity, index=lc.index)
    jac_series = pd.Series(jaccard_avg, index=lc.index)
    gap3_series = pd.Series(gaps_since_3, index=lc.index)

    add_cond("consensus_intensity ≥ 4", cons_series >= 4)
    add_cond("consensus_intensity ≥ 5", cons_series >= 5)
    add_cond("consensus_intensity ≤ 2", cons_series <= 2)
    add_cond("jaccard_5sest ≥ 0.40", jac_series >= 0.40)
    add_cond("jaccard_5sest ≤ 0.20", jac_series <= 0.20)
    add_cond("rolling_10 ≥ 1.5", rolling_mh >= 1.5)
    add_cond("rolling_10 ≤ 1.0", rolling_mh <= 1.0)
    add_cond("rolling_5  ≥ 2.0", rolling_5 >= 2.0)
    add_cond("gap_since_≥3 ≤ 2", gap3_series <= 2)
    add_cond("gap_since_≥3 ≥ 10", gap3_series >= 10)
    add_cond("pool_size ≥ 16", lc["pool_size"] >= 16)
    add_cond("pool_size ≤ 14", lc["pool_size"] <= 14)

    K = len(cond_tests)

    rows_disc = []
    n_above = 0
    n_clearly_above = 0
    for r in cond_tests:
        if r["Lift"] > 0:
            n_above += 1
        # "chiaramente sopra" = IC inferiore Wilson 95% > base_rate
        if r["Lo"] > base_rate:
            n_clearly_above += 1
            mark = "🔥"
        elif r["Hi"] < base_rate:
            mark = "🧊"  # chiaramente sotto
        elif r["Lift"] > 0:
            mark = "↑"
        elif r["Lift"] < 0:
            mark = "↓"
        else:
            mark = "—"
        rows_disc.append({
            "Condizione":   r["Condizione"],
            "N":            r["N"],
            "Hits ≥3":      r["Hits"],
            "P osservata":  f"{r['P']*100:.1f}%",
            "IC 95%":       f"[{r['Lo']*100:.1f}%, {r['Hi']*100:.1f}%]",
            "Lift vs base": f"{r['Lift']*100:+.1f}%",
            "Trend":        mark,
        })

    st.markdown(
        f"**Base rate P(≥3) = {base_rate*100:.1f}%**  ·  "
        f"Condizioni testate: **{K}**  ·  "
        f"Sopra il base rate: **{n_above}/{K}**  ·  "
        f"🔥 con IC che NON tocca la base: **{n_clearly_above}**"
    )
    df_disc = pd.DataFrame(rows_disc)
    if "Lift vs base" in df_disc.columns:
        df_disc = df_disc.assign(
            _lift_num=df_disc["Lift vs base"].str.replace("%", "").str.replace("+", "").astype(float)
        ).sort_values("_lift_num", ascending=False).drop(columns=["_lift_num"])
    st.dataframe(df_disc, use_container_width=True, hide_index=True)

    st.caption(
        "🔥 = condizione con IC 95% interamente sopra il base rate "
        "(probabilità osservata chiaramente più alta del normale) · "
        "↑ = sopra il base rate ma IC sovrapposto · "
        "↓ = sotto il base rate · "
        "🧊 = IC interamente sotto il base rate."
    )

    if n_clearly_above == 0:
        st.info(
            "ℹ️ Nessuna condizione ha IC interamente sopra il base rate — "
            "guarda comunque le 🔥 e le ↑: sono i punti più promettenti del dato. "
            "Decidi tu se vale la pena esplorarli."
        )
    else:
        st.success(
            f"🔥 **{n_clearly_above} condizioni** hanno IC 95% interamente sopra il base rate. "
            "Sono i candidati più solidi per essere regole reali."
        )

    # ─── 8. ATTESA MEDIA TRA EVENTI ────────────────────────────────────────────
    st.subheader("8. Quante estrazioni servono in media per arrivare a un evento?")
    st.caption("Tempo medio di attesa fra eventi consecutivi della stessa intensità.")

    waits_rows = []
    targets = [
        (3, "Sestina ≥ 3 (T0)", "t0_ses"),
        (4, "Sestina ≥ 4 (T0)", "t0_ses"),
        (3, "Sestina ≥ 3 (lifecycle)", "lc_ses"),
        (4, "Sestina ≥ 4 (lifecycle)", "lc_ses"),
        (5, "Pool ≥ 5 (lifecycle)", "lc_pool"),
    ]
    for k_thresh, label, kind in targets:
        if kind == "t0_ses":
            ev_draws = lc.loc[lc["ses_hit_t0"] >= k_thresh, "draw"].values
        elif kind == "lc_ses":
            ev_draws = lc_full.loc[lc_full["best_ses_hit"] >= k_thresh, "draw"].values
        else:
            ev_draws = lc_full.loc[lc_full["best_pool_hit"] >= k_thresh, "draw"].values
        if len(ev_draws) < 2:
            continue
        gaps = np.diff(ev_draws)
        p_emp = 1 / np.mean(gaps) if np.mean(gaps) else 0
        waits_rows.append({
            "Evento": label,
            "N eventi": len(ev_draws),
            "Gap medio": f"{np.mean(gaps):.1f}",
            "Gap mediano": f"{np.median(gaps):.0f}",
            "Gap min": int(np.min(gaps)),
            "Gap max": int(np.max(gaps)),
            "P empirica/draw": f"{p_emp*100:.2f}%",
            "Attesa media": f"~{np.mean(gaps):.0f} draw",
        })
    if waits_rows:
        st.dataframe(pd.DataFrame(waits_rows), use_container_width=True, hide_index=True)

    st.divider()
    st.caption(
        "📐 **Note metodologiche** · IC = Intervallo di Confidenza Wilson 95% (osservato) · "
        "Baseline random = ipergeometrica (49 numeri, 6 estratti, 5 sestine indipendenti) · "
        "Tutti i calcoli sono deterministici da `backtest_ml_storico.xlsx`. "
        "Niente correzioni teoriche: vedi il dato così com'è."
    )
