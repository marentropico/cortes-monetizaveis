"""Gameplay-Shorts-Pipeline | Studio 9:16 — Gradio Web Interface."""

from __future__ import annotations

import inspect
import json
import os
import queue
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import gradio as gr

from src import INPUT_DIR, OUTPUT_DIR, PROJECT_ROOT, PROJECTS_TEMP_DIR, REMOTION_DIR, REPOS_DIR, TEMP_DIR
from src.captioner import CAPTION_PRESETS, extract_words_in_range
from src.context_analyzer import analyze_transcript_for_cuts
from src.demo_generator import generate_demo_gameplay
from src.face_detector import generate_layout_preview
from src.ffmpeg_utils import probe_video_info, verify_ffmpeg_capabilities
from src.llm_pool import has_active_pool
from src.transcriber import GameplayTranscriber
from src.thumbnail_generator import (
    generate_thumbnails_for_clips,
    list_generated_thumbnails,
    upload_thumbnails_batch,
)
from src.video_editor import VerticalVideoEditor, list_rendered_clips
from src.youtube_publisher import (
    QUEUE_FILE as YT_QUEUE_FILE,
    check_youtube_studio_ready,
    generate_youtube_queue,
    launch_chrome_cdp,
    load_uploaded_history,
    sync_queue_with_youtube_api,
    upload_queue as yt_upload_queue,
)
from src.youtube_analytics import (
    ANALYTICS_CACHE_FILE,
    analyze_performance_with_pool,
    fetch_channel_analytics_api,
    get_saved_youtube_config,
    save_youtube_api_config,
    scrape_studio_analytics_cdp,
)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm"}

CUSTOM_CSS = """
.hero-banner {
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #083344 100%);
    border: 1px solid rgba(56, 189, 248, 0.28);
    border-radius: 12px;
    padding: 14px 20px;
    margin-bottom: 10px;
    color: #f8fafc;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}
.hero-banner h1 {
    margin: 0;
    font-size: 1.35rem;
    letter-spacing: -0.02em;
    color: #38bdf8;
}
.hero-banner p {
    margin: 2px 0 0 0;
    color: #cbd5e1;
    font-size: 0.86rem;
}
.badge-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}
.status-pill {
    background: rgba(15, 23, 42, 0.72);
    border: 1px solid rgba(56, 189, 248, 0.35);
    border-radius: 999px;
    padding: 4px 11px;
    font-size: 0.78rem;
    color: #e2e8f0;
}
.primary-cta button {
    min-height: 50px !important;
    font-size: 1.02rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.01em;
}
"""


def _ensure_dirs() -> None:
    for d in (INPUT_DIR, OUTPUT_DIR, TEMP_DIR, PROJECTS_TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def list_input_videos() -> list[str]:
    """Return sorted list of video filenames inside input/."""
    _ensure_dirs()
    files = [
        p.name
        for p in sorted(INPUT_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return files


def _resolve_input_video(filename: str | None) -> Path | None:
    if not filename:
        return None
    p = INPUT_DIR / filename
    return p if p.is_file() else None


def _read_cuts_json_text() -> tuple[str, list[list[Any]]]:
    cpath = TEMP_DIR / "cuts.json"
    if not cpath.is_file():
        return "[]", []
    try:
        raw = cpath.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            return raw, []
        rows = [
            [
                c.get("id", i + 1),
                c.get("title", ""),
                c.get("start", 0.0),
                c.get("end", 0.0),
                c.get("duration_type", f"{int(round(float(c.get('end', 0)) - float(c.get('start', 0))))}s"),
                c.get("hook_text", ""),
                c.get("context_reason", ""),
            ]
            for i, c in enumerate(data)
        ]
        return json.dumps(data, ensure_ascii=False, indent=2), rows
    except Exception:
        return "[]", []


def _read_transcript_summary() -> str:
    tpath = TEMP_DIR / "transcript.json"
    if not tpath.is_file():
        return "Nenhuma transcrição ativa em temp/transcript.json."
    try:
        data = json.loads(tpath.read_text(encoding="utf-8"))
        segs = data.get("segments", [])
        header = (
            f"Arquivo: {data.get('video_file', '?')} | "
            f"Idioma: {str(data.get('language', '?')).upper()} | "
            f"Segmentos: {len(segs)} | Duração: {data.get('duration', 0)}s\n"
            + ("-" * 60)
        )
        lines = [
            f"[{s.get('start', 0):06.2f}s -> {s.get('end', 0):06.2f}s] {s.get('text', '')}"
            for s in segs[:40]
        ]
        if len(segs) > 40:
            lines.append(f"... (+{len(segs) - 40} segmentos no arquivo temp/transcript.json)")
        return header + "\n" + "\n".join(lines)
    except Exception as exc:
        return f"Erro ao ler transcript.json: {exc}"


def _build_header_html() -> str:
    try:
        caps = verify_ffmpeg_capabilities()
        enc = caps["best_h264_encoder"]
    except Exception:
        enc = "libx264"

    pool_ok = "Pool IA Ativa" if has_active_pool() else "Pool IA Offline"
    clips_count = len(list_rendered_clips())

    return f"""
    <div class="hero-banner">
      <div>
        <h1>🎮 Hard Cleeps Studio &nbsp;|&nbsp; Shorts 9:16</h1>
        <p>Jogue o vídeo em <code>input/</code>, escolha o range e gere cortes prontos para publicar.</p>
      </div>
      <div class="badge-row">
        <span class="status-pill">🚀 {enc}</span>
        <span class="status-pill">🤖 {pool_ok}</span>
        <span class="status-pill">🎬 Cortes prontos: {clips_count}</span>
      </div>
    </div>
    """


def _build_input_bank_rows() -> list[list[Any]]:
    rows: list[list[Any]] = []
    for fname in list_input_videos():
        vpath = INPUT_DIR / fname
        cached_t = PROJECTS_TEMP_DIR / vpath.stem / "transcript.json"
        cache_status = "✅ Em Cache" if cached_t.is_file() else "⏳ Pendente"
        try:
            info = probe_video_info(vpath)
            res = f"{info['width']}x{info['height']}"
            dur = f"{info['duration']:.1f}s"
            fps = f"{info['fps']:.1f}"
            size = f"{info['size_mb']:.1f} MB"
            audio = "Sim" if info["has_audio"] else "Mudo"
        except Exception:
            res, dur, fps, size, audio = "?", "?", "?", "?", "?"
        rows.append([fname, res, dur, fps, size, audio, cache_status])
    return rows


def _build_projects_gallery_data(
    source_filter: str = "Todos",
    duration_filter: str = "Todos",
) -> tuple[list[list[Any]], list[str], list[str], list[dict[str, Any]]]:
    clips = list_rendered_clips()
    sources = ["Todos"] + sorted({str(c.get("source_video", "Desconhecido")) for c in clips})

    filtered: list[dict[str, Any]] = []
    for c in clips:
        if source_filter != "Todos" and c.get("source_video") != source_filter:
            continue
        dtype = str(c.get("duration_type", ""))
        if duration_filter != "Todos" and dtype != duration_filter:
            continue
        filtered.append(c)

    rows = [
        [
            c.get("source_video", ""),
            c.get("title", ""),
            f"{float(c.get('duration', 0)):.1f}s",
            c.get("duration_type", ""),
            c.get("layout_mode", ""),
            c.get("encoder", ""),
            f"{float(c.get('size_mb', 0)):.1f} MB",
            c.get("hook_text", ""),
            c.get("context_reason", ""),
        ]
        for c in filtered
    ]
    labels = [f"{c.get('source_video', '')} / {Path(c['output_path']).name}" for c in filtered]
    return rows, sources, labels, filtered


def _ecosystem_diagnostics_md() -> tuple[str, list[list[Any]]]:
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

    diag_lines = [
        "### Diagnóstico Local do Ambiente",
        f"- **FFmpeg:** `{caps.get('ffmpeg_path', 'não encontrado')}`",
        f"- **FFprobe:** `{caps.get('ffprobe_path', 'não encontrado')}`",
        f"- **Filtro `subtitles` (`libass`):** `{'Sim' if caps.get('has_subtitles_filter') else 'Não'}`",
        f"- **Melhor Encoder H.264:** `{caps.get('best_h264_encoder', 'desconhecido')}`",
        f"- **GPUs CUDA (`faster-whisper`):** `{cuda_count}` (usando `{'cuda/float16' if cuda_count > 0 else 'cpu/int8'}`)",
        f"- **MediaPipe:** `{mp_ver}` (`{mp_mode}`)",
        f"- **Remotion Studio:** `{'Disponível em remotion/' if (REMOTION_DIR / 'package.json').is_file() else 'Não encontrado'}`",
    ]

    repo_specs = [
        ("faster-whisper", "SYSTRAN/faster-whisper", "Transcrição Whisper CTranslate2 + word timestamps"),
        ("stable-ts", "jianfch/stable-ts", "Alinhamento/estabilização de timestamps e segmentos"),
        ("clipsai", "ClipsAI/clipsai", "Referência TextTiling de segmentação de tópicos"),
        ("auto-captions", "nikhil-reddy05/auto-captions", "Conversão JSON -> legendas dinâmicas .ass"),
        ("auto-subtitle", "m1guelpf/auto-subtitle", "Automação CLI Whisper + FFmpeg subtitles"),
    ]
    repo_rows: list[list[Any]] = []
    for folder, name, role in repo_specs:
        exists = (REPOS_DIR / folder).is_dir()
        repo_rows.append([name, f"repos/{folder}", "✅ Clonado localmente" if exists else "❌ Ausente", role])

    remotion_exists = (REMOTION_DIR / "src" / "GameplayShortTemplate.tsx").is_file()
    repo_rows.append(
        [
            "Remotion (Projeto local)",
            "remotion/",
            "✅ Integrado (GameplayShortTemplate 9:16)" if remotion_exists else "⚠️ Sem template",
            "Templates React/Motion 9:16 para overlays avançados",
        ]
    )

    return "\n".join(diag_lines), repo_rows


# --- Pipeline Actions ---

def action_refresh_studio() -> tuple[Any, str, list[list[Any]], str, str]:
    videos = list_input_videos()
    cuts_txt, cuts_rows = _read_cuts_json_text()
    t_summary = _read_transcript_summary()
    return (
        gr.update(choices=videos, value=videos[0] if videos else None),
        cuts_txt,
        cuts_rows,
        t_summary,
        _build_header_html(),
    )


def _run_with_live_logs(
    worker_fn: Callable[[Callable[[str], None]], Any],
    logs: list[str],
):
    """Run blocking work in a background thread and yield live log snapshots."""
    q: queue.Queue[tuple[str, Any]] = queue.Queue()

    def _emit(msg: str) -> None:
        q.put(("log", f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"))

    def _runner() -> None:
        result = None
        err: Exception | None = None
        try:
            result = worker_fn(_emit)
        except Exception as exc:
            err = exc
        finally:
            q.put(("done", (result, err)))

    t = threading.Thread(target=_runner, daemon=True)
    t.start()

    while True:
        try:
            kind, payload = q.get(timeout=0.4)
        except queue.Empty:
            if not t.is_alive():
                break
            continue

        if kind == "log":
            logs.append(payload)
            yield "progress", None
        elif kind == "done":
            result, err = payload
            if err is not None:
                raise err
            yield "done", result
            break


def action_transcribe(
    video_name: str | None,
    language: str,
    model_size: str,
    use_cache: bool,
):
    vpath = _resolve_input_video(video_name)
    if vpath is None:
        yield "❌ Selecione um vídeo válido na pasta input/.", _read_transcript_summary(), _build_header_html()
        return

    logs: list[str] = [f"[{datetime.now().strftime('%H:%M:%S')}] Iniciando transcrição de {vpath.name}..."]
    yield "\n".join(logs), _read_transcript_summary(), _build_header_html()

    def _work(emit: Callable[[str], None]) -> Any:
        transcriber = GameplayTranscriber(model_size=model_size)
        return transcriber.transcribe(vpath, language=language, use_cache=use_cache, progress_callback=emit)

    try:
        for state, _ in _run_with_live_logs(_work, logs):
            if state == "progress":
                yield "\n".join(logs), _read_transcript_summary(), _build_header_html()
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ temp/transcript.json pronto!")
        yield "\n".join(logs), _read_transcript_summary(), _build_header_html()
    except Exception as exc:
        logs.append(f"❌ Erro na transcrição: {exc}")
        yield "\n".join(logs), _read_transcript_summary(), _build_header_html()


def action_analyze_context(
    duration_mode: str,
    max_cuts: int,
    distribute_across_video: bool,
    use_llm_pool: bool,
) -> tuple[str, list[list[Any]], str]:
    logs: list[str] = []
    try:
        cuts = analyze_transcript_for_cuts(
            transcript_path=TEMP_DIR / "transcript.json",
            duration_mode=duration_mode,
            max_cuts=int(max_cuts),
            output_path=TEMP_DIR / "cuts.json",
            distribute_across_video=bool(distribute_across_video),
            use_llm_pool=bool(use_llm_pool),
            progress_callback=lambda m: logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {m}"),
        )
        cuts_txt, cuts_rows = _read_cuts_json_text()
        logs.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Análise concluída: "
            f"{len(cuts)} cortes ({duration_mode}) salvos em temp/cuts.json."
        )
        return cuts_txt, cuts_rows, "\n".join(logs)
    except Exception as exc:
        cuts_txt, cuts_rows = _read_cuts_json_text()
        return cuts_txt, cuts_rows, f"❌ Erro na análise contextual: {exc}"


def action_save_cuts_json(json_text: str) -> tuple[str, list[list[Any]], str]:
    try:
        parsed = json.loads(json_text)
        if not isinstance(parsed, list):
            return json_text, [], "❌ O conteúdo de cuts.json precisa ser uma lista JSON ([...])."
        for idx, item in enumerate(parsed, start=1):
            if "start" not in item or "end" not in item:
                return json_text, [], f"❌ Item #{idx} está sem os campos obrigatórios 'start' e 'end'."
            item.setdefault("id", idx)
            item.setdefault("title", f"Corte_{idx}")
        formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
        (TEMP_DIR / "cuts.json").write_text(formatted, encoding="utf-8")
        _, cuts_rows = _read_cuts_json_text()
        return formatted, cuts_rows, f"✅ cuts.json salvo com {len(parsed)} cortes!"
    except Exception as exc:
        return json_text, [], f"❌ JSON inválido: {exc}"


def action_preview_layout(video_name: str | None, layout_mode: str) -> tuple[str | None, str]:
    vpath = _resolve_input_video(video_name)
    if vpath is None:
        return None, "❌ Selecione um vídeo válido para gerar o preview 9:16."
    try:
        info = probe_video_info(vpath)
        ts = min(3.0, max(0.2, float(info.get("duration", 4.0)) * 0.2))
        img_path, det = generate_layout_preview(vpath, timestamp=ts, layout_mode=layout_mode)
        msg = (
            f"👁️ Preview 9:16 gerado ({det['mode']}, backend={det['detector_backend']}, "
            f"rosto={'sim' if det['detected'] else 'não'})"
        )
        return img_path, msg
    except Exception as exc:
        return None, f"❌ Erro ao gerar preview: {exc}"


def action_render_cuts(
    video_name: str | None,
    layout_mode: str,
    caption_preset: str,
    words_per_line: int,
    burn_captions: bool,
    skip_existing: bool,
    precision_retranscribe: bool,
    refine_captions_with_llm: bool,
):
    vpath = _resolve_input_video(video_name)
    if vpath is None:
        yield "❌ Selecione um vídeo válido na pasta input/.", gr.update(), None, _build_header_html()
        return

    logs = [f"[{datetime.now().strftime('%H:%M:%S')}] Iniciando renderização 9:16 de {vpath.name}..."]
    yield "\n".join(logs), gr.update(), None, _build_header_html()

    def _work(emit: Callable[[str], None]) -> list[dict[str, Any]]:
        editor = VerticalVideoEditor(
            caption_preset=caption_preset,
            words_per_line=int(words_per_line),
            burn_captions=burn_captions,
        )
        return editor.render_cuts(
            vpath,
            cuts_path=TEMP_DIR / "cuts.json",
            transcript_path=TEMP_DIR / "transcript.json",
            layout_mode=layout_mode,
            progress_callback=emit,
            cache_facecam_per_video=True,
            skip_existing=bool(skip_existing),
            precision_retranscribe=bool(precision_retranscribe),
            refine_captions_with_llm=bool(refine_captions_with_llm),
        )

    try:
        records: list[dict[str, Any]] = []
        for state, res in _run_with_live_logs(_work, logs):
            if state == "progress":
                yield "\n".join(logs), gr.update(), None, _build_header_html()
            elif state == "done" and res is not None:
                records = res
        choices = [r["output_path"] for r in records]
        first_vid = choices[0] if choices else None
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 {len(records)} Shorts verticais prontos!")
        yield (
            "\n".join(logs),
            gr.update(choices=choices, value=first_vid),
            first_vid,
            _build_header_html(),
        )
    except Exception as exc:
        logs.append(f"❌ Erro na renderização: {exc}")
        yield "\n".join(logs), gr.update(), None, _build_header_html()


def action_one_click_pipeline(
    video_name: str | None,
    language: str,
    duration_mode: str,
    max_cuts: int,
    model_size: str,
    layout_mode: str,
    caption_preset: str,
    words_per_line: int,
    burn_captions: bool,
    use_cache: bool,
    distribute_across_video: bool,
    skip_existing: bool,
    use_llm_pool: bool,
    precision_retranscribe: bool,
    refine_captions_with_llm: bool,
):
    vpath = _resolve_input_video(video_name)
    if vpath is None:
        yield (
            "❌ Selecione um vídeo válido em input/ (ou gere um demo na aba Banco de Vídeos).",
            "[]",
            [],
            _read_transcript_summary(),
            None,
            gr.update(),
            None,
            _build_header_html(),
        )
        return

    logs: list[str] = [f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Pipeline 1-Click iniciado para {vpath.name}"]
    yield (
        "\n".join(logs),
        *(_read_cuts_json_text()),
        _read_transcript_summary(),
        None,
        gr.update(),
        None,
        _build_header_html(),
    )

    try:
        # Step 1: Transcribe with live % updates
        def _transcribe_work(emit: Callable[[str], None]) -> Any:
            transcriber = GameplayTranscriber(model_size=model_size)
            return transcriber.transcribe(vpath, language=language, use_cache=use_cache, progress_callback=emit)

        for state, _ in _run_with_live_logs(_transcribe_work, logs):
            if state == "progress":
                yield (
                    "\n".join(logs),
                    *(_read_cuts_json_text()),
                    _read_transcript_summary(),
                    None,
                    gr.update(),
                    None,
                    _build_header_html(),
                )

        t_summary = _read_transcript_summary()

        # Step 2: Contextual Analysis (Pool LLM + Local Fallback)
        limit_label = "sem limite (máx. do contexto)" if int(max_cuts) <= 0 else f"máx {int(max_cuts)}"
        logs.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] Analisando contexto "
            f"({duration_mode}, {limit_label}, pool_llm={'sim' if use_llm_pool else 'não'})..."
        )
        cuts = analyze_transcript_for_cuts(
            transcript_path=TEMP_DIR / "transcript.json",
            duration_mode=duration_mode,
            max_cuts=int(max_cuts),
            output_path=TEMP_DIR / "cuts.json",
            distribute_across_video=bool(distribute_across_video),
            use_llm_pool=bool(use_llm_pool),
            progress_callback=lambda m: logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {m}"),
        )
        cuts_txt, cuts_rows = _read_cuts_json_text()
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {len(cuts)} cortes contextuais selecionados em temp/cuts.json.")

        # Preview frame
        info = probe_video_info(vpath)
        preview_ts = cuts[0]["start"] + 1.0 if cuts else min(2.0, float(info.get("duration", 2.0)) * 0.2)
        preview_path, _ = generate_layout_preview(vpath, timestamp=preview_ts, layout_mode=layout_mode)

        yield (
            "\n".join(logs),
            cuts_txt,
            cuts_rows,
            t_summary,
            preview_path,
            gr.update(),
            None,
            _build_header_html(),
        )

        # Step 3: Render vertical 9:16 cuts with live clip progress
        def _render_work(emit: Callable[[str], None]) -> list[dict[str, Any]]:
            editor = VerticalVideoEditor(
                caption_preset=caption_preset,
                words_per_line=int(words_per_line),
                burn_captions=burn_captions,
            )
            return editor.render_cuts(
                vpath,
                cuts_path=TEMP_DIR / "cuts.json",
                transcript_path=TEMP_DIR / "transcript.json",
                layout_mode=layout_mode,
                progress_callback=emit,
                cache_facecam_per_video=True,
                skip_existing=bool(skip_existing),
                precision_retranscribe=bool(precision_retranscribe),
                refine_captions_with_llm=bool(refine_captions_with_llm),
            )

        records: list[dict[str, Any]] = []
        for state, res in _run_with_live_logs(_render_work, logs):
            if state == "progress":
                yield (
                    "\n".join(logs),
                    cuts_txt,
                    cuts_rows,
                    t_summary,
                    preview_path,
                    gr.update(),
                    None,
                    _build_header_html(),
                )
            elif state == "done" and res is not None:
                records = res

        choices = [r["output_path"] for r in records]
        first_vid = choices[0] if choices else None
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 Pipeline concluído! {len(records)} cortes em output/{vpath.stem}/")

        yield (
            "\n".join(logs),
            cuts_txt,
            cuts_rows,
            t_summary,
            preview_path,
            gr.update(choices=choices, value=first_vid),
            first_vid,
            _build_header_html(),
        )
    except Exception as exc:
        logs.append(f"❌ Falha no pipeline: {exc}")
        cuts_txt, cuts_rows = _read_cuts_json_text()
        yield (
            "\n".join(logs),
            cuts_txt,
            cuts_rows,
            _read_transcript_summary(),
            None,
            gr.update(),
            None,
            _build_header_html(),
        )


# --- Video Bank Actions ---

def action_refresh_bank() -> tuple[list[list[Any]], Any, str | None]:
    rows = _build_input_bank_rows()
    files = [r[0] for r in rows]
    first_path = str(INPUT_DIR / files[0]) if files else None
    return rows, gr.update(choices=files, value=files[0] if files else None), first_path


def action_upload_video(file_obj: Any) -> tuple[list[list[Any]], Any, Any, str]:
    if file_obj is None:
        rows, dd, _ = action_refresh_bank()
        return rows, dd, gr.update(), "Nenhum arquivo selecionado."
    src_path = Path(str(file_obj))
    if not src_path.is_file():
        rows, dd, _ = action_refresh_bank()
        return rows, dd, gr.update(), "❌ Arquivo inválido."
    dest = INPUT_DIR / src_path.name
    shutil.copy2(src_path, dest)
    rows, dd, _ = action_refresh_bank()
    files = [r[0] for r in rows]
    return (
        rows,
        dd,
        gr.update(choices=files, value=dest.name),
        f"✅ Vídeo '{dest.name}' adicionado ao banco input/!",
    )


def action_generate_demo(lang: str, duration: int) -> tuple[list[list[Any]], Any, Any, str | None, str]:
    try:
        out_path = generate_demo_gameplay(language=lang, duration=float(duration))
        rows, dd, _ = action_refresh_bank()
        files = [r[0] for r in rows]
        return (
            rows,
            dd,
            gr.update(choices=files, value=out_path.name),
            str(out_path),
            f"✅ Vídeo demo '{out_path.name}' ({duration}s) gerado em input/!",
        )
    except Exception as exc:
        rows, dd, first_path = action_refresh_bank()
        return rows, dd, gr.update(), first_path, f"❌ Erro ao gerar demo: {exc}"


def action_delete_input_video(filename: str | None) -> tuple[list[list[Any]], Any, Any, str | None, str]:
    vpath = _resolve_input_video(filename)
    if vpath is None:
        rows, dd, first_path = action_refresh_bank()
        return rows, dd, gr.update(), first_path, "❌ Vídeo não encontrado."
    vpath.unlink()
    rows, dd, first_path = action_refresh_bank()
    files = [r[0] for r in rows]
    return (
        rows,
        dd,
        gr.update(choices=files, value=files[0] if files else None),
        first_path,
        f"🗑️ Vídeo '{vpath.name}' removido de input/.",
    )


# --- Projects Gallery Actions ---

def action_refresh_gallery(
    source_filter: str,
    duration_filter: str,
) -> tuple[list[list[Any]], Any, Any, list[dict[str, Any]], str | None, str]:
    rows, sources, labels, filtered = _build_projects_gallery_data(source_filter, duration_filter)
    first_clip = filtered[0] if filtered else None
    vid_path = first_clip["output_path"] if first_clip else None
    details = _format_clip_details(first_clip)
    return (
        rows,
        gr.update(choices=sources, value=source_filter if source_filter in sources else "Todos"),
        gr.update(choices=labels, value=labels[0] if labels else None),
        filtered,
        vid_path,
        details,
    )


def _format_clip_details(clip: dict[str, Any] | None) -> str:
    if not clip:
        return "Nenhum corte selecionado."
    return (
        f"### {clip.get('title', 'Corte')}\n"
        f"- **Origem:** `{clip.get('source_video', '?')}`\n"
        f"- **Duração:** `{float(clip.get('duration', 0)):.1f}s` (`{clip.get('duration_type', '')}`)\n"
        f"- **Layout / Encoder:** `{clip.get('layout_mode', '')}` | `{clip.get('encoder', '')}`\n"
        f"- **Hook:** {clip.get('hook_text', '-')}\n"
        f"- **Contexto:** {clip.get('context_reason', '-')}\n"
        f"- **Arquivo:** `{clip.get('output_path', '')}`"
    )


def action_select_gallery_row(evt: gr.SelectData, clips_state: list[dict[str, Any]]) -> tuple[str | None, str]:
    idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else int(evt.index)
    if 0 <= idx < len(clips_state):
        clip = clips_state[idx]
        return clip["output_path"], _format_clip_details(clip)
    return None, "Selecione uma linha válida."


def action_select_gallery_dropdown(label: str | None, clips_state: list[dict[str, Any]]) -> tuple[str | None, str]:
    if not label:
        return None, "Nenhum corte selecionado."
    for clip in clips_state:
        cand = f"{clip.get('source_video', '')} / {Path(clip['output_path']).name}"
        if cand == label:
            return clip["output_path"], _format_clip_details(clip)
    return None, "Corte não encontrado."


def action_open_output_folder() -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(OUTPUT_DIR))
    return f"📂 Pasta aberta: {OUTPUT_DIR}"


# --- Ecosystem & Remotion Actions ---

def action_export_remotion_props() -> str:
    cpath = TEMP_DIR / "cuts.json"
    tpath = TEMP_DIR / "transcript.json"
    if not cpath.is_file():
        return "❌ Gere ou carregue temp/cuts.json antes de exportar para o Remotion."
    try:
        cuts = json.loads(cpath.read_text(encoding="utf-8"))
        if not cuts:
            return "❌ cuts.json está vazio."
        first = cuts[0]
        words: list[dict[str, Any]] = []
        if tpath.is_file():
            tdata = json.loads(tpath.read_text(encoding="utf-8"))
            words = extract_words_in_range(tdata, float(first["start"]), float(first["end"]))[:30]
        props = {
            "title": first.get("title", "GAMEPLAY_SHORT"),
            "hookText": first.get("hook_text", "OLHA ISSO!"),
            "durationType": first.get("duration_type", "30s"),
            "accentColor": "#00E6FF",
            "words": words,
        }
        out_props = REMOTION_DIR / "src" / "latest_short_props.json"
        out_props.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"✅ Props do corte #1 exportados para {out_props}"
    except Exception as exc:
        return f"❌ Erro ao exportar props Remotion: {exc}"


def action_launch_remotion_studio() -> str:
    if not (REMOTION_DIR / "package.json").is_file():
        return "❌ Projeto Remotion não encontrado em remotion/."
    try:
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            ["npm.cmd" if os.name == "nt" else "npm", "run", "dev"],
            cwd=str(REMOTION_DIR),
            creationflags=creationflags,
        )
        return "🎨 Remotion Studio iniciado em nova janela! Acesse http://localhost:3000 no navegador."
    except Exception as exc:
        return f"❌ Erro ao iniciar Remotion Studio: {exc}"


# --- YouTube Shorts Publisher Actions ---

def _read_yt_queue_ui(selected_paths: list[str] | None = None) -> tuple[str, list[list[Any]]]:
    items = generate_youtube_queue()
    sel_set = {str(Path(p).resolve()) for p in (selected_paths or []) if p}
    filtered = (
        [it for it in items if str(Path(str(it.get("video_path", ""))).resolve()) in sel_set]
        if selected_paths is not None
        else items
    )
    rows = [
        [
            it.get("id", ""),
            it.get("filename", ""),
            it.get("youtube_title", ""),
            it.get("visibility", "PUBLIC"),
            "✅ Postado" if it.get("status") == "posted" else "⏳ Pendente",
            it.get("youtube_url", ""),
        ]
        for it in filtered
    ]
    return json.dumps(items, ensure_ascii=False, indent=2), rows


def _filter_yt_selector_choices(
    source_filter: str = "Todos",
    dur_filter: str = "Todos",
) -> list[tuple[str, str]]:
    items = generate_youtube_queue()
    choices: list[tuple[str, str]] = []
    for it in items:
        src = str(it.get("source_video", ""))
        if source_filter and source_filter != "Todos" and src != source_filter:
            continue
        fname = str(it.get("filename", ""))
        if dur_filter and dur_filter != "Todos":
            if f"_{dur_filter}" not in fname:
                continue
        icon = "✅" if it.get("status") == "posted" else "⏳"
        label = f"{icon} #{it.get('id')} | {fname} ({it.get('duration', 0)}s)"
        choices.append((label, str(it.get("video_path", ""))))
    return choices


def action_yt_select_mode(
    mode: str,
    source_filter: str,
    dur_filter: str,
) -> tuple[Any, list[list[Any]], str]:
    items = generate_youtube_queue()
    choices = _filter_yt_selector_choices(source_filter, dur_filter)
    allowed_paths = {val for _, val in choices}
    if mode == "clear":
        selected: list[str] = []
        msg = "🧹 Fila de postagem limpa."
    elif mode == "pending":
        selected = [
            str(it.get("video_path", ""))
            for it in items
            if str(it.get("video_path", "")) in allowed_paths and it.get("status") != "posted"
        ]
        msg = f"⏳ {len(selected)} corte(s) pendente(s) selecionado(s) para a fila."
    else:
        selected = [val for _, val in choices]
        msg = f"☑️ {len(selected)} corte(s) selecionado(s) para a fila."

    _, rows = _read_yt_queue_ui(selected)
    return gr.update(choices=choices, value=selected), rows, msg


def action_yt_sync_api(
    source_filter: str,
    dur_filter: str,
    selected_paths: list[str] | None,
) -> tuple[str, Any, list[list[Any]], str]:
    try:
        _, stats = sync_queue_with_youtube_api(refresh_api=True)
        choices = _filter_yt_selector_choices(source_filter, dur_filter)
        q_txt, q_rows = _read_yt_queue_ui(selected_paths or [])
        msg = (
            f"✅ Sincronizado via {stats['source']} ({stats['channel_videos_checked']} vídeos do canal verificados): "
            f"{stats['newly_marked']} marcados agora como Postado | "
            f"Total: {stats['posted_total']} postados, {stats['pending_total']} pendentes."
        )
        return q_txt, gr.update(choices=choices, value=selected_paths or []), q_rows, msg
    except Exception as exc:
        choices = _filter_yt_selector_choices(source_filter, dur_filter)
        q_txt, q_rows = _read_yt_queue_ui(selected_paths or [])
        return q_txt, gr.update(choices=choices, value=selected_paths or []), q_rows, f"❌ Erro ao sincronizar com API do YouTube: {exc}"


def action_yt_open_chrome() -> str:
    try:
        port, msg = launch_chrome_cdp(9222)
        ok, ready_msg = check_youtube_studio_ready(port)
        return f"🌐 {msg}\n{ready_msg}"
    except Exception as exc:
        return f"❌ Erro ao abrir Chrome do YouTube Studio: {exc}"


def action_yt_check_status() -> str:
    try:
        _, msg = check_youtube_studio_ready(9222)
        return msg
    except Exception as exc:
        return f"❌ Erro ao verificar YouTube Studio: {exc}"


def action_yt_save_queue(json_text: str) -> tuple[str, list[list[Any]], str]:
    try:
        parsed = json.loads(json_text)
        if not isinstance(parsed, list):
            return json_text, [], "❌ A fila precisa ser uma lista JSON."
        for item in parsed:
            item["edited"] = True
        formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
        YT_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        YT_QUEUE_FILE.write_text(formatted, encoding="utf-8")
        _, rows = _read_yt_queue_ui()
        return formatted, rows, f"✅ Fila salva com {len(parsed)} vídeos em output/youtube_posts_queue.json!"
    except Exception as exc:
        return json_text, [], f"❌ JSON inválido: {exc}"


def action_yt_upload_batch(
    selected_paths: list[str] | None,
    visibility: str,
    skip_posted: bool,
):
    sel = list(selected_paths or [])
    logs = [
        f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Iniciando upload automático YouTube Shorts ({len(sel)} vídeo(s) na fila, {visibility})..."
    ]
    q_txt, q_rows = _read_yt_queue_ui(sel)
    yield "\n".join(logs), q_txt, q_rows

    def _work(emit: Callable[[str], None]) -> Any:
        return yt_upload_queue(
            visibility=visibility,
            skip_posted=bool(skip_posted),
            progress_callback=emit,
            selected_paths=sel,
        )

    try:
        for state, _ in _run_with_live_logs(_work, logs):
            if state == "progress":
                q_txt, q_rows = _read_yt_queue_ui(sel)
                yield "\n".join(logs), q_txt, q_rows
        q_txt, q_rows = _read_yt_queue_ui(sel)
        logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 Lote YouTube concluído!")
        yield "\n".join(logs), q_txt, q_rows
    except Exception as exc:
        logs.append(f"❌ Erro no upload automático: {exc}")
        q_txt, q_rows = _read_yt_queue_ui(sel)
        yield "\n".join(logs), q_txt, q_rows


def action_thumb_generate(selected_paths: list[str] | None) -> tuple[list[str], str]:
    try:
        sel = list(selected_paths or [])
        logs: list[str] = []
        res = generate_thumbnails_for_clips(
            selected_paths=sel if sel else None,
            prefer_youtube_cover=True,
            progress_callback=lambda m: logs.append(m),
        )
        thumbs = [r["thumbnail_path"] for r in res] or list_generated_thumbnails()
        return thumbs, f"✅ {len(res)} capa(s) gerada(s) em output/thumbnails/!\n" + "\n".join(logs[-6:])
    except Exception as exc:
        return list_generated_thumbnails(), f"❌ Erro ao gerar capas: {exc}"


def action_thumb_upload(selected_paths: list[str] | None) -> str:
    try:
        sel = list(selected_paths or [])
        logs: list[str] = []
        res = upload_thumbnails_batch(
            selected_paths=sel if sel else None,
            port=9222,
            progress_callback=lambda m: logs.append(m),
        )
        ok_cnt = sum(1 for r in res if r.get("status") == "updated")
        return f"✅ {ok_cnt}/{len(res)} capa(s) atualizada(s) no YouTube Studio!\n" + "\n".join(logs[-10:])
    except Exception as exc:
        return f"❌ Erro ao atualizar capas no YouTube Studio: {exc}"


def _read_analytics_ui() -> tuple[str, list[list[Any]]]:
    if not ANALYTICS_CACHE_FILE.exists():
        return (
            "📭 Nenhum dado de analytics salvo ainda. Cole sua **YouTube Data API Key** ou abra o **YouTube Studio (Chrome CDP)** e clique para atualizar.",
            [],
        )
    try:
        data = json.loads(ANALYTICS_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"⚠️ Erro ao ler cache de analytics: `{exc}`", []

    ch = data.get("channel") or {}
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
                "avg_engagement_pct": sum(float(x.get("engagement_pct", 0.0)) for x in items) / cnt,
            }

    ch_id = ch.get("id") or ch.get("channel_id") or "?"
    fetched_at = data.get("updated_at") or data.get("fetched_at") or "?"

    lines = [
        f"### 📺 {ch.get('title', 'Canal')} (`{ch_id}`)",
        f"- **Inscritos:** `{ch.get('subscribers', 0):,}` | **Views totais do canal:** `{ch.get('total_views', 0):,}` | **Vídeos no canal:** `{ch.get('video_count', 0)}`",
        f"- **Última coleta:** `{fetched_at}` | **Fonte:** `{data.get('source', 'YouTube Data API v3')}`",
    ]
    if buckets:
        lines.append("\n**Desempenho por faixa de duração (últimos vídeos coletados):**")
        for b_name in ("30s", "60s", "90s", "Longo"):
            if b_name in buckets:
                b = buckets[b_name]
                lines.append(
                    f"- **{b_name}**: `{b.get('count', 0)}` vídeo(s) | média `{b.get('avg_views', 0):.1f}` views | `{b.get('avg_likes', 0):.1f}` likes | engajamento médio `{b.get('avg_engagement_pct', 0):.2f}%`"
                )

    rows: list[list[Any]] = []
    for v in videos:
        studio_cells = " | ".join(v.get("studio_cells") or [])
        rows.append(
            [
                v.get("title", ""),
                v.get("bucket", ""),
                v.get("duration_sec", 0),
                v.get("views", 0),
                v.get("likes", 0),
                v.get("comments", 0),
                v.get("engagement_pct", 0.0),
                studio_cells[:120],
                v.get("url", ""),
            ]
        )
    return "\n".join(lines), rows


def action_an_save_config(api_key: str, channel_ref: str) -> str:
    try:
        return save_youtube_api_config(api_key, channel_ref)
    except Exception as exc:
        return f"❌ Erro ao salvar configuração: {exc}"


def action_an_fetch_api(api_key: str, channel_ref: str) -> tuple[str, list[list[Any]], str]:
    try:
        if api_key.strip() or channel_ref.strip():
            save_youtube_api_config(api_key, channel_ref)
        data = fetch_channel_analytics_api(api_key=api_key, channel_ref=channel_ref, max_videos=40)
        summary_md, rows = _read_analytics_ui()
        return (
            summary_md,
            rows,
            f"✅ Dados coletados via YouTube Data API v3: {len(data.get('videos', []))} vídeos analisados.",
        )
    except Exception as exc:
        summary_md, rows = _read_analytics_ui()
        return summary_md, rows, f"❌ Erro na YouTube Data API v3: {exc}"


def action_an_scrape_studio() -> tuple[str, list[list[Any]], str]:
    try:
        data = scrape_studio_analytics_cdp(port=9222)
        summary_md, rows = _read_analytics_ui()
        return (
            summary_md,
            rows,
            f"✅ YouTube Studio inspecionado via Chrome CDP: {len(data.get('videos', []))} vídeos capturados.",
        )
    except Exception as exc:
        summary_md, rows = _read_analytics_ui()
        return summary_md, rows, f"❌ Erro ao ler YouTube Studio (CDP): {exc}"


def action_an_ai_coach() -> str:
    try:
        return analyze_performance_with_pool()
    except Exception as exc:
        return f"❌ Erro ao gerar análise com Pool IA: {exc}"


def build_ui() -> tuple[gr.Blocks, dict[str, Any]]:
    _ensure_dirs()
    init_videos = list_input_videos()
    init_cuts_txt, init_cuts_rows = _read_cuts_json_text()
    init_t_summary = _read_transcript_summary()
    init_bank_rows = _build_input_bank_rows()
    init_gallery_rows, init_sources, init_labels, init_clips = _build_projects_gallery_data()
    diag_md, repo_rows = _ecosystem_diagnostics_md()
    init_yt_txt, init_yt_rows = _read_yt_queue_ui([])
    init_yt_choices = _filter_yt_selector_choices("Todos", "Todos")
    init_an_key, init_an_ref = get_saved_youtube_config()
    init_an_summary, init_an_rows = _read_analytics_ui()

    theme = gr.themes.Soft(
        primary_hue="sky",
        secondary_hue="indigo",
        neutral_hue="slate",
    )

    blocks_sig = inspect.signature(gr.Blocks.__init__).parameters
    blocks_kwargs: dict[str, Any] = {"title": "Gameplay-Shorts-Pipeline | Studio 9:16"}
    if "theme" in blocks_sig:
        blocks_kwargs["theme"] = theme
    if "css" in blocks_sig:
        blocks_kwargs["css"] = CUSTOM_CSS

    with gr.Blocks(**blocks_kwargs) as demo:
        header_html = gr.HTML(_build_header_html())

        with gr.Tabs():
            # ================================================================
            # TAB 1: GERAR CORTES (FLUXO ESSENCIAL EM 2 CLIQUES)
            # ================================================================
            with gr.Tab("⚡ 1. Gerar Cortes"):
                with gr.Row():
                    studio_video_dd = gr.Dropdown(
                        label="🎬 Vídeo de Entrada (pasta input/)",
                        choices=init_videos,
                        value=init_videos[0] if init_videos else None,
                        scale=4,
                    )
                    studio_refresh_btn = gr.Button("🔄 Atualizar", scale=1)
                    duration_dd = gr.Dropdown(
                        label="⏱️ Range de Duração",
                        choices=[
                            ("Mix Inteligente (30s + 60s + 90s)", "mix"),
                            ("30s (Rápido / Punchline)", "30s"),
                            ("60s (Padrão Contextual)", "60s"),
                            ("90s (Storytelling / Partida)", "90s"),
                        ],
                        value="mix",
                        scale=2,
                    )

                with gr.Row(elem_classes=["primary-cta"]):
                    one_click_btn = gr.Button(
                        "🚀 GERAR CORTES AUTOMATICAMENTE", variant="primary"
                    )

                logs_box = gr.Textbox(
                    label="🖥️ Progresso em Tempo Real",
                    value="Pronto. Selecione o vídeo, defina o range e clique em GERAR CORTES AUTOMATICAMENTE.",
                    lines=6,
                    interactive=False,
                )

                with gr.Accordion("➕ Enviar ou Gerenciar Vídeos (input/)", open=False):
                    with gr.Row():
                        upload_file = gr.File(
                            label="📤 Arraste ou selecione um vídeo (.mp4, .mkv, .mov)",
                            file_types=[".mp4", ".mkv", ".mov", ".avi", ".webm"],
                            scale=2,
                        )
                        with gr.Column(scale=2):
                            bank_video_dd = gr.Dropdown(
                                label="Selecionar Vídeo em input/",
                                choices=init_videos,
                                value=init_videos[0] if init_videos else None,
                            )
                            with gr.Row():
                                bank_refresh_btn = gr.Button("🔄 Atualizar Lista")
                                bank_send_btn = gr.Button("📌 Usar no Estúdio", variant="primary")
                                bank_delete_btn = gr.Button("🗑️ Remover", variant="stop")
                            bank_status = gr.Textbox(label="Status", interactive=False, lines=1)

                    bank_table = gr.Dataframe(
                        label="Vídeos em input/",
                        headers=["Arquivo", "Resolução", "Duração", "FPS", "Tamanho", "Áudio", "Transcrição"],
                        value=init_bank_rows,
                        interactive=False,
                    )
                    with gr.Accordion("👁️ Player Original (16:9) & Vídeo Demo", open=False):
                        bank_player = gr.Video(
                            label="Inspeção (16:9)",
                            value=str(INPUT_DIR / init_videos[0]) if init_videos else None,
                            height=320,
                        )
                        with gr.Row():
                            demo_lang_dd = gr.Dropdown(
                                label="Idioma Demo",
                                choices=[("Português (PT-BR)", "pt"), ("Inglês (EN)", "en")],
                                value="pt",
                            )
                            demo_dur_slider = gr.Slider(
                                label="Duração (s)", minimum=20, maximum=95, value=36, step=2
                            )
                            gen_demo_btn = gr.Button("🎬 Gerar Demo de Teste")

                with gr.Accordion("✂️ Cortes Planejados & Preview", open=False):
                    cuts_df = gr.Dataframe(
                        label="Cortes Planejados (temp/cuts.json)",
                        headers=["ID", "Título", "Início (s)", "Fim (s)", "Tipo", "Hook", "Motivo Contextual"],
                        value=init_cuts_rows,
                        interactive=False,
                        wrap=True,
                    )
                    with gr.Row():
                        rendered_dd = gr.Dropdown(label="🎞️ Cortes Gerados Nesta Sessão", choices=[], value=None)
                    rendered_player = gr.Video(label="Preview Vertical 9:16", height=420)
                    with gr.Accordion("📝 Editar JSON manualmente (temp/cuts.json)", open=False):
                        cuts_editor = gr.Code(
                            label="temp/cuts.json",
                            language="json",
                            value=init_cuts_txt,
                            lines=10,
                        )
                        save_cuts_btn = gr.Button("💾 Salvar Edições em temp/cuts.json")

                with gr.Accordion("⚙️ Configurações Avançadas (Whisper, Pool IA, Legendas, Enquadramento)", open=False):
                    with gr.Row():
                        lang_dd = gr.Dropdown(
                            label="🌐 Idioma",
                            choices=[
                                ("Português (PT-BR)", "pt"),
                                ("Inglês (EN)", "en"),
                                ("Automático (PT/EN)", "auto"),
                            ],
                            value="pt",
                        )
                        model_dd = gr.Dropdown(
                            label="🧠 Whisper (Passada 1)",
                            choices=["tiny", "base", "small", "medium"],
                            value="base",
                        )
                        layout_dd = gr.Dropdown(
                            label="📐 Enquadramento 9:16",
                            choices=[
                                ("Automático (3-Zonas: 16:9 Topo + Zoom 9:16 + Rosto Circular)", "auto"),
                                ("Split-Screen Clássico (Webcam Topo + Gameplay)", "split_screen"),
                                ("Webcam Superior Esquerda + Gameplay", "top_left"),
                                ("Webcam Superior Direita + Gameplay", "top_right"),
                                ("Webcam Centro-Esquerda + Gameplay", "mid_left"),
                                ("Webcam Centro-Direita + Gameplay", "mid_right"),
                                ("Webcam Inferior Esquerda + Gameplay", "bottom_left"),
                                ("Webcam Inferior Direita + Gameplay", "bottom_right"),
                                ("Fundo Desfocado + 16:9 Central", "blur_bg"),
                                ("Crop Central Tela Cheia 9:16", "center_only"),
                            ],
                            value="auto",
                        )
                        preset_dd = gr.Dropdown(
                            label="💬 Estilo da Legenda",
                            choices=[(CAPTION_PRESETS[k]["label"], k) for k in CAPTION_PRESETS],
                            value="hormozi",
                        )
                        words_slider = gr.Slider(
                            label="Palavras/Bloco", minimum=2, maximum=5, value=3, step=1
                        )

                    with gr.Row():
                        burn_captions_chk = gr.Checkbox(label="Queimar Legendas (.ass)", value=True)
                        cache_chk = gr.Checkbox(label="Usar Cache", value=True)
                        distribute_chk = gr.Checkbox(label="Distribuir no VOD (+1h)", value=True)
                        skip_existing_chk = gr.Checkbox(label="Pular já renderizados", value=False)
                        max_cuts_slider = gr.Slider(
                            label="✂️ Teto de Cortes (0 = Ilimitado / Máximo do Contexto)",
                            minimum=0,
                            maximum=100,
                            value=0,
                            step=1,
                        )

                    with gr.Row():
                        use_llm_pool_chk = gr.Checkbox(label="🤖 Curadoria & Títulos via Pool IA", value=True)
                        precision_retranscribe_chk = gr.Checkbox(label="🎯 Passada 2 (Whisper small)", value=True)
                        refine_captions_chk = gr.Checkbox(label="✨ Lapidar Legendas via Pool IA", value=True)

                    with gr.Accordion("🛠️ Modo Manual / Debug (Etapa por Etapa)", open=False):
                        with gr.Row():
                            step1_btn = gr.Button("1️⃣ Transcrever Áudio")
                            step2_btn = gr.Button("2️⃣ Analisar Contexto")
                            step3_btn = gr.Button("3️⃣ Renderizar Cortes")
                            preview_btn = gr.Button("👁️ Preview Enquadramento")
                        with gr.Row():
                            layout_preview_img = gr.Image(
                                label="Preview Enquadramento 1080x1920", type="filepath", height=340
                            )
                            transcript_box = gr.Textbox(
                                label="Transcrição Ativa (temp/transcript.json)",
                                value=init_t_summary,
                                lines=10,
                                interactive=False,
                            )

            # ================================================================
            # TAB 2: SHORTS PRONTOS & PUBLICAÇÃO YOUTUBE
            # ================================================================
            with gr.Tab("🎬 2. Shorts & Publicar"):
                gallery_state = gr.State(init_clips)

                with gr.Row():
                    yt_vis_dd = gr.Dropdown(
                        label="Visibilidade",
                        choices=[("Público", "PUBLIC"), ("Não listado", "UNLISTED"), ("Privado", "PRIVATE")],
                        value="PUBLIC",
                        scale=1,
                    )
                    yt_skip_chk = gr.Checkbox(label="Pular já postados", value=True, scale=1)
                    yt_sync_api_btn = gr.Button("🔄 Sincronizar com Canal (API)", scale=1)
                    yt_upload_btn = gr.Button(
                        "🚀 PUBLICAR FILA NO YOUTUBE SHORTS", variant="primary", scale=2
                    )

                yt_logs = gr.Textbox(
                    label="Status da Publicação",
                    value="1) Filtre o projeto abaixo  2) Marque os cortes desejados nos checkboxes  3) Clique em PUBLICAR FILA NO YOUTUBE SHORTS.",
                    lines=2,
                    interactive=False,
                )

                with gr.Row():
                    with gr.Column(scale=6):
                        with gr.Row():
                            gal_source_dd = gr.Dropdown(
                                label="📁 Selecionar Projeto", choices=init_sources, value="Todos", scale=3
                            )
                            gal_dur_dd = gr.Dropdown(
                                label="Duração",
                                choices=["Todos", "30s", "60s", "90s"],
                                value="Todos",
                                scale=1,
                            )
                            gal_refresh_btn = gr.Button("🔄 Atualizar", scale=1)
                            gal_open_btn = gr.Button("📂 Pasta output/", scale=1)

                        with gr.Row():
                            yt_sel_all_btn = gr.Button("☑️ Selecionar Todos do Filtro", scale=1)
                            yt_sel_pending_btn = gr.Button("⏳ Selecionar Pendentes", scale=1)
                            yt_clear_sel_btn = gr.Button("🧹 Limpar Fila", scale=1)

                        yt_clip_selector = gr.CheckboxGroup(
                            label="☑️ Cortes Prontos — marque para adicionar na Fila de Postagem (desmarque para remover)",
                            choices=init_yt_choices,
                            value=[],
                        )

                        yt_table = gr.Dataframe(
                            label="Fila de Postagem Ativa (somente cortes marcados acima)",
                            headers=["ID", "Arquivo", "Título YouTube Shorts", "Visibilidade", "Status", "URL"],
                            value=init_yt_rows,
                            interactive=False,
                            wrap=True,
                        )

                        gal_status = gr.Textbox(label="Status", visible=False)
                        with gr.Accordion("🎞️ Tabela Detalhada dos Cortes Prontos (clique para assistir)", open=False):
                            gallery_table = gr.Dataframe(
                                label="Cortes Prontos",
                                headers=["Projeto Origem", "Título", "Duração", "Tipo", "Layout", "Encoder", "Tamanho", "Hook", "Motivo"],
                                value=init_gallery_rows,
                                interactive=False,
                                wrap=True,
                            )

                        with gr.Accordion("🖼️ Capas & Thumbnails com Hook (sem IA generativa)", open=False):
                            gr.Markdown(
                                "Usa o cover do Short já postado (ou frame do MP4) + **Hook** estilizado por cima em `1080x1920`. "
                                "Se nenhum corte estiver marcado acima, gera/atualiza para **todos os já postados**."
                            )
                            with gr.Row():
                                thumb_gen_btn = gr.Button("🎨 Gerar Capas com Hook", variant="secondary")
                                thumb_upload_btn = gr.Button("🚀 Atualizar Capas no YouTube Studio", variant="primary")
                            thumb_status = gr.Textbox(label="Status das Capas", interactive=False, lines=3)
                            thumb_gallery = gr.Gallery(
                                label="Capas Geradas (output/thumbnails/)",
                                value=list_generated_thumbnails(),
                                columns=4,
                                height=320,
                            )

                    with gr.Column(scale=4):
                        gal_clip_dd = gr.Dropdown(
                            label="Selecionar Short",
                            choices=init_labels,
                            value=init_labels[0] if init_labels else None,
                        )
                        gal_player = gr.Video(
                            label="Player Vertical (9:16)",
                            value=init_clips[0]["output_path"] if init_clips else None,
                            height=460,
                        )
                        gal_details_md = gr.Markdown(
                            _format_clip_details(init_clips[0] if init_clips else None)
                        )

                with gr.Accordion("🔑 Sessão Chrome Studio & Editor JSON da Fila", open=False):
                    with gr.Row():
                        yt_open_chrome_btn = gr.Button("1️⃣ Abrir Chrome YouTube Studio (Login)")
                        yt_check_btn = gr.Button("🔍 Verificar Sessão Logada")
                        yt_refresh_btn = gr.Button("🔄 Atualizar Fila JSON")
                    yt_editor = gr.Code(
                        label="Editor JSON da Fila (Título, Descrição e Hashtags)",
                        language="json",
                        value=init_yt_txt,
                        lines=10,
                    )
                    yt_save_btn = gr.Button("💾 Salvar Edições da Fila YouTube")

            # ================================================================
            # TAB 3: ANALYTICS & SISTEMA
            # ================================================================
            with gr.Tab("📊 3. Analytics & Sistema"):
                with gr.Row():
                    an_fetch_api_btn = gr.Button("📡 Atualizar Métricas (API v3)", variant="primary", scale=2)
                    an_scrape_studio_btn = gr.Button("🖥️ Ler YouTube Studio (CDP)", scale=1)
                    an_ai_btn = gr.Button("🧠 Coach IA (Sugestões)", variant="secondary", scale=1)

                an_status = gr.Textbox(label="Status da Coleta", interactive=False, lines=1)
                an_summary_md = gr.Markdown(value=init_an_summary)
                an_table = gr.Dataframe(
                    headers=[
                        "Título",
                        "Faixa",
                        "Duração (s)",
                        "Views",
                        "Likes",
                        "Comentários",
                        "Engajamento (%)",
                        "Dados Studio",
                        "URL",
                    ],
                    value=init_an_rows,
                    interactive=False,
                    wrap=True,
                )
                an_ai_md = gr.Markdown(
                    value="*Clique em **🧠 Coach IA (Sugestões)** após coletar os dados para receber recomendações de duração, hooks e títulos.*"
                )

                with gr.Accordion("🔑 Credenciais YouTube Data API (.env)", open=not bool(init_an_key)):
                    with gr.Row():
                        an_api_key = gr.Textbox(
                            label="YouTube Data API v3 Key",
                            value=init_an_key,
                            type="password",
                            placeholder="AIzaSy...",
                        )
                        an_channel_ref = gr.Textbox(
                            label="Canal (@handle, UC... ou URL)",
                            value=init_an_ref,
                            placeholder="@hardcleeps ou UC...",
                        )
                    an_save_cfg_btn = gr.Button("💾 Salvar Credenciais no .env")

                with gr.Accordion("🛠️ Diagnóstico do Ambiente & Remotion Studio", open=False):
                    diag_markdown = gr.Markdown(diag_md)
                    repos_table = gr.Dataframe(
                        label="Repositórios Open-Source & Ferramentas Integradas",
                        headers=["Repositório / Projeto", "Pasta Local", "Status", "Papel no Pipeline"],
                        value=repo_rows,
                        interactive=False,
                        wrap=True,
                    )
                    with gr.Row():
                        remotion_export_btn = gr.Button("📦 Exportar 1º Corte -> Remotion Props")
                        remotion_launch_btn = gr.Button("🚀 Abrir Remotion Studio (npm run dev)")
                    remotion_status = gr.Textbox(label="Status Remotion", interactive=False, lines=2)

        # ================================================================
        # EVENT WIRING
        # ================================================================
        studio_refresh_btn.click(
            action_refresh_studio,
            outputs=[studio_video_dd, cuts_editor, cuts_df, transcript_box, header_html],
        )

        step1_btn.click(
            action_transcribe,
            inputs=[studio_video_dd, lang_dd, model_dd, cache_chk],
            outputs=[logs_box, transcript_box, header_html],
        )

        step2_btn.click(
            action_analyze_context,
            inputs=[duration_dd, max_cuts_slider, distribute_chk, use_llm_pool_chk],
            outputs=[cuts_editor, cuts_df, logs_box],
        )

        save_cuts_btn.click(
            action_save_cuts_json,
            inputs=[cuts_editor],
            outputs=[cuts_editor, cuts_df, logs_box],
        )

        preview_btn.click(
            action_preview_layout,
            inputs=[studio_video_dd, layout_dd],
            outputs=[layout_preview_img, logs_box],
        )

        step3_btn.click(
            action_render_cuts,
            inputs=[
                studio_video_dd,
                layout_dd,
                preset_dd,
                words_slider,
                burn_captions_chk,
                skip_existing_chk,
                precision_retranscribe_chk,
                refine_captions_chk,
            ],
            outputs=[logs_box, rendered_dd, rendered_player, header_html],
        )

        rendered_dd.change(lambda p: p, inputs=[rendered_dd], outputs=[rendered_player])

        one_click_btn.click(
            action_one_click_pipeline,
            inputs=[
                studio_video_dd,
                lang_dd,
                duration_dd,
                max_cuts_slider,
                model_dd,
                layout_dd,
                preset_dd,
                words_slider,
                burn_captions_chk,
                cache_chk,
                distribute_chk,
                skip_existing_chk,
                use_llm_pool_chk,
                precision_retranscribe_chk,
                refine_captions_chk,
            ],
            outputs=[
                logs_box,
                cuts_editor,
                cuts_df,
                transcript_box,
                layout_preview_img,
                rendered_dd,
                rendered_player,
                header_html,
            ],
        )

        # Tab 2 events
        upload_file.upload(
            action_upload_video,
            inputs=[upload_file],
            outputs=[bank_table, bank_video_dd, studio_video_dd, bank_status],
        )
        gen_demo_btn.click(
            action_generate_demo,
            inputs=[demo_lang_dd, demo_dur_slider],
            outputs=[bank_table, bank_video_dd, studio_video_dd, bank_player, bank_status],
        )
        bank_refresh_btn.click(
            action_refresh_bank,
            outputs=[bank_table, bank_video_dd, bank_player],
        )
        bank_video_dd.change(
            lambda fname: str(INPUT_DIR / fname) if fname and (INPUT_DIR / fname).is_file() else None,
            inputs=[bank_video_dd],
            outputs=[bank_player],
        )
        bank_send_btn.click(
            lambda fname: (gr.update(value=fname), f"✅ '{fname}' selecionado na Aba 1 (Estúdio Pipeline)!"),
            inputs=[bank_video_dd],
            outputs=[studio_video_dd, bank_status],
        )
        bank_delete_btn.click(
            action_delete_input_video,
            inputs=[bank_video_dd],
            outputs=[bank_table, bank_video_dd, studio_video_dd, bank_player, bank_status],
        )

        # Tab 2 gallery + selector events
        def _refresh_tab2_all(src: str, dur: str, sel: list[str] | None):
            g_rows, g_srcs, g_labels, g_clips, g_player, g_md = action_refresh_gallery(src, dur)
            choices = _filter_yt_selector_choices(src, dur)
            _, q_rows = _read_yt_queue_ui(sel or [])
            return g_rows, g_srcs, g_labels, g_clips, g_player, g_md, gr.update(choices=choices, value=sel or []), q_rows

        for trigger in (gal_refresh_btn.click, gal_source_dd.change, gal_dur_dd.change):
            trigger(
                _refresh_tab2_all,
                inputs=[gal_source_dd, gal_dur_dd, yt_clip_selector],
                outputs=[gallery_table, gal_source_dd, gal_clip_dd, gallery_state, gal_player, gal_details_md, yt_clip_selector, yt_table],
            )

        yt_clip_selector.change(
            lambda sel: _read_yt_queue_ui(sel or [])[1],
            inputs=[yt_clip_selector],
            outputs=[yt_table],
        )
        yt_sel_all_btn.click(
            lambda s, d: action_yt_select_mode("all", s, d),
            inputs=[gal_source_dd, gal_dur_dd],
            outputs=[yt_clip_selector, yt_table, yt_logs],
        )
        yt_sel_pending_btn.click(
            lambda s, d: action_yt_select_mode("pending", s, d),
            inputs=[gal_source_dd, gal_dur_dd],
            outputs=[yt_clip_selector, yt_table, yt_logs],
        )
        yt_clear_sel_btn.click(
            lambda s, d: action_yt_select_mode("clear", s, d),
            inputs=[gal_source_dd, gal_dur_dd],
            outputs=[yt_clip_selector, yt_table, yt_logs],
        )
        thumb_gen_btn.click(
            action_thumb_generate,
            inputs=[yt_clip_selector],
            outputs=[thumb_gallery, thumb_status],
        )
        thumb_upload_btn.click(
            action_thumb_upload,
            inputs=[yt_clip_selector],
            outputs=[thumb_status],
        )
        gallery_table.select(
            action_select_gallery_row,
            inputs=[gallery_state],
            outputs=[gal_player, gal_details_md],
        )
        gal_clip_dd.change(
            action_select_gallery_dropdown,
            inputs=[gal_clip_dd, gallery_state],
            outputs=[gal_player, gal_details_md],
        )
        gal_open_btn.click(action_open_output_folder, outputs=[gal_status])

        # Tab 4 events
        remotion_export_btn.click(action_export_remotion_props, outputs=[remotion_status])
        remotion_launch_btn.click(action_launch_remotion_studio, outputs=[remotion_status])

        # Tab 5 events
        yt_open_chrome_btn.click(action_yt_open_chrome, outputs=[yt_logs])
        yt_check_btn.click(action_yt_check_status, outputs=[yt_logs])
        yt_refresh_btn.click(
            lambda sel: (*_read_yt_queue_ui(sel or []), "🔄 Fila YouTube atualizada."),
            inputs=[yt_clip_selector],
            outputs=[yt_editor, yt_table, yt_logs],
        )
        yt_sync_api_btn.click(
            action_yt_sync_api,
            inputs=[gal_source_dd, gal_dur_dd, yt_clip_selector],
            outputs=[yt_editor, yt_clip_selector, yt_table, yt_logs],
        )
        yt_save_btn.click(action_yt_save_queue, inputs=[yt_editor], outputs=[yt_editor, yt_table, yt_logs])
        yt_upload_btn.click(
            action_yt_upload_batch,
            inputs=[yt_clip_selector, yt_vis_dd, yt_skip_chk],
            outputs=[yt_logs, yt_editor, yt_table],
        )

        # Tab 6 events
        an_save_cfg_btn.click(
            action_an_save_config,
            inputs=[an_api_key, an_channel_ref],
            outputs=[an_status],
        )
        an_fetch_api_btn.click(
            action_an_fetch_api,
            inputs=[an_api_key, an_channel_ref],
            outputs=[an_summary_md, an_table, an_status],
        )
        an_scrape_studio_btn.click(
            action_an_scrape_studio,
            outputs=[an_summary_md, an_table, an_status],
        )
        an_ai_btn.click(
            action_an_ai_coach,
            outputs=[an_ai_md],
        )

    launch_sig = inspect.signature(demo.launch).parameters
    launch_kwargs: dict[str, Any] = {
        "server_name": "127.0.0.1",
        "server_port": 7860,
        "inbrowser": True,
        "allowed_paths": [str(PROJECT_ROOT)],
    }
    if "theme" in launch_sig and "theme" not in blocks_sig:
        launch_kwargs["theme"] = theme
    if "css" in launch_sig and "css" not in blocks_sig:
        launch_kwargs["css"] = CUSTOM_CSS

    return demo, launch_kwargs


if __name__ == "__main__":
    app, launch_opts = build_ui()
    app.launch(**launch_opts)
