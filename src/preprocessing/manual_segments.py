"""
Manual markup data model for Step 2.

ManualSegment: user-defined time interval within a source video with tags/roles.
ManualSegmentsStore: persist/restore segments to .videoeditor/manual_segments.json
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Tag / role catalogue ──────────────────────────────────────────────────────

TAGS: List[tuple] = [
    ("intro",        "Начало"),
    ("middle",       "Середина"),
    ("ending",       "Финал"),
    ("transition",   "Переход"),
    ("dynamic",      "Динамичная сцена"),
    ("calm",         "Спокойная сцена"),
    ("camera_move",  "Красивый проход камеры"),
    ("detail",       "Деталь"),
    ("wide_shot",    "Общий план"),
    ("required",     "Обязательно использовать"),
    ("optional",     "Можно использовать"),
    ("backup",       "Запасной фрагмент"),
    ("forbidden",    "Не использовать"),
    ("bad",          "Плохой фрагмент"),
]

TAG_IDS         = [t[0] for t in TAGS]
TAG_NAMES       = {t[0]: t[1] for t in TAGS}
TAG_NAME_TO_ID  = {t[1]: t[0] for t in TAGS}

INCLUDE_POLICIES: List[tuple] = [
    ("required",    "Обязательно"),
    ("recommended", "Рекомендовано"),
    ("optional",    "Можно"),
    ("backup",      "Запасной"),
    ("forbidden",   "Запрещено"),
]

PRIORITIES: List[tuple] = [
    ("high",      "Высокий"),
    ("normal",    "Обычный"),
    ("low",       "Низкий"),
    ("backup",    "Запасной"),
    ("forbidden", "Запрещён"),
]


@dataclass
class ManualSegment:
    manual_segment_id: str
    source_file: str
    start_time: float
    end_time: float
    duration: float
    user_tags: List[str] = field(default_factory=list)
    priority: str = "normal"
    include_policy: str = "optional"
    user_note: str = ""
    status: str = "active"

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def create(
        cls,
        source_file: str,
        start_time: float,
        end_time: float,
        user_tags: Optional[List[str]] = None,
        priority: str = "normal",
        include_policy: str = "optional",
        user_note: str = "",
    ) -> "ManualSegment":
        start_time = round(float(start_time), 2)
        end_time   = round(float(end_time),   2)
        return cls(
            manual_segment_id=str(uuid.uuid4()),
            source_file=str(source_file),
            start_time=start_time,
            end_time=end_time,
            duration=round(end_time - start_time, 2),
            user_tags=list(user_tags or []),
            priority=priority,
            include_policy=include_policy,
            user_note=user_note,
            status="active",
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ManualSegment":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class ManualSegmentsStore:
    """Persist ManualSegments to PROJECT_DIR/.videoeditor/manual_segments.json."""

    _FILENAME = "manual_segments.json"
    _VERSION  = 2

    def __init__(self, project_dir: str):
        self._project_dir = Path(project_dir)
        self._path = self._project_dir / ".videoeditor" / self._FILENAME
        self._segments: List[ManualSegment] = []
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._segments = [
                    ManualSegment.from_dict(s)
                    for s in data.get("segments", [])
                ]
        except Exception:
            self._segments = []

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": self._VERSION,
            "segments": [s.to_dict() for s in self._segments],
        }
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def add(self, segment: ManualSegment) -> ManualSegment:
        self._segments.append(segment)
        self.save()
        return segment

    def update(self, segment: ManualSegment):
        for i, s in enumerate(self._segments):
            if s.manual_segment_id == segment.manual_segment_id:
                self._segments[i] = segment
                break
        self.save()

    def delete(self, segment_id: str):
        self._segments = [
            s for s in self._segments if s.manual_segment_id != segment_id
        ]
        self.save()

    def clear_for_source(self, source_file: str):
        self._segments = [
            s for s in self._segments if s.source_file != str(source_file)
        ]
        self.save()

    def clear_all(self):
        self._segments = []
        self.save()

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_all(self) -> List[ManualSegment]:
        return [s for s in self._segments if s.status == "active"]

    def get_for_source(self, source_file: str) -> List[ManualSegment]:
        sf = str(source_file)
        return [
            s for s in self._segments
            if s.source_file == sf and s.status == "active"
        ]

    def has_any(self) -> bool:
        return bool(self.get_all())

    # ── Step 3 helpers ────────────────────────────────────────────────────────

    def get_forbidden_ranges(self) -> List[tuple]:
        """(source_file, start_time, end_time) for forbidden/bad segments."""
        return [
            (s.source_file, s.start_time, s.end_time)
            for s in self.get_all()
            if s.include_policy == "forbidden"
            or "forbidden" in s.user_tags
            or "bad" in s.user_tags
        ]

    def get_required_ranges(self) -> List[tuple]:
        """(source_file, start_time, end_time) for required/recommended segments."""
        return [
            (s.source_file, s.start_time, s.end_time)
            for s in self.get_all()
            if s.include_policy in ("required", "recommended")
            or "required" in s.user_tags
        ]
