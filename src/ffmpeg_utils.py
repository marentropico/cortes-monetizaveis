"""FFmpeg discovery, video probing, and hardware H.264 encoder detection utilities."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from src import PROJECT_ROOT


def _candidate_bin_dirs() -> list[Path]:
    """Return candidate directories where full FFmpeg binaries may reside on Windows."""
    candidates: list[Path] = [
        PROJECT_ROOT / "bin",
        Path("C:/ffmpeg/bin"),
        Path("C:/Program Files/ffmpeg/bin"),
    ]

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_links = Path(local_app_data) / "Microsoft" / "WinGet" / "Links"
        if winget_links.exists():
            candidates.append(winget_links)

        winget_pkgs = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.exists():
            for pkg_dir in sorted(winget_pkgs.glob("Gyan.FFmpeg*")):
                for exe in pkg_dir.rglob("ffmpeg.exe"):
                    candidates.append(exe.parent)

    return candidates


def _find_binary(name: str) -> str:
    """Locate ffmpeg or ffprobe executable and ensure its directory is on PATH."""
    exe_name = f"{name}.exe" if os.name == "nt" else name
    found = shutil.which(name)
    if found and "remotion" not in found.lower():
        return found

    for directory in _candidate_bin_dirs():
        candidate = directory / exe_name
        if candidate.is_file():
            dir_str = str(directory)
            current_path = os.environ.get("PATH", "")
            if dir_str.lower() not in current_path.lower():
                os.environ["PATH"] = f"{dir_str}{os.pathsep}{current_path}"
            return str(candidate)

    if found:
        return found

    raise FileNotFoundError(
        f"Binário '{exe_name}' não encontrado no PATH nem nos diretórios WinGet/FFmpeg."
    )


def get_ffmpeg_path() -> str:
    """Return path to ffmpeg executable and inject its folder into PATH."""
    return _find_binary("ffmpeg")


def get_ffprobe_path() -> str:
    """Return path to ffprobe executable and inject its folder into PATH."""
    return _find_binary("ffprobe")


def ensure_ffmpeg_in_path() -> tuple[str, str]:
    """Ensure both ffmpeg and ffprobe are discoverable in PATH."""
    return get_ffmpeg_path(), get_ffprobe_path()


def _parse_fps(raw_fps: str | None) -> float:
    if not raw_fps or raw_fps in ("0/0", "0"):
        return 30.0
    if "/" in raw_fps:
        num, den = raw_fps.split("/", 1)
        try:
            d = float(den)
            return round(float(num) / d, 3) if d != 0 else 30.0
        except ValueError:
            return 30.0
    try:
        return round(float(raw_fps), 3)
    except ValueError:
        return 30.0


def probe_video_info(video_path: str | Path) -> dict[str, Any]:
    """Probe video metadata using ffprobe."""
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Vídeo não encontrado: {path}")

    ffprobe = get_ffprobe_path()
    cmd = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"Falha ao inspecionar vídeo com ffprobe: {proc.stderr.strip()}")

    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    width = int(video_stream.get("width", 0)) if video_stream else 0
    height = int(video_stream.get("height", 0)) if video_stream else 0
    fps = _parse_fps(video_stream.get("r_frame_rate") or video_stream.get("avg_frame_rate")) if video_stream else 30.0
    codec = str(video_stream.get("codec_name", "unknown")) if video_stream else "unknown"

    duration = 0.0
    for cand in (
        fmt.get("duration"),
        video_stream.get("duration") if video_stream else None,
        audio_stream.get("duration") if audio_stream else None,
    ):
        if cand is not None:
            try:
                duration = round(float(cand), 3)
                break
            except (TypeError, ValueError):
                pass

    size_bytes = path.stat().st_size
    return {
        "path": str(path),
        "filename": path.name,
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
        "has_audio": audio_stream is not None,
        "codec": codec,
    }


def _test_h264_encoder(ffmpeg_bin: str, encoder: str) -> bool:
    """Run a tiny null encode to verify whether a hardware/software H.264 encoder works."""
    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "nullsrc=s=256x256:d=0.1",
        "-c:v",
        encoder,
        "-pix_fmt",
        "yuv420p",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


@lru_cache(maxsize=1)
def detect_best_h264_encoder() -> str:
    """Test encoders in order (NVENC, AMF, QSV, libx264) and return the best working one."""
    ffmpeg_bin = get_ffmpeg_path()
    for encoder in ("h264_nvenc", "h264_amf", "h264_qsv", "libx264"):
        if _test_h264_encoder(ffmpeg_bin, encoder):
            return encoder
    return "libx264"


def get_h264_encoder_args(encoder: str | None = None) -> list[str]:
    """Return FFmpeg output video arguments tuned for the selected encoder."""
    chosen = encoder or detect_best_h264_encoder()
    if chosen == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "21", "-pix_fmt", "yuv420p"]
    if chosen == "h264_amf":
        return [
            "-c:v",
            "h264_amf",
            "-quality",
            "balanced",
            "-rc",
            "cqp",
            "-qp_i",
            "21",
            "-qp_p",
            "22",
            "-pix_fmt",
            "yuv420p",
        ]
    if chosen == "h264_qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "21", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def verify_ffmpeg_capabilities() -> dict[str, Any]:
    """Inspect FFmpeg version, subtitle filter availability, and best encoder."""
    ffmpeg_bin = get_ffmpeg_path()
    ffprobe_bin = get_ffprobe_path()
    filters_proc = subprocess.run(
        [ffmpeg_bin, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    filters_text = filters_proc.stdout
    return {
        "ffmpeg_path": ffmpeg_bin,
        "ffprobe_path": ffprobe_bin,
        "has_subtitles_filter": " subtitles " in filters_text or "\tsubtitles\t" in filters_text or " subtitles\n" in filters_text or "subtitles" in filters_text,
        "has_boxblur_filter": "boxblur" in filters_text,
        "best_h264_encoder": detect_best_h264_encoder(),
    }
