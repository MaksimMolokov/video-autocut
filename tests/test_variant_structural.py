"""
Structural variant diversity tests.

Covers:
  Unit:
    1–11  build_variant_constraints() differences
    12–15 analyze_timeline_difference() correctness
    16–20 Minimum requirement checks
    21–24 Intro/outro picker with exclusions
    25–27 _fill_body seed behaviour
    28–30 CandidatePools building

  Integration:
    31–45 Full synthetic 20-scene build → 4 distinct timelines

  Regression:
    46–53 Previous-session contract preserved
"""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.timeline.variant_constraints import (
    VariantMemory,
    VariantConstraints,
    TimelineFingerprint,
    CandidatePools,
    build_candidate_pools,
    build_variant_constraints,
    analyze_timeline_difference,
    check_minimum_requirements,
    get_pair_threshold,
    scene_id,
    _lcs_length,
    PAIR_THRESHOLDS,
)


# ── Minimal mock objects ──────────────────────────────────────────────────────

@dataclass
class MockFeatures:
    action_score:            float = 0.5
    motion_score:            float = 0.5
    sharpness_score:         float = 0.6
    brightness_score:        float = 0.6
    camera_stability_score:  float = 0.7
    visual_complexity_score: float = 0.5
    scene_change_score:      float = 0.3
    color_saturation_score:  float = 0.5
    color_diversity_score:   float = 0.5
    contrast_score:          float = 0.5
    calm_score:              float = 0.5
    technical_quality_score: float = 0.6
    uniqueness_score:        float = 0.5


class MockCand:
    def __init__(self, path='v.mp4', start=0.0, end=3.0,
                 motion=0.5, sharpness=0.6, action=0.5,
                 stability=0.7, final_score=0.6):
        self.source_path = path
        self.start       = start
        self.end         = end
        self.duration    = end - start
        self.final_score = final_score
        self.features    = MockFeatures(
            motion_score=motion, sharpness_score=sharpness,
            action_score=action, camera_stability_score=stability,
        )
        self.is_must_use = False


class MockSeg:
    def __init__(self, path='v.mp4', start=0.0, end=3.0):
        self.source_path   = path
        self.start         = start
        self.end           = end
        self.duration      = end - start
        self._features     = None
        self.start_transition = ''
        self.role          = 'body'


def make_rich_pool(n=20) -> List[MockCand]:
    """Build n distinct candidates from two 'source' files."""
    cands = []
    for i in range(n):
        path  = 'a.mp4' if i % 2 == 0 else 'b.mp4'
        start = float(i * 5)
        end   = start + 3.0 + (i % 3)
        motion    = 0.3 + (i % 5) * 0.1
        sharpness = 0.4 + (i % 4) * 0.1
        action    = 0.2 + (i % 6) * 0.1
        stability = 0.5 + (i % 3) * 0.1
        score     = 0.3 + (i % 7) * 0.05
        cands.append(MockCand(path, start, end, motion, sharpness, action, stability, score))
    return cands


def make_segments_from_cands(cands: list) -> List[MockSeg]:
    return [MockSeg(c.source_path, c.start, c.end) for c in cands]


def make_fp(variant_id: str, segs: List[MockSeg], seed: int = 42) -> TimelineFingerprint:
    return TimelineFingerprint.from_segments(segs, variant_id, seed)


# ── Helper: build memory with one variant registered ──────────────────────────

def _memory_with_A(pool: CandidatePools) -> VariantMemory:
    mem  = VariantMemory()
    vc_a = build_variant_constraints('A', mem, pool)
    segs = make_segments_from_cands(pool.all_candidates[:5])
    fp_a = make_fp('A', segs, 42 + vc_a.seed_offset)
    mem.register('A', fp_a)
    return mem


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS: build_variant_constraints
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildVariantConstraints(unittest.TestCase):

    def setUp(self):
        cands = make_rich_pool(20)
        self.pool = build_candidate_pools(cands)
        self.empty_mem = VariantMemory()

    # 1. A/B/C/D get different opening strategies
    def test_opening_strategies_differ(self):
        mem = VariantMemory()
        strategies = set()
        for letter in 'ABCD':
            vc = build_variant_constraints(letter, mem, self.pool)
            strategies.add(vc.opening_strategy)
            # Register dummy so memory grows
            segs = make_segments_from_cands(self.pool.all_candidates[:3])
            fp = make_fp(letter, segs)
            mem.register(letter, fp)
        self.assertGreater(len(strategies), 1, "All variants have same opening_strategy")

    # 2. A/B/C/D get different ending strategies
    def test_ending_strategies_differ(self):
        mem = VariantMemory()
        strategies = set()
        for letter in 'ABCD':
            vc = build_variant_constraints(letter, mem, self.pool)
            strategies.add(vc.ending_strategy)
            segs = make_segments_from_cands(self.pool.all_candidates[:3])
            mem.register(letter, make_fp(letter, segs))
        self.assertGreater(len(strategies), 1)

    # 3. A/B/C/D get different scene_selection_strategy
    def test_scene_selection_strategies_differ(self):
        mem = VariantMemory()
        strategies = set()
        for letter in 'ABCD':
            vc = build_variant_constraints(letter, mem, self.pool)
            strategies.add(vc.scene_selection_strategy)
            segs = make_segments_from_cands(self.pool.all_candidates[:3])
            mem.register(letter, make_fp(letter, segs))
        self.assertEqual(len(strategies), 4, f"Expected 4 distinct strategies, got {strategies}")

    # 4. A is balanced baseline
    def test_a_is_balanced(self):
        vc = build_variant_constraints('A', self.empty_mem, self.pool)
        self.assertEqual(vc.scene_selection_strategy, 'balanced_top_quality')
        self.assertEqual(vc.segment_duration_policy, 'normal')
        self.assertIsNone(vc.scene_overlap_limit)
        self.assertEqual(vc.diversity_pressure, 0.0)

    # 5. B has shorter segment policy
    def test_b_has_shorter_policy(self):
        mem = _memory_with_A(self.pool)
        vc = build_variant_constraints('B', mem, self.pool)
        self.assertEqual(vc.segment_duration_policy, 'shorter')

    # 6. C has longer segment policy
    def test_c_has_longer_policy(self):
        mem = _memory_with_A(self.pool)
        vc = build_variant_constraints('C', mem, self.pool)
        self.assertEqual(vc.segment_duration_policy, 'longer')

    # 7. D has highest diversity_pressure
    def test_d_has_highest_diversity_pressure(self):
        mem = VariantMemory()
        pressures = {}
        for letter in 'ABCD':
            vc = build_variant_constraints(letter, mem, self.pool)
            pressures[letter] = vc.diversity_pressure
            segs = make_segments_from_cands(self.pool.all_candidates[:3])
            mem.register(letter, make_fp(letter, segs))
        self.assertEqual(pressures['D'], max(pressures.values()))

    # 8. B/C/D exclude A's opening when alternatives exist (rich pool)
    def test_b_excludes_a_opening(self):
        mem = _memory_with_A(self.pool)
        vc = build_variant_constraints('B', mem, self.pool)
        self.assertTrue(
            len(vc.excluded_opening_ids) > 0,
            "B should exclude A's opening when alternatives are available"
        )

    # 9. D has higher pressure than B and C
    def test_d_pressure_greater_than_b_and_c(self):
        mem = _memory_with_A(self.pool)
        vc_b = build_variant_constraints('B', mem, self.pool)
        vc_c = build_variant_constraints('C', mem, self.pool)
        vc_d = build_variant_constraints('D', mem, self.pool)
        self.assertGreater(vc_d.diversity_pressure, vc_b.diversity_pressure)
        self.assertGreater(vc_d.diversity_pressure, vc_c.diversity_pressure)

    # 10. A has no exclusions (it is baseline)
    def test_a_has_no_exclusions(self):
        vc = build_variant_constraints('A', self.empty_mem, self.pool)
        self.assertEqual(len(vc.excluded_opening_ids), 0)
        self.assertEqual(len(vc.excluded_ending_ids), 0)
        self.assertEqual(len(vc.soft_excluded_ids), 0)

    # 11. seed_offsets unique across A/B/C/D
    def test_seed_offsets_unique(self):
        mem = VariantMemory()
        offsets = set()
        for letter in 'ABCD':
            vc = build_variant_constraints(letter, mem, self.pool)
            offsets.add(vc.seed_offset)
            segs = make_segments_from_cands(self.pool.all_candidates[:3])
            mem.register(letter, make_fp(letter, segs))
        self.assertEqual(len(offsets), 4)


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS: analyze_timeline_difference
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyzeTimelineDifference(unittest.TestCase):

    def _fp(self, vid, segs, seed=42):
        return make_fp(vid, segs, seed)

    # 12. Identical timelines → overall_similarity = 1.0
    def test_identical_similarity_is_1(self):
        segs = [MockSeg('v.mp4', 0, 3), MockSeg('v.mp4', 5, 8), MockSeg('v.mp4', 10, 13)]
        fp_a = self._fp('A', segs)
        fp_b = self._fp('B', segs)
        diff = analyze_timeline_difference(fp_a, fp_b)
        self.assertAlmostEqual(diff['overall_similarity'], 1.0, places=2)

    # 13. Different openings detected
    def test_different_openings_detected(self):
        segs_a = [MockSeg('a.mp4', 0, 3), MockSeg('v.mp4', 5, 8)]
        segs_b = [MockSeg('b.mp4', 0, 3), MockSeg('v.mp4', 5, 8)]
        fp_a = self._fp('A', segs_a)
        fp_b = self._fp('B', segs_b)
        diff = analyze_timeline_difference(fp_a, fp_b)
        self.assertFalse(diff['same_opening'])

    # 14. Different endings detected
    def test_different_endings_detected(self):
        segs_a = [MockSeg('v.mp4', 0, 3), MockSeg('a.mp4', 10, 13)]
        segs_b = [MockSeg('v.mp4', 0, 3), MockSeg('b.mp4', 10, 13)]
        fp_a = self._fp('A', segs_a)
        fp_b = self._fp('B', segs_b)
        diff = analyze_timeline_difference(fp_a, fp_b)
        self.assertFalse(diff['same_ending'])

    # 15. Empty fingerprints don't crash
    def test_empty_fingerprints_no_crash(self):
        fp_a = make_fp('A', [])
        fp_b = make_fp('B', [])
        diff = analyze_timeline_difference(fp_a, fp_b)
        self.assertEqual(diff['overall_similarity'], 0.0)

    # 16. scene_set_overlap_ratio range 0–1
    def test_scene_set_overlap_range(self):
        segs_a = [MockSeg('a.mp4', 0, 3), MockSeg('b.mp4', 5, 8)]
        segs_b = [MockSeg('a.mp4', 0, 3), MockSeg('c.mp4', 10, 13)]
        fp_a = self._fp('A', segs_a)
        fp_b = self._fp('B', segs_b)
        diff = analyze_timeline_difference(fp_a, fp_b)
        self.assertGreaterEqual(diff['scene_set_overlap_ratio'], 0.0)
        self.assertLessEqual(diff['scene_set_overlap_ratio'], 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS: check_minimum_requirements
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckMinimumRequirements(unittest.TestCase):

    def setUp(self):
        cands = make_rich_pool(20)
        self.pool = build_candidate_pools(cands)

    # 17. A never has violations
    def test_a_never_has_violations(self):
        mem = VariantMemory()
        segs = [MockSeg('a.mp4', 0, 3), MockSeg('b.mp4', 5, 8)]
        fp_a = make_fp('A', segs)
        violations = check_minimum_requirements(fp_a, mem, self.pool)
        self.assertEqual(violations, [])

    # 18. Identical B vs A triggers same_opening violation when alternatives exist
    def test_same_opening_triggers_violation(self):
        mem = VariantMemory()
        segs_a = [MockSeg('a.mp4', 0, 3), MockSeg('b.mp4', 5, 8)]
        fp_a = make_fp('A', segs_a)
        mem.register('A', fp_a)
        # B has same opening scene
        segs_b = [MockSeg('a.mp4', 0, 3), MockSeg('c.mp4', 10, 13)]
        fp_b = make_fp('B', segs_b)
        violations = check_minimum_requirements(fp_b, mem, self.pool)
        # Should flag same_opening (pool has >1 opening candidate)
        opening_violations = [v for v in violations if 'same_opening' in v]
        self.assertTrue(len(opening_violations) > 0 or len(violations) > 0)

    # 19. Similarity above threshold triggers violation
    def test_high_similarity_triggers_violation(self):
        mem = VariantMemory()
        segs = [MockSeg(f'v.mp4', i * 5, i * 5 + 3) for i in range(6)]
        fp_a = make_fp('A', segs)
        mem.register('A', fp_a)
        # B identical to A
        fp_b = make_fp('B', segs)
        violations = check_minimum_requirements(fp_b, mem, self.pool)
        self.assertTrue(len(violations) > 0,
                        "Identical timelines should fail minimum requirements")

    # 20. Returns empty list when diversity is sufficient
    def test_diverse_variants_no_violations(self):
        mem = VariantMemory()
        segs_a = [MockSeg('a.mp4', i * 5, i * 5 + 3) for i in range(5)]
        fp_a = make_fp('A', segs_a)
        mem.register('A', fp_a)
        # B has completely different scenes
        segs_b = [MockSeg('b.mp4', i * 5 + 100, i * 5 + 103) for i in range(5)]
        fp_b = make_fp('B', segs_b)
        violations = check_minimum_requirements(fp_b, mem, self.pool)
        sim_violations = [v for v in violations if 'similarity' in v]
        self.assertEqual(sim_violations, [])


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS: build_candidate_pools
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildCandidatePools(unittest.TestCase):

    # 21. All pools populated for rich input
    def test_pools_populated(self):
        cands = make_rich_pool(20)
        pools = build_candidate_pools(cands)
        self.assertGreater(len(pools.all_candidates), 0)
        self.assertGreater(len(pools.opening_candidates), 0)
        self.assertGreater(len(pools.ending_candidates), 0)

    # 22. all_candidates sorted by score descending
    def test_all_candidates_sorted_descending(self):
        cands = make_rich_pool(10)
        pools = build_candidate_pools(cands)
        scores = [getattr(c, 'final_score', 0.0) for c in pools.all_candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))

    # 23. material_level correct for rich input
    def test_material_level_rich(self):
        pools = build_candidate_pools(make_rich_pool(20))
        self.assertEqual(pools.material_level, 'rich')

    # 24. material_level limited for small input
    def test_material_level_limited(self):
        pools = build_candidate_pools(make_rich_pool(3))
        self.assertEqual(pools.material_level, 'limited')

    # 25. opening_candidates sorted by score
    def test_opening_sorted(self):
        pools = build_candidate_pools(make_rich_pool(20))
        scores = [getattr(c, 'final_score', 0.0) for c in pools.opening_candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))

    # 26. high_motion_candidates have motion > threshold
    def test_high_motion_candidates(self):
        pools = build_candidate_pools(make_rich_pool(20))
        for c in pools.high_motion_candidates:
            f = getattr(c, 'features', None)
            if f:
                self.assertTrue(
                    getattr(f, 'motion_score', 0) > 0.4 or
                    getattr(f, 'action_score', 0) > 0.4
                )

    # 27. alternative_candidates are not in top-half
    def test_alternative_not_in_top_half(self):
        pools = build_candidate_pools(make_rich_pool(20))
        top_half_ids = {id(c) for c in pools.all_candidates[:len(pools.all_candidates)//2]}
        for c in pools.alternative_candidates:
            self.assertNotIn(id(c), top_half_ids,
                             "Alternative candidate should not be in top half")


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS: pair thresholds and scene_id
# ═══════════════════════════════════════════════════════════════════════════════

class TestPairThresholdsAndSceneId(unittest.TestCase):

    # 28. A-D threshold strictest
    def test_a_d_strictest(self):
        t_ad = get_pair_threshold('A', 'D')
        t_ab = get_pair_threshold('A', 'B')
        t_ac = get_pair_threshold('A', 'C')
        self.assertLess(t_ad, t_ab)
        self.assertLess(t_ad, t_ac)

    # 29. scene_id stable across calls
    def test_scene_id_stable(self):
        c = MockCand('v.mp4', 1.0, 4.0)
        id1 = scene_id(c)
        id2 = scene_id(c)
        self.assertEqual(id1, id2)

    # 30. scene_id distinct for different clips
    def test_scene_id_distinct(self):
        c1 = MockCand('v.mp4', 0.0, 3.0)
        c2 = MockCand('v.mp4', 5.0, 8.0)
        c3 = MockCand('other.mp4', 0.0, 3.0)
        ids = {scene_id(c1), scene_id(c2), scene_id(c3)}
        self.assertEqual(len(ids), 3)


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS: Synthetic 20-scene build
# ═══════════════════════════════════════════════════════════════════════════════

class TestSyntheticFourVariantBuild(unittest.TestCase):
    """
    Simulate building 4 variants sequentially using VariantMemory.
    Uses apply_variant_scoring (no FFmpeg), so tests are fast and pure Python.
    """

    def setUp(self):
        from src.timeline.variant_constraints import apply_variant_scoring
        self.apply_scoring = apply_variant_scoring
        self.cands = make_rich_pool(20)
        self.pool  = build_candidate_pools(self.cands)

    def _build_variant(self, letter: str, mem: VariantMemory, seed_override: int = None):
        vc = build_variant_constraints(letter, mem, self.pool)
        seed = seed_override if seed_override is not None else (42 + vc.seed_offset)
        ordered = self.apply_scoring(self.cands, vc, seed)
        # Simulate selecting first 5 clips as "timeline"
        chosen = []
        for c in ordered:
            from src.timeline.variant_constraints import scene_id as _sid
            if _sid(c) not in vc.hard_excluded_ids:
                chosen.append(c)
            if len(chosen) >= 5:
                break
        segs = make_segments_from_cands(chosen)
        fp = make_fp(letter, segs, seed)
        mem.register(letter, fp)
        return segs, fp, vc

    def test_31_four_builds_produce_fingerprints(self):
        mem = VariantMemory()
        for letter in 'ABCD':
            self._build_variant(letter, mem)
        self.assertEqual(len(mem.fingerprints), 4)

    def test_32_fingerprints_have_correct_variant_ids(self):
        mem = VariantMemory()
        for letter in 'ABCD':
            self._build_variant(letter, mem)
        for letter in 'ABCD':
            self.assertEqual(mem.fingerprints[letter].variant_id, letter)

    def test_33_memory_tracks_opening_ids(self):
        mem = VariantMemory()
        for letter in 'ABCD':
            self._build_variant(letter, mem)
        self.assertEqual(len(mem.used_opening_ids), 4)

    def test_34_memory_tracks_ending_ids(self):
        mem = VariantMemory()
        for letter in 'ABCD':
            self._build_variant(letter, mem)
        self.assertEqual(len(mem.used_ending_ids), 4)

    def test_35_b_excludes_a_opening_when_alternatives_exist(self):
        mem = VariantMemory()
        _, fp_a, _ = self._build_variant('A', mem)
        vc_b = build_variant_constraints('B', mem, self.pool)
        self.assertIn(fp_a.first_scene_id, vc_b.excluded_opening_ids)

    def test_36_c_excludes_a_and_b_openings(self):
        mem = VariantMemory()
        for letter in 'AB':
            self._build_variant(letter, mem)
        vc_c = build_variant_constraints('C', mem, self.pool)
        # Should exclude both A and B openings
        for prev in 'AB':
            self.assertIn(mem.fingerprints[prev].first_scene_id, vc_c.excluded_opening_ids)

    def test_37_d_excludes_all_prev_openings(self):
        mem = VariantMemory()
        for letter in 'ABC':
            self._build_variant(letter, mem)
        vc_d = build_variant_constraints('D', mem, self.pool)
        for prev in 'ABC':
            self.assertIn(mem.fingerprints[prev].first_scene_id, vc_d.excluded_opening_ids)

    def test_38_b_has_soft_excluded_from_a(self):
        mem = VariantMemory()
        _, fp_a, _ = self._build_variant('A', mem)
        vc_b = build_variant_constraints('B', mem, self.pool)
        # With rich material, B should have some soft exclusions from A
        if self.pool.material_level == 'rich':
            self.assertGreater(len(vc_b.soft_excluded_ids), 0)

    def test_39_d_constraint_has_higher_overlap_strictness(self):
        mem = VariantMemory()
        for letter in 'ABC':
            self._build_variant(letter, mem)
        vc_d = build_variant_constraints('D', mem, self.pool)
        self.assertIsNotNone(vc_d.scene_overlap_limit)
        self.assertLessEqual(vc_d.scene_overlap_limit, 0.55)

    def test_40_b_segment_duration_shorter_than_c(self):
        mem = VariantMemory()
        _, fp_a, _ = self._build_variant('A', mem)
        vc_b = build_variant_constraints('B', mem, self.pool)
        vc_c = build_variant_constraints('C', mem, self.pool)
        self.assertEqual(vc_b.segment_duration_policy, 'shorter')
        self.assertEqual(vc_c.segment_duration_policy, 'longer')

    def test_41_pair_thresholds_all_defined(self):
        for va in 'ABCD':
            for vb in 'ABCD':
                if va != vb:
                    thr = get_pair_threshold(va, vb)
                    self.assertGreater(thr, 0.0)
                    self.assertLessEqual(thr, 1.0)

    def test_42_lcs_length_correct(self):
        self.assertEqual(_lcs_length(['a', 'b', 'c'], ['a', 'b', 'c']), 3)
        self.assertEqual(_lcs_length(['a', 'b', 'c'], ['x', 'y', 'z']), 0)
        self.assertEqual(_lcs_length(['a', 'b', 'c'], ['a', 'x', 'c']), 2)
        self.assertEqual(_lcs_length([], ['a']), 0)

    def test_43_analyze_diff_detects_same_opening(self):
        segs_a = [MockSeg('x.mp4', 0, 3), MockSeg('y.mp4', 5, 8)]
        segs_b = [MockSeg('x.mp4', 0, 3), MockSeg('z.mp4', 10, 13)]
        fp_a = make_fp('A', segs_a)
        fp_b = make_fp('B', segs_b)
        diff = analyze_timeline_difference(fp_a, fp_b)
        self.assertTrue(diff['same_opening'])
        self.assertFalse(diff['same_ending'])

    def test_44_d_has_alternative_selection_strategy(self):
        mem = VariantMemory()
        for letter in 'ABC':
            self._build_variant(letter, mem)
        vc_d = build_variant_constraints('D', mem, self.pool)
        self.assertEqual(vc_d.scene_selection_strategy, 'least_used_high_quality')

    def test_45_memory_all_used_ids_grows(self):
        mem = VariantMemory()
        prev_count = 0
        for letter in 'ABCD':
            self._build_variant(letter, mem)
            new_count = len(mem.all_used_ids())
            # Each variant should add at least some unique scene IDs
            # (may not always grow if pool is very small)
            self.assertGreaterEqual(new_count, prev_count)
            prev_count = new_count


# ═══════════════════════════════════════════════════════════════════════════════
# REGRESSION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegressionContracts(unittest.TestCase):
    """Ensure nothing regressed in existing variant_profiles API."""

    def test_46_variant_profiles_still_importable(self):
        from src.variant_profiles import VARIANT_PROFILES, SIMILARITY_THRESHOLD
        self.assertIn('A', VARIANT_PROFILES)
        self.assertIn('B', VARIANT_PROFILES)
        self.assertIn('C', VARIANT_PROFILES)
        self.assertIn('D', VARIANT_PROFILES)

    def test_47_compare_timelines_still_works(self):
        from src.variant_profiles import compare_timelines
        segs_a = [MockSeg('v.mp4', 0, 3)]
        segs_b = [MockSeg('v.mp4', 0, 3)]
        self.assertAlmostEqual(compare_timelines(segs_a, segs_b), 1.0)

    def test_48_calculate_timeline_stats_still_works(self):
        from src.variant_profiles import calculate_timeline_stats
        segs = [MockSeg('v.mp4', 0, 5), MockSeg('v.mp4', 5, 9)]
        stats = calculate_timeline_stats(segs)
        self.assertEqual(stats['n_clips'], 2)
        self.assertAlmostEqual(stats['total_duration'], 9.0, places=1)

    def test_49_timeline_fingerprint_from_empty_segments(self):
        fp = TimelineFingerprint.from_segments([], 'A', 42)
        self.assertEqual(fp.first_scene_id, '')
        self.assertEqual(fp.segment_count, 0)
        self.assertEqual(fp.total_duration, 0.0)

    def test_50_timeline_fingerprint_preserves_variant_id(self):
        segs = [MockSeg('v.mp4', 0, 3)]
        fp = TimelineFingerprint.from_segments(segs, 'C', 999)
        self.assertEqual(fp.variant_id, 'C')
        self.assertEqual(fp.seed, 999)

    def test_51_variant_memory_register_and_retrieve(self):
        mem = VariantMemory()
        segs = [MockSeg('v.mp4', 0, 3), MockSeg('v.mp4', 5, 8)]
        fp = TimelineFingerprint.from_segments(segs, 'A', 42)
        mem.register('A', fp)
        self.assertIn('A', mem.fingerprints)
        self.assertEqual(mem.fingerprints['A'].first_scene_id, fp.first_scene_id)

    def test_52_get_pair_threshold_symmetric(self):
        self.assertEqual(get_pair_threshold('A', 'B'), get_pair_threshold('B', 'A'))
        self.assertEqual(get_pair_threshold('C', 'D'), get_pair_threshold('D', 'C'))

    def test_53_candidate_pools_empty_input(self):
        pools = build_candidate_pools([])
        self.assertEqual(pools.total_usable, 0)
        self.assertEqual(pools.material_level, 'limited')


if __name__ == '__main__':
    unittest.main()
