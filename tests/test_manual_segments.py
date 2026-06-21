"""
Tests for src/preprocessing/manual_segments.py

Covers:
 1. ManualSegment.create() sets correct fields
 2. ManualSegmentsStore saves and loads from disk
 3. store.add() persists after reload
 4. store.delete() removes the segment
 5. store.clear_for_source() removes only that source's segments
 6. store.get_forbidden_ranges() returns only forbidden/bad segments
 7. store.get_required_ranges() returns only required/recommended segments
 8. store.has_any() returns False for empty store
 9. Tags can contain multiple values
10. ManualSegment.from_dict roundtrip
"""
import tempfile
import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.preprocessing.manual_segments import (
    ManualSegment,
    ManualSegmentsStore,
    TAGS,
    TAG_IDS,
    TAG_NAMES,
    TAG_NAME_TO_ID,
    INCLUDE_POLICIES,
    PRIORITIES,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def store(tmpdir):
    return ManualSegmentsStore(tmpdir)


def _make_seg(source="video.mp4", start=1.0, end=5.0, **kwargs):
    return ManualSegment.create(source_file=source, start_time=start, end_time=end, **kwargs)


# ── Test 1: ManualSegment.create() sets correct fields ────────────────────────

def test_create_sets_fields():
    seg = ManualSegment.create(
        source_file="/data/clip.mp4",
        start_time=2.5,
        end_time=10.0,
        user_tags=["intro", "dynamic"],
        priority="high",
        include_policy="required",
        user_note="opening shot",
    )
    assert seg.source_file == "/data/clip.mp4"
    assert seg.start_time == 2.5
    assert seg.end_time == 10.0
    assert abs(seg.duration - 7.5) < 0.01
    assert seg.user_tags == ["intro", "dynamic"]
    assert seg.priority == "high"
    assert seg.include_policy == "required"
    assert seg.user_note == "opening shot"
    assert seg.status == "active"
    assert len(seg.manual_segment_id) == 36  # UUID4 length


def test_create_rounds_times():
    seg = ManualSegment.create(source_file="v.mp4", start_time=1.123456, end_time=4.987654)
    assert seg.start_time == round(1.123456, 2)
    assert seg.end_time == round(4.987654, 2)


def test_create_default_fields():
    seg = ManualSegment.create(source_file="v.mp4", start_time=0.0, end_time=3.0)
    assert seg.user_tags == []
    assert seg.priority == "normal"
    assert seg.include_policy == "optional"
    assert seg.user_note == ""


# ── Test 2: ManualSegmentsStore saves and loads from disk ─────────────────────

def test_store_saves_and_loads(tmpdir):
    store1 = ManualSegmentsStore(tmpdir)
    seg = _make_seg()
    store1.add(seg)

    # Confirm the JSON file was written
    json_path = Path(tmpdir) / ".videoeditor" / "manual_segments.json"
    assert json_path.exists()

    # Load via a fresh store instance
    store2 = ManualSegmentsStore(tmpdir)
    loaded = store2.get_all()
    assert len(loaded) == 1
    assert loaded[0].manual_segment_id == seg.manual_segment_id
    assert loaded[0].source_file == seg.source_file


# ── Test 3: store.add() persists after reload ─────────────────────────────────

def test_add_persists(tmpdir):
    store = ManualSegmentsStore(tmpdir)
    seg = _make_seg(source="a.mp4", start=0.0, end=4.0)
    store.add(seg)

    reloaded = ManualSegmentsStore(tmpdir)
    all_segs = reloaded.get_all()
    assert any(s.manual_segment_id == seg.manual_segment_id for s in all_segs)


# ── Test 4: store.delete() removes the segment ───────────────────────────────

def test_delete_removes_segment(tmpdir):
    store = ManualSegmentsStore(tmpdir)
    seg1 = _make_seg(source="a.mp4")
    seg2 = _make_seg(source="b.mp4")
    store.add(seg1)
    store.add(seg2)

    store.delete(seg1.manual_segment_id)

    remaining = store.get_all()
    assert len(remaining) == 1
    assert remaining[0].manual_segment_id == seg2.manual_segment_id

    # Confirm persistence
    reloaded = ManualSegmentsStore(tmpdir)
    assert len(reloaded.get_all()) == 1


# ── Test 5: store.clear_for_source() removes only that source ─────────────────

def test_clear_for_source(tmpdir):
    store = ManualSegmentsStore(tmpdir)
    store.add(_make_seg(source="a.mp4"))
    store.add(_make_seg(source="a.mp4"))
    store.add(_make_seg(source="b.mp4"))

    store.clear_for_source("a.mp4")

    remaining = store.get_all()
    assert len(remaining) == 1
    assert remaining[0].source_file == "b.mp4"


# ── Test 6: get_forbidden_ranges() returns only forbidden/bad ─────────────────

def test_get_forbidden_ranges(tmpdir):
    store = ManualSegmentsStore(tmpdir)
    # forbidden via include_policy
    store.add(_make_seg(source="v.mp4", start=0.0, end=3.0, include_policy="forbidden"))
    # forbidden via user_tags
    store.add(_make_seg(source="v.mp4", start=5.0, end=8.0, user_tags=["forbidden"]))
    # bad via user_tags
    store.add(_make_seg(source="v.mp4", start=10.0, end=12.0, user_tags=["bad"]))
    # should NOT be in forbidden
    store.add(_make_seg(source="v.mp4", start=20.0, end=25.0, include_policy="required"))

    forbidden = store.get_forbidden_ranges()
    assert len(forbidden) == 3
    starts = {f[1] for f in forbidden}
    assert starts == {0.0, 5.0, 10.0}
    # required segment not included
    assert not any(f[1] == 20.0 for f in forbidden)


# ── Test 7: get_required_ranges() returns only required/recommended ───────────

def test_get_required_ranges(tmpdir):
    store = ManualSegmentsStore(tmpdir)
    store.add(_make_seg(source="v.mp4", start=0.0, end=3.0, include_policy="required"))
    store.add(_make_seg(source="v.mp4", start=5.0, end=8.0, include_policy="recommended"))
    store.add(_make_seg(source="v.mp4", start=10.0, end=12.0, user_tags=["required"]))
    # should NOT be in required
    store.add(_make_seg(source="v.mp4", start=20.0, end=25.0, include_policy="optional"))

    required = store.get_required_ranges()
    assert len(required) == 3
    starts = {r[1] for r in required}
    assert starts == {0.0, 5.0, 10.0}
    assert not any(r[1] == 20.0 for r in required)


# ── Test 8: has_any() returns False for empty store ───────────────────────────

def test_has_any_empty(tmpdir):
    store = ManualSegmentsStore(tmpdir)
    assert store.has_any() is False


def test_has_any_nonempty(tmpdir):
    store = ManualSegmentsStore(tmpdir)
    store.add(_make_seg())
    assert store.has_any() is True


# ── Test 9: tags can contain multiple values ──────────────────────────────────

def test_multiple_tags():
    tags = ["intro", "dynamic", "camera_move", "wide_shot"]
    seg = ManualSegment.create(
        source_file="v.mp4",
        start_time=0.0,
        end_time=5.0,
        user_tags=tags,
    )
    assert seg.user_tags == tags
    assert len(seg.user_tags) == 4


def test_multiple_tags_persisted(tmpdir):
    tags = ["intro", "dynamic", "camera_move"]
    store = ManualSegmentsStore(tmpdir)
    seg = _make_seg(user_tags=tags)
    store.add(seg)

    reloaded = ManualSegmentsStore(tmpdir)
    loaded_seg = reloaded.get_all()[0]
    assert loaded_seg.user_tags == tags


# ── Test 10: ManualSegment.from_dict roundtrip ───────────────────────────────

def test_from_dict_roundtrip():
    original = ManualSegment.create(
        source_file="/path/to/video.mp4",
        start_time=3.14,
        end_time=9.99,
        user_tags=["calm", "detail"],
        priority="low",
        include_policy="backup",
        user_note="nice close-up",
    )
    d = original.to_dict()
    restored = ManualSegment.from_dict(d)

    assert restored.manual_segment_id == original.manual_segment_id
    assert restored.source_file == original.source_file
    assert restored.start_time == original.start_time
    assert restored.end_time == original.end_time
    assert restored.duration == original.duration
    assert restored.user_tags == original.user_tags
    assert restored.priority == original.priority
    assert restored.include_policy == original.include_policy
    assert restored.user_note == original.user_note
    assert restored.status == original.status


def test_from_dict_ignores_unknown_keys():
    original = ManualSegment.create(source_file="v.mp4", start_time=0.0, end_time=2.0)
    d = original.to_dict()
    d["unknown_future_field"] = "some_value"
    # Should not raise
    restored = ManualSegment.from_dict(d)
    assert restored.manual_segment_id == original.manual_segment_id


# ── Additional: store.clear_all() ────────────────────────────────────────────

def test_clear_all(tmpdir):
    store = ManualSegmentsStore(tmpdir)
    store.add(_make_seg(source="a.mp4"))
    store.add(_make_seg(source="b.mp4"))
    store.add(_make_seg(source="c.mp4"))

    store.clear_all()
    assert store.get_all() == []
    assert store.has_any() is False

    # Verify on disk too
    reloaded = ManualSegmentsStore(tmpdir)
    assert reloaded.get_all() == []


# ── Additional: get_for_source() ─────────────────────────────────────────────

def test_get_for_source(tmpdir):
    store = ManualSegmentsStore(tmpdir)
    store.add(_make_seg(source="a.mp4", start=0.0, end=2.0))
    store.add(_make_seg(source="a.mp4", start=3.0, end=5.0))
    store.add(_make_seg(source="b.mp4", start=0.0, end=4.0))

    a_segs = store.get_for_source("a.mp4")
    b_segs = store.get_for_source("b.mp4")
    c_segs = store.get_for_source("c.mp4")

    assert len(a_segs) == 2
    assert len(b_segs) == 1
    assert len(c_segs) == 0
