"""
Part 5 — FFmpeg integration tests.
Part 9 — Post-render validation via ffprobe.

These tests create synthetic media (solid-color videos, sine-wave audio),
run FFmpegRenderer.render(), and validate the output with ffprobe.

Requirements:
  - FFmpeg must be available (tested at module level)
  - Tests run in ~2-3 minutes total for the default 15s render

Set RUN_INTEGRATION_TESTS=0 to skip all tests in this file.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import (
    RUN_INTEGRATION, ffmpeg_available,
    create_synthetic_video, create_synthetic_audio,
    probe_file, get_video_duration, get_audio_duration, get_resolution,
    ALL_14_STYLE_IDS, TIMELINE_STYLE_IDS,
)

SKIP_MSG = "Integration tests disabled (set RUN_INTEGRATION_TESTS=1 to enable)"
FFMPEG_MISSING = "FFmpeg not available"


def _ffmpeg_ok():
    return ffmpeg_available()


def _make_segments(video_path: str, n: int = 3, seg_dur: float = 5.0, start_gap: float = 2.0):
    """Create n SelectedSegment objects from a synthetic video file."""
    from src.segment_selector import SelectedSegment
    segs = []
    for i in range(n):
        start = float(i * (seg_dur + start_gap))
        end   = start + seg_dur
        s = SelectedSegment(
            source_path=video_path,
            start=start,
            end=end,
            duration=seg_dur,
            is_must_use=False,
        )
        segs.append(s)
    return segs


def _make_segments_with_roles(video_path: str, n: int = 5, seg_dur: float = 3.0):
    """Create segments with intro/body/outro roles (simulates TimelineBuilder output)."""
    from src.segment_selector import SelectedSegment
    segs = []
    for i in range(n):
        start = float(i * (seg_dur + 1))
        end   = start + seg_dur
        s = SelectedSegment(
            source_path=video_path,
            start=start,
            end=end,
            duration=seg_dur,
            is_must_use=False,
        )
        if i == 0:
            s.role = 'intro'
            s.start_transition = 'fade_in'
            s.start_transition_duration = 0.5
            s.end_transition = ''
            s.end_transition_duration = 0.0
        elif i == n - 1:
            s.role = 'outro'
            s.start_transition = ''
            s.start_transition_duration = 0.0
            s.end_transition = 'fade_out'
            s.end_transition_duration = 0.8
        else:
            s.role = 'body'
            s.start_transition = ''
            s.start_transition_duration = 0.0
            s.end_transition = ''
            s.end_transition_duration = 0.0
        segs.append(s)
    return segs


def _output_config(duration: float, fmt: str = 'horizontal'):
    from src.config_loader import OutputConfig
    return OutputConfig(target_duration=duration, format=fmt, dynamic_level='balanced')


@unittest.skipUnless(RUN_INTEGRATION, SKIP_MSG)
@unittest.skipUnless(_ffmpeg_ok(), FFMPEG_MISSING)
class TestRenderBasic(unittest.TestCase):
    """
    5.1 — Basic render for horizontal output, 15 seconds.
    Verifies that FFmpegRenderer.render() produces a valid video file.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='vtest_')
        cls.video_path = str(Path(cls.tmp) / 'test_h.mp4')
        cls.audio_path = str(Path(cls.tmp) / 'test_audio.m4a')
        ok_v = create_synthetic_video(cls.video_path, duration=30.0, motion=True)
        ok_a = create_synthetic_audio(cls.audio_path, duration=40.0)
        if not ok_v:
            raise RuntimeError(f"Could not create synthetic video at {cls.video_path}")
        if not ok_a:
            cls.audio_path = None

    def _render(self, output_name, segments=None, fmt='horizontal',
                target=15.0, music=None, transition='none', transition_dur=0.0):
        from src.ffmpeg_renderer import FFmpegRenderer
        output_path = str(Path(self.tmp) / output_name)
        segs = segments or _make_segments(self.video_path, n=3, seg_dur=5.0)
        cfg  = _output_config(target, fmt)
        FFmpegRenderer.render(
            segments=segs,
            output_config=cfg,
            output_path=output_path,
            music_path=music,
            music_fade_in=1.0,
            music_fade_out=1.0,
            music_start_time=0.0,
            between_clip_transition=transition,
            between_clip_transition_dur=transition_dur,
        )
        return output_path

    def test_render_produces_file(self):
        out = self._render('out_basic.mp4')
        self.assertTrue(Path(out).exists(), "Output file not created")
        self.assertGreater(Path(out).stat().st_size, 1000, "Output file suspiciously small")

    def test_render_video_stream_exists(self):
        out = self._render('out_vstream.mp4')
        info = probe_file(out)
        types = [s.get('codec_type') for s in info.get('streams', [])]
        self.assertIn('video', types, "No video stream in output")

    def test_render_duration_approximately_target(self):
        target = 15.0
        out = self._render('out_dur.mp4', target=target)
        dur = get_video_duration(out)
        self.assertGreater(dur, target * 0.85,
                           f"Video duration {dur:.1f}s is much shorter than target {target}s")
        self.assertLess(dur, target * 1.20,
                        f"Video duration {dur:.1f}s is much longer than target {target}s")

    def test_render_resolution_horizontal(self):
        out = self._render('out_res_h.mp4', fmt='horizontal')
        w, h = get_resolution(out)
        self.assertGreater(w, h, f"Expected width > height for horizontal output, got {w}×{h}")

    def test_render_resolution_vertical(self):
        out = self._render('out_res_v.mp4', fmt='vertical')
        w, h = get_resolution(out)
        self.assertGreater(h, w, f"Expected height > width for vertical output, got {w}×{h}")

    def test_render_resolution_square(self):
        out = self._render('out_res_sq.mp4', fmt='square')
        w, h = get_resolution(out)
        self.assertEqual(w, h, f"Expected width == height for square output, got {w}×{h}")

    def test_render_with_music_has_audio_stream(self):
        if not self.audio_path:
            self.skipTest("Synthetic audio not created")
        out = self._render('out_music.mp4', music=self.audio_path)
        info = probe_file(out)
        types = [s.get('codec_type') for s in info.get('streams', [])]
        self.assertIn('audio', types, "No audio stream in output with music")

    def test_audio_duration_matches_video(self):
        if not self.audio_path:
            self.skipTest("Synthetic audio not created")
        target = 15.0
        out = self._render('out_sync.mp4', music=self.audio_path, target=target)
        video_dur = get_video_duration(out)
        audio_dur = get_audio_duration(out)
        if audio_dur > 0:
            gap = abs(audio_dur - video_dur)
            self.assertLess(gap, 3.0,
                            f"Audio ({audio_dur:.1f}s) and video ({video_dur:.1f}s) "
                            f"differ by {gap:.1f}s > 3s — audio longer than video bug")

    def test_validate_output_returns_ok(self):
        from src.ffmpeg_renderer import FFmpegRenderer
        target = 15.0
        out = self._render('out_validate.mp4', target=target)
        result = FFmpegRenderer._validate_output(out, target)
        self.assertIn('ok', result)
        self.assertIn('video_dur', result)
        self.assertIn('audio_dur', result)
        self.assertIn('container_dur', result)
        self.assertIn('gap', result)
        # Video stream must be present and close to target
        self.assertGreater(result['video_dur'], target * 0.80,
                           f"Validation says video_dur={result['video_dur']:.1f}s, expected ≥{target*0.80:.1f}s")

    def test_role_tagged_segments_render_correctly(self):
        """Segments with intro/body/outro roles and fade transitions should render."""
        segs = _make_segments_with_roles(self.video_path, n=5, seg_dur=3.0)
        out = self._render('out_roles.mp4', segments=segs, target=15.0)
        self.assertTrue(Path(out).exists())
        dur = get_video_duration(out)
        self.assertGreater(dur, 5.0, "Render with roles produced very short output")


@unittest.skipUnless(RUN_INTEGRATION, SKIP_MSG)
@unittest.skipUnless(_ffmpeg_ok(), FFMPEG_MISSING)
class TestRenderTransitions(unittest.TestCase):
    """
    5.4 — Transition logic is applied in the render pipeline.
    Verifies that xfade and no-transition paths both produce valid output.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='vtest_trans_')
        cls.video_path = str(Path(cls.tmp) / 'test_h.mp4')
        ok = create_synthetic_video(cls.video_path, duration=30.0, motion=True)
        if not ok:
            raise RuntimeError("Could not create synthetic video")

    def _render(self, name, transition, dur=0.5, target=15.0):
        from src.ffmpeg_renderer import FFmpegRenderer
        output_path = str(Path(self.tmp) / name)
        segs = _make_segments(self.video_path, n=3, seg_dur=5.0)
        cfg  = _output_config(target)
        FFmpegRenderer.render(
            segments=segs,
            output_config=cfg,
            output_path=output_path,
            between_clip_transition=transition,
            between_clip_transition_dur=dur,
        )
        return output_path

    def test_no_transition_renders_ok(self):
        out = self._render('out_cut.mp4', transition='none')
        self.assertTrue(Path(out).exists())
        self.assertGreater(get_video_duration(out), 5.0)

    def test_crossfade_transition_renders_ok(self):
        out = self._render('out_crossfade.mp4', transition='crossfade', dur=0.5)
        self.assertTrue(Path(out).exists())
        self.assertGreater(get_video_duration(out), 5.0)

    def test_zoom_in_transition_renders_ok(self):
        out = self._render('out_zoom.mp4', transition='zoom_in', dur=0.35)
        self.assertTrue(Path(out).exists())
        self.assertGreater(get_video_duration(out), 5.0)

    def test_fade_transition_renders_ok(self):
        out = self._render('out_fade.mp4', transition='cinematic_crossfade', dur=0.8)
        self.assertTrue(Path(out).exists())
        self.assertGreater(get_video_duration(out), 5.0)

    def test_beat_flash_transition_renders_ok(self):
        out = self._render('out_flash.mp4', transition='beat_flash', dur=0.15)
        self.assertTrue(Path(out).exists())
        self.assertGreater(get_video_duration(out), 5.0)

    def test_transition_does_not_shorten_video_severely(self):
        """Transitions reduce total duration slightly but not by >30%."""
        out_cut   = self._render('out_t_cut.mp4',   transition='none')
        out_fade  = self._render('out_t_fade.mp4',  transition='crossfade', dur=0.5)
        dur_cut   = get_video_duration(out_cut)
        dur_fade  = get_video_duration(out_fade)
        if dur_cut > 0 and dur_fade > 0:
            reduction = (dur_cut - dur_fade) / dur_cut
            self.assertLess(reduction, 0.30,
                            f"Transition reduced duration by {reduction*100:.0f}% (too much)")


@unittest.skipUnless(RUN_INTEGRATION, SKIP_MSG)
@unittest.skipUnless(_ffmpeg_ok(), FFMPEG_MISSING)
class TestRenderDuration90s(unittest.TestCase):
    """
    5.2 — 90-second render regression.
    The output must be close to 90 seconds, NOT 6-10 seconds.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='vtest_90s_')
        cls.video_path = str(Path(cls.tmp) / 'long_h.mp4')
        ok = create_synthetic_video(cls.video_path, duration=120.0, motion=True)
        if not ok:
            raise RuntimeError("Could not create synthetic 120s video")

    def test_90s_render_not_6_to_10_seconds(self):
        from src.ffmpeg_renderer import FFmpegRenderer
        target = 90.0
        output_path = str(Path(self.tmp) / 'out_90s.mp4')
        # 18 segments × 5s = 90s material
        segs = _make_segments(self.video_path, n=18, seg_dur=5.0, start_gap=1.0)
        cfg  = _output_config(target)
        FFmpegRenderer.render(
            segments=segs,
            output_config=cfg,
            output_path=output_path,
        )
        dur = get_video_duration(output_path)
        self.assertGreater(dur, 40.0,
                           f"90s target produced only {dur:.1f}s — this is the 6-10s bug!")
        self.assertGreater(dur, target * 0.70,
                           f"90s target produced only {dur:.1f}s — too short")

    def test_validate_output_ok_for_90s(self):
        from src.ffmpeg_renderer import FFmpegRenderer
        target = 90.0
        output_path = str(Path(self.tmp) / 'out_90s_val.mp4')
        segs = _make_segments(self.video_path, n=18, seg_dur=5.0, start_gap=1.0)
        cfg  = _output_config(target)
        FFmpegRenderer.render(segments=segs, output_config=cfg, output_path=output_path)
        result = FFmpegRenderer._validate_output(output_path, target)
        self.assertTrue(result.get('ok'),
                        f"Validation failed: {result.get('error')}")


@unittest.skipUnless(RUN_INTEGRATION, SKIP_MSG)
@unittest.skipUnless(_ffmpeg_ok(), FFMPEG_MISSING)
class TestOutputValidation(unittest.TestCase):
    """
    Part 9 — Post-render validation.
    Verify that _validate_output correctly detects problems.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='vtest_val_')
        cls.video_path = str(Path(cls.tmp) / 'val_h.mp4')
        ok = create_synthetic_video(cls.video_path, duration=30.0)
        if not ok:
            raise RuntimeError("Could not create synthetic video")

    def _render_and_probe(self, name, n_segs, seg_dur, target, fmt='horizontal'):
        from src.ffmpeg_renderer import FFmpegRenderer
        output_path = str(Path(self.tmp) / name)
        segs = _make_segments(self.video_path, n=n_segs, seg_dur=seg_dur, start_gap=0.5)
        cfg  = _output_config(target, fmt)
        FFmpegRenderer.render(segments=segs, output_config=cfg, output_path=output_path)
        return output_path

    def test_validate_returns_dict_with_required_keys(self):
        from src.ffmpeg_renderer import FFmpegRenderer
        out = self._render_and_probe('val_keys.mp4', 3, 5.0, 15.0)
        r   = FFmpegRenderer._validate_output(out, 15.0)
        for key in ('ok', 'container_dur', 'video_dur', 'audio_dur', 'gap', 'error'):
            self.assertIn(key, r, f"Key '{key}' missing from _validate_output result")

    def test_gap_is_negative_or_zero_without_music(self):
        """Without music, audio_dur=0, gap = 0 - video_dur < 0."""
        from src.ffmpeg_renderer import FFmpegRenderer
        out = self._render_and_probe('val_noaudio.mp4', 3, 5.0, 15.0)
        r   = FFmpegRenderer._validate_output(out, 15.0)
        self.assertLessEqual(r.get('gap', 0), 0.1,
                             "Expected gap ≤ 0 when no audio track present")

    def test_resolution_horizontal_in_output(self):
        out = self._render_and_probe('val_res_h.mp4', 3, 5.0, 15.0, 'horizontal')
        w, h = get_resolution(out)
        self.assertGreater(w, h, f"Expected horizontal (w>h), got {w}×{h}")
        # Check aspect ratio ≈ 16:9
        ratio = w / h
        self.assertAlmostEqual(ratio, 16/9, delta=0.1,
                               msg=f"Expected 16:9 aspect ratio, got {ratio:.2f}")

    def test_resolution_vertical_in_output(self):
        out = self._render_and_probe('val_res_v.mp4', 3, 5.0, 15.0, 'vertical')
        w, h = get_resolution(out)
        self.assertGreater(h, w, f"Expected vertical (h>w), got {w}×{h}")
        ratio = h / w
        self.assertAlmostEqual(ratio, 16/9, delta=0.1,
                               msg=f"Expected 9:16 aspect ratio (h/w), got {ratio:.2f}")

    def test_resolution_square_in_output(self):
        out = self._render_and_probe('val_res_sq.mp4', 3, 5.0, 15.0, 'square')
        w, h = get_resolution(out)
        self.assertEqual(w, h, f"Expected square (w==h), got {w}×{h}")


@unittest.skipUnless(RUN_INTEGRATION, SKIP_MSG)
@unittest.skipUnless(_ffmpeg_ok(), FFMPEG_MISSING)
class TestAudioFade(unittest.TestCase):
    """
    5.5 — Audio fade is applied (fade_in/out do not cause clicks).
    We verify that renders with fade complete without error and
    produce valid output. Acoustic analysis requires librosa which
    may not be installed, so we test structural correctness only.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='vtest_fade_')
        cls.video_path = str(Path(cls.tmp) / 'fade_h.mp4')
        cls.audio_path = str(Path(cls.tmp) / 'fade_audio.m4a')
        ok_v = create_synthetic_video(cls.video_path, duration=30.0)
        ok_a = create_synthetic_audio(cls.audio_path, duration=40.0, freq=440.0)
        if not ok_v or not ok_a:
            raise RuntimeError("Could not create synthetic media")

    def _render(self, name, fade_in=2.0, fade_out=2.0, target=15.0):
        from src.ffmpeg_renderer import FFmpegRenderer
        output_path = str(Path(self.tmp) / name)
        segs = _make_segments(self.video_path, n=3, seg_dur=5.0)
        cfg  = _output_config(target)
        FFmpegRenderer.render(
            segments=segs,
            output_config=cfg,
            output_path=output_path,
            music_path=self.audio_path,
            music_fade_in=fade_in,
            music_fade_out=fade_out,
        )
        return output_path

    def test_fade_in_2s_renders_ok(self):
        out = self._render('fade_in2.mp4', fade_in=2.0)
        self.assertTrue(Path(out).exists())
        self.assertGreater(get_video_duration(out), 5.0)

    def test_fade_out_3s_renders_ok(self):
        out = self._render('fade_out3.mp4', fade_out=3.0)
        self.assertTrue(Path(out).exists())
        self.assertGreater(get_video_duration(out), 5.0)

    def test_audio_stream_present_after_fade(self):
        out = self._render('fade_stream.mp4')
        info = probe_file(out)
        types = [s.get('codec_type') for s in info.get('streams', [])]
        self.assertIn('audio', types, "No audio stream after fade render")

    def test_audio_not_longer_than_video(self):
        out = self._render('fade_sync.mp4')
        video_dur = get_video_duration(out)
        audio_dur = get_audio_duration(out)
        if audio_dur > 0:
            gap = audio_dur - video_dur
            self.assertLess(gap, 3.0,
                            f"Audio ({audio_dur:.1f}s) is {gap:.1f}s longer than video ({video_dur:.1f}s)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
