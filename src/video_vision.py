"""Lightweight OpenCV visual context helpers (Contact Sheets + Thumbnail loader) for multimodal LLM curation."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src import INPUT_DIR, PROJECTS_TEMP_DIR


def resolve_video_path(transcript_data: dict[str, Any], video_path: str | Path | None = None) -> Path | None:
    if video_path:
        p = Path(video_path)
        if p.is_file():
            return p
    vp = transcript_data.get("video_path")
    if vp and Path(str(vp)).is_file():
        return Path(str(vp))
    vf = transcript_data.get("video_file")
    if vf:
        cand = INPUT_DIR / str(vf)
        if cand.is_file():
            return cand
    return None


def _encode_jpeg_b64(bgr_or_path: np.ndarray | Path, max_w: int = 1280, quality: int = 80) -> str | None:
    if isinstance(bgr_or_path, Path):
        if not bgr_or_path.is_file():
            return None
        img = cv2.imread(str(bgr_or_path), cv2.IMREAD_COLOR)
    else:
        img = bgr_or_path
    if img is None:
        return None
    h, w = img.shape[:2]
    if w > max_w:
        nh = max(2, int(round(h * (max_w / w))))
        img = cv2.resize(img, (max_w, nh), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def load_video_context_meta(transcript_data: dict[str, Any], vpath: Path | None) -> dict[str, Any]:
    """Load saved YouTube title/description/thumbnail if available in temp/projects/<stem>/."""
    fallback_title = str(transcript_data.get("video_file") or (vpath.name if vpath else "video.mp4"))
    meta: dict[str, Any] = {
        "title": Path(fallback_title).stem.replace("_", " "),
        "channel": "",
        "description": "",
        "tags": [],
        "thumb_b64": None,
    }
    if vpath is None:
        return meta

    proj_dir = PROJECTS_TEMP_DIR / vpath.stem
    meta_file = proj_dir / "video_meta.json"
    if meta_file.is_file():
        try:
            saved = json.loads(meta_file.read_text(encoding="utf-8"))
            if saved.get("title"):
                meta["title"] = str(saved["title"])
            if saved.get("channel"):
                meta["channel"] = str(saved["channel"])
            if saved.get("description"):
                meta["description"] = str(saved["description"])[:600]
            if isinstance(saved.get("tags"), list):
                meta["tags"] = [str(t) for t in saved["tags"][:12]]
        except Exception:
            pass

    thumb_file = proj_dir / "source_thumb.jpg"
    if thumb_file.is_file():
        meta["thumb_b64"] = _encode_jpeg_b64(thumb_file, max_w=720, quality=80)

    return meta


def build_contact_sheet_b64(
    vpath: Path,
    start_sec: float,
    end_sec: float,
    grid_cols: int = 4,
    grid_rows: int = 4,
    tile_w: int = 320,
    tile_h: int = 180,
) -> str | None:
    """Build a 4x4 timestamped JPEG contact sheet across [start_sec, end_sec] in <1s."""
    if not vpath.is_file():
        return None

    cap = cv2.VideoCapture(str(vpath))
    if not cap.isOpened():
        return None

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        dur = total_frames / max(1.0, fps)
        s0 = max(0.0, float(start_sec))
        s1 = min(dur - 0.2 if dur > 1.0 else dur, float(end_sec))
        if s1 <= s0:
            return None

        n_tiles = grid_cols * grid_rows
        times = np.linspace(s0 + 1.0, max(s0 + 1.0, s1 - 1.0), num=n_tiles)
        canvas = np.zeros((grid_rows * tile_h, grid_cols * tile_w, 3), dtype=np.uint8)

        for idx, t in enumerate(times):
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(float(t) * fps))))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            tile = cv2.resize(frame, (tile_w, tile_h), interpolation=cv2.INTER_AREA)

            mm = int(t // 60)
            ss = int(t % 60)
            label = f"{mm:02d}:{ss:02d} ({int(t)}s)"
            cv2.rectangle(tile, (4, 4), (150, 26), (0, 0, 0), -1)
            cv2.putText(
                tile,
                label,
                (8, 21),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (0, 235, 255),
                1,
                cv2.LINE_AA,
            )

            r = idx // grid_cols
            c = idx % grid_cols
            canvas[r * tile_h : (r + 1) * tile_h, c * tile_w : (c + 1) * tile_w] = tile

        return _encode_jpeg_b64(canvas, max_w=grid_cols * tile_w, quality=78)
    finally:
        cap.release()
