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
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.multioutput import MultiOutputClassifier
import requests, re
from datetime import date, timedelta
import warnings
warnings.filterwarnings("ignore")

st.set_page_config(page_title="Magic Dream — App 1", page_icon="🎯", layout="wide",
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_HEADERS_JSON = {**_HEADERS, "Accept": "application/json, text/plain, */*"}


def _valid_6(nums) -> list | None:
    """Return sorted valid lotto draw or None."""
    if not nums or len(nums) < 6:
        return None
    s = sorted(set(int(x) for x in nums if 1 <= int(x) <= 49))
    if len(s) == 6:
        return s
    return None


def _extract_lotto_nums(html: str):
    """Try multiple parsing strategies to extract 6 valid lotto numbers from HTML/JSON."""
    import json as _json

    # Strategy 1: full JSON parse — look for "results", "numbers", "wyniki" keys
    for chunk in re.findall(r'\{[^{}]{30,2000}\}', html):
        try:
            obj = _json.loads(chunk)
            for key in ("results", "numbers", "wyniki", "balls", "losowania", "drawn"):
                if key in obj:
                    v = obj[key]
                    if isinstance(v, list):
                        r = _valid_6(v)
                        if r:
                            return r
        except Exception:
            pass

    # Strategy 2: JSON array of exactly 6 numbers 1-49
    json_pattern = re.compile(r'\[(\s*\d+\s*(?:,\s*\d+\s*){5})\]')
    for m in json_pattern.finditer(html):
        parts = [int(x) for x in m.group(1).split(",")]
        r = _valid_6(parts)
        if r:
            return r

    # Strategy 3: HTML ball/number elements (classes or data-attributes)
    for pat in [
        re.compile(r'data-(?:number|value|ball|result)="(\d{1,2})"', re.I),
        re.compile(
            r'class="[^"]*(?:ball|liczba|lotto-ball|result-ball|result-number|number|kula)[^"]*"'
            r'[^>]*>\s*(\d{1,2})\s*<', re.I),
        re.compile(r'<(?:span|div|li|td)[^>]*>\s*(\d{1,2})\s*</(?:span|div|li|td)>', re.I),
    ]:
        nums = []
        for m in pat.finditer(html):
            n = int(m.group(1))
            if 1 <= n <= 49 and n not in nums:
                nums.append(n)
            if len(nums) >= 6:
                r = _valid_6(nums[:6])
                if r:
                    return r
                nums = nums[1:]

    # Strategy 4: wynikilotto.net.pl specific — table cells in sequence
    tds = re.findall(r'<td[^>]*>\s*(\d{1,2})\s*</td>', html, re.I)
    for i in range(len(tds) - 5):
        candidate = [int(tds[i + j]) for j in range(6)]
        r = _valid_6(candidate)
        if r:
            return r

    # Strategy 5: fallback sliding window (relaxed range check ≥ 10)
    all_nums = [int(x) for x in re.findall(r'\b([1-9]|[1-4]\d)\b', html)]
    window = []
    for n in all_nums:
        if n not in window:
            window.append(n)
        if len(window) == 6:
            s = sorted(window)
            if s[-1] - s[0] >= 10 and s[5] <= 49:
                return s
            window.pop(0)

    return None


def _fetch_lotto_pl_api(draw_date_str: str):
    """Try lotto.pl official JSON API endpoints. Returns sorted list[int] or None."""
    import json as _json
    y, m, d = draw_date_str[:4], draw_date_str[5:7], draw_date_str[8:10]
    api_urls = [
        f"https://www.lotto.pl/api/lotteries/draw-results/by-date?game=Lotto&drawDate={y}-{m}-{d}",
        f"https://www.lotto.pl/api/lotteries/draw-results/by-date?game=Lotto&drawDate={y}{m}{d}",
        f"https://www.lotto.pl/lotto/wyniki-i-wygrane/wyniki-losowania/{y}-{m}-{d}",
    ]
    for url in api_urls:
        try:
            r = requests.get(url, headers=_HEADERS_JSON, timeout=12)
            if r.status_code != 200:
                continue
            # Try JSON parse first
            try:
                data = r.json()
                # lotto.pl API typically returns {"results": [...], "numbers": [...]}
                for key in ("numbers", "results", "wyniki", "balls", "drawn"):
                    v = data.get(key) if isinstance(data, dict) else None
                    if v and isinstance(v, list):
                        res = _valid_6(v)
                        if res:
                            return res
                # nested: data["items"][0]["results"]
                if isinstance(data, dict):
                    items = data.get("items") or data.get("draws") or data.get("data") or []
                    if isinstance(items, list) and items:
                        first = items[0]
                        if isinstance(first, dict):
                            for key in ("numbers", "results", "wyniki", "balls"):
                                v = first.get(key)
                                if v and isinstance(v, list):
                                    res = _valid_6(v)
                                    if res:
                                        return res
            except Exception:
                pass
            # Fallback: HTML parse
            res = _extract_lotto_nums(r.text)
            if res:
                return res
        except Exception:
            continue
    return None


def fetch_draw_for_date(draw_date_str: str):
    """
    Fetch 6 Kumulacja numbers for a given date (YYYY-MM-DD).
    Tries lotto.pl API first, then multiple Polish result sites.
    Returns sorted list[int] or None.
    """
    y, m, d = draw_date_str[:4], draw_date_str[5:7], draw_date_str[8:10]

    # 1) lotto.pl official API
    res = _fetch_lotto_pl_api(draw_date_str)
    if res:
        return res

    # 2) HTML scraping fallback sites
    urls = [
        f"https://www.wynikilotto.net.pl/lotto/wyniki/{y}/{m}/{d}/",
        f"https://wynikilotto.net.pl/wyniki-lotto/{y}-{m}-{d}/",
        f"https://pewniaki.pl/wyniki-lotto/{y}-{m}-{d}/",
        f"https://totalniaki.pl/wyniki-lotto/{y}-{m}-{d}/",
        f"https://lotto24.pl/wyniki-lotto/{y}-{m}-{d}/",
        f"https://lotto.org.pl/lotto/{y}/{m}/{d}/",
    ]
    for url in urls:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=12)
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
        show_debug = st.checkbox("🐛 Mostra dettagli fetch", value=False, key="fetch_debug")
        if st.button("🔍 Cerca ora", use_container_width=True):
            missing = get_missing_draw_dates(df)
            if not missing:
                st.success("✅ Database già aggiornato!")
            else:
                with st.spinner(f"Cerco {len(missing)} draw…"):
                    df_up, n_added, messages = auto_update_draws(df)
                if n_added:
                    for msg in messages:
                        st.success(msg)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.warning(
                        f"⚠️ Nessuna trovata online per: {', '.join(missing)}\n\n"
                        "Inseriscile manualmente sopra."
                    )
                    if show_debug:
                        y, mo, d_str = missing[0][:4], missing[0][5:7], missing[0][8:10]
                        st.markdown("**Siti testati:**")
                        test_urls = [
                            f"https://www.lotto.pl/api/lotteries/draw-results/by-date?game=Lotto&drawDate={missing[0]}",
                            f"https://www.wynikilotto.net.pl/lotto/wyniki/{y}/{mo}/{d_str}/",
                            f"https://pewniaki.pl/wyniki-lotto/{missing[0]}/",
                            f"https://totalniaki.pl/wyniki-lotto/{missing[0]}/",
                        ]
                        for tu in test_urls:
                            try:
                                tr = requests.get(tu, headers=_HEADERS_JSON, timeout=8)
                                st.code(f"{tr.status_code} — {tu}", language="")
                            except Exception as e:
                                st.code(f"ERR {e} — {tu}", language="")

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


# ── TAB 5: LABORATORIO ───────────────────────────────────────────────────────
def tab_laboratorio(df):
    st.subheader("🧪 Laboratorio Pattern — Analisi N-1 → N (zero data leakage)")
    st.caption(
        "Il laboratorio usa SOLO dati fino alla penultima draw (N-1). "
        "La draw N è mostrata solo alla fine per verifica. Nessun aggiornamento al database."
    )

    if len(df) < 30:
        st.warning("Servono almeno 30 draw nel database.")
        return

    N_idx  = len(df) - 1   # ultima draw = risultato reale da confrontare
    N1_idx = len(df) - 2   # penultima = base del laboratorio

    draw_N  = get_nums(df.iloc[N_idx])
    draw_N1 = get_nums(df.iloc[N1_idx])
    info_N  = df.iloc[N_idx]
    info_N1 = df.iloc[N1_idx]

    # Header: mostra le due draw
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(f"**🔵 Draw N-1** (base) &nbsp; #{int(info_N1['draw'])} · {str(info_N1['date'])[:10]}")
        st.markdown("".join(ball_html(n, "sofi1") for n in draw_N1), unsafe_allow_html=True)
    with col_b:
        st.markdown(f"**🔴 Draw N** (risultato reale) &nbsp; #{int(info_N['draw'])} · {str(info_N['date'])[:10]}")
        st.markdown("".join(ball_html(n, "ripe") for n in draw_N), unsafe_allow_html=True)

    st.markdown("---")

    # Finestra storica: 100 draw FINO a N-1 inclusa
    hist_start = max(0, N1_idx - 100)
    hist = df.iloc[hist_start : N1_idx + 1].reset_index(drop=True)

    # ══════════════════════════════════════════════════════════════════════════
    # ANALISI 1 — Effetto giorno del mese
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("📅 Analisi 1 — Effetto Giorno del Mese", expanded=True):
        scores_1 = {n: 0.0 for n in range(1, 50)}
        try:
            day_N = pd.to_datetime(info_N["date"]).day
        except Exception:
            day_N = None

        if day_N:
            near_range = 2
            near_N = set(range(max(1, day_N - near_range), min(50, day_N + near_range + 1)))

            day_rows = []
            for _, row in hist.iterrows():
                try:
                    dom = pd.to_datetime(row["date"]).day
                except Exception:
                    continue
                nums = set(get_nums(row))
                near = set(range(max(1, dom - near_range), min(50, dom + near_range + 1)))
                exp  = len(near) * 6 / 49
                hits = len(nums & near)
                day_rows.append({"day": dom, "hits": hits, "expected": exp,
                                  "excess": hits - exp})

            da_df = pd.DataFrame(day_rows)
            if not da_df.empty:
                avg_h  = da_df["hits"].mean()
                avg_ex = da_df["expected"].mean()
                pct_ok = (da_df["hits"] >= da_df["expected"]).mean() * 100

                m1, m2, m3 = st.columns(3)
                m1.metric("Hit medi vicino giorno", f"{avg_h:.2f}")
                m2.metric("Atteso (casuale)", f"{avg_ex:.2f}")
                m3.metric("% draw con ≥ atteso", f"{pct_ok:.0f}%")

                st.markdown(f"**Giorno draw N = {day_N}** → numeri vicini: `{sorted(near_N)}`")

                # Score: proximity to day_N
                for n in range(1, 50):
                    dist = abs(n - day_N)
                    if dist <= near_range:
                        scores_1[n] = float(near_range + 1 - dist)

                # Chart: excess by day-of-month
                exc = da_df.groupby("day")["excess"].mean().reset_index()
                fig1 = go.Figure(go.Bar(
                    x=exc["day"], y=exc["excess"],
                    marker_color=["#2ecc71" if v >= 0 else "#e74c3c" for v in exc["excess"]],
                ))
                fig1.add_hline(y=0, line_dash="dash", line_color="#f0a500")
                fig1.update_layout(
                    title="Eccesso hit vicino al giorno (storico)",
                    xaxis_title="Giorno del mese", yaxis_title="Hit − Atteso",
                    plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
                    font=dict(color="#e6edf3"), showlegend=False,
                )
                st.plotly_chart(fig1, use_container_width=True)
        else:
            st.warning("Date non disponibili per questa analisi.")

    # ══════════════════════════════════════════════════════════════════════════
    # ANALISI 2 — Differenze posizionali tra sestine consecutive
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("📐 Analisi 2 — Differenze Posizionali Consecutive", expanded=True):
        delta_rows = []
        for i in range(len(hist) - 1):
            prev_n = get_nums(hist.iloc[i])
            curr_n = get_nums(hist.iloc[i + 1])
            row = {}
            for k in range(6):
                row[f"D{k+1}"] = curr_n[k] - prev_n[k]
            delta_rows.append(row)

        delta_df = pd.DataFrame(delta_rows)
        scores_2 = {n: 0.0 for n in range(1, 50)}

        if not delta_df.empty:
            pos_table = []
            for k in range(6):
                col = f"D{k+1}"
                mean_d = delta_df[col].mean()
                std_d  = delta_df[col].std()
                pct_p  = (delta_df[col] > 0).mean()
                pct_e  = (delta_df[col] % 2 == 0).mean()
                pred_v = max(1, min(49, int(round(draw_N1[k] + mean_d))))
                pos_table.append({
                    "Pos": f"N{k+1}", "N-1": draw_N1[k],
                    "Media Δ": round(mean_d, 2), "Std Δ": round(std_d, 2),
                    "% ↑": f"{pct_p*100:.0f}%", "% pari": f"{pct_e*100:.0f}%",
                    "Predetto": pred_v,
                })
                # Score window around prediction
                pred_f = draw_N1[k] + mean_d
                for n in range(1, 50):
                    dist = abs(n - pred_f)
                    if dist <= max(1, std_d):
                        scores_2[n] += max(0.0, 1.0 - dist / (std_d + 1))

            st.dataframe(pd.DataFrame(pos_table), use_container_width=True, hide_index=True)

            # Boxplot
            fig2 = go.Figure()
            colors = ["#e74c3c", "#3498db", "#2ecc71", "#f0a500", "#9b59b6", "#1abc9c"]
            for k in range(6):
                fig2.add_trace(go.Box(
                    y=delta_df[f"D{k+1}"], name=f"N{k+1}",
                    marker_color=colors[k], boxmean=True,
                ))
            fig2.update_layout(
                title="Distribuzione Δ per posizione (100 draw)",
                yaxis_title="Δ vs draw precedente",
                plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
                font=dict(color="#e6edf3"),
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.warning("Dati insufficienti.")

    # ══════════════════════════════════════════════════════════════════════════
    # ANALISI 3 — Pattern parità e differenza inter-sestina
    # ══════════════════════════════════════════════════════════════════════════
    with st.expander("🔢 Analisi 3 — Pattern Parità e Finestre ±5 / ±10", expanded=True):
        par_rows = []
        for i in range(len(hist) - 1):
            prev_n = get_nums(hist.iloc[i])
            curr_n = get_nums(hist.iloc[i + 1])
            for k in range(6):
                d = curr_n[k] - prev_n[k]
                par_rows.append({
                    "pos": k + 1, "delta": d,
                    "even": d % 2 == 0,
                    "w5":   abs(d) <= 5,
                    "w10":  abs(d) <= 10,
                    "up":   d > 0,
                })

        par_df = pd.DataFrame(par_rows)
        scores_3 = {n: 0.0 for n in range(1, 50)}

        if not par_df.empty:
            par_table = []
            for k in range(6):
                sub = par_df[par_df["pos"] == k + 1]
                pct_e   = sub["even"].mean()
                pct_w5  = sub["w5"].mean()
                pct_w10 = sub["w10"].mean()
                pct_up  = sub["up"].mean()
                mean_d  = sub["delta"].mean()
                par_table.append({
                    "Pos": f"N{k+1}", "N-1": draw_N1[k],
                    "% Δ pari": f"{pct_e*100:.0f}%",
                    "% |Δ|≤5":  f"{pct_w5*100:.0f}%",
                    "% |Δ|≤10": f"{pct_w10*100:.0f}%",
                    "% crescente": f"{pct_up*100:.0f}%",
                    "Media Δ": round(mean_d, 2),
                })
                base = draw_N1[k]
                for n in range(1, 50):
                    d = abs(n - base)
                    if d <= 5:
                        scores_3[n] += pct_w5 * 2.0
                    elif d <= 10:
                        scores_3[n] += pct_w10 * 1.0

            st.dataframe(pd.DataFrame(par_table), use_container_width=True, hide_index=True)

            g1, g2, g3, g4 = st.columns(4)
            g1.metric("% Δ pari", f"{par_df['even'].mean()*100:.0f}%")
            g2.metric("% |Δ|≤5",  f"{par_df['w5'].mean()*100:.0f}%")
            g3.metric("% |Δ|≤10", f"{par_df['w10'].mean()*100:.0f}%")
            g4.metric("% crescente", f"{par_df['up'].mean()*100:.0f}%")

            # Sign heatmap (last 50 pairs)
            sign_mat = []
            for i in range(len(hist) - 1):
                pn = get_nums(hist.iloc[i])
                cn = get_nums(hist.iloc[i + 1])
                sign_mat.append([1 if cn[k] > pn[k] else (-1 if cn[k] < pn[k] else 0) for k in range(6)])
            sign_arr = np.array(sign_mat[-50:])
            fig3 = go.Figure(go.Heatmap(
                z=sign_arr,
                colorscale=[[0, "#e74c3c"], [0.5, "#2c3e50"], [1, "#2ecc71"]],
                zmid=0, xgaps=1, ygaps=1,
                x=[f"N{k+1}" for k in range(6)],
                hovertemplate="Draw %{y} · N%{x}: %{z}<extra></extra>",
            ))
            fig3.update_layout(
                title="Segno Δ per posizione — ultime 50 draw (🟢=+, 🔴=−)",
                plot_bgcolor="#0d1117", paper_bgcolor="#0d1117",
                font=dict(color="#e6edf3"),
            )
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.warning("Dati insufficienti.")

    # ══════════════════════════════════════════════════════════════════════════
    # OUTPUT FINALE — verifica su N e previsione N+1
    # ══════════════════════════════════════════════════════════════════════════
    st.markdown("---")
    st.subheader("🎯 Output Finale del Laboratorio")

    def _lab_build_sestina(base_nums, sc1, sc2, sc3, df_ref, idx_ref):
        """Combine 3 scores and pick best law-passing sestina from top-15."""
        total = {}
        for n in range(1, 50):
            total[n] = sc1.get(n, 0) * 1.0 + sc2.get(n, 0) * 2.0 + sc3.get(n, 0) * 2.0
        ranked = sorted(total.items(), key=lambda x: -x[1])
        pool15 = [n for n, _ in ranked[:15]]

        best, best_sc = None, -9999
        tried = 0
        for combo in combinations(pool15, 6):
            tried += 1
            if tried > 3000:
                break
            nums = list(combo)
            lp, lt = laws_pass_count(nums, df_ref, idx_ref)
            if lp < 9:
                continue
            sc = sum(total.get(n, 0) for n in nums) + lp * 0.5
            if sc > best_sc:
                best_sc, best = sc, sorted(nums)

        if best is None:
            best = sorted([n for n, _ in ranked[:6]])
        return best, total, ranked

    # ── Previsione per draw N (verifica)
    sestina_N, total_N, ranked_N = _lab_build_sestina(
        draw_N1, scores_1, scores_2, scores_3,
        df.iloc[: N1_idx + 1], N1_idx,
    )
    hits_N = sorted(set(sestina_N) & set(draw_N))

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Previsione laboratorio per draw #{int(info_N['draw'])}** (usando solo dati ≤ N-1)")
        balls_pred = ""
        for n in sestina_N:
            cls = "sofi1" if n in set(draw_N) else "out"
            balls_pred += ball_html(n, cls)
        st.markdown(balls_pred, unsafe_allow_html=True)

    with col2:
        st.markdown(f"**Risultato reale draw #{int(info_N['draw'])}**")
        balls_real = ""
        for n in draw_N:
            cls = "ripe" if n in set(sestina_N) else "sofi2"
            balls_real += ball_html(n, cls)
        st.markdown(balls_real, unsafe_allow_html=True)

    h = len(hits_N)
    color = "#2ecc71" if h >= 3 else "#f0a500" if h >= 2 else "#e74c3c"
    st.markdown(f"""
    <div style="background:#161b22;border:2px solid {color};border-radius:10px;
                padding:1rem 2rem;text-align:center;margin:1rem 0;">
      <div style="font-size:2rem;color:{color};font-weight:800">{h}/6 indovinati</div>
      <div style="color:#8b949e">
        {"Numeri comuni: " + " ".join(f"{n:02d}" for n in hits_N) if hits_N else "Nessun numero comune"}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Previsione N+1
    st.markdown("---")
    nx_draw_num = int(info_N["draw"]) + 1
    st.subheader(f"🔮 Previsione Draw #{nx_draw_num} (in arrivo)")

    # Rebuild scores using draw_N as base
    sc1_next = {n: 0.0 for n in range(1, 50)}
    sc2_next = {n: 0.0 for n in range(1, 50)}
    sc3_next = {n: 0.0 for n in range(1, 50)}

    # Score 1: day of next expected draw
    try:
        date_N_dt = pd.to_datetime(info_N["date"]).date()
        nxt_date = date_N_dt + timedelta(days=1)
        while nxt_date.weekday() not in _DRAW_WEEKDAYS:
            nxt_date += timedelta(days=1)
        day_next = nxt_date.day
        for n in range(1, 50):
            dist = abs(n - day_next)
            if dist <= 2:
                sc1_next[n] = float(3 - dist)
    except Exception:
        pass

    # Score 2: apply mean deltas to draw_N
    if not delta_df.empty:
        for k in range(6):
            mean_d = delta_df[f"D{k+1}"].mean()
            std_d  = delta_df[f"D{k+1}"].std()
            pred_f = draw_N[k] + mean_d
            for n in range(1, 50):
                dist = abs(n - pred_f)
                if dist <= max(1, std_d):
                    sc2_next[n] += max(0.0, 1.0 - dist / (std_d + 1))

    # Score 3: ±5/±10 windows around draw_N
    if not par_df.empty:
        for k in range(6):
            sub = par_df[par_df["pos"] == k + 1]
            pct_w5  = sub["w5"].mean()
            pct_w10 = sub["w10"].mean()
            base = draw_N[k]
            for n in range(1, 50):
                d = abs(n - base)
                if d <= 5:
                    sc3_next[n] += pct_w5 * 2.0
                elif d <= 10:
                    sc3_next[n] += pct_w10 * 1.0

    sestina_next, total_next, ranked_next = _lab_build_sestina(
        draw_N, sc1_next, sc2_next, sc3_next, df, len(df) - 1,
    )

    pool_N = build_pool(df, draw_idx=-1)
    lp_next, _ = laws_pass_count(sestina_next, df, len(df) - 1)

    st.markdown(f"**Sestina laboratorio draw #{nx_draw_num}:**")
    balls_next_html = ""
    for n in sestina_next:
        if n in pool_N["ripetuti"]:   cls = "ripe"
        elif n in pool_N["soffi_1"]:  cls = "sofi1"
        elif n in pool_N["soffi_24"]: cls = "sofi2"
        else:                         cls = "ml"
        balls_next_html += ball_html(n, cls)
    st.markdown(balls_next_html, unsafe_allow_html=True)

    st.markdown(
        f"Leggi ✓: **{lp_next}/13** &nbsp;|&nbsp; "
        f"Score: **{sum(total_next.get(n,0) for n in sestina_next):.2f}**"
    )

    st.markdown("**Top-15 candidati (laboratorio):**")
    cands_html = ""
    for n, _ in ranked_next[:15]:
        if n in pool_N["ripetuti"]:   cls = "ripe"
        elif n in pool_N["soffi_1"]:  cls = "sofi1"
        elif n in pool_N["soffi_24"]: cls = "sofi2"
        else:                         cls = "ml"
        cands_html += ball_html(n, cls)
    st.markdown(cands_html, unsafe_allow_html=True)

    st.markdown("---")
    with st.expander("ℹ️ Logica di scoring combinato"):
        st.markdown(f"""
**Punteggio composito** per ogni numero 1-49:

| Analisi | Peso | Descrizione |
|---------|------|-------------|
| 📅 Giorno del mese | 1× | Prossimità al giorno del mese della prossima draw |
| 📐 Delta posizionale | 2× | Finestra attorno al valore N-1 + media storica dei delta |
| 🔢 Parità ±5/±10 | 2× | Probabilità storica che il numero rimanga entro ±5 o ±10 |

Filtro: reject sestine con < 9/13 leggi superate.
Top-15 candidati → enumerate combinazioni → seleziona score max.
        """)


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


# ── TAB 6: STORICO STRATEGIE (Magic Lab) ─────────────────────────────────────
def tab_storico_strategie():
    st.subheader("📈 Storico Strategie — confronto draw per draw")
    st.caption(
        "Dati prodotti da Magic Lab (magic_experiment_lab.py). "
        "Ogni riga = una draw. Ogni colonna = hit_t0 di quella strategia al draw T+0."
    )

    # Try to find magic_lab relative to this file
    _here = Path(__file__).resolve().parent
    for _candidate in [_here / "../../magic_lab", _here / "../magic_lab", _here / "magic_lab"]:
        _lab_dir = _candidate.resolve()
        if _lab_dir.exists():
            break
    else:
        _lab_dir = None

    _cmp_path = (_lab_dir / "latest_strategy_comparison.csv") if _lab_dir else None
    _det_path = (_lab_dir / "latest_backtest_detail.csv")    if _lab_dir else None

    @st.cache_data(ttl=120, show_spinner=False)
    def _load(p: str) -> pd.DataFrame:
        try:
            return pd.read_csv(p)
        except Exception:
            return pd.DataFrame()

    if _cmp_path is None or not _cmp_path.exists():
        st.warning(
            "⏳ Magic Lab non ha ancora prodotto i dati storico.\n\n"
            "Attendi il primo ciclo di Magic Dream (3-5 min)."
        )
        return

    cmp = _load(str(_cmp_path))
    if cmp.empty:
        st.warning("⏳ Nessun dato disponibile.")
        return

    strat_cols = [c for c in cmp.columns if c not in ("draw", "vincitore", "max_hit")]

    if "vincitore" in cmp.columns:
        win_counts = cmp["vincitore"].value_counts().rename_axis("Strategia").reset_index(name="Vittorie")
        win_counts = win_counts.sort_values("Vittorie", ascending=False)
        st.markdown("### Vittorie per strategia")
        wA, wB = st.columns([2, 1])
        with wA:
            fig_w = px.bar(win_counts, x="Strategia", y="Vittorie",
                           color="Strategia", title="Quante draw ha vinto ogni strategia")
            st.plotly_chart(fig_w, use_container_width=True)
        with wB:
            st.dataframe(win_counts, use_container_width=True, hide_index=True)

    st.markdown("---")

    if "max_hit" in cmp.columns:
        dist = cmp["max_hit"].value_counts().sort_index().rename_axis("Hit max").reset_index(name="Draw")
        total = len(cmp)
        dA, dB = st.columns([2, 1])
        with dA:
            fig_d = px.bar(dist, x="Hit max", y="Draw", title="Distribuzione hit massimo per draw")
            st.plotly_chart(fig_d, use_container_width=True)
        with dB:
            st.markdown("**Frequenza hit massimi**")
            for _, r in dist.iterrows():
                h = int(r["Hit max"])
                n = int(r["Draw"])
                pct = n / total * 100
                tag = " 🔥" if h >= 5 else ""
                st.markdown(f"Hit = **{h}**{tag}: {n} draw ({pct:.1f}%)")

    st.markdown("---")

    n_show = st.slider("Draw da mostrare (più recenti)", 50, min(2000, len(cmp)), min(500, len(cmp)), 50)
    show = cmp.sort_values("draw", ascending=False).head(n_show).copy()

    def _color(val):
        try:
            v = int(val)
        except Exception:
            return ""
        if v >= 5:
            return "background-color:#7f1d1d; color:#fca5a5; font-weight:700"
        if v == 4:
            return "background-color:#1e3a5f; color:#93c5fd; font-weight:700"
        if v == 3:
            return "background-color:#1e4a2e; color:#86efac"
        return ""

    sc = [c for c in strat_cols if c in show.columns]
    st.dataframe(show.style.applymap(_color, subset=sc), use_container_width=True, hide_index=True)

    if _det_path and _det_path.exists():
        with st.expander("Dettaglio completo draw × strategia", expanded=False):
            det = _load(str(_det_path))
            if not det.empty:
                st.dataframe(det.tail(3000), use_container_width=True, hide_index=True)


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
    t1, t2, t3, t4, t5, t6 = st.tabs([
        "🎯 PREDICI",
        "🔬 BACKTEST 100 draw",
        "📊 ANALISI",
        "🗄️ DATI & STORIA",
        "🧪 LABORATORIO",
        "📈 STORICO STRATEGIE",
    ])

    with t1:
        tab_predici(df, pool_info, ml_nums, ml_probs, candidates)
    with t2:
        tab_backtest(df)
    with t3:
        tab_analisi(df)
    with t4:
        tab_dati(df)
    with t5:
        tab_laboratorio(df)
    with t6:
        tab_storico_strategie()


main()
