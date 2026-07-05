"""Speech Analyzer (ТЗ §8): распознавание речи в исходниках через Whisper.

Зачем: склейка посреди фразы ломает восприятие (семейные видео, интервью).
Планировщик сдвигает границы фрагментов так, чтобы фразы не резались.

Бэкенд: mlx-whisper (нативный Apple Silicon). Библиотека отсутствует /
аудио нет → анализ тихо пропускается, пайплайн работает как раньше.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

WHISPER_MODEL = "mlx-community/whisper-small-mlx"  # ~500МБ, скачивается один раз

Phrase = tuple[float, float, str]  # (start, end, text) в таймлайне исходника


def available() -> bool:
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe_video(path: str | Path) -> list[Phrase] | None:
    """Фразы с таймкодами. None — распознавание недоступно/не удалось."""
    if not available():
        log.info("mlx-whisper не установлен — анализ речи пропущен")
        return None
    try:
        import mlx_whisper
        result = mlx_whisper.transcribe(str(path), path_or_hf_repo=WHISPER_MODEL,
                                        verbose=None)
        phrases: list[Phrase] = []
        for seg in result.get("segments", []):
            text = (seg.get("text") or "").strip()
            # выбрасываем «пустые» сегменты и галлюцинации на шуме
            if len(text) < 2 or float(seg.get("no_speech_prob", 0)) > 0.6:
                continue
            phrases.append((round(float(seg["start"]), 3),
                            round(float(seg["end"]), 3), text))
        return phrases
    except Exception as e:  # речь — вспомогательный сигнал, не роняем анализ
        log.warning("Whisper не справился с %s: %s", path, e)
        return None


def adjust_for_speech(start: float, end: float, phrases: list,
                      scene_start: float, scene_end: float,
                      max_len: float) -> tuple[float, float]:
    """Сдвигает границы фрагмента, чтобы не резать фразу посередине.

    Правила:
    - граница внутри фразы → расширяем фрагмент до конца/начала фразы,
      если позволяют границы сцены и max_len; иначе сжимаем до края фразы;
    - фрагмент короче 1с после правок не отдаём — возвращаем исходный.
    """
    new_start, new_end = start, end

    for p_start, p_end, _ in phrases:
        # начало фрагмента режет фразу
        if p_start < new_start < p_end:
            if new_start - p_start <= 1.5 and p_start >= scene_start:
                new_start = p_start          # захватываем фразу целиком
            else:
                new_start = min(p_end, new_end)  # начинаем после фразы
        # конец фрагмента режет фразу
        if p_start < new_end < p_end:
            if (p_end - new_start) <= max_len and p_end <= scene_end:
                new_end = p_end              # договариваем фразу
            else:
                new_end = max(p_start, new_start)  # заканчиваем до фразы

    if new_end - new_start < 1.0:
        return start, end                    # правки съели фрагмент — отменяем
    return round(new_start, 3), round(new_end, 3)
