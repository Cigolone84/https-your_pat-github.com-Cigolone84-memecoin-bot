"""
IL_CONCETTO.xlsx — cambio di paradigma "ritorno al futuro".
Usa il MEGLIO delle 8 strategie per ogni draw (frequenza ~2%, non FreqHot8 debole).
Mostra: frequenza vera -> 73 ripetizioni -> finestra attuale con "mancano ancora N"
-> stasera = i posti che restano all'appello.
"""
import sys
from pathlib import Path
from collections import Counter
import argparse
import pandas as pd

sys.path.insert(0, "/home/user/https-your_pat-github.com-Cigolone84-memecoin-bot")

# ── Carica i dati reali nel formato di lab ──────────────────────────────────────
src = Path("/root/.claude/uploads/017b8930-ae2e-4f40-85ea-72c6574a83c6/bcb37b72-lotto_09.05_aggiornato_7350_1.xlsx")
df_raw = pd.read_excel(str(src), sheet_name="Lotto_NoPlus").dropna(subset=["n1","n2","n3","n4","n5","n6"])
for c in ["draw_id","n1","n2","n3","n4","n5","n6"]:
    df_raw[c] = df_raw[c].astype(int)
df_csv = df_raw[["draw_id","date","n1","n2","n3","n4","n5","n6"]].rename(columns={"draw_id":"draw"})
csv_out = Path("/tmp/lotto_reale.csv")
df_csv.to_csv(str(csv_out), index=False)

import magic_experiment_lab as lab
lab.DRAWS_CSV_PATH = csv_out
lab.BACKTEST_PATH  = Path("/nonexistent.xlsx")

df = lab.load_draws(limit=0)
print(f"Draw caricati: {len(df)}")

# mappa draw -> numeri reali
actual_by_draw = {}
for _, r in df.iterrows():
    a = r.get("actual")
    if isinstance(a, frozenset) and len(a) == 6:
        actual_by_draw[int(r["draw"])] = a

# ── Backtest col MEGLIO di tutte le 8 strategie (freq_window=120) ───────────────
FREQ_WIN = 120
WARMUP   = 120
print(f"Backtest 8 strategie (freq_window={FREQ_WIN})...")
bt = lab.run_backtest(df, warmup=WARMUP, freq_window=FREQ_WIN)

# per ogni draw: max hit tra le 8 strategie + candidati della migliore
per_draw = {}
for sname, df_s in bt.items():
    if df_s.empty:
        continue
    for _, row in df_s.iterrows():
        d = int(row["draw"])
        hit = int(row["hit_t0"]) if pd.notna(row.get("hit_t0")) else 0
        cands = str(row.get("candidates",""))
        per_draw.setdefault(d, {"hits":{}, "cands":{}})
        per_draw[d]["hits"][sname] = hit
        per_draw[d]["cands"][sname] = cands

draws_ordinati = sorted(d for d in per_draw if d in actual_by_draw)

# ── Costruisci la lista di previsioni (1 per draw) col MEGLIO ───────────────────
results = []
for d in draws_ordinati:
    hits = per_draw[d]["hits"]
    best_s = max(hits, key=hits.get) if hits else ""
    max_hit = hits.get(best_s, 0)
    cands = lab.parse_nums(per_draw[d]["cands"].get(best_s,""))
    actual = actual_by_draw[d]
    results.append({
        "draw": d,
        "previsione_8": " ".join(f"{n:02d}" for n in sorted(cands)),
        "strategia_migliore": best_s,
        "numeri_usciti": " ".join(f"{n:02d}" for n in sorted(actual)),
        "numeri_azzeccati": " ".join(f"{n:02d}" for n in sorted(cands & actual)),
        "n_azzeccati": max_hit,
        "esito_4plus": "GIUSTA (4+)" if max_hit >= 4 else "sbagliata",
    })

total = len(results)
n_giuste = sum(1 for r in results if r["n_azzeccati"] >= 4)
R = n_giuste / total if total else 0
print(f"Totale previsioni: {total}, GIUSTE (4+): {n_giuste}, frequenza R = {R*100:.3f}%")

# ── COLONNA "mancano_ancora": finestra mobile di 100 a ritroso ──────────────────
# Per ogni previsione, guardo le 100 che finiscono li (incluse) e calcolo:
#   attesi = round(R*100), giuste_finestra = quante 4+, mancano = max(0, attesi-giuste)
WIN = 100
attesi_100 = max(1, round(R * WIN))   # quante 4+ ci si aspetta in 100 (>=1)
for i in range(total):
    lo = max(0, i - WIN + 1)
    seg = results[lo:i + 1]
    g = sum(1 for r in seg if r["n_azzeccati"] >= 4)
    results[i]["giuste_ultime_100"] = g
    results[i]["attese_100"] = attesi_100
    results[i]["mancano_ancora"] = max(0, attesi_100 - g)
    # streak sbagliate fino a qui
    st = 0
    for r in reversed(seg):
        if r["n_azzeccati"] < 4: st += 1
        else: break
    results[i]["streak_sbagliate"] = st
print(f"Attesi per 100 = {attesi_100}")

# ── PASSO 2: le 73 ripetizioni ──────────────────────────────────────────────────
WIN = 100
N_FIN = total // WIN
fin_rows = []
for w in range(N_FIN):
    seg = results[w*WIN:(w+1)*WIN]
    g = [r for r in seg if r["n_azzeccati"] >= 4]
    conf = Counter()
    for r in g:
        for n in r["numeri_azzeccati"].split():
            conf[int(n)] += 1
    top4 = [str(n) for n,_ in conf.most_common(4)]
    fin_rows.append({
        "RIPETIZIONE #": w+1,
        "draw_inizio": seg[0]["draw"], "draw_fine": seg[-1]["draw"],
        "PREVISIONI": WIN, "SBAGLIATE": WIN-len(g), "GIUSTE (4+)": len(g),
        "numeri_nelle_giuste": " ".join(top4) if top4 else "(nessuna)",
    })
df_73 = pd.DataFrame(fin_rows)
media_hit = df_73["GIUSTE (4+)"].mean() if not df_73.empty else 0
n_con_hit = int((df_73["GIUSTE (4+)"] >= 1).sum()) if not df_73.empty else 0

# ── PASSO 3: finestra attuale (ultime 100) + "mancano ancora N" ─────────────────
ultime100 = results[-WIN:]
g_att = sum(1 for r in ultime100 if r["n_azzeccati"] >= 4)
attesi = R * WIN                      # quanti 4+ ci si aspetta in 100 previsioni
mancano = max(0, round(attesi) - g_att)  # quanti mancano all'appello

# streak finale di sbagliate
streak = 0
for r in reversed(ultime100):
    if r["n_azzeccati"] < 4: streak += 1
    else: break

# ── Numeri di stasera: consenso prossima previsione (8 strategie) ───────────────
ranking = lab.compute_cycle_summary(bt)
pred = lab.generate_next_predictions(df, FREQ_WIN, 8, ranking)
voti = Counter()
for _, row in pred.iterrows():
    for n in lab.parse_nums(str(row.get("Predizione",""))):
        voti[n] += 1
stasera_6 = sorted([n for n,_ in voti.most_common(6)])
stasera_4 = sorted([n for n,_ in voti.most_common(4)])
print(f"Finestra attuale: {g_att} giuste, attesi {attesi:.1f}, MANCANO ANCORA {mancano}, streak={streak}")
print(f"Stasera TOP4={stasera_4} TOP6={stasera_6}")

# ── Foglio IL_CONCETTO ───────────────────────────────────────────────────────────
righe = []
def sep(t): righe.append({"VOCE": t, "VALORE": ""})
def kv(k,v): righe.append({"VOCE": k, "VALORE": v})

sep("══════════ PASSO 1 — FREQUENZA (ritorno al futuro su tutta la storia) ══════════")
kv("Draw analizzati", total)
kv("Previsioni fatte (1 per draw, meglio di 8 strategie)", total)
kv("GIUSTE (4+ numeri)", n_giuste)
kv("SBAGLIATE", total - n_giuste)
kv("FREQUENZA R (4+ su 100 previsioni)", f"{R*100:.2f}%  ->  ~{R*WIN:.1f} ogni 100")
sep("")
sep("══════════ PASSO 2 — LE %d RIPETIZIONI (finestre di 100) ══════════" % N_FIN)
kv("Finestre con almeno 1 giusta", f"{n_con_hit}/{N_FIN}")
kv("Media giuste per finestra", f"{media_hit:.2f}")
kv("-> dettaglio nel foglio '73_Ripetizioni'", "")
sep("")
sep("══════════ PASSO 3 — FINESTRA ATTUALE (ultime 100 fino a stasera) ══════════")
kv("Previsioni nella finestra", WIN)
kv("GIUSTE gia' uscite", g_att)
kv("SBAGLIATE (le escludiamo)", WIN - g_att)
kv("ATTESE per frequenza (R x 100)", f"{attesi:.1f}")
kv(">>> MANCANO ANCORA ALL'APPELLO <<<", mancano)
kv("Streak finale sbagliate consecutive", streak)
kv("-> dettaglio nel foglio 'Ultime_100'", "")
sep("")
sep("══════════ PASSO 4 — STASERA NEL 2%: ESCLUSIONE COMPLETATA ══════════")
kv("PREVISIONI GIA' SBAGLIATE nella finestra (escluse)", WIN - g_att)
kv("GIUSTE GIA' USCITE nella finestra", g_att)
kv("ATTESE su 100 (R x 100)", f"{attesi:.1f}")
kv(">>> MANCANO ANCORA ALL'APPELLO <<<", mancano)
kv("Streak finale sbagliate consecutive", streak)
sep("")
kv("════ CONCLUSIONE ════", "")
kv(f"DATI SPERIMENTALI: {total} previsioni reali -> R = {R*100:.2f}%", "")
kv(f"FINESTRA ATTUALE: {WIN-g_att} escluse, {g_att} giuste", "")
kv(f"STASERA e' uno dei posti che MANCANO ANCORA ALL'APPELLO", "")
kv("▶▶▶  STASERA TOP 6:", " ".join(f"{n:02d}" for n in stasera_6))
kv("▶▶▶  STASERA TOP 4:", " ".join(f"{n:02d}" for n in stasera_4))
df_concetto = pd.DataFrame(righe)

# Foglio ultime 100
df_u = pd.DataFrame(ultime100)
df_u.insert(0, "n_in_finestra", range(1, len(df_u)+1))
df_u = pd.concat([df_u, pd.DataFrame([{
    "n_in_finestra":"STASERA","draw":"?",
    "previsione_8":" ".join(f"{n:02d}" for n in stasera_6),
    "strategia_migliore":"consenso 8 strategie",
    "numeri_usciti":"DA ESTRARRE","numeri_azzeccati":"← UNO DEI %d POSTI ALL'APPELLO" % mancano,
    "n_azzeccati":"?","esito_4plus":"CANDIDATA PER ESCLUSIONE",
}])], ignore_index=True)

# ── FOGLIO TUTTE LE PREVISIONI (il database completo) ──────────────────────────
df_tutte = pd.DataFrame(results)
df_tutte.insert(0, "n_previsione", range(1, len(df_tutte) + 1))
# ordina colonne in modo leggibile
cols = ["n_previsione","draw","previsione_8","strategia_migliore","numeri_usciti",
        "numeri_azzeccati","n_azzeccati","esito_4plus",
        "giuste_ultime_100","attese_100","mancano_ancora","streak_sbagliate"]
df_tutte = df_tutte[[c for c in cols if c in df_tutte.columns]]

out = Path("/home/user/https-your_pat-github.com-Cigolone84-memecoin-bot/IL_CONCETTO.xlsx")

# ── FOGLIO Solo_Le_Giuste: solo il 2% vincente ──────────────────────────────────
df_giuste = df_tutte[df_tutte["esito_4plus"] == "GIUSTA (4+)"].copy().reset_index(drop=True)
df_giuste.insert(0, "hit_numero", range(1, len(df_giuste)+1))

# numeri piu comuni nelle previsioni GIUSTE (cosa prevedeva la strategia quando vinciamo)
voti_in_previsioni_giuste = Counter()
voti_numeri_azzeccati     = Counter()
for _, r in df_giuste.iterrows():
    for n in str(r.get("previsione_8","")).split():
        if n.isdigit(): voti_in_previsioni_giuste[int(n)] += 1
    for n in str(r.get("numeri_azzeccati","")).split():
        if n.isdigit(): voti_numeri_azzeccati[int(n)] += 1

n_g = len(df_giuste)

# riepilogo
riepilogo = pd.DataFrame([
    {"VOCE": f"QUESTE SONO LE {n_g} PREVISIONI NEL 2% (tutte le 4+ azzeccate)",
     "VALORE": f"su {total} previsioni totali = {R*100:.2f}%"},
    {"VOCE": "---", "VALORE": ""},
    {"VOCE": "NUMERI PIU COMUNI nelle 8 previsioni delle vincenti (top 10)",
     "VALORE": " | ".join(f"{n:02d}({c}x)" for n,c in voti_in_previsioni_giuste.most_common(10))},
    {"VOCE": "NUMERI PIU AZZECCATI in assoluto nelle vincenti (top 10)",
     "VALORE": " | ".join(f"{n:02d}({c}x)" for n,c in voti_numeri_azzeccati.most_common(10))},
    {"VOCE": "---", "VALORE": ""},
    {"VOCE": "TOP 6 NUMERI DA GIOCARE STASERA (dai numeri piu azzeccati storicamente)",
     "VALORE": " ".join(f"{n:02d}" for n,_ in voti_numeri_azzeccati.most_common(6))},
    {"VOCE": "TOP 4",
     "VALORE": " ".join(f"{n:02d}" for n,_ in voti_numeri_azzeccati.most_common(4))},
    {"VOCE": "---", "VALORE": ""},
    {"VOCE": "streak medio prima di una GIUSTA (quante sbagliate di fila precedono il 2%)",
     "VALORE": round(df_giuste["streak_sbagliate"].mean(), 1) if "streak_sbagliate" in df_giuste.columns else "n/d"},
    {"VOCE": "streak ATTUALE (sbagliate consecutive ora)",
     "VALORE": results[-1]["streak_sbagliate"]},
    {"VOCE": "CONCLUSIONE",
     "VALORE": (
         f"Dati sperimentali: {n_g} volte nel {R*100:.2f}% su {total} previsioni reali. "
         f"Streak attuale: {results[-1]['streak_sbagliate']} sbagliate consecutive. "
         f">>> STASERA: {' '.join(f'{n:02d}' for n,_ in voti_numeri_azzeccati.most_common(6))}"
     )},
])

with pd.ExcelWriter(str(out), engine="openpyxl") as w:
    df_concetto.to_excel(w,  sheet_name="IL_CONCETTO",     index=False)
    riepilogo.to_excel(w,    sheet_name="Solo_Le_Giuste",  index=False)
    df_giuste.to_excel(w,    sheet_name="148_Vincenti",    index=False)
    df_tutte.to_excel(w,     sheet_name="Tutte_Previsioni",index=False)
    df_73.to_excel(w,        sheet_name="73_Ripetizioni",  index=False)
    df_u.to_excel(w,         sheet_name="Ultime_100",      index=False)

print(f"\nFile: {out} ({out.stat().st_size//1024} KB)")
print(f"Foglio 148_Vincenti: {len(df_giuste)} righe")
print("Top 6 numeri piu azzeccati nelle 148 vincenti:",
      [n for n,_ in voti_numeri_azzeccati.most_common(6)])
print("Streak attuale:", results[-1]["streak_sbagliate"])
