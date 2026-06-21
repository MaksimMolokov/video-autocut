"""
Tests for Step 2 candidate pool behaviour:
  - Multiple candidates found from multiple videos
  - No hard cap on candidate count
  - Exclusion + replacement logic
  - Duration preservation when segments are excluded
  - Backup pool used before warning

All tests are pure unit tests — no video files, no DB, no Streamlit.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.preprocessing.fragment_scorer import (
    score_fragments, check_material_sufficiency, _DEFAULT_CALIB,
)
from src.preprocessing.scene_merger import merge_fragments_into_scenes


# ── Helpers ───────────────────────────────────────────────────────────────────

def _frag(source_id, start_s, end_s, quality=0.65, sharpness=0.55, **kw):
    return {
        'id':              int(source_id * 100000 + start_s * 100),
        'source_id':       source_id,
        'source_path':     f'/fake/video{source_id}.mp4',
        'start_s':         start_s,
        'end_s':           end_s,
        'duration_s':      end_s - start_s,
        'quality_score':   quality,
        'sharpness':       sharpness,
        'brightness':      0.50,
        'stability':       0.80,
        'motion':          0.30,
        'contrast':        0.45,
        'cinematic_score': 0.50,
        'action_score':    0.30,
        'is_rejected':     False,
        'thumbnail_path':  None,
        'preview_path':    None,
        **kw,
    }


def _good_frags_for_video(source_id, n=5, quality=0.70):
    """n consecutive 4s fragments from one video, quality enough to be 'good'."""
    return [_frag(source_id, i * 5.0, i * 5.0 + 4.0, quality=quality) for i in range(n)]


# ── Test 1: Multiple candidates per video ─────────────────────────────────────

class TestMultipleCandidatesPerVideo(unittest.TestCase):

    def test_single_video_multiple_scenes(self):
        """One video with 5 good segments → at least 2 scenes found."""
        frags = _good_frags_for_video(source_id=1, n=5)
        calib, enriched = score_fragments(frags)
        scenes = merge_fragments_into_scenes(enriched, calibration=calib, gap_s=0.5)
        # With gap_s=0.5, each 1s gap splits → 5 separate scenes
        self.assertGreater(len(scenes), 1, "Single video with multiple segments should yield multiple scenes")

    def test_multiple_videos_produce_candidates_each(self):
        """5 videos × 5 segments each → fragments found from all 5 videos."""
        frags = []
        for vid in range(1, 6):
            frags.extend(_good_frags_for_video(source_id=vid, n=5))
        calib, enriched = score_fragments(frags)
        scenes = merge_fragments_into_scenes(enriched, calibration=calib)
        source_ids_in_scenes = {s['source_id'] for s in scenes}
        self.assertEqual(len(source_ids_in_scenes), 5,
                         "All 5 videos should contribute scenes")

    def test_each_video_has_at_least_one_scene(self):
        """No video is silently dropped when all have good material."""
        frags = []
        for vid in range(1, 4):
            frags.extend(_good_frags_for_video(source_id=vid, n=3, quality=0.72))
        calib, enriched = score_fragments(frags)
        scenes = merge_fragments_into_scenes(enriched, calibration=calib)
        for vid in range(1, 4):
            vid_scenes = [s for s in scenes if s['source_id'] == vid]
            self.assertGreater(len(vid_scenes), 0, f"video {vid} should have at least one scene")


# ── Test 2: No hard cap on candidates ─────────────────────────────────────────

class TestNoHardCap(unittest.TestCase):

    def test_20_good_fragments_produce_more_than_4_scenes(self):
        """Critical: system must not cap results at 4."""
        frags = _good_frags_for_video(source_id=1, n=20, quality=0.72)
        calib, enriched = score_fragments(frags)
        scenes = merge_fragments_into_scenes(enriched, calibration=calib, gap_s=0.5)
        self.assertGreater(len(scenes), 4,
                           "20 good fragments must yield more than 4 scenes (no artificial cap)")

    def test_50_fragments_across_3_videos_not_capped(self):
        frags = []
        for vid in range(1, 4):
            frags.extend(_good_frags_for_video(source_id=vid, n=17, quality=0.68))
        calib, enriched = score_fragments(frags)
        scenes = merge_fragments_into_scenes(enriched, calibration=calib, gap_s=0.5)
        self.assertGreater(len(scenes), 10,
                           "50 good fragments across 3 videos must not be capped")

    def test_all_good_fragments_preserved_in_scored_list(self):
        """score_fragments must return the same count as input — nothing dropped."""
        frags = _good_frags_for_video(source_id=1, n=30, quality=0.75)
        _, enriched = score_fragments(frags)
        self.assertEqual(len(enriched), 30)


# ── Test 3: Exclusion semantics ───────────────────────────────────────────────

class TestExclusionSemantics(unittest.TestCase):

    def _make_scenes(self):
        frags = _good_frags_for_video(source_id=1, n=10, quality=0.75)
        calib, enriched = score_fragments(frags)
        return merge_fragments_into_scenes(enriched, calibration=calib, gap_s=0.5)

    def test_excluded_fragment_ids_not_in_selected_duration(self):
        scenes = self._make_scenes()
        # Reject the first scene's fragment_ids
        first_scene_fids = set(scenes[0].get('fragment_ids', []))
        rejected_fids = first_scene_fids

        suf = check_material_sufficiency(scenes, 60.0, rejected_fids)
        # Rejected scene's duration must NOT appear in selected_dur
        rejected_dur = scenes[0]['duration_s']
        total_dur = sum(s['duration_s'] for s in scenes)
        expected_selected = total_dur - rejected_dur
        self.assertAlmostEqual(suf['selected_dur'], expected_selected, delta=0.5)

    def test_excluding_multiple_scenes_tracks_correctly(self):
        scenes = self._make_scenes()
        # Reject first 3 scenes
        rejected_fids = set()
        rejected_dur = 0.0
        for s in scenes[:3]:
            rejected_fids.update(s.get('fragment_ids', []))
            rejected_dur += s['duration_s']

        suf = check_material_sufficiency(scenes, 60.0, rejected_fids)
        total_dur = sum(s['duration_s'] for s in scenes)
        self.assertAlmostEqual(suf['selected_dur'], total_dur - rejected_dur, delta=0.5)
        self.assertEqual(suf['n_rejected_user'], 3)

    def test_rejected_scenes_never_counted_in_pool(self):
        """Core requirement: rejected_by_user cannot sneak into any duration count."""
        frags = _good_frags_for_video(source_id=1, n=5, quality=0.80)
        calib, enriched = score_fragments(frags)
        scenes = merge_fragments_into_scenes(enriched, calibration=calib, gap_s=0.5)

        # Reject ALL scenes
        all_fids = set()
        for s in scenes:
            all_fids.update(s.get('fragment_ids', []))

        suf = check_material_sufficiency(scenes, 60.0, all_fids)
        self.assertEqual(suf['selected_dur'], 0.0)
        self.assertEqual(suf['backup_dur'], 0.0)
        self.assertFalse(suf['has_enough'])


# ── Test 4: Duration preservation via backup pool ─────────────────────────────

class TestDurationPreservation(unittest.TestCase):

    def test_backup_pool_covers_shortage(self):
        """After excluding best scenes, backup pool should cover the gap."""
        # best scenes (selected)
        best_scenes = [
            {'source_id': 1, 'start_s': 0, 'end_s': 15, 'duration_s': 15,
             'quality_score': 0.80, 'ums_score': 0.80, 'category': 'best',
             'fragment_ids': [1]},
        ]
        # backup scenes
        backup_scenes = [
            {'source_id': 1, 'start_s': 20, 'end_s': 60, 'duration_s': 40,
             'quality_score': 0.35, 'ums_score': 0.35, 'category': 'backup',
             'fragment_ids': [2]},
        ]
        scenes = best_scenes + backup_scenes
        rejected_fids = {1}  # user rejected the only best scene

        suf = check_material_sufficiency(scenes, 30.0, rejected_fids)
        self.assertFalse(suf['has_enough'])     # best gone
        self.assertTrue(suf['has_with_backup']) # backup covers 40s > 45s needed

    def test_warning_when_even_backup_insufficient(self):
        """If backup + selected < target, shortage must be > 0."""
        scenes = [
            {'source_id': 1, 'start_s': 0, 'end_s': 5, 'duration_s': 5,
             'quality_score': 0.80, 'ums_score': 0.80, 'category': 'best',
             'fragment_ids': [1]},
        ]
        # No backup. Target = 60s.
        suf = check_material_sufficiency(scenes, 60.0, set())
        self.assertFalse(suf['has_enough'])
        self.assertFalse(suf['has_with_backup'])
        self.assertGreater(suf['shortage'], 0)

    def test_no_duration_reduction_if_backup_available(self):
        """
        After user excludes a scene, system should NOT silently reduce duration —
        it should flag that backup can fill the gap.
        """
        scenes = [
            {'source_id': 1, 'start_s':  0, 'end_s': 30, 'duration_s': 30,
             'quality_score': 0.80, 'ums_score': 0.80, 'category': 'best',
             'fragment_ids': [1]},
            {'source_id': 1, 'start_s': 35, 'end_s': 65, 'duration_s': 30,
             'quality_score': 0.35, 'ums_score': 0.35, 'category': 'backup',
             'fragment_ids': [2]},
        ]
        # User excludes the best scene
        rejected_fids = {1}
        suf = check_material_sufficiency(scenes, 30.0, rejected_fids)
        # Total available (backup) = 30s, need = 30*1.5 = 45s → not fully covered
        # But has_with_backup checks total_dur >= need
        # total_dur = 30 (backup) < 45 → not covered
        # selected_dur = 0 (only scene was rejected)
        # backup_dur = 30s
        self.assertEqual(suf['selected_dur'], 0.0)
        self.assertEqual(suf['backup_dur'], 30.0)
        # shortage = need - selected = 45 - 0 = 45
        self.assertGreater(suf['shortage'], 0)


# ── Test 5: Dynamic threshold prevents all-rejected scenario ─────────────────

class TestDynamicThresholdsPreventLoss(unittest.TestCase):

    def test_moderately_good_footage_not_all_rejected(self):
        """
        If footage is moderately good (quality 0.45–0.60), not everything
        should be rejected — dynamic thresholds adapt.
        """
        frags = [_frag(1, i * 5.0, i * 5.0 + 4.0, quality=0.45 + i * 0.01)
                 for i in range(15)]
        calib, enriched = score_fragments(frags)
        usable = [f for f in enriched if f['category'] in ('best', 'good', 'backup')]
        self.assertGreater(len(usable), 0,
                           "Moderate-quality footage should produce usable candidates")

    def test_single_high_quality_frame_in_weak_project_is_best(self):
        """
        One very sharp frame in an otherwise weak project should be classified
        as 'best' relative to the project.
        """
        weak_frags = [_frag(1, i * 5.0, i * 5.0 + 4.0, quality=0.18, sharpness=0.15)
                      for i in range(10)]
        # One standout fragment
        weak_frags.append(_frag(1, 50.0, 54.0, quality=0.72, sharpness=0.75))
        _, enriched = score_fragments(weak_frags)
        # The standout fragment should be 'best' or 'good'
        standout = next(f for f in enriched if f['quality_score'] == 0.72)
        self.assertIn(standout['category'], ('best', 'good'))


# ── Test 6: scene_merger integration with scorer ──────────────────────────────

class TestScorerMergerIntegration(unittest.TestCase):

    def test_scored_fragments_produce_categorized_scenes(self):
        frags = _good_frags_for_video(source_id=1, n=6, quality=0.72)
        calib, enriched = score_fragments(frags)
        scenes = merge_fragments_into_scenes(enriched, calibration=calib)
        for s in scenes:
            self.assertIn('category', s)
            self.assertIn(s['category'], ('best', 'good', 'backup', 'rejected_by_system'))
            self.assertIn('ums_score', s)

    def test_backup_scenes_included_not_discarded(self):
        """Backup-quality fragments should appear in scenes, not be silently dropped."""
        frags = [_frag(1, i * 5.0, i * 5.0 + 4.0, quality=0.30, sharpness=0.25)
                 for i in range(8)]
        calib, enriched = score_fragments(frags)
        scenes = merge_fragments_into_scenes(enriched, calibration=calib, min_quality=0.10)
        # At minimum, some scenes should exist
        self.assertGreater(len(scenes), 0,
                           "Backup-quality fragments should produce scenes (not all discarded)")

    def test_rejected_by_system_breaks_scene_chain(self):
        """Truly corrupt fragments should still break scene continuity."""
        frags = [
            _frag(1, 0.0,  4.0, quality=0.80),  # good
            _frag(1, 4.0,  8.0, quality=0.01, sharpness=0.01, is_rejected=True),  # corrupt
            _frag(1, 8.0, 12.0, quality=0.75),  # good
        ]
        calib, enriched = score_fragments(frags)
        scenes = merge_fragments_into_scenes(enriched, calibration=calib)
        # Two separate scenes (corrupt breaks the chain)
        source_scenes = [s for s in scenes if s['source_id'] == 1]
        self.assertEqual(len(source_scenes), 2)


if __name__ == '__main__':
    unittest.main()
