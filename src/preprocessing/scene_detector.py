"""
Scene splitting via PySceneDetect with OpenCV fallback.

Algorithm selection (based on research):
  AdaptiveDetector (default) — rolling-average of HSV frame differences.
  Unlike ContentDetector (fixed threshold=27), AdaptiveDetector computes
  frame_score / rolling_avg > adaptive_threshold (default 3.0), which
  self-adjusts to camera motion and avoids false positives on fast pans.
  Reference: PySceneDetect docs, github.com/Breakthrough/PySceneDetect

  ContentDetector is kept as secondary for hard-cut-heavy content.
"""

import logging
import subprocess
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Scene:
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


class SceneDetector:
    def __init__(
        self,
        threshold: float = 3.0,    # adaptive_threshold for AdaptiveDetector
        frame_skip: int = 2,        # lowered from 5 → finer detection
        min_scene_length: float = 0.8,
    ):
        self.threshold = threshold
        self.frame_skip = frame_skip
        self.min_scene_length = min_scene_length

    def split(self, video_path: str) -> List[Scene]:
        try:
            return self._split_pyscenedetect(video_path)
        except Exception as e:
            logger.warning(f'[SceneDetector] PySceneDetect failed ({e}), using FFmpeg fallback')
            return self._split_ffmpeg_fallback(video_path)

    def _split_pyscenedetect(self, video_path: str) -> List[Scene]:
        from scenedetect import open_video, SceneManager
        from scenedetect.detectors import AdaptiveDetector

        video = open_video(video_path)

        manager = SceneManager()
        # AdaptiveDetector: rolling-average normalisation makes it robust to
        # fast camera moves that cause ContentDetector false positives.
        manager.add_detector(
            AdaptiveDetector(
                adaptive_threshold=self.threshold,   # default 3.0
                min_scene_len=self.min_scene_length,
            )
        )
        manager.detect_scenes(video, frame_skip=self.frame_skip)
        scene_list = manager.get_scene_list()

        if not scene_list:
            duration = self._get_duration(video_path)
            if duration and duration >= self.min_scene_length:
                return [Scene(0.0, duration)]
            return []

        scenes = [
            Scene(start_s=s[0].get_seconds(), end_s=s[1].get_seconds())
            for s in scene_list
        ]
        scenes = [s for s in scenes if s.duration_s >= self.min_scene_length]
        logger.info(f'[SceneDetector] {len(scenes)} scenes found in {video_path}')
        return scenes

    def _split_ffmpeg_fallback(self, video_path: str) -> List[Scene]:
        """Chunk video into fixed-size scenes when PySceneDetect unavailable."""
        duration = self._get_duration(video_path)
        if not duration:
            return []
        chunk = 4.0
        scenes = []
        t = 0.0
        while t < duration - self.min_scene_length:
            end = min(t + chunk, duration)
            if (end - t) >= self.min_scene_length:
                scenes.append(Scene(t, end))
            t = end
        logger.info(f'[SceneDetector] FFmpeg fallback: {len(scenes)} chunks')
        return scenes

    @staticmethod
    def _get_duration(video_path: str) -> Optional[float]:
        try:
            result = subprocess.run(
                [
                    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', video_path,
                ],
                capture_output=True, text=True, timeout=15,
            )
            return float(result.stdout.strip())
        except Exception:
            return None
