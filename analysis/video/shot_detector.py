"""
ShotDetector — intra-scene shot/cut detection (TASK-021).

Detects actual edit points (cuts, dissolves) within scenes
to build higher-resolution timeline data.
"""
from __future__ import annotations

import logging
from typing import Dict, List

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class ShotDetector:
    """Detect cuts and dissolves within a video segment."""

    def __init__(self, sensitivity: float = 0.35) -> None:
        self.sensitivity = sensitivity

    def detect(
        self,
        video_path: str,
        segment_start_s: float = 0.0,
        segment_end_s: Optional[float] = None,
    ) -> List[Dict]:
        """
        Return list of detected shots within the segment:
        [{start_s, end_s, shot_type: 'cut'|'dissolve'|'fade', confidence}]
        """
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.set(cv2.CAP_PROP_POS_MSEC, segment_start_s * 1000)

        end_frame = int((segment_end_s * fps)) if segment_end_s else int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        threshold = 0.25 + self.sensitivity * 0.4

        shots = []
        prev_frame = None
        shot_start = segment_start_s
        frame_idx = int(segment_start_s * fps)

        while frame_idx <= end_frame:
            ret, frame = cap.read()
            if not ret:
                break
            t = frame_idx / fps
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0

            if prev_frame is not None:
                diff = np.mean(np.abs(gray - prev_frame))
                shot_type, confidence = _classify_transition(diff, threshold)
                if shot_type != "none":
                    shots.append({
                        "start_s": shot_start,
                        "end_s": t,
                        "shot_type": shot_type,
                        "confidence": confidence,
                    })
                    shot_start = t

            prev_frame = gray
            frame_idx += 1

        t_end = (segment_end_s or end_frame / fps)
        if shot_start < t_end - 0.05:
            shots.append({
                "start_s": shot_start,
                "end_s": t_end,
                "shot_type": "interior",
                "confidence": 1.0,
            })

        cap.release()
        return shots


def _classify_transition(diff: float, threshold: float):
    if diff > threshold * 2:
        return "cut", min(1.0, diff / 0.8)
    if diff > threshold:
        return "dissolve", diff / threshold
    return "none", 0.0


from typing import Optional
