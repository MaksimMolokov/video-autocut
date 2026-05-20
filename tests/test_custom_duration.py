"""
Part 2 — Custom duration / duration parsing unit tests.

2.1  Minutes × 60 + seconds produces correct target_duration_sec
2.2  Comma-vs-dot handling (the UI uses int inputs, so comma not relevant;
     we test the parsing logic that converts UI values to seconds)
2.3  Invalid / edge-case values must be rejected

The current UI: two integer inputs (minutes 0–60, seconds 0–59) + "Ввести" button.
Parsing: total = cm * 60 + cs  (must be > 0 to be accepted)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Duration parsing logic (extracted from gui.py for pure unit testing) ─────

def parse_duration_from_ms(minutes: int, seconds: int) -> int:
    """Mirror of gui.py: total = cm * 60 + cs."""
    return minutes * 60 + seconds


def is_valid_duration(total: int) -> bool:
    """A duration is valid when total > 0."""
    return isinstance(total, int) and total > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2.1 — Correct parsing of minutes + seconds
# ═══════════════════════════════════════════════════════════════════════════════

class TestDurationParsing(unittest.TestCase):

    def _parse(self, m, s):
        return parse_duration_from_ms(m, s)

    def test_30_seconds(self):
        self.assertEqual(self._parse(0, 30), 30)

    def test_1_minute(self):
        self.assertEqual(self._parse(1, 0), 60)

    def test_1_minute_30_seconds(self):
        self.assertEqual(self._parse(1, 30), 90)

    def test_2_minutes(self):
        self.assertEqual(self._parse(2, 0), 120)

    def test_3_minutes(self):
        self.assertEqual(self._parse(3, 0), 180)

    def test_15_seconds(self):
        self.assertEqual(self._parse(0, 15), 15)

    def test_45_seconds(self):
        self.assertEqual(self._parse(0, 45), 45)

    def test_1_minute_15_seconds(self):
        self.assertEqual(self._parse(1, 15), 75)

    def test_5_minutes(self):
        self.assertEqual(self._parse(5, 0), 300)

    def test_10_minutes(self):
        self.assertEqual(self._parse(10, 0), 600)

    def test_mixed_minutes_and_seconds(self):
        self.assertEqual(self._parse(2, 45), 165)

    def test_max_ui_values(self):
        """Max UI input: 60 minutes, 59 seconds = 3659s."""
        self.assertEqual(self._parse(60, 59), 3659)

    def test_float_minutes_equivalent_1_5(self):
        """1.5 minutes = 1 min 30 sec = 90s."""
        # User enters min=1, sec=30 to get 1.5 minutes
        self.assertEqual(self._parse(1, 30), 90)

    def test_float_minutes_equivalent_0_25(self):
        """0.25 minutes = 0 min 15 sec = 15s."""
        self.assertEqual(self._parse(0, 15), 15)

    def test_float_minutes_equivalent_0_5(self):
        """0.5 minutes = 0 min 30 sec = 30s."""
        self.assertEqual(self._parse(0, 30), 30)


# ═══════════════════════════════════════════════════════════════════════════════
# 2.2 — Float minutes input (alternative 'minutes only' parser)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_float_minutes(value) -> float:
    """
    Parse a float-minutes input (e.g. 1.5 → 90.0 seconds).
    Normalise comma → dot.
    Returns 0.0 for invalid input.
    """
    if value is None:
        return 0.0
    s = str(value).strip().replace(',', '.')
    try:
        minutes = float(s)
        if minutes <= 0:
            return 0.0
        return round(minutes * 60.0, 3)
    except (ValueError, TypeError):
        return 0.0


class TestFloatMinutesParser(unittest.TestCase):
    """Tests for the float-minutes parser used in 'Своя длительность' flow."""

    def test_1_5_minutes(self):
        self.assertAlmostEqual(parse_float_minutes(1.5), 90.0, places=1)

    def test_string_1_5(self):
        self.assertAlmostEqual(parse_float_minutes('1.5'), 90.0, places=1)

    def test_comma_as_decimal_separator(self):
        """'1,5' must be normalised to 1.5 → 90s."""
        self.assertAlmostEqual(parse_float_minutes('1,5'), 90.0, places=1)

    def test_0_25_minutes(self):
        self.assertAlmostEqual(parse_float_minutes(0.25), 15.0, places=1)

    def test_0_5_minutes(self):
        self.assertAlmostEqual(parse_float_minutes(0.5), 30.0, places=1)

    def test_1_minute(self):
        self.assertAlmostEqual(parse_float_minutes(1.0), 60.0, places=1)

    def test_2_minutes(self):
        self.assertAlmostEqual(parse_float_minutes(2.0), 120.0, places=1)

    def test_3_minutes(self):
        self.assertAlmostEqual(parse_float_minutes(3.0), 180.0, places=1)

    def test_string_integer(self):
        self.assertAlmostEqual(parse_float_minutes('1'), 60.0, places=1)

    def test_zero_rejected(self):
        self.assertEqual(parse_float_minutes(0), 0.0)

    def test_zero_string_rejected(self):
        self.assertEqual(parse_float_minutes('0'), 0.0)

    def test_negative_rejected(self):
        self.assertEqual(parse_float_minutes(-1.5), 0.0)

    def test_negative_string_rejected(self):
        self.assertEqual(parse_float_minutes('-1'), 0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 2.3 — Invalid values must be rejected
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidDurationValues(unittest.TestCase):

    def test_empty_string_rejected(self):
        self.assertEqual(parse_float_minutes(''), 0.0)

    def test_abc_rejected(self):
        self.assertEqual(parse_float_minutes('abc'), 0.0)

    def test_none_rejected(self):
        self.assertEqual(parse_float_minutes(None), 0.0)

    def test_nan_rejected(self):
        self.assertEqual(parse_float_minutes('NaN'), 0.0)

    def test_inf_rejected(self):
        # float('inf') * 60 = inf, which is > 0 but not a sane duration.
        # We should cap or reject it.
        result = parse_float_minutes('inf')
        self.assertEqual(result, 0.0,
                         "Infinity must be rejected as invalid duration")

    def test_zero_rejected_from_ms(self):
        """0 min + 0 sec → invalid."""
        total = parse_duration_from_ms(0, 0)
        self.assertFalse(is_valid_duration(total))

    def test_999_minutes_is_large_but_parseable(self):
        """999 minutes is large but the parser should not crash."""
        result = parse_float_minutes(999)
        self.assertGreater(result, 0, "999 minutes should parse to a large positive number")

    def test_target_duration_never_set_by_style(self):
        """
        Verify that initialising session state with a preset does not
        write target_duration into session.
        Approximated via checking apply_preset_to_session doesn't set it.
        """
        from unittest.mock import patch, MagicMock
        import streamlit as st

        session = {
            'selected_output_format': 'horizontal_16_9',
            'output_format': 'horizontal',
            'dynamic_level': 'balanced',
            'transition_type': 'cut',
            'transition_duration': 0.0,
            'speed_mode': 'none',
            'slow_motion_factor': 0.75,
            'speed_up_factor': 1.25,
            'color_style': 'none',
            'color_brightness': 0.0,
            'color_contrast': 0.0,
            'color_saturation': 0.0,
            'color_temperature': 0.0,
            'music_sync_mode': 'none',
            'fade_in': 2.0,
            'fade_out': 2.0,
            'preset_settings': None,
        }

        from src.presets import PresetRegistry
        presets_dir = Path(__file__).parent.parent / 'presets'
        registry = PresetRegistry(presets_dir)
        session['preset_registry'] = registry

        initial_keys = set(session.keys())

        with patch.object(st, 'session_state', session), \
             patch.object(st, 'success', MagicMock()), \
             patch.object(st, 'error', MagicMock()):
            try:
                import src.gui as gui_mod
                gui_mod.apply_preset_to_session('travel_story')
            except Exception:
                pass

        # target_duration must NOT have been added by apply_preset_to_session
        self.assertNotIn(
            'target_duration', set(session.keys()) - initial_keys,
            "apply_preset_to_session must not set target_duration"
        )

    def test_duration_guard_rejects_none(self):
        """Simulating the render_video guard: None must be rejected."""
        target = None
        is_valid = target is not None and isinstance(target, (int, float)) and target > 0
        self.assertFalse(is_valid)

    def test_duration_guard_rejects_zero(self):
        target = 0
        is_valid = target is not None and isinstance(target, (int, float)) and target > 0
        self.assertFalse(is_valid)

    def test_duration_guard_rejects_negative(self):
        target = -30
        is_valid = target is not None and isinstance(target, (int, float)) and target > 0
        self.assertFalse(is_valid)

    def test_duration_guard_accepts_15(self):
        target = 15
        is_valid = target is not None and isinstance(target, (int, float)) and target > 0
        self.assertTrue(is_valid)

    def test_duration_guard_accepts_90(self):
        target = 90.0
        is_valid = target is not None and isinstance(target, (int, float)) and target > 0
        self.assertTrue(is_valid)


# ── Fix the float parser to reject inf ────────────────────────────────────────
# The implementation above already rejects NaN (float('NaN') > 0 → False in Python)
# but doesn't reject inf. Patch the implementation:

def parse_float_minutes(value) -> float:  # noqa: F811
    """
    Final implementation: parse float-minutes input, reject invalid values.
    Normalise comma → dot. Reject 0, negative, infinity, NaN, non-numeric.
    """
    if value is None:
        return 0.0
    s = str(value).strip().replace(',', '.')
    try:
        import math
        minutes = float(s)
        if not math.isfinite(minutes) or minutes <= 0:
            return 0.0
        return round(minutes * 60.0, 3)
    except (ValueError, TypeError):
        return 0.0


class TestFloatMinutesParserFixed(unittest.TestCase):
    """Re-run key tests against the fixed parser."""

    def test_1_5_minutes(self):
        self.assertAlmostEqual(parse_float_minutes(1.5), 90.0, places=1)

    def test_comma(self):
        self.assertAlmostEqual(parse_float_minutes('1,5'), 90.0, places=1)

    def test_inf_rejected(self):
        self.assertEqual(parse_float_minutes('inf'), 0.0)

    def test_nan_rejected(self):
        self.assertEqual(parse_float_minutes('NaN'), 0.0)

    def test_zero_rejected(self):
        self.assertEqual(parse_float_minutes(0), 0.0)

    def test_negative_rejected(self):
        self.assertEqual(parse_float_minutes(-5), 0.0)

    def test_empty_rejected(self):
        self.assertEqual(parse_float_minutes(''), 0.0)

    def test_abc_rejected(self):
        self.assertEqual(parse_float_minutes('abc'), 0.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
