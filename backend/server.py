"""FastAPI backend server for Hard Cleeps Studio 9:16."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import (
    INPUT_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
    PROJECTS_TEMP_DIR,
    REMOTION_DIR,
    REPOS_DIR,
    TEMP_DIR,
)
from src.captioner import CAPTION_PRESETS
from src.context_analyzer import analyze_transcript_for_cuts
from src.demo_generator import generate_demo_gameplay
from src.face_detector import generate_layout_preview
from src.face_tracker import (
    clear_pinned_face,
    extract_frame_for_pin,
    get_pinned_face,
    pin_face_from_frame,
)
from src.ffmpeg_utils import probe_video_info, verify_ffmpeg_capabilities
from src.llm_pool import has_active_pool
from src.thumbnail_generator import (
    generate_thumbnails_for_clips,
    list_generated_thumbnails,
    upload_thumbnails_batch,
)
from src.transcriber import GameplayTranscriber
from src.video_editor import VerticalVideoEditor, list_rendered_clips
from src.youtube_analytics import (
    ANALYTICS_CACHE_FILE,
    analyze_performance_with_pool,
    fetch_channel_analytics_api,
    get_saved_youtube_config,
    save_youtube_api_config,
    scrape_studio_analytics_cdp,
)
from src.youtube_downloader import download_youtube_video, get_downloader_status
from src.youtube_publisher import (
    QUEUE_FILE as YT_QUEUE_FILE,
    check_youtube_studio_ready,
    generate_youtube_queue,
    launch_chrome_cdp,
    sync_queue_with_youtube_api,
    upload_queue as yt_upload_queue,
)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"


def _ensure_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, TEMP_DIR, PROJECTS_TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _safe_child(base_dir: Path, rel_path: str) -> Path:
    base_resolved = base_dir.resolve()
    target = (base_resolved / rel_path).resolve()
    if not target.is_relative_to(base_resolved):
        raise HTTPException(status_code=403, detail="Acesso negado ao caminho solicitado.")
    return target


def _media_url_for_output(path_str: str | Path) -> str:
    p = Path(path_str).resolve()
    out_root = OUTPUT_DIR.resolve()
    if p.is_relative_to(out_root):
        rel = p.relative_to(out_root).as_posix()
        return f"/api/media/output/{rel}"
    return ""


def _media_url_for_temp(path_str: str | Path) -> str:
    p = Path(path_str).resolve()
    tmp_root = TEMP_DIR.resolve()
    if p.is_relative_to(tmp_root):
        rel = p.relative_to(tmp_root).as_posix()
        return f"/api/media/temp/{rel}"
    return ""


# ---------------------------------------------------------------------------
# Background Job Manager (Pipeline & YouTube Upload)
# ---------------------------------------------------------------------------


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._current_job_id: str | None = None
        self._active_by_kind: dict[str, str] = {}

    def get_current(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._current_job_id:
                return None
            return dict(self._jobs.get(self._current_job_id, {}))

    def get_all_by_kind(self) -> dict[str, dict[str, Any] | None]:
        with self._lock:
            out: dict[str, dict[str, Any] | None] = {}
            for kind, jid in self._active_by_kind.items():
                j = self._jobs.get(jid)
                out[kind] = dict(j) if j else None
            return out

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def is_running(self) -> bool:
        with self._lock:
            for jid in self._active_by_kind.values():
                j = self._jobs.get(jid)
                if j and j.get("status") == "running":
                    return True
            return False

    def clear_current(self) -> None:
        with self._lock:
            if self.is_running():
                return
            self._current_job_id = None
            self._active_by_kind.clear()

    def create(
        self,
        kind: str,
        title: str,
        queue_total: int = 1,
        current_video: str | None = None,
    ) -> str:
        with self._lock:
            existing_id = self._active_by_kind.get(kind)
            if existing_id:
                cur = self._jobs.get(existing_id)
                if cur and cur.get("status") == "running":
                    raise HTTPException(
                        status_code=409,
                        detail=f"Já existe uma tarefa '{kind}' em andamento: {cur.get('title')}",
                    )
            job_id = uuid.uuid4().hex[:12]
            self._jobs[job_id] = {
                "job_id": job_id,
                "kind": kind,
                "title": title,
                "status": "running",
                "step": "starting",
                "progress": 0,
                "queue_index": 1,
                "queue_total": queue_total,
                "current_video": current_video,
                "logs": [],
                "result": None,
                "error": None,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": None,
            }
            self._current_job_id = job_id
            self._active_by_kind[kind] = job_id
            return job_id

    def set_queue_item(self, job_id: str, queue_index: int, current_video: str | None) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j["queue_index"] = queue_index
            j["current_video"] = current_video

    def append_log(self, job_id: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j["logs"].append(line)
            if len(j["logs"]) > 400:
                j["logs"] = j["logs"][-400:]
            m = re.search(r"(\d{1,3})(?:\.\d+)?%", message)
            if m:
                pct = min(99, max(0, int(m.group(1))))
                if j["kind"] == "pipeline":
                    step = j.get("step", "")
                    if step == "transcribe":
                        j["progress"] = int(pct * 0.35)
                    elif step == "render":
                        j["progress"] = 45 + int(pct * 0.54)
                else:
                    j["progress"] = pct

    def set_step(self, job_id: str, step: str, progress: int | None = None) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j["step"] = step
            if progress is not None:
                j["progress"] = progress

    def finish(self, job_id: str, result: Any = None) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j["status"] = "done"
            j["step"] = "done"
            j["progress"] = 100
            j["result"] = result
            j["finished_at"] = datetime.now().isoformat(timespec="seconds")

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j["status"] = "error"
            j["error"] = error
            j["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Erro: {error}")
            j["finished_at"] = datetime.now().isoformat(timespec="seconds")


jobs = JobManager()


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(title="Hard Cleeps Studio 9:16 API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class DemoVideoRequest(BaseModel):
    language: str = "pt"
    duration: int = 36


class DownloadUrlRequest(BaseModel):
    url: str
    quality: str = "1080p"


class CutsUpdateRequest(BaseModel):
    cuts: list[dict[str, Any]]


class LayoutPreviewRequest(BaseModel):
    video_name: str
    layout_mode: str = "auto"


class PinFrameRequest(BaseModel):
    timestamp: float = 10.0


class PinFaceRequest(BaseModel):
    timestamp: float
    norm_x: float
    norm_y: float


class ClearRecordsRequest(BaseModel):
    clear_input_caches: bool = False


class PipelineRunRequest(BaseModel):
    mode: str = "full"  # full | transcribe | analyze | render
    video_name: str | None = None
    video_names: list[str] | None = None
    language: str = "pt"
    duration_mode: str = "mix"
    max_cuts: int = 0
    model_size: str = "base"
    layout_mode: str = "auto"
    caption_preset: str = "hormozi"
    words_per_line: int = 3
    burn_captions: bool = True
    use_cache: bool = True
    distribute_across_video: bool = True
    skip_existing: bool = False
    use_llm_pool: bool = True
    precision_retranscribe: bool = True
    refine_captions_with_llm: bool = True
    dynamic_face_tracking: bool = True
    face_track_mode: str = "pinned"  # pinned | quick_detect


class QueueItemUpdateRequest(BaseModel):
    video_path: str
    youtube_title: str
    youtube_description: str
    visibility: str = "PUBLIC"


class QueueBulkUpdateRequest(BaseModel):
    items: list[dict[str, Any]]


class YouTubeUploadRequest(BaseModel):
    selected_paths: list[str]
    visibility: str = "PUBLIC"
    skip_posted: bool = True


class ThumbnailsRequest(BaseModel):
    selected_paths: list[str] = []


class AnalyticsConfigRequest(BaseModel):
    api_key: str = ""
    channel_ref: str = ""


# ---------------------------------------------------------------------------
# Health & Diagnostics
# ---------------------------------------------------------------------------


_shutdown_lock = threading.Lock()
_shutdown_timer: threading.Timer | None = None


def _cancel_scheduled_shutdown() -> None:
    global _shutdown_timer
    with _shutdown_lock:
        if _shutdown_timer is not None:
            _shutdown_timer.cancel()
            _shutdown_timer = None


def _execute_shutdown() -> None:
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(os.getpid())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
    os._exit(0)


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    _cancel_scheduled_shutdown()
    _ensure_dirs()
    try:
        caps = verify_ffmpeg_capabilities()
        encoder = caps.get("best_h264_encoder", "libx264")
    except Exception:
        encoder = "libx264"

    return {
        "ok": True,
        "encoder": encoder,
        "pool_active": has_active_pool(),
        "clips_count": len(list_rendered_clips()),
        "current_job": jobs.get_current(),
    }


@app.get("/api/presets")
def api_presets() -> dict[str, Any]:
    return {
        "caption_presets": [
            {"id": k, "label": v.get("label", k)} for k, v in CAPTION_PRESETS.items()
        ],
        "layouts": [
            {"id": "auto", "label": "Automático (3-Zonas: 16:9 Topo + Zoom 9:16 + Rosto Circular)"},
            {"id": "split_screen", "label": "Split-Screen Clássico (Webcam Topo + Gameplay)"},
            {"id": "top_left", "label": "Webcam Superior Esquerda + Gameplay"},
            {"id": "top_right", "label": "Webcam Superior Direita + Gameplay"},
            {"id": "mid_left", "label": "Webcam Centro-Esquerda + Gameplay"},
            {"id": "mid_right", "label": "Webcam Centro-Direita + Gameplay"},
            {"id": "bottom_left", "label": "Webcam Inferior Esquerda + Gameplay"},
            {"id": "bottom_right", "label": "Webcam Inferior Direita + Gameplay"},
            {"id": "blur_bg", "label": "Fundo Desfocado + 16:9 Central"},
            {"id": "center_only", "label": "Crop Central Tela Cheia 9:16"},
        ],
    }


@app.get("/api/diagnostics")
def api_diagnostics() -> dict[str, Any]:
    try:
        caps = verify_ffmpeg_capabilities()
    except Exception as exc:
        caps = {"error": str(exc)}

    try:
        import ctranslate2

        cuda_count = ctranslate2.get_cuda_device_count()
    except Exception:
        cuda_count = 0

    try:
        import mediapipe as mp

        mp_ver = getattr(mp, "__version__", "instalado")
        mp_mode = "solutions" if hasattr(mp, "solutions") else "tasks/opencv-fallback"
    except Exception as exc:
        mp_ver = f"erro: {exc}"
        mp_mode = "unavailable"

    repo_specs = [
        ("faster-whisper", "SYSTRAN/faster-whisper", "Transcrição Whisper CTranslate2 + word timestamps"),
        ("stable-ts", "jianfch/stable-ts", "Alinhamento/estabilização de timestamps e segmentos"),
        ("clipsai", "ClipsAI/clipsai", "Referência TextTiling de segmentação de tópicos"),
        ("auto-captions", "nikhil-reddy05/auto-captions", "Conversão JSON -> legendas dinâmicas .ass"),
        ("auto-subtitle", "m1guelpf/auto-subtitle", "Automação CLI Whisper + FFmpeg subtitles"),
    ]
    repos = []
    for folder, name, role in repo_specs:
        repos.append(
            {
                "name": name,
                "folder": f"repos/{folder}",
                "installed": (REPOS_DIR / folder).is_dir(),
                "role": role,
            }
        )

    return {
        "ffmpeg_path": caps.get("ffmpeg_path", "não encontrado"),
        "ffprobe_path": caps.get("ffprobe_path", "não encontrado"),
        "has_subtitles_filter": bool(caps.get("has_subtitles_filter", False)),
        "best_h264_encoder": caps.get("best_h264_encoder", "desconhecido"),
        "cuda_count": cuda_count,
        "whisper_device": "cuda/float16" if cuda_count > 0 else "cpu/int8",
        "mediapipe_version": mp_ver,
        "mediapipe_mode": mp_mode,
        "remotion_available": (REMOTION_DIR / "package.json").is_file(),
        "remotion_template": (REMOTION_DIR / "src" / "GameplayShortTemplate.tsx").is_file(),
        "repos": repos,
    }


@app.post("/api/system/heartbeat")
def api_system_heartbeat() -> dict[str, bool]:
    _cancel_scheduled_shutdown()
    return {"ok": True}


@app.post("/api/system/shutdown")
def api_system_shutdown() -> dict[str, str]:
    """Schedule graceful shutdown in 4s (cancelled automatically if UI reloads)."""
    global _shutdown_timer
    with _shutdown_lock:
        if _shutdown_timer is not None:
            _shutdown_timer.cancel()
        _shutdown_timer = threading.Timer(4.0, _execute_shutdown)
        _shutdown_timer.daemon = True
        _shutdown_timer.start()
    return {"message": "Shutdown agendado."}


@app.post("/api/system/open-output")
def api_open_output() -> dict[str, str]:
    _ensure_dirs()
    try:
        if os.name == "nt":
            os.startfile(str(OUTPUT_DIR))
        return {"message": f"Pasta aberta: {OUTPUT_DIR}"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/system/clear-records")
def api_clear_records(req: ClearRecordsRequest | None = None) -> dict[str, Any]:
    """Clean outputs, active temp artifacts and stale caches, keeping models/sessions and inspecting input/."""
    _ensure_dirs()
    if jobs.is_running():
        raise HTTPException(
            status_code=409,
            detail="Aguarde a tarefa em andamento terminar antes de limpar os registros.",
        )

    clear_input_caches = bool(req.clear_input_caches) if req else False

    input_files = sorted(
        [
            p
            for p in INPUT_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        ],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    active_names = [p.name for p in input_files]
    active_stems = {p.stem for p in input_files}

    removed_outputs = 0
    for child in OUTPUT_DIR.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            removed_outputs += 1

    (OUTPUT_DIR / "thumbnails").mkdir(parents=True, exist_ok=True)
    for json_name in ("projects_index.json", "youtube_posts_queue.json"):
        jpath = OUTPUT_DIR / json_name
        jpath.write_text("[]", encoding="utf-8")

    removed_temp_files = 0
    for pattern in (
        "transcript.json",
        "cuts.json",
        "layout_preview.jpg",
        "pin_frame.jpg",
        "track_cmds_*.txt",
        "*.ass",
        "*.wav",
        "pip_circle_mask_*.png",
    ):
        for f in TEMP_DIR.glob(pattern):
            if f.is_file():
                f.unlink(missing_ok=True)
                removed_temp_files += 1

    removed_project_caches = 0
    if PROJECTS_TEMP_DIR.is_dir():
        for proj_dir in PROJECTS_TEMP_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            if clear_input_caches or proj_dir.name not in active_stems:
                shutil.rmtree(proj_dir, ignore_errors=True)
                removed_project_caches += 1

    jobs.clear_current()

    if active_names:
        msg = (
            f"Registros limpos! {len(active_names)} vídeo(s) detectado(s) em input/ "
            f"pronto(s) para um novo ciclo."
        )
    else:
        msg = "Registros limpos! Pasta input/ vazia — adicione novos vídeos para começar."

    return {
        "message": msg,
        "input_videos": active_names,
        "removed_outputs": removed_outputs,
        "removed_temp_files": removed_temp_files,
        "removed_project_caches": removed_project_caches,
    }


@app.post("/api/remotion/export")
def api_remotion_export() -> dict[str, Any]:
    cuts_path = TEMP_DIR / "cuts.json"
    if not cuts_path.is_file():
        raise HTTPException(status_code=404, detail="Gere cortes primeiro em temp/cuts.json.")
    cuts = json.loads(cuts_path.read_text(encoding="utf-8"))
    if not cuts:
        raise HTTPException(status_code=400, detail="Nenhum corte em temp/cuts.json.")
    first = cuts[0]
    props = {
        "hookText": first.get("hook_text", "OLHA O QUE ACONTECEU!"),
        "title": first.get("title", "Gameplay_Short"),
        "startSec": first.get("start", 0),
        "endSec": first.get("end", 30),
        "durationType": first.get("duration_type", "30s"),
    }
    out_props = REMOTION_DIR / "props_cut_01.json"
    out_props.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"message": f"Props exportadas para {out_props.name}", "props": props}


@app.post("/api/remotion/launch")
def api_remotion_launch() -> dict[str, str]:
    if not (REMOTION_DIR / "package.json").is_file():
        raise HTTPException(status_code=404, detail="Pasta remotion/ não encontrada.")
    try:
        creation_flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
        subprocess.Popen(
            ["cmd", "/c", "npm", "run", "dev"] if os.name == "nt" else ["npm", "run", "dev"],
            cwd=str(REMOTION_DIR),
            creationflags=creation_flags,
        )
        return {"message": "Remotion Studio iniciado em nova janela (http://localhost:3000)."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Input Videos
# ---------------------------------------------------------------------------


@app.get("/api/videos")
def api_list_videos() -> dict[str, Any]:
    _ensure_dirs()
    videos: list[dict[str, Any]] = []
    for p in sorted(INPUT_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not (p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS):
            continue
        cached_t = PROJECTS_TEMP_DIR / p.stem / "transcript.json"
        try:
            info = probe_video_info(p)
            videos.append(
                {
                    "filename": p.name,
                    "width": info["width"],
                    "height": info["height"],
                    "duration": round(float(info["duration"]), 1),
                    "fps": round(float(info["fps"]), 1),
                    "size_mb": round(float(info["size_mb"]), 1),
                    "has_audio": bool(info["has_audio"]),
                    "cached": cached_t.is_file(),
                    "media_url": f"/api/media/input/{p.name}",
                }
            )
        except Exception:
            videos.append(
                {
                    "filename": p.name,
                    "width": 0,
                    "height": 0,
                    "duration": 0.0,
                    "fps": 0.0,
                    "size_mb": round(p.stat().st_size / (1024 * 1024), 1),
                    "has_audio": True,
                    "cached": cached_t.is_file(),
                    "media_url": f"/api/media/input/{p.name}",
                }
            )
    return {"videos": videos}


@app.post("/api/videos/upload")
async def api_upload_video(file: UploadFile = File(...)) -> dict[str, Any]:
    _ensure_dirs()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")
    fname = Path(file.filename).name
    if Path(fname).suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato de vídeo não suportado.")
    dest = _safe_child(INPUT_DIR, fname)
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    return {"filename": fname, "message": f"Vídeo '{fname}' enviado para input/."}


@app.post("/api/videos/demo")
def api_generate_demo(req: DemoVideoRequest) -> dict[str, Any]:
    try:
        out_path = generate_demo_gameplay(language=req.language, duration=float(req.duration))
        return {
            "filename": out_path.name,
            "message": f"Vídeo demo '{out_path.name}' ({req.duration}s) gerado em input/.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/videos/downloader-status")
def api_downloader_status() -> dict[str, Any]:
    return get_downloader_status()


@app.post("/api/videos/download-url")
def api_download_youtube_url(req: DownloadUrlRequest) -> dict[str, Any]:
    status = get_downloader_status()
    if not status["available"]:
        raise HTTPException(
            status_code=412,
            detail="yt-dlp.exe não encontrado. Instale o YtoWave e reabra o aplicativo.",
        )
    if not req.url.strip():
        raise HTTPException(status_code=400, detail="Informe o link do vídeo do YouTube.")

    job_id = jobs.create("download", "Download YouTube → input/")

    def _worker() -> None:
        emit: Callable[[str], None] = lambda msg: jobs.append_log(job_id, msg)
        try:
            jobs.set_step(job_id, "download", 5)
            out_path = download_youtube_video(
                url=req.url,
                quality=req.quality,
                progress_callback=emit,
            )
            jobs.finish(job_id, {"downloaded_filename": out_path.name})
        except Exception as exc:
            jobs.fail(job_id, str(exc))

    threading.Thread(target=_worker, daemon=True).start()
    return {"job_id": job_id}


@app.delete("/api/videos/{filename}")
def api_delete_video(filename: str) -> dict[str, str]:
    target = _safe_child(INPUT_DIR, filename)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    target.unlink()
    return {"message": f"Vídeo '{target.name}' removido de input/."}


@app.get("/api/videos/{filename}/pinned-face")
def api_get_pinned_face(filename: str) -> dict[str, Any]:
    target = _safe_child(INPUT_DIR, filename)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    data = get_pinned_face(target)
    if not data:
        return {"pinned": False, "thumb_url": None, "timestamp": None}
    thumb = data.get("thumb_path", "")
    return {
        "pinned": True,
        "thumb_url": (_media_url_for_temp(thumb) + f"?t={int(time.time())}") if thumb else None,
        "timestamp": data.get("timestamp"),
    }


@app.post("/api/videos/{filename}/pin-frame")
def api_pin_frame(filename: str, req: PinFrameRequest) -> dict[str, Any]:
    target = _safe_child(INPUT_DIR, filename)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    try:
        info = extract_frame_for_pin(target, timestamp=req.timestamp)
        return {
            "frame_url": _media_url_for_temp(info["frame_path"]) + f"?t={int(time.time() * 1000)}",
            "timestamp": info["timestamp"],
            "duration": info["duration"],
            "width": info["width"],
            "height": info["height"],
            "faces": info["faces"],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/videos/{filename}/pin-face")
def api_pin_face(filename: str, req: PinFaceRequest) -> dict[str, Any]:
    target = _safe_child(INPUT_DIR, filename)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    try:
        saved = pin_face_from_frame(
            target, timestamp=req.timestamp, norm_x=req.norm_x, norm_y=req.norm_y
        )
        return {
            "pinned": True,
            "thumb_url": _media_url_for_temp(saved["thumb_path"]) + f"?t={int(time.time() * 1000)}",
            "timestamp": saved["timestamp"],
            "message": f"Rosto pinnado em {saved['timestamp']}s! O circle crop seguirá esse rosto.",
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/videos/{filename}/pinned-face")
def api_clear_pinned_face(filename: str) -> dict[str, Any]:
    target = _safe_child(INPUT_DIR, filename)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    clear_pinned_face(target)
    return {"pinned": False, "message": "Pin do rosto removido."}


# ---------------------------------------------------------------------------
# Pipeline & Cuts
# ---------------------------------------------------------------------------


def _read_transcript_meta() -> dict[str, Any] | None:
    tpath = TEMP_DIR / "transcript.json"
    if not tpath.is_file():
        return None
    try:
        data = json.loads(tpath.read_text(encoding="utf-8"))
        segs = data.get("segments", [])
        return {
            "video_file": data.get("video_file", "?"),
            "language": str(data.get("language", "?")).upper(),
            "segments_count": len(segs),
            "duration": data.get("duration", 0),
            "preview_segments": segs[:40],
        }
    except Exception:
        return None


def _read_cuts_list() -> list[dict[str, Any]]:
    cpath = TEMP_DIR / "cuts.json"
    if not cpath.is_file():
        return []
    try:
        data = json.loads(cpath.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


@app.get("/api/pipeline/state")
def api_pipeline_state() -> dict[str, Any]:
    return {
        "cuts": _read_cuts_list(),
        "transcript": _read_transcript_meta(),
        "current_job": jobs.get_current(),
    }


@app.put("/api/pipeline/cuts")
def api_save_cuts(req: CutsUpdateRequest) -> dict[str, Any]:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    formatted = json.dumps(req.cuts, ensure_ascii=False, indent=2)
    (TEMP_DIR / "cuts.json").write_text(formatted, encoding="utf-8")
    return {"cuts": req.cuts, "message": f"{len(req.cuts)} corte(s) salvos em temp/cuts.json."}


@app.post("/api/pipeline/preview-layout")
def api_preview_layout(req: LayoutPreviewRequest) -> dict[str, Any]:
    vpath = _safe_child(INPUT_DIR, req.video_name)
    if not vpath.is_file():
        raise HTTPException(status_code=404, detail="Vídeo não encontrado em input/.")
    info = probe_video_info(vpath)
    ts = min(2.5, float(info.get("duration", 2.5)) * 0.25)
    preview_path, msg = generate_layout_preview(vpath, timestamp=ts, layout_mode=req.layout_mode)
    return {
        "preview_url": _media_url_for_temp(preview_path) + f"?t={int(time.time())}",
        "message": msg,
    }


@app.post("/api/pipeline/run")
def api_run_pipeline(req: PipelineRunRequest) -> dict[str, Any]:
    mode = req.mode
    queue_paths: list[Path | None] = []
    if mode in ("full", "transcribe", "render"):
        raw_names = req.video_names if req.video_names else ([req.video_name] if req.video_name else [])
        if not raw_names:
            raise HTTPException(status_code=400, detail="Selecione um vídeo em input/.")
        for vname in raw_names:
            vp = _safe_child(INPUT_DIR, vname)
            if not vp.is_file():
                raise HTTPException(status_code=404, detail=f"Vídeo '{vname}' não encontrado em input/.")
            queue_paths.append(vp)
    else:
        queue_paths.append(_safe_child(INPUT_DIR, req.video_name) if req.video_name else None)

    first_name = queue_paths[0].name if queue_paths[0] else None
    if len(queue_paths) > 1:
        job_title = f"Fila de Cortes ({len(queue_paths)} vídeos)"
    else:
        title_map = {
            "full": f"Pipeline Completo: {first_name}",
            "transcribe": f"Transcrição: {first_name}",
            "analyze": "Análise Contextual",
            "render": f"Renderização 9:16: {first_name}",
        }
        job_title = title_map.get(mode, "Pipeline")

    job_id = jobs.create(
        "pipeline",
        job_title,
        queue_total=len(queue_paths),
        current_video=first_name,
    )

    def _worker() -> None:
        emit: Callable[[str], None] = lambda msg: jobs.append_log(job_id, msg)
        try:
            rendered_urls: list[dict[str, Any]] = []
            preview_url = ""
            total_q = len(queue_paths)

            for q_idx, vpath in enumerate(queue_paths, start=1):
                if vpath is not None:
                    jobs.set_queue_item(job_id, q_idx, vpath.name)
                    if total_q > 1:
                        emit(f"📦 [{q_idx}/{total_q}] Iniciando vídeo da fila: {vpath.name}")

                if mode in ("full", "transcribe"):
                    assert vpath is not None
                    jobs.set_step(job_id, "transcribe", 5)
                    emit(f"🎙️ Iniciando transcrição ({req.model_size}, {req.language}) para {vpath.name}...")
                    transcriber = GameplayTranscriber(model_size=req.model_size)
                    transcriber.transcribe(
                        vpath,
                        language=req.language,
                        use_cache=req.use_cache,
                        progress_callback=emit,
                    )
                    emit("✅ Transcrição concluída.")

                if mode in ("full", "analyze"):
                    if not (TEMP_DIR / "transcript.json").is_file():
                        raise RuntimeError("Nenhuma transcrição encontrada em temp/transcript.json.")
                    jobs.set_step(job_id, "analyze", 38)
                    limit_label = "sem limite" if req.max_cuts <= 0 else f"máx {req.max_cuts}"
                    emit(
                        f"🧠 Analisando contexto ({req.duration_mode}, {limit_label}, "
                        f"pool_llm={'sim' if req.use_llm_pool else 'não'})..."
                    )
                    cuts = analyze_transcript_for_cuts(
                        transcript_path=TEMP_DIR / "transcript.json",
                        duration_mode=req.duration_mode,
                        max_cuts=int(req.max_cuts),
                        output_path=TEMP_DIR / "cuts.json",
                        distribute_across_video=bool(req.distribute_across_video),
                        use_llm_pool=bool(req.use_llm_pool),
                        progress_callback=emit,
                    )
                    emit(f"✂️ {len(cuts)} corte(s) selecionados em temp/cuts.json.")

                if mode == "full" and vpath is not None:
                    jobs.set_step(job_id, "preview", 42)
                    cuts_now = _read_cuts_list()
                    info = probe_video_info(vpath)
                    preview_ts = (
                        float(cuts_now[0]["start"]) + 1.0
                        if cuts_now
                        else min(2.0, float(info.get("duration", 2.0)) * 0.2)
                    )
                    preview_path, _ = generate_layout_preview(
                        vpath, timestamp=preview_ts, layout_mode=req.layout_mode
                    )
                    preview_url = _media_url_for_temp(preview_path) + f"?t={int(time.time())}"

                if mode in ("full", "render"):
                    assert vpath is not None
                    if not (TEMP_DIR / "cuts.json").is_file():
                        raise RuntimeError("Nenhum corte encontrado em temp/cuts.json.")
                    jobs.set_step(job_id, "render", 45)
                    emit(f"🎬 Renderizando cortes 9:16 ({req.layout_mode}, legenda={req.caption_preset})...")
                    editor = VerticalVideoEditor(
                        caption_preset=req.caption_preset,
                        words_per_line=int(req.words_per_line),
                        burn_captions=bool(req.burn_captions),
                    )
                    records = editor.render_cuts(
                        vpath,
                        cuts_path=TEMP_DIR / "cuts.json",
                        transcript_path=TEMP_DIR / "transcript.json",
                        layout_mode=req.layout_mode,
                        progress_callback=emit,
                        cache_facecam_per_video=True,
                        skip_existing=bool(req.skip_existing),
                        precision_retranscribe=bool(req.precision_retranscribe),
                        refine_captions_with_llm=bool(req.refine_captions_with_llm),
                        dynamic_face_tracking=bool(req.dynamic_face_tracking),
                        face_track_mode=req.face_track_mode,
                    )
                    for r in records:
                        rendered_urls.append(
                            {
                                "title": r.get("title", ""),
                                "output_path": r.get("output_path", ""),
                                "media_url": _media_url_for_output(r.get("output_path", "")),
                                "duration": r.get("duration", 0),
                            }
                        )
                    emit(f"🎉 Concluído! {len(records)} Short(s) renderizado(s).")

            jobs.finish(
                job_id,
                {
                    "rendered": rendered_urls,
                    "preview_url": preview_url,
                    "cuts_count": len(_read_cuts_list()),
                },
            )
        except Exception as exc:
            jobs.fail(job_id, str(exc))

    threading.Thread(target=_worker, daemon=True).start()
    return {"job_id": job_id}


# ---------------------------------------------------------------------------
# Jobs (Polling & SSE Stream)
# ---------------------------------------------------------------------------


@app.get("/api/jobs/current")
def api_current_job() -> dict[str, Any]:
    return {"job": jobs.get_current(), "jobs": jobs.get_all_by_kind()}


@app.get("/api/jobs/{job_id}/stream")
async def api_stream_job(job_id: str) -> StreamingResponse:
    if jobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job não encontrado.")

    async def event_gen():
        last_log_idx = 0
        last_state_key = ""
        while True:
            snap = jobs.get(job_id)
            if not snap:
                break
            logs = snap.get("logs", [])
            if len(logs) > last_log_idx:
                new_lines = logs[last_log_idx:]
                last_log_idx = len(logs)
                yield f"event: logs\ndata: {json.dumps({'lines': new_lines}, ensure_ascii=False)}\n\n"

            state_key = f"{snap.get('status')}|{snap.get('step')}|{snap.get('progress')}"
            if state_key != last_state_key:
                last_state_key = state_key
                payload = {
                    "status": snap.get("status"),
                    "step": snap.get("step"),
                    "progress": snap.get("progress"),
                    "result": snap.get("result"),
                    "error": snap.get("error"),
                }
                yield f"event: state\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            if snap.get("status") in ("done", "error"):
                break
            await asyncio.sleep(0.35)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Clips, YouTube Queue & Thumbnails
# ---------------------------------------------------------------------------


@app.get("/api/clips")
def api_list_clips(
    source: str = Query("Todos"),
    duration: str = Query("Todos"),
) -> dict[str, Any]:
    clips = list_rendered_clips()
    queue_items = generate_youtube_queue()
    queue_by_path = {
        str(Path(str(it.get("video_path", ""))).resolve()): it for it in queue_items
    }

    sources = ["Todos"] + sorted({str(c.get("source_video", "Desconhecido")) for c in clips})

    enriched: list[dict[str, Any]] = []
    for c in clips:
        if source != "Todos" and c.get("source_video") != source:
            continue
        if duration != "Todos" and str(c.get("duration_type", "")) != duration:
            continue

        resolved = str(Path(str(c.get("output_path", ""))).resolve())
        q = queue_by_path.get(resolved, {})
        enriched.append(
            {
                **c,
                "media_url": _media_url_for_output(c.get("output_path", "")),
                "filename": Path(str(c.get("output_path", ""))).name,
                "youtube_status": q.get("status", "pending"),
                "youtube_url": q.get("youtube_url", ""),
                "youtube_title": q.get("youtube_title", c.get("youtube_title", "")),
                "youtube_description": q.get(
                    "youtube_description", c.get("youtube_description", "")
                ),
                "visibility": q.get("visibility", "PUBLIC"),
            }
        )

    return {"clips": enriched, "sources": sources, "queue": queue_items}


@app.put("/api/youtube/queue/item")
def api_update_queue_item(req: QueueItemUpdateRequest) -> dict[str, Any]:
    items = generate_youtube_queue()
    target = str(Path(req.video_path).resolve())
    updated = False
    for it in items:
        if str(Path(str(it.get("video_path", ""))).resolve()) == target:
            it["youtube_title"] = req.youtube_title
            it["youtube_description"] = req.youtube_description
            it["visibility"] = req.visibility
            it["edited"] = True
            updated = True
            break
    if not updated:
        raise HTTPException(status_code=404, detail="Item não encontrado na fila.")

    YT_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    YT_QUEUE_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"message": "Metadados do Short atualizados na fila."}


@app.put("/api/youtube/queue")
def api_save_queue_bulk(req: QueueBulkUpdateRequest) -> dict[str, Any]:
    for it in req.items:
        it["edited"] = True
    YT_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    YT_QUEUE_FILE.write_text(
        json.dumps(req.items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"message": f"Fila salva com {len(req.items)} item(ns)."}


@app.post("/api/youtube/sync")
def api_youtube_sync() -> dict[str, Any]:
    try:
        items, stats = sync_queue_with_youtube_api(refresh_api=True)
        return {
            "stats": stats,
            "count": len(items),
            "message": (
                f"Sincronizado via {stats['source']} ({stats['channel_videos_checked']} vídeos): "
                f"{stats['newly_marked']} novos marcados | "
                f"{stats['posted_total']} postados, {stats['pending_total']} pendentes."
            ),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/youtube/chrome/launch")
def api_chrome_launch() -> dict[str, Any]:
    try:
        port, msg = launch_chrome_cdp(9222)
        ok, ready_msg = check_youtube_studio_ready(port)
        return {"port": port, "ready": ok, "message": f"{msg} — {ready_msg}"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/youtube/chrome/status")
def api_chrome_status() -> dict[str, Any]:
    try:
        ok, msg = check_youtube_studio_ready(9222)
        return {"ready": ok, "message": msg}
    except Exception as exc:
        return {"ready": False, "message": str(exc)}


@app.post("/api/youtube/upload")
def api_youtube_upload(req: YouTubeUploadRequest) -> dict[str, Any]:
    if not req.selected_paths:
        raise HTTPException(status_code=400, detail="Selecione pelo menos 1 Short para publicar.")
    job_id = jobs.create(
        "upload", f"Publicação YouTube Shorts ({len(req.selected_paths)} vídeo(s))"
    )

    def _worker() -> None:
        emit: Callable[[str], None] = lambda msg: jobs.append_log(job_id, msg)
        try:
            jobs.set_step(job_id, "upload", 10)
            emit(
                f"🚀 Iniciando upload de {len(req.selected_paths)} Short(s) ({req.visibility})..."
            )
            res = yt_upload_queue(
                visibility=req.visibility,
                skip_posted=bool(req.skip_posted),
                progress_callback=emit,
                selected_paths=req.selected_paths,
            )
            emit("🎉 Lote YouTube concluído!")
            jobs.finish(job_id, {"uploaded": res})
        except Exception as exc:
            jobs.fail(job_id, str(exc))

    threading.Thread(target=_worker, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/thumbnails")
def api_list_thumbnails() -> dict[str, Any]:
    paths = list_generated_thumbnails()
    items = [
        {"path": p, "filename": Path(p).name, "media_url": _media_url_for_output(p)}
        for p in paths
    ]
    return {"thumbnails": items}


@app.post("/api/thumbnails/generate")
def api_generate_thumbnails(req: ThumbnailsRequest) -> dict[str, Any]:
    try:
        logs: list[str] = []
        res = generate_thumbnails_for_clips(
            selected_paths=req.selected_paths if req.selected_paths else None,
            prefer_youtube_cover=True,
            progress_callback=lambda m: logs.append(m),
        )
        return {
            "count": len(res),
            "logs": logs,
            "message": f"{len(res)} capa(s) gerada(s) em output/thumbnails/.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/thumbnails/upload")
def api_upload_thumbnails(req: ThumbnailsRequest) -> dict[str, Any]:
    try:
        logs: list[str] = []
        res = upload_thumbnails_batch(
            selected_paths=req.selected_paths if req.selected_paths else None,
            port=9222,
            progress_callback=lambda m: logs.append(m),
        )
        ok_cnt = sum(1 for r in res if r.get("status") == "updated")
        return {
            "updated": ok_cnt,
            "total": len(res),
            "logs": logs,
            "message": f"{ok_cnt}/{len(res)} capa(s) atualizada(s) no YouTube Studio.",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Analytics & AI Coach
# ---------------------------------------------------------------------------


def _build_analytics_payload() -> dict[str, Any]:
    api_key, channel_ref = get_saved_youtube_config()
    masked_key = (
        f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) > 12 else ("*" * len(api_key))
    )
    if not ANALYTICS_CACHE_FILE.exists():
        return {
            "has_data": False,
            "api_key_masked": masked_key,
            "has_api_key": bool(api_key),
            "channel_ref": channel_ref,
            "data": None,
        }
    data = json.loads(ANALYTICS_CACHE_FILE.read_text(encoding="utf-8"))
    videos = data.get("videos") or []
    buckets = data.get("bucket_summary") or {}
    if not buckets and videos:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for v in videos:
            b = str(v.get("bucket") or "other")
            grouped.setdefault(b, []).append(v)
        for b, items in grouped.items():
            cnt = len(items)
            buckets[b] = {
                "count": cnt,
                "avg_views": sum(float(x.get("views", 0)) for x in items) / cnt,
                "avg_likes": sum(float(x.get("likes", 0)) for x in items) / cnt,
                "avg_engagement_pct": sum(
                    float(x.get("engagement_pct", 0.0)) for x in items
                )
                / cnt,
            }
        data["bucket_summary"] = buckets
    return {
        "has_data": True,
        "api_key_masked": masked_key,
        "has_api_key": bool(api_key),
        "channel_ref": channel_ref,
        "data": data,
    }


@app.get("/api/analytics")
def api_get_analytics() -> dict[str, Any]:
    return _build_analytics_payload()


@app.post("/api/analytics/config")
def api_save_analytics_config(req: AnalyticsConfigRequest) -> dict[str, str]:
    try:
        msg = save_youtube_api_config(req.api_key, req.channel_ref)
        return {"message": msg}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/analytics/fetch-api")
def api_fetch_analytics_api(req: AnalyticsConfigRequest) -> dict[str, Any]:
    try:
        saved_key, saved_ref = get_saved_youtube_config()
        use_key = req.api_key.strip() or saved_key
        use_ref = req.channel_ref.strip() or saved_ref
        if req.api_key.strip() or req.channel_ref.strip():
            save_youtube_api_config(use_key, use_ref)
        data = fetch_channel_analytics_api(
            api_key=use_key, channel_ref=use_ref, max_videos=40
        )
        payload = _build_analytics_payload()
        payload["message"] = (
            f"Coletados {len(data.get('videos', []))} vídeos via YouTube Data API v3."
        )
        return payload
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/analytics/scrape-studio")
def api_scrape_analytics_studio() -> dict[str, Any]:
    try:
        data = scrape_studio_analytics_cdp(port=9222)
        payload = _build_analytics_payload()
        payload["message"] = (
            f"Capturados {len(data.get('videos', []))} vídeos via YouTube Studio CDP."
        )
        return payload
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/analytics/ai-coach")
def api_analytics_ai_coach() -> dict[str, str]:
    try:
        advice = analyze_performance_with_pool()
        return {"advice": advice}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Media Streaming Routes
# ---------------------------------------------------------------------------


@app.get("/api/media/input/{filename}")
def api_media_input(filename: str) -> FileResponse:
    target = _safe_child(INPUT_DIR, filename)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(target)


@app.get("/api/media/output/{subpath:path}")
def api_media_output(subpath: str) -> FileResponse:
    target = _safe_child(OUTPUT_DIR, subpath)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(target)


@app.get("/api/media/temp/{subpath:path}")
def api_media_temp(subpath: str) -> FileResponse:
    target = _safe_child(TEMP_DIR, subpath)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return FileResponse(target)


# ---------------------------------------------------------------------------
# Serve Built React Frontend (Production / Standalone Mode)
# ---------------------------------------------------------------------------

if FRONTEND_DIST_DIR.is_dir():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found.")
        candidate = FRONTEND_DIST_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
