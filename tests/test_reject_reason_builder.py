"""Unit tests for reject_reason_builder (VI2-013)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.reject_reason_builder import build_reject_reasons, primary_reject_reason


def _frag(**kw) -> dict:
    base = dict(
        id=1, start_s=0.0, end_s=5.0,
        sharpness=0.7, camera_shake=0.0, brightness=0.5,
        is_blurry=False, is_duplicate=False,
        camera_motion_type="static", scene_tags=[],
        quality_score=0.6,
    )
    base.update(kw)
    return base


def _preset(**kw) -> dict:
    clip = kw.pop("clip", {})
    sel  = kw.pop("sel", {})
    return {"clip_selection": clip, "segment_selection": sel}


class TestBasicQualityRejects(unittest.TestCase):

    def test_blurry_frame_rejected(self):
        reasons = build_reject_reasons(_frag(is_blurry=True))
        self.assertTrue(any("Размытый" in r for r in reasons))

    def test_very_low_sharpness_rejected(self):
        reasons = build_reject_reasons(_frag(sharpness=0.05))
        self.assertTrue(any("Размытый" in r for r in reasons))

    def test_too_dark_rejected(self):
        reasons = build_reject_reasons(_frag(brightness=0.02))
        self.assertTrue(any("тёмный" in r for r in reasons))

    def test_overexposed_rejected(self):
        reasons = build_reject_reasons(_frag(brightness=0.97))
        self.assertTrue(any("Засветка" in r for r in reasons))

    def test_strong_shake_rejected(self):
        reasons = build_reject_reasons(_frag(camera_shake=0.90))
        self.assertTrue(any("тряска" in r for r in reasons))

    def test_duplicate_rejected(self):
        reasons = build_reject_reasons(_frag(is_duplicate=True))
        self.assertTrue(any("Дубль" in r for r in reasons))

    def test_good_fragment_no_reasons(self):
        reasons = build_reject_reasons(_frag())
        self.assertEqual(reasons, [])


class TestPresetQualityThreshold(unittest.TestCase):

    def test_quality_below_preset_min(self):
        ps = _preset(sel={"min_scores": {"quality_score": 0.70}})
        reasons = build_reject_reasons(_frag(quality_score=0.50), ps)
        self.assertTrue(any("качество" in r.lower() for r in reasons))

    def test_quality_above_preset_min_ok(self):
        ps = _preset(sel={"min_scores": {"quality_score": 0.40}})
        reasons = build_reject_reasons(_frag(quality_score=0.65), ps)
        self.assertFalse(any("качество" in r.lower() for r in reasons))

    def test_brightness_below_preset_min(self):
        ps = _preset(sel={"min_scores": {"brightness": 0.40}})
        reasons = build_reject_reasons(_frag(brightness=0.25), ps)
        self.assertTrue(any("Яркость" in r for r in reasons))

    def test_stability_below_preset_min(self):
        ps = _preset(sel={"min_scores": {"stability": 0.80}})
        reasons = build_reject_reasons(_frag(camera_shake=0.50), ps)
        self.assertTrue(any("Нестабильный" in r for r in reasons))


class TestDurationRejects(unittest.TestCase):

    def test_too_short_clip(self):
        ps = _preset(clip={"segment_min_duration": 2.0})
        reasons = build_reject_reasons(_frag(start_s=0.0, end_s=0.8), ps)
        self.assertTrue(any("короткий" in r for r in reasons))

    def test_too_long_clip(self):
        ps = _preset(clip={"segment_max_duration": 5.0})
        reasons = build_reject_reasons(_frag(start_s=0.0, end_s=12.0), ps)
        self.assertTrue(any("длинный" in r for r in reasons))

    def test_duration_in_range_ok(self):
        ps = _preset(clip={"segment_min_duration": 1.0, "segment_max_duration": 10.0})
        reasons = build_reject_reasons(_frag(start_s=0.0, end_s=5.0), ps)
        self.assertFalse(any("короткий" in r or "длинный" in r for r in reasons))


class TestMotionRejects(unittest.TestCase):

    def test_rejected_motion_type_caught(self):
        ps = _preset(sel={"rejected_camera_motion": ["shake", "handheld"]})
        reasons = build_reject_reasons(_frag(camera_motion_type="shake"), ps)
        self.assertTrue(any("запрещён" in r for r in reasons))

    def test_preferred_motion_type_not_rejected(self):
        ps = _preset(sel={
            "preferred_camera_motion": ["pan_left", "dolly"],
            "rejected_camera_motion": ["shake"],
        })
        reasons = build_reject_reasons(_frag(camera_motion_type="dolly"), ps)
        self.assertFalse(any("запрещён" in r for r in reasons))


class TestPoseAndEyeRejects(unittest.TestCase):

    def test_bad_crop_rejected(self):
        reasons = build_reject_reasons(_frag(bad_crop=True))
        self.assertTrue(any("кроп" in r.lower() for r in reasons))

    def test_low_pose_quality_rejected(self):
        reasons = build_reject_reasons(_frag(pose_quality_score=0.10))
        self.assertTrue(any("поза" in r.lower() or "ракурс" in r.lower() for r in reasons))

    def test_eyes_closed_with_preset_threshold(self):
        ps = _preset(sel={"min_scores": {"eyes_open_score": 0.60}})
        reasons = build_reject_reasons(_frag(eyes_open_score=0.30), ps)
        self.assertTrue(any("глаза" in r.lower() for r in reasons))

    def test_eyes_ok_without_threshold(self):
        reasons = build_reject_reasons(_frag(eyes_open_score=0.20))
        self.assertFalse(any("глаза" in r.lower() for r in reasons))


class TestPrimaryRejectReason(unittest.TestCase):

    def test_returns_none_for_good_fragment(self):
        self.assertIsNone(primary_reject_reason(_frag()))

    def test_returns_first_reason(self):
        r = primary_reject_reason(_frag(is_blurry=True))
        self.assertIsNotNone(r)
        self.assertIsInstance(r, str)

    def test_multiple_problems_returns_first(self):
        r = primary_reject_reason(_frag(is_blurry=True, is_duplicate=True))
        self.assertIsNotNone(r)


if __name__ == "__main__":
    unittest.main()
