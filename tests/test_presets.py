"""
Unit tests for preset loading and validation
Tests all 10 presets to ensure they are valid and complete
"""

import pytest
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.presets import PresetRegistry, PresetLoader, PresetValidator
from src.presets.preset_models import (
    DynamicLevel, TransitionType, SpeedEffectMode, ColorStyle,
    MusicSyncMode, AudioSelectionMode, FitMode, CropPosition,
    ExportFormat, ExportQuality, HardwareAcceleration
)


class TestPresetLoading:
    """Test that all presets load correctly"""

    def setup_method(self):
        """Setup test fixtures"""
        self.presets_dir = Path(__file__).parent.parent / "presets"
        self.loader = PresetLoader(self.presets_dir)
        self.validator = PresetValidator()
        self.registry = PresetRegistry(self.presets_dir)

    def test_presets_directory_exists(self):
        """Test that presets directory exists"""
        assert self.presets_dir.exists(), f"Presets directory not found: {self.presets_dir}"
        assert self.presets_dir.is_dir(), f"Presets path is not a directory: {self.presets_dir}"

    def test_all_10_presets_exist(self):
        """Test that all 10 presets exist"""
        expected_presets = [
            "clean_basic",
            "cinematic_nature_drone",
            "urban_drone_promo",
            "fast_action_sport",
            "fpv_fast_cut",
            "social_reels_dynamic",
            "business_promo_clean",
            "real_estate_object_showcase",
            "travel_memories",
            "construction_inspection_report"
        ]

        for preset_id in expected_presets:
            preset_file = self.presets_dir / f"{preset_id}.yaml"
            assert preset_file.exists(), f"Preset file not found: {preset_file}"

    def test_all_presets_load(self):
        """Test that all presets load without errors"""
        presets = self.loader.load_all_presets()
        assert len(presets) >= 10, f"Expected at least 10 presets, found {len(presets)}"

        for preset_id, preset in presets.items():
            assert preset is not None, f"Preset {preset_id} failed to load"
            assert preset.preset_id == preset_id, f"Preset ID mismatch: {preset.preset_id} != {preset_id}"

    def test_preset_has_required_fields(self):
        """Test that each preset has all required fields"""
        required_fields = ["preset_id", "name", "emoji", "description", "recommended_for", "settings"]

        presets = self.loader.load_all_presets()
        for preset_id, preset in presets.items():
            assert preset.preset_id, f"{preset_id}: missing preset_id"
            assert preset.name, f"{preset_id}: missing name"
            assert preset.emoji, f"{preset_id}: missing emoji"
            assert preset.description, f"{preset_id}: missing description"
            assert preset.recommended_for, f"{preset_id}: missing recommended_for"
            assert preset.settings, f"{preset_id}: missing settings"

    def test_preset_has_all_10_settings_blocks(self):
        """Test that each preset has all 10 required settings blocks"""
        required_blocks = [
            "dynamic_level",
            "clip_selection",
            "transitions",
            "speed_effects",
            "color",
            "music_sync",
            "quality_filters",
            "audio_selection",
            "framing",
            "export"
        ]

        presets = self.loader.load_all_presets()
        for preset_id, preset in presets.items():
            settings = preset.settings

            # Check dynamic_level
            assert settings.dynamic_level is not None, f"{preset_id}: missing dynamic_level"

            # Check all setting blocks exist
            assert settings.clip_selection is not None, f"{preset_id}: missing clip_selection"
            assert settings.transitions is not None, f"{preset_id}: missing transitions"
            assert settings.speed_effects is not None, f"{preset_id}: missing speed_effects"
            assert settings.color is not None, f"{preset_id}: missing color"
            assert settings.music_sync is not None, f"{preset_id}: missing music_sync"
            assert settings.quality_filters is not None, f"{preset_id}: missing quality_filters"
            assert settings.audio_selection is not None, f"{preset_id}: missing audio_selection"
            assert settings.framing is not None, f"{preset_id}: missing framing"
            assert settings.export is not None, f"{preset_id}: missing export"


class TestPresetValidation:
    """Test preset validation logic"""

    def setup_method(self):
        """Setup test fixtures"""
        self.presets_dir = Path(__file__).parent.parent / "presets"
        self.validator = PresetValidator()
        self.loader = PresetLoader(self.presets_dir)

    def test_valid_enum_values(self):
        """Test that all enum values are valid"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            s = preset.settings

            # Check dynamic_level
            assert isinstance(s.dynamic_level, DynamicLevel), \
                f"{preset_id}: invalid dynamic_level type"

            # Check transitions.type
            assert isinstance(s.transitions.type, TransitionType), \
                f"{preset_id}: invalid transition type"

            # Check speed_effects.mode
            assert isinstance(s.speed_effects.mode, SpeedEffectMode), \
                f"{preset_id}: invalid speed_effects mode"

            # Check color.style
            assert isinstance(s.color.style, ColorStyle), \
                f"{preset_id}: invalid color style"

            # Check music_sync.mode
            assert isinstance(s.music_sync.mode, MusicSyncMode), \
                f"{preset_id}: invalid music_sync mode"

            # Check audio_selection.mode
            assert isinstance(s.audio_selection.mode, AudioSelectionMode), \
                f"{preset_id}: invalid audio_selection mode"

            # Check framing.output_format
            assert isinstance(s.framing.output_format, ExportFormat), \
                f"{preset_id}: invalid framing output_format"

            # Check framing.fit_mode
            assert isinstance(s.framing.fit_mode, FitMode), \
                f"{preset_id}: invalid framing fit_mode"

            # Check framing.crop_position
            assert isinstance(s.framing.crop_position, CropPosition), \
                f"{preset_id}: invalid framing crop_position"

            # Check export.quality
            assert isinstance(s.export.quality, ExportQuality), \
                f"{preset_id}: invalid export quality"

    def test_segment_duration_logic(self):
        """Test that segment_min_duration < segment_max_duration"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            clip = preset.settings.clip_selection
            assert clip.segment_min_duration < clip.segment_max_duration, \
                f"{preset_id}: segment_min_duration ({clip.segment_min_duration}) >= segment_max_duration ({clip.segment_max_duration})"

    def test_transition_duration_range(self):
        """Test that transition duration is in acceptable range"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            duration = preset.settings.transitions.duration
            assert 0.0 <= duration <= 2.0, \
                f"{preset_id}: transition duration {duration} out of range [0.0, 2.0]"

    def test_speed_factors_range(self):
        """Test that speed factors are in acceptable range"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            speed = preset.settings.speed_effects

            # Slow motion factor should be < 1.0
            assert 0.3 <= speed.slow_motion_factor < 1.0, \
                f"{preset_id}: slow_motion_factor {speed.slow_motion_factor} out of range [0.3, 1.0)"

            # Speed up factor should be > 1.0
            assert 1.0 < speed.speed_up_factor <= 3.0, \
                f"{preset_id}: speed_up_factor {speed.speed_up_factor} out of range (1.0, 3.0]"

    def test_audio_selection_parameters(self):
        """Test audio selection parameters are in valid ranges"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            audio = preset.settings.audio_selection

            # Check avoid_intro_seconds
            assert audio.avoid_intro_seconds >= 0.0, \
                f"{preset_id}: negative avoid_intro_seconds"

            # Check avoid_last_seconds_count
            assert audio.avoid_last_seconds_count >= 0.0, \
                f"{preset_id}: negative avoid_last_seconds_count"

            # Check analysis_window_sec
            assert audio.analysis_window_sec > 0.0, \
                f"{preset_id}: non-positive analysis_window_sec"

            # Check hop_sec
            assert audio.hop_sec > 0.0, \
                f"{preset_id}: non-positive hop_sec"

            # Check fade_in/fade_out
            assert audio.fade_in >= 0.0, f"{preset_id}: negative fade_in"
            assert audio.fade_out >= 0.0, f"{preset_id}: negative fade_out"

    def test_resolution_format(self):
        """Test that resolution is either null or in format WIDTHxHEIGHT"""
        import re
        presets = self.loader.load_all_presets()
        resolution_pattern = re.compile(r'^\d+x\d+$')

        for preset_id, preset in presets.items():
            # Check framing resolution
            framing_res = preset.settings.framing.resolution
            if framing_res is not None:
                assert resolution_pattern.match(framing_res), \
                    f"{preset_id}: invalid framing resolution format: {framing_res}"

            # Check export resolution
            export_res = preset.settings.export.resolution
            if export_res is not None:
                assert resolution_pattern.match(export_res), \
                    f"{preset_id}: invalid export resolution format: {export_res}"


class TestPresetRegistry:
    """Test preset registry operations"""

    def setup_method(self):
        """Setup test fixtures"""
        self.presets_dir = Path(__file__).parent.parent / "presets"
        self.registry = PresetRegistry(self.presets_dir)

    def test_registry_lists_all_presets(self):
        """Test that registry lists all presets"""
        presets_list = self.registry.list_presets()
        assert len(presets_list) >= 10, f"Expected at least 10 presets, got {len(presets_list)}"

        for preset_info in presets_list:
            assert "id" in preset_info
            assert "name" in preset_info
            assert "emoji" in preset_info
            assert "description" in preset_info

    def test_registry_get_preset_by_id(self):
        """Test getting individual presets by ID"""
        test_ids = ["clean_basic", "cinematic_nature_drone", "social_reels_dynamic"]

        for preset_id in test_ids:
            preset = self.registry.get_preset(preset_id)
            assert preset is not None, f"Failed to get preset: {preset_id}"
            assert preset.preset_id == preset_id

    def test_registry_get_nonexistent_preset(self):
        """Test getting a nonexistent preset returns None"""
        preset = self.registry.get_preset("nonexistent_preset_xyz")
        assert preset is None


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
