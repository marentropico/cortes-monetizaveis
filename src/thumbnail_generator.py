"""Local viral Shorts thumbnail generator (PIL + Hook text) and batch YouTube Studio updater."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from src import OUTPUT_DIR
from src.video_editor import list_rendered_clips
from src.youtube_publisher import (
    QUEUE_FILE,
    _attach_file_via_cdp,
    find_active_cdp_port,
    generate_youtube_queue,
    load_uploaded_history,
)

THUMBNAILS_DIR = OUTPUT_DIR / "thumbnails"

_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\impact.ttf",
    r"C:\Windows\Fonts\ariblk.ttf",
    r"C:\Windows\Fonts\seguibl.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
)


def _load_bold_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for fpath in _FONT_CANDIDATES:
        if Path(fpath).is_file():
            try:
                return ImageFont.truetype(fpath, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _extract_video_id(youtube_url: str) -> str:
    m = re.search(r"(?:shorts/|youtu\.be/|v=)([A-Za-z0-9_-]{11})", youtube_url or "")
    return m.group(1) if m else ""


def _fetch_youtube_cover_image(video_id: str) -> Image.Image | None:
    """Try downloading the existing YouTube Shorts vertical cover (oar2.jpg)."""
    if not video_id:
        return None
    for variant in ("oar2.jpg", "sd2.jpg", "maxresdefault.jpg"):
        url = f"https://i.ytimg.com/vi/{video_id}/{variant}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status != 200:
                    continue
                data = resp.read()
                if len(data) < 8000:
                    continue
                from io import BytesIO

                img = Image.open(BytesIO(data)).convert("RGB")
                # Prefer vertical covers (height >= width) or high-res images
                if img.height >= 720 or variant == "oar2.jpg":
                    return img
        except Exception:
            continue
    return None


def _extract_mp4_frame(video_path: Path, timestamp: float = 2.5) -> Image.Image:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Não foi possível abrir o vídeo: {video_path}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
        idx = min(max(0, total_frames - 1), int(round(timestamp * fps)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"Não foi possível ler frame de {video_path}")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)
    finally:
        cap.release()


def _wrap_hook_lines(text: str, font: ImageFont.FreeTypeFont, max_width_px: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = [w for w in re.sub(r"\s+", " ", text.strip()).split(" ") if w]
    if not words:
        return []
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        cand = f"{cur} {w}"
        bbox = draw.textbbox((0, 0), cand, font=font, stroke_width=10)
        if (bbox[2] - bbox[0]) <= max_width_px:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines[:4]


def _apply_fisheye_bulge(
    rgba_img: Image.Image,
    cy: float,
    ry: float,
    strength: float = 0.36,
) -> Image.Image:
    """Apply a smooth elliptical fisheye/bulge warp to an RGBA text overlay layer."""
    arr = np.array(rgba_img, dtype=np.uint8)
    h, w = arr.shape[:2]
    cx = w / 2.0
    rx = w * 0.50
    ry = max(220.0, ry)

    y_idx, x_idx = np.indices((h, w), dtype=np.float32)
    dx = (x_idx - cx) / rx
    dy = (y_idx - cy) / ry
    r2 = dx * dx + dy * dy

    # Smooth Gaussian-weighted barrel magnification ("gordinha" center bulge)
    scale = 1.0 / (1.0 + strength * np.exp(-r2 * 1.15))
    map_x = (cx + (x_idx - cx) * scale).astype(np.float32)
    map_y = (cy + (y_idx - cy) * scale).astype(np.float32)

    warped = cv2.remap(
        arr,
        map_x,
        map_y,
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return Image.fromarray(warped, mode="RGBA")


def render_hook_thumbnail(
    base_img: Image.Image,
    hook_text: str,
    output_path: Path,
) -> Path:
    """Compose a 1080x1920 high-contrast thumbnail with stylized hook typography."""
    target_w, target_h = 1080, 1920
    img = base_img.convert("RGB")
    if img.size != (target_w, target_h):
        # Center-crop/cover to 1080x1920 without distortion
        src_ar = img.width / max(1, img.height)
        tgt_ar = target_w / target_h
        if src_ar > tgt_ar:
            new_w = int(round(img.height * tgt_ar))
            x0 = (img.width - new_w) // 2
            img = img.crop((x0, 0, x0 + new_w, img.height))
        elif src_ar < tgt_ar:
            new_h = int(round(img.width / tgt_ar))
            y0 = (img.height - new_h) // 2
            img = img.crop((0, y0, img.width, y0 + new_h))
        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # Slight punchy contrast & saturation boost for thumbnail pop
    img = ImageEnhance.Contrast(img).enhance(1.10)
    img = ImageEnhance.Color(img).enhance(1.12)

    clean_hook = re.sub(r"#\w+", "", hook_text or "").strip().upper()
    if not clean_hook:
        clean_hook = "MOMENTO INSANO!"

    # Add a soft centered band scrim around the vertical middle so the hook pops cleanly
    overlay = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    band_top, band_bot = 620, 1300
    mid_y = (band_top + band_bot) / 2.0
    half_span = (band_bot - band_top) / 2.0
    for y in range(band_top, band_bot):
        dist = abs(y - mid_y) / half_span
        alpha = int(135 * max(0.0, 1.0 - dist ** 1.4))
        ov_draw.line([(0, y), (target_w, y)], fill=(8, 10, 18, alpha))

    composed = Image.alpha_composite(img.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(composed)

    # Pick largest font size that fits cleanly in <= 3-4 lines (leaving room for fisheye bulge)
    font_size = 104
    lines: list[str] = []
    font = _load_bold_font(font_size)
    while font_size >= 60:
        font = _load_bold_font(font_size)
        lines = _wrap_hook_lines(clean_hook, font, max_width_px=840, draw=draw)
        if len(lines) <= 3:
            break
        font_size -= 8

    line_heights: list[int] = []
    for ln in lines:
        bb = draw.textbbox((0, 0), ln, font=font, stroke_width=10)
        line_heights.append((bb[3] - bb[1]) + 20)

    total_h = sum(line_heights)
    start_y = max(480, (target_h - total_h) // 2)

    # Render Hook text + drop shadow on a dedicated RGBA layer for fisheye warp
    text_layer = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    sh_layer = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    sh_draw = ImageDraw.Draw(sh_layer)
    cur_y = start_y
    for i, ln in enumerate(lines):
        bb = draw.textbbox((0, 0), ln, font=font, stroke_width=10)
        lw = bb[2] - bb[0]
        x = (target_w - lw) // 2
        sh_draw.text((x + 6, cur_y + 8), ln, font=font, fill=(0, 0, 0, 210), stroke_width=12, stroke_fill=(0, 0, 0, 210))
        cur_y += line_heights[i]
    sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(radius=6))
    text_layer = Image.alpha_composite(text_layer, sh_layer)

    txt_draw = ImageDraw.Draw(text_layer)
    cur_y = start_y
    for i, ln in enumerate(lines):
        bb = draw.textbbox((0, 0), ln, font=font, stroke_width=10)
        lw = bb[2] - bb[0]
        x = (target_w - lw) // 2
        fill_col = (255, 230, 0, 255) if i % 2 == 0 else (255, 255, 255, 255)
        txt_draw.text(
            (x, cur_y),
            ln,
            font=font,
            fill=fill_col,
            stroke_width=10,
            stroke_fill=(0, 0, 0, 255),
        )
        cur_y += line_heights[i]

    text_center_y = start_y + total_h / 2.0
    text_layer = _apply_fisheye_bulge(
        text_layer,
        cy=text_center_y,
        ry=max(260.0, total_h * 0.90),
        strength=0.38,
    )
    composed = Image.alpha_composite(composed, text_layer)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rgb_out = composed.convert("RGB")
    for q in (92, 85, 76):
        rgb_out.save(output_path, format="JPEG", quality=q, optimize=True)
        if output_path.stat().st_size <= 1_900_000:
            break
    return output_path


def get_thumbnail_path_for_clip(video_path: str | Path) -> Path:
    vpath = Path(video_path).resolve()
    proj_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", vpath.parent.name).strip("_")[:40] or "shorts"
    return THUMBNAILS_DIR / proj_slug / f"{vpath.stem}_thumb.jpg"


def ensure_thumbnail_for_clip(
    video_path: str | Path,
    hook_text: str = "",
    youtube_title: str = "",
) -> Path:
    """Ensure a clickbait Hook thumbnail exists for the given clip MP4."""
    vpath = Path(video_path).resolve()
    out_jpg = get_thumbnail_path_for_clip(vpath)
    if out_jpg.is_file():
        return out_jpg

    hook = hook_text.strip()
    if not hook:
        clips_by_path = {str(Path(c["output_path"]).resolve()): c for c in list_rendered_clips()}
        clip_meta = clips_by_path.get(str(vpath), {})
        hook = str(clip_meta.get("hook_text") or "").strip()
    if not hook and youtube_title:
        hook = re.sub(r"[^\w\s!?.,áéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ-]", "", youtube_title).strip()

    base_img = _extract_mp4_frame(vpath, timestamp=2.5)
    return render_hook_thumbnail(base_img, hook_text=hook, output_path=out_jpg)


def generate_thumbnails_for_clips(
    selected_paths: list[str] | None = None,
    prefer_youtube_cover: bool = True,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Generate hook thumbnails for posted/selected clips and save them under output/thumbnails/."""
    queue_items = generate_youtube_queue()
    clips_by_path = {str(Path(c["output_path"]).resolve()): c for c in list_rendered_clips()}
    sel_set = {str(Path(p).resolve()) for p in selected_paths} if selected_paths else None

    results: list[dict[str, Any]] = []
    targets = []
    for it in queue_items:
        vpath = Path(str(it.get("video_path", ""))).resolve()
        if not vpath.is_file():
            continue
        if sel_set is not None:
            if str(vpath) not in sel_set:
                continue
        elif it.get("status") != "posted":
            continue
        targets.append(it)

    for idx, it in enumerate(targets, start=1):
        vpath = Path(str(it["video_path"])).resolve()
        clip_meta = clips_by_path.get(str(vpath), {})
        hook = str(clip_meta.get("hook_text") or "").strip()
        if not hook:
            # Fallback to title without emojis/hashtags
            hook = re.sub(r"[^\w\s!?.,áéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ-]", "", str(it.get("youtube_title", "")))
        vid = _extract_video_id(str(it.get("youtube_url", "")))
        proj_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", vpath.parent.name).strip("_")[:40] or "shorts"
        out_jpg = THUMBNAILS_DIR / proj_slug / f"{vpath.stem}_thumb.jpg"

        base_img: Image.Image | None = None
        source_used = "mp4_frame"
        if prefer_youtube_cover and vid:
            base_img = _fetch_youtube_cover_image(vid)
            if base_img is not None:
                source_used = "youtube_cover"
        if base_img is None:
            base_img = _extract_mp4_frame(vpath, timestamp=2.5)

        render_hook_thumbnail(base_img, hook_text=hook, output_path=out_jpg)
        if progress_callback:
            progress_callback(f"[{idx}/{len(targets)}] Capa gerada ({source_used}): {out_jpg.name}")

        results.append(
            {
                "id": it.get("id"),
                "filename": vpath.name,
                "video_path": str(vpath),
                "video_id": vid,
                "youtube_url": it.get("youtube_url", ""),
                "hook_text": hook,
                "thumbnail_path": str(out_jpg),
                "source": source_used,
            }
        )

    return results


def list_generated_thumbnails() -> list[str]:
    if not THUMBNAILS_DIR.exists():
        return []
    return [
        str(p)
        for p in sorted(THUMBNAILS_DIR.rglob("*_thumb.jpg"), key=lambda x: x.stat().st_mtime, reverse=True)
        if p.is_file()
    ]


def upload_thumbnails_batch(
    selected_paths: list[str] | None = None,
    port: int = 9222,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Batch-upload generated hook thumbnails to YouTube Studio via Chrome CDP."""
    active_port = find_active_cdp_port(port)
    if active_port is None:
        raise RuntimeError(
            "Chrome CDP não está aberto. Abra o Chrome do YouTube Studio e faça login primeiro."
        )

    queue_items = json.loads(QUEUE_FILE.read_text(encoding="utf-8")) if QUEUE_FILE.is_file() else generate_youtube_queue()
    sel_set = {str(Path(p).resolve()) for p in selected_paths} if selected_paths else None

    targets: list[tuple[dict[str, Any], str, Path]] = []
    for it in queue_items:
        vpath = Path(str(it.get("video_path", ""))).resolve()
        if sel_set is not None and str(vpath) not in sel_set:
            continue
        vid = _extract_video_id(str(it.get("youtube_url", "")))
        if not vid:
            continue
        proj_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", vpath.parent.name).strip("_")[:40] or "shorts"
        thumb_path = THUMBNAILS_DIR / proj_slug / f"{vpath.stem}_thumb.jpg"
        if thumb_path.is_file():
            targets.append((it, vid, thumb_path))

    if not targets:
        raise ValueError("Nenhuma capa gerada encontrada para vídeos já postados (gere as capas primeiro).")

    from playwright.sync_api import sync_playwright

    updated: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{active_port}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()

        for idx, (it, vid, thumb_path) in enumerate(targets, start=1):
            if progress_callback:
                progress_callback(f"[{idx}/{len(targets)}] Atualizando capa de {vid} ({thumb_path.name})...")
            page = ctx.new_page()
            try:
                page.goto(f"https://studio.youtube.com/video/{vid}/edit", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_selector("ytcp-video-thumbnail-editor", timeout=20000)
                file_input = page.locator('ytcp-video-thumbnail-editor input[type="file"]').first
                _attach_file_via_cdp(page, file_input, thumb_path)
                time.sleep(2.0)

                save_btn = page.locator("ytcp-button#save, #save").first
                save_btn.wait_for(state="visible", timeout=15000)
                for _ in range(15):
                    disabled = (save_btn.get_attribute("disabled") is not None) or (
                        (save_btn.get_attribute("aria-disabled") or "false").lower() == "true"
                    )
                    if not disabled:
                        break
                    time.sleep(0.5)
                save_btn.click()
                time.sleep(2.5)
                updated.append({"video_id": vid, "thumbnail_path": str(thumb_path), "status": "updated"})
                if progress_callback:
                    progress_callback(f"  ✅ Capa salva em https://youtube.com/shorts/{vid}")
            except Exception as exc:
                updated.append({"video_id": vid, "thumbnail_path": str(thumb_path), "status": f"error: {exc}"})
                if progress_callback:
                    progress_callback(f"  ❌ Falha em {vid}: {exc}")
            finally:
                try:
                    page.close()
                except Exception:
                    pass

    return updated
