"""
agente_desktop.py — Agente AI autonomo Magic Dream.

Finestra di chat desktop (tkinter). Parte con Magic Dream,
monitora in background, parla con Claude API, ti notifica da solo.
Nessun browser necessario.
"""
from __future__ import annotations

import ast
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

# Auto-installa anthropic se mancante
try:
    import anthropic as _anthropic_check  # noqa: F401
except ImportError:
    print("Installo libreria anthropic...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "anthropic"])
    print("anthropic installata.")

import tkinter as tk
from tkinter import font as tkfont  # noqa: F401
from tkinter import scrolledtext

ROOT_DIR = Path(__file__).resolve().parent
LOG_PATH = ROOT_DIR / "magic_dream_24_7.log"
MAGIC_LAB_DIR = ROOT_DIR / "magic_lab"
API_KEY_FILE = ROOT_DIR / "anthropic_api_key.txt"
WORKER_FILE = ROOT_DIR / "magic_experiment_lab.py"
WORKER_BACKUP = ROOT_DIR / "magic_experiment_lab_backup.py"
LAST_ANALYSIS_FILE = MAGIC_LAB_DIR / "last_analysis.txt"

GITHUB_BASE = (
    "https://raw.githubusercontent.com/Cigolone84/"
    "https-your_pat-github.com-Cigolone84-memecoin-bot/"
    "claude/explore-repo-structure-vp60l"
)
GITHUB_FILES = [
    "magic_dream_24_7.py",
    "magic_experiment_lab.py",
    "setup_magic_dream.py",
    "AVVIA_MAGIC_DREAM.bat",
    "magic_dream_app3.py",
    "agente_desktop.py",
]

PORTS = {"App 1": 8601, "App 2": 8602, "App 3": 8603}

MONITOR_INTERVAL = 300    # 5 minuti tra un check e l'altro
STARTUP_DELAY = 10        # secondi prima del primo check automatico
IMPROVE_INTERVAL = 21600  # 6 ore tra cicli di miglioramento automatici
MAX_HISTORY_EXCHANGES = 3  # scambi completi da tenere in memoria

DESKTOP_CANDIDATES = [
    Path(r"C:\Users\serti\OneDrive\Desktop"),
    Path(r"C:\Users\serti\Desktop"),
    Path(r"C:\Users\Public\Desktop"),
]
AGENT_NOTES_FILE = MAGIC_LAB_DIR / "agent_notes.txt"

# Whitelist per read_source_code
SOURCE_WHITELIST = [
    "magic_experiment_lab.py",
    "app3-lifecycle/app3.py",
]

SYSTEM_PROMPT = (
    "Sei l'agente AI autonomo di Magic Dream — sistema di analisi statistica del lotto italiano"
    " (Superenalotto / lotto 90 numeri).\n\n"
    "=== STRUTTURA MAGIC DREAM ===\n"
    f"Cartella principale: {ROOT_DIR}\n"
    "- magic_dream_24_7.py: supervisor che mantiene App1+App2+App3 sempre attive\n"
    "- magic_experiment_lab.py: worker background che genera previsioni (6 strategie)\n"
    "- setup_magic_dream.py: copia file lotto e installa App3\n"
    "- app3-lifecycle/app3.py: App3 Magic Dream (la dashboard principale)\n"
    "- app1-app2-dashboard/lotto-dashboard/app.py: App1 dashboard lotto\n"
    "- app1-app2-dashboard/lotto-dashboard/app2.py: App2 dashboard lotto\n"
    "- magic_lab/: cartella output del worker (CSV con previsioni)\n"
    "- anthropic_api_key.txt: chiave API\n\n"
    "=== PORTE ===\n"
    "- App1 (localhost:8601): dashboard lotto principale, pool candidati, previsioni ML\n"
    "- App2 (localhost:8602): dashboard lotto secondaria, analisi backtest\n"
    "- App3 (localhost:8603): Magic Dream Centro Operativo — lifecycle, strategie, Magic Lab\n\n"
    "=== LOTTO ITALIANO — REGOLE BASE ===\n"
    "- 90 numeri (1-90), si estraggono 5 per ruota\n"
    "- 10 ruote: Bari, Cagliari, Firenze, Genova, Milano, Napoli, Palermo, Roma, Torino,"
    " Venezia + Nazionale\n"
    "- Estratto: 1 numero, Ambo: 2, Terno: 3, Quaterna: 4, Cinquina: 5\n"
    "- Frequenze: ogni numero ha un ciclo storico di uscite e ritardi\n"
    "- Ritardo: quante estrazioni fa da quando un numero non esce"
    " (numero \"in ritardo\" = potenzialmente \"maturo\")\n\n"
    "=== STRATEGIE MAGIC DREAM (6 strategie in magic_experiment_lab.py) ===\n"
    "1. FreqHot8: i 8 numeri piu frequenti nell'ultima finestra di N draw\n"
    "2. FreqCold8: i 8 numeri meno frequenti (teoria del recupero)\n"
    "3. HotCold4+4: mix 4 caldi + 4 freddi\n"
    "4. Decade8: analisi per decade (1-9, 10-19, ... 80-90) — copre le decadi piu attive\n"
    "5. Delay8: i 8 numeri con piu alto ritardo attuale (teoria della maturazione)\n"
    "6. NucleoPool: nucleo di numeri che co-appaiono frequentemente insieme\n\n"
    "=== OUTPUT MAGIC LAB (magic_lab/) ===\n"
    "- latest_strategy_ranking.csv: ranking delle 6 strategie per hit rate"
    " (colonne: strategy, hit_3plus, hit_rate, total_events)\n"
    "- latest_next_predictions.csv: i numeri previsti per il prossimo draw (per strategia)\n"
    "- latest_event_gaps.csv: gaps tra eventi significativi (usato per semaforo)\n"
    "- latest_range_positions.csv: posizione di ogni numero nel suo range storico\n"
    "- latest_cycle_summary.csv: riassunto cicli lifecycle\n"
    "- latest_cycle_windows.csv: finestre temporali dei cicli\n\n"
    "=== SEMAFORO IN APP3 ===\n"
    "- Verde (attivare): gap >= 75 percentile — momento ottimale per puntare\n"
    "- Blu (monitorare forte): gap >= mediana\n"
    "- Giallo (preparare): gap >= 25 percentile\n"
    "- Rosso (non inseguire): gap basso — ciclo non maturo\n\n"
    "=== BACKTEST ===\n"
    "File: app1-app2-dashboard/lotto-dashboard/backtest_ml_storico.xlsx\n"
    "- Walk-forward su 500 draw storici (no data leakage)\n"
    "- Metrica principale: hit rate >= 3 numeri su 8 selezionati\n"
    "- Benchmark random: ~2.8% (prob casuale di 3+ match da 8 su 90)\n"
    "- Target realistico: >10% hit rate per essere utile\n\n"
    "=== DESKTOP PATHS ===\n"
    "Percorsi da esplorare con list_folder:\n"
    "- C:\\Users\\serti\\OneDrive\\Desktop  (primo tentativo)\n"
    "- C:\\Users\\serti\\Desktop            (fallback)\n"
    "Cartelle lotto da cercare: 'lotto', '3 ml', 'lotto-dashboard'\n\n"
    "=== MEMORIA PERSISTENTE ===\n"
    "Hai accesso a save_note/read_notes per ricordare trovate importanti tra una sessione e l'altra.\n"
    "Salva sempre: percorso cartella lotto trovata, hit rate migliore, ultima analisi importante.\n"
    "All'avvio, leggi prima le note per riprendere dal punto corretto.\n\n"
    "=== WORKER magic_experiment_lab.py ===\n"
    "Usa check_worker per vedere se sta girando e quando ha prodotto l'ultimo output.\n"
    "Usa start_worker per avviarlo se non gira (serve ogni 3 ore per aggiornare i CSV).\n\n"
    "=== TUOI COMPITI AUTONOMI ===\n"
    "1. Monitora le 3 app ogni 5 minuti — se offline, avvisa e diagnoza\n"
    "2. Leggi i CSV di Magic Lab e interpreta i risultati\n"
    "3. Quando hai dati sufficienti, analizza le performance delle strategie\n"
    "4. Suggerisci miglioramenti al codice (magic_experiment_lab.py) ogni 6 ore\n"
    "5. Riferisci all'utente solo i risultati finali, non i dettagli tecnici\n\n"
    "=== COMPORTAMENTO ===\n"
    "- Parla SEMPRE in italiano\n"
    "- Messaggi brevi e diretti — l'utente vuole fatti, non spiegazioni\n"
    "- Agisci prima, riferisci dopo\n"
    "- Non chiedere conferma per azioni di monitoraggio/lettura\n"
    "- Chiedi conferma solo prima di modificare file Python\n"
    "- Salva le note delle scoperte importanti con save_note\n"
)

TOOLS = [
    {
        "name": "check_status",
        "description": "Controlla se le app Magic Dream sono online",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "read_log",
        "description": "Legge le ultime N righe del log del supervisor",
        "input_schema": {
            "type": "object",
            "properties": {
                "lines": {
                    "type": "integer",
                    "description": "Righe da leggere (default 30)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "read_magic_lab",
        "description": "Elenca i CSV di Magic Lab o mostra il contenuto di uno specifico",
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {
                    "type": "string",
                    "description": "Nome file CSV (opzionale)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "run_update",
        "description": "Scarica aggiornamenti da GitHub e installa",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_setup",
        "description": "Esegue setup: installa App3, crea cartelle",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "open_browser",
        "description": "Apre una app nel browser",
        "input_schema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "enum": ["App 1", "App 2", "App 3"]},
            },
            "required": ["app"],
        },
    },
    {
        "name": "read_source_code",
        "description": (
            "Legge il codice sorgente di un file Python di Magic Dream. "
            "File ammessi: magic_experiment_lab.py, app3-lifecycle/app3.py"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Percorso relativo del file da leggere. "
                        "Valori ammessi: 'magic_experiment_lab.py' "
                        "oppure 'app3-lifecycle/app3.py'"
                    ),
                }
            },
            "required": ["filename"],
        },
    },
    {
        "name": "list_folder",
        "description": "Elenca il contenuto di una cartella sul PC. Usa per esplorare Desktop, cartella lotto, Magic Dream, ecc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Percorso cartella, es: C:\\Users\\serti\\OneDrive\\Desktop"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Legge qualsiasi file di testo sul PC (.py, .csv, .txt, .bat, .log, ecc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Percorso completo del file"},
                "max_lines": {"type": "integer", "description": "Righe max da leggere (default 300)"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Scrive o sovrascrive un file dentro Magic Dream (backup automatico .bak). Usa per migliorare il codice.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Percorso file (deve essere dentro Magic Dream)"},
                "content": {"type": "string", "description": "Contenuto completo del file"}
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "save_note",
        "description": "Salva una nota persistente. Usa per ricordare scoperte importanti tra una sessione e l'altra.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Testo della nota da salvare"}
            },
            "required": ["text"],
        },
    },
    {
        "name": "read_notes",
        "description": "Legge le note salvate nelle sessioni precedenti.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "check_worker",
        "description": "Verifica se magic_experiment_lab.py sta girando e quando ha prodotto l'ultimo output.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "start_worker",
        "description": "Avvia magic_experiment_lab.py in background per aggiornare i CSV di Magic Lab.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


# ── Tools implementation ────────────────────────────────────────────────────

def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://localhost:{port}/_stcore/health", timeout=3
        ) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def tool_check_status() -> str:
    lines = []
    all_ok = True
    for name, port in PORTS.items():
        ok = _health(port)
        if not ok:
            all_ok = False
        lines.append(f"{name} (:{port}): {'✅ online' if ok else '❌ offline'}")
    if all_ok:
        lines.append("→ Tutto in funzione.")
    return "\n".join(lines)


def tool_read_log(lines: int = 30) -> str:
    if not LOG_PATH.exists():
        return "Log non trovato. Il supervisor non e ancora avviato."
    text = LOG_PATH.read_text(encoding="utf-8", errors="replace")
    rows = text.splitlines()
    return "\n".join(rows[-lines:]) if rows else "(vuoto)"


def tool_read_magic_lab(file: str | None = None) -> str:
    if not MAGIC_LAB_DIR.exists():
        return "Cartella magic_lab non trovata — Magic Lab non ha ancora girato."
    csvs = sorted(MAGIC_LAB_DIR.glob("*.csv"))
    if not csvs:
        return "Nessun CSV in magic_lab."
    if file:
        target = MAGIC_LAB_DIR / file
        if not target.exists():
            return f"{file} non trovato. Disponibili: {[f.name for f in csvs]}"
        try:
            import csv as csvmod
            rows = list(csvmod.DictReader(target.open(encoding="utf-8")))
            if not rows:
                return f"{file}: vuoto"
            header = ",".join(rows[0].keys())
            body = "\n".join(
                ",".join(str(v) for v in r.values()) for r in rows[:8]
            )
            return f"{file} ({len(rows)} righe):\n{header}\n{body}"
        except Exception as e:
            return f"Errore: {e}"
    lines = []
    for f in csvs:
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m %H:%M")
        lines.append(f"  {f.name}  ({f.stat().st_size}B, {mtime})")
    return "File in magic_lab:\n" + "\n".join(lines)


def tool_run_update() -> str:
    results = []
    for fname in GITHUB_FILES:
        try:
            urllib.request.urlretrieve(f"{GITHUB_BASE}/{fname}", ROOT_DIR / fname)
            results.append(f"OK: {fname}")
        except Exception as e:
            results.append(f"ERRORE {fname}: {e}")
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT_DIR / "setup_magic_dream.py")],
            cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=60,
        )
        return (
            "\n".join(results)
            + "\n\nSetup:\n"
            + (r.stdout or "")
            + (r.stderr or "")
        )
    except Exception as e:
        return "\n".join(results) + f"\n\nSetup fallito: {e}"


def tool_run_setup() -> str:
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT_DIR / "setup_magic_dream.py")],
            cwd=str(ROOT_DIR), capture_output=True, text=True, timeout=60,
        )
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"Errore: {e}"


def tool_open_browser(app: str) -> str:
    urls = {
        "App 1": "http://localhost:8601",
        "App 2": "http://localhost:8602",
        "App 3": "http://localhost:8603",
    }
    url = urls.get(app)
    if not url:
        return f"App sconosciuta: {app}"
    webbrowser.open(url)
    return f"Browser aperto su {url}"


def tool_read_source_code(filename: str) -> str:
    """Legge il sorgente di un file Python dalla whitelist."""
    clean = filename.strip().lstrip("/").lstrip("\\")
    if clean not in SOURCE_WHITELIST:
        return (
            f"Accesso negato: '{clean}' non e nella whitelist. "
            f"File ammessi: {SOURCE_WHITELIST}"
        )
    target = ROOT_DIR / clean
    if not target.exists():
        return f"File non trovato: {target}"
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Errore lettura {clean}: {e}"


def _tool_list_folder(path: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"Cartella non trovata: {path}"
        if not p.is_dir():
            return f"Non è una cartella: {path}"
        items = []
        for item in sorted(p.iterdir()):
            if item.is_dir():
                try:
                    sub = len(list(item.iterdir()))
                except PermissionError:
                    sub = "?"
                items.append(f"📁 {item.name}/  ({sub} elementi)")
            else:
                size = item.stat().st_size
                mtime = datetime.fromtimestamp(item.stat().st_mtime).strftime("%d/%m %H:%M")
                items.append(f"📄 {item.name}  ({size}B, {mtime})")
        return f"{path}  ({len(items)} elementi):\n" + "\n".join(items)
    except Exception as e:
        return f"Errore list_folder: {e}"


def _tool_read_file(path: str, max_lines: int = 300) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"File non trovato: {path}"
        allowed = {'.py', '.txt', '.csv', '.json', '.md', '.bat', '.log', '.ini', '.cfg'}
        if p.suffix.lower() not in allowed:
            return f"Tipo non supportato: {p.suffix}. Tipi OK: {allowed}"
        text = p.read_text(encoding='utf-8', errors='replace')
        lines = text.splitlines()
        preview = "\n".join(lines[:max_lines])
        suffix = f"\n... ({len(lines)-max_lines} righe omesse)" if len(lines) > max_lines else ""
        return f"{path}  ({len(lines)} righe):\n{preview}{suffix}"
    except Exception as e:
        return f"Errore read_file: {e}"


def _tool_write_file(path: str, content: str) -> str:
    try:
        p = Path(path).resolve()
        if not str(p).startswith(str(ROOT_DIR.resolve())):
            return f"Scrittura consentita solo dentro: {ROOT_DIR}"
        if p.exists():
            shutil.copy2(str(p), str(p.with_suffix(p.suffix + ".bak")))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding='utf-8')
        return f"✅ Salvato: {p}"
    except Exception as e:
        return f"Errore write_file: {e}"


def tool_save_note(text: str) -> str:
    try:
        MAGIC_LAB_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        entry = f"\n=== {timestamp} ===\n{text.strip()}\n"
        with AGENT_NOTES_FILE.open("a", encoding="utf-8") as f:
            f.write(entry)
        return "✅ Nota salvata."
    except Exception as e:
        return f"Errore save_note: {e}"


def tool_read_notes() -> str:
    if not AGENT_NOTES_FILE.exists():
        return "Nessuna nota salvata — prima sessione."
    text = AGENT_NOTES_FILE.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return "\n".join(lines[-60:]) if lines else "(vuoto)"


def tool_check_worker() -> str:
    result = []
    if MAGIC_LAB_DIR.exists():
        csvs = sorted(MAGIC_LAB_DIR.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
        if csvs:
            latest = csvs[0]
            age_min = (time.time() - latest.stat().st_mtime) / 60
            result.append(f"Ultimo CSV: {latest.name} ({age_min:.0f} min fa)")
            result.append("✅ Worker attivo" if age_min < 200 else "⚠️ Worker forse stoppato (output > 3h fa)")
        else:
            result.append("⚠️ Nessun CSV — worker non ha ancora girato")
    else:
        result.append("⚠️ magic_lab/ non esiste ancora")
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10,
        )
        n = max(0, r.stdout.lower().count("python.exe") - 1)
        result.append(f"Processi python.exe attivi: {n}")
    except Exception:
        pass
    return "\n".join(result)


def tool_start_worker() -> str:
    if not WORKER_FILE.exists():
        return f"❌ {WORKER_FILE.name} non trovato"
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.Popen(
            [sys.executable, str(WORKER_FILE), "--loop", "--interval-minutes", "180"],
            cwd=str(ROOT_DIR),
            creationflags=flags,
        )
        return "✅ Worker avviato in background — output in magic_lab/ (prima esecuzione dopo ~3 min)"
    except Exception as e:
        return f"❌ Errore avvio worker: {e}"


def execute_tool(name: str, inp: dict) -> str:
    try:
        if name == "check_status":
            return tool_check_status()
        elif name == "read_log":
            return tool_read_log(inp.get("lines", 30))
        elif name == "read_magic_lab":
            return tool_read_magic_lab(inp.get("file"))
        elif name == "run_update":
            return tool_run_update()
        elif name == "run_setup":
            return tool_run_setup()
        elif name == "open_browser":
            return tool_open_browser(inp.get("app", "App 1"))
        elif name == "list_folder":
            return _tool_list_folder(inp.get("path", str(ROOT_DIR)))
        elif name == "read_file":
            return _tool_read_file(inp.get("path", ""), inp.get("max_lines", 150))
        elif name == "write_file":
            return _tool_write_file(inp.get("path", ""), inp.get("content", ""))
        elif name == "read_source_code":
            return tool_read_source_code(inp.get("filename", ""))
        elif name == "save_note":
            return tool_save_note(inp.get("text", ""))
        elif name == "read_notes":
            return tool_read_notes()
        elif name == "check_worker":
            return tool_check_worker()
        elif name == "start_worker":
            return tool_start_worker()
        return f"Strumento sconosciuto: {name}"
    except Exception as e:
        return f"Errore {name}: {e}"


# ── Claude agentic loop ─────────────────────────────────────────────────────

def _trim_history(history: list, max_exchanges: int = MAX_HISTORY_EXCHANGES) -> list:
    """Keep last max_exchanges complete user/assistant pairs (end_turn only — no tool sequences)."""
    pairs: list[list] = []
    i = len(history) - 1
    while i > 0 and len(pairs) < max_exchanges:
        if history[i].get("role") == "assistant" and history[i - 1].get("role") == "user":
            pairs.insert(0, history[i - 1: i + 1])
            i -= 2
        else:
            i -= 1
    return [msg for pair in pairs for msg in pair]


def run_agent(message: str, api_key: str, history: list) -> tuple[str, list]:
    """
    Returns (reply_text, updated_history).

    History: keeps last MAX_HISTORY_EXCHANGES complete exchanges (end_turn pairs).
    On API 400 (BadRequestError) retries from scratch with no history.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    messages = _trim_history(history) + [{"role": "user", "content": message}]

    for _ in range(15):  # max 15 tool rounds
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.BadRequestError:
            messages = [{"role": "user", "content": message}]
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

        if resp.stop_reason == "end_turn":
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            new_exchange = [
                {"role": "user", "content": message},
                {"role": "assistant", "content": resp.content},
            ]
            updated_hist = _trim_history(history) + new_exchange
            return text, updated_hist

        if resp.stop_reason == "tool_use":
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": execute_tool(b.name, b.input),
                    })
            messages = messages + [
                {"role": "assistant", "content": resp.content},
                {"role": "user", "content": results},
            ]
        else:
            break

    return "Errore: risposta inattesa dall'API.", history


# ── Improvement cycle ───────────────────────────────────────────────────────

def _read_all_csvs() -> str:
    """Legge tutti i CSV di magic_lab e restituisce una stringa riassuntiva."""
    if not MAGIC_LAB_DIR.exists():
        return "Cartella magic_lab non trovata."
    csvs = sorted(MAGIC_LAB_DIR.glob("*.csv"))
    if not csvs:
        return "Nessun CSV disponibile in magic_lab."
    import csv as csvmod
    parts = []
    for f in csvs:
        try:
            rows = list(csvmod.DictReader(f.open(encoding="utf-8")))
            if not rows:
                parts.append(f"=== {f.name}: vuoto ===")
                continue
            header = ",".join(rows[0].keys())
            body = "\n".join(
                ",".join(str(v) for v in r.values()) for r in rows[:10]
            )
            parts.append(f"=== {f.name} ({len(rows)} righe) ===\n{header}\n{body}")
        except Exception as e:
            parts.append(f"=== {f.name}: errore lettura ({e}) ===")
    return "\n\n".join(parts)


def _save_analysis(text: str) -> None:
    """Salva il testo di analisi in magic_lab/last_analysis.txt."""
    try:
        MAGIC_LAB_DIR.mkdir(parents=True, exist_ok=True)
        LAST_ANALYSIS_FILE.write_text(
            f"=== Analisi del {datetime.now().strftime('%d/%m/%Y %H:%M')} ===\n\n{text}",
            encoding="utf-8",
        )
    except Exception:
        pass  # Non bloccare l'esecuzione per un errore di log


def run_improvement_cycle(api_key: str, msg_queue: "queue.Queue") -> None:
    """
    Ciclo di miglioramento autonomo in due fasi:
    1. Analyst: analizza i risultati CSV e identifica cosa migliorare
    2. Developer: propone modifiche Python concrete a magic_experiment_lab.py
    Valida con ast.parse, crea backup e applica se valido.
    """
    import anthropic

    msg_queue.put(("agent", "🔬 Ciclo di miglioramento avviato..."))

    # --- Raccolta dati ---
    if not WORKER_FILE.exists():
        msg_queue.put((
            "agent",
            "❌ magic_experiment_lab.py non trovato — impossibile migliorare.",
        ))
        return

    source_code = WORKER_FILE.read_text(encoding="utf-8", errors="replace")
    csv_data = _read_all_csvs()

    if csv_data.startswith("Nessun CSV") or csv_data.startswith("Cartella"):
        msg_queue.put((
            "agent",
            "⏸ Ciclo di miglioramento posticipato — Magic Lab non ha ancora prodotto dati.",
        ))
        return

    client = anthropic.Anthropic(api_key=api_key)

    # --- Chiamata 1: Analyst ---
    analyst_prompt = (
        "Sei un analista statistico del lotto italiano esperto di Machine Learning.\n\n"
        "Ecco i risultati prodotti da Magic Lab (CSV):\n\n"
        f"{csv_data}\n\n"
        "Analizza i risultati delle 6 strategie (FreqHot8, FreqCold8, HotCold4+4, Decade8,"
        " Delay8, NucleoPool). Identifica:\n"
        "1. Quale strategia performa meglio e perche\n"
        "2. Quali strategie sono sotto il benchmark (~2.8% hit rate per 3+ su 8)\n"
        "3. Cosa migliorare concretamente nel codice Python\n"
        "Sii specifico e tecnico. Rispondi in italiano."
    )
    try:
        analyst_resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": analyst_prompt}],
        )
        analysis = "".join(
            b.text for b in analyst_resp.content if hasattr(b, "text")
        )
    except Exception as e:
        msg_queue.put(("agent", f"❌ Errore nella fase di analisi: {e}"))
        return

    # Mostra l'analisi all'utente in modo sintetico
    analysis_preview = "\n".join(analysis.splitlines()[:8])
    msg_queue.put(("agent", f"📊 Analisi:\n{analysis_preview}\n\nDeveloper sta scrivendo il codice..."))

    # --- Chiamata 2: Developer ---
    developer_prompt = (
        "Sei uno sviluppatore Python esperto di analisi statistica del lotto italiano.\n\n"
        "=== ANALISI DEL RICERCATORE ===\n"
        f"{analysis}\n\n"
        "=== CODICE ATTUALE DI magic_experiment_lab.py ===\n"
        f"{source_code}\n\n"
        "Basandoti sull'analisi, riscrivi magic_experiment_lab.py COMPLETO con le migliorie integrate.\n"
        "OBBLIGATORIO:\n"
        "- Restituisci IL FILE COMPLETO, non frammenti\n"
        "- Il file deve contenere TUTTE le 6 strategie: FreqHot8, FreqCold8, HotCold4, Decade8, Delay8, NucleoPool\n"
        "- Mantieni la struttura generale e le interfacce esistenti\n"
        "- Il codice deve essere Python valido e sintatticamente corretto\n"
        "- Se l'analisi non giustifica modifiche, scrivi solo: NESSUNA_MODIFICA\n"
        "Rispondi SOLO con il file Python completo (nessun testo prima o dopo),"
        " oppure NESSUNA_MODIFICA."
    )
    try:
        dev_resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": developer_prompt}],
        )
        proposed_code = "".join(
            b.text for b in dev_resp.content if hasattr(b, "text")
        ).strip()
    except Exception as e:
        msg_queue.put(("agent", f"❌ Errore nella fase di sviluppo: {e}"))
        _save_analysis(analysis)
        return

    if proposed_code == "NESSUNA_MODIFICA" or not proposed_code:
        msg_queue.put((
            "agent",
            "ℹ️ Il Developer non ha proposto modifiche — le strategie attuali sono ottimali"
            " rispetto ai dati disponibili.",
        ))
        _save_analysis(analysis)
        return

    # Pulisce eventuali backtick markdown (```python ... ```)
    if proposed_code.startswith("```"):
        lines = proposed_code.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        proposed_code = "\n".join(lines)

    # --- Validazione AST ---
    try:
        ast.parse(proposed_code)
    except SyntaxError as e:
        msg_queue.put((
            "agent",
            f"❌ Codice proposto non valido (SyntaxError: {e})"
            " — nessuna modifica applicata",
        ))
        _save_analysis(analysis + f"\n\n--- CODICE PROPOSTO (NON VALIDO) ---\n{proposed_code}")
        return

    # --- Controllo simboli chiave ---
    REQUIRED_SYMBOLS = ["FreqHot8", "FreqCold8", "HotCold4", "Decade8", "Delay8", "NucleoPool"]
    missing = [s for s in REQUIRED_SYMBOLS if s not in proposed_code]
    if missing:
        msg_queue.put((
            "agent",
            f"❌ File proposto manca di: {missing} — nessuna modifica applicata (sicurezza)",
        ))
        _save_analysis(analysis + f"\n\n--- CODICE RIFIUTATO (simboli mancanti: {missing}) ---\n")
        return

    # --- Backup e applicazione ---
    try:
        shutil.copy2(WORKER_FILE, WORKER_BACKUP)
        WORKER_FILE.write_text(proposed_code, encoding="utf-8")
        msg_queue.put((
            "agent",
            "✅ Miglioramento applicato a magic_experiment_lab.py — "
            "backup in magic_experiment_lab_backup.py",
        ))
        _save_analysis(
            analysis + f"\n\n--- MODIFICA APPLICATA ---\n{proposed_code}"
        )
    except Exception as e:
        msg_queue.put(("agent", f"❌ Errore nel salvataggio del file: {e}"))


# ── Desktop GUI ─────────────────────────────────────────────────────────────

class AgentApp:
    BUBBLE_USER = "#0a84ff"
    BUBBLE_AGENT = "#2c2c2e"
    BG = "#1c1c1e"
    TEXT = "#f2f2f7"
    INPUT_BG = "#2c2c2e"

    def __init__(self):
        self.api_key: str = self._load_api_key()
        self.history: list = []
        self.msg_queue: queue.Queue = queue.Queue()
        self._offline_reported: set = set()

        self._build_window()
        self._schedule_queue_check()

        # Primo messaggio automatico dopo startup
        threading.Thread(target=self._startup_check, daemon=True).start()
        # Monitor loop
        threading.Thread(target=self._monitor_loop, daemon=True).start()
        # Auto-improvement loop (ogni 6 ore)
        threading.Thread(target=self._improvement_loop, daemon=True).start()

    # ── API key ────────────────────────────────────────────────────────────

    def _load_api_key(self) -> str:
        if API_KEY_FILE.exists():
            k = API_KEY_FILE.read_text().strip()
            if k:
                return k
        return os.environ.get("ANTHROPIC_API_KEY", "")

    def _save_api_key(self, key: str) -> None:
        API_KEY_FILE.write_text(key.strip())
        self.api_key = key.strip()

    # ── Window ─────────────────────────────────────────────────────────────

    def _build_window(self) -> None:
        self.root = tk.Tk()
        self.root.title("🤖 Agente Magic Dream")
        self.root.geometry("640x720")
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.minsize(400, 500)

        # Header
        hdr = tk.Frame(self.root, bg="#111113", pady=8)
        hdr.pack(fill=tk.X)
        tk.Label(
            hdr, text="🤖  Agente Magic Dream", bg="#111113",
            fg=self.TEXT, font=("Segoe UI", 14, "bold"),
        ).pack(side=tk.LEFT, padx=12)

        self._status_lbl = tk.Label(
            hdr, text="● avvio…", bg="#111113",
            fg="#ffcc00", font=("Segoe UI", 10),
        )
        self._status_lbl.pack(side=tk.RIGHT, padx=12)

        # Quick buttons
        btn_bar = tk.Frame(self.root, bg=self.BG, pady=4)
        btn_bar.pack(fill=tk.X, padx=8)

        quick_buttons = [
            ("🔍 Controlla", lambda: self._send("Controlla tutte le app e dimmi lo stato.")),
            ("📋 Log",        lambda: self._send("Mostrami gli ultimi log.")),
            ("⬇️ Aggiorna",  lambda: self._send("Aggiorna Magic Dream da GitHub.")),
            ("🌐 Apri App3",  lambda: self._send("Apri App3 nel browser.")),
            ("🔬 Migliora",   self._trigger_improvement),
        ]

        for label, cmd in quick_buttons:
            tk.Button(
                btn_bar, text=label, command=cmd,
                bg="#3a3a3c", fg=self.TEXT, relief=tk.FLAT,
                font=("Segoe UI", 9), padx=8, pady=4, cursor="hand2",
                activebackground="#48484a", activeforeground=self.TEXT,
            ).pack(side=tk.LEFT, padx=3)

        # API Key button — right side
        tk.Button(
            btn_bar, text="🔑 API Key", command=self._ask_api_key,
            bg="#3a3a3c", fg="#ffcc00", relief=tk.FLAT,
            font=("Segoe UI", 9), padx=8, pady=4, cursor="hand2",
            activebackground="#48484a", activeforeground="#ffcc00",
        ).pack(side=tk.RIGHT, padx=3)

        # Chat area
        self._chat = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, bg=self.BG, fg=self.TEXT,
            font=("Segoe UI", 11), relief=tk.FLAT, padx=12, pady=8,
            state=tk.DISABLED, cursor="arrow",
        )
        self._chat.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 0))

        # Tag styles
        self._chat.tag_config(
            "user_hdr", foreground="#0a84ff", font=("Segoe UI", 9, "bold"),
        )
        self._chat.tag_config(
            "user_txt", foreground=self.TEXT,
            font=("Segoe UI", 11), lmargin1=16, lmargin2=16,
        )
        self._chat.tag_config(
            "agent_hdr", foreground="#30d158", font=("Segoe UI", 9, "bold"),
        )
        self._chat.tag_config(
            "agent_txt", foreground=self.TEXT,
            font=("Segoe UI", 11), lmargin1=16, lmargin2=16,
        )
        self._chat.tag_config(
            "thinking", foreground="#636366",
            font=("Segoe UI", 10, "italic"), lmargin1=16,
        )

        # Input row
        inp_frame = tk.Frame(self.root, bg=self.BG, pady=8)
        inp_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

        self._entry = tk.Entry(
            inp_frame, bg=self.INPUT_BG, fg=self.TEXT,
            insertbackground=self.TEXT,
            relief=tk.FLAT, font=("Segoe UI", 12), bd=8,
        )
        self._entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        self._entry.bind("<Return>", lambda _: self._on_send())
        self._entry.focus()

        tk.Button(
            inp_frame, text="➤", command=self._on_send,
            bg=self.BUBBLE_USER, fg="white", relief=tk.FLAT,
            font=("Segoe UI", 13, "bold"), padx=12, pady=6,
            cursor="hand2", activebackground="#0060cc",
        ).pack(side=tk.LEFT, padx=(6, 0))

    # ── Chat display ────────────────────────────────────────────────────────

    def _append(self, role: str, text: str) -> None:
        self._chat.config(state=tk.NORMAL)
        now = datetime.now().strftime("%H:%M")
        if role == "user":
            self._chat.insert(tk.END, f"\nTu  {now}\n", "user_hdr")
            self._chat.insert(tk.END, text + "\n", "user_txt")
        elif role == "agent":
            self._chat.insert(tk.END, f"\nAgente  {now}\n", "agent_hdr")
            self._chat.insert(tk.END, text + "\n", "agent_txt")
        elif role == "thinking":
            self._chat.insert(tk.END, text + "\n", "thinking")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    # ── Send / receive ──────────────────────────────────────────────────────

    def _on_send(self) -> None:
        msg = self._entry.get().strip()
        if not msg:
            return
        self._entry.delete(0, tk.END)
        self._send(msg)

    def _send(self, message: str) -> None:
        self._append("user", message)
        threading.Thread(
            target=self._agent_thread, args=(message,), daemon=True
        ).start()

    def _agent_thread(self, message: str) -> None:
        if not self.api_key:
            self.msg_queue.put((
                "agent",
                "⚠️ Nessuna API key. Clicca '🔑 API Key' per inserirla.",
            ))
            return
        self.msg_queue.put(("thinking", "⏳ sto elaborando…"))
        try:
            reply, new_hist = run_agent(message, self.api_key, self.history)
            self.history = new_hist
            self.msg_queue.put(("agent", reply))
        except Exception as e:
            self.msg_queue.put(("agent", f"❌ Errore: {e}"))

    # ── Improvement trigger ─────────────────────────────────────────────────

    def _trigger_improvement(self) -> None:
        """Avvia manualmente il ciclo di miglioramento."""
        if not self.api_key:
            self._append(
                "agent",
                "⚠️ Nessuna API key. Clicca '🔑 API Key' per inserirla.",
            )
            return
        threading.Thread(
            target=run_improvement_cycle,
            args=(self.api_key, self.msg_queue),
            daemon=True,
        ).start()

    # ── Queue processing ────────────────────────────────────────────────────

    def _schedule_queue_check(self) -> None:
        self.root.after(200, self._check_queue)

    def _check_queue(self) -> None:
        try:
            while True:
                kind, data = self.msg_queue.get_nowait()
                if kind == "thinking":
                    self._remove_thinking()
                    self._append("thinking", data)
                elif kind == "agent":
                    self._remove_thinking()
                    self._append("agent", data)
                    self._flash_title()
                elif kind == "status":
                    self._status_lbl.config(text=data[0], fg=data[1])
        except queue.Empty:
            pass
        self.root.after(200, self._check_queue)

    def _remove_thinking(self) -> None:
        self._chat.config(state=tk.NORMAL)
        start = "1.0"
        while True:
            pos = self._chat.search("⏳ sto elaborando…", start, tk.END)
            if not pos:
                break
            line = int(pos.split(".")[0])
            self._chat.delete(f"{line}.0", f"{line+1}.0")
        self._chat.config(state=tk.DISABLED)

    def _flash_title(self) -> None:
        orig = self.root.title()
        self.root.title("🔔 AGENTE — nuovo messaggio")
        self.root.after(3000, lambda: self.root.title(orig))
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(1500, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    # ── Background monitor ──────────────────────────────────────────────────

    def _startup_check(self) -> None:
        time.sleep(STARTUP_DELAY)
        if not self.api_key:
            self.msg_queue.put((
                "agent",
                "Ciao! Sono il tuo agente Magic Dream.\n\n"
                "⚠️ Inserisci la tua API Key Anthropic (clicca '🔑 API Key') "
                "per attivarmi completamente.\n\n"
                "Senza chiave posso mostrare solo lo stato base delle app.",
            ))
            status = tool_check_status()
            self.msg_queue.put(("agent", "Stato attuale:\n" + status))
            return
        status = tool_check_status()
        lab_data = tool_read_magic_lab()
        notes = tool_read_notes()
        worker_status = tool_check_worker()

        # Trova il primo desktop esistente
        desktop_paths = "\n".join(str(p) for p in DESKTOP_CANDIDATES)

        threading.Thread(
            target=self._agent_thread,
            args=(
                f"Sei appena avviato. Stato app:\n{status}\n\n"
                f"Worker:\n{worker_status}\n\n"
                f"Magic Lab:\n{lab_data}\n\n"
                f"Note sessioni precedenti:\n{notes}\n\n"
                "COMPITI (eseguili in sequenza senza aspettare input):\n"
                f"1. Leggi le note precedenti qui sopra — ricorda cosa sai già\n"
                f"2. Prova list_folder sui questi percorsi Desktop (nell'ordine) finché uno funziona:\n"
                f"{desktop_paths}\n"
                "3. Trova la cartella lotto originale (es. 'lotto' o '3 ml') ed esplorane il contenuto\n"
                "4. Verifica lo stato del worker — se fermo, avvialo con start_worker\n"
                "5. Analizza i CSV in magic_lab/ — quale strategia ha il hit rate più alto?\n"
                "6. Salva le scoperte importanti con save_note (percorso lotto trovato, hit rate migliore)\n"
                "7. Dammi un report finale: stato sistemi, confronto strategie, cosa migliorare\n"
                "Agisci in autonomia, non chiedere conferma.",
            ),
            daemon=True,
        ).start()

    def _monitor_loop(self) -> None:
        time.sleep(STARTUP_DELAY + 30)  # lascia tempo al check di avvio
        while True:
            time.sleep(MONITOR_INTERVAL)
            offline = [n for n, p in PORTS.items() if not _health(p)]
            if offline:
                newly_offline = set(offline) - self._offline_reported
                if newly_offline and self.api_key:
                    self._offline_reported.update(newly_offline)
                    msg = (
                        f"⚠️ Rilevato: {', '.join(newly_offline)} non risponde. Verifico."
                    )
                    self.msg_queue.put(("agent", msg))
                    problem = (
                        f"{', '.join(newly_offline)} risulta offline. "
                        "Controlla i log e dimmi cosa sta succedendo. "
                        "Il supervisor dovrebbe riavviarle automaticamente — "
                        "conferma che stia funzionando."
                    )
                    threading.Thread(
                        target=self._agent_thread, args=(problem,), daemon=True
                    ).start()
            else:
                if self._offline_reported:
                    self._offline_reported.clear()
                    self.msg_queue.put(("agent", "✅ Tutte le app sono tornate online."))
            all_ok = not offline
            dot = "● tutto ok" if all_ok else f"● {len(offline)} offline"
            color = "#30d158" if all_ok else "#ff453a"
            self.msg_queue.put(("status", (dot, color)))

    def _improvement_loop(self) -> None:
        """Ciclo automatico di miglioramento ogni IMPROVE_INTERVAL secondi."""
        # Prima attesa: aspetta startup + margine prima di iniziare il ciclo
        time.sleep(STARTUP_DELAY + 60)
        while True:
            time.sleep(IMPROVE_INTERVAL)
            # Solo se magic_lab ha CSV (Magic Lab ha girato almeno una volta)
            if not self.api_key:
                continue
            if not MAGIC_LAB_DIR.exists():
                continue
            csvs = list(MAGIC_LAB_DIR.glob("*.csv"))
            if not csvs:
                continue
            threading.Thread(
                target=run_improvement_cycle,
                args=(self.api_key, self.msg_queue),
                daemon=True,
            ).start()

    # ── API key dialog ──────────────────────────────────────────────────────

    def _ask_api_key(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("API Key Anthropic")
        win.geometry("480x180")
        win.configure(bg=self.BG)
        win.grab_set()

        tk.Label(
            win, text="Incolla qui la tua API Key Anthropic:",
            bg=self.BG, fg=self.TEXT, font=("Segoe UI", 11),
        ).pack(pady=(20, 6))
        tk.Label(
            win, text="(la trovi su console.anthropic.com → API Keys)",
            bg=self.BG, fg="#636366", font=("Segoe UI", 9),
        ).pack()

        entry = tk.Entry(
            win, show="*", width=50, bg=self.INPUT_BG,
            fg=self.TEXT, insertbackground=self.TEXT,
            font=("Segoe UI", 11), relief=tk.FLAT, bd=6,
        )
        entry.pack(pady=10, ipady=4)
        if self.api_key:
            entry.insert(0, self.api_key)

        def save():
            key = entry.get().strip()
            if key:
                self._save_api_key(key)
                win.destroy()
                self._append("agent", "✅ API Key salvata. Sono operativo!")
            else:
                entry.config(bg="#4a1010")

        tk.Button(
            win, text="Salva", command=save,
            bg=self.BUBBLE_USER, fg="white", relief=tk.FLAT,
            font=("Segoe UI", 11), padx=20, pady=6,
        ).pack()
        entry.focus()
        entry.bind("<Return>", lambda _: save())

    # ── Close ───────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    AgentApp().run()
