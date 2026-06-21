"""
PathManager — relative path resolution (TASK-005).

All file references inside a project are stored as paths relative to the
project root. This makes projects fully portable across machines.

Usage:
    pm = PathManager(project_root)
    abs_path = pm.abs(relative_path)
    rel_path = pm.rel(absolute_path)
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from infrastructure.config.config_manager import cfg

_PathLike = Union[str, Path]


class PathManager:
    """Resolve and convert paths relative to a project root."""

    def __init__(self, project_root: _PathLike) -> None:
        self.root = Path(project_root).resolve()
        _storage = cfg.storage
        self._project_dir = self.root / _storage.get("project_dir_name", ".videoeditor")

    # ── Directories ───────────────────────────────────────────────────────────

    @property
    def project_dir(self) -> Path:
        return self._project_dir

    @property
    def previews_dir(self) -> Path:
        return self._project_dir / cfg.get("storage.previews_dir", "previews")

    @property
    def audio_clips_dir(self) -> Path:
        return self._project_dir / cfg.get("storage.audio_clips_dir", "audio_clips")

    @property
    def temp_dir(self) -> Path:
        return self._project_dir / cfg.get("storage.temp_dir", "temp")

    @property
    def db_path(self) -> Path:
        return self._project_dir / cfg.get("storage.analysis_db_name", "analysis.db")

    @property
    def manifest_path(self) -> Path:
        return self._project_dir / cfg.get("storage.manifest_name", "project.json")

    @property
    def manual_segments_path(self) -> Path:
        return self._project_dir / cfg.get("storage.manual_segments_file", "manual_segments.json")

    # ── Conversion ────────────────────────────────────────────────────────────

    def abs(self, path: _PathLike) -> Path:
        """Convert a stored relative path to an absolute path."""
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.root / p).resolve()

    def rel(self, path: _PathLike) -> str:
        """Convert an absolute path to a project-relative string for storage."""
        p = Path(path).resolve()
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            # Path outside project root — store as absolute (external file)
            return str(p)

    def ensure_dirs(self) -> None:
        """Create all project subdirectories if they don't exist."""
        for d in (self.project_dir, self.previews_dir, self.audio_clips_dir, self.temp_dir):
            d.mkdir(parents=True, exist_ok=True)

    def is_external(self, path: _PathLike) -> bool:
        """Return True if path is outside the project root."""
        try:
            Path(path).resolve().relative_to(self.root)
            return False
        except ValueError:
            return True
