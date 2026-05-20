"""
Simple tempo sync strategy
Adjusts clip durations to match general music tempo without precise beat alignment
"""

import logging
import random
from typing import List

from .base import MusicSyncStrategy
from .models import AudioAnalysis, CutPlan, CutPoint, MusicSyncSettings
from src.segment_selector import SelectedSegment


logger = logging.getLogger(__name__)


class SimpleTempoSync(MusicSyncStrategy):
    """Simple tempo-based synchronization"""

    def build_cut_plan(
        self,
        audio_analysis: AudioAnalysis,
        available_segments: List[SelectedSegment],
        target_duration: float,
        dynamic_level: str
    ) -> CutPlan:
        """
        Build cut plan based on simple tempo matching

        Uses tempo to suggest average clip duration but doesn't align to specific beats.

        Args:
            audio_analysis: Music analysis
            available_segments: Available video segments
            target_duration: Target video duration
            dynamic_level: Dynamic level setting

        Returns:
            CutPlan object
        """
        logger.info("[SimpleTempoSync] Building cut plan...")

        plan = CutPlan(target_duration=target_duration)

        # Get clip duration range based on dynamic level
        min_dur, max_dur = self._get_clip_duration_range(dynamic_level)

        # If we have tempo, adjust durations to match musical rhythm
        if audio_analysis.tempo:
            beat_duration = 60.0 / audio_analysis.tempo  # Duration of one beat

            # Adjust preferred duration to be multiple of beats
            beats_per_clip = {
                "slow": 8,  # 8 beats per clip
                "balanced": 4,  # 4 beats per clip
                "fast": 2  # 2 beats per clip
            }.get(dynamic_level, 4)

            preferred_duration = beat_duration * beats_per_clip

            # Clamp to min/max range
            preferred_duration = max(min_dur, min(max_dur, preferred_duration))

            logger.info(f"  Tempo: {audio_analysis.tempo:.1f} BPM")
            logger.info(f"  Beat duration: {beat_duration:.2f}s")
            logger.info(f"  Preferred clip duration: {preferred_duration:.2f}s ({beats_per_clip} beats)")
        else:
            # No tempo detected, use middle of range
            preferred_duration = (min_dur + max_dur) / 2
            logger.info(f"  No tempo detected, using {preferred_duration:.2f}s clips")

        # Build segments
        current_time = 0.0
        segment_idx = 0

        while current_time < target_duration:
            remaining = target_duration - current_time

            # Determine clip duration with some variation
            if remaining < min_dur:
                clip_duration = remaining
            else:
                # Add slight random variation (+/- 20%)
                variation = random.uniform(0.8, 1.2)
                clip_duration = preferred_duration * variation
                clip_duration = max(min_dur, min(max_dur, clip_duration, remaining))

            # Get energy and structure info if available
            energy_level = None
            structure_section = None

            energy_section = audio_analysis.get_section_at_time(current_time)
            if energy_section:
                energy_level = energy_section.energy_level

            structure = audio_analysis.get_structure_at_time(current_time)
            if structure:
                structure_section = structure.section_type

            # Create cut point
            cut_point = CutPoint(
                time=current_time,
                source_segment_idx=segment_idx % len(available_segments),
                beat_aligned=False,  # Not precisely aligned
                energy_level=energy_level,
                structure_section=structure_section
            )
            plan.cut_points.append(cut_point)
            plan.segment_durations.append(clip_duration)

            current_time += clip_duration
            segment_idx += 1

        self.log_plan_stats(plan)

        return plan
