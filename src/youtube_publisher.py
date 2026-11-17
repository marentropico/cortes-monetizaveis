"""YouTube Shorts metadata generator and real-Chrome CDP uploader (via Playwright)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src import OUTPUT_DIR, TEMP_DIR
from src.video_editor import list_rendered_clips

QUEUE_FILE = OUTPUT_DIR / "youtube_posts_queue.json"
HISTORY_FILE = OUTPUT_DIR / "uploaded_history.json"
CHROME_PROFILE_DIR = TEMP_DIR / "youtube_chrome_profile"

CURATED_TITLES_BY_ID: dict[int, str] = {
    18: "ESSE É O PUZZLE MAIS DIFÍCIL DO JOGO E DEU TUDO ERRADO! 😂 #shorts #zelda",
    19: "NO ZELDA ORIGINAL PODIA EQUIPAR 3 ITENS AO MESMO TEMPO! 🤔 #shorts #zelda",
    20: "A MÚSICA DO ÓRGÃO DO GANONDORF VAI FICANDO MAIS ALTA! 😱🎹 #shorts #zelda",
    21: "TODAS AS PARTES DA TRIFORCE REUNIDAS! O CONFRONTO FINAL! 🔺⚔️ #shorts #zelda",
    22: "ESSE ATAQUE DO GANONDORF É NOVO?! DERROTANDO O REI DEMONÍACO! ⚔️😱 #shorts #zelda",
    23: "MEU DEUS, A PRINCESA ZELDA VAI MORRER NA FUGA! 😱🏰 #shorts #zelda",
    24: "QUE BARULHO FOI ESSE?! A TRANSFORMAÇÃO GIGANTE EM GANON! 👹⚡ #shorts #zelda",
    25: "VOLTE PARA O SEU TEMPO, LINK! O FINAL EMOCIONANTE DE ZELDA! 😭🗡️ #shorts #zelda",
    26: "O REMAKE DEIXOU TODOS OS SEGREDOS DE ZELDA MUITO ÓBVIOS? 🤔👻 #shorts #zelda",
    27: "SE FIZEREM REMAKE DE MAJORA'S MASK, TEM QUE SER FIEL AO N64! 🎭🎶 #shorts #zelda",
}


def _find_chrome_executable() -> str:
    local_app = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(local_app) / "Google" / "Chrome" / "Application" / "chrome.exe" if local_app else None,
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for cand in candidates:
        if cand and cand.is_file():
            return str(cand)
    raise FileNotFoundError("Google Chrome ou Microsoft Edge não encontrado no sistema.")


def _cdp_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_active_cdp_port(preferred: int = 9222) -> int | None:
    for p in (preferred, 9222, 9223, 9224):
        if _cdp_alive(p):
            return p
    return None


def launch_chrome_cdp(port: int = 9222) -> tuple[int, str]:
    """Launch real Chrome with persistent profile & remote debugging on YouTube Studio."""
    active = find_active_cdp_port(port)
    if active is not None:
        return active, f"Chrome CDP já está ativo na porta {active}."

    chosen_port = port
    if _port_in_use(chosen_port):
        for alt in (9223, 9224, 9225):
            if not _port_in_use(alt):
                chosen_port = alt
                break

    chrome_exe = _find_chrome_executable()
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        cmd_str = (
            f'"{chrome_exe}" --remote-debugging-port={chosen_port} '
            f'--user-data-dir="{CHROME_PROFILE_DIR}" '
            '--no-first-run --no-default-browser-check --new-window "https://studio.youtube.com"'
        )
        # Escape single quotes for PowerShell single-quoted literal
        ps_cmd_str = cmd_str.replace("'", "''")
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine='{ps_cmd_str}'}} | Out-Null",
            ],
            check=False,
        )
    else:
        cmd = [
            chrome_exe,
            f"--remote-debugging-port={chosen_port}",
            f"--user-data-dir={CHROME_PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            "https://studio.youtube.com",
        ]
        subprocess.Popen(cmd, start_new_session=True)

    deadline = time.time() + 10.0
    while time.time() < deadline:
        if _cdp_alive(chosen_port):
            return (
                chosen_port,
                f"Chrome aberto na porta {chosen_port}. Se ainda não estiver logado, faça login no YouTube Studio na janela aberta.",
            )
        time.sleep(0.4)

    return chosen_port, f"Chrome iniciado (porta {chosen_port}); aguarde carregar a janela."


def load_uploaded_history() -> dict[str, dict[str, Any]]:
    if HISTORY_FILE.is_file():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _save_uploaded_history(history: dict[str, dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def build_viral_metadata(cut: dict[str, Any], source_video: str = "") -> dict[str, str]:
    """Build YouTube Shorts title (<=100 chars) and SEO description with hashtags."""
    if cut.get("youtube_title") and cut.get("youtube_description"):
        return {
            "youtube_title": str(cut["youtube_title"])[:100],
            "youtube_description": str(cut["youtube_description"])[:5000],
        }

    cut_id = int(cut.get("id", 0))
    hook = str(cut.get("hook_text", "")).strip()
    reason = str(cut.get("context_reason", "")).strip()
    reason = re.sub(r"\s*(?:—|\|)\s*(?:Corte\s*\d+s|Score.*).*$", "", reason, flags=re.IGNORECASE).strip()
    raw_title = str(cut.get("title", f"Corte_{cut_id}")).replace("_", " ").strip()

    is_zelda = "zelda" in source_video.lower() or "ganondorf" in source_video.lower()
    game_label = "The Legend of Zelda: Ocarina of Time Remake" if is_zelda else (
        Path(source_video).stem if source_video else "Gameplay"
    )
    hashtags = (
        "#shorts #zelda #ocarinaoftime #gameplay #alanzoka #cortes #nintendo"
        if is_zelda
        else "#shorts #gameplay #gaming #cortes #clips"
    )

    if cut_id in CURATED_TITLES_BY_ID:
        yt_title = CURATED_TITLES_BY_ID[cut_id]
    else:
        base = hook if hook else raw_title.upper()
        suffix = " #shorts #zelda" if is_zelda else " #shorts"
        max_base = 100 - len(suffix)
        yt_title = (base[:max_base].rstrip() + suffix)[:100]

    source_credit = (
        "Trecho cortado da gameplay da Live do Alanzoka"
        if is_zelda
        else "Trecho cortado da gameplay"
    )
    yt_desc = (
        f"{hook or raw_title}\n\n"
        f"{reason}\n\n"
        f"🎮 Jogo: {game_label}\n"
        f"{source_credit}\n\n"
        f"{hashtags}"
    ).strip()

    return {
        "youtube_title": yt_title[:100],
        "youtube_description": yt_desc[:5000],
    }


def generate_youtube_queue(
    cuts_path: str | Path | None = None,
    preserve_manual_edits: bool = True,
) -> list[dict[str, Any]]:
    """Build/refresh output/youtube_posts_queue.json matching rendered MP4 clips."""
    existing_by_path: dict[str, dict[str, Any]] = {}
    if preserve_manual_edits and QUEUE_FILE.is_file():
        try:
            prev = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
            if isinstance(prev, list):
                for item in prev:
                    if item.get("video_path"):
                        existing_by_path[str(Path(item["video_path"]).resolve())] = item
        except Exception:
            pass

    cuts_by_id: dict[int, dict[str, Any]] = {}
    cpath = Path(cuts_path or (TEMP_DIR / "cuts.json"))
    if cpath.is_file():
        try:
            for c in json.loads(cpath.read_text(encoding="utf-8")):
                cuts_by_id[int(c.get("id", 0))] = c
        except Exception:
            pass

    history = load_uploaded_history()
    clips = list_rendered_clips()
    queue_items: list[dict[str, Any]] = []
    used_ids: set[int] = set()

    for clip in clips:
        vpath = Path(clip["output_path"]).resolve()
        if not vpath.is_file():
            continue
        # Parse numeric ID prefix like 18_...
        m = re.match(r"^(\d+)_", vpath.stem)
        raw_cid = int(m.group(1)) if m else int(clip.get("id", 0) or 0)
        if raw_cid <= 0:
            raw_cid = (max(used_ids) + 1) if used_ids else 1

        prev_item = existing_by_path.get(str(vpath))
        prev_id = int(prev_item.get("id", 0)) if prev_item else 0
        if prev_id > 0 and prev_id not in used_ids:
            cid = prev_id
        elif raw_cid not in used_ids:
            cid = raw_cid
        else:
            cid = max(used_ids) + 1
        used_ids.add(cid)

        cut_meta = cuts_by_id.get(raw_cid, {}) if str(clip.get("source_video", "")) in str(cpath) or len(clips) <= len(cuts_by_id) else {}
        merged_cut = {
            "id": cid,
            "title": clip.get("title") or cut_meta.get("title") or vpath.stem,
            "hook_text": clip.get("hook_text") or cut_meta.get("hook_text", ""),
            "context_reason": clip.get("context_reason") or cut_meta.get("context_reason", ""),
            "youtube_title": clip.get("youtube_title") or cut_meta.get("youtube_title", ""),
            "youtube_description": clip.get("youtube_description") or cut_meta.get("youtube_description", ""),
        }
        source_video = str(clip.get("source_video", ""))
        meta = build_viral_metadata(merged_cut, source_video=source_video)

        hist_entry = history.get(str(vpath))
        status = "posted" if hist_entry else "pending"

        queue_items.append(
            {
                "id": cid,
                "filename": vpath.name,
                "video_path": str(vpath),
                "source_video": source_video,
                "duration": clip.get("duration", 0.0),
                "youtube_title": (
                    prev_item["youtube_title"]
                    if (prev_item and cid not in CURATED_TITLES_BY_ID and prev_item.get("youtube_title"))
                    else (prev_item["youtube_title"] if prev_item and prev_item.get("edited") else meta["youtube_title"])
                ),
                "youtube_description": (
                    prev_item["youtube_description"]
                    if (prev_item and prev_item.get("edited"))
                    else meta["youtube_description"]
                ),
                "visibility": prev_item.get("visibility", "PUBLIC") if prev_item else "PUBLIC",
                "status": status,
                "youtube_url": hist_entry.get("youtube_url", "") if hist_entry else "",
            }
        )

    queue_items.sort(key=lambda x: x["id"])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return queue_items


def _normalize_yt_title(text: str) -> str:
    """Normalize a YouTube title or slug for fuzzy matching against published channel videos."""
    s = re.sub(r"#\w+", " ", str(text or "").lower())
    s = re.sub(r"^\d+_", " ", s)
    s = re.sub(r"_(?:30s|60s|90s)\b", " ", s)
    s = re.sub(r"[^a-z0-9\u00c0-\u024f]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sync_queue_with_youtube_api(refresh_api: bool = True) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compare pending queue items against live YouTube channel videos via Data API v3."""
    from difflib import SequenceMatcher
    from src.youtube_analytics import (
        ANALYTICS_CACHE_FILE,
        fetch_channel_analytics_api,
        get_saved_youtube_config,
    )

    api_key, channel_ref = get_saved_youtube_config()
    channel_videos: list[dict[str, Any]] = []
    source_label = "cache"

    if refresh_api and api_key and channel_ref:
        data = fetch_channel_analytics_api(api_key=api_key, channel_ref=channel_ref, max_videos=50)
        channel_videos = data.get("videos") or []
        source_label = "YouTube Data API v3"
    elif ANALYTICS_CACHE_FILE.is_file():
        data = json.loads(ANALYTICS_CACHE_FILE.read_text(encoding="utf-8"))
        channel_videos = data.get("videos") or []
    else:
        raise RuntimeError(
            "YouTube Data API Key ou Canal não configurados no .env. Salve-os na Aba 3 (Analytics & Sistema)."
        )

    yt_norm_list: list[tuple[str, dict[str, Any]]] = [
        (_normalize_yt_title(v.get("title", "")), v)
        for v in channel_videos
        if v.get("title")
    ]

    items = generate_youtube_queue()
    history = load_uploaded_history()
    newly_marked = 0

    for item in items:
        if item.get("status") == "posted" and item.get("youtube_url"):
            continue
        cand_titles = [
            _normalize_yt_title(item.get("youtube_title", "")),
            _normalize_yt_title(Path(str(item.get("filename", ""))).stem),
        ]
        matched_vid: dict[str, Any] | None = None
        best_score = 0.0
        for ct in cand_titles:
            if not ct:
                continue
            for yt_norm, vid in yt_norm_list:
                if not yt_norm:
                    continue
                if ct == yt_norm or (len(ct) >= 16 and (ct in yt_norm or yt_norm in ct)):
                    matched_vid = vid
                    best_score = 1.0
                    break
                score = SequenceMatcher(None, ct, yt_norm).ratio()
                if score > best_score:
                    best_score = score
                    if score >= 0.78:
                        matched_vid = vid
            if best_score >= 1.0:
                break

        if matched_vid:
            vpath = str(Path(item["video_path"]).resolve())
            url = str(matched_vid.get("url", ""))
            item["status"] = "posted"
            item["youtube_url"] = url
            history[vpath] = {
                "id": item["id"],
                "filename": item["filename"],
                "youtube_title": item.get("youtube_title", ""),
                "youtube_url": url,
                "visibility": item.get("visibility", "PUBLIC"),
                "uploaded_at": matched_vid.get("published_at") or datetime.now().isoformat(timespec="seconds"),
                "synced_from": source_label,
            }
            newly_marked += 1

    _save_uploaded_history(history)
    QUEUE_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    pending_count = sum(1 for it in items if it.get("status") != "posted")
    posted_count = len(items) - pending_count
    return items, {
        "source": source_label,
        "channel_videos_checked": len(channel_videos),
        "newly_marked": newly_marked,
        "posted_total": posted_count,
        "pending_total": pending_count,
    }


def check_youtube_studio_ready(port: int = 9222) -> tuple[bool, str]:
    """Connect via Playwright CDP and verify if Chrome is logged into YouTube Studio."""
    active_port = find_active_cdp_port(port)
    if active_port is None:
        return False, "Chrome CDP não encontrado. Clique primeiro em '1️⃣ Abrir Chrome do YouTube Studio'."

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{active_port}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = next((pg for pg in ctx.pages if "youtube.com" in pg.url or "google.com" in pg.url), None)
        if page is None:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        if "studio.youtube.com" not in page.url and "accounts.google.com" not in page.url:
            page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=20000)
            time.sleep(2.0)

        url = page.url
        if "accounts.google.com" in url or "signin" in url.lower():
            return (
                False,
                f"Chrome aberto (porta {active_port}), mas aguardando login na conta Google/YouTube ({url}).",
            )
        if "studio.youtube.com" in url:
            return True, f"✅ YouTube Studio pronto e logado (porta {active_port})!"
        return False, f"Página atual inesperada: {url}"


def _fill_textbox(page, locator, text: str) -> None:
    locator.wait_for(state="visible", timeout=25000)
    locator.click()
    time.sleep(0.2)
    locator.press("Control+a")
    locator.press("Backspace")
    time.sleep(0.1)
    locator.fill(text)
    time.sleep(0.15)
    try:
        current = locator.inner_text().strip()
    except Exception:
        current = ""
    if not current and text.strip():
        locator.click()
        page.keyboard.insert_text(text)


def _attach_file_via_cdp(page, file_input, vpath: Path) -> None:
    """Attach local video file of any size (>50MB supported) via Chrome DevTools DOM.setFileInputFiles."""
    file_input.wait_for(state="attached", timeout=30000)
    try:
        cdp = page.context.new_cdp_session(page)
        try:
            eval_res = cdp.send(
                "Runtime.evaluate",
                {
                    "expression": """
                        (() => {
                            const findInput = (root) => {
                                const direct = root.querySelector('input[type="file"]');
                                if (direct) return direct;
                                for (const el of root.querySelectorAll('*')) {
                                    if (el.shadowRoot) {
                                        const found = findInput(el.shadowRoot);
                                        if (found) return found;
                                    }
                                }
                                return null;
                            };
                            return findInput(document);
                        })()
                    """,
                    "returnByValue": False,
                },
            )
            obj_id = eval_res.get("result", {}).get("objectId")
            if obj_id:
                cdp.send("DOM.setFileInputFiles", {"files": [str(vpath)], "objectId": obj_id})
                return
        finally:
            cdp.detach()
    except Exception:
        pass
    # Fallback for <50MB files
    file_input.set_input_files(str(vpath))


def _start_short_upload_tab(
    page,
    video_path: str | Path,
    title: str,
    description: str,
    visibility: str = "PUBLIC",
    progress_callback: Callable[[str], None] | None = None,
    thumbnail_path: str | Path | None = None,
) -> tuple[bool, dict[str, Any] | str]:
    """Open upload wizard in `page`, fill metadata, and leave it uploading at Visibility step."""
    vpath = Path(video_path).resolve()
    if not vpath.is_file():
        return False, f"Arquivo não encontrado: {vpath}"

    if progress_callback:
        progress_callback(f"Abrindo upload do YouTube Studio para {vpath.name}...")

    for attempt in range(2):
        try:
            if attempt == 0:
                page.goto("https://www.youtube.com/upload", wait_until="commit", timeout=45000)
            else:
                page.goto("https://studio.youtube.com", wait_until="domcontentloaded", timeout=45000)
                time.sleep(1.5)
                create_btn = page.locator("#create-icon").first
                if create_btn.is_visible(timeout=8000):
                    create_btn.click()
                    time.sleep(0.6)
                    page.locator("tp-yt-paper-item#text-item-0").first.click()
            break
        except Exception:
            if attempt == 1:
                raise
            time.sleep(2.0)
    time.sleep(2.5)

    if "accounts.google.com" in page.url or "signin" in page.url.lower():
        return False, "Sessão não está logada no YouTube Studio."

    file_input = page.locator('input[type="file"]').first
    _attach_file_via_cdp(page, file_input, vpath)

    if progress_callback:
        progress_callback(f"Arquivo anexado ({vpath.name}). Preenchendo título e descrição...")

    title_box = page.locator("#title-textarea #textbox").first
    title_box.wait_for(state="visible", timeout=35000)
    _fill_textbox(page, title_box, title[:100])

    desc_box = page.locator("#description-textarea #textbox").first
    desc_box.wait_for(state="visible", timeout=20000)
    _fill_textbox(page, desc_box, description[:5000])

    # Mark "Not made for kids"
    not_kids = page.locator('tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]').first
    not_kids.wait_for(state="visible", timeout=25000)
    not_kids.scroll_into_view_if_needed()
    not_kids.click()
    time.sleep(0.8)

    # Attach Hook thumbnail in Step 1 (Details) if available and enabled by YouTube Studio
    if thumbnail_path and Path(thumbnail_path).is_file():
        try:
            thumb_input = page.locator('ytcp-video-thumbnail-editor input[type="file"]').first
            if thumb_input.count() > 0:
                _attach_file_via_cdp(page, thumb_input, Path(thumbnail_path))
                time.sleep(1.2)
                if progress_callback:
                    progress_callback(f"🖼️ Capa Hook anexada: {Path(thumbnail_path).name}")
            elif progress_callback:
                progress_callback("ℹ️ Campo de miniatura indisponível para este Short durante o upload.")
        except Exception as exc:
            if progress_callback:
                progress_callback(f"ℹ️ Miniatura não anexada no upload ({exc}); seguindo publicação.")

    yt_url = ""
    try:
        link_el = page.locator('a[href*="youtu.be/"], a[href*="youtube.com/shorts/"]').first
        if link_el.count() > 0:
            yt_url = (link_el.get_attribute("href") or "").strip()
    except Exception:
        pass

    # Step through Next x3 (Details -> Video Elements -> Checks -> Visibility)
    for _ in range(3):
        next_btn = page.locator("ytcp-uploads-dialog #next-button, #next-button").first
        next_btn.wait_for(state="visible", timeout=35000)
        next_btn.scroll_into_view_if_needed()
        next_btn.click()
        time.sleep(1.0)

    vis_key = visibility.upper().strip()
    if vis_key not in ("PUBLIC", "UNLISTED", "PRIVATE"):
        vis_key = "PUBLIC"
    vis_radio = page.locator(f'tp-yt-paper-radio-button[name="{vis_key}"]').first
    vis_radio.wait_for(state="visible", timeout=25000)
    vis_radio.scroll_into_view_if_needed()
    vis_radio.click()
    time.sleep(0.6)

    if progress_callback:
        progress_callback(f"⏳ {vpath.name} enviando em segundo plano...")

    return True, {
        "page": page,
        "vpath": vpath,
        "yt_url": yt_url,
        "done_btn": page.locator("#done-button").first,
        "deadline": time.time() + 600.0,
        "last_prog_report": 0.0,
        "saw_upload_signal": False,
    }


def _poll_upload_tab(
    state: dict[str, Any],
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """Check one uploading tab; if 100% done, click Publish, close tab immediately, and return ('done', url)."""
    page = state["page"]
    vpath: Path = state["vpath"]
    done_btn = state["done_btn"]
    deadline: float = state["deadline"]

    if time.time() >= deadline:
        return "error", "Timeout aguardando conclusão do envio no YouTube Studio."

    prog_text = ""
    try:
        for sel in (
            "ytcp-video-upload-progress",
            "ytcp-uploads-dialog .progress-label",
            "span.progress-label",
        ):
            loc = page.locator(sel).first
            if loc.count() > 0:
                txt = loc.inner_text().strip()
                if txt:
                    prog_text = txt
                    break
    except Exception:
        pass

    low = prog_text.lower()
    is_pct_uploading = bool(re.search(r"\b\d{1,3}%", low)) and "100%" not in low
    is_uploading_word = any(k in low for k in ("enviando", "uploading", "restante", "left", "envio:"))
    upload_done_word = any(
        k in low
        for k in (
            "100%",
            "envio concluído",
            "upload complete",
            "processando",
            "processing",
            "verificações",
            "checks",
            "nenhum problema",
            "no issues",
        )
    )
    if is_pct_uploading or is_uploading_word or upload_done_word:
        state["saw_upload_signal"] = True

    still_uploading = is_pct_uploading or (is_uploading_word and not upload_done_word)
    try:
        is_disabled = (done_btn.get_attribute("aria-disabled") or "false").lower() == "true"
    except Exception:
        is_disabled = True

    if not still_uploading and not is_disabled and (
        upload_done_word or not state["saw_upload_signal"] or time.time() > deadline - 585
    ):
        time.sleep(1.2)
        yt_url = state["yt_url"]
        if not yt_url:
            try:
                link_el = page.locator('a[href*="youtu.be/"], a[href*="youtube.com/shorts/"]').first
                if link_el.count() > 0:
                    yt_url = (link_el.get_attribute("href") or "").strip()
            except Exception:
                pass

        done_btn.click()
        time.sleep(2.5)
        try:
            close_btn = page.locator("ytcp-video-share-dialog #close-button, #close-button").first
            if close_btn.is_visible(timeout=12000):
                close_btn.click()
                time.sleep(0.8)
        except Exception:
            pass
        return "done", yt_url or "Publicado no YouTube Studio"

    if progress_callback and time.time() - state["last_prog_report"] >= 8.0 and prog_text:
        state["last_prog_report"] = time.time()
        progress_callback(f"  Progresso YouTube ({vpath.name}): {prog_text.replace(chr(10), ' ')}")
    return "uploading", ""


def upload_single_short(
    page,
    video_path: str | Path,
    title: str,
    description: str,
    visibility: str = "PUBLIC",
    progress_callback: Callable[[str], None] | None = None,
    thumbnail_path: str | Path | None = None,
) -> tuple[bool, str]:
    """Upload one MP4 to YouTube Studio through the open logged-in browser page."""
    ok, res = _start_short_upload_tab(
        page=page,
        video_path=video_path,
        title=title,
        description=description,
        visibility=visibility,
        progress_callback=progress_callback,
        thumbnail_path=thumbnail_path,
    )
    if not ok:
        return False, str(res)
    state = res
    assert isinstance(state, dict)
    while True:
        status, msg = _poll_upload_tab(state, progress_callback=progress_callback)
        if status == "done":
            return True, msg
        if status == "error":
            return False, msg
        time.sleep(1.5)


def upload_queue(
    start_id: int = 18,
    end_id: int = 27,
    visibility: str = "PUBLIC",
    port: int = 9222,
    skip_posted: bool = True,
    progress_callback: Callable[[str], None] | None = None,
    selected_paths: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Upload queued Shorts via Chrome CDP (by selected_paths or [start_id, end_id])."""
    active_port = find_active_cdp_port(port)
    if active_port is None:
        raise RuntimeError(
            "Chrome CDP não está aberto. Clique em '1️⃣ Abrir Chrome do YouTube Studio' e faça login primeiro."
        )

    if QUEUE_FILE.is_file():
        try:
            queue_items = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            queue_items = generate_youtube_queue()
    else:
        queue_items = generate_youtube_queue()

    if selected_paths is not None:
        norm_set = {str(Path(p).resolve()) for p in selected_paths if p}
        targets = [
            item
            for item in queue_items
            if str(Path(item["video_path"]).resolve()) in norm_set
        ]
        if not targets:
            raise ValueError("Nenhum corte selecionado na fila. Marque ao menos um corte para publicar.")
    else:
        targets = [item for item in queue_items if int(start_id) <= int(item["id"]) <= int(end_id)]
        if not targets:
            raise ValueError(f"Nenhum corte encontrado na fila entre ID {start_id} e {end_id}.")

    history = load_uploaded_history()
    results: list[dict[str, Any]] = []

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{active_port}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()

        max_concurrent_tabs = 2
        pending_tabs: list[dict[str, Any]] = []

        def _finalize_tab(entry: dict[str, Any], ok: bool, msg: str) -> None:
            item = entry["item"]
            vpath = entry["vpath"]
            try:
                entry["page"].close()
            except Exception:
                pass
            if ok:
                history[vpath] = {
                    "id": item["id"],
                    "filename": item["filename"],
                    "youtube_title": item["youtube_title"],
                    "visibility": visibility,
                    "youtube_url": msg if msg.startswith("http") else "",
                    "posted_at": datetime.now().isoformat(timespec="seconds"),
                }
                _save_uploaded_history(history)
                item["status"] = "posted"
                item["youtube_url"] = history[vpath]["youtube_url"]
                if progress_callback:
                    progress_callback(f"✅ #{item['id']} publicado e aba fechada! {item['youtube_url']}")
                results.append({**item, "status": "posted"})
            else:
                if progress_callback:
                    progress_callback(f"❌ Falha no #{item['id']}: {msg}")
                results.append({**item, "status": f"error: {msg}"})

        def _drain_ready_tabs(wait_until_below: int) -> None:
            while len(pending_tabs) >= wait_until_below and pending_tabs:
                still_running: list[dict[str, Any]] = []
                for entry in pending_tabs:
                    try:
                        status, msg = _poll_upload_tab(entry["state"], progress_callback=progress_callback)
                    except Exception as exc:
                        status, msg = "error", str(exc)
                    if status == "done":
                        _finalize_tab(entry, True, msg)
                    elif status == "error":
                        _finalize_tab(entry, False, msg)
                    else:
                        still_running.append(entry)
                pending_tabs[:] = still_running
                if len(pending_tabs) >= wait_until_below and pending_tabs:
                    time.sleep(1.2)

        for idx, item in enumerate(targets, start=1):
            vpath = str(Path(item["video_path"]).resolve())
            if skip_posted and vpath in history:
                if progress_callback:
                    progress_callback(f"[{idx}/{len(targets)}] Pulando #{item['id']} já postado: {item['filename']}")
                results.append({**item, "status": "skipped_already_posted"})
                continue

            _drain_ready_tabs(max_concurrent_tabs)

            if progress_callback:
                progress_callback(
                    f"[{idx}/{len(targets)}] Postando #{item['id']}: {item['youtube_title']}"
                )

            thumb_path: Path | None = None
            try:
                from src.thumbnail_generator import ensure_thumbnail_for_clip

                thumb_path = ensure_thumbnail_for_clip(
                    vpath,
                    youtube_title=str(item.get("youtube_title", "")),
                )
                if progress_callback:
                    progress_callback(f"🎨 Capa Hook pronta: {thumb_path.name}")
            except Exception as exc:
                if progress_callback:
                    progress_callback(f"ℹ️ Capa Hook ignorada ({exc}); seguindo upload.")

            upload_page = ctx.new_page()
            try:
                ok, res = _start_short_upload_tab(
                    page=upload_page,
                    video_path=vpath,
                    title=item["youtube_title"],
                    description=item["youtube_description"],
                    visibility=visibility,
                    progress_callback=progress_callback,
                    thumbnail_path=thumb_path,
                )
            except Exception as exc:
                ok, res = False, str(exc)

            if ok and isinstance(res, dict):
                pending_tabs.append({"item": item, "vpath": vpath, "page": upload_page, "state": res})
            else:
                _finalize_tab({"item": item, "vpath": vpath, "page": upload_page}, False, str(res))

        _drain_ready_tabs(1)

    generate_youtube_queue()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Publicador automático YouTube Shorts via Chrome CDP")
    parser.add_argument("--prepare-queue", action="store_true", help="Apenas gera output/youtube_posts_queue.json")
    parser.add_argument("--open-chrome", action="store_true", help="Abre Chrome CDP no YouTube Studio")
    parser.add_argument("--check", action="store_true", help="Verifica se Chrome CDP está logado no YouTube Studio")
    parser.add_argument("--upload", action="store_true", help="Posta cortes da fila")
    parser.add_argument("--start-id", type=int, default=18)
    parser.add_argument("--end-id", type=int, default=27)
    parser.add_argument("--visibility", default="PUBLIC", choices=["PUBLIC", "UNLISTED", "PRIVATE"])
    args = parser.parse_args()

    if args.prepare_queue:
        q = generate_youtube_queue()
        print(f"Fila gerada com {len(q)} itens em {QUEUE_FILE}")
    if args.open_chrome:
        port, msg = launch_chrome_cdp()
        print(f"Port={port} | {msg}")
    if args.check:
        ok, msg = check_youtube_studio_ready()
        print(f"Ready={ok} | {msg}")
    if args.upload:
        upload_queue(
            start_id=args.start_id,
            end_id=args.end_id,
            visibility=args.visibility,
            progress_callback=print,
        )


if __name__ == "__main__":
    main()
