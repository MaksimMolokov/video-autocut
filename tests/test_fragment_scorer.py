"""
Tests for fragment_scorer: UMS computation, dynamic calibration, categorization.
All tests use synthetic fragment dicts — no video files needed.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.preprocessing.fragment_scorer import (
    calibrate_project_thresholds,
    compute_ums,
    assign_category,
    score_fragments,
    check_material_sufficiency,
    build_diagnostic_report,
    _DEFAULT_CALIB,
)


# ── Helper factories ──────────────────────────────────────────────────────────

def _frag(quality=0.65, sharpness=0.55, brightness=0.50, stability=0.80,
          motion=0.30, contrast=0.45, cinematic=0.50,
          source_id=1, start_s=0.0, end_s=5.0, **kw):
    base = {
        'id': int(start_s * 100 + source_id * 10000),
        'source_id': source_id,
        'start_s': start_s, 'end_s': end_s, 'duration_s': end_s - start_s,
        'quality_score': quality, 'sharpness': sharpness,
        'brightness': brightness, 'stability': stability,
        'motion': motion, 'contrast': contrast,
        'cinematic_score': cinematic, 'action_score': 0.3,
        'is_rejected': False,
    }
    base.update(kw)
    return base


def _scene(category='good', duration_s=10.0, fids=None):
    return {
        'source_id': 1, 'start_s': 0.0, 'end_s': duration_s,
        'duration_s': duration_s,
        'quality_score': 0.6, 'ums_score': 0.55,
        'category': category,
        'fragment_ids': fids or [1, 2],
    }


# ── Calibration tests ─────────────────────────────────────────────────────────

class TestCalibration(unittest.TestCase):

    def test_too_few_fragments_returns_defaults(self):
        calib = calibrate_project_thresholds([_frag() for _ in range(3)])
        self.assertEqual(calib['n_total'], 0.0)  # default calib n_total is 0
        self.assertAlmostEqual(calib['p50_quality'], _DEFAULT_CALIB['p50_quality'])

    def test_many_fragments_computes_percentiles(self):
        # 10 fragments with quality 0.10, 0.20, ..., 1.00
        frags = [_frag(quality=(i + 1) * 0.10) for i in range(10)]
        calib = calibrate_project_thresholds(frags)
        self.assertEqual(calib['n_total'], 10.0)
        self.assertAlmostEqual(calib['p50_quality'], 0.50, delta=0.12)
        self.assertGreater(calib['p75_quality'], calib['p50_quality'])
        self.assertGreater(calib['p50_quality'], calib['p25_quality'])

    def test_high_quality_project_has_high_p50(self):
        frags = [_frag(quality=0.85 + i * 0.01) for i in range(10)]
        calib = calibrate_project_thresholds(frags)
        self.assertGreater(calib['p50_quality'], 0.80)

    def test_low_quality_project_has_low_p50(self):
        frags = [_frag(quality=0.10 + i * 0.01) for i in range(10)]
        calib = calibrate_project_thresholds(frags)
        self.assertLess(calib['p50_quality'], 0.25)

    def test_all_zero_quality_returns_defaults(self):
        frags = [_frag(quality=0.0) for _ in range(20)]
        calib = calibrate_project_thresholds(frags)
        # zero-quality fragments filtered out → n_total = 0 → defaults
        self.assertEqual(calib['n_total'], 0.0)


# ── UMS computation tests ─────────────────────────────────────────────────────

class TestComputeUMS(unittest.TestCase):

    def _calib(self):
        return dict(_DEFAULT_CALIB)

    def test_perfect_fragment_scores_high(self):
        f = _frag(quality=0.90, sharpness=0.90, brightness=0.50, stability=0.95,
                  motion=0.30, contrast=0.70, cinematic=0.80)
        ums = compute_ums(f, self._calib())
        self.assertGreater(ums, 0.70)

    def test_corrupt_fragment_scores_low(self):
        f = _frag(quality=0.05, sharpness=0.01, brightness=0.02, stability=0.10,
                  motion=0.0, contrast=0.01, cinematic=0.0, is_rejected=True)
        ums = compute_ums(f, self._calib())
        self.assertLess(ums, 0.30)

    def test_overexposed_fragment_penalized(self):
        f_ok   = _frag(brightness=0.50)
        f_over = _frag(brightness=0.95)
        ums_ok   = compute_ums(f_ok,   self._calib())
        ums_over = compute_ums(f_over, self._calib())
        self.assertGreater(ums_ok, ums_over)

    def test_dark_fragment_penalized(self):
        f_ok   = _frag(brightness=0.50)
        f_dark = _frag(brightness=0.08)
        self.assertGreater(compute_ums(f_ok, self._calib()),
                           compute_ums(f_dark, self._calib()))

    def test_blurry_fragment_penalized(self):
        f_sharp = _frag(sharpness=0.80)
        f_blury = _frag(sharpness=0.05)
        self.assertGreater(compute_ums(f_sharp, self._calib()),
                           compute_ums(f_blury, self._calib()))

    def test_unstable_fragment_penalized(self):
        f_stable = _frag(stability=0.90)
        f_shaky  = _frag(stability=0.10)
        self.assertGreater(compute_ums(f_stable, self._calib()),
                           compute_ums(f_shaky, self._calib()))

    def test_static_stable_shot_not_penalized(self):
        """Very stable static shot should score reasonably (establishing shot use case)."""
        f = _frag(motion=0.02, stability=0.95, sharpness=0.70, brightness=0.50)
        ums = compute_ums(f, self._calib())
        self.assertGreater(ums, 0.40)

    def test_chaotic_motion_penalized(self):
        f_gentle  = _frag(motion=0.30, stability=0.80)
        f_chaotic = _frag(motion=0.90, stability=0.20)
        self.assertGreater(compute_ums(f_gentle, self._calib()),
                           compute_ums(f_chaotic, self._calib()))

    def test_ums_in_range_0_1(self):
        for quality in [0.0, 0.3, 0.6, 0.9, 1.0]:
            for sharpness in [0.0, 0.5, 1.0]:
                f = _frag(quality=quality, sharpness=sharpness)
                ums = compute_ums(f, self._calib())
                self.assertGreaterEqual(ums, 0.0)
                self.assertLessEqual(ums, 1.0)

    def test_relative_sharpness_adapts_to_project(self):
        """In a project with median sharpness=0.80, a 0.60-sharpness frame
        should score better than with default calibration (median=0.28)."""
        calib_default = dict(_DEFAULT_CALIB)
        calib_sharp_project = dict(_DEFAULT_CALIB)
        calib_sharp_project['p50_sharpness'] = 0.80

        f = _frag(sharpness=0.60)
        # With sharp-project calibration, 0.60 is slightly below median → lower rel_sharp
        # With default calibration, 0.60 is well above median 0.28 → higher rel_sharp
        ums_default = compute_ums(f, calib_default)
        ums_sharp   = compute_ums(f, calib_sharp_project)
        self.assertGreater(ums_default, ums_sharp)


# ── Category assignment tests ─────────────────────────────────────────────────

class TestAssignCategory(unittest.TestCase):

    def _calib(self):
        return dict(_DEFAULT_CALIB)

    def test_high_ums_is_best(self):
        self.assertEqual(assign_category(0.85, self._calib()), 'best')

    def test_medium_ums_is_good(self):
        self.assertEqual(assign_category(0.55, self._calib()), 'good')

    def test_low_ums_is_backup(self):
        self.assertEqual(assign_category(0.32, self._calib()), 'backup')

    def test_very_low_ums_is_rejected(self):
        self.assertEqual(assign_category(0.10, self._calib()), 'rejected_by_system')

    def test_is_rejected_flag_overrides(self):
        # Even a high UMS should be rejected if is_rejected=True
        self.assertEqual(assign_category(0.95, self._calib(), is_rejected=True),
                         'rejected_by_system')

    def test_dynamic_thresholds_for_weak_project(self):
        """In a very weak project, thresholds lower so we still find 'good' material."""
        weak_calib = {
            'p25_quality': 0.08, 'p50_quality': 0.15, 'p75_quality': 0.25,
            'p50_sharpness': 0.10, 'n_total': 20.0,
        }
        # UMS=0.45 should still be 'good' in a weak project
        # (floor: thr_good >= 0.42, so p50=0.15 → thr_good=0.42)
        cat = assign_category(0.45, weak_calib)
        self.assertEqual(cat, 'good')

    def test_dynamic_thresholds_for_strong_project(self):
        """In a high-quality project, thresholds rise so only truly good material is 'best'."""
        strong_calib = {
            'p25_quality': 0.65, 'p50_quality': 0.78, 'p75_quality': 0.90,
            'p50_sharpness': 0.70, 'n_total': 50.0,
        }
        # UMS=0.70 should NOT be 'best' when project p75=0.90 → thr_best=0.82
        cat = assign_category(0.70, strong_calib)
        self.assertNotEqual(cat, 'best')

    def test_threshold_clamped_never_too_permissive(self):
        """Backup threshold never drops below 0.22 even in very weak projects."""
        very_weak_calib = {
            'p25_quality': 0.01, 'p50_quality': 0.05, 'p75_quality': 0.10,
            'p50_sharpness': 0.05, 'n_total': 10.0,
        }
        # UMS=0.05 should still be rejected (below 0.22 floor)
        cat = assign_category(0.05, very_weak_calib)
        self.assertEqual(cat, 'rejected_by_system')


# ── score_fragments integration ───────────────────────────────────────────────

class TestScoreFragments(unittest.TestCase):

    def test_diverse_project_has_multiple_categories(self):
        frags = (
            [_frag(quality=0.90, sharpness=0.90) for _ in range(5)]  # best
            + [_frag(quality=0.60, sharpness=0.55) for _ in range(5)]  # good
            + [_frag(quality=0.30, sharpness=0.20) for _ in range(5)]  # backup/weak
        )
        calib, enriched = score_fragments(frags)
        categories = {f['category'] for f in enriched}
        self.assertGreater(len(categories), 1, "Expected multiple categories")

    def test_all_fragments_get_ums_score(self):
        frags = [_frag(quality=q * 0.1) for q in range(1, 11)]
        _, enriched = score_fragments(frags)
        for f in enriched:
            self.assertIn('ums_score', f)
            self.assertIn('category', f)
            self.assertGreaterEqual(f['ums_score'], 0.0)
            self.assertLessEqual(f['ums_score'], 1.0)

    def test_original_fragments_not_mutated(self):
        frags = [_frag()]
        original_keys = set(frags[0].keys())
        score_fragments(frags)
        self.assertEqual(set(frags[0].keys()), original_keys)

    def test_returns_same_count(self):
        frags = [_frag(quality=i * 0.05) for i in range(20)]
        _, enriched = score_fragments(frags)
        self.assertEqual(len(enriched), 20)

    def test_no_candidates_lost(self):
        """Key requirement: no fragment should be silently dropped."""
        frags = [_frag(quality=0.1 + i * 0.04) for i in range(20)]
        _, enriched = score_fragments(frags)
        self.assertEqual(len(enriched), len(frags))

    def test_good_quality_project_finds_best_candidates(self):
        frags = [_frag(quality=0.70 + i * 0.02, sharpness=0.75) for i in range(10)]
        _, enriched = score_fragments(frags)
        best_count = sum(1 for f in enriched if f['category'] == 'best')
        self.assertGreater(best_count, 0, "High-quality project should have 'best' fragments")

    def test_weak_project_still_finds_backup(self):
        """Even weak footage should surface its best as 'backup' (not all rejected)."""
        frags = [_frag(quality=0.20 + i * 0.02, sharpness=0.15) for i in range(15)]
        _, enriched = score_fragments(frags)
        usable = sum(1 for f in enriched if f['category'] in ('best', 'good', 'backup'))
        self.assertGreater(usable, 0, "Weak project should still have usable fragments")


# ── Material sufficiency tests ────────────────────────────────────────────────

class TestMaterialSufficiency(unittest.TestCase):

    def test_enough_material_ok(self):
        scenes = [_scene('best', 30.0), _scene('good', 30.0), _scene('good', 30.0)]
        suf = check_material_sufficiency(scenes, target_duration=30.0, rejected_fids=set())
        self.assertTrue(suf['has_enough'])
        self.assertEqual(suf['shortage'], 0.0)

    def test_not_enough_selected_but_backup_covers(self):
        scenes = [
            _scene('good', 10.0, fids=[1, 2]),
            _scene('backup', 40.0, fids=[3, 4]),
        ]
        suf = check_material_sufficiency(scenes, target_duration=30.0, rejected_fids=set())
        self.assertFalse(suf['has_enough'])   # 10s < 45s needed (30*1.5)
        self.assertTrue(suf['has_with_backup'])   # 50s >= 45s

    def test_user_rejected_scenes_excluded_from_pool(self):
        rejected_fids = {1, 2}  # scene 1 fids
        scenes = [
            _scene('best', 30.0, fids=[1, 2]),   # user-rejected
            _scene('good', 20.0, fids=[3, 4]),
        ]
        suf = check_material_sufficiency(scenes, 20.0, rejected_fids)
        # Only 20s from 'good' scene, not 50s (rejected doesn't count)
        self.assertAlmostEqual(suf['selected_dur'], 20.0)
        self.assertEqual(suf['n_rejected_user'], 1)

    def test_rejected_by_user_not_counted_as_selected(self):
        """Core requirement: user exclusion must not silently restore footage."""
        rejected_fids = {10, 11}
        scenes = [
            _scene('best', 60.0, fids=[10, 11]),   # all material, but rejected
        ]
        suf = check_material_sufficiency(scenes, 60.0, rejected_fids)
        self.assertAlmostEqual(suf['selected_dur'], 0.0)
        self.assertFalse(suf['has_enough'])

    def test_shortage_reported_correctly(self):
        scenes = [_scene('good', 20.0, fids=[1])]
        suf = check_material_sufficiency(scenes, 60.0, set())
        self.assertGreater(suf['shortage'], 0.0)
        # Need 60*1.5=90s, have 20s → shortage = 70s
        self.assertAlmostEqual(suf['shortage'], 70.0)

    def test_counts_per_category(self):
        scenes = [
            _scene('best', 10.0, fids=[1]),
            _scene('best', 10.0, fids=[2]),
            _scene('good', 10.0, fids=[3]),
            _scene('backup', 10.0, fids=[4]),
        ]
        suf = check_material_sufficiency(scenes, 30.0, set())
        self.assertEqual(suf['n_best'], 2)
        self.assertEqual(suf['n_good'], 1)
        self.assertEqual(suf['n_backup'], 1)


# ── Diagnostic report tests ───────────────────────────────────────────────────

class TestDiagnosticReport(unittest.TestCase):

    def test_report_has_required_fields(self):
        frags = [_frag(source_id=1, quality=0.7, **{'ums_score': 0.7, 'category': 'best'}),
                 _frag(source_id=2, quality=0.5, **{'ums_score': 0.5, 'category': 'good'})]
        calib = dict(_DEFAULT_CALIB)
        scenes = [_scene('best', 10.0), _scene('good', 10.0)]
        report = build_diagnostic_report(frags, calib, scenes, 30.0)
        for key in ('n_videos', 'n_raw_fragments', 'calib', 'scene_counts', 'sufficiency'):
            self.assertIn(key, report)

    def test_report_counts_videos(self):
        frags = ([_frag(source_id=1, **{'category': 'best'})] * 5
                 + [_frag(source_id=2, **{'category': 'good'})] * 5)
        calib = dict(_DEFAULT_CALIB)
        scenes = [_scene()]
        report = build_diagnostic_report(frags, calib, scenes, 60.0)
        self.assertEqual(report['n_videos'], 2)
        self.assertEqual(report['n_raw_fragments'], 10)


if __name__ == '__main__':
    unittest.main()
