"""
Visual-Music Match Sync Strategy
Matches video content characteristics to music character
"""

import logging
import random
from typing import List, Tuple, Optional
import numpy as np

from .models import (
    AudioAnalysis, CutPlan, CutPoint, MusicMood, EnergyLevel, TrackSection
)
from .base import MusicSyncStrategy

logger = logging.getLogger(__name__)


class VisualMusicMatchStrategy(MusicSyncStrategy):
    """
    Visual-Music Match - intelligent video selection based on music character

    Matches video characteristics to music:
    - High energy music → High motion video
    - Calm music → Stable, slow shots
    - Dramatic music → Varied motion, quality shots
    - Chorus/drop → Most dynamic clips
    - Intro/outro → Establishing/closing shots

    Uses video segment metadata (motion score, quality) to select appropriate clips
    """

    def __init__(self, settings: dict):
        self.settings = settings

        # Matching preferences
        self.match_energy_to_motion = settings.get('match_energy_to_motion', True)
        self.match_mood_to_style = settings.get('match_mood_to_style', True)
        self.match_structure_to_content = settings.get('match_structure_to_content', True)

        # Clip selection preferences
        self.high_energy_motion_threshold = settings.get('high_energy_motion_threshold', 0.6)
        self.low_energy_motion_threshold = settings.get('low_energy_motion_threshold', 0.3)

        # Duration settings
        self.min_clip_duration = settings.get('min_clip_duration', 1.0)
        self.max_clip_duration = settings.get('max_clip_duration', 5.0)

        # Diversity
        self.avoid_repetition_window = settings.get('avoid_repetition_window', 5)  # Don't repeat same clip within N cuts

    def build_cut_plan(self, audio_analysis: AudioAnalysis, available_segments: List,
                      target_duration: float, dynamic_level: str = "balanced") -> CutPlan:
        """
        Build cut plan with visual-music matching
        """
        logger.info("[VisualMusicMatch] Building visual-music matched cut plan")
        logger.info(f"  Target duration: {target_duration:.1f}s")
        logger.info(f"  Available available_segments: {len(available_segments)}")

        # Adjust duration ranges based on dynamic level
        min_dur = self.min_clip_duration
        max_dur = self.max_clip_duration

        if dynamic_level == "fast":
            min_dur *= 0.7
            max_dur *= 0.7
        elif dynamic_level == "slow":
            min_dur *= 1.3
            max_dur *= 1.3

        cut_plan = CutPlan(target_duration=target_duration)
        current_time = 0.0
        recent_sources = []  # Track recently used available_segments to avoid repetition

        while current_time < target_duration:
            # Determine music characteristics at this point
            music_context = self._get_music_context(audio_analysis, current_time)

            # Determine desired clip duration based on context
            clip_duration = self._get_context_appropriate_duration(
                music_context, min_dur, max_dur, target_duration - current_time
            )

            if clip_duration < 0.5:
                break

            # Select best matching video source
            source_idx = self._select_matching_source(
                available_segments, music_context, recent_sources
            )

            # Track recent available_segments for diversity
            recent_sources.append(source_idx)
            if len(recent_sources) > self.avoid_repetition_window:
                recent_sources.pop(0)

            # Check for beat alignment
            beat_aligned = False
            if music_context.get('use_beats', False) and audio_analysis.beat_times:
                beat = audio_analysis.get_beat_at_time(current_time, tolerance=0.3)
                if beat:
                    beat_aligned = True

            # Create cut point
            cut_point = CutPoint(
                time=current_time,
                source_segment_idx=source_idx,
                beat_aligned=beat_aligned,
                energy_level=music_context.get('energy_level'),
                structure_section=music_context.get('structure_section'),
                is_climax=music_context.get('is_climax', False),
                is_drop=music_context.get('is_drop', False)
            )

            cut_plan.cut_points.append(cut_point)
            cut_plan.segment_durations.append(clip_duration)

            current_time += clip_duration

        # Calculate statistics
        cut_plan.calculate_stats()

        logger.info(f"\n  Total cuts: {cut_plan.total_cuts}")
        logger.info(f"  Beat-aligned cuts: {cut_plan.beat_aligned_cuts}")
        logger.info(f"  Climax cuts: {cut_plan.climax_cuts}")
        logger.info(f"  Avg segment duration: {cut_plan.avg_segment_duration:.2f}s")

        # Log source distribution
        source_usage = {}
        for cp in cut_plan.cut_points:
            source_usage[cp.source_segment_idx] = source_usage.get(cp.source_segment_idx, 0) + 1
        logger.info(f"  Source distribution: {source_usage}")

        return cut_plan

    def _get_music_context(self, analysis: AudioAnalysis, time: float) -> dict:
        """
        Get comprehensive music context at given time

        Returns dict with:
        - energy_level: EnergyLevel
        - mood: MusicMood
        - structure_section: TrackSection
        - is_climax: bool
        - is_drop: bool
        - use_beats: bool
        - desired_motion: str (low/medium/high)
        """
        context = {}

        # Energy level
        energy_section = audio_analysis.get_section_at_time(time)
        if energy_section:
            context['energy_level'] = energy_section.energy_level
        else:
            context['energy_level'] = EnergyLevel.MEDIUM

        # Mood
        context['mood'] = audio_analysis.detected_mood

        # Structure
        structure_section = audio_analysis.get_structure_at_time(time)
        if structure_section:
            context['structure_section'] = structure_section.section_type
        else:
            context['structure_section'] = TrackSection.UNKNOWN

        # Special moments
        context['is_climax'] = audio_analysis.is_near_peak(time)
        context['is_drop'] = audio_analysis.is_near_drop(time)

        # Determine if beats should be used
        context['use_beats'] = (
            context['energy_level'] == EnergyLevel.HIGH or
            context['structure_section'] in [TrackSection.CHORUS, TrackSection.DROP] or
            context['is_drop']
        )

        # Determine desired motion level
        context['desired_motion'] = self._determine_desired_motion(context)

        return context

    def _determine_desired_motion(self, music_context: dict) -> str:
        """Determine what motion level we want in video based on music"""

        energy = music_context.get('energy_level')
        mood = music_context.get('mood')
        structure = music_context.get('structure_section')

        # High motion for energetic contexts
        if (energy == EnergyLevel.HIGH or
            structure in [TrackSection.CHORUS, TrackSection.DROP] or
            music_context.get('is_drop', False) or
            music_context.get('is_climax', False) or
            mood in [MusicMood.ENERGETIC, MusicMood.AGGRESSIVE, MusicMood.HAPPY]):
            return 'high'

        # Low motion for calm contexts
        elif (energy == EnergyLevel.LOW or
              structure in [TrackSection.INTRO, TrackSection.OUTRO] or
              mood in [MusicMood.CALM, MusicMood.ATMOSPHERIC, MusicMood.ROMANTIC]):
            return 'low'

        # Medium motion for everything else
        else:
            return 'medium'

    def _get_context_appropriate_duration(self, music_context: dict, min_dur: float,
                                         max_dur: float, remaining: float) -> float:
        """Determine appropriate clip duration based on music context"""

        energy = music_context.get('energy_level', EnergyLevel.MEDIUM)
        structure = music_context.get('structure_section')
        is_climax = music_context.get('is_climax', False)
        is_drop = music_context.get('is_drop', False)

        # Base duration
        if energy == EnergyLevel.HIGH or is_climax or is_drop:
            # Short clips for high energy
            duration = random.uniform(min_dur, min_dur + (max_dur - min_dur) * 0.4)
        elif energy == EnergyLevel.LOW:
            # Long clips for low energy
            duration = random.uniform(min_dur + (max_dur - min_dur) * 0.6, max_dur)
        else:
            # Medium clips
            duration = random.uniform(min_dur + (max_dur - min_dur) * 0.3,
                                    min_dur + (max_dur - min_dur) * 0.7)

        # Adjust for structure
        if structure == TrackSection.INTRO or structure == TrackSection.OUTRO:
            duration *= 1.3  # Longer establishing/closing shots
        elif structure == TrackSection.DROP:
            duration *= 0.7  # Shorter intense shots

        # Clamp to remaining time
        duration = min(duration, remaining)
        duration = max(duration, 0.5)

        return duration

    def _select_matching_source(self, available_segments: List, music_context: dict,
                                recent_sources: List[int]) -> int:
        """
        Select video source that best matches music context

        Note: This is a simplified version. In a real implementation,
        you would have access to video segment metadata (motion score,
        quality score, visual features, etc.) and could do sophisticated matching.

        For now, we use a heuristic approach with some randomness.
        """
        desired_motion = music_context.get('desired_motion', 'medium')

        # Create candidate list (avoid recent available_segments)
        candidates = []
        for i, source in enumerate(available_segments):
            if i not in recent_sources[-min(3, len(recent_sources)):]:  # Avoid last 3
                candidates.append(i)

        if not candidates:
            # All available_segments were recent, just use any
            candidates = list(range(len(available_segments)))

        # Simple selection strategy based on desired motion
        # In a real implementation, you would use actual motion scores
        if desired_motion == 'high':
            # Prefer available_segments with higher indices (heuristic: later in video = more action)
            weights = [i + 1 for i in candidates]
        elif desired_motion == 'low':
            # Prefer available_segments with lower indices (heuristic: earlier = establishing)
            weights = [len(available_segments) - i for i in candidates]
        else:
            # Uniform distribution
            weights = [1.0 for _ in candidates]

        # Add randomness
        weights = np.array(weights, dtype=float)
        weights = weights / weights.sum()

        selected_idx = np.random.choice(candidates, p=weights)

        return selected_idx
