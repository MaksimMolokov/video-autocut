"""FPV Showroom: цельный однодублевый облёт локации → обзорный ролик.

Три кита режима:
1. detect_zones — ключевые зоны маршрута (LLM смотрит на последовательность
   описаний 10с-кусков и группирует их: «вход», «зал», «бар»…; взлёт/посадка
   помечаются техническими).
2. solve_timing — укладка в тайминг: окна обязательных зон на нормальной
   скорости, промежутки ускоряются; не влезает — честные предупреждения.
3. build_fpv_plan — план, покрывающий маршрут НЕПРЕРЫВНО от первой до
   последней зоны. Порядок исходника не нарушается никогда.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import numpy as np

from core.llm_analyzer import LLMAnalyzer
from core.models import MontagePlan, PlanSegment, Project, Scene, SourceVideo, Zone

log = logging.getLogger(__name__)

# Стили showroom: скорость зон, максимум ускорения промежутков, переход.
# gap_max калиброван под типовой кейс «5 минут маршрута → 60с ролика»
# (нужна средняя перемотка ×5–8; hyperlapse-эффект читаем при плавном полёте)
STYLES = {
    "smooth":  {"title": "Плавный обзор",     "zone_speed": 1.0, "gap_max": 8.0,
                "fade": 0.5, "window": (3.0, 6.0)},
    "dynamic": {"title": "Динамичный обзор",  "zone_speed": 1.2, "gap_max": 12.0,
                "fade": 0.25, "window": (2.5, 5.0)},
    "premium": {"title": "Премиальный showroom", "zone_speed": 1.0, "gap_max": 6.0,
                "fade": 0.6, "window": (3.5, 7.0)},
}

_MIN_GAP_SPEED = 1.0   # промежуток не замедляем
_MIN_GAP_LEN = 0.4     # короче — приклеивается к соседней зоне


# ─────────────────────────── Зоны ───────────────────────────

_ZONES_SCHEMA = {
    "name": "fpv_zones", "strict": True,
    "schema": {
        "type": "object",
        "properties": {"zones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string",
                              "description": "короткое имя зоны: вход, зал, бар, терраса…"},
                    "start_index": {"type": "integer",
                                    "description": "номер первого куска зоны (из списка)"},
                    "end_index": {"type": "integer",
                                  "description": "номер последнего куска зоны"},
                    "technical": {"type": "boolean",
                                  "description": "взлёт/посадка/настройка — не для монтажа"},
                },
                "required": ["title", "start_index", "end_index", "technical"],
                "additionalProperties": False,
            },
        }},
        "required": ["zones"], "additionalProperties": False,
    },
}


def detect_zones(storage, project: Project, video: SourceVideo) -> list[Zone]:
    """Ключевые зоны маршрута FPV-файла. LLM группирует последовательность
    кусков; без LLM — fallback-группировка похожих соседей."""
    scenes = sorted(storage.list_scenes_by_video(video.id), key=lambda s: s.start)
    if not scenes:
        return []

    zones = _detect_zones_llm(scenes) or _detect_zones_fallback(scenes)

    result: list[Zone] = []
    for title, first, last, technical in zones:
        chunk = scenes[first:last + 1]
        if not chunk:
            continue
        z = Zone(
            project_id=project.id, video_id=video.id,
            start=chunk[0].start, end=chunk[-1].end,
            title=title or "зона",
            technical=technical,
            required=not technical,
            score=round(float(np.mean([c.aesthetic_score or c.quality_score
                                       for c in chunk])), 3),
            thumbnail_path=chunk[len(chunk) // 2].thumbnail_path,
        )
        result.append(z)

    storage.delete_zones_for_video(video.id)
    for z in result:
        storage.save_zone(z)
    return result


def _detect_zones_llm(scenes: list[Scene]) -> list[tuple[str, int, int, bool]] | None:
    described = [s for s in scenes if s.llm_status == "done" and s.description]
    if len(described) < len(scenes) * 0.6:
        return None  # описаний мало — fallback честнее
    llm = LLMAnalyzer()
    if not llm.is_available():
        return None
    listing = "\n".join(f"{i}. [{s.start:.0f}–{s.end:.0f}с] {s.description}"
                        for i, s in enumerate(scenes))
    try:
        resp = llm.client.chat.completions.create(
            model=llm.model, temperature=0.1, max_tokens=3000,
            response_format={"type": "json_schema", "json_schema": _ZONES_SCHEMA},
            messages=[
                {"role": "system", "content":
                    "Ты — монтажёр FPV-обзоров локаций. Видео снято ОДНИМ дублем: "
                    "оператор проходит локацию от входа до финальной точки. "
                    "Сгруппируй последовательные куски в ключевые зоны маршрута "
                    "(вход, зал, бар, терраса, коридор…). Зона — это 1-4 куска "
                    "(примерно 10-40 секунд). Если участок длинный и однородный — "
                    "всё равно раздели его по заметным ориентирам из описаний "
                    "(здание, объект, люди, поворот маршрута), каждой части — "
                    "своё название. Итого зон должно быть от 4 до 10. "
                    "Взлёт, посадка, настройка, земля/руки в кадре — "
                    "technical=true. Индексы кусков не пересекаются и идут "
                    "по возрастанию."},
                {"role": "user", "content":
                    f"Куски видео по порядку:\n{listing}"},
            ],
        )
        data = json.loads(resp.choices[0].message.content)
        out = []
        prev_end = -1
        for zn in data.get("zones", []):
            a, b = int(zn["start_index"]), int(zn["end_index"])
            a, b = max(a, prev_end + 1), min(b, len(scenes) - 1)
            if a > b:
                continue
            out.append((str(zn.get("title", "зона")).strip(), a, b,
                        bool(zn.get("technical", False))))
            prev_end = b
        return out or None
    except Exception as e:
        log.warning("LLM-детекция зон не удалась: %s", e)
        return None


def _detect_zones_fallback(scenes: list[Scene]) -> list[tuple[str, int, int, bool]]:
    """Без LLM: группируем соседние похожие куски (общие теги/тип)."""
    from core.montage_planner import _similar_scenes
    groups: list[list[int]] = [[0]]
    hist_cache: dict = {}
    for i in range(1, len(scenes)):
        if _similar_scenes(scenes[i - 1], scenes[i], hist_cache):
            groups[-1].append(i)
        else:
            groups.append([i])
    out = []
    for g in groups:
        first, last = g[0], g[-1]
        title = (scenes[first].description[:40] or f"зона {first + 1}").strip()
        out.append((title, first, last, False))
    return out


# ─────────────────────────── Тайминг ───────────────────────────

@dataclass
class TimingSolution:
    window: float          # длина окна обязательной зоны, сек исходника
    zone_speed: float      # скорость показа зон
    gap_speed: float       # скорость промежутков
    fits: bool             # уложились ли в target
    warnings: list[str]


def solve_timing(zone_lens: list[float], route_len: float,
                 target: float, style: str) -> TimingSolution:
    """Подбор окна зон и скорости промежутков под целевую длительность.

    Промежуток = весь маршрут МИНУС показанные окна зон (непоказанные части
    зон тоже перематываются). Логика по спеке: сохранить обязательные зоны →
    ускорить промежутки → если не влезает, уменьшать окна → предупреждать.
    """
    cfg = STYLES.get(style, STYLES["smooth"])
    w_min, w_max = cfg["window"]
    z_speed = cfg["zone_speed"]
    gap_max = cfg["gap_max"]
    warnings: list[str] = []

    def parts(w: float) -> tuple[float, float]:
        shown = sum(min(w, zl) for zl in zone_lens)
        return shown / z_speed, max(route_len - shown, 0.0)

    for w in np.arange(w_max, w_min - 0.01, -0.5):
        zone_out, gap_total = parts(float(w))
        rest = target - zone_out
        if rest <= 0:
            continue  # одни зоны уже не влезают — уменьшаем окно дальше
        gap_speed = max(gap_total / rest, _MIN_GAP_SPEED) if gap_total > 0 else 1.0
        if gap_speed <= gap_max:
            return TimingSolution(round(float(w), 2), z_speed,
                                  round(float(gap_speed), 2), True, [])

    # Не влезло даже при минимальных окнах и максимальном ускорении
    zone_out, gap_total = parts(w_min)
    total = zone_out + gap_total / gap_max
    warnings.append(
        f"Тайминг {target:.0f}с слишком короткий: {len(zone_lens)} обязательных "
        f"зон + маршрут займут минимум ~{total:.0f}с. Варианты: увеличить "
        f"длительность ролика; снять отметку с части зон; выбрать стиль "
        f"«динамичный» (сильнее ускоряет); согласиться с {total:.0f}с.")
    return TimingSolution(round(float(w_min), 2), z_speed, gap_max, False, warnings)


# ─────────────────────────── План ───────────────────────────

def build_fpv_plan(storage, project: Project, video: SourceVideo,
                   music=None) -> MontagePlan:
    """Showroom-план: непрерывный маршрут, зоны — нормально, промежутки —
    перемотка. Порядок исходника неизменен по построению (сегменты идут
    строго по возрастанию таймкода)."""
    from core.frame_quality import motion_profile, window_motion_ok
    from core.music_selector import select_music_cue
    from core.presets import get_preset

    zones = storage.list_zones(video.id)
    if not zones:
        raise ValueError("Зоны не найдены — сначала выполните детекцию зон")
    style = STYLES.get(project.fpv_style, STYLES["smooth"])

    # Маршрут: от первой до последней НЕтехнической зоны
    active = [z for z in zones if not z.technical]
    if not active:
        raise ValueError("Все зоны помечены техническими")
    route_start, route_end = active[0].start, active[-1].end
    required = [z for z in active if z.required]
    if not required:
        required = active  # ничего не отмечено — показываем все зоны

    sol = solve_timing([z.duration for z in required], route_end - route_start,
                       project.target_duration, project.fpv_style)

    # Позиция окна внутри зоны — самый плавный участок по плотному профилю
    profile = motion_profile(video.path, route_start, route_end)

    def best_window(z: Zone, w: float) -> tuple[float, float]:
        w = min(w, z.duration)
        if z.duration <= w + 0.2 or profile is None:
            mid = z.start + z.duration / 2
            st = min(max(mid - w / 2, z.start), z.end - w)
            return st, st + w
        times, vecs = profile
        best, best_bad = z.start, float("inf")
        for st in np.arange(z.start, z.end - w + 0.01, 0.5):
            ok, bad = window_motion_ok(times, vecs, st, st + w)
            bad += 0 if ok else 50  # дёрганые окна — в самый конец очереди
            if bad < best_bad:
                best, best_bad = float(st), bad
        return round(best, 3), round(best + w, 3)

    windows = [best_window(z, sol.window) for z in required]

    # Сегменты: [перемотка] [зона] [перемотка] [зона] … строго по порядку
    plan = MontagePlan(project_id=project.id, mode="fpv")
    plan.transition = "crossfade"
    plan.transition_duration = style["fade"]
    plan.warnings = list(sol.warnings)

    scenes = sorted(storage.list_scenes_by_video(video.id), key=lambda s: s.start)

    def scene_at(t: float) -> Scene:
        for s in scenes:
            if s.start <= t < s.end:
                return s
        return scenes[-1]

    order = 0
    cursor = route_start
    for z, (w_start, w_end) in zip(required, windows):
        if w_start - cursor >= _MIN_GAP_LEN:   # перемотка до зоны
            plan.segments.append(PlanSegment(
                scene_id=scene_at(cursor).id, order=order,
                src_start=round(cursor, 3), src_end=round(w_start, 3),
                slot="переезд", speed=sol.gap_speed, crop="smart",
                reason=f"перемотка ×{sol.gap_speed:g} по маршруту"))
            order += 1
        else:
            w_start = cursor  # микрозазор приклеиваем к зоне
        plan.segments.append(PlanSegment(
            scene_id=scene_at(w_start).id, order=order,
            src_start=round(w_start, 3), src_end=round(w_end, 3),
            slot=z.title[:24], speed=sol.zone_speed, crop="smart",
            reason=f"обязательная зона «{z.title}»"
                   + (f" ×{sol.zone_speed:g}" if sol.zone_speed != 1 else "")))
        order += 1
        cursor = w_end
    if route_end - cursor >= _MIN_GAP_LEN and required[-1].end < route_end - 0.5:
        # хвост маршрута после последней зоны — короткая перемотка к финалу
        plan.segments.append(PlanSegment(
            scene_id=scene_at(cursor).id, order=order,
            src_start=round(cursor, 3), src_end=round(route_end, 3),
            slot="финал", speed=sol.gap_speed, crop="smart",
            reason=f"выход к финальной точке ×{sol.gap_speed:g}"))

    # Музыка: фрагмент под длительность, фейды; биты не снапим (скорости)
    if music is not None and project.music_path:
        cue = select_music_cue(music, plan.total_duration,
                               get_preset("drone_cinematic"))
        plan.music_offset = cue.offset
        plan.music_fade_in = cue.fade_in
        plan.music_fade_out = cue.fade_out
    return plan
