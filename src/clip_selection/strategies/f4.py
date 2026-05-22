"""
F4 Strategy — impact sport machine clip selection.
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class F4Strategy(ClipSelectionStrategy):
    """
    Стратегия для стиля F4.

    Цель:
    - Агрессивный action-монтаж с максимальным движением
    - Высокое движение и action обязательны
    - Отрицательный вес к спокойным кадрам
    - Нестабильность не является недостатком
    """

    def get_strategy_name(self) -> str:
        return "f4_impact_sport_machine"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 1.4,
            'brightness': 0.8,
            'contrast': 1.2,
            'motion': 2.8,
            'stability': -0.5,
            'visual_complexity': 1.4,
            'uniqueness': 1.6,
            'action': 2.8,
            'calm': -2.0,
            'technical_quality': 0.8,
        }

    def get_ordering_type(self) -> str:
        return 'buildup_impact'

    def filter_candidates(self, candidates: List) -> List:
        """Keep only clips with significant motion or action."""
        filtered = []
        for clip in candidates:
            f = clip.features
            if f.motion_score >= 0.25 or f.action_score >= 0.25:
                filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.45

    def get_randomness_level(self) -> float:
        return 0.55
