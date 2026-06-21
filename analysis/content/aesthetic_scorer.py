"""
AestheticScorer — visual attractiveness scoring.

Combines composition, color harmony, balance, saliency, and lighting.
Modes: basic_opencv (default), saliency_based.
Returns aesthetic_score in [0, 1].
"""
from __future__ import annotations

import cv2
import numpy as np


class AestheticScorer:
    """Score visual attractiveness of a frame/segment.

    mode: "basic_opencv" | "saliency_based"
    """

    def __init__(self, mode: str = "basic_opencv"):
        self.mode = mode

    def score(self, video_path: str, start_s: float) -> float:
        """Return aesthetic_score [0, 1] for the frame at start_s."""
        frame = _get_frame(video_path, start_s)
        if frame is None:
            return 0.5
        return self._score_frame(frame)

    def score_segment(self, video_path: str, start_s: float, end_s: float,
                       n_samples: int = 3) -> float:
        """Average aesthetic score across multiple frames in segment."""
        dur = max(0.5, end_s - start_s)
        scores = []
        try:
            cap = cv2.VideoCapture(video_path)
            for i in range(n_samples):
                t = start_s + dur * (i + 0.5) / n_samples
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ret, frame = cap.read()
                if ret:
                    scores.append(self._score_frame(frame))
            cap.release()
        except Exception:
            pass
        return float(np.mean(scores)) if scores else 0.5

    def _score_frame(self, frame: np.ndarray) -> float:
        if self.mode == "saliency_based":
            return self._score_saliency(frame)
        return self._score_basic(frame)

    def _score_basic(self, frame: np.ndarray) -> float:
        composition = _rule_of_thirds(frame)
        color       = _color_harmony(frame)
        balance     = _visual_balance(frame)
        exposure    = _exposure_quality(frame)
        lighting    = _lighting_quality(frame)
        sharpness   = _local_sharpness(frame)

        score = (
            0.22 * composition +
            0.20 * color +
            0.18 * balance +
            0.18 * exposure +
            0.12 * lighting +
            0.10 * sharpness
        )
        return float(min(1.0, max(0.0, score)))

    def _score_saliency(self, frame: np.ndarray) -> float:
        """Extended mode: uses OpenCV saliency map for subject importance."""
        base = self._score_basic(frame)
        try:
            saliency = cv2.saliency.StaticSaliencySpectralResidual_create()
            success, sal_map = saliency.computeSaliency(frame)
            if success:
                # High saliency variance → interesting subject composition
                sal_norm = (sal_map * 255).astype(np.uint8)
                sal_score = float(np.std(sal_norm.astype(np.float32))) / 64.0
                sal_score = min(1.0, sal_score)
                return float(base * 0.7 + sal_score * 0.3)
        except Exception:
            pass
        return base


# ── Metric functions ──────────────────────────────────────────────────────────

def _rule_of_thirds(frame: np.ndarray) -> float:
    """Score how well the main subject aligns with rule-of-thirds intersections."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)

    # Rule of thirds grid points
    grid_x = [w // 3, 2 * w // 3]
    grid_y = [h // 3, 2 * h // 3]

    scores = []
    for gx in grid_x:
        for gy in grid_y:
            region = edges[max(0, gy-20):gy+20, max(0, gx-20):gx+20]
            scores.append(float(region.mean() / 255.0))

    return float(np.mean(scores))


def _color_harmony(frame: np.ndarray) -> float:
    """Score based on color distribution — penalize muddy/monotone palettes."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].flatten()
    sat = hsv[:, :, 1].flatten()

    if sat.mean() < 20:
        return 0.4  # grayscale-like

    # Spread of hue values — moderate spread is good
    hue_std = float(np.std(hue))
    score = min(1.0, hue_std / 60.0)  # 60° spread = good

    # Penalize very low saturation
    sat_score = float(np.mean(sat) / 255.0)
    return (score + sat_score) / 2.0


def _visual_balance(frame: np.ndarray) -> float:
    """Score visual balance: how evenly distributed is visual weight."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape
    left = gray[:, :w//2].mean()
    right = gray[:, w//2:].mean()
    top = gray[:h//2, :].mean()
    bottom = gray[h//2:, :].mean()

    h_balance = 1.0 - abs(left - right) / max(left + right, 1.0)
    v_balance = 1.0 - abs(top - bottom) / max(top + bottom, 1.0)
    return float((h_balance + v_balance) / 2.0)


def _exposure_quality(frame: np.ndarray) -> float:
    """Score exposure — penalize over/under-exposed frames."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_brightness = float(np.mean(gray) / 255.0)
    overexposed = float(np.mean(gray > 240) )
    underexposed = float(np.mean(gray < 15))

    # Ideal: mean ~0.4–0.6, minimal clipping
    brightness_score = 1.0 - abs(mean_brightness - 0.5) * 2
    clip_penalty = (overexposed + underexposed) * 3
    return max(0.0, min(1.0, brightness_score - clip_penalty))


def _lighting_quality(frame: np.ndarray) -> float:
    """Score lighting: penalise harsh shadows and blown-out areas."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l   = lab[:, :, 0].astype(np.float32)
    mean_l = float(l.mean()) / 255.0
    std_l  = float(l.std()) / 255.0
    # Ideal: mean 0.35-0.65, moderate std
    mean_score = 1.0 - abs(mean_l - 0.50) * 2.5
    std_score  = min(1.0, std_l / 0.20)       # some contrast is good
    return max(0.0, float((mean_score + std_score) / 2))


def _local_sharpness(frame: np.ndarray) -> float:
    """Laplacian variance as proxy for sharpness."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    lap  = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    # Typical range 0-2000; normalise to [0, 1]
    return float(min(1.0, lap / 800.0))


def _get_frame(video_path: str, t: float):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None
