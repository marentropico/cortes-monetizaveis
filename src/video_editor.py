"""FFmpeg-based vertical 9:16 video cutter, split-screen compositor, and hardware-accelerated renderer."""

from __future__ import annotations

import argparse
import json
import queue
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src import OUTPUT_DIR, PROJECT_ROOT, PROJECTS_TEMP_DIR, TEMP_DIR
from src.captioner import ASSCaptionGenerator, load_transcript
from src.face_detector import FaceCropResult, FacecamDetector, _compute_gameplay_crop, _even
from src.ffmpeg_utils import (
    detect_best_h264_encoder,
    ensure_ffmpeg_in_path,
    get_ffmpeg_path,
    get_h264_encoder_args,
    probe_video_info,
)

PROJECTS_INDEX_FILE = OUTPUT_DIR / "projects_index.json"


def _load_projects_index() -> list[dict[str, Any]]:
    if PROJECTS_INDEX_FILE.is_file():
        try:
            data = json.loads(PROJECTS_INDEX_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def _save_projects_index(records: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_INDEX_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_rendered_clips() -> list[dict[str, Any]]:
    """Return catalog of rendered Shorts clips with metadata, filtering missing files."""
    records = _load_projects_index()
    known_paths: set[str] = set()
    valid: list[dict[str, Any]] = []

    for rec in records:
        clip_path = Path(rec.get("output_path", ""))
        if not clip_path.is_absolute():
            clip_path = PROJECT_ROOT / clip_path
        if clip_path.is_file():
            rec["output_path"] = str(clip_path)
            known_paths.add(str(clip_path.resolve()))
            valid.append(rec)

    # Also discover any orphaned .mp4 files in output/
    if OUTPUT_DIR.exists():
        for mp4 in sorted(OUTPUT_DIR.rglob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
            resolved = str(mp4.resolve())
            if resolved not in known_paths:
                try:
                    info = probe_video_info(mp4)
                except Exception:
                    info = {"duration": 0.0, "size_mb": round(mp4.stat().st_size / (1024 * 1024), 2)}
                valid.append(
                    {
                        "id": mp4.stem,
                        "title": mp4.stem,
                        "source_video": mp4.parent.name if mp4.parent != OUTPUT_DIR else "Desconhecido",
                        "output_path": str(mp4),
                        "duration": info.get("duration", 0.0),
                        "duration_type": "custom",
                        "size_mb": info.get("size_mb", 0.0),
                        "layout_mode": "9:16",
                        "hook_text": "",
                        "context_reason": "Detectado na pasta output/",
                        "created_at": datetime.fromtimestamp(mp4.stat().st_mtime).isoformat(timespec="seconds"),
                    }
                )

    valid.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return valid


class VerticalVideoEditor:
    """Renders 1080x1920 Shorts/Reels from temp/cuts.json and temp/transcript.json."""

    def __init__(
        self,
        caption_preset: str = "hormozi",
        words_per_line: int = 3,
        burn_captions: bool = True,
    ) -> None:
        ensure_ffmpeg_in_path()
        self.ffmpeg_bin = get_ffmpeg_path()
        self.preferred_encoder = detect_best_h264_encoder()
        self.captioner = ASSCaptionGenerator(preset=caption_preset, words_per_line=words_per_line)
        self.burn_captions = burn_captions
        self.face_detector = FacecamDetector()

    @staticmethod
    def _ensure_circle_mask_png(size: int = 340) -> Path:
        """Create/reuse an anti-aliased grayscale circular alpha mask PNG for pip_split."""
        mask_path = TEMP_DIR / f"pip_circle_mask_{size}.png"
        if mask_path.is_file():
            return mask_path
        import cv2
        import numpy as np

        mask_path.parent.mkdir(parents=True, exist_ok=True)
        mask = np.zeros((size, size), dtype=np.uint8)
        cv2.circle(mask, (size // 2, size // 2), size // 2 - 4, 255, -1, cv2.LINE_AA)
        mask = cv2.GaussianBlur(mask, (3, 3), 0)
        cv2.imwrite(str(mask_path), mask)
        return mask_path

    @staticmethod
    def _ensure_scaled_brand_png(src_path: Path, cache_name: str, max_w: int = 460, max_h: int = 250) -> Path:
        """Pre-scale branding PNG once into temp/ to avoid per-frame 3K Lanczos scaling."""
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        dst_path = TEMP_DIR / cache_name
        if dst_path.is_file() and dst_path.stat().st_mtime >= src_path.stat().st_mtime:
            return dst_path
        from PIL import Image

        with Image.open(src_path) as img:
            rgba = img.convert("RGBA")
            rgba.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            # Ensure even dimensions for FFmpeg filters
            ew = max(2, rgba.width - (rgba.width % 2))
            eh = max(2, rgba.height - (rgba.height % 2))
            if (ew, eh) != (rgba.width, rgba.height):
                rgba = rgba.resize((ew, eh), Image.Resampling.LANCZOS)
            rgba.save(dst_path, format="PNG")
        return dst_path

    @classmethod
    def _get_branding_assets(cls) -> tuple[Path, Path | None] | None:
        """Return pre-scaled (logo, follow | None) from temp/ if assets/logo.png exists."""
        assets_dir = PROJECT_ROOT / "assets"
        logo = assets_dir / "logo.png"
        follow = assets_dir / "follow.png"
        if logo.is_file():
            scaled_logo = cls._ensure_scaled_brand_png(logo, "brand_logo_460.png")
            scaled_follow = (
                cls._ensure_scaled_brand_png(follow, "brand_follow_460.png")
                if follow.is_file()
                else None
            )
            return scaled_logo, scaled_follow
        return None

    def _build_filter_complex(
        self,
        crop_info: FaceCropResult,
        ass_rel_posix: str | None,
        clip_duration: float = 30.0,
        track_info: dict[str, Any] | None = None,
    ) -> tuple[str, list[Path]]:
        sub_suffix = f",subtitles='{ass_rel_posix}'" if ass_rel_posix else ""

        if crop_info.mode == "pip_split" and crop_info.face_crop:
            fc = crop_info.face_crop
            gc = crop_info.gameplay_crop
            side = min(fc["w"], fc["h"])
            fx = fc["x"] + (fc["w"] - side) // 2
            fy = fc["y"] + (fc["h"] - side) // 2
            mask_path = self._ensure_circle_mask_png(340)
            extra_inputs: list[Path] = [mask_path]

            if track_info and track_info.get("cmd_file"):
                ic = track_info["initial_crop"]
                ia = float(track_info.get("initial_alpha", 1.0))
                cmd_rel = Path(track_info["cmd_file"]).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
                face_chain = (
                    f"[vface]sendcmd=f='{cmd_rel}',"
                    f"crop@facecrop=w={ic['w']}:h={ic['h']}:x={ic['x']}:y={ic['y']},"
                    "scale=340:340:flags=lanczos,setsar=1,format=rgba[f_rgba];"
                    "[1:v]format=gray[mask];"
                    f"[f_rgba][mask]alphamerge,colorchannelmixer@facealpha=aa={ia:.2f}[f_circ];"
                )
            elif track_info and track_info.get("is_static") and track_info.get("initial_crop"):
                ic = track_info["initial_crop"]
                face_chain = (
                    f"[vface]crop={ic['w']}:{ic['h']}:{ic['x']}:{ic['y']},"
                    "scale=340:340:flags=lanczos,setsar=1,format=rgba[f_rgba];"
                    "[1:v]format=gray[mask];"
                    "[f_rgba][mask]alphamerge[f_circ];"
                )
            else:
                face_chain = (
                    f"[vface]crop={side}:{side}:{fx}:{fy},"
                    "scale=340:340:flags=lanczos,setsar=1,format=rgba[f_rgba];"
                    "[1:v]format=gray[mask];"
                    "[f_rgba][mask]alphamerge[f_circ];"
                )

            base_chain = (
                "[0:v]setpts=PTS-STARTPTS,fps=30,split=3[vtop][vbot][vface];"
                "[vtop]scale=1080:608:flags=lanczos,setsar=1[top];"
                f"[vbot]crop={gc['w']}:{gc['h']}:{gc['x']}:{gc['y']},"
                "scale=1080:1312:flags=lanczos,setsar=1[bot];"
                "[top][bot]vstack=inputs=2[base];"
                + face_chain
            )

            branding = self._get_branding_assets()
            if branding is not None:
                logo_path, follow_path = branding
                extra_inputs.append(logo_path)
                if follow_path is not None:
                    extra_inputs.append(follow_path)
                    dur = max(6.0, float(clip_duration))
                    t1 = round(dur * 0.42, 3)
                    t2 = round(max(t1 + 2.0, dur * 0.85), 3)
                    pop_follow = (
                        f"if(lt(t-{t1:.3f},0.16),0.72+0.40*(t-{t1:.3f})/0.16,"
                        f"if(lt(t-{t1:.3f},0.28),1.12-0.12*(t-{t1:.3f}-0.16)/0.12,1.0))"
                    )
                    pop_logo_ret = (
                        f"if(gte(t,{t2:.3f}),"
                        f"if(lt(t-{t2:.3f},0.16),0.72+0.40*(t-{t2:.3f})/0.16,"
                        f"if(lt(t-{t2:.3f},0.28),1.12-0.12*(t-{t2:.3f}-0.16)/0.12,1.0)),"
                        "1.0)"
                    )
                    fc_str = (
                        base_chain
                        + "[base][f_circ]overlay=x=696:y=438:shortest=1[base_circ];"
                        + "[2:v]format=rgba,colorchannelmixer=aa=0.50,"
                        + f"scale=w='trunc(iw*{pop_logo_ret}/2)*2':h=-2:eval=frame:flags=bilinear[brand_logo];"
                        + "[3:v]format=rgba,colorchannelmixer=aa=0.50,"
                        + f"scale=w='trunc(iw*{pop_follow}/2)*2':h=-2:eval=frame:flags=bilinear[brand_follow];"
                        + f"[base_circ][brand_logo]overlay=x=420-w/2:y=608-h/2:enable='lt(t,{t1:.3f})+gte(t,{t2:.3f})':shortest=1[base_b1];"
                        + f"[base_b1][brand_follow]overlay=x=420-w/2:y=608-h/2:enable='gte(t,{t1:.3f})*lt(t,{t2:.3f})':shortest=1"
                        + f"{sub_suffix}[vout]"
                    )
                else:
                    fc_str = (
                        base_chain
                        + "[base][f_circ]overlay=x=696:y=438:shortest=1[base_circ];"
                        + "[2:v]format=rgba,colorchannelmixer=aa=0.50[brand_logo];"
                        + f"[base_circ][brand_logo]overlay=x=420-w/2:y=608-h/2:shortest=1{sub_suffix}[vout]"
                    )
            else:
                fc_str = (
                    base_chain
                    + f"[base][f_circ]overlay=x=696:y=438:shortest=1{sub_suffix}[vout]"
                )
            return fc_str, extra_inputs

        if crop_info.mode == "split_screen" and crop_info.face_crop:
            fc = crop_info.face_crop
            gc = crop_info.gameplay_crop
            return (
                "[0:v]setpts=PTS-STARTPTS,fps=30,split=2[vtop][vbot];"
                f"[vtop]crop={fc['w']}:{fc['h']}:{fc['x']}:{fc['y']},"
                "scale=1080:640:flags=lanczos,setsar=1[top];"
                f"[vbot]crop={gc['w']}:{gc['h']}:{gc['x']}:{gc['y']},"
                "scale=1080:1280:flags=lanczos,setsar=1[bot];"
                f"[top][bot]vstack=inputs=2{sub_suffix}[vout]"
            ), []

        if crop_info.mode == "center_only":
            gc = crop_info.gameplay_crop
            return (
                "[0:v]setpts=PTS-STARTPTS,fps=30,"
                f"crop={gc['w']}:{gc['h']}:{gc['x']}:{gc['y']},"
                f"scale=1080:1920:flags=lanczos,setsar=1{sub_suffix}[vout]"
            ), []

        # blur_bg mode
        bg_crop = _compute_gameplay_crop(crop_info.frame_width, crop_info.frame_height, 1080, 1920)
        src_ar = crop_info.frame_width / max(1, crop_info.frame_height)
        if src_ar >= (1080.0 / 1920.0):
            fg_w = 1080
            fg_h = _even(int(round(1080.0 / src_ar)))
        else:
            fg_h = 1920
            fg_w = _even(int(round(1920.0 * src_ar)))

        return (
            "[0:v]setpts=PTS-STARTPTS,fps=30,split=2[vbg][vfg];"
            f"[vbg]crop={bg_crop['w']}:{bg_crop['h']}:{bg_crop['x']}:{bg_crop['y']},"
            "scale=1080:1920:flags=bilinear,boxblur=25:5,eq=brightness=-0.12,setsar=1[bg];"
            f"[vfg]scale={fg_w}:{fg_h}:flags=lanczos,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2{sub_suffix}[vout]"
        ), []

    def _run_ffmpeg_render(
        self,
        video_path: Path,
        start: float,
        duration: float,
        filter_complex: str,
        has_audio: bool,
        output_file: Path,
        encoder: str,
        extra_inputs: list[Path] | None = None,
    ) -> tuple[bool, str]:
        def _build_cmd(use_hwaccel: bool) -> list[str]:
            cmd = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
            if use_hwaccel:
                cmd.extend(["-hwaccel", "d3d11va"])
            cmd.extend(["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video_path)])
            for extra_inp in extra_inputs or []:
                cmd.extend(["-loop", "1", "-r", "30", "-t", f"{duration:.3f}", "-i", str(extra_inp)])

            cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]"])
            if has_audio:
                cmd.extend(
                    ["-map", "0:a", "-af", "asetpts=PTS-STARTPTS", "-c:a", "aac", "-b:a", "192k", "-ar", "44100"]
                )
            cmd.extend(get_h264_encoder_args(encoder))
            cmd.extend(["-r", "30", "-movflags", "+faststart", str(output_file)])
            return cmd

        for hwaccel in (True, False):
            proc = subprocess.run(
                _build_cmd(hwaccel),
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if proc.returncode == 0:
                return True, ""
            if not hwaccel:
                return False, proc.stderr.strip()
        return False, "FFmpeg render failed"

    def _load_or_detect_video_facecam(
        self,
        vpath: Path,
        layout_mode: str,
        cuts: list[dict[str, Any]],
        total_dur: float,
        progress_callback: Callable[[str], None] | None = None,
    ) -> FaceCropResult:
        """Detect facecam once for the entire video and cache coordinates to speed up large batches."""
        proj_temp = PROJECTS_TEMP_DIR / vpath.stem
        proj_temp.mkdir(parents=True, exist_ok=True)
        cache_file = proj_temp / "facecam_cache.json"
        source_size = vpath.stat().st_size
        source_mtime = round(vpath.stat().st_mtime, 2)

        if cache_file.is_file():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if (
                    cached.get("layout_version") == 2
                    and cached.get("source_size") == source_size
                    and cached.get("source_mtime") == source_mtime
                    and cached.get("layout_mode") == layout_mode
                    and "result" in cached
                ):
                    if progress_callback:
                        progress_callback(f"Facecam carregada do cache para {vpath.name} ({cached['result']['mode']}).")
                    return FaceCropResult(**cached["result"])
            except Exception:
                pass

        # Sample across up to 3 cuts spread through the timeline for robust detection
        sample_start = max(0.0, float(cuts[0].get("start", 0.0)))
        sample_end = min(total_dur, float(cuts[-1].get("end", sample_start + 30.0))) if total_dur > 0 else sample_start + 30.0
        if progress_callback:
            progress_callback(f"Analisando facecam uma única vez para o vídeo {vpath.name}...")

        res = self.face_detector.detect_facecam(
            vpath,
            start=sample_start,
            end=max(sample_start + 1.0, sample_end),
            layout_mode=layout_mode,
            num_samples=14,
        )
        cache_payload = {
            "layout_version": 2,
            "source_size": source_size,
            "source_mtime": source_mtime,
            "layout_mode": layout_mode,
            "result": res.to_dict(),
        }
        cache_file.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return res

    def render_cuts(
        self,
        video_path: str | Path,
        cuts_path: str | Path | None = None,
        transcript_path: str | Path | None = None,
        layout_mode: str = "auto",
        progress_callback: Callable[[str], None] | None = None,
        cache_facecam_per_video: bool = True,
        skip_existing: bool = False,
        precision_retranscribe: bool = True,
        refine_captions_with_llm: bool = True,
        dynamic_face_tracking: bool = True,
        face_track_mode: str = "pinned",
    ) -> list[dict[str, Any]]:
        """Render all cuts listed in cuts.json into output/<video_stem>/."""
        vpath = Path(video_path).resolve()
        if not vpath.is_file():
            raise FileNotFoundError(f"Vídeo não encontrado: {vpath}")

        cpath = Path(cuts_path or (TEMP_DIR / "cuts.json"))
        if not cpath.is_file():
            raise FileNotFoundError(f"Arquivo cuts.json não encontrado em {cpath}")

        cuts = json.loads(cpath.read_text(encoding="utf-8"))
        if not isinstance(cuts, list) or not cuts:
            raise ValueError("O arquivo cuts.json está vazio ou inválido.")

        tpath = Path(transcript_path or (TEMP_DIR / "transcript.json"))
        transcript_data = load_transcript(tpath) if tpath.is_file() else {"segments": []}

        video_info = probe_video_info(vpath)
        has_audio = bool(video_info.get("has_audio", False))
        total_dur = float(video_info.get("duration") or 0.0)

        project_out_dir = OUTPUT_DIR / vpath.stem
        project_out_dir.mkdir(parents=True, exist_ok=True)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

        rendered_records: list[dict[str, Any]] = []
        existing_index = _load_projects_index()
        precision_transcriber = None

        cached_crop_res: FaceCropResult | None = None
        if cache_facecam_per_video:
            cached_crop_res = self._load_or_detect_video_facecam(
                vpath=vpath,
                layout_mode=layout_mode,
                cuts=cuts,
                total_dur=total_dur,
                progress_callback=progress_callback,
            )

        prep_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=2)
        stop_event = threading.Event()

        def _producer() -> None:
            nonlocal precision_transcriber
            try:
                for idx, cut in enumerate(cuts, start=1):
                    if stop_event.is_set():
                        break
                    cut_id = int(cut.get("id", idx))
                    title = str(cut.get("title") or f"Corte_{cut_id}").strip()
                    safe_title = "".join(ch if (ch.isalnum() or ch in ("_", "-")) else "_" for ch in title)[:55]
                    c_start = max(0.0, float(cut["start"]))
                    c_end = float(cut["end"])
                    if total_dur > 0:
                        c_end = min(total_dur, c_end)
                    duration = round(c_end - c_start, 3)
                    if duration < 1.5:
                        continue

                    out_mp4 = project_out_dir / f"{cut_id:02d}_{safe_title}.mp4"
                    if skip_existing and out_mp4.is_file() and out_mp4.stat().st_size > 10_240:
                        try:
                            clip_info = probe_video_info(out_mp4)
                            if float(clip_info.get("duration", 0)) < 1.0:
                                raise ValueError("Duração inválida")
                            if progress_callback:
                                progress_callback(f"[{idx}/{len(cuts)}] Pulando corte já renderizado: {out_mp4.name}")
                            existing_rec = next(
                                (r for r in existing_index if r.get("output_path") == str(out_mp4)),
                                None,
                            )
                            record = existing_rec or {
                                "id": cut_id,
                                "title": safe_title,
                                "source_video": vpath.name,
                                "source_stem": vpath.stem,
                                "output_path": str(out_mp4),
                                "start": c_start,
                                "end": c_end,
                                "duration": clip_info.get("duration", duration),
                                "duration_type": cut.get("duration_type", f"{int(round(duration))}s"),
                                "size_mb": clip_info.get("size_mb", 0.0),
                                "layout_mode": cached_crop_res.mode if cached_crop_res else layout_mode,
                                "encoder": self.preferred_encoder,
                                "hook_text": cut.get("hook_text", ""),
                                "context_reason": cut.get("context_reason", ""),
                                "created_at": datetime.fromtimestamp(out_mp4.stat().st_mtime).isoformat(timespec="seconds"),
                            }
                            prep_queue.put({"kind": "skipped", "record": record, "out_mp4": out_mp4})
                            continue
                        except Exception:
                            if progress_callback:
                                progress_callback(f"[{idx}/{len(cuts)}] Arquivo incompleto detectado ({out_mp4.name}); re-renderizando...")
                            out_mp4.unlink(missing_ok=True)

                    if cached_crop_res is not None:
                        crop_res = cached_crop_res
                    else:
                        if progress_callback:
                            progress_callback(f"[{idx}/{len(cuts)}] Analisando facecam para '{safe_title}'...")
                        crop_res = self.face_detector.detect_facecam(
                            vpath,
                            start=c_start,
                            end=c_end,
                            layout_mode=layout_mode,
                            num_samples=10,
                        )

                    ass_rel_posix: str | None = None
                    if self.burn_captions:
                        clip_segs = [
                            s
                            for s in transcript_data.get("segments", [])
                            if float(s.get("end", 0.0)) >= c_start and float(s.get("start", 0.0)) <= c_end
                        ]
                        clip_lang = str(transcript_data.get("language", "pt"))

                        if precision_retranscribe:
                            try:
                                if precision_transcriber is None:
                                    from src.transcriber import GameplayTranscriber

                                    if progress_callback:
                                        progress_callback("Passada 2: carregando Whisper 'small' (beam=5) para legendas de alta precisão...")
                                    precision_transcriber = GameplayTranscriber(model_size="small")
                                if progress_callback:
                                    progress_callback(f"[{idx}/{len(cuts)}] Re-transcrevendo trecho #{cut_id} com alta precisão...")
                                refined_segs = precision_transcriber.retranscribe_clip_range(
                                    vpath,
                                    start=c_start,
                                    end=c_end,
                                    language=clip_lang,
                                    audio_wav_path=transcript_data.get("audio_wav"),
                                )
                                if refined_segs:
                                    clip_segs = refined_segs
                            except Exception as exc:
                                if progress_callback:
                                    progress_callback(f"Passada 2 ignorada em #{cut_id} ({exc}); usando transcrição base.")

                        if refine_captions_with_llm and clip_segs:
                            try:
                                from src.llm_pool import has_active_pool, refine_segment_captions_with_pool

                                if has_active_pool():
                                    clip_segs, used_llm = refine_segment_captions_with_pool(
                                        clip_segs,
                                        game_context=vpath.stem,
                                        language=clip_lang,
                                    )
                                    if progress_callback:
                                        progress_callback(f"[{idx}/{len(cuts)}] Legendas lapidadas via {used_llm}.")
                            except Exception as exc:
                                if progress_callback:
                                    progress_callback(f"Lapidação LLM ignorada em #{cut_id} ({exc}).")

                        ass_path = TEMP_DIR / f"cut_{cut_id}.ass"
                        self.captioner.generate_ass(
                            transcript_data={"segments": clip_segs},
                            cut_start=c_start,
                            cut_end=c_end,
                            output_ass_path=ass_path,
                            hook_text=str(cut.get("hook_text", "")),
                            layout_mode=crop_res.mode,
                        )
                        ass_rel_posix = ass_path.relative_to(PROJECT_ROOT).as_posix()

                    if face_track_mode == "quick_detect" and layout_mode == "auto" and crop_res.mode != "pip_split":
                        fw, fh = crop_res.frame_width, crop_res.frame_height
                        fsz = _even(min(fw, fh) // 3)
                        crop_res = FaceCropResult(
                            detected=True,
                            mode="pip_split",
                            detector_backend=crop_res.detector_backend,
                            frame_width=fw,
                            frame_height=fh,
                            face_crop={"x": _even((fw - fsz) // 2), "y": _even((fh - fsz) // 3), "w": fsz, "h": fsz},
                            gameplay_crop=_compute_gameplay_crop(fw, fh, 1080, 1312),
                            confidence=crop_res.confidence,
                            detections_count=crop_res.detections_count,
                            samples_count=crop_res.samples_count,
                        )

                    track_info: dict[str, Any] | None = None
                    if dynamic_face_tracking and crop_res.mode == "pip_split" and crop_res.face_crop:
                        try:
                            from src.face_tracker import track_face_in_cut

                            if progress_callback:
                                mode_lbl = "Quick Detect" if face_track_mode == "quick_detect" else "Rosto Pinnado"
                                progress_callback(f"[{idx}/{len(cuts)}] Rastreando rosto ({mode_lbl}) no trecho #{cut_id}...")
                            track_info = track_face_in_cut(
                                video_path=vpath,
                                start=c_start,
                                end=c_end,
                                fallback_crop=crop_res.face_crop,
                                cmd_output_path=TEMP_DIR / f"track_cmds_{cut_id}.txt",
                                sample_fps=3.0,
                                mode=face_track_mode,
                            )
                        except Exception as exc:
                            if progress_callback:
                                progress_callback(f"Tracking dinâmico ignorado em #{cut_id} ({exc}); usando crop fixo.")
                            track_info = None

                    filter_complex, extra_inputs = self._build_filter_complex(
                        crop_res, ass_rel_posix, clip_duration=duration, track_info=track_info
                    )
                    prep_queue.put(
                        {
                            "kind": "render",
                            "idx": idx,
                            "cut": cut,
                            "cut_id": cut_id,
                            "safe_title": safe_title,
                            "c_start": c_start,
                            "c_end": c_end,
                            "duration": duration,
                            "out_mp4": out_mp4,
                            "crop_res": crop_res,
                            "filter_complex": filter_complex,
                            "extra_inputs": extra_inputs,
                        }
                    )
            except Exception as exc:
                prep_queue.put({"kind": "error", "error": exc})
            finally:
                prep_queue.put(None)

        prep_thread = threading.Thread(target=_producer, daemon=True)
        prep_thread.start()

        try:
            while True:
                item = prep_queue.get()
                if item is None:
                    break
                if item["kind"] == "error":
                    raise item["error"]
                if item["kind"] == "skipped":
                    record = item["record"]
                    out_mp4 = item["out_mp4"]
                    rendered_records.append(record)
                    existing_index = [r for r in existing_index if r.get("output_path") != str(out_mp4)]
                    existing_index.insert(0, record)
                    _save_projects_index(existing_index)
                    continue

                idx = item["idx"]
                cut = item["cut"]
                cut_id = item["cut_id"]
                safe_title = item["safe_title"]
                c_start = item["c_start"]
                c_end = item["c_end"]
                duration = item["duration"]
                out_mp4 = item["out_mp4"]
                crop_res = item["crop_res"]
                filter_complex = item["filter_complex"]
                extra_inputs = item["extra_inputs"]

                if progress_callback:
                    progress_callback(
                        f"[{idx}/{len(cuts)}] Renderizando {out_mp4.name} ({crop_res.mode}, {self.preferred_encoder})..."
                    )

                ok, err = self._run_ffmpeg_render(
                    video_path=vpath,
                    start=c_start,
                    duration=duration,
                    filter_complex=filter_complex,
                    has_audio=has_audio,
                    output_file=out_mp4,
                    encoder=self.preferred_encoder,
                    extra_inputs=extra_inputs,
                )
                used_encoder = self.preferred_encoder

                if not ok and self.preferred_encoder != "libx264":
                    if progress_callback:
                        progress_callback(f"Fallback automático para libx264 em {out_mp4.name}...")
                    used_encoder = "libx264"
                    ok, err = self._run_ffmpeg_render(
                        video_path=vpath,
                        start=c_start,
                        duration=duration,
                        filter_complex=filter_complex,
                        has_audio=has_audio,
                        output_file=out_mp4,
                        encoder="libx264",
                        extra_inputs=extra_inputs,
                    )

                if not ok:
                    raise RuntimeError(f"Erro ao renderizar {out_mp4.name}: {err}")

                clip_info = probe_video_info(out_mp4)
                record = {
                    "id": cut_id,
                    "title": safe_title,
                    "source_video": vpath.name,
                    "source_stem": vpath.stem,
                    "output_path": str(out_mp4),
                    "start": c_start,
                    "end": c_end,
                    "duration": clip_info.get("duration", duration),
                    "duration_type": cut.get("duration_type", f"{int(round(duration))}s"),
                    "size_mb": clip_info.get("size_mb", 0.0),
                    "layout_mode": crop_res.mode,
                    "encoder": used_encoder,
                    "hook_text": cut.get("hook_text", ""),
                    "context_reason": cut.get("context_reason", ""),
                    "youtube_title": cut.get("youtube_title", ""),
                    "youtube_description": cut.get("youtube_description", ""),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
                rendered_records.append(record)

                # Save index incrementally after each clip for safe batch resume
                existing_index = [r for r in existing_index if r.get("output_path") != str(out_mp4)]
                existing_index.insert(0, record)
                _save_projects_index(existing_index)
        finally:
            stop_event.set()
            prep_thread.join(timeout=2.0)

        if progress_callback:
            progress_callback(f"Renderização concluída: {len(rendered_records)} Shorts salvos em {project_out_dir}")
        return rendered_records


def main() -> None:
    parser = argparse.ArgumentParser(description="Renderiza cortes verticais 9:16 a partir de temp/cuts.json")
    parser.add_argument("video", help="Caminho do vídeo original em input/")
    parser.add_argument("--cuts", default=str(TEMP_DIR / "cuts.json"))
    parser.add_argument("--transcript", default=str(TEMP_DIR / "transcript.json"))
    parser.add_argument("--layout", default="auto", choices=["auto", "top_left", "top_right", "mid_left", "mid_right", "bottom_left", "bottom_right", "center_only", "blur_bg"])
    parser.add_argument("--preset", default="hormozi", choices=["hormozi", "gamer_neon", "clean_white"])
    parser.add_argument("--no-captions", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--no-facecam-cache", action="store_true")
    args = parser.parse_args()

    editor = VerticalVideoEditor(caption_preset=args.preset, burn_captions=not args.no_captions)
    editor.render_cuts(
        args.video,
        cuts_path=args.cuts,
        transcript_path=args.transcript,
        layout_mode=args.layout,
        progress_callback=print,
        cache_facecam_per_video=not args.no_facecam_cache,
        skip_existing=args.skip_existing,
    )


if __name__ == "__main__":
    main()
