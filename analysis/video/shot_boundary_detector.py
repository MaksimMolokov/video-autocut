"""
ShotBoundaryDetector — detects shot boundaries within a video.

Supports two modes:
  content_threshold  — histogram difference > threshold
  adaptive_threshold — adaptive per-video threshold

Returns a list of ShotBoundary objects with type (cut/fade/dissolve/unknown),
boundary_confidence, and scene_change_score.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_VALID_TYPES = {"cut", "fade", "dissolve", "camera_motion_change", "content_change", "unknown"}


@dataclass
class ShotBoundary:
    start_sec: float
    end_sec: float
    duration_sec: float
    boundary_type: str          # cut | fade | dissolve | camera_motion_change | content_change | unknown
    boundary_confidence: float  # [0-1]
    scene_change_score: float   # raw histogram diff score


class ShotBoundaryDetector:
    """
    Detect shot boundaries inside a video file.

    Usage:
        boundaries = ShotBoundaryDetector().detect(video_path)
        # or with mode:
        boundaries = ShotBoundaryDetector(mode="adaptive_threshold").detect(video_path)
    """

    MIN_SCENE_DURATION = 0.5    # seconds — ignore shorter scenes
    CUT_THRESHOLD      = 0.35   # histogram diff → hard cut
    FADE_THRESHOLD     = 0.12   # subtle diff over time → fade/dissolve

    def __init__(self, mode: str = "content_threshold", sample_fps: float = 10.0,
                 threshold: Optional[float] = None):
        self.mode       = mode
        self.sample_fps = sample_fps
        self.threshold  = threshold  # явный порог для content_threshold (иначе CUT_THRESHOLD)

    def detect(self, video_path: str) -> List[ShotBoundary]:
        try:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration_s   = total_frames / fps

            step = max(1, int(fps / self.sample_fps))
            diffs, timestamps = _compute_diffs(cap, step, fps)
            cap.release()

            if len(diffs) < 2:
                return [_whole_video_boundary(duration_s)]

            threshold = _adaptive_threshold(diffs) if self.mode == "adaptive_threshold" \
                        else (self.threshold if self.threshold is not None else self.CUT_THRESHOLD)

            boundaries = _find_boundaries(diffs, timestamps, threshold, duration_s,
                                          self.MIN_SCENE_DURATION)
            return boundaries if boundaries else [_whole_video_boundary(duration_s)]

        except Exception as exc:
            logger.warning(f"[ShotBoundaryDetector] {exc}")
            return []


# ── Helpers ────────────────────────────────────────────────────────────────────

def _compute_diffs(cap: cv2.VideoCapture, step: int, fps: float):
    diffs, timestamps = [], []
    prev_hist = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % step == 0:
            hist = _color_hist(frame)
            if prev_hist is not None:
                diff = float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
                diffs.append(diff)
                timestamps.append(frame_idx / fps)
            prev_hist = hist
        frame_idx += 1

    return diffs, timestamps


def _color_hist(frame: np.ndarray) -> np.ndarray:
    small = cv2.resize(frame, (64, 64))
    hsv   = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    # H+S+V: без V-канала кадры, отличающиеся только яркостью
    # (белый/чёрный, день/ночь, фейды), дают идентичные гистограммы
    hist  = cv2.calcHist([hsv], [0, 1, 2], None, [15, 16, 16],
                         [0, 180, 0, 256, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def _adaptive_threshold(diffs: List[float]) -> float:
    arr = np.array(diffs)
    return float(np.mean(arr) + 1.5 * np.std(arr))


def _find_boundaries(diffs: List[float], timestamps: List[float],
                     threshold: float, duration_s: float,
                     min_dur: float) -> List[ShotBoundary]:
    boundaries = []
    scene_start = 0.0

    for i, diff in enumerate(diffs):
        t = timestamps[i]
        if diff >= threshold:
            end_t = t
            dur   = end_t - scene_start
            if dur >= min_dur:
                btype, conf = _classify_boundary(diff, threshold)
                boundaries.append(ShotBoundary(
                    start_sec          = round(scene_start, 3),
                    end_sec            = round(end_t, 3),
                    duration_sec       = round(dur, 3),
                    boundary_type      = btype,
                    boundary_confidence= round(conf, 4),
                    scene_change_score = round(diff, 4),
                ))
            scene_start = t

    # Final scene
    if duration_s - scene_start >= min_dur:
        boundaries.append(ShotBoundary(
            start_sec          = round(scene_start, 3),
            end_sec            = round(duration_s, 3),
            duration_sec       = round(duration_s - scene_start, 3),
            boundary_type      = "unknown",
            boundary_confidence= 0.5,
            scene_change_score = 0.0,
        ))

    return boundaries


def _classify_boundary(diff: float, threshold: float) -> tuple[str, float]:
    if diff > threshold * 2.5:
        return "cut", min(1.0, diff / 0.8)
    if diff > threshold * 1.5:
        return "content_change", 0.75
    if diff > threshold:
        return "dissolve", 0.60
    return "unknown", 0.40


def _whole_video_boundary(duration_s: float) -> ShotBoundary:
    return ShotBoundary(
        start_sec=0.0, end_sec=round(duration_s, 3),
        duration_sec=round(duration_s, 3),
        boundary_type="unknown", boundary_confidence=1.0, scene_change_score=0.0,
    )
