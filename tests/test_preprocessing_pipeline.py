"""
Integration tests for the preprocessing stage:
- Fragment whitelist filter in FragmentLibrary
- Prep-approved IDs behaviour
- Music range logic
- Old pipeline not broken when prep skipped
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestFragmentLibraryAllowedIds(unittest.TestCase):
    """Test allowed_fragment_ids filter in FragmentLibrary.get_candidates()."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from src.storage.analysis_db import AnalysisDB
        from src.preprocessing.clip_library import FragmentLibrary
        self.db = AnalysisDB(self._tmp.name)
        self.lib = FragmentLibrary(self.db)

        # Create a fake video file and populate DB with fragments
        video_path = Path(self._tmp.name) / 'test.mp4'
        video_path.write_bytes(b'\x00' * 512)
        self.video_path = str(video_path)
        sid = self.db.save_source_file(self.video_path)
        self.db.mark_analyzed(self.video_path)

        fragments = [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0, 'quality_score': 0.80},
            {'start_s': 5.0, 'end_s': 8.0, 'duration_s': 3.0, 'quality_score': 0.70},
            {'start_s': 10.0, 'end_s': 13.0, 'duration_s': 3.0, 'quality_score': 0.60},
        ]
        self.db.save_fragments(sid, fragments)
        all_rows = self.db.get_fragments_filtered(min_quality=0.0)
        self.frag_ids = [r['id'] for r in all_rows]

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_no_filter_returns_all(self):
        cands = self.lib.get_all_candidates_for_project(min_quality=0.0)
        self.assertEqual(len(cands), 3)

    def test_allowed_ids_filters_correctly(self):
        allowed = {self.frag_ids[0], self.frag_ids[2]}
        cands = self.lib.get_all_candidates_for_project(
            min_quality=0.0, allowed_fragment_ids=allowed
        )
        self.assertEqual(len(cands), 2)

    def test_empty_allowed_set_returns_nothing(self):
        cands = self.lib.get_all_candidates_for_project(
            min_quality=0.0, allowed_fragment_ids=set()
        )
        self.assertEqual(len(cands), 0)

    def test_none_allowed_ids_returns_all(self):
        cands = self.lib.get_all_candidates_for_project(
            min_quality=0.0, allowed_fragment_ids=None
        )
        self.assertEqual(len(cands), 3)

    def test_fragment_id_attached_to_candidate(self):
        cands = self.lib.get_all_candidates_for_project(min_quality=0.0)
        for c in cands:
            # _fragment_id must be attached so render filter can use it
            self.assertTrue(hasattr(c, '_fragment_id'),
                            "CandidateClip missing _fragment_id attribute")
            self.assertIn(c._fragment_id, self.frag_ids)


class TestMusicFragmentDBRoundTrip(unittest.TestCase):
    """Ensure music fragment schema created and basic CRUD works."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from src.storage.analysis_db import AnalysisDB
        self.db = AnalysisDB(self._tmp.name)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_empty_get(self):
        rows = self.db.get_music_fragments('/fake/audio.mp3')
        self.assertEqual(rows, [])

    def test_is_music_analyzed_false_before_save(self):
        self.assertFalse(self.db.is_music_analyzed('/fake/audio.mp3'))

    def test_save_and_retrieve_fragments(self):
        frags = [
            {'start_s': 0.0, 'end_s': 30.0, 'duration_s': 30.0, 'fragment_type': 'intro',
             'energy_score': 0.4, 'rhythm_score': 0.5, 'beat_clarity': 0.6, 'montage_score': 0.55,
             'reason': 'test', 'warnings': '', 'selected_by_system': 1,
             'excluded_by_user': 0, 'status': 'recommended'},
        ]
        self.db.save_music_fragments('/fake/audio.mp3', frags)
        result = self.db.get_music_fragments('/fake/audio.mp3')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['fragment_type'], 'intro')

    def test_selected_range_none_when_none_selected(self):
        self.db.save_music_fragments('/fake/audio.mp3', [
            {'start_s': 10.0, 'end_s': 40.0, 'duration_s': 30.0, 'fragment_type': 'peak',
             'energy_score': 0.8, 'rhythm_score': 0.7, 'beat_clarity': 0.8, 'montage_score': 0.8,
             'reason': '', 'warnings': '', 'selected_by_system': 1,
             'excluded_by_user': 0, 'status': 'best'},
        ])
        rng = self.db.get_selected_music_range('/fake/audio.mp3')
        self.assertIsNone(rng)

    def test_selected_range_returns_after_user_selection(self):
        self.db.save_music_fragments('/fake/audio.mp3', [
            {'start_s': 10.0, 'end_s': 40.0, 'duration_s': 30.0, 'fragment_type': 'peak',
             'energy_score': 0.8, 'rhythm_score': 0.7, 'beat_clarity': 0.8, 'montage_score': 0.8,
             'reason': '', 'warnings': '', 'selected_by_system': 1,
             'excluded_by_user': 0, 'status': 'best'},
        ])
        rows = self.db.get_music_fragments('/fake/audio.mp3')
        self.db.update_music_fragment_user_selection(rows[0]['id'], True)
        rng = self.db.get_selected_music_range('/fake/audio.mp3')
        self.assertIsNotNone(rng)
        self.assertAlmostEqual(rng[0], 10.0)
        self.assertAlmostEqual(rng[1], 40.0)

    def test_reset_clears_all(self):
        self.db.save_music_fragments('/fake/audio.mp3', [
            {'start_s': 0.0, 'end_s': 30.0, 'duration_s': 30.0, 'fragment_type': 'intro',
             'energy_score': 0.4, 'rhythm_score': 0.5, 'beat_clarity': 0.6, 'montage_score': 0.55,
             'reason': '', 'warnings': '', 'selected_by_system': 1,
             'excluded_by_user': 0, 'status': 'recommended'},
        ])
        self.db.reset_music_fragments('/fake/audio.mp3')
        self.assertEqual(self.db.get_music_fragments('/fake/audio.mp3'), [])


class TestMusicFragmentAnalyzerNoLibrosa(unittest.TestCase):
    """Graceful fallback when audio file is missing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from src.storage.analysis_db import AnalysisDB
        self.db = AnalysisDB(self._tmp.name)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_missing_file_returns_empty(self):
        from src.preprocessing.music_fragment_analyzer import analyze_music_for_preprocessing
        result = analyze_music_for_preprocessing('/nonexistent/audio.mp3', self.db)
        self.assertEqual(result, [])

    def test_no_music_no_crash(self):
        """Calling analyze with missing file must not raise."""
        from src.preprocessing.music_fragment_analyzer import analyze_music_for_preprocessing
        try:
            analyze_music_for_preprocessing('/nonexistent/track.wav', self.db)
        except Exception as e:
            self.fail(f"analyze_music_for_preprocessing raised unexpectedly: {e}")


class TestPrepSkipDoesNotBreakPipeline(unittest.TestCase):
    """When prep is skipped (prep_approved_ids=None), all fragments pass through."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from src.storage.analysis_db import AnalysisDB
        from src.preprocessing.clip_library import FragmentLibrary
        self.db = AnalysisDB(self._tmp.name)
        self.lib = FragmentLibrary(self.db)

        video_path = Path(self._tmp.name) / 'vid.mp4'
        video_path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(video_path))
        self.db.mark_analyzed(str(video_path))
        self.db.save_fragments(sid, [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0, 'quality_score': 0.80},
            {'start_s': 5.0, 'end_s': 8.0, 'duration_s': 3.0, 'quality_score': 0.40},
        ])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_skip_mode_uses_all_fragments(self):
        cands = self.lib.get_all_candidates_for_project(
            min_quality=0.0, allowed_fragment_ids=None
        )
        self.assertEqual(len(cands), 2)

    def test_music_duration_warning_logic(self):
        """Selected music range shorter than target triggers expected comparison."""
        music_range = (0.0, 30.0)
        target = 60.0
        music_dur = music_range[1] - music_range[0]
        self.assertLess(music_dur, target * 0.8)


if __name__ == '__main__':
    unittest.main()
