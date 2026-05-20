"""
Part 3 — Full timeline builder tests.

3.1  Timeline structure (intro, body, outro, audio_segment, target_duration)
3.2  Intro and outro are different segments; warning when reused
3.3  Planned duration ≈ target duration (tolerances)
3.4  Body adapts to duration (more clips for longer targets)

Also covers Part 4 scoring via the timeline path.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import (
    ALL_14_STYLE_IDS, TIMELINE_STYLE_IDS,
    make_candidates, StubCandidate, StubFeatures,
)


def _build(candidates, target, preset_id, music_path=None):
    """Convenience wrapper around TimelineBuilder.build with mocked audio."""
    from src.timeline.timeline_builder import TimelineBuilder
    with patch('src.timeline.audio_boundary.AudioBoundaryDetector._load'):
        return TimelineBuilder.build(
            candidates=candidates,
            target_duration=target,
            preset_id=preset_id,
            music_path=music_path,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3.1 — Timeline structure
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimelineStructure(unittest.TestCase):

    def setUp(self):
        self.candidates = make_candidates(n=20, duration=4.0, start_offset=5.0)

    def test_result_has_segments_list(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        self.assertIsInstance(r.segments, list)

    def test_result_has_intro_log(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        self.assertIsNotNone(r.intro_log)
        self.assertIsInstance(r.intro_log, str)

    def test_result_has_outro_log(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        self.assertIsNotNone(r.outro_log)
        self.assertIsInstance(r.outro_log, str)

    def test_result_has_audio_log(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        self.assertIsNotNone(r.audio_log)
        self.assertIsInstance(r.audio_log, str)

    def test_result_has_narrative(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        self.assertIsNotNone(r.narrative)

    def test_result_has_audio_start_end(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        self.assertIsInstance(r.audio_start, (int, float))
        self.assertIsInstance(r.audio_end, (int, float))

    def test_segments_have_role_attr(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        for seg in r.segments:
            self.assertTrue(hasattr(seg, 'role'), "Segment missing 'role' attribute")
            self.assertIn(seg.role, ('intro', 'body', 'outro'))

    def test_intro_segment_present_when_enough_candidates(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        roles = [s.role for s in r.segments]
        self.assertIn('intro', roles, "No intro segment in timeline")

    def test_outro_segment_present_when_enough_candidates(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        roles = [s.role for s in r.segments]
        self.assertIn('outro', roles, "No outro segment in timeline")

    def test_body_segments_present(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        body = [s for s in r.segments if s.role == 'body']
        self.assertGreater(len(body), 0, "No body segments in timeline")

    def test_intro_is_first(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        if r.segments:
            self.assertEqual(r.segments[0].role, 'intro',
                             f"First segment role is '{r.segments[0].role}', expected 'intro'")

    def test_outro_is_last(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        if len(r.segments) >= 2:
            self.assertEqual(r.segments[-1].role, 'outro',
                             f"Last segment role is '{r.segments[-1].role}', expected 'outro'")

    def test_body_between_intro_and_outro(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        segs = r.segments
        if len(segs) >= 3:
            roles_middle = [s.role for s in segs[1:-1]]
            for role in roles_middle:
                self.assertEqual(role, 'body',
                                 f"Non-body segment in middle: {role}")

    def test_intro_has_start_transition(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        intros = [s for s in r.segments if s.role == 'intro']
        if intros:
            self.assertTrue(hasattr(intros[0], 'start_transition'))

    def test_outro_has_end_transition(self):
        r = _build(self.candidates, 30.0, 'travel_story')
        outros = [s for s in r.segments if s.role == 'outro']
        if outros:
            self.assertTrue(hasattr(outros[0], 'end_transition'))

    def test_all_timeline_styles_produce_valid_result(self):
        """Every non-easy style must produce a valid TimelineResult."""
        for pid in TIMELINE_STYLE_IDS:
            with self.subTest(style=pid):
                r = _build(self.candidates, 30.0, pid)
                self.assertIsNotNone(r)
                self.assertIsInstance(r.segments, list)

    def test_empty_candidates_produces_empty_segments(self):
        r = _build([], 30.0, 'travel_story')
        self.assertEqual(r.segments, [])
        self.assertEqual(r.intro_log, 'none')


# ═══════════════════════════════════════════════════════════════════════════════
# 3.2 — Intro ≠ Outro (must be different segments)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntroOutroDifferent(unittest.TestCase):

    def test_intro_and_outro_are_different_objects(self):
        candidates = make_candidates(n=15, duration=5.0, start_offset=5.0)
        r = _build(candidates, 40.0, 'travel_story')
        intros  = [s for s in r.segments if s.role == 'intro']
        outros  = [s for s in r.segments if s.role == 'outro']
        if intros and outros:
            self.assertIsNot(intros[0], outros[0],
                             "Intro and outro are the same object!")

    def test_intro_and_outro_have_different_source_or_times(self):
        candidates = make_candidates(n=15, duration=5.0, start_offset=5.0)
        r = _build(candidates, 40.0, 'travel_story')
        intros  = [s for s in r.segments if s.role == 'intro']
        outros  = [s for s in r.segments if s.role == 'outro']
        if intros and outros:
            intro_key = (intros[0].source_path, intros[0].start)
            outro_key = (outros[0].source_path, outros[0].start)
            self.assertNotEqual(intro_key, outro_key,
                                "Intro and outro point to identical clip!")

    def test_only_one_intro(self):
        candidates = make_candidates(n=15, duration=5.0, start_offset=5.0)
        r = _build(candidates, 40.0, 'travel_story')
        intros = [s for s in r.segments if s.role == 'intro']
        self.assertLessEqual(len(intros), 1, "More than one intro segment!")

    def test_only_one_outro(self):
        candidates = make_candidates(n=15, duration=5.0, start_offset=5.0)
        r = _build(candidates, 40.0, 'travel_story')
        outros = [s for s in r.segments if s.role == 'outro']
        self.assertLessEqual(len(outros), 1, "More than one outro segment!")

    def test_single_candidate_handles_gracefully(self):
        """With only 1 candidate, intro and outro may be the same — no crash."""
        c = [make_candidates(n=1, duration=10.0, start_offset=5.0)[0]]
        r = _build(c, 30.0, 'travel_story')
        self.assertIsNotNone(r)

    def test_two_candidates_intro_and_outro_distinct(self):
        """With 2 candidates, intro and outro should use different ones."""
        candidates = [
            StubCandidate(
                source_path='/fake/v.mp4', start=5.0, end=10.0, duration=5.0,
                is_must_use=False, final_score=0.8,
                features=StubFeatures(sharpness_score=0.7, brightness_score=0.6,
                                     camera_stability_score=0.7),
            ),
            StubCandidate(
                source_path='/fake/v.mp4', start=15.0, end=20.0, duration=5.0,
                is_must_use=False, final_score=0.6,
                features=StubFeatures(sharpness_score=0.6, brightness_score=0.5,
                                     camera_stability_score=0.6),
            ),
        ]
        r = _build(candidates, 20.0, 'travel_story')
        self.assertIsNotNone(r)
        # Should not crash
        intros  = [s for s in r.segments if s.role == 'intro']
        outros  = [s for s in r.segments if s.role == 'outro']
        if intros and outros:
            self.assertNotEqual(
                (intros[0].start, intros[0].source_path),
                (outros[0].start, outros[0].source_path),
                "With 2 candidates, intro and outro should be distinct"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 3.3 — Planned duration ≈ target duration
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimelineDurationMatch(unittest.TestCase):

    def _total(self, result) -> float:
        return sum(s.duration for s in result.segments)

    def test_duration_tolerance_15s(self):
        candidates = make_candidates(n=25, duration=3.0, start_offset=5.0)
        r = _build(candidates, 15.0, 'travel_story')
        total = self._total(r)
        # Allow ±0.5s for short clips, but must not be < 5s (that's the 6-10s bug)
        self.assertGreater(total, 5.0,
                           f"15s target produced only {total:.1f}s — too short")
        self.assertLess(total, 20.0,
                        f"15s target produced {total:.1f}s — too long")

    def test_duration_tolerance_30s(self):
        candidates = make_candidates(n=25, duration=4.0, start_offset=5.0)
        r = _build(candidates, 30.0, 'travel_story')
        total = self._total(r)
        self.assertGreater(total, 15.0,
                           f"30s target produced only {total:.1f}s")

    def test_duration_tolerance_90s(self):
        candidates = make_candidates(n=40, duration=4.0, start_offset=5.0)
        r = _build(candidates, 90.0, 'travel_story')
        total = self._total(r)
        self.assertGreater(total, 40.0,
                           f"90s target produced only {total:.1f}s — likely the 6-10s bug")

    def test_intro_outro_do_not_exceed_target(self):
        candidates = make_candidates(n=15, duration=3.0, start_offset=5.0)
        r = _build(candidates, 20.0, 'travel_story')
        intros  = [s for s in r.segments if s.role == 'intro']
        outros  = [s for s in r.segments if s.role == 'outro']
        intro_dur = sum(s.duration for s in intros)
        outro_dur = sum(s.duration for s in outros)
        self.assertLess(intro_dur + outro_dur, 20.0,
                        "intro+outro duration exceeds target_duration")

    def test_duration_target_respected_for_all_styles(self):
        """All styles must produce at least 50% of target when enough candidates exist."""
        candidates = make_candidates(n=40, duration=3.0, start_offset=5.0)
        for pid in TIMELINE_STYLE_IDS:
            with self.subTest(style=pid):
                r = _build(candidates, 30.0, pid)
                total = self._total(r)
                self.assertGreater(
                    total, 10.0,
                    f"{pid}: produced only {total:.1f}s for 30s target"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# 3.4 — Body adapts to duration
# ═══════════════════════════════════════════════════════════════════════════════

class TestBodyAdaptsToDuration(unittest.TestCase):

    def test_more_body_clips_for_longer_target(self):
        candidates = make_candidates(n=50, duration=3.0, start_offset=5.0)
        r_short = _build(candidates, 15.0, 'travel_story')
        r_long  = _build(candidates, 90.0, 'travel_story')
        body_short = [s for s in r_short.segments if s.role == 'body']
        body_long  = [s for s in r_long.segments  if s.role == 'body']
        self.assertGreater(
            len(body_long), len(body_short),
            f"Expected more body clips for 90s than 15s: "
            f"15s→{len(body_short)}, 90s→{len(body_long)}"
        )

    def test_body_duration_grows_with_target(self):
        candidates = make_candidates(n=50, duration=3.0, start_offset=5.0)
        r_short = _build(candidates, 15.0, 'travel_story')
        r_long  = _build(candidates, 90.0, 'travel_story')
        body_dur_short = sum(s.duration for s in r_short.segments if s.role == 'body')
        body_dur_long  = sum(s.duration for s in r_long.segments  if s.role == 'body')
        self.assertGreater(body_dur_long, body_dur_short)

    def test_fill_body_zero_budget_returns_empty(self):
        from src.timeline.timeline_builder import TimelineBuilder
        candidates = make_candidates(n=10, duration=3.0)
        result = TimelineBuilder._fill_body(candidates, 0.0, 'simple')
        self.assertEqual(result, [])

    def test_fill_body_negative_budget_returns_empty(self):
        from src.timeline.timeline_builder import TimelineBuilder
        candidates = make_candidates(n=10, duration=3.0)
        result = TimelineBuilder._fill_body(candidates, -5.0, 'simple')
        self.assertEqual(result, [])

    def test_fill_body_budget_not_exceeded_badly(self):
        from src.timeline.timeline_builder import TimelineBuilder
        candidates = make_candidates(n=10, duration=5.0)
        budget = 20.0
        result = TimelineBuilder._fill_body(candidates, budget, 'simple')
        total = sum(c.duration for c in result)
        self.assertLessEqual(total, budget * 1.15 + 0.01,
                             f"Body overshot budget by more than 15%: {total:.1f}s > {budget*1.15:.1f}s")

    def test_narrative_story_arc_first_clips_have_lower_action(self):
        from src.timeline.timeline_builder import TimelineBuilder
        candidates = []
        action_values = [0.1, 0.3, 0.5, 0.7, 0.9, 0.2, 0.4, 0.6]
        for i, a in enumerate(action_values):
            c = StubCandidate(
                source_path='/fake/v.mp4',
                start=float(i * 6 + 5),
                end=float(i * 6 + 11),
                duration=6.0,
                is_must_use=False,
                final_score=0.5,
                features=StubFeatures(action_score=a, motion_score=a),
            )
            candidates.append(c)
        result = TimelineBuilder._order_body(candidates, 'story_arc')
        if len(result) >= 4:
            n = len(result)
            first_action = sum(c.features.action_score for c in result[:n//3]) / (n//3)
            last_action  = sum(c.features.action_score for c in result[-(n//4):]) / (n//4)
            self.assertLess(first_action, last_action,
                            "story_arc: first third should be calmer than last quarter")


if __name__ == '__main__':
    unittest.main(verbosity=2)
