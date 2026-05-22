"""
ThumbnailService — generates and caches fragment preview images.

Usage:
    path = ThumbnailService.get_or_create(source_path, start, end)
    # Returns absolute JPEG path (str) or None on failure.

Cache location: ~/.video_editor_thumbnails/<hash>.jpg
Hash key:       md5(source_path + ":" + start_ms + ":" + end_ms)

Thread-safe: concurrent calls for the same key are safe because FFmpeg
writes to a temp file and renames atomically via Python's shutil.move.
"""

import hashlib
import logging
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_CACHE = Path.home() / ".video_editor_thumbnails"


class ThumbnailService:
    """Generate and cache single-frame JPEG previews for video fragments."""

    CACHE_DIR: Path = _DEFAULT_CACHE
    WIDTH: int = 320          # thumbnail width in pixels
    QUALITY: int = 5          # ffmpeg -q:v (1=best, 31=worst for mjpeg)
    TIMEOUT: int = 20         # seconds per ffmpeg call

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def get_or_create(
        cls,
        source_path: str,
        start: float,
        end: float,
        cache_dir: Optional[Path] = None,
    ) -> Optional[str]:
        """
        Return path to thumbnail JPEG, generating it if not cached.
        Returns None if generation fails.
        """
        dest = cls._dest_path(source_path, start, end, cache_dir)
        if dest.exists():
            return str(dest)
        return cls._generate(source_path, start, end, dest)

    @classmethod
    def get_or_create_batch(
        cls,
        items: list,          # list of (source_path, start, end)
        cache_dir: Optional[Path] = None,
        max_workers: int = 4,
    ) -> dict:
        """
        Generate thumbnails for multiple fragments in parallel.
        Returns {(source_path, start, end): path_or_None}.
        """
        results: dict = {}
        to_generate = []
        for source_path, start, end in items:
            dest = cls._dest_path(source_path, start, end, cache_dir)
            if dest.exists():
                results[(source_path, start, end)] = str(dest)
            else:
                to_generate.append((source_path, start, end, dest))

        if to_generate:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                fut_map = {
                    ex.submit(cls._generate, sp, s, e, d): (sp, s, e)
                    for sp, s, e, d in to_generate
                }
                for fut in as_completed(fut_map):
                    key = fut_map[fut]
                    try:
                        results[key] = fut.result()
                    except Exception as exc:
                        logger.debug(f"ThumbnailService batch error {key}: {exc}")
                        results[key] = None

        return results

    @classmethod
    def fragment_id(cls, source_path: str, start: float, end: float) -> str:
        """Stable 16-char hex ID for a fragment (used as cache key)."""
        raw = f"{source_path}:{int(start*1000)}:{int(end*1000)}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    @classmethod
    def cache_stats(cls, cache_dir: Optional[Path] = None) -> dict:
        d = cache_dir or cls.CACHE_DIR
        if not d.exists():
            return {"count": 0, "size_bytes": 0}
        files = list(d.glob("thumb_*.jpg"))
        size = sum(f.stat().st_size for f in files)
        return {"count": len(files), "size_bytes": size}

    @classmethod
    def clear_cache(cls, cache_dir: Optional[Path] = None) -> int:
        d = cache_dir or cls.CACHE_DIR
        if not d.exists():
            return 0
        removed = 0
        for f in d.glob("thumb_*.jpg"):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _dest_path(
        cls, source_path: str, start: float, end: float, cache_dir: Optional[Path]
    ) -> Path:
        d = cache_dir or cls.CACHE_DIR
        d.mkdir(parents=True, exist_ok=True)
        fid = cls.fragment_id(source_path, start, end)
        return d / f"thumb_{fid}.jpg"

    @classmethod
    def _generate(
        cls,
        source_path: str,
        start: float,
        end: float,
        dest: Path,
    ) -> Optional[str]:
        """Extract one frame at ~40% through the fragment and save as JPEG."""
        if not Path(source_path).exists():
            return None

        # Pick frame time: 40% into the fragment (avoids cold-start motion blur)
        duration = max(0.1, end - start)
        frame_time = start + duration * 0.4

        try:
            # Write to temp file, then rename — avoids partial files on timeout
            with tempfile.NamedTemporaryFile(
                suffix=".jpg", dir=dest.parent, delete=False
            ) as tmp:
                tmp_path = Path(tmp.name)

            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-hwaccel", "auto",
                    "-ss", f"{frame_time:.3f}",
                    "-i", str(source_path),
                    "-vframes", "1",
                    "-vf", f"scale={cls.WIDTH}:-1",
                    "-q:v", str(cls.QUALITY),
                    str(tmp_path),
                ],
                capture_output=True,
                timeout=cls.TIMEOUT,
            )

            if result.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0:
                import shutil
                shutil.move(str(tmp_path), str(dest))
                return str(dest)
            else:
                tmp_path.unlink(missing_ok=True)
                return None

        except subprocess.TimeoutExpired:
            logger.debug(f"ThumbnailService: timeout for {source_path}@{frame_time:.1f}s")
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        except Exception as exc:
            logger.debug(f"ThumbnailService: {exc}")
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None
