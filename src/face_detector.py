"""Computer vision facecam detection and 9:16 smart crop calculation (MediaPipe + OpenCV)."""

from __future__ import annotations

import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src import MODELS_TEMP_DIR, TEMP_DIR

BLAZEFACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
)


@dataclass
class FaceCropResult:
    detected: bool
    mode: str  # "split_screen", "blur_bg", "center_only"
    detector_backend: str
    frame_width: int
    frame_height: int
    face_crop: dict[str, int] | None  # {"x": int, "y": int, "w": int, "h": int}
    gameplay_crop: dict[str, int]     # {"x": int, "y": int, "w": int, "h": int}
    confidence: float
    detections_count: int
    samples_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _even(n: int) -> int:
    return max(2, int(n) - (int(n) % 2))


def _even_offset(n: int) -> int:
    return max(0, int(n) - (int(n) % 2))


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


def _compute_gameplay_crop(frame_w: int, frame_h: int, target_w: int, target_h: int) -> dict[str, int]:
    """Compute center crop of source frame matching target_w:target_h aspect ratio."""
    target_ar = target_w / float(target_h)
    src_ar = frame_w / float(frame_h)

    if src_ar > target_ar:
        crop_h = _even(frame_h)
        crop_w = _even(int(round(crop_h * target_ar)))
    else:
        crop_w = _even(frame_w)
        crop_h = _even(int(round(crop_w / target_ar)))

    crop_w = min(crop_w, _even(frame_w))
    crop_h = min(crop_h, _even(frame_h))
    x = _even_offset((frame_w - crop_w) // 2)
    y = _even_offset((frame_h - crop_h) // 2)
    return {"x": x, "y": y, "w": crop_w, "h": crop_h}


def _preset_corner_crop(frame_w: int, frame_h: int, corner: str) -> dict[str, int]:
    """Return fixed corner webcam crop in 1080:640 (1.6875:1) proportion."""
    target_ar = 1080.0 / 640.0
    crop_w = _even(int(round(frame_w * 0.30)))
    crop_h = _even(int(round(crop_w / target_ar)))
    if crop_h > frame_h // 2:
        crop_h = _even(frame_h // 2)
        crop_w = _even(int(round(crop_h * target_ar)))

    pad_x = _even(int(frame_w * 0.015))
    pad_y = _even(int(frame_h * 0.02))

    if corner == "top_left":
        x, y = pad_x, pad_y
    elif corner == "top_right":
        x, y = frame_w - crop_w - pad_x, pad_y
    elif corner == "mid_left":
        x, y = pad_x, (frame_h - crop_h) // 2
    elif corner == "mid_right":
        x, y = frame_w - crop_w - pad_x, (frame_h - crop_h) // 2
    elif corner == "bottom_left":
        x, y = pad_x, frame_h - crop_h - pad_y
    else:  # bottom_right
        x, y = frame_w - crop_w - pad_x, frame_h - crop_h - pad_y

    x = _clamp(_even(x), 0, max(0, frame_w - crop_w))
    y = _clamp(_even(y), 0, max(0, frame_h - crop_h))
    return {"x": x, "y": y, "w": crop_w, "h": crop_h}


class FacecamDetector:
    """Detects stationary streamer facecam using MediaPipe (or OpenCV fallback)."""

    def __init__(self, min_confidence: float = 0.5) -> None:
        self.min_confidence = min_confidence
        self._backend_name = "none"
        self._mp_solutions_detector = None
        self._mp_tasks_detector = None
        self._haar_cascades: list[cv2.CascadeClassifier] = []
        self._init_detector()

    def _init_detector(self) -> None:
        # 1. Try classic mediapipe.solutions.face_detection
        try:
            import mediapipe as mp

            if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_detection"):
                self._mp_solutions_detector = mp.solutions.face_detection.FaceDetection(
                    model_selection=1,
                    min_detection_confidence=self.min_confidence,
                )
                self._backend_name = "mediapipe.solutions"
                return
        except Exception:
            pass

        # 2. Try MediaPipe Tasks Vision FaceDetector with local/cached BlazeFace tflite
        try:
            from mediapipe.tasks import python as mp_tasks
            from mediapipe.tasks.python import vision as mp_vision

            MODELS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
            model_path = MODELS_TEMP_DIR / "blaze_face_short_range.tflite"
            if not model_path.is_file():
                try:
                    urllib.request.urlretrieve(BLAZEFACE_MODEL_URL, str(model_path))
                except Exception:
                    pass

            if model_path.is_file():
                base_options = mp_tasks.BaseOptions(model_asset_path=str(model_path))
                options = mp_vision.FaceDetectorOptions(
                    base_options=base_options,
                    min_detection_confidence=self.min_confidence,
                )
                self._mp_tasks_detector = mp_vision.FaceDetector.create_from_options(options)
                self._backend_name = "mediapipe.tasks"
                return
        except Exception:
            pass

        # 3. Fallback: OpenCV Haar Cascades bundled with opencv-python
        for xml_name in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml"):
            xml_path = Path(cv2.data.haarcascades) / xml_name
            if xml_path.is_file():
                clf = cv2.CascadeClassifier(str(xml_path))
                if not clf.empty():
                    self._haar_cascades.append(clf)

        self._backend_name = "opencv.haar" if self._haar_cascades else "none"

    def _detect_faces_in_frame(self, bgr_frame: np.ndarray) -> list[tuple[float, float, float, float, float]]:
        """Return list of normalized detections: (cx, cy, bw, bh, score)."""
        h, w = bgr_frame.shape[:2]
        if h == 0 or w == 0:
            return []

        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        detections: list[tuple[float, float, float, float, float]] = []

        if self._mp_solutions_detector is not None:
            res = self._mp_solutions_detector.process(rgb)
            if res and res.detections:
                for det in res.detections:
                    box = det.location_data.relative_bounding_box
                    bw = float(box.width)
                    bh = float(box.height)
                    cx = float(box.xmin) + bw * 0.5
                    cy = float(box.ymin) + bh * 0.5
                    score = float(det.score[0]) if det.score else 0.7
                    if 0.02 <= bw <= 0.65 and 0.02 <= bh <= 0.65:
                        detections.append((cx, cy, bw, bh, score))
            return detections

        if self._mp_tasks_detector is not None:
            import mediapipe as mp

            def _run_tasks(rgb_crop: np.ndarray, offset_x: int, offset_y: int, min_score: float) -> list[tuple[float, float, float, float, float]]:
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_crop)
                res = self._mp_tasks_detector.detect(mp_img)
                found: list[tuple[float, float, float, float, float]] = []
                if res and res.detections:
                    for det in res.detections:
                        bb = det.bounding_box
                        score = float(det.categories[0].score) if det.categories else 0.75
                        if score < min_score:
                            continue
                        bw = bb.width / float(w)
                        bh = bb.height / float(h)
                        cx = (offset_x + bb.origin_x + bb.width * 0.5) / float(w)
                        cy = (offset_y + bb.origin_y + bb.height * 0.5) / float(h)
                        if 0.02 <= bw <= 0.65 and 0.02 <= bh <= 0.65:
                            found.append((cx, cy, bw, bh, score))
                return found

            detections = _run_tasks(rgb, 0, 0, self.min_confidence)
            if not any(d[4] >= 0.65 for d in detections):
                tiles = [
                    (0, 0, int(w * 0.42), int(h * 0.55)),
                    (int(w * 0.58), 0, w - int(w * 0.58), int(h * 0.55)),
                    (0, int(h * 0.15), int(w * 0.42), int(h * 0.60)),
                    (int(w * 0.58), int(h * 0.15), w - int(w * 0.58), int(h * 0.60)),
                    (0, int(h * 0.45), int(w * 0.42), h - int(h * 0.45)),
                    (int(w * 0.58), int(h * 0.45), w - int(w * 0.58), h - int(h * 0.45)),
                ]
                tile_dets: list[tuple[float, float, float, float, float]] = []
                for tx, ty, tw, th in tiles:
                    if tw < 64 or th < 64:
                        continue
                    sub = np.ascontiguousarray(rgb[ty : ty + th, tx : tx + tw])
                    tile_dets.extend(_run_tasks(sub, tx, ty, 0.60))

                # Deduplicate overlapping tile hits keeping highest confidence
                tile_dets.sort(key=lambda d: d[4], reverse=True)
                for cand in tile_dets:
                    if not any(((cand[0] - ex[0]) ** 2 + (cand[1] - ex[1]) ** 2) ** 0.5 <= 0.06 for ex in detections):
                        detections.append(cand)
            return detections

        if self._haar_cascades:
            gray = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2GRAY)
            for clf in self._haar_cascades:
                boxes = clf.detectMultiScale(
                    gray,
                    scaleFactor=1.15,
                    minNeighbors=5,
                    minSize=(max(28, w // 25), max(28, h // 25)),
                )
                for (x, y, bw_px, bh_px) in boxes:
                    bw = bw_px / float(w)
                    bh = bh_px / float(h)
                    cx = (x + bw_px * 0.5) / float(w)
                    cy = (y + bh_px * 0.5) / float(h)
                    if 0.02 <= bw <= 0.55 and 0.02 <= bh <= 0.55:
                        detections.append((cx, cy, bw, bh, 0.7))
                if detections:
                    break

        return detections

    def detect_facecam(
        self,
        video_path: str | Path,
        start: float = 0.0,
        end: float | None = None,
        layout_mode: str = "auto",
        num_samples: int = 12,
        face_target: str = "auto",
    ) -> FaceCropResult:
        """Analyze frames in [start, end] to locate stationary streamer facecam."""
        vpath = Path(video_path)
        if not vpath.is_file():
            raise FileNotFoundError(f"Vídeo não encontrado: {vpath}")

        cap = cv2.VideoCapture(str(vpath))
        if not cap.isOpened():
            raise RuntimeError(f"Não foi possível abrir o vídeo com OpenCV: {vpath}")

        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
            frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
            total_dur = total_frames / fps if fps > 0 else 0.0
            t_start = max(0.0, start)
            t_end = min(total_dur, end) if (end is not None and total_dur > 0) else total_dur
            if t_end <= t_start:
                t_end = max(t_start + 1.0, total_dur)

            mode_norm = layout_mode.lower().strip()
            if mode_norm in ("top_left", "top_right", "mid_left", "mid_right", "bottom_left", "bottom_right"):
                return FaceCropResult(
                    detected=True,
                    mode="split_screen",
                    detector_backend=f"manual:{mode_norm}",
                    frame_width=frame_w,
                    frame_height=frame_h,
                    face_crop=_preset_corner_crop(frame_w, frame_h, mode_norm),
                    gameplay_crop=_compute_gameplay_crop(frame_w, frame_h, 1080, 1280),
                    confidence=1.0,
                    detections_count=1,
                    samples_count=1,
                )

            if mode_norm == "center_only":
                return FaceCropResult(
                    detected=False,
                    mode="center_only",
                    detector_backend="manual:center_only",
                    frame_width=frame_w,
                    frame_height=frame_h,
                    face_crop=None,
                    gameplay_crop=_compute_gameplay_crop(frame_w, frame_h, 1080, 1920),
                    confidence=0.0,
                    detections_count=0,
                    samples_count=0,
                )

            if mode_norm == "blur_bg":
                return FaceCropResult(
                    detected=False,
                    mode="blur_bg",
                    detector_backend="manual:blur_bg",
                    frame_width=frame_w,
                    frame_height=frame_h,
                    face_crop=None,
                    gameplay_crop={"x": 0, "y": 0, "w": _even(frame_w), "h": _even(frame_h)},
                    confidence=0.0,
                    detections_count=0,
                    samples_count=0,
                )

            # Automatic detection across sampled timestamps
            times = np.linspace(t_start, max(t_start, t_end - 0.1), num=max(3, num_samples))
            all_dets: list[tuple[float, float, float, float, float]] = []
            for t in times:
                frame_idx = min(max(0, total_frames - 1), int(round(float(t) * fps)))
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ok, frame = cap.read()
                if ok and frame is not None:
                    all_dets.extend(self._detect_faces_in_frame(frame))

            if not all_dets:
                return FaceCropResult(
                    detected=False,
                    mode="blur_bg",
                    detector_backend=self._backend_name,
                    frame_width=frame_w,
                    frame_height=frame_h,
                    face_crop=None,
                    gameplay_crop={"x": 0, "y": 0, "w": _even(frame_w), "h": _even(frame_h)},
                    confidence=0.0,
                    detections_count=0,
                    samples_count=len(times),
                )

            # Spatial clustering: stationary facecams remain in the same location across frames
            clusters: list[list[tuple[float, float, float, float, float]]] = []
            for det in all_dets:
                placed = False
                for cl in clusters:
                    ref = cl[0]
                    dist = ((det[0] - ref[0]) ** 2 + (det[1] - ref[1]) ** 2) ** 0.5
                    if dist <= 0.08:
                        cl.append(det)
                        placed = True
                        break
                if not placed:
                    clusters.append([det])

            def _cluster_rank(cl: list[tuple[float, float, float, float, float]]) -> float:
                med_x = float(np.median([d[0] for d in cl]))
                med_y = float(np.median([d[1] for d in cl]))
                is_edge_or_corner = (med_x < 0.35 or med_x > 0.65) or (med_y < 0.35 or med_y > 0.65)
                edge_bonus = 1.35 if is_edge_or_corner else 1.0
                return len(cl) * edge_bonus

            clusters.sort(key=_cluster_rank, reverse=True)
            best_cluster = clusters[0]
            min_hits = max(2, int(len(times) * 0.25))

            if face_target in ("left", "right") and len(clusters) > 1:
                valid_clusters = [c for c in clusters if len(c) >= min_hits] or [best_cluster]
                # Filter to clusters near the primary webcam corner
                ref_x = float(np.median([d[0] for d in best_cluster]))
                ref_y = float(np.median([d[1] for d in best_cluster]))
                nearby = [
                    c for c in valid_clusters
                    if abs(float(np.median([d[1] for d in c])) - ref_y) <= 0.16
                    and abs(float(np.median([d[0] for d in c])) - ref_x) <= 0.25
                ]
                if nearby:
                    best_cluster = (
                        max(nearby, key=lambda c: float(np.median([d[0] for d in c])))
                        if face_target == "right"
                        else min(nearby, key=lambda c: float(np.median([d[0] for d in c])))
                    )

            if len(best_cluster) < min_hits:
                return FaceCropResult(
                    detected=False,
                    mode="blur_bg",
                    detector_backend=self._backend_name,
                    frame_width=frame_w,
                    frame_height=frame_h,
                    face_crop=None,
                    gameplay_crop={"x": 0, "y": 0, "w": _even(frame_w), "h": _even(frame_h)},
                    confidence=0.0,
                    detections_count=len(best_cluster),
                    samples_count=len(times),
                )

            cx = float(np.median([d[0] for d in best_cluster]))
            cy = float(np.median([d[1] for d in best_cluster]))
            bw = float(np.median([d[2] for d in best_cluster]))
            bh = float(np.median([d[3] for d in best_cluster]))
            conf = float(np.mean([d[4] for d in best_cluster]))

            use_classic_split = mode_norm == "split_screen"
            if use_classic_split:
                target_ar = 1080.0 / 640.0
                crop_h_px = _even(_clamp(int(round(bh * frame_h * 1.90)), int(frame_h * 0.18), int(frame_h * 0.48)))
                crop_w_px = _even(int(round(crop_h_px * target_ar)))
                if crop_w_px > frame_w:
                    crop_w_px = _even(frame_w)
                    crop_h_px = _even(int(round(crop_w_px / target_ar)))
            else:
                # Square 1:1 crop for circular facecam PiP (pip_split)
                crop_size = _even(_clamp(int(round(bh * frame_h * 2.05)), int(frame_h * 0.18), int(frame_h * 0.48)))
                crop_size = _even(min(crop_size, frame_w, frame_h))
                crop_w_px = crop_size
                crop_h_px = crop_size

            center_x_px = int(round(cx * frame_w))
            center_y_px = int(round((cy + bh * 0.08) * frame_h))

            x = _clamp(_even_offset(center_x_px - crop_w_px // 2), 0, max(0, frame_w - crop_w_px))
            y = _clamp(_even_offset(center_y_px - crop_h_px // 2), 0, max(0, frame_h - crop_h_px))

            out_mode = "split_screen" if use_classic_split else "pip_split"
            bot_h = 1280 if use_classic_split else 1312
            return FaceCropResult(
                detected=True,
                mode=out_mode,
                detector_backend=self._backend_name,
                frame_width=frame_w,
                frame_height=frame_h,
                face_crop={"x": x, "y": y, "w": crop_w_px, "h": crop_h_px},
                gameplay_crop=_compute_gameplay_crop(frame_w, frame_h, 1080, bot_h),
                confidence=round(conf, 3),
                detections_count=len(best_cluster),
                samples_count=len(times),
            )
        finally:
            cap.release()


def generate_layout_preview(
    video_path: str | Path,
    timestamp: float = 2.0,
    layout_mode: str = "auto",
    output_path: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Render a 1080x1920 preview JPEG showing how the 9:16 crop will look."""
    vpath = Path(video_path)
    detector = FacecamDetector()
    res = detector.detect_facecam(
        vpath,
        start=max(0.0, timestamp - 2.0),
        end=timestamp + 4.0,
        layout_mode=layout_mode,
        num_samples=8,
    )

    cap = cv2.VideoCapture(str(vpath))
    if not cap.isOpened():
        raise RuntimeError(f"Erro ao abrir vídeo para preview: {vpath}")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
        frame_idx = min(max(0, total_frames - 1), int(round(timestamp * fps)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("Não foi possível ler frame para preview.")
    finally:
        cap.release()

    if res.mode == "pip_split" and res.face_crop:
        fc = res.face_crop
        gc = res.gameplay_crop
        top_img = cv2.resize(frame, (1080, 608), interpolation=cv2.INTER_AREA)
        bot_roi = frame[gc["y"] : gc["y"] + gc["h"], gc["x"] : gc["x"] + gc["w"]]
        bot_img = cv2.resize(bot_roi, (1080, 1312), interpolation=cv2.INTER_AREA)
        canvas = np.vstack([top_img, bot_img])
        cv2.rectangle(canvas, (0, 606), (1080, 610), (0, 230, 255), -1)

        # Circular facecam PiP straddling the split seam on the right
        pip_size = 340
        side = min(fc["w"], fc["h"])
        fx0 = fc["x"] + (fc["w"] - side) // 2
        fy0 = fc["y"] + (fc["h"] - side) // 2
        face_roi = frame[fy0 : fy0 + side, fx0 : fx0 + side]
        face_sq = cv2.resize(face_roi, (pip_size, pip_size), interpolation=cv2.INTER_AREA)

        mask = np.zeros((pip_size, pip_size), dtype=np.float32)
        cv2.circle(mask, (pip_size // 2, pip_size // 2), pip_size // 2 - 4, 1.0, -1, cv2.LINE_AA)
        mask_3 = np.repeat(mask[:, :, None], 3, axis=2)

        px, py = 1080 - pip_size - 44, 608 - pip_size // 2
        bg_patch = canvas[py : py + pip_size, px : px + pip_size].astype(np.float32)
        blended = (face_sq.astype(np.float32) * mask_3 + bg_patch * (1.0 - mask_3)).astype(np.uint8)
        canvas[py : py + pip_size, px : px + pip_size] = blended
        cv2.circle(canvas, (px + pip_size // 2, py + pip_size // 2), pip_size // 2 - 3, (0, 230, 255), 5, cv2.LINE_AA)
    elif res.mode == "split_screen" and res.face_crop:
        fc = res.face_crop
        gc = res.gameplay_crop
        top_roi = frame[fc["y"] : fc["y"] + fc["h"], fc["x"] : fc["x"] + fc["w"]]
        bot_roi = frame[gc["y"] : gc["y"] + gc["h"], gc["x"] : gc["x"] + gc["w"]]
        top_img = cv2.resize(top_roi, (1080, 640), interpolation=cv2.INTER_AREA)
        bot_img = cv2.resize(bot_roi, (1080, 1280), interpolation=cv2.INTER_AREA)
        canvas = np.vstack([top_img, bot_img])
        # Subtle neon divider bar
        cv2.rectangle(canvas, (0, 636), (1080, 644), (0, 230, 255), -1)
    elif res.mode == "center_only":
        gc = res.gameplay_crop
        roi = frame[gc["y"] : gc["y"] + gc["h"], gc["x"] : gc["x"] + gc["w"]]
        canvas = cv2.resize(roi, (1080, 1920), interpolation=cv2.INTER_AREA)
    else:
        # Blur background + sharp centered 16:9 gameplay
        bg_crop = _compute_gameplay_crop(res.frame_width, res.frame_h, 1080, 1920)
        bg_roi = frame[bg_crop["y"] : bg_crop["y"] + bg_crop["h"], bg_crop["x"] : bg_crop["x"] + bg_crop["w"]]
        bg_img = cv2.resize(bg_roi, (1080, 1920), interpolation=cv2.INTER_LINEAR)
        bg_img = cv2.GaussianBlur(bg_img, (51, 51), 0)
        bg_img = (bg_img * 0.55).astype(np.uint8)

        fg_h = _even(int(round(1080 * (res.frame_height / max(1, res.frame_width)))))
        fg_img = cv2.resize(frame, (1080, fg_h), interpolation=cv2.INTER_AREA)
        y0 = (1920 - fg_h) // 2
        bg_img[y0 : y0 + fg_h, 0:1080] = fg_img
        canvas = bg_img

    out_file = Path(output_path or (TEMP_DIR / "layout_preview.jpg"))
    out_file.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_file), canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    return str(out_file), res.to_dict()
