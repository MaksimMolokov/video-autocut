"""Три главные сущности (ТЗ §24): Проект, Сцена, Монтажный план.

Всё остальное — сервисы вокруг них. Модели сериализуются в SQLite (storage.py)
и в JSON для обмена с LLM и UI.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# --- Типы сцен (ТЗ §9) ---
SCENE_TYPES = [
    "intro", "establishing", "detail", "action", "people", "location",
    "food", "product", "transition", "climax", "ending",
]

# --- Слоты драматургии (ТЗ §12) ---
STORY_SLOTS = ["intro", "development", "main", "climax", "ending"]


@dataclass
class Project:
    """Проект монтажа (ТЗ §3–4, §19)."""
    name: str
    id: str = field(default_factory=_new_id)
    created_at: float = field(default_factory=time.time)
    source_paths: list[str] = field(default_factory=list)   # видеофайлы
    music_path: str = ""
    preset_id: str = "generic"                              # или свой сценарий:
    scenario_text: str = ""
    aspect: str = "9:16"                                    # 9:16 | 16:9 | 1:1
    target_duration: int = 30                               # секунды
    style: str = "dynamic"                                  # стиль монтажа
    dynamics: str = "medium"                                # low | medium | high
    with_intro: bool = True
    with_ending: bool = True
    sync_to_music: bool = True
    # Опция: стабилизировать дёрганые сцены вместо исключения (default ВЫКЛ —
    # дёрганое просто не попадает в монтаж, материала обычно достаточно)
    stabilize_shaky: bool = False
    # Опция: анализ речи Whisper — не резать склейками посреди фразы
    analyze_speech: bool = True
    # FPV Showroom: пути файлов, помеченных как цельный однодублевый облёт
    fpv_files: list[str] = field(default_factory=list)
    fpv_style: str = "smooth"   # smooth | dynamic | premium
    # Длительная статичная пауза (картинка не меняется, людей нет) сжимается
    # так, чтобы в ролике занимать не больше этого времени, сек
    fpv_pause_out: float = 0.5
    status: str = "new"        # new | analyzing | analyzed | planned | rendered
    analysis_progress: str = ""  # живой статус фонового воркера для UI

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class SourceVideo:
    """Исходный видеофайл с техметаданными (ТЗ §7.1)."""
    project_id: str
    path: str
    id: str = field(default_factory=_new_id)
    duration: float = 0.0
    fps: float = 0.0
    width: int = 0
    height: int = 0
    orientation: str = ""      # horizontal | vertical | square
    bitrate: int = 0
    has_audio: bool = False
    codec: str = ""
    valid: bool = True         # файл читается и стабилен
    error: str = ""
    file_hash: str = ""        # быстрый отпечаток файла — кэш анализа
    speech_segments: list = field(default_factory=list)  # [[start, end, text], …]
    fpv_showroom: bool = False # цельный FPV-облёт локации одним дублем


@dataclass
class Scene:
    """Карточка найденной сцены — центральная сущность каталога (ТЗ §9)."""
    video_id: str
    video_path: str
    start: float               # сек в исходнике
    end: float
    id: str = field(default_factory=_new_id)
    project_id: str = ""

    # Превью (ТЗ §7.6)
    thumbnail_path: str = ""
    preview_path: str = ""

    # Метрики качества из OpenCV (ТЗ §7.3–7.4), диапазон 0..1
    quality_score: float = 0.0      # интегральная техническая оценка
    stability_score: float = 0.0    # отсутствие тряски
    sharpness: float = 0.0          # сырая дисперсия Лапласиана
    brightness: float = 0.0         # средняя яркость 0..255
    motion: str = ""                # static | slow | fast
    motion_type: str = ""           # pan | zoom_in | zoom_out | flyover | rotate | shake | none
    jerkiness: float = 0.0          # 0..1 дёрганость камеры (1 = сильные рывки)
    best_moment: float = 0.0        # таймкод самого резкого кадра — центр фрагмента
    speech_segments: list = field(default_factory=list)  # фразы внутри сцены [[s, e, text], …]

    # Смысловой анализ от LLM (ТЗ §7.5, §8; SPEC §5.1)
    description: str = ""
    tags: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    people_count: int = 0
    emotions: list[str] = field(default_factory=list)
    composition: str = ""
    lighting: str = ""
    aesthetic_score: float = 0.0    # 0..1, «красота» от LLM
    subject_x: float = 0.5          # позиция главного объекта (0..1) — умный кроп
    subject_y: float = 0.5
    scene_type: str = ""            # из SCENE_TYPES
    recommended_slot: str = ""      # из STORY_SLOTS
    recommendation_reason: str = ""
    scenario_match_score: float = 0.0   # заполняет Scene Matcher (Фаза 6)
    scenario_match_key: str = ""    # хэш сценария, для которого посчитан score —
                                    # ранжирование не пересчитывается зря
    llm_status: str = "pending"     # pending | done | failed | skipped

    # Пользовательские пометки (ТЗ §15)
    user_flag: str = ""             # good | bad | banned | pinned

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)

    def llm_card(self) -> dict[str, Any]:
        """Компактная карточка для передачи LLM-ранжировщику (ТЗ §8.4)."""
        return {
            "id": self.id,
            "duration": self.duration,
            "description": self.description,
            "tags": self.tags,
            "scene_type": self.scene_type,
            "quality": round(self.quality_score, 2),
            "aesthetic": round(self.aesthetic_score, 2),
            "motion": self.motion,
            "motion_type": self.motion_type,
            "people_count": self.people_count,
        }


@dataclass
class PlanSegment:
    """Один фрагмент монтажного плана (ТЗ §11)."""
    scene_id: str
    order: int                 # позиция в ролике
    src_start: float           # таймкоды в исходнике
    src_end: float
    slot: str                  # место в структуре (STORY_SLOTS) или имя зоны FPV
    reason: str = ""           # причина выбора — обязательна для прозрачности
    id: str = field(default_factory=_new_id)
    crop: str = "center"       # рекомендация кадрирования
    beat_synced: bool = False  # склейка выровнена по биту
    speed: float = 1.0         # скорость воспроизведения (FPV: перемотка промежутков)

    @property
    def duration(self) -> float:
        """Длительность в ИСХОДНИКЕ, сек."""
        return round(self.src_end - self.src_start, 3)

    @property
    def out_duration(self) -> float:
        """Длительность в РОЛИКЕ с учётом скорости, сек."""
        return round((self.src_end - self.src_start) / max(self.speed, 0.01), 3)


@dataclass
class Zone:
    """Ключевая зона маршрута внутри FPV showroom-файла."""
    project_id: str
    video_id: str
    start: float               # таймкоды в исходнике
    end: float
    title: str = ""            # «вход», «барная зона», …
    id: str = field(default_factory=_new_id)
    required: bool = True      # обязательно показать в ролике
    technical: bool = False    # взлёт/посадка/настройка — исключается
    score: float = 0.0         # визуальная ценность 0..1
    thumbnail_path: str = ""

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


@dataclass
class MontagePlan:
    """Монтажный план — отдельная сущность (ТЗ §24)."""
    project_id: str
    id: str = field(default_factory=_new_id)
    created_at: float = field(default_factory=time.time)
    segments: list[PlanSegment] = field(default_factory=list)
    # Альтернативы на каждый слот: slot -> [scene_id, ...] (ТЗ §14)
    alternatives: dict[str, list[str]] = field(default_factory=dict)
    # Подобранный фрагмент музыки (ТЗ §16): с какой секунды трека и фейды
    music_offset: float = 0.0
    music_fade_in: float = 1.0
    music_fade_out: float = 1.5
    # Переход между сценами (из пресета)
    transition: str = "cut"            # cut | crossfade
    transition_duration: float = 0.0
    mode: str = "standard"             # standard | fpv — showroom-план
    warnings: list[str] = field(default_factory=list)  # тайминг не влез и т.п.
    status: str = "draft"      # draft | rendered | final
    preview_path: str = ""
    export_path: str = ""

    @property
    def total_duration(self) -> float:
        """Длительность РОЛИКА (с учётом скоростей сегментов)."""
        return round(sum(s.out_duration for s in self.segments), 3)
