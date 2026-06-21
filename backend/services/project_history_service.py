"""
ProjectHistoryService — list and manage project history (TZ MVP requirement #14).

Stores a registry of all known projects with their last state.
Registry is saved at ~/.videoeditor_projects.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional


_REGISTRY_PATH = Path.home() / ".videoeditor_projects.json"


class ProjectHistoryService:
    """Track and list all projects created on this machine."""

    def register(self, project_root: str, project_name: str) -> None:
        """Add or update a project in the registry."""
        registry = self._load()
        key = str(Path(project_root).resolve())
        registry[key] = {
            "root": key,
            "name": project_name,
            "last_opened": time.time(),
            "exists": Path(key).exists(),
        }
        self._save(registry)

    def list_projects(self) -> List[Dict]:
        """Return all registered projects, sorted by last_opened desc."""
        registry = self._load()
        projects = []
        for key, info in registry.items():
            info["exists"] = Path(key).exists()
            # Try to get extra info from manifest
            manifest_path = Path(key) / ".videoeditor" / "project.json"
            if manifest_path.exists():
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    info["video_count"] = len(manifest.get("videos", []))
                    info["last_render"] = manifest.get("last_render_path")
                    info["prep_mode"] = manifest.get("prep_mode")
                except Exception:
                    pass
            projects.append(info)

        return sorted(projects, key=lambda p: p.get("last_opened", 0), reverse=True)

    def remove(self, project_root: str) -> None:
        """Remove a project from the registry (does not delete files)."""
        registry = self._load()
        key = str(Path(project_root).resolve())
        registry.pop(key, None)
        self._save(registry)

    def get_recent(self, limit: int = 5) -> List[Dict]:
        return self.list_projects()[:limit]

    def _load(self) -> Dict:
        if _REGISTRY_PATH.exists():
            try:
                with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self, registry: Dict) -> None:
        with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
