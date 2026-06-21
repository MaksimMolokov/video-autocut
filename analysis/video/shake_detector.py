"""
ShakeDetector — camera shake / motion type detection (TASK-024).

Uses Optical Flow to distinguish intentional camera movement
(pan, tilt, zoom) from technical shake (random jitter).
"""
from __future__ import annotations

from typing import Dict

import cv2
import numpy as np

from infrastructure.config.config_manager import cfg

_SHAKE_THRESHOLD = 0.7  # shake_score above this → reject


class ShakeDetector:
    """Analyze camera motion type and shake level."""

    def score(self, video_path: str, start_s: float, end_s: float) -> Dict:
        """
        Return {
            shake_score: float [0=stable, 1=very shaky],
            motion_type: str  ['static'|'pan'|'tilt'|'zoom'|'shake'],
            stability: float [0=unstable, 1=stable],
        }
        """
        frames = _sample_frames(video_path, start_s, end_s, n=6)
        if len(frames) < 2:
            return {"shake_score": 0.0, "motion_type": "static", "stability": 1.0}

        flows = _compute_flows(frames)
        if not flows:
            return {"shake_score": 0.0, "motion_type": "static", "stability": 1.0}

        # Global motion vectors (mean dx, dy per frame pair)
        mean_dx = [float(np.mean(f[..., 0])) for f in flows]
        mean_dy = [float(np.mean(f[..., 1])) for f in flows]

        # Variance of residual after removing global motion = shake
        residual_x = [f[..., 0] - dx for f, dx in zip(flows, mean_dx)]
        residual_y = [f[..., 1] - dy for f, dy in zip(flows, mean_dy)]
        shake_x = float(np.mean([np.std(r) for r in residual_x]))
        shake_y = float(np.mean([np.std(r) for r in residual_y]))
        shake_score = min(1.0, (shake_x + shake_y) / 15.0)

        motion_type = _classify_motion(mean_dx, mean_dy, shake_score)
        stability = max(0.0, 1.0 - shake_score)

        return {
            "shake_score": shake_score,
            "motion_type": motion_type,
            "stability": stability,
        }


def _compute_flows(frames):
    flows = []
    prev = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
    for frame in frames[1:]:
        curr = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(prev, curr, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        flows.append(flow)
        prev = curr
    return flows


def _classify_motion(mean_dx, mean_dy, shake_score: float) -> str:
    if shake_score > _SHAKE_THRESHOLD:
        return "shake"
    avg_dx = float(np.mean(np.abs(mean_dx)))
    avg_dy = float(np.mean(np.abs(mean_dy)))
    if avg_dx < 0.3 and avg_dy < 0.3:
        return "static"
    if avg_dx > avg_dy * 1.5:
        return "pan"
    if avg_dy > avg_dx * 1.5:
        return "tilt"
    return "zoom"


def _sample_frames(video_path: str, start_s: float, end_s: float, n: int = 6):
    cap = cv2.VideoCapture(video_path)
    duration = max(end_s - start_s, 0.1)
    frames = []
    for i in range(n):
        t = start_s + duration * i / (n - 1) if n > 1 else start_s
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret and frame is not None:
            frames.append(frame)
    cap.release()
    return frames
