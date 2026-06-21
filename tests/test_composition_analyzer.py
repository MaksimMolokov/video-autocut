"""Unit tests for CompositionAnalyzer (VI2-008)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))


def _solid_frame(h=120, w=160, color=(128, 128, 128)) -> np.ndarray:
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    frame[:] = color
    return frame


def _make_cap(frame: np.ndarray, fps: float = 25.0):
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.get.return_value = fps
    cap.read.return_value = (True, frame)
    cap.release = MagicMock()
    return cap


class TestCompositionAnalyzerImport(unittest.TestCase):

    def test_import_ok(self):
        from analysis.content.composition_analyzer import CompositionAnalyzer, CompositionResult
        self.assertTrue(callable(CompositionAnalyzer))

    def test_result_fields(self):
        from analysis.content.composition_analyzer import CompositionResult
        r = CompositionResult(0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        for attr in ["rule_of_thirds_score", "horizon_level_score", "symmetry_score",
                     "subject_position_score", "visual_depth_score",
                     "background_clutter_score", "composition_score"]:
            self.assertTrue(hasattr(r, attr), f"Missing field: {attr}")

    def test_all_scores_in_range(self):
        from analysis.content.composition_analyzer import CompositionResult
        r = CompositionResult(
            composition_score=0.55,
            rule_of_thirds_score=0.6,
            horizon_level_score=0.7,
            symmetry_score=0.5,
            subject_position_score=0.5,
            visual_depth_score=0.4,
            background_clutter_score=0.3,
        )
        for attr in ["rule_of_thirds_score", "horizon_level_score", "symmetry_score",
                     "subject_position_score", "visual_depth_score",
                     "background_clutter_score", "composition_score"]:
            val = getattr(r, attr)
            self.assertGreaterEqual(val, 0.0, f"{attr} < 0")
            self.assertLessEqual(val, 1.0, f"{attr} > 1")


class TestCompositionAnalyzerAnalyze(unittest.TestCase):

    def setUp(self):
        from analysis.content.composition_analyzer import CompositionAnalyzer
        self.analyzer = CompositionAnalyzer()

    def _run(self, frame):
        cap = _make_cap(frame)
        with patch("cv2.VideoCapture", return_value=cap):
            return self.analyzer.analyze("fake.mp4", 0.0, 2.0)

    def test_returns_composition_result(self):
        from analysis.content.composition_analyzer import CompositionResult
        result = self._run(_solid_frame())
        self.assertIsInstance(result, CompositionResult)

    def test_composition_score_in_range(self):
        result = self._run(_solid_frame())
        self.assertGreaterEqual(result.composition_score, 0.0)
        self.assertLessEqual(result.composition_score, 1.0)

    def test_bright_frame_vs_dark_frame(self):
        bright = self._run(_solid_frame(color=(220, 220, 220)))
        dark   = self._run(_solid_frame(color=(10, 10, 10)))
        # Both should return valid scores — just checking no exception
        self.assertIsNotNone(bright)
        self.assertIsNotNone(dark)

    def test_symmetry_high_for_uniform_frame(self):
        # Uniform solid color frame should have near-perfect symmetry
        result = self._run(_solid_frame(color=(100, 100, 100)))
        self.assertGreater(result.symmetry_score, 0.70)


if __name__ == "__main__":
    unittest.main()
