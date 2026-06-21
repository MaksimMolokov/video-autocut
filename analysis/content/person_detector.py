"""
PersonDetector — detect human presence in video segments (TASK-031).

Uses MediaPipe Pose or fallback to HOG person detector.
Determines if a person is present and whether they are the main subject.
"""
from __future__ import annotations

import logging
from typing import Dict

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class PersonDetector:
    def __init__(self) -> None:
        self._mp_pose = None
        self._hog = None
        self._init()

    def _init(self) -> None:
        try:
            import mediapipe as mp
            self._mp_pose = mp.solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=0,
                min_detection_confidence=0.5,
            )
        except ImportError:
            logger.info("[PersonDetector] mediapipe unavailable, using HOG fallback")
            self._hog = cv2.HOGDescriptor()
            self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def detect(self, video_path: str, start_s: float, end_s: float) -> Dict:
        """
        Return {
            has_person: bool,
            person_count: int,
            person_is_main_subject: bool,
        }
        """
        frames = _sample(video_path, start_s, end_s, n=3)
        counts = []

        for frame in frames:
            if self._mp_pose:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = self._mp_pose.process(rgb)
                counts.append(1 if result.pose_landmarks else 0)
            elif self._hog:
                rects, _ = self._hog.detectMultiScale(frame, winStride=(8, 8), padding=(4, 4), scale=1.05)
                counts.append(len(rects))
            else:
                counts.append(0)

        person_count = int(round(np.mean(counts))) if counts else 0
        has_person = person_count > 0

        # Simple heuristic: person is "main subject" if detected in most frames
        is_main = sum(c > 0 for c in counts) >= len(counts) * 0.6

        return {
            "has_person": has_person,
            "person_count": person_count,
            "person_is_main_subject": is_main,
        }


def _sample(video_path, start_s, end_s, n=3):
    cap = cv2.VideoCapture(video_path)
    dur = max(end_s - start_s, 0.1)
    frames = []
    for i in range(n):
        t = start_s + dur * (i + 0.5) / n
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, f = cap.read()
        if ret and f is not None:
            frames.append(f)
    cap.release()
    return frames
