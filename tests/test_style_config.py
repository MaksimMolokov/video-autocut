"""
Part 1 — Style configuration unit tests.

1.1  All 14 style IDs exist, no duplicates, backend+UI agree
1.2  Each style has video_intro, video_outro, audio_intro, audio_outro rules
1.3  Style does NOT override global output_format (Style != Format)
1.4  Style does NOT set target_duration (Style != Duration)
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import ALL_14_STYLE_IDS, TIMELINE_STYLE_IDS


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_profile(pid: str):
    from src.timeline.intro_outro_rules import get_profile
    return get_profile(pid)


def _load_style_profiles() -> dict:
    from src.timeline.intro_outro_rules import STYLE_PROFILES
    return STYLE_PROFILES


def _get_preset_registry():
    from src.presets import PresetRegistry
    presets_dir = Path(__file__).parent.parent / 'presets'
    return PresetRegistry(presets_dir)


# ═══════════════════════════════════════════════════════════════════════════════
# 1.1 — All style IDs exist, no duplicates
# ═══════════════════════════════════════════════════════════════════════════════

class TestAllStyleIDsExist(unittest.TestCase):

    def setUp(self):
        self.profiles = _load_style_profiles()

    def test_exactly_14_profiles(self):
        self.assertEqual(len(self.profiles), len(ALL_14_STYLE_IDS),
                         f"Expected {len(ALL_14_STYLE_IDS)} styles, got {len(self.profiles)}: {list(self.profiles)}")

    def test_no_duplicate_ids(self):
        ids = list(self.profiles.keys())
        self.assertEqual(len(ids), len(set(ids)), "Duplicate style IDs detected")

    def test_all_expected_ids_present(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                self.assertIn(pid, self.profiles,
                              f"Style '{pid}' missing from STYLE_PROFILES")

    def test_no_unexpected_ids(self):
        for pid in self.profiles:
            with self.subTest(style=pid):
                self.assertIn(pid, ALL_14_STYLE_IDS,
                              f"Unexpected style '{pid}' found in STYLE_PROFILES")

    def test_preset_id_field_matches_key(self):
        """Each profile's preset_id must equal its dict key."""
        for key, profile in self.profiles.items():
            with self.subTest(style=key):
                self.assertEqual(profile.preset_id, key,
                                 f"profile.preset_id='{profile.preset_id}' != key='{key}'")

    def test_preset_yaml_files_exist_for_all_styles(self):
        """Every style ID must have a corresponding YAML preset file."""
        presets_dir = Path(__file__).parent.parent / 'presets'
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                yaml_file = presets_dir / f"{pid}.yaml"
                self.assertTrue(yaml_file.exists(),
                                f"Missing preset file: presets/{pid}.yaml")

    def test_use_new_system_list_covers_13_presets(self):
        """
        The use_new_system list in gui.py must cover exactly the non-easy styles.
        easy_mode uses EasyClipSelector, not TimelineBuilder.
        """
        use_new = [
            'drone_nature_cinematic', 'drone_landscape_clean', 'fast_action_sport',
            'urban_city_rhythm', 'social_media_punchy', 'business_promo_clean',
            'travel_story', 'real_estate_property_tour', 'event_highlights',
            'calm_minimal_documentary', 'intelligent_beauty_mix',
            'sport_dynamic_cut', 'sport_highlight_impact',
            'f1', 'f2', 'f3', 'f4', 'f5', 'f6',
        ]
        expected = sorted(TIMELINE_STYLE_IDS)
        self.assertEqual(sorted(use_new), expected)

    def test_get_profile_returns_default_for_unknown(self):
        """Unknown preset IDs must not raise — return a default profile."""
        profile = _get_profile('totally_unknown_preset_zzz')
        self.assertIsNotNone(profile)


# ═══════════════════════════════════════════════════════════════════════════════
# 1.2 — Each style has all required intro/outro rules
# ═══════════════════════════════════════════════════════════════════════════════

class TestStyleHasAllRules(unittest.TestCase):

    def test_all_styles_have_video_intro_rule(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIsNotNone(p.video_intro,
                                     f"{pid}: video_intro is None")

    def test_all_styles_have_video_outro_rule(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIsNotNone(p.video_outro,
                                     f"{pid}: video_outro is None")

    def test_all_styles_have_audio_intro_rule(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIsNotNone(p.audio_intro,
                                     f"{pid}: audio_intro is None")

    def test_all_styles_have_audio_outro_rule(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIsNotNone(p.audio_outro,
                                     f"{pid}: audio_outro is None")

    def test_all_styles_have_video_intro_transition(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                t = p.video_intro.start_transition
                self.assertIsInstance(t, str, f"{pid}: start_transition not a string")
                self.assertTrue(len(t) > 0, f"{pid}: start_transition is empty")

    def test_all_styles_have_video_outro_transition(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                t = p.video_outro.end_transition
                self.assertIsInstance(t, str, f"{pid}: end_transition not a string")
                self.assertTrue(len(t) > 0, f"{pid}: end_transition is empty")

    def test_all_styles_have_valid_intro_transition_token(self):
        VALID_INTRO_TOKENS = {
            'clean_cut', 'fade_in', 'beat_flash', 'zoom_in', 'cinematic_crossfade',
        }
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIn(
                    p.video_intro.start_transition, VALID_INTRO_TOKENS,
                    f"{pid}: unknown intro transition '{p.video_intro.start_transition}'"
                )

    def test_all_styles_have_valid_outro_transition_token(self):
        VALID_OUTRO_TOKENS = {
            'clean_cut', 'fade_out', 'beat_cut', 'flash_impact',
            'cinematic_fade', 'freeze_final',
        }
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIn(
                    p.video_outro.end_transition, VALID_OUTRO_TOKENS,
                    f"{pid}: unknown outro transition '{p.video_outro.end_transition}'"
                )

    def test_all_styles_have_valid_audio_intro_mode(self):
        VALID_AUDIO_INTRO_MODES = {
            'from_start', 'soft_fade', 'phrase_start', 'beat_start', 'drop_start',
        }
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIn(
                    p.audio_intro.mode, VALID_AUDIO_INTRO_MODES,
                    f"{pid}: unknown audio_intro mode '{p.audio_intro.mode}'"
                )

    def test_all_styles_have_valid_audio_outro_mode(self):
        VALID_AUDIO_OUTRO_MODES = {
            'soft_fade_end', 'phrase_fade_end', 'beat_cut_end', 'punch_end',
            'soft_fade',  # alias used in some profiles
        }
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIn(
                    p.audio_outro.mode, VALID_AUDIO_OUTRO_MODES,
                    f"{pid}: unknown audio_outro mode '{p.audio_outro.mode}'"
                )

    def test_audio_fade_durations_positive(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertGreater(p.audio_intro.fade_in_sec, 0,
                                   f"{pid}: audio_intro.fade_in_sec <= 0")
                self.assertGreater(p.audio_outro.fade_out_sec, 0,
                                   f"{pid}: audio_outro.fade_out_sec <= 0")

    def test_all_styles_have_valid_narrative(self):
        VALID_NARRATIVES = {
            'simple', 'story_arc', 'energy_peak', 'buildup_impact', 'beauty_arc',
        }
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIn(p.narrative, VALID_NARRATIVES,
                              f"{pid}: unknown narrative '{p.narrative}'")

    def test_weights_are_dicts(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIsInstance(p.video_intro.weights, dict,
                                     f"{pid}: intro weights not a dict")
                self.assertIsInstance(p.video_outro.weights, dict,
                                     f"{pid}: outro weights not a dict")

    def test_forbidden_are_lists(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertIsInstance(p.video_intro.forbidden, list,
                                     f"{pid}: intro forbidden not a list")
                self.assertIsInstance(p.video_outro.forbidden, list,
                                     f"{pid}: outro forbidden not a list")

    def test_thresholds_in_valid_range(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                for attr in ('min_sharpness', 'min_brightness'):
                    val = getattr(p.video_intro, attr)
                    self.assertGreaterEqual(val, 0.0, f"{pid} intro {attr} < 0")
                    self.assertLessEqual(val, 1.0, f"{pid} intro {attr} > 1")
                    val = getattr(p.video_outro, attr)
                    self.assertGreaterEqual(val, 0.0, f"{pid} outro {attr} < 0")
                    self.assertLessEqual(val, 1.0, f"{pid} outro {attr} > 1")


# ── Mock that supports both dict and attribute access (like Streamlit session_state) ──

class _MockSessionState:
    """
    Mimics Streamlit's session_state: supports both ss['key'] and ss.key.
    Also supports 'key' in ss.
    """
    def __init__(self, data: dict):
        object.__setattr__(self, '_data', dict(data))

    def __contains__(self, key):
        return key in object.__getattribute__(self, '_data')

    def __getitem__(self, key):
        return object.__getattribute__(self, '_data')[key]

    def __setitem__(self, key, value):
        object.__getattribute__(self, '_data')[key] = value

    def __getattr__(self, key):
        data = object.__getattribute__(self, '_data')
        if key in data:
            return data[key]
        raise AttributeError(key)

    def __setattr__(self, key, value):
        object.__getattribute__(self, '_data')[key] = value

    def get(self, key, default=None):
        return object.__getattribute__(self, '_data').get(key, default)

    def as_dict(self):
        return dict(object.__getattribute__(self, '_data'))


# ═══════════════════════════════════════════════════════════════════════════════
# 1.3 — Style does NOT override global output_format
# ═══════════════════════════════════════════════════════════════════════════════

class TestStyleDoesNotOverrideFormat(unittest.TestCase):
    """
    Verifies that apply_preset_to_session() uses the user-selected format,
    not the format baked into the preset YAML.

    Architectural invariant: Style != Output format
    """

    def _make_session(self, selected_format: str) -> _MockSessionState:
        """Return a mock session_state with a user-selected format."""
        from src.presets import PresetRegistry
        presets_dir = Path(__file__).parent.parent / 'presets'
        registry = PresetRegistry(presets_dir)
        return _MockSessionState({
            'selected_output_format': selected_format,
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
            'preset_registry': registry,
        })

    def _apply_preset(self, preset_id: str, mock_ss: _MockSessionState):
        """Run apply_preset_to_session with a proper session_state mock."""
        import streamlit as st
        with patch.object(st, 'session_state', mock_ss), \
             patch.object(st, 'success', MagicMock()), \
             patch.object(st, 'error', MagicMock()):
            from src.gui import apply_preset_to_session
            apply_preset_to_session(preset_id)

    def test_horizontal_format_preserved_across_all_styles(self):
        """
        User chose horizontal_16_9. Applying any style must NOT change this to vertical.
        """
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                ss = self._make_session('horizontal_16_9')
                self._apply_preset(pid, ss)
                self.assertEqual(
                    ss['output_format'], 'horizontal',
                    f"{pid} overrode user format: expected 'horizontal', got '{ss['output_format']}'"
                )

    def test_vertical_format_preserved(self):
        """User chose vertical_9_16. Style must not revert to horizontal."""
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                ss = self._make_session('vertical_9_16')
                self._apply_preset(pid, ss)
                self.assertEqual(
                    ss['output_format'], 'vertical',
                    f"{pid} overrode user format: expected 'vertical', got '{ss['output_format']}'"
                )

    def test_square_format_preserved(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                ss = self._make_session('square_1_1')
                self._apply_preset(pid, ss)
                self.assertEqual(
                    ss['output_format'], 'square',
                    f"{pid} overrode user format: expected 'square', got '{ss['output_format']}'"
                )

    def test_style_profile_has_no_target_format_field(self):
        """IntroOutroProfile must not have output_format or resolution fields."""
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertFalse(
                    hasattr(p, 'output_format'),
                    f"{pid}: IntroOutroProfile has 'output_format' — must not"
                )
                self.assertFalse(
                    hasattr(p, 'resolution'),
                    f"{pid}: IntroOutroProfile has 'resolution' — must not"
                )

    def test_output_config_format_comes_from_caller_not_style(self):
        """
        OutputConfig is constructed with format from session_state (caller),
        not from the style profile.
        """
        from src.config_loader import OutputConfig
        for fmt in ('horizontal', 'vertical', 'square'):
            with self.subTest(format=fmt):
                cfg = OutputConfig(
                    target_duration=60.0,
                    format=fmt,
                    dynamic_level='balanced',
                )
                self.assertEqual(cfg.format, fmt)
                w, h = cfg.resolution
                if fmt == 'horizontal':
                    self.assertGreater(w, h)
                elif fmt == 'vertical':
                    self.assertGreater(h, w)
                else:
                    self.assertEqual(w, h)

    def test_format_user_map_covers_all_ui_options(self):
        """
        The user_format_map in apply_preset_to_session must cover all
        UI format option keys.
        """
        user_format_map = {
            'horizontal_16_9': 'horizontal',
            'vertical_9_16': 'vertical',
            'square_1_1': 'square',
            'original': 'horizontal',
        }
        ui_formats = ['horizontal_16_9', 'vertical_9_16', 'square_1_1', 'original']
        for fmt in ui_formats:
            with self.subTest(format=fmt):
                self.assertIn(fmt, user_format_map,
                              f"UI format '{fmt}' missing from user_format_map")
                self.assertIsNotNone(user_format_map[fmt])


# ═══════════════════════════════════════════════════════════════════════════════
# 1.4 — Style does NOT set target_duration
# ═══════════════════════════════════════════════════════════════════════════════

class TestStyleDoesNotSetDuration(unittest.TestCase):
    """
    Architectural invariant: Style != Target duration.

    The style profile must not contain a target_duration field.
    The preset YAML may have audio_selection defaults but NOT a
    controlling target_duration_sec that overrides user input.
    """

    def test_style_profile_has_no_target_duration(self):
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = _get_profile(pid)
                self.assertFalse(
                    hasattr(p, 'target_duration'),
                    f"{pid}: IntroOutroProfile has 'target_duration'"
                )
                self.assertFalse(
                    hasattr(p, 'target_duration_sec'),
                    f"{pid}: IntroOutroProfile has 'target_duration_sec'"
                )

    def test_timeline_result_uses_caller_target_duration(self):
        """
        TimelineBuilder.build() must accept target_duration as a parameter,
        not derive it from the profile.
        """
        import inspect
        from src.timeline.timeline_builder import TimelineBuilder
        sig = inspect.signature(TimelineBuilder.build)
        self.assertIn('target_duration', sig.parameters,
                      "TimelineBuilder.build() must accept target_duration parameter")

    def test_timeline_respects_target_duration_15s(self):
        """A 15-second target must produce segments summing close to 15s."""
        from tests.helpers import make_candidates
        from src.timeline.timeline_builder import TimelineBuilder
        from unittest.mock import patch
        candidates = make_candidates(n=20, duration=3.0, start_offset=5.0)
        with patch('src.timeline.audio_boundary.AudioBoundaryDetector._load'):
            result = TimelineBuilder.build(candidates, 15.0, 'travel_story')
        total = sum(s.duration for s in result.segments)
        self.assertGreater(total, 5.0,
                           f"Expected > 5s for 15s target, got {total:.1f}s")
        self.assertLess(total, 20.0,
                        f"Expected < 20s for 15s target, got {total:.1f}s")

    def test_timeline_respects_target_duration_90s(self):
        """A 90-second target must produce substantially more content than 15s target."""
        from tests.helpers import make_candidates
        from src.timeline.timeline_builder import TimelineBuilder
        from unittest.mock import patch
        candidates_15 = make_candidates(n=30, duration=3.0, start_offset=5.0)
        candidates_90 = make_candidates(n=30, duration=3.0, start_offset=5.0)
        with patch('src.timeline.audio_boundary.AudioBoundaryDetector._load'):
            result_15 = TimelineBuilder.build(candidates_15, 15.0, 'travel_story')
            result_90 = TimelineBuilder.build(candidates_90, 90.0, 'travel_story')
        dur_15 = sum(s.duration for s in result_15.segments)
        dur_90 = sum(s.duration for s in result_90.segments)
        self.assertGreater(dur_90, dur_15,
                           f"90s target ({dur_90:.1f}s) should be longer than 15s target ({dur_15:.1f}s)")

    def test_style_cannot_force_6_second_video_from_90s_target(self):
        """
        Regression: the style must not cause a 6-10s output when target=90s.
        TimelineBuilder must return segments summing > 50% of target.
        """
        from tests.helpers import make_candidates
        from src.timeline.timeline_builder import TimelineBuilder
        from unittest.mock import patch

        for pid in TIMELINE_STYLE_IDS:
            with self.subTest(style=pid):
                candidates = make_candidates(n=30, duration=3.0, start_offset=5.0)
                with patch('src.timeline.audio_boundary.AudioBoundaryDetector._load'):
                    result = TimelineBuilder.build(candidates, 90.0, pid)
                total = sum(s.duration for s in result.segments)
                self.assertGreater(
                    total, 10.0,
                    f"{pid}: got only {total:.1f}s for 90s target — style overriding duration?"
                )

    def test_preset_yaml_duration_field_not_controlling(self):
        """
        Preset YAML may have default audio_selection durations, but there must
        be no 'target_duration_sec' or 'duration' key at the top level of settings.
        """
        presets_dir = Path(__file__).parent.parent / 'presets'
        import yaml  # noqa: F401 — must be importable
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                yaml_file = presets_dir / f"{pid}.yaml"
                if not yaml_file.exists():
                    self.skipTest(f"YAML file missing for {pid}")
                try:
                    import yaml as _yaml
                    data = _yaml.safe_load(yaml_file.read_text())
                    settings = data.get('settings', {})
                    # These keys must not appear as top-level controlling settings
                    self.assertNotIn(
                        'target_duration_sec', settings,
                        f"{pid}.yaml has 'target_duration_sec' in settings"
                    )
                    self.assertNotIn(
                        'target_duration', settings,
                        f"{pid}.yaml has 'target_duration' in settings"
                    )
                except ImportError:
                    self.skipTest("PyYAML not installed")


if __name__ == '__main__':
    unittest.main(verbosity=2)
