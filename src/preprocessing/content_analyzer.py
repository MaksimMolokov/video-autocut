"""Content analysis: face detection, pose estimation, saliency (Level 2)."""

import logging
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

from .clip_scorer import ContentMetrics
from .scene_detector import Scene

logger = logging.getLogger(__name__)

_face_detector = None
_pose_detector = None
_saliency = None


def _get_face_detector():
    global _face_detector
    if _face_detector is None:
        import mediapipe as mp
        _face_detector = mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.5,
        )
    return _face_detector


def _get_pose_detector():
    global _pose_detector
    if _pose_detector is None:
        import mediapipe as mp
        _pose_detector = mp.solutions.pose.Pose(
            model_complexity=0,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
            static_image_mode=True,
        )
    return _pose_detector


def _get_saliency():
    global _saliency
    if _saliency is None:
        _saliency = cv2.saliency.StaticSaliencySpectralResidual_create()
    return _saliency


class ContentAnalyzer:
    """Analyze semantic content of a video scene: faces, people, subjects."""

    def __init__(self, n_frames: int = 3):
        self.n_frames = n_frames

    def analyze(self, video_path: str, scene: Scene) -> ContentMetrics:
        frames = self._sample_frames(video_path, scene.start_s, scene.end_s)
        if not frames:
            return ContentMetrics()
        return self._analyze_frames(frames)

    def analyze_frames(self, frames: List[np.ndarray]) -> ContentMetrics:
        return self._analyze_frames(frames)

    # ------------------------------------------------------------------

    def _sample_frames(
        self, video_path: str, start_s: float, end_s: float
    ) -> List[np.ndarray]:
        duration = end_s - start_s
        if duration <= 0:
            return []
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = min(self.n_frames, max(1, int(duration * fps)))
        timestamps = [
            start_s + duration * (i + 1) / (n + 1)
            for i in range(n)
        ]
        frames = []
        for ts in timestamps:
            cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
        cap.release()
        return frames

    def _analyze_frames(self, frames: List[np.ndarray]) -> ContentMetrics:
        face_results = [self._detect_face(f) for f in frames]
        pose_results = [self._detect_pose(f) for f in frames]
        sal_results = [self._detect_saliency(f) for f in frames]
        crop_results = [self._crop_suitability_9_16(f) for f in frames]

        # Aggregate over frames
        has_face = any(r['has_face'] for r in face_results)
        face_area = max((r['face_area_ratio'] for r in face_results), default=0.0)
        face_count = max((r.get('face_count', 0) for r in face_results), default=0)
        has_person = any(r for r in pose_results)
        has_subject = any(r for r in sal_results)
        crop_9_16 = float(np.mean(crop_results)) if crop_results else 0.5

        scene_type = _classify_shot_type(face_area, has_face, has_subject)

        return ContentMetrics(
            has_face=has_face,
            face_area_ratio=round(face_area, 4),
            has_person=has_person,
            has_subject=has_subject,
            scene_type=scene_type,
            crop_9_16=round(crop_9_16, 3),
        )

    # ------------------------------------------------------------------
    # Per-frame detectors
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_face(frame: np.ndarray) -> dict:
        try:
            det = _get_face_detector()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = det.process(rgb)
            if not results.detections:
                return {'has_face': False, 'face_area_ratio': 0.0, 'face_count': 0}
            max_det = max(
                results.detections,
                key=lambda d: d.location_data.relative_bounding_box.width *
                              d.location_data.relative_bounding_box.height,
            )
            bbox = max_det.location_data.relative_bounding_box
            area = bbox.width * bbox.height
            return {
                'has_face': True,
                'face_area_ratio': float(max(0.0, area)),
                'face_count': len(results.detections),
            }
        except Exception as e:
            logger.debug(f'[ContentAnalyzer] Face detection error: {e}')
            return {'has_face': False, 'face_area_ratio': 0.0, 'face_count': 0}

    @staticmethod
    def _detect_pose(frame: np.ndarray) -> bool:
        try:
            det = _get_pose_detector()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = det.process(rgb)
            return bool(results.pose_landmarks)
        except Exception as e:
            logger.debug(f'[ContentAnalyzer] Pose detection error: {e}')
            return False

    @staticmethod
    def _detect_saliency(frame: np.ndarray) -> bool:
        try:
            sal = _get_saliency()
            ok, sal_map = sal.computeSaliency(frame)
            if not ok:
                return False
            return float(sal_map.max()) > 0.5
        except Exception as e:
            logger.debug(f'[ContentAnalyzer] Saliency error: {e}')
            return False

    @staticmethod
    def _crop_suitability_9_16(frame: np.ndarray) -> float:
        """Fraction of saliency within the central 9:16 crop zone."""
        try:
            h, w = frame.shape[:2]
            target_w = int(h * 9 / 16)
            if target_w >= w:
                return 1.0
            sal = _get_saliency()
            ok, sal_map = sal.computeSaliency(frame)
            if not ok:
                return 0.5
            total = float(sal_map.sum())
            if total < 1e-6:
                return 0.5
            x_start = (w - target_w) // 2
            x_end = x_start + target_w
            crop_sal = float(sal_map[:, x_start:x_end].sum())
            return min(1.0, crop_sal / total)
        except Exception:
            return 0.5


def _classify_shot_type(
    face_area: float, has_face: bool, has_subject: bool
) -> str:
    if has_face:
        if face_area > 0.15:
            return 'close'
        if face_area > 0.04:
            return 'medium'
        return 'wide'
    if has_subject:
        return 'medium'
    return 'wide'
