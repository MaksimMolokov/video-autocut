"""
FaceDetector — detect faces in video segments (TASK-030).

Uses MediaPipe Face Detection. Returns count, size ratio, and visibility quality.
"""
from __future__ import annotations

import logging
from typing import Dict, List

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_SAMPLE_N = 4


class FaceDetector:
    def __init__(self) -> None:
        self._detector = None
        self._init_detector()

    def _init_detector(self) -> None:
        try:
            import mediapipe as mp
            self._detector = mp.solutions.face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.5
            )
        except ImportError:
            logger.warning("[FaceDetector] mediapipe not installed — face detection disabled")

    def detect(self, video_path: str, start_s: float, end_s: float) -> Dict:
        """
        Return {
            has_face: bool,
            face_count: int,
            face_size_ratio: float  (max face area / frame area),
        }
        """
        if self._detector is None:
            return {"has_face": False, "face_count": 0, "face_size_ratio": 0.0}

        frames = _sample(video_path, start_s, end_s, _SAMPLE_N)
        all_counts = []
        all_sizes = []

        for frame in frames:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = self._detector.process(rgb)
            if result.detections:
                count = len(result.detections)
                all_counts.append(count)
                for det in result.detections:
                    bb = det.location_data.relative_bounding_box
                    size = bb.width * bb.height
                    all_sizes.append(size)
            else:
                all_counts.append(0)

        has_face = any(c > 0 for c in all_counts)
        face_count = int(round(np.mean(all_counts))) if all_counts else 0
        face_size_ratio = float(max(all_sizes)) if all_sizes else 0.0

        return {
            "has_face": has_face,
            "face_count": face_count,
            "face_size_ratio": face_size_ratio,
        }


def _sample(video_path: str, start_s: float, end_s: float, n: int):
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
