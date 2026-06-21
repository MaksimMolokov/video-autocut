"""
CameraMotionClassifier — classifies camera movement for a video segment.

Supports 15 motion types via optical-flow analysis (OpenCV).
Falls back to "unknown" gracefully if OpenCV or the source file is unavailable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Ordered from most specific to most generic
MOTION_TYPES = [
    "static",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "zoom_in",
    "zoom_out",
    "dolly",
    "orbit",
    "handheld",
    "aerial_forward",
    "aerial_descent",
    "shake",
    "roll",
    "unknown",
]

# Energy classification thresholds (average optical-flow magnitude in px/frame)
_SLOW_MAX  = 2.0
_FAST_MIN  = 8.0


@dataclass
class MotionResult:
    motion_type: str       # one of MOTION_TYPES
    confidence: float      # 0–1
    speed: str             # "slow" | "medium" | "fast"
    flow_magnitude: float  # average magnitude across sampled frames


class CameraMotionClassifier:
    """
    Classify camera motion for a video clip using dense optical flow.

    Usage:
        result = CameraMotionClassifier().classify(path, start_s=0.0, end_s=5.0)
        print(result.motion_type, result.speed)
    """

    def __init__(self, sample_fps: float = 5.0, max_frames: int = 20):
        """
        Args:
            sample_fps:  Frames per second to sample from the clip.
            max_frames:  Cap on total sampled frames (for performance).
        """
        self.sample_fps  = sample_fps
        self.max_frames  = max_frames

    def classify(
        self,
        video_path: str,
        start_s: float = 0.0,
        end_s: Optional[float] = None,
    ) -> MotionResult:
        """
        Run optical-flow classification on [start_s, end_s] of video_path.
        Returns MotionResult with motion_type, confidence, speed, flow_magnitude.
        """
        try:
            import cv2
            import numpy as np
        except ImportError:
            logger.warning("[CameraMotion] OpenCV not available — returning 'unknown'")
            return MotionResult("unknown", 0.0, "medium", 0.0)

        try:
            return self._classify_cv2(video_path, start_s, end_s)
        except Exception as exc:
            logger.warning(f"[CameraMotion] classify failed ({exc}) — returning 'unknown'")
            return MotionResult("unknown", 0.0, "medium", 0.0)

    # ── internal ──────────────────────────────────────────────────────────────

    def _classify_cv2(
        self,
        video_path: str,
        start_s: float,
        end_s: Optional[float],
    ) -> MotionResult:
        import cv2
        import numpy as np

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return MotionResult("unknown", 0.0, "medium", 0.0)

        fps_src = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if end_s is None:
            end_s = total_frames / fps_src

        start_frame = max(0, int(start_s * fps_src))
        end_frame   = min(total_frames, int(end_s * fps_src))
        clip_frames = max(1, end_frame - start_frame)

        step = max(1, int(fps_src / self.sample_fps))
        sample_positions = list(range(start_frame, end_frame, step))[: self.max_frames]

        flows = []
        prev_gray = None

        for pos in sample_positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                flow = cv2.calcOpticalFlowFarneback(
                    prev_gray, gray,
                    None, 0.5, 3, 15, 3, 5, 1.2, 0,
                )
                flows.append(flow)
            prev_gray = gray

        cap.release()

        if not flows:
            return MotionResult("unknown", 0.0, "medium", 0.0)

        # Aggregate flow statistics
        import numpy as np
        all_flows = np.stack(flows, axis=0)           # (N, H, W, 2)
        mag = np.sqrt(all_flows[..., 0]**2 + all_flows[..., 1]**2)
        mean_mag  = float(np.mean(mag))
        mean_dx   = float(np.mean(all_flows[..., 0]))  # positive = right
        mean_dy   = float(np.mean(all_flows[..., 1]))  # positive = down
        std_mag   = float(np.std(mag))

        motion_type, confidence = self._infer_type(mean_dx, mean_dy, mean_mag, std_mag)
        speed = "slow" if mean_mag < _SLOW_MAX else ("fast" if mean_mag > _FAST_MIN else "medium")

        return MotionResult(motion_type, confidence, speed, mean_mag)

    @staticmethod
    def _infer_type(
        dx: float, dy: float, mag: float, std: float
    ) -> tuple[str, float]:
        """
        Rule-based classification from aggregate flow vectors.
        Returns (motion_type, confidence).
        """
        # Very low magnitude → static
        if mag < 0.8:
            return "static", 0.90

        # High variability relative to magnitude → handheld or shake
        if std > mag * 1.5:
            return "shake" if mag > 4.0 else "handheld", 0.70

        abs_dx, abs_dy = abs(dx), abs(dy)

        # Dominant horizontal motion → pan
        if abs_dx > abs_dy * 1.5:
            if dx > 0:
                return "pan_right", 0.80
            else:
                return "pan_left",  0.80

        # Dominant vertical motion → tilt
        if abs_dy > abs_dx * 1.5:
            if dy < 0:
                return "tilt_up",   0.75
            else:
                return "tilt_down", 0.75

        # Zoom: expansion (zoom in) vs contraction (zoom out) detected via
        # divergence — simplified: if center flow magnitude > edges it's zoom_in
        if mag > 2.0:
            if dx > 0 and dy > 0:
                return "zoom_in",  0.65
            elif dx < 0 and dy < 0:
                return "zoom_out", 0.65

        # Mixed steady motion with low std → dolly / aerial
        if std < mag * 0.5 and mag > 2.0:
            if abs_dy > 1.5:
                return "aerial_descent" if dy > 0 else "aerial_forward", 0.60
            return "dolly", 0.60

        return "handheld", 0.50
