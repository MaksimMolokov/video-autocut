"""
F2 Strategy — cinematic velocity flow clip selection.
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class F2Strategy(ClipSelectionStrategy):
    """
    Стратегия для стиля F2.

    Цель:
    - Плавный cinematic-монтаж с движением камеры
    - Высокая стабильность и резкость
    - Умеренное движение в кадре
    - Избегать тёмных, размытых и сильно трясущихся кадров
    """

    def get_strategy_name(self) -> str:
        return "f2_cinematic_velocity_flow"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 1.6,
            'brightness': 1.2,
            'contrast': 0.8,
            'motion': 1.4,
            'stability': 1.8,
            'visual_complexity': 1.2,
            'uniqueness': 1.3,
            'action': 0.4,
            'calm': 0.2,
            'technical_quality': 1.4,
        }

    def get_ordering_type(self) -> str:
        return 'beauty_arc'

    def filter_candidates(self, candidates: List) -> List:
        """Keep stable, sharp and well-lit clips."""
        filtered = []
        for clip in candidates:
            f = clip.features
            if f.camera_stability_score < 0.25:
                continue
            if f.brightness_score < 0.15:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.35

    def get_randomness_level(self) -> float:
        return 0.3
