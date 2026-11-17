"""Speech-to-Text transcription calibrated for PT-BR and EN gameplay videos."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np

from src import MODELS_TEMP_DIR, PROJECTS_TEMP_DIR, TEMP_DIR
from src.ffmpeg_utils import ensure_ffmpeg_in_path, get_ffmpeg_path, probe_video_info

PROMPTS_BY_LANGUAGE = {
    "pt": (
        "Gameplay em português brasileiro. Streamer reagindo à partida, clutch, "
        "kill, olha isso, caraca, mano, meu Deus, não acredito, bora, jogada insana."
    ),
    "en": (
        "Gameplay commentary in English. Streamer reacting to the match, clutch, "
        "kill, look at this, oh my god, bro, no way, insane play, let's go."
    ),
}


def normalize_language(language: str | None) -> str | None:
    """Normalize user language selector to 'pt', 'en', or None (auto)."""
    if not language:
        return None
    norm = language.strip().lower()
    if norm in ("auto", "detect", ""):
        return None
    if norm.startswith("pt"):
        return "pt"
    if norm.startswith("en"):
        return "en"
    return norm


def _fmt_mmss(seconds: float) -> str:
    total_sec = max(0, int(round(seconds)))
    h, rem = divmod(total_sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"


def _build_smart_initial_prompt(vpath: Path, norm_lang: str | None) -> str | None:
    """Build Whisper initial_prompt using video_meta.json (title/channel/tags) and recursive channel glossary."""
    parts: list[str] = []

    meta_path = PROJECTS_TEMP_DIR / vpath.stem / "video_meta.json"
    title = ""
    channel = ""
    tags: list[str] = []
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            title = str(meta.get("title") or "").strip()
            channel = str(meta.get("channel") or meta.get("uploader") or "").strip()
            raw_tags = meta.get("tags") or []
            if isinstance(raw_tags, list):
                tags = [str(t).strip() for t in raw_tags if str(t).strip()][:8]
        except Exception:
            pass

    if not title:
        title = " ".join(vpath.stem.replace("_", " ").replace("-", " ").split())[:90]

    if title:
        parts.append(f"Vídeo: {title[:90]}.")
    if channel:
        parts.append(f"Canal: {channel[:40]}.")
    if tags:
        parts.append(f"Termos: {', '.join(tags)[:100]}.")

    glossary_path = TEMP_DIR / "channel_glossary.json"
    if glossary_path.is_file():
        try:
            gdata = json.loads(glossary_path.read_text(encoding="utf-8"))
            terms = gdata.get("terms", []) if isinstance(gdata, dict) else (gdata if isinstance(gdata, list) else [])
            clean_terms = [str(t).strip() for t in terms if str(t).strip()][-20:]
            if clean_terms:
                parts.append(f"Glossário: {', '.join(clean_terms)[:120]}.")
        except Exception:
            pass

    base_prompt = PROMPTS_BY_LANGUAGE.get(norm_lang or "", "")
    if base_prompt:
        parts.append(base_prompt)

    prompt = " ".join(parts).strip()
    return prompt[:420] if prompt else None


def _parse_youtube_json3(json3_path: Path, duration: float = 0.0) -> list[dict[str, Any]]:
    """Parse YouTube .json3 subtitle file into Whisper-compatible segments + word timestamps."""
    data = json.loads(json3_path.read_text(encoding="utf-8"))
    events = data.get("events", [])
    if not isinstance(events, list):
        return []

    segments: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict) or not ev.get("segs"):
            continue
        t_start_ms = int(ev.get("tStartMs", 0) or 0)
        d_dur_ms = int(ev.get("dDurationMs", 0) or 0)
        seg_start = max(0.0, round(t_start_ms / 1000.0, 3))
        if duration > 0 and seg_start >= duration:
            continue

        raw_words: list[tuple[str, float]] = []
        text_parts: list[str] = []
        for seg in ev["segs"]:
            if not isinstance(seg, dict):
                continue
            chunk = str(seg.get("utf8", "")).replace("\n", " ")
            if not chunk.strip():
                continue
            text_parts.append(chunk)
            offset_ms = int(seg.get("tOffsetMs", 0) or 0)
            w_start = max(seg_start, round((t_start_ms + offset_ms) / 1000.0, 3))
            for tok in chunk.split():
                raw_words.append((tok, w_start))

        full_text = " ".join("".join(text_parts).split()).strip()
        if not full_text or not raw_words:
            continue

        # Deduplicate consecutive identical rolling caption lines
        if segments and segments[-1]["text"] == full_text and abs(seg_start - segments[-1]["start"]) < 1.0:
            continue

        seg_end = round((t_start_ms + max(d_dur_ms, 300)) / 1000.0, 3)
        if duration > 0:
            seg_end = min(round(duration, 3), seg_end)
        if seg_end <= seg_start:
            seg_end = round(seg_start + 0.3, 3)

        # Clamp previous segment end if YouTube rolling captions overlap
        if segments and segments[-1]["end"] > seg_start:
            clamped_prev = max(round(segments[-1]["start"] + 0.1, 3), seg_start)
            segments[-1]["end"] = clamped_prev
            if segments[-1]["words"]:
                segments[-1]["words"][-1]["end"] = max(
                    round(segments[-1]["words"][-1]["start"] + 0.04, 3),
                    clamped_prev,
                )

        words: list[dict[str, Any]] = []
        for idx, (tok, w_start) in enumerate(raw_words):
            if idx + 1 < len(raw_words):
                next_start = raw_words[idx + 1][1]
                w_end = max(round(w_start + 0.04, 3), next_start)
            else:
                w_end = max(round(w_start + 0.04, 3), seg_end)
            words.append(
                {
                    "word": tok,
                    "start": w_start,
                    "end": min(seg_end, w_end) if seg_end > w_start else w_end,
                    "probability": 1.0,
                }
            )

        segments.append(
            {
                "start": seg_start,
                "end": seg_end,
                "text": full_text,
                "words": words,
            }
        )

    return segments


def _stabilize_words(raw_words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure monotonic, non-overlapping word timestamps and filter ASR stutter loops."""
    cleaned: list[dict[str, Any]] = []
    prev_end = 0.0
    last_norm = ""
    repeat_streak_starts: list[float] = []

    for w in raw_words:
        text = str(w.get("word", "")).strip()
        if not text:
            continue
        start = float(w.get("start", prev_end))
        end = float(w.get("end", start + 0.12))
        if start < prev_end:
            start = prev_end
        if end <= start:
            end = start + 0.08

        norm_tok = text.lower().strip(".,!?;:\"'")
        if norm_tok and norm_tok == last_norm:
            repeat_streak_starts = [t for t in repeat_streak_starts if start - t <= 1.5]
            repeat_streak_starts.append(start)
            if len(repeat_streak_starts) > 2:
                prev_end = end
                continue
        else:
            last_norm = norm_tok
            repeat_streak_starts = [start] if norm_tok else []

        prob = float(w.get("probability", 1.0))
        cleaned.append(
            {
                "word": text,
                "start": round(start, 3),
                "end": round(end, 3),
                "probability": round(prob, 4),
            }
        )
        prev_end = end
    return cleaned


def _regroup_segments(raw_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Regroup segments along sentence punctuation and natural speech pauses."""
    all_words: list[dict[str, Any]] = []
    for seg in raw_segments:
        words = seg.get("words") or []
        if words:
            all_words.extend(words)
        else:
            txt = str(seg.get("text", "")).strip()
            if txt:
                all_words.append(
                    {
                        "word": txt,
                        "start": float(seg.get("start", 0.0)),
                        "end": float(seg.get("end", 0.5)),
                        "probability": 1.0,
                    }
                )

    all_words = _stabilize_words(all_words)
    if not all_words:
        return []

    grouped: list[dict[str, Any]] = []
    buf: list[dict[str, Any]] = []

    for idx, word in enumerate(all_words):
        buf.append(word)
        next_word = all_words[idx + 1] if idx + 1 < len(all_words) else None
        gap = (next_word["start"] - word["end"]) if next_word else 99.0
        seg_dur = buf[-1]["end"] - buf[0]["start"]
        ends_sentence = word["word"].endswith((".", "!", "?"))

        should_split = (
            next_word is None
            or ends_sentence
            or gap >= 0.55
            or (seg_dur >= 9.0 and (gap >= 0.25 or word["word"].endswith(",")))
            or len(buf) >= 22
        )

        if should_split:
            grouped.append(
                {
                    "id": len(grouped),
                    "start": round(buf[0]["start"], 3),
                    "end": round(buf[-1]["end"], 3),
                    "text": " ".join(w["word"] for w in buf).strip(),
                    "words": buf,
                }
            )
            buf = []

    return grouped


class GameplayTranscriber:
    """Wrapper over faster-whisper with word-level stabilization and caching."""

    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "auto",
        download_root: Path | None = None,
    ) -> None:
        self.model_size = model_size
        self.download_root = Path(download_root or MODELS_TEMP_DIR)
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.device, self.compute_type = self._resolve_device(device, compute_type)
        self._model = None

    @staticmethod
    def _resolve_device(device: str, compute_type: str) -> tuple[str, str]:
        chosen_device = device
        if chosen_device == "auto":
            try:
                import ctranslate2

                chosen_device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                chosen_device = "cpu"

        chosen_compute = compute_type
        if chosen_compute == "auto":
            chosen_compute = "float16" if chosen_device == "cuda" else "int8"

        return chosen_device, chosen_compute

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            # Match physical cores (avoids SMT contention & thermal throttling on CPU)
            cpu_threads = min(8, max(2, (os.cpu_count() or 4) // 2))
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=cpu_threads,
                download_root=str(self.download_root),
            )
        return self._model

    @staticmethod
    def extract_audio_wav(video_path: Path, wav_path: Path) -> Path:
        """Extract 16kHz mono PCM WAV from video for deterministic transcription & RMS analysis."""
        ensure_ffmpeg_in_path()
        ffmpeg_bin = get_ffmpeg_path()
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            "highpass=f=120,lowpass=f=4500,dynaudnorm=f=150:g=15",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0 or not wav_path.is_file():
            raise RuntimeError(f"Falha ao extrair áudio WAV: {proc.stderr.strip()}")
        return wav_path

    @staticmethod
    def _load_wav_float32(wav_path: Path) -> np.ndarray:
        """Load 16kHz mono PCM WAV directly into float32 waveform (avoids PyAV metadata_errors)."""
        with wave.open(str(wav_path), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        if not raw:
            return np.zeros(0, dtype=np.float32)
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    def transcribe(
        self,
        video_path: str | Path,
        language: str = "pt",
        use_cache: bool = True,
        progress_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Transcribe video audio to temp/transcript.json and project cache."""
        vpath = Path(video_path).resolve()
        if not vpath.is_file():
            raise FileNotFoundError(f"Vídeo não encontrado: {vpath}")

        norm_lang = normalize_language(language)
        project_dir = PROJECTS_TEMP_DIR / vpath.stem
        project_dir.mkdir(parents=True, exist_ok=True)
        cached_json = project_dir / "transcript.json"
        active_json = TEMP_DIR / "transcript.json"
        TEMP_DIR.mkdir(parents=True, exist_ok=True)

        video_info = probe_video_info(vpath)
        source_mtime = round(vpath.stat().st_mtime, 2)
        source_size = vpath.stat().st_size

        if use_cache and cached_json.is_file():
            try:
                cached = json.loads(cached_json.read_text(encoding="utf-8"))
                same_file = (
                    cached.get("source_size") == source_size
                    and cached.get("source_mtime") == source_mtime
                    and cached.get("model_size") == self.model_size
                )
                same_lang = norm_lang is None or cached.get("requested_language") == norm_lang
                if same_file and same_lang and cached.get("segments"):
                    active_json.write_text(
                        json.dumps(cached, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    if progress_callback:
                        progress_callback(f"Transcrição carregada do cache ({vpath.name}).")
                    return cached
            except Exception:
                pass

        if not video_info.get("has_audio", True):
            empty_payload = {
                "video_file": vpath.name,
                "video_path": str(vpath),
                "language": norm_lang or "pt",
                "requested_language": norm_lang,
                "language_probability": 0.0,
                "duration": video_info.get("duration", 0.0),
                "model_size": self.model_size,
                "source_size": source_size,
                "source_mtime": source_mtime,
                "segments": [],
            }
            payload_str = json.dumps(empty_payload, ensure_ascii=False, indent=2)
            cached_json.write_text(payload_str, encoding="utf-8")
            active_json.write_text(payload_str, encoding="utf-8")
            return empty_payload

        # Fast-path Passada 1: use YouTube .json3 subtitles when available (avoids local Whisper Passada 1)
        json3_path = project_dir / "youtube_subs.json3"
        if json3_path.is_file():
            try:
                if progress_callback:
                    progress_callback("Lendo legenda oficial/automática do YouTube (.json3)...")
                yt_segments = _parse_youtube_json3(json3_path, float(video_info.get("duration", 0.0) or 0.0))
                if yt_segments:
                    yt_payload = {
                        "video_file": vpath.name,
                        "video_path": str(vpath),
                        "language": norm_lang or "pt",
                        "requested_language": norm_lang,
                        "language_probability": 1.0,
                        "duration": video_info.get("duration", 0.0),
                        "model_size": "youtube-json3",
                        "source_size": source_size,
                        "source_mtime": source_mtime,
                        "segments": yt_segments,
                    }
                    yt_str = json.dumps(yt_payload, ensure_ascii=False, indent=2)
                    cached_json.write_text(yt_str, encoding="utf-8")
                    active_json.write_text(yt_str, encoding="utf-8")
                    if progress_callback:
                        progress_callback(f"Transcrição carregada via YouTube (.json3): {len(yt_segments)} segmentos.")
                    return yt_payload
            except Exception as exc:
                if progress_callback:
                    progress_callback(f"Falha ao ler .json3 ({exc}); usando Whisper local...")

        wav_path = project_dir / "audio_16k.wav"
        wav_fresh = (
            wav_path.is_file()
            and wav_path.stat().st_size > 100_000
            and wav_path.stat().st_mtime >= vpath.stat().st_mtime
        )
        if wav_fresh:
            if progress_callback:
                progress_callback(f"Reutilizando áudio WAV já extraído ({wav_path.name})...")
        else:
            if progress_callback:
                progress_callback(f"Extraindo áudio de {vpath.name}...")
            self.extract_audio_wav(vpath, wav_path)

        if progress_callback:
            progress_callback(
                f"Carregando faster-whisper ({self.model_size}, {self.device}/{self.compute_type})..."
            )
        model = self._get_model()

        initial_prompt = _build_smart_initial_prompt(vpath, norm_lang)
        if progress_callback:
            lang_label = norm_lang.upper() if norm_lang else "AUTO (PT/EN)"
            progress_callback(f"Transcrevendo áudio [{lang_label}] com alinhamento por palavra...")

        audio_array = self._load_wav_float32(wav_path)
        raw_segments: list[dict[str, Any]] = []
        detected_lang = norm_lang or "pt"
        lang_prob = 0.0
        total_dur = max(0.01, float(video_info.get("duration") or (len(audio_array) / 16000.0)))
        partial_json = project_dir / "transcript.partial.json"

        if len(audio_array) > 0:
            try:
                use_batched = total_dur >= 180.0 and self.device == "cpu"
                if use_batched:
                    from faster_whisper import BatchedInferencePipeline

                    batched_model = BatchedInferencePipeline(model=model)
                    segments_iter, info = batched_model.transcribe(
                        audio_array,
                        language=norm_lang,
                        initial_prompt=initial_prompt,
                        beam_size=1,
                        batch_size=4,
                        repetition_penalty=1.18,
                        no_repeat_ngram_size=3,
                        word_timestamps=True,
                        vad_filter=True,
                        vad_parameters={"min_silence_duration_ms": 350, "speech_pad_ms": 150},
                    )
                else:
                    segments_iter, info = model.transcribe(
                        audio_array,
                        language=norm_lang,
                        initial_prompt=initial_prompt,
                        beam_size=3,
                        repetition_penalty=1.18,
                        no_repeat_ngram_size=3,
                        word_timestamps=True,
                        vad_filter=True,
                        vad_parameters={"min_silence_duration_ms": 350, "speech_pad_ms": 150},
                        condition_on_previous_text=False,
                    )

                last_pct = -5.0
                last_ts = -30.0
                for seg in segments_iter:
                    words = []
                    if seg.words:
                        for w in seg.words:
                            words.append(
                                {
                                    "word": w.word.strip(),
                                    "start": round(float(w.start), 3),
                                    "end": round(float(w.end), 3),
                                    "probability": round(float(getattr(w, "probability", 1.0)), 4),
                                }
                            )
                    raw_segments.append(
                        {
                            "start": round(float(seg.start), 3),
                            "end": round(float(seg.end), 3),
                            "text": seg.text.strip(),
                            "words": words,
                        }
                    )
                    seg_end = float(seg.end)
                    pct = min(99.0, (seg_end / total_dur) * 100.0)
                    if progress_callback and (pct - last_pct >= 5.0 or seg_end - last_ts >= 30.0):
                        last_pct = pct
                        last_ts = seg_end
                        progress_callback(
                            f"Transcrevendo: {pct:.0f}% [{_fmt_mmss(seg_end)} / {_fmt_mmss(total_dur)}] "
                            f"({len(raw_segments)} frases)"
                        )
                    if len(raw_segments) % 100 == 0:
                        partial_json.write_text(
                            json.dumps(
                                {"video_file": vpath.name, "segments": raw_segments},
                                ensure_ascii=False,
                            ),
                            encoding="utf-8",
                        )

                detected_lang = getattr(info, "language", None) or norm_lang or "pt"
                lang_prob = round(float(getattr(info, "language_probability", 1.0)), 4)
            except ValueError as exc:
                if "need at least one array" not in str(exc):
                    raise

        stabilized_segments = _regroup_segments(raw_segments)

        payload = {
            "video_file": vpath.name,
            "video_path": str(vpath),
            "language": detected_lang,
            "requested_language": norm_lang,
            "language_probability": lang_prob,
            "duration": video_info.get("duration", 0.0),
            "model_size": self.model_size,
            "source_size": source_size,
            "source_mtime": source_mtime,
            "audio_wav": str(wav_path),
            "segments": stabilized_segments,
        }

        payload_str = json.dumps(payload, ensure_ascii=False, indent=2)
        cached_json.write_text(payload_str, encoding="utf-8")
        active_json.write_text(payload_str, encoding="utf-8")
        partial_json.unlink(missing_ok=True)

        if progress_callback:
            progress_callback(
                f"Transcrição concluída: {len(stabilized_segments)} segmentos ({detected_lang})."
            )
        return payload

    def retranscribe_clip_range(
        self,
        video_path: str | Path,
        start: float,
        end: float,
        language: str = "pt",
        audio_wav_path: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Passada 2: high-precision transcription (beam_size=3) on a single [start, end] clip slice."""
        vpath = Path(video_path).resolve()
        project_dir = PROJECTS_TEMP_DIR / vpath.stem
        wav_path = Path(audio_wav_path) if audio_wav_path else (project_dir / "audio_16k.wav")
        if not wav_path.is_file():
            self.extract_audio_wav(vpath, wav_path)

        with wave.open(str(wav_path), "rb") as wf:
            sr = wf.getframerate()
            total_frames = wf.getnframes()
            f0 = max(0, min(total_frames, int(round(start * sr))))
            f1 = max(f0, min(total_frames, int(round(end * sr))))
            wf.setpos(f0)
            raw = wf.readframes(f1 - f0)

        if not raw:
            return []

        clip_audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if len(clip_audio) < 1600:
            return []

        norm_lang = normalize_language(language)
        initial_prompt = _build_smart_initial_prompt(vpath, norm_lang)

        model = self._get_model()
        segments_iter, _ = model.transcribe(
            clip_audio,
            language=norm_lang,
            initial_prompt=initial_prompt,
            beam_size=3,
            repetition_penalty=1.18,
            no_repeat_ngram_size=3,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
        )

        raw_segments: list[dict[str, Any]] = []
        for seg in segments_iter:
            words = []
            if seg.words:
                for w in seg.words:
                    words.append(
                        {
                            "word": w.word.strip(),
                            "start": round(start + float(w.start), 3),
                            "end": round(start + float(w.end), 3),
                            "probability": round(float(getattr(w, "probability", 1.0)), 4),
                        }
                    )
            raw_segments.append(
                {
                    "start": round(start + float(seg.start), 3),
                    "end": round(start + float(seg.end), 3),
                    "text": seg.text.strip(),
                    "words": words,
                }
            )
        return _regroup_segments(raw_segments)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcreve gameplay com faster-whisper.")
    parser.add_argument("video", help="Caminho do vídeo em input/")
    parser.add_argument("--language", default="pt", choices=["pt", "en", "auto"], help="Idioma principal")
    parser.add_argument("--model", default="small", help="Tamanho do modelo Whisper (tiny, base, small, medium)")
    parser.add_argument("--no-cache", action="store_true", help="Força nova transcrição")
    args = parser.parse_args()

    transcriber = GameplayTranscriber(model_size=args.model)
    result = transcriber.transcribe(
        args.video,
        language=args.language,
        use_cache=not args.no_cache,
        progress_callback=print,
    )
    print(f"Salvo em temp/transcript.json ({len(result['segments'])} segmentos)")


if __name__ == "__main__":
    main()
