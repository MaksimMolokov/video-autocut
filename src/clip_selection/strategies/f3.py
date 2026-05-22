"""
F3 Strategy — urban pulse cut clip selection.
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class F3Strategy(ClipSelectionStrategy):
    """
    Стратегия для стиля F3.

    Цель:
    - Быстрый городской монтаж с высоким разнообразием
    - Максимальное движение, action и визуальная сложность
    - Избегать полностью статичных и слишком тёмных кадров
    - Негативный вес к спокойным кадрам
    """

    def get_strategy_name(self) -> str:
        return "f3_urban_pulse_cut"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 1.4,
            'brightness': 1.0,
            'contrast': 1.4,
            'motion': 2.2,
            'stability': 0.3,
            'visual_complexity': 1.6,
            'uniqueness': 2.0,
            'action': 1.8,
            'calm': -0.5,
            'technical_quality': 0.8,
        }

    def get_ordering_type(self) -> str:
        return 'energy_peak'

    def filter_candidates(self, candidates: List) -> List:
        """Skip completely static and very dark clips."""
        filtered = []
        for clip in candidates:
            f = clip.features
            if f.motion_score < 0.15:
                continue
            if f.brightness_score < 0.10:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.4

    def get_randomness_level(self) -> float:
        return 0.5
