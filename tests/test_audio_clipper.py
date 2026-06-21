"""
Tests for audio_clipper — graceful failure paths (no real audio files needed).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAudioClipperEdgeCases(unittest.TestCase):

    def test_missing_file_returns_none(self):
        from src.preprocessing.audio_clipper import get_or_create_audio_clip
        result = get_or_create_audio_clip('/nonexistent/audio.mp3', 0.0, 30.0)
        self.assertIsNone(result)

    def test_zero_duration_returns_none(self):
        from src.preprocessing.audio_clipper import get_or_create_audio_clip
        result = get_or_create_audio_clip('/nonexistent/audio.mp3', 10.0, 10.0)
        self.assertIsNone(result)

    def test_negative_duration_returns_none(self):
        from src.preprocessing.audio_clipper import get_or_create_audio_clip
        result = get_or_create_audio_clip('/nonexistent/audio.mp3', 30.0, 10.0)
        self.assertIsNone(result)

    def test_does_not_raise_on_missing_file(self):
        from src.preprocessing.audio_clipper import get_or_create_audio_clip
        try:
            get_or_create_audio_clip('/nonexistent/track.wav', 0.0, 60.0)
        except Exception as e:
            self.fail(f'get_or_create_audio_clip raised unexpectedly: {e}')


class TestSceneClipperEdgeCases(unittest.TestCase):

    def test_missing_video_returns_none(self):
        from src.preprocessing.scene_clipper import get_or_create_scene_clip
        result = get_or_create_scene_clip('/nonexistent/video.mp4', 0.0, 10.0)
        self.assertIsNone(result)

    def test_zero_duration_returns_none(self):
        from src.preprocessing.scene_clipper import get_or_create_scene_clip
        result = get_or_create_scene_clip('/nonexistent/video.mp4', 5.0, 5.0)
        self.assertIsNone(result)

    def test_does_not_raise_on_missing_video(self):
        from src.preprocessing.scene_clipper import get_or_create_scene_clip
        try:
            get_or_create_scene_clip('/nonexistent/video.mp4', 0.0, 15.0)
        except Exception as e:
            self.fail(f'get_or_create_scene_clip raised unexpectedly: {e}')


if __name__ == '__main__':
    unittest.main()
