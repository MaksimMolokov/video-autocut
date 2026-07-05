"""Previews (ТЗ §7.6): thumbnail и preview-клип сцены через ffmpeg."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import config

log = logging.getLogger(__name__)


def make_thumbnail(video_path: str, timecode: float, out_path: Path) -> bool:
    """JPEG-миниатюра кадра сцены."""
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{timecode:.3f}", "-i", video_path,
        "-frames:v", "1",
        "-vf", f"scale={config.THUMB_WIDTH}:-2",
        "-q:v", "4",
        str(out_path),
    ]
    return _run(cmd, out_path)


def make_preview_clip(video_path: str, start: float, end: float, out_path: Path) -> bool:
    """Лёгкий mp4-клип сцены для воспроизведения в каталоге (ТЗ §10, §15)."""
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{start:.3f}", "-i", video_path,
        "-t", f"{end - start:.3f}",
        "-vf", f"scale=-2:{config.PREVIEW_HEIGHT}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(config.PREVIEW_CRF),
        "-an", "-movflags", "+faststart",
        str(out_path),
    ]
    return _run(cmd, out_path)


def extract_frame(video_path: str, timecode: float, out_path: Path,
                  max_side: int = config.FRAME_MAX_SIDE) -> bool:
    """Кадр для отправки в LLM: даунскейл до max_side по длинной стороне
    (SPEC §5.1: качество анализа не падает, prefill в 2–3 раза быстрее)."""
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{timecode:.3f}", "-i", video_path,
        "-frames:v", "1",
        "-vf", f"scale='if(gt(iw,ih),{max_side},-2)':'if(gt(iw,ih),-2,{max_side})'",
        "-q:v", "3",
        str(out_path),
    ]
    return _run(cmd, out_path)


def _run(cmd: list[str], out_path: Path) -> bool:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        ok = res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0
        if not ok:
            log.warning("ffmpeg fail (%s): %s", out_path.name, res.stderr.strip()[:300])
        return ok
    except (subprocess.TimeoutExpired, OSError) as e:
        log.warning("ffmpeg exception (%s): %s", out_path.name, e)
        return False
