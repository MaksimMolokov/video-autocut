"""
Base class for music sync strategies
"""

from abc import ABC, abstractmethod
from typing import List
import logging

from .models import AudioAnalysis, CutPlan, MusicSyncSettings
from src.segment_selector import SelectedSegment


logger = logging.getLogger(__name__)


class MusicSyncStrategy(ABC):
    """Base class for music synchronization strategies"""

    def __init__(self, settings: MusicSyncSettings):
        """
        Initialize strategy

        Args:
            settings: Music sync settings
        """
        self.settings = settings

    @abstractmethod
    def build_cut_plan(
        self,
        audio_analysis: AudioAnalysis,
        available_segments: List[SelectedSegment],
        target_duration: float,
        dynamic_level: str
    ) -> CutPlan:
        """
        Build a plan for cutting video based on music analysis

        Args:
            audio_analysis: Analysis of the music file
            available_segments: Available video segments to use
            target_duration: Target duration for final video
            dynamic_level: Dynamic level (slow/balanced/fast)

        Returns:
            CutPlan with cut points and segment assignments

        Raises:
            ValueError: If unable to create valid cut plan
        """
        pass

    def _get_clip_duration_range(self, dynamic_level: str) -> tuple:
        """
        Get min/max clip duration based on dynamic level

        Args:
            dynamic_level: slow, balanced, or fast

        Returns:
            (min_duration, max_duration) tuple
        """
        duration_ranges = {
            "slow": (4.0, 8.0),
            "balanced": (2.0, 5.0),
            "fast": (0.8, 3.0)
        }
        return duration_ranges.get(dynamic_level, (2.0, 5.0))

    def log_plan_stats(self, plan: CutPlan):
        """Log statistics about the cut plan"""
        plan.calculate_stats()

        logger.info(f"[{self.__class__.__name__}] Cut plan created:")
        logger.info(f"  Total cuts: {plan.total_cuts}")
        logger.info(f"  Beat-aligned cuts: {plan.beat_aligned_cuts}")
        logger.info(f"  Average segment duration: {plan.avg_segment_duration:.2f}s")
