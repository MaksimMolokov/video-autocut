"""Tests for MusicFragmentAnalyzer: metric helpers, DB integration, edge cases."""

import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class _MockBeatPoint:
    def __init__(self, time, strength=0.7):
        self.time = time
        self.strength = strength


class _MockStructureSection:
    def __init__(self, start, end, section_type, confidence=0.9):
        self.start_time = start
        self.end_time = end
        self.duration = end - start
        self.section_type = section_type
        self.confidence = confidence


class _MockAnalysis:
    def __init__(self):
        self.duration = 180.0
        self.tempo = 128.0
        self.energy_curve = [float(i % 10) / 10 for i in range(200)]
        self.beat_times = [i * 0.47 for i in range(380)]
        self.beat_points = [_MockBeatPoint(t, 0.7 + (i % 3) * 0.1) for i, t in enumerate(self.beat_times)]
        self.peak_times = [60.0, 120.0]
        self.drop_times = [55.0, 115.0]
        self.structure_sections = []
        self.energy_sections = []


class TestMusicFragmentAnalyzerHelpers(unittest.TestCase):

    def setUp(self):
        from src.preprocessing.music_fragment_analyzer import (
            _section_energy, _section_rhythm, _section_beat_clarity, _montage_score, _reason
        )
        self._energy  = _section_energy
        self._rhythm  = _section_rhythm
        self._beat_cl = _section_beat_clarity
        self._score   = _montage_score
        self._reason  = _reason
        self.analysis = _MockAnalysis()

    def test_section_energy_mid_section(self):
        # Non-trivial section should give a non-zero energy
        e = self._energy(0.0, 60.0, self.analysis)
        self.assertGreater(e, 0.0)
        self.assertLessEqual(e, 1.0)

    def test_section_rhythm_dense_beats(self):
        r = self._rhythm(0.0, 60.0, self.analysis)
        # 128 BPM → ~2.13 beats/s → normalised to 0.71
        self.assertGreater(r, 0.5)
        self.assertLessEqual(r, 1.0)

    def test_section_rhythm_empty_returns_zero(self):
        empty = _MockAnalysis()
        empty.beat_times = []
        r = self._rhythm(0.0, 30.0, empty)
        self.assertEqual(r, 0.0)

    def test_beat_clarity_normalised(self):
        bc = self._beat_cl(0.0, 60.0, self.analysis)
        self.assertGreaterEqual(bc, 0.0)
        self.assertLessEqual(bc, 1.0)

    def test_montage_score_peak_bonus(self):
        # Section containing a peak_time should get a bonus
        class FakeSection:
            start_time = 55.0
            end_time   = 75.0
            duration   = 20.0
        score_peak = self._score('calm', 0.5, 0.5, 0.5, FakeSection(), self.analysis)

        class FarSection:
            start_time = 0.0
            end_time   = 20.0
            duration   = 20.0
        score_far = self._score('calm', 0.5, 0.5, 0.5, FarSection(), self.analysis)
        self.assertGreater(score_peak, score_far)

    def test_montage_score_type_bonus_drop_gt_calm(self):
        class Sec:
            start_time = 0.0
            end_time   = 30.0
            duration   = 30.0
        a = _MockAnalysis()
        a.peak_times = []
        score_drop = self._score('drop', 0.5, 0.5, 0.5, Sec(), a)
        score_calm = self._score('calm', 0.5, 0.5, 0.5, Sec(), a)
        self.assertGreater(score_drop, score_calm)

    def test_montage_score_bounds(self):
        class Sec:
            start_time = 0.0
            end_time   = 30.0
            duration   = 30.0
        for ftype in ('intro', 'buildup', 'drop', 'peak', 'calm', 'outro', 'loopable'):
            for e, r, b in [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.5, 0.5)]:
                s = self._score(ftype, e, r, b, Sec(), self.analysis)
                self.assertGreaterEqual(s, 0.0, f"negative score for {ftype}")
                self.assertLessEqual(s, 1.0, f"score > 1 for {ftype}")

    def test_reason_returns_string(self):
        for ftype in ('intro', 'buildup', 'drop', 'peak', 'calm', 'outro', 'loopable'):
            r = self._reason(ftype, 0.5, 0.5, 0.5)
            self.assertIsInstance(r, str)
            self.assertGreater(len(r), 0)


class TestAnalysisToDicts(unittest.TestCase):
    """Test _analysis_to_fragments with mocked AudioAnalysis."""

    def _make_section(self, start, end, name):
        class _SectionType:
            pass
        sec = _MockStructureSection(start, end, type('SType', (), {'name': name})())
        return sec

    def test_structure_sections_converted(self):
        from src.preprocessing.music_fragment_analyzer import _analysis_to_fragments
        analysis = _MockAnalysis()
        analysis.structure_sections = [
            self._make_section(0.0, 25.0, 'INTRO'),
            self._make_section(25.0, 90.0, 'VERSE'),
            self._make_section(90.0, 130.0, 'CHORUS'),
            self._make_section(130.0, 180.0, 'OUTRO'),
        ]
        fragments = _analysis_to_fragments(analysis)
        self.assertGreater(len(fragments), 0)
        types = {f['fragment_type'] for f in fragments}
        self.assertIn('intro', types)
        self.assertIn('peak', types)   # CHORUS → peak

    def test_short_sections_skipped(self):
        from src.preprocessing.music_fragment_analyzer import _analysis_to_fragments
        analysis = _MockAnalysis()
        analysis.structure_sections = [
            self._make_section(0.0, 3.0, 'INTRO'),   # < 5s → skipped
            self._make_section(3.0, 60.0, 'VERSE'),  # ok
        ]
        fragments = _analysis_to_fragments(analysis)
        # Only the VERSE section should appear
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0]['fragment_type'], 'calm')

    def test_best_fragment_tagged(self):
        from src.preprocessing.music_fragment_analyzer import _analysis_to_fragments
        analysis = _MockAnalysis()
        analysis.structure_sections = [
            self._make_section(0.0, 60.0, 'INTRO'),
            self._make_section(60.0, 120.0, 'CHORUS'),
        ]
        fragments = _analysis_to_fragments(analysis)
        statuses = [f['status'] for f in fragments]
        self.assertEqual(statuses.count('best'), 1)

    def test_all_required_keys_present(self):
        from src.preprocessing.music_fragment_analyzer import _analysis_to_fragments
        analysis = _MockAnalysis()
        analysis.structure_sections = [self._make_section(0.0, 60.0, 'INTRO')]
        frags = _analysis_to_fragments(analysis)
        required = {
            'start_s', 'end_s', 'duration_s', 'fragment_type',
            'energy_score', 'rhythm_score', 'beat_clarity', 'montage_score',
            'reason', 'warnings', 'selected_by_system', 'excluded_by_user', 'status',
        }
        for key in required:
            self.assertIn(key, frags[0], f"Missing key: {key}")

    def test_fallback_to_energy_sections(self):
        from src.preprocessing.music_fragment_analyzer import _analysis_to_fragments
        try:
            from src.music_sync.models import EnergyLevel, EnergySection
        except ImportError:
            self.skipTest("music_sync not available")

        analysis = _MockAnalysis()
        analysis.structure_sections = []
        analysis.energy_sections = [
            EnergySection(0.0, 60.0, EnergyLevel.LOW, 0.2),
            EnergySection(60.0, 120.0, EnergyLevel.HIGH, 0.8),
        ]
        fragments = _analysis_to_fragments(analysis)
        self.assertGreater(len(fragments), 0)


class TestMusicFragmentDB(unittest.TestCase):
    """Test DB save/retrieve round-trip for music fragments."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from src.storage.analysis_db import AnalysisDB
        self.db = AnalysisDB(self._tmp.name)
        self.audio_path = '/fake/test_track.mp3'

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def _sample_fragments(self):
        return [
            {
                'start_s': 0.0, 'end_s': 25.0, 'duration_s': 25.0,
                'fragment_type': 'intro', 'energy_score': 0.4,
                'rhythm_score': 0.5, 'beat_clarity': 0.6, 'montage_score': 0.55,
                'reason': 'хорошее вступление', 'warnings': '',
                'selected_by_system': 1, 'excluded_by_user': 0, 'status': 'recommended',
            },
            {
                'start_s': 60.0, 'end_s': 90.0, 'duration_s': 30.0,
                'fragment_type': 'peak', 'energy_score': 0.9,
                'rhythm_score': 0.8, 'beat_clarity': 0.85, 'montage_score': 0.87,
                'reason': 'кульминация', 'warnings': '',
                'selected_by_system': 1, 'excluded_by_user': 0, 'status': 'best',
            },
        ]

    def test_save_and_retrieve(self):
        frags = self._sample_fragments()
        self.db.save_music_fragments(self.audio_path, frags)
        rows = self.db.get_music_fragments(self.audio_path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['fragment_type'], 'intro')
        self.assertEqual(rows[1]['fragment_type'], 'peak')

    def test_is_music_analyzed_false_for_new_file(self):
        self.assertFalse(self.db.is_music_analyzed(self.audio_path))

    def test_update_user_selection(self):
        frags = self._sample_fragments()
        self.db.save_music_fragments(self.audio_path, frags)
        rows = self.db.get_music_fragments(self.audio_path)
        fid = rows[1]['id']  # peak fragment
        self.db.update_music_fragment_user_selection(fid, True)
        selected_range = self.db.get_selected_music_range(self.audio_path)
        self.assertIsNotNone(selected_range)
        self.assertAlmostEqual(selected_range[0], 60.0)
        self.assertAlmostEqual(selected_range[1], 90.0)

    def test_exclude_hides_fragment(self):
        frags = self._sample_fragments()
        self.db.save_music_fragments(self.audio_path, frags)
        rows = self.db.get_music_fragments(self.audio_path)
        fid = rows[0]['id']
        self.db.update_music_fragment_user_selection(fid, False, excluded_by_user=True)
        rows2 = self.db.get_music_fragments(self.audio_path)
        self.assertEqual(len(rows2), 1)  # excluded one hidden
        self.assertEqual(rows2[0]['fragment_type'], 'peak')

    def test_reset_clears_fragments(self):
        self.db.save_music_fragments(self.audio_path, self._sample_fragments())
        self.db.reset_music_fragments(self.audio_path)
        rows = self.db.get_music_fragments(self.audio_path)
        self.assertEqual(len(rows), 0)

    def test_get_selected_music_range_returns_none_when_none_selected(self):
        self.db.save_music_fragments(self.audio_path, self._sample_fragments())
        rng = self.db.get_selected_music_range(self.audio_path)
        self.assertIsNone(rng)


if __name__ == '__main__':
    unittest.main()
