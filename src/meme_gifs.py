"""Giphy API meme fetcher and local cache for caricature Shorts reaction overlays."""

from __future__ import annotations

import json
import os
import random
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src import PROJECT_ROOT
from src.llm_pool import load_env_file

MEME_GIFS_DIR = PROJECT_ROOT / "assets" / "meme_gifs"
MANIFEST_FILE = MEME_GIFS_DIR / "manifest.json"

MEME_KEYWORDS: list[str] = [
    "wtf",
    "shocked",
    "panic",
    "mindblown",
    "rage",
    "crying",
    "cringe",
    "facepalm",
    "sus",
    "sneaky",
    "horny",
    "evil laugh",
    "hype",
    "smug",
    "laughing",
    "clown",
]


def _slug(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", term.strip().lower()).strip("_")


def _get_giphy_key() -> str:
    load_env_file()
    for k, v in os.environ.items():
        if k.upper() in ("GIPHY_API_KEY", "GIPHY_KEY") and v.strip():
            return v.strip()
    raise RuntimeError("GIPHY_API_KEY não encontrada no .env.")


def fetch_giphy_pack(per_keyword: int = 3, keywords: list[str] | None = None) -> dict[str, list[dict[str, str]]]:
    """Download `per_keyword` GIFs from Giphy for each sentiment keyword into assets/meme_gifs/."""
    api_key = _get_giphy_key()
    MEME_GIFS_DIR.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, list[dict[str, str]]] = {}
    if MANIFEST_FILE.is_file():
        try:
            loaded = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
        except Exception:
            manifest = {}

    target_words = keywords or MEME_KEYWORDS
    for kw in target_words:
        slug = _slug(kw)
        kw_dir = MEME_GIFS_DIR / slug
        kw_dir.mkdir(parents=True, exist_ok=True)

        existing = [
            it for it in manifest.get(slug, []) if (PROJECT_ROOT / it.get("path", "")).is_file()
        ]
        if len(existing) >= per_keyword:
            manifest[slug] = existing[:per_keyword]
            continue

        q = urllib.parse.quote(kw)
        url = (
            f"https://api.giphy.com/v1/gifs/search"
            f"?api_key={urllib.parse.quote(api_key)}&q={q}&limit=8&rating=pg-13&lang=en"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "HardCleepsStudio/2.0"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))

        items = payload.get("data") or []
        saved_list: list[dict[str, str]] = []
        for idx, item in enumerate(items, start=1):
            if len(saved_list) >= per_keyword:
                break
            images = item.get("images") or {}
            chosen = (
                images.get("fixed_height")
                or images.get("downsized_medium")
                or images.get("downsized")
                or {}
            )
            gif_url = str(chosen.get("url") or "").strip()
            if not gif_url:
                continue
            dst_gif = kw_dir / f"meme_{len(saved_list) + 1}.gif"
            try:
                g_req = urllib.request.Request(gif_url, headers={"User-Agent": "HardCleepsStudio/2.0"})
                with urllib.request.urlopen(g_req, timeout=12.0) as g_resp:
                    raw = g_resp.read()
                if len(raw) < 1000:
                    continue
                dst_gif.write_bytes(raw)
                saved_list.append(
                    {
                        "id": str(item.get("id") or ""),
                        "title": str(item.get("title") or kw)[:80],
                        "path": dst_gif.relative_to(PROJECT_ROOT).as_posix(),
                    }
                )
            except Exception:
                continue

        manifest[slug] = saved_list
        print(f"[Giphy] {kw} -> {len(saved_list)} GIF(s)")

    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def pick_meme_gif(sentiment: str) -> Path | None:
    """Pick a cached meme GIF matching a sentiment keyword."""
    slug = _slug(sentiment)
    kw_dir = MEME_GIFS_DIR / slug
    if not kw_dir.is_dir():
        return None
    gifs = sorted(kw_dir.glob("*.gif"))
    if not gifs:
        return None
    return random.choice(gifs)


def list_meme_pack() -> dict[str, Any]:
    """Return all 16 sentiment folders and their currently saved GIFs for UI selection."""
    manifest: dict[str, list[dict[str, str]]] = {}
    if MANIFEST_FILE.is_file():
        try:
            loaded = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
        except Exception:
            manifest = {}

    sentiments: list[dict[str, Any]] = []
    for kw in MEME_KEYWORDS:
        slug = _slug(kw)
        kw_dir = MEME_GIFS_DIR / slug
        meta_by_path = {it.get("path", ""): it for it in manifest.get(slug, []) if isinstance(it, dict)}
        items: list[dict[str, str]] = []
        if kw_dir.is_dir():
            for gf in sorted(kw_dir.glob("*.gif")):
                rel = gf.relative_to(PROJECT_ROOT).as_posix()
                m = meta_by_path.get(rel, {})
                items.append(
                    {
                        "filename": gf.name,
                        "title": str(m.get("title") or gf.stem),
                        "url": f"/api/memes/file/{slug}/{gf.name}",
                    }
                )
        sentiments.append({"keyword": kw, "slug": slug, "items": items})
    return {"sentiments": sentiments}


def search_giphy_candidates(query: str, limit: int = 12) -> list[dict[str, str]]:
    """Search Giphy and return preview/download URLs without saving locally yet."""
    api_key = _get_giphy_key()
    q = urllib.parse.quote(query.strip() or "meme")
    url = (
        f"https://api.giphy.com/v1/gifs/search"
        f"?api_key={urllib.parse.quote(api_key)}&q={q}&limit={max(1, min(24, limit))}&rating=pg-13"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "HardCleepsStudio/2.0"})
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))

    out: list[dict[str, str]] = []
    for item in payload.get("data") or []:
        images = item.get("images") or {}
        preview = images.get("fixed_height_small") or images.get("fixed_height") or {}
        full = images.get("fixed_height") or images.get("downsized_medium") or preview
        p_url = str(preview.get("url") or "").strip()
        f_url = str(full.get("url") or "").strip()
        if p_url and f_url:
            out.append(
                {
                    "id": str(item.get("id") or ""),
                    "title": str(item.get("title") or query)[:80],
                    "preview_url": p_url,
                    "gif_url": f_url,
                }
            )
    return out


def save_chosen_giphy(sentiment: str, gif_url: str, giphy_id: str = "", title: str = "") -> dict[str, str]:
    """Download a user-selected Giphy GIF into the sentiment folder."""
    slug = _slug(sentiment)
    kw_dir = MEME_GIFS_DIR / slug
    kw_dir.mkdir(parents=True, exist_ok=True)

    existing_nums = []
    for gf in kw_dir.glob("meme_*.gif"):
        m = re.match(r"meme_(\d+)\.gif$", gf.name)
        if m:
            existing_nums.append(int(m.group(1)))
    next_idx = (max(existing_nums) + 1) if existing_nums else 1
    dst_gif = kw_dir / f"meme_{next_idx}.gif"

    req = urllib.request.Request(gif_url, headers={"User-Agent": "HardCleepsStudio/2.0"})
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        raw = resp.read()
    if len(raw) < 500:
        raise ValueError("GIF inválido retornado pelo Giphy.")
    dst_gif.write_bytes(raw)

    manifest: dict[str, list[dict[str, str]]] = {}
    if MANIFEST_FILE.is_file():
        try:
            manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    entry = {
        "id": giphy_id,
        "title": title[:80] or sentiment,
        "path": dst_gif.relative_to(PROJECT_ROOT).as_posix(),
    }
    manifest.setdefault(slug, []).append(entry)
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"filename": dst_gif.name, "url": f"/api/memes/file/{slug}/{dst_gif.name}", "title": entry["title"]}


def delete_meme_gif(slug: str, filename: str) -> None:
    """Delete a saved meme GIF from a sentiment folder."""
    safe_slug = _slug(slug)
    safe_name = Path(filename).name
    target = MEME_GIFS_DIR / safe_slug / safe_name
    if target.is_file():
        target.unlink()
    if MANIFEST_FILE.is_file():
        try:
            manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
            if isinstance(manifest, dict) and safe_slug in manifest:
                manifest[safe_slug] = [
                    it for it in manifest[safe_slug] if Path(it.get("path", "")).name != safe_name
                ]
                MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    res = fetch_giphy_pack(per_keyword=3)
    total = sum(len(v) for v in res.values())
    print(f"Concluído: {len(res)} sentimentos, {total} GIFs salvos em {MEME_GIFS_DIR}.")
