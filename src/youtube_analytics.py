"""YouTube Channel & Shorts performance inspector (Data API v3 + YouTube Studio CDP + AI Coach)."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from src import OUTPUT_DIR, PROJECT_ROOT
from src.llm_pool import call_llm_json, has_active_pool, load_env_file
from src.youtube_publisher import find_active_cdp_port, launch_chrome_cdp

ANALYTICS_CACHE_FILE = OUTPUT_DIR / "channel_analytics.json"


def save_youtube_api_config(api_key: str, channel_ref: str) -> str:
    """Persist YOUTUBE_API_KEY and YOUTUBE_CHANNEL_HANDLE/ID into .env cleanly."""
    env_path = PROJECT_ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []

    updates = {
        "YOUTUBE_API_KEY": api_key.strip(),
        "YOUTUBE_CHANNEL_REF": channel_ref.strip(),
    }
    os.environ["YOUTUBE_API_KEY"] = updates["YOUTUBE_API_KEY"]
    os.environ["YOUTUBE_CHANNEL_REF"] = updates["YOUTUBE_CHANNEL_REF"]

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        replaced = False
        for k, v in updates.items():
            if stripped.startswith(f"{k}="):
                new_lines.append(f"{k}={v}")
                seen.add(k)
                replaced = True
                break
        if not replaced:
            new_lines.append(line)

    for k, v in updates.items():
        if k not in seen and v:
            new_lines.append(f"{k}={v}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return "✅ Configuração salva no .env!"


def get_saved_youtube_config() -> tuple[str, str]:
    load_env_file()
    return (
        os.environ.get("YOUTUBE_API_KEY", "").strip(),
        os.environ.get("YOUTUBE_CHANNEL_REF", "").strip(),
    )


def _yt_api_get(endpoint: str, params: dict[str, str], api_key: str) -> dict[str, Any]:
    q = dict(params)
    q["key"] = api_key
    url = f"https://www.googleapis.com/youtube/v3/{endpoint}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            msg = body
        raise RuntimeError(f"YouTube Data API erro {exc.code}: {msg}") from exc


def _parse_iso_duration(iso_str: str) -> float:
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", iso_str or "")
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    sec = int(m.group(3) or 0)
    return float(h * 3600 + mins * 60 + sec)


def _duration_bucket(sec: float) -> str:
    if sec <= 42:
        return "30s"
    if sec <= 72:
        return "60s"
    if sec <= 125:
        return "90s"
    return "Longo"


def fetch_channel_analytics_api(
    api_key: str | None = None,
    channel_ref: str | None = None,
    max_videos: int = 40,
) -> dict[str, Any]:
    """Fetch channel summary and video performance metrics using YouTube Data API v3."""
    saved_key, saved_ref = get_saved_youtube_config()
    key = (api_key or saved_key).strip()
    ref = (channel_ref or saved_ref).strip()

    if not key:
        raise ValueError("YOUTUBE_API_KEY não configurada. Cole a chave no campo acima ou no .env.")

    # Auto-detect channel ID from existing analytics cache if ref is blank
    if not ref and ANALYTICS_CACHE_FILE.is_file():
        try:
            prev = json.loads(ANALYTICS_CACHE_FILE.read_text(encoding="utf-8"))
            ref = str(prev.get("channel", {}).get("id", "")).strip()
        except Exception:
            pass

    if not ref:
        raise ValueError("Informe o @handle do canal (ex: @BNJRRecords) ou o ID do canal (UC...).")

    ch_params: dict[str, str] = {"part": "snippet,statistics,contentDetails"}
    if ref.startswith("UC") and len(ref) >= 20:
        ch_params["id"] = ref
    else:
        handle = ref if ref.startswith("@") else f"@{ref}"
        ch_params["forHandle"] = handle

    ch_data = _yt_api_get("channels", ch_params, key)
    items = ch_data.get("items") or []
    if not items:
        raise ValueError(f"Canal não encontrado na YouTube API para '{ref}'.")

    ch = items[0]
    ch_id = ch["id"]
    ch_snip = ch.get("snippet", {})
    ch_stats = ch.get("statistics", {})
    uploads_playlist = ch.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")

    video_ids: list[str] = []
    if uploads_playlist:
        pl_data = _yt_api_get(
            "playlistItems",
            {"part": "contentDetails", "playlistId": uploads_playlist, "maxResults": str(min(50, max_videos))},
            key,
        )
        for pi in pl_data.get("items", []):
            vid = pi.get("contentDetails", {}).get("videoId")
            if vid:
                video_ids.append(vid)

    videos_list: list[dict[str, Any]] = []
    if video_ids:
        v_data = _yt_api_get(
            "videos",
            {"part": "snippet,statistics,contentDetails", "id": ",".join(video_ids)},
            key,
        )
        for v in v_data.get("items", []):
            vid = v["id"]
            snip = v.get("snippet", {})
            stats = v.get("statistics", {})
            dur_sec = _parse_iso_duration(v.get("contentDetails", {}).get("duration", ""))
            views = int(stats.get("viewCount", 0))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            eng_pct = round(((likes + comments) / max(1, views)) * 100.0, 2) if views > 0 else 0.0
            is_short = dur_sec <= 180.0
            videos_list.append(
                {
                    "video_id": vid,
                    "title": snip.get("title", ""),
                    "published_at": snip.get("publishedAt", "")[:16].replace("T", " "),
                    "duration_sec": dur_sec,
                    "bucket": _duration_bucket(dur_sec),
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "engagement_pct": eng_pct,
                    "url": f"https://youtube.com/shorts/{vid}" if is_short else f"https://youtu.be/{vid}",
                    "source": "youtube_api_v3",
                }
            )

    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "channel": {
            "id": ch_id,
            "title": ch_snip.get("title", ""),
            "custom_url": ch_snip.get("customUrl", ref),
            "subscribers": int(ch_stats.get("subscriberCount", 0)),
            "total_views": int(ch_stats.get("viewCount", 0)),
            "video_count": int(ch_stats.get("videoCount", 0)),
        },
        "videos": videos_list,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ANALYTICS_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def scrape_studio_analytics_cdp(port: int = 9222) -> dict[str, Any]:
    """Read Shorts performance & channel ID directly from logged-in YouTube Studio via Chrome CDP."""
    active_port = find_active_cdp_port(port)
    if active_port is None:
        active_port, _ = launch_chrome_cdp(port)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{active_port}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        try:
            page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.5)
            if "accounts.google.com" in page.url or "signin" in page.url.lower():
                raise RuntimeError("Faça login no YouTube Studio na janela do Chrome antes de ler os dados.")

            m = re.search(r"/channel/(UC[A-Za-z0-9_-]+)", page.url)
            channel_id = m.group(1) if m else ""
            if channel_id:
                page.goto(
                    f"https://studio.youtube.com/channel/{channel_id}/videos/short",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                time.sleep(3.5)

            scraped_rows = page.evaluate(
                """
                () => {
                    const out = [];
                    const rows = document.querySelectorAll('ytcp-video-row');
                    for (const row of rows) {
                        const titleEl = row.querySelector('#video-title, a#video-title');
                        const linkEl = row.querySelector('a[href*="/video/"]');
                        const title = titleEl ? titleEl.textContent.trim() : '';
                        const href = linkEl ? linkEl.getAttribute('href') : '';
                        const vidMatch = href ? href.match(/\\/video\\/([A-Za-z0-9_-]+)/) : null;
                        const vid = vidMatch ? vidMatch[1] : '';
                        const cells = Array.from(row.querySelectorAll('[role="cell"], .tablecell-views, .tablecell-comments, .tablecell-likes'))
                            .map(c => c.innerText.replace(/\\s+/g, ' ').trim());
                        if (title) {
                            out.push({ video_id: vid, title, cells });
                        }
                    }
                    return out;
                }
                """
            )
        finally:
            try:
                page.close()
            except Exception:
                pass

    # Merge into analytics cache
    existing: dict[str, Any] = {}
    if ANALYTICS_CACHE_FILE.is_file():
        try:
            existing = json.loads(ANALYTICS_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    ch_info = existing.get("channel", {})
    if channel_id and not ch_info.get("id"):
        ch_info["id"] = channel_id

    existing_by_id = {v.get("video_id"): v for v in existing.get("videos", []) if v.get("video_id")}
    studio_videos: list[dict[str, Any]] = []
    for row in scraped_rows or []:
        vid = row.get("video_id", "")
        cells = row.get("cells", [])
        base_item = dict(existing_by_id.get(vid, {}))
        base_item.setdefault("video_id", vid)
        base_item["title"] = row.get("title") or base_item.get("title", "")
        base_item["studio_cells"] = " | ".join(c for c in cells if c)
        if vid and not base_item.get("url"):
            base_item["url"] = f"https://youtube.com/shorts/{vid}"
        studio_videos.append(base_item)

    if not existing.get("videos") and studio_videos:
        existing["videos"] = studio_videos
    elif studio_videos:
        by_vid = {v.get("video_id"): v for v in studio_videos if v.get("video_id")}
        for v in existing.get("videos", []):
            st = by_vid.get(v.get("video_id"))
            if st:
                v["studio_cells"] = st.get("studio_cells", "")
        known_vids = {v.get("video_id") for v in existing.get("videos", [])}
        for st in studio_videos:
            if st.get("video_id") and st["video_id"] not in known_vids:
                existing["videos"].append(st)

    existing["channel"] = ch_info
    existing["studio_updated_at"] = datetime.now().isoformat(timespec="seconds")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ANALYTICS_CACHE_FILE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return existing


def analyze_performance_with_pool(analytics_data: dict[str, Any] | None = None) -> str:
    """Ask the .env Gemini Pool to analyze Shorts performance and recommend improvements."""
    if analytics_data is None:
        if not ANALYTICS_CACHE_FILE.is_file():
            return "❌ Atualize as métricas do canal primeiro antes de pedir a análise da IA."
        analytics_data = json.loads(ANALYTICS_CACHE_FILE.read_text(encoding="utf-8"))

    videos = analytics_data.get("videos", [])
    if not videos:
        return "❌ Nenhum vídeo encontrado nas métricas para analisar."

    if not has_active_pool():
        return "❌ Pool LLM (.env) não configurado."

    compact = [
        {
            "title": v.get("title", ""),
            "bucket": v.get("bucket", ""),
            "duration_sec": v.get("duration_sec", 0),
            "views": v.get("views", 0),
            "likes": v.get("likes", 0),
            "comments": v.get("comments", 0),
            "engagement_pct": v.get("engagement_pct", 0),
        }
        for v in videos[:30]
    ]
    prompt = f"""
Analise os dados reais de desempenho dos Shorts deste canal e responda em JSON:
{{
  "resumo": "diagnóstico geral em 2 frases",
  "melhor_duracao": "qual formato (30s, 60s ou 90s) está performando melhor e por quê",
  "padroes_vencedores": ["padrão 1", "padrão 2", "padrão 3"],
  "proximos_passos": ["ação prática 1", "ação prática 2", "ação prática 3"]
}}

CANAL: {json.dumps(analytics_data.get("channel", {}), ensure_ascii=False)}
SHORTS: {json.dumps(compact, ensure_ascii=False)}
""".strip()

    parsed, provider = call_llm_json(prompt, temperature=0.3, max_tokens=2048)
    if not isinstance(parsed, dict):
        return f"Resultado ({provider}): {parsed}"

    lines = [
        f"### 🧠 Diagnóstico do Canal (`{provider}`)",
        parsed.get("resumo", ""),
        f"\n- **Melhor formato:** {parsed.get('melhor_duracao', '-')}",
        "\n**Padrões dos vídeos que mais performaram:**",
        *[f"- {p}" for p in parsed.get("padroes_vencedores", [])],
        "\n**Recomendações para os próximos cortes:**",
        *[f"- {a}" for a in parsed.get("proximos_passos", [])],
    ]
    return "\n".join(lines)
