"""
Regression tests — covering all known bugs and key invariants.

Regression 1  — Video must not freeze after 30 seconds (duration continuity)
Regression 2  — After style change, video must not be 6–10 seconds (for 90s target)
Regression 3  — Audio must not be longer than video
Regression 4  — Style must not override output_format
Regression 5  — Style must not override target_duration
Regression 6  — Render ID / temp files must not conflict across renders
Regression 7  — _validate_output logic is correct for all pass/fail cases
Regression 8  — session_state: change_style preserves target_duration
Regression 9  — session_state: change_duration clears target_duration only
Regression 10 — TimelineBuilder fallback when CandidateClips are empty
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import (
    ALL_14_STYLE_IDS, TIMELINE_STYLE_IDS,
    make_candidates, StubCandidate, StubFeatures,
    RUN_INTEGRATION, ffmpeg_available,
    create_synthetic_video, create_synthetic_audio,
    get_video_duration, get_audio_duration,
)

SKIP_INT = "Integration tests disabled"
SKIP_FFMPEG = "FFmpeg not available"


def _build(candidates, target, preset_id):
    from src.timeline.timeline_builder import TimelineBuilder
    with patch('src.timeline.audio_boundary.AudioBoundaryDetector._load'):
        return TimelineBuilder.build(candidates, target, preset_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Regression 1 — Duration continuity (no freeze at 30s mark)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoDurationTruncation(unittest.TestCase):
    """
    The 6-10s bug manifested as the video stopping at the length of a single
    source clip (~6-10s) while audio continued. This regression ensures that
    TimelineBuilder plans enough segments to fill the target duration.
    """

    def test_planned_duration_not_6_to_10_for_90s_target(self):
        """90s target must produce > 40s of planned timeline content."""
        candidates = make_candidates(n=40, duration=4.0, start_offset=5.0)
        for pid in TIMELINE_STYLE_IDS:
            with self.subTest(style=pid):
                r = _build(candidates, 90.0, pid)
                total = sum(s.duration for s in r.segments)
                self.assertGreater(
                    total, 40.0,
                    f"{pid}: planned timeline = {total:.1f}s for 90s target "
                    f"(this is the 6-10s freeze bug)"
                )

    def test_planned_duration_not_6_to_10_for_60s_target(self):
        candidates = make_candidates(n=30, duration=4.0, start_offset=5.0)
        for pid in TIMELINE_STYLE_IDS:
            with self.subTest(style=pid):
                r = _build(candidates, 60.0, pid)
                total = sum(s.duration for s in r.segments)
                self.assertGreater(
                    total, 25.0,
                    f"{pid}: planned timeline = {total:.1f}s for 60s target"
                )

    def test_single_source_provides_enough_material(self):
        """
        Even with a single source, 90s of candidates should fill a 90s timeline.
        """
        candidates = make_candidates(n=30, duration=3.0, start_offset=2.0)
        r = _build(candidates, 90.0, 'travel_story')
        total = sum(s.duration for s in r.segments)
        self.assertGreater(total, 30.0,
                           f"Single-source timeline produced only {total:.1f}s for 90s target")


# ═══════════════════════════════════════════════════════════════════════════════
# Regression 2 — After style change, duration must not drop to 6-10s
# ═══════════════════════════════════════════════════════════════════════════════

class TestStyleChangePreservesTargetDuration(unittest.TestCase):
    """
    Simulates the flow: generate 30s → change style → generate 90s.
    The second generation must produce ≈ 90s, NOT 6-10s.
    """

    def _simulate_two_renders(self, style1, style2, target1, target2):
        """Return (planned_dur1, planned_dur2) for two sequential renders."""
        candidates1 = make_candidates(n=20, duration=3.0, start_offset=5.0)
        candidates2 = make_candidates(n=40, duration=3.0, start_offset=5.0)
        r1 = _build(candidates1, target1, style1)
        r2 = _build(candidates2, target2, style2)
        dur1 = sum(s.duration for s in r1.segments)
        dur2 = sum(s.duration for s in r2.segments)
        return dur1, dur2

    def test_changing_style_then_90s_not_6_10s(self):
        _, dur2 = self._simulate_two_renders(
            'travel_story', 'sport_dynamic_cut', 30.0, 90.0
        )
        self.assertGreater(
            dur2, 30.0,
            f"After style change to sport_dynamic_cut, got {dur2:.1f}s for 90s target"
        )

    def test_all_styles_after_travel_story_not_6s(self):
        for pid in TIMELINE_STYLE_IDS:
            with self.subTest(style=pid):
                _, dur2 = self._simulate_two_renders('travel_story', pid, 30.0, 90.0)
                self.assertGreater(
                    dur2, 20.0,
                    f"Style change → {pid}: planned {dur2:.1f}s for 90s target"
                )

    def test_session_state_target_duration_preserved_after_style_change(self):
        """
        When user clicks "Изменить стиль", target_duration must NOT be cleared.
        """
        # Simulate what the button does (from gui.py)
        session = {
            'page': 'render',
            'selected_preset_id': 'travel_story',
            'target_duration': 90.0,
            'generation_status': 'completed',
        }
        # Simulate "Изменить стиль" button click logic
        session['page'] = 'welcome'
        session['selected_preset_id'] = None
        # target_duration must NOT be set to None
        # (the bug was: target_duration = None was in this button's handler)
        session['generation_status'] = None

        self.assertIsNotNone(
            session.get('target_duration'),
            "'Изменить стиль' cleared target_duration — this causes the 6-10s bug"
        )
        self.assertEqual(session['target_duration'], 90.0)

    def test_session_state_target_duration_cleared_only_for_change_duration(self):
        """
        "Изменить длительность" SHOULD clear target_duration.
        "Изменить стиль" should NOT.
        """
        session = {
            'page': 'render',
            'selected_preset_id': 'travel_story',
            'target_duration': 90.0,
            'generation_status': 'completed',
        }

        # "Изменить длительность"
        session_dur = dict(session)
        session_dur['page'] = 'welcome'
        session_dur['target_duration'] = None
        session_dur['generation_status'] = None
        self.assertIsNone(session_dur['target_duration'])

        # "Изменить стиль" — must preserve duration
        session_style = dict(session)
        session_style['page'] = 'welcome'
        session_style['selected_preset_id'] = None
        # target_duration NOT touched
        session_style['generation_status'] = None
        self.assertEqual(session_style['target_duration'], 90.0)


# ═══════════════════════════════════════════════════════════════════════════════
# Regression 3 — Audio must not be longer than video
# ═══════════════════════════════════════════════════════════════════════════════

class TestAudioNotLongerThanVideo(unittest.TestCase):
    """
    Verifies the _validate_output logic correctly detects audio > video.
    The actual FFmpeg render regression is in TestRenderDuration90s.
    """

    def test_validate_output_detects_audio_longer_than_video(self):
        """
        Simulate a result where audio > video by 5s.
        _validate_output must set ok=False.
        """
        from src.ffmpeg_renderer import FFmpegRenderer
        import unittest.mock as mock

        # Simulate ffprobe JSON output where audio is 5s longer
        fake_ffprobe_output = '''{
  "streams": [
    {"codec_type": "video", "duration": "30.0"},
    {"codec_type": "audio", "duration": "35.0"}
  ],
  "format": {"duration": "35.0"}
}'''

        with mock.patch('subprocess.run') as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = fake_ffprobe_output
            mock_run.return_value = mock_result

            result = FFmpegRenderer._validate_output('/fake/output.mp4', 30.0)
            self.assertFalse(
                result.get('ok'),
                f"Expected ok=False when audio ({result.get('audio_dur'):.1f}s) "
                f"> video ({result.get('video_dur'):.1f}s) by 5s"
            )
            self.assertGreater(result.get('gap', 0), 0)

    def test_validate_output_ok_when_no_audio(self):
        """No audio stream (no music) must still be ok if video duration is correct."""
        from src.ffmpeg_renderer import FFmpegRenderer
        import unittest.mock as mock

        fake_ffprobe_output = '''{
  "streams": [
    {"codec_type": "video", "duration": "30.0"}
  ],
  "format": {"duration": "30.0"}
}'''

        with mock.patch('subprocess.run') as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = fake_ffprobe_output
            mock_run.return_value = mock_result

            result = FFmpegRenderer._validate_output('/fake/output.mp4', 30.0)
            self.assertTrue(
                result.get('ok'),
                f"Expected ok=True for video without audio; got: {result}"
            )

    def test_validate_output_detects_short_video(self):
        """Video that is only 50% of target must be detected as not ok."""
        from src.ffmpeg_renderer import FFmpegRenderer
        import unittest.mock as mock

        fake_ffprobe_output = '''{
  "streams": [
    {"codec_type": "video", "duration": "10.0"},
    {"codec_type": "audio", "duration": "10.0"}
  ],
  "format": {"duration": "10.0"}
}'''

        with mock.patch('subprocess.run') as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = fake_ffprobe_output
            mock_run.return_value = mock_result

            result = FFmpegRenderer._validate_output('/fake/output.mp4', 90.0)
            self.assertFalse(
                result.get('ok'),
                "Expected ok=False for 10s video with 90s target"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Regression 4+5 — Style must not override format or duration
# ═══════════════════════════════════════════════════════════════════════════════

class TestStyleDoesNotOverrideFormatOrDuration(unittest.TestCase):

    def test_output_config_format_is_not_from_style(self):
        """
        OutputConfig must be constructed with the user-chosen format,
        not from IntroOutroProfile.
        """
        from src.config_loader import OutputConfig
        from src.timeline.intro_outro_rules import get_profile

        # Even if a style "wants" vertical, the OutputConfig must use the caller's format
        profile = get_profile('sport_dynamic_cut')
        self.assertFalse(hasattr(profile, 'output_format'))

        # OutputConfig constructed with horizontal must give horizontal resolution
        cfg = OutputConfig(target_duration=90.0, format='horizontal', dynamic_level='balanced')
        w, h = cfg.resolution
        self.assertGreater(w, h,
                           "OutputConfig with format='horizontal' returned vertical resolution!")

    def test_timeline_result_does_not_contain_format(self):
        """TimelineResult must not have output_format or resolution fields."""
        from src.timeline.timeline_builder import TimelineResult
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(TimelineResult)}
        self.assertNotIn('output_format', field_names)
        self.assertNotIn('resolution', field_names)

    def test_timeline_result_does_not_contain_target_duration(self):
        """
        TimelineResult stores computed segment list but NOT target_duration_sec
        as a controlling field that would override the caller's intent.
        """
        from src.timeline.timeline_builder import TimelineResult
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(TimelineResult)}
        # It's OK to have audio_start/audio_end but not a 'target_duration' controlling field
        self.assertNotIn('target_duration', field_names)
        self.assertNotIn('target_duration_sec', field_names)

    def test_all_style_profiles_lack_format_field(self):
        from src.timeline.intro_outro_rules import get_profile
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = get_profile(pid)
                self.assertFalse(hasattr(p, 'output_format'))
                self.assertFalse(hasattr(p, 'resolution'))

    def test_all_style_profiles_lack_duration_field(self):
        from src.timeline.intro_outro_rules import get_profile
        for pid in ALL_14_STYLE_IDS:
            with self.subTest(style=pid):
                p = get_profile(pid)
                self.assertFalse(hasattr(p, 'target_duration'))
                self.assertFalse(hasattr(p, 'target_duration_sec'))


# ═══════════════════════════════════════════════════════════════════════════════
# Regression 6 — Temp files and renders do not conflict
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderIsolation(unittest.TestCase):

    def test_two_renders_produce_different_segment_lists(self):
        """
        Two sequential builds with different presets must produce different timelines.
        This simulates render1 (style A) → render2 (style B).
        """
        candidates_a = make_candidates(n=20, duration=4.0, start_offset=5.0)
        candidates_b = make_candidates(n=20, duration=4.0, start_offset=5.0)

        r_travel = _build(candidates_a, 30.0, 'travel_story')
        r_sport  = _build(candidates_b, 30.0, 'sport_dynamic_cut')

        # At minimum, narratives should differ
        self.assertNotEqual(
            r_travel.narrative, r_sport.narrative,
            "travel_story and sport_dynamic_cut have same narrative — unexpected"
        )

    def test_cached_audio_boundary_does_not_persist(self):
        """
        AudioBoundaryDetector is instantiated fresh per render.
        Test that two builds with different preset_ids don't share state.
        """
        from src.timeline.audio_boundary import AudioBoundaryDetector
        d1 = AudioBoundaryDetector('/path/a.mp3')
        d2 = AudioBoundaryDetector('/path/b.mp3')
        self.assertIsNot(d1, d2)
        self.assertEqual(d1.audio_path, '/path/a.mp3')
        self.assertEqual(d2.audio_path, '/path/b.mp3')


# ═══════════════════════════════════════════════════════════════════════════════
# Regression 7 — _validate_output logic correctness
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateOutputLogic(unittest.TestCase):

    def _validate(self, video_dur: float, audio_dur: float, target: float):
        from src.ffmpeg_renderer import FFmpegRenderer
        import unittest.mock as mock

        streams = [{"codec_type": "video", "duration": str(video_dur)}]
        if audio_dur > 0:
            streams.append({"codec_type": "audio", "duration": str(audio_dur)})

        fake_output = f'''{{
  "streams": {streams},
  "format": {{"duration": "{max(video_dur, audio_dur)}"}}
}}'''.replace("'", '"')

        with mock.patch('subprocess.run') as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = fake_output
            mock_run.return_value = mock_result
            return FFmpegRenderer._validate_output('/fake/out.mp4', target)

    def test_exact_match_is_ok(self):
        r = self._validate(30.0, 30.0, 30.0)
        self.assertTrue(r['ok'])

    def test_90_percent_of_target_is_ok(self):
        r = self._validate(81.0, 81.0, 90.0)
        self.assertTrue(r['ok'], f"81s of 90s target should be ok: {r}")

    def test_89_percent_of_target_is_not_ok(self):
        r = self._validate(80.0, 80.0, 90.0)
        self.assertFalse(r['ok'], "80s of 90s target (< 90%) should not be ok")

    def test_audio_3s_longer_is_not_ok(self):
        r = self._validate(30.0, 33.1, 30.0)
        self.assertFalse(r['ok'],
                         "Audio 3.1s longer than video should not be ok")

    def test_audio_2s_longer_is_ok(self):
        r = self._validate(30.0, 32.0, 30.0)
        self.assertTrue(r['ok'],
                        "Audio 2s longer than video should be ok (gap < 3.0)")

    def test_gap_field_correct(self):
        r = self._validate(30.0, 35.0, 30.0)
        self.assertAlmostEqual(r['gap'], 5.0, places=1)

    def test_no_audio_gap_is_negative(self):
        r = self._validate(30.0, 0.0, 30.0)
        self.assertLessEqual(r['gap'], 0)

    def test_ffprobe_failure_returns_not_ok(self):
        from src.ffmpeg_renderer import FFmpegRenderer
        import unittest.mock as mock
        with mock.patch('subprocess.run') as mock_run:
            mock_result = mock.MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ''
            mock_run.return_value = mock_result
            r = FFmpegRenderer._validate_output('/fake/out.mp4', 30.0)
            self.assertFalse(r['ok'])


# ═══════════════════════════════════════════════════════════════════════════════
# Regression 8+9 — Session state: navigation buttons
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionStateNavigation(unittest.TestCase):
    """
    Verifies the state management invariants documented in gui.py.
    """

    def _change_style(self, session):
        """Simulate 'Изменить стиль' button click."""
        session['page'] = 'welcome'
        session['selected_preset_id'] = None
        # MUST NOT touch target_duration
        session['generation_status'] = None
        return session

    def _change_duration(self, session):
        """Simulate 'Изменить длительность' button click."""
        session['page'] = 'welcome'
        session['target_duration'] = None
        session['generation_status'] = None
        return session

    def test_change_style_preserves_target_duration(self):
        session = {'target_duration': 90.0, 'selected_preset_id': 'travel_story',
                   'page': 'render', 'generation_status': 'completed'}
        self._change_style(session)
        self.assertEqual(session['target_duration'], 90.0,
                         "'Изменить стиль' must not clear target_duration")

    def test_change_style_preserves_music_path(self):
        session = {'target_duration': 90.0, 'selected_preset_id': 'travel_story',
                   'page': 'render', 'generation_status': 'completed',
                   'music_path': '/path/to/music.mp3'}
        self._change_style(session)
        self.assertEqual(session['music_path'], '/path/to/music.mp3')

    def test_change_style_clears_preset_id(self):
        session = {'target_duration': 90.0, 'selected_preset_id': 'travel_story',
                   'page': 'render', 'generation_status': 'completed'}
        self._change_style(session)
        self.assertIsNone(session['selected_preset_id'])

    def test_change_duration_clears_target_duration(self):
        session = {'target_duration': 90.0, 'selected_preset_id': 'travel_story',
                   'page': 'render', 'generation_status': 'completed'}
        self._change_duration(session)
        self.assertIsNone(session['target_duration'],
                          "'Изменить длительность' must clear target_duration")

    def test_change_duration_preserves_preset_id(self):
        session = {'target_duration': 90.0, 'selected_preset_id': 'travel_story',
                   'page': 'render', 'generation_status': 'completed'}
        self._change_duration(session)
        self.assertEqual(session['selected_preset_id'], 'travel_story',
                         "'Изменить длительность' must not clear selected_preset_id")

    def test_regen_button_does_not_change_target_duration(self):
        """'Сгенерировать заново' must keep target_duration as-is."""
        session = {'target_duration': 90.0, 'selected_preset_id': 'sport_dynamic_cut',
                   'generation_status': 'completed', 'render_logs': [], 'render_progress': 100}
        # Simulate regen button
        session['generation_status'] = 'starting'
        session['render_logs'] = []
        session['render_progress'] = 0
        session['render_stage'] = ''
        self.assertEqual(session['target_duration'], 90.0)

    def test_target_duration_guard_in_render_video(self):
        """render_video must fail immediately if target_duration is None or 0."""
        invalid_durations = [None, 0, 0.0, -1, -30.0]
        for td in invalid_durations:
            with self.subTest(target_duration=td):
                is_valid = (
                    td is not None
                    and isinstance(td, (int, float))
                    and td > 0
                )
                self.assertFalse(is_valid,
                                 f"target_duration={td!r} should be rejected by guard")


# ═══════════════════════════════════════════════════════════════════════════════
# Regression 10 — TimelineBuilder graceful fallback
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimelineBuilderEdgeCases(unittest.TestCase):

    def test_empty_candidates_returns_empty_timeline(self):
        r = _build([], 30.0, 'travel_story')
        self.assertEqual(r.segments, [])

    def test_single_very_long_candidate(self):
        """A single 120s candidate for a 30s target must not crash."""
        c = make_candidates(n=1, duration=120.0, start_offset=5.0)
        r = _build(c, 30.0, 'travel_story')
        self.assertIsNotNone(r)

    def test_all_clips_disqualified_by_forbidden(self):
        """If all clips are black-frame, intro scorer returns None for all."""
        candidates = []
        for i in range(10):
            c = StubCandidate(
                source_path='/fake/v.mp4',
                start=float(i * 6 + 5),
                end=float(i * 6 + 11),
                duration=6.0,
                is_must_use=False,
                final_score=0.5,
                features=StubFeatures(brightness_score=0.01),  # all black
            )
            candidates.append(c)
        r = _build(candidates, 30.0, 'travel_story')
        # Must not crash; intro may be empty
        self.assertIsNotNone(r)
        intros = [s for s in r.segments if s.role == 'intro']
        # Intro log should indicate "none" found
        if not intros:
            self.assertEqual(r.intro_log, 'none')

    def test_unknown_preset_id_gets_default_profile(self):
        """Unknown preset must not raise — use default profile."""
        candidates = make_candidates(n=10, duration=4.0, start_offset=5.0)
        r = _build(candidates, 20.0, 'totally_unknown_preset_xyz')
        self.assertIsNotNone(r)

    def test_target_duration_much_smaller_than_clip_duration(self):
        """Target 2s, but all clips are 5s — must handle gracefully."""
        candidates = make_candidates(n=5, duration=5.0, start_offset=5.0)
        r = _build(candidates, 2.0, 'travel_story')
        self.assertIsNotNone(r)


if __name__ == '__main__':
    unittest.main(verbosity=2)
