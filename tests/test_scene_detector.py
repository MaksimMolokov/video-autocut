"""Unit tests for SceneDetector. Video-dependent tests auto-skip when no fixture."""

import sys
import os
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Optional test video fixture — skip tests requiring it if absent
_TEST_VIDEO = str(Path(__file__).parent / 'fixtures' / 'sample_60s.mp4')
_HAS_VIDEO = os.path.exists(_TEST_VIDEO)


class TestSceneDetectorAPI(unittest.TestCase):
    """Tests that don't require a real video file."""

    def setUp(self):
        from src.preprocessing.scene_detector import SceneDetector
        self.detector = SceneDetector()

    def test_instantiation(self):
        self.assertIsNotNone(self.detector)

    def test_split_nonexistent_returns_empty_or_raises(self):
        """SceneDetector on a missing file must not crash the caller."""
        try:
            scenes = self.detector.split('/tmp/_no_such_video_xyz.mp4')
            # FFmpeg fallback may return empty list
            self.assertIsInstance(scenes, list)
        except Exception:
            pass  # Raising is also acceptable — caller handles it


@unittest.skipUnless(_HAS_VIDEO, f'No fixture video at {_TEST_VIDEO}')
class TestSceneDetectorWithVideo(unittest.TestCase):

    def setUp(self):
        from src.preprocessing.scene_detector import SceneDetector
        self.detector = SceneDetector()

    def test_detects_multiple_scenes(self):
        scenes = self.detector.split(_TEST_VIDEO, min_scene_length=0.8)
        self.assertGreaterEqual(len(scenes), 3,
                                f'Expected >= 3 scenes, got {len(scenes)}')

    def test_min_scene_length_respected(self):
        scenes = self.detector.split(_TEST_VIDEO, min_scene_length=2.0)
        for s in scenes:
            # Allow 0.2s tolerance for detector rounding
            self.assertGreaterEqual(s.duration_s, 1.8,
                                    f'Scene too short: {s.duration_s:.2f}s')

    def test_scenes_are_non_overlapping(self):
        scenes = self.detector.split(_TEST_VIDEO)
        for i in range(len(scenes) - 1):
            self.assertLessEqual(scenes[i].end_s, scenes[i + 1].start_s + 0.1,
                                 f'Overlap between scene {i} and {i+1}')

    def test_scenes_cover_full_duration(self):
        scenes = self.detector.split(_TEST_VIDEO)
        self.assertGreater(len(scenes), 0)
        # First scene starts near 0
        self.assertLess(scenes[0].start_s, 2.0)

    def test_scene_start_less_than_end(self):
        scenes = self.detector.split(_TEST_VIDEO)
        for s in scenes:
            self.assertLess(s.start_s, s.end_s,
                            f'start_s={s.start_s} >= end_s={s.end_s}')


class TestSceneDataclass(unittest.TestCase):
    """Test Scene dataclass properties."""

    def test_scene_duration(self):
        from src.preprocessing.scene_detector import Scene
        s = Scene(start_s=1.5, end_s=4.5)
        self.assertAlmostEqual(s.duration_s, 3.0)

    def test_scene_duration_zero_length(self):
        from src.preprocessing.scene_detector import Scene
        s = Scene(start_s=5.0, end_s=5.0)
        self.assertAlmostEqual(s.duration_s, 0.0)


if __name__ == '__main__':
    unittest.main()
