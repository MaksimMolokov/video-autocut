"""Unit tests for EyeStateAnalyzer (VI2-007)."""
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


def _eye_result(**kw):
    from analysis.content.eye_state_analyzer import EyeStateResult
    defaults = dict(eyes_open_score=0.5, eyes_detected=False, eye_count=0, face_count=0)
    defaults.update(kw)
    return EyeStateResult(**defaults)


class TestEyeStateAnalyzerImport(unittest.TestCase):

    def test_import_ok(self):
        from analysis.content.eye_state_analyzer import EyeStateAnalyzer, EyeStateResult
        self.assertTrue(callable(EyeStateAnalyzer))

    def test_result_fields(self):
        r = _eye_result()
        for attr in ["eyes_open_score", "eyes_detected", "eye_count", "face_count"]:
            self.assertTrue(hasattr(r, attr), f"Missing field: {attr}")

    def test_score_defaults_in_range(self):
        r = _eye_result()
        self.assertGreaterEqual(r.eyes_open_score, 0.0)
        self.assertLessEqual(r.eyes_open_score, 1.0)

    def test_all_possible_values_in_range(self):
        r = _eye_result(eyes_open_score=0.85, eyes_detected=True, eye_count=2, face_count=1)
        self.assertGreaterEqual(r.eyes_open_score, 0.0)
        self.assertLessEqual(r.eyes_open_score, 1.0)


class TestEyeStateAnalyzerNoFace(unittest.TestCase):

    def test_empty_frame_returns_result(self):
        from analysis.content.eye_state_analyzer import EyeStateAnalyzer, EyeStateResult
        analyzer = EyeStateAnalyzer()
        cap = _make_cap(_solid_frame())
        with patch("cv2.VideoCapture", return_value=cap):
            result = analyzer.analyze("fake.mp4", 0.0, 2.0)
        self.assertIsInstance(result, EyeStateResult)

    def test_no_face_neutral_score(self):
        from analysis.content.eye_state_analyzer import EyeStateAnalyzer
        analyzer = EyeStateAnalyzer()
        cap = _make_cap(_solid_frame())
        with patch("cv2.VideoCapture", return_value=cap):
            result = analyzer.analyze("fake.mp4", 0.0, 2.0)
        # No face detected — neutral score (benefit of the doubt)
        self.assertGreaterEqual(result.eyes_open_score, 0.0)
        self.assertLessEqual(result.eyes_open_score, 1.0)
        self.assertEqual(result.face_count, 0)

    def test_eye_count_non_negative(self):
        from analysis.content.eye_state_analyzer import EyeStateAnalyzer
        analyzer = EyeStateAnalyzer()
        cap = _make_cap(_solid_frame())
        with patch("cv2.VideoCapture", return_value=cap):
            result = analyzer.analyze("fake.mp4", 0.0, 2.0)
        self.assertGreaterEqual(result.eye_count, 0)


class TestEyeStateAnalyzerWithMockedCascade(unittest.TestCase):

    def _mock_analyzers_return(self, face_cc, eye_cc):
        """Patch both cascade getters on an EyeStateAnalyzer instance."""
        from analysis.content.eye_state_analyzer import EyeStateAnalyzer
        analyzer = EyeStateAnalyzer()
        analyzer._face_cascade = face_cc
        analyzer._eye_cascade  = eye_cc
        return analyzer

    def test_two_eyes_found_high_score(self):
        # Mock: detectMultiScale returns a face, then 2 eyes
        face_cc = MagicMock()
        eye_cc  = MagicMock()

        face_cc.detectMultiScale.return_value = np.array([[10, 10, 40, 40]])
        eye_cc.detectMultiScale.return_value  = np.array([[5, 5, 10, 10],
                                                           [25, 5, 10, 10]])

        analyzer = self._mock_analyzers_return(face_cc, eye_cc)
        cap = _make_cap(_solid_frame())
        with patch("cv2.VideoCapture", return_value=cap):
            result = analyzer.analyze("fake.mp4", 0.0, 2.0)
        self.assertGreater(result.eyes_open_score, 0.5)
        self.assertGreater(result.face_count, 0)

    def test_zero_eyes_found_low_score(self):
        face_cc = MagicMock()
        eye_cc  = MagicMock()

        face_cc.detectMultiScale.return_value = np.array([[10, 10, 40, 40]])
        eye_cc.detectMultiScale.return_value  = np.array([]).reshape(0, 4)

        analyzer = self._mock_analyzers_return(face_cc, eye_cc)
        cap = _make_cap(_solid_frame())
        with patch("cv2.VideoCapture", return_value=cap):
            result = analyzer.analyze("fake.mp4", 0.0, 2.0)
        # 0 eyes for 1 face → closed eyes
        self.assertLessEqual(result.eyes_open_score, 0.5)


if __name__ == "__main__":
    unittest.main()
