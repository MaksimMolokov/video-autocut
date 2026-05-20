"""
Smart Beat Priority Sync Strategy
Syncs only to important musical accents, not every beat
"""

import logging
import random
from typing import List, Tuple
import numpy as np

from .models import (
    AudioAnalysis, CutPlan, CutPoint, BeatPoint, EnergyLevel
)
from .base import MusicSyncStrategy

logger = logging.getLogger(__name__)


class SmartBeatPriorityStrategy(MusicSyncStrategy):
    """
    Smart Beat Priority - intelligent beat selection

    Instead of cutting on every beat or every N beats, this strategy:
    1. Identifies "important" beats (strong beats, downbeats, accented)
    2. Only cuts on these important beats
    3. Uses energy changes to determine beat importance
    4. Adapts to musical phrasing (4, 8, 16 bar patterns)

    Result: More musical, less mechanical editing
    """

    def __init__(self, settings: dict):
        self.settings = settings

        # Importance thresholds
        self.min_beat_strength = settings.get('min_beat_strength', 0.7)  # 0.0-1.0
        self.prefer_strong_beats_only = settings.get('prefer_strong_beats_only', True)

        # Musical phrasing (prefer cuts at phrase boundaries)
        self.use_musical_phrasing = settings.get('use_musical_phrasing', True)
        self.phrase_length_beats = settings.get('phrase_length_beats', 8)  # 4, 8, 16

        # Energy-based importance
        self.energy_change_threshold = settings.get('energy_change_threshold', 0.2)

        # Duration constraints
        self.min_clip_duration = settings.get('min_clip_duration', 1.0)
        self.max_clip_duration = settings.get('max_clip_duration', 6.0)

    def build_cut_plan(self, audio_analysis: AudioAnalysis, available_segments: List,
                      target_duration: float, dynamic_level: str = "balanced") -> CutPlan:
        """
        Build cut plan using smart beat selection
        """
        logger.info("[SmartBeatSync] Building smart beat-priority cut plan")
        logger.info(f"  Target duration: {target_duration:.1f}s")
        logger.info(f"  Total beats detected: {len(audio_analysis.beat_points)}")

        if not audio_analysis.beat_points:
            logger.warning("  No beats detected, falling back to energy-based cuts")
            return self._build_energy_fallback(audio_analysis, target_duration, available_segments)

        # Identify important beats
        important_beats = self._identify_important_beats(audio_analysis)
        logger.info(f"  Important beats: {len(important_beats)} / {len(audio_analysis.beat_points)}")

        # Adjust min/max duration based on dynamic level
        min_dur = self.min_clip_duration
        max_dur = self.max_clip_duration

        if dynamic_level == "fast":
            min_dur *= 0.7
            max_dur *= 0.7
        elif dynamic_level == "slow":
            min_dur *= 1.3
            max_dur *= 1.3

        logger.info(f"  Clip duration range: {min_dur:.1f}s - {max_dur:.1f}s")

        cut_plan = CutPlan(target_duration=target_duration)
        current_time = 0.0
        source_idx = 0
        last_beat_idx = 0

        while current_time < target_duration:
            # Find next important beat within duration range
            next_beat, beat_idx = self._find_next_important_beat(
                important_beats, current_time, min_dur, max_dur, last_beat_idx
            )

            if next_beat is None:
                # No suitable beat found, use max duration
                clip_duration = min(max_dur, target_duration - current_time)
            else:
                clip_duration = next_beat.time - current_time
                last_beat_idx = beat_idx

            # Ensure minimum duration
            if clip_duration < 0.5:
                break

            # Check for climax/drop at this time
            is_climax = audio_analysis.is_near_peak(current_time)
            is_drop = audio_analysis.is_near_drop(current_time)

            # Get energy level
            energy_section = audio_analysis.get_section_at_time(current_time)
            energy_level = energy_section.energy_level if energy_section else None

            # Create cut point
            cut_point = CutPoint(
                time=current_time,
                source_segment_idx=source_idx % len(available_segments),
                beat_aligned=next_beat is not None,
                energy_level=energy_level,
                is_climax=is_climax,
                is_drop=is_drop
            )

            cut_plan.cut_points.append(cut_point)
            cut_plan.segment_durations.append(clip_duration)

            current_time += clip_duration
            source_idx += 1

        # Calculate statistics
        cut_plan.calculate_stats()

        logger.info(f"\n  Total cuts: {cut_plan.total_cuts}")
        logger.info(f"  Beat-aligned cuts: {cut_plan.beat_aligned_cuts}")
        logger.info(f"  Climax cuts: {cut_plan.climax_cuts}")
        logger.info(f"  Avg segment duration: {cut_plan.avg_segment_duration:.2f}s")

        return cut_plan

    def _identify_important_beats(self, analysis: AudioAnalysis) -> List[BeatPoint]:
        """
        Identify which beats are "important" for cutting

        Importance factors:
        1. Beat strength (from audio_analysis)
        2. Strong beats (downbeats)
        3. Musical phrasing (every 4th, 8th, 16th beat)
        4. Energy changes (beats near energy transitions)
        """
        important_beats = []

        for i, beat in enumerate(audio_analysis.beat_points):
            importance_score = 0.0

            # Factor 1: Beat strength
            if beat.strength >= self.min_beat_strength:
                importance_score += 1.0

            # Factor 2: Strong beats (downbeats)
            if beat.is_strong_beat:
                importance_score += 2.0  # Strong beats are very important

            # Factor 3: Musical phrasing
            if self.use_musical_phrasing and (i + 1) % self.phrase_length_beats == 0:
                importance_score += 1.5  # Phrase boundaries are important

            # Factor 4: Energy changes
            if self._is_near_energy_change(audio_analysis, beat.time):
                importance_score += 1.0

            # If only strong beats preferred, filter strictly
            if self.prefer_strong_beats_only:
                if beat.is_strong_beat or importance_score >= 2.0:
                    important_beats.append(beat)
            else:
                # Accept beats with any positive importance
                if importance_score > 0:
                    important_beats.append(beat)

        return important_beats

    def _is_near_energy_change(self, analysis: AudioAnalysis, time: float) -> bool:
        """Check if this time is near an energy level change"""
        if not audio_analysis.energy_sections or len(audio_analysis.energy_sections) < 2:
            return False

        # Find current and next section
        for i, section in enumerate(audio_analysis.energy_sections[:-1]):
            next_section = audio_analysis.energy_sections[i + 1]

            # Check if near section boundary
            if abs(time - next_section.start_time) < 1.0:  # Within 1 second
                # Check if energy actually changed
                if section.energy_level != next_section.energy_level:
                    return True

        return False

    def _find_next_important_beat(self, important_beats: List[BeatPoint],
                                  current_time: float, min_dur: float, max_dur: float,
                                  last_beat_idx: int) -> Tuple[BeatPoint, int]:
        """
        Find next important beat within duration range

        Returns: (BeatPoint, index) or (None, -1) if no suitable beat
        """
        for i, beat in enumerate(important_beats[last_beat_idx:], start=last_beat_idx):
            if beat.time <= current_time:
                continue

            duration = beat.time - current_time

            if min_dur <= duration <= max_dur:
                return beat, i

            # If duration exceeds max, no suitable beat
            if duration > max_dur:
                return None, -1

        return None, -1

    def _build_energy_fallback(self, analysis: AudioAnalysis, target_duration: float,
                               available_segments: List) -> CutPlan:
        """Fallback when no beats are detected - use energy changes"""
        logger.info("  Building energy-based fallback plan")

        cut_plan = CutPlan(target_duration=target_duration)

        if not audio_analysis.energy_sections:
            # Ultimate fallback - uniform cuts
            logger.warning("  No energy sections, using uniform cuts")
            current_time = 0.0
            source_idx = 0
            clip_duration = 2.0

            while current_time < target_duration:
                remaining = target_duration - current_time
                if remaining < 0.5:
                    break

                duration = min(clip_duration, remaining)
                cut_plan.cut_points.append(CutPoint(
                    time=current_time,
                    source_segment_idx=source_idx % len(available_segments),
                    beat_aligned=False
                ))
                cut_plan.segment_durations.append(duration)

                current_time += duration
                source_idx += 1

            cut_plan.calculate_stats()
            return cut_plan

        # Use energy section boundaries as cut points
        current_time = 0.0
        source_idx = 0

        for section in audio_analysis.energy_sections:
            if current_time >= target_duration:
                break

            section_duration = min(section.duration, target_duration - current_time)

            # Split long sections
            if section_duration > self.max_clip_duration:
                # Multiple cuts within section
                num_cuts = int(section_duration / self.max_clip_duration) + 1
                clip_duration = section_duration / num_cuts

                for _ in range(num_cuts):
                    if current_time >= target_duration:
                        break

                    cut_plan.cut_points.append(CutPoint(
                        time=current_time,
                        source_segment_idx=source_idx % len(available_segments),
                        beat_aligned=False,
                        energy_level=section.energy_level
                    ))
                    cut_plan.segment_durations.append(clip_duration)

                    current_time += clip_duration
                    source_idx += 1
            else:
                # Single cut for this section
                cut_plan.cut_points.append(CutPoint(
                    time=current_time,
                    source_segment_idx=source_idx % len(available_segments),
                    beat_aligned=False,
                    energy_level=section.energy_level
                ))
                cut_plan.segment_durations.append(section_duration)

                current_time += section_duration
                source_idx += 1

        cut_plan.calculate_stats()
        return cut_plan
