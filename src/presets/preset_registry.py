"""
Preset registry and applier - manages presets and applies them to projects
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

from .preset_models import Preset, PresetSettings, ProjectEditMode, EditMode
from .preset_loader import PresetLoader
from .preset_validator import PresetValidator

logger = logging.getLogger(__name__)


class PresetRegistry:
    """
    Central registry for all presets
    Loads, validates, and manages presets
    """

    def __init__(self, presets_dir: Path):
        """
        Initialize preset registry

        Args:
            presets_dir: Directory containing preset YAML files
        """
        self.presets_dir = Path(presets_dir)
        self.loader = PresetLoader(presets_dir)
        self.validator = PresetValidator()
        self.presets: Dict[str, Preset] = {}
        self._load_presets()

    def _load_presets(self):
        """Load and validate all presets"""
        raw_presets = self.loader.load_all_presets()

        for preset_id, preset in raw_presets.items():
            validated_preset, has_warnings = self.validator.validate_preset(preset)
            self.presets[preset_id] = validated_preset

            if has_warnings:
                logger.warning(f"Preset '{preset_id}' loaded with warnings")

        logger.info(f"Preset registry initialized with {len(self.presets)} presets")

    def get_preset(self, preset_id: str) -> Optional[Preset]:
        """
        Get preset by ID

        Args:
            preset_id: Preset identifier

        Returns:
            Preset object or None if not found
        """
        return self.presets.get(preset_id)

    def list_presets(self) -> List[Dict[str, str]]:
        """
        List all available presets with basic info

        Returns:
            List of dicts with preset info
        """
        return [
            {
                'preset_id': preset.preset_id,
                'name': preset.name,
                'emoji': preset.emoji,
                'description': preset.description,
                'recommended_for': ', '.join(preset.recommended_for)
            }
            for preset in self.presets.values()
        ]

    def get_preset_names(self) -> List[str]:
        """Get list of preset names"""
        return [preset.name for preset in self.presets.values()]

    def get_preset_ids(self) -> List[str]:
        """Get list of preset IDs"""
        return list(self.presets.keys())

    def reload_presets(self):
        """Reload all presets from disk"""
        logger.info("Reloading presets...")
        self.presets.clear()
        self._load_presets()


class PresetApplier:
    """
    Applies presets to project configuration
    Handles conversion between preset format and project format
    """

    def __init__(self, registry: PresetRegistry):
        """
        Initialize preset applier

        Args:
            registry: Preset registry
        """
        self.registry = registry

    def apply_preset_to_project(self, preset_id: str, project_config: dict) -> dict:
        """
        Apply preset settings to project configuration

        Args:
            preset_id: ID of preset to apply
            project_config: Existing project configuration dict

        Returns:
            Updated project configuration with preset applied
        """
        preset = self.registry.get_preset(preset_id)
        if not preset:
            logger.error(f"Preset '{preset_id}' not found")
            return project_config

        # Log preset selection
        logger.info(f"Applying preset: {preset.name} ({preset_id})")
        self.registry.validator.log_preset_summary(preset)

        # Update edit mode
        if 'edit_mode' not in project_config:
            project_config['edit_mode'] = {}

        project_config['edit_mode']['type'] = EditMode.PRESET.value
        project_config['edit_mode']['selected_preset'] = preset_id
        project_config['edit_mode']['manual_overrides'] = False

        # Convert preset settings to project settings format
        settings = self._convert_preset_to_project_settings(preset.settings)

        # Merge with existing settings (preset settings take precedence)
        if 'settings' not in project_config:
            project_config['settings'] = {}

        project_config['settings'].update(settings)

        logger.info(f"Preset '{preset_id}' applied successfully")
        return project_config

    def _convert_preset_to_project_settings(self, preset_settings: PresetSettings) -> dict:
        """
        Convert PresetSettings to project config format

        Args:
            preset_settings: Preset settings object

        Returns:
            Dictionary in project config format
        """
        return {
            'dynamic_level': preset_settings.dynamic_level.value,

            'clip_selection': {
                'segment_min_duration': preset_settings.clip_selection.segment_min_duration,
                'segment_max_duration': preset_settings.clip_selection.segment_max_duration
            },

            'transitions': {
                'enabled': preset_settings.transitions.enabled,
                'type': preset_settings.transitions.type.value,
                'duration': preset_settings.transitions.duration,
                'randomize': preset_settings.transitions.randomize
            },

            'speed_effects': {
                'enabled': preset_settings.speed_effects.enabled,
                'mode': preset_settings.speed_effects.mode.value,
                'slow_motion_factor': preset_settings.speed_effects.slow_motion_factor,
                'speed_up_factor': preset_settings.speed_effects.speed_up_factor,
                'intensity': preset_settings.speed_effects.intensity.value
            },

            'color': {
                'enabled': preset_settings.color.enabled,
                'style': preset_settings.color.style.value,
                'intensity': preset_settings.color.intensity.value
            },

            'music_sync': {
                'enabled': preset_settings.music_sync.enabled,
                'mode': preset_settings.music_sync.mode.value
            },

            'quality_filters': {
                'enabled': preset_settings.quality_filters.enabled,
                'remove_blurry': preset_settings.quality_filters.remove_blurry,
                'remove_dark': preset_settings.quality_filters.remove_dark,
                'remove_shaky': preset_settings.quality_filters.remove_shaky,
                'stabilization': preset_settings.quality_filters.stabilization.value
            },

            'audio_selection': {
                'enabled': preset_settings.audio_selection.enabled,
                'mode': preset_settings.audio_selection.mode.value,
                'avoid_intro': preset_settings.audio_selection.avoid_intro,
                'avoid_intro_seconds': preset_settings.audio_selection.avoid_intro_seconds,
                'avoid_last_seconds': preset_settings.audio_selection.avoid_last_seconds,
                'avoid_last_seconds_count': preset_settings.audio_selection.avoid_last_seconds_count,
                'fade_in': preset_settings.audio_selection.fade_in,
                'fade_out': preset_settings.audio_selection.fade_out,
                'loop_audio_if_short': preset_settings.audio_selection.loop_audio_if_short
            },

            'framing': {
                'output_format': preset_settings.framing.output_format.value,
                'resolution': preset_settings.framing.resolution,
                'fit_mode': preset_settings.framing.fit_mode.value,
                'allow_crop': preset_settings.framing.allow_crop,
                'avoid_black_bars': preset_settings.framing.avoid_black_bars,
                'crop_position': preset_settings.framing.crop_position.value
            },

            'export': {
                'format': preset_settings.export.format.value,
                'resolution': preset_settings.export.resolution,
                'quality': preset_settings.export.quality.value,
                'hardware_acceleration': preset_settings.export.hardware_acceleration
            }
        }

    def mark_manual_overrides(self, project_config: dict):
        """
        Mark that user has made manual overrides to preset

        Args:
            project_config: Project configuration dict
        """
        if 'edit_mode' in project_config and project_config['edit_mode'].get('type') == EditMode.PRESET.value:
            project_config['edit_mode']['type'] = EditMode.PRESET_WITH_MANUAL_OVERRIDES.value
            project_config['edit_mode']['manual_overrides'] = True

            logger.info("[Preset] Manual overrides enabled")

            if 'selected_preset' in project_config['edit_mode']:
                logger.info(f"[Preset] Base preset: {project_config['edit_mode']['selected_preset']}")
