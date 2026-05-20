"""
Music Structure Sync Strategy
Adapts editing to track structure (intro, verse, chorus, drop, outro)
"""

import logging
import random
from typing import List, Tuple
import numpy as np

from .models import (
    AudioAnalysis, CutPlan, CutPoint, EnergyLevel, TrackSection
)
from .base import MusicSyncStrategy

logger = logging.getLogger(__name__)


class StructureSyncStrategy(MusicSyncStrategy):
    """
    Music Structure Sync - intelligent adaptation to track structure

    Different editing approaches for different sections:
    - INTRO: Slow, establishing shots, longer clips
    - VERSE: Medium pace, storytelling
    - CHORUS: Fast, energetic, short clips
    - BRIDGE: Transition, medium clips
    - DROP: Very fast, intense cuts
    - BUILDUP: Accelerating pace
    - BREAKDOWN: Slower, breathing space
    - OUTRO: Slow fade out, longer clips
    """

    def __init__(self, settings: dict):
        self.settings = settings

        # Structure-specific clip duration ranges (in seconds)
        self.structure_durations = {
            TrackSection.INTRO: (3.0, 7.0),     # Long, establishing
            TrackSection.VERSE: (2.0, 4.0),     # Medium, storytelling
            TrackSection.CHORUS: (0.8, 2.5),    # Fast, energetic
            TrackSection.BRIDGE: (2.0, 3.5),    # Transition
            TrackSection.DROP: (0.5, 1.5),      # Very fast, intense
            TrackSection.BUILDUP: (1.5, 3.0),   # Medium, building
            TrackSection.BREAKDOWN: (2.5, 5.0), # Slower, breathing
            TrackSection.OUTRO: (3.0, 8.0),     # Long fade out
            TrackSection.UNKNOWN: (2.0, 4.0)    # Default
        }

        # Whether to use beat sync within each section
        self.use_beats_in_chorus = settings.get('use_beats_in_chorus', True)
        self.use_beats_in_drop = settings.get('use_beats_in_drop', True)

        # Emphasis on structural changes
        self.emphasize_structure_changes = settings.get('emphasize_structure_changes', True)

        # Climax handling
        self.climax_priority = settings.get('climax_priority', True)

    def build_cut_plan(self, audio_audio_analysis: AudioAnalysis, available_segments: List,
                      target_duration: float, dynamic_level: str = "balanced") -> CutPlan:
        """
        Build cut plan based on track structure
        """
        logger.info("[StructureSync] Building structure-based cut plan")
        logger.info(f"  Target duration: {target_duration:.1f}s")
        logger.info(f"  Track duration: {audio_audio_analysis.duration:.1f}s")
        logger.info(f"  Structure sections: {len(audio_audio_analysis.structure_sections)}")

        if not audio_audio_analysis.structure_sections:
            logger.warning("  No structure detected, using default approach")
            return self._build_default_plan(audio_audio_analysis, target_duration, available_segments)

        cut_plan = CutPlan(target_duration=target_duration)
        current_time = 0.0
        source_idx = 0

        # Log detected structure
        for section in audio_analysis.structure_sections:
            logger.info(f"    {section.section_type.value}: {section.start_time:.1f}s - {section.end_time:.1f}s "
                       f"({section.duration:.1f}s)")

        # Process each structural section
        for section in audio_analysis.structure_sections:
            if current_time >= target_duration:
                break

            section_duration = min(section.duration, target_duration - current_time)
            logger.info(f"\n  Processing {section.section_type.value} section ({section.start_time:.1f}s - {section.end_time:.1f}s)")

            # Get appropriate clip duration for this section
            min_dur, max_dur = self.structure_durations.get(
                section.section_type,
                self.structure_durations[TrackSection.UNKNOWN]
            )

            # Adjust based on dynamic level
            if dynamic_level == "fast":
                min_dur *= 0.7
                max_dur *= 0.7
            elif dynamic_level == "slow":
                min_dur *= 1.3
                max_dur *= 1.3

            # Generate cuts for this section
            section_time = 0.0
            while section_time < section_duration and current_time < target_duration:
                # Check if we should align to beat
                use_beat = False
                if section.section_type == TrackSection.CHORUS and self.use_beats_in_chorus:
                    use_beat = True
                elif section.section_type == TrackSection.DROP and self.use_beats_in_drop:
                    use_beat = True

                # Determine clip duration
                if use_beat and audio_analysis.beat_times:
                    # Find next beat
                    clip_duration = self._get_beat_aligned_duration(
                        audio_analysis, section.start_time + section_time, min_dur, max_dur
                    )
                else:
                    # Random duration within range
                    clip_duration = random.uniform(min_dur, max_dur)

                # Clamp to available time
                clip_duration = min(clip_duration, section_duration - section_time,
                                  target_duration - current_time)

                if clip_duration < 0.5:  # Minimum clip duration
                    break

                # Check for climax
                is_climax = False
                if self.climax_priority:
                    is_climax = audio_analysis.is_near_peak(section.start_time + section_time)

                # Check for drop
                is_drop = audio_analysis.is_near_drop(section.start_time + section_time)

                # Create cut point
                cut_point = CutPoint(
                    time=current_time,
                    source_segment_idx=source_idx % len(available_segments),
                    beat_aligned=use_beat,
                    structure_section=section.section_type,
                    is_climax=is_climax,
                    is_drop=is_drop or section.section_type == TrackSection.DROP
                )

                cut_plan.cut_points.append(cut_point)
                cut_plan.segment_durations.append(clip_duration)

                current_time += clip_duration
                section_time += clip_duration
                source_idx += 1

            logger.info(f"    Created {len([cp for cp in cut_plan.cut_points if cp.structure_section == section.section_type])} cuts for {section.section_type.value}")

        # Calculate statistics
        cut_plan.calculate_stats()

        logger.info(f"\n  Total cuts: {cut_plan.total_cuts}")
        logger.info(f"  Beat-aligned cuts: {cut_plan.beat_aligned_cuts}")
        logger.info(f"  Climax cuts: {cut_plan.climax_cuts}")
        logger.info(f"  Drop cuts: {cut_plan.drop_cuts}")
        logger.info(f"  Avg segment duration: {cut_plan.avg_segment_duration:.2f}s")

        return cut_plan

    def _get_beat_aligned_duration(self, audio_analysis: AudioAnalysis, current_time: float,
                                   min_dur: float, max_dur: float) -> float:
        """Get duration aligned to next beat"""
        if not audio_analysis.beat_times:
            return random.uniform(min_dur, max_dur)

        # Find beats within acceptable range
        suitable_beats = []
        for beat_time in audio_analysis.beat_times:
            if beat_time > current_time:
                duration = beat_time - current_time
                if min_dur <= duration <= max_dur:
                    suitable_beats.append(beat_time)

        if suitable_beats:
            # Pick random suitable beat
            beat_time = random.choice(suitable_beats)
            return beat_time - current_time
        else:
            # No suitable beat, use random duration
            return random.uniform(min_dur, max_dur)

    def _build_default_plan(self, audio_analysis: AudioAnalysis, target_duration: float,
                           available_segments: List) -> CutPlan:
        """Fallback plan when no structure is detected"""
        logger.info("  Building default plan (no structure detected)")

        cut_plan = CutPlan(target_duration=target_duration)
        current_time = 0.0
        source_idx = 0

        # Use medium duration as default
        min_dur, max_dur = 2.0, 4.0

        while current_time < target_duration:
            clip_duration = min(
                random.uniform(min_dur, max_dur),
                target_duration - current_time
            )

            if clip_duration < 0.5:
                break

            cut_point = CutPoint(
                time=current_time,
                source_segment_idx=source_idx % len(available_segments),
                beat_aligned=False
            )

            cut_plan.cut_points.append(cut_point)
            cut_plan.segment_durations.append(clip_duration)

            current_time += clip_duration
            source_idx += 1

        cut_plan.calculate_stats()
        return cut_plan
