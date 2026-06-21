"""ProjectService — project lifecycle management (TASK-003)."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from infrastructure.config.config_manager import cfg
from infrastructure.database.models import Project, SourceVideo as SourceFile, create_db_engine, init_db
from infrastructure.database.repository import SchemaVersionRepo, SourceFileRepo
from infrastructure.storage.manifest import ManifestManager, VideoEntry, MusicEntry
from infrastructure.storage.path_manager import PathManager


class ProjectService:
    """Create, open and manage video editor projects."""

    def __init__(self, project_root: str) -> None:
        self.pm = PathManager(project_root)
        self.pm.ensure_dirs()
        self._engine = create_db_engine(str(self.pm.db_path))
        init_db(self._engine)
        self._manifest = ManifestManager(self.pm)
        self._ensure_schema_version()

    # ── Public API ─────────────────────────────────────────────────────────────

    def open_or_create(self, project_name: str) -> dict:
        manifest = self._manifest.load()
        manifest.project_name = manifest.project_name or project_name
        self._manifest.save(manifest)
        return {"project_name": manifest.project_name, "root": str(self.pm.root)}

    def add_video_files(self, abs_paths: List[str]) -> List[str]:
        """Register video files; return their relative paths."""
        manifest = self._manifest.load()
        existing = {v.rel_path for v in manifest.videos}
        added = []
        with Session(self._engine) as session:
            repo = SourceFileRepo(session)
            for path in abs_paths:
                rel = self.pm.rel(path)
                if rel not in existing:
                    manifest.videos.append(VideoEntry(rel_path=rel))
                    existing.add(rel)
                repo.get_or_create(rel)
            added.append(rel)
        self._manifest.save(manifest)
        return [v.rel_path for v in manifest.videos]

    def set_music(self, abs_path: str) -> None:
        manifest = self._manifest.load()
        rel = self.pm.rel(abs_path)
        manifest.music = MusicEntry(rel_path=rel)
        self._manifest.save(manifest)

    def get_manifest(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self._manifest.load())

    def update_settings(self, **kwargs) -> None:
        self._manifest.update(**kwargs)

    def file_hash(self, abs_path: str) -> str:
        h = hashlib.md5()
        with open(abs_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def abs_path(self, rel_path: str) -> str:
        return str(self.pm.abs(rel_path))

    # ── Internal ───────────────────────────────────────────────────────────────

    def _ensure_schema_version(self) -> None:
        with Session(self._engine) as session:
            repo = SchemaVersionRepo(session)
            current = repo.get_current()
            target = cfg.schema_version
            if current < target:
                repo.set_version(target, f"init v{target}")
