"""
Timeline builder — per-style intro/outro logic.

Public API:
    TimelineBuilder.build(candidates, target_duration, preset_id) → TimelineResult
    AudioBoundaryDetector.find_best_start(audio_path, rule, avoid_sec) → float
    AudioBoundaryDetector.find_best_end(audio_path, start, duration, rule) → float
    get_profile(preset_id) → IntroOutroProfile
"""

from .intro_outro_rules import (
    IntroOutroProfile,
    VideoIntroRule,
    VideoOutroRule,
    AudioIntroRule,
    AudioOutroRule,
    get_profile,
    STYLE_PROFILES,
)
from .intro_outro_scorer import IntroOutroScorer
from .timeline_builder import TimelineBuilder, TimelineResult
from .audio_boundary import AudioBoundaryDetector

__all__ = [
    "IntroOutroProfile",
    "VideoIntroRule",
    "VideoOutroRule",
    "AudioIntroRule",
    "AudioOutroRule",
    "get_profile",
    "STYLE_PROFILES",
    "IntroOutroScorer",
    "TimelineBuilder",
    "TimelineResult",
    "AudioBoundaryDetector",
]
