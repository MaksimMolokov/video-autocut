"""
Mood Adaptive Sync Strategy
Adapts editing style to detected music mood
"""

import logging
import random
from typing import List, Tuple
import numpy as np

from .models import (
    AudioAnalysis, CutPlan, CutPoint, MusicMood, EnergyLevel
)
from .base import MusicSyncStrategy

logger = logging.getLogger(__name__)


class MoodAdaptiveSyncStrategy(MusicSyncStrategy):
    """
    Mood Adaptive Sync - editing adapts to music mood/emotion

    Different editing styles for different moods:
    - CALM: Long, smooth transitions, minimal cuts
    - ENERGETIC: Fast cuts, dynamic
    - DRAMATIC: Varied pace, emphasis on emotional peaks
    - HAPPY: Medium-fast, upbeat rhythm
    - ATMOSPHERIC: Long, flowing, minimal interference
    - AGGRESSIVE: Very fast, sharp cuts, intense
    - ROMANTIC: Medium-slow, smooth, gentle
    - EPIC: Varied, builds to climaxes, dramatic
    """

    def __init__(self, settings: dict):
        self.settings = settings

        # Mood-specific editing parameters
        self.mood_params = {
            MusicMood.CALM: {
                'clip_duration': (4.0, 8.0),
                'pace_variation': 0.2,          # Low variation = consistent
                'transition_sharpness': 0.2,    # Smooth transitions
                'use_beats': False,
                'climax_emphasis': 0.3
            },
            MusicMood.ENERGETIC: {
                'clip_duration': (1.0, 2.5),
                'pace_variation': 0.4,
                'transition_sharpness': 0.7,
                'use_beats': True,
                'climax_emphasis': 0.6
            },
            MusicMood.DRAMATIC: {
                'clip_duration': (2.0, 5.0),
                'pace_variation': 0.7,          # High variation for drama
                'transition_sharpness': 0.5,
                'use_beats': False,
                'climax_emphasis': 0.9          # Strong emphasis on peaks
            },
            MusicMood.HAPPY: {
                'clip_duration': (1.5, 3.0),
                'pace_variation': 0.3,
                'transition_sharpness': 0.6,
                'use_beats': True,
                'climax_emphasis': 0.4
            },
            MusicMood.ATMOSPHERIC: {
                'clip_duration': (5.0, 10.0),
                'pace_variation': 0.15,
                'transition_sharpness': 0.1,    # Very smooth
                'use_beats': False,
                'climax_emphasis': 0.2
            },
            MusicMood.AGGRESSIVE: {
                'clip_duration': (0.5, 1.8),
                'pace_variation': 0.5,
                'transition_sharpness': 0.9,    # Sharp cuts
                'use_beats': True,
                'climax_emphasis': 0.7
            },
            MusicMood.ROMANTIC: {
                'clip_duration': (3.0, 6.0),
                'pace_variation': 0.25,
                'transition_sharpness': 0.3,
                'use_beats': False,
                'climax_emphasis': 0.5
            },
            MusicMood.EPIC: {
                'clip_duration': (2.0, 6.0),
                'pace_variation': 0.8,          # Very varied for epic feel
                'transition_sharpness': 0.6,
                'use_beats': True,
                'climax_emphasis': 1.0          # Maximum climax emphasis
            },
            MusicMood.UNKNOWN: {
                'clip_duration': (2.0, 4.0),
                'pace_variation': 0.4,
                'transition_sharpness': 0.5,
                'use_beats': True,
                'climax_emphasis': 0.5
            }
        }

    def build_cut_plan(self, audio_audio_analysis: AudioAnalysis, available_segments: List,
                      target_duration: float, dynamic_level: str = "balanced") -> CutPlan:
        """
        Build cut plan based on detected mood
        """
        detected_mood = audio_analysis.detected_mood
        mood_confidence = audio_analysis.mood_confidence

        logger.info("[MoodSync] Building mood-adaptive cut plan")
        logger.info(f"  Detected mood: {detected_mood.value} (confidence: {mood_confidence:.2f})")
        logger.info(f"  Target duration: {target_duration:.1f}s")

        # Get mood-specific parameters
        params = self.mood_params.get(detected_mood, self.mood_params[MusicMood.UNKNOWN])

        min_dur, max_dur = params['clip_duration']
        pace_variation = params['pace_variation']
        use_beats = params['use_beats']
        climax_emphasis = params['climax_emphasis']

        # Adjust based on dynamic level
        if dynamic_level == "fast":
            min_dur *= 0.7
            max_dur *= 0.7
        elif dynamic_level == "slow":
            min_dur *= 1.3
            max_dur *= 1.3

        logger.info(f"  Clip duration range: {min_dur:.1f}s - {max_dur:.1f}s")
        logger.info(f"  Pace variation: {pace_variation:.1f}")
        logger.info(f"  Use beats: {use_beats}")
        logger.info(f"  Climax emphasis: {climax_emphasis:.1f}")

        cut_plan = CutPlan(
            target_duration=target_duration,
            applied_settings={'mood': detected_mood.value, 'params': params}
        )

        current_time = 0.0
        source_idx = 0

        while current_time < target_duration:
            # Base duration with mood-specific variation
            base_duration = random.uniform(min_dur, max_dur)

            # Apply pace variation (makes editing more/less varied)
            if pace_variation > 0:
                variation = random.uniform(-pace_variation, pace_variation)
                clip_duration = base_duration * (1.0 + variation)
            else:
                clip_duration = base_duration

            # Clamp to valid range
            clip_duration = max(0.5, min(clip_duration, target_duration - current_time))

            if clip_duration < 0.5:
                break

            # Check for climax and adjust if mood emphasizes it
            is_climax = audio_analysis.is_near_peak(current_time)
            if is_climax and climax_emphasis > 0.5:
                # Shorten clip at climax for more cuts = more intensity
                clip_duration *= (1.0 - climax_emphasis * 0.5)
                clip_duration = max(0.5, clip_duration)
                logger.debug(f"    Climax at {current_time:.1f}s - shortening clip to {clip_duration:.2f}s")

            # Beat alignment if mood uses it
            beat_aligned = False
            if use_beats and audio_analysis.beat_times:
                # Try to find nearest beat
                beat = audio_analysis.get_beat_at_time(current_time, tolerance=0.3)
                if beat:
                    beat_aligned = True

            # Check for drop
            is_drop = audio_analysis.is_near_drop(current_time)

            # Get energy level at this point
            energy_section = audio_analysis.get_section_at_time(current_time)
            energy_level = energy_section.energy_level if energy_section else None

            # Create cut point
            cut_point = CutPoint(
                time=current_time,
                source_segment_idx=source_idx % len(available_segments),
                beat_aligned=beat_aligned,
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

        # Log pace variation stats
        if cut_plan.segment_durations:
            duration_std = np.std(cut_plan.segment_durations)
            logger.info(f"  Duration std dev: {duration_std:.2f}s (variation level)")

        return cut_plan
