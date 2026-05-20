"""
Preset loader - loads presets from YAML files
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, Optional
from dataclasses import fields

from .preset_models import (
    Preset, PresetSettings, ClipSelectionSettings, TransitionSettings,
    SpeedEffectSettings, ColorSettings, MusicSyncSettings, QualityFilterSettings,
    ExportSettings, AudioSelectionSettings, FramingSettings,
    DynamicLevel, TransitionType, SpeedEffectMode, ColorStyle,
    MusicSyncMode, ExportFormat, ExportQuality, StabilizationLevel,
    Intensity, AudioSelectionMode, FitMode, CropPosition
)

logger = logging.getLogger(__name__)


class PresetLoader:
    """Loads and parses preset files from YAML"""

    def __init__(self, presets_dir: Path):
        """
        Initialize preset loader

        Args:
            presets_dir: Directory containing preset YAML files
        """
        self.presets_dir = Path(presets_dir)
        if not self.presets_dir.exists():
            logger.warning(f"Presets directory does not exist: {self.presets_dir}")

    def load_preset(self, preset_file: Path) -> Optional[Preset]:
        """
        Load a single preset from YAML file

        Args:
            preset_file: Path to preset YAML file

        Returns:
            Preset object or None if loading failed
        """
        try:
            with open(preset_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            if not data:
                logger.error(f"Empty preset file: {preset_file}")
                return None

            # Parse preset
            preset = self._parse_preset(data, preset_file)
            logger.info(f"Loaded preset: {preset.name} ({preset.preset_id})")
            return preset

        except Exception as e:
            logger.error(f"Failed to load preset {preset_file}: {e}")
            return None

    def load_all_presets(self) -> Dict[str, Preset]:
        """
        Load all presets from the presets directory

        Returns:
            Dictionary mapping preset_id to Preset object
        """
        presets = {}

        if not self.presets_dir.exists():
            logger.warning(f"Presets directory not found: {self.presets_dir}")
            return presets

        # Load all YAML files
        for preset_file in self.presets_dir.glob("*.yaml"):
            preset = self.load_preset(preset_file)
            if preset:
                presets[preset.preset_id] = preset

        logger.info(f"Loaded {len(presets)} presets from {self.presets_dir}")
        return presets

    def _parse_preset(self, data: dict, source_file: Path) -> Preset:
        """Parse preset data from dictionary"""

        preset_id = data.get('preset_id', source_file.stem)
        name = data.get('name', preset_id)
        description = data.get('description', '')
        emoji = data.get('emoji', '🎬')
        recommended_for = data.get('recommended_for', [])

        settings_data = data.get('settings', {})
        settings = self._parse_settings(settings_data)

        return Preset(
            preset_id=preset_id,
            name=name,
            description=description,
            emoji=emoji,
            recommended_for=recommended_for,
            settings=settings
        )

    def _parse_settings(self, data: dict) -> PresetSettings:
        """Parse settings from dictionary"""

        return PresetSettings(
            dynamic_level=self._parse_enum(data.get('dynamic_level', 'balanced'), DynamicLevel),
            clip_selection=self._parse_clip_selection(data.get('clip_selection', {})),
            transitions=self._parse_transitions(data.get('transitions', {})),
            speed_effects=self._parse_speed_effects(data.get('speed_effects', {})),
            color=self._parse_color(data.get('color', {})),
            music_sync=self._parse_music_sync(data.get('music_sync', {})),
            quality_filters=self._parse_quality_filters(data.get('quality_filters', {})),
            audio_selection=self._parse_audio_selection(data.get('audio_selection', {})),
            framing=self._parse_framing(data.get('framing', {})),
            export=self._parse_export(data.get('export', {}))
        )

    def _parse_clip_selection(self, data: dict) -> ClipSelectionSettings:
        """Parse clip selection settings"""
        return ClipSelectionSettings(
            segment_min_duration=data.get('segment_min_duration', 2.0),
            segment_max_duration=data.get('segment_max_duration', 5.0)
        )

    def _parse_transitions(self, data: dict) -> TransitionSettings:
        """Parse transition settings"""
        return TransitionSettings(
            enabled=data.get('enabled', True),
            type=self._parse_enum(data.get('type', 'cut'), TransitionType),
            duration=data.get('duration', 0.3),
            randomize=data.get('randomize', False)
        )

    def _parse_speed_effects(self, data: dict) -> SpeedEffectSettings:
        """Parse speed effect settings"""
        return SpeedEffectSettings(
            enabled=data.get('enabled', False),
            mode=self._parse_enum(data.get('mode', 'none'), SpeedEffectMode),
            slow_motion_factor=data.get('slow_motion_factor', 0.85),
            speed_up_factor=data.get('speed_up_factor', 1.15),
            intensity=self._parse_enum(data.get('intensity', 'medium'), Intensity)
        )

    def _parse_color(self, data: dict) -> ColorSettings:
        """Parse color settings"""
        return ColorSettings(
            enabled=data.get('enabled', False),
            style=self._parse_enum(data.get('style', 'natural'), ColorStyle),
            intensity=self._parse_enum(data.get('intensity', 'medium'), Intensity)
        )

    def _parse_music_sync(self, data: dict) -> MusicSyncSettings:
        """Parse music sync settings"""
        return MusicSyncSettings(
            enabled=data.get('enabled', True),
            mode=self._parse_enum(data.get('mode', 'simple_tempo'), MusicSyncMode)
        )

    def _parse_quality_filters(self, data: dict) -> QualityFilterSettings:
        """Parse quality filter settings"""
        return QualityFilterSettings(
            enabled=data.get('enabled', True),
            remove_blurry=data.get('remove_blurry', True),
            remove_dark=data.get('remove_dark', True),
            remove_shaky=data.get('remove_shaky', False),
            stabilization=self._parse_enum(data.get('stabilization', 'none'), StabilizationLevel)
        )

    def _parse_audio_selection(self, data: dict) -> AudioSelectionSettings:
        """Parse audio selection settings"""
        return AudioSelectionSettings(
            enabled=data.get('enabled', True),
            mode=self._parse_enum(data.get('mode', 'auto_highlight'), AudioSelectionMode),
            manual_start=data.get('manual_start'),
            manual_end=data.get('manual_end'),
            avoid_intro=data.get('avoid_intro', True),
            avoid_intro_seconds=data.get('avoid_intro_seconds', 10.0),
            avoid_last_seconds=data.get('avoid_last_seconds', True),
            avoid_last_seconds_count=data.get('avoid_last_seconds_count', 8.0),
            analysis_window_sec=data.get('analysis_window_sec', 2.0),
            hop_sec=data.get('hop_sec', 0.5),
            prefer_energy=data.get('prefer_energy', True),
            prefer_stability=data.get('prefer_stability', True),
            prefer_climax=data.get('prefer_climax', True),
            fade_in=data.get('fade_in', 1.5),
            fade_out=data.get('fade_out', 2.5),
            loop_audio_if_short=data.get('loop_audio_if_short', False),
            fallback_mode=self._parse_enum(
                data.get('fallback_mode', 'from_start'), AudioSelectionMode
            )
        )

    def _parse_framing(self, data: dict) -> FramingSettings:
        """Parse framing settings"""
        return FramingSettings(
            output_format=self._parse_enum(data.get('output_format', 'original'), ExportFormat),
            resolution=data.get('resolution'),
            fit_mode=self._parse_enum(data.get('fit_mode', 'fill'), FitMode),
            allow_crop=data.get('allow_crop', True),
            avoid_black_bars=data.get('avoid_black_bars', True),
            crop_position=self._parse_enum(data.get('crop_position', 'center'), CropPosition)
        )

    def _parse_export(self, data: dict) -> ExportSettings:
        """Parse export settings"""
        return ExportSettings(
            format=self._parse_enum(data.get('format', 'original'), ExportFormat),
            resolution=data.get('resolution'),
            quality=self._parse_enum(data.get('quality', 'high'), ExportQuality),
            hardware_acceleration=data.get('hardware_acceleration', 'auto')
        )

    def _normalize_value(self, value: str, enum_class) -> str:
        """
        Normalize value before parsing to enum
        Handles specific normalization cases from user requirements

        Args:
            value: String value to normalize
            enum_class: Target enum class

        Returns:
            Normalized value
        """
        if not value:
            return value

        value = str(value).lower().strip()

        # Normalize intensity: low → light
        if enum_class == Intensity:
            if value == 'low':
                logger.info(f"Normalizing intensity 'low' → 'light'")
                return 'light'

        # Normalize stabilization: high → medium (high not supported)
        if enum_class == StabilizationLevel:
            if value == 'high':
                logger.info(f"Normalizing stabilization 'high' → 'medium' (high not supported)")
                return 'medium'

        return value

    def _parse_enum(self, value: str, enum_class):
        """
        Parse enum value with normalization, return default if invalid

        Args:
            value: String value to parse
            enum_class: Enum class

        Returns:
            Enum value or first enum value as default
        """
        # Apply normalization first
        normalized_value = self._normalize_value(value, enum_class)

        try:
            return enum_class(normalized_value)
        except (ValueError, KeyError):
            default = list(enum_class)[0]
            logger.warning(f"Invalid {enum_class.__name__} value: {normalized_value} (original: {value}), using fallback {default.value}")
            return default
