"""Previews: thumbnail, preview clip, кадр для LLM."""
import subprocess

from core.previews import extract_frame, make_preview_clip, make_thumbnail


def _probe(path, key):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", f"stream={key}", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return out.stdout.strip().split(",")[0]


def test_thumbnail(synthetic_video, tmp_path):
    out = tmp_path / "t.jpg"
    assert make_thumbnail(str(synthetic_video), 1.0, out)
    assert int(_probe(out, "width")) == 480


def test_preview_clip(synthetic_video, tmp_path):
    out = tmp_path / "p.mp4"
    assert make_preview_clip(str(synthetic_video), 1.0, 3.0, out)
    assert int(_probe(out, "height")) == 360
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip())
    assert 1.7 <= dur <= 2.3


def test_extract_frame_downscale(synthetic_video, tmp_path):
    out = tmp_path / "f.jpg"
    assert extract_frame(str(synthetic_video), 1.0, out, max_side=320)
    assert max(int(_probe(out, "width")), int(_probe(out, "height"))) == 320


def test_fail_on_missing_source(tmp_path):
    assert not make_thumbnail("/nonexistent.mp4", 1.0, tmp_path / "x.jpg")
    assert not make_preview_clip("/nonexistent.mp4", 0, 1, tmp_path / "x.mp4")
