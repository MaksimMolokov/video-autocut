"""
EyeStateAnalyzer — detects whether eyes are open or closed in a video segment.

Uses OpenCV Haar cascades (no heavy DL dependency required).
Returns eyes_open_score [0-1]: 1.0 = clearly open, 0.0 = closed / not detected.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class EyeStateResult:
    eyes_open_score: float      # 0-1; 1=open, 0=closed/not found
    eyes_detected: bool
    eye_count: int
    face_count: int


class EyeStateAnalyzer:
    """Analyze eye state across key frames of a segment."""

    def __init__(self, sample_frames: int = 3):
        self._n = sample_frames
        self._face_cascade = None
        self._eye_cascade  = None

    def analyze(self, video_path: str, start_s: float, end_s: float) -> EyeStateResult:
        face_cc = self._get_face_cascade()
        eye_cc  = self._get_eye_cascade()
        if face_cc is None or eye_cc is None:
            return EyeStateResult(0.5, False, 0, 0)

        frames = _sample_frames(video_path, start_s, end_s, self._n)
        if not frames:
            return EyeStateResult(0.5, False, 0, 0)

        total_faces = 0
        eyes_open_count = 0
        eyes_detected_count = 0

        for frame in frames:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            faces = face_cc.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
            if len(faces) == 0:
                continue
            total_faces += len(faces)
            for (x, y, fw, fh) in faces:
                roi = gray[y:y+fh, x:x+fw]
                # Only look at the upper half of face for eyes
                upper = roi[:fh//2, :]
                eyes = eye_cc.detectMultiScale(upper, 1.05, 3, minSize=(10, 10))
                if len(eyes) >= 2:
                    eyes_open_count += 1
                    eyes_detected_count += 1
                elif len(eyes) == 1:
                    eyes_detected_count += 1
                    eyes_open_count += 0.5  # partial credit

        if total_faces == 0:
            return EyeStateResult(0.5, False, 0, 0)

        score = eyes_open_count / total_faces
        return EyeStateResult(
            eyes_open_score = round(float(min(1.0, score)), 4),
            eyes_detected   = eyes_detected_count > 0,
            eye_count       = eyes_detected_count,
            face_count      = total_faces,
        )

    def _get_face_cascade(self):
        if self._face_cascade is None:
            try:
                path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                cc = cv2.CascadeClassifier(path)
                self._face_cascade = cc if not cc.empty() else None
            except Exception:
                self._face_cascade = None
        return self._face_cascade

    def _get_eye_cascade(self):
        if self._eye_cascade is None:
            try:
                path = cv2.data.haarcascades + "haarcascade_eye.xml"
                cc = cv2.CascadeClassifier(path)
                self._eye_cascade = cc if not cc.empty() else None
            except Exception:
                self._eye_cascade = None
        return self._eye_cascade


def _sample_frames(video_path: str, start_s: float, end_s: float,
                   n: int) -> List[np.ndarray]:
    dur = max(0.5, end_s - start_s)
    frames = []
    try:
        cap = cv2.VideoCapture(video_path)
        for i in range(n):
            t = start_s + dur * (i + 0.5) / n
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if ret:
                frames.append(frame)
        cap.release()
    except Exception:
        pass
    return frames
