"""
Preset validator - validates preset settings and provides fallbacks
"""

import logging
from typing import Dict, Any

from .preset_models import (
    Preset, PresetSettings, TransitionType, SpeedEffectMode,
    MusicSyncMode, StabilizationLevel
)

logger = logging.getLogger(__name__)


class PresetValidator:
    """Validates preset settings and provides fallback values"""

    # Supported features - can be extended as features are implemented
    SUPPORTED_TRANSITIONS = {
        TransitionType.CUT,
        TransitionType.FADE,
        TransitionType.CROSSFADE,
        TransitionType.FLASH,
        TransitionType.BLUR,
        TransitionType.ZOOM
    }

    SUPPORTED_SPEED_MODES = {
        SpeedEffectMode.NONE,
        SpeedEffectMode.SLOW_MOTION,
        SpeedEffectMode.SPEED_UP,
        SpeedEffectMode.SPEED_RAMP
    }

    SUPPORTED_MUSIC_SYNC_MODES = {
        MusicSyncMode.NONE,
        MusicSyncMode.SIMPLE_TEMPO,
        MusicSyncMode.BEAT_SYNC,
        MusicSyncMode.DYNAMIC_SYNC
    }

    FALLBACK_TRANSITION = TransitionType.CUT
    FALLBACK_SPEED_MODE = SpeedEffectMode.NONE
    FALLBACK_MUSIC_SYNC = MusicSyncMode.SIMPLE_TEMPO

    def __init__(self):
        """Initialize validator"""
        pass

    def validate_preset(self, preset: Preset) -> tuple[Preset, bool]:
        """
        Validate preset and apply fallbacks if needed

        Args:
            preset: Preset to validate

        Returns:
            Tuple of (validated_preset, has_warnings)
        """
        has_warnings = False
        settings = preset.settings

        # Validate transitions
        if settings.transitions.type not in self.SUPPORTED_TRANSITIONS:
            logger.warning(
                f"[Preset: {preset.preset_id}] "
                f"Transition '{settings.transitions.type.value}' not supported. "
                f"Using fallback: {self.FALLBACK_TRANSITION.value}"
            )
            settings.transitions.type = self.FALLBACK_TRANSITION
            has_warnings = True

        # Validate speed effects
        if settings.speed_effects.mode not in self.SUPPORTED_SPEED_MODES:
            logger.warning(
                f"[Preset: {preset.preset_id}] "
                f"Speed mode '{settings.speed_effects.mode.value}' not supported. "
                f"Using fallback: {self.FALLBACK_SPEED_MODE.value}"
            )
            settings.speed_effects.mode = self.FALLBACK_SPEED_MODE
            has_warnings = True

        # Validate music sync
        if settings.music_sync.mode not in self.SUPPORTED_MUSIC_SYNC_MODES:
            logger.warning(
                f"[Preset: {preset.preset_id}] "
                f"Music sync mode '{settings.music_sync.mode.value}' not supported. "
                f"Using fallback: {self.FALLBACK_MUSIC_SYNC.value}"
            )
            settings.music_sync.mode = self.FALLBACK_MUSIC_SYNC
            has_warnings = True

        # Validate clip durations
        if settings.clip_selection.segment_min_duration > settings.clip_selection.segment_max_duration:
            logger.warning(
                f"[Preset: {preset.preset_id}] "
                f"Min duration ({settings.clip_selection.segment_min_duration}) > "
                f"Max duration ({settings.clip_selection.segment_max_duration}). Swapping values."
            )
            settings.clip_selection.segment_min_duration, settings.clip_selection.segment_max_duration = \
                settings.clip_selection.segment_max_duration, settings.clip_selection.segment_min_duration
            has_warnings = True

        # Validate audio selection
        if settings.audio_selection.enabled and settings.audio_selection.manual_start is not None:
            if settings.audio_selection.manual_end is None:
                logger.warning(
                    f"[Preset: {preset.preset_id}] "
                    f"Manual audio start specified but no end. Disabling manual range."
                )
                settings.audio_selection.manual_start = None
                has_warnings = True
            elif settings.audio_selection.manual_start >= settings.audio_selection.manual_end:
                logger.warning(
                    f"[Preset: {preset.preset_id}] "
                    f"Manual audio start >= end. Disabling manual range."
                )
                settings.audio_selection.manual_start = None
                settings.audio_selection.manual_end = None
                has_warnings = True

        return preset, has_warnings

    def log_preset_summary(self, preset: Preset):
        """Log summary of preset settings"""
        logger.info(f"[Preset] Selected: {preset.preset_id}")
        logger.info(f"[Preset] Name: {preset.name}")
        logger.info(f"[Preset] Dynamic level: {preset.settings.dynamic_level.value}")
        logger.info(f"[Preset] Transition: {preset.settings.transitions.type.value}")
        logger.info(f"[Preset] Music sync: {preset.settings.music_sync.mode.value}")
        logger.info(f"[Preset] Color style: {preset.settings.color.style.value}")
        logger.info(f"[Preset] Speed effect: {preset.settings.speed_effects.mode.value}")
        logger.info(f"[Preset] Export format: {preset.settings.export.format.value}")

        if preset.settings.audio_selection.enabled:
            logger.info(f"[Preset] Audio selection: {preset.settings.audio_selection.mode.value}")

        if preset.settings.framing.avoid_black_bars:
            logger.info(f"[Preset] Framing: {preset.settings.framing.fit_mode.value}")
