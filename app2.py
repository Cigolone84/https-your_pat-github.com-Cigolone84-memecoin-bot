"""
App 2 — Signal Correction Engine
Walk-forward simulation su 7000+ draw storiche.
Per ogni draw N usa solo dati fino a N-1, genera segnali, confronta con reale,
accumula gli errori e calibra automaticamente i pesi con regressione logistica.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
from itertools import combinations
import os, pickle, warnings
warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="App 2 — Signal Correction",
    page_icon="⚗️", layout="wide",
    initial_sidebar_state="collapsed",
)

# ── THEME ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  body,.stApp{background:#0a0e17;color:#e6edf3}
  .block-container{padding-top:1rem}
  .kpi{background:#161b22;border:1px solid #30363d;border-radius:10px;
       padding:1rem 1.5rem;text-align:center}
  .kv{font-size:1.8rem;font-weight:700;color:#f0a500}
  .kl{font-size:.8rem;color:#8b949e;margin-top:4px}
  .ball{display:inline-block;width:34px;height:34px;border-radius:50%;
        font-weight:700;font-size:.82rem;line-height:34px;text-align:center;margin:3px}
  .ripe{background:#e74c3c;color:#fff}
  .sofi1{background:#3498db;color:#fff}
  .sofi2{background:#e67e22;color:#fff}
  .ml{background:#9b59b6;color:#fff}
  .out{background:#2c3e50;color:#8b949e;border:1px solid #444}
  .hit{background:#2ecc71;color:#fff}
  hr{border-color:#30363d}
</style>""", unsafe_allow_html=True)

SIM_CACHE = "sim_cache.pkl"
FEAT_CACHE = "feat_cache.pkl"
WARMUP = 100

# ── DATA ─────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Caricamento dati…")
def load_draws():
    try:
        df = pd.read_csv("lotto_draws.csv")
    except FileNotFoundError:
        st.error("⚠️ lotto_draws.csv non trovato. Avvia prima App 1.")
        st.stop()
    df.columns = [c.lower().strip() for c in df.columns]
    num_cols = [c for c in df.columns if c.startswith("n") and c[1:].isdigit()]
    if len(num_cols) < 6:
        cands = [c for c in df.columns if df[c].dtype in [np.int64, np.float64]]
        num_cols = cands[-6:]
    df = df.rename(columns={num_cols[i]: f"n{i+1}" for i in range(6)})
    for c in [f"n{i}" for i in range(1,7)]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=[f"n{i}" for i in range(1,7)]).reset_index(drop=True)
    if "draw" not in df.columns: df["draw"] = range(1, len(df)+1)
    if "date" not in df.columns: df["date"] = ""
    return df

def get_nums(row):
    return sorted([int(row[f"n{i}"]) for i in range(1,7)])

def build_pool(prev6):
    ripe = set(prev6)
    s1, s24 = set(), set()
    for n in prev6:
        for d in (1,):
            if 1<=n-d<=49: s1.add(n-d)
            if 1<=n+d<=49: s1.add(n+d)
        for d in (2,3,4):
            if 1<=n-d<=49: s24.add(n-d)
            if 1<=n+d<=49: s24.add(n+d)
    s1  -= ripe
    s24 -= ripe | s1
    return ripe, s1, s24

# ── WALK-FORWARD SIMULATION ───────────────────────────────────────────────────
def run_simulation(df, start=WARMUP, progress_cb=None):
    """
    Walk-forward su tutte le draw dal draw `start` in poi.
    Per ogni draw i usa solo dati fino a i-1.
    Ritorna DataFrame con statistiche per-draw.
    """
    N = len(df)
    rows = []

    for i in range(start, N):
        if progress_cb and i % 200 == 0:
            progress_cb((i - start) / (N - start))

        prev = get_nums(df.iloc[i-1])
        curr = set(get_nums(df.iloc[i]))
        ripe, s1, s24 = build_pool(prev)
        pool = ripe | s1 | s24

        # frequency in last 50 draws (before i)
        freq = {}
        for j in range(max(0, i-50), i):
            for n in get_nums(df.iloc[j]):
                freq[n] = freq.get(n,0) + 1

        # day of month
        try:
            day = pd.to_datetime(df.iloc[i]["date"]).day
            day_near = sum(1 for n in curr if abs(n-day) <= 2)
        except Exception:
            day, day_near = 25, 0

        # hits per category
        rh  = len(ripe  & curr)
        s1h = len(s1    & curr)
        s24h= len(s24   & curr)
        ph  = len(pool  & curr)
        out = 6 - ph

        # positional delta (from N-2 if available)
        delta_hit = 0
        if i >= 2:
            prev2 = get_nums(df.iloc[i-2])
            for k in range(6):
                mean_d = prev[k] - prev2[k]
                pred_n = max(1, min(49, int(round(prev[k] + mean_d))))
                if pred_n in curr:
                    delta_hit += 1

        rows.append({
            "idx":       i,
            "draw":      int(df.iloc[i]["draw"]),
            "ripe_hit":  rh,  "sofi1_hit": s1h,  "sofi24_hit": s24h,
            "pool_hit":  ph,  "outside":   out,
            "day_near":  day_near,
            "delta_hit": delta_hit,
            "ripe_sz":   len(ripe),  "sofi1_sz": len(s1),  "sofi24_sz": len(s24),
            "pool_sz":   len(pool),
        })

    if progress_cb:
        progress_cb(1.0)
    return pd.DataFrame(rows)


# ── FEATURE MATRIX (per logistic regression) ─────────────────────────────────
def build_features(df, start=WARMUP, max_draws=5000, progress_cb=None):
    """
    Per ogni draw i e ogni numero n in 1-49: calcola feature vector + label.
    X shape: (draws × 49, n_features)
    y shape: (draws × 49,)  —  1 se n appare nel draw reale
    """
    N = min(len(df), start + max_draws)
    X_rows, y_rows, meta = [], [], []

    for i in range(start, N):
        if progress_cb and i % 300 == 0:
            progress_cb((i - start) / (N - start))

        prev = get_nums(df.iloc[i-1])
        curr = set(get_nums(df.iloc[i]))
        ripe, s1, s24 = build_pool(prev)

        freq = {}
        for j in range(max(0, i-50), i):
            for n in get_nums(df.iloc[j]):
                freq[n] = freq.get(n,0) + 1

        try:
            day = pd.to_datetime(df.iloc[i]["date"]).day
        except Exception:
            day = 25

        # positional delta signal
        if i >= 2:
            prev2 = get_nums(df.iloc[i-2])
            deltas = [prev[k]-prev2[k] for k in range(6)]
            preds  = [max(1,min(49,prev[k]+deltas[k])) for k in range(6)]
        else:
            preds = prev[:]

        for n in range(1, 50):
            # 7 features
            f_ripe  = 1.0 if n in ripe  else 0.0
            f_sofi1 = 1.0 if n in s1    else 0.0
            f_sofi24= 1.0 if n in s24   else 0.0
            f_day   = max(0.0, 3.0 - abs(n-day)) / 3.0
            f_freq  = freq.get(n,0) / 6.0
            f_delta = max(0.0, 1.0 - min(abs(n-p) for p in preds) / 5.0)
            f_outside= 0.0 if (n in ripe or n in s1 or n in s24) else 1.0

            X_rows.append([f_ripe, f_sofi1, f_sofi24, f_day, f_freq, f_delta, f_outside])
            y_rows.append(1 if n in curr else 0)
            meta.append({"draw_idx": i, "num": n})

    if progress_cb:
        progress_cb(1.0)

    return (np.array(X_rows, dtype=np.float32),
            np.array(y_rows,  dtype=np.int8),
            pd.DataFrame(meta))

FEATURE_NAMES = ["Ripetuto", "Soffio±1", "Coperto±2-4", "Giorno", "Freq50", "DeltaPos", "FuoriPool"]


# ── LOGISTIC REGRESSION ───────────────────────────────────────────────────────
def train_corrector(X, y):
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    clf = LogisticRegression(C=1.0, max_iter=500, class_weight="balanced")
    clf.fit(Xs, y)
    return clf, scaler

def predict_proba_all(clf, scaler, df):
    """Generate probability for each number in 1-49 for the next draw."""
    prev = get_nums(df.iloc[-1])
    ripe, s1, s24 = build_pool(prev)

    freq = {}
    for j in range(max(0, len(df)-50), len(df)):
        for n in get_nums(df.iloc[j]):
            freq[n] = freq.get(n,0) + 1

    try:
        day = pd.to_datetime(df.iloc[-1]["date"]).day
    except Exception:
        day = 25

    if len(df) >= 2:
        prev2 = get_nums(df.iloc[-2])
        deltas = [prev[k]-prev2[k] for k in range(6)]
        preds  = [max(1,min(49,prev[k]+deltas[k])) for k in range(6)]
    else:
        preds = prev[:]

    feats = []
    for n in range(1, 50):
        feats.append([
            1.0 if n in ripe  else 0.0,
            1.0 if n in s1    else 0.0,
            1.0 if n in s24   else 0.0,
            max(0.0, 3.0 - abs(n-day)) / 3.0,
            freq.get(n,0) / 6.0,
            max(0.0, 1.0 - min(abs(n-p) for p in preds) / 5.0),
            0.0 if (n in ripe or n in s1 or n in s24) else 1.0,
        ])

    Xs = scaler.transform(np.array(feats, dtype=np.float32))
    probs = clf.predict_proba(Xs)[:,1]
    return {n+1: float(probs[n]) for n in range(49)}, ripe, s1, s24


# ── LAWS ─────────────────────────────────────────────────────────────────────
def laws_pass(nums):
    n = sorted(nums)
    pari = sum(1 for x in n if x%2==0)
    gaps = [n[i+1]-n[i] for i in range(5)]
    return sum([
        len(set(x//10 for x in n)) >= 3,
        1 <= pari <= 5,
        n[5]-n[0] > 20,
        n[0] <= 10 or n[1] <= 15,
        4 <= sum(gaps)/5 <= 11,
        n[0] <= 15,
        n[5] >= 35,
        any(g <= 3 for g in gaps),
        2 <= pari <= 4,
        18 <= sum(n)/6 <= 32,
        70 <= sum(n) <= 160,
    ])

def best_sestina_from_probs(probs_dict):
    ranked = sorted(probs_dict.items(), key=lambda x:-x[1])
    pool20 = [n for n,_ in ranked[:20]]

    best, best_sc = None, -1
    for combo in combinations(pool20, 6):
        nums = list(combo)
        if laws_pass(nums) < 9: continue
        sc = sum(probs_dict[n] for n in nums)
        if sc > best_sc:
            best_sc, best = sc, sorted(nums)

    if best is None:
        best = sorted([n for n,_ in ranked[:6]])
    return best, ranked[:20]


# ── BALL HTML ────────────────────────────────────────────────────────────────
def ball(n, cls="out"):
    return f'<span class="ball {cls}">{n:02d}</span>'


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    df = load_draws()
    last = df.iloc[-1]
    last_nums = get_nums(last)
    nx = int(last["draw"]) + 1

    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:1rem;margin-bottom:1rem">
      <span style="font-size:2.5rem">⚗️</span>
      <div>
        <div style="font-size:1.8rem;font-weight:800">App 2 — Signal Correction Engine</div>
        <div style="font-size:.85rem;color:#8b949e">
          {len(df):,} draw · Ultima: #{int(last['draw'])} del {str(last['date'])[:10]} ·
          {'  '.join(f'<b>{n:02d}</b>' for n in last_nums)} · Prossima: <b>#{nx}</b>
        </div>
      </div>
    </div>
    <hr>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs([
        "🚀 Simulazione", "📈 Calibrazione", "⚗️ Segnale Corretto", "🔍 Debug per Draw"
    ])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — SIMULAZIONE
    # ══════════════════════════════════════════════════════════════════════════
    with tab1:
        st.subheader("🚀 Walk-Forward Simulation su 7000+ Draw")
        st.caption(
            "Per ogni draw N usa SOLO dati fino a N-1. "
            "Misura quanti numeri di ogni categoria si sono realmente avverati."
        )

        col_run, col_status = st.columns([2,3])
        with col_run:
            force = st.checkbox("Forza ricalcolo (ignora cache)")
            run_btn = st.button("▶ Avvia simulazione", use_container_width=True, type="primary")

        sim = None
        if os.path.exists(SIM_CACHE) and not force:
            with open(SIM_CACHE,"rb") as f:
                sim = pickle.load(f)
            col_status.success(f"✅ Cache caricata: {len(sim):,} draw simulate.")

        if run_btn:
            prog = st.progress(0.0, text="Simulazione in corso…")
            sim = run_simulation(df, start=WARMUP,
                                 progress_cb=lambda v: prog.progress(v, text=f"{v*100:.0f}%"))
            prog.empty()
            with open(SIM_CACHE,"wb") as f:
                pickle.dump(sim, f)
            st.success(f"✅ Simulazione completata: {len(sim):,} draw analizzate!")

        if sim is None:
            st.info("Premi **▶ Avvia simulazione** per generare i dati.")
            return

        # KPIs
        k1,k2,k3,k4,k5 = st.columns(5)
        for col,(lab,val,ico) in zip([k1,k2,k3,k4,k5],[
            ("Hit medi ripetuti",    sim["ripe_hit"].mean(),   "🔴"),
            ("Hit medi soffi ±1",    sim["sofi1_hit"].mean(),  "🔵"),
            ("Hit medi coperti ±2-4",sim["sofi24_hit"].mean(),"🟠"),
            ("Hit medi pool tot.",   sim["pool_hit"].mean(),   "🟢"),
            ("Hit medi fuori pool",  sim["outside"].mean(),    "⚫"),
        ]):
            col.markdown(f'<div class="kpi"><div class="kv">{ico} {val:.3f}</div>'
                         f'<div class="kl">{lab}</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Rolling 100-draw hit rates
        roll = sim[["ripe_hit","sofi1_hit","sofi24_hit","pool_hit","outside"]].rolling(100).mean()
        fig_roll = go.Figure()
        for col, name, color in [
            ("ripe_hit",   "Ripetuti",   "#e74c3c"),
            ("sofi1_hit",  "Soffi ±1",   "#3498db"),
            ("sofi24_hit", "Coperti ±4", "#e67e22"),
            ("pool_hit",   "Pool tot.",  "#2ecc71"),
        ]:
            fig_roll.add_trace(go.Scatter(
                x=sim["draw"], y=roll[col], name=name,
                line=dict(color=color, width=2), mode="lines",
            ))
        fig_roll.update_layout(
            title="Hit rate per categoria — media mobile 100 draw",
            xaxis_title="Draw #", yaxis_title="Hit medi su 6",
            plot_bgcolor="#0a0e17", paper_bgcolor="#0a0e17",
            font=dict(color="#e6edf3"), legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig_roll, use_container_width=True)

        # Distribuzione hit per categoria
        col_a, col_b = st.columns(2)
        for ax, field, title, color in [
            (col_a, "ripe_hit",  "Distribuzione hit Ripetuti",  "#e74c3c"),
            (col_b, "sofi1_hit", "Distribuzione hit Soffi ±1",  "#3498db"),
        ]:
            vc = sim[field].value_counts().sort_index()
            fig = go.Figure(go.Bar(
                x=[str(i) for i in vc.index],
                y=vc.values/len(sim)*100,
                marker_color=color,
                text=[f"{v:.0f}%" for v in vc.values/len(sim)*100],
                textposition="outside",
            ))
            fig.update_layout(
                title=title, xaxis_title="N° hit", yaxis_title="%",
                plot_bgcolor="#0a0e17", paper_bgcolor="#0a0e17",
                font=dict(color="#e6edf3"), showlegend=False,
            )
            ax.plotly_chart(fig, use_container_width=True)

        # Summary table
        st.markdown("### 📊 Statistiche empiriche complete")
        stats_rows = []
        for field, label in [
            ("ripe_hit","🔴 Ripetuti"), ("sofi1_hit","🔵 Soffi ±1"),
            ("sofi24_hit","🟠 Coperti ±2-4"), ("pool_hit","🟢 Pool tot."),
            ("day_near","📅 Vicini al giorno"), ("delta_hit","📐 Predetti da delta"),
        ]:
            col = sim[field]
            stats_rows.append({
                "Segnale": label,
                "Media": f"{col.mean():.3f}",
                "P(=0)": f"{(col==0).mean()*100:.0f}%",
                "P(≥1)": f"{(col>=1).mean()*100:.0f}%",
                "P(≥2)": f"{(col>=2).mean()*100:.0f}%",
                "P(≥3)": f"{(col>=3).mean()*100:.0f}%",
                "Max": int(col.max()),
            })
        st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)

        st.session_state["sim"] = sim

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — CALIBRAZIONE
    # ══════════════════════════════════════════════════════════════════════════
    with tab2:
        st.subheader("📈 Calibrazione Automatica dei Segnali")
        st.caption(
            "Regressione logistica su 5000 draw: impara P(numero esce | segnali). "
            "I coefficienti diventano i nuovi pesi del sistema."
        )

        run_calib = st.button("🔬 Calibra segnali (5000 draw)", use_container_width=True)
        clf, scaler = None, None

        if os.path.exists(FEAT_CACHE) and not run_calib:
            with open(FEAT_CACHE,"rb") as f:
                clf, scaler = pickle.load(f)
            st.success("✅ Calibrazione caricata dalla cache.")

        if run_calib:
            prog2 = st.progress(0.0, text="Costruzione feature matrix…")
            X, y, meta = build_features(df, start=WARMUP, max_draws=5000,
                                         progress_cb=lambda v: prog2.progress(v, text=f"Feature: {v*100:.0f}%"))
            prog2.progress(0.9, "Addestramento logistic regression…")
            clf, scaler = train_corrector(X, y)
            prog2.progress(1.0); prog2.empty()

            with open(FEAT_CACHE,"wb") as f:
                pickle.dump((clf, scaler), f)

            # AUC
            Xs = scaler.transform(X)
            auc = roc_auc_score(y, clf.predict_proba(Xs)[:,1])
            st.success(f"✅ Calibrazione completata. AUC = **{auc:.4f}**")

        if clf is None:
            st.info("Premi il pulsante per calibrare (serve la simulazione).")
        else:
            # Coefficienti apprensi
            coefs = clf.coef_[0]
            feat_df = pd.DataFrame({
                "Segnale": FEATURE_NAMES,
                "Coefficiente": [round(c,4) for c in coefs],
                "Peso relativo": [round(abs(c)/sum(abs(coefs))*100,1) for c in coefs],
                "Direzione": ["🔼 Favorisce" if c>0 else "🔽 Penalizza" for c in coefs],
            }).sort_values("Coefficiente", ascending=False)

            st.markdown("### Coefficienti appresi (logistic regression)")
            st.dataframe(feat_df, use_container_width=True, hide_index=True)

            # Bar chart coefficienti
            fig_coef = go.Figure(go.Bar(
                x=feat_df["Segnale"], y=feat_df["Coefficiente"],
                marker_color=["#2ecc71" if v>0 else "#e74c3c" for v in feat_df["Coefficiente"]],
                text=[f"{v:+.3f}" for v in feat_df["Coefficiente"]],
                textposition="outside",
            ))
            fig_coef.add_hline(y=0, line_dash="dash", line_color="#f0a500")
            fig_coef.update_layout(
                title="Pesi appresi: quanto ogni segnale predice P(numero esce)",
                yaxis_title="Coefficiente", plot_bgcolor="#0a0e17",
                paper_bgcolor="#0a0e17", font=dict(color="#e6edf3"), showlegend=False,
            )
            st.plotly_chart(fig_coef, use_container_width=True)

            # Confronto pesi PRIMA (hardcoded) vs DOPO (appresi)
            st.markdown("### Confronto: pesi originali App 1 vs pesi calibrati")
            orig_weights = {
                "Ripetuto": 1.5, "Soffio±1": 2.5, "Coperto±2-4": 2.0,
                "Giorno": 1.0, "Freq50": 0.3, "DeltaPos": 2.0, "FuoriPool": 0.0,
            }
            comp_rows = []
            for i, feat in enumerate(FEATURE_NAMES):
                orig = orig_weights.get(feat, 0.0)
                learn = coefs[i]
                comp_rows.append({
                    "Segnale": feat,
                    "Peso originale App1": orig,
                    "Coeff. calibrato": round(learn,4),
                    "Cambiamento": "🔼 aumenta" if learn>orig else "🔽 riduce" if learn<orig else "≈ simile",
                })
            st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

            st.session_state["clf"] = clf
            st.session_state["scaler"] = scaler

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3 — SEGNALE CORRETTO
    # ══════════════════════════════════════════════════════════════════════════
    with tab3:
        st.subheader(f"⚗️ Sestina Corretta per Draw #{nx}")
        st.caption("Generata dal modello calibrato su 7000+ draw. Aggiornamento automatico ad ogni nuova estrazione.")

        clf  = st.session_state.get("clf")
        scaler = st.session_state.get("scaler")

        if clf is None:
            if os.path.exists(FEAT_CACHE):
                with open(FEAT_CACHE,"rb") as f:
                    clf, scaler = pickle.load(f)
                st.session_state["clf"] = clf
                st.session_state["scaler"] = scaler
            else:
                st.warning("Prima calibra il modello nel tab **📈 Calibrazione**.")
                return

        probs, ripe, s1, s24 = predict_proba_all(clf, scaler, df)
        sestina, top20 = best_sestina_from_probs(probs)

        # Show sestina
        st.markdown(f"### 🏆 Sestina calibrata #{nx}")
        balls_html = ""
        for n in sestina:
            if n in ripe:  cls = "ripe"
            elif n in s1:  cls = "sofi1"
            elif n in s24: cls = "sofi2"
            else:          cls = "ml"
            balls_html += ball(n, cls)
        st.markdown(balls_html, unsafe_allow_html=True)

        lp = laws_pass(sestina)
        sc = sum(probs[n] for n in sestina)
        st.markdown(f"Leggi: **{lp}/11** &nbsp;|&nbsp; Score prob: **{sc:.4f}** &nbsp;|&nbsp; "
                    f"Somma: {sum(sestina)} · Range: {max(sestina)-min(sestina)}")

        # Top 20 con probabilità
        st.markdown("### 📊 Top 20 candidati per probabilità")
        prob_df = pd.DataFrame([
            {"N°": n, "P(esce)": f"{p*100:.2f}%",
             "Categoria": "Ripetuto" if n in ripe else
                          "Soffio±1" if n in s1   else
                          "Coperto±2-4" if n in s24 else "Fuori pool",
             "In sestina": "✅" if n in sestina else ""}
            for n,p in top20
        ])
        st.dataframe(prob_df, use_container_width=True, hide_index=True)

        # Heatmap 1-49 probability
        prob_arr = np.array([probs[n] for n in range(1,50)]).reshape(7,7)
        fig_heat = go.Figure(go.Heatmap(
            z=prob_arr,
            x=[str(c*7+1)+"-"+str((c+1)*7) for c in range(7)],
            y=[str(r) for r in range(7)],
            text=[[f"{n:02d}\n{probs[n]*100:.1f}%" for n in range(r*7+1, min(50, (r+1)*7+1))]
                  for r in range(7)],
            texttemplate="%{text}",
            colorscale="RdYlGn", showscale=True,
            hovertemplate="Num %{text}: %{z:.4f}<extra></extra>",
        ))
        fig_heat.update_layout(
            title=f"Probabilità P(esce) per ciascun numero 1-49 — draw #{nx}",
            plot_bgcolor="#0a0e17", paper_bgcolor="#0a0e17",
            font=dict(color="#e6edf3"),
        )
        st.plotly_chart(fig_heat, use_container_width=True)

        # Barchart probability
        fig_bar = go.Figure(go.Bar(
            x=list(range(1,50)),
            y=[probs[n]*100 for n in range(1,50)],
            marker_color=["#2ecc71" if n in sestina else
                          "#e74c3c" if n in ripe else
                          "#3498db" if n in s1  else
                          "#e67e22" if n in s24 else "#2c3e50"
                          for n in range(1,50)],
            hovertemplate="N° %{x}: %{y:.2f}%<extra></extra>",
        ))
        fig_bar.update_layout(
            title="Probabilità per numero (verde = in sestina)",
            xaxis_title="Numero", yaxis_title="P(esce) %",
            plot_bgcolor="#0a0e17", paper_bgcolor="#0a0e17",
            font=dict(color="#e6edf3"),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4 — DEBUG PER DRAW
    # ══════════════════════════════════════════════════════════════════════════
    with tab4:
        st.subheader("🔍 Analisi draw specifica")
        sim_loaded = st.session_state.get("sim")
        if sim_loaded is None and os.path.exists(SIM_CACHE):
            with open(SIM_CACHE,"rb") as f:
                sim_loaded = pickle.load(f)

        if sim_loaded is None:
            st.info("Avvia prima la simulazione.")
            return

        draw_min = int(sim_loaded["draw"].min())
        draw_max = int(sim_loaded["draw"].max())
        sel = st.slider("Seleziona draw #", draw_min, draw_max, draw_max)

        row_sel = sim_loaded[sim_loaded["draw"] == sel]
        if row_sel.empty:
            st.warning("Draw non trovata nella simulazione.")
            return

        row = row_sel.iloc[0]
        idx = int(row["idx"])

        prev_nums = get_nums(df.iloc[idx-1])
        curr_nums = get_nums(df.iloc[idx])

        col_p, col_c = st.columns(2)
        with col_p:
            st.markdown(f"**Draw #{sel-1}** (base)")
            st.markdown("".join(ball(n,"sofi1") for n in prev_nums), unsafe_allow_html=True)
        with col_c:
            st.markdown(f"**Draw #{sel}** (reale)")
            ripe_s, s1_s, s24_s = build_pool(prev_nums)
            hits_html = ""
            for n in curr_nums:
                cls = "ripe" if n in ripe_s else "sofi1" if n in s1_s else \
                      "sofi2" if n in s24_s else "out"
                hits_html += ball(n, cls)
            st.markdown(hits_html, unsafe_allow_html=True)

        st.markdown("---")
        m1,m2,m3,m4,m5 = st.columns(5)
        for col,(lab,val) in zip([m1,m2,m3,m4,m5],[
            ("Ripetuti hit", int(row["ripe_hit"])),
            ("Soffi±1 hit", int(row["sofi1_hit"])),
            ("Coperti hit", int(row["sofi24_hit"])),
            ("Pool tot hit", int(row["pool_hit"])),
            ("Fuori pool", int(row["outside"])),
        ]):
            col.markdown(f'<div class="kpi"><div class="kv">{val}</div>'
                         f'<div class="kl">{lab}</div></div>', unsafe_allow_html=True)

        # show which actual numbers fell in which category
        st.markdown("#### Categoria di ciascun numero uscito")
        cat_rows = []
        for n in curr_nums:
            rp,s1_,s24_ = build_pool(prev_nums)
            d_min = min(abs(n-b) for b in prev_nums)
            cat_rows.append({
                "Numero": n,
                "Categoria": "🔴 Ripetuto" if n in rp else
                             "🔵 Soffio±1" if n in s1_ else
                             f"🟠 Coperto±{d_min}" if n in s24_ else
                             f"⚫ Fuori pool (dist {d_min})",
                "Dist. min da N-1": d_min,
            })
        st.dataframe(pd.DataFrame(cat_rows), use_container_width=True, hide_index=True)


main()
