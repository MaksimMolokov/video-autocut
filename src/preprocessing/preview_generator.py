"""Generate JPEG thumbnails and short video previews via FFmpeg."""

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class PreviewGenerator:
    def __init__(self, previews_dir: str, thumbnail_size: str = '320x180'):
        self.previews_dir = Path(previews_dir)
        self.previews_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_size = thumbnail_size

    def generate_thumbnail(
        self,
        source_path: str,
        start_s: float,
        end_s: float,
        fragment_id: int,
    ) -> str:
        mid_s = (start_s + end_s) / 2.0
        out_path = str(self.previews_dir / f'{fragment_id}.jpg')

        cmd = [
            'ffmpeg', '-y',
            '-ss', f'{mid_s:.3f}',
            '-i', source_path,
            '-vframes', '1',
            '-s', self.thumbnail_size,
            '-q:v', '3',
            out_path,
        ]
        try:
            subprocess.run(
                cmd, check=True, capture_output=True, timeout=15
            )
            return out_path
        except subprocess.CalledProcessError as e:
            logger.warning(
                f'[PreviewGenerator] Thumbnail failed for fragment {fragment_id}: '
                f'{e.stderr.decode(errors="replace")[-200:]}'
            )
            return ''
        except FileNotFoundError:
            logger.error('[PreviewGenerator] ffmpeg not found')
            return ''

    def generate_video_preview(
        self,
        source_path: str,
        start_s: float,
        end_s: float,
        fragment_id: int,
        max_duration: float = 3.0,
    ) -> str:
        duration = end_s - start_s
        preview_dur = min(duration, max_duration)
        # Take from the middle
        preview_start = start_s + max(0.0, (duration - preview_dur) / 2.0)
        out_path = str(self.previews_dir / f'{fragment_id}_preview.mp4')

        cmd = [
            'ffmpeg', '-y',
            '-ss', f'{preview_start:.3f}',
            '-i', source_path,
            '-t', f'{preview_dur:.3f}',
            '-vf', f'scale={self.thumbnail_size},fps=24',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
            '-an',
            out_path,
        ]
        try:
            subprocess.run(
                cmd, check=True, capture_output=True, timeout=30
            )
            return out_path
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(f'[PreviewGenerator] Video preview failed: {e}')
            return ''

    def delete_previews_for_source(self, source_id: int):
        """Remove all preview files associated with a source (uses fragment id pattern)."""
        for f in self.previews_dir.glob(f'*.jpg'):
            f.unlink(missing_ok=True)
        for f in self.previews_dir.glob(f'*_preview.mp4'):
            f.unlink(missing_ok=True)
