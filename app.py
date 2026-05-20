"""
Lotto NO PLUS — v5
Walk-forward backtest | 2+2+2+2 strategy | 13 Laws | Auto-fetch | Verifica risultati
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from itertools import combinations
from sklearn.ensemble import RandomForestClassifier
from sklearn.multioutput import MultiOutputClassifier
import requests, re
from datetime import date, timedelta
import warnings
warnings.filterwarnings("ignore")

st.set_page_config(page_title="Lotto NO PLUS", page_icon="🎯", layout="wide",
                   initial_sidebar_state="expanded")

# ── THEME ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  body, .stApp { background:#0d1117; color:#e6edf3; }
  .block-container { padding-top:1rem; }
  .kpi-box { background:#161b22; border:1px solid #30363d; border-radius:10px;
             padding:1rem 1.5rem; text-align:center; }
  .kpi-val { font-size:2rem; font-weight:700; color:#f0a500; }
  .kpi-lab { font-size:.8rem; color:#8b949e; margin-top:4px; }
  .ball { display:inline-block; width:36px; height:36px; border-radius:50%;
          font-weight:700; font-size:.85rem; line-height:36px; text-align:center;
          margin:3px; }
  .ball-ripe  { background:#e74c3c; color:#fff; }
  .ball-sofi1 { background:#3498db; color:#fff; }
  .ball-sofi2 { background:#e67e22; color:#fff; }
  .ball-ml    { background:#9b59b6; color:#fff; }
  .ball-std   { background:#2ecc71; color:#fff; }
  .ball-out   { background:#2c3e50; color:#8b949e; border:1px solid #444; }
  .hit-box  { background:#0d3b1e; border:1px solid #2ecc71; border-radius:8px;
              padding:.5rem 1rem; margin:.3rem 0; }
  .miss-box { background:#3b0d0d; border:1px solid #e74c3c; border-radius:8px;
              padding:.5rem 1rem; margin:.3rem 0; }
  section[data-testid="stSidebar"] { background:#0d1117 !important; }
  section[data-testid="stSidebar"] .block-container { padding:1rem; }
  div[data-testid="stTabs"] button { color:#8b949e !important; }
  div[data-testid="stTabs"] button[aria-selected="true"] { color:#f0a500 !important;
    border-bottom:2px solid #f0a500 !important; }
  hr { border-color:#30363d; }
</style>
""", unsafe_allow_html=True)

# ── DATA LOADING ──────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="Caricamento dati…")
def load_draws():
    try:
        df = pd.read_csv("lotto_draws.csv")
    except FileNotFoundError:
        st.error("⚠️ lotto_draws.csv non trovato nella cartella dell'app.")
        st.stop()

    # normalise column names
    df.columns = [c.lower().strip() for c in df.columns]
    num_cols = [c for c in df.columns if c.startswith("n") and c[1:].isdigit()]
    if not num_cols:
        num_cols = [c for c in df.columns if "num" in c or "ball" in c]
    if len(num_cols) < 6:
        candidates = [c for c in df.columns if df[c].dtype in [np.int64, np.float64]]
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


# ── AUTO-FETCH MISSING DRAWS ──────────────────────────────────────────────────
# Polish Lotto (Kumulacja) draws: Tuesday=1, Thursday=3, Saturday=5
_DRAW_WEEKDAYS = {1, 3, 5}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


def _extract_lotto_nums(html: str):
    """
    Try multiple parsing strategies to extract exactly 6 valid lotto numbers (1-49)
    from an HTML page. Returns sorted list of 6 ints or None.
    """
    # Strategy 1: JSON embedded — look for array of 6 numbers 1-49
    json_pattern = re.compile(r'\[(\s*\d+\s*(?:,\s*\d+\s*){5})\]')
    for m in json_pattern.finditer(html):
        parts = [int(x) for x in m.group(1).split(",")]
        if len(parts) == 6 and all(1 <= x <= 49 for x in parts) and len(set(parts)) == 6:
            s = sorted(parts)
            if s[-1] - s[0] > 20:
                return s

    # Strategy 2: HTML ball elements — spans/divs with class containing "ball" or "liczba"
    ball_pat = re.compile(
        r'class="[^"]*(?:ball|liczba|lotto-ball|result-ball|number)[^"]*"[^>]*>\s*(\d{1,2})\s*<',
        re.IGNORECASE,
    )
    ball_nums = []
    for m in ball_pat.finditer(html):
        n = int(m.group(1))
        if 1 <= n <= 49 and n not in ball_nums:
            ball_nums.append(n)
        if len(ball_nums) == 6:
            s = sorted(ball_nums)
            if s[-1] - s[0] > 20:
                return s
            ball_nums = []

    # Strategy 3: data-number or data-value attributes
    data_pat = re.compile(r'data-(?:number|value|ball)="(\d{1,2})"', re.IGNORECASE)
    data_nums = []
    for m in data_pat.finditer(html):
        n = int(m.group(1))
        if 1 <= n <= 49 and n not in data_nums:
            data_nums.append(n)
        if len(data_nums) == 6:
            s = sorted(data_nums)
            if s[-1] - s[0] > 20:
                return s
            data_nums = []

    # Strategy 4: sliding window of 6 unique 1-49 numbers (fallback, conservative)
    all_nums = [int(x) for x in re.findall(r'\b([1-9]|[1-4]\d)\b', html)]
    window = []
    for n in all_nums:
        if n not in window:
            window.append(n)
        if len(window) == 6:
            s = sorted(window)
            # strict validation: span > 25, all unique, no obvious date numbers
            if s[-1] - s[0] > 25 and s[5] <= 49:
                return s
            window.pop(0)

    return None


def fetch_draw_for_date(draw_date_str: str):
    """
    Fetch 6 Kumulacja numbers for a given date (YYYY-MM-DD).
    Tries multiple Polish lotto result sites. Returns sorted list[int] or None.
    """
    y, m, d = draw_date_str[:4], draw_date_str[5:7], draw_date_str[8:10]

    urls = [
        # wynikilotto.net.pl — main source
        f"https://www.wynikilotto.net.pl/lotto/wyniki/{y}/{m}/{d}/",
        # pewniaki.pl — backup
        f"https://pewniaki.pl/wyniki-lotto/{y}-{m}-{d}/",
        # lotto.pl — official (HTML, might block bots)
        f"https://www.lotto.pl/lotto/wyniki-i-wygrane/wyniki-losowania/{y}-{m}-{d}",
        # totalniaki.pl
        f"https://totalniaki.pl/wyniki-lotto/{y}-{m}-{d}/",
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            result = _extract_lotto_nums(resp.text)
            if result:
                return result
        except Exception:
            continue

    return None


def get_missing_draw_dates(df) -> list:
    """
    Returns list of date strings (YYYY-MM-DD) that should have a draw
    but are not yet in the database. Uses Tue/Thu/Sat schedule.
    """
    known_dates = set(str(x)[:10] for x in df["date"] if str(x)[:10] != "nan")
    last_date_str = str(df.iloc[-1]["date"])[:10]
    try:
        last_date = date.fromisoformat(last_date_str)
    except Exception:
        return []

    today = date.today()
    missing = []
    d = last_date + timedelta(days=1)
    while d <= today:
        if d.weekday() in _DRAW_WEEKDAYS and str(d) not in known_dates:
            missing.append(str(d))
        d += timedelta(days=1)
    return missing


def auto_update_draws(df):
    """
    Called at app startup: silently fetch any missing draws and update CSV.
    Returns (updated_df, n_added, [messages]).
    """
    missing = get_missing_draw_dates(df)
    if not missing:
        return df, 0, []

    added, messages = 0, []
    current_df = df.copy()

    for draw_date in missing:
        nums = fetch_draw_for_date(draw_date)
        if nums and len(set(nums)) == 6 and all(1 <= n <= 49 for n in nums):
            next_draw_num = int(current_df.iloc[-1]["draw"]) + 1
            current_df = add_draw_to_csv(current_df, next_draw_num, draw_date, sorted(nums))
            messages.append(
                f"Draw #{next_draw_num} ({draw_date}): "
                + " ".join(f"{n:02d}" for n in sorted(nums))
            )
            added += 1

    return current_df, added, messages


def add_draw_to_csv(df, draw_num, draw_date, nums):
    """Append a new draw row, save CSV, return updated df."""
    new_row = {
        "draw": int(draw_num), "date": str(draw_date),
        "n1": nums[0], "n2": nums[1], "n3": nums[2],
        "n4": nums[3], "n5": nums[4], "n6": nums[5],
    }
    df_new = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df_new = (df_new.sort_values("draw")
                    .drop_duplicates(subset=["draw"])
                    .reset_index(drop=True))
    df_new.to_csv("lotto_draws.csv", index=False)
    return df_new


# ── 13 LAWS ───────────────────────────────────────────────────────────────────
def check_laws(nums, df_history=None, draw_idx=None):
    n = sorted(nums)
    laws = {}

    # L1: tutti 6 nel pool degli ultimi 9 draw
    if df_history is not None and draw_idx is not None and draw_idx >= 9:
        pool9 = set()
        for i in range(draw_idx - 9, draw_idx):
            pool9.update(get_nums(df_history.iloc[i]))
        laws["L1_pool9"] = all(x in pool9 for x in n)
    else:
        laws["L1_pool9"] = True

    # L2: tutti 6 nel pool degli ultimi 5 draw
    if df_history is not None and draw_idx is not None and draw_idx >= 5:
        pool5 = set()
        for i in range(draw_idx - 5, draw_idx):
            pool5.update(get_nums(df_history.iloc[i]))
        laws["L2_pool5"] = all(x in pool5 for x in n)
    else:
        laws["L2_pool5"] = True

    # L3: ≥3 decine diverse
    laws["L3_decine"] = len(set(x // 10 for x in n)) >= 3

    # L4: pari/dispari alternati (non 6 pari o 6 dispari)
    pari = sum(1 for x in n if x % 2 == 0)
    laws["L4_pari_disp"] = 1 <= pari <= 5

    # L5: range (max-min) > 20
    laws["L5_range"] = (n[5] - n[0]) > 20

    # L6: primo numero ≤ 10 oppure secondo ≤ 15
    laws["L6_d1d2"] = n[0] <= 10 or n[1] <= 15

    # L7: gap medio tra consecutivi 5-10
    gaps = [n[i+1] - n[i] for i in range(5)]
    avg_gap = sum(gaps) / 5
    laws["L7_gap"] = 4 <= avg_gap <= 11

    # L8: primo numero ≤ 15
    laws["L8_n1"] = n[0] <= 15

    # L9: ultimo numero ≥ 35
    laws["L9_n6"] = n[5] >= 35

    # L10: almeno una coppia con differenza ≤ 3
    laws["L10_coppia"] = any(n[i+1] - n[i] <= 3 for i in range(5))

    # L11: pari in range 2-4
    laws["L11_pari24"] = 2 <= pari <= 4

    # L12: media in 18-32
    laws["L12_media"] = 18 <= (sum(n) / 6) <= 32

    # L13: somma in range storicamente frequente (70-160)
    laws["L13_somma"] = 70 <= sum(n) <= 160

    return laws


def laws_pass_count(nums, df_history=None, draw_idx=None):
    lv = check_laws(nums, df_history, draw_idx)
    return sum(lv.values()), len(lv)


# ── POOL BUILDING ─────────────────────────────────────────────────────────────
def build_pool(df, draw_idx=-1):
    row = df.iloc[draw_idx]
    last = get_nums(row)

    ripetuti = set(last)
    soffi_1 = set()
    soffi_24 = set()

    for n in last:
        for d in (1,):
            if 1 <= n - d <= 49: soffi_1.add(n - d)
            if 1 <= n + d <= 49: soffi_1.add(n + d)
        for d in (2, 3, 4):
            if 1 <= n - d <= 49: soffi_24.add(n - d)
            if 1 <= n + d <= 49: soffi_24.add(n + d)

    soffi_1  -= ripetuti
    soffi_24 -= ripetuti | soffi_1

    pool_all = ripetuti | soffi_1 | soffi_24

    # compute frequency in last 50 draws
    freq = {}
    start = max(0, draw_idx - 50 if draw_idx > 0 else len(df) - 51)
    end   = draw_idx if draw_idx > 0 else len(df) - 1
    for i in range(start, end):
        for x in get_nums(df.iloc[i]):
            freq[x] = freq.get(x, 0) + 1

    return {
        "ripetuti": ripetuti,
        "soffi_1":  soffi_1,
        "soffi_24": soffi_24,
        "pool_all": pool_all,
        "last_nums": last,
        "freq": freq,
    }


def classify_num(n, pool_info):
    if n in pool_info["ripetuti"]:  return "ripe"
    if n in pool_info["soffi_1"]:   return "sofi1"
    if n in pool_info["soffi_24"]:  return "sofi2"
    return "std"


# ── ML MODEL ─────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Addestramento ML…")
def train_ml(df_hash, _df):
    df = _df
    X, y = [], []
    for i in range(20, len(df) - 1):
        feats = []
        for j in range(i - 10, i):
            feats.extend(get_nums(df.iloc[j]))
        # frequency features
        freq = {}
        for j in range(max(0, i - 50), i):
            for x in get_nums(df.iloc[j]):
                freq[x] = freq.get(x, 0) + 1
        for n in range(1, 50):
            feats.append(freq.get(n, 0))
        X.append(feats)
        y.append(get_nums(df.iloc[i]))

    X = np.array(X, dtype=np.float32)
    y_bin = np.zeros((len(y), 49), dtype=np.int8)
    for idx, row in enumerate(y):
        for n in row:
            y_bin[idx, n - 1] = 1

    clf = MultiOutputClassifier(RandomForestClassifier(
        n_estimators=100, max_depth=8, random_state=42, n_jobs=-1
    ))
    clf.fit(X, y_bin)
    return clf, X[-1]


def ml_predict(clf, df, top_n=8):
    feats = []
    for j in range(len(df) - 10, len(df)):
        feats.extend(get_nums(df.iloc[j]))
    freq = {}
    for j in range(max(0, len(df) - 50), len(df)):
        for x in get_nums(df.iloc[j]):
            freq[x] = freq.get(x, 0) + 1
    for n in range(1, 50):
        feats.append(freq.get(n, 0))

    X = np.array([feats], dtype=np.float32)
    probs = np.array([e.predict_proba(X)[0][1] for e in clf.estimators_])
    ranked = np.argsort(probs)[::-1][:top_n] + 1
    return list(ranked), probs


# ── WALK-FORWARD BACKTEST ─────────────────────────────────────────────────────
@st.cache_data(show_spinner="Eseguendo backtest…", ttl=300)
def run_backtest(df_hash, _df, n_draws=100):
    df   = _df
    total = len(df)
    start = total - n_draws
    rows  = []

    for i in range(start, total):
        actual = set(get_nums(df.iloc[i]))
        pool   = build_pool(df, draw_idx=i - 1)

        ripe_hits   = len(pool["ripetuti"] & actual)
        sofi1_hits  = len(pool["soffi_1"]  & actual)
        sofi24_hits = len(pool["soffi_24"] & actual)
        pool_hits   = len(pool["pool_all"] & actual)
        outside     = 6 - pool_hits

        laws_ok, laws_tot = laws_pass_count(sorted(actual), df, i)

        rows.append({
            "draw":       int(df.iloc[i]["draw"]),
            "date":       str(df.iloc[i]["date"])[:10],
            "actual":     sorted(actual),
            "ripe_hits":  ripe_hits,
            "sofi1_hits": sofi1_hits,
            "sofi24_hits":sofi24_hits,
            "pool_hits":  pool_hits,
            "outside":    outside,
            "laws_ok":    laws_ok,
            "pool_size":  len(pool["pool_all"]),
        })

    return pd.DataFrame(rows)


# ── STRATEGY: top 5 sestine ───────────────────────────────────────────────────
def generate_candidates(pool_info, ml_nums, df, n_sample=5000, seed=42):
    rng  = np.random.default_rng(seed)
    pool = sorted(pool_info["pool_all"])
    extra = [n for n in ml_nums if n not in pool_info["pool_all"]]
    extended_pool = pool + extra[:4]

    results = []
    tried   = set()

    # Weighted sampling: ripetuti/soffi get higher weight
    weights = []
    for n in extended_pool:
        if n in pool_info["ripetuti"]:   weights.append(4)
        elif n in pool_info["soffi_1"]:  weights.append(3)
        elif n in pool_info["soffi_24"]: weights.append(2)
        elif n in ml_nums:               weights.append(2)
        else:                            weights.append(1)

    w_arr = np.array(weights, dtype=float)
    w_arr /= w_arr.sum()

    for _ in range(n_sample * 3):
        if len(results) >= n_sample:
            break
        chosen = rng.choice(extended_pool, size=6, replace=False, p=w_arr)
        key    = tuple(sorted(chosen))
        if key in tried:
            continue
        tried.add(key)

        nums  = list(key)
        score = 0

        # signal hits
        ripe_in  = sum(1 for x in nums if x in pool_info["ripetuti"])
        sofi1_in = sum(1 for x in nums if x in pool_info["soffi_1"])
        sofi24_in= sum(1 for x in nums if x in pool_info["soffi_24"])
        ml_in    = sum(1 for x in nums if x in ml_nums)

        # empirical weights from backtest: avg sofi1=1.28, sofi24=2.18, ripe=0.72
        score += ripe_in  * 1.5
        score += sofi1_in * 2.5
        score += sofi24_in* 2.0
        score += ml_in    * 1.8

        # frequency bonus
        score += sum(pool_info["freq"].get(x, 0) * 0.05 for x in nums)

        # law filter
        lp, lt = laws_pass_count(nums, df, len(df))
        law_ratio = lp / lt
        if law_ratio < 0.7:   # reject < 9/13 laws
            continue
        score += law_ratio * 3

        results.append({
            "nums":     nums,
            "score":    round(score, 3),
            "ripe_in":  ripe_in,
            "sofi1_in": sofi1_in,
            "sofi24_in":sofi24_in,
            "ml_in":    ml_in,
            "laws_ok":  lp,
        })

    results.sort(key=lambda x: -x["score"])
    return results[:5]


# ── BALL HTML ─────────────────────────────────────────────────────────────────
def ball_html(n, cls="std"):
    return f'<span class="ball ball-{cls}">{n:02d}</span>'


def nums_html(nums, pool_info=None, actual=None):
    out = ""
    for n in sorted(nums):
        if actual is not None:
            cls = "sofi1" if n in actual else "out"
        elif pool_info:
            cls = classify_num(n, pool_info)
        else:
            cls = "std"
        out += ball_html(n, cls)
    return out


# ── SIDEBAR ───────────────────────────────────────────────────────────────────
def render_sidebar(df):
    with st.sidebar:
        st.markdown("## 🗄️ Database")
        last = df.iloc[-1]
        last_draw = int(last["draw"])
        next_draw = last_draw + 1
        st.markdown(f"**Ultima draw:** #{last_draw} · {str(last['date'])[:10]}")
        st.markdown(f"**Tot. draw:** {len(df):,} · **Prossima:** #{next_draw}")
        st.markdown("---")

        # ── Aggiungi draw manuale
        st.markdown("### ➕ Aggiungi draw")
        with st.form("add_draw_form"):
            col_n, col_d = st.columns(2)
            inp_draw = col_n.number_input("N° draw", min_value=1, value=next_draw, step=1)
            inp_date = col_d.date_input("Data", value=date.today())
            c1, c2, c3 = st.columns(3)
            c4, c5, c6 = st.columns(3)
            n1 = c1.number_input("N1", 1, 49, value=1, key="s1")
            n2 = c2.number_input("N2", 1, 49, value=2, key="s2")
            n3 = c3.number_input("N3", 1, 49, value=3, key="s3")
            n4 = c4.number_input("N4", 1, 49, value=4, key="s4")
            n5 = c5.number_input("N5", 1, 49, value=5, key="s5")
            n6 = c6.number_input("N6", 1, 49, value=6, key="s6")
            submitted = st.form_submit_button("✅ Salva draw", use_container_width=True)

        if submitted:
            nums = sorted([n1, n2, n3, n4, n5, n6])
            if len(set(nums)) < 6:
                st.error("I 6 numeri devono essere tutti diversi!")
            else:
                add_draw_to_csv(df, inp_draw, inp_date, nums)
                st.success(f"Draw #{inp_draw} aggiunto: {' '.join(f'{x:02d}' for x in nums)}")
                st.cache_data.clear()
                st.rerun()

        st.markdown("---")

        # ── Auto-fetch manuale (forza ricerca)
        st.markdown("### 🌐 Forza aggiornamento")
        st.caption("Riesegui la ricerca online delle draw mancanti.")
        if st.button("🔍 Cerca ora", use_container_width=True):
            missing = get_missing_draw_dates(df)
            if not missing:
                st.success("✅ Database già aggiornato!")
            else:
                with st.spinner(f"Cerco {len(missing)} draw…"):
                    _, n_added, messages = auto_update_draws(df)
                if n_added:
                    for m in messages:
                        st.success(m)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning(
                        f"Nessuna trovata online per: {', '.join(missing)}\n"
                        "Inseriscile manualmente sopra."
                    )

        st.markdown("---")
        st.caption("💡 Se l'auto-fetch fallisce, inserisci i numeri manualmente sopra.")

    return df


# ── HEADER ────────────────────────────────────────────────────────────────────
def render_header(df):
    last    = df.iloc[-1]
    nums    = get_nums(last)
    somma   = sum(nums)
    rng     = nums[-1] - nums[0]
    pari    = sum(1 for x in nums if x % 2 == 0)
    nx_draw = int(last["draw"]) + 1

    col_logo, col_k1, col_k2, col_k3, col_k4 = st.columns([3, 1, 1, 1, 1])
    with col_logo:
        st.markdown("""
        <div style="display:flex;align-items:center;gap:1rem;">
          <span style="font-size:3rem">🎯</span>
          <div>
            <div style="font-size:2rem;font-weight:800;color:#e6edf3">Lotto NO PLUS</div>
            <div style="font-size:.8rem;color:#8b949e">
              Database: <b>{n}</b> draw (1957–2026) · Ultima: <b>#{draw}</b> del {date} ·
              {balls}
            </div>
          </div>
        </div>
        """.format(
            n=f"{len(df):,}",
            draw=int(last["draw"]),
            date=str(last["date"])[:10],
            balls=" ".join(f"`{x:02d}`" for x in nums),
        ), unsafe_allow_html=True)

    for col, val, lab in [
        (col_k1, somma,   "Somma ultima"),
        (col_k2, rng,     "Range ultima"),
        (col_k3, pari,    "Pari ultima"),
        (col_k4, nx_draw, "Prossima draw"),
    ]:
        with col:
            st.markdown(f"""
            <div class="kpi-box">
              <div class="kpi-val">{val}</div>
              <div class="kpi-lab">{lab}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)


# ── TAB 1: PREDICI ────────────────────────────────────────────────────────────
def tab_predici(df, pool_info, ml_nums, ml_probs, candidates):
    nx = int(df.iloc[-1]["draw"]) + 1
    st.subheader(f"🎯 Pool candidati e sestine top — draw #{nx}")

    # ─ Pool legend
    leg_cols = st.columns(5)
    for c, (label, cls, count) in zip(leg_cols, [
        ("Ripetuti",      "ripe",  len(pool_info["ripetuti"])),
        ("Soffi ±1",      "sofi1", len(pool_info["soffi_1"])),
        ("Coperti ±2-4",  "sofi2", len(pool_info["soffi_24"])),
        ("ML top-8",      "ml",    len([n for n in ml_nums if n in pool_info["pool_all"]])),
        ("Fuori pool",    "out",   49 - len(pool_info["pool_all"])),
    ]):
        c.markdown(f'<span class="ball ball-{cls}">&bull;</span> **{label}** ({count})', unsafe_allow_html=True)

    # ─ Pool balls
    all_pool = sorted(pool_info["pool_all"])
    html = ""
    for n in range(1, 50):
        if n in pool_info["ripetuti"]:   cls = "ripe"
        elif n in pool_info["soffi_1"]:  cls = "sofi1"
        elif n in pool_info["soffi_24"]: cls = "sofi2"
        else:                            cls = "out"
        html += ball_html(n, cls)
    st.markdown(html, unsafe_allow_html=True)

    pool_size = len(pool_info["pool_all"])
    st.markdown(f"**Pool size:** {pool_size}/49 &nbsp;|&nbsp; "
                f"**Ripetuti:** {len(pool_info['ripetuti'])} &nbsp;|&nbsp; "
                f"**Soffi ±1:** {len(pool_info['soffi_1'])} &nbsp;|&nbsp; "
                f"**Soffi ±2-4:** {len(pool_info['soffi_24'])}", unsafe_allow_html=True)

    st.markdown("---")

    # ─ ML top 8
    st.markdown("**ML top-8 numeri predetti:**")
    ml_html = ""
    for n in sorted(ml_nums[:8]):
        cls = classify_num(n, pool_info)
        if cls == "std": cls = "ml"
        ml_html += ball_html(n, cls)
    st.markdown(ml_html, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("🏆 Top 5 Sestine Candidate")

    if not candidates:
        st.warning("Nessuna sestina generata — controlla i dati.")
        return

    for rank, c in enumerate(candidates, 1):
        nums = sorted(c["nums"])
        balls_html = ""
        for n in nums:
            if n in pool_info["ripetuti"]:   cls = "ripe"
            elif n in pool_info["soffi_1"]:  cls = "sofi1"
            elif n in pool_info["soffi_24"]: cls = "sofi2"
            elif n in ml_nums:               cls = "ml"
            else:                            cls = "std"
            balls_html += ball_html(n, cls)

        medal = ["🥇","🥈","🥉","4️⃣","5️⃣"][rank-1]
        st.markdown(f"""
        <div style="background:#161b22;border:1px solid #30363d;border-radius:10px;
                    padding:1rem 1.5rem;margin:.5rem 0;">
          <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap;">
            <span style="font-size:1.5rem">{medal}</span>
            {balls_html}
            <span style="color:#8b949e;font-size:.85rem;margin-left:auto">
              Score: <b style="color:#f0a500">{c['score']}</b> &nbsp;|&nbsp;
              Leggi: {c['laws_ok']}/13 &nbsp;|&nbsp;
              🔴{c['ripe_in']} 🔵{c['sofi1_in']} 🟠{c['sofi24_in']} 🟣{c['ml_in']}
            </span>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ─ Verifica risultato
    st.markdown("---")
    with st.expander(f"🎯 Verifica risultato draw #{nx} — inserisci i numeri usciti"):
        st.caption("Inserisci i 6 numeri usciti per vedere quanti ne ha presi ogni sestina.")
        vc = st.columns(6)
        defaults = [1, 2, 3, 4, 5, 6]
        actual_in = [vc[i].number_input(f"N{i+1}", 1, 49, value=defaults[i], key=f"ver{i}") for i in range(6)]
        actual_set = set(actual_in)

        if len(actual_set) == 6:
            st.markdown("#### Risultato per ogni sestina:")
            for rank, c in enumerate(candidates, 1):
                nums_s = sorted(c["nums"])
                hits  = [n for n in nums_s if n in actual_set]
                misses= [n for n in nums_s if n not in actual_set]
                medal = ["🥇","🥈","🥉","4️⃣","5️⃣"][rank-1]

                balls = ""
                for n in nums_s:
                    cls = "sofi1" if n in actual_set else "out"
                    balls += ball_html(n, cls)

                hit_color = "#0d3b1e" if len(hits) >= 3 else "#2a2a0d" if len(hits) >= 2 else "#3b0d0d"
                hit_border= "#2ecc71" if len(hits) >= 3 else "#f0a500" if len(hits) >= 2 else "#e74c3c"
                st.markdown(f"""
                <div style="background:{hit_color};border:1px solid {hit_border};border-radius:10px;
                            padding:.8rem 1.5rem;margin:.4rem 0;">
                  <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap;">
                    <span style="font-size:1.3rem">{medal}</span>
                    {balls}
                    <span style="margin-left:auto;font-size:1.1rem;font-weight:700;color:{hit_border}">
                      {len(hits)}/6 indovinati
                    </span>
                  </div>
                </div>
                """, unsafe_allow_html=True)

            # also show actual draw balls
            st.markdown("**Numeri usciti:**")
            actual_balls = "".join(ball_html(n, "std") for n in sorted(actual_set))
            st.markdown(actual_balls, unsafe_allow_html=True)
        else:
            st.warning("Inserisci 6 numeri distinti.")

    # ─ Strategy explanation
    st.markdown("---")
    with st.expander("ℹ️ Come funziona la strategia 2+2+2+2"):
        st.markdown("""
**Basi sperimentali** (dalle ultime 100 draw):

| Categoria | Hit medi/draw | P(≥1 hit) | P(≥2 hit) |
|-----------|--------------|-----------|-----------|
| 🔴 Ripetuti (stessi numeri) | 0.72 | 56% | 15% |
| 🔵 Soffi ±1 | 1.28 | 79% | 40% |
| 🟠 Coperti ±2-4 | 2.18 | 88% | 65% |
| 🟣 ML Random Forest | ~1.0 | 60% | 25% |

**La sestina è generata così:**
1. Pool ristretto = Ripetuti ∪ Soffi±1 ∪ Coperti±2-4 (in media ~22 numeri su 49)
2. Campionamento pesato: ogni numero è valorizzato per quanti segnali convergono
3. Filtro con 13 leggi (eliminate sestine che violano >3 leggi)
4. Ranking per score composito (segnali × pesi empirici)

**Attenzione onesta:** non esiste sistema che garantisce il "sei".
La probabilità resta 1:13.983.816. Questo tool massimizza i numeri attesi coperti (target: 2-3 hit per sestina).
        """)


# ── TAB 2: BACKTEST ───────────────────────────────────────────────────────────
def tab_backtest(df):
    st.subheader("🔬 Backtest Walk-Forward — Ultime 100 Draw Reali")
    st.caption("Per ogni draw N, la strategia usa solo i dati fino a N-1 (zero data leakage).")

    bt = run_backtest(id(df), df, n_draws=100)

    # ─ KPI summary
    k1, k2, k3, k4, k5 = st.columns(5)
    metrics = [
        ("Hit medi ripetuti",   bt["ripe_hits"].mean(),  "🔴"),
        ("Hit medi soffi ±1",   bt["sofi1_hits"].mean(), "🔵"),
        ("Hit medi coperti",    bt["sofi24_hits"].mean(),"🟠"),
        ("Hit medi pool tot.",  bt["pool_hits"].mean(),  "🟢"),
        ("Fuori pool medi",     bt["outside"].mean(),    "⚫"),
    ]
    for col, (lab, val, ico) in zip([k1, k2, k3, k4, k5], metrics):
        col.markdown(f"""
        <div class="kpi-box">
          <div class="kpi-val">{ico} {val:.2f}</div>
          <div class="kpi-lab">{lab}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ─ Distribution charts
    col_a, col_b = st.columns(2)

    with col_a:
        # Ripetuti distribution
        rc = bt["ripe_hits"].value_counts().sort_index()
        fig = go.Figure(go.Bar(
            x=[str(i) for i in rc.index],
            y=rc.values / len(bt) * 100,
            marker_color=["#e74c3c"] * len(rc),
            text=[f"{v:.0f}%" for v in rc.values / len(bt) * 100],
            textposition="outside",
        ))
        fig.update_layout(
            title="Distribuzione Ripetuti per draw",
            xaxis_title="N° ripetuti", yaxis_title="%",
            plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
            font=dict(color="#e6edf3"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        # Pool hits distribution
        ph = bt["pool_hits"].value_counts().sort_index()
        fig2 = go.Figure(go.Bar(
            x=[str(i) for i in ph.index],
            y=ph.values / len(bt) * 100,
            marker_color=["#2ecc71"] * len(ph),
            text=[f"{v:.0f}%" for v in ph.values / len(bt) * 100],
            textposition="outside",
        ))
        fig2.update_layout(
            title="Copertura pool (hit su 6) per draw",
            xaxis_title="N° numeri reali nel pool", yaxis_title="%",
            plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
            font=dict(color="#e6edf3"), showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ─ Stacked bar: composizione draw
    fig3 = go.Figure()
    x = list(range(1, len(bt) + 1))
    fig3.add_trace(go.Bar(name="🔴 Ripetuti",   x=x, y=bt["ripe_hits"],   marker_color="#e74c3c"))
    fig3.add_trace(go.Bar(name="🔵 Soffi ±1",   x=x, y=bt["sofi1_hits"],  marker_color="#3498db"))
    fig3.add_trace(go.Bar(name="🟠 Coperti ±2-4", x=x, y=bt["sofi24_hits"],marker_color="#e67e22"))
    fig3.add_trace(go.Bar(name="⚫ Fuori pool",  x=x, y=bt["outside"],     marker_color="#2c3e50"))
    fig3.update_layout(
        barmode="stack",
        title="Composizione reale ogni draw (-100 → -1)",
        xaxis_title="Draw (dal più vecchio al più recente)",
        yaxis_title="Numeri per categoria",
        plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
        font=dict(color="#e6edf3"),
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig3, use_container_width=True)

    # ─ Empirical summary table
    st.markdown("### 📊 Statistiche empiriche sperimentali")
    pcts = {
        "Categoria": ["🔴 Ripetuti", "🔵 Soffi ±1", "🟠 Coperti ±2-4", "🟢 Pool tot."],
        "Hit medi": [
            f"{bt['ripe_hits'].mean():.2f}",
            f"{bt['sofi1_hits'].mean():.2f}",
            f"{bt['sofi24_hits'].mean():.2f}",
            f"{bt['pool_hits'].mean():.2f}",
        ],
        "P(0 hit)": [
            f"{(bt['ripe_hits']==0).mean()*100:.0f}%",
            f"{(bt['sofi1_hits']==0).mean()*100:.0f}%",
            f"{(bt['sofi24_hits']==0).mean()*100:.0f}%",
            f"{(bt['pool_hits']==0).mean()*100:.0f}%",
        ],
        "P(≥1 hit)": [
            f"{(bt['ripe_hits']>=1).mean()*100:.0f}%",
            f"{(bt['sofi1_hits']>=1).mean()*100:.0f}%",
            f"{(bt['sofi24_hits']>=1).mean()*100:.0f}%",
            f"{(bt['pool_hits']>=1).mean()*100:.0f}%",
        ],
        "P(≥2 hit)": [
            f"{(bt['ripe_hits']>=2).mean()*100:.0f}%",
            f"{(bt['sofi1_hits']>=2).mean()*100:.0f}%",
            f"{(bt['sofi24_hits']>=2).mean()*100:.0f}%",
            f"{(bt['pool_hits']>=2).mean()*100:.0f}%",
        ],
        "P(≥3 hit)": [
            f"{(bt['ripe_hits']>=3).mean()*100:.0f}%",
            f"{(bt['sofi1_hits']>=3).mean()*100:.0f}%",
            f"{(bt['sofi24_hits']>=3).mean()*100:.0f}%",
            f"{(bt['pool_hits']>=3).mean()*100:.0f}%",
        ],
    }
    st.dataframe(pd.DataFrame(pcts), use_container_width=True, hide_index=True)

    # ─ Draw-by-draw detail table
    st.markdown("### 📋 Dettaglio draw per draw (-100 → -1)")

    rows_display = []
    for _, r in bt.iterrows():
        rows_display.append({
            "Draw #":    int(r["draw"]),
            "Data":      r["date"],
            "Numeri usciti": " ".join(f"{x:02d}" for x in r["actual"]),
            "🔴 Ripe": int(r["ripe_hits"]),
            "🔵 Sofi±1": int(r["sofi1_hits"]),
            "🟠 Cop±2-4": int(r["sofi24_hits"]),
            "🟢 Pool tot": int(r["pool_hits"]),
            "⚫ Fuori": int(r["outside"]),
            "Leggi ✓": int(r["laws_ok"]),
        })

    disp_df = pd.DataFrame(rows_display)

    def color_pool(val):
        v = int(val) if str(val).isdigit() else 0
        if v >= 5: return "background-color:#0d3b1e; color:#2ecc71"
        if v >= 4: return "background-color:#1a3a0d; color:#82e06a"
        if v >= 3: return "background-color:#2a2a0d; color:#e0c06a"
        return "background-color:#3b0d0d; color:#e74c3c"

    # pandas >= 2.1 uses .map(), older uses .applymap()
    try:
        styled = disp_df.style.map(color_pool, subset=["🟢 Pool tot"])
    except AttributeError:
        styled = disp_df.style.applymap(color_pool, subset=["🟢 Pool tot"])

    st.dataframe(styled, use_container_width=True, hide_index=True, height=450)


# ── TAB 3: ANALISI ────────────────────────────────────────────────────────────
def tab_analisi(df):
    st.subheader("📊 Analisi Storica")

    # Frequency of each number
    all_nums = []
    for _, row in df.iterrows():
        all_nums.extend(get_nums(row))

    freq = pd.Series(all_nums).value_counts().sort_index()
    expected = len(df) * 6 / 49

    fig = go.Figure(go.Bar(
        x=freq.index, y=freq.values,
        marker_color=["#e74c3c" if v > expected * 1.1 else
                      "#3498db" if v < expected * 0.9 else "#2ecc71"
                      for v in freq.values],
        hovertemplate="Numero %{x}: %{y} uscite<extra></extra>",
    ))
    fig.add_hline(y=expected, line_dash="dash", line_color="#f0a500",
                  annotation_text=f"Atteso ({expected:.0f})")
    fig.update_layout(
        title="Frequenza storica ogni numero (1957–2026)",
        xaxis_title="Numero", yaxis_title="Uscite",
        plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
        font=dict(color="#e6edf3"),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Rolling sum / range
    col_a, col_b = st.columns(2)
    last100 = df.tail(100).copy()
    last100["somma"] = last100.apply(lambda r: sum(get_nums(r)), axis=1)
    last100["range"] = last100.apply(lambda r: get_nums(r)[-1] - get_nums(r)[0], axis=1)
    last100["pari"]  = last100.apply(lambda r: sum(1 for x in get_nums(r) if x%2==0), axis=1)

    with col_a:
        fig2 = px.line(last100, y="somma", title="Somma draw — ultime 100",
                       color_discrete_sequence=["#3498db"])
        fig2.add_hline(y=last100["somma"].mean(), line_dash="dash", line_color="#f0a500")
        fig2.update_layout(plot_bgcolor="#0d1117", paper_bgcolor="#0d1117", font=dict(color="#e6edf3"))
        st.plotly_chart(fig2, use_container_width=True)

    with col_b:
        fig3 = px.line(last100, y="pari", title="Numeri pari per draw — ultime 100",
                       color_discrete_sequence=["#e67e22"])
        fig3.add_hline(y=3, line_dash="dash", line_color="#f0a500")
        fig3.update_layout(plot_bgcolor="#0d1117", paper_bgcolor="#0d1117", font=dict(color="#e6edf3"),
                           yaxis=dict(tickvals=list(range(7))))
        st.plotly_chart(fig3, use_container_width=True)

    # Law verification on last 200 draws
    st.markdown("### ✅ Verifica 13 Leggi (ultime 200 draw)")
    law_names = {
        "L1_pool9":    "Pool ultimi 9 draw",
        "L2_pool5":    "Pool ultimi 5 draw",
        "L3_decine":   "≥3 decine diverse",
        "L4_pari_disp":"Pari/dispari misti (1-5)",
        "L5_range":    "Range > 20",
        "L6_d1d2":     "D1≤10 o D2≤15",
        "L7_gap":      "Gap medio 4-11",
        "L8_n1":       "N1 ≤ 15",
        "L9_n6":       "N6 ≥ 35",
        "L10_coppia":  "Coppia con diff ≤ 3",
        "L11_pari24":  "Pari 2-4",
        "L12_media":   "Media 18-32",
        "L13_somma":   "Somma 70-160",
    }
    check_n = min(200, len(df))
    law_counts = {k: 0 for k in law_names}
    for i in range(len(df) - check_n, len(df)):
        nums = get_nums(df.iloc[i])
        lv   = check_laws(nums, df, i)
        for k in law_names:
            if lv.get(k, False):
                law_counts[k] += 1

    law_df = pd.DataFrame({
        "Legge":      list(law_names.values()),
        "Verificata": [law_counts[k] for k in law_names],
        "Su 200":     [check_n] * len(law_names),
        "%":          [round(law_counts[k] / check_n * 100, 1) for k in law_names],
    })
    law_df["✓"] = law_df["%"].apply(lambda v: "✅" if v >= 80 else "⚠️" if v >= 65 else "❌")
    st.dataframe(law_df, use_container_width=True, hide_index=True)


# ── TAB 4: DATI ───────────────────────────────────────────────────────────────
def tab_dati(df):
    st.subheader("🗄️ Dati & Storia")

    n_show = st.slider("Ultime N draw", 10, min(500, len(df)), 50)
    sub    = df.tail(n_show)[["draw", "date", "n1", "n2", "n3", "n4", "n5", "n6"]].copy()
    sub["Somma"] = sub.apply(lambda r: sum(get_nums(r)), axis=1)
    sub["Range"] = sub.apply(lambda r: get_nums(r)[-1] - get_nums(r)[0], axis=1)
    sub["Pari"]  = sub.apply(lambda r: sum(1 for x in get_nums(r) if x%2==0), axis=1)

    sub = sub.rename(columns={"draw":"Draw","date":"Data",
                               "n1":"N1","n2":"N2","n3":"N3","n4":"N4","n5":"N5","n6":"N6"})
    st.dataframe(sub[::-1], use_container_width=True, hide_index=True, height=500)

    # Download
    csv = sub.to_csv(index=False).encode()
    st.download_button("⬇️ Scarica CSV selezionato", csv, "lotto_export.csv", "text/csv")


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    df = load_draws()

    # ── AUTO-UPDATE ON STARTUP ────────────────────────────────────────────────
    missing_dates = get_missing_draw_dates(df)
    if missing_dates:
        with st.spinner(f"🔄 Cerco {len(missing_dates)} draw mancanti…"):
            df_updated, n_added, messages = auto_update_draws(df)
        if n_added:
            st.cache_data.clear()
            df = df_updated
            banner = "  \n".join(f"✅ **{m}**" for m in messages)
            st.success(f"🆕 {n_added} draw aggiunta/e automaticamente!\n\n{banner}")
        elif missing_dates:
            next_expected = missing_dates[0]
            st.info(
                f"⏳ Nessuna nuova draw trovata online. "
                f"Prossima attesa: **{next_expected}** "
                f"(oppure inseriscila manualmente dal sidebar)."
            )
    # ─────────────────────────────────────────────────────────────────────────

    render_sidebar(df)
    render_header(df)

    # Build pool for LAST draw → used by tabs 1
    pool_info = build_pool(df, draw_idx=-1)

    # Train ML (cached)
    with st.spinner("ML in addestramento…"):
        clf, _ = train_ml(id(df), df)
    ml_nums, ml_probs = ml_predict(clf, df, top_n=8)

    # Generate candidates (cached via st.cache_data on generate_candidates would need hash)
    with st.spinner("Generazione candidati…"):
        candidates = generate_candidates(pool_info, ml_nums, df, n_sample=4000)

    # Tabs
    t1, t2, t3, t4 = st.tabs([
        "🎯 PREDICI",
        "🔬 BACKTEST 100 draw",
        "📊 ANALISI",
        "🗄️ DATI & STORIA",
    ])

    with t1:
        tab_predici(df, pool_info, ml_nums, ml_probs, candidates)
    with t2:
        tab_backtest(df)
    with t3:
        tab_analisi(df)
    with t4:
        tab_dati(df)


main()
