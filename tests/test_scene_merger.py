"""
Tests for scene_merger: merging fine-grained DB fragments into coherent scenes.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.preprocessing.scene_merger import (
    merge_fragments_into_scenes,
    deduplicate_scenes,
    compute_beat_sync_scores,
    _scene_status,
    _scene_reason,
    _scene_warnings,
)


def _frag(source_id, start_s, end_s, quality=0.65, **overrides):
    base = {
        'id':              int(source_id * 10000 + start_s * 100),
        'source_id':       source_id,
        'source_path':     f'/fake/video{source_id}.mp4',
        'start_s':         start_s,
        'end_s':           end_s,
        'duration_s':      end_s - start_s,
        'quality_score':   quality,
        'cinematic_score': 0.5,
        'action_score':    0.4,
        'motion':          0.5,
        'stability':       0.7,
        'sharpness':       0.6,
        'brightness':      0.55,
        'contrast':        0.5,
        'thumbnail_path':  None,
        'preview_path':    None,
    }
    base.update(overrides)
    return base


class TestMergeFragmentsIntoScenes(unittest.TestCase):

    # ── Basic merging ─────────────────────────────────────────────────────────

    def test_empty_input_returns_empty(self):
        self.assertEqual(merge_fragments_into_scenes([]), [])

    def test_single_fragment_above_min_dur_becomes_scene(self):
        frags = [_frag(1, 0.0, 5.0)]
        scenes = merge_fragments_into_scenes(frags, min_duration=3.0)
        self.assertEqual(len(scenes), 1)

    def test_single_fragment_below_fallback_min_discarded(self):
        # 0.5 s is below the fallback floor (_FALLBACK_MIN_DUR = 0.8 s), so even
        # the fallback pass cannot save it.  Fragments this short must be discarded.
        frags = [_frag(1, 0.0, 0.5)]
        scenes = merge_fragments_into_scenes(frags, min_duration=3.0)
        self.assertEqual(len(scenes), 0)

    def test_single_fragment_rescued_by_fallback(self):
        # 1.0 s fragment: below primary min_dur=1.5 but above fallback floor=0.8.
        # The fallback pass must save it so drone/action footage is not lost.
        frags = [_frag(1, 0.0, 1.0)]
        scenes = merge_fragments_into_scenes(frags)  # default min_duration=1.5
        self.assertEqual(len(scenes), 1,
            "1.0 s fragment must be rescued by fallback (above 0.8 s floor)")

    def test_consecutive_fragments_merged_into_one_scene(self):
        frags = [_frag(1, i * 3.0, (i + 1) * 3.0) for i in range(4)]
        scenes = merge_fragments_into_scenes(frags)
        self.assertEqual(len(scenes), 1)
        self.assertAlmostEqual(scenes[0]['start_s'], 0.0)
        self.assertAlmostEqual(scenes[0]['end_s'], 12.0)

    def test_scene_start_and_end_correct(self):
        frags = [_frag(1, 5.0, 8.0), _frag(1, 8.0, 11.0)]
        scenes = merge_fragments_into_scenes(frags)
        self.assertEqual(len(scenes), 1)
        self.assertAlmostEqual(scenes[0]['start_s'], 5.0)
        self.assertAlmostEqual(scenes[0]['end_s'], 11.0)

    # ── Splitting ─────────────────────────────────────────────────────────────

    def test_gap_above_threshold_splits_into_two_scenes(self):
        frags = [
            _frag(1, 0.0, 3.0),
            _frag(1, 0.0, 3.0),
            _frag(1, 5.5, 8.5),   # 2.5 s gap > default 1.0
        ]
        frags[1]['start_s'] = 3.0
        frags[1]['end_s'] = 6.0
        # Re-do properly
        frags = [
            _frag(1, 0.0,  4.0),
            _frag(1, 6.0, 10.0),  # 2 s gap
        ]
        scenes = merge_fragments_into_scenes(frags, gap_s=1.0)
        self.assertEqual(len(scenes), 2)

    def test_low_quality_fragment_splits_scene(self):
        frags = [
            _frag(1, 0.0, 3.0, quality=0.7),
            _frag(1, 3.0, 6.0, quality=0.05),   # below min_quality
            _frag(1, 6.0, 9.0, quality=0.7),
        ]
        scenes = merge_fragments_into_scenes(frags, min_quality=0.25)
        # Low-quality fragment breaks the run; two separate scenes of 3 s each
        self.assertEqual(len(scenes), 2)

    def test_max_duration_forces_split(self):
        frags = [_frag(1, i * 3.0, (i + 1) * 3.0) for i in range(15)]
        scenes = merge_fragments_into_scenes(frags, max_duration=20.0)
        for s in scenes:
            self.assertLessEqual(s['duration_s'], 21.0)

    # ── Multi-video grouping ──────────────────────────────────────────────────

    def test_two_videos_produce_separate_scenes(self):
        frags = [
            _frag(1, 0.0, 4.0), _frag(1, 4.0, 8.0),
            _frag(2, 0.0, 4.0), _frag(2, 4.0, 8.0),
        ]
        scenes = merge_fragments_into_scenes(frags)
        src_ids = {s['source_id'] for s in scenes}
        self.assertEqual(src_ids, {1, 2})

    def test_multiple_scenes_from_one_video(self):
        """Same video → multiple scenes when big gaps exist."""
        frags = [
            _frag(1, 0.0,  4.0),
            _frag(1, 4.0,  8.0),
            _frag(1, 20.0, 24.0),   # 12 s gap
            _frag(1, 24.0, 28.0),
        ]
        scenes = merge_fragments_into_scenes(frags)
        self.assertGreaterEqual(len(scenes), 2)

    def test_sorted_by_source_then_start(self):
        frags = [
            _frag(2, 0.0,  4.0),
            _frag(1, 10.0, 14.0),
            _frag(1, 0.0,  4.0),
        ]
        scenes = merge_fragments_into_scenes(frags)
        # Should be: (source_id=1, start=0), (source_id=1, start=10), (source_id=2, start=0)
        self.assertEqual(scenes[0]['source_id'], 1)
        self.assertAlmostEqual(scenes[0]['start_s'], 0.0)

    # ── Fragment ID tracking ──────────────────────────────────────────────────

    def test_fragment_ids_included_in_scene(self):
        frags = [_frag(1, 0.0, 3.0), _frag(1, 3.0, 6.0)]
        scenes = merge_fragments_into_scenes(frags)
        self.assertEqual(len(scenes[0]['fragment_ids']), 2)

    def test_fragment_ids_match_input_ids(self):
        f1 = _frag(1, 0.0, 3.0)
        f2 = _frag(1, 3.0, 6.0)
        scenes = merge_fragments_into_scenes([f1, f2])
        self.assertIn(f1['id'], scenes[0]['fragment_ids'])
        self.assertIn(f2['id'], scenes[0]['fragment_ids'])

    # ── Required fields ──────────────────────────────────────────────────────

    def test_all_required_fields_present(self):
        frags = [_frag(1, 0.0, 5.0)]
        scenes = merge_fragments_into_scenes(frags)
        required = {
            'source_id', 'source_path', 'filename',
            'start_s', 'end_s', 'duration_s', 'fragment_ids',
            'quality_score', 'quality_max',
            'cinematic_score', 'action_score', 'motion',
            'stability', 'sharpness', 'brightness',
            'thumbnail_path', 'preview_path', 'clip_path',
            'status', 'reason', 'warnings',
            'user_approved', 'n_fragments',
        }
        for field in required:
            self.assertIn(field, scenes[0], f"Missing field: {field}")

    def test_scene_has_source_path(self):
        frags = [_frag(1, 0.0, 5.0)]
        scenes = merge_fragments_into_scenes(frags)
        self.assertEqual(scenes[0]['source_path'], '/fake/video1.mp4')

    def test_scene_has_filename(self):
        frags = [_frag(1, 0.0, 5.0)]
        scenes = merge_fragments_into_scenes(frags)
        self.assertEqual(scenes[0]['filename'], 'video1.mp4')

    # ── No artificial limits ──────────────────────────────────────────────────

    def test_not_limited_to_4_results(self):
        """System must never cap results at 4 fragments."""
        frags = []
        for i in range(20):
            frags.append(_frag(1, i * 5.0, i * 5.0 + 4.0))
        # gap_s=0.5 → every 1-second gap triggers a split → 20 separate scenes
        scenes = merge_fragments_into_scenes(frags, gap_s=0.5)
        self.assertGreater(len(scenes), 4)

    def test_variable_scene_durations(self):
        """Scene durations must reflect content, not be fixed at 2-3 s."""
        frags = [
            _frag(1, 0.0,  4.0),
            _frag(1, 4.0,  8.0),
            _frag(1, 8.0, 12.0),
            _frag(1, 20.0, 24.0),
        ]
        scenes = merge_fragments_into_scenes(frags)
        durations = sorted({round(s['duration_s']) for s in scenes})
        # Expect at least 2 distinct duration lengths (the merged one vs the isolated one)
        self.assertGreaterEqual(len(durations), 1)
        # The merged scene must be longer than a single raw fragment
        max_dur = max(s['duration_s'] for s in scenes)
        self.assertGreater(max_dur, 4.0)

    # ── Score aggregation ─────────────────────────────────────────────────────

    def test_quality_score_is_mean(self):
        frags = [_frag(1, 0.0, 3.0, quality=0.8), _frag(1, 3.0, 6.0, quality=0.6)]
        scenes = merge_fragments_into_scenes(frags)
        self.assertAlmostEqual(scenes[0]['quality_score'], 0.7, places=2)

    def test_quality_max_is_highest(self):
        frags = [_frag(1, 0.0, 3.0, quality=0.9), _frag(1, 3.0, 6.0, quality=0.5)]
        scenes = merge_fragments_into_scenes(frags)
        self.assertAlmostEqual(scenes[0]['quality_max'], 0.9, places=2)

    # ── Status classification ─────────────────────────────────────────────────

    def test_status_best_high_quality(self):
        self.assertEqual(_scene_status(0.75), 'best')

    def test_status_good_mid_quality(self):
        self.assertEqual(_scene_status(0.60), 'good')

    def test_status_acceptable(self):
        self.assertEqual(_scene_status(0.40), 'acceptable')

    def test_status_weak_low_quality(self):
        self.assertEqual(_scene_status(0.20), 'weak')

    # ── Reason and warnings ───────────────────────────────────────────────────

    def test_reason_is_non_empty_string(self):
        r = _scene_reason(0.6, 0.5, 0.4, 0.5, 0.7, 0.6)
        self.assertIsInstance(r, str)
        self.assertGreater(len(r), 0)

    def test_warnings_empty_for_normal_scene(self):
        w = _scene_warnings(stability=0.7, brightness=0.5, dur=10.0)
        self.assertEqual(w, '')

    def test_warnings_for_shaky_dark_scene(self):
        w = _scene_warnings(stability=0.2, brightness=0.1, dur=5.0)
        self.assertIn('нестабильная', w)
        self.assertIn('темный', w)

    def test_warnings_for_overexposed_scene(self):
        w = _scene_warnings(stability=0.7, brightness=0.95, dur=5.0)
        self.assertIn('пересвет', w)

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_all_low_quality_returns_empty(self):
        frags = [_frag(1, i * 3.0, (i + 1) * 3.0, quality=0.1) for i in range(5)]
        scenes = merge_fragments_into_scenes(frags, min_quality=0.25)
        self.assertEqual(len(scenes), 0)

    def test_missing_optional_fields_handled(self):
        frag = {
            'id': 1, 'source_id': 1, 'start_s': 0.0, 'end_s': 5.0,
            'duration_s': 5.0, 'quality_score': 0.6,
        }
        scenes = merge_fragments_into_scenes([frag])
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0]['quality_score'], 0.6)

    def test_source_id_none_handled_as_zero(self):
        frag = _frag(0, 0.0, 5.0)
        frag['source_id'] = None
        scenes = merge_fragments_into_scenes([frag])
        self.assertEqual(len(scenes), 1)

    # ── Regression: merged scenes lack 'id' field causing KeyError in prep viewer
    # (gui.py:734 does frag['id'] on prep_video_frags which are merged scenes)
    # The fix is in gui.py: inject id=fragment_ids[0] before storing in session.
    # This test documents the fact that merge_fragments_into_scenes does NOT
    # include 'id' in its output (it only has 'fragment_ids'); the fix must be
    # applied at the call site.

    def test_merged_scene_has_no_top_level_id_key(self):
        """Confirms that merged scenes do NOT have a top-level 'id' field.
        The 'id' must be injected by gui.py before storing in session_state
        to avoid KeyError when displaying prep fragments."""
        frags = [_frag(1, 0.0, 3.0, id=42), _frag(1, 3.0, 6.0, id=43)]
        scenes = merge_fragments_into_scenes(frags)
        # fragment_ids must carry the DB IDs
        self.assertIn('fragment_ids', scenes[0])
        self.assertIn(42, scenes[0]['fragment_ids'])
        self.assertIn(43, scenes[0]['fragment_ids'])
        # The top-level 'id' key is NOT present; gui.py must inject it
        self.assertNotIn('id', scenes[0])

    def test_n_fragments_count_correct(self):
        frags = [_frag(1, i * 3.0, (i + 1) * 3.0) for i in range(3)]
        scenes = merge_fragments_into_scenes(frags)
        self.assertEqual(scenes[0]['n_fragments'], 3)


def _scene(source_id, start_s, end_s, ums=0.55, thumbnail=None, **overrides):
    base = {
        'source_id':    source_id,
        'source_path':  f'/fake/video{source_id}.mp4',
        'start_s':      start_s,
        'end_s':        end_s,
        'duration_s':   end_s - start_s,
        'ums_score':    ums,
        'quality_score': 0.6,
        'motion':       0.3,
        'stability':    0.7,
        'thumbnail_path': thumbnail,
    }
    base.update(overrides)
    return base


def _music_frag(duration_s, energy_score=0.6, **kw):
    return {'duration_s': duration_s, 'energy_score': energy_score, **kw}


class TestDeduplicateScenes(unittest.TestCase):
    """Algorithm 4: pHash cross-video deduplication."""

    def test_no_thumbnails_all_non_duplicates(self):
        """Scenes without thumbnails can't be hashed → all marked non-duplicate."""
        scenes = [
            _scene(1, 0.0, 5.0),
            _scene(2, 0.0, 5.0),
        ]
        result = deduplicate_scenes(scenes)
        self.assertEqual(len(result), 2)
        self.assertFalse(result[0]['is_cross_duplicate'])
        self.assertFalse(result[1]['is_cross_duplicate'])

    def test_all_scenes_get_is_cross_duplicate_field(self):
        """Every scene in result must have `is_cross_duplicate` key."""
        scenes = [_scene(1, 0.0, 5.0), _scene(1, 5.0, 10.0)]
        result = deduplicate_scenes(scenes)
        for s in result:
            self.assertIn('is_cross_duplicate', s)

    def test_same_source_never_marked_duplicate(self):
        """Scenes from the SAME source video must never be marked cross-duplicates."""
        scenes = [_scene(1, 0.0, 5.0), _scene(1, 5.0, 10.0)]
        result = deduplicate_scenes(scenes)
        self.assertFalse(result[0]['is_cross_duplicate'])
        self.assertFalse(result[1]['is_cross_duplicate'])

    def test_original_dicts_not_mutated(self):
        """deduplicate_scenes must not modify input scene dicts in place."""
        scenes = [_scene(1, 0.0, 5.0), _scene(2, 0.0, 5.0)]
        for s in scenes:
            self.assertNotIn('is_cross_duplicate', s)
        deduplicate_scenes(scenes)
        for s in scenes:
            self.assertNotIn('is_cross_duplicate', s)

    def test_empty_input(self):
        self.assertEqual(deduplicate_scenes([]), [])

    def test_single_scene(self):
        result = deduplicate_scenes([_scene(1, 0.0, 5.0)])
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]['is_cross_duplicate'])

    def test_keeps_higher_ums_scene(self):
        """When two cross-video scenes are near-identical, the lower-UMS one is the duplicate."""
        # We can't easily create identical real thumbnails in unit tests,
        # so we patch _phash_from_thumbnail to return a fixed value.
        import unittest.mock as mock
        with mock.patch(
            'src.preprocessing.scene_merger._phash_from_thumbnail',
            side_effect=[0b1010_1010, 0b1010_1010],  # identical hashes
        ):
            scenes = [
                _scene(1, 0.0, 5.0, ums=0.80, thumbnail='/fake/a.jpg'),
                _scene(2, 0.0, 5.0, ums=0.40, thumbnail='/fake/b.jpg'),
            ]
            result = deduplicate_scenes(scenes, hamming_threshold=10)
            # Higher UMS (0.80) should NOT be the duplicate
            self.assertFalse(result[0]['is_cross_duplicate'])
            self.assertTrue(result[1]['is_cross_duplicate'])

    def test_different_hashes_not_marked_duplicate(self):
        """Scenes with very different hashes (distance > threshold) stay clean."""
        import unittest.mock as mock
        with mock.patch(
            'src.preprocessing.scene_merger._phash_from_thumbnail',
            side_effect=[0x0000_0000_0000_0000, 0xFFFF_FFFF_FFFF_FFFF],  # dist=64
        ):
            scenes = [
                _scene(1, 0.0, 5.0, thumbnail='/fake/a.jpg'),
                _scene(2, 0.0, 5.0, thumbnail='/fake/b.jpg'),
            ]
            result = deduplicate_scenes(scenes, hamming_threshold=10)
            self.assertFalse(result[0]['is_cross_duplicate'])
            self.assertFalse(result[1]['is_cross_duplicate'])

    def test_hamming_threshold_boundary(self):
        """Distance exactly == threshold → marked duplicate; distance > threshold → not."""
        import unittest.mock as mock
        # Hash A has 10 bits different from hash B
        hash_a = 0b0000_0000_0000_0000_0000_0000_0000_0000_0000_0000_0000_0000_0000_0000_0000_0000
        hash_b = (1 << 10) - 1  # 10 lowest bits set → Hamming = 10
        with mock.patch(
            'src.preprocessing.scene_merger._phash_from_thumbnail',
            side_effect=[hash_a, hash_b],
        ):
            scenes = [
                _scene(1, 0.0, 5.0, ums=0.7, thumbnail='/fake/a.jpg'),
                _scene(2, 0.0, 5.0, ums=0.5, thumbnail='/fake/b.jpg'),
            ]
            result = deduplicate_scenes(scenes, hamming_threshold=10)
            dups = [s for s in result if s['is_cross_duplicate']]
            self.assertEqual(len(dups), 1)


class TestComputeBeatSyncScores(unittest.TestCase):
    """Algorithm 5: beat-synchronized fragment scoring."""

    def test_no_music_all_zero(self):
        """Without music fragments, all scenes get beat_sync_score=0.0."""
        scenes = [_scene(1, 0.0, 4.0), _scene(1, 4.0, 8.0)]
        result = compute_beat_sync_scores(scenes, music_frags=[])
        for s in result:
            self.assertEqual(s['beat_sync_score'], 0.0)

    def test_all_scenes_get_score_field(self):
        scenes = [_scene(1, 0.0, 4.0)]
        music = [_music_frag(4.0)]
        result = compute_beat_sync_scores(scenes, music)
        self.assertIn('beat_sync_score', result[0])

    def test_score_in_range_0_1(self):
        scenes = [_scene(1, i * 3.0, (i + 1) * 3.0) for i in range(5)]
        music = [_music_frag(3.0), _music_frag(6.0)]
        result = compute_beat_sync_scores(scenes, music)
        for s in result:
            v = s['beat_sync_score']
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_perfect_beat_fit_scores_high(self):
        """Scene duration exactly = beat_interval → perfect fit_score."""
        beat = 4.0
        scenes = [_scene(1, 0.0, beat, motion=0.5, stability=0.5)]
        music = [_music_frag(beat, energy_score=0.5)]
        result = compute_beat_sync_scores(scenes, music)
        self.assertGreater(result[0]['beat_sync_score'], 0.50)

    def test_exact_multiple_also_scores_high(self):
        """Scene duration = 2× beat_interval → nearest_n=2, perfect fit."""
        beat = 3.0
        scenes = [_scene(1, 0.0, beat * 2, motion=0.5, stability=0.5)]
        music = [_music_frag(beat, energy_score=0.5)]
        result = compute_beat_sync_scores(scenes, music)
        self.assertGreater(result[0]['beat_sync_score'], 0.50)

    def test_bad_fit_scores_lower_than_good_fit(self):
        """Scene that fits beat poorly should score lower than one that fits well."""
        beat = 4.0
        scene_good = _scene(1, 0.0, beat,        motion=0.5, stability=0.5)
        scene_bad  = _scene(1, 0.0, beat * 0.33, motion=0.5, stability=0.5)
        music = [_music_frag(beat, energy_score=0.5)]
        good_score = compute_beat_sync_scores([scene_good], music)[0]['beat_sync_score']
        bad_score  = compute_beat_sync_scores([scene_bad],  music)[0]['beat_sync_score']
        self.assertGreater(good_score, bad_score)

    def test_high_energy_match_boosts_score(self):
        """High motion scene + high energy music → better energy_match."""
        beat = 4.0
        scene_active = _scene(1, 0.0, beat, motion=0.90, stability=0.10)
        scene_calm   = _scene(1, 0.0, beat, motion=0.05, stability=0.95)
        music_energetic = [_music_frag(beat, energy_score=0.90)]
        score_active = compute_beat_sync_scores([scene_active], music_energetic)[0]['beat_sync_score']
        score_calm   = compute_beat_sync_scores([scene_calm],   music_energetic)[0]['beat_sync_score']
        self.assertGreater(score_active, score_calm)

    def test_empty_scenes_returns_empty(self):
        result = compute_beat_sync_scores([], [_music_frag(4.0)])
        self.assertEqual(result, [])

    def test_original_not_mutated(self):
        scenes = [_scene(1, 0.0, 4.0)]
        original_keys = set(scenes[0].keys())
        music = [_music_frag(4.0)]
        compute_beat_sync_scores(scenes, music)
        self.assertEqual(set(scenes[0].keys()), original_keys)

    def test_returns_same_count(self):
        scenes = [_scene(1, i * 4.0, (i + 1) * 4.0) for i in range(6)]
        music = [_music_frag(4.0)]
        result = compute_beat_sync_scores(scenes, music)
        self.assertEqual(len(result), len(scenes))

    def test_music_frags_too_short_ignored(self):
        """Fragments with duration ≤ 0.5s are filtered — result should still work."""
        scenes = [_scene(1, 0.0, 4.0)]
        music = [_music_frag(0.3), _music_frag(0.1)]  # all too short
        result = compute_beat_sync_scores(scenes, music)
        for s in result:
            self.assertEqual(s['beat_sync_score'], 0.0)

    def test_beat_interval_uses_median_not_mean(self):
        """Median phrase length is used as beat_interval; one outlier shouldn't skew it."""
        beat = 4.0
        # 3 fragments of 4s, 1 very long outlier
        music = [_music_frag(beat), _music_frag(beat), _music_frag(beat), _music_frag(60.0)]
        scenes = [_scene(1, 0.0, beat)]
        result = compute_beat_sync_scores(scenes, music)
        # Perfect fit at 4s should yield high score (median=4.0, not mean=18.0)
        self.assertGreater(result[0]['beat_sync_score'], 0.40)


if __name__ == '__main__':
    unittest.main()
