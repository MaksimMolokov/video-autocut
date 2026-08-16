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
_SUBJECT_GAP_MAX = 3.0  # предел перемотки по кадрам С ЛЮДЬМИ: танцор на ×8
                        # выглядит категорически плохо; пустые промежутки
                        # (дрон летит/завис между этажами) гонятся до gap_max
_FREEZE_MIN_LEN = 2.5   # статичный кусок длиннее этого — «замёрзшая пауза»:
                        # сжимается до project.fpv_pause_out экранных секунд
                        # (по умолчанию 0.5с), быстрее любой перемотки
_FREEZE_DIFF_MAX = 2.0  # средняя пофреймовая разница (0..255) ниже —
                        # картинка «стоит» (шум сенсора/кодека даёт <1.5)


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


_MIN_ZONE_INTEREST = 0.15  # ниже — в кандидате нет ничего интересного (см. _auto_zones)


def _has_subject(s: Scene, cache: dict) -> bool:
    """Есть ли в кадре человек/объект внимания — сначала доверяем LLM
    (people_count), но если она молчит, проверяем настоящими CV-детекторами
    (лица/силуэты по core.smart_crop). Это нужно, потому что: 1) без LM
    Studio people_count всегда 0 у всех сцен; 2) даже при работающей LLM
    она смотрит один кадр сцены и может не заметить танцующего человека
    в динамичной позе — а CV-детектор проверяет несколько кадров отдельно."""
    if s.people_count > 0:
        return True
    if s.id in cache:
        return cache[s.id]
    from core.smart_crop import find_focus
    found = find_focus(s.video_path, s.start, s.end) is not None
    cache[s.id] = found
    return found


def _interest_score(s: Scene, subject_cache: dict | None = None) -> float:
    """Визуальная/содержательная ценность кадра — чтобы выбирать «сюжеты»
    (танцующий человек, красивая деталь), а не просто самый технически
    чистый участок.

    Человек в кадре ДОМИНИРУЕТ над эстетикой и качеством: сцена с танцором
    всегда должна обыгрывать пустой кадр, каким бы красивым и технически
    чистым тот ни был — иначе «сюжетом» становится завис дрона над пустым
    залом, а танец уезжает в перемотку (реальная жалоба). quality_score
    намеренно почти не участвует: статичный завис «чище» динамики по метрикам.
    Статичный кадр БЕЗ обнаруженного субъекта дополнительно штрафуется.
    """
    has_subject = _has_subject(s, subject_cache) if subject_cache is not None \
        else s.people_count > 0
    score = (0.55 * (1.0 if has_subject else 0.0)
            + 0.35 * (s.aesthetic_score or 0.0)
            + 0.10 * s.quality_score)
    if s.motion == "static" and not has_subject:
        score *= 0.25  # статика без людей — почти всегда «ничего не происходит»
    return round(score, 4)


def _window_interest(scenes: list[Scene], w_start: float, w_end: float,
                     subject_cache: dict | None = None) -> float:
    """Средняя интересность окна, взвешенная по перекрытию со сценами."""
    total, acc = 0.0, 0.0
    for s in scenes:
        ov = min(w_end, s.end) - max(w_start, s.start)
        if ov > 0:
            total += ov
            acc += ov * _interest_score(s, subject_cache)
    return acc / total if total > 0 else 0.0


def _subject_spans(scenes: list[Scene], cache: dict,
                   merge_gap: float = 2.0) -> list[tuple[float, float]]:
    """Непрерывные интервалы «в кадре есть человек». Соседние сцены с людьми
    сливаются (разрыв короче merge_gap — тот же танец/человек)."""
    spans: list[list[float]] = []
    for s in sorted(scenes, key=lambda x: x.start):
        if not _has_subject(s, cache):
            continue
        if spans and s.start - spans[-1][1] <= merge_gap:
            spans[-1][1] = max(spans[-1][1], s.end)
        else:
            spans.append([s.start, s.end])
    return [(a, b) for a, b in spans]


def _frozen_spans_profile(path: str, start: float, end: float,
                          min_len: float = _FREEZE_MIN_LEN
                          ) -> list[tuple[float, float]] | None:
    """Паузы по честному замеру: пофреймовая разница картинки почти ноль
    на протяжении min_len — картинка буквально не меняется.

    Основной детектор пауз: не зависит от классификации сцен (лёгкий дрейф
    дрона помечает сцену «slow» — и сценный детектор паузу пропускает) и от
    CV-детекции людей (ложный «человек» в пустом кадре — пауза уходила в
    щадящую перемотку). Замерший человек в позе тоже пауза: раз ничего не
    меняется — держать это дольше настройки незачем.
    None — декодировать не удалось (детекция по сценам остаётся fallback-ом).
    """
    from core.frame_quality import change_profile
    prof = change_profile(path, start, end)
    if prof is None:
        return None
    times, diffs = prof
    k = max(int(0.5 * len(diffs) / max(times[-1] - times[0], 1e-6)), 1)
    smooth = np.convolve(diffs, np.ones(k) / k, mode="same")  # окно ~0.5с
    spans: list[tuple[float, float]] = []
    run_start = None
    for t, d in zip(times, smooth):
        if d < _FREEZE_DIFF_MAX:
            if run_start is None:
                run_start = float(t)
        elif run_start is not None:
            if t - run_start >= min_len:
                spans.append((run_start, float(t)))
            run_start = None
    if run_start is not None and times[-1] - run_start >= min_len:
        spans.append((run_start, float(times[-1])))
    return spans


def _merge_spans(spans: list[tuple[float, float]],
                 merge_gap: float = 0.5) -> list[tuple[float, float]]:
    """Объединяет пересекающиеся/соседние интервалы."""
    out: list[list[float]] = []
    for lo, hi in sorted(spans):
        if out and lo - out[-1][1] <= merge_gap:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [(a, b) for a, b in out]


def _frozen_spans(scenes: list[Scene], cache: dict,
                  min_len: float = _FREEZE_MIN_LEN) -> list[tuple[float, float]]:
    """Интервалы «картинка не меняется»: подряд идущие статичные сцены без
    людей. Длиннее min_len — «замёрзшая пауза» (дрон завис, ничего не
    происходит): в ролике сжимается до фиксированной длительности."""
    spans: list[list[float]] = []
    for s in sorted(scenes, key=lambda x: x.start):
        if s.motion != "static" or _has_subject(s, cache):
            continue
        if spans and s.start - spans[-1][1] <= 0.5:
            spans[-1][1] = max(spans[-1][1], s.end)
        else:
            spans.append([s.start, s.end])
    return [(a, b) for a, b in spans if b - a >= min_len]


def _split_by_subject(a: float, b: float, spans: list[tuple[float, float]]
                      ) -> list[tuple[float, float, bool]]:
    """Интервал [a,b) → куски (lo, hi, есть_ли_люди) по subject-интервалам."""
    parts: list[tuple[float, float, bool]] = []
    cur = a
    for lo, hi in spans:
        lo, hi = max(lo, a), min(hi, b)
        if lo >= hi:
            continue
        if cur < lo:
            parts.append((cur, lo, False))
        parts.append((lo, hi, True))
        cur = hi
    if cur < b:
        parts.append((cur, b, False))
    return parts


def _zones_from_raw(project: Project, video: SourceVideo, scenes: list[Scene],
                    raw: list[tuple[str, int, int, bool]]) -> list[Zone]:
    result: list[Zone] = []
    for title, first, last, technical in raw:
        chunk = scenes[first:last + 1]
        if not chunk:
            continue
        result.append(Zone(
            project_id=project.id, video_id=video.id,
            start=chunk[0].start, end=chunk[-1].end,
            title=title or "зона",
            technical=technical,
            required=not technical,
            score=round(float(np.mean([c.aesthetic_score or c.quality_score
                                       for c in chunk])), 3),
            thumbnail_path=chunk[len(chunk) // 2].thumbnail_path,
        ))
    return result


def _auto_zones(project: Project, video: SourceVideo, scenes: list[Scene],
                route_start: float, route_end: float,
                lane_width: float | None = None) -> list[Zone]:
    """Fallback без осмысленной группировки (LLM недоступен, или контент
    однородный — танец, спортивная съёмка, где нет «комнат»): маршрут делится
    на k равных полос, в каждой берётся самый «интересный» кусок — это и есть
    сюжет, показываемый на нормальной скорости. Остальное — перемотка.

    Без этого шага один цельный дубль без явных смен локации (или когда
    группировка схлопывает всё в один блок) даёт ОДНУ гигантскую зону —
    и тогда почти весь ролик превращается в перемотку («видео всё дёрганое
    и перемотанное», как и было до этого фикса).

    `lane_width` — фиксированная ширина полосы (сек); если задана, число
    полос считается от неё, а не от project.target_duration. Используется
    для деления ОДНОЙ длинной зоны на несколько моментов внутри неё же
    (см. _expand_long_zones): длинный танец должен показать несколько
    красивых кадров с перемоткой между ними, а не один момент + одна
    гигантская перемотка до следующей комнаты.
    """
    span = route_end - route_start
    if span <= 0 or not scenes:
        return []
    if lane_width:
        k = max(1, round(span / lane_width))
    else:
        k = int(np.clip(round(project.target_duration / 10), 4, 10))
    lane = span / k
    subject_cache: dict = {}
    # Если на маршруте вообще есть люди — сюжет ТОЛЬКО на людях: полоса без
    # человека (пустой пролёт, завис между этажами) целиком уходит в
    # перемотку, каким бы красивым ни был кадр. Локации без людей
    # (пустой ресторан) работают по эстетике, как раньше.
    route_scenes = [s for s in scenes if s.end > route_start and s.start < route_end]
    route_has_people = any(_has_subject(s, subject_cache) for s in route_scenes)
    zones: list[Zone] = []
    last_scene_id = None
    for i in range(k):
        lo, hi = route_start + i * lane, route_start + (i + 1) * lane
        chunk = [s for s in scenes if s.end > lo and s.start < hi]
        if not chunk:
            continue
        best = max(chunk, key=lambda sc: _interest_score(sc, subject_cache))
        best_score = _interest_score(best, subject_cache)
        if best_score < _MIN_ZONE_INTEREST:
            # во всей полосе нет ничего интересного (пустой статичный кадр,
            # завис дрон) — не делаем из неё «обязательный сюжет», пусть
            # целиком станет перемоткой между соседними зонами
            continue
        if route_has_people and not _has_subject(best, subject_cache):
            continue  # люди в видео есть, а в этой полосе нет — перемотка
        if best.id == last_scene_id:
            continue  # соседняя полоса выбрала тот же кусок — не дублируем
        last_scene_id = best.id
        title = (best.description[:32].strip() if best.description
                 else f"момент {i + 1}")
        zones.append(Zone(
            project_id=project.id, video_id=video.id,
            start=best.start, end=best.end, title=title or f"момент {i + 1}",
            technical=False, required=True,
            score=best_score, thumbnail_path=best.thumbnail_path,
        ))
    return zones


def _expand_long_zones(project: Project, video: SourceVideo, scenes: list[Scene],
                       zones: list[Zone], target_span: float) -> list[Zone]:
    """Длинная зона (60с непрерывного танца, большой зал) не должна давать
    ОДИН показ + одну гигантскую перемотку до следующей зоны — внутри неё
    самой нужно найти несколько красивых моментов и перематывать МЕЖДУ ними.

    Зона длиннее `target_span * 1.8` делится на несколько под-зон через
    ту же логику интересности, что и _auto_zones (полосы + порог скуки),
    но в границах САМОЙ этой зоны. Хуже одной интересной под-зоны — зона
    остаётся как есть (не размножаем шум).
    """
    out: list[Zone] = []
    for z in zones:
        if z.duration <= target_span * 1.8:
            out.append(z)
            continue
        subs = _auto_zones(project, video, scenes, z.start, z.end,
                           lane_width=target_span)
        out.extend(subs if len(subs) >= 2 else [z])
    return out


def _split_excluding_technical(start: float, end: float,
                               technical_zones: list[Zone]) -> list[tuple[float, float]]:
    """Режет интервал [start, end) на куски, вырезая пересечения с
    техническими зонами — их footage не должно попадать в ролик ВООБЩЕ,
    ни на нормальной, ни на перемоточной скорости (взлёт/посадка/пауза
    между этажами и т.п., явно помеченные пользователем как «не для
    монтажа»)."""
    intervals = [(start, end)]
    for tz in technical_zones:
        next_intervals = []
        for a, b in intervals:
            lo, hi = max(a, tz.start), min(b, tz.end)
            if lo < hi:
                if a < lo:
                    next_intervals.append((a, lo))
                if hi < b:
                    next_intervals.append((hi, b))
            else:
                next_intervals.append((a, b))
        intervals = next_intervals
    return [(a, b) for a, b in intervals if b - a >= _MIN_GAP_LEN]


def detect_zones(storage, project: Project, video: SourceVideo) -> list[Zone]:
    """Ключевые зоны маршрута FPV-файла.

    LLM группирует последовательность кусков по содержанию (вход, зал, бар…).
    Если LLM недоступен ИЛИ результат слишком крупный (меньше 4 зон, или
    какая-то зона занимает больше 45% маршрута — типичный симптом «весь дубль
    похож сам на себя», как в танце или однородной локации), включается
    автоделение маршрута на равные интервалы с выбором самого интересного
    кадра в каждом — так «сюжеты» распределены по всему видео, а не
    схлопнуты в один огромный блок.
    """
    scenes = sorted(storage.list_scenes_by_video(video.id), key=lambda s: s.start)
    if not scenes:
        return []

    raw = _detect_zones_llm(scenes)
    zones = _zones_from_raw(project, video, scenes, raw) if raw else []

    non_tech = [z for z in zones if not z.technical]
    route_span = scenes[-1].end - scenes[0].start
    coarse = (not non_tech) or len(non_tech) < 4 or any(
        z.duration > route_span * 0.45 for z in non_tech)

    if coarse and route_span > 15:
        tech_zones = [z for z in zones if z.technical]
        # технические границы (взлёт/посадка), если LLM их нашёл — сохраняем;
        # внутри них автоделение не расставляет сюжеты
        route_start = max((z.end for z in tech_zones
                           if z.start <= scenes[0].start + route_span * 0.3),
                          default=scenes[0].start)
        route_end = min((z.start for z in tech_zones
                         if z.end >= scenes[-1].end - route_span * 0.3),
                        default=scenes[-1].end)
        auto = _auto_zones(project, video, scenes, route_start, route_end)
        if auto:
            zones = tech_zones + auto

    if not zones:
        # последний рубеж: короткий клип или автоделение ничего не дало —
        # хоть какая-то группировка лучше пустого каталога зон
        zones = _zones_from_raw(project, video, scenes, _detect_zones_fallback(scenes))

    zones.sort(key=lambda z: z.start)
    storage.delete_zones_for_video(video.id)
    for z in zones:
        storage.save_zone(z)
    return zones


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
    gap_speed: float       # скорость промежутков БЕЗ людей
    fits: bool             # уложились ли в target
    warnings: list[str]
    subject_gap_speed: float = 1.0  # щадящая перемотка по кадрам С людьми


def solve_timing(zone_lens: list[float], route_len: float,
                 target: float, style: str,
                 subject_len: float = 0.0,
                 frozen_len: float = 0.0,
                 frozen_out: float = 0.0) -> TimingSolution:
    """Подбор окна зон и скоростей промежутков под целевую длительность.

    Промежуток = весь маршрут МИНУС показанные окна зон (непоказанные части
    зон тоже перематываются). Промежутки делятся на три сорта:
    - с людьми (subject_len — суммарное «человеческое» время маршрута):
      перематываются щадяще, не быстрее ×_SUBJECT_GAP_MAX — ускоренный
      танцор выглядит категорически плохо;
    - «замёрзшие» паузы (frozen_len — картинка не меняется): занимают в
      ролике фиксированные frozen_out секунд, вне зависимости от длины;
    - пустые (дрон летит между этажами): гонятся до gap_max — переход
      между людьми должен быть минимален.
    Логика: сохранить обязательные зоны → срезать замёрзшее → сжать пустое →
    мягко сжать людей → если не влезает, уменьшать окна → предупреждать.
    """
    cfg = STYLES.get(style, STYLES["smooth"])
    w_min, w_max = cfg["window"]
    z_speed = cfg["zone_speed"]
    gap_max = cfg["gap_max"]
    warnings: list[str] = []

    def parts(w: float) -> tuple[float, float, float]:
        """(экранное время зон, пустой промежуток, промежуток с людьми).
        Окна зон лежат на людях (их так выбирают) — показанное время
        вычитается из «человеческого». Замёрзшие паузы исключаются из
        пустого промежутка: их экранное время фиксировано (frozen_out)."""
        shown = sum(min(w, zl) for zl in zone_lens)
        gap_total = max(route_len - shown, 0.0)
        subj_gap = min(max(subject_len - shown, 0.0), gap_total)
        frozen = min(frozen_len, gap_total - subj_gap)
        return shown / z_speed, gap_total - subj_gap - frozen, subj_gap

    for w in np.arange(w_max, w_min - 0.01, -0.5):
        zone_out, empty_gap, subj_gap = parts(float(w))
        rest = target - zone_out - frozen_out
        if rest <= 0:
            continue  # одни зоны уже не влезают — уменьшаем окно дальше
        # пустые промежутки жмём в первую очередь — их не жалко
        t_empty_min = empty_gap / gap_max
        t_subj = rest - t_empty_min
        if subj_gap > 0:
            if t_subj <= 0:
                continue
            s_subj = max(subj_gap / t_subj, _MIN_GAP_SPEED)
            if s_subj > _SUBJECT_GAP_MAX:
                continue  # людей пришлось бы гнать слишком быстро
        else:
            s_subj = 1.0
        # запас времени отдаём пустым промежуткам — не гоним их зря
        t_subj_used = subj_gap / s_subj
        s_empty = (empty_gap / max(rest - t_subj_used, 1e-9)
                   if empty_gap > 0 else 1.0)
        s_empty = min(max(s_empty, _MIN_GAP_SPEED), gap_max)
        if zone_out + frozen_out + t_subj_used + empty_gap / s_empty <= target + 1.0:
            return TimingSolution(round(float(w), 2), z_speed,
                                  round(float(s_empty), 2), True, [],
                                  round(float(s_subj), 2))

    # Не влезло даже при минимальных окнах и максимальных ускорениях
    zone_out, empty_gap, subj_gap = parts(w_min)
    total = (zone_out + frozen_out + empty_gap / gap_max
             + subj_gap / _SUBJECT_GAP_MAX)
    warnings.append(
        f"Тайминг {target:.0f}с слишком короткий: {len(zone_lens)} обязательных "
        f"зон + маршрут займут минимум ~{total:.0f}с (кадры с людьми не "
        f"перематываются быстрее ×{_SUBJECT_GAP_MAX:g} — танец должен остаться "
        f"смотрибельным). Варианты: увеличить длительность ролика; снять "
        f"отметку с части зон; выбрать стиль «динамичный» (сильнее ускоряет); "
        f"согласиться с {total:.0f}с.")
    return TimingSolution(round(float(w_min), 2), z_speed, gap_max, False,
                          warnings, _SUBJECT_GAP_MAX)


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

    # Технические зоны (взлёт/посадка/пауза между этажами — явно помечены
    # пользователем «не для монтажа») вырезаются из ролика целиком, на
    # любой скорости — не только на границах маршрута, но и в середине.
    technical_zones = [z for z in zones if z.technical]

    scenes = sorted(storage.list_scenes_by_video(video.id), key=lambda s: s.start)

    # Длинный непрерывный кусок (60с танца, большой зал) не должен давать
    # ОДИН показ + одну гигантскую перемотку до следующей зоны — внутри
    # него самого ищем несколько красивых моментов (см. _expand_long_zones).
    target_span = style["window"][1] * 3.0
    required = _expand_long_zones(project, video, scenes, required, target_span)
    required.sort(key=lambda z: z.start)

    # Технические куски физически не попадут в ролик (см. add_gap ниже) —
    # тайминг-солвер должен считать маршрут БЕЗ них, иначе выделит на
    # перемотку время, которое на деле пропадёт, и ролик выйдет короче target
    technical_span = sum(
        max(0.0, min(tz.end, route_end) - max(tz.start, route_start))
        for tz in technical_zones)
    route_len = (route_end - route_start) - technical_span

    # «Человеческое» время маршрута: эти куски перематываются щадяще
    # (≤×_SUBJECT_GAP_MAX), пустые — быстро. Технические не считаем: они
    # вырезаются целиком.
    subject_cache: dict = {}
    subject_spans = _subject_spans(scenes, subject_cache)

    def _span_len_in_route(lo: float, hi: float) -> float:
        """Длина куска внутри маршрута за вычетом технических зон."""
        lo, hi = max(lo, route_start), min(hi, route_end)
        if lo >= hi:
            return 0.0
        seg_len = hi - lo
        for tz in technical_zones:
            seg_len -= max(0.0, min(hi, tz.end) - max(lo, tz.start))
        return max(seg_len, 0.0)

    # «Замёрзшие» паузы (картинка не меняется): каждая занимает в ролике
    # не больше project.fpv_pause_out секунд — правило пользователя.
    # Основной детектор — пофреймовая разница картинки (точные границы,
    # не зависит от классификации сцен и CV-людей); сценный — дополнение.
    pause_out = max(float(project.fpv_pause_out or 0.5), 0.1)
    # короче фейда сегмент нельзя: crossfade-цепочка ломается на офсетах
    pause_out = max(pause_out, style["fade"] + 0.1)
    frozen_raw = list(_frozen_spans(scenes, subject_cache))
    profile_spans = _frozen_spans_profile(video.path, route_start, route_end)
    if profile_spans:
        frozen_raw += profile_spans
    frozen_spans = [(lo, hi) for lo, hi in _merge_spans(frozen_raw)
                    if _span_len_in_route(lo, hi) >= _FREEZE_MIN_LEN]
    frozen_len = sum(_span_len_in_route(lo, hi) for lo, hi in frozen_spans)

    def _frozen_overlap(lo: float, hi: float) -> float:
        return sum(max(0.0, min(hi, fh) - max(lo, fl))
                   for fl, fh in frozen_spans)

    # «Человеческое» время не должно включать паузы: замер главнее —
    # ложный «человек» от CV в пустом замершем кадре не спасает паузу
    subject_len = sum(
        max(_span_len_in_route(lo, hi) - _frozen_overlap(lo, hi), 0.0)
        for lo, hi in subject_spans)

    # Зона, почти целиком лежащая на паузе (ложный «сюжет» на замершем
    # кадре), не показывается на нормальной скорости — уходит в перемотку
    # и сжимается как пауза. Все зоны на паузах — краевой случай, оставляем.
    unfrozen = [z for z in required
                if _frozen_overlap(z.start, z.end) < 0.7 * z.duration]
    if unfrozen:
        required = unfrozen

    sol = solve_timing([z.duration for z in required], route_len,
                       project.target_duration, project.fpv_style,
                       subject_len=subject_len,
                       frozen_len=frozen_len,
                       frozen_out=pause_out * len(frozen_spans))

    # Позиция окна внутри зоны — плавный участок (плотный профиль движения)
    # И одновременно самый «интересный» (танцующий человек, красивая деталь):
    # смаз/рывок штрафуется жёстко, интересность — тай-брейк среди плавных.
    profile = motion_profile(video.path, route_start, route_end)

    def best_window(z: Zone, w: float) -> tuple[float, float]:
        w = min(w, z.duration)
        if z.duration <= w + 0.2:
            mid = z.start + z.duration / 2
            st = min(max(mid - w / 2, z.start), z.end - w)
            return round(st, 3), round(st + w, 3)
        best, best_score = z.start, float("inf")
        for st in np.arange(z.start, z.end - w + 0.01, 0.5):
            motion_bad = 0.0
            if profile is not None:
                times, vecs = profile
                ok, bad = window_motion_ok(times, vecs, st, st + w)
                motion_bad = bad if ok else bad + 50  # дёрганое — в конец очереди
            interest = _window_interest(scenes, st, st + w, subject_cache)
            frozen_frac = _frozen_overlap(st, st + w) / w  # окно на паузе — зря
            score = (motion_bad - 8.0 * interest + 40.0 * frozen_frac)
            if score < best_score:
                best, best_score = float(st), score
        return round(best, 3), round(best + w, 3)

    windows = [best_window(z, sol.window) for z in required]

    # Сегменты: [перемотка] [зона] [перемотка] [зона] … строго по порядку
    plan = MontagePlan(project_id=project.id, mode="fpv")
    plan.transition = "crossfade"
    plan.transition_duration = style["fade"]
    plan.warnings = list(sol.warnings)

    def scene_at(t: float) -> Scene:
        for s in scenes:
            if s.start <= t < s.end:
                return s
        return scenes[-1]

    def add_gap(a: float, b: float, label: str):
        """Перемотка [a,b): технические зоны вырезаны совсем; куски с людьми
        перематываются щадяще (subject_gap_speed); «замёрзшие» паузы
        сжимаются до pause_out экранных секунд; пустые — быстро."""
        nonlocal order
        for lo, hi in _split_excluding_technical(a, b, technical_zones):
            # 1) паузы главнее людей: замер картинки честнее CV-детекции —
            # ложный «человек» в пустом кадре не должен спасать паузу;
            # 2) остальное делится на «с людьми» и «пустое»
            pieces: list[list] = []   # [lo, hi, kind: subject|frozen|empty]
            for flo, fhi, frozen in _split_by_subject(lo, hi, frozen_spans):
                if frozen:
                    pieces.append([flo, fhi, "frozen"])
                    continue
                for plo, phi, subj in _split_by_subject(flo, fhi, subject_spans):
                    pieces.append([plo, phi, "subject" if subj else "empty"])
            # микрокуски приклеиваем к соседу — не плодим сегменты
            merged: list[list] = []
            for plo, phi, kind in pieces:
                if merged and phi - plo < _MIN_GAP_LEN:
                    merged[-1][1] = phi
                else:
                    merged.append([plo, phi, kind])
            if len(merged) > 1 and merged[0][1] - merged[0][0] < _MIN_GAP_LEN:
                merged[1][0] = merged[0][0]
                merged.pop(0)
            for plo, phi, kind in merged:
                if kind == "frozen":
                    # вся пауза → pause_out экранных секунд, но не медленнее
                    # обычной перемотки пустых участков
                    speed = max((phi - plo) / pause_out, sol.gap_speed)
                    reason = (f"статичная пауза {phi - plo:.0f}с — сжата "
                              f"до {pause_out:g}с")
                elif kind == "subject":
                    speed = sol.subject_gap_speed
                    reason = f"щадящая перемотка ×{speed:g} — в кадре люди"
                else:
                    speed = sol.gap_speed
                    reason = f"перемотка ×{speed:g} по маршруту"
                plan.segments.append(PlanSegment(
                    scene_id=scene_at(plo).id, order=order,
                    src_start=round(plo, 3), src_end=round(phi, 3),
                    slot=label, speed=round(speed, 2), crop="smart",
                    reason=reason))
                order += 1

    order = 0
    cursor = route_start
    for z, (w_start, w_end) in zip(required, windows):
        if w_start - cursor >= _MIN_GAP_LEN:   # перемотка до зоны
            add_gap(cursor, w_start, "переезд")
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
    if route_end - cursor >= _MIN_GAP_LEN:
        # хвост маршрута после последней зоны — короткая перемотка к финалу.
        # Без этой проверки (раньше сравнивавшей .end последней ЗОНЫ вместо
        # фактического курсора-окна) хвост маршрута молча пропадал каждый
        # раз, когда последняя показанная зона совпадала с концом активного
        # маршрута — локация оказывалась показана не до конца.
        add_gap(cursor, route_end, "финал")

    # Музыка: фрагмент под длительность, фейды; биты не снапим (скорости)
    if music is not None and project.music_path:
        cue = select_music_cue(music, plan.total_duration,
                               get_preset("drone_cinematic"))
        plan.music_offset = cue.offset
        plan.music_fade_in = cue.fade_in
        plan.music_fade_out = cue.fade_out
    return plan
