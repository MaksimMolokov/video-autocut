"""Music Selector: выбор правильного фрагмента трека под сценарий."""
import numpy as np

from core.audio_analyzer import MusicAnalysis
from core.music_selector import (MusicCue, _desired_profile, select_music_cue,
                                 shifted_cut_points)
from core.presets import get_preset


def _music(curve, duration=None, downbeats=None) -> MusicAnalysis:
    return MusicAnalysis(
        path="x", duration=duration or float(len(curve)),
        bpm=120.0, beats=[i * 0.5 for i in range(int(len(curve) * 2))],
        downbeats=downbeats or [i * 2.0 for i in range(len(curve) // 2)],
        energy_curve=list(curve),
        cut_points=[i * 2.0 for i in range(len(curve) // 2)],
    )


def test_short_track_starts_at_zero():
    cue = select_music_cue(_music([0.5] * 20), 30.0, get_preset("generic"))
    assert cue.offset == 0.0
    assert "с начала" in cue.reason


def test_calm_preset_avoids_loud_start():
    """Трек: громкое начало, спокойная середина с нарастанием к концу.
    Для спокойного пресета старт должен уйти из громкой зоны."""
    curve = [1.0] * 30 + [0.25] * 15 + [0.5] * 15 + [0.9] * 25 + [0.3] * 15  # 100 c
    cue = select_music_cue(_music(curve), 30.0, get_preset("slow_cinematic"))
    assert cue.offset >= 25.0  # не в громкой голове трека
    assert cue.offset + 30.0 <= 100.0 + 0.01


def test_high_dynamics_prefers_energetic_start():
    """Для high-динамики (reels) выгоден энергичный старт."""
    curve = [0.15] * 40 + [0.95] * 40 + [0.2] * 20  # тихо → мощно → тихо
    cue = select_music_cue(_music(curve), 20.0, get_preset("reels_fast"))
    window = np.array(curve[int(cue.offset):int(cue.offset) + 20])
    assert window.mean() >= 0.5  # старт попал в энергичную зону
    assert cue.fade_in <= 0.5    # быстрый вход для хука


def test_offset_snapped_to_downbeat():
    curve = [0.2] * 30 + [0.8] * 40 + [0.3] * 30
    cue = select_music_cue(_music(curve), 25.0, get_preset("generic"))
    downbeats = [i * 2.0 for i in range(50)]
    assert min(abs(cue.offset - b) for b in downbeats) <= 2.0


def test_offset_never_exceeds_track():
    curve = [0.5] * 40
    cue = select_music_cue(_music(curve), 35.0, get_preset("generic"))
    assert cue.offset + 35.0 <= 40.0 + 0.01


def test_desired_profile_matches_slots():
    p = get_preset("generic")
    prof = _desired_profile(p, 30)
    assert len(prof) == 30
    assert all(0 < v <= 1 for v in prof)
    # кульминация энергичнее вступления и финала
    assert prof[-2] < prof[int(30 * 0.8)] > prof[0]


def test_shifted_cut_points():
    music = _music([0.5] * 20)
    music.cut_points = [10.0, 12.0, 14.0]
    assert shifted_cut_points(music, 10.0) == [0.0, 2.0, 4.0]
    assert shifted_cut_points(music, 13.0) == [1.0]


def test_cue_is_dataclass_with_reason():
    cue = select_music_cue(_music([0.5] * 60), 30.0, get_preset("drone_cinematic"))
    assert isinstance(cue, MusicCue)
    assert cue.reason and cue.duration == 30.0
