"""Standalone desktop window launcher for Hard Cleeps Studio 9:16."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
PROFILE_DIR = ROOT / "temp" / "studio-app-profile"
PYTHON_EXE = ROOT / ".venv" / "Scripts" / "python.exe"


def _find_app_browser() -> str | None:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    for name in ("msedge", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _wait_for_url(url: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.35)
    return False


def _open_standalone_window(url: str) -> subprocess.Popen[bytes] | None:
    browser = _find_app_browser()
    if browser:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        return subprocess.Popen(
            [
                browser,
                f"--app={url}",
                "--window-size=1440,920",
                f"--user-data-dir={PROFILE_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
        )
    webbrowser.open(url)
    return None


def _free_port_if_busy(port: int) -> None:
    """Terminate any stale backend/ffmpeg tree still listening on the target port."""
    if os.name != "nt":
        return
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        pids: set[str] = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] == "LISTENING":
                pid = parts[4]
                if pid.isdigit() and int(pid) > 0 and int(pid) != os.getpid():
                    pids.add(pid)
        for pid in pids:
            print(f"[Studio] Encerrando instância anterior na porta {port} (PID {pid})...")
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", pid],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Hard Cleeps Studio Standalone Launcher")
    parser.add_argument("--dev", action="store_true", help="Run Vite HMR dev server + FastAPI")
    parser.add_argument("--port", type=int, default=8765, help="FastAPI backend port")
    args = parser.parse_args()

    py = str(PYTHON_EXE) if PYTHON_EXE.is_file() else sys.executable
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    procs: list[subprocess.Popen[bytes]] = []

    def _cleanup_all(*_args) -> None:
        for p in procs:
            if p.poll() is None:
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    else:
                        p.send_signal(signal.SIGTERM)
                except Exception:
                    pass

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, lambda *_a: (_cleanup_all(), sys.exit(0)))
            except Exception:
                pass

    try:
        if not args.dev and not DIST_DIR.is_dir():
            print("[Studio] Build do frontend não encontrado. Gerando build de produção...")
            npm_cmd = ["cmd", "/c", "npm", "run", "build"] if os.name == "nt" else ["npm", "run", "build"]
            subprocess.run(npm_cmd, cwd=str(FRONTEND_DIR), check=True)

        _free_port_if_busy(args.port)
        print(f"[Studio] Iniciando Backend FastAPI na porta {args.port}...")
        backend_proc = subprocess.Popen(
            [py, "-m", "uvicorn", "backend.server:app", "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=str(ROOT),
            env=env,
        )
        procs.append(backend_proc)

        if not _wait_for_url(f"http://127.0.0.1:{args.port}/api/health", timeout=25.0):
            print("[Studio] Erro: Backend não respondeu a tempo.")
            return

        target_url = f"http://127.0.0.1:{args.port}"
        if args.dev:
            print("[Studio] Iniciando Frontend Vite HMR na porta 5173...")
            npm_dev = ["cmd", "/c", "npm", "run", "dev"] if os.name == "nt" else ["npm", "run", "dev"]
            vite_proc = subprocess.Popen(npm_dev, cwd=str(FRONTEND_DIR), env=env)
            procs.append(vite_proc)
            target_url = "http://127.0.0.1:5173"
            _wait_for_url(target_url, timeout=20.0)

        print(f"[Studio] Abrindo janela standalone: {target_url}")
        print("[Studio] Mantenha este terminal aberto enquanto usa o app (Ctrl+C para encerrar).")
        _open_standalone_window(target_url)

        backend_proc.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        _cleanup_all()


if __name__ == "__main__":
    main()
