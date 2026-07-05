"""Preset Manager (ТЗ §5): 12 готовых сценарных пресетов.

Каждый пресет описывает идею, структуру слотов (доли от итоговой длительности),
предпочтительные типы сцен на слот, динамику и правила интро/финала.
Структура слотов согласована с ТЗ §12.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SlotSpec:
    """Один слот драматургии внутри пресета."""
    slot: str                  # intro | development | main | climax | ending
    share: float               # доля итоговой длительности (суммарно = 1.0)
    scene_types: list[str]     # предпочтительные типы сцен (по убыванию)
    min_fragment: float = 1.5  # мин. длительность фрагмента, сек
    max_fragment: float = 6.0  # макс. длительность фрагмента, сек
    prefer_motion: list[str] = field(default_factory=list)  # static|slow|fast


@dataclass
class Preset:
    id: str
    title: str
    idea: str                          # описание идеи ролика
    dynamics: str                      # low | medium | high
    slots: list[SlotSpec]
    intro_rule: str = "спокойный или общий кадр, задающий место действия"
    ending_rule: str = "завершённый кадр: общий вид или спокойный фрагмент, без обрыва"
    sync_to_music: bool = True

    def scenario_text(self) -> str:
        """Текст сценария для LLM-ранжировщика."""
        lines = [f"Идея ролика: {self.idea}", f"Динамика: {self.dynamics}.",
                 "Структура:"]
        for s in self.slots:
            lines.append(f"- {s.slot} (~{int(s.share * 100)}%): типы сцен {', '.join(s.scene_types)}")
        lines.append(f"Вступление: {self.intro_rule}")
        lines.append(f"Финал: {self.ending_rule}")
        return "\n".join(lines)


def _slots(*specs) -> list[SlotSpec]:
    return [SlotSpec(*s) for s in specs]


PRESETS: dict[str, Preset] = {p.id: p for p in [
    Preset(
        id="fpv_location", title="FPV обзор локации", dynamics="high",
        idea="Динамичный FPV-облёт локации: непрерывное движение, пролёты сквозь пространства, эффект присутствия.",
        slots=_slots(
            ("intro", 0.15, ["establishing", "location"], 1.5, 4.0, ["slow"]),
            ("development", 0.30, ["action", "location", "detail"], 1.5, 4.0, ["fast", "slow"]),
            ("main", 0.25, ["action", "location"], 1.5, 4.0, ["fast"]),
            ("climax", 0.20, ["climax", "action"], 2.0, 5.0, ["fast"]),
            ("ending", 0.10, ["ending", "establishing"], 2.0, 5.0, ["slow", "static"]),
        ),
    ),
    Preset(
        id="restaurant", title="Реклама ресторана/кафе", dynamics="medium",
        idea="Аппетитная реклама заведения: атмосфера, интерьер, блюда крупным планом, довольные гости.",
        slots=_slots(
            ("intro", 0.15, ["establishing", "location"], 2.0, 5.0, ["slow", "static"]),
            ("development", 0.30, ["detail", "food", "location"], 1.5, 4.0, ["slow"]),
            ("main", 0.30, ["food", "people", "detail"], 1.5, 4.0, ["slow", "static"]),
            ("climax", 0.15, ["food", "climax", "people"], 2.0, 4.0, ["slow"]),
            ("ending", 0.10, ["ending", "establishing"], 2.0, 5.0, ["static", "slow"]),
        ),
    ),
    Preset(
        id="coworking", title="Реклама коворкинга", dynamics="medium",
        idea="Современное рабочее пространство: свет, зоны, атмосфера продуктивности, люди за работой.",
        slots=_slots(
            ("intro", 0.15, ["establishing", "location"], 2.0, 5.0, ["slow"]),
            ("development", 0.35, ["location", "detail", "people"], 1.5, 4.0, ["slow"]),
            ("main", 0.25, ["people", "detail"], 1.5, 4.0, ["slow", "static"]),
            ("climax", 0.15, ["climax", "location"], 2.0, 4.0, ["slow"]),
            ("ending", 0.10, ["ending", "establishing"], 2.0, 5.0, ["static"]),
        ),
    ),
    Preset(
        id="travel", title="Туристический ролик", dynamics="medium",
        idea="Путешествие: пейзажи, достопримечательности, атмосфера места, ощущение открытия.",
        slots=_slots(
            ("intro", 0.15, ["establishing", "location"], 2.0, 5.0, ["slow"]),
            ("development", 0.30, ["location", "detail", "people"], 1.5, 4.5, ["slow"]),
            ("main", 0.25, ["location", "action", "people"], 1.5, 4.5, ["slow", "fast"]),
            ("climax", 0.20, ["climax", "location"], 2.0, 5.0, ["slow", "fast"]),
            ("ending", 0.10, ["ending", "establishing"], 2.0, 5.0, ["slow", "static"]),
        ),
    ),
    Preset(
        id="family", title="Семейное видео", dynamics="low",
        idea="Тёплое семейное видео: эмоции, лица, совместные моменты, естественность.",
        slots=_slots(
            ("intro", 0.15, ["establishing", "people"], 2.0, 5.0, ["static", "slow"]),
            ("development", 0.35, ["people", "detail"], 2.0, 5.0, ["static", "slow"]),
            ("main", 0.25, ["people", "action"], 2.0, 5.0, ["slow"]),
            ("climax", 0.15, ["people", "climax"], 2.0, 5.0, ["slow"]),
            ("ending", 0.10, ["ending", "people"], 2.5, 6.0, ["static", "slow"]),
        ),
    ),
    Preset(
        id="birthday", title="День рождения", dynamics="medium",
        idea="Праздник: торт, свечи, поздравления, эмоции именинника и гостей, веселье.",
        slots=_slots(
            ("intro", 0.15, ["establishing", "detail"], 2.0, 4.0, ["slow", "static"]),
            ("development", 0.30, ["people", "detail", "action"], 1.5, 4.0, ["slow"]),
            ("main", 0.25, ["people", "action"], 1.5, 4.0, ["slow", "fast"]),
            ("climax", 0.20, ["climax", "people"], 2.0, 5.0, ["slow"]),
            ("ending", 0.10, ["ending", "people"], 2.0, 5.0, ["static", "slow"]),
        ),
    ),
    Preset(
        id="drone_cinematic", title="Дроновое cinematic video", dynamics="medium",
        idea="Кинематографичные дроновые кадры: масштаб, плавные пролёты, величие пейзажа.",
        slots=_slots(
            ("intro", 0.15, ["establishing"], 2.5, 6.0, ["slow"]),
            ("development", 0.30, ["location", "establishing"], 2.0, 6.0, ["slow"]),
            ("main", 0.25, ["location", "action"], 2.0, 6.0, ["slow"]),
            ("climax", 0.20, ["climax", "establishing"], 2.5, 6.0, ["slow", "fast"]),
            ("ending", 0.10, ["ending", "establishing"], 3.0, 6.0, ["slow", "static"]),
        ),
    ),
    Preset(
        id="reels_fast", title="Быстрый Reels для Instagram", dynamics="high",
        idea="Цепляющий вертикальный ролик: быстрые склейки, самое яркое в первые 2 секунды, высокий темп.",
        slots=_slots(
            ("intro", 0.10, ["climax", "action", "detail"], 1.0, 2.5, ["fast", "slow"]),
            ("development", 0.30, ["action", "detail"], 1.0, 2.5, ["fast"]),
            ("main", 0.30, ["action", "people", "detail"], 1.0, 2.5, ["fast"]),
            ("climax", 0.20, ["climax", "action"], 1.5, 3.0, ["fast"]),
            ("ending", 0.10, ["ending", "establishing"], 1.5, 3.0, ["slow"]),
        ),
        intro_rule="сразу самый цепляющий кадр — хук в первые 2 секунды",
    ),
    Preset(
        id="tiktok_clip", title="Вертикальный TikTok клип", dynamics="high",
        idea="Ритмичный вертикальный клип под музыку: склейки строго по битам, энергия, движение.",
        slots=_slots(
            ("intro", 0.10, ["action", "climax"], 1.0, 2.0, ["fast"]),
            ("development", 0.30, ["action", "detail", "people"], 1.0, 2.5, ["fast"]),
            ("main", 0.30, ["action", "people"], 1.0, 2.5, ["fast"]),
            ("climax", 0.20, ["climax", "action"], 1.5, 3.0, ["fast"]),
            ("ending", 0.10, ["ending"], 1.5, 3.0, ["slow", "static"]),
        ),
        intro_rule="мгновенный хук: движение или самый яркий кадр",
    ),
    Preset(
        id="real_estate", title="Презентация недвижимости", dynamics="low",
        idea="Презентация объекта: фасад, входная группа, ключевые помещения, детали отделки, вид из окон.",
        slots=_slots(
            ("intro", 0.15, ["establishing"], 2.5, 6.0, ["slow", "static"]),
            ("development", 0.35, ["location", "detail"], 2.0, 5.0, ["slow"]),
            ("main", 0.25, ["location", "detail"], 2.0, 5.0, ["slow", "static"]),
            ("climax", 0.15, ["climax", "location"], 2.5, 5.0, ["slow"]),
            ("ending", 0.10, ["ending", "establishing"], 2.5, 6.0, ["static", "slow"]),
        ),
    ),
    Preset(
        id="slow_cinematic", title="Атмосферный slow cinematic", dynamics="low",
        idea="Медитативный атмосферный ролик: длинные планы, настроение, свет, фактуры, неторопливость.",
        slots=_slots(
            ("intro", 0.15, ["establishing"], 3.0, 7.0, ["static", "slow"]),
            ("development", 0.35, ["detail", "location"], 2.5, 6.0, ["static", "slow"]),
            ("main", 0.25, ["detail", "location"], 2.5, 6.0, ["slow"]),
            ("climax", 0.15, ["climax", "establishing"], 3.0, 6.0, ["slow"]),
            ("ending", 0.10, ["ending"], 3.0, 7.0, ["static"]),
        ),
        sync_to_music=False,
    ),
    Preset(
        id="action_montage", title="Динамичный action монтаж", dynamics="high",
        idea="Энергичный экшн: скорость, движение, адреналин, резкая смена планов, монтаж в ритм.",
        slots=_slots(
            ("intro", 0.10, ["action", "establishing"], 1.0, 2.5, ["fast", "slow"]),
            ("development", 0.30, ["action"], 1.0, 2.5, ["fast"]),
            ("main", 0.30, ["action", "detail"], 1.0, 2.5, ["fast"]),
            ("climax", 0.20, ["climax", "action"], 1.5, 3.5, ["fast"]),
            ("ending", 0.10, ["ending", "establishing"], 2.0, 4.0, ["slow"]),
        ),
    ),
    Preset(
        id="generic", title="Универсальный ролик", dynamics="medium",
        idea="Сбалансированный ролик: понятное начало, содержательная середина, яркая кульминация, завершённый финал.",
        slots=_slots(
            ("intro", 0.15, ["establishing", "intro", "location"], 1.5, 5.0, ["slow", "static"]),
            ("development", 0.30, ["location", "detail", "people"], 1.5, 4.5, []),
            ("main", 0.25, ["action", "people", "detail"], 1.5, 4.5, []),
            ("climax", 0.20, ["climax", "action"], 2.0, 5.0, []),
            ("ending", 0.10, ["ending", "establishing"], 2.0, 5.0, ["slow", "static"]),
        ),
    ),
]}


def get_preset(preset_id: str) -> Preset:
    return PRESETS.get(preset_id, PRESETS["generic"])
