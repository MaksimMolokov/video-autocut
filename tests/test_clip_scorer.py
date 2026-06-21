"""Unit tests for ClipScorer: quality, style scores, CLIP tag influence."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.preprocessing.quality_analyzer import TechMetrics
from src.preprocessing.clip_scorer import ClipScorer, ContentMetrics

scorer = ClipScorer()


def make_metrics(**kwargs) -> TechMetrics:
    defaults = dict(
        sharpness=0.70, brightness=0.50, contrast=0.50,
        stability=0.80, motion=0.20, action=0.20, calm=0.70,
        is_black=False, is_corrupt=False, overexpose=False,
        is_empty=False, is_rejected=False,
    )
    defaults.update(kwargs)
    return TechMetrics(**defaults)


class TestQualityScore(unittest.TestCase):

    def test_good_clip_high_quality(self):
        m = make_metrics(sharpness=0.9, brightness=0.55, stability=0.9, motion=0.15)
        s = scorer.score(m)
        self.assertGreater(s.quality_score, 0.70)

    def test_terrible_clip_low_quality(self):
        # All bad: blurry, dark, shaky, slow — scorer gives low result
        m = make_metrics(
            sharpness=0.01, brightness=0.02, stability=0.05,
            motion=0.01, is_black=True,
        )
        s = scorer.score(m)
        self.assertLess(s.quality_score, 0.60)

    def test_overexposed_clip_penalised(self):
        normal = make_metrics(overexpose=False)
        over = make_metrics(overexpose=True)
        self.assertGreater(scorer.score(normal).quality_score,
                           scorer.score(over).quality_score)

    def test_quality_score_bounds(self):
        for _ in range(10):
            import random
            m = make_metrics(
                sharpness=random.random(), brightness=random.random(),
                stability=random.random(), motion=random.random(),
            )
            s = scorer.score(m)
            self.assertGreaterEqual(s.quality_score, 0.0)
            self.assertLessEqual(s.quality_score, 1.0)


class TestStyleScores(unittest.TestCase):

    def test_stable_sharp_high_cinematic(self):
        m = make_metrics(stability=0.95, sharpness=0.90, motion=0.05)
        s = scorer.score(m)
        self.assertGreater(s.cinematic_score, 0.70)

    def test_fast_motion_high_action(self):
        m = make_metrics(motion=0.85, action=0.80, stability=0.25)
        s = scorer.score(m)
        self.assertGreater(s.action_score, s.cinematic_score)

    def test_cinematic_vs_action_distinct(self):
        stable = make_metrics(stability=0.9, motion=0.1, action=0.1)
        dynamic = make_metrics(stability=0.3, motion=0.8, action=0.7)
        self.assertGreater(scorer.score(stable).cinematic_score,
                           scorer.score(dynamic).cinematic_score)
        self.assertGreater(scorer.score(dynamic).action_score,
                           scorer.score(stable).action_score)

    def test_all_style_scores_in_range(self):
        m = make_metrics()
        s = scorer.score(m)
        for val in [s.quality_score, s.cinematic_score, s.action_score,
                    s.social_score, s.premium_score, s.travel_score]:
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 1.0)


class TestContentMetricsInfluence(unittest.TestCase):

    def test_face_boosts_social_score(self):
        m = make_metrics()
        c_no_face = ContentMetrics(has_face=False)
        c_face = ContentMetrics(has_face=True)
        self.assertGreater(scorer.score(m, c_face).social_score,
                           scorer.score(m, c_no_face).social_score)

    def test_subject_boosts_quality(self):
        m = make_metrics()
        c_no = ContentMetrics(has_subject=False)
        c_yes = ContentMetrics(has_subject=True)
        self.assertGreater(scorer.score(m, c_yes).quality_score,
                           scorer.score(m, c_no).quality_score)


class TestClipTagInfluence(unittest.TestCase):

    def test_nature_tag_boosts_travel(self):
        m = make_metrics()
        base = scorer.score(m).travel_score
        with_tag = scorer.score(m, scene_tag='nature').travel_score
        self.assertGreater(with_tag, base)

    def test_interior_tag_reduces_travel(self):
        m = make_metrics()
        base = scorer.score(m).travel_score
        with_tag = scorer.score(m, scene_tag='interior').travel_score
        self.assertLess(with_tag, base)

    def test_travel_tags_ocean_mountains(self):
        m = make_metrics()
        base = scorer.score(m).travel_score
        for tag in ('ocean', 'mountains'):
            boosted = scorer.score(m, scene_tag=tag).travel_score
            self.assertGreater(boosted, base,
                               msg=f'tag={tag} should boost travel_score')

    def test_clip_tag_does_not_affect_other_scores(self):
        m = make_metrics()
        s_base = scorer.score(m)
        s_tag = scorer.score(m, scene_tag='nature')
        self.assertEqual(s_base.cinematic_score, s_tag.cinematic_score)
        self.assertEqual(s_base.action_score, s_tag.action_score)
        self.assertEqual(s_base.quality_score, s_tag.quality_score)


if __name__ == '__main__':
    unittest.main()
