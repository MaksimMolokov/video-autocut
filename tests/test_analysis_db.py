"""Unit tests for AnalysisDB: CRUD, cache invalidation, fragment counts."""

import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAnalysisDB(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_dir = self._tmp.name
        from src.storage.analysis_db import AnalysisDB
        self.db = AnalysisDB(self.project_dir)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    # Table creation / basic insert
    # ------------------------------------------------------------------

    def test_create_tables_does_not_raise(self):
        # save_source_file uses all tables — no error = tables exist
        path = Path(self.project_dir) / 'test.mp4'
        path.write_bytes(b'\x00' * 128)
        self.db.save_source_file(str(path))

    # ------------------------------------------------------------------
    # Cache miss / hit
    # ------------------------------------------------------------------

    def test_cache_miss_nonexistent_file(self):
        self.assertFalse(self.db.is_analyzed('/tmp/_nonexistent_video_xyz.mp4'))

    def test_cache_hit_after_mark_analyzed(self):
        path = Path(self.project_dir) / 'good.mp4'
        path.write_bytes(b'\x00' * 1024)
        self.db.save_source_file(str(path))
        self.db.mark_analyzed(str(path))
        self.assertTrue(self.db.is_analyzed(str(path)))

    def test_cache_invalidated_after_file_modification(self):
        path = Path(self.project_dir) / 'modify.mp4'
        path.write_bytes(b'\x00' * 1024)
        self.db.save_source_file(str(path))
        self.db.mark_analyzed(str(path))
        self.assertTrue(self.db.is_analyzed(str(path)))
        # Modify content — hash changes
        path.write_bytes(b'\xFF' * 2048)
        self.assertFalse(self.db.is_analyzed(str(path)))

    def test_cache_miss_for_pending_file(self):
        path = Path(self.project_dir) / 'pending.mp4'
        path.write_bytes(b'\xAA' * 512)
        self.db.save_source_file(str(path))
        # status is still 'pending'
        self.assertFalse(self.db.is_analyzed(str(path)))

    # ------------------------------------------------------------------
    # Fragment save / count
    # ------------------------------------------------------------------

    def test_save_and_count_fragments(self):
        path = Path(self.project_dir) / 'frag.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        fragments = [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0, 'quality_score': 0.75},
            {'start_s': 5.0, 'end_s': 9.0, 'duration_s': 4.0, 'quality_score': 0.82},
        ]
        self.db.save_fragments(sid, fragments)
        self.assertEqual(self.db.count_fragments(min_quality=0.0), 2)

    def test_count_fragments_quality_filter(self):
        path = Path(self.project_dir) / 'filter.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        fragments = [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0, 'quality_score': 0.30},
            {'start_s': 5.0, 'end_s': 9.0, 'duration_s': 4.0, 'quality_score': 0.80},
        ]
        self.db.save_fragments(sid, fragments)
        self.assertEqual(self.db.count_fragments(min_quality=0.55), 1)
        self.assertEqual(self.db.count_fragments(min_quality=0.0), 2)

    # ------------------------------------------------------------------
    # Error marking
    # ------------------------------------------------------------------

    def test_mark_error(self):
        path = Path(self.project_dir) / 'err.mp4'
        path.write_bytes(b'\x00' * 128)
        self.db.save_source_file(str(path))
        self.db.mark_error(str(path), 'test error')
        pending = self.db.get_pending_paths()
        self.assertIn(str(path), pending)

    # ------------------------------------------------------------------
    # Approval / priority
    # ------------------------------------------------------------------

    def test_fragment_approval(self):
        path = Path(self.project_dir) / 'appr.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        self.db.save_fragments(sid, [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0, 'quality_score': 0.70},
        ])
        rows = self.db.get_fragments_filtered(min_quality=0.0)
        self.assertEqual(len(rows), 1)
        fid = rows[0]['id']
        self.db.update_fragment_approval(fid, True)
        rows2 = self.db.get_fragments_filtered(min_quality=0.0, approved_only=True)
        self.assertEqual(len(rows2), 1)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def test_get_stats_empty(self):
        stats = self.db.get_stats()
        self.assertEqual(stats['total_files'], 0)
        self.assertEqual(stats['total_fragments'], 0)

    def test_get_stats_after_analyze(self):
        path = Path(self.project_dir) / 'stat.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        self.db.save_fragments(sid, [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0, 'quality_score': 0.70},
            {'start_s': 5.0, 'end_s': 8.0, 'duration_s': 3.0, 'quality_score': 0.30},
        ])
        self.db.mark_analyzed(str(path))
        stats = self.db.get_stats()
        self.assertEqual(stats['analyzed_files'], 1)
        self.assertEqual(stats['total_fragments'], 2)
        self.assertEqual(stats['good_fragments'], 1)  # only quality >= 0.55

    # ------------------------------------------------------------------
    # reset_all
    # ------------------------------------------------------------------

    def test_reset_all_clears_data(self):
        path = Path(self.project_dir) / 'reset.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        self.db.save_fragments(sid, [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0, 'quality_score': 0.70},
        ])
        self.db.reset_all()
        self.assertEqual(self.db.count_fragments(min_quality=0.0), 0)

    # ------------------------------------------------------------------
    # Scene tag filter
    # ------------------------------------------------------------------

    def test_scene_tag_filter(self):
        path = Path(self.project_dir) / 'tagged.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        self.db.save_fragments(sid, [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0, 'quality_score': 0.7, 'scene_tag': 'nature'},
            {'start_s': 4.0, 'end_s': 7.0, 'duration_s': 3.0, 'quality_score': 0.7, 'scene_tag': 'city'},
        ])
        rows = self.db.get_fragments_filtered(min_quality=0.0, scene_tags=['nature'])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['scene_tag'], 'nature')

    def test_get_available_scene_tags(self):
        path = Path(self.project_dir) / 'tags.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        self.db.save_fragments(sid, [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0, 'quality_score': 0.7, 'scene_tag': 'ocean'},
            {'start_s': 4.0, 'end_s': 7.0, 'duration_s': 3.0, 'quality_score': 0.7, 'scene_tag': 'ocean'},
            {'start_s': 8.0, 'end_s': 11.0, 'duration_s': 3.0, 'quality_score': 0.7, 'scene_tag': 'city'},
        ])
        tags = self.db.get_available_scene_tags()
        self.assertIn('ocean', tags)
        self.assertIn('city', tags)
        self.assertEqual(len(tags), 2)  # distinct

    # ------------------------------------------------------------------
    # Regression: get_fragments_filtered must return 'filename' and
    # 'source_path' keys (gui.py accesses frag['filename'] at line ~750)
    # ------------------------------------------------------------------

    def test_fragments_filtered_returns_filename_key(self):
        """Regression: frag['filename'] must be accessible — previously
        get_fragments_filtered only SELECTed sf.path but not sf.filename,
        causing a KeyError when the fragment viewer in gui.py accessed it."""
        path = Path(self.project_dir) / 'clip_with_filename.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        self.db.save_fragments(sid, [
            {'start_s': 0.0, 'end_s': 4.0, 'duration_s': 4.0, 'quality_score': 0.80},
        ])
        rows = self.db.get_fragments_filtered(min_quality=0.0)
        self.assertEqual(len(rows), 1)
        # Must have both joined columns — no KeyError
        self.assertIn('filename', rows[0].keys())
        self.assertIn('source_path', rows[0].keys())
        self.assertEqual(rows[0]['filename'], 'clip_with_filename.mp4')
        self.assertEqual(rows[0]['source_path'], str(path))

    def test_fragments_filtered_filename_matches_basename(self):
        """filename column must equal the basename of the path, not the full path."""
        path = Path(self.project_dir) / 'my_video_file.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        self.db.save_fragments(sid, [
            {'start_s': 1.0, 'end_s': 5.0, 'duration_s': 4.0, 'quality_score': 0.70},
        ])
        rows = self.db.get_fragments_filtered(min_quality=0.0)
        row = rows[0]
        self.assertEqual(row['filename'], path.name)
        self.assertNotEqual(row['filename'], str(path),
                            "filename should be the basename, not the full path")

    def test_fragments_filtered_exclude_duplicates_flag(self):
        """exclude_duplicates=False must return fragments even when is_duplicate=1."""
        path = Path(self.project_dir) / 'dup.mp4'
        path.write_bytes(b'\x00' * 512)
        sid = self.db.save_source_file(str(path))
        self.db.save_fragments(sid, [
            {'start_s': 0.0, 'end_s': 3.0, 'duration_s': 3.0,
             'quality_score': 0.75, 'is_duplicate': True},
        ])
        # With duplicates excluded (default) — should not appear
        rows_excluded = self.db.get_fragments_filtered(
            min_quality=0.0, exclude_duplicates=True
        )
        self.assertEqual(len(rows_excluded), 0)
        # With duplicates included — must appear
        rows_included = self.db.get_fragments_filtered(
            min_quality=0.0, exclude_duplicates=False
        )
        self.assertEqual(len(rows_included), 1)


class TestRenderHistory(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        from src.storage.analysis_db import AnalysisDB
        self.db = AnalysisDB(self._tmp.name)
        self.project_dir = self._tmp.name

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_save_and_retrieve_render(self):
        rid = self.db.save_render(
            project_dir=self.project_dir,
            style_id='f2',
            style_name='Cinematic',
            clip_count=12,
            duration_s=65.0,
        )
        self.assertGreater(rid, 0)
        rows = self.db.get_render_history(project_dir=self.project_dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['style_id'], 'f2')
        self.assertEqual(rows[0]['clip_count'], 12)
        self.assertIsNone(rows[0]['user_rating'])

    def test_set_rating(self):
        rid = self.db.save_render(self.project_dir, style_id='f4')
        self.db.set_render_rating(rid, 4)
        rows = self.db.get_render_history(self.project_dir)
        self.assertEqual(rows[0]['user_rating'], 4)

    def test_rating_clamped_to_5(self):
        rid = self.db.save_render(self.project_dir, style_id='f3')
        self.db.set_render_rating(rid, 99)
        rows = self.db.get_render_history(self.project_dir)
        self.assertLessEqual(rows[0]['user_rating'], 5)

    def test_delete_render_entry(self):
        rid = self.db.save_render(self.project_dir, style_id='f5')
        self.db.delete_render_history_entry(rid)
        rows = self.db.get_render_history(self.project_dir)
        self.assertEqual(len(rows), 0)

    def test_history_ordered_newest_first(self):
        self.db.save_render(self.project_dir, style_id='f2')
        self.db.save_render(self.project_dir, style_id='f4')
        rows = self.db.get_render_history(self.project_dir)
        self.assertEqual(rows[0]['style_id'], 'f4')

    def test_empty_history(self):
        rows = self.db.get_render_history(self.project_dir)
        self.assertEqual(rows, [])


if __name__ == '__main__':
    unittest.main()
