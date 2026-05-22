"""
Variant diversity tests — no Streamlit or FFmpeg required.

Tests cover:
- VariantProfile definitions and completeness
- compare_timelines() Jaccard similarity metric
- similarity_matrix() pairwise computation
- calculate_timeline_stats() correctness
- get_variant_ui_description() output
- apply_profile_weights() candidate re-scoring
- apply_alternative_penalty() D-variant pool
- shuffle_candidates_for_regen() determinism
- Diversity enforcement logic (threshold, regen loop)
- Profile seed uniqueness
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.variant_profiles import (
    VARIANT_PROFILES,
    VariantProfile,
    SIMILARITY_THRESHOLD,
    compare_timelines,
    similarity_matrix,
    calculate_timeline_stats,
    get_variant_ui_description,
    apply_profile_weights,
    apply_alternative_penalty,
    shuffle_candidates_for_regen,
)


# ── Mock objects ──────────────────────────────────────────────────────────────

@dataclass
class MockFeatures:
    action_score:    float = 0.5
    motion_score:    float = 0.5
    sharpness_score: float = 0.5
    brightness_score: float = 0.5


class MockSeg:
    def __init__(self, source_path='vid.mp4', start=0.0, end=3.0, _features=None):
        self.source_path = source_path
        self.start       = start
        self.end         = end
        self.duration    = end - start
        self._features   = _features or MockFeatures()


class MockCand:
    """Simulates a CandidateClip with features and final_score."""
    def __init__(self, source_path='vid.mp4', start=0.0, end=3.0,
                 motion=0.5, sharpness=0.5, final_score=0.5):
        self.source_path = source_path
        self.start       = start
        self.end         = end
        self.duration    = end - start
        self.features    = MockFeatures(
            action_score=0.5, motion_score=motion, sharpness_score=sharpness
        )
        self.final_score = final_score


def make_timeline(clips: list[tuple]) -> list:
    """Build a list of MockSeg from (path, start, end) tuples."""
    return [MockSeg(source_path=p, start=s, end=e) for p, s, e in clips]


# ── Profile definitions ───────────────────────────────────────────────────────

class TestVariantProfileDefinitions(unittest.TestCase):

    def test_all_four_profiles_defined(self):
        for letter in ('A', 'B', 'C', 'D'):
            self.assertIn(letter, VARIANT_PROFILES, f"Profile {letter} missing")

    def test_profiles_are_frozen_dataclasses(self):
        for letter, p in VARIANT_PROFILES.items():
            with self.assertRaises((AttributeError, TypeError)):
                p.seed_offset = 999  # frozen → must raise

    def test_seed_offsets_unique(self):
        offsets = [p.seed_offset for p in VARIANT_PROFILES.values()]
        self.assertEqual(len(offsets), len(set(offsets)), "seed_offsets must be unique")

    def test_seed_offsets_positive(self):
        for p in VARIANT_PROFILES.values():
            self.assertGreater(p.seed_offset, 0)

    def test_a_is_balanced_baseline(self):
        a = VARIANT_PROFILES['A']
        self.assertEqual(a.clip_duration_multiplier, 1.0)
        self.assertEqual(a.motion_weight_delta, 0.0)
        self.assertEqual(a.aesthetic_weight_delta, 0.0)
        self.assertEqual(a.scene_selection_strategy, 'balanced')
        self.assertEqual(a.diversity_penalty, 0.0)

    def test_b_is_dynamic_shorter_clips(self):
        b = VARIANT_PROFILES['B']
        self.assertLess(b.clip_duration_multiplier, 1.0)
        self.assertGreater(b.motion_weight_delta, 0.0)

    def test_c_is_cinematic_longer_clips(self):
        c = VARIANT_PROFILES['C']
        self.assertGreater(c.clip_duration_multiplier, 1.0)
        self.assertGreater(c.aesthetic_weight_delta, 0.0)

    def test_d_has_diversity_penalty(self):
        d = VARIANT_PROFILES['D']
        self.assertGreater(d.diversity_penalty, 0.0)
        self.assertEqual(d.scene_selection_strategy, 'alternative')

    def test_all_profiles_have_required_fields(self):
        required_fields = (
            'letter', 'label', 'description', 'seed_offset',
            'clip_duration_multiplier', 'motion_weight_delta',
            'aesthetic_weight_delta', 'beat_sync_strength',
            'transition_profile', 'scene_selection_strategy',
            'diversity_penalty', 'energy_label',
        )
        for letter, p in VARIANT_PROFILES.items():
            for f in required_fields:
                self.assertTrue(hasattr(p, f), f"Profile {letter} missing field '{f}'")

    def test_a_b_c_zero_diversity_penalty(self):
        for letter in ('A', 'B', 'C'):
            self.assertEqual(VARIANT_PROFILES[letter].diversity_penalty, 0.0)

    def test_similarity_threshold_value(self):
        self.assertGreater(SIMILARITY_THRESHOLD, 0.5)
        self.assertLess(SIMILARITY_THRESHOLD, 1.0)
        self.assertEqual(SIMILARITY_THRESHOLD, 0.85)


# ── compare_timelines() ───────────────────────────────────────────────────────

class TestCompareTimelines(unittest.TestCase):

    def test_identical_timelines_score_1(self):
        tl = make_timeline([('a.mp4', 0, 3), ('b.mp4', 5, 8)])
        self.assertAlmostEqual(compare_timelines(tl, tl), 1.0)

    def test_disjoint_timelines_score_0(self):
        a = make_timeline([('a.mp4', 0, 3)])
        b = make_timeline([('b.mp4', 10, 13)])
        self.assertAlmostEqual(compare_timelines(a, b), 0.0)

    def test_partial_overlap(self):
        a = make_timeline([('v.mp4', 0, 3), ('v.mp4', 5, 8)])
        b = make_timeline([('v.mp4', 0, 3), ('v.mp4', 10, 13)])
        score = compare_timelines(a, b)
        # 1 shared / 3 union = 0.333...
        self.assertAlmostEqual(score, 1 / 3, places=3)

    def test_empty_a_returns_0(self):
        b = make_timeline([('x.mp4', 0, 3)])
        self.assertEqual(compare_timelines([], b), 0.0)

    def test_empty_b_returns_0(self):
        a = make_timeline([('x.mp4', 0, 3)])
        self.assertEqual(compare_timelines(a, []), 0.0)

    def test_both_empty_returns_0(self):
        self.assertEqual(compare_timelines([], []), 0.0)

    def test_start_rounding_tolerance(self):
        """Clips differing by < 0.1s in start should be considered the same."""
        a = [MockSeg('v.mp4', start=1.00, end=4.00)]
        b = [MockSeg('v.mp4', start=1.04, end=4.04)]
        # round(1.00, 1) == round(1.04, 1) == 1.0 → same key
        self.assertAlmostEqual(compare_timelines(a, b), 1.0)

    def test_score_range_0_to_1(self):
        a = make_timeline([('a.mp4', 0, 3), ('b.mp4', 5, 8), ('c.mp4', 10, 13)])
        b = make_timeline([('a.mp4', 0, 3), ('x.mp4', 20, 23)])
        score = compare_timelines(a, b)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


# ── similarity_matrix() ───────────────────────────────────────────────────────

class TestSimilarityMatrix(unittest.TestCase):

    def test_keys_are_pairs(self):
        variants = {
            'A': make_timeline([('a.mp4', 0, 3)]),
            'B': make_timeline([('b.mp4', 0, 3)]),
            'C': make_timeline([('c.mp4', 0, 3)]),
        }
        mat = similarity_matrix(variants)
        self.assertIn('AvsB', mat)
        self.assertIn('AvsC', mat)
        self.assertIn('BvsC', mat)
        self.assertEqual(len(mat), 3)

    def test_identical_variants_score_1(self):
        segs = make_timeline([('v.mp4', 0, 3)])
        mat = similarity_matrix({'A': segs, 'B': segs})
        self.assertAlmostEqual(mat['AvsB'], 1.0)

    def test_disjoint_variants_score_0(self):
        mat = similarity_matrix({
            'A': make_timeline([('a.mp4', 0, 3)]),
            'B': make_timeline([('b.mp4', 10, 13)]),
        })
        self.assertAlmostEqual(mat['AvsB'], 0.0)


# ── calculate_timeline_stats() ────────────────────────────────────────────────

class TestCalculateTimelineStats(unittest.TestCase):

    def test_empty_returns_zeros(self):
        s = calculate_timeline_stats([])
        self.assertEqual(s['n_clips'], 0)
        self.assertEqual(s['avg_duration'], 0.0)
        self.assertEqual(s['total_duration'], 0.0)

    def test_clip_counts(self):
        segs = [MockSeg(start=0, end=5), MockSeg(start=0, end=3)]
        s = calculate_timeline_stats(segs)
        self.assertEqual(s['n_clips'], 2)
        self.assertAlmostEqual(s['total_duration'], 8.0, places=1)
        self.assertAlmostEqual(s['avg_duration'], 4.0, places=1)

    def test_energy_range(self):
        segs = [MockSeg(_features=MockFeatures(action_score=0.8, motion_score=0.7)) for _ in range(5)]
        s = calculate_timeline_stats(segs)
        self.assertGreater(s['energy'], 0.0)
        self.assertLessEqual(s['energy'], 1.0)

    def test_no_features_uses_default_energy(self):
        segs = [MockSeg(_features=None) for _ in range(3)]
        for seg in segs:
            seg._features = None
        s = calculate_timeline_stats(segs)
        self.assertEqual(s['energy'], 0.5)


# ── get_variant_ui_description() ──────────────────────────────────────────────

class TestGetVariantUiDescription(unittest.TestCase):

    def test_returns_non_empty_string(self):
        p = VARIANT_PROFILES['B']
        stats = {'avg_duration': 2.5, 'total_duration': 30.0, 'energy': 0.75, 'n_clips': 12}
        desc = get_variant_ui_description(p, stats)
        self.assertIsInstance(desc, str)
        self.assertGreater(len(desc), 0)

    def test_includes_profile_description(self):
        p = VARIANT_PROFILES['C']
        stats = {'avg_duration': 4.0, 'total_duration': 60.0, 'energy': 0.3, 'n_clips': 15}
        desc = get_variant_ui_description(p, stats)
        self.assertIn(p.description, desc)

    def test_high_energy_label(self):
        p = VARIANT_PROFILES['B']
        stats = {'avg_duration': 2.0, 'total_duration': 30.0, 'energy': 0.80, 'n_clips': 15}
        desc = get_variant_ui_description(p, stats)
        self.assertIn("Высокая", desc)

    def test_low_energy_label(self):
        p = VARIANT_PROFILES['C']
        stats = {'avg_duration': 5.0, 'total_duration': 60.0, 'energy': 0.20, 'n_clips': 12}
        desc = get_variant_ui_description(p, stats)
        self.assertIn("Низкая", desc)

    def test_with_ref_stats_includes_pct_diff(self):
        p = VARIANT_PROFILES['B']
        stats     = {'avg_duration': 2.5, 'total_duration': 25.0, 'energy': 0.7, 'n_clips': 10}
        ref_stats = {'avg_duration': 4.0, 'total_duration': 50.0, 'energy': 0.5, 'n_clips': 12}
        desc = get_variant_ui_description(p, stats, ref_stats)
        self.assertIn("≠A", desc)

    def test_without_ref_stats_no_pct_diff(self):
        p = VARIANT_PROFILES['A']
        stats = {'avg_duration': 3.0, 'total_duration': 30.0, 'energy': 0.5, 'n_clips': 10}
        desc = get_variant_ui_description(p, stats)
        self.assertNotIn("≠A", desc)


# ── apply_profile_weights() ───────────────────────────────────────────────────

class TestApplyProfileWeights(unittest.TestCase):

    def test_a_no_change(self):
        cands = [MockCand(motion=0.5, sharpness=0.5, final_score=0.5)]
        apply_profile_weights(cands, VARIANT_PROFILES['A'])
        self.assertAlmostEqual(cands[0].final_score, 0.5)

    def test_b_boosts_motion_candidates(self):
        high_motion = MockCand(motion=1.0, sharpness=0.2, final_score=0.5)
        low_motion  = MockCand(motion=0.0, sharpness=0.2, final_score=0.5)
        apply_profile_weights([high_motion, low_motion], VARIANT_PROFILES['B'])
        self.assertGreater(high_motion.final_score, low_motion.final_score)

    def test_c_boosts_aesthetic_candidates(self):
        high_aes = MockCand(motion=0.2, sharpness=1.0, final_score=0.5)
        low_aes  = MockCand(motion=0.2, sharpness=0.0, final_score=0.5)
        apply_profile_weights([high_aes, low_aes], VARIANT_PROFILES['C'])
        self.assertGreater(high_aes.final_score, low_aes.final_score)

    def test_returns_same_list(self):
        cands = [MockCand()]
        result = apply_profile_weights(cands, VARIANT_PROFILES['B'])
        self.assertIs(result, cands)

    def test_no_features_skipped(self):
        cand = MockCand(final_score=0.5)
        cand.features = None
        apply_profile_weights([cand], VARIANT_PROFILES['B'])
        self.assertAlmostEqual(cand.final_score, 0.5)


# ── apply_alternative_penalty() ───────────────────────────────────────────────

class TestApplyAlternativePenalty(unittest.TestCase):

    def _make_cands(self, clips):
        return [MockCand(source_path=p, start=s, end=e, final_score=1.0) for p, s, e in clips]

    def _make_segs(self, clips):
        return [MockSeg(source_path=p, start=s, end=e) for p, s, e in clips]

    def test_no_penalty_when_empty_existing(self):
        cands = self._make_cands([('v.mp4', 0, 3)])
        result, n = apply_alternative_penalty(cands, [], 0.5)
        self.assertEqual(n, 0)
        self.assertAlmostEqual(cands[0].final_score, 1.0)

    def test_penalises_reused_clips(self):
        cands = self._make_cands([('v.mp4', 0, 3), ('v.mp4', 5, 8)])
        existing = self._make_segs([('v.mp4', 0, 3)])
        result, n = apply_alternative_penalty(cands, existing, 0.5)
        self.assertEqual(n, 1)
        self.assertAlmostEqual(cands[0].final_score, 0.5)
        self.assertAlmostEqual(cands[1].final_score, 1.0)

    def test_zero_penalty_no_change(self):
        cands = self._make_cands([('v.mp4', 0, 3)])
        existing = self._make_segs([('v.mp4', 0, 3)])
        result, n = apply_alternative_penalty(cands, existing, 0.0)
        self.assertEqual(n, 0)
        self.assertAlmostEqual(cands[0].final_score, 1.0)

    def test_returns_same_list(self):
        cands = self._make_cands([('v.mp4', 0, 3)])
        result, _ = apply_alternative_penalty(cands, [], 0.5)
        self.assertIs(result, cands)

    def test_counts_penalised_correctly(self):
        cands = self._make_cands([
            ('v.mp4', 0, 3), ('v.mp4', 5, 8), ('v.mp4', 10, 13)
        ])
        existing = self._make_segs([('v.mp4', 0, 3), ('v.mp4', 5, 8)])
        _, n = apply_alternative_penalty(cands, existing, 0.5)
        self.assertEqual(n, 2)


# ── shuffle_candidates_for_regen() ────────────────────────────────────────────

class TestShuffleCandidatesForRegen(unittest.TestCase):

    def test_same_seed_produces_same_order(self):
        cands = [MockCand(start=float(i)) for i in range(10)]
        s1 = shuffle_candidates_for_regen(cands, regen_attempt=1, base_seed=42)
        s2 = shuffle_candidates_for_regen(cands, regen_attempt=1, base_seed=42)
        self.assertEqual(
            [c.start for c in s1],
            [c.start for c in s2],
        )

    def test_different_attempts_produce_different_order(self):
        cands = [MockCand(start=float(i)) for i in range(10)]
        s1 = shuffle_candidates_for_regen(cands, regen_attempt=1, base_seed=42)
        s2 = shuffle_candidates_for_regen(cands, regen_attempt=2, base_seed=42)
        self.assertNotEqual(
            [c.start for c in s1],
            [c.start for c in s2],
        )

    def test_does_not_mutate_original(self):
        cands = [MockCand(start=float(i)) for i in range(5)]
        original_order = [c.start for c in cands]
        shuffle_candidates_for_regen(cands, regen_attempt=1, base_seed=42)
        self.assertEqual([c.start for c in cands], original_order)

    def test_returns_same_elements(self):
        cands = [MockCand(start=float(i)) for i in range(6)]
        shuffled = shuffle_candidates_for_regen(cands, regen_attempt=1, base_seed=7)
        self.assertEqual(len(shuffled), len(cands))
        self.assertEqual(set(id(c) for c in shuffled), set(id(c) for c in cands))


# ── Diversity enforcement logic ───────────────────────────────────────────────

class TestDiversityEnforcement(unittest.TestCase):

    def test_threshold_constant(self):
        self.assertEqual(SIMILARITY_THRESHOLD, 0.85)

    def test_below_threshold_accepted(self):
        a = make_timeline([('a.mp4', 0, 3), ('b.mp4', 5, 8)])
        b = make_timeline([('c.mp4', 0, 3), ('d.mp4', 5, 8)])
        self.assertLess(compare_timelines(a, b), SIMILARITY_THRESHOLD)

    def test_identical_above_threshold(self):
        tl = make_timeline([('a.mp4', 0, 3), ('b.mp4', 5, 8)])
        self.assertGreater(compare_timelines(tl, tl), SIMILARITY_THRESHOLD)

    def test_four_distinct_profiles_produce_different_seeds(self):
        seeds = [42 + VARIANT_PROFILES[l].seed_offset for l in 'ABCD']
        self.assertEqual(len(seeds), len(set(seeds)))

    def test_b_clips_are_shorter_than_c_by_multiplier(self):
        mult_b = VARIANT_PROFILES['B'].clip_duration_multiplier
        mult_c = VARIANT_PROFILES['C'].clip_duration_multiplier
        self.assertLess(mult_b, mult_c)

    def test_similarity_matrix_returns_all_pairs(self):
        tls = {
            'A': make_timeline([('a.mp4', 0, 3)]),
            'B': make_timeline([('b.mp4', 0, 3)]),
            'C': make_timeline([('c.mp4', 0, 3)]),
            'D': make_timeline([('d.mp4', 0, 3)]),
        }
        mat = similarity_matrix(tls)
        expected_keys = {'AvsB', 'AvsC', 'AvsD', 'BvsC', 'BvsD', 'CvsD'}
        self.assertEqual(set(mat.keys()), expected_keys)

    def test_all_sim_scores_between_0_and_1(self):
        tls = {
            'A': make_timeline([('a.mp4', 0, 3), ('b.mp4', 5, 8)]),
            'B': make_timeline([('a.mp4', 0, 3), ('c.mp4', 10, 13)]),
        }
        mat = similarity_matrix(tls)
        for k, v in mat.items():
            self.assertGreaterEqual(v, 0.0, f"{k} below 0")
            self.assertLessEqual(v, 1.0, f"{k} above 1")


if __name__ == '__main__':
    unittest.main()
