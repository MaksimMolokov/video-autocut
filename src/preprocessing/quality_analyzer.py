"""Technical quality metrics: sharpness, brightness, stability, motion, defects."""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import cv2
import numpy as np

from .scene_detector import Scene

logger = logging.getLogger(__name__)

# Rejection thresholds (configurable via constructor)
DEFAULT_THRESHOLDS = {
    'sharpness':   0.08,
    'brightness_lo': 0.10,
    'brightness_hi': 0.94,
    'stability':   0.15,
    'duration':    0.80,
    'edge_density': 0.015,
    'overexpose_ratio': 0.15,
}


@dataclass
class FrameMetrics:
    sharpness: float = 0.0
    brightness: float = 0.0
    overexpose: bool = False
    is_black: bool = False
    is_corrupt: bool = False
    edge_density: float = 0.0


@dataclass
class TechMetrics:
    sharpness: float = 0.5
    brightness: float = 0.5
    contrast: float = 0.5
    motion: float = 0.2
    stability: float = 0.8
    action: float = 0.2
    calm: float = 0.7
    is_black: bool = False
    is_corrupt: bool = False
    overexpose: bool = False
    is_empty: bool = False
    # Rejection flag — set when any hard threshold is violated
    is_rejected: bool = False
    reject_reason: str = ''


class QualityAnalyzer:
    def __init__(self, thresholds: Optional[dict] = None, n_frames: int = 8):
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.n_frames = n_frames

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, video_path: str, scene: Scene) -> TechMetrics:
        frames = self._sample_frames(video_path, scene.start_s, scene.end_s)
        if not frames:
            return TechMetrics(is_rejected=True, reject_reason='no_frames')
        return self._compute_metrics(frames, scene)

    def analyze_frame(self, frame: np.ndarray) -> FrameMetrics:
        return self._analyze_frame(frame)

    # ------------------------------------------------------------------
    # Frame sampling
    # ------------------------------------------------------------------

    def _sample_frames(
        self, video_path: str, start_s: float, end_s: float
    ) -> List[np.ndarray]:
        duration = end_s - start_s
        if duration <= 0:
            return []

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.warning(f'[QualityAnalyzer] Cannot open {video_path}')
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = min(self.n_frames, max(2, int(duration * fps)))
        # Skip first and last frame to avoid transitions
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

    # ------------------------------------------------------------------
    # Per-frame metrics
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_frame(frame: np.ndarray) -> FrameMetrics:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Sharpness: Laplacian variance
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharpness = float(min(1.0, laplacian_var / 500.0))

        # Brightness: HSV value channel
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        brightness = float(hsv[:, :, 2].mean()) / 255.0

        # Overexposure
        overexposed_ratio = float((frame > 250).mean())
        overexpose = overexposed_ratio > DEFAULT_THRESHOLDS['overexpose_ratio']

        # Defect flags
        is_black = brightness < 0.04
        is_corrupt = sharpness < 0.02 and brightness < 0.10

        # Edge density (emptiness detection)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(edges.mean()) / 255.0

        return FrameMetrics(
            sharpness=sharpness,
            brightness=brightness,
            overexpose=overexpose,
            is_black=is_black,
            is_corrupt=is_corrupt,
            edge_density=edge_density,
        )

    # ------------------------------------------------------------------
    # Optical flow (stability / motion)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_optical_flow(frame1: np.ndarray, frame2: np.ndarray):
        g1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(
            g1, g2, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
        instability = float(mag.std())
        motion = float(mag.mean()) / 10.0
        stability = float(max(0.0, 1.0 - instability / 10.0))
        return stability, motion

    # ------------------------------------------------------------------
    # Aggregate metrics
    # ------------------------------------------------------------------

    def _compute_metrics(self, frames: List[np.ndarray], scene: Scene) -> TechMetrics:
        per_frame = [self._analyze_frame(f) for f in frames]

        sharpnesses = [m.sharpness for m in per_frame]
        brightnesses = [m.brightness for m in per_frame]
        edge_densities = [m.edge_density for m in per_frame]

        sharpness = float(np.median(sharpnesses))
        brightness = float(np.mean(brightnesses))
        edge_density = float(np.mean(edge_densities))
        overexpose = any(m.overexpose for m in per_frame)
        is_black = all(b < 0.05 for b in brightnesses)
        is_corrupt = float(np.median(sharpnesses)) < 0.02

        # Contrast: std of gray pixel values (first frame)
        gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
        contrast = float(min(1.0, gray.std() / 64.0))

        # Optical flow across consecutive pairs
        stabilities, motions = [], []
        for i in range(len(frames) - 1):
            stab, mot = self._compute_optical_flow(frames[i], frames[i + 1])
            stabilities.append(stab)
            motions.append(mot)

        stability = float(np.mean(stabilities)) if stabilities else 1.0
        motion = float(np.mean(motions)) if motions else 0.0
        action = motion * (1.0 - stability * 0.5)
        calm = stability * (1.0 - motion * 0.5)
        is_empty = edge_density < self.thresholds['edge_density'] and brightness < 0.90

        # Rejection check
        reject_reason = ''
        t = self.thresholds
        if is_black:
            reject_reason = 'black_frame'
        elif is_corrupt:
            reject_reason = 'corrupt'
        elif sharpness < t['sharpness']:
            reject_reason = f'blurry ({sharpness:.3f})'
        elif brightness < t['brightness_lo']:
            reject_reason = f'dark ({brightness:.3f})'
        elif brightness > t['brightness_hi']:
            reject_reason = f'overexposed ({brightness:.3f})'
        elif stability < t['stability']:
            reject_reason = f'unstable ({stability:.3f})'
        elif scene.duration_s < t['duration']:
            reject_reason = f'too_short ({scene.duration_s:.2f}s)'
        elif is_empty:
            reject_reason = 'empty_frame'

        return TechMetrics(
            sharpness=round(sharpness, 4),
            brightness=round(brightness, 4),
            contrast=round(contrast, 4),
            motion=round(min(1.0, motion), 4),
            stability=round(stability, 4),
            action=round(min(1.0, action), 4),
            calm=round(min(1.0, calm), 4),
            is_black=is_black,
            is_corrupt=is_corrupt,
            overexpose=overexpose,
            is_empty=is_empty,
            is_rejected=bool(reject_reason),
            reject_reason=reject_reason,
        )
