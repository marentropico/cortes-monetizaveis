"""Local .env LLM pool with round-robin + failover (Gemini 3.5/3.1 Flash Lite + OpenRouter)."""

from __future__ import annotations

import itertools
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from src import PROJECT_ROOT

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


def _call_gemini(endpoint: dict[str, str], prompt: str, system_prompt: str, temperature: float, max_tokens: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{endpoint['model']}:generateContent?key={endpoint['key']}"
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
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
                raw = _call_gemini(ep, prompt, system_prompt, temperature, max_tokens)
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


def select_cuts_with_pool(
    transcript_data: dict[str, Any],
    duration_mode: str = "60s",
    max_cuts: int = 0,
    distribute_across_video: bool = True,
) -> tuple[list[dict[str, Any]], str]:
    """Use the Gemini/OpenRouter pool to curate contextual cuts from transcript.json."""
    segments = transcript_data.get("segments", [])
    if not segments:
        raise ValueError("Transcrição vazia; não há falas para analisar.")

    total_duration = float(transcript_data.get("duration") or segments[-1]["end"])
    video_file = str(transcript_data.get("video_file", "gameplay.mp4"))
    lang = str(transcript_data.get("language", "pt")).lower()

    compact_lines = [
        f"[{float(s['start']):.1f}->{float(s['end']):.1f}] {s.get('text', '').strip()}"
        for s in segments
        if s.get("text", "").strip()
    ]
    transcript_block = "\n".join(compact_lines)

    duration_rules = {
        "30s": "Todos os cortes devem ter entre 24 e 35 segundos (duration_type='30s').",
        "60s": "Todos os cortes devem ter entre 48 e 65 segundos (duration_type='60s').",
        "90s": "Todos os cortes devem ter entre 75 e 95 segundos (duration_type='90s').",
        "mix": "Misture de forma equilibrada cortes de '30s' (24-35s), '60s' (48-65s) e '90s' (75-95s).",
    }.get(duration_mode, "Todos os cortes devem ter entre 48 e 65 segundos (duration_type='60s').")

    dist_rule = (
        "Distribua os cortes por TODO o vídeo (início, meio e fim), sem concentrar tudo em um só trecho."
        if distribute_across_video and total_duration >= 600
        else "Priorize os momentos de maior impacto independente da posição."
    )

    system_prompt = (
        "Você é um editor sênior especialista em YouTube Shorts, Reels e TikTok de gameplay. "
        "Sua tarefa é analisar a transcrição com timestamps e selecionar os melhores momentos "
        "com começo, meio e clímax (humor, sustos, jogadas épicas, reações sinceras ou lore marcante). "
        "Ignore repetições sem sentido ou alucinações de transcrição. Responda APENAS com JSON válido."
    )

    qty_rule = (
        "EXTRAIA O MÁXIMO possível de bons cortes não sobrepostos que o contexto completo do vídeo sustentar "
        "(sem limite artificial; se houver conteúdo para 30, 50 ou mais cortes bons ao longo do vídeo, inclua todos)."
        if max_cuts <= 0
        else f"até {max_cuts} cortes (NÃO pode haver sobreposição temporal entre cortes)."
    )

    user_prompt = f"""
Vídeo: {video_file}
Idioma: {lang}
Duração total: {total_duration:.1f} segundos
Quantidade desejada: {qty_rule}
Regra de duração: {duration_rules}
Distribuição: {dist_rule}

Retorne uma lista JSON onde cada item tenha exatamente as chaves:
- "id": inteiro sequencial (1, 2, ...)
- "title": slug curto com underscores sem acentos, terminando em _30s, _60s ou _90s (ex: "Susto_No_Castelo_30s")
- "start": float em segundos (entre 0.0 e {total_duration:.1f})
- "end": float em segundos (respeitando a regra de duração e <= {total_duration:.1f})
- "duration_type": "30s", "60s" ou "90s"
- "hook_text": frase curta e chamativa em MAIÚSCULAS (máx. 7 palavras) para aparecer no topo nos primeiros 3s
- "context_reason": 1 frase natural explicando o momento (NÃO escreva 'Corte 30s', 'Score' ou termos técnicos)
- "youtube_title": título viral para YouTube Shorts com emoji e #shorts (máx. 95 caracteres)
- "youtube_description": descrição natural e atrativa para o YouTube com hashtags no final (NÃO escreva 'corte automático')

TRANSCRIÇÃO:
{transcript_block}
""".strip()

    max_out_tokens = 16384 if (max_cuts <= 0 or max_cuts > 15) else 8192
    parsed, provider_label = call_llm_json(
        user_prompt, system_prompt=system_prompt, temperature=0.3, max_tokens=max_out_tokens
    )
    if isinstance(parsed, dict):
        parsed = parsed.get("cuts") or parsed.get("clips") or list(parsed.values())[0]
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("O pool LLM retornou uma lista de cortes vazia ou inválida.")

    clean_cuts: list[dict[str, Any]] = []
    for raw in parsed:
        try:
            c_start = max(0.0, round(float(raw["start"]), 2))
            c_end = min(total_duration, round(float(raw["end"]), 2))
            if c_end - c_start < 6.0:
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

    return refined, provider_label
