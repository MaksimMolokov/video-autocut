"""
SceneDetector — shot boundary detection (TASK-020).

Supports multiple algorithms: scenedetect (content-aware) and
threshold-based histogram diff (fast fallback).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from infrastructure.config.config_manager import cfg

logger = logging.getLogger(__name__)

_ALGORITHMS = ("scenedetect", "histogram")


class SceneDetector:
    """Detect scene boundaries in a video file."""

    def __init__(
        self,
        algorithm: str = "scenedetect",
        sensitivity: float = 0.4,
    ) -> None:
        if algorithm not in _ALGORITHMS:
            raise ValueError(f"algorithm must be one of {_ALGORITHMS}")
        self.algorithm = algorithm
        self.sensitivity = sensitivity  # 0=very sensitive, 1=coarse

    def detect(self, video_path: str) -> List[Dict[str, Any]]:
        """Return list of {start_s, end_s, _src_duration_s}."""
        if self.algorithm == "scenedetect":
            scenes = self._detect_scenedetect(video_path)
        else:
            scenes = self._detect_histogram(video_path)

        if not scenes:
            logger.warning("[SceneDetector] primary pass returned 0 scenes, trying fallback")
            scenes = self._detect_histogram(video_path, coarse=True)

        min_dur = cfg.get("scene.min_duration", 1.5)
        fallback_min = cfg.get("scene.fallback_min_duration", 0.8)
        valid = [s for s in scenes if (s["end_s"] - s["start_s"]) >= min_dur]
        if not valid:
            valid = [s for s in scenes if (s["end_s"] - s["start_s"]) >= fallback_min]

        src_dur = self._get_duration(video_path)
        for s in valid:
            s["_src_duration_s"] = src_dur
        return valid

    # ── Algorithms ────────────────────────────────────────────────────────────

    def _detect_scenedetect(self, video_path: str) -> List[dict]:
        try:
            from scenedetect import open_video, SceneManager
            from scenedetect.detectors import ContentDetector
            video = open_video(video_path)
            manager = SceneManager()
            threshold = max(10, int(27 * (1 - self.sensitivity)))
            manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=15))
            manager.detect_scenes(video)
            scene_list = manager.get_scene_list()
            if not scene_list:
                return []
            return [
                {"start_s": s[0].get_seconds(), "end_s": s[1].get_seconds()}
                for s in scene_list
            ]
        except Exception as exc:
            logger.warning("[SceneDetector] scenedetect failed (%s), falling back", exc)
            return self._detect_histogram(video_path)

    def _detect_histogram(self, video_path: str, coarse: bool = False) -> List[dict]:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        threshold = 0.3 if not coarse else 0.5
        min_scene_frames = int((cfg.get("scene.fallback_min_duration", 0.8) if coarse
                                else cfg.get("scene.min_duration", 1.5)) * fps)

        scenes = []
        prev_hist = None
        scene_start = 0.0
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
            cv2.normalize(hist, hist)
            t = frame_idx / fps

            if prev_hist is not None:
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)
                if diff > threshold and (frame_idx - int(scene_start * fps)) >= min_scene_frames:
                    scenes.append({"start_s": scene_start, "end_s": t})
                    scene_start = t

            prev_hist = hist
            frame_idx += 1

        duration = total_frames / fps
        if scene_start < duration - 0.1:
            scenes.append({"start_s": scene_start, "end_s": duration})

        cap.release()
        return scenes

    def _get_duration(self, video_path: str) -> float:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        return frames / fps if fps else 0.0
