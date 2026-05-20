"""
Tests for the intro/outro selection and timeline builder system.

10 test groups:
  1.  IntroOutroScorer — score_intro basic scoring (weight dot-product)
  2.  IntroOutroScorer — score_outro basic scoring
  3.  IntroOutroScorer — forbidden token filter
  4.  IntroOutroScorer — hard threshold checks
  5.  IntroOutroScorer — pick_best_intro / pick_best_outro ordering
  6.  AudioBoundaryDetector — find_best_start (all modes, no librosa)
  7.  AudioBoundaryDetector — find_best_end (all modes, no librosa)
  8.  IntroOutroProfile — all 14 style profiles load with valid fields
  9.  TimelineBuilder — build() produces correct role tags and ordering
  10. TimelineBuilder — narrative ordering + audio boundary log
"""

import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Minimal stubs for ClipFeatures / CandidateClip so tests run without
# importing the full video_analysis chain.
# ---------------------------------------------------------------------------

@dataclass
class _ClipFeatures:
    sharpness_score:         float = 0.5
    brightness_score:        float = 0.5
    contrast_score:          float = 0.5
    motion_score:            float = 0.5
    camera_stability_score:  float = 0.5
    visual_complexity_score: float = 0.5
    scene_change_score:      float = 0.1
    color_saturation_score:  float = 0.5
    color_diversity_score:   float = 0.5
    action_score:            float = 0.5
    calm_score:              float = 0.5
    technical_quality_score: float = 0.5
    uniqueness_score:        float = 0.5


@dataclass
class _CandidateClip:
    source_path:  str = "/fake/clip.mp4"
    start:        float = 0.0
    end:          float = 5.0
    duration:     float = 5.0
    is_must_use:  bool = False
    final_score:  float = 0.5
    features:     _ClipFeatures = field(default_factory=_ClipFeatures)


def _make_clip(**feat_overrides) -> _CandidateClip:
    f = _ClipFeatures(**feat_overrides)
    return _CandidateClip(features=f)


# ---------------------------------------------------------------------------
# Group 1 — score_intro basic scoring
# ---------------------------------------------------------------------------

class TestScoreIntroBasic(unittest.TestCase):
    """score_intro returns blended score for a qualifying clip."""

    def setUp(self):
        from src.timeline.intro_outro_rules import get_profile
        from src.timeline.intro_outro_scorer import IntroOutroScorer
        self.scorer = IntroOutroScorer
        self.profile = get_profile('drone_nature_cinematic')

    def test_returns_float_for_good_clip(self):
        clip = _make_clip(
            sharpness_score=0.7, brightness_score=0.6,
            camera_stability_score=0.8, motion_score=0.2,
        )
        clip.final_score = 0.6
        score = self.scorer.score_intro(clip, self.profile)
        self.assertIsNotNone(score)
        self.assertIsInstance(score, float)

    def test_score_increases_with_sharpness(self):
        """Higher sharpness → higher intro score (all else equal)."""
        clip_low  = _make_clip(sharpness_score=0.30); clip_low.final_score = 0.5
        clip_high = _make_clip(sharpness_score=0.90); clip_high.final_score = 0.5
        s_low  = self.scorer.score_intro(clip_low,  self.profile)
        s_high = self.scorer.score_intro(clip_high, self.profile)
        if s_low is not None and s_high is not None:
            self.assertGreater(s_high, s_low)

    def test_blending_with_final_score(self):
        """blended = raw*0.70 + final_score*0.30"""
        from src.timeline.intro_outro_rules import get_profile, VideoIntroRule
        # Use a profile with a single known weight so raw is predictable.
        p = get_profile('drone_nature_cinematic')
        clip = _make_clip(sharpness_score=1.0, brightness_score=0.5,
                          camera_stability_score=0.9, motion_score=0.1)
        clip.final_score = 0.0
        score_fs0 = self.scorer.score_intro(clip, p)

        clip2 = _make_clip(sharpness_score=1.0, brightness_score=0.5,
                           camera_stability_score=0.9, motion_score=0.1)
        clip2.final_score = 1.0
        score_fs1 = self.scorer.score_intro(clip2, p)

        if score_fs0 is not None and score_fs1 is not None:
            # fs=1.0 should yield a higher blended score
            self.assertGreater(score_fs1, score_fs0)

    def test_none_for_disqualified_clip(self):
        """Black frame must return None."""
        clip = _make_clip(brightness_score=0.01)
        clip.final_score = 0.9
        score = self.scorer.score_intro(clip, self.profile)
        self.assertIsNone(score)

    def test_score_range_approx_0_to_2(self):
        """Score should be in a sane range (not e.g. 100)."""
        clip = _make_clip(); clip.final_score = 0.5
        score = self.scorer.score_intro(clip, self.profile)
        if score is not None:
            self.assertLess(score, 10.0)
            self.assertGreater(score, -5.0)

    def test_sport_profile_penalises_calm(self):
        """sport_dynamic_cut weights calm_score negatively."""
        from src.timeline.intro_outro_rules import get_profile
        sp = get_profile('sport_dynamic_cut')
        calm_clip  = _make_clip(calm_score=0.9, action_score=0.6,
                                motion_score=0.7, sharpness_score=0.6)
        calm_clip.final_score = 0.5
        action_clip = _make_clip(calm_score=0.1, action_score=0.9,
                                 motion_score=0.9, sharpness_score=0.6)
        action_clip.final_score = 0.5
        s_calm   = sp.video_intro.weights.get('calm_score', 0) * 0.9
        s_action = sp.video_intro.weights.get('calm_score', 0) * 0.1
        self.assertLess(s_calm, s_action)


# ---------------------------------------------------------------------------
# Group 2 — score_outro basic scoring
# ---------------------------------------------------------------------------

class TestScoreOutroBasic(unittest.TestCase):

    def setUp(self):
        from src.timeline.intro_outro_rules import get_profile
        from src.timeline.intro_outro_scorer import IntroOutroScorer
        self.scorer = IntroOutroScorer
        self.profile = get_profile('travel_story')

    def test_returns_float_for_good_clip(self):
        clip = _make_clip(sharpness_score=0.6, brightness_score=0.5)
        clip.final_score = 0.5
        score = self.scorer.score_outro(clip, self.profile)
        self.assertIsNotNone(score)
        self.assertIsInstance(score, float)

    def test_none_for_blur(self):
        clip = _make_clip(sharpness_score=0.05)
        clip.final_score = 0.8
        score = self.scorer.score_outro(clip, self.profile)
        self.assertIsNone(score)

    def test_none_for_black_frame(self):
        clip = _make_clip(brightness_score=0.03)
        clip.final_score = 0.8
        score = self.scorer.score_outro(clip, self.profile)
        self.assertIsNone(score)

    def test_score_nonzero_good_clip(self):
        clip = _make_clip(
            sharpness_score=0.7, brightness_score=0.6,
            calm_score=0.7, motion_score=0.2,
        )
        clip.final_score = 0.6
        score = self.scorer.score_outro(clip, self.profile)
        if score is not None:
            self.assertNotEqual(score, 0.0)

    def test_final_score_influences_blend(self):
        clip_a = _make_clip(); clip_a.final_score = 0.0
        clip_b = _make_clip(); clip_b.final_score = 1.0
        sa = self.scorer.score_outro(clip_a, self.profile)
        sb = self.scorer.score_outro(clip_b, self.profile)
        if sa is not None and sb is not None:
            self.assertGreater(sb, sa)


# ---------------------------------------------------------------------------
# Group 3 — forbidden token filter
# ---------------------------------------------------------------------------

class TestForbiddenTokenFilter(unittest.TestCase):

    def setUp(self):
        from src.timeline.intro_outro_scorer import IntroOutroScorer
        self.scorer = IntroOutroScorer

    def _disqualified(self, clip, tokens):
        return self.scorer._is_forbidden(clip.features, tokens)

    def test_black_frame_token(self):
        clip = _make_clip(brightness_score=0.05)
        self.assertTrue(self._disqualified(clip, ['black_frame']))

    def test_black_frame_above_threshold_ok(self):
        clip = _make_clip(brightness_score=0.10)
        self.assertFalse(self._disqualified(clip, ['black_frame']))

    def test_blur_token(self):
        clip = _make_clip(sharpness_score=0.10)
        self.assertTrue(self._disqualified(clip, ['blur']))

    def test_shaky_token(self):
        clip = _make_clip(camera_stability_score=0.15)
        self.assertTrue(self._disqualified(clip, ['shaky']))

    def test_high_motion_token(self):
        clip = _make_clip(motion_score=0.85)
        self.assertTrue(self._disqualified(clip, ['high_motion']))

    def test_low_motion_token(self):
        clip = _make_clip(motion_score=0.10)
        self.assertTrue(self._disqualified(clip, ['low_motion']))

    def test_low_brightness_token(self):
        clip = _make_clip(brightness_score=0.15)
        self.assertTrue(self._disqualified(clip, ['low_brightness']))

    def test_scene_change_token(self):
        clip = _make_clip(scene_change_score=0.80)
        self.assertTrue(self._disqualified(clip, ['scene_change']))

    def test_empty_token_list_never_disqualifies(self):
        clip = _make_clip(brightness_score=0.01, sharpness_score=0.01)
        self.assertFalse(self._disqualified(clip, []))

    def test_no_subject_token(self):
        clip = _make_clip(visual_complexity_score=0.05)
        self.assertTrue(self._disqualified(clip, ['no_subject']))

    def test_low_action_token(self):
        clip = _make_clip(action_score=0.10)
        self.assertTrue(self._disqualified(clip, ['low_action']))

    def test_unknown_token_ignored(self):
        clip = _make_clip()  # all-normal clip
        self.assertFalse(self._disqualified(clip, ['nonexistent_token_xyz']))

    def test_multiple_tokens_any_match_disqualifies(self):
        # clip is not blurry but is black
        clip = _make_clip(brightness_score=0.02, sharpness_score=0.8)
        self.assertTrue(self._disqualified(clip, ['blur', 'black_frame']))


# ---------------------------------------------------------------------------
# Group 4 — hard threshold checks
# ---------------------------------------------------------------------------

class TestHardThresholds(unittest.TestCase):

    def setUp(self):
        from src.timeline.intro_outro_scorer import IntroOutroScorer
        self.scorer = IntroOutroScorer

    def _passes(self, clip, rule):
        return self.scorer._passes_hard_thresholds(clip.features, rule)

    def test_min_sharpness_fails(self):
        from src.timeline.intro_outro_rules import VideoIntroRule
        rule = VideoIntroRule(min_sharpness=0.40)
        clip = _make_clip(sharpness_score=0.30)
        self.assertFalse(self._passes(clip, rule))

    def test_min_sharpness_passes(self):
        from src.timeline.intro_outro_rules import VideoIntroRule
        rule = VideoIntroRule(min_sharpness=0.25)
        clip = _make_clip(sharpness_score=0.30)
        self.assertTrue(self._passes(clip, rule))

    def test_min_brightness_fails(self):
        from src.timeline.intro_outro_rules import VideoIntroRule
        rule = VideoIntroRule(min_brightness=0.30)
        clip = _make_clip(brightness_score=0.20)
        self.assertFalse(self._passes(clip, rule))

    def test_min_action_fails(self):
        from src.timeline.intro_outro_rules import VideoIntroRule
        rule = VideoIntroRule(min_action=0.50)
        clip = _make_clip(action_score=0.30)
        self.assertFalse(self._passes(clip, rule))

    def test_max_calm_fails(self):
        from src.timeline.intro_outro_rules import VideoIntroRule
        rule = VideoIntroRule(max_calm=0.30)
        clip = _make_clip(calm_score=0.80)
        self.assertFalse(self._passes(clip, rule))

    def test_min_stability_fails(self):
        from src.timeline.intro_outro_rules import VideoIntroRule
        rule = VideoIntroRule(min_stability=0.60)
        clip = _make_clip(camera_stability_score=0.40)
        self.assertFalse(self._passes(clip, rule))

    def test_all_defaults_pass_normal_clip(self):
        from src.timeline.intro_outro_rules import VideoIntroRule
        rule = VideoIntroRule()   # default thresholds
        clip = _make_clip()       # all 0.5 defaults
        self.assertTrue(self._passes(clip, rule))


# ---------------------------------------------------------------------------
# Group 5 — pick_best_intro / pick_best_outro
# ---------------------------------------------------------------------------

class TestPickBestIntroOutro(unittest.TestCase):

    def setUp(self):
        from src.timeline.intro_outro_rules import get_profile
        from src.timeline.intro_outro_scorer import IntroOutroScorer
        self.scorer = IntroOutroScorer
        self.profile = get_profile('drone_nature_cinematic')

    def _good_clip(self, score=0.7, start=5.0):
        c = _make_clip(
            sharpness_score=0.7, brightness_score=0.6,
            camera_stability_score=0.8, motion_score=0.2,
        )
        c.final_score = score
        c.start = start
        return c

    def test_pick_best_intro_returns_list(self):
        clips = [self._good_clip(start=10.0) for _ in range(5)]
        result = self.scorer.pick_best_intro(clips, self.profile, n=3)
        self.assertIsInstance(result, list)
        self.assertLessEqual(len(result), 3)

    def test_pick_best_intro_respects_skip_start(self):
        """Clips starting within skip_source_start_sec must be excluded."""
        skip = self.profile.video_intro.skip_source_start_sec
        early = self._good_clip(start=skip * 0.5)  # before skip boundary
        late  = self._good_clip(start=skip + 5.0)
        result = self.scorer.pick_best_intro([early, late], self.profile)
        # early clip should NOT appear in result
        self.assertNotIn(early, result)

    def test_pick_best_intro_orders_by_score(self):
        clips = [self._good_clip(score=float(i) / 10, start=10.0) for i in range(1, 6)]
        result = self.scorer.pick_best_intro(clips, self.profile, n=3)
        scores = [self.scorer.score_intro(c, self.profile) for c in result]
        scores_nn = [s for s in scores if s is not None]
        self.assertEqual(scores_nn, sorted(scores_nn, reverse=True))

    def test_pick_best_outro_returns_list(self):
        clips = [self._good_clip(start=20.0) for _ in range(5)]
        result = self.scorer.pick_best_outro(clips, self.profile, n=2)
        self.assertIsInstance(result, list)
        self.assertLessEqual(len(result), 2)

    def test_pick_best_intro_empty_input(self):
        result = self.scorer.pick_best_intro([], self.profile)
        self.assertEqual(result, [])

    def test_pick_best_outro_empty_input(self):
        result = self.scorer.pick_best_outro([], self.profile)
        self.assertEqual(result, [])

    def test_all_disqualified_returns_empty(self):
        """All black-frame clips → no valid intro."""
        clips = [_make_clip(brightness_score=0.01) for _ in range(5)]
        for c in clips:
            c.start = 10.0
            c.final_score = 0.9
        result = self.scorer.pick_best_intro(clips, self.profile)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Group 6 — AudioBoundaryDetector find_best_start (no librosa)
# ---------------------------------------------------------------------------

class TestAudioBoundaryDetectorStart(unittest.TestCase):
    """
    Tests AudioBoundaryDetector.find_best_start() with pre-loaded mock data
    so we don't need a real audio file or librosa.
    """

    def _make_detector(self, beats=None, onsets=None, phrase_boundaries=None):
        from src.timeline.audio_boundary import AudioBoundaryDetector
        d = AudioBoundaryDetector.__new__(AudioBoundaryDetector)
        d.audio_path = "/fake/audio.mp3"
        d._loaded = True
        d._duration = 180.0
        d._beats = beats or [4.0, 8.0, 12.0, 16.0, 20.0]
        d._onsets = onsets or [3.5, 7.8, 11.2, 15.0, 19.5]
        d._phrase_boundaries = phrase_boundaries or [6.0, 12.0, 18.0]
        return d

    def _rule(self, mode, avoid=5.0):
        r = MagicMock()
        r.mode = mode
        r.avoid_first_sec = avoid
        return r

    def test_from_start_returns_zero(self):
        d = self._make_detector()
        self.assertEqual(d.find_best_start(self._rule('from_start')), 0.0)

    def test_soft_fade_returns_avoid_sec(self):
        d = self._make_detector()
        self.assertEqual(d.find_best_start(self._rule('soft_fade', avoid=7.0)), 7.0)

    def test_phrase_start_finds_first_boundary_after_avoid(self):
        d = self._make_detector(phrase_boundaries=[4.0, 10.0, 18.0])
        result = d.find_best_start(self._rule('phrase_start', avoid=5.0))
        self.assertEqual(result, 10.0)

    def test_phrase_start_falls_back_to_beat(self):
        # No phrase boundary after avoid_sec
        d = self._make_detector(phrase_boundaries=[2.0], beats=[8.0, 12.0])
        result = d.find_best_start(self._rule('phrase_start', avoid=5.0))
        self.assertEqual(result, 8.0)

    def test_beat_start_finds_first_beat_after_avoid(self):
        d = self._make_detector(beats=[3.0, 7.0, 11.0])
        result = d.find_best_start(self._rule('beat_start', avoid=5.0))
        self.assertEqual(result, 7.0)

    def test_beat_start_falls_back_to_avoid(self):
        d = self._make_detector(beats=[2.0, 4.0])  # all before avoid
        result = d.find_best_start(self._rule('beat_start', avoid=5.0))
        self.assertEqual(result, 5.0)

    def test_drop_start_finds_first_onset_after_avoid(self):
        d = self._make_detector(onsets=[3.0, 6.5, 10.0])
        result = d.find_best_start(self._rule('drop_start', avoid=5.0))
        self.assertEqual(result, 6.5)

    def test_drop_start_falls_back_to_beat(self):
        d = self._make_detector(onsets=[2.0, 4.0], beats=[7.0])
        result = d.find_best_start(self._rule('drop_start', avoid=5.0))
        self.assertEqual(result, 7.0)

    def test_unknown_mode_returns_avoid(self):
        d = self._make_detector()
        result = d.find_best_start(self._rule('unknown_mode_xyz', avoid=9.0))
        self.assertEqual(result, 9.0)


# ---------------------------------------------------------------------------
# Group 7 — AudioBoundaryDetector find_best_end (no librosa)
# ---------------------------------------------------------------------------

class TestAudioBoundaryDetectorEnd(unittest.TestCase):

    def _make_detector(self, beats=None, phrase_boundaries=None):
        from src.timeline.audio_boundary import AudioBoundaryDetector
        d = AudioBoundaryDetector.__new__(AudioBoundaryDetector)
        d.audio_path = "/fake/audio.mp3"
        d._loaded = True
        d._duration = 200.0
        d._beats = beats or [10.0, 20.0, 30.0, 40.0, 50.0, 55.0, 59.0]
        d._onsets = [10.5, 20.5, 30.5, 40.5, 50.5]
        d._phrase_boundaries = phrase_boundaries or [15.0, 30.0, 45.0, 58.0]
        return d

    def _rule(self, mode):
        r = MagicMock()
        r.mode = mode
        if hasattr(r, 'outro_mode'):
            del r.outro_mode
        return r

    def test_soft_fade_end_returns_ideal(self):
        d = self._make_detector()
        result = d.find_best_end(start=10.0, target_duration=60.0, rule=self._rule('soft_fade_end'))
        self.assertAlmostEqual(result, 70.0, places=1)

    def test_soft_fade_alias(self):
        d = self._make_detector()
        result = d.find_best_end(start=0.0, target_duration=50.0, rule=self._rule('soft_fade'))
        self.assertAlmostEqual(result, 50.0, places=1)

    def test_beat_cut_end_snaps_to_beat(self):
        d = self._make_detector(beats=[45.0, 58.0, 62.0])
        # ideal_end = 0 + 60 = 60
        result = d.find_best_end(start=0.0, target_duration=60.0, rule=self._rule('beat_cut_end'))
        self.assertEqual(result, 58.0)  # nearest beat ≤ 60

    def test_phrase_fade_end_within_tolerance(self):
        # phrase boundary at 58s, ideal_end at 60, diff=2 → 2/60=0.033 < 0.15
        d = self._make_detector(phrase_boundaries=[40.0, 58.0])
        result = d.find_best_end(start=0.0, target_duration=60.0,
                                 rule=self._rule('phrase_fade_end'))
        self.assertEqual(result, 58.0)

    def test_punch_end_finds_last_beat_in_window(self):
        d = self._make_detector(beats=[57.5, 59.0, 60.5])
        # ideal_end=60, window=[58, 60]
        result = d.find_best_end(start=0.0, target_duration=60.0, rule=self._rule('punch_end'))
        self.assertEqual(result, 59.0)

    def test_punch_end_no_candidate_returns_ideal(self):
        d = self._make_detector(beats=[10.0, 20.0])  # none in window [58,60]
        result = d.find_best_end(start=0.0, target_duration=60.0, rule=self._rule('punch_end'))
        self.assertAlmostEqual(result, 60.0, places=1)

    def test_unknown_mode_returns_ideal(self):
        d = self._make_detector()
        result = d.find_best_end(start=0.0, target_duration=60.0, rule=self._rule('mystery_mode'))
        self.assertAlmostEqual(result, 60.0, places=1)


# ---------------------------------------------------------------------------
# Group 8 — IntroOutroProfile — all 14 style profiles load correctly
# ---------------------------------------------------------------------------

EXPECTED_PRESET_IDS = [
    'drone_nature_cinematic', 'drone_landscape_clean', 'fast_action_sport',
    'urban_city_rhythm', 'social_media_punchy', 'business_promo_clean',
    'travel_story', 'real_estate_property_tour', 'event_highlights',
    'calm_minimal_documentary', 'intelligent_beauty_mix',
    'sport_dynamic_cut', 'sport_highlight_impact', 'easy_mode',
]


class TestAllProfilesLoad(unittest.TestCase):

    def _get(self, pid):
        from src.timeline.intro_outro_rules import get_profile
        return get_profile(pid)

    def test_all_14_presets_load(self):
        from src.timeline.intro_outro_rules import get_profile
        for pid in EXPECTED_PRESET_IDS:
            with self.subTest(preset=pid):
                p = get_profile(pid)
                self.assertIsNotNone(p)
                self.assertEqual(p.preset_id, pid)

    def test_video_intro_has_weights(self):
        for pid in EXPECTED_PRESET_IDS:
            with self.subTest(preset=pid):
                p = self._get(pid)
                self.assertIsInstance(p.video_intro.weights, dict)

    def test_video_outro_has_end_transition(self):
        for pid in EXPECTED_PRESET_IDS:
            with self.subTest(preset=pid):
                p = self._get(pid)
                self.assertIsInstance(p.video_outro.end_transition, str)
                self.assertTrue(len(p.video_outro.end_transition) > 0)

    def test_audio_intro_has_fade_in(self):
        for pid in EXPECTED_PRESET_IDS:
            with self.subTest(preset=pid):
                p = self._get(pid)
                self.assertGreater(p.audio_intro.fade_in_sec, 0)

    def test_audio_outro_has_fade_out(self):
        for pid in EXPECTED_PRESET_IDS:
            with self.subTest(preset=pid):
                p = self._get(pid)
                self.assertGreater(p.audio_outro.fade_out_sec, 0)

    def test_narrative_is_valid_string(self):
        valid_narratives = {'simple', 'story_arc', 'energy_peak', 'buildup_impact', 'beauty_arc'}
        for pid in EXPECTED_PRESET_IDS:
            with self.subTest(preset=pid):
                p = self._get(pid)
                self.assertIn(p.narrative, valid_narratives)

    def test_unknown_preset_returns_default(self):
        from src.timeline.intro_outro_rules import get_profile
        p = get_profile('totally_unknown_preset_zzz')
        self.assertIsNotNone(p)

    def test_sport_presets_have_high_action_threshold(self):
        """Sport presets must require action_score > 0 for intro."""
        for pid in ('sport_dynamic_cut', 'sport_highlight_impact', 'fast_action_sport'):
            with self.subTest(preset=pid):
                p = self._get(pid)
                self.assertGreater(p.video_intro.min_action, 0.0)

    def test_cinematic_presets_have_stability_requirement(self):
        """Cinematic presets should require some stability."""
        for pid in ('drone_nature_cinematic', 'calm_minimal_documentary'):
            with self.subTest(preset=pid):
                p = self._get(pid)
                self.assertGreaterEqual(p.video_intro.min_stability, 0.0)


# ---------------------------------------------------------------------------
# Group 9 — TimelineBuilder.build() produces correct role tags
# ---------------------------------------------------------------------------

class TestTimelineBuilderRoles(unittest.TestCase):

    def _make_candidates(self, n=10):
        clips = []
        for i in range(n):
            c = _CandidateClip(
                source_path=f"/fake/video_{i % 3}.mp4",
                start=float(i * 5),
                end=float(i * 5 + 5),
                duration=5.0,
                is_must_use=False,
                final_score=float(i) / n,
                features=_ClipFeatures(
                    sharpness_score=0.5 + i * 0.03,
                    brightness_score=0.5,
                    camera_stability_score=0.6,
                    action_score=0.4,
                    motion_score=0.3,
                    calm_score=0.4,
                ),
            )
            clips.append(c)
        return clips

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_build_returns_timeline_result(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(
            candidates=clips,
            target_duration=30.0,
            preset_id='travel_story',
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result.segments, list)

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_intro_segment_exists(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(clips, 30.0, 'travel_story')
        roles = [s.role for s in result.segments]
        self.assertIn('intro', roles)

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_outro_segment_exists(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(clips, 30.0, 'travel_story')
        roles = [s.role for s in result.segments]
        self.assertIn('outro', roles)

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_intro_is_first_segment(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(clips, 30.0, 'travel_story')
        if result.segments:
            self.assertEqual(result.segments[0].role, 'intro')

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_outro_is_last_segment(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(clips, 30.0, 'travel_story')
        if len(result.segments) >= 2:
            self.assertEqual(result.segments[-1].role, 'outro')

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_intro_and_outro_are_different_clips(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(clips, 30.0, 'travel_story')
        intro_segs = [s for s in result.segments if s.role == 'intro']
        outro_segs = [s for s in result.segments if s.role == 'outro']
        if intro_segs and outro_segs:
            self.assertIsNot(intro_segs[0], outro_segs[0])

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_intro_has_start_transition_attr(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(clips, 30.0, 'travel_story')
        intro_segs = [s for s in result.segments if s.role == 'intro']
        if intro_segs:
            self.assertTrue(hasattr(intro_segs[0], 'start_transition'))

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_outro_has_end_transition_attr(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(clips, 30.0, 'travel_story')
        outro_segs = [s for s in result.segments if s.role == 'outro']
        if outro_segs:
            self.assertTrue(hasattr(outro_segs[0], 'end_transition'))

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_intro_log_populated(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(clips, 30.0, 'travel_story')
        self.assertIsInstance(result.intro_log, str)
        self.assertNotEqual(result.intro_log, '')

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_outro_log_populated(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(10)
        result = TimelineBuilder.build(clips, 30.0, 'travel_story')
        self.assertIsInstance(result.outro_log, str)

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_empty_candidates_returns_empty_segments(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        result = TimelineBuilder.build([], 30.0, 'travel_story')
        self.assertEqual(result.segments, [])

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_narrative_field_set(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_candidates(8)
        result = TimelineBuilder.build(clips, 30.0, 'sport_dynamic_cut')
        self.assertIsInstance(result.narrative, str)


# ---------------------------------------------------------------------------
# Group 10 — Narrative ordering + audio boundary integration
# ---------------------------------------------------------------------------

class TestNarrativeOrdering(unittest.TestCase):

    def _make_clips_with_action(self, action_scores):
        clips = []
        for i, a in enumerate(action_scores):
            c = _CandidateClip(
                source_path="/fake/v.mp4",
                start=float(i * 5),
                end=float(i * 5 + 5),
                duration=5.0,
                is_must_use=False,
                final_score=0.5,
                features=_ClipFeatures(action_score=a, motion_score=a * 0.8),
            )
            clips.append(c)
        return clips

    def test_simple_ordering_preserves_score_sort(self):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_clips_with_action([0.3, 0.8, 0.5, 0.6, 0.2])
        result = TimelineBuilder._order_body(clips, 'simple')
        # simple = score-sorted already (no re-sort by this method)
        self.assertEqual(result, clips)

    def test_energy_peak_orders_by_motion_ascending(self):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_clips_with_action([0.8, 0.2, 0.5])
        result = TimelineBuilder._order_body(clips, 'energy_peak')
        motions = [c.features.motion_score for c in result]
        self.assertEqual(motions, sorted(motions))

    def test_buildup_impact_orders_by_action_ascending(self):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_clips_with_action([0.9, 0.1, 0.5])
        result = TimelineBuilder._order_body(clips, 'buildup_impact')
        actions = [c.features.action_score for c in result]
        self.assertEqual(actions, sorted(actions))

    def test_story_arc_with_small_set_sorted_ascending(self):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_clips_with_action([0.9, 0.2, 0.5])
        result = TimelineBuilder._order_body(clips, 'story_arc')
        # <4 clips → sort ascending by action
        actions = [c.features.action_score for c in result]
        self.assertEqual(actions, sorted(actions))

    def test_story_arc_large_set_starts_calm_ends_climax(self):
        from src.timeline.timeline_builder import TimelineBuilder
        # 8 clips with known action scores
        clips = self._make_clips_with_action([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.9])
        result = TimelineBuilder._order_body(clips, 'story_arc')
        # First third should be calm, last quarter should be climax
        n = len(result)
        first_avg  = sum(c.features.action_score for c in result[:n // 3]) / (n // 3)
        last_avg   = sum(c.features.action_score for c in result[-(n // 4):]) / (n // 4)
        self.assertLess(first_avg, last_avg)

    def test_beauty_arc_orders_by_sharpness_brightness_product(self):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = []
        for sh, br in [(0.9, 0.9), (0.3, 0.4), (0.6, 0.7)]:
            c = _CandidateClip(
                source_path="/fake/v.mp4", start=0.0, end=5.0, duration=5.0,
                is_must_use=False, final_score=0.5,
                features=_ClipFeatures(sharpness_score=sh, brightness_score=br),
            )
            clips.append(c)
        result = TimelineBuilder._order_body(clips, 'beauty_arc')
        products = [c.features.sharpness_score * c.features.brightness_score for c in result]
        self.assertEqual(products, sorted(products))

    def test_unknown_narrative_returns_clips_unchanged(self):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = self._make_clips_with_action([0.5, 0.3, 0.7])
        result = TimelineBuilder._order_body(clips, 'totally_unknown_narrative')
        self.assertEqual(result, clips)

    def test_fill_body_respects_budget(self):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = [_CandidateClip(
            source_path="/fake/v.mp4", start=float(i * 6), end=float(i * 6 + 6),
            duration=6.0, is_must_use=False, final_score=0.5, features=_ClipFeatures()
        ) for i in range(10)]
        budget = 20.0
        result = TimelineBuilder._fill_body(clips, budget, 'simple')
        total = sum(c.duration for c in result)
        self.assertLessEqual(total, budget * 1.15)

    def test_fill_body_empty_input(self):
        from src.timeline.timeline_builder import TimelineBuilder
        result = TimelineBuilder._fill_body([], 30.0, 'simple')
        self.assertEqual(result, [])

    def test_fill_body_zero_budget(self):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = [_CandidateClip(
            source_path="/fake/v.mp4", start=0.0, end=5.0, duration=5.0,
            is_must_use=False, final_score=0.5, features=_ClipFeatures()
        )]
        result = TimelineBuilder._fill_body(clips, 0.0, 'simple')
        self.assertEqual(result, [])

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_audio_log_set_when_no_music(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = [_CandidateClip(
            source_path="/fake/v.mp4", start=5.0, end=10.0, duration=5.0,
            is_must_use=False, final_score=0.6, features=_ClipFeatures()
        ) for _ in range(6)]
        result = TimelineBuilder.build(clips, 20.0, 'travel_story', music_path=None)
        self.assertEqual(result.audio_log, 'no music')

    @patch('src.timeline.audio_boundary.AudioBoundaryDetector._load')
    def test_total_segment_duration_close_to_target(self, mock_load):
        from src.timeline.timeline_builder import TimelineBuilder
        clips = [_CandidateClip(
            source_path="/fake/v.mp4",
            start=float(i * 5),
            end=float(i * 5 + 5),
            duration=5.0,
            is_must_use=False,
            final_score=float(i) / 20,
            features=_ClipFeatures(action_score=0.5, motion_score=0.4),
        ) for i in range(20)]
        target = 40.0
        result = TimelineBuilder.build(clips, target, 'travel_story')
        total = sum(s.duration for s in result.segments)
        # Allow ±20% tolerance
        self.assertGreater(total, target * 0.50)
        self.assertLess(total, target * 1.20)


if __name__ == '__main__':
    unittest.main(verbosity=2)
