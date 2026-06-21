"""
ConfigManager — centralized configuration loader (TASK-004).

Loads defaults.yaml, allows project-level overrides.
All thresholds, weights and parameters must come through here — never hardcoded.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

_DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"


class ConfigManager:
    """Singleton-style config loader with dot-path access."""

    _instance: Optional["ConfigManager"] = None
    _config: dict

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load(_DEFAULTS_PATH, override_path=None)
        return cls._instance

    # ── Loading ──────────────────────────────────────────────────────────────

    def _load(self, defaults_path: Path, override_path: Optional[Path]) -> None:
        with open(defaults_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}

        if override_path and override_path.exists():
            with open(override_path, "r", encoding="utf-8") as f:
                overrides = yaml.safe_load(f) or {}
            self._config = _deep_merge(self._config, overrides)

    def load_project_overrides(self, project_dir: Path) -> None:
        """Load project-level config overrides (e.g. .videoeditor/config.yaml)."""
        override_path = project_dir / self.get("storage.project_dir_name") / "config.yaml"
        self._load(_DEFAULTS_PATH, override_path)

    # ── Access ───────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Dot-separated key access: cfg.get('quality.weights.sharpness')"""
        parts = key.split(".")
        node = self._config
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise KeyError(f"Config key not found: {key!r}")
        return value

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def quality(self) -> dict:
        return self._config.get("quality", {})

    @property
    def scene(self) -> dict:
        return self._config.get("scene", {})

    @property
    def timeline(self) -> dict:
        return self._config.get("timeline", {})

    @property
    def music_sync(self) -> dict:
        return self._config.get("music_sync", {})

    @property
    def render(self) -> dict:
        return self._config.get("render", {})

    @property
    def storage(self) -> dict:
        return self._config.get("storage", {})

    @property
    def platforms(self) -> dict:
        return self._config.get("platforms", {})

    @property
    def analysis(self) -> dict:
        return self._config.get("analysis", {})

    @property
    def schema_version(self) -> int:
        return int(self.get("database.schema_version", 2))


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# Module-level singleton accessor
cfg = ConfigManager()
