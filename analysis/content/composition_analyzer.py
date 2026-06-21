"""
CompositionAnalyzer — evaluates frame composition quality.

Scores: rule_of_thirds, horizon_level, symmetry, subject_position,
visual_depth, background_clutter. Returns a CompositionResult dataclass.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CompositionResult:
    composition_score: float        # overall [0-1]
    rule_of_thirds_score: float
    horizon_level_score: float      # 1.0 = level horizon
    symmetry_score: float
    subject_position_score: float   # is main subject off-centre?
    visual_depth_score: float       # foreground + background presence
    background_clutter_score: float # 1.0 = clean, 0.0 = cluttered
    notes: list = field(default_factory=list)


class CompositionAnalyzer:
    """
    Analyse frame composition for a video segment.

    Usage:
        result = CompositionAnalyzer().analyze(video_path, start_s, end_s)
    """

    def analyze(self, video_path: str, start_s: float, end_s: float) -> CompositionResult:
        frame = _sample_frame(video_path, (start_s + end_s) / 2)
        if frame is None:
            return _default_result()
        return self._score_frame(frame)

    def _score_frame(self, frame: np.ndarray) -> CompositionResult:
        try:
            rot_score = _rule_of_thirds(frame)
            hor_score = _horizon_level(frame)
            sym_score = _symmetry(frame)
            sub_score = _subject_position(frame)
            dep_score = _visual_depth(frame)
            clt_score = _background_clutter(frame)

            notes = []
            if hor_score < 0.6:
                notes.append("tilted horizon")
            if clt_score < 0.4:
                notes.append("cluttered background")

            overall = (
                0.25 * rot_score +
                0.20 * hor_score +
                0.15 * sym_score +
                0.20 * sub_score +
                0.10 * dep_score +
                0.10 * clt_score
            )
            return CompositionResult(
                composition_score       = round(float(overall), 4),
                rule_of_thirds_score    = round(float(rot_score), 4),
                horizon_level_score     = round(float(hor_score), 4),
                symmetry_score          = round(float(sym_score), 4),
                subject_position_score  = round(float(sub_score), 4),
                visual_depth_score      = round(float(dep_score), 4),
                background_clutter_score= round(float(clt_score), 4),
                notes                   = notes,
            )
        except Exception as exc:
            logger.debug(f"[CompositionAnalyzer] failed: {exc}")
            return _default_result()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sample_frame(video_path: str, t: float) -> Optional[np.ndarray]:
    try:
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0, t) * 1000)
        ret, frame = cap.read()
        cap.release()
        return frame if ret else None
    except Exception:
        return None


def _default_result() -> CompositionResult:
    return CompositionResult(0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5)


def _rule_of_thirds(frame: np.ndarray) -> float:
    h, w = frame.shape[:2]
    gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    gx = [w // 3, 2 * w // 3]
    gy = [h // 3, 2 * h // 3]
    scores = []
    for x in gx:
        for y in gy:
            r = edges[max(0, y-25):y+25, max(0, x-25):x+25]
            scores.append(float(r.mean() / 255.0))
    base = float(np.mean(scores))
    # Normalise: 0.15 density → 1.0
    return min(1.0, base / 0.15)


def _horizon_level(frame: np.ndarray) -> float:
    """Detect strong horizontal edges; tilted horizon → low score."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Detect lines via HoughLines
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=max(30, w // 8))
    if lines is None:
        return 0.65  # neutral

    angles = []
    for line in lines[:20]:
        rho, theta = line[0]
        # theta near π/2 = horizontal line
        angle_from_horiz = abs(theta - np.pi / 2)
        if angle_from_horiz < np.pi / 6:  # within 30° of horizontal
            angles.append(angle_from_horiz)

    if not angles:
        return 0.65

    mean_tilt = float(np.mean(angles))  # 0 = perfectly level
    return max(0.0, 1.0 - mean_tilt / (np.pi / 6))


def _symmetry(frame: np.ndarray) -> float:
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    left  = gray[:, :w//2]
    right = cv2.flip(gray[:, w//2:w//2*2], 1)
    if left.shape != right.shape:
        right = cv2.resize(right, (left.shape[1], left.shape[0]))
    diff = np.abs(left - right).mean() / 255.0
    return max(0.0, 1.0 - diff * 3)


def _subject_position(frame: np.ndarray) -> float:
    """Check if main subject (via saliency) is off-centre (good for composition)."""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Use edge energy as proxy for subject location
    edges = cv2.Canny(gray, 30, 90).astype(np.float32)
    if edges.max() == 0:
        return 0.5

    # Compute center of mass
    m = cv2.moments(edges)
    if m["m00"] == 0:
        return 0.5
    cx = m["m10"] / m["m00"]
    cy = m["m01"] / m["m00"]

    # Normalise to [-1, 1]
    nx = (cx / w - 0.5) * 2
    ny = (cy / h - 0.5) * 2

    # Subject at rule-of-thirds points → high score
    rot_x = [1/3, 2/3]  # normalized
    rot_y = [1/3, 2/3]
    best = min(
        abs(cx / w - rx) + abs(cy / h - ry)
        for rx in rot_x for ry in rot_y
    )
    return max(0.0, 1.0 - best * 3)


def _visual_depth(frame: np.ndarray) -> float:
    """Estimate depth by comparing sharpness in top/mid/bottom thirds."""
    h = frame.shape[0]
    thirds = [
        frame[:h//3],
        frame[h//3: 2*h//3],
        frame[2*h//3:],
    ]
    sharpness = []
    for t in thirds:
        gray = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharpness.append(float(lap))

    if max(sharpness) == 0:
        return 0.5
    # High variance across thirds → depth
    std = float(np.std(sharpness))
    return min(1.0, std / (max(sharpness) * 0.5 + 1e-6))


def _background_clutter(frame: np.ndarray) -> float:
    """Low edge density in background (top/sides) → clean background."""
    h, w = frame.shape[:2]
    gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150).astype(np.float32) / 255.0

    bg_mask = np.zeros((h, w), np.float32)
    # Top third and side strips as "background"
    bg_mask[:h//3, :] = 1
    bg_mask[:, :w//8] = 1
    bg_mask[:, 7*w//8:] = 1

    bg_density = (edges * bg_mask).mean()
    return max(0.0, 1.0 - bg_density * 8)
