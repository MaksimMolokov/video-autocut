"""Unit tests for QualityAnalyzer frame-level metrics."""

import sys
import unittest
import numpy as np
import cv2
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.preprocessing.quality_analyzer import QualityAnalyzer

analyzer = QualityAnalyzer()


def _solid(value, shape=(200, 200, 3)):
    return np.full(shape, value, dtype=np.uint8)


def _checkerboard(size=200, block=10):
    frame = np.zeros((size, size, 3), dtype=np.uint8)
    for i in range(0, size, block * 2):
        for j in range(0, size, block * 2):
            frame[i:i+block, j:j+block] = 255
            frame[i+block:i+block*2, j+block:j+block*2] = 255
    return frame


class TestQualityAnalyzerFrameMetrics(unittest.TestCase):

    # ------------------------------------------------------------------
    # Black / brightness
    # ------------------------------------------------------------------

    def test_black_frame_is_black(self):
        m = analyzer._analyze_frame(np.zeros((720, 1280, 3), dtype=np.uint8))
        self.assertTrue(m.is_black)
        self.assertLess(m.brightness, 0.05)

    def test_bright_frame_high_brightness(self):
        m = analyzer._analyze_frame(_solid(240))
        self.assertGreater(m.brightness, 0.85)

    def test_dark_frame_low_brightness(self):
        m = analyzer._analyze_frame(_solid(12))
        self.assertLess(m.brightness, 0.10)

    # ------------------------------------------------------------------
    # Tenengrad sharpness
    # ------------------------------------------------------------------

    def test_sharp_checkerboard(self):
        """High-frequency checkerboard → strong Sobel gradients → high sharpness."""
        m = analyzer._analyze_frame(_checkerboard())
        self.assertGreater(m.sharpness, 0.30,
                           "Checkerboard should yield high sharpness via Tenengrad")

    def test_blurry_uniform_frame(self):
        """Heavily blurred frame → gradients near zero → low sharpness."""
        frame = cv2.GaussianBlur(_solid(128), (51, 51), 20)
        m = analyzer._analyze_frame(frame)
        self.assertLess(m.sharpness, 0.05)

    def test_sharpness_higher_for_sharp_than_blurry(self):
        """Tenengrad must rank sharp above blurry."""
        sharp = _checkerboard()
        blurry = cv2.GaussianBlur(sharp.copy(), (31, 31), 10)
        ms = analyzer._analyze_frame(sharp)
        mb = analyzer._analyze_frame(blurry)
        self.assertGreater(ms.sharpness, mb.sharpness)

    # ------------------------------------------------------------------
    # Overexposure
    # ------------------------------------------------------------------

    def test_overexposed_frame(self):
        m = analyzer._analyze_frame(_solid(253))
        self.assertTrue(m.overexpose)

    def test_normal_frame_not_overexposed(self):
        m = analyzer._analyze_frame(_solid(140))
        self.assertFalse(m.overexpose)

    # ------------------------------------------------------------------
    # Metric bounds — all values in [0,1]
    # ------------------------------------------------------------------

    def test_all_metrics_in_range(self):
        frame = np.random.randint(50, 200, (480, 640, 3), dtype=np.uint8)
        m = analyzer._analyze_frame(frame)
        for attr in ('sharpness', 'brightness', 'colorfulness', 'complexity', 'edge_density'):
            v = getattr(m, attr)
            self.assertGreaterEqual(v, 0.0, f'{attr} below 0')
            self.assertLessEqual(v, 1.0,   f'{attr} above 1')

    # ------------------------------------------------------------------
    # Colorfulness — Hasler & Süsstrunk 2003
    # ------------------------------------------------------------------

    def test_gray_frame_low_colorfulness(self):
        """Pure gray has no chroma → colorfulness ≈ 0."""
        gray_bgr = _solid(128)   # R==G==B → rg=0, yb=0
        m = analyzer._analyze_frame(gray_bgr)
        self.assertLess(m.colorfulness, 0.05,
                        "Pure gray frame should have near-zero colorfulness")

    def test_saturated_red_higher_colorfulness_than_gray(self):
        """Red-only frame has rg = R-G ≠ 0 → higher colorfulness than gray."""
        red = np.zeros((200, 200, 3), dtype=np.uint8)
        red[:, :, 2] = 200   # R channel in BGR
        m_red  = analyzer._analyze_frame(red)
        m_gray = analyzer._analyze_frame(_solid(128))
        self.assertGreater(m_red.colorfulness, m_gray.colorfulness)

    def test_colorful_random_frame_above_threshold(self):
        """Random color noise has high chroma variance → colorfulness > 0.2."""
        np.random.seed(42)
        frame = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        m = analyzer._analyze_frame(frame)
        self.assertGreater(m.colorfulness, 0.20)

    # ------------------------------------------------------------------
    # Complexity — Shannon entropy
    # ------------------------------------------------------------------

    def test_uniform_frame_low_complexity(self):
        """Solid color has only one histogram bin → entropy ≈ 0."""
        m = analyzer._analyze_frame(_solid(128))
        self.assertLess(m.complexity, 0.15,
                        "Uniform frame should have near-zero complexity (entropy)")

    def test_random_frame_high_complexity(self):
        """Random noise spans all histogram bins → near-maximum entropy."""
        np.random.seed(7)
        frame = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        m = analyzer._analyze_frame(frame)
        self.assertGreater(m.complexity, 0.85,
                           "Random-noise frame should have high Shannon entropy")

    def test_complexity_higher_for_noise_than_solid(self):
        np.random.seed(0)
        noisy = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        m_noise = analyzer._analyze_frame(noisy)
        m_solid = analyzer._analyze_frame(_solid(128))
        self.assertGreater(m_noise.complexity, m_solid.complexity)

    # ------------------------------------------------------------------
    # Edge density
    # ------------------------------------------------------------------

    def test_edge_density_high_for_grid(self):
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        for i in range(0, 200, 5):
            frame[i, :] = 255
            frame[:, i] = 255
        m = analyzer._analyze_frame(frame)
        self.assertGreater(m.edge_density, 0.01)

    def test_edge_density_low_for_solid(self):
        m = analyzer._analyze_frame(_solid(100))
        self.assertLess(m.edge_density, 0.02)


class TestOpticalFlow(unittest.TestCase):
    """_compute_optical_flow now returns (stability, motion, coherence, dx, dy, instability)."""

    def _flow(self, f1, f2):
        return analyzer._compute_optical_flow(f1, f2)

    def test_static_frames_high_stability(self):
        frame = _solid(128)
        frame[80:120, 80:120] = 200
        stab, motion, *_ = self._flow(frame, frame)
        self.assertGreater(stab, 0.80)
        self.assertLess(motion, 0.10)

    def test_metrics_in_valid_range(self):
        a = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        b = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
        # Returns (stability, motion, coherence, dx, dy, instability, mag_map)
        stab, motion, coherence, dx, dy, instability, mag_map = self._flow(a, b)
        self.assertGreaterEqual(stab, 0.0)
        self.assertLessEqual(stab, 1.0)
        self.assertGreaterEqual(motion, 0.0)
        self.assertGreaterEqual(coherence, 0.0)
        self.assertLessEqual(coherence, 1.0)

    def test_coherence_near_one_for_static(self):
        """Identical frames → zero-displacement vectors → perfectly coherent."""
        frame = _checkerboard()
        _, _, coherence, dx, dy, _, _ = self._flow(frame, frame)
        self.assertGreater(coherence, 0.80,
                           "Static frame pair should have near-1 angular coherence")


class TestCameraMotionClassification(unittest.TestCase):
    """_classify_camera_motion(mean_dx, mean_dy, coherence, instability) → str."""

    def _cls(self, dx, dy, coherence=0.85, instability=2.0):
        return analyzer._classify_camera_motion(dx, dy, coherence, instability)

    def test_static(self):
        result = analyzer._classify_camera_motion(0.1, 0.05, 0.9, 0.3)
        self.assertEqual(result, 'static')

    def test_shake_low_coherence(self):
        result = analyzer._classify_camera_motion(3.0, 2.0, 0.20, 5.0)
        self.assertEqual(result, 'shake')

    def test_pan_right(self):
        result = self._cls(dx=4.0, dy=0.2)
        self.assertEqual(result, 'pan_right')

    def test_pan_left(self):
        result = self._cls(dx=-4.0, dy=0.2)
        self.assertEqual(result, 'pan_left')

    def test_tilt_up(self):
        """Positive dy = content moving down = camera tilts up."""
        result = self._cls(dx=0.1, dy=4.0)
        self.assertEqual(result, 'tilt_up')

    def test_tilt_down(self):
        result = self._cls(dx=0.1, dy=-4.0)
        self.assertEqual(result, 'tilt_down')

    def test_all_valid_types(self):
        valid = {'static', 'pan_left', 'pan_right', 'tilt_up', 'tilt_down',
                 'zoom_in', 'zoom_out', 'shake'}
        for _ in range(10):
            np.random.seed(_)
            dx = np.random.uniform(-5, 5)
            dy = np.random.uniform(-5, 5)
            coh = np.random.uniform(0, 1)
            inst = np.random.uniform(0, 6)
            result = analyzer._classify_camera_motion(dx, dy, coh, inst)
            self.assertIn(result, valid, f"Unexpected type '{result}'")


class TestTechMetricsNewFields(unittest.TestCase):
    """TechMetrics must carry colorfulness, complexity, camera_motion_type."""

    def test_new_fields_exist_in_techmetrics(self):
        from src.preprocessing.quality_analyzer import TechMetrics
        m = TechMetrics()
        self.assertTrue(hasattr(m, 'colorfulness'))
        self.assertTrue(hasattr(m, 'complexity'))
        self.assertTrue(hasattr(m, 'camera_motion_type'))

    def test_new_fields_in_range(self):
        from src.preprocessing.quality_analyzer import TechMetrics
        m = TechMetrics(colorfulness=0.5, complexity=0.7)
        self.assertGreaterEqual(m.colorfulness, 0.0)
        self.assertLessEqual(m.colorfulness, 1.0)
        self.assertGreaterEqual(m.complexity, 0.0)
        self.assertLessEqual(m.complexity, 1.0)


if __name__ == '__main__':
    unittest.main()
