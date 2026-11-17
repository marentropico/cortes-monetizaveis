"""OpenCV Zoo YuNet + SFace dynamic face pinning and tracking for circular PiP."""

from __future__ import annotations

import json
import random
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src import MODELS_TEMP_DIR, PROJECTS_TEMP_DIR, TEMP_DIR

YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
SFACE_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)

YUNET_PATH = MODELS_TEMP_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_PATH = MODELS_TEMP_DIR / "face_recognition_sface_2021dec.onnx"


def _even(n: int) -> int:
    return max(2, n - (n % 2))


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def ensure_tracker_models() -> tuple[Path, Path]:
    """Download YuNet and SFace ONNX models to temp/models/ if missing."""
    MODELS_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    for url, dst in ((YUNET_URL, YUNET_PATH), (SFACE_URL, SFACE_PATH)):
        if not dst.is_file() or dst.stat().st_size < 100_000:
            urllib.request.urlretrieve(url, str(dst))
    return YUNET_PATH, SFACE_PATH


def _create_models(input_w: int, input_h: int) -> tuple[Any, Any]:
    yunet_p, sface_p = ensure_tracker_models()
    detector = cv2.FaceDetectorYN.create(
        str(yunet_p),
        "",
        (input_w, input_h),
        score_threshold=0.52,
        nms_threshold=0.3,
        top_k=20,
    )
    recognizer = cv2.FaceRecognizerSF.create(str(sface_p), "")
    return detector, recognizer


def _pinned_dir(video_path: str | Path) -> Path:
    return PROJECTS_TEMP_DIR / Path(video_path).stem


def get_pinned_face(video_path: str | Path) -> dict[str, Any] | None:
    p = _pinned_dir(video_path) / "pinned_face.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_pinned_face(video_path: str | Path) -> None:
    d = _pinned_dir(video_path)
    for name in ("pinned_face.json", "pinned_face.jpg"):
        f = d / name
        if f.is_file():
            f.unlink(missing_ok=True)


def extract_frame_for_pin(video_path: str | Path, timestamp: float = 10.0) -> dict[str, Any]:
    """Extract a frame and detect all candidate faces for UI click-to-pin."""
    vpath = Path(video_path)
    cap = cv2.VideoCapture(str(vpath))
    if not cap.isOpened():
        raise RuntimeError(f"Não foi possível abrir o vídeo: {vpath}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total / max(1.0, fps)
        ts = max(0.0, min(float(timestamp), max(0.0, duration - 0.2)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(ts * fps)))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("Falha ao ler frame do vídeo.")
    finally:
        cap.release()

    h, w = frame.shape[:2]
    detector, _ = _create_models(w, h)
    _, faces = detector.detect(frame)

    boxes: list[dict[str, float]] = []
    if faces is not None:
        for row in faces:
            fx, fy, fw, fh = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            boxes.append(
                {
                    "x": round(fx / w, 4),
                    "y": round(fy / h, 4),
                    "w": round(fw / w, 4),
                    "h": round(fh / h, 4),
                    "cx": round((fx + fw / 2.0) / w, 4),
                    "cy": round((fy + fh / 2.0) / h, 4),
                    "score": round(float(row[-1]), 3),
                }
            )

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    out_jpg = TEMP_DIR / "pin_frame.jpg"
    cv2.imwrite(str(out_jpg), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])

    return {
        "frame_path": str(out_jpg),
        "timestamp": round(ts, 2),
        "duration": round(duration, 2),
        "width": w,
        "height": h,
        "faces": boxes,
    }


def pin_face_from_frame(
    video_path: str | Path,
    timestamp: float,
    norm_x: float,
    norm_y: float,
) -> dict[str, Any]:
    """Pin the streamer's face nearest to (norm_x, norm_y) at timestamp using SFace."""
    vpath = Path(video_path)
    cap = cv2.VideoCapture(str(vpath))
    if not cap.isOpened():
        raise RuntimeError(f"Não foi possível abrir o vídeo: {vpath}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(timestamp * fps))))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("Falha ao ler frame para pin.")
    finally:
        cap.release()

    h, w = frame.shape[:2]
    detector, recognizer = _create_models(w, h)
    _, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        raise ValueError("Nenhum rosto detectado nesse momento do vídeo. Avance para outro frame.")

    px, py = norm_x * w, norm_y * h
    best_row = None
    best_dist = float("inf")
    for row in faces:
        fx, fy, fw, fh = float(row[0]), float(row[1]), float(row[2]), float(row[3])
        cx, cy = fx + fw / 2.0, fy + fh / 2.0
        inside = fx <= px <= fx + fw and fy <= py <= fy + fh
        dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
        if inside:
            dist *= 0.25
        if dist < best_dist:
            best_dist = dist
            best_row = row

    assert best_row is not None
    aligned = recognizer.alignCrop(frame, best_row)
    feat = recognizer.feature(aligned)

    fx, fy, fw, fh = [int(round(float(v))) for v in best_row[:4]]
    pad = int(round(max(fw, fh) * 0.35))
    x0, y0 = max(0, fx - pad), max(0, fy - pad)
    x1, y1 = min(w, fx + fw + pad), min(h, fy + fh + pad)

    pdir = _pinned_dir(vpath)
    pdir.mkdir(parents=True, exist_ok=True)
    thumb_path = pdir / "pinned_face.jpg"
    cv2.imwrite(str(thumb_path), frame[y0:y1, x0:x1], [cv2.IMWRITE_JPEG_QUALITY, 92])

    payload = {
        "timestamp": round(float(timestamp), 2),
        "norm_x": round(float(norm_x), 4),
        "norm_y": round(float(norm_y), 4),
        "box": {"x": fx, "y": fy, "w": fw, "h": fh},
        "embedding": feat.flatten().astype(float).tolist(),
        "thumb_path": str(thumb_path),
    }
    (pdir / "pinned_face.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def track_face_in_cut(
    video_path: str | Path,
    start: float,
    end: float,
    fallback_crop: dict[str, int],
    cmd_output_path: str | Path,
    sample_fps: float = 3.0,
    mode: str = "pinned",
) -> dict[str, Any]:
    """Track the pinned face (or random multi-face switching in 'quick_detect') across [start, end]."""
    vpath = Path(video_path)
    is_quick = mode == "quick_detect"
    pinned = None if is_quick else get_pinned_face(vpath)
    pinned_feat = (
        np.array(pinned["embedding"], dtype=np.float32).reshape(1, -1)
        if pinned and pinned.get("embedding")
        else None
    )

    cap = cv2.VideoCapture(str(vpath))
    if not cap.isOpened():
        raise RuntimeError(f"Não foi possível abrir o vídeo: {vpath}")

    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)

        # Downscale for YuNet (up to 640x360) for 4x+ faster detection
        det_w = min(640, frame_w)
        det_h = max(2, int(round(frame_h * (det_w / max(1, frame_w)))))
        scale_x = frame_w / max(1, det_w)
        scale_y = frame_h / max(1, det_h)
        detector, recognizer = _create_models(det_w, det_h)

        duration = max(0.5, float(end) - float(start))
        step_frames = max(1, int(round(fps / max(1.0, sample_fps))))
        start_frame = max(0, int(round(float(start) * fps)))
        end_frame = max(start_frame + 1, int(round(float(end) * fps)))

        # Single initial seek, then sequential cap.grab() (avoids costly keyframe seeks)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        raw_samples: list[dict[str, Any]] = []
        last_cx = float(fallback_crop["x"] + fallback_crop["w"] / 2.0)
        last_cy = float(fallback_crop["y"] + fallback_crop["h"] / 2.0)
        last_switch_t = -999.0
        next_switch_interval = random.uniform(2.0, 3.0)

        cur_frame_idx = start_frame
        while cur_frame_idx < end_frame:
            ok = cap.grab()
            if not ok:
                break
            if (cur_frame_idx - start_frame) % step_frames == 0:
                t_rel = (cur_frame_idx - start_frame) / max(1.0, fps)
                ok_ret, frame = cap.retrieve()
                if not ok_ret or frame is None:
                    raw_samples.append({"t": float(t_rel), "detected": False})
                    cur_frame_idx += 1
                    continue

                small = (
                    cv2.resize(frame, (det_w, det_h), interpolation=cv2.INTER_AREA)
                    if (det_w != frame_w or det_h != frame_h)
                    else frame
                )
                _, faces_small = detector.detect(small)
                if faces_small is None or len(faces_small) == 0:
                    raw_samples.append({"t": float(t_rel), "detected": False})
                    cur_frame_idx += 1
                    continue

                # Project boxes + 5 landmarks back to full-res coordinates
                faces = faces_small.copy()
                faces[:, 0::2] *= scale_x
                faces[:, 1::2] *= scale_y
                # Restore score column (index 14) which shouldn't be scaled
                faces[:, 14] = faces_small[:, 14]

                chosen = None
                if is_quick:
                    if len(faces) == 1:
                        chosen = faces[0]
                        if last_switch_t < 0:
                            last_switch_t = float(t_rel)
                    else:
                        if last_switch_t < 0:
                            chosen = random.choice(list(faces))
                            last_switch_t = float(t_rel)
                            next_switch_interval = random.uniform(2.0, 3.0)
                        elif (float(t_rel) - last_switch_t) >= next_switch_interval:
                            # Switch to a different random face (excluding closest to current focus)
                            scored = sorted(
                                list(faces),
                                key=lambda r: (
                                    (float(r[0]) + float(r[2]) / 2.0 - last_cx) ** 2
                                    + (float(r[1]) + float(r[3]) / 2.0 - last_cy) ** 2
                                ),
                            )
                            candidates = scored[1:] if len(scored) > 1 else scored
                            chosen = random.choice(candidates)
                            last_switch_t = float(t_rel)
                            next_switch_interval = random.uniform(2.0, 3.0)
                        else:
                            # Hold current face smoothly until 2.0-3.0s window elapses
                            best_dist = float("inf")
                            for row in faces:
                                cx = float(row[0]) + float(row[2]) / 2.0
                                cy = float(row[1]) + float(row[3]) / 2.0
                                d = ((cx - last_cx) ** 2 + (cy - last_cy) ** 2) ** 0.5
                                if d < best_dist:
                                    best_dist = d
                                    chosen = row
                elif pinned_feat is not None:
                    best_score = -1.0
                    for row in faces:
                        aligned = recognizer.alignCrop(frame, row)
                        feat = recognizer.feature(aligned)
                        score = float(
                            recognizer.match(pinned_feat, feat, cv2.FaceRecognizerSF_FR_COSINE)
                        )
                        if score >= 0.28 and score > best_score:
                            best_score = score
                            chosen = row
                else:
                    best_dist = float("inf")
                    for row in faces:
                        cx = float(row[0]) + float(row[2]) / 2.0
                        cy = float(row[1]) + float(row[3]) / 2.0
                        d = ((cx - last_cx) ** 2 + (cy - last_cy) ** 2) ** 0.5
                        if d < best_dist:
                            best_dist = d
                            chosen = row

                if chosen is None:
                    raw_samples.append({"t": float(t_rel), "detected": False})
                else:
                    fx, fy, fw, fh = float(chosen[0]), float(chosen[1]), float(chosen[2]), float(chosen[3])
                    cx = fx + fw / 2.0
                    cy = fy + fh * 0.54
                    size = _even(_clamp(int(round(fh * 2.15)), int(frame_h * 0.18), int(frame_h * 0.60)))
                    size = _even(min(size, frame_w, frame_h))
                    last_cx, last_cy = cx, cy
                    raw_samples.append(
                        {
                            "t": float(t_rel),
                            "detected": True,
                            "cx": cx,
                            "cy": cy,
                            "size": size,
                        }
                    )
            cur_frame_idx += 1
    finally:
        cap.release()

    # Hysteresis for visibility (hide only after >= 0.70s absent) + 7% deadband anti-jitter
    absent_hide_samples = max(2, int(round(0.70 * sample_fps)))
    miss_streak = 0
    cur_visible = True if any(s.get("detected") for s in raw_samples[:3]) else False

    smooth_cx = float(fallback_crop["x"] + fallback_crop["w"] / 2.0)
    smooth_cy = float(fallback_crop["y"] + fallback_crop["h"] / 2.0)
    smooth_sz = float(fallback_crop["w"])

    keyframes: list[dict[str, Any]] = []
    for s in raw_samples:
        if s["detected"]:
            miss_streak = 0
            deadband_px = max(8.0, smooth_sz * 0.07)
            size_deadband_px = max(10.0, smooth_sz * 0.10)
            if not cur_visible:
                smooth_cx = s["cx"]
                smooth_cy = s["cy"]
                smooth_sz = float(s["size"])
            else:
                jump = ((s["cx"] - smooth_cx) ** 2 + (s["cy"] - smooth_cy) ** 2) ** 0.5
                if jump > frame_w * 0.14:
                    # Scene cut -> snap immediately
                    smooth_cx, smooth_cy, smooth_sz = s["cx"], s["cy"], float(s["size"])
                elif jump > deadband_px or abs(float(s["size"]) - smooth_sz) > size_deadband_px:
                    # Smooth follow only when exceeding 7% crop-size threshold
                    if jump > deadband_px:
                        smooth_cx = 0.45 * s["cx"] + 0.55 * smooth_cx
                        smooth_cy = 0.45 * s["cy"] + 0.55 * smooth_cy
                    if abs(float(s["size"]) - smooth_sz) > size_deadband_px:
                        smooth_sz = 0.35 * float(s["size"]) + 0.65 * smooth_sz
            cur_visible = True
        else:
            miss_streak += 1
            if miss_streak >= absent_hide_samples:
                cur_visible = False

        sz = _even(_clamp(int(round(smooth_sz)), int(frame_h * 0.16), min(frame_w, frame_h)))
        x = _clamp(int(round(smooth_cx - sz / 2.0)), 0, max(0, frame_w - sz))
        y = _clamp(int(round(smooth_cy - sz / 2.0)), 0, max(0, frame_h - sz))
        x -= x % 2
        y -= y % 2
        keyframes.append({"t": s["t"], "x": x, "y": y, "w": sz, "h": sz, "visible": cur_visible})

    # Auto-Static Bypass: if always visible and variation <= 7% threshold, use static crop
    if keyframes and all(kf["visible"] for kf in keyframes):
        xs = [kf["x"] for kf in keyframes]
        ys = [kf["y"] for kf in keyframes]
        ws = [kf["w"] for kf in keyframes]
        static_tol = max(10, int(round((sum(ws) / len(ws)) * 0.07)))
        if (max(xs) - min(xs) <= static_tol) and (max(ys) - min(ys) <= static_tol) and (max(ws) - min(ws) <= static_tol):
            med_x = _even(int(round(float(np.median(xs)))))
            med_y = _even(int(round(float(np.median(ys)))))
            med_w = _even(int(round(float(np.median(ws)))))
            return {
                "is_static": True,
                "cmd_file": None,
                "initial_crop": {"x": med_x, "y": med_y, "w": med_w, "h": med_w},
                "initial_alpha": 1.0,
                "keyframes_count": len(keyframes),
                "pinned_used": pinned_feat is not None,
            }

    # Write FFmpeg sendcmd file with cubic ease-in-out movement + smooth alpha fades
    def _ease_in_out_cubic(u: float) -> float:
        return 4.0 * u * u * u if u < 0.5 else 1.0 - ((-2.0 * u + 2.0) ** 3) / 2.0

    cmd_lines: list[str] = []
    prev_vis: bool | None = None
    prev_box: tuple[int, int, int, int] | None = None
    prev_t: float = 0.0

    for kf in keyframes:
        t = float(kf["t"])
        box = (kf["x"], kf["y"], kf["w"], kf["h"])
        vis = bool(kf["visible"])

        if prev_vis is None:
            aa = 1.0 if vis else 0.0
            cmd_lines.append(
                f"{t:.3f} crop@facecrop x {box[0]}, crop@facecrop y {box[1]}, "
                f"crop@facecrop w {box[2]}, crop@facecrop h {box[3]}, "
                f"colorchannelmixer@facealpha aa {aa:.2f};"
            )
            prev_vis = vis
            prev_box = box
            prev_t = t
            continue

        if vis != prev_vis:
            if vis:
                # Fade in smoothly over 0.18s at new position
                cmd_lines.append(
                    f"{t:.3f} crop@facecrop x {box[0]}, crop@facecrop y {box[1]}, "
                    f"crop@facecrop w {box[2]}, crop@facecrop h {box[3]}, "
                    "colorchannelmixer@facealpha aa 0.35;"
                )
                cmd_lines.append(f"{t + 0.09:.3f} colorchannelmixer@facealpha aa 0.70;")
                cmd_lines.append(f"{t + 0.18:.3f} colorchannelmixer@facealpha aa 1.00;")
            else:
                # Fade out smoothly over 0.24s
                cmd_lines.append(f"{t:.3f} colorchannelmixer@facealpha aa 0.65;")
                cmd_lines.append(f"{t + 0.12:.3f} colorchannelmixer@facealpha aa 0.30;")
                cmd_lines.append(f"{t + 0.24:.3f} colorchannelmixer@facealpha aa 0.00;")
            prev_vis = vis
            prev_box = box
            prev_t = t
        elif vis and prev_box is not None and box != prev_box:
            dt = max(0.04, t - prev_t)
            dist = ((box[0] - prev_box[0]) ** 2 + (box[1] - prev_box[1]) ** 2) ** 0.5
            if dist > frame_w * 0.16:
                # True scene cut -> snap cleanly without panning across unrelated scene
                cmd_lines.append(
                    f"{t:.3f} crop@facecrop x {box[0]}, crop@facecrop y {box[1]}, "
                    f"crop@facecrop w {box[2]}, crop@facecrop h {box[3]};"
                )
            else:
                # Smooth 30fps cubic ease-in-out glide between prev_box and box
                steps = max(2, min(12, int(round(dt * 30.0))))
                last_emitted = prev_box
                for step_i in range(1, steps + 1):
                    u = step_i / steps
                    e = _ease_in_out_cubic(u)
                    ix = _clamp(_even(int(round(prev_box[0] + (box[0] - prev_box[0]) * e))), 0, frame_w - 2)
                    iy = _clamp(_even(int(round(prev_box[1] + (box[1] - prev_box[1]) * e))), 0, frame_h - 2)
                    iw = _even(int(round(prev_box[2] + (box[2] - prev_box[2]) * e)))
                    ih = iw
                    ix = _clamp(ix, 0, max(0, frame_w - iw))
                    iy = _clamp(iy, 0, max(0, frame_h - ih))
                    cur_box = (ix - (ix % 2), iy - (iy % 2), iw, ih)
                    if cur_box != last_emitted or step_i == steps:
                        st = prev_t + dt * u
                        cmd_lines.append(
                            f"{st:.3f} crop@facecrop x {cur_box[0]}, crop@facecrop y {cur_box[1]}, "
                            f"crop@facecrop w {cur_box[2]}, crop@facecrop h {cur_box[3]};"
                        )
                        last_emitted = cur_box
            prev_box = box
            prev_t = t
        else:
            prev_t = t

    cmd_path = Path(cmd_output_path)
    cmd_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_path.write_text("\n".join(cmd_lines) + "\n", encoding="utf-8")

    init = keyframes[0] if keyframes else {**fallback_crop, "visible": True}
    return {
        "cmd_file": str(cmd_path),
        "initial_crop": {"x": init["x"], "y": init["y"], "w": init["w"], "h": init["h"]},
        "initial_alpha": 1.0 if init["visible"] else 0.0,
        "keyframes_count": len(keyframes),
        "pinned_used": pinned_feat is not None,
    }
