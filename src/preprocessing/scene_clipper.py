"""
Extracts short video preview clips for scenes using ffmpeg. Results are cached.
Clips are stored in the system temp directory and re-used across runs.
"""
import hashlib
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CLIP_DIR = Path(tempfile.gettempdir()) / 'video_editor_scene_clips'


def get_or_create_scene_clip(
    video_path: str,
    start_s: float,
    end_s: float,
    max_duration_s: float = 15.0,
    height: int = 360,
) -> Optional[str]:
    """
    Extract a preview video clip from video_path[start_s : min(end_s, start_s+max_duration_s)].
    Returns the path to the cached mp4 file, or None on failure.
    """
    if not Path(video_path).exists():
        return None

    _CLIP_DIR.mkdir(parents=True, exist_ok=True)
    clip_dur = min(end_s - start_s, max_duration_s)
    if clip_dur <= 0:
        return None

    key = f"{video_path}|{start_s:.3f}|{end_s:.3f}|{height}"
    clip_path = _CLIP_DIR / (hashlib.md5(key.encode()).hexdigest() + '.mp4')

    if clip_path.exists() and clip_path.stat().st_size > 1024:
        return str(clip_path)

    try:
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(start_s),
            '-i', video_path,
            '-t', str(clip_dur),
            '-vf', f'scale=-2:{height}',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
            '-an',
            '-movflags', '+faststart',
            str(clip_path),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=90)
        if r.returncode == 0 and clip_path.exists() and clip_path.stat().st_size > 1024:
            return str(clip_path)
        logger.warning('[SceneClipper] ffmpeg error: %s', r.stderr.decode()[:300])
    except subprocess.TimeoutExpired:
        logger.warning('[SceneClipper] ffmpeg timed out for %s', video_path)
    except FileNotFoundError:
        logger.warning('[SceneClipper] ffmpeg not found')
    except Exception as exc:
        logger.warning('[SceneClipper] Failed: %s', exc)
    return None
