"""
Integration tests for the preprocessing pipeline.

Slow tests that run the full analyze_project() loop are marked
@unittest.skipUnless(HAS_TEST_PROJECT, ...) — they only run when
a test project directory is available via env var TEST_PROJECT_DIR.
"""

import os
import sys
import time
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_TEST_PROJECT = os.environ.get('TEST_PROJECT_DIR', '')
_HAS_PROJECT = bool(_TEST_PROJECT and Path(_TEST_PROJECT).is_dir())


class TestAnalyzeProjectEmptyDir(unittest.TestCase):
    """analyze_project must not crash on an empty or no-video folder."""

    def test_empty_folder_returns_zero(self):
        from src.preprocessing.pipeline import analyze_project
        with tempfile.TemporaryDirectory() as tmp:
            n = analyze_project(tmp)
        self.assertEqual(n, 0)

    def test_no_video_folder_returns_zero(self):
        from src.preprocessing.pipeline import analyze_project
        with tempfile.TemporaryDirectory() as tmp:
            # Create non-video files only
            (Path(tmp) / 'readme.txt').write_text('hello')
            (Path(tmp) / 'photo.jpg').write_bytes(b'\xFF\xD8\xFF')
            n = analyze_project(tmp)
        self.assertEqual(n, 0)

    def test_progress_callback_not_called_for_empty(self):
        from src.preprocessing.pipeline import analyze_project
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            analyze_project(tmp, progress_callback=lambda *a: calls.append(a))
        self.assertEqual(len(calls), 0)


class TestListVideoFiles(unittest.TestCase):
    """list_video_files must find common extensions and ignore .videoeditor/."""

    def test_finds_mp4(self):
        from src.preprocessing.pipeline import list_video_files
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'clip.mp4').write_bytes(b'\x00' * 128)
            (Path(tmp) / 'other.txt').write_text('x')
            found = list_video_files(tmp)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].suffix, '.mp4')

    def test_ignores_videoeditor_dir(self):
        from src.preprocessing.pipeline import list_video_files
        with tempfile.TemporaryDirectory() as tmp:
            hidden = Path(tmp) / '.videoeditor'
            hidden.mkdir()
            (hidden / 'clip.mp4').write_bytes(b'\x00' * 128)
            (Path(tmp) / 'real.mp4').write_bytes(b'\x00' * 128)
            found = list_video_files(tmp)
        self.assertEqual(len(found), 1)
        self.assertNotIn('.videoeditor', str(found[0]))


@unittest.skipUnless(_HAS_PROJECT, 'Set TEST_PROJECT_DIR to run integration tests')
class TestFullPipeline(unittest.TestCase):

    def test_analyze_project_returns_fragments(self):
        from src.preprocessing.pipeline import analyze_project
        n = analyze_project(_TEST_PROJECT)
        self.assertGreaterEqual(n, 5, f'Expected >= 5 good fragments, got {n}')

    def test_cache_hit_fast(self):
        from src.preprocessing.pipeline import analyze_project
        analyze_project(_TEST_PROJECT)           # warm up
        start = time.time()
        analyze_project(_TEST_PROJECT)           # from cache
        elapsed = time.time() - start
        self.assertLess(elapsed, 3.0,
                        f'Cache miss — second run took {elapsed:.1f}s')

    def test_fragment_quality_above_threshold(self):
        from src.preprocessing.pipeline import analyze_project
        from src.storage.analysis_db import AnalysisDB
        from src.preprocessing.clip_library import FragmentLibrary

        analyze_project(_TEST_PROJECT)
        lib = FragmentLibrary(AnalysisDB(_TEST_PROJECT))
        candidates = lib.get_candidates(min_quality=0.55)
        for c in candidates:
            self.assertGreaterEqual(
                c.features.technical_quality_score, 0.45,
                'Low-quality candidate leaked through (0.05 tolerance)',
            )

    def test_thumbnails_generated(self):
        from src.preprocessing.pipeline import analyze_project
        from src.storage.analysis_db import AnalysisDB
        from src.preprocessing.clip_library import FragmentLibrary

        analyze_project(_TEST_PROJECT)
        lib = FragmentLibrary(AnalysisDB(_TEST_PROJECT))
        frags = lib.get_fragments_for_ui(min_quality=0.0, limit=10)
        self.assertGreater(len(frags), 0)
        for f in frags:
            if f.thumbnail_path:
                self.assertTrue(
                    Path(f.thumbnail_path).exists(),
                    f'Thumbnail missing: {f.thumbnail_path}',
                )

    def test_progress_callback_called_n_times(self):
        from src.preprocessing.pipeline import analyze_project
        from src.storage.analysis_db import AnalysisDB

        # Reset so all files are re-analyzed
        AnalysisDB(_TEST_PROJECT).reset_all()
        calls = []
        analyze_project(_TEST_PROJECT,
                        progress_callback=lambda name, done, total: calls.append(done))
        # Callback must be called once per pending file
        self.assertGreater(len(calls), 0)
        # Last call must equal total
        self.assertEqual(calls[-1], len(calls))


if __name__ == '__main__':
    unittest.main()
