"""Local contextual highlight & topic segmentation engine (zero external LLM APIs)."""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
import wave
from pathlib import Path
from typing import Any

import numpy as np

from src import TEMP_DIR

DURATION_CONFIGS: dict[str, tuple[float, float, float]] = {
    "30s": (22.0, 30.0, 35.0),
    "60s": (45.0, 60.0, 66.0),
    "90s": (72.0, 90.0, 95.0),
}

STOPWORDS_PT_EN = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "pra", "com", "sem", "e", "ou", "mas",
    "que", "se", "eu", "tu", "ele", "ela", "nos", "você", "voce", "eles", "elas", "é", "eh",
    "foi", "vai", "tá", "ta", "tô", "to", "aqui", "ali", "lá", "la", "isso", "isto", "esse",
    "the", "an", "and", "or", "but", "if", "in", "on", "at", "to", "for", "of", "with",
    "is", "are", "was", "were", "be", "been", "i", "you", "he", "she", "it", "we", "they",
    "this", "that", "there", "here", "so", "just", "like", "yeah", "uh", "um",
}

REACTION_PATTERNS_PT = [
    (r"\b(olha isso|se liga|olha só|escuta isso|presta atenção)\b", 2.4, "Gancho visual/verbal"),
    (r"\b(não acredito|nao acredito|mentira|impossível|impossivel|absurdo|insano)\b", 2.6, "Clímax/Surpresa"),
    (r"\b(caraca|caramba|meu deus|nossa|eita|vixe|mds|socorro)\b", 2.1, "Reação intensa"),
    (r"\b(clutch|matei|morri|ganhamos|perdemos|deu bom|deu ruim|gg|ace|headshot)\b", 2.2, "Ação de gameplay"),
    (r"\b(mano|velho|cara|brother|peraí|perai|cuidado|corre|vai vai)\b", 1.5, "Urgência/Interação"),
    (r"(kkkk+|haha+|rsrs+)", 1.9, "Humor/Risada"),
]

REACTION_PATTERNS_EN = [
    (r"\b(look at this|watch this|check this out|listen up|wait a second)\b", 2.4, "Hook opener"),
    (r"\b(no way|unbelievable|impossible|insane|crazy|oh my god|omg|holy)\b", 2.6, "Climax/Surprise"),
    (r"\b(what the|wtf|bro|dude|seriously|how did|why would)\b", 1.8, "Strong reaction"),
    (r"\b(clutch|let'?s go|lets go|dead|eliminated|headshot|gg|we won|run run|watch out)\b", 2.2, "Gameplay peak"),
    (r"(haha+|lmao+|lmfao+|lol+)", 1.9, "Humor/Laugh"),
]

HOOK_OPENERS = (
    "olha", "se liga", "escuta", "sabia", "cuidado", "espera", "pera", "mano", "caraca",
    "nunca", "por que", "como", "quem", "look", "watch", "wait", "listen", "bro", "dude",
    "why", "how", "never", "no way", "oh my",
)


def _tokenize(text: str) -> list[str]:
    clean = unicodedata.normalize("NFKD", text.lower())
    clean = "".join(ch for ch in clean if not unicodedata.combining(ch))
    tokens = re.findall(r"[a-z0-9']+", clean)
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS_PT_EN]


def _texttiling_boundaries(segments: list[dict[str, Any]], window_k: int = 3) -> set[int]:
    """Detect topical shift segment indices using TextTiling (ClipsAI-inspired)."""
    n = len(segments)
    if n < 5:
        return {0}

    vocab: dict[str, int] = {}
    seg_tokens: list[list[str]] = []
    for seg in segments:
        toks = _tokenize(seg.get("text", ""))
        seg_tokens.append(toks)
        for tok in toks:
            if tok not in vocab:
                vocab[tok] = len(vocab)

    if not vocab:
        return {0}

    mat = np.zeros((n, len(vocab)), dtype=np.float32)
    for i, toks in enumerate(seg_tokens):
        for tok in toks:
            mat[i, vocab[tok]] += 1.0
        norm = np.linalg.norm(mat[i])
        if norm > 0:
            mat[i] /= norm

    k = min(window_k, max(1, n // 4))
    gap_scores = np.zeros(n - 1, dtype=np.float32)
    for i in range(n - 1):
        left = mat[max(0, i - k + 1) : i + 1].mean(axis=0)
        right = mat[i + 1 : min(n, i + 1 + k)].mean(axis=0)
        denom = float(np.linalg.norm(left) * np.linalg.norm(right))
        sim = float(np.dot(left, right) / denom) if denom > 1e-8 else 0.0
        gap_scores[i] = sim

    if len(gap_scores) >= 3:
        kernel = np.array([0.25, 0.5, 0.25], dtype=np.float32)
        smoothed = np.convolve(gap_scores, kernel, mode="same")
    else:
        smoothed = gap_scores

    depth = np.zeros_like(smoothed)
    for i in range(len(smoothed)):
        l_peak = smoothed[i]
        for j in range(i - 1, -1, -1):
            if smoothed[j] >= l_peak:
                l_peak = smoothed[j]
            else:
                break
        r_peak = smoothed[i]
        for j in range(i + 1, len(smoothed)):
            if smoothed[j] >= r_peak:
                r_peak = smoothed[j]
            else:
                break
        depth[i] = max(0.0, (l_peak - smoothed[i]) + (r_peak - smoothed[i]))

    mean_d = float(np.mean(depth))
    std_d = float(np.std(depth))
    threshold = mean_d + 0.5 * std_d
    boundaries = {0}
    for i, d in enumerate(depth):
        if d >= threshold and d > 0.05:
            boundaries.add(i + 1)

    for i in range(1, n):
        pause = float(segments[i]["start"]) - float(segments[i - 1]["end"])
        if pause >= 1.8:
            boundaries.add(i)

    return boundaries


def _load_rms_envelope(wav_path: str | Path | None, bin_sec: float = 0.5) -> np.ndarray | None:
    """Compute RMS energy envelope per bin_sec directly from 16kHz PCM WAV."""
    if not wav_path:
        return None
    p = Path(wav_path)
    if not p.is_file():
        return None
    try:
        with wave.open(str(p), "rb") as wf:
            sr = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) == 0:
            return None
        hop = max(1, int(sr * bin_sec))
        usable = (len(samples) // hop) * hop
        if usable == 0:
            return None
        blocks = samples[:usable].reshape(-1, hop)
        rms = np.sqrt(np.mean(blocks * blocks, axis=1))
        return rms
    except Exception:
        return None


def _audio_energy_score(rms: np.ndarray | None, start: float, end: float, bin_sec: float = 0.5) -> float:
    if rms is None or len(rms) == 0:
        return 0.0
    i0 = max(0, int(start / bin_sec))
    i1 = min(len(rms), max(i0 + 1, int(math.ceil(end / bin_sec))))
    seg_rms = rms[i0:i1]
    if len(seg_rms) == 0:
        return 0.0
    global_mean = float(np.mean(rms)) + 1e-5
    peak_ratio = float(np.percentile(seg_rms, 90)) / global_mean
    dyn_range = float(np.std(seg_rms)) / global_mean
    return min(4.0, max(0.0, (peak_ratio - 0.8) * 1.4 + dyn_range * 1.2))


def _sanitize_title(text: str, cut_id: int, duration_type: str) -> str:
    clean = unicodedata.normalize("NFKD", text)
    clean = "".join(ch for ch in clean if not unicodedata.combining(ch))
    words = re.findall(r"[A-Za-z0-9]+", clean)
    slug = "_".join(words[:5]) if words else f"Gameplay_Corte_{cut_id}"
    slug = slug[:42].strip("_")
    return f"{slug}_{duration_type}"


def _extract_hook_text(segments_in_window: list[dict[str, Any]], lang: str) -> str:
    if not segments_in_window:
        return "OLHA ESSA JOGADA!" if lang == "pt" else "WATCH THIS PLAY!"

    best_seg = segments_in_window[0]
    best_h = -1.0
    for seg in segments_in_window[:3]:
        txt = seg.get("text", "").strip()
        h = 0.0
        if "!" in txt:
            h += 2.0
        if "?" in txt:
            h += 1.6
        low = txt.lower()
        if any(low.startswith(op) or f" {op} " in low for op in HOOK_OPENERS):
            h += 2.2
        if 3 <= len(txt.split()) <= 10:
            h += 1.0
        if h > best_h:
            best_h = h
            best_seg = seg

    raw = best_seg.get("text", "").strip()
    words = raw.split()
    if len(words) > 7:
        raw = " ".join(words[:7])
    return raw.upper().strip(".,;:")


def _score_window(
    window_segs: list[dict[str, Any]],
    start: float,
    end: float,
    target_dur: float,
    is_topic_start: bool,
    rms: np.ndarray | None,
    lang: str,
) -> tuple[float, list[str]]:
    duration = max(0.5, end - start)
    full_text = " ".join(s.get("text", "") for s in window_segs).strip()
    low_text = full_text.lower()
    reasons: list[str] = []

    score = 0.0
    patterns = REACTION_PATTERNS_PT if lang == "pt" else REACTION_PATTERNS_EN
    other_patterns = REACTION_PATTERNS_EN if lang == "pt" else REACTION_PATTERNS_PT

    reaction_hits = 0.0
    for pat, weight, label in patterns + [(p, w * 0.7, lbl) for p, w, lbl in other_patterns]:
        matches = re.findall(pat, low_text)
        if matches:
            reaction_hits += min(len(matches), 3) * weight
            if label not in reasons:
                reasons.append(label)
    score += min(10.0, reaction_hits)

    # Hook quality in first 6 seconds
    early_segs = [s for s in window_segs if float(s["start"]) - start <= 6.5]
    early_text = " ".join(s.get("text", "") for s in early_segs).lower()
    hook_score = 0.0
    if "?" in early_text:
        hook_score += 1.8
    if "!" in early_text:
        hook_score += 1.8
    if any(op in early_text for op in HOOK_OPENERS):
        hook_score += 2.2
    if hook_score >= 2.0:
        reasons.append("Gancho forte inicial" if lang == "pt" else "Strong opening hook")
    score += hook_score

    # Speech density (words per second) & anti-repetition check (penalizes ASR loops)
    raw_tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9']+", low_text)
    word_count = sum(len(s.get("words") or s.get("text", "").split()) for s in window_segs)
    if len(raw_tokens) >= 12:
        lexical_diversity = len(set(raw_tokens)) / float(len(raw_tokens))
        if lexical_diversity < 0.32:
            score -= 10.0
            reasons.append("Penalidade por repetição ASR" if lang == "pt" else "ASR repetition penalty")
    wps = word_count / duration
    if 1.8 <= wps <= 4.5:
        density_score = 2.5 - abs(wps - 3.0) * 0.6
    elif wps > 4.5:
        density_score = 1.6
    else:
        density_score = max(0.0, wps)
    score += max(0.0, density_score)

    # Punctuation & conversational dynamism
    excl_count = full_text.count("!") + full_text.count("?")
    if excl_count >= 2:
        score += min(2.5, excl_count * 0.6)

    # Audio energy burst
    energy_score = _audio_energy_score(rms, start, end)
    if energy_score >= 1.5:
        reasons.append("Pico de áudio/emoção" if lang == "pt" else "Audio energy peak")
    score += energy_score

    # Topic boundary bonus (ClipsAI TextTiling)
    if is_topic_start:
        score += 1.5
        reasons.append("Início de tópico (TextTiling)" if lang == "pt" else "Topic boundary start")

    # Closeness to requested duration bucket
    dur_penalty = abs(duration - target_dur) / max(target_dur, 1.0)
    score -= dur_penalty * 2.2

    if not reasons:
        reasons.append("Ritmo contínuo de fala" if lang == "pt" else "Continuous speech flow")

    return round(score, 4), reasons


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float, max_iou: float = 0.25) -> bool:
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    if inter <= 0:
        return False
    min_len = max(0.1, min(a_end - a_start, b_end - b_start))
    return (inter / min_len) > max_iou


def _build_candidates_for_bucket(
    segments: list[dict[str, Any]],
    boundaries: set[int],
    rms: np.ndarray | None,
    total_duration: float,
    duration_type: str,
    lang: str,
) -> list[dict[str, Any]]:
    min_dur, target_dur, max_dur = DURATION_CONFIGS[duration_type]
    effective_min = min(min_dur, max(4.0, total_duration * 0.55))
    effective_target = min(target_dur, total_duration)

    candidates: list[dict[str, Any]] = []
    n = len(segments)
    for i in range(n):
        win_start = float(segments[i]["start"])
        win_segs: list[dict[str, Any]] = []
        best_j = None
        best_diff = 1e9

        for j in range(i, n):
            win_segs.append(segments[j])
            win_end = float(segments[j]["end"])
            dur = win_end - win_start
            if dur >= effective_min and dur <= max_dur:
                diff = abs(dur - effective_target)
                if diff < best_diff:
                    best_diff = diff
                    best_j = j
            if dur > max_dur:
                break

        if best_j is None and i == 0 and total_duration > 4.0:
            # Handle short video shorter than min_dur gracefully
            win_segs = list(segments)
            best_j = n - 1

        if best_j is not None:
            chosen_segs = segments[i : best_j + 1]
            c_start = float(chosen_segs[0]["start"])
            c_end = float(chosen_segs[-1]["end"])
            # Pad subtly without exceeding video length
            c_start_pad = max(0.0, round(c_start - 0.35, 2))
            c_end_pad = min(total_duration, round(c_end + 0.45, 2))
            if c_end_pad - c_start_pad < 3.0:
                continue

            score, reasons = _score_window(
                chosen_segs,
                c_start_pad,
                c_end_pad,
                effective_target,
                i in boundaries,
                rms,
                lang,
            )
            hook = _extract_hook_text(chosen_segs, lang)
            candidates.append(
                {
                    "start": c_start_pad,
                    "end": c_end_pad,
                    "duration_type": duration_type,
                    "score": score,
                    "hook_text": hook,
                    "reasons": reasons,
                    "preview_text": chosen_segs[0].get("text", ""),
                }
            )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates


def _select_candidates(
    pool_by_bucket: dict[str, list[dict[str, Any]]],
    buckets: list[str],
    total_duration: float,
    max_cuts: int,
    distribute_across_video: bool,
) -> list[dict[str, Any]]:
    """Select non-overlapping highlights, optionally balanced across timeline zones for long VODs."""
    selected: list[dict[str, Any]] = []
    use_zones = distribute_across_video and total_duration >= 600.0 and max_cuts >= 4

    if use_zones:
        num_zones = min(max_cuts, max(3, int(total_duration // 900) + 2))
        zone_len = total_duration / float(num_zones)
        zoned: dict[str, list[list[dict[str, Any]]]] = {
            b: [[] for _ in range(num_zones)] for b in buckets
        }
        for b in buckets:
            for cand in pool_by_bucket[b]:
                z_idx = min(num_zones - 1, max(0, int(cand["start"] / zone_len)))
                zoned[b][z_idx].append(cand)

        z_ptr: dict[tuple[str, int], int] = {(b, z): 0 for b in buckets for z in range(num_zones)}
        # Round-robin across zones, alternating duration buckets for mix mode
        bucket_turn = 0
        while len(selected) < max_cuts:
            progressed = False
            for z in range(num_zones):
                if len(selected) >= max_cuts:
                    break
                for offset in range(len(buckets)):
                    b = buckets[(bucket_turn + offset) % len(buckets)]
                    z_list = zoned[b][z]
                    key = (b, z)
                    picked_here = False
                    while z_ptr[key] < len(z_list):
                        cand = z_list[z_ptr[key]]
                        z_ptr[key] += 1
                        if not any(_overlaps(cand["start"], cand["end"], s["start"], s["end"]) for s in selected):
                            selected.append(cand)
                            progressed = True
                            picked_here = True
                            break
                    if picked_here:
                        bucket_turn += 1
                        break
            if not progressed:
                break

    # Fill any remaining slots up to max_cuts using global top scores
    idx_map = {b: 0 for b in buckets}
    while len(selected) < max_cuts:
        progressed = False
        for b in buckets:
            if len(selected) >= max_cuts:
                break
            b_list = pool_by_bucket[b]
            while idx_map[b] < len(b_list):
                cand = b_list[idx_map[b]]
                idx_map[b] += 1
                if not any(_overlaps(cand["start"], cand["end"], s["start"], s["end"]) for s in selected):
                    selected.append(cand)
                    progressed = True
                    break
        if not progressed:
            break

    return selected


def analyze_transcript_for_cuts(
    transcript_path: str | Path | None = None,
    duration_mode: str = "60s",
    max_cuts: int = 0,
    output_path: str | Path | None = None,
    distribute_across_video: bool = True,
    use_llm_pool: bool = True,
    progress_callback: Any | None = None,
) -> list[dict[str, Any]]:
    """Generate contextual cuts (30s, 60s, 90s, or mix) into temp/cuts.json."""
    t_path = Path(transcript_path or (TEMP_DIR / "transcript.json"))
    if not t_path.is_file():
        raise FileNotFoundError(
            f"Transcrição não encontrada em {t_path}. Execute a etapa de transcrição primeiro."
        )

    data = json.loads(t_path.read_text(encoding="utf-8"))
    segments: list[dict[str, Any]] = data.get("segments", [])
    total_duration = float(data.get("duration") or 0.0)
    if total_duration <= 0.0 and segments:
        total_duration = float(segments[-1]["end"])

    lang = (data.get("language") or "pt").lower()
    if lang.startswith("pt"):
        lang = "pt"
    elif lang.startswith("en"):
        lang = "en"

    mode = duration_mode.lower().strip()
    if mode not in ("30s", "60s", "90s", "mix"):
        mode = "60s"

    # Try .env LLM Pool first when enabled and segments exist
    if use_llm_pool and segments:
        try:
            from src.llm_pool import has_active_pool, select_cuts_with_pool

            if has_active_pool():
                if progress_callback:
                    progress_callback("Analisando contexto com Pool LLM (.env)...")
                llm_cuts, provider_label = select_cuts_with_pool(
                    transcript_data=data,
                    duration_mode=mode,
                    max_cuts=max_cuts,
                    distribute_across_video=distribute_across_video,
                )
                out_file = Path(output_path or (TEMP_DIR / "cuts.json"))
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_text(json.dumps(llm_cuts, ensure_ascii=False, indent=2), encoding="utf-8")
                if progress_callback:
                    progress_callback(f"Pool LLM ({provider_label}) selecionou {len(llm_cuts)} cortes!")
                return llm_cuts
        except Exception as exc:
            if progress_callback:
                progress_callback(f"Fallback para analisador local (Pool indisponível: {exc})")

    rms = _load_rms_envelope(data.get("audio_wav"))
    effective_max_cuts = max_cuts if max_cuts > 0 else max(1, int(total_duration // 25))

    selected: list[dict[str, Any]] = []

    if segments:
        boundaries = _texttiling_boundaries(segments)
        buckets = ["30s", "60s", "90s"] if mode == "mix" else [mode]
        pool_by_bucket = {
            b: _build_candidates_for_bucket(segments, boundaries, rms, total_duration, b, lang)
            for b in buckets
        }
        selected = _select_candidates(
            pool_by_bucket=pool_by_bucket,
            buckets=buckets,
            total_duration=total_duration,
            max_cuts=effective_max_cuts,
            distribute_across_video=distribute_across_video,
        )

    # Fallback if video had no transcribed speech (pure non-verbal gameplay)
    if not selected and total_duration > 4.0:
        fallback_bucket = "30s" if mode == "mix" else mode
        _, target_dur, _ = DURATION_CONFIGS[fallback_bucket]
        win_len = min(target_dur, total_duration)
        step = max(win_len * 0.9, total_duration / max(1, effective_max_cuts))
        t = 0.0
        while t < total_duration - 3.0 and len(selected) < effective_max_cuts:
            end_t = min(total_duration, round(t + win_len, 2))
            if end_t - t >= 4.0:
                selected.append(
                    {
                        "start": round(t, 2),
                        "end": end_t,
                        "duration_type": fallback_bucket,
                        "score": 1.0,
                        "hook_text": "MOMENTO INSANO DE GAMEPLAY!" if lang == "pt" else "INSANE GAMEPLAY MOMENT!",
                        "reasons": [
                            "Fallback por energia/segmentação temporal (sem fala detectada)"
                            if lang == "pt"
                            else "Temporal/audio energy fallback (no speech detected)"
                        ],
                        "preview_text": f"Gameplay_{len(selected)+1}",
                    }
                )
            t += step

    # Sort chronologically for cleaner project organization
    selected.sort(key=lambda x: x["start"])

    cuts_json: list[dict[str, Any]] = []
    for idx, item in enumerate(selected, start=1):
        dtype = item["duration_type"]
        actual_len = round(item["end"] - item["start"], 1)
        reason_str = (
            f"{' + '.join(item['reasons'])} | Score {item['score']:.1f} | "
            f"Corte {dtype} ({actual_len}s)"
        )
        cuts_json.append(
            {
                "id": idx,
                "title": _sanitize_title(item.get("preview_text", ""), idx, dtype),
                "start": round(float(item["start"]), 2),
                "end": round(float(item["end"]), 2),
                "duration_type": dtype,
                "hook_text": item["hook_text"],
                "context_reason": reason_str,
            }
        )

    out_file = Path(output_path or (TEMP_DIR / "cuts.json"))
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(cuts_json, ensure_ascii=False, indent=2), encoding="utf-8")
    return cuts_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Analisa temp/transcript.json e gera temp/cuts.json")
    parser.add_argument("--transcript", default=str(TEMP_DIR / "transcript.json"))
    parser.add_argument("--duration", default="60s", choices=["30s", "60s", "90s", "mix"])
    parser.add_argument("--max-cuts", type=int, default=5)
    parser.add_argument("--no-distribute", action="store_true", help="Desativa distribuição por zonas temporais")
    parser.add_argument("--no-llm", action="store_true", help="Força analisador heurístico local sem Pool .env")
    parser.add_argument("--output", default=str(TEMP_DIR / "cuts.json"))
    args = parser.parse_args()

    cuts = analyze_transcript_for_cuts(
        transcript_path=args.transcript,
        duration_mode=args.duration,
        max_cuts=args.max_cuts,
        output_path=args.output,
        distribute_across_video=not args.no_distribute,
        use_llm_pool=not args.no_llm,
        progress_callback=print,
    )
    print(f"Gerados {len(cuts)} cortes em {args.output}")


if __name__ == "__main__":
    main()
