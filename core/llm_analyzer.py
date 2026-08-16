"""LLM Analyzer (ТЗ §7.5, §8): смысловой анализ ключевого кадра сцены.

Стек по SPEC_LOCAL_VIDEO_ANALYSIS.md: Qwen3-VL 8B Instruct через LM Studio
(OpenAI-совместимый API, localhost:1234/v1), structured output по JSON-схеме.
Правила из спеки: 1 кадр = 1 запрос, кадр даунскейлится до 1024px,
temperature 0.2, при недоступном LM Studio — graceful degradation
(сцена остаётся llm_status=pending и дозаполняется позже).
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from openai import OpenAI, APIConnectionError

import config
from core.models import SCENE_TYPES, STORY_SLOTS, Scene

log = logging.getLogger(__name__)

# JSON-схема ответа (SPEC §5.1 + поля карточки сцены из ТЗ §9)
SCENE_SCHEMA = {
    "name": "scene_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "scene_description": {"type": "string",
                                  "description": "2-3 предложения: что происходит в кадре"},
            "objects": {"type": "array", "items": {"type": "string"},
                        "description": "главные объекты в кадре"},
            "people_count": {"type": "integer"},
            "emotions": {"type": "array", "items": {"type": "string"},
                         "description": "эмоции людей, если есть"},
            "composition": {"type": "string",
                            "description": "композиция: план (общий/средний/крупный), ракурс, баланс"},
            "lighting": {"type": "string", "description": "характер света"},
            "aesthetic_score": {"type": "number", "minimum": 0, "maximum": 1,
                                "description": "красота кадра, число от 0.0 до 1.0"},
            "scene_type": {"type": "string", "enum": SCENE_TYPES},
            "recommended_slot": {"type": "string", "enum": STORY_SLOTS,
                                 "description": "рекомендуемое место в ролике"},
            "tags": {"type": "array", "items": {"type": "string"},
                     "description": "5-10 коротких тегов на английском: people, food, nature, building, interior, exterior, vehicle, closeup, wide-shot и т.п."},
            "usable_for_edit": {"type": "boolean",
                                "description": "пригоден ли кадр для монтажа"},
            "subject_x": {"type": "number", "minimum": 0, "maximum": 1,
                          "description": "горизонтальная позиция главного объекта/людей: 0=левый край, 0.5=центр, 1=правый край"},
            "subject_y": {"type": "number", "minimum": 0, "maximum": 1,
                          "description": "вертикальная позиция главного объекта: 0=верх, 0.5=центр, 1=низ"},
        },
        "required": ["scene_description", "objects", "people_count", "emotions",
                     "composition", "lighting", "aesthetic_score", "scene_type",
                     "recommended_slot", "tags", "usable_for_edit",
                     "subject_x", "subject_y"],
        "additionalProperties": False,
    },
}

_SYSTEM_PROMPT = (
    "Ты — ассистент видеомонтажёра. Анализируешь кадр из видео для каталога сцен. "
    "Отвечай только валидным JSON по заданной схеме, без лишнего текста. "
    "Описание — кратко, 1-2 предложения по-русски. Теги — по-английски, не больше 8. "
    "aesthetic_score — число от 0.0 до 1.0. "
    "Оценивай честно: технически слабые или скучные кадры должны получать низкий aesthetic_score.\n"
    "Определения scene_type: establishing — общий план места/пейзажа; location — "
    "пространство локации; detail — крупный план детали; action — движение и действие; "
    "people — люди в центре внимания; food — еда; product — товар крупным планом "
    "(ТОЛЬКО если в кадре реально товар); transition — переходный кадр; "
    "climax — самый эффектный кадр; intro/ending — явные открывающий/финальный кадры. "
    "Если сомневаешься между product и другим типом — выбирай другой."
)


def _parse_json_lenient(content: str) -> dict | None:
    """Парсит JSON устойчиво к артефактам локальных моделей:
    хвостовые пробелы до лимита токенов, markdown-обёртка, обрыв генерации."""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.split("\n", 1)[1] if "\n" in content else content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Берём самый внешний {...}-блок
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            pass
    # Обрыв генерации: дозакрываем скобки
    if start != -1:
        frag = content[start:].rstrip().rstrip(",")
        frag = frag.rsplit(",", 1)[0] if frag.count('"') % 2 else frag  # битая строка в конце
        for suffix in ("}", "]}", '"]}', "}}"):
            try:
                return json.loads(frag + suffix)
            except json.JSONDecodeError:
                continue
    return None


class LLMAnalyzer:
    def __init__(self, base_url: str = config.LM_STUDIO_BASE_URL,
                 model: str = config.LLM_MODEL):
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=config.LM_STUDIO_API_KEY,
                             timeout=config.LLM_TIMEOUT, max_retries=1)

    def is_available(self) -> bool:
        """LM Studio запущен и модель загружена?"""
        try:
            models = [m.id for m in self.client.models.list().data]
        except APIConnectionError:
            return False
        except Exception as e:
            log.warning("LM Studio: ошибка списка моделей: %s", e)
            return False
        if not models:
            return False
        if self.model not in models:
            # Модель с другим id (напр. mlx-community/Qwen3-VL-8B...) — ищем по подстроке
            matches = [m for m in models if "vl" in m.lower() or "vision" in m.lower()
                       or "gemma-3" in m.lower()]
            if matches:
                log.info("Модель %s не найдена, использую %s", self.model, matches[0])
                self.model = matches[0]
            else:
                log.warning("В LM Studio нет vision-модели. Загружены: %s", models)
                return False
        return True

    def analyze_frame(self, frame_path: Path | list[Path]) -> dict | None:
        """Кадр (или 2–3 кадра длинной сцены) → структурированное описание.

        Несколько кадров уходят одним запросом — модель видит развитие сцены
        (начало/конец) и описывает её целиком.
        """
        paths = [frame_path] if isinstance(frame_path, Path) else list(frame_path)
        if len(paths) == 1:
            text = "Проанализируй этот кадр из видео для каталога сцен."
        else:
            text = (f"Это {len(paths)} кадра ОДНОЙ сцены (от начала к концу). "
                    "Опиши сцену целиком, учитывая её развитие.")
        content: list[dict] = [{"type": "text", "text": text}]
        for p in paths:
            img_b64 = base64.b64encode(p.read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=config.LLM_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS,
                response_format={"type": "json_schema", "json_schema": SCENE_SCHEMA},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
            )
            data = _parse_json_lenient(resp.choices[0].message.content or "")
            if data is None:
                log.warning("LLM-анализ кадра %s: невалидный JSON (finish=%s)",
                            paths[0].name, resp.choices[0].finish_reason)
            return data
        except Exception as e:
            log.warning("LLM-анализ кадра %s не удался: %s", paths[0].name, e)
            return None

    def fill_scene(self, scene: Scene, frame_path: Path | list[Path]) -> bool:
        """Заполняет смысловые поля карточки сцены. True при успехе."""
        data = self.analyze_frame(frame_path)
        if not data:
            scene.llm_status = "failed"
            return False
        scene.description = data.get("scene_description", "")
        scene.objects = data.get("objects", [])
        scene.people_count = int(data.get("people_count", 0) or 0)
        scene.emotions = data.get("emotions", [])
        scene.composition = data.get("composition", "")
        scene.lighting = data.get("lighting", "")
        # модели иногда дают оценку по 10-балльной шкале вопреки схеме
        raw_score = float(data.get("aesthetic_score", 0) or 0)
        if raw_score > 1:
            raw_score /= 10.0
        scene.aesthetic_score = float(min(max(raw_score, 0), 1))
        scene.scene_type = data.get("scene_type", "")
        scene.recommended_slot = data.get("recommended_slot", "")
        scene.tags = data.get("tags", [])
        scene.subject_x = float(min(max(data.get("subject_x", 0.5) or 0.5, 0), 1))
        scene.subject_y = float(min(max(data.get("subject_y", 0.5) or 0.5, 0), 1))
        if not data.get("usable_for_edit", True):
            scene.tags.append("not-usable")
        scene.scenario_match_key = ""  # описание изменилось — ранжирование заново
        scene.llm_status = "done"
        return True
