"""
agente_magic.py — Agente AI autonomo per Magic Dream.

Avvia con:
    streamlit run agente_magic.py --server.port 8604

L'agente usa Claude claude-sonnet-4-6 con tool use per monitorare le tre app
Streamlit (porte 8601, 8602, 8603), leggere log, aggiornare file e aprire
il browser. L'utente interagisce in italiano.
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

import anthropic
import streamlit as st

# ---------------------------------------------------------------------------
# Percorsi
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
LOG_PATH = ROOT_DIR / "magic_dream_24_7.log"
MAGIC_LAB_DIR = ROOT_DIR / "magic_lab"
API_KEY_FILE = ROOT_DIR / "anthropic_api_key.txt"

# ---------------------------------------------------------------------------
# Configurazione app
# ---------------------------------------------------------------------------
APPS_INFO = {
    "App 1": {"port": 8601, "desc": "Dashboard principale"},
    "App 2": {"port": 8602, "desc": "Dashboard lotto"},
    "App 3": {"port": 8603, "desc": "Lifecycle Magic Dream"},
}

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096

# URL base per aggiornamenti (stesso di AGGIORNA.bat)
UPDATE_BASE_URL = (
    "https://raw.githubusercontent.com/Cigolone84/"
    "https-your_pat-github.com-Cigolone84-memecoin-bot/"
    "claude/explore-repo-structure-vp60l"
)
UPDATE_FILES = [
    "magic_dream_24_7.py",
    "magic_experiment_lab.py",
    "setup_magic_dream.py",
    "AVVIA_MAGIC_DREAM.bat",
    "magic_dream_app3.py",
]

# ---------------------------------------------------------------------------
# Prompt di sistema
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """Sei l'agente autonomo di Magic Dream.
Monitora 3 app Streamlit:
- App 1 (porta 8601): App principale
- App 2 (porta 8602): Dashboard lotto
- App 3 (porta 8603): Lifecycle Magic Dream

Hai accesso a strumenti per:
- Controllare lo stato delle app (check_status)
- Leggere i log (read_log)
- Consultare i CSV di Magic Lab (read_magic_lab)
- Scaricare aggiornamenti da GitHub (run_update)
- Eseguire il setup (run_setup)
- Aprire il browser (open_browser)

La cartella di Magic Dream è la cartella padre di questo script.
Le app sono gestite dal supervisore magic_dream_24_7.py.
Magic Lab (magic_experiment_lab.py) genera file CSV di strategia nella sottocartella magic_lab/.

Quando ti viene chiesto qualcosa, esegui le azioni necessarie in modo autonomo,
segnala i problemi trovati e suggerisci soluzioni.
Rispondi sempre in italiano, in modo conciso e chiaro.
"""

# ---------------------------------------------------------------------------
# Definizione degli strumenti per Claude
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_status",
        "description": (
            "Controlla lo stato di salute delle tre app Streamlit sulle porte 8601, 8602, 8603. "
            "Restituisce un dizionario con il nome dell'app e lo stato 'online' o 'offline'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_log",
        "description": (
            "Legge le ultime N righe del file di log magic_dream_24_7.log. "
            "Utile per diagnosticare problemi e vedere eventi recenti."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lines": {
                    "type": "integer",
                    "description": "Numero di righe da leggere dalla fine del log. Default: 50.",
                    "default": 50,
                }
            },
            "required": [],
        },
    },
    {
        "name": "read_magic_lab",
        "description": (
            "Elenca i file CSV nella cartella magic_lab e mostra le prime righe di ciascuno. "
            "Utile per vedere le strategie generate da Magic Lab."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "preview_rows": {
                    "type": "integer",
                    "description": "Numero di righe di anteprima per ogni CSV. Default: 5.",
                    "default": 5,
                }
            },
            "required": [],
        },
    },
    {
        "name": "run_update",
        "description": (
            "Scarica i file aggiornati da GitHub (come AGGIORNA.bat) e poi esegue "
            "python setup_magic_dream.py. Restituisce l'output del processo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "run_setup",
        "description": (
            "Esegue python setup_magic_dream.py nella cartella di Magic Dream. "
            "Utile per re-inizializzare le cartelle e copiare i file necessari."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "open_browser",
        "description": (
            "Apre un URL nel browser predefinito. "
            "Solo URL localhost sono permessi (es. http://localhost:8601)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL da aprire, deve iniziare con http://localhost.",
                }
            },
            "required": ["url"],
        },
    },
]

# ---------------------------------------------------------------------------
# Implementazione degli strumenti
# ---------------------------------------------------------------------------

def _is_healthy(port: int, timeout: int = 3) -> bool:
    """Controlla se un'app Streamlit risponde sull'endpoint di health."""
    try:
        url = f"http://localhost:{port}/_stcore/health"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def tool_check_status() -> dict[str, str]:
    """Controlla lo stato delle 3 app e restituisce un dizionario nome→stato."""
    result: dict[str, str] = {}
    for name, info in APPS_INFO.items():
        port = info["port"]
        status = "online" if _is_healthy(port) else "offline"
        result[name] = status
    return result


def tool_read_log(lines: int = 50) -> str:
    """Legge le ultime N righe del file di log."""
    if not LOG_PATH.exists():
        return f"File di log non trovato: {LOG_PATH}"
    try:
        with LOG_PATH.open("r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
        tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
        content = "".join(tail)
        if not content.strip():
            return "Il log è vuoto."
        return content
    except Exception as exc:
        return f"Errore lettura log: {exc}"


def tool_read_magic_lab(preview_rows: int = 5) -> str:
    """Elenca i CSV in magic_lab e mostra le prime righe."""
    if not MAGIC_LAB_DIR.exists():
        return f"Cartella magic_lab non trovata: {MAGIC_LAB_DIR}"

    csv_files = sorted(MAGIC_LAB_DIR.glob("*.csv"))
    if not csv_files:
        return "Nessun file CSV trovato nella cartella magic_lab."

    parts: list[str] = [f"Trovati {len(csv_files)} file CSV in magic_lab:\n"]
    for csv_path in csv_files:
        parts.append(f"\n--- {csv_path.name} ---")
        try:
            with csv_path.open("r", encoding="utf-8", errors="replace") as fh:
                rows = []
                for i, line in enumerate(fh):
                    if i >= preview_rows + 1:  # +1 per intestazione
                        break
                    rows.append(line.rstrip())
            parts.append("\n".join(rows))
            size_kb = csv_path.stat().st_size / 1024
            parts.append(f"(Dimensione: {size_kb:.1f} KB)")
        except Exception as exc:
            parts.append(f"Errore lettura: {exc}")

    return "\n".join(parts)


def tool_run_update() -> str:
    """Scarica file da GitHub e poi esegue setup_magic_dream.py."""
    output_parts: list[str] = []

    # Costruisce il comando PowerShell per il download (stesso di AGGIORNA.bat)
    ps_parts = []
    for fname in UPDATE_FILES:
        url = f"{UPDATE_BASE_URL}/{fname}"
        out_path = str(ROOT_DIR / fname).replace("\\", "\\\\")
        ps_parts.append(
            f"try {{ Write-Host 'Scarico {fname}...'; "
            f"Invoke-WebRequest -Uri '{url}' -OutFile '{out_path}' -UseBasicParsing; "
            f"Write-Host '  OK' }} "
            f"catch {{ Write-Host \"  ERRORE: $_\" }}"
        )
    ps_script = "; ".join(ps_parts)

    # Su Windows usa PowerShell, altrimenti usa curl/wget
    if sys.platform == "win32":
        cmd_download = ["powershell", "-NoProfile", "-Command", ps_script]
    else:
        # Su Linux/Mac usa wget o curl come fallback
        download_lines = []
        for fname in UPDATE_FILES:
            url = f"{UPDATE_BASE_URL}/{fname}"
            out_path = ROOT_DIR / fname
            download_lines.append(
                f"echo 'Scarico {fname}...' && "
                f"wget -q -O '{out_path}' '{url}' && echo '  OK' || echo '  ERRORE'"
            )
        cmd_download = ["bash", "-c", " && ".join(download_lines)]

    try:
        result = subprocess.run(
            cmd_download,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = result.stdout or ""
        err = result.stderr or ""
        output_parts.append("=== Download da GitHub ===")
        if out:
            output_parts.append(out)
        if err:
            output_parts.append(f"[stderr] {err}")
    except subprocess.TimeoutExpired:
        output_parts.append("ERRORE: timeout durante il download.")
    except Exception as exc:
        output_parts.append(f"ERRORE download: {exc}")

    # Esegui setup_magic_dream.py
    output_parts.append("\n=== Esecuzione setup_magic_dream.py ===")
    setup_result = _run_setup()
    output_parts.append(setup_result)

    return "\n".join(output_parts)


def _run_setup() -> str:
    """Esegue setup_magic_dream.py e restituisce l'output."""
    setup_script = ROOT_DIR / "setup_magic_dream.py"
    if not setup_script.exists():
        return f"setup_magic_dream.py non trovato in {ROOT_DIR}"
    try:
        result = subprocess.run(
            [sys.executable, str(setup_script)],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = result.stdout or ""
        err = result.stderr or ""
        combined = out
        if err:
            combined += f"\n[stderr] {err}"
        return combined if combined.strip() else "Setup completato (nessun output)."
    except subprocess.TimeoutExpired:
        return "ERRORE: timeout durante il setup."
    except Exception as exc:
        return f"ERRORE setup: {exc}"


def tool_run_setup() -> str:
    """Wrapper pubblico per run_setup."""
    return _run_setup()


def tool_open_browser(url: str) -> str:
    """Apre un URL localhost nel browser predefinito."""
    if not url.startswith("http://localhost"):
        return f"ERRORE: solo URL localhost sono permessi. Ricevuto: {url}"
    try:
        webbrowser.open(url)
        return f"Browser aperto su: {url}"
    except Exception as exc:
        return f"ERRORE apertura browser: {exc}"


# ---------------------------------------------------------------------------
# Dispatcher degli strumenti
# ---------------------------------------------------------------------------

def execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Esegue lo strumento richiesto e restituisce il risultato come stringa."""
    if tool_name == "check_status":
        result = tool_check_status()
        lines = ["Stato delle app:"]
        for app_name, status in result.items():
            icon = "✅" if status == "online" else "❌"
            port = APPS_INFO[app_name]["port"]
            desc = APPS_INFO[app_name]["desc"]
            lines.append(f"  {icon} {app_name} (porta {port}, {desc}): {status}")
        return "\n".join(lines)

    elif tool_name == "read_log":
        lines = tool_input.get("lines", 50)
        return tool_read_log(lines=int(lines))

    elif tool_name == "read_magic_lab":
        preview_rows = tool_input.get("preview_rows", 5)
        return tool_read_magic_lab(preview_rows=int(preview_rows))

    elif tool_name == "run_update":
        return tool_run_update()

    elif tool_name == "run_setup":
        return tool_run_setup()

    elif tool_name == "open_browser":
        url = tool_input.get("url", "")
        return tool_open_browser(url)

    else:
        return f"Strumento sconosciuto: {tool_name}"


# ---------------------------------------------------------------------------
# Recupero API key
# ---------------------------------------------------------------------------

def get_api_key() -> str | None:
    """Restituisce la chiave API: dalla sidebar, dall'env, o dal file."""
    # 1. Dalla sessione Streamlit (inserita dall'utente)
    if st.session_state.get("api_key"):
        return st.session_state["api_key"].strip()
    # 2. Dalla variabile d'ambiente
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key
    # 3. Dal file anthropic_api_key.txt
    if API_KEY_FILE.exists():
        try:
            key = API_KEY_FILE.read_text(encoding="utf-8").strip()
            if key:
                return key
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Loop agentico
# ---------------------------------------------------------------------------

def run_agent_loop(
    client: anthropic.Anthropic,
    user_message: str,
    history: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """
    Esegue il loop agentico completo:
      1. Invia la storia + il messaggio utente a Claude
      2. Se Claude chiama strumenti → esegui → aggiungi risultati → ripeti
      3. Restituisce la risposta finale e la lista dei tool_use log

    Ritorna (testo_risposta, tool_uses_log).
    """
    # Aggiungi il messaggio utente alla storia temporanea
    messages: list[dict[str, Any]] = list(history) + [
        {"role": "user", "content": user_message}
    ]

    tool_uses_log: list[dict[str, Any]] = []

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Aggiungi la risposta dell'assistente alla storia locale
        messages.append({"role": "assistant", "content": response.content})

        # Se stop_reason è "end_turn" o "max_tokens", non ci sono tool da chiamare
        if response.stop_reason in ("end_turn", "max_tokens"):
            # Estrai il testo finale
            text_parts = [
                block.text
                for block in response.content
                if hasattr(block, "text")
            ]
            final_text = "\n".join(text_parts).strip()
            return final_text, tool_uses_log

        # Gestisci le chiamate agli strumenti
        if response.stop_reason == "tool_use":
            tool_results: list[dict[str, Any]] = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input if isinstance(block.input, dict) else {}
                tool_use_id = block.id

                # Log per la UI
                tool_uses_log.append(
                    {
                        "name": tool_name,
                        "input": tool_input,
                        "id": tool_use_id,
                    }
                )

                # Esegui lo strumento
                tool_output = execute_tool(tool_name, tool_input)

                # Aggiorna il log con il risultato
                tool_uses_log[-1]["output"] = tool_output

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": tool_output,
                    }
                )

            # Aggiungi i risultati degli strumenti alla storia
            messages.append({"role": "user", "content": tool_results})
            # Continua il loop
            continue

        # Stop reason non gestito — esci
        text_parts = [
            block.text
            for block in response.content
            if hasattr(block, "text")
        ]
        final_text = "\n".join(text_parts).strip()
        return final_text, tool_uses_log


# ---------------------------------------------------------------------------
# Controllo automatico dello stato
# ---------------------------------------------------------------------------

def run_status_check(client: anthropic.Anthropic) -> None:
    """
    Esegue un controllo completo dello stato e aggiunge il risultato
    alla chat come se fosse una risposta automatica.
    """
    user_msg = (
        "Esegui un controllo completo dello stato: "
        "controlla tutte le app e leggi le ultime 30 righe del log. "
        "Dimmi cosa trovi."
    )

    with st.chat_message("assistant"):
        with st.spinner("Controllo in corso..."):
            try:
                response_text, tool_uses = run_agent_loop(
                    client=client,
                    user_message=user_msg,
                    history=[],
                )
            except anthropic.APIError as exc:
                response_text = f"Errore API durante il controllo: {exc}"
                tool_uses = []
            except Exception as exc:
                response_text = f"Errore inatteso: {exc}"
                tool_uses = []

        # Mostra gli strumenti usati
        if tool_uses:
            with st.expander("Strumenti usati", expanded=False):
                for tu in tool_uses:
                    st.markdown(f"**{tu['name']}**")
                    if tu.get("input"):
                        st.json(tu["input"])
                    if tu.get("output"):
                        st.code(tu["output"], language="text")

        st.markdown(response_text)

    # Aggiungi alla storia della conversazione
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response_text,
            "tool_uses": tool_uses,
            "auto": True,
        }
    )


# ---------------------------------------------------------------------------
# Interfaccia Streamlit
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="Agente Magic Dream",
        page_icon="🤖",
        layout="wide",
    )

    st.title("🤖 Agente Magic Dream")
    st.caption(
        "Agente AI autonomo per monitorare e gestire le app Magic Dream "
        "(porte 8601, 8602, 8603)."
    )

    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------
    with st.sidebar:
        st.header("Configurazione")

        # API key
        st.subheader("Chiave API Anthropic")

        # Mostra da dove viene la chiave (se già trovata)
        env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        file_key = ""
        if API_KEY_FILE.exists():
            try:
                file_key = API_KEY_FILE.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        if env_key:
            st.info("Chiave caricata dalla variabile d'ambiente ANTHROPIC_API_KEY.")
        elif file_key:
            st.info(f"Chiave caricata da: {API_KEY_FILE.name}")

        # Campo di input manuale
        manual_key = st.text_input(
            "Inserisci la chiave API (opzionale se già configurata):",
            type="password",
            value=st.session_state.get("api_key", ""),
            help="La chiave viene tenuta solo in memoria per questa sessione.",
        )
        if manual_key:
            st.session_state["api_key"] = manual_key

        st.divider()

        # Pulsante "Controlla tutto"
        st.subheader("Azioni rapide")
        controlla_tutto = st.button(
            "🔍 Controlla tutto",
            use_container_width=True,
            help="Esegue un controllo completo dello stato delle app e del log.",
        )

        st.divider()

        # Info sulle app
        st.subheader("App monitorate")
        for app_name, info in APPS_INFO.items():
            st.markdown(
                f"- **{app_name}** (porta {info['port']}): {info['desc']}"
            )

        st.divider()
        st.markdown(
            f"**Modello:** {MODEL}  \n"
            f"**Cartella:** `{ROOT_DIR.name}`  \n"
            f"**Log:** `{LOG_PATH.name}`"
        )

    # -----------------------------------------------------------------------
    # Inizializzazione stato sessione
    # -----------------------------------------------------------------------
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "status_checked" not in st.session_state:
        st.session_state.status_checked = False

    # -----------------------------------------------------------------------
    # Recupera la chiave API
    # -----------------------------------------------------------------------
    api_key = get_api_key()

    if not api_key:
        st.warning(
            "Nessuna chiave API Anthropic trovata. "
            "Inseriscila nella barra laterale, oppure imposta la variabile "
            "d'ambiente `ANTHROPIC_API_KEY`, oppure crea il file "
            f"`{API_KEY_FILE.name}` nella stessa cartella dello script."
        )
        st.stop()

    # Crea il client Anthropic
    try:
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as exc:
        st.error(f"Errore durante la creazione del client Anthropic: {exc}")
        st.stop()

    # -----------------------------------------------------------------------
    # Mostra la cronologia dei messaggi
    # -----------------------------------------------------------------------
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            # Mostra strumenti usati (solo per i messaggi dell'assistente)
            if msg["role"] == "assistant" and msg.get("tool_uses"):
                with st.expander("Strumenti usati", expanded=False):
                    for tu in msg["tool_uses"]:
                        st.markdown(f"**{tu['name']}**")
                        if tu.get("input"):
                            st.json(tu["input"])
                        if tu.get("output"):
                            st.code(tu["output"], language="text")
            st.markdown(msg["content"])

    # -----------------------------------------------------------------------
    # Controllo automatico al primo caricamento
    # -----------------------------------------------------------------------
    if not st.session_state.status_checked:
        st.session_state.status_checked = True
        run_status_check(client)
        st.rerun()

    # -----------------------------------------------------------------------
    # Pulsante "Controlla tutto"
    # -----------------------------------------------------------------------
    if controlla_tutto:
        run_status_check(client)
        st.rerun()

    # -----------------------------------------------------------------------
    # Input utente
    # -----------------------------------------------------------------------
    user_input = st.chat_input("Scrivi qui la tua domanda in italiano...")

    if user_input:
        # Mostra il messaggio utente
        with st.chat_message("user"):
            st.markdown(user_input)

        # Aggiungi alla storia
        st.session_state.messages.append(
            {"role": "user", "content": user_input}
        )

        # Costruisci la storia per Claude (solo role+content)
        history_for_claude: list[dict[str, Any]] = []
        for msg in st.session_state.messages[:-1]:  # escludi l'ultimo (appena aggiunto)
            if msg["role"] in ("user", "assistant"):
                history_for_claude.append(
                    {"role": msg["role"], "content": msg["content"]}
                )

        # Esegui il loop agentico
        with st.chat_message("assistant"):
            with st.spinner("Sto elaborando..."):
                try:
                    response_text, tool_uses = run_agent_loop(
                        client=client,
                        user_message=user_input,
                        history=history_for_claude,
                    )
                except anthropic.AuthenticationError:
                    response_text = (
                        "Chiave API non valida. Controlla la chiave nella barra laterale."
                    )
                    tool_uses = []
                except anthropic.RateLimitError:
                    response_text = (
                        "Limite di richieste raggiunto. Attendi qualche momento e riprova."
                    )
                    tool_uses = []
                except anthropic.APIStatusError as exc:
                    response_text = f"Errore API Anthropic (HTTP {exc.status_code}): {exc.message}"
                    tool_uses = []
                except anthropic.APIConnectionError as exc:
                    response_text = f"Errore di connessione all'API: {exc}"
                    tool_uses = []
                except Exception as exc:
                    response_text = f"Errore inatteso: {type(exc).__name__}: {exc}"
                    tool_uses = []

            # Mostra strumenti usati
            if tool_uses:
                with st.expander("Strumenti usati", expanded=True):
                    for tu in tool_uses:
                        st.markdown(f"**{tu['name']}**")
                        if tu.get("input"):
                            st.json(tu["input"])
                        if tu.get("output"):
                            st.code(tu["output"], language="text")

            st.markdown(response_text)

        # Aggiungi alla storia
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": response_text,
                "tool_uses": tool_uses,
            }
        )

        st.rerun()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
