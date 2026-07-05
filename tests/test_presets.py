"""Пресеты: состав, корректность структуры, суммы долей."""
import pytest

from core.models import SCENE_TYPES, STORY_SLOTS
from core.presets import PRESETS, get_preset


def test_all_12_tz_presets_present():
    tz_ids = {"fpv_location", "restaurant", "coworking", "travel", "family",
              "birthday", "drone_cinematic", "reels_fast", "tiktok_clip",
              "real_estate", "slow_cinematic", "action_montage"}
    assert tz_ids <= set(PRESETS)


@pytest.mark.parametrize("preset_id", list(PRESETS))
def test_preset_structure(preset_id):
    p = PRESETS[preset_id]
    assert p.idea and p.title
    assert p.dynamics in ("low", "medium", "high")
    # доли слотов дают ровно 1.0
    assert abs(sum(s.share for s in p.slots) - 1.0) < 1e-6
    slots = [s.slot for s in p.slots]
    # драматургия: начинается вступлением, заканчивается финалом (ТЗ §12)
    assert slots[0] == "intro" and slots[-1] == "ending"
    for s in p.slots:
        assert s.slot in STORY_SLOTS
        assert 0 < s.min_fragment <= s.max_fragment
        assert all(t in SCENE_TYPES for t in s.scene_types)
        assert all(m in ("static", "slow", "fast") for m in s.prefer_motion)


def test_get_preset_fallback():
    assert get_preset("nonexistent").id == "generic"
    assert get_preset("restaurant").id == "restaurant"


def test_scenario_text():
    text = PRESETS["restaurant"].scenario_text()
    assert "Идея ролика" in text and "intro" in text and "Финал" in text
