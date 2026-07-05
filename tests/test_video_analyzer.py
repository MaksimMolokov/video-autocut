"""Video Analyzer: ffprobe-метаданные, ошибки, ориентация."""
import subprocess

from core.video_analyzer import probe_video


def test_probe_synthetic(synthetic_video):
    v = probe_video("proj", synthetic_video)
    assert v.valid, v.error
    assert 8.5 <= v.duration <= 9.5
    assert v.width == 640 and v.height == 360
    assert abs(v.fps - 30) < 0.1
    assert v.orientation == "horizontal"
    assert v.codec == "h264"
    assert not v.has_audio


def test_probe_missing_file(tmp_path):
    v = probe_video("proj", tmp_path / "nope.mp4")
    assert not v.valid and v.error


def test_probe_broken_file(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    v = probe_video("proj", bad)
    assert not v.valid


def test_probe_vertical(media_dir):
    out = media_dir / "vertical.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=duration=2:size=360x640:rate=30",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True,
    )
    v = probe_video("proj", out)
    assert v.orientation == "vertical"


def test_probe_with_audio(media_dir):
    out = media_dir / "with_audio.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=duration=2:size=320x240:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(out)],
        check=True, capture_output=True,
    )
    v = probe_video("proj", out)
    assert v.valid and v.has_audio
