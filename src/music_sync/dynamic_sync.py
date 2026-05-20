"""
Dynamic sync strategy (Enhanced Energy Curve Sync)
Adapts video editing pace to music energy dynamics with advanced features:
- Energy curve following
- Climax/peak detection
- Drop emphasis
- Smooth transitions during energy changes
"""

import logging
from typing import List, Tuple
import random
import numpy as np

from .base import MusicSyncStrategy
from .models import (
    AudioAnalysis, CutPlan, CutPoint, MusicSyncSettings,
    EnergySection, EnergyLevel, BeatPoint
)
from src.segment_selector import SelectedSegment


logger = logging.getLogger(__name__)


class DynamicSync(MusicSyncStrategy):
    """Dynamic editing synchronized to music energy"""

    def build_cut_plan(
        self,
        audio_analysis: AudioAnalysis,
        available_segments: List[SelectedSegment],
        target_duration: float,
        dynamic_level: str
    ) -> CutPlan:
        """
        Build cut plan adapted to music energy dynamics

        Args:
            audio_analysis: Music analysis with energy sections
            available_segments: Available video segments
            target_duration: Target video duration
            dynamic_level: Dynamic level setting

        Returns:
            CutPlan adapted to music dynamics
        """
        logger.info("[DynamicSync] Building energy-adaptive cut plan...")

        plan = CutPlan(target_duration=target_duration)

        # Check if we have energy analysis
        if not audio_analysis.energy_sections:
            logger.warning("  No energy sections detected - cannot perform dynamic sync")
            raise ValueError("Energy analysis failed - no sections found")

        logger.info(f"  Detected {len(audio_analysis.energy_sections)} energy sections:")
        for section in audio_analysis.energy_sections:
            logger.info(f"    {section.start_time:.1f}s - {section.end_time:.1f}s: "
                       f"{section.energy_level.value} (energy: {section.avg_energy:.2f})")

        # Build segments section by section
        current_time = 0.0
        segment_idx = 0

        for section in audio_analysis.energy_sections:
            # Skip sections beyond target duration
            if section.start_time >= target_duration:
                break

            # Adjust section end if it exceeds target
            section_end = min(section.end_time, target_duration)
            section_duration = section_end - max(current_time, section.start_time)

            if section_duration < 0.5:
                continue

            # Get clip duration range for this energy level
            min_dur, max_dur = self._get_energy_clip_duration(section.energy_level, dynamic_level)

            logger.debug(f"  Section {section.start_time:.1f}s-{section_end:.1f}s "
                        f"({section.energy_level.value}): clips {min_dur:.1f}s-{max_dur:.1f}s")

            # Get beats in this section if available and setting enabled
            section_beats = []
            if self.settings.use_beats_inside_sections and audio_analysis.beat_points:
                section_beats = [
                    b for b in audio_analysis.beat_points
                    if section.start_time <= b.time <= section_end
                ]

            # Fill section with clips
            section_start = max(current_time, section.start_time)
            time_in_section = section_start

            while time_in_section < section_end:
                remaining = section_end - time_in_section

                # Determine clip duration
                if section.energy_level == EnergyLevel.HIGH and section_beats and len(section_beats) > 2:
                    # High energy - try to align to beats
                    clip_duration = self._get_beat_aligned_duration(
                        time_in_section, section_beats, min_dur, max_dur, remaining
                    )
                else:
                    # Normal duration selection
                    preferred_dur = (min_dur + max_dur) / 2
                    variation = random.uniform(0.85, 1.15)
                    clip_duration = preferred_dur * variation
                    clip_duration = max(min_dur, min(max_dur, clip_duration, remaining))

                # Create cut point
                # Determine if this cut is beat-aligned
                is_beat_aligned = False
                if section_beats:
                    # Check if close to a beat
                    closest_beat = min(section_beats, key=lambda b: abs(b.time - time_in_section))
                    if abs(closest_beat.time - time_in_section) < self.settings.beat_tolerance:
                        is_beat_aligned = True

                # Check for climax and drop
                is_climax = audio_analysis.is_near_peak(time_in_section)
                is_drop = audio_analysis.is_near_drop(time_in_section)

                # Get structure section if available
                structure_section = None
                structure = audio_analysis.get_structure_at_time(time_in_section)
                if structure:
                    structure_section = structure.section_type

                # Enhanced climax handling - shorten clips at climax for more intensity
                if is_climax and self.settings.climax_priority:
                    clip_duration *= 0.7  # Shorter clips = more cuts = more intensity
                    logger.debug(f"    Climax at {time_in_section:.1f}s - shortening to {clip_duration:.2f}s")

                # Enhanced drop handling - very short clips for intense drops
                if is_drop:
                    clip_duration *= 0.6  # Even shorter for drops
                    logger.debug(f"    Drop at {time_in_section:.1f}s - shortening to {clip_duration:.2f}s")

                cut_point = CutPoint(
                    time=time_in_section,
                    source_segment_idx=segment_idx % len(available_segments),
                    beat_aligned=is_beat_aligned,
                    energy_level=section.energy_level,
                    structure_section=structure_section,
                    is_climax=is_climax,
                    is_drop=is_drop
                )
                plan.cut_points.append(cut_point)
                plan.segment_durations.append(clip_duration)

                time_in_section += clip_duration
                segment_idx += 1

            current_time = time_in_section

        # Fill any remaining time if needed
        if current_time < target_duration:
            remaining = target_duration - current_time
            if remaining > 0.5:
                logger.info(f"  Filling remaining {remaining:.1f}s")
                self._fill_remaining(plan, current_time, target_duration, available_segments, segment_idx)

        self.log_plan_stats(plan)

        if not plan.cut_points:
            raise ValueError("Failed to create dynamic cut plan")

        # Log energy distribution
        energy_counts = {
            EnergyLevel.LOW: 0,
            EnergyLevel.MEDIUM: 0,
            EnergyLevel.HIGH: 0
        }
        climax_count = 0
        drop_count = 0

        for cp in plan.cut_points:
            if cp.energy_level:
                energy_counts[cp.energy_level] += 1
            if cp.is_climax:
                climax_count += 1
            if cp.is_drop:
                drop_count += 1

        logger.info(f"  Energy distribution: "
                   f"Low={energy_counts[EnergyLevel.LOW]}, "
                   f"Medium={energy_counts[EnergyLevel.MEDIUM]}, "
                   f"High={energy_counts[EnergyLevel.HIGH]}")
        logger.info(f"  Climax cuts: {climax_count}, Drop cuts: {drop_count}")

        # Calculate energy curve statistics
        plan.calculate_stats()

        return plan

    def _get_energy_clip_duration(
        self,
        energy_level: EnergyLevel,
        dynamic_level: str
    ) -> Tuple[float, float]:
        """
        Get clip duration range based on energy level

        Args:
            energy_level: Energy level of the section
            dynamic_level: Overall dynamic level setting

        Returns:
            (min_duration, max_duration) tuple
        """
        # Base durations from settings
        base_durations = {
            EnergyLevel.LOW: self.settings.low_energy_clip_duration,
            EnergyLevel.MEDIUM: self.settings.medium_energy_clip_duration,
            EnergyLevel.HIGH: self.settings.high_energy_clip_duration
        }

        min_dur, max_dur = base_durations.get(energy_level, (2.0, 4.0))

        # Adjust based on dynamic level
        if dynamic_level == "slow":
            min_dur *= 1.2
            max_dur *= 1.2
        elif dynamic_level == "fast":
            min_dur *= 0.8
            max_dur *= 0.8

        return (min_dur, max_dur)

    def _get_beat_aligned_duration(
        self,
        start_time: float,
        beats: List[BeatPoint],
        min_dur: float,
        max_dur: float,
        max_remaining: float
    ) -> float:
        """
        Get duration aligned to next beat

        Args:
            start_time: Start time of clip
            beats: Available beats
            min_dur: Minimum duration
            max_dur: Maximum duration
            max_remaining: Maximum remaining time

        Returns:
            Duration aligned to beat if possible
        """
        # Find next suitable beat
        future_beats = [b for b in beats if b.time > start_time + min_dur]

        if not future_beats:
            # No suitable beat, use preferred duration
            return min(max_dur, max_remaining)

        # Find closest beat within range
        for beat in future_beats:
            duration = beat.time - start_time
            if min_dur <= duration <= max_dur and duration <= max_remaining:
                return duration

        # No perfect beat, use preferred duration
        preferred = (min_dur + max_dur) / 2
        return min(preferred, max_remaining)

    def _fill_remaining(
        self,
        plan: CutPlan,
        current_time: float,
        target_duration: float,
        available_segments: List[SelectedSegment],
        start_idx: int
    ):
        """
        Fill remaining time to reach target duration

        Args:
            plan: Current cut plan
            current_time: Current time position
            target_duration: Target duration
            available_segments: Available segments
            start_idx: Starting segment index
        """
        min_dur, max_dur = self.settings.medium_energy_clip_duration
        segment_idx = start_idx

        while current_time < target_duration:
            remaining = target_duration - current_time
            duration = min(max_dur, remaining)

            if duration < min_dur / 2:
                break

            cut_point = CutPoint(
                time=current_time,
                source_segment_idx=segment_idx % len(available_segments),
                beat_aligned=False
            )
            plan.cut_points.append(cut_point)
            plan.segment_durations.append(duration)

            current_time += duration
            segment_idx += 1
