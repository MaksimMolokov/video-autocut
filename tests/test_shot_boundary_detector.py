"""Unit tests for ShotBoundaryDetector (VI2-010)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_frame(brightness: float = 0.5) -> np.ndarray:
    val = int(brightness * 255)
    return np.full((64, 64, 3), val, dtype=np.uint8)


def _make_mock_cap(frames, fps=25.0):
    """Return a mock cv2.VideoCapture that yields the given list of frames."""
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.get.side_effect = lambda prop: {
        cv2.CAP_PROP_FPS: fps,
        cv2.CAP_PROP_FRAME_COUNT: float(len(frames)),
    }.get(prop, 0.0)
    frame_iter = iter(frames)

    def read_side_effect():
        try:
            return True, next(frame_iter)
        except StopIteration:
            return False, None

    cap.read.side_effect = read_side_effect
    cap.release = MagicMock()
    return cap


class TestShotBoundaryDetectorImport(unittest.TestCase):

    def test_import_ok(self):
        from analysis.video.shot_boundary_detector import ShotBoundaryDetector, ShotBoundary
        self.assertTrue(callable(ShotBoundaryDetector))

    def test_shot_boundary_fields(self):
        from analysis.video.shot_boundary_detector import ShotBoundary
        sb = ShotBoundary(
            start_sec=0.0, end_sec=2.0, duration_sec=2.0,
            boundary_type="cut", boundary_confidence=0.9, scene_change_score=0.85,
        )
        self.assertEqual(sb.boundary_type, "cut")
        self.assertAlmostEqual(sb.duration_sec, 2.0)


class TestShotBoundaryDetectorLogic(unittest.TestCase):

    def setUp(self):
        from analysis.video.shot_boundary_detector import ShotBoundaryDetector
        self.det = ShotBoundaryDetector(mode="content_threshold", threshold=0.3)

    def test_detect_returns_list(self):
        # Build frames: 10 similar + 1 very different + 10 similar
        light = [_make_frame(0.5)] * 10
        dark  = [_make_frame(0.02)] * 10
        all_frames = light + dark

        cap = _make_mock_cap(all_frames, fps=10.0)
        with patch("cv2.VideoCapture", return_value=cap):
            result = self.det.detect("fake.mp4")
        self.assertIsInstance(result, list)

    def test_no_boundaries_on_uniform_video(self):
        frames = [_make_frame(0.5)] * 30
        cap = _make_mock_cap(frames, fps=10.0)
        with patch("cv2.VideoCapture", return_value=cap):
            result = self.det.detect("fake.mp4")
        # Uniform video should produce few or no boundaries
        self.assertLessEqual(len(result), 2)

    def test_clear_cut_detected(self):
        # Abrupt change from white to black frames
        white = [_make_frame(1.0)] * 15
        black = [_make_frame(0.0)] * 15
        frames = white + black
        cap = _make_mock_cap(frames, fps=15.0)
        with patch("cv2.VideoCapture", return_value=cap):
            result = self.det.detect("fake.mp4")
        # Should detect at least one boundary
        self.assertGreaterEqual(len(result), 1)

    def test_boundary_fields_populated(self):
        white = [_make_frame(1.0)] * 10
        black = [_make_frame(0.0)] * 10
        cap = _make_mock_cap(white + black, fps=10.0)
        with patch("cv2.VideoCapture", return_value=cap):
            result = self.det.detect("fake.mp4")
        if result:
            b = result[0]
            self.assertGreaterEqual(b.start_sec, 0.0)
            self.assertGreater(b.end_sec, b.start_sec)
            self.assertIn(b.boundary_type, ("cut", "fade", "dissolve", "unknown"))
            self.assertGreaterEqual(b.boundary_confidence, 0.0)
            self.assertLessEqual(b.boundary_confidence, 1.0)


class TestShotBoundaryModes(unittest.TestCase):

    def test_adaptive_threshold_mode(self):
        from analysis.video.shot_boundary_detector import ShotBoundaryDetector
        det = ShotBoundaryDetector(mode="adaptive_threshold")
        frames = [_make_frame(0.5)] * 20
        cap = _make_mock_cap(frames, fps=10.0)
        with patch("cv2.VideoCapture", return_value=cap):
            result = det.detect("fake.mp4")
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()
