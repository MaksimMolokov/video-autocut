"""Unit tests for ScoringService — multi-level fragment scoring (VI2-012, VI2-016)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.scoring_service import ScoringService, FragmentScore, _clamp, _score_role


def _frag(**kw) -> dict:
    base = dict(
        id=1, start_s=0.0, end_s=5.0,
        sharpness=0.70, camera_shake=0.10, brightness=0.50,
        quality_score=0.60, aesthetic_score=0.55, composition_score=0.55,
        vi_score=0.60, camera_motion_type="static",
        scene_tags=[], suggested_role="body",
        is_blurry=False, is_duplicate=False,
    )
    base.update(kw)
    return base


def _preset(**kw) -> dict:
    return {
        "clip_selection":      kw.get("clip", {}),
        "segment_selection":   kw.get("sel", {}),
        "scoring_weights":     kw.get("weights", {}),
    }


svc = ScoringService()


class TestFragmentScoreDataclass(unittest.TestCase):

    def test_defaults_in_range(self):
        s = FragmentScore()
        for field_name in ["technical_score", "aesthetic_score", "vi_score",
                           "style_fit_score", "semantic_score", "global_quality_score"]:
            val = getattr(s, field_name)
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)

    def test_reject_reasons_default_empty(self):
        s = FragmentScore()
        self.assertEqual(s.reject_reasons, [])


class TestScoreFragment(unittest.TestCase):

    def test_returns_fragment_score(self):
        result = svc.score_fragment(_frag())
        self.assertIsInstance(result, FragmentScore)

    def test_global_score_in_range(self):
        result = svc.score_fragment(_frag())
        self.assertGreaterEqual(result.global_quality_score, 0.0)
        self.assertLessEqual(result.global_quality_score, 1.0)

    def test_good_fragment_higher_global_than_bad(self):
        good = svc.score_fragment(_frag(sharpness=0.95, camera_shake=0.0, quality_score=0.90))
        bad  = svc.score_fragment(_frag(sharpness=0.05, camera_shake=0.90, quality_score=0.10,
                                        is_blurry=True))
        self.assertGreater(good.global_quality_score, bad.global_quality_score)

    def test_technical_score_high_for_sharp_stable(self):
        result = svc.score_fragment(_frag(sharpness=0.95, camera_shake=0.0, brightness=0.55))
        self.assertGreater(result.technical_score, 0.75)

    def test_reject_score_zero_for_good_fragment(self):
        result = svc.score_fragment(_frag())
        self.assertEqual(result.reject_score, 0.0)

    def test_reject_score_nonzero_for_blurry(self):
        result = svc.score_fragment(_frag(is_blurry=True))
        self.assertGreater(result.reject_score, 0.0)

    def test_vi_score_used_in_global(self):
        high_vi = svc.score_fragment(_frag(vi_score=0.95, quality_score=0.95))
        low_vi  = svc.score_fragment(_frag(vi_score=0.10, quality_score=0.10))
        self.assertGreater(high_vi.global_quality_score, low_vi.global_quality_score)

    def test_explanation_not_empty(self):
        result = svc.score_fragment(_frag())
        self.assertGreater(len(result.explanation), 5)


class TestMotionFit(unittest.TestCase):

    def test_preferred_motion_high_fit(self):
        ps = _preset(sel={"preferred_camera_motion": ["dolly", "pan_left"]})
        result = svc.score_fragment(_frag(camera_motion_type="dolly"), ps)
        self.assertGreater(result.motion_fit, 0.70)

    def test_rejected_motion_low_fit(self):
        ps = _preset(sel={"rejected_camera_motion": ["shake"]})
        result = svc.score_fragment(_frag(camera_motion_type="shake"), ps)
        self.assertLess(result.motion_fit, 0.20)

    def test_neutral_motion_mid_fit(self):
        ps = _preset(sel={
            "preferred_camera_motion": ["dolly"],
            "rejected_camera_motion": ["shake"],
        })
        result = svc.score_fragment(_frag(camera_motion_type="static"), ps)
        self.assertAlmostEqual(result.motion_fit, 0.50)


class TestSemanticScore(unittest.TestCase):

    def test_matching_tags_boost_semantic(self):
        ps = _preset(sel={"preferred_scene_categories": ["nature", "aerial", "landscape"]})
        result = svc.score_fragment(_frag(scene_tags=["nature", "aerial"]), ps)
        self.assertGreater(result.semantic_score, 0.50)

    def test_no_overlap_neutral_semantic(self):
        ps = _preset(sel={"preferred_scene_categories": ["sport", "action"]})
        result = svc.score_fragment(_frag(scene_tags=["nature"]), ps)
        self.assertAlmostEqual(result.semantic_score, 0.50)

    def test_empty_preferred_cats_neutral(self):
        result = svc.score_fragment(_frag(scene_tags=["nature"]))
        self.assertAlmostEqual(result.semantic_score, 0.50)


class TestStyleFit(unittest.TestCase):

    def test_stored_style_fit_used(self):
        f = _frag(style_fit_scores={"fast_reels": 0.88})
        result = svc.score_fragment(f, style_id="fast_reels")
        self.assertAlmostEqual(result.style_fit_score, 0.88, places=2)

    def test_missing_style_falls_back_to_heuristic(self):
        f = _frag(style_fit_scores={})
        result = svc.score_fragment(f, style_id="fast_reels")
        self.assertGreater(result.style_fit_score, 0.0)
        self.assertLess(result.style_fit_score, 1.0)


class TestApplyScores(unittest.TestCase):

    def test_mutates_frags_in_place(self):
        frags = [_frag(id=i) for i in range(5)]
        result = svc.apply_scores(frags)
        self.assertIs(result, frags)
        for f in frags:
            self.assertIn("quality_score", f)
            self.assertIn("vi_score", f)
            self.assertIn("style_fit_score", f)
            self.assertIn("suggested_role", f)
            self.assertIn("_score_explanation", f)

    def test_rejection_reason_written_for_bad_frag(self):
        frags = [_frag(id=0, is_blurry=True, rejection_reason=None)]
        svc.apply_scores(frags)
        self.assertIsNotNone(frags[0].get("rejection_reason"))

    def test_good_frags_sorted_higher_than_bad(self):
        frags = [
            _frag(id=0, sharpness=0.95, camera_shake=0.0, quality_score=0.90),
            _frag(id=1, sharpness=0.10, camera_shake=0.85, quality_score=0.10, is_blurry=True),
        ]
        svc.apply_scores(frags)
        self.assertGreater(frags[0]["quality_score"], frags[1]["quality_score"])


class TestHelpers(unittest.TestCase):

    def test_clamp_within_bounds(self):
        self.assertEqual(_clamp(-0.5), 0.0)
        self.assertEqual(_clamp(1.5), 1.0)
        self.assertAlmostEqual(_clamp(0.5), 0.5)

    def test_score_role_with_matching_tags(self):
        frag = _frag(scene_tags=["action", "sport"], start_s=0.0, end_s=2.0)
        rules = {"intro": {"preferred_tags": ["action", "sport"], "duration_sec": {"min": 0.5, "max": 5}}}
        score = _score_role(frag, "intro", rules)
        self.assertGreater(score, 0.50)

    def test_score_role_duration_out_of_range_penalty(self):
        frag = _frag(start_s=0.0, end_s=15.0)
        rules = {"main_part": {"duration_sec": {"min": 1, "max": 8}}}
        score = _score_role(frag, "body", rules)
        self.assertLessEqual(score, 0.50)


if __name__ == "__main__":
    unittest.main()
