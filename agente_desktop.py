"""
agente_desktop.py — Agente AI autonomo Magic Dream.

Finestra di chat desktop (tkinter). Parte con Magic Dream,
monitora in background, parla con Claude API, ti notifica da solo.
Nessun browser necessario.
"""
from __future__ import annotations

import os
import queue
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

from tkinter import font as tkfont
import tkinter as tk
from tkinter import scrolledtext, simpledialog, ttk

ROOT_DIR = Path(__file__).resolve().parent
LOG_PATH = ROOT_DIR / "magic_dream_24_7.log"
MAGIC_LAB_DIR = ROOT_DIR / "magic_lab"
API_KEY_FILE = ROOT_DIR / "anthropic_api_key.txt"

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

MONITOR_INTERVAL = 300  # 5 minuti tra un check e l'altro
STARTUP_DELAY = 10      # secondi prima del primo check automatico

SYSTEM_PROMPT = """Sei l'agente AI autonomo di Magic Dream, un sistema di analisi del lotto italiano che gira 24/7 sul PC dell'utente.

Compito principale: monitorare le 3 app Streamlit (App1=8601 dashboard, App2=8602 dashboard, App3=8603 lifecycle Magic Dream) e il worker Magic Lab, risolvere problemi autonomamente, e riferire all'utente solo quando necessario.

Strumenti disponibili:
- check_status: controlla quali app sono online/offline
- read_log: legge i log del supervisor
- read_magic_lab: legge i CSV prodotti da Magic Lab
- run_update: scarica aggiornamenti da GitHub e installa
- run_setup: installa App3 e crea cartelle
- open_browser: apre un'app nel browser

Comportamento:
- Sii proattivo: se vedi un problema, agisci e poi avvisa l'utente
- Sii conciso: messaggi brevi, diretti, in italiano
- Chiedi conferma solo per azioni rischiose (es. aggiornamento)
- Il supervisor magic_dream_24_7.py gestisce già il riavvio delle app — se un'app è offline da poco, aspetta che si riavvi da sola
- Se l'utente chiede "controlla tutto", usa check_status e report brevemente

La cartella Magic Dream è: """ + str(ROOT_DIR) + """
Rispondi SEMPRE in italiano, messaggi brevi e concreti."""

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
                "lines": {"type": "integer", "description": "Righe da leggere (default 30)"}
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
                "file": {"type": "string", "description": "Nome file CSV (opzionale)"}
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
                "app": {"type": "string", "enum": ["App 1", "App 2", "App 3"]}
            },
            "required": ["app"],
        },
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
        return "Log non trovato. Il supervisor non è ancora avviato."
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
            body = "\n".join(",".join(str(v) for v in r.values()) for r in rows[:8])
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
        return "\n".join(results) + "\n\nSetup:\n" + (r.stdout or "") + (r.stderr or "")
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
    urls = {"App 1": "http://localhost:8601", "App 2": "http://localhost:8602",
            "App 3": "http://localhost:8603"}
    url = urls.get(app)
    if not url:
        return f"App sconosciuta: {app}"
    webbrowser.open(url)
    return f"Browser aperto su {url}"


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
        return f"Strumento sconosciuto: {name}"
    except Exception as e:
        return f"Errore {name}: {e}"


# ── Claude agentic loop ─────────────────────────────────────────────────────

def run_agent(message: str, api_key: str, history: list) -> tuple[str, list]:
    """Returns (reply_text, updated_history)."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    messages = history + [{"role": "user", "content": message}]

    for _ in range(10):  # max 10 tool rounds
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        if resp.stop_reason == "end_turn":
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            new_hist = messages + [{"role": "assistant", "content": resp.content}]
            return text, new_hist[-30:]
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
        self.root.geometry("620x700")
        self.root.configure(bg=self.BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.minsize(400, 500)

        # Header
        hdr = tk.Frame(self.root, bg="#111113", pady=8)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="🤖  Agente Magic Dream", bg="#111113",
                 fg=self.TEXT, font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT, padx=12)

        self._status_lbl = tk.Label(hdr, text="● avvio…", bg="#111113",
                                    fg="#ffcc00", font=("Segoe UI", 10))
        self._status_lbl.pack(side=tk.RIGHT, padx=12)

        # Quick buttons
        btn_bar = tk.Frame(self.root, bg=self.BG, pady=4)
        btn_bar.pack(fill=tk.X, padx=8)
        for label, cmd in [
            ("🔍 Controlla", lambda: self._send("Controlla tutte le app e dimmi lo stato.")),
            ("📋 Log", lambda: self._send("Mostrami gli ultimi log.")),
            ("⬇️ Aggiorna", lambda: self._send("Aggiorna Magic Dream da GitHub.")),
            ("🌐 Apri App3", lambda: self._send("Apri App3 nel browser.")),
        ]:
            tk.Button(
                btn_bar, text=label, command=cmd,
                bg="#3a3a3c", fg=self.TEXT, relief=tk.FLAT,
                font=("Segoe UI", 9), padx=8, pady=4, cursor="hand2",
                activebackground="#48484a", activeforeground=self.TEXT,
            ).pack(side=tk.LEFT, padx=3)

        # Key button
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
        self._chat.tag_config("user_hdr", foreground="#0a84ff",
                              font=("Segoe UI", 9, "bold"))
        self._chat.tag_config("user_txt", foreground=self.TEXT,
                              font=("Segoe UI", 11), lmargin1=16, lmargin2=16)
        self._chat.tag_config("agent_hdr", foreground="#30d158",
                              font=("Segoe UI", 9, "bold"))
        self._chat.tag_config("agent_txt", foreground=self.TEXT,
                              font=("Segoe UI", 11), lmargin1=16, lmargin2=16)
        self._chat.tag_config("thinking", foreground="#636366",
                              font=("Segoe UI", 10, "italic"), lmargin1=16)

        # Input row
        inp_frame = tk.Frame(self.root, bg=self.BG, pady=8)
        inp_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

        self._entry = tk.Entry(
            inp_frame, bg=self.INPUT_BG, fg=self.TEXT, insertbackground=self.TEXT,
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
        threading.Thread(target=self._agent_thread, args=(message,), daemon=True).start()

    def _agent_thread(self, message: str) -> None:
        if not self.api_key:
            self.msg_queue.put(("agent",
                "⚠️ Nessuna API key. Clicca '🔑 API Key' per inserirla."))
            return
        self.msg_queue.put(("thinking", "⏳ sto elaborando…"))
        try:
            reply, new_hist = run_agent(message, self.api_key, self.history)
            self.history = new_hist
            self.msg_queue.put(("agent", reply))
        except Exception as e:
            self.msg_queue.put(("agent", f"❌ Errore: {e}"))

    # ── Queue processing ────────────────────────────────────────────────────

    def _schedule_queue_check(self) -> None:
        self.root.after(200, self._check_queue)

    def _check_queue(self) -> None:
        try:
            while True:
                kind, data = self.msg_queue.get_nowait()
                if kind == "thinking":
                    # Remove previous thinking line if present
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
        # Find and delete thinking lines
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
            self.msg_queue.put(("agent",
                "Ciao! Sono il tuo agente Magic Dream.\n\n"
                "⚠️ Inserisci la tua API Key Anthropic (clicca '🔑 API Key') "
                "per attivarmi completamente.\n\n"
                "Senza chiave posso mostrare solo lo stato base delle app."))
            # Show basic status anyway
            status = tool_check_status()
            self.msg_queue.put(("agent", "Stato attuale:\n" + status))
            return
        # Ask agent to do an autonomous startup check
        threading.Thread(
            target=self._agent_thread,
            args=("Sei appena stato avviato. Controlla lo stato di tutte le app e dimmi se tutto è a posto. Sii breve.",),
            daemon=True,
        ).start()

    def _monitor_loop(self) -> None:
        time.sleep(STARTUP_DELAY + 30)  # give startup check time to finish
        while True:
            time.sleep(MONITOR_INTERVAL)
            offline = [n for n, p in PORTS.items() if not _health(p)]
            if offline:
                newly_offline = set(offline) - self._offline_reported
                if newly_offline and self.api_key:
                    self._offline_reported.update(newly_offline)
                    msg = f"⚠️ Rilevato: {', '.join(newly_offline)} non risponde. Verifico."
                    self.msg_queue.put(("agent", msg))
                    problem = f"{', '.join(newly_offline)} risulta offline. Controlla i log e dimmi cosa sta succedendo. Il supervisor dovrebbe riavviarle automaticamente — conferma che stia funzionando."
                    threading.Thread(
                        target=self._agent_thread, args=(problem,), daemon=True
                    ).start()
            else:
                # Clear offline set when all back online
                if self._offline_reported:
                    self._offline_reported.clear()
                    self.msg_queue.put(("agent", "✅ Tutte le app sono tornate online."))
            # Update status dot
            all_ok = not offline
            dot = "● tutto ok" if all_ok else f"● {len(offline)} offline"
            color = "#30d158" if all_ok else "#ff453a"
            self.msg_queue.put(("status", (dot, color)))

    # ── API key dialog ──────────────────────────────────────────────────────

    def _ask_api_key(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("API Key Anthropic")
        win.geometry("480x180")
        win.configure(bg=self.BG)
        win.grab_set()

        tk.Label(win, text="Incolla qui la tua API Key Anthropic:",
                 bg=self.BG, fg=self.TEXT, font=("Segoe UI", 11)).pack(pady=(20, 6))
        tk.Label(win, text="(la trovi su console.anthropic.com → API Keys)",
                 bg=self.BG, fg="#636366", font=("Segoe UI", 9)).pack()

        entry = tk.Entry(win, show="*", width=50, bg=self.INPUT_BG,
                         fg=self.TEXT, insertbackground=self.TEXT,
                         font=("Segoe UI", 11), relief=tk.FLAT, bd=6)
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

        tk.Button(win, text="Salva", command=save,
                  bg=self.BUBBLE_USER, fg="white", relief=tk.FLAT,
                  font=("Segoe UI", 11), padx=20, pady=6).pack()
        entry.focus()
        entry.bind("<Return>", lambda _: save())

    # ── Close ───────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    AgentApp().run()
