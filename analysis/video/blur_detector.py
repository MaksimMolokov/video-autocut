"""
BlurDetector — detect blurry frames in a video segment (TASK-023).

Uses Laplacian variance (primary) + high-frequency energy (secondary).
Returns blur_score [0=sharp, 1=blurry] and is_blurry flag.
"""
from __future__ import annotations

from typing import Dict

import cv2
import numpy as np

from infrastructure.config.config_manager import cfg


class BlurDetector:
    """Detect motion blur and out-of-focus frames."""

    def __init__(self) -> None:
        self._threshold = cfg.get("quality.sharpness_min", 0.04)

    def score(self, video_path: str, start_s: float, end_s: float) -> Dict:
        """Return {score: float [0=sharp,1=blurry], is_blurry: bool}."""
        frames = _sample(video_path, start_s, end_s, n=4)
        if not frames:
            return {"score": 1.0, "is_blurry": True}

        lap_scores = [_laplacian_score(f) for f in frames]
        hf_scores = [_high_freq_score(f) for f in frames]

        sharpness = float(np.mean(lap_scores))
        hf = float(np.mean(hf_scores))

        # Combined: weighted average (laplacian is primary)
        combined_sharpness = 0.7 * sharpness + 0.3 * hf
        blur_score = max(0.0, 1.0 - combined_sharpness / max(self._threshold * 10, 0.01))
        blur_score = min(1.0, blur_score)
        is_blurry = combined_sharpness < self._threshold

        return {"score": blur_score, "is_blurry": is_blurry}

    def is_blurry_frame(self, frame: "np.ndarray") -> bool:
        return _laplacian_score(frame) < self._threshold


def _laplacian_score(frame: "np.ndarray") -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var() / 3000.0)


def _high_freq_score(frame: "np.ndarray") -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    f = np.fft.fft2(gray)
    fshift = np.fft.fftshift(f)
    magnitude = np.log1p(np.abs(fshift))
    h, w = magnitude.shape
    center_h, center_w = h // 4, w // 4
    center = magnitude[center_h:3*center_h, center_w:3*center_w]
    high_freq = magnitude.sum() - center.sum()
    return float(min(1.0, high_freq / (magnitude.sum() + 1e-9)))


def _sample(video_path: str, start_s: float, end_s: float, n: int = 4):
    cap = cv2.VideoCapture(video_path)
    duration = max(end_s - start_s, 0.1)
    frames = []
    for i in range(n):
        t = start_s + duration * (i + 0.5) / n
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)
    cap.release()
    return frames
