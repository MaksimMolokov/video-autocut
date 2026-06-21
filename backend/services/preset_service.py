"""PresetService — load and apply presets (TASK-003)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml

_PRESETS_DIR = Path(__file__).resolve().parents[2] / "presets"


class PresetService:
    _cache: Dict[str, dict] = {}

    def list_presets(self) -> List[dict]:
        return [self._load(p) for p in sorted(_PRESETS_DIR.glob("*.yaml"))]

    def get_preset(self, preset_id: str) -> Optional[dict]:
        for path in _PRESETS_DIR.glob("*.yaml"):
            preset = self._load(path)
            if preset.get("preset_id") == preset_id:
                return preset
        return None

    def get_by_category(self, category: str) -> List[dict]:
        return [p for p in self.list_presets()
                if category.lower() in str(p.get("recommended_for", [])).lower()]

    def _load(self, path: Path) -> dict:
        key = str(path)
        if key not in self._cache:
            with open(path, "r", encoding="utf-8") as f:
                self._cache[key] = yaml.safe_load(f) or {}
        return self._cache[key]
