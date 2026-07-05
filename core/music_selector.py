"""Умный выбор фрагмента музыки под сценарий (ТЗ §16 + UX-требование).

Ролик короче трека, поэтому важно взять ПРАВИЛЬНЫЙ кусок:
- вступление ролика ложится на спокойный участок (для low/medium динамики),
- энергия трека нарастает к кульминации ролика (~75% таймлайна),
- начало фрагмента прижато к сильной доле — биты совпадают со склейками,
- вход/выход с фейдами, финал не обрывается.

Алгоритм: строим желаемый профиль энергии по слотам пресета, скользим окном
длиной с ролик по energy_curve трека и берём окно с максимальной похожестью.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from core.audio_analyzer import MusicAnalysis
from core.presets import Preset

log = logging.getLogger(__name__)

# Желаемая энергия по слотам (масштаб 0..1)
_SLOT_ENERGY = {
    "intro": 0.35, "development": 0.6, "main": 0.75, "climax": 1.0, "ending": 0.3,
}
# Для высокой динамики вступление тоже энергичное (хук Reels/TikTok)
_SLOT_ENERGY_HIGH = {
    "intro": 0.8, "development": 0.75, "main": 0.85, "climax": 1.0, "ending": 0.4,
}


@dataclass
class MusicCue:
    offset: float          # с какой секунды трека начинать
    duration: float        # длина фрагмента (= длине ролика)
    fade_in: float
    fade_out: float
    score: float = 0.0     # похожесть профиля (диагностика)
    reason: str = ""


def select_music_cue(music: MusicAnalysis, target_duration: float,
                     preset: Preset) -> MusicCue:
    """Выбирает лучший фрагмент трека под структуру ролика."""
    fade_in = 0.3 if preset.dynamics == "high" else 1.0
    fade_out = 1.5
    curve = np.array(music.energy_curve, dtype=float)

    # Трек короче ролика или почти равен — берём с начала
    if music.duration <= target_duration + 2 or len(curve) < int(target_duration) + 2:
        return MusicCue(0.0, min(target_duration, music.duration), fade_in, fade_out,
                        reason="трек короткий — используется с начала")

    desired = _desired_profile(preset, int(round(target_duration)))
    win = len(desired)

    # Скользящее окно: похожесть = корреляция + штраф за разницу уровней
    best_start, best_score = 0, -np.inf
    last = len(curve) - win
    for start in range(0, last + 1):
        window = curve[start:start + win]
        if window.std() < 1e-6:
            corr = 0.0
        else:
            corr = float(np.corrcoef(window, desired)[0, 1])
            if np.isnan(corr):
                corr = 0.0
        level_penalty = float(np.abs(window - desired).mean())
        score = corr - 0.5 * level_penalty
        if score > best_score:
            best_score, best_start = score, start

    offset = float(best_start)
    # Прижимаем старт к ближайшей сильной доле (биты лягут на склейки)
    anchors = music.downbeats or music.beats
    if anchors:
        near = [b for b in anchors if abs(b - offset) <= 2.0]
        if near:
            offset = min(near, key=lambda b: abs(b - offset))
    # Не вылезаем за конец трека
    offset = min(offset, music.duration - target_duration)
    offset = max(offset, 0.0)

    return MusicCue(
        offset=round(offset, 3),
        duration=target_duration,
        fade_in=fade_in, fade_out=fade_out,
        score=round(best_score, 3),
        reason=f"профиль «{preset.dynamics}»: спокойнее в начале, пик к кульминации"
        if preset.dynamics != "high" else "профиль «high»: энергичный старт-хук",
    )


def _desired_profile(preset: Preset, n_seconds: int) -> np.ndarray:
    """Секундный профиль желаемой энергии из долей слотов пресета."""
    table = _SLOT_ENERGY_HIGH if preset.dynamics == "high" else _SLOT_ENERGY
    profile: list[float] = []
    for spec in preset.slots:
        n = max(int(round(spec.share * n_seconds)), 1)
        profile.extend([table.get(spec.slot, 0.6)] * n)
    profile = profile[:n_seconds] or [0.6]
    while len(profile) < n_seconds:
        profile.append(profile[-1])
    return np.array(profile, dtype=float)


def shifted_cut_points(music: MusicAnalysis, offset: float) -> list[float]:
    """Точки склейки в системе координат ролика (трек начат с offset)."""
    cuts = music.cut_points or music.beats
    return [round(c - offset, 3) for c in cuts if c >= offset]
