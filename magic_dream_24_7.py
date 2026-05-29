"""
Magic Dream 24/7 local supervisor.

Keeps App 1, App 2, App 3, and Magic Lab alive while this script is running.
This touches only the Magic Dream copy and uses ports 8601, 8602, 8603.

All three apps start in parallel so the browser opens faster.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = ROOT_DIR / "app1-app2-dashboard" / "lotto-dashboard"
APP3_DIR = ROOT_DIR / "app3-lifecycle"
MAGIC_LAB_SCRIPT = ROOT_DIR / "magic_experiment_lab.py"
LOG_PATH = ROOT_DIR / "magic_dream_24_7.log"

CHECK_INTERVAL_SECONDS = 20
FAILS_BEFORE_RESTART = 3
STARTUP_GRACE_SECONDS = 60

APPS = {
    "App 1": {
        "script": DASHBOARD_DIR / "app.py",
        "cwd": DASHBOARD_DIR,
        "port": 8601,
        "open_browser": True,
        "browser_delay": 0,
    },
    "App 2": {
        "script": DASHBOARD_DIR / "app2.py",
        "cwd": DASHBOARD_DIR,
        "port": 8602,
        "open_browser": True,
        "browser_delay": 2,
    },
    "App 3": {
        "script": APP3_DIR / "app3.py",
        "cwd": APP3_DIR,
        "port": 8603,
        "open_browser": True,
        "browser_delay": 4,
    },
}

WORKERS = {
    "Magic Lab": {
        "script": MAGIC_LAB_SCRIPT,
        "args": [
            "--loop",
            "--interval-minutes",
            "180",
            "--limit",
            "0",
            "--warmup",
            "120",
            "--freq-window",
            "100",
            "--keep-top",
            "5",
        ],
        "cwd": ROOT_DIR,
        "log": ROOT_DIR / "magic_lab_worker.log",
    },
}


def now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    line = f"[{now()}] {message}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def health_url(port: int) -> str:
    return f"http://localhost:{port}/_stcore/health"


def app_url(port: int) -> str:
    return f"http://localhost:{port}"


def is_healthy(port: int, timeout: int = 3) -> bool:
    try:
        with urllib.request.urlopen(health_url(port), timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _launch_process(name: str, cfg: dict) -> subprocess.Popen | None:
    """Start the Streamlit/Python process. Returns None if script missing."""
    script = Path(cfg["script"])
    cwd = Path(cfg["cwd"])
    port = int(cfg["port"])

    if not script.exists():
        log(f"ATTENZIONE: {name} script non trovato: {script}  — saltato")
        return None

    log_file = ROOT_DIR / f"{name.lower().replace(' ', '_')}_streamlit.log"
    stream = log_file.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(script),
            "--server.port",
            str(port),
            "--server.headless",
            "true",
        ],
        cwd=str(cwd),
        stdout=stream,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    proc._magic_log_stream = stream
    log(f"Avviato {name} sulla porta {port}")
    return proc


def _wait_for_health(name: str, cfg: dict, proc: subprocess.Popen | None, opened: set[str]) -> None:
    """Wait until app is healthy, then open browser. Runs in a thread."""
    if proc is None:
        return
    port = int(cfg["port"])
    deadline = time.time() + STARTUP_GRACE_SECONDS
    while time.time() < deadline:
        if proc.poll() is not None:
            log(f"{name} si è fermato durante l'avvio (codice {proc.returncode})")
            return
        if is_healthy(port):
            log(f"{name} pronto su {app_url(port)}")
            if cfg.get("open_browser") and name not in opened:
                delay = cfg.get("browser_delay", 0)
                if delay:
                    time.sleep(delay)
                webbrowser.open(app_url(port))
                opened.add(name)
            return
        time.sleep(2)
    log(f"{name} non ha risposto entro {STARTUP_GRACE_SECONDS}s — verrà monitorato")


def start_app(name: str, cfg: dict, opened: set[str]) -> subprocess.Popen | None:
    """Start app and wait for health in a background thread (non-blocking)."""
    proc = _launch_process(name, cfg)
    t = threading.Thread(target=_wait_for_health, args=(name, cfg, proc, opened), daemon=True)
    t.start()
    return proc


def stop_app(name: str, proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        log(f"Fermo {name}")
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    stream = getattr(proc, "_magic_log_stream", None)
    if stream:
        try:
            stream.close()
        except Exception:
            pass


def start_worker(name: str, cfg: dict) -> subprocess.Popen | None:
    script = Path(cfg["script"])
    if not script.exists():
        log(f"ATTENZIONE: {name} worker script non trovato: {script} — Magic Lab non avviato")
        return None
    log_file = Path(cfg["log"])
    log(f"Avvio {name}: {script}")
    stream = log_file.open("a", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(script), *cfg.get("args", [])],
        cwd=str(cfg["cwd"]),
        stdout=stream,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    proc._magic_log_stream = stream
    return proc


def main() -> int:
    log("=" * 60)
    log("Magic Dream 24/7 supervisor in avvio")
    log(f"Cartella: {ROOT_DIR}")
    log("Porte: App1=8601  App2=8602  App3=8603")
    log("App 1 → http://localhost:8601")
    log("App 2 → http://localhost:8602")
    log("App 3 → http://localhost:8603  (si apre nel browser)")
    log("Magic Lab → avvio in background, prima simulazione entro 3 minuti")
    log("=" * 60)

    opened: set[str] = set()
    procs: dict[str, subprocess.Popen | None] = {}
    fails: dict[str, int] = {name: 0 for name in APPS}

    # Start all apps in parallel (non-blocking)
    for name, cfg in APPS.items():
        procs[name] = start_app(name, cfg, opened)

    # Start Magic Lab worker
    for name, cfg in WORKERS.items():
        procs[name] = start_worker(name, cfg)

    log("Tutte le app avviate — attesa health check in background…")
    log("Se vedi avvisi 'Magic Lab non pronto' in App3: normale per i primi 2-3 minuti.")

    try:
        while True:
            for name, cfg in APPS.items():
                port = int(cfg["port"])
                proc = procs.get(name)
                dead = proc is None or proc.poll() is not None
                healthy = False if dead else is_healthy(port)

                if proc is None:
                    # Script was missing at startup — skip silently
                    continue

                if dead:
                    log(f"{name} non è in esecuzione")
                    fails[name] = FAILS_BEFORE_RESTART
                elif healthy:
                    fails[name] = 0
                else:
                    fails[name] += 1
                    log(f"{name} health check fallito ({fails[name]}/{FAILS_BEFORE_RESTART})")

                if fails[name] >= FAILS_BEFORE_RESTART:
                    stop_app(name, proc)
                    procs[name] = start_app(name, cfg, opened)
                    fails[name] = 0

            for name, cfg in WORKERS.items():
                proc = procs.get(name)
                if proc is None:
                    continue
                if proc.poll() is not None:
                    code = proc.returncode
                    log(f"{name} non è in esecuzione (codice={code}); riavvio")
                    stop_app(name, proc)
                    procs[name] = start_worker(name, cfg)

            time.sleep(CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log("Supervisor interrotto dall'utente")
    finally:
        for name, proc in procs.items():
            stop_app(name, proc)
        log("Magic Dream 24/7 supervisor fermato")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
