"""
Test script for music sync functionality
Tests basic functionality without requiring actual audio files
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all modules can be imported"""
    print("Testing imports...")

    try:
        from src.music_sync import (
            MusicAnalyzer,
            AudioAnalysisCache,
            MusicSyncSettings,
            create_strategy,
            SimpleTempoSync,
            BeatSync,
            DynamicSync,
            EnergyLevel
        )
        print("✓ All music_sync imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_cache():
    """Test cache functionality"""
    print("\nTesting cache...")

    try:
        from src.music_sync import AudioAnalysisCache

        cache = AudioAnalysisCache(cache_dir="temp/audio_analysis_test")
        print(f"✓ Cache initialized at: {cache.cache_dir}")

        # Test cache directory creation
        if cache.cache_dir.exists():
            print("✓ Cache directory created")
        else:
            print("✗ Cache directory not created")
            return False

        return True
    except Exception as e:
        print(f"✗ Cache test failed: {e}")
        return False


def test_strategy_creation():
    """Test strategy factory"""
    print("\nTesting strategy creation...")

    try:
        from src.music_sync import create_strategy, MusicSyncSettings

        # Test each strategy type
        for mode in ["simple_tempo", "beat_sync", "dynamic_sync"]:
            settings = MusicSyncSettings(mode=mode)
            strategy = create_strategy(settings)
            print(f"✓ Created {mode} strategy: {strategy.__class__.__name__}")

        return True
    except Exception as e:
        print(f"✗ Strategy creation failed: {e}")
        return False


def test_settings():
    """Test settings configuration"""
    print("\nTesting settings...")

    try:
        from src.music_sync import MusicSyncSettings

        # Test default settings
        settings_default = MusicSyncSettings()
        print(f"✓ Default settings: mode={settings_default.mode}")

        # Test beat sync settings
        settings_beat = MusicSyncSettings(
            mode="beat_sync",
            cut_every_n_beats=4,
            prefer_strong_beats=True,
            beat_tolerance=0.1
        )
        print(f"✓ Beat sync settings: cut_every_n_beats={settings_beat.cut_every_n_beats}")

        # Test dynamic sync settings
        settings_dynamic = MusicSyncSettings(
            mode="dynamic_sync",
            low_energy_clip_duration=(4.0, 7.0),
            high_energy_clip_duration=(0.8, 2.5)
        )
        print(f"✓ Dynamic sync settings: low_energy={settings_dynamic.low_energy_clip_duration}")

        return True
    except Exception as e:
        print(f"✗ Settings test failed: {e}")
        return False


def test_integration_import():
    """Test integration module"""
    print("\nTesting integration module...")

    try:
        from src.music_sync_integration import (
            MusicSyncIntegration,
            integrate_music_sync_with_selection
        )
        print("✓ Integration module imports successful")

        integration = MusicSyncIntegration(cache_enabled=False)
        print(f"✓ MusicSyncIntegration created")

        return True
    except Exception as e:
        print(f"✗ Integration test failed: {e}")
        return False


def test_librosa_availability():
    """Test if librosa is available"""
    print("\nTesting librosa availability...")

    try:
        import librosa
        print(f"✓ librosa version: {librosa.__version__}")
        return True
    except ImportError:
        print("✗ librosa not installed")
        print("  Install with: pip install librosa")
        return False


def test_data_models():
    """Test data model creation"""
    print("\nTesting data models...")

    try:
        from src.music_sync import (
            AudioAnalysis,
            BeatPoint,
            EnergySection,
            EnergyLevel,
            CutPlan,
            CutPoint
        )

        # Test BeatPoint
        beat = BeatPoint(time=1.5, strength=0.8, is_strong_beat=True)
        print(f"✓ BeatPoint created: {beat.time}s, strength={beat.strength}")

        # Test EnergySection
        section = EnergySection(
            start_time=0.0,
            end_time=10.0,
            energy_level=EnergyLevel.HIGH,
            avg_energy=0.85
        )
        print(f"✓ EnergySection created: {section.energy_level.value}, {section.duration:.1f}s")

        # Test AudioAnalysis
        analysis = AudioAnalysis(
            file_path="test.mp3",
            duration=60.0,
            sample_rate=44100,
            tempo=120.0
        )
        print(f"✓ AudioAnalysis created: {analysis.tempo} BPM")

        # Test CutPlan
        cut_plan = CutPlan(target_duration=60.0)
        print(f"✓ CutPlan created: target={cut_plan.target_duration}s")

        return True
    except Exception as e:
        print(f"✗ Data model test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("=" * 60)
    print("Music Sync Module Test Suite")
    print("=" * 60)

    results = []

    results.append(("Imports", test_imports()))
    results.append(("Data Models", test_data_models()))
    results.append(("Settings", test_settings()))
    results.append(("Strategy Creation", test_strategy_creation()))
    results.append(("Cache", test_cache()))
    results.append(("Integration", test_integration_import()))
    results.append(("Librosa", test_librosa_availability()))

    print("\n" + "=" * 60)
    print("Test Results")
    print("=" * 60)

    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status:8} {name}")

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    print("=" * 60)
    print(f"Total: {passed_count}/{total_count} tests passed")

    if passed_count == total_count:
        print("\n✓ All tests passed! Music sync module is ready to use.")
        print("\nNext steps:")
        print("1. Make sure librosa is installed: pip install librosa")
        print("2. Add music to your project in the GUI")
        print("3. Enable music sync in Settings → Music Sync")
        print("4. Choose your sync mode and render!")
        return 0
    else:
        print("\n✗ Some tests failed. Check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
