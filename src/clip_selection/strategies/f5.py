"""
F5 Strategy — premium brand smooth clip selection.
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class F5Strategy(ClipSelectionStrategy):
    """
    Стратегия для стиля F5.

    Цель:
    - Премиальный стиль с максимальной резкостью и стабильностью
    - Спокойные, хорошо освещённые кадры
    - Избегать движения, тряски и тёмных кадров
    - Отрицательный вес к action-кадрам
    """

    def get_strategy_name(self) -> str:
        return "f5_premium_brand_smooth"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 2.0,
            'brightness': 1.5,
            'contrast': 0.6,
            'motion': 0.3,
            'stability': 2.0,
            'visual_complexity': 1.2,
            'uniqueness': 1.3,
            'action': -0.5,
            'calm': 1.8,
            'technical_quality': 1.6,
        }

    def get_ordering_type(self) -> str:
        return 'beauty_arc'

    def filter_candidates(self, candidates: List) -> List:
        """Keep only stable, sharp, well-lit and calm clips."""
        filtered = []
        for clip in candidates:
            f = clip.features
            if f.camera_stability_score < 0.40:
                continue
            if f.brightness_score < 0.20:
                continue
            if f.motion_score > 0.75:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.3

    def get_randomness_level(self) -> float:
        return 0.2
