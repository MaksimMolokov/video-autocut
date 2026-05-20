"""
Beat sync strategy
Aligns video cuts to musical beats/onsets for rhythmic editing
"""

import logging
from typing import List, Optional
import random

from .base import MusicSyncStrategy
from .models import AudioAnalysis, CutPlan, CutPoint, MusicSyncSettings, BeatPoint
from src.segment_selector import SelectedSegment


logger = logging.getLogger(__name__)


class BeatSync(MusicSyncStrategy):
    """Beat-synchronized video editing"""

    def build_cut_plan(
        self,
        audio_analysis: AudioAnalysis,
        available_segments: List[SelectedSegment],
        target_duration: float,
        dynamic_level: str
    ) -> CutPlan:
        """
        Build cut plan aligned to musical beats

        Args:
            audio_analysis: Music analysis with beat information
            available_segments: Available video segments
            target_duration: Target video duration
            dynamic_level: Dynamic level setting

        Returns:
            CutPlan with beat-aligned cuts
        """
        logger.info("[BeatSync] Building beat-aligned cut plan...")

        plan = CutPlan(target_duration=target_duration)

        # Check if we have beats
        if not audio_analysis.beat_points:
            logger.warning("  No beats detected - cannot perform beat sync")
            raise ValueError("Beat detection failed - no beats found")

        logger.info(f"  Detected {len(audio_analysis.beat_points)} beats")
        logger.info(f"  Tempo: {audio_analysis.tempo:.1f} BPM" if audio_analysis.tempo else "  Tempo: unknown")

        # Get settings
        cut_every_n_beats = self._get_beat_interval(dynamic_level)
        min_dur = self.settings.min_clip_duration
        max_dur = self.settings.max_clip_duration

        logger.info(f"  Cut every {cut_every_n_beats} beats")
        logger.info(f"  Clip duration range: {min_dur:.1f}s - {max_dur:.1f}s")

        # Select beat points to use for cuts
        cut_beats = self._select_cut_beats(
            audio_analysis.beat_points,
            cut_every_n_beats,
            target_duration
        )

        logger.info(f"  Selected {len(cut_beats)} beat points for cuts")

        # Build cut plan
        segment_idx = 0

        for i, beat in enumerate(cut_beats):
            # Skip if we've exceeded target duration
            if beat.time >= target_duration:
                break

            # Calculate duration to next cut
            if i < len(cut_beats) - 1:
                next_beat = cut_beats[i + 1]
                duration = next_beat.time - beat.time

                # Clamp duration
                duration = max(min_dur, min(max_dur, duration))

                # Don't exceed target
                if beat.time + duration > target_duration:
                    duration = target_duration - beat.time
            else:
                # Last segment - go to end
                duration = target_duration - beat.time

            # Skip if duration is too small
            if duration < min_dur / 2:
                continue

            # Get energy and structure info
            energy_level = None
            structure_section = None

            energy_section = audio_analysis.get_section_at_time(beat.time)
            if energy_section:
                energy_level = energy_section.energy_level

            structure = audio_analysis.get_structure_at_time(beat.time)
            if structure:
                structure_section = structure.section_type

            # Check for climax and drop
            is_climax = audio_analysis.is_near_peak(beat.time)
            is_drop = audio_analysis.is_near_drop(beat.time)

            # Create cut point
            cut_point = CutPoint(
                time=beat.time,
                source_segment_idx=segment_idx % len(available_segments),
                beat_aligned=True,
                energy_level=energy_level,
                structure_section=structure_section,
                is_climax=is_climax,
                is_drop=is_drop
            )
            plan.cut_points.append(cut_point)
            plan.segment_durations.append(duration)

            segment_idx += 1

        # If we don't have enough segments, fill in with offbeat cuts
        if plan.cut_points:
            total_duration = sum(plan.segment_durations)

            if total_duration < target_duration and self.settings.allow_offbeat_cuts:
                logger.info(f"  Adding offbeat cuts to reach target duration")
                self._fill_gaps(plan, target_duration, available_segments, min_dur, max_dur)

        self.log_plan_stats(plan)

        if not plan.cut_points:
            raise ValueError("Failed to create beat-aligned cut plan")

        return plan

    def _get_beat_interval(self, dynamic_level: str) -> int:
        """
        Get how many beats between cuts based on dynamic level

        Args:
            dynamic_level: slow/balanced/fast

        Returns:
            Number of beats between cuts
        """
        intervals = {
            "slow": self.settings.cut_every_n_beats * 2,  # Less frequent cuts
            "balanced": self.settings.cut_every_n_beats,
            "fast": max(1, self.settings.cut_every_n_beats // 2)  # More frequent cuts
        }
        return intervals.get(dynamic_level, self.settings.cut_every_n_beats)

    def _select_cut_beats(
        self,
        all_beats: List[BeatPoint],
        interval: int,
        max_time: float
    ) -> List[BeatPoint]:
        """
        Select which beats to use for cuts

        Args:
            all_beats: All detected beats
            interval: Cut every N beats
            max_time: Maximum time to consider

        Returns:
            List of selected beats
        """
        selected = []

        # Filter beats within time range
        valid_beats = [b for b in all_beats if b.time <= max_time]

        if not valid_beats:
            return []

        # Select beats at intervals
        if self.settings.prefer_strong_beats:
            # Try to select strong beats first
            strong_beats = [b for b in valid_beats if b.is_strong_beat]

            if strong_beats:
                # Take every Nth strong beat
                for i in range(0, len(strong_beats), interval):
                    selected.append(strong_beats[i])
            else:
                # Fall back to regular interval
                for i in range(0, len(valid_beats), interval):
                    selected.append(valid_beats[i])
        else:
            # Regular interval
            for i in range(0, len(valid_beats), interval):
                selected.append(valid_beats[i])

        # Always include first beat if not already there
        if selected and selected[0].time > 0.5:
            selected.insert(0, valid_beats[0])

        return selected

    def _fill_gaps(
        self,
        plan: CutPlan,
        target_duration: float,
        available_segments: List[SelectedSegment],
        min_dur: float,
        max_dur: float
    ):
        """
        Fill gaps to reach target duration with offbeat cuts

        Args:
            plan: Current cut plan
            target_duration: Target duration
            available_segments: Available segments
            min_dur: Minimum clip duration
            max_dur: Maximum clip duration
        """
        if not plan.cut_points:
            return

        current_duration = sum(plan.segment_durations)
        remaining = target_duration - current_duration

        if remaining < min_dur:
            return

        # Add segments at the end
        last_time = plan.cut_points[-1].time + plan.segment_durations[-1]
        segment_idx = plan.cut_points[-1].source_segment_idx + 1

        while last_time < target_duration:
            gap = target_duration - last_time
            duration = min(max_dur, gap)

            if duration < min_dur / 2:
                break

            cut_point = CutPoint(
                time=last_time,
                source_segment_idx=segment_idx % len(available_segments),
                beat_aligned=False  # These are offbeat fills
            )
            plan.cut_points.append(cut_point)
            plan.segment_durations.append(duration)

            last_time += duration
            segment_idx += 1
