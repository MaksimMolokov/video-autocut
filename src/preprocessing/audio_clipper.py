"""
Extracts audio preview clips for music fragments using ffmpeg. Results are cached.
Clips are stored in the system temp directory and re-used across runs.
"""
import hashlib
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_AUDIO_CLIP_DIR = Path(tempfile.gettempdir()) / 'video_editor_audio_clips'


def get_or_create_audio_clip(
    audio_path: str,
    start_s: float,
    end_s: float,
    fade_s: float = 0.4,
) -> Optional[str]:
    """
    Extract audio segment audio_path[start_s:end_s] with a short fade-in/out.
    Returns path to cached mp3 file, or None on failure.
    """
    if not Path(audio_path).exists():
        return None

    dur = end_s - start_s
    if dur <= 0:
        return None

    _AUDIO_CLIP_DIR.mkdir(parents=True, exist_ok=True)

    key = f"{audio_path}|{start_s:.3f}|{end_s:.3f}"
    clip_path = _AUDIO_CLIP_DIR / (hashlib.md5(key.encode()).hexdigest() + '.mp3')

    if clip_path.exists() and clip_path.stat().st_size > 512:
        return str(clip_path)

    actual_fade = min(fade_s, dur * 0.08)
    af = (
        f'afade=t=in:st=0:d={actual_fade:.3f},'
        f'afade=t=out:st={max(0.0, dur - actual_fade):.3f}:d={actual_fade:.3f}'
    )

    try:
        cmd = [
            'ffmpeg', '-y',
            '-ss', str(start_s),
            '-i', audio_path,
            '-t', str(dur),
            '-af', af,
            '-c:a', 'libmp3lame', '-q:a', '4',
            str(clip_path),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        if r.returncode == 0 and clip_path.exists() and clip_path.stat().st_size > 512:
            return str(clip_path)
        logger.warning('[AudioClipper] ffmpeg error: %s', r.stderr.decode()[:300])
    except subprocess.TimeoutExpired:
        logger.warning('[AudioClipper] ffmpeg timed out for %s', audio_path)
    except FileNotFoundError:
        logger.warning('[AudioClipper] ffmpeg not found')
    except Exception as exc:
        logger.warning('[AudioClipper] Failed: %s', exc)
    return None
