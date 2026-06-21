"""
QualityEngine — unified quality analysis (TASK-022).

Analyzes sharpness, contrast, brightness, noise, colorfulness,
saturation for a video segment. All metrics normalized to [0, 1].
"""
from __future__ import annotations

import logging
from typing import Any, Dict

import cv2
import numpy as np

from infrastructure.config.config_manager import cfg

logger = logging.getLogger(__name__)

_SAMPLE_FRAMES = 5  # frames to sample per segment


class QualityEngine:
    """Compute quality metrics for a video segment."""

    def analyze(self, video_path: str, start_s: float, end_s: float) -> Dict[str, Any]:
        """
        Return dict with: sharpness, brightness, contrast, noise_level,
        colorfulness, saturation, motion_magnitude.
        All values in [0, 1].
        """
        frames = _sample_frames(video_path, start_s, end_s, n=_SAMPLE_FRAMES)
        if not frames:
            return _empty_metrics()

        sharpness_vals = [_sharpness(f) for f in frames]
        brightness_vals = [_brightness(f) for f in frames]
        contrast_vals = [_contrast(f) for f in frames]
        color_vals = [_colorfulness(f) for f in frames]
        sat_vals = [_saturation(f) for f in frames]
        noise_vals = [_noise(f) for f in frames]

        motion = _optical_flow_magnitude(frames) if len(frames) > 1 else 0.0

        return {
            "sharpness": float(np.mean(sharpness_vals)),
            "brightness": float(np.mean(brightness_vals)),
            "contrast": float(np.mean(contrast_vals)),
            "colorfulness": float(np.mean(color_vals)),
            "saturation": float(np.mean(sat_vals)),
            "noise_level": float(np.mean(noise_vals)),
            "motion_magnitude": float(motion),
        }


# ── Metric functions ──────────────────────────────────────────────────────────

def _sharpness(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    return float(min(1.0, lap_var / 3000.0))  # 3000 ≈ sharp reference


def _brightness(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray) / 255.0)


def _contrast(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.std(gray) / 128.0)


def _colorfulness(frame: np.ndarray) -> float:
    """Hasler & Süsstrunk colorfulness metric, normalized."""
    b, g, r = frame[:, :, 0].astype(float), frame[:, :, 1].astype(float), frame[:, :, 2].astype(float)
    rg = r - g
    yb = 0.5 * (r + g) - b
    std_rg, std_yb = np.std(rg), np.std(yb)
    mean_rg, mean_yb = np.mean(rg), np.mean(yb)
    cf = np.sqrt(std_rg ** 2 + std_yb ** 2) + 0.3 * np.sqrt(mean_rg ** 2 + mean_yb ** 2)
    return float(min(1.0, cf / 150.0))


def _saturation(frame: np.ndarray) -> float:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    return float(np.mean(hsv[:, :, 1]) / 255.0)


def _noise(frame: np.ndarray) -> float:
    """Estimate noise via residual after Gaussian blur (higher = more noise)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    residual = np.std(gray - blurred)
    return float(min(1.0, residual / 20.0))


def _optical_flow_magnitude(frames) -> float:
    if len(frames) < 2:
        return 0.0
    magnitudes = []
    prev = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
    for frame in frames[1:]:
        curr = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(prev, curr, None,
                                            0.5, 3, 15, 3, 5, 1.2, 0)
        mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        magnitudes.append(np.mean(mag))
        prev = curr
    return float(min(1.0, np.mean(magnitudes) / 30.0))


def _sample_frames(video_path: str, start_s: float, end_s: float, n: int = 5):
    cap = cv2.VideoCapture(video_path)
    duration = end_s - start_s
    step = duration / (n + 1)
    frames = []
    for i in range(1, n + 1):
        t = start_s + step * i
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)
    cap.release()
    return frames


def _empty_metrics() -> Dict[str, Any]:
    return {
        "sharpness": 0.0, "brightness": 0.0, "contrast": 0.0,
        "colorfulness": 0.0, "saturation": 0.0, "noise_level": 1.0,
        "motion_magnitude": 0.0,
    }
