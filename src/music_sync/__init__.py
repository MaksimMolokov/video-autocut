"""
Music synchronization module for video editing
Provides beat-aligned and energy-adaptive video cutting based on music analysis
"""

from .models import (
    AudioAnalysis,
    BeatPoint,
    EnergySection,
    EnergyLevel,
    MusicMood,
    TrackSection,
    MusicStructureSection,
    CutPlan,
    CutPoint,
    MusicSyncSettings
)
from .analyzer import MusicAnalyzer
from .advanced_analyzer import AdvancedMusicAnalyzer
from .cache import AudioAnalysisCache
from .simple_tempo import SimpleTempoSync
from .beat_sync import BeatSync
from .dynamic_sync import DynamicSync
from .structure_sync import StructureSyncStrategy
from .mood_sync import MoodAdaptiveSyncStrategy
from .smart_beat_sync import SmartBeatPriorityStrategy
from .visual_match_sync import VisualMusicMatchStrategy
from .base import MusicSyncStrategy


__all__ = [
    # Data models
    'AudioAnalysis',
    'BeatPoint',
    'EnergySection',
    'EnergyLevel',
    'MusicMood',
    'TrackSection',
    'MusicStructureSection',
    'CutPlan',
    'CutPoint',
    'MusicSyncSettings',

    # Analyzers and cache
    'MusicAnalyzer',
    'AdvancedMusicAnalyzer',
    'AudioAnalysisCache',

    # Strategies
    'MusicSyncStrategy',
    'SimpleTempoSync',
    'BeatSync',
    'DynamicSync',
    'StructureSyncStrategy',
    'MoodAdaptiveSyncStrategy',
    'SmartBeatPriorityStrategy',
    'VisualMusicMatchStrategy',

    # Factory function
    'create_strategy',
]


def create_strategy(settings: MusicSyncSettings) -> MusicSyncStrategy:
    """
    Factory function to create appropriate sync strategy

    Args:
        settings: Music sync settings including mode

    Returns:
        Appropriate MusicSyncStrategy instance

    Raises:
        ValueError: If mode is unknown
    """
    mode = settings.mode.lower()

    # Original modes
    if mode == "none" or mode == "simple_tempo":
        return SimpleTempoSync(settings)
    elif mode == "beat_sync":
        return BeatSync(settings)
    elif mode == "dynamic_sync":
        return DynamicSync(settings)

    # New intelligent modes
    elif mode == "structure_sync":
        return StructureSyncStrategy(settings)
    elif mode == "mood_sync":
        return MoodAdaptiveSyncStrategy(settings)
    elif mode == "smart_beat_sync":
        return SmartBeatPriorityStrategy(settings)
    elif mode == "visual_match_sync":
        return VisualMusicMatchStrategy(settings)

    else:
        raise ValueError(f"Unknown music sync mode: {settings.mode}")
