"""
F6 Strategy — dream travel atmosphere clip selection.
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class F6Strategy(ClipSelectionStrategy):
    """
    Стратегия для стиля F6.

    Цель:
    - Атмосферный travel-монтаж с эмоцией и story flow
    - Высокая уникальность и визуальная насыщенность
    - Достаточная яркость и стабильность
    - Избегать тёмных и нестабильных кадров
    """

    def get_strategy_name(self) -> str:
        return "f6_dream_travel_atmosphere"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 1.5,
            'brightness': 1.4,
            'contrast': 0.7,
            'motion': 1.0,
            'stability': 1.4,
            'visual_complexity': 1.4,
            'uniqueness': 1.8,
            'action': 0.5,
            'calm': 0.8,
            'technical_quality': 1.2,
        }

    def get_ordering_type(self) -> str:
        return 'story_arc'

    def filter_candidates(self, candidates: List) -> List:
        """Skip dark and unstable clips."""
        filtered = []
        for clip in candidates:
            f = clip.features
            if f.brightness_score < 0.12:
                continue
            if f.camera_stability_score < 0.18:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.35

    def get_randomness_level(self) -> float:
        return 0.35
