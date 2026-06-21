"""
SaliencyDetector — detect visually important regions (TASK-032).

Used for smart crop and composition scoring.
Returns normalized saliency score [0, 1] for a video segment.
"""
from __future__ import annotations

import cv2
import numpy as np


class SaliencyDetector:
    """Compute visual saliency for video segment frames."""

    def __init__(self) -> None:
        try:
            self._saliency = cv2.saliency.StaticSaliencyFineGrained_create()
        except AttributeError:
            self._saliency = None

    def score(self, video_path: str, start_s: float, end_s: float) -> float:
        """Return mean saliency score [0, 1] for the segment."""
        frame = _get_frame(video_path, (start_s + end_s) / 2)
        if frame is None:
            return 0.5
        return self._frame_score(frame)

    def saliency_map(self, frame: np.ndarray) -> np.ndarray:
        """Return saliency map (H×W float32) for a single frame."""
        if self._saliency:
            success, smap = self._saliency.computeSaliency(frame)
            if success:
                return smap.astype(np.float32)
        return _spectral_residual(frame)

    def center_weighted_score(self, frame: np.ndarray) -> float:
        """Score biased toward center — higher if salient area is centered."""
        smap = self.saliency_map(frame)
        h, w = smap.shape[:2]
        weights = _gaussian_weight_map(h, w)
        return float(np.sum(smap * weights) / (np.sum(weights) + 1e-9))

    def _frame_score(self, frame: np.ndarray) -> float:
        smap = self.saliency_map(frame)
        return float(np.mean(smap))


def _get_frame(video_path: str, t: float):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def _gaussian_weight_map(h: int, w: int) -> np.ndarray:
    cx, cy = w / 2, h / 2
    x = np.linspace(0, w, w)
    y = np.linspace(0, h, h)
    xx, yy = np.meshgrid(x, y)
    sigma_x, sigma_y = w / 3, h / 3
    weights = np.exp(-((xx - cx) ** 2 / (2 * sigma_x ** 2) + (yy - cy) ** 2 / (2 * sigma_y ** 2)))
    return weights.astype(np.float32)


def _spectral_residual(frame: np.ndarray) -> np.ndarray:
    """Fallback spectral residual saliency."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    f = np.fft.fft2(gray)
    log_amplitude = np.log(np.abs(f) + 1e-9)
    phase = np.angle(f)
    smoothed = cv2.GaussianBlur(log_amplitude, (5, 5), 0)
    residual = log_amplitude - smoothed
    saliency = np.abs(np.fft.ifft2(np.exp(residual + 1j * phase))) ** 2
    saliency = cv2.GaussianBlur(saliency.astype(np.float32), (9, 9), 0)
    saliency = (saliency - saliency.min()) / (saliency.max() - saliency.min() + 1e-9)
    return saliency
