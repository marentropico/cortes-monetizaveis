"""YouTube video downloader powered by YtoWave's yt-dlp binary discovery."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from src import INPUT_DIR, PROJECT_ROOT
from src.ffmpeg_utils import get_ffmpeg_path

YTOWAVE_DOWNLOAD_URL = "https://marentropico.github.io/ytowave/"


def _candidate_yt_dlp_paths() -> list[Path]:
    candidates: list[Path] = []

    env_path = os.environ.get("YT_DLP_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))

    env_bin = os.environ.get("YTOWAVE_BIN_DIR", "").strip()
    if env_bin:
        candidates.append(Path(env_bin) / "yt-dlp.exe")
        candidates.append(Path(env_bin) / "yt-dlp")

    # Relative sibling (e.g. Desktop/ytowave alongside Desktop/Cortes Monetizaveis)
    candidates.append(PROJECT_ROOT.parent / "ytowave" / "bin" / "yt-dlp.exe")

    # Standard Windows user/system locations
    local_app = os.environ.get("LOCALAPPDATA", "")
    prog_files = os.environ.get("ProgramFiles", "")
    prog_x86 = os.environ.get("ProgramFiles(x86)", "")
    user_prof = os.environ.get("USERPROFILE", "")

    for base in filter(None, [local_app, prog_files, prog_x86]):
        b = Path(base)
        for app_dir in ("YtoWave", "ytowave", "Programs/YtoWave", "Programs/ytowave"):
            candidates.extend(
                [
                    b / app_dir / "bin" / "yt-dlp.exe",
                    b / app_dir / "resources" / "bin" / "yt-dlp.exe",
                    b / app_dir / "resources" / "app.asar.unpacked" / "bin" / "yt-dlp.exe",
                ]
            )

    if user_prof:
        up = Path(user_prof)
        for desk in ("Desktop", "OneDrive/Desktop", "Downloads"):
            candidates.append(up / desk / "ytowave" / "bin" / "yt-dlp.exe")

    return candidates


def find_yt_dlp() -> str | None:
    """Locate yt-dlp executable in PATH or YtoWave installation directories."""
    for name in ("yt-dlp", "yt-dlp.exe"):
        found = shutil.which(name)
        if found and Path(found).is_file():
            return str(Path(found).resolve())

    for cand in _candidate_yt_dlp_paths():
        try:
            if cand.is_file():
                return str(cand.resolve())
        except OSError:
            continue

    return None


def get_downloader_status() -> dict[str, Any]:
    yt_dlp = find_yt_dlp()
    return {
        "available": yt_dlp is not None,
        "yt_dlp_path": yt_dlp or "",
        "download_page_url": YTOWAVE_DOWNLOAD_URL,
    }


def _sanitize_filename_template() -> str:
    return "%(title).90B.%(ext)s"


def download_youtube_video(
    url: str,
    quality: str = "1080p",
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    """Download a YouTube video directly into input/ as MP4 (H.264/AAC preferred)."""
    clean_url = url.strip()
    if not clean_url or not re.match(r"^https?://", clean_url, re.IGNORECASE):
        raise ValueError("Informe uma URL válida começando com http:// ou https://.")

    yt_dlp = find_yt_dlp()
    if not yt_dlp:
        raise FileNotFoundError(
            "yt-dlp.exe não encontrado. Instale o YtoWave e reabra o aplicativo."
        )

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = get_ffmpeg_path()

    # Prefer H.264 (avc1) + AAC (mp4a) for fast OpenCV/MediaPipe/FFmpeg processing
    if quality == "720p":
        fmt = "bv*[height<=720][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=720]+ba/b[height<=720]/b"
    elif quality == "best":
        fmt = "bv*[vcodec^=avc1]+ba[acodec^=mp4a]/bv*+ba/b"
    else:  # 1080p default
        fmt = "bv*[height<=1080][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=1080]+ba/b[height<=1080]/b"

    out_tmpl = str(INPUT_DIR / _sanitize_filename_template())
    cmd = [
        yt_dlp,
        "--no-playlist",
        "--newline",
        "--progress",
        "--windows-filenames",
        "--restrict-filenames",
        "-f",
        fmt,
        "--merge-output-format",
        "mp4",
        "--ffmpeg-location",
        str(Path(ffmpeg_path).parent),
        "-o",
        out_tmpl,
        "--print",
        "after_move:filepath",
    ]
    if shutil.which("node"):
        cmd.extend(["--js-runtimes", "node"])
    cmd.append(clean_url)

    if progress_callback:
        progress_callback(f"🌐 Iniciando download ({quality}) via {Path(yt_dlp).name}...")

    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
    )

    final_path: Path | None = None
    last_lines: list[str] = []
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.strip()
        if not line:
            continue
        last_lines.append(line)
        if len(last_lines) > 20:
            last_lines = last_lines[-20:]

        candidate = Path(line)
        if candidate.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"} and candidate.is_file():
            final_path = candidate

        if progress_callback:
            if "[download]" in line and "%" in line:
                m = re.search(r"(\d+(?:\.\d+)?%)", line)
                pct = m.group(1) if m else ""
                progress_callback(f"⬇️ Baixando ({pct}): {line}")
            elif line.startswith("[Merger]") or line.startswith("[VideoRemuxer]"):
                progress_callback(f"🔧 Finalizando MP4: {line}")
            elif line.startswith("ERROR:"):
                progress_callback(f"❌ {line}")

    rc = proc.wait()
    if rc != 0:
        err_tail = " | ".join(last_lines[-3:])
        raise RuntimeError(f"Falha no yt-dlp (código {rc}): {err_tail}")

    if final_path is None or not final_path.is_file():
        mp4s = sorted(INPUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if mp4s:
            final_path = mp4s[0]
        else:
            raise RuntimeError("Download concluído, mas o arquivo MP4 final não foi localizado em input/.")

    if progress_callback:
        progress_callback(f"✅ Vídeo salvo em input/: {final_path.name}")

    return final_path
