"""
App 2 — Meta-Learner Signal Correction Engine
5 strati: precision storica → errori per decina → pattern posizionali
          → regressione logistica → sestina finale dal pool di App 1.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from itertools import combinations
import warnings
warnings.filterwarnings("ignore")

st.set_page_config(
    page_title="Meta-Learner — Signal Correction",
    page_icon="🧬", layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""<style>
  body,.stApp{background:#0a0e17;color:#e6edf3}
  .block-container{padding-top:1rem}
  .kpi{background:#161b22;border:1px solid #30363d;border-radius:10px;
       padding:1rem 1.5rem;text-align:center;margin-bottom:.5rem}
  .kv{font-size:1.8rem;font-weight:700;color:#f0a500}
  .kl{font-size:.8rem;color:#8b949e;margin-top:4px}
  .ball{display:inline-block;width:34px;height:34px;border-radius:50%;
        font-weight:700;font-size:.82rem;line-height:34px;text-align:center;margin:3px}
  .ripe{background:#e74c3c;color:#fff}
  .sofi1{background:#3498db;color:#fff}
  .sofi2{background:#e67e22;color:#fff}
  .hit{background:#2ecc71;color:#000}
  .out{background:#2c3e50;color:#8b949e;border:1px solid #444}
  hr{border-color:#30363d}
  div[data-testid="stTabs"] button{color:#8b949e!important}
  div[data-testid="stTabs"] button[aria-selected="true"]{color:#f0a500!important;
    border-bottom:2px solid #f0a500!important}
</style>""", unsafe_allow_html=True)

# ── CONSTANTS ─────────────────────────────────────────────────────────────────
WARMUP        = 100
PREC_WINDOW   = 300
DECADE_WINDOW = 100
POS_WINDOW    = 100
# Sum range wider than L13 (70-160) because real draws often exceed 160
SUM_MIN, SUM_MAX = 75, 215
RANGE_MIN     = 25
MIN_DECADES   = 3
FEATURE_NAMES = ["Ripetuto", "Soffio±1", "Coperto±2-4",
                 "Decade Bias", "Freq50", "Ritardo", "Pos Boost"]

# ── DATA ─────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Caricamento dati…")
def load_draws():
    try:
        df = pd.read_csv("lotto_draws.csv")
    except FileNotFoundError:
        st.error("⚠️ lotto_draws.csv non trovato.")
        st.stop()
    df.columns = [c.lower().strip() for c in df.columns]
    num_cols = [c for c in df.columns if c.startswith("n") and c[1:].isdigit()]
    if not num_cols:
        num_cols = [c for c in df.columns if "num" in c or "ball" in c]
    if len(num_cols) < 6:
        candidates = [c for c in df.columns
                      if df[c].dtype in [np.int64, np.float64]]
        num_cols = candidates[-6:]
    df = df.rename(columns={num_cols[i]: f"n{i+1}" for i in range(6)})
    for c in [f"n{i}" for i in range(1, 7)]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=[f"n{i}" for i in range(1, 7)]).reset_index(drop=True)
    if "draw" not in df.columns:
        df["draw"] = range(1, len(df) + 1)
    if "date" not in df.columns:
        df["date"] = ""
    return df


def get_nums(row):
    return sorted([int(row[f"n{i}"]) for i in range(1, 7)])


def build_pool_at(df, prev_idx):
    """Pool for draw prev_idx+1 using only draw at prev_idx."""
    last = get_nums(df.iloc[prev_idx])
    ripetuti = set(last)
    soffi_1, soffi_24 = set(), set()
    for n in last:
        for sign in (-1, 1):
            v = n + sign
            if 1 <= v <= 49:
                soffi_1.add(v)
        for d in (2, 3, 4):
            for sign in (-1, 1):
                v = n + sign * d
                if 1 <= v <= 49:
                    soffi_24.add(v)
    soffi_1  -= ripetuti
    soffi_24 -= (ripetuti | soffi_1)
    return {
        "ripetuti": ripetuti,
        "soffi_1":  soffi_1,
        "soffi_24": soffi_24,
        "pool_all": ripetuti | soffi_1 | soffi_24,
    }


# ── STRATO 1: PRECISION STORICA ───────────────────────────────────────────────
@st.cache_data(show_spinner="Strato 1 — precision storica…")
def compute_precision(df_hash, _df):
    df    = _df
    total = len(df)
    start = max(WARMUP, total - PREC_WINDOW)

    records = []
    for i in range(start, total):
        actual = set(get_nums(df.iloc[i]))
        pool   = build_pool_at(df, i - 1)
        for cat, members in [("Ripetuto",     pool["ripetuti"]),
                              ("Soffio±1",    pool["soffi_1"]),
                              ("Coperto±2-4", pool["soffi_24"])]:
            for n in members:
                records.append({
                    "draw_idx": i,
                    "draw":     int(df.iloc[i]["draw"]),
                    "category": cat,
                    "hit":      int(n in actual),
                })
    rec_df = pd.DataFrame(records)

    prec_tables = {}
    for ws in [50, 100, 200, 300]:
        wstart = max(start, total - ws)
        sub    = rec_df[rec_df["draw_idx"] >= wstart]
        pt     = sub.groupby("category").agg(
            appearances=("hit", "count"),
            hits=("hit", "sum"),
        )
        pt["precision"]    = pt["hits"] / pt["appearances"]
        pt["hit_per_draw"] = pt["hits"] / ws
        prec_tables[ws]    = pt

    # Cumulative rolling precision for chart
    rolling_data = {}
    for cat in ["Ripetuto", "Soffio±1", "Coperto±2-4"]:
        sub = rec_df[rec_df["category"] == cat].sort_values("draw_idx")
        grp = sub.groupby("draw_idx").agg(
            hits=("hit", "sum"), appearances=("hit", "count")
        ).reset_index()
        cum_h = grp["hits"].cumsum()
        cum_a = grp["appearances"].cumsum()
        rolling_data[cat] = {
            "draw":         [int(df.iloc[idx]["draw"]) for idx in grp["draw_idx"]],
            "rolling_prec": (cum_h / cum_a).tolist(),
        }

    # Dynamic weights from 100-draw window, normalized to sum=3
    w100 = prec_tables.get(100, prec_tables[min(prec_tables)])
    cats = ["Ripetuto", "Soffio±1", "Coperto±2-4"]
    raw  = {c: float(w100.loc[c, "precision"]) if c in w100.index else 0.1
            for c in cats}
    total_w     = sum(raw.values()) or 1.0
    dyn_weights = {c: v / total_w * 3.0 for c, v in raw.items()}

    return prec_tables, rolling_data, dyn_weights


# ── STRATO 2: ERRORI PER DECINA ───────────────────────────────────────────────
DECADES = [
    ("D1 (1-10)",  set(range(1,  11))),
    ("D2 (11-20)", set(range(11, 21))),
    ("D3 (21-30)", set(range(21, 31))),
    ("D4 (31-40)", set(range(31, 41))),
    ("D5 (41-49)", set(range(41, 50))),
]


@st.cache_data(show_spinner="Strato 2 — errori per decina…")
def compute_decade_bias(df_hash, _df):
    df      = _df
    total   = len(df)
    start   = max(WARMUP, total - DECADE_WINDOW)
    n_draws = total - start

    fp = {d[0]: 0 for d in DECADES}
    fn = {d[0]: 0 for d in DECADES}

    for i in range(start, total):
        actual   = set(get_nums(df.iloc[i]))
        pool_set = build_pool_at(df, i - 1)["pool_all"]
        for dname, dset in DECADES:
            fp[dname] += len((pool_set & dset) - actual)
            fn[dname] += len((actual & dset) - pool_set)

    # bias > 0 → overestimated → penalize; bias < 0 → underestimated → promote
    bias = {d[0]: (fp[d[0]] - fn[d[0]]) / n_draws for d in DECADES}

    num_bias = {}
    for n in range(1, 50):
        for dname, dset in DECADES:
            if n in dset:
                num_bias[n] = bias[dname]
                break

    return bias, fn, fp, num_bias, n_draws


# ── STRATO 3: PATTERN POSIZIONALI ─────────────────────────────────────────────
@st.cache_data(show_spinner="Strato 3 — pattern posizionali…")
def compute_positional_analysis(df_hash, _df):
    df    = _df
    total = len(df)
    start = max(WARMUP, total - POS_WINDOW)

    pos_errors = [[] for _ in range(6)]
    for i in range(start, total):
        actual      = sorted(get_nums(df.iloc[i]))
        pool_sorted = sorted(build_pool_at(df, i - 1)["pool_all"])
        if not pool_sorted:
            continue
        for k in range(6):
            ak      = actual[k]
            closest = min(pool_sorted, key=lambda x: abs(x - ak))
            pos_errors[k].append(ak - closest)

    pos_means = [np.mean(e) if e else 0.0 for e in pos_errors]
    pos_stds  = [np.std(e)  if e else 5.0 for e in pos_errors]

    pos_boost = {}
    for n in range(1, 50):
        boost = 0.0
        for k in range(6):
            lo = max(1,  1 + k * 7 - 4)
            hi = min(49, 1 + k * 7 + 12)
            if lo <= n <= hi:
                boost += 0.4
            mu    = pos_means[k]
            sigma = pos_stds[k] if pos_stds[k] > 0 else 5.0
            if abs(mu) > 1.5:
                correction = n - mu
                if 1 <= correction <= 49 and abs(n - correction) <= sigma:
                    boost += 0.3
        pos_boost[n] = boost

    return pos_means, pos_stds, pos_errors, pos_boost


# ── STRATO 4: META-LEARNER ────────────────────────────────────────────────────
def _make_feature_row(n, pool, freq, ritardo, num_bias, pos_boost):
    return [
        1.0 if n in pool["ripetuti"] else 0.0,
        1.0 if n in pool["soffi_1"]  else 0.0,
        1.0 if n in pool["soffi_24"] else 0.0,
        -float(num_bias.get(n, 0.0)),        # negate: underestimated → positive
        freq.get(n, 0) / 50.0,
        min(ritardo.get(n, 200), 200) / 200.0,
        min(pos_boost.get(n, 0.0), 3.0) / 3.0,
    ]


def _pool_and_features(df, idx, num_bias, pos_boost):
    pool = build_pool_at(df, idx - 1)

    freq = {}
    for j in range(max(0, idx - 50), idx):
        for n in get_nums(df.iloc[j]):
            freq[n] = freq.get(n, 0) + 1

    ritardo = {}
    for n in range(1, 50):
        found = False
        for j in range(idx - 1, max(-1, idx - 201), -1):
            if n in set(get_nums(df.iloc[j])):
                ritardo[n] = idx - j - 1
                found = True
                break
        if not found:
            ritardo[n] = 200

    X = np.array(
        [_make_feature_row(n, pool, freq, ritardo, num_bias, pos_boost)
         for n in range(1, 50)],
        dtype=np.float32,
    )
    return X, pool


@st.cache_data(show_spinner="Strato 4 — training Meta-Learner…")
def train_meta_learner(df_hash, _df, num_bias, pos_boost):
    df    = _df
    total = len(df)
    start = max(WARMUP, total - PREC_WINDOW)

    X_parts, y_parts = [], []
    for i in range(start, total):
        actual     = set(get_nums(df.iloc[i]))
        X_i, _     = _pool_and_features(df, i, num_bias, pos_boost)
        y_i        = np.array([1 if n in actual else 0 for n in range(1, 50)],
                               dtype=np.int8)
        X_parts.append(X_i)
        y_parts.append(y_i)

    X_mat = np.vstack(X_parts)
    y_vec = np.concatenate(y_parts)

    scaler = StandardScaler()
    X_sc   = scaler.fit_transform(X_mat)
    clf    = LogisticRegression(C=0.5, class_weight="balanced",
                                max_iter=1000, random_state=42)
    clf.fit(X_sc, y_vec)
    return clf, scaler


def predict_proba_for(df, idx, clf, scaler, num_bias, pos_boost):
    """P(esce) per ogni numero 1-49 per draw df.iloc[idx], dati < idx."""
    X, pool = _pool_and_features(df, idx, num_bias, pos_boost)
    probs   = clf.predict_proba(scaler.transform(X))[:, 1]
    return {n: float(probs[n - 1]) for n in range(1, 50)}, pool


def predict_next_draw(df, clf, scaler, num_bias, pos_boost):
    """P(esce) per la draw successiva (non ancora nel CSV)."""
    prev    = len(df) - 1
    pool    = build_pool_at(df, prev)

    freq = {}
    for j in range(max(0, prev - 49), prev + 1):
        for n in get_nums(df.iloc[j]):
            freq[n] = freq.get(n, 0) + 1

    ritardo = {}
    for n in range(1, 50):
        found = False
        for j in range(prev, max(-1, prev - 201), -1):
            if n in set(get_nums(df.iloc[j])):
                ritardo[n] = prev - j
                found = True
                break
        if not found:
            ritardo[n] = 200

    X     = np.array(
        [_make_feature_row(n, pool, freq, ritardo, num_bias, pos_boost)
         for n in range(1, 50)],
        dtype=np.float32,
    )
    probs = clf.predict_proba(scaler.transform(X))[:, 1]
    return {n: float(probs[n - 1]) for n in range(1, 50)}, pool


# ── STRATO 5: SESTINA FINALE ──────────────────────────────────────────────────
def generate_sestine(pool, probs, n_sestine=3,
                     s_min=SUM_MIN, s_max=SUM_MAX,
                     r_min=RANGE_MIN, d_min=MIN_DECADES):
    """Re-rank pool numbers by calibrated probs, apply hard constraints."""
    pool_ranked = sorted(pool["pool_all"], key=lambda x: probs.get(x, 0), reverse=True)
    top_pool    = pool_ranked[:min(28, len(pool_ranked))]

    results = []
    for combo in combinations(top_pool, 6):
        s   = sorted(combo)
        rng = s[5] - s[0]
        if rng < r_min:
            continue
        if len(set(n // 10 for n in s)) < d_min:
            continue
        tot = sum(s)
        if not (s_min <= tot <= s_max):
            continue
        results.append((sum(probs.get(n, 0) for n in s), s))

    results.sort(reverse=True)

    # Fallback: relax constraints if nothing found
    if not results:
        for combo in combinations(top_pool, 6):
            s = sorted(combo)
            if s[5] - s[0] < 20:
                continue
            results.append((sum(probs.get(n, 0) for n in s), s))
        results.sort(reverse=True)

    return results[:n_sestine]


# ── HTML HELPERS ──────────────────────────────────────────────────────────────
def ball_html(n, css="out"):
    return f'<span class="ball {css}">{n:02d}</span>'


def pool_html(pool):
    parts = (
        [ball_html(n, "ripe")  for n in sorted(pool["ripetuti"])]
        + [ball_html(n, "sofi1") for n in sorted(pool["soffi_1"])]
        + [ball_html(n, "sofi2") for n in sorted(pool["soffi_24"])]
    )
    return "".join(parts)


def sestina_html(nums, pool=None, actual=None):
    parts = []
    for n in sorted(nums):
        if actual and n in actual:
            css = "hit"
        elif pool:
            if   n in pool.get("ripetuti", set()):  css = "ripe"
            elif n in pool.get("soffi_1",  set()):  css = "sofi1"
            elif n in pool.get("soffi_24", set()):  css = "sofi2"
            else:                                    css = "out"
        else:
            css = "out"
        parts.append(ball_html(n, css))
    return "".join(parts)


def kpi_card(val, label, sub=""):
    return (
        f'<div class="kpi"><div class="kv">{val}</div>'
        f'<div class="kl">{label}</div>'
        + (f'<div class="kl">{sub}</div>' if sub else "")
        + "</div>"
    )


# ── MAIN ──────────────────────────────────────────────────────────────────────
st.title("🧬 Meta-Learner — Signal Correction Engine")
st.caption(
    "Impara dagli errori reali di App 1 su 300 draw e corregge i segnali in tempo reale. "
    "Zero data leakage — ogni draw usa solo dati precedenti."
)

df      = load_draws()
df_hash = f"{len(df)}-{int(df.iloc[-1]['draw'])}"

if len(df) < WARMUP + 20:
    st.error(f"Servono almeno {WARMUP+20} estrazioni. Trovate: {len(df)}")
    st.stop()

# Run all strati (cached after first run)
prec_tables, rolling_data, dyn_weights = compute_precision(df_hash, df)
bias, fn_c, fp_c, num_bias, n_draws    = compute_decade_bias(df_hash, df)
pos_means, pos_stds, pos_errors, pos_boost = compute_positional_analysis(df_hash, df)
clf, scaler = train_meta_learner(df_hash, df, num_bias, pos_boost)

next_probs, next_pool = predict_next_draw(df, clf, scaler, num_bias, pos_boost)
top_sestine           = generate_sestine(next_pool, next_probs)

# ── TABS ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Precision Storica",
    "🎯 Errori per Decina",
    "⚗️ Segnale Corretto",
    "🔍 Verifica Storica",
])

CAT_COLORS = {
    "Ripetuto":      "#e74c3c",
    "Soffio±1": "#3498db",
    "Coperto±2-4": "#e67e22",
}

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — PRECISION STORICA
# ═══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("Precision reale per categoria (walk-forward, zero leakage)")
    st.caption(
        "P(cat) = hit_cat / volte_in_pool — walk-forward su ogni draw usando solo dati precedenti."
    )

    w100 = prec_tables.get(100)
    if w100 is not None:
        cols = st.columns(3)
        for i, cat in enumerate(list(CAT_COLORS)):
            with cols[i]:
                if cat in w100.index:
                    p   = w100.loc[cat, "precision"]
                    h   = int(w100.loc[cat, "hits"])
                    app = int(w100.loc[cat, "appearances"])
                    st.markdown(
                        kpi_card(f"{p:.1%}", cat, f"{h} hit / {app} in pool (100 draw)"),
                        unsafe_allow_html=True,
                    )

    st.markdown("---")
    st.markdown("#### Precision per finestra temporale")
    trows = []
    for ws in [50, 100, 200, 300]:
        pt = prec_tables.get(ws)
        if pt is None:
            continue
        for cat in list(CAT_COLORS):
            if cat in pt.index:
                trows.append({
                    "Finestra":  f"{ws} draw",
                    "Categoria": cat,
                    "Precision": f"{pt.loc[cat,'precision']:.1%}",
                    "Hit":       int(pt.loc[cat, "hits"]),
                    "In Pool":   int(pt.loc[cat, "appearances"]),
                    "Hit/Draw":  f"{pt.loc[cat,'hits'] / ws:.2f}",
                })
    if trows:
        st.dataframe(pd.DataFrame(trows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("#### Precision cumulativa nel tempo")
    fig = go.Figure()
    for cat, color in CAT_COLORS.items():
        rd = rolling_data.get(cat, {})
        if rd:
            fig.add_trace(go.Scatter(
                x=rd["draw"], y=rd["rolling_prec"],
                name=cat, line=dict(color=color, width=2), mode="lines",
            ))
    fig.update_layout(
        template="plotly_dark", height=350,
        xaxis_title="Draw #", yaxis_title="Precision cumulativa",
        yaxis_tickformat=".0%",
        paper_bgcolor="#0a0e17", plot_bgcolor="#0d1117", margin=dict(t=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Pesi dinamici vs originali App 1")
    orig_w = {"Ripetuto": 1.5, "Soffio±1": 2.5, "Coperto±2-4": 2.0}
    wcols  = st.columns(3)
    for i, cat in enumerate(list(CAT_COLORS)):
        with wcols[i]:
            w     = dyn_weights[cat]
            delta = w - orig_w[cat]
            arrow = "▲" if delta > 0 else "▼"
            color = "#2ecc71" if delta > 0 else "#e74c3c"
            st.markdown(
                kpi_card(
                    f"{w:.3f}", cat,
                    f"Originale: {orig_w[cat]:.1f} &nbsp; "
                    f'<span style="color:{color}">{arrow} {abs(delta):.3f}</span>',
                ),
                unsafe_allow_html=True,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — ERRORI PER DECINA
# ═══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("Errori sistematici per decina")
    st.caption(
        f"Analisi su {n_draws} draw. FP = in pool ma non uscito. FN = uscito ma non in pool. "
        "Bias = (FP-FN)/draw — positivo → sovrastimata → penalizzata."
    )

    decade_names = [d[0] for d in DECADES]
    cols = st.columns(5)
    for i, dname in enumerate(decade_names):
        with cols[i]:
            b     = bias[dname]
            color = "#e74c3c" if b > 0.5 else ("#2ecc71" if b < -0.5 else "#8b949e")
            label = "Sovrastimata" if b > 0.5 else ("Sottostimata" if b < -0.5 else "Bilanciata")
            st.markdown(
                kpi_card(f"{b:+.2f}", dname,
                         f"{label} · FP:{fp_c[dname]} FN:{fn_c[dname]}"),
                unsafe_allow_html=True,
            )

    st.markdown("---")
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        name="Falsi Positivi (in pool, non uscito)",
        x=decade_names, y=[fp_c[d] for d in decade_names],
        marker_color="#e74c3c",
    ))
    fig2.add_trace(go.Bar(
        name="Falsi Negativi (uscito, non in pool)",
        x=decade_names, y=[fn_c[d] for d in decade_names],
        marker_color="#2ecc71",
    ))
    fig2.update_layout(
        barmode="group", template="plotly_dark", height=320,
        paper_bgcolor="#0a0e17", plot_bgcolor="#0d1117",
        margin=dict(t=10), yaxis_title="Conteggio",
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("#### Bias netto (FP-FN)/draw per decina")
    fig3 = go.Figure(go.Bar(
        x=decade_names,
        y=[bias[d] for d in decade_names],
        marker_color=["#e74c3c" if bias[d] > 0 else "#2ecc71" for d in decade_names],
        text=[f"{bias[d]:+.2f}" for d in decade_names],
        textposition="outside",
    ))
    fig3.update_layout(
        template="plotly_dark", height=270,
        paper_bgcolor="#0a0e17", plot_bgcolor="#0d1117",
        margin=dict(t=30), yaxis_title="Bias",
    )
    st.plotly_chart(fig3, use_container_width=True)

    st.markdown("#### Top 20 numeri più sbilanciati")
    bias_rows = sorted(
        [(n, num_bias.get(n, 0.0)) for n in range(1, 50)],
        key=lambda x: abs(x[1]), reverse=True,
    )
    bdf = pd.DataFrame([{
        "Numero":   n,
        "Bias":     f"{b:+.3f}",
        "Effetto":  "Penalizzato" if b > 0 else "Premiato",
        "Decina":   next(dn for dn, ds in DECADES if n in ds),
    } for n, b in bias_rows[:20]])
    st.dataframe(bdf, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SEGNALE CORRETTO
# ═══════════════════════════════════════════════════════════════════════════════
with tab3:
    last_draw_num = int(df.iloc[-1]["draw"])
    st.subheader(f"⚗️ Segnale Corretto — Prossima draw dopo #{last_draw_num}")
    st.caption(
        f"Numeri re-rankati SOLO dal pool di App 1 con probabilità Meta-Learner. "
        f"Vincoli: range ≥ {RANGE_MIN}, ≥ {MIN_DECADES} decine, somma {SUM_MIN}-{SUM_MAX}."
    )

    st.markdown("**Pool App 1:** " + pool_html(next_pool), unsafe_allow_html=True)
    st.caption(
        f"Ripetuti: {len(next_pool['ripetuti'])} | "
        f"Soffi±1: {len(next_pool['soffi_1'])} | "
        f"Coperti±2-4: {len(next_pool['soffi_24'])} | "
        f"Totale: {len(next_pool['pool_all'])}"
    )
    st.markdown("---")

    if not top_sestine:
        st.error("Nessuna sestina trovata. Pool troppo piccolo o vincoli troppo stretti.")
    else:
        for rank, (score, sestina) in enumerate(top_sestine, 1):
            pari = sum(1 for n in sestina if n % 2 == 0)
            rng  = max(sestina) - min(sestina)
            tot  = sum(sestina)
            dec  = len(set(n // 10 for n in sestina))

            st.markdown(f"### #{rank}  —  Score ML: {score:.4f}")
            st.markdown(sestina_html(sestina, pool=next_pool), unsafe_allow_html=True)

            details = []
            for n in sorted(sestina):
                cat = ("Ripetuto"     if n in next_pool["ripetuti"]  else
                       "Soffio±1"    if n in next_pool["soffi_1"]   else
                       "Coperto±2-4" if n in next_pool["soffi_24"]  else "—")
                p   = next_probs.get(n, 0)
                b   = num_bias.get(n, 0)
                tag = "▲ premiato" if b < -0.2 else ("▼ penalizzato" if b > 0.2 else "≈ neutro")
                details.append(
                    f"**{n:02d}** {cat} · p={p:.2%} · bias={b:+.2f} {tag}"
                )
            for line in details:
                st.markdown(f"- {line}")
            st.caption(
                f"Range: {rng} | Somma: {tot} | Decine: {dec} | "
                f"Pari: {pari} | Dispari: {6-pari}"
            )
            st.markdown("---")

    # Probability heatmap 1-49
    st.markdown("#### P(esce) — tutti i 49 numeri")
    bar_colors = [
        "#e74c3c" if n in next_pool["ripetuti"]  else
        "#3498db" if n in next_pool["soffi_1"]   else
        "#e67e22" if n in next_pool["soffi_24"]  else
        "#2c3e50"
        for n in range(1, 50)
    ]
    fig_h = go.Figure(go.Bar(
        x=list(range(1, 50)),
        y=[next_probs.get(n, 0) for n in range(1, 50)],
        marker_color=bar_colors,
        hovertemplate="%{x}: %{y:.2%}<extra></extra>",
    ))
    fig_h.update_layout(
        template="plotly_dark", height=300,
        paper_bgcolor="#0a0e17", plot_bgcolor="#0d1117",
        xaxis_title="Numero", yaxis_title="P(esce)",
        yaxis_tickformat=".0%", margin=dict(t=10),
    )
    st.plotly_chart(fig_h, use_container_width=True)

    st.markdown("#### Coefficienti Meta-Learner")
    coef_df = pd.DataFrame({
        "Feature":      FEATURE_NAMES,
        "Coefficiente": clf.coef_[0],
    }).sort_values("Coefficiente", ascending=False)
    coef_df["Direzione"] = coef_df["Coefficiente"].apply(
        lambda c: "▲ Promuove" if c > 0 else "▼ Penalizza"
    )
    st.dataframe(coef_df, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — VERIFICA STORICA
# ═══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("🔍 Verifica Storica — Meta-Learner vs App 1")
    st.caption(
        "Seleziona una draw passata. Pool e feature calcolati con soli dati precedenti. "
        "Il modello LR è globale (trained su tutto lo storico disponibile)."
    )

    total_draws = len(df)
    min_idx     = WARMUP + 10
    draw_nums   = [int(df.iloc[i]["draw"]) for i in range(min_idx, total_draws)]
    default_i   = max(0, len(draw_nums) - 2)

    sel_draw = st.selectbox("Draw da verificare", draw_nums, index=default_i)
    sel_idx  = int(df.index[df["draw"] == sel_draw][0])
    sel_date = str(df.iloc[sel_idx]["date"])[:10]
    sel_act  = set(get_nums(df.iloc[sel_idx]))

    hist_probs, hist_pool = predict_proba_for(
        df, sel_idx, clf, scaler, num_bias, pos_boost
    )
    hist_ml   = generate_sestine(hist_pool, hist_probs, n_sestine=3)
    app1_w    = {
        n: (1.5 if n in hist_pool["ripetuti"] else
            2.5 if n in hist_pool["soffi_1"]  else
            2.0 if n in hist_pool["soffi_24"] else 0.0)
        for n in range(1, 50)
    }
    hist_app1 = generate_sestine(hist_pool, app1_w, n_sestine=1)

    # Result header
    col_r, col_p = st.columns(2)
    with col_r:
        st.markdown(f"**Draw #{sel_draw}** ({sel_date})")
        st.markdown("**Risultato reale:**")
        st.markdown(sestina_html(sel_act, pool=hist_pool), unsafe_allow_html=True)
        psize = len(hist_pool["pool_all"])
        inp   = len(sel_act & hist_pool["pool_all"])
        st.caption(
            f"Pool: {psize} | Nel pool: {inp}/6 | "
            f"Ripe: {len(sel_act & hist_pool['ripetuti'])} | "
            f"Sofi: {len(sel_act & hist_pool['soffi_1'])} | "
            f"Cop: {len(sel_act & hist_pool['soffi_24'])}"
        )
    with col_p:
        st.markdown("**Pool App 1:**")
        st.markdown(pool_html(hist_pool), unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### Meta-Learner — top-3 sestine (pesi calibrati)")
    best_ml = 0
    if not hist_ml:
        st.warning("Nessuna sestina trovata.")
    else:
        for rank, (score, sestina) in enumerate(hist_ml, 1):
            hits    = len(set(sestina) & sel_act)
            best_ml = max(best_ml, hits)
            mark    = "🎯" * hits if hits else "❌"
            st.markdown(f"**ML #{rank}** &nbsp; {mark} {hits}/6 hit &nbsp; Score: {score:.4f}")
            st.markdown(
                sestina_html(sestina, pool=hist_pool, actual=sel_act),
                unsafe_allow_html=True,
            )
            st.caption(
                f"Range: {max(sestina)-min(sestina)} | Somma: {sum(sestina)} | "
                f"Decine: {len(set(n//10 for n in sestina))}"
            )
            st.markdown("---")

    st.markdown("#### App 1 — sestina con pesi fissi")
    best_a1 = 0
    if hist_app1:
        _, a1_best = hist_app1[0]
        best_a1    = len(set(a1_best) & sel_act)
        mark1      = "🎯" * best_a1 if best_a1 else "❌"
        st.markdown(f"**App 1 #1** &nbsp; {mark1} {best_a1}/6 hit")
        st.markdown(
            sestina_html(a1_best, pool=hist_pool, actual=sel_act),
            unsafe_allow_html=True,
        )
        st.caption(f"Range: {max(a1_best)-min(a1_best)} | Somma: {sum(a1_best)}")

    st.markdown("---")
    if best_ml > best_a1:
        st.success(f"✅ Meta-Learner vince: {best_ml} hit vs App 1: {best_a1} hit")
    elif best_ml == best_a1:
        st.info(f"↔️ Pareggio: entrambi {best_ml} hit")
    else:
        st.warning(f"⚠️ App 1 vince: {best_a1} hit vs Meta-Learner: {best_ml} hit")

    with st.expander("Dettaglio probabilità tutti i numeri del pool"):
        prows = []
        for n in sorted(hist_pool["pool_all"]):
            cat = ("Ripetuto"     if n in hist_pool["ripetuti"]  else
                   "Soffio±1"    if n in hist_pool["soffi_1"]   else
                   "Coperto±2-4")
            prows.append({
                "Numero":    n,
                "Categoria": cat,
                "P(ML)":     f"{hist_probs.get(n,0):.2%}",
                "P(App1)":   f"{app1_w.get(n,0):.2f}",
                "Uscito":    "✅" if n in sel_act else "—",
            })
        st.dataframe(pd.DataFrame(prows), use_container_width=True, hide_index=True)
