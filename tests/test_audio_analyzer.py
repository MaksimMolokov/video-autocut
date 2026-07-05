"""Audio Analyzer: темп, биты, энергетика, точки склеек."""
import json

import pytest

from core.audio_analyzer import MusicAnalysis, _ranges, analyze_music
import numpy as np


@pytest.fixture(scope="module")
def analysis(synthetic_music) -> MusicAnalysis:
    return analyze_music(synthetic_music)


def test_duration_and_bpm(analysis):
    assert 9.5 <= analysis.duration <= 10.5
    # клики каждые 0.5 c → 120 BPM (допускаем кратные ошибки трекера)
    assert analysis.bpm > 0
    assert any(abs(analysis.bpm - x) < 8 for x in (60, 120, 240))


def test_beats_detected(analysis):
    assert len(analysis.beats) >= 8
    assert all(0 <= b <= analysis.duration + 0.1 for b in analysis.beats)
    # биты возрастают
    assert analysis.beats == sorted(analysis.beats)


def test_downbeats_subset(analysis):
    assert analysis.downbeats == analysis.beats[::4]


def test_energy_curve(analysis):
    curve = analysis.energy_curve
    assert len(curve) >= int(analysis.duration)
    assert all(0.0 <= v <= 1.0 for v in curve)
    # громкость нарастала → вторая половина энергичнее первой
    half = len(curve) // 2
    assert np.mean(curve[half:]) > np.mean(curve[:half])


def test_climax_in_second_half(analysis):
    assert analysis.climax_time > analysis.duration / 2


def test_cut_points_spacing(analysis):
    cuts = analysis.cut_points
    assert cuts
    assert all(b - a >= 1.0 for a, b in zip(cuts, cuts[1:]))


def test_json_serializable(analysis):
    data = json.loads(analysis.to_json())
    assert data["bpm"] == analysis.bpm


def test_music_cache_roundtrip(storage, synthetic_music):
    """Второй вызов analyze_music_cached не гоняет librosa — читает из БД."""
    from core import audio_analyzer
    from core.audio_analyzer import analyze_music_cached

    m1 = analyze_music_cached(storage, synthetic_music)

    calls = []
    orig = audio_analyzer.analyze_music

    def spy(path):
        calls.append(path)
        return orig(path)

    audio_analyzer.analyze_music = spy
    try:
        m2 = analyze_music_cached(storage, synthetic_music)
    finally:
        audio_analyzer.analyze_music = orig

    assert calls == []                       # librosa не запускалась
    assert m2.bpm == m1.bpm and m2.beats == m1.beats
    assert m2.calm_ranges == m1.calm_ranges  # кортежи восстановлены из JSON


def test_ranges_helper():
    arr = np.array([0.1, 0.1, 0.1, 0.9, 0.9, 0.1, 0.1, 0.1])
    calm = _ranges(arr, lambda v: v < 0.4)
    assert (0.0, 3.0) in calm and (5.0, 8.0) in calm
    # одиночный элемент (< 2 сек) не образует диапазон
    energetic = _ranges(arr, lambda v: v >= 0.7)
    assert energetic == [(3.0, 5.0)]
