"""Audio Analyzer (ТЗ §16): темп, биты, энергетика, точки для склеек.

librosa импортируется лениво: тяжёлая зависимость не должна тормозить
запуск CLI/UI, когда музыка не анализируется.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class MusicAnalysis:
    path: str
    duration: float = 0.0
    bpm: float = 0.0
    beats: list[float] = field(default_factory=list)        # таймкоды битов
    downbeats: list[float] = field(default_factory=list)    # сильные доли (каждый 4-й бит)
    energy_curve: list[float] = field(default_factory=list) # энергия 0..1 по秒ундам
    calm_ranges: list[tuple[float, float]] = field(default_factory=list)
    energetic_ranges: list[tuple[float, float]] = field(default_factory=list)
    climax_time: float = 0.0        # центр самого энергичного участка
    cut_points: list[float] = field(default_factory=list)   # кандидаты для смены кадра

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def analyze_music(path: str | Path) -> MusicAnalysis:
    import librosa  # ленивый импорт

    path = str(path)
    y, sr = librosa.load(path, sr=22050, mono=True)
    duration = float(len(y) / sr)
    result = MusicAnalysis(path=path, duration=round(duration, 2))

    # Темп и биты
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    result.bpm = round(float(np.atleast_1d(tempo)[0]), 1)
    beats = librosa.frames_to_time(beat_frames, sr=sr)
    result.beats = [round(float(b), 3) for b in beats]
    result.downbeats = result.beats[::4]  # приближение: сильная доля каждые 4 бита

    # Огибающая энергии по секундам (RMS), нормированная 0..1
    rms = librosa.feature.rms(y=y, hop_length=512)[0]
    t_rms = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)
    per_sec = []
    for s in range(int(duration) + 1):
        mask = (t_rms >= s) & (t_rms < s + 1)
        per_sec.append(float(rms[mask].mean()) if mask.any() else 0.0)
    arr = np.array(per_sec)
    if arr.max() > 0:
        arr = arr / arr.max()
    result.energy_curve = [round(float(v), 3) for v in arr]

    # Спокойные/энергичные диапазоны по порогам
    result.calm_ranges = _ranges(arr, lambda v: v < 0.4)
    result.energetic_ranges = _ranges(arr, lambda v: v >= 0.7)

    # Кульминация: центр самого длинного/сильного энергичного окна (окно 5 сек)
    if len(arr) >= 5:
        window = np.convolve(arr, np.ones(5) / 5, mode="valid")
        result.climax_time = round(float(np.argmax(window)) + 2.5, 2)

    # Точки склеек: сильные доли + всплески энергии (onset strength peaks)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    peaks = librosa.util.peak_pick(onset_env, pre_max=10, post_max=10,
                                   pre_avg=20, post_avg=20, delta=0.6, wait=15)
    onset_times = librosa.frames_to_time(peaks, sr=sr)
    cut_candidates = sorted(set(
        [round(float(t), 3) for t in result.downbeats]
        + [round(float(t), 3) for t in onset_times]
    ))
    # не чаще раза в секунду
    cuts, last = [], -10.0
    for t in cut_candidates:
        if t - last >= 1.0:
            cuts.append(t)
            last = t
    result.cut_points = cuts
    return result


def _ranges(arr: np.ndarray, pred) -> list[tuple[float, float]]:
    """Непрерывные диапазоны секунд, где pred(value) истинно (длиной >= 2 сек)."""
    out, start = [], None
    for i, v in enumerate(arr):
        if pred(v) and start is None:
            start = i
        elif not pred(v) and start is not None:
            if i - start >= 2:
                out.append((float(start), float(i)))
            start = None
    if start is not None and len(arr) - start >= 2:
        out.append((float(start), float(len(arr))))
    return out
