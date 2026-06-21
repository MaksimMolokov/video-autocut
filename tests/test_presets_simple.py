"""
Simple unit tests for preset loading and validation using unittest
Tests all 10 presets to ensure they are valid and complete
"""

import unittest
from pathlib import Path
import sys
import re

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.presets import PresetRegistry, PresetLoader, PresetValidator
from src.presets.preset_models import (
    DynamicLevel, TransitionType, SpeedEffectMode, ColorStyle,
    MusicSyncMode, AudioSelectionMode, FitMode, CropPosition,
    ExportFormat, ExportQuality
)


class TestPresetLoading(unittest.TestCase):
    """Test that all presets load correctly"""

    @classmethod
    def setUpClass(cls):
        """Setup test fixtures"""
        cls.presets_dir = Path(__file__).parent.parent / "presets"
        cls.loader = PresetLoader(cls.presets_dir)
        cls.validator = PresetValidator()
        cls.registry = PresetRegistry(cls.presets_dir)

    def test_01_presets_directory_exists(self):
        """Test that presets directory exists"""
        self.assertTrue(self.presets_dir.exists(), f"Presets directory not found: {self.presets_dir}")
        self.assertTrue(self.presets_dir.is_dir(), f"Presets path is not a directory")

    def test_02_all_10_presets_exist(self):
        """Test that all core presets exist"""
        expected_presets = [
            "easy_mode",
            "drone_nature_cinematic",
            "drone_landscape_clean",
            "fast_action_sport",
            "urban_city_rhythm",
            "social_media_punchy",
            "business_promo_clean",
            "real_estate_property_tour",
            "travel_story",
            "event_highlights",
            "calm_minimal_documentary",
            "intelligent_beauty_mix",
            "sport_dynamic_cut",
            "sport_highlight_impact",
        ]

        for preset_id in expected_presets:
            preset_file = self.presets_dir / f"{preset_id}.yaml"
            self.assertTrue(preset_file.exists(), f"Preset file not found: {preset_file}")
            print(f"✓ Found preset: {preset_id}")

    def test_03_all_presets_load(self):
        """Test that all presets load without errors"""
        presets = self.loader.load_all_presets()
        self.assertGreaterEqual(len(presets), 10, f"Expected at least 10 presets, found {len(presets)}")

        print(f"\n✓ Loaded {len(presets)} presets:")
        for preset_id, preset in presets.items():
            self.assertIsNotNone(preset, f"Preset {preset_id} failed to load")
            self.assertEqual(preset.preset_id, preset_id, f"Preset ID mismatch")
            print(f"  - {preset.emoji} {preset.name} ({preset_id})")

    def test_04_preset_has_all_10_settings_blocks(self):
        """Test that each preset has all 10 required settings blocks"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            settings = preset.settings

            # Check dynamic_level
            self.assertIsNotNone(settings.dynamic_level, f"{preset_id}: missing dynamic_level")

            # Check all setting blocks exist
            self.assertIsNotNone(settings.clip_selection, f"{preset_id}: missing clip_selection")
            self.assertIsNotNone(settings.transitions, f"{preset_id}: missing transitions")
            self.assertIsNotNone(settings.speed_effects, f"{preset_id}: missing speed_effects")
            self.assertIsNotNone(settings.color, f"{preset_id}: missing color")
            self.assertIsNotNone(settings.music_sync, f"{preset_id}: missing music_sync")
            self.assertIsNotNone(settings.quality_filters, f"{preset_id}: missing quality_filters")
            self.assertIsNotNone(settings.audio_selection, f"{preset_id}: missing audio_selection")
            self.assertIsNotNone(settings.framing, f"{preset_id}: missing framing")
            self.assertIsNotNone(settings.export, f"{preset_id}: missing export")

            print(f"✓ {preset_id}: all 10 settings blocks present")


class TestPresetValidation(unittest.TestCase):
    """Test preset validation logic"""

    @classmethod
    def setUpClass(cls):
        """Setup test fixtures"""
        cls.presets_dir = Path(__file__).parent.parent / "presets"
        cls.validator = PresetValidator()
        cls.loader = PresetLoader(cls.presets_dir)

    def test_05_valid_enum_values(self):
        """Test that all enum values are valid"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            s = preset.settings

            # Check dynamic_level
            self.assertIsInstance(s.dynamic_level, DynamicLevel,
                f"{preset_id}: invalid dynamic_level type")

            # Check transitions.type
            self.assertIsInstance(s.transitions.type, TransitionType,
                f"{preset_id}: invalid transition type")

            # Check speed_effects.mode
            self.assertIsInstance(s.speed_effects.mode, SpeedEffectMode,
                f"{preset_id}: invalid speed_effects mode")

            # Check color.style
            self.assertIsInstance(s.color.style, ColorStyle,
                f"{preset_id}: invalid color style")

            # Check music_sync.mode
            self.assertIsInstance(s.music_sync.mode, MusicSyncMode,
                f"{preset_id}: invalid music_sync mode")

            # Check audio_selection.mode
            self.assertIsInstance(s.audio_selection.mode, AudioSelectionMode,
                f"{preset_id}: invalid audio_selection mode")

            print(f"✓ {preset_id}: all enum values valid")

    def test_06_segment_duration_logic(self):
        """Test that segment_min_duration < segment_max_duration"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            clip = preset.settings.clip_selection
            self.assertLess(clip.segment_min_duration, clip.segment_max_duration,
                f"{preset_id}: segment_min_duration >= segment_max_duration")
            print(f"✓ {preset_id}: segment durations valid ({clip.segment_min_duration}s - {clip.segment_max_duration}s)")

    def test_07_transition_duration_range(self):
        """Test that transition duration is in acceptable range"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            duration = preset.settings.transitions.duration
            self.assertGreaterEqual(duration, 0.0,
                f"{preset_id}: transition duration < 0.0")
            self.assertLessEqual(duration, 2.0,
                f"{preset_id}: transition duration > 2.0")
            print(f"✓ {preset_id}: transition duration valid ({duration}s)")

    def test_08_speed_factors_range(self):
        """Test that speed factors are in acceptable range"""
        presets = self.loader.load_all_presets()

        for preset_id, preset in presets.items():
            speed = preset.settings.speed_effects
            if not speed.enabled:
                # Выключенные speed-эффекты держат нейтральный factor 1.0 — это валидно
                continue

            # Slow motion factor should be < 1.0
            self.assertGreaterEqual(speed.slow_motion_factor, 0.3,
                f"{preset_id}: slow_motion_factor too low")
            self.assertLess(speed.slow_motion_factor, 1.0,
                f"{preset_id}: slow_motion_factor >= 1.0")

            # Speed up factor should be > 1.0
            self.assertGreater(speed.speed_up_factor, 1.0,
                f"{preset_id}: speed_up_factor <= 1.0")
            self.assertLessEqual(speed.speed_up_factor, 3.0,
                f"{preset_id}: speed_up_factor too high")

            print(f"✓ {preset_id}: speed factors valid (slow: {speed.slow_motion_factor}, fast: {speed.speed_up_factor})")

    def test_09_resolution_format(self):
        """Test that resolution is either null or in format WIDTHxHEIGHT"""
        presets = self.loader.load_all_presets()
        resolution_pattern = re.compile(r'^\d+x\d+$')

        for preset_id, preset in presets.items():
            # Check framing resolution
            framing_res = preset.settings.framing.resolution
            if framing_res is not None:
                self.assertIsNotNone(resolution_pattern.match(framing_res),
                    f"{preset_id}: invalid framing resolution format: {framing_res}")

            # Check export resolution
            export_res = preset.settings.export.resolution
            if export_res is not None:
                self.assertIsNotNone(resolution_pattern.match(export_res),
                    f"{preset_id}: invalid export resolution format: {export_res}")

            print(f"✓ {preset_id}: resolution format valid")


class TestPresetRegistry(unittest.TestCase):
    """Test preset registry operations"""

    @classmethod
    def setUpClass(cls):
        """Setup test fixtures"""
        cls.presets_dir = Path(__file__).parent.parent / "presets"
        cls.registry = PresetRegistry(cls.presets_dir)

    def test_10_registry_lists_all_presets(self):
        """Test that registry lists all presets"""
        presets_list = self.registry.list_presets()
        self.assertGreaterEqual(len(presets_list), 10,
            f"Expected at least 10 presets, got {len(presets_list)}")

        print(f"\n✓ Registry contains {len(presets_list)} presets:")
        for preset_info in presets_list:
            self.assertIn("preset_id", preset_info)
            self.assertIn("name", preset_info)
            self.assertIn("emoji", preset_info)
            self.assertIn("description", preset_info)
            print(f"  {preset_info['emoji']} {preset_info['name']}")

    def test_11_registry_get_preset_by_id(self):
        """Test getting individual presets by ID"""
        test_ids = ["easy_mode", "drone_nature_cinematic", "social_media_punchy"]

        for preset_id in test_ids:
            preset = self.registry.get_preset(preset_id)
            self.assertIsNotNone(preset, f"Failed to get preset: {preset_id}")
            self.assertEqual(preset.preset_id, preset_id)
            print(f"✓ Successfully retrieved preset: {preset_id}")

    def test_12_registry_get_nonexistent_preset(self):
        """Test getting a nonexistent preset returns None"""
        preset = self.registry.get_preset("nonexistent_preset_xyz")
        self.assertIsNone(preset, "Nonexistent preset should return None")
        print("✓ Nonexistent preset correctly returns None")


def run_tests():
    """Run all tests and print summary"""
    print("\n" + "="*70)
    print("RUNNING PRESET VALIDATION TESTS")
    print("="*70 + "\n")

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestPresetLoading))
    suite.addTests(loader.loadTestsFromTestCase(TestPresetValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestPresetRegistry))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Total tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")

    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED!")
    else:
        print("\n❌ SOME TESTS FAILED")

    print("="*70 + "\n")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
