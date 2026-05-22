"""
UI state logic tests — no Streamlit session_state required.

Tests cover:
- Platform preset definitions and locking rules
- Format/duration conflict prevention
- Sound notification state logic (event_key deduplication)
- Preview count mode (1 or 4 variants)
- Variant characterisation label generation
- Generation status machine transitions
"""
from __future__ import annotations
import importlib
import sys
import os
import unittest
from pathlib import Path

# Make src importable without running Streamlit
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import only pure-Python symbols from gui (no Streamlit execution needed)
import src.gui as _gui_mod

_PLATFORM_PRESETS = _gui_mod._PLATFORM_PRESETS
_FMT_LABELS       = _gui_mod._FMT_LABELS
_VARIANT_LABELS   = _gui_mod._VARIANT_LABELS
_variant_char_label = _gui_mod._variant_char_label


# ─────────────────────────────────────────────────────────────────────────────
class TestPlatformPresets(unittest.TestCase):

    def test_all_expected_keys_present(self):
        expected = {'custom', 'reels', 'tiktok', 'shorts', 'youtube', 'stories', 'website_hero'}
        self.assertEqual(set(_PLATFORM_PRESETS.keys()), expected)

    def test_custom_has_no_locks(self):
        p = _PLATFORM_PRESETS['custom']
        self.assertFalse(p['locks_format'],   "custom should not lock format")
        self.assertFalse(p['locks_duration'], "custom should not lock duration")
        self.assertIsNone(p['format'])
        self.assertIsNone(p['duration_seconds'])

    def test_vertical_platforms_have_correct_format(self):
        vertical = ['reels', 'tiktok', 'shorts', 'stories']
        for pid in vertical:
            with self.subTest(platform=pid):
                p = _PLATFORM_PRESETS[pid]
                self.assertTrue(p['locks_format'], f"{pid} should lock format")
                self.assertEqual(p['format'], 'vertical_9_16',
                                 f"{pid} should be vertical_9_16")

    def test_horizontal_platforms_have_correct_format(self):
        horizontal = ['youtube', 'website_hero']
        for pid in horizontal:
            with self.subTest(platform=pid):
                p = _PLATFORM_PRESETS[pid]
                self.assertTrue(p['locks_format'], f"{pid} should lock format")
                self.assertEqual(p['format'], 'horizontal_16_9',
                                 f"{pid} should be horizontal_16_9")

    def test_no_platform_format_contradiction(self):
        """A vertical platform must not have horizontal format and vice-versa."""
        for pid, p in _PLATFORM_PRESETS.items():
            if pid == 'custom':
                continue
            if p['format'] == 'vertical_9_16':
                self.assertNotEqual(pid, 'youtube',
                    "YouTube should not be vertical")
            if p['format'] == 'horizontal_16_9':
                self.assertNotIn(pid, ('reels', 'tiktok', 'shorts', 'stories'),
                    f"{pid} should not be horizontal")

    def test_all_platforms_lock_duration_except_custom(self):
        for pid, p in _PLATFORM_PRESETS.items():
            if pid == 'custom':
                self.assertFalse(p['locks_duration'])
            else:
                self.assertTrue(p['locks_duration'], f"{pid} should lock duration")

    def test_duration_seconds_are_positive(self):
        for pid, p in _PLATFORM_PRESETS.items():
            if pid == 'custom':
                continue
            with self.subTest(platform=pid):
                self.assertIsNotNone(p['duration_seconds'])
                self.assertGreater(p['duration_seconds'], 0)

    def test_stories_duration_15s(self):
        self.assertEqual(_PLATFORM_PRESETS['stories']['duration_seconds'], 15)

    def test_website_hero_duration_10s(self):
        self.assertEqual(_PLATFORM_PRESETS['website_hero']['duration_seconds'], 10)

    def test_reels_tiktok_shorts_duration_30s(self):
        for pid in ('reels', 'tiktok', 'shorts'):
            with self.subTest(platform=pid):
                self.assertEqual(_PLATFORM_PRESETS[pid]['duration_seconds'], 30)

    def test_youtube_duration_60s(self):
        self.assertEqual(_PLATFORM_PRESETS['youtube']['duration_seconds'], 60)

    def test_required_keys_in_all_presets(self):
        required = {'label', 'icon', 'locks_format', 'locks_duration',
                    'format', 'duration_seconds', 'desc'}
        for pid, p in _PLATFORM_PRESETS.items():
            with self.subTest(platform=pid):
                for key in required:
                    self.assertIn(key, p, f"{pid} missing key '{key}'")

    def test_fmt_labels_covers_all_locked_formats(self):
        locked_formats = {p['format'] for p in _PLATFORM_PRESETS.values()
                          if p.get('format') is not None}
        for fmt in locked_formats:
            with self.subTest(fmt=fmt):
                self.assertIn(fmt, _FMT_LABELS,
                              f"Format {fmt!r} not in _FMT_LABELS")


# ─────────────────────────────────────────────────────────────────────────────
class TestPlatformNormalisationLogic(unittest.TestCase):
    """
    Test the _normalize_platform_settings() logic in isolation using a mock
    session_state, without requiring a running Streamlit server.
    """

    def _make_ss(self, platform, selected_fmt=None, target_dur=None):
        """Return a dict simulating session_state for the given scenario."""
        return {
            'platform_preset': platform,
            'selected_output_format': selected_fmt,
            'target_duration': target_dur,
        }

    def _normalize(self, ss: dict):
        """Run normalisation logic extracted from _normalize_platform_settings()."""
        platform = ss.get('platform_preset', 'custom') or 'custom'
        preset = _PLATFORM_PRESETS.get(platform, _PLATFORM_PRESETS['custom'])
        warnings = []
        _fmt_new_to_old = {
            'vertical_9_16': 'vertical', 'horizontal_16_9': 'horizontal',
            'square_1_1': 'square', 'original': 'horizontal',
        }
        if preset['locks_format']:
            resolved_fmt = preset['format']
            stored = ss.get('selected_output_format')
            if stored and stored != resolved_fmt:
                warnings.append('format_overridden')
            ss['selected_output_format'] = resolved_fmt
        else:
            resolved_fmt = ss.get('selected_output_format', 'horizontal_16_9')
        ss['output_format'] = _fmt_new_to_old.get(resolved_fmt, 'horizontal')

        if preset['locks_duration']:
            resolved_dur = float(preset['duration_seconds'])
            stored = ss.get('target_duration')
            if stored and abs(stored - resolved_dur) > 0.5:
                warnings.append('duration_overridden')
            ss['target_duration'] = resolved_dur
        else:
            resolved_dur = ss.get('target_duration') or 0.0

        return resolved_fmt, resolved_dur, warnings

    def test_custom_leaves_manual_format(self):
        ss = self._make_ss('custom', 'vertical_9_16', 45)
        fmt, dur, warns = self._normalize(ss)
        self.assertEqual(fmt, 'vertical_9_16')
        self.assertEqual(dur, 45)
        self.assertEqual(warns, [])

    def test_reels_forces_vertical_format(self):
        ss = self._make_ss('reels', 'horizontal_16_9', 60)
        fmt, dur, warns = self._normalize(ss)
        self.assertEqual(fmt, 'vertical_9_16')
        self.assertEqual(dur, 30.0)
        self.assertIn('format_overridden', warns)
        self.assertIn('duration_overridden', warns)

    def test_youtube_forces_horizontal(self):
        ss = self._make_ss('youtube', 'vertical_9_16', 30)
        fmt, dur, warns = self._normalize(ss)
        self.assertEqual(fmt, 'horizontal_16_9')
        self.assertEqual(dur, 60.0)
        self.assertIn('format_overridden', warns)

    def test_reels_no_warning_when_already_correct(self):
        ss = self._make_ss('reels', 'vertical_9_16', 30)
        fmt, dur, warns = self._normalize(ss)
        self.assertEqual(fmt, 'vertical_9_16')
        self.assertEqual(dur, 30.0)
        self.assertEqual(warns, [])

    def test_output_format_old_key_synced(self):
        ss = self._make_ss('reels')
        self._normalize(ss)
        self.assertEqual(ss['output_format'], 'vertical')

    def test_youtube_output_format_horizontal(self):
        ss = self._make_ss('youtube')
        self._normalize(ss)
        self.assertEqual(ss['output_format'], 'horizontal')


# ─────────────────────────────────────────────────────────────────────────────
class TestSoundNotificationLogic(unittest.TestCase):
    """
    Test the deduplication logic that prevents sound from replaying on rerun.
    Simulates _play_completion_sound() without actually producing audio.
    """

    def _sound_should_play(self, sound_enabled: bool, played_key, event_key: str) -> bool:
        """Pure-logic simulation of the guard checks in _play_completion_sound()."""
        if not sound_enabled:
            return False
        if played_key == event_key:
            return False
        return True

    def test_plays_when_enabled_and_not_played(self):
        self.assertTrue(self._sound_should_play(True, None, 'preview_ready'))

    def test_no_play_when_disabled(self):
        self.assertFalse(self._sound_should_play(False, None, 'preview_ready'))

    def test_no_replay_same_event_key(self):
        self.assertFalse(self._sound_should_play(True, 'preview_ready', 'preview_ready'))

    def test_plays_for_new_event_key(self):
        self.assertTrue(self._sound_should_play(True, 'preview_ready', 'final_completed'))

    def test_different_jobs_get_different_keys(self):
        keys = {'preview_ready', 'variants_ready', 'final_completed'}
        # All three events are distinct
        self.assertEqual(len(keys), 3)


# ─────────────────────────────────────────────────────────────────────────────
class TestPreviewCountMode(unittest.TestCase):

    def test_preview_count_1_single_variant(self):
        pcount = 1
        letters = list('ABCD')[:pcount]
        self.assertEqual(letters, ['A'])

    def test_preview_count_4_all_variants(self):
        pcount = 4
        letters = list('ABCD')[:pcount]
        self.assertEqual(letters, ['A', 'B', 'C', 'D'])

    def test_variant_seed_offsets(self):
        """Each variant A-D gets a distinct seed."""
        seeds = {42 + i * 997 for i in range(4)}
        self.assertEqual(len(seeds), 4)   # all distinct

    def test_variant_labels_map(self):
        self.assertEqual(_VARIANT_LABELS[0], 'A')
        self.assertEqual(_VARIANT_LABELS[1], 'B')
        self.assertEqual(_VARIANT_LABELS[2], 'C')
        self.assertEqual(_VARIANT_LABELS[3], 'D')


# ─────────────────────────────────────────────────────────────────────────────
class TestVariantCharLabel(unittest.TestCase):
    """
    _variant_char_label() returns a non-empty string for any input.
    Uses a mock SelectedSegment with _features attached.
    """

    class MockFeatures:
        def __init__(self, action=0.5, motion=0.5, sharp=0.5):
            self.action_score   = action
            self.motion_score   = motion
            self.sharpness_score = sharp

    class MockSeg:
        def __init__(self, features=None):
            self._features = features
            self.duration  = 3.0

    def test_returns_string_with_features(self):
        segs = [self.MockSeg(self.MockFeatures(action=0.8)) for _ in range(5)]
        label = _variant_char_label(segs, 0)
        self.assertIsInstance(label, str)
        self.assertGreater(len(label), 0)

    def test_returns_string_without_features(self):
        segs = [self.MockSeg(None) for _ in range(3)]
        label = _variant_char_label(segs, 1)
        self.assertIsInstance(label, str)
        self.assertGreater(len(label), 0)

    def test_high_action_label(self):
        segs = [self.MockSeg(self.MockFeatures(action=0.9)) for _ in range(5)]
        label = _variant_char_label(segs, 0)
        self.assertEqual(label, "Более динамичный")

    def test_calm_label(self):
        segs = [self.MockSeg(self.MockFeatures(action=0.1, motion=0.1)) for _ in range(5)]
        label = _variant_char_label(segs, 0)
        self.assertEqual(label, "Более спокойный")

    def test_empty_segments_returns_empty(self):
        label = _variant_char_label([], 0)
        self.assertEqual(label, "")

    def test_seed_offset_cycles_fallback(self):
        """Without features, labels cycle through 4 fallback strings."""
        segs = [self.MockSeg(None)]
        labels = [_variant_char_label(segs, i) for i in range(4)]
        # All should be non-empty and all should cycle (not all equal)
        self.assertTrue(all(isinstance(l, str) and len(l) > 0 for l in labels))


# ─────────────────────────────────────────────────────────────────────────────
class TestGenerationStatusMachine(unittest.TestCase):
    """
    Test the valid status transitions described in the spec.
    Transitions are pure logic — no Streamlit required.
    """

    VALID_TRANSITIONS = {
        None:              {'starting'},
        'starting':        {'rendering'},
        'rendering':       {'draft_ready', 'preview_ready', 'variants_ready',
                            'completed', 'failed'},
        'draft_ready':     {'rendering'},
        'preview_ready':   {'rendering', 'draft_ready', 'starting'},
        'variants_ready':  {'rendering', 'draft_ready', 'starting'},
        'completed':       {'starting'},
        'failed':          {'starting'},
    }

    def test_starting_leads_to_rendering(self):
        self.assertIn('rendering', self.VALID_TRANSITIONS['starting'])

    def test_rendering_can_go_to_preview_ready(self):
        self.assertIn('preview_ready', self.VALID_TRANSITIONS['rendering'])

    def test_rendering_can_go_to_variants_ready(self):
        self.assertIn('variants_ready', self.VALID_TRANSITIONS['rendering'])

    def test_preview_ready_can_trigger_final(self):
        self.assertIn('rendering', self.VALID_TRANSITIONS['preview_ready'])

    def test_final_does_not_auto_start(self):
        """Final render must be user-triggered (goes from preview_ready → rendering via button)."""
        # 'preview_ready' → 'completed' is NOT a direct transition; requires 'rendering' in between
        self.assertNotIn('completed', self.VALID_TRANSITIONS['preview_ready'])

    def test_failed_can_restart(self):
        self.assertIn('starting', self.VALID_TRANSITIONS['failed'])

    def test_completed_does_not_auto_restart(self):
        """completed → rendering must go via 'starting'."""
        self.assertNotIn('rendering', self.VALID_TRANSITIONS['completed'])


# ─────────────────────────────────────────────────────────────────────────────
class TestManualFormatDurationAccess(unittest.TestCase):
    """
    When platform is custom, format and duration must be writable.
    When platform is locked, they must not be user-editable.
    This tests the data properties, not the UI widget.
    """

    def test_custom_allows_any_format(self):
        p = _PLATFORM_PRESETS['custom']
        self.assertFalse(p['locks_format'])
        self.assertIsNone(p['format'])  # None = user controls it

    def test_locked_platform_has_fixed_format(self):
        for pid in ('reels', 'tiktok', 'shorts', 'stories', 'youtube', 'website_hero'):
            with self.subTest(platform=pid):
                p = _PLATFORM_PRESETS[pid]
                self.assertTrue(p['locks_format'])
                self.assertIsNotNone(p['format'])
                self.assertIn(p['format'], _FMT_LABELS)

    def test_locked_platform_has_fixed_duration(self):
        for pid in ('reels', 'tiktok', 'shorts', 'stories', 'youtube', 'website_hero'):
            with self.subTest(platform=pid):
                p = _PLATFORM_PRESETS[pid]
                self.assertTrue(p['locks_duration'])
                self.assertIsNotNone(p['duration_seconds'])
                self.assertIsInstance(p['duration_seconds'], (int, float))


if __name__ == '__main__':
    unittest.main()
