"""Technical quality metrics: sharpness, brightness, stability, motion, defects.

Algorithm notes (Step 2 material selection):
  Sharpness — Tenengrad (Sobel gradient magnitude mean), normalized by 200.
    More noise-resistant than Laplacian variance (Santos 1997).
  Colorfulness — Hasler & Süsstrunk (2003): 95.3% correlation with human ratings.
  Complexity — Shannon entropy of grayscale histogram, normalized by 8 bits.
  Camera motion type — angular coherence of optical flow vectors:
    |mean(exp(i*angle))| ≈ 1 for coherent pan/tilt, ≈ 0 for shake.

  v3 additions:
  Composition (Rule-of-Thirds) — Canny edges weighted by proximity to the 4 third-lines.
    Well-composed shots have strong edges at x=W/3, x=2W/3, y=H/3, y=2H/3 (Birkhoff 1933;
    applied to photography by Krages 2005). Gaussian-weighted mask on the four lines.
  Temporal Coherence — mean histogram intersection between consecutive frame pairs.
    Low value = colour distribution changes sharply inside the fragment = accidental cut
    or severe lighting change. Flags bad fragments before they reach the montage editor.
  Motion Saliency — center-weighted optical flow magnitude.
    High value = motion concentrated in frame center = subject likely in frame.
    Low value = uniform/peripheral motion = panning landscape shot.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from .scene_detector import Scene

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = {
    # Hard-reject thresholds — only truly broken/unreadable frames.
    # These are intentionally lenient so that action/drone/handheld footage
    # is not silently discarded.  The UMS scorer (fragment_scorer.py) is
    # responsible for quality ranking; this layer only gates out garbage.
    'sharpness':         0.04,   # was 0.08 — motion blur in drone/action footage is normal
    'brightness_lo':     0.05,   # was 0.10 — allow dark cinematic shots
    'brightness_hi':     0.97,   # was 0.94 — allow near-overexposed shots
    'stability':         0.05,   # was 0.15 — only reject extreme uncontrolled shake
    'duration':          0.80,
    'edge_density':      0.008,  # was 0.015 — allow low-contrast shots
    'overexpose_ratio':  0.25,   # was 0.15
}


@dataclass
class FrameMetrics:
    sharpness:         float = 0.0
    brightness:        float = 0.0
    colorfulness:      float = 0.0
    complexity:        float = 0.0
    composition_score: float = 0.0
    overexpose:        bool  = False
    is_black:          bool  = False
    is_corrupt:        bool  = False
    edge_density:      float = 0.0


@dataclass
class TechMetrics:
    sharpness:          float = 0.5
    brightness:         float = 0.5
    contrast:           float = 0.5
    motion:             float = 0.2
    stability:          float = 0.8
    action:             float = 0.2
    calm:               float = 0.7
    colorfulness:       float = 0.0
    complexity:         float = 0.0
    camera_motion_type: str   = ''
    composition_score:  float = 0.0
    temporal_coherence: float = 1.0
    saliency_score:     float = 0.0
    is_black:           bool  = False
    is_corrupt:         bool  = False
    overexpose:         bool  = False
    is_empty:           bool  = False
    is_rejected:        bool  = False
    reject_reason:      str   = ''


class QualityAnalyzer:
    def __init__(self, thresholds: Optional[dict] = None, n_frames: int = 8):
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.n_frames = n_frames
        # Pre-build thirds weight mask (lazily, per-frame-size)
        self._thirds_cache: dict = {}

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
    # Rule-of-Thirds composition weight mask
    # ------------------------------------------------------------------

    def _get_thirds_mask(self, h: int, w: int) -> np.ndarray:
        """Gaussian-weighted mask high on the four rule-of-thirds lines."""
        key = (h, w)
        if key not in self._thirds_cache:
            sigma_h = h * 0.06   # ~6% of frame height bandwidth per line
            sigma_w = w * 0.06
            ys = np.arange(h, dtype=np.float32)
            xs = np.arange(w, dtype=np.float32)
            # Vertical weight: peaks at y=H/3 and y=2H/3
            wy = (np.exp(-0.5 * ((ys - h / 3) / sigma_h) ** 2) +
                  np.exp(-0.5 * ((ys - 2 * h / 3) / sigma_h) ** 2))
            # Horizontal weight: peaks at x=W/3 and x=2W/3
            wx = (np.exp(-0.5 * ((xs - w / 3) / sigma_w) ** 2) +
                  np.exp(-0.5 * ((xs - 2 * w / 3) / sigma_w) ** 2))
            # 2D mask: union (max) of horizontal and vertical line weights
            mask = np.maximum(wy[:, np.newaxis], wx[np.newaxis, :])
            self._thirds_cache[key] = mask.astype(np.float32)
        return self._thirds_cache[key]

    # ------------------------------------------------------------------
    # Per-frame metrics
    # ------------------------------------------------------------------

    def _analyze_frame(self, frame: np.ndarray) -> FrameMetrics:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Tenengrad sharpness: mean gradient magnitude (Sobel), normalized
        sx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        tenengrad = float(np.mean(np.sqrt(sx ** 2 + sy ** 2)))
        sharpness = float(min(1.0, tenengrad / 200.0))

        # Brightness: HSV value channel mean
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        brightness = float(hsv[:, :, 2].mean()) / 255.0

        # Overexposure
        overexposed_ratio = float((frame > 250).mean())
        overexpose = overexposed_ratio > DEFAULT_THRESHOLDS['overexpose_ratio']

        # Defect flags
        is_black = brightness < 0.04
        is_corrupt = sharpness < 0.02 and brightness < 0.10

        # Edge density
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(edges.mean()) / 255.0

        # Colorfulness — Hasler & Süsstrunk 2003
        R = frame[:, :, 2].astype(np.float32)
        G = frame[:, :, 1].astype(np.float32)
        B = frame[:, :, 0].astype(np.float32)
        rg = R - G
        yb = 0.5 * (R + G) - B
        cf_raw = (
            float(np.sqrt(rg.std() ** 2 + yb.std() ** 2))
            + 0.3 * float(np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
        )
        colorfulness = float(min(1.0, cf_raw / 100.0))

        # Shannon entropy of grayscale histogram → visual complexity
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        hist_sum = hist.sum()
        if hist_sum > 0:
            p = hist[hist > 0] / hist_sum
            entropy = float(-np.sum(p * np.log2(p)))
        else:
            entropy = 0.0
        complexity = float(min(1.0, entropy / 8.0))

        # Rule-of-Thirds composition — Canny edges aligned to thirds lines
        h, w = gray.shape
        mask = self._get_thirds_mask(h, w)
        edges_f = edges.astype(np.float32) / 255.0
        edge_sum = float(edges_f.sum()) + 1e-6
        composition_score = float(min(1.0, (edges_f * mask).sum() / edge_sum))

        return FrameMetrics(
            sharpness=sharpness,
            brightness=brightness,
            colorfulness=colorfulness,
            complexity=complexity,
            composition_score=composition_score,
            overexpose=overexpose,
            is_black=is_black,
            is_corrupt=is_corrupt,
            edge_density=edge_density,
        )

    # ------------------------------------------------------------------
    # Optical flow (stability / motion / angular coherence)
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_optical_flow(
        frame1: np.ndarray, frame2: np.ndarray
    ) -> Tuple[float, float, float, float, float, float, np.ndarray]:
        """
        Returns (stability, motion, coherence, mean_dx, mean_dy, instability, mag_map).

        mag_map — 2D array of flow magnitudes (used for saliency scoring).
        coherence — angular coherence |mean(exp(i*angle))|:
          ≈1 = all vectors same direction (intentional pan/tilt)
          ≈0 = random directions (camera shake)
        """
        g1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(
            g1, g2, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        fx, fy = flow[..., 0], flow[..., 1]
        mag = np.sqrt(fx ** 2 + fy ** 2)

        instability = float(mag.std())
        motion = float(mag.mean()) / 10.0
        stability = float(max(0.0, 1.0 - instability / 10.0))

        # Angular coherence via circular mean (magnitude-masked)
        angles = np.arctan2(fy, fx)
        moving = mag > 0.1
        if moving.any():
            cos_mean = float(np.mean(np.cos(angles[moving])))
            sin_mean = float(np.mean(np.sin(angles[moving])))
            coherence = float(np.sqrt(cos_mean ** 2 + sin_mean ** 2))
        else:
            coherence = 1.0

        mean_dx = float(np.mean(fx))
        mean_dy = float(np.mean(fy))

        return stability, motion, coherence, mean_dx, mean_dy, instability, mag

    # ------------------------------------------------------------------
    # Camera motion type classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_camera_motion(
        mean_dx: float, mean_dy: float, coherence: float, instability: float
    ) -> str:
        mean_mag = float(np.sqrt(mean_dx ** 2 + mean_dy ** 2))
        if mean_mag < 0.5 and instability < 1.5:
            return 'static'
        if coherence < 0.40:
            return 'shake'
        ax, ay = abs(mean_dx), abs(mean_dy)
        if ax > ay * 1.3:
            return 'pan_right' if mean_dx > 0 else 'pan_left'
        if ay > ax * 1.3:
            return 'tilt_up' if mean_dy > 0 else 'tilt_down'
        if ax >= ay:
            return 'pan_right' if mean_dx > 0 else 'pan_left'
        return 'tilt_up' if mean_dy > 0 else 'tilt_down'

    # ------------------------------------------------------------------
    # Temporal coherence (histogram intersection across frame pairs)
    # ------------------------------------------------------------------

    @staticmethod
    def _histogram_intersection(f1: np.ndarray, f2: np.ndarray) -> float:
        """Normalised histogram intersection [0–1]. 1 = identical colour distribution."""
        hist1 = cv2.calcHist([f1], [0, 1, 2], None, [16, 16, 16],
                             [0, 256, 0, 256, 0, 256]).flatten()
        hist2 = cv2.calcHist([f2], [0, 1, 2], None, [16, 16, 16],
                             [0, 256, 0, 256, 0, 256]).flatten()
        s1 = hist1.sum()
        s2 = hist2.sum()
        if s1 == 0 or s2 == 0:
            return 1.0
        h1n = hist1 / s1
        h2n = hist2 / s2
        return float(np.minimum(h1n, h2n).sum())

    # ------------------------------------------------------------------
    # Motion saliency — center-weighted flow magnitude
    # ------------------------------------------------------------------

    @staticmethod
    def _center_saliency(mag_map: np.ndarray) -> float:
        """
        Fraction of motion energy concentrated in the central region.
        Uses a 2D Gaussian weight centered on the frame. [0–1]
        """
        h, w = mag_map.shape
        if mag_map.sum() < 1e-6:
            return 0.0
        sigma_h = h * 0.30
        sigma_w = w * 0.30
        ys = np.arange(h, dtype=np.float32) - h / 2
        xs = np.arange(w, dtype=np.float32) - w / 2
        gauss_y = np.exp(-0.5 * (ys / sigma_h) ** 2)
        gauss_x = np.exp(-0.5 * (xs / sigma_w) ** 2)
        weight = gauss_y[:, np.newaxis] * gauss_x[np.newaxis, :]
        weighted = float((mag_map * weight).sum())
        total = float(mag_map.sum()) + 1e-6
        return float(min(1.0, weighted / total))

    # ------------------------------------------------------------------
    # Aggregate metrics
    # ------------------------------------------------------------------

    def _compute_metrics(self, frames: List[np.ndarray], scene: Scene) -> TechMetrics:
        per_frame = [self._analyze_frame(f) for f in frames]

        sharpness         = float(np.median([m.sharpness         for m in per_frame]))
        brightness        = float(np.mean(  [m.brightness        for m in per_frame]))
        edge_density      = float(np.mean(  [m.edge_density      for m in per_frame]))
        colorfulness      = float(np.mean(  [m.colorfulness      for m in per_frame]))
        complexity        = float(np.mean(  [m.complexity        for m in per_frame]))
        composition_score = float(np.mean(  [m.composition_score for m in per_frame]))
        overexpose        = any(m.overexpose for m in per_frame)
        is_black          = all(m.brightness < 0.05 for m in per_frame)
        is_corrupt        = sharpness < 0.02

        # Contrast: std of gray pixel values (first frame)
        gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
        contrast = float(min(1.0, gray.std() / 64.0))

        # Optical flow across consecutive frame pairs
        stabilities:   List[float]     = []
        motions:       List[float]     = []
        coherences:    List[float]     = []
        mean_dxs:      List[float]     = []
        mean_dys:      List[float]     = []
        instabilities: List[float]     = []
        mag_maps:      List[np.ndarray] = []

        for i in range(len(frames) - 1):
            stab, mot, coh, mdx, mdy, inst, mag = self._compute_optical_flow(
                frames[i], frames[i + 1]
            )
            stabilities.append(stab)
            motions.append(mot)
            coherences.append(coh)
            mean_dxs.append(mdx)
            mean_dys.append(mdy)
            instabilities.append(inst)
            mag_maps.append(mag)

        stability = float(np.mean(stabilities)) if stabilities else 1.0
        motion    = float(np.mean(motions))     if motions    else 0.0
        action    = motion * (1.0 - stability * 0.5)
        calm      = stability * (1.0 - motion * 0.5)
        is_empty  = edge_density < self.thresholds['edge_density'] and brightness < 0.90

        # Camera motion type
        if stabilities:
            camera_motion_type = self._classify_camera_motion(
                float(np.mean(mean_dxs)),
                float(np.mean(mean_dys)),
                float(np.mean(coherences)),
                float(np.mean(instabilities)),
            )
        else:
            camera_motion_type = 'static'

        # Temporal coherence — histogram intersection between all consecutive frame pairs
        hist_intersections = [
            self._histogram_intersection(frames[i], frames[i + 1])
            for i in range(len(frames) - 1)
        ]
        temporal_coherence = float(np.mean(hist_intersections)) if hist_intersections else 1.0

        # Motion saliency — center-weighted flow energy averaged over all pairs
        if mag_maps:
            saliency_per_pair = [self._center_saliency(m) for m in mag_maps]
            saliency_score = float(np.mean(saliency_per_pair))
        else:
            saliency_score = 0.0

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
            colorfulness=round(colorfulness, 4),
            complexity=round(complexity, 4),
            camera_motion_type=camera_motion_type,
            composition_score=round(composition_score, 4),
            temporal_coherence=round(temporal_coherence, 4),
            saliency_score=round(saliency_score, 4),
            is_black=is_black,
            is_corrupt=is_corrupt,
            overexpose=overexpose,
            is_empty=is_empty,
            is_rejected=bool(reject_reason),
            reject_reason=reject_reason,
        )
