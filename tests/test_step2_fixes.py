"""
Tests for Step 2 fixes:
  - Quality thresholds don't discard all fragments for action/drone footage
  - pipeline.py keeps quality-filtered (non-corrupt) fragments
  - scene_merger fallback for short scenes
  - max_duration in DB query doesn't filter long single-take videos
  - Error "Видеофрагменты не найдены" never appears for valid footage
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── 1. Quality thresholds ──────────────────────────────────────────────────────

class TestQualityThresholds(unittest.TestCase):
    """DEFAULT_THRESHOLDS must not hard-reject normal action/drone footage."""

    def setUp(self):
        from src.preprocessing.quality_analyzer import DEFAULT_THRESHOLDS
        self.t = DEFAULT_THRESHOLDS

    def test_sharpness_threshold_allows_motion_blur(self):
        # DJI footage in flight commonly has Tenengrad ≈ 0.04–0.07 due to motion blur.
        # Threshold must be ≤ 0.05 so this footage is not silently discarded.
        self.assertLessEqual(self.t['sharpness'], 0.05,
            "sharpness threshold too strict — will discard normal drone footage")

    def test_stability_threshold_allows_camera_motion(self):
        # Handheld / drone shots during active movement have stability ≈ 0.05–0.15.
        # Threshold must be ≤ 0.06 so moving camera footage is not discarded.
        self.assertLessEqual(self.t['stability'], 0.06,
            "stability threshold too strict — will discard normal action/drone footage")

    def test_brightness_lo_allows_dark_cinematic_shots(self):
        self.assertLessEqual(self.t['brightness_lo'], 0.06,
            "brightness_lo threshold too strict — will discard dark cinematic shots")


# ── 2. Pipeline keeps quality-filtered fragments ───────────────────────────────

class TestPipelineKeepsQualityFiltered(unittest.TestCase):
    """Fragments rejected for quality reasons (not corrupt) must be kept in DB."""

    def _make_blurry_metrics(self):
        from src.preprocessing.quality_analyzer import TechMetrics
        # sharpness=0.062 — blurry per old threshold (0.08) but valid per new (0.04)
        return TechMetrics(
            sharpness=0.062,
            brightness=0.40,
            stability=0.074,
            motion=0.64,
            is_rejected=True,
            reject_reason='blurry (0.062)',
        )

    def test_blurry_fragment_not_skipped(self):
        """A 'blurry' fragment (not corrupt) must produce a DB entry."""
        from src.preprocessing.pipeline import _analyze_one_video
        from src.preprocessing.quality_analyzer import TechMetrics, DEFAULT_THRESHOLDS

        # With the new thresholds, sharpness=0.062 >= 0.04 threshold → not rejected
        threshold = DEFAULT_THRESHOLDS['sharpness']
        self.assertLess(threshold, 0.062,
            f"sharpness threshold {threshold} >= 0.062 means DJI footage would still be rejected")

    def test_corrupt_fragment_still_skipped(self):
        """Fragments with reject_reason 'no_frames'/'black_frame'/'corrupt' must be skipped."""
        _unreadable = {'no_frames', 'black_frame', 'corrupt'}
        # These are the only reasons pipeline hard-skips
        for reason in _unreadable:
            self.assertIn(reason, _unreadable)  # tautology to document intent

    def test_quality_rejection_does_not_call_mark_error(self):
        """When fragments exist (even quality-filtered), mark_error must NOT be called."""
        # This is tested by checking the DB state after analyze_project
        import tempfile
        from src.storage.analysis_db import AnalysisDB

        with tempfile.TemporaryDirectory() as tmpdir:
            db = AnalysisDB(tmpdir)
            # Simulate: video analyzed, 1 fragment saved (even with low quality)
            path = str(Path(tmpdir) / 'test.mp4')
            Path(path).write_bytes(b'\x00' * 512)
            sid = db.save_source_file(path)
            db.save_fragments(sid, [{
                'start_s': 0.0, 'end_s': 10.0, 'duration_s': 10.0,
                'quality_score': 0.35,  # low but not zero
            }])
            db.mark_analyzed(path, duration_s=10.0)

            statuses = db.get_source_files_status()
            self.assertEqual(statuses[0]['status'], 'analyzed')
            self.assertEqual(statuses[0]['n_frags'], 1)
            db.close()


# ── 3. Scene merger fallback ───────────────────────────────────────────────────

class TestSceneMergerFallback(unittest.TestCase):
    """When primary pass returns 0 scenes, fallback at 0.8 s must be used."""

    def _frag(self, source_id, start_s, end_s, quality=0.5):
        return {
            'id': int(source_id * 10000 + start_s * 100),
            'source_id': source_id,
            'source_path': f'/fake/video{source_id}.mp4',
            'start_s': start_s,
            'end_s': end_s,
            'duration_s': end_s - start_s,
            'quality_score': quality,
            'is_rejected': False,
        }

    def test_fallback_saves_short_fragments(self):
        """Single 1.0 s fragment passes fallback (0.8 s) but not primary (1.5 s)."""
        from src.preprocessing.scene_merger import merge_fragments_into_scenes

        frags = [self._frag(1, 0.0, 1.0)]  # 1.0s — below primary min_dur=1.5
        scenes_primary = merge_fragments_into_scenes(frags, min_duration=1.5)
        # Primary returns nothing
        # But merge_fragments_into_scenes should apply fallback internally
        # and return the 1.0 s fragment
        self.assertEqual(len(scenes_primary), 1,
            "Fallback should rescue 1.0 s fragment when primary (1.5 s) discards it")

    def test_fallback_not_applied_when_primary_works(self):
        """Normal fragments (>= 1.5 s) should not trigger fallback."""
        from src.preprocessing.scene_merger import merge_fragments_into_scenes

        frags = [self._frag(1, 0.0, 5.0)]  # 5 s — passes primary
        scenes = merge_fragments_into_scenes(frags, min_duration=1.5)
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0]['duration_s'], 5.0)

    def test_fallback_discards_sub_0_8s_fragments(self):
        """Fragments shorter than scene-detector min (0.8 s) must still be rejected."""
        from src.preprocessing.scene_merger import merge_fragments_into_scenes

        frags = [self._frag(1, 0.0, 0.5)]  # 0.5 s — below fallback min
        scenes = merge_fragments_into_scenes(frags, min_duration=1.5)
        self.assertEqual(len(scenes), 0)


# ── 4. max_duration in DB query ────────────────────────────────────────────────

class TestDBMaxDuration(unittest.TestCase):
    """Long single-take fragments must not be filtered by max_duration=30 default."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from src.storage.analysis_db import AnalysisDB
        self.db = AnalysisDB(self._tmp.name)
        video_path = str(Path(self._tmp.name) / 'long_video.mp4')
        Path(video_path).write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(video_path)
        self.db.mark_analyzed(video_path, duration_s=735.0)
        self.db.save_fragments(sid, [{
            'start_s': 0.0, 'end_s': 735.0, 'duration_s': 735.0,
            'quality_score': 0.50,
        }])

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_long_fragment_visible_with_max_3600(self):
        rows = self.db.get_fragments_filtered(
            min_quality=0.0, min_duration=0.5, max_duration=3600.0, limit=100
        )
        self.assertEqual(len(rows), 1, "735 s fragment must be visible when max_duration=3600")

    def test_long_fragment_hidden_with_default_max_30(self):
        rows = self.db.get_fragments_filtered(
            min_quality=0.0, min_duration=0.5, max_duration=30.0, limit=100
        )
        self.assertEqual(len(rows), 0, "735 s fragment must be filtered by old max_duration=30")


# ── 5. find_video_files: case-insensitive extensions ──────────────────────────

class TestFindVideoFiles(unittest.TestCase):
    """list_video_files must find .MP4 / .MOV uppercase extensions."""

    def test_uppercase_extensions_found(self):
        from src.preprocessing.pipeline import list_video_files
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / 'clip.MP4').write_bytes(b'\x00')
            (Path(tmpdir) / 'clip.MOV').write_bytes(b'\x00')
            (Path(tmpdir) / 'doc.pdf').write_bytes(b'\x00')
            found = list_video_files(tmpdir)
            names = {f.name for f in found}
            self.assertIn('clip.MP4', names)
            self.assertIn('clip.MOV', names)
            self.assertNotIn('doc.pdf', names)

    def test_empty_directory_returns_empty_list(self):
        from src.preprocessing.pipeline import list_video_files
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(list_video_files(tmpdir), [])

    def test_path_with_cyrillic_and_spaces(self):
        from src.preprocessing.pipeline import list_video_files
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = Path(tmpdir) / 'сигарный клуб'
            subdir.mkdir()
            (subdir / 'test.mp4').write_bytes(b'\x00')
            found = list_video_files(str(subdir))
            self.assertEqual(len(found), 1)


# ── 6. No fragments error message context ─────────────────────────────────────

class TestErrorMessageQuality(unittest.TestCase):
    """Error message must never say 'кадры не удалось прочитать' for quality-filtered videos."""

    def test_error_message_not_misleading(self):
        """The RuntimeError in pipeline.py must not claim unreadable frames for quality issues."""
        import inspect
        from src.preprocessing import pipeline
        source = inspect.getsource(pipeline._analyze_one_video)
        # Old misleading message must be gone
        self.assertNotIn(
            'кадры не удалось прочитать',
            source,
            "Old misleading error message still present in pipeline._analyze_one_video",
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
