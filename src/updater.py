"""GitHub commit-based auto-updater for Hard Cleeps Studio."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from src import PROJECT_ROOT, TEMP_DIR

UPDATER_CONFIG_FILE = TEMP_DIR / "updater_config.json"
APP_VERSION = "2.0.0"


def load_updater_config() -> dict[str, Any]:
    default = {"auto_update": False, "last_check": None}
    if UPDATER_CONFIG_FILE.is_file():
        try:
            data = json.loads(UPDATER_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**default, **data}
        except Exception:
            pass
    return default


def save_updater_config(auto_update: bool) -> dict[str, Any]:
    cfg = load_updater_config()
    cfg["auto_update"] = bool(auto_update)
    UPDATER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATER_CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def _run_git(args: list[str], timeout: float = 8.0) -> tuple[int, str]:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creation_flags,
            check=False,
        )
        return proc.returncode, (proc.stdout or "").strip()
    except Exception as exc:
        return 1, str(exc)


def get_local_version_info() -> dict[str, str]:
    rc_h, head = _run_git(["rev-parse", "--short", "HEAD"], timeout=3.0)
    rc_b, branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], timeout=3.0)
    rc_r, remote = _run_git(["remote", "get-url", "origin"], timeout=3.0)
    return {
        "version": APP_VERSION,
        "commit": head if rc_h == 0 and head else "local",
        "branch": branch if rc_b == 0 and branch and branch != "HEAD" else "main",
        "remote": remote if rc_r == 0 else "",
    }


def check_for_updates(fetch: bool = True) -> dict[str, Any]:
    """Check origin/<branch> for new commits without blocking offline operation."""
    cfg = load_updater_config()
    info = get_local_version_info()
    branch = info["branch"]
    base: dict[str, Any] = {
        "version": APP_VERSION,
        "current_commit": info["commit"],
        "remote_commit": info["commit"],
        "branch": branch,
        "remote": info["remote"],
        "available": False,
        "commits_ahead": 0,
        "changelog": [],
        "needs_pip": False,
        "needs_frontend_build": False,
        "offline": False,
        "auto_update": bool(cfg.get("auto_update", False)),
    }

    if not (PROJECT_ROOT / ".git").exists() or not info["remote"]:
        base["offline"] = True
        return base

    if fetch:
        rc_f, _ = _run_git(["fetch", "origin", branch, "--quiet"], timeout=10.0)
        if rc_f != 0:
            base["offline"] = True
            return base

    rc_rem, rem_hash = _run_git(["rev-parse", "--short", f"origin/{branch}"], timeout=4.0)
    if rc_rem != 0 or not rem_hash:
        base["offline"] = True
        return base

    rc_cnt, cnt_str = _run_git(["rev-list", "--count", f"HEAD..origin/{branch}"], timeout=4.0)
    ahead = int(cnt_str) if rc_cnt == 0 and cnt_str.isdigit() else 0

    changelog: list[str] = []
    needs_pip = False
    needs_frontend_build = False
    if ahead > 0:
        rc_log, log_str = _run_git(["log", f"HEAD..origin/{branch}", "--oneline", "-n", "15"], timeout=4.0)
        if rc_log == 0 and log_str:
            changelog = [line.strip() for line in log_str.splitlines() if line.strip()]
        rc_diff, diff_str = _run_git(["diff", "--name-only", f"HEAD..origin/{branch}"], timeout=4.0)
        if rc_diff == 0 and diff_str:
            changed = diff_str.splitlines()
            needs_pip = any(f.strip() == "requirements.txt" for f in changed)
            needs_frontend_build = any(f.strip().startswith("frontend/") for f in changed)

    cfg["last_check"] = datetime.now().isoformat(timespec="seconds")
    try:
        UPDATER_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        UPDATER_CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    base.update(
        {
            "remote_commit": rem_hash,
            "available": ahead > 0,
            "commits_ahead": ahead,
            "changelog": changelog,
            "needs_pip": needs_pip,
            "needs_frontend_build": needs_frontend_build,
        }
    )
    return base


def spawn_update_and_restart(branch: str | None = None) -> None:
    """Spawn external PowerShell updater script so running Python/UI files can be updated safely."""
    script_path = PROJECT_ROOT / "installer" / "update_and_restart.ps1"
    if not script_path.is_file():
        raise FileNotFoundError(f"Script de atualização não encontrado: {script_path}")

    target_branch = branch or get_local_version_info()["branch"]
    pid = os.getpid()
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-RepoDir",
        str(PROJECT_ROOT),
        "-Branch",
        target_branch,
        "-WaitPid",
        str(pid),
    ]
    creation_flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), creationflags=creation_flags)
