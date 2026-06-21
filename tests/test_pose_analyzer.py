"""Unit tests for PoseAnalyzer (VI2-007)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))


def _solid_frame(h=120, w=160) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _make_cap(frame: np.ndarray):
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.get.return_value = 25.0
    cap.read.return_value = (True, frame)
    cap.release = MagicMock()
    return cap


def _full_pose_result(**kw):
    from analysis.content.pose_analyzer import PoseResult
    defaults = dict(
        pose_quality_score=0.7, body_crop_quality_score=0.6,
        main_person_area_ratio=0.35, head_visible=True,
        full_body_visible=True, bad_crop=False, reject_reasons=[],
    )
    defaults.update(kw)
    return PoseResult(**defaults)


class TestPoseAnalyzerImport(unittest.TestCase):

    def test_import_ok(self):
        from analysis.content.pose_analyzer import PoseAnalyzer, PoseResult
        self.assertTrue(callable(PoseAnalyzer))

    def test_pose_result_fields(self):
        r = _full_pose_result()
        for attr in ["pose_quality_score", "body_crop_quality_score",
                     "main_person_area_ratio", "head_visible",
                     "full_body_visible", "bad_crop", "reject_reasons"]:
            self.assertTrue(hasattr(r, attr), f"Missing field: {attr}")

    def test_scores_in_range(self):
        r = _full_pose_result()
        self.assertGreaterEqual(r.pose_quality_score, 0.0)
        self.assertLessEqual(r.pose_quality_score, 1.0)
        self.assertGreaterEqual(r.body_crop_quality_score, 0.0)
        self.assertLessEqual(r.body_crop_quality_score, 1.0)

    def test_reject_reasons_default_empty(self):
        r = _full_pose_result()
        self.assertIsInstance(r.reject_reasons, list)


class TestPoseAnalyzerNoPersonFrame(unittest.TestCase):

    def test_empty_frame_no_crash(self):
        from analysis.content.pose_analyzer import PoseAnalyzer, PoseResult
        analyzer = PoseAnalyzer()
        cap = _make_cap(_solid_frame())
        with patch("cv2.VideoCapture", return_value=cap):
            result = analyzer.analyze("fake.mp4", 0.0, 2.0)
        self.assertIsInstance(result, PoseResult)

    def test_returns_pose_result_type(self):
        from analysis.content.pose_analyzer import PoseAnalyzer, PoseResult
        analyzer = PoseAnalyzer()
        cap = _make_cap(_solid_frame())
        with patch("cv2.VideoCapture", return_value=cap):
            result = analyzer.analyze("fake.mp4", 0.0, 2.0)
        self.assertIsInstance(result, PoseResult)

    def test_area_ratio_in_range(self):
        from analysis.content.pose_analyzer import PoseAnalyzer
        analyzer = PoseAnalyzer()
        cap = _make_cap(_solid_frame())
        with patch("cv2.VideoCapture", return_value=cap):
            result = analyzer.analyze("fake.mp4", 0.0, 2.0)
        self.assertGreaterEqual(result.main_person_area_ratio, 0.0)
        self.assertLessEqual(result.main_person_area_ratio, 1.0)

    def test_scores_in_valid_range(self):
        from analysis.content.pose_analyzer import PoseAnalyzer
        analyzer = PoseAnalyzer()
        cap = _make_cap(_solid_frame())
        with patch("cv2.VideoCapture", return_value=cap):
            result = analyzer.analyze("fake.mp4", 0.0, 2.0)
        self.assertGreaterEqual(result.pose_quality_score, 0.0)
        self.assertLessEqual(result.pose_quality_score, 1.0)
        self.assertGreaterEqual(result.body_crop_quality_score, 0.0)
        self.assertLessEqual(result.body_crop_quality_score, 1.0)


class TestDefaultResult(unittest.TestCase):

    def test_default_result_sensible(self):
        from analysis.content.pose_analyzer import _default_result
        r = _default_result()
        self.assertAlmostEqual(r.pose_quality_score, 0.5)
        self.assertFalse(r.bad_crop)
        self.assertEqual(r.reject_reasons, [])


if __name__ == "__main__":
    unittest.main()
