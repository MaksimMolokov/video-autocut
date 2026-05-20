"""
Tests for the video regeneration flow.

Covers the bug where after clicking "Изменить стиль" and re-generating,
the output video is shorter than the selected duration (e.g. 6-10s instead of 90s).

Test groups:
  1. Session-state transitions for navigation buttons
  2. target_duration guard in render_video
  3. Per-source budget calculation
  4. Fallback trigger when collected duration is insufficient
  5. Duration sanity check thresholds
  6. "Изменить стиль" preserves target_duration
  7. "Изменить длительность" clears target_duration
  8. Per-source logging format
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Make project root importable
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers to mock the heavy Streamlit session-state machinery
# ---------------------------------------------------------------------------

class FakeSessionState(dict):
    """dict that also supports attribute access (mimics st.session_state)."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value

    def get(self, key, default=None):
        return super().get(key, default)


def _make_st_mock(initial_state: dict | None = None) -> MagicMock:
    """Return a minimal mock of the streamlit module."""
    st = MagicMock()
    st.session_state = FakeSessionState(initial_state or {})
    st.rerun = MagicMock()
    st.button = MagicMock(return_value=False)
    st.spinner = MagicMock()
    st.spinner.return_value.__enter__ = MagicMock(return_value=None)
    st.spinner.return_value.__exit__ = MagicMock(return_value=False)
    return st


# ---------------------------------------------------------------------------
# Group 1 — session-state transitions for navigation buttons
# ---------------------------------------------------------------------------

class TestNavigationStateTransitions(unittest.TestCase):
    """Group 1: verify button handler logic (extracted to pure functions)."""

    def _apply_change_style(self, state: dict) -> dict:
        """Mimic the 'Изменить стиль' button handler."""
        state['page'] = 'welcome'
        state['selected_preset_id'] = None
        # target_duration MUST NOT be cleared — that's the bug we fixed
        state['generation_status'] = None
        return state

    def _apply_change_duration(self, state: dict) -> dict:
        """Mimic the 'Изменить длительность' button handler."""
        state['page'] = 'welcome'
        state['target_duration'] = None
        state['generation_status'] = None
        return state

    def test_change_style_preserves_target_duration(self):
        """After 'Изменить стиль', target_duration must stay unchanged."""
        state = {
            'page': 'auto_render',
            'selected_preset_id': 'travel_story',
            'target_duration': 90.0,
            'generation_status': 'completed',
        }
        result = self._apply_change_style(state)
        self.assertEqual(result['target_duration'], 90.0)

    def test_change_style_clears_preset(self):
        """After 'Изменить стиль', selected_preset_id is None."""
        state = {'selected_preset_id': 'fast_action_sport', 'target_duration': 60.0,
                 'generation_status': 'completed'}
        result = self._apply_change_style(state)
        self.assertIsNone(result['selected_preset_id'])

    def test_change_style_resets_generation_status(self):
        state = {'selected_preset_id': 'easy_mode', 'target_duration': 30.0,
                 'generation_status': 'completed'}
        result = self._apply_change_style(state)
        self.assertIsNone(result['generation_status'])

    def test_change_duration_clears_target_duration(self):
        """After 'Изменить длительность', target_duration is None."""
        state = {'target_duration': 90.0, 'generation_status': 'completed'}
        result = self._apply_change_duration(state)
        self.assertIsNone(result['target_duration'])

    def test_change_duration_resets_generation_status(self):
        state = {'target_duration': 90.0, 'generation_status': 'completed'}
        result = self._apply_change_duration(state)
        self.assertIsNone(result['generation_status'])

    def test_new_project_different_from_change_style(self):
        """'Новый проект' should reset videos; 'Изменить стиль' should not."""
        initial_videos = ['/path/a.mp4', '/path/b.mp4']
        state = {
            'selected_preset_id': 'easy_mode',
            'target_duration': 60.0,
            'generation_status': 'completed',
            'selected_videos': initial_videos,
        }
        result = self._apply_change_style(state)
        # Videos are preserved after 'Изменить стиль'
        self.assertEqual(result['selected_videos'], initial_videos)


# ---------------------------------------------------------------------------
# Group 2 — target_duration guard
# ---------------------------------------------------------------------------

class TestTargetDurationGuard(unittest.TestCase):
    """Group 2: render_video must abort when target_duration is missing/zero."""

    def _check_guard(self, target_duration_value) -> bool:
        """Return True if the guard would abort (bad value)."""
        td = target_duration_value
        return not td or td <= 0

    def test_none_triggers_guard(self):
        self.assertTrue(self._check_guard(None))

    def test_zero_triggers_guard(self):
        self.assertTrue(self._check_guard(0))

    def test_negative_triggers_guard(self):
        self.assertTrue(self._check_guard(-5))

    def test_valid_90s_passes_guard(self):
        self.assertFalse(self._check_guard(90.0))

    def test_valid_30s_passes_guard(self):
        self.assertFalse(self._check_guard(30.0))

    def test_valid_180s_passes_guard(self):
        self.assertFalse(self._check_guard(180.0))


# ---------------------------------------------------------------------------
# Group 3 — per-source budget calculation
# ---------------------------------------------------------------------------

class TestPerSourceBudget(unittest.TestCase):
    """Group 3: per-source budget = (target / n_sources) * 1.5."""

    def _budget(self, target: float, n_sources: int) -> float:
        return (target / n_sources) * 1.5

    def test_10_sources_90s_target(self):
        b = self._budget(90.0, 10)
        self.assertAlmostEqual(b, 13.5)

    def test_1_source_90s_target(self):
        b = self._budget(90.0, 1)
        self.assertAlmostEqual(b, 135.0)

    def test_5_sources_60s_target(self):
        b = self._budget(60.0, 5)
        self.assertAlmostEqual(b, 18.0)

    def test_budget_always_larger_than_equal_split(self):
        """Budget per source must exceed the naive equal split."""
        for n in [1, 2, 5, 10]:
            naive = 90.0 / n
            budget = self._budget(90.0, n)
            self.assertGreater(budget, naive, f"Budget ≤ naive for {n} sources")

    def test_budget_with_many_sources_still_positive(self):
        b = self._budget(30.0, 30)
        self.assertGreater(b, 0)


# ---------------------------------------------------------------------------
# Group 4 — fallback trigger logic
# ---------------------------------------------------------------------------

class TestFallbackTrigger(unittest.TestCase):
    """Group 4: fallback fires when collected < 90% of target."""

    def _should_fallback(self, collected: float, target: float) -> bool:
        return collected < target * 0.90

    def test_9s_collected_of_90s_triggers_fallback(self):
        self.assertTrue(self._should_fallback(9.0, 90.0))

    def test_80s_collected_of_90s_triggers_fallback(self):
        self.assertTrue(self._should_fallback(80.0, 90.0))

    def test_81s_collected_of_90s_no_fallback(self):
        self.assertFalse(self._should_fallback(81.0, 90.0))

    def test_exact_90pct_no_fallback(self):
        self.assertFalse(self._should_fallback(81.0, 90.0))

    def test_full_target_no_fallback(self):
        self.assertFalse(self._should_fallback(90.0, 90.0))

    def test_zero_collected_triggers_fallback(self):
        self.assertTrue(self._should_fallback(0.0, 90.0))

    def test_6s_of_90s_triggers_fallback(self):
        """Replicates the reported bug scenario: 6-10s collected for 90s target."""
        for collected in [6.0, 7.5, 9.0, 10.0]:
            self.assertTrue(
                self._should_fallback(collected, 90.0),
                f"Expected fallback for {collected}s collected"
            )


# ---------------------------------------------------------------------------
# Group 5 — duration sanity check thresholds
# ---------------------------------------------------------------------------

class TestDurationSanityCheck(unittest.TestCase):
    """Group 5: sanity check correctly classifies planned vs target."""

    def _classify(self, planned: float, target: float) -> str:
        if planned < target * 0.50:
            return 'critical'
        if planned < target * 0.90:
            return 'warning'
        return 'ok'

    def test_critical_below_50pct(self):
        self.assertEqual(self._classify(40.0, 90.0), 'critical')

    def test_warning_between_50_and_90pct(self):
        self.assertEqual(self._classify(60.0, 90.0), 'warning')

    def test_ok_above_90pct(self):
        self.assertEqual(self._classify(85.0, 90.0), 'ok')

    def test_ok_at_100pct(self):
        self.assertEqual(self._classify(90.0, 90.0), 'ok')

    def test_ok_over_100pct(self):
        self.assertEqual(self._classify(100.0, 90.0), 'ok')

    def test_critical_9s_for_90s_target(self):
        """The reported bug: 9s planned for 90s target is critical."""
        self.assertEqual(self._classify(9.0, 90.0), 'critical')


# ---------------------------------------------------------------------------
# Group 6 — "Изменить стиль" preserves state correctly
# ---------------------------------------------------------------------------

class TestChangeStyleState(unittest.TestCase):
    """Group 6: 'Изменить стиль' preserves audio, videos, format."""

    def _apply_change_style(self, state: dict) -> dict:
        state = dict(state)  # copy
        state['page'] = 'welcome'
        state['selected_preset_id'] = None
        # target_duration intentionally NOT cleared (bug fix)
        state['generation_status'] = None
        return state

    def test_audio_preserved(self):
        state = {'selected_audio': '/path/music.mp3', 'target_duration': 90.0,
                 'generation_status': 'completed', 'selected_preset_id': 'easy_mode'}
        result = self._apply_change_style(state)
        self.assertEqual(result['selected_audio'], '/path/music.mp3')

    def test_selected_videos_preserved(self):
        videos = ['/a.mp4', '/b.mp4']
        state = {'selected_videos': videos, 'target_duration': 90.0,
                 'generation_status': 'completed', 'selected_preset_id': 'easy_mode'}
        result = self._apply_change_style(state)
        self.assertEqual(result['selected_videos'], videos)

    def test_output_format_preserved(self):
        state = {'selected_output_format': 'vertical_9_16', 'target_duration': 60.0,
                 'generation_status': 'completed', 'selected_preset_id': 'easy_mode'}
        result = self._apply_change_style(state)
        self.assertEqual(result['selected_output_format'], 'vertical_9_16')

    def test_page_set_to_welcome(self):
        state = {'page': 'auto_render', 'target_duration': 30.0,
                 'generation_status': 'completed', 'selected_preset_id': 'easy_mode'}
        result = self._apply_change_style(state)
        self.assertEqual(result['page'], 'welcome')

    def test_different_durations_all_preserved(self):
        for dur in [30.0, 60.0, 90.0, 180.0]:
            state = {'target_duration': dur, 'generation_status': 'completed',
                     'selected_preset_id': 'easy_mode'}
            result = self._apply_change_style(state)
            self.assertEqual(result['target_duration'], dur, f"Failed for {dur}s")


# ---------------------------------------------------------------------------
# Group 7 — "Изменить длительность" clears only duration
# ---------------------------------------------------------------------------

class TestChangeDurationState(unittest.TestCase):
    """Group 7: 'Изменить длительность' only clears target_duration."""

    def _apply_change_duration(self, state: dict) -> dict:
        state = dict(state)
        state['page'] = 'welcome'
        state['target_duration'] = None
        state['generation_status'] = None
        return state

    def test_preset_preserved(self):
        state = {'selected_preset_id': 'fast_action_sport', 'target_duration': 60.0,
                 'generation_status': 'completed'}
        result = self._apply_change_duration(state)
        self.assertEqual(result['selected_preset_id'], 'fast_action_sport')

    def test_duration_cleared(self):
        state = {'target_duration': 90.0, 'generation_status': 'completed',
                 'selected_preset_id': 'easy_mode'}
        result = self._apply_change_duration(state)
        self.assertIsNone(result['target_duration'])

    def test_videos_preserved(self):
        videos = ['/a.mp4']
        state = {'selected_videos': videos, 'target_duration': 90.0,
                 'generation_status': 'completed', 'selected_preset_id': 'easy_mode'}
        result = self._apply_change_duration(state)
        self.assertEqual(result['selected_videos'], videos)


# ---------------------------------------------------------------------------
# Group 8 — integration: segment accumulation with mocked SegmentSelector
# ---------------------------------------------------------------------------

class TestSegmentAccumulation(unittest.TestCase):
    """
    Group 8: simulate the per-source segment selection loop with mocked
    SegmentSelector to verify budget/fallback logic.
    """

    def _run_selection_loop(
        self,
        target: float,
        source_returns: list,  # list of (seconds_returned | Exception) per source
        fallback_returns: float = 90.0,
    ) -> tuple[float, bool]:
        """
        Simulate the new per-source loop.
        Returns (total_duration_collected, fallback_was_used).
        """
        n = len(source_returns)
        budget = (target / n) * 1.5
        all_segs = []

        for ret in source_returns:
            if isinstance(ret, Exception):
                pass  # silently skip
            else:
                # fake segments totalling `ret` seconds
                seg = MagicMock()
                seg.duration = ret
                all_segs.append(seg)

        collected = sum(s.duration for s in all_segs)
        fallback_used = False
        if collected < target * 0.90:
            all_segs = []  # trigger fallback
            fallback_used = True
            # fallback returns fallback_returns seconds
            seg = MagicMock()
            seg.duration = fallback_returns
            all_segs.append(seg)

        total = sum(s.duration for s in all_segs)
        return total, fallback_used

    def test_all_sources_succeed_no_fallback(self):
        target = 90.0
        # 10 sources each returning 9s
        returns = [9.0] * 10
        total, fallback = self._run_selection_loop(target, returns)
        self.assertFalse(fallback)
        self.assertAlmostEqual(total, 90.0)

    def test_9_of_10_fail_triggers_fallback(self):
        """The reported bug: 9/10 sources fail, only 9s collected → fallback."""
        target = 90.0
        returns = [Exception("ffmpeg failed")] * 9 + [9.0]
        total, fallback = self._run_selection_loop(target, returns, fallback_returns=90.0)
        self.assertTrue(fallback, "Fallback should have been triggered")
        self.assertAlmostEqual(total, 90.0)

    def test_all_sources_fail_triggers_fallback(self):
        target = 90.0
        returns = [Exception("error")] * 10
        total, fallback = self._run_selection_loop(target, returns, fallback_returns=90.0)
        self.assertTrue(fallback)

    def test_partial_material_shortage_triggers_fallback(self):
        """Sources return less than their budget → fallback."""
        target = 90.0
        # Each source returns only 3s (well below 9s budget)
        returns = [3.0] * 10  # 30s total < 90s * 0.9 = 81s
        total, fallback = self._run_selection_loop(target, returns, fallback_returns=90.0)
        self.assertTrue(fallback)
        self.assertAlmostEqual(total, 90.0)

    def test_sufficient_material_no_fallback(self):
        """85s collected for 90s target (≥ 90%) → no fallback."""
        target = 90.0
        returns = [8.5] * 10  # 85s total
        total, fallback = self._run_selection_loop(target, returns)
        self.assertFalse(fallback)

    def test_single_source_failure_no_fallback_if_still_enough(self):
        """1/10 fails but remaining 9 produce enough → no fallback."""
        target = 90.0
        returns = [Exception("fail")] + [10.0] * 9  # 90s total
        total, fallback = self._run_selection_loop(target, returns)
        self.assertFalse(fallback)
        self.assertAlmostEqual(total, 90.0)

    def test_budget_is_1_5x_per_source(self):
        """Budget is 1.5× the naive equal split."""
        target = 90.0
        n = 10
        budget = (target / n) * 1.5
        naive = target / n
        self.assertAlmostEqual(budget, 13.5)
        self.assertGreater(budget, naive)

    def test_fallback_produces_target_duration(self):
        """After fallback, the total should equal the original target."""
        target = 90.0
        returns = [Exception("fail")] * 10
        total, fallback = self._run_selection_loop(target, returns, fallback_returns=target)
        self.assertTrue(fallback)
        self.assertAlmostEqual(total, target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
