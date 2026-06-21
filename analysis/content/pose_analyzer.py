"""
PoseAnalyzer — estimates human pose quality in a video segment.

Uses MediaPipe Pose if available, falls back to person bounding-box heuristics.
Returns PoseResult with pose_quality_score, body_crop_quality_score, etc.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PoseResult:
    pose_quality_score: float           # [0-1] overall
    body_crop_quality_score: float      # is person well-framed?
    main_person_area_ratio: float       # fraction of frame occupied
    head_visible: bool
    full_body_visible: bool
    bad_crop: bool                      # True if head/feet cut off badly
    reject_reasons: List[str]


class PoseAnalyzer:
    """
    Analyze human pose and framing quality for a video segment.

    Uses MediaPipe Pose when available; falls back to face+body heuristics.
    """

    def __init__(self, sample_frames: int = 3):
        self._n = sample_frames
        self._mp_pose = None

    def analyze(self, video_path: str, start_s: float, end_s: float) -> PoseResult:
        frames = _sample_frames(video_path, start_s, end_s, self._n)
        if not frames:
            return _default_result()

        results = [self._analyze_frame(f) for f in frames]
        return _merge_results(results)

    def _analyze_frame(self, frame: np.ndarray) -> PoseResult:
        mp_pose = self._get_mp_pose()
        if mp_pose is not None:
            return self._analyze_mediapipe(frame, mp_pose)
        return self._analyze_heuristic(frame)

    def _analyze_mediapipe(self, frame: np.ndarray, pose) -> PoseResult:
        try:
            import mediapipe as mp
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = pose.process(rgb)

            if not res.pose_landmarks:
                return _default_result()

            lm = res.pose_landmarks.landmark
            MPLandmark = mp.solutions.pose.PoseLandmark

            # Key landmarks
            nose    = lm[MPLandmark.NOSE]
            lhip    = lm[MPLandmark.LEFT_HIP]
            rhip    = lm[MPLandmark.RIGHT_HIP]
            lankle  = lm[MPLandmark.LEFT_ANKLE]
            rankle  = lm[MPLandmark.RIGHT_ANKLE]
            lshoulder = lm[MPLandmark.LEFT_SHOULDER]
            rshoulder = lm[MPLandmark.RIGHT_SHOULDER]

            # Visibility checks
            head_vis = nose.visibility > 0.5
            feet_vis = (lankle.visibility + rankle.visibility) / 2 > 0.4

            # Bounding box of all landmarks
            xs = [l.x for l in lm]
            ys = [l.y for l in lm]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            area_ratio = (x2 - x1) * (y2 - y1)

            # Bad crop: head near top or feet near bottom
            head_cut = head_vis and nose.y < 0.05
            feet_cut = feet_vis and (lankle.y > 0.95 or rankle.y > 0.95)

            # Body crop quality: person should occupy 20-70% of frame vertically
            vert_span = y2 - y1
            crop_ok = 0.15 <= vert_span <= 0.85

            reject = []
            if head_cut:
                reject.append("head_cut_off")
            if feet_cut and not feet_vis:
                pass  # waist shot is fine
            if area_ratio < 0.04:
                reject.append("person_too_small")

            # Pose quality: is body upright?
            shoulder_level = abs(lshoulder.y - rshoulder.y)
            hip_level = abs(lhip.y - rhip.y)
            pose_q = max(0.0, 1.0 - (shoulder_level + hip_level) * 4)

            # Body crop quality
            if crop_ok and not head_cut:
                crop_q = min(1.0, 0.6 + area_ratio * 0.8)
            else:
                crop_q = max(0.0, 0.4 - len(reject) * 0.15)

            return PoseResult(
                pose_quality_score       = round(float(pose_q), 4),
                body_crop_quality_score  = round(float(crop_q), 4),
                main_person_area_ratio   = round(float(area_ratio), 4),
                head_visible             = bool(head_vis),
                full_body_visible        = bool(feet_vis),
                bad_crop                 = bool(head_cut or (not crop_ok)),
                reject_reasons           = reject,
            )
        except Exception as exc:
            logger.debug(f"[PoseAnalyzer] mediapipe failed: {exc}")
            return _default_result()

    def _analyze_heuristic(self, frame: np.ndarray) -> PoseResult:
        """Fallback: detect face + estimate body bounding box."""
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = frame.shape[:2]
            cc_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            cc = cv2.CascadeClassifier(cc_path)
            faces = cc.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))

            if len(faces) == 0:
                return _default_result()

            # Use the largest face
            fx, fy, fw, fh = sorted(faces, key=lambda f: f[2]*f[3])[-1]
            face_top_ratio = fy / h
            face_size_ratio = (fw * fh) / (w * h)

            head_cut = face_top_ratio < 0.03
            body_est_bottom = fy + fh * 5  # rough body extent
            body_ratio = min(1.0, body_est_bottom / h)

            reject = []
            if head_cut:
                reject.append("head_cut_off")
            if face_size_ratio < 0.005:
                reject.append("person_too_small")

            crop_q = 0.7 if (not head_cut and face_size_ratio > 0.01) else 0.3

            return PoseResult(
                pose_quality_score       = 0.65 if not reject else 0.35,
                body_crop_quality_score  = crop_q,
                main_person_area_ratio   = round(float(face_size_ratio * 5), 4),
                head_visible             = not head_cut,
                full_body_visible        = False,
                bad_crop                 = bool(head_cut),
                reject_reasons           = reject,
            )
        except Exception:
            return _default_result()

    def _get_mp_pose(self):
        if self._mp_pose is None:
            try:
                import mediapipe as mp
                self._mp_pose = mp.solutions.pose.Pose(
                    static_image_mode=True,
                    model_complexity=0,
                    min_detection_confidence=0.5,
                )
            except Exception:
                self._mp_pose = False  # sentinel: unavailable
        return self._mp_pose if self._mp_pose is not False else None


def _default_result() -> PoseResult:
    return PoseResult(
        pose_quality_score=0.5, body_crop_quality_score=0.5,
        main_person_area_ratio=0.0, head_visible=True,
        full_body_visible=False, bad_crop=False, reject_reasons=[],
    )


def _merge_results(results: List[PoseResult]) -> PoseResult:
    if not results:
        return _default_result()
    pose_q = float(np.mean([r.pose_quality_score for r in results]))
    crop_q = float(np.mean([r.body_crop_quality_score for r in results]))
    area   = float(np.mean([r.main_person_area_ratio for r in results]))
    head_v = any(r.head_visible for r in results)
    full_v = any(r.full_body_visible for r in results)
    bad_c  = sum(1 for r in results if r.bad_crop) > len(results) // 2
    all_rej: List[str] = []
    for r in results:
        all_rej.extend(r.reject_reasons)
    rej = list(dict.fromkeys(all_rej))  # unique, preserve order
    return PoseResult(
        pose_quality_score=round(pose_q, 4), body_crop_quality_score=round(crop_q, 4),
        main_person_area_ratio=round(area, 4), head_visible=head_v,
        full_body_visible=full_v, bad_crop=bad_c, reject_reasons=rej,
    )


def _sample_frames(video_path: str, start_s: float, end_s: float,
                   n: int) -> List[np.ndarray]:
    dur, frames = max(0.5, end_s - start_s), []
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
