"""Automatic Wikipedia/Wikimedia image fetcher and styled B-roll card builder."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

USER_AGENT = "HardCleepsStudio/2.0 (https://github.com; desktop-broll-fetcher)"


def _slugify(term: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", term.strip())
    return re.sub(r"_+", "_", s).strip("_").lower()[:48] or "asset"


def _make_broll_card(src_img_path: Path, dst_png_path: Path, max_dim: int = 440) -> Path:
    """Style a downloaded image into a rounded RGBA B-roll card with subtle border & shadow."""
    img = Image.open(src_img_path).convert("RGBA")
    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    w, h = img.size

    # Rounded mask
    radius = max(18, min(w, h) // 10)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)

    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    card.paste(img, (0, 0), mask)

    # Subtle glowing purple/orange accent border
    border = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        [1, 1, w - 2, h - 2], radius=radius, outline=(255, 255, 255, 210), width=4
    )
    card = Image.alpha_composite(card, border)

    # Soft drop shadow canvas
    pad = 18
    canvas = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [pad, pad + 4, pad + w, pad + h + 4], radius=radius, fill=(0, 0, 0, 140)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(card, (pad, pad), card)
    canvas.save(dst_png_path, format="PNG")
    return dst_png_path


def fetch_wikipedia_image(term: str, cache_dir: Path) -> Path | None:
    """Fetch a Wikipedia summary thumbnail for `term` (PT then EN) and return styled RGBA PNG."""
    clean_term = term.strip()
    if len(clean_term) < 2:
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(clean_term)
    styled_png = cache_dir / f"{slug}_card.png"
    if styled_png.is_file() and styled_png.stat().st_size > 500:
        return styled_png

    raw_img = cache_dir / f"{slug}_raw.img"
    for lang in ("pt", "en"):
        encoded = urllib.parse.quote(clean_term.replace(" ", "_"))
        api_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
        req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            thumb = (data.get("thumbnail") or {}).get("source") or (data.get("originalimage") or {}).get("source")
            if not thumb:
                continue
            img_req = urllib.request.Request(thumb, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(img_req, timeout=8.0) as img_resp:
                raw_bytes = img_resp.read()
            if len(raw_bytes) < 500:
                continue
            raw_img.write_bytes(raw_bytes)
            _make_broll_card(raw_img, styled_png)
            raw_img.unlink(missing_ok=True)
            return styled_png
        except Exception:
            continue

    raw_img.unlink(missing_ok=True)
    return None


def prepare_broll_events_for_cut(
    entities: list[str],
    cut_words: list[dict[str, Any]],
    cut_start: float,
    cut_duration: float,
    cache_dir: Path,
    max_events: int = 3,
) -> list[dict[str, Any]]:
    """Match cited entities to relative word timestamps and fetch Wikipedia B-roll PNG cards."""
    if not entities or not cut_words or cut_duration < 8.0:
        return []

    events: list[dict[str, Any]] = []
    used_times: list[float] = []

    for ent in entities:
        if len(events) >= max_events:
            break
        ent_clean = str(ent).strip()
        if len(ent_clean) < 3:
            continue
        ent_tokens = [t.lower() for t in re.findall(r"[A-Za-zÀ-ÿ0-9]+", ent_clean) if len(t) >= 3]
        if not ent_tokens:
            continue

        # Find first occurrence of the entity in cut_words
        matched_rel: float | None = None
        for w in cut_words:
            w_tok = re.sub(r"[^A-Za-zÀ-ÿ0-9]+", "", str(w.get("word", "")).lower())
            if not w_tok:
                continue
            if w_tok == ent_tokens[0] or (len(ent_tokens[0]) >= 5 and ent_tokens[0] in w_tok):
                rel_t = float(w.get("start", cut_start)) - cut_start
                if 2.2 <= rel_t <= max(2.5, cut_duration - 2.2):
                    if all(abs(rel_t - ut) >= 4.5 for ut in used_times):
                        matched_rel = round(rel_t, 2)
                        break

        if matched_rel is None:
            continue

        card_path = fetch_wikipedia_image(ent_clean, cache_dir)
        if card_path and card_path.is_file():
            used_times.append(matched_rel)
            events.append(
                {
                    "entity": ent_clean,
                    "image_path": str(card_path),
                    "start": matched_rel,
                    "duration": 1.6,
                }
            )

    return events
