"""Scene Detector (ТЗ §7.2): разбиение видео на сцены через PySceneDetect.

- AdaptiveDetector устойчивее к плавным дроновым панорамам, чем ContentDetector.
- Слишком короткие сцены отбрасываются, слишком длинные — режутся на части
  (длинный непрерывный пролёт = несколько потенциальных фрагментов).
"""
from __future__ import annotations

import logging
from pathlib import Path

from scenedetect import AdaptiveDetector, detect

import config

log = logging.getLogger(__name__)


def detect_scenes(path: str | Path, duration: float) -> list[tuple[float, float]]:
    """Возвращает список (start_sec, end_sec) сцен видеофайла."""
    try:
        scene_list = detect(
            str(path),
            AdaptiveDetector(adaptive_threshold=config.ADAPTIVE_THRESHOLD),
            show_progress=False,
        )
    except Exception as e:  # повреждённый файл не должен ронять пайплайн
        log.warning("PySceneDetect не справился с %s: %s", path, e)
        scene_list = []

    if scene_list:
        raw = [(s.get_seconds(), e.get_seconds()) for s, e in scene_list]
    else:
        # Ни одной смены сцены (один непрерывный кадр) — весь файл одна сцена
        raw = [(0.0, duration)] if duration > 0 else []

    return _normalize(raw)


def _normalize(raw: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Отсев коротких и нарезка длинных сцен."""
    result: list[tuple[float, float]] = []
    for start, end in raw:
        length = end - start
        if length < config.MIN_SCENE_LEN_SEC:
            continue
        if length <= config.MAX_SCENE_LEN_SEC:
            result.append((round(start, 3), round(end, 3)))
            continue
        # Длинную сцену режем на равные куски <= MAX_SCENE_LEN_SEC
        n_parts = int(length // config.MAX_SCENE_LEN_SEC) + 1
        part = length / n_parts
        for i in range(n_parts):
            s = start + i * part
            e = min(start + (i + 1) * part, end)
            if e - s >= config.MIN_SCENE_LEN_SEC:
                result.append((round(s, 3), round(e, 3)))
    return result
