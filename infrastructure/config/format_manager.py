"""
FormatManager — output format configs, separate from style (TZ section 8).

Format = aspect ratio + resolution + crop strategy.
Style = montage aesthetic.
Duration = clip density selection.
These three are ALWAYS independent parameters.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml

_FORMATS_PATH = Path(__file__).parent / "output_formats.yaml"


class FormatManager:
    _cache: Optional[dict] = None

    def _load(self) -> dict:
        if self._cache is None:
            with open(_FORMATS_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self._cache = data.get("formats", {})
        return self._cache

    def list_formats(self) -> List[dict]:
        return list(self._load().values())

    def get_format(self, format_id: str) -> Optional[dict]:
        return self._load().get(format_id)

    def get_crop_strategy(self, format_id: str) -> str:
        fmt = self.get_format(format_id)
        return fmt.get("crop_strategy", "center") if fmt else "center"

    def is_vertical(self, format_id: str) -> bool:
        fmt = self.get_format(format_id)
        if not fmt:
            return False
        return fmt.get("aspect_ratio") in ("9:16",)

    def get_resolution(self, format_id: str) -> tuple:
        fmt = self.get_format(format_id)
        if not fmt:
            return (1920, 1080)
        return (fmt.get("width", 1920), fmt.get("height", 1080))

    def get_typical_duration(self, format_id: str) -> tuple:
        """Return (min_s, max_s) typical duration for this format."""
        fmt = self.get_format(format_id)
        if not fmt:
            return (15, 60)
        d = fmt.get("typical_duration", [15, 60])
        return (d[0], d[1])

    def validate_duration(self, format_id: str, duration_s: float) -> Optional[str]:
        """Return warning string if duration is outside typical range, else None."""
        min_d, max_d = self.get_typical_duration(format_id)
        fmt = self.get_format(format_id)
        name = fmt.get("name", format_id) if fmt else format_id
        if duration_s < min_d:
            return f"{name}: типичная длительность от {min_d}с, выбрано {duration_s:.0f}с"
        if max_d < 9999 and duration_s > max_d:
            return f"{name}: типичная длительность до {max_d}с, выбрано {duration_s:.0f}с"
        return None


fmt_manager = FormatManager()
