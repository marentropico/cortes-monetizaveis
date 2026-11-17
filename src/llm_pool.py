"""Local .env LLM pool with round-robin + failover (Gemini 3.5/3.1 Flash Lite + OpenRouter)."""

from __future__ import annotations

import itertools
import json
import os
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from src import PROJECT_ROOT, TEMP_DIR

_RR_COUNTER = itertools.count(0)


def load_env_file(env_path: Path | None = None) -> dict[str, str]:
    """Load key=value pairs from .env without overwriting existing os.environ vars."""
    path = env_path or (PROJECT_ROOT / ".env")
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            loaded[k] = v
            os.environ.setdefault(k, v)
    return loaded


def get_pool_endpoints() -> list[dict[str, str]]:
    """Return ordered list of active LLM endpoints configured in .env."""
    load_env_file()
    primary_model = os.environ.get("ARANDU_MODEL", "gemini-3.5-flash-lite").strip()
    fallback_model = os.environ.get("ARANDU_MODEL_FALLBACK", "gemini-3.1-flash-lite").strip()

    gemini_keys: list[tuple[str, str]] = []
    for var_name in ("ARANDU_GEMINI_KEY_1", "ARANDU_GEMINI_KEY_2", "ARANDU_GEMINI_KEY_3"):
        val = os.environ.get(var_name, "").strip()
        if val and not val.startswith("seu_token"):
            gemini_keys.append((var_name, val))

    endpoints: list[dict[str, str]] = []
    # Rotate starting key on each call for balanced quota usage
    if gemini_keys:
        offset = next(_RR_COUNTER) % len(gemini_keys)
        rotated = gemini_keys[offset:] + gemini_keys[:offset]
        for kname, kval in rotated:
            endpoints.append({"provider": "gemini", "key_name": kname, "key": kval, "model": primary_model})
        if fallback_model and fallback_model != primary_model:
            for kname, kval in rotated:
                endpoints.append({"provider": "gemini", "key_name": kname, "key": kval, "model": fallback_model})

    or_key = os.environ.get("ARANDU_OPENROUTER_KEY", "").strip()
    or_model = os.environ.get("ARANDU_OPENROUTER_FREE_MODEL", "openrouter/free").strip()
    if or_key and not or_key.startswith("seu_token"):
        endpoints.append({"provider": "openrouter", "key_name": "ARANDU_OPENROUTER_KEY", "key": or_key, "model": or_model})

    return endpoints


def has_active_pool() -> bool:
    return len(get_pool_endpoints()) > 0


def _extract_json_payload(raw_text: str) -> Any:
    text = raw_text.strip()
    # Strip markdown code fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _call_gemini(
    endpoint: dict[str, str],
    prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
    images_b64: list[str] | None = None,
) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{endpoint['model']}:generateContent?key={endpoint['key']}"
    parts: list[dict[str, Any]] = []
    for b64 in images_b64 or []:
        if b64:
            parts.append({"inlineData": {"mimeType": "image/jpeg", "data": b64}})
    parts.append({"text": prompt})

    payload: dict[str, Any] = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    if system_prompt:
        payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_openrouter(endpoint: dict[str, str], prompt: str, system_prompt: str, temperature: float, max_tokens: int) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": endpoint["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {endpoint['key']}",
            "HTTP-Referer": "http://localhost:7860",
            "X-Title": "Gameplay-Shorts-Pipeline",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def call_llm_json(
    prompt: str,
    system_prompt: str = "",
    temperature: float = 0.25,
    max_tokens: int = 8192,
    images_b64: list[str] | None = None,
) -> tuple[Any, str]:
    """Call the LLM pool with automatic failover and return (parsed_json, provider_label)."""
    endpoints = get_pool_endpoints()
    if not endpoints:
        raise RuntimeError("Nenhuma chave ativa configurada no arquivo .env.")

    errors: list[str] = []
    for ep in endpoints:
        label = f"{ep['model']} ({ep['key_name']})"
        try:
            if ep["provider"] == "gemini":
                try:
                    raw = _call_gemini(ep, prompt, system_prompt, temperature, max_tokens, images_b64=images_b64)
                except urllib.error.HTTPError as img_exc:
                    if images_b64 and img_exc.code == 400:
                        raw = _call_gemini(ep, prompt, system_prompt, temperature, max_tokens, images_b64=None)
                    else:
                        raise
            else:
                raw = _call_openrouter(ep, prompt, system_prompt, temperature, max_tokens)
            parsed = _extract_json_payload(raw)
            return parsed, label
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:180]
            errors.append(f"{label}: HTTP {exc.code} - {body}")
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    raise RuntimeError("Todas as chaves do pool falharam:\n" + "\n".join(errors))


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float, max_iou: float = 0.20) -> bool:
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    if inter <= 0:
        return False
    min_len = max(0.1, min(a_end - a_start, b_end - b_start))
    return (inter / min_len) > max_iou


def _format_transcript_with_pacing(segments: list[dict[str, Any]]) -> list[str]:
    """Format transcript segments with dead-air pause markers and high-energy pacing cues."""
    lines: list[str] = []
    prev_end: float | None = None
    for s in segments:
        text = str(s.get("text", "")).strip()
        if not text:
            continue
        st = float(s.get("start", 0.0))
        en = float(s.get("end", st))
        if prev_end is not None and (st - prev_end) >= 2.2:
            lines.append(f"[... PAUSA {st - prev_end:.1f}s ...]")
        dur = max(0.25, en - st)
        wps = len(text.split()) / dur
        is_energetic = wps >= 3.2 or "!" in text or "?" in text or any(
            k in text.lower() for k in ("caraca", "mano", "nossa", "olha", "impossível", "meu deus", "kkk", "haha", "wtf", "bro")
        )
        tag = " [⚡]" if is_energetic else ""
        lines.append(f"[{st:.1f}->{en:.1f}]{tag} {text}")
        prev_end = en
    return lines


def _snap_to_segment_boundaries(
    c_start: float,
    c_end: float,
    segments: list[dict[str, Any]],
    total_duration: float,
) -> tuple[float, float]:
    """Snap LLM timestamps to clean sentence/segment boundaries so cuts never clip mid-word."""
    valid = [s for s in segments if str(s.get("text", "")).strip()]
    if not valid:
        return c_start, c_end

    # Snap start to nearest segment start within +-2.5s
    best_start_seg = min(valid, key=lambda s: abs(float(s["start"]) - c_start))
    if abs(float(best_start_seg["start"]) - c_start) <= 2.5:
        c_start = max(0.0, round(float(best_start_seg["start"]) - 0.12, 2))

    # Snap end to nearest segment end within +-2.5s
    best_end_seg = min(valid, key=lambda s: abs(float(s["end"]) - c_end))
    if abs(float(best_end_seg["end"]) - c_end) <= 2.5:
        c_end = min(total_duration, round(float(best_end_seg["end"]) + 0.25, 2))

    return c_start, c_end


def _build_time_windows(
    segments: list[dict[str, Any]],
    total_duration: float,
    window_sec: float = 1800.0,
    overlap_sec: float = 60.0,
    max_segs_per_win: int = 950,
) -> list[list[dict[str, Any]]]:
    """Split long transcripts into 30-minute overlapping time windows (with segment-count cap)."""
    if total_duration <= 2100.0 and len(segments) <= max_segs_per_win:
        return [segments]

    step = max(300.0, window_sec - overlap_sec)
    windows: list[list[dict[str, Any]]] = []
    cur_t = 0.0
    while cur_t < total_duration:
        win_end = cur_t + window_sec
        chunk = [
            s for s in segments
            if float(s.get("end", 0.0)) >= cur_t and float(s.get("start", 0.0)) <= win_end
        ]
        if chunk:
            if len(chunk) > max_segs_per_win:
                for i in range(0, len(chunk), max_segs_per_win - 40):
                    sub = chunk[i : i + max_segs_per_win]
                    if sub:
                        windows.append(sub)
            else:
                windows.append(chunk)
        if win_end >= total_duration:
            break
        cur_t += step

    return windows or [segments]


def select_cuts_with_pool(
    transcript_data: dict[str, Any],
    duration_mode: str = "60s",
    max_cuts: int = 0,
    distribute_across_video: bool = True,
    video_path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Use the Gemini/OpenRouter pool to curate high-retention viral cuts from transcript.json."""
    segments = [s for s in transcript_data.get("segments", []) if str(s.get("text", "")).strip()]
    if not segments:
        raise ValueError("Transcrição vazia; não há falas para analisar.")

    from src.video_vision import build_contact_sheet_b64, load_video_context_meta, resolve_video_path

    total_duration = float(transcript_data.get("duration") or segments[-1]["end"])
    video_file = str(transcript_data.get("video_file", "video.mp4"))
    lang = str(transcript_data.get("language", "pt")).lower()
    vpath = resolve_video_path(transcript_data, video_path)
    video_meta = load_video_context_meta(transcript_data, vpath)
    meta_title = video_meta.get("title") or video_file
    meta_channel = video_meta.get("channel") or ""
    meta_desc = video_meta.get("description") or ""
    thumb_b64 = video_meta.get("thumb_b64")

    duration_rules = {
        "30s": "Todos os cortes devem ter entre 22 e 35 segundos (duration_type='30s').",
        "60s": "Todos os cortes devem ter entre 45 e 65 segundos (duration_type='60s').",
        "90s": "Todos os cortes devem ter entre 72 e 95 segundos (duration_type='90s').",
        "mix": "Misture de forma equilibrada cortes de '30s' (22-35s), '60s' (45-65s) e '90s' (72-95s) conforme o arco natural de cada momento.",
    }.get(duration_mode, "Todos os cortes devem ter entre 45 e 65 segundos (duration_type='60s').")

    dist_rule = (
        "Distribua os cortes por TODO o vídeo (início, meio e fim), sem concentrar tudo em um só trecho."
        if distribute_across_video and total_duration >= 600
        else "Priorize os momentos de maior potencial viral independente da posição."
    )

    system_prompt = (
        "Você simula uma SALA DE REUNIÃO DE ROTEIRO (Writers' Room) com 3 especialistas avaliando uma transcrição "
        "para escolher os melhores YouTube Shorts, Reels e TikToks virais (em qualquer nicho: gameplay, compilado de memes, "
        "monólogo/opinião, podcast/mesa redonda, review ou react).\n\n"
        "AS 3 PERSONALIDADES NA SALA:\n"
        "1. [JOVEM VIRAL]: Jovem adulto hiperconectado, radar afiado para banalidades virais, frases fora de contexto, "
        "cringe, absurdos do cotidiano e momentos que fazem as pessoas comentarem e mandarem pros amigos.\n"
        "2. [CINEASTA]: Especialista em ganchos de roteiro e retenção. Exige COLD OPEN nos primeiros 2s (nunca começar em silêncio "
        "ou 'e aí galera'), arco dramático completo e FECHAMENTO SECO na virada/clímax.\n"
        "3. [COMEDIANTE]: Especialista em memes, timing cômico e hooks magnéticos. Cria o 'hook_text' e o 'youtube_title' "
        "com ironia, choque ou humor genuíno (sem clichês robóticos).\n\n"
        "Adapte a seleção ao nicho detectado (ex: em compilado de memes, mantenha setup+punchline de cada meme sem misturar; "
        "em podcast, pegue pergunta incisiva+resposta completa; em gameplay, clutches/sustos/rage/RP).\n"
        "Ignore alucinações do Whisper ('Obrigado por assistir', 'Legendas...', loops) e evite trechos cheios de '[... PAUSA ...]'. "
        "Trechos com [⚡] indicam picos de energia/velocidade.\n"
        "Responda EXCLUSIVAMENTE com JSON válido (lista de objetos)."
    )

    windows = _build_time_windows(segments, total_duration, window_sec=1800.0, overlap_sec=60.0)
    per_win_max = (
        max(3, (max_cuts + len(windows) - 1) // len(windows))
        if max_cuts > 0
        else 0
    )
    qty_rule = (
        "EXTRAIA TODOS os cortes excelentes e não sobrepostos que o trecho sustentar com alta qualidade "
        "(prefira quantidade com padrão alto; descarte trechos mornos)."
        if per_win_max <= 0
        else f"selecione até {per_win_max} melhores cortes (NÃO pode haver sobreposição temporal)."
    )

    def _analyze_window(win_segs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
        win_start = float(win_segs[0]["start"])
        win_end = float(win_segs[-1]["end"])
        transcript_block = "\n".join(_format_transcript_with_pacing(win_segs))

        images_b64: list[str] = []
        if thumb_b64:
            images_b64.append(thumb_b64)
        sheet_b64 = build_contact_sheet_b64(vpath, win_start, win_end) if vpath is not None else None
        if sheet_b64:
            images_b64.append(sheet_b64)

        visual_note = ""
        if images_b64:
            visual_note = (
                "\nContexto visual anexado: "
                + ("1) Thumbnail original do vídeo; " if thumb_b64 else "")
                + ("2) Grade 4x4 de frames da janela com timestamps [MM:SS] — use as imagens para reconhecer memes visuais, expressões, sustos e eventos de tela sem fala." if sheet_b64 else "")
            )

        meta_block = f"Título original: {meta_title}"
        if meta_channel:
            meta_block += f" | Canal: {meta_channel}"
        if meta_desc:
            meta_block += f"\nResumo da descrição: {meta_desc[:350]}"

        user_prompt = f"""
{meta_block}
Arquivo: {video_file} | Idioma: {lang}
Janela analisada: {win_start:.1f}s até {win_end:.1f}s (Duração total do vídeo: {total_duration:.1f}s){visual_note}
Quantidade desejada: {qty_rule}
Regra de duração: {duration_rules}
Distribuição: {dist_rule}

Retorne uma lista JSON onde cada item represente uma decisão da sala e tenha EXATAMENTE estas chaves (nesta ordem):
- "id": inteiro sequencial (1, 2, ...)
- "room_debate": objeto curto com a opinião das 3 personalidades ANTES de fechar os timestamps:
  {{"jovem_viral": "...", "cineasta": "...", "comediante": "..."}}
- "consensus_score": nota de 1.0 a 10.0 dada pela sala (só inclua cortes com nota >= 7.0)
- "title": slug curto com underscores sem acentos, terminando em _30s, _60s ou _90s (ex: "Susto_No_Castelo_30s")
- "start": float em segundos (entre {win_start:.1f} e {win_end:.1f}, começando exatamente no cold open definido pelo Cineasta)
- "end": float em segundos (respeitando a regra de duração e <= {win_end:.1f}, fechando seco na punchline)
- "duration_type": "30s", "60s" ou "90s"
- "hook_text": frase curta e explosiva em MAIÚSCULAS criada pelo Comediante + Jovem Viral (máx. 6 palavras, SEM hashtags, ex: "NINGUÉM ESPERAVA ESSE FINAL!")
- "context_reason": 1 frase natural resumindo o consenso da sala sobre por que esse corte viraliza (sem termos técnicos)
- "youtube_title": título altamente clicável com curiosidade/humor + 1 emoji + #shorts (máx. 90 caracteres)
- "youtube_description": 1-2 frases envolventes + 3-5 hashtags de nicho relevantes ao conteúdo real (nunca escreva 'corte automático')

TRANSCRIÇÃO:
{transcript_block}
""".strip()

        max_out_tokens = 16384 if (per_win_max <= 0 or per_win_max > 15) else 8192
        parsed, lbl = call_llm_json(
            user_prompt,
            system_prompt=system_prompt,
            temperature=0.35,
            max_tokens=max_out_tokens,
            images_b64=images_b64 or None,
        )
        if isinstance(parsed, dict):
            parsed = parsed.get("cuts") or parsed.get("clips") or list(parsed.values())[0]
        return (parsed if isinstance(parsed, list) else []), lbl

    all_raw: list[dict[str, Any]] = []
    used_labels: list[str] = []
    unique_keys = len({ep["key_name"] for ep in get_pool_endpoints()})
    max_workers = max(1, min(len(windows), max(1, unique_keys), 3))

    if max_workers == 1:
        for win_segs in windows:
            items, lbl = _analyze_window(win_segs)
            all_raw.extend(items)
            if lbl:
                used_labels.append(lbl)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool_exec:
            futures = [pool_exec.submit(_analyze_window, ws) for ws in windows]
            for fut in as_completed(futures):
                items, lbl = fut.result()
                all_raw.extend(items)
                if lbl:
                    used_labels.append(lbl)

    provider_label = used_labels[0] if len(set(used_labels)) <= 1 else f"{len(windows)} janelas ({len(set(used_labels))} chaves)"

    if not all_raw:
        raise ValueError("O pool LLM retornou uma lista de cortes vazia ou inválida.")

    # Prioritize highest consensus_score when resolving overlaps across 60s window boundaries
    all_raw.sort(key=lambda r: float(r.get("consensus_score", 7.5)) if isinstance(r, dict) else 0.0, reverse=True)

    clean_cuts: list[dict[str, Any]] = []
    for raw in all_raw:
        try:
            c_start = max(0.0, round(float(raw["start"]), 2))
            c_end = min(total_duration, round(float(raw["end"]), 2))
            c_start, c_end = _snap_to_segment_boundaries(c_start, c_end, segments, total_duration)
            if c_end - c_start < 10.0:
                continue
            score = float(raw.get("consensus_score", 8.0))
            if score < 6.5:
                continue
            if any(_overlaps(c_start, c_end, ex["start"], ex["end"]) for ex in clean_cuts):
                continue

            dur = c_end - c_start
            dtype = str(raw.get("duration_type", "")).strip()
            if dtype not in ("30s", "60s", "90s"):
                dtype = "30s" if dur < 42 else ("60s" if dur < 72 else "90s")

            title = re.sub(r"[^A-Za-z0-9_-]+", "_", str(raw.get("title", f"Corte_{len(clean_cuts)+1}")))
            title = re.sub(r"_+", "_", title).strip("_")[:50]
            if not title.endswith(("_30s", "_60s", "_90s")):
                title = f"{title}_{dtype}"

            clean_cuts.append(
                {
                    "id": len(clean_cuts) + 1,
                    "title": title,
                    "start": c_start,
                    "end": c_end,
                    "duration_type": dtype,
                    "hook_text": str(raw.get("hook_text", "OLHA ISSO!")).strip().upper()[:60],
                    "context_reason": str(raw.get("context_reason", "")).strip(),
                    "youtube_title": str(raw.get("youtube_title", "")).strip()[:100],
                    "youtube_description": str(raw.get("youtube_description", "")).strip()[:4000],
                }
            )
            if max_cuts > 0 and len(clean_cuts) >= max_cuts:
                break
        except Exception:
            continue

    if not clean_cuts:
        raise ValueError("Nenhum corte válido restou após validação dos timestamps do LLM.")

    clean_cuts.sort(key=lambda x: x["start"])
    for idx, item in enumerate(clean_cuts, start=1):
        item["id"] = idx

    return clean_cuts, provider_label


def refine_segment_captions_with_pool(
    segments: list[dict[str, Any]],
    game_context: str = "",
    language: str = "pt",
) -> tuple[list[dict[str, Any]], str]:
    """Polish ASR transcript segments using the LLM pool and keep word timestamps aligned."""
    if not segments:
        return segments, "none"

    items = [
        {"i": idx, "text": str(seg.get("text", "")).strip()}
        for idx, seg in enumerate(segments)
        if str(seg.get("text", "")).strip()
    ]
    if not items:
        return segments, "none"

    system_prompt = (
        "Você é um revisor de legendas especialista em games. "
        "Corrija erros fonéticos do reconhecimento de voz, nomes próprios de jogos, gírias brasileiras/inglesas, "
        "acentuação e pontuação mantendo EXATAMENTE o mesmo significado e ritmo falado, sem resumir nem inventar frases. "
        "Responda APENAS em JSON válido."
    )
    user_prompt = f"""
Contexto do vídeo: {game_context or 'Gameplay'}
Idioma principal: {language}

Corrija o campo "text" de cada item abaixo. Mantenha o mesmo índice "i" para todos os itens.
Retorne uma lista JSON no formato: [{{"i": 0, "text": "..."}}, ...]

ITENS:
{json.dumps(items, ensure_ascii=False)}
""".strip()

    parsed, provider_label = call_llm_json(user_prompt, system_prompt=system_prompt, temperature=0.1, max_tokens=8192)
    if isinstance(parsed, dict):
        parsed = parsed.get("items") or parsed.get("segments") or list(parsed.values())[0]
    if not isinstance(parsed, list):
        return segments, provider_label

    corrected_by_idx = {
        int(it["i"]): str(it["text"]).strip()
        for it in parsed
        if isinstance(it, dict) and "i" in it and "text" in it
    }

    refined: list[dict[str, Any]] = []
    for idx, seg in enumerate(segments):
        new_seg = dict(seg)
        new_text = corrected_by_idx.get(idx)
        orig_words = seg.get("words") or []
        if new_text and new_text != seg.get("text"):
            new_seg["text"] = new_text
            new_tokens = new_text.split()
            if new_tokens:
                if len(new_tokens) == len(orig_words):
                    # Exact 1-to-1 replacement preserves precise Whisper word timings
                    new_seg["words"] = [
                        {
                            "word": tok,
                            "start": orig_words[k]["start"],
                            "end": orig_words[k]["end"],
                            "probability": orig_words[k].get("probability", 1.0),
                        }
                        for k, tok in enumerate(new_tokens)
                    ]
                else:
                    # Proportional timing redistribution within the segment [start, end]
                    s0 = float(orig_words[0]["start"]) if orig_words else float(seg["start"])
                    s1 = float(orig_words[-1]["end"]) if orig_words else float(seg["end"])
                    span = max(0.15, s1 - s0)
                    total_chars = max(1, sum(len(t) for t in new_tokens))
                    cursor = s0
                    rebuilt: list[dict[str, Any]] = []
                    for tok in new_tokens:
                        w_dur = max(0.06, span * (len(tok) / float(total_chars)))
                        end_t = min(s1, cursor + w_dur)
                        rebuilt.append({"word": tok, "start": round(cursor, 3), "end": round(end_t, 3), "probability": 1.0})
                        cursor = end_t
                    if rebuilt:
                        rebuilt[-1]["end"] = round(s1, 3)
                    new_seg["words"] = rebuilt
        refined.append(new_seg)

    _update_channel_glossary(items, corrected_by_idx)
    return refined, provider_label


def _update_channel_glossary(
    orig_items: list[dict[str, Any]],
    corrected_by_idx: dict[int, str],
    max_terms: int = 80,
) -> None:
    """Persist proper nouns and corrected terms into temp/channel_glossary.json for future Whisper prompts."""
    new_terms: list[str] = []
    for it in orig_items:
        idx = int(it["i"])
        orig_text = str(it.get("text", ""))
        new_text = corrected_by_idx.get(idx, "")
        if not new_text or new_text == orig_text:
            continue
        orig_lower_tokens = set(re.findall(r"[A-Za-zÀ-ÿ0-9_-]{3,}", orig_text.lower()))
        for tok in re.findall(r"[A-Za-zÀ-ÿ0-9_-]{3,}", new_text):
            # Keep capitalized proper nouns or acronyms/slang newly introduced by the LLM
            if tok.lower() not in orig_lower_tokens and (tok[0].isupper() or any(c.isdigit() for c in tok)):
                new_terms.append(tok)

    if not new_terms:
        return

    glossary_path = TEMP_DIR / "channel_glossary.json"
    existing: list[str] = []
    if glossary_path.is_file():
        try:
            data = json.loads(glossary_path.read_text(encoding="utf-8"))
            raw = data.get("terms", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            existing = [str(t).strip() for t in raw if str(t).strip()]
        except Exception:
            existing = []

    merged: list[str] = []
    seen_lower: set[str] = set()
    for term in existing + new_terms:
        low = term.lower()
        if low not in seen_lower:
            seen_lower.add(low)
            merged.append(term)

    if len(merged) > max_terms:
        merged = merged[-max_terms:]

    try:
        glossary_path.parent.mkdir(parents=True, exist_ok=True)
        glossary_path.write_text(
            json.dumps({"terms": merged}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
