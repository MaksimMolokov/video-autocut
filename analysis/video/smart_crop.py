"""
SmartCrop — content-aware crop for vertical / non-standard formats (TZ section 8).

Logic (TZ):
  1. If faces detected → crop around face center
  2. If person detected (no face) → crop around person center
  3. If no people → crop around saliency + motion center
  4. If crop quality is low → return warning to show user
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Relative crop center (x, y) in [0, 1] — default is frame center
_DEFAULT_CENTER = (0.5, 0.5)


class SmartCrop:
    """Determine optimal crop center for a video segment."""

    def __init__(self) -> None:
        self._face_detector = None
        self._init_face()

    def _init_face(self) -> None:
        try:
            import mediapipe as mp
            self._face_detector = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.4
            )
        except Exception as exc:
            # Не только ImportError: в некоторых сборках mediapipe нет .solutions
            # (Tasks-only API) → AttributeError. Деградируем на saliency/центр.
            logger.info("[SmartCrop] mediapipe face init failed (%s) — saliency fallback", exc)
            self._face_detector = None

    def get_crop_center(
        self,
        video_path: str,
        start_s: float,
        end_s: float,
    ) -> Dict:
        """
        Returns {
            center_x: float,   # 0..1 relative to frame width
            center_y: float,   # 0..1 relative to frame height
            method: str,       # 'face' | 'person' | 'saliency' | 'center'
            confidence: float, # 0..1
            warning: str | None,
        }
        """
        frame = _get_frame(video_path, (start_s + end_s) / 2)
        if frame is None:
            return _default_result("center")

        h, w = frame.shape[:2]

        # 1. Try face detection
        if self._face_detector:
            result = self._detect_face(frame)
            if result:
                return {**result, "warning": None}

        # 2. Try person / HOG
        person_center = _detect_person_hog(frame, w, h)
        if person_center:
            cx, cy = person_center
            return {
                "center_x": cx, "center_y": cy,
                "method": "person", "confidence": 0.6, "warning": None,
            }

        # 3. Saliency fallback
        sal_center = _saliency_center(frame, w, h)
        if sal_center:
            cx, cy = sal_center
            warning = None
            # If saliency is near edge, crop quality may be bad
            if cx < 0.15 or cx > 0.85:
                warning = "Центр внимания у края кадра — проверьте crop"
            return {
                "center_x": cx, "center_y": cy,
                "method": "saliency", "confidence": 0.4, "warning": warning,
            }

        return _default_result("center")

    def _detect_face(self, frame: np.ndarray) -> Optional[Dict]:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._face_detector.process(rgb)
        if not result.detections:
            return None
        h, w = frame.shape[:2]
        # Pick largest face
        largest = max(result.detections, key=lambda d: (
            d.location_data.relative_bounding_box.width *
            d.location_data.relative_bounding_box.height
        ))
        bb = largest.location_data.relative_bounding_box
        cx = bb.xmin + bb.width / 2
        cy = bb.ymin + bb.height / 2
        return {
            "center_x": float(np.clip(cx, 0.1, 0.9)),
            "center_y": float(np.clip(cy, 0.1, 0.85)),
            "method": "face",
            "confidence": float(largest.score[0]) if largest.score else 0.8,
        }

    def get_crop_for_segment(
        self,
        video_path: str,
        start_s: float,
        end_s: float,
        target_width: int,
        target_height: int,
    ) -> Dict:
        """
        Return FFmpeg crop parameters: {x, y, w, h, warning}.
        x, y in pixels relative to source frame.
        """
        center = self.get_crop_center(video_path, start_s, end_s)
        frame = _get_frame(video_path, (start_s + end_s) / 2)
        if frame is None:
            return {"x": 0, "y": 0, "w": target_width, "h": target_height,
                    "warning": center.get("warning")}

        src_h, src_w = frame.shape[:2]
        cx_px = int(center["center_x"] * src_w)
        cy_px = int(center["center_y"] * src_h)

        x = max(0, min(src_w - target_width, cx_px - target_width // 2))
        y = max(0, min(src_h - target_height, cy_px - target_height // 2))

        return {
            "x": x, "y": y,
            "w": target_width, "h": target_height,
            "center_x": center["center_x"],
            "center_y": center["center_y"],
            "method": center["method"],
            "warning": center.get("warning"),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_frame(video_path: str, t: float) -> Optional[np.ndarray]:
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def _detect_person_hog(frame, w, h) -> Optional[Tuple[float, float]]:
    try:
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        small = cv2.resize(frame, (min(w, 640), min(h, 480)))
        rects, _ = hog.detectMultiScale(small, winStride=(8, 8), padding=(4, 4), scale=1.05)
        if not len(rects):
            return None
        scale_x = w / small.shape[1]
        scale_y = h / small.shape[0]
        x, y, rw, rh = rects[0]
        cx = (x + rw / 2) * scale_x / w
        cy = (y + rh / 2) * scale_y / h
        return (float(np.clip(cx, 0.1, 0.9)), float(np.clip(cy, 0.1, 0.9)))
    except Exception:
        return None


def _saliency_center(frame, w, h) -> Optional[Tuple[float, float]]:
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        f = np.fft.fft2(gray)
        log_amp = np.log(np.abs(f) + 1e-9)
        phase = np.angle(f)
        smoothed = cv2.GaussianBlur(log_amp, (5, 5), 0)
        residual = log_amp - smoothed
        smap = np.abs(np.fft.ifft2(np.exp(residual + 1j * phase))) ** 2
        smap = cv2.GaussianBlur(smap.astype(np.float32), (11, 11), 0)
        _, _, _, max_loc = cv2.minMaxLoc(smap)
        return (float(max_loc[0] / w), float(max_loc[1] / h))
    except Exception:
        return None


def _default_result(method: str) -> Dict:
    return {
        "center_x": 0.5, "center_y": 0.5,
        "method": method, "confidence": 0.3,
        "warning": None,
    }
