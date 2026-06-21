"""
Tests for Step2SelectionAdapter + candidate_filter.

Covers:
  1. MontagePool.is_active=False when prep_mode != 'done'
  2. Forbidden fragment IDs are removed from candidates
  3. Forbidden time ranges filter SegmentSelector candidates (no _fragment_id)
  4. Priority fragment IDs get score boost and is_must_use=True
  5. Score boost is capped at 1.0
  6. Legacy mode (pool.is_active=False) passes candidates through unchanged
  7. Empty forbidden set does not remove any candidates
  8. Candidates without _fragment_id are not removed by ID-based filter
  9. No overlap for adjacent (touching) ranges — only strict overlap counts
 10. Step2SelectionAdapter.build_pool() returns inactive pool when not 'done'
 11. Step2SelectionAdapter.build_pool() with empty forbidden_fids skips DB lookup
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_candidate(fid=None, source_path='/fake/video.mp4', start=0.0, end=5.0, score=0.5):
    """Create a minimal duck-type candidate."""
    c = MagicMock()
    c.source_path = source_path
    c.start = start
    c.end = end
    c.final_score = score
    c.is_must_use = False
    if fid is not None:
        c._fragment_id = fid
    else:
        # Simulate SegmentSelector candidate: no _fragment_id attribute
        del c._fragment_id
    return c


# ── 1. MontagePool defaults ────────────────────────────────────────────────────

class TestMontagePool(unittest.TestCase):
    def test_inactive_by_default(self):
        from src.preprocessing.step2_adapter import MontagePool
        pool = MontagePool()
        self.assertFalse(pool.is_active)

    def test_active_when_set(self):
        from src.preprocessing.step2_adapter import MontagePool
        pool = MontagePool(forbidden_fragment_ids={1, 2}, is_active=True)
        self.assertIn(1, pool.forbidden_fragment_ids)
        self.assertTrue(pool.is_active)


# ── 2. apply_montage_pool — forbidden IDs ─────────────────────────────────────

class TestCandidateFilterForbiddenIds(unittest.TestCase):
    def _pool(self, forbidden_ids=(), priority_ids=(), ranges=()):
        from src.preprocessing.step2_adapter import MontagePool
        return MontagePool(
            forbidden_fragment_ids=set(forbidden_ids),
            forbidden_ranges=list(ranges),
            priority_fragment_ids=set(priority_ids),
            is_active=True,
        )

    def test_forbidden_id_removed(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=42)
        pool = self._pool(forbidden_ids={42})
        result = apply_montage_pool([c], pool)
        self.assertEqual(result, [])

    def test_non_forbidden_id_kept(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=7)
        pool = self._pool(forbidden_ids={42})
        result = apply_montage_pool([c], pool)
        self.assertEqual(len(result), 1)

    def test_mixed_forbidden_non_forbidden(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        c1 = _make_candidate(fid=1)
        c2 = _make_candidate(fid=2)
        c3 = _make_candidate(fid=3)
        pool = self._pool(forbidden_ids={2})
        result = apply_montage_pool([c1, c2, c3], pool)
        ids = [getattr(r, '_fragment_id', None) for r in result]
        self.assertIn(1, ids)
        self.assertNotIn(2, ids)
        self.assertIn(3, ids)

    def test_candidate_without_fragment_id_not_removed_by_id_filter(self):
        """SegmentSelector candidates (no _fragment_id) must not be removed by ID blacklist."""
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=None)   # no _fragment_id
        pool = self._pool(forbidden_ids={1, 2, 3, 99})
        result = apply_montage_pool([c], pool)
        self.assertEqual(len(result), 1)


# ── 3. apply_montage_pool — forbidden ranges ──────────────────────────────────

class TestCandidateFilterForbiddenRanges(unittest.TestCase):
    def _pool(self, ranges=()):
        from src.preprocessing.step2_adapter import MontagePool
        return MontagePool(forbidden_ranges=list(ranges), is_active=True)

    def test_overlapping_range_removed(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=None, source_path='/v/a.mp4', start=5.0, end=10.0)
        pool = self._pool(ranges=[('/v/a.mp4', 4.0, 11.0)])
        result = apply_montage_pool([c], pool)
        self.assertEqual(result, [])

    def test_adjacent_range_not_removed(self):
        """Ranges that touch but don't overlap must not be filtered."""
        from src.preprocessing.candidate_filter import apply_montage_pool
        # candidate: [10, 15), forbidden: [5, 10) — they touch at 10 but don't overlap
        c = _make_candidate(fid=None, source_path='/v/a.mp4', start=10.0, end=15.0)
        pool = self._pool(ranges=[('/v/a.mp4', 5.0, 10.0)])
        result = apply_montage_pool([c], pool)
        self.assertEqual(len(result), 1)

    def test_different_source_path_not_filtered(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=None, source_path='/v/b.mp4', start=0.0, end=10.0)
        pool = self._pool(ranges=[('/v/a.mp4', 0.0, 10.0)])
        result = apply_montage_pool([c], pool)
        self.assertEqual(len(result), 1)

    def test_partial_overlap_removed(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=None, source_path='/v/a.mp4', start=8.0, end=15.0)
        pool = self._pool(ranges=[('/v/a.mp4', 5.0, 10.0)])
        result = apply_montage_pool([c], pool)
        self.assertEqual(result, [])


# ── 4. apply_montage_pool — priority boost ────────────────────────────────────

class TestCandidateFilterPriorityBoost(unittest.TestCase):
    def _pool(self, priority_ids=()):
        from src.preprocessing.step2_adapter import MontagePool
        return MontagePool(
            priority_fragment_ids=set(priority_ids),
            score_boost=0.30,
            is_active=True,
        )

    def test_priority_id_boosted(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=5, score=0.50)
        pool = self._pool(priority_ids={5})
        result = apply_montage_pool([c], pool)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].final_score, 0.80, places=5)
        self.assertTrue(result[0].is_must_use)

    def test_non_priority_id_not_boosted(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=9, score=0.50)
        pool = self._pool(priority_ids={5})
        result = apply_montage_pool([c], pool)
        self.assertAlmostEqual(result[0].final_score, 0.50, places=5)
        self.assertFalse(result[0].is_must_use)

    def test_score_capped_at_1(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=3, score=0.95)
        pool = self._pool(priority_ids={3})
        result = apply_montage_pool([c], pool)
        self.assertLessEqual(result[0].final_score, 1.0)
        self.assertAlmostEqual(result[0].final_score, 1.0, places=5)

    def test_candidate_without_id_not_boosted(self):
        """SegmentSelector candidates (no _fragment_id) must not get priority boost."""
        from src.preprocessing.candidate_filter import apply_montage_pool
        c = _make_candidate(fid=None, score=0.50)
        pool = self._pool(priority_ids={1, 2, 3})
        result = apply_montage_pool([c], pool)
        self.assertAlmostEqual(result[0].final_score, 0.50, places=5)
        self.assertFalse(result[0].is_must_use)


# ── 5. Legacy pass-through (is_active=False) ──────────────────────────────────

class TestCandidateFilterLegacyMode(unittest.TestCase):
    def test_inactive_pool_returns_unchanged_list(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        from src.preprocessing.step2_adapter import MontagePool
        candidates = [_make_candidate(fid=i) for i in range(5)]
        pool = MontagePool(is_active=False)
        result = apply_montage_pool(candidates, pool)
        self.assertIs(result, candidates)

    def test_empty_forbidden_set_keeps_all(self):
        from src.preprocessing.candidate_filter import apply_montage_pool
        from src.preprocessing.step2_adapter import MontagePool
        candidates = [_make_candidate(fid=i) for i in range(3)]
        pool = MontagePool(forbidden_fragment_ids=set(), is_active=True)
        result = apply_montage_pool(candidates, pool)
        self.assertEqual(len(result), 3)


# ── 6. Step2SelectionAdapter.build_pool ───────────────────────────────────────

class TestStep2AdapterBuildPool(unittest.TestCase):
    def test_inactive_when_prep_mode_not_done(self):
        from src.preprocessing.step2_adapter import Step2SelectionAdapter
        for mode in (None, 'running', 'skipped', ''):
            pool = Step2SelectionAdapter.build_pool(
                prep_mode=mode,
                prep_rejected_fids={1, 2},
                prep_approved_ids={3},
                db_dirs=[],
            )
            self.assertFalse(pool.is_active, f'Expected inactive for mode={mode!r}')

    def test_active_when_prep_mode_done_with_data(self):
        from src.preprocessing.step2_adapter import Step2SelectionAdapter
        pool = Step2SelectionAdapter.build_pool(
            prep_mode='done',
            prep_rejected_fids={10},
            prep_approved_ids={20},
            db_dirs=[],
        )
        self.assertTrue(pool.is_active)
        self.assertIn(10, pool.forbidden_fragment_ids)
        self.assertIn(20, pool.priority_fragment_ids)

    def test_inactive_when_no_data(self):
        from src.preprocessing.step2_adapter import Step2SelectionAdapter
        pool = Step2SelectionAdapter.build_pool(
            prep_mode='done',
            prep_rejected_fids=set(),
            prep_approved_ids=set(),
            db_dirs=[],
        )
        self.assertFalse(pool.is_active)

    def test_db_lookup_called_for_forbidden_ids(self):
        """When forbidden IDs are present, adapter must query the DB for time ranges."""
        import tempfile
        from pathlib import Path as _Path
        from src.preprocessing.step2_adapter import Step2SelectionAdapter
        from src.storage.analysis_db import AnalysisDB

        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up a real DB with one fragment
            db = AnalysisDB(tmpdir)
            vid = str(_Path(tmpdir) / 'clip.mp4')
            _Path(vid).write_bytes(b'\x00' * 512)
            sid = db.save_source_file(vid)
            db.save_fragments(sid, [{
                'start_s': 5.0, 'end_s': 10.0, 'duration_s': 5.0, 'quality_score': 0.5,
            }])
            db.mark_analyzed(vid, duration_s=15.0)
            # Find the fragment ID
            rows = db.get_fragments_by_ids({999999})  # non-existent
            self.assertEqual(rows, [])
            # Real ID
            all_rows = db.get_fragments_filtered(min_quality=0.0, min_duration=0.0, max_duration=9999.0, limit=10)
            fid = all_rows[0]['id']
            db.close()

            pool = Step2SelectionAdapter.build_pool(
                prep_mode='done',
                prep_rejected_fids={fid},
                prep_approved_ids=set(),
                db_dirs=[tmpdir],
            )
            self.assertEqual(len(pool.forbidden_ranges), 1)
            src, start, end = pool.forbidden_ranges[0]
            self.assertEqual(src, vid)
            self.assertAlmostEqual(start, 5.0)
            self.assertAlmostEqual(end, 10.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
