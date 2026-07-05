"""Фикстуры: синтетическое видео (3 контрастные сцены), музыка с битами,
изолированное хранилище (PROJECTS_DIR → tmp)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

import config
from core.storage import Storage


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("media")


@pytest.fixture(scope="session")
def synthetic_video(media_dir: Path) -> Path:
    """9-секундное видео из 3 визуально разных сцен (жёсткие склейки)."""
    parts = []
    for i, src in enumerate(["testsrc2", "smptebars", "rgbtestsrc"]):
        part = media_dir / f"part{i}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error",
             "-f", "lavfi", "-i", f"{src}=duration=3:size=640x360:rate=30",
             "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
             str(part)],
            check=True, capture_output=True,
        )
        parts.append(part)
    concat = media_dir / "concat.txt"
    concat.write_text("".join(f"file '{p}'\n" for p in parts))
    out = media_dir / "synthetic.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(concat), "-c", "copy", str(out)],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture(scope="session")
def synthetic_music(media_dir: Path) -> Path:
    """10 секунд: клики на 120 BPM + нарастающая громкость (для energy curve)."""
    import soundfile as sf

    sr = 22050
    dur = 10.0
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    audio = np.zeros_like(t)
    # клик каждые 0.5 c (120 BPM)
    for beat in np.arange(0.0, dur, 0.5):
        idx = int(beat * sr)
        n = min(1500, len(audio) - idx)
        click = np.sin(2 * np.pi * 1000 * t[:n]) * np.exp(-t[:n] * 60)
        audio[idx:idx + n] += click
    # нарастание энергии к концу
    audio *= np.linspace(0.3, 1.0, len(audio))
    audio += 0.05 * np.sin(2 * np.pi * 220 * t)  # фоновый тон
    out = media_dir / "music.wav"
    sf.write(out, audio / max(abs(audio).max(), 1e-9), sr)
    return out


@pytest.fixture(scope="session")
def shaky_video(media_dir: Path) -> Path:
    """4 секунды сильно дёрганой камеры: кроп прыгает случайно каждый кадр."""
    out = media_dir / "shaky.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=duration=4:size=800x450:rate=30",
         "-vf", ("crop=640:360:"
                 "x='floor(random(1)*160)':y='floor(random(2)*90)'"),
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture(scope="session")
def smooth_pan_video(media_dir: Path) -> Path:
    """4 секунды плавной панорамы: кроп равномерно едет слева направо."""
    out = media_dir / "smooth_pan.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=duration=4:size=800x450:rate=30",
         "-vf", "crop=640:360:x='(iw-ow)*t/4':y=45",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture()
def storage(tmp_path, monkeypatch) -> Storage:
    """Изолированное хранилище: и БД, и папки проектов — во временной директории."""
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    s = Storage(db_path=None)
    yield s
    s.close()
