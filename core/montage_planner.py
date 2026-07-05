"""Scene Matcher + Montage Planner (ТЗ §11–12, §24).

Двухступенчатый подбор:
1. Rule-based скоринг: тип сцены × слот пресета, качество, эстетика,
   движение, пользовательские пометки (banned/pinned/good/bad).
2. Опционально LLM-ранжирование (ТЗ §8): Qwen3-VL 8B получает сценарий и
   компактные карточки сцен-кандидатов, уточняет соответствие сценарию.

План собирается по слотам драматургии, склейки выравниваются по битам музыки,
у каждого сегмента — причина выбора. Альтернативы на слот сохраняются (ТЗ §14).
"""
from __future__ import annotations

import json
import logging
import random

import config
from core.audio_analyzer import MusicAnalysis
from core.llm_analyzer import LLMAnalyzer
from core.models import MontagePlan, PlanSegment, Project, Scene
from core.presets import Preset, SlotSpec, get_preset

log = logging.getLogger(__name__)

_ALTERNATIVES_PER_SLOT = 4  # сколько запасных сцен хранить на слот


def build_plan(project: Project, scenes: list[Scene],
               music: MusicAnalysis | None = None,
               use_llm: bool = True, variant: int = 0) -> MontagePlan:
    """variant=0 — детерминированный лучший план; variant>0 — «другой вариант»:
    топ-кандидаты слотов перемешиваются воспроизводимо (тот же variant —
    тот же план), закреплённые сцены всегда остаются первыми."""
    preset = get_preset(project.preset_id)
    scenario = project.scenario_text or preset.scenario_text()

    usable = [s for s in scenes if s.user_flag != "banned" and "not-usable" not in s.tags]
    if not usable:
        raise ValueError("Нет пригодных сцен для монтажа")

    # Дёрганые сцены (тряска, смаз) исключаются из монтажа — кроме закреплённых.
    # Fallback: если стабильных сцен слишком мало, берём наименее дёрганые.
    stable = [s for s in usable
              if s.user_flag == "pinned"
              or (s.motion_type != "shake"
                  and s.stability_score >= config.STABILITY_MIN)]
    if len(stable) >= 3:
        usable = stable
    else:
        usable = sorted(usable, key=lambda s: s.jerkiness)[:max(len(usable) // 2, 3)]
        log.warning("Стабильных сцен мало (%d) — взяты наименее дёрганые", len(usable))

    # LLM-уточнение соответствия сценарию (если доступно)
    if use_llm:
        _llm_rank(scenario, usable)

    plan = MontagePlan(project_id=project.id)
    used_scene_ids: set[str] = set()
    used_video_run: str = ""   # анти-повтор: не два фрагмента подряд из одного видео

    order = 0
    for slot_spec in preset.slots:
        slot_duration = project.target_duration * slot_spec.share
        candidates = _rank_for_slot(usable, slot_spec, used_scene_ids)
        if not candidates:
            candidates = _rank_for_slot(usable, slot_spec, set())  # разрешаем повтор в крайнем случае

        if variant and len(candidates) > 1:
            # «Другой вариант»: перемешиваем топ слота воспроизводимо,
            # pinned не выпадают из головы списка
            rnd = random.Random(f"{variant}:{slot_spec.slot}")
            top, rest = candidates[:6], candidates[6:]
            rnd.shuffle(top)
            top.sort(key=lambda c: c[0].user_flag != "pinned")
            candidates = top + rest

        remaining = slot_duration
        slot_alternatives: list[str] = []
        for scene, score, reason in candidates:
            if remaining < slot_spec.min_fragment:
                # слот заполнен — остальные кандидаты становятся альтернативами
                if scene.id not in used_scene_ids:
                    slot_alternatives.append(scene.id)
                continue
            if scene.id in used_scene_ids:
                continue
            # Не подряд из одного исходника (ТЗ §23.6) — но только если
            # реально есть свободный кандидат из другого видео
            if scene.video_id == used_video_run and any(
                c.video_id != used_video_run and c.id not in used_scene_ids
                for c, _, _ in candidates
            ):
                slot_alternatives.append(scene.id)
                continue

            frag_len = min(scene.duration, slot_spec.max_fragment, remaining)
            if frag_len < slot_spec.min_fragment:
                continue
            src_start, src_end = _pick_fragment(scene, frag_len)
            plan.segments.append(PlanSegment(
                scene_id=scene.id, order=order,
                src_start=src_start, src_end=src_end,
                slot=slot_spec.slot, reason=reason, crop="smart",
            ))
            used_scene_ids.add(scene.id)
            used_video_run = scene.video_id
            remaining -= frag_len
            order += 1

        plan.alternatives[slot_spec.slot] = slot_alternatives[:_ALTERNATIVES_PER_SLOT]

    if music and preset.sync_to_music and project.sync_to_music:
        # Умный выбор фрагмента трека под сценарий: спокойный вход,
        # энергия к кульминации, корректные фейды (ТЗ §16)
        from core.music_selector import select_music_cue, shifted_cut_points
        cue = select_music_cue(music, plan.total_duration, preset)
        plan.music_offset = cue.offset
        plan.music_fade_in = cue.fade_in
        plan.music_fade_out = cue.fade_out
        _snap_to_beats(plan, shifted_cut_points(music, cue.offset))

    _renumber(plan)
    return plan


# --- Скоринг ---

def _rank_for_slot(scenes: list[Scene], spec: SlotSpec,
                   used: set[str]) -> list[tuple[Scene, float, str]]:
    ranked = []
    for s in scenes:
        if s.id in used:
            continue
        if s.duration < spec.min_fragment:
            continue
        score, why = _score(s, spec)
        ranked.append((s, score, why))
    ranked.sort(key=lambda x: -x[1])
    return ranked


def _score(s: Scene, spec: SlotSpec) -> tuple[float, str]:
    reasons = []
    # Тип сцены: точное попадание в приоритеты слота
    if s.scene_type in spec.scene_types:
        type_score = 1.0 - 0.15 * spec.scene_types.index(s.scene_type)
        reasons.append(f"тип «{s.scene_type}» подходит слоту")
    elif s.recommended_slot == spec.slot:
        type_score = 0.7
        reasons.append("LLM рекомендовала это место в ролике")
    else:
        type_score = 0.3
    # Движение: несовпадение с темпом слота штрафуется жёстко — быстрый
    # смазанный пролёт в спокойном вступлении выглядит дёргано и некрасиво
    if not spec.prefer_motion or s.motion in spec.prefer_motion:
        motion_score = 1.0
        if spec.prefer_motion:
            reasons.append(f"движение «{s.motion}» соответствует динамике")
    elif s.motion == "fast" and spec.slot in ("intro", "ending"):
        motion_score = 0.1   # быстрый кадр в начале/финале — почти запрет
    else:
        motion_score = 0.3
    # Качество и эстетика
    quality = 0.6 * s.quality_score + 0.4 * (s.aesthetic_score or s.quality_score)
    if s.aesthetic_score >= 0.7:
        reasons.append("высокая эстетика кадра")
    # Соответствие сценарию от LLM-ранжирования
    match = s.scenario_match_score or 0.5
    if s.scenario_match_score >= 0.7:
        reasons.append("высокое соответствие сценарию")
    # Пользовательские пометки (ТЗ §15)
    user_bonus = {"pinned": 0.5, "good": 0.2, "bad": -0.4}.get(s.user_flag, 0.0)
    if s.user_flag == "pinned":
        reasons.append("закреплена пользователем")

    total = 0.35 * type_score + 0.15 * motion_score + 0.25 * quality + 0.25 * match + user_bonus
    if not reasons:
        reasons.append(f"лучший доступный кандидат (q={s.quality_score:.2f})")
    return round(total, 4), "; ".join(reasons[:3])


def _pick_fragment(scene: Scene, frag_len: float) -> tuple[float, float]:
    """Берём фрагмент из середины сцены: начала/концы часто смазаны переходом."""
    if scene.duration <= frag_len:
        return scene.start, scene.end
    pad = (scene.duration - frag_len) / 2
    start = round(scene.start + pad, 3)
    return start, round(start + frag_len, 3)


# --- Музыка ---

def _snap_to_beats(plan: MontagePlan, cuts: list[float]):
    """Выравнивание границ фрагментов по точкам склейки музыки (ТЗ §16).

    `cuts` — таймкоды в системе координат ролика (уже сдвинутые на offset
    выбранного фрагмента трека). Склейка подтягивается к ближайшей точке
    (допуск ±0.35 сек, длительность не опускается ниже 1 сек).
    """
    if not cuts:
        return
    timeline = 0.0
    for seg in plan.segments:
        end_t = timeline + seg.duration
        nearest = min(cuts, key=lambda c: abs(c - end_t))
        delta = nearest - end_t
        if abs(delta) <= 0.35 and seg.duration + delta >= 1.0:
            seg.src_end = round(seg.src_end + delta, 3)
            seg.beat_synced = True
        timeline += seg.duration


def _renumber(plan: MontagePlan):
    for i, seg in enumerate(plan.segments):
        seg.order = i


# --- LLM-ранжирование (ТЗ §8.4–8.6) ---

_RANK_BATCH = 25  # карточек на один запрос: не упираемся в контекст при 100+ сценах


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _llm_rank(scenario: str, scenes: list[Scene]) -> bool:
    """Просит LLM оценить соответствие карточек сцен сценарию (0..1).

    Работает с текстовыми карточками, а не с изображениями — быстрый запрос.
    Карточки уходят батчами по _RANK_BATCH, чтобы большая библиотека
    не упёрлась в контекст модели.
    При недоступности LM Studio молча пропускается (скоринг остаётся rule-based).
    """
    llm = LLMAnalyzer()
    if not llm.is_available():
        log.info("LM Studio недоступен — ранжирование только rule-based")
        return False

    cards = [s.llm_card() for s in scenes if s.llm_status == "done"]
    if not cards:
        return False

    schema = {
        "name": "scene_ranking", "strict": True,
        "schema": {
            "type": "object",
            "properties": {"scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "match": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["id", "match"],
                    "additionalProperties": False,
                },
            }},
            "required": ["scores"], "additionalProperties": False,
        },
    }
    by_id: dict[str, float] = {}
    try:
        for batch in _chunks(cards, _RANK_BATCH):
            resp = llm.client.chat.completions.create(
                model=llm.model, temperature=0.1, max_tokens=3500,
                response_format={"type": "json_schema", "json_schema": schema},
                messages=[
                    {"role": "system", "content":
                        "Ты — режиссёр монтажа. Оцени соответствие каждой сцены сценарию "
                        "по шкале 0.0-1.0. Отвечай только JSON."},
                    {"role": "user", "content":
                        f"Сценарий:\n{scenario}\n\nСцены:\n{json.dumps(batch, ensure_ascii=False)}"},
                ],
            )
            data = json.loads(resp.choices[0].message.content)
            for x in data.get("scores", []):
                by_id[x["id"]] = float(x["match"])
    except Exception as e:
        log.warning("LLM-ранжирование не удалось (%s) — используется rule-based", e)
        if not by_id:
            return False
    for s in scenes:
        if s.id in by_id:
            s.scenario_match_score = min(max(by_id[s.id], 0.0), 1.0)
    return True
