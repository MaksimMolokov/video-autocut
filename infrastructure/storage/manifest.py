"""
Project Manifest — project.json (TASK-006).

Single source of truth for project state. Replaces scattered session_state
and enables full project restore after restart or on another machine.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from infrastructure.config.config_manager import cfg
from infrastructure.storage.path_manager import PathManager

_SCHEMA_VERSION = 1


@dataclass
class VideoEntry:
    rel_path: str                  # relative to project root
    duration_s: float = 0.0
    analyzed: bool = False
    fragment_count: int = 0


@dataclass
class MusicEntry:
    rel_path: str
    duration_s: float = 0.0
    analyzed: bool = False
    selected_start_s: Optional[float] = None
    selected_end_s: Optional[float] = None


@dataclass
class ProjectManifest:
    schema_version: int = _SCHEMA_VERSION
    project_name: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    videos: List[VideoEntry] = field(default_factory=list)
    music: Optional[MusicEntry] = None

    selected_preset_id: Optional[str] = None
    platform: Optional[str] = None
    target_duration_s: float = 30.0
    output_format: str = "16_9"

    watermark_enabled: bool = False
    watermark_text: str = ""
    watermark_position: str = "bottom_right"
    watermark_opacity: float = 0.7

    prep_mode: Optional[str] = None   # None | 'manual' | 'auto' | 'skipped'
    last_render_path: Optional[str] = None

    extra: Dict[str, Any] = field(default_factory=dict)


class ManifestManager:
    """Load / save / update ProjectManifest for a given project directory."""

    def __init__(self, path_manager: PathManager) -> None:
        self._pm = path_manager
        self._path = path_manager.manifest_path

    def load(self) -> ProjectManifest:
        if not self._path.exists():
            return ProjectManifest()
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _from_dict(data)

    def save(self, manifest: ProjectManifest) -> None:
        manifest.updated_at = time.time()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)

    def update(self, **kwargs: Any) -> ProjectManifest:
        manifest = self.load()
        for key, value in kwargs.items():
            if hasattr(manifest, key):
                setattr(manifest, key, value)
        self.save(manifest)
        return manifest


def _from_dict(data: dict) -> ProjectManifest:
    videos = [VideoEntry(**v) for v in data.pop("videos", [])]
    music_data = data.pop("music", None)
    music = MusicEntry(**music_data) if music_data else None
    return ProjectManifest(videos=videos, music=music, **{
        k: v for k, v in data.items() if k in ProjectManifest.__dataclass_fields__
    })
