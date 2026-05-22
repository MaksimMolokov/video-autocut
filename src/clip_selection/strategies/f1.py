"""
F1 Strategy — ultra-dynamic beat-driven montage clip selection.
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class F1Strategy(ClipSelectionStrategy):
    """
    Стратегия для стиля F1.

    Цель:
    - Максимальная динамика, движение, action
    - Сверхкороткие фрагменты под ритм
    - Высокое разнообразие источников и временных точек
    - Избегать спокойных, тёмных, размытых кадров
    """

    def get_strategy_name(self) -> str:
        return "f1"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 0.7,
            'brightness': 0.6,
            'contrast': 0.9,
            'motion': 2.2,
            'stability': 0.2,
            'visual_complexity': 1.0,
            'uniqueness': 1.3,
            'action': 2.2,
            'calm': 0.0,
            'technical_quality': 0.6,
        }

    def get_ordering_type(self) -> str:
        return 'buildup_impact'

    def filter_candidates(self, candidates: List) -> List:
        """Keep only highly dynamic clips."""
        filtered = []
        for clip in candidates:
            f = clip.features
            if f.motion_score < 0.2 and f.action_score < 0.25:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.45

    def get_randomness_level(self) -> float:
        return 0.5
