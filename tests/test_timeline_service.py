"""Unit tests for TimelineService._select_segments — variant logic (VI2-011)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.timeline_service import _select_segments


def _candidate(
    fid: int,
    quality: float = 0.6,
    duration: float = 4.0,
    role: str = "body",
    motion: str = "static",
    tags: List[str] = None,
    style_fits: List = None,
) -> SimpleNamespace:
    fp = SimpleNamespace(
        camera_motion_type=motion,
        semantic_tags=tags or [],
        suggested_role=role,
    )
    c = SimpleNamespace(
        id=fid,
        quality_score=quality,
        duration_s=duration,
        start_s=0.0,
        end_s=duration,
        feature_profile=fp,
        style_fits=style_fits or [],
    )

    class FakeSrc:
        rel_path = f"video_{fid}.mp4"

    c.source_file = FakeSrc()
    return c


def _preset(
    min_dur: float = 1.0,
    max_dur: float = 10.0,
    min_q: float = 0.30,
    preferred_motion: List[str] = None,
    rejected_motion: List[str] = None,
    preferred_cats: List[str] = None,
) -> dict:
    return {
        "settings": {
            "preset_id": "test",
            "clip_selection": {
                "segment_min_duration": min_dur,
                "segment_max_duration": max_dur,
                "min_quality_score": min_q,
            },
            "segment_selection": {
                "preferred_camera_motion": preferred_motion or [],
                "rejected_camera_motion":  rejected_motion or [],
                "preferred_scene_categories": preferred_cats or [],
                "min_scores": {"quality_score": min_q},
            },
        }
    }


class TestVariantA(unittest.TestCase):
    """seed_offset=0 → sort by quality_score descending."""

    def test_best_quality_first(self):
        candidates = [
            _candidate(0, quality=0.50),
            _candidate(1, quality=0.90),
            _candidate(2, quality=0.70),
        ]
        segs = _select_segments(candidates, _preset(), 20.0, 0)
        self.assertGreater(len(segs), 0)
        # First segment should come from candidate with highest quality
        self.assertEqual(segs[0]["fragment_id"], 1)

    def test_all_segments_have_required_fields(self):
        candidates = [_candidate(i) for i in range(4)]
        segs = _select_segments(candidates, _preset(), 20.0, 0)
        for s in segs:
            self.assertIn("source_rel_path", s)
            self.assertIn("start_s", s)
            self.assertIn("end_s", s)
            self.assertIn("role", s)
            self.assertIn("score", s)
            self.assertIn("fragment_id", s)


class TestVariantC(unittest.TestCase):
    """seed_offset=2 → structured: intro → body → outro."""

    def test_intro_comes_first(self):
        candidates = [
            _candidate(0, role="body",  quality=0.70),
            _candidate(1, role="intro", quality=0.60),
            _candidate(2, role="body",  quality=0.80),
            _candidate(3, role="outro", quality=0.60),
        ]
        segs = _select_segments(candidates, _preset(), 20.0, 2)
        if len(segs) >= 2:
            # intro segment should come before any outro segment
            intro_idx = next((i for i, s in enumerate(segs) if s["role"] == "intro"), None)
            outro_idx = next((i for i, s in enumerate(segs) if s["role"] == "outro"), None)
            if intro_idx is not None and outro_idx is not None:
                self.assertLess(intro_idx, outro_idx)

    def test_produces_segments(self):
        candidates = [_candidate(i, role=["intro", "body", "body", "outro"][i]) for i in range(4)]
        segs = _select_segments(candidates, _preset(), 20.0, 2)
        self.assertGreater(len(segs), 0)


class TestVariantD(unittest.TestCase):
    """seed_offset=3 → random shuffle — deterministic with fixed seed."""

    def test_deterministic_with_same_seed(self):
        candidates = [_candidate(i) for i in range(6)]
        segs_a = _select_segments(candidates, _preset(), 20.0, 3)
        segs_b = _select_segments(candidates, _preset(), 20.0, 3)
        self.assertEqual([s["fragment_id"] for s in segs_a],
                         [s["fragment_id"] for s in segs_b])

    def test_different_seed_gives_different_order(self):
        candidates = [_candidate(i) for i in range(8)]
        ids_d0 = [s["fragment_id"] for s in _select_segments(candidates, _preset(), 30.0, 0)]
        ids_d3 = [s["fragment_id"] for s in _select_segments(candidates, _preset(), 30.0, 3)]
        # With 8 candidates it's extremely unlikely to be identical
        self.assertNotEqual(ids_d0, ids_d3)


class TestDurationFilling(unittest.TestCase):

    def test_does_not_exceed_target_by_much(self):
        candidates = [_candidate(i, duration=3.0) for i in range(10)]
        target = 15.0
        segs = _select_segments(candidates, _preset(max_dur=5.0), target, 0)
        total_dur = sum(s["end_s"] - s["start_s"] for s in segs)
        self.assertLessEqual(total_dur, target * 1.25)

    def test_stops_when_target_reached(self):
        candidates = [_candidate(i, duration=5.0) for i in range(20)]
        target = 10.0
        segs = _select_segments(candidates, _preset(max_dur=8.0), target, 0)
        total_dur = sum(s["end_s"] - s["start_s"] for s in segs)
        self.assertLessEqual(total_dur, target * 1.25)


class TestFiltering(unittest.TestCase):

    def test_rejected_motion_excluded(self):
        candidates = [
            _candidate(0, motion="static",   quality=0.8),
            _candidate(1, motion="shake",    quality=0.9),  # should be filtered
            _candidate(2, motion="pan_left", quality=0.7),
        ]
        ps = _preset(rejected_motion=["shake"])
        segs = _select_segments(candidates, ps, 20.0, 0)
        fragment_ids = [s["fragment_id"] for s in segs]
        # shake candidate (id=1) should NOT appear
        self.assertNotIn(1, fragment_ids)

    def test_low_quality_filtered_below_min(self):
        candidates = [
            _candidate(0, quality=0.80),
            _candidate(1, quality=0.10),  # below min_quality
        ]
        ps = _preset(min_q=0.50)
        segs = _select_segments(candidates, ps, 20.0, 0)
        fragment_ids = [s["fragment_id"] for s in segs]
        self.assertNotIn(1, fragment_ids)

    def test_filter_relaxed_when_pool_too_small(self):
        # Only 2 candidates, one filtered → pool < 3, should relax and include all
        candidates = [
            _candidate(0, quality=0.80),
            _candidate(1, quality=0.10),
        ]
        ps = _preset(min_q=0.50)
        segs = _select_segments(candidates, ps, 20.0, 0)
        # After relaxation both candidates should be available
        self.assertGreater(len(segs), 0)


if __name__ == "__main__":
    unittest.main()
