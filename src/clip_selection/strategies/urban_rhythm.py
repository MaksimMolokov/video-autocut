"""
Urban Rhythm Strategy - для городских ритмичных видео
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class UrbanRhythmStrategy(ClipSelectionStrategy):
    """
    Стратегия для Urban City Rhythm

    Цель:
    - Ритмичные городские кадры
    - Архитектура, движение, улицы
    - Высокая визуальная плотность
    - Средняя динамика
    - Смена планов
    """

    def get_strategy_name(self) -> str:
        return "urban_rhythm"

    def get_feature_weights(self) -> Dict[str, float]:
        """
        Высокие веса:
        - visual_complexity (1.3) - визуальная плотность
        - uniqueness (1.2) - разнообразие
        - motion (1.1) - средняя динамика
        - contrast (1.0) - контраст
        """
        return {
            'sharpness': 1.0,
            'brightness': 0.7,
            'contrast': 1.0,
            'motion': 1.1,
            'stability': 0.8,
            'visual_complexity': 1.3,
            'uniqueness': 1.2,
            'action': 0.8,
            'calm': 0.2,
            'technical_quality': 1.0
        }

    def get_ordering_type(self) -> str:
        """Ритмичное чередование"""
        return 'rhythmic_alternation'

    def filter_candidates(self, candidates: List) -> List:
        """
        Отфильтровать:
        - Слишком статичные клипы (motion < 0.2)
        """
        filtered = []

        for clip in candidates:
            # Убрать слишком статичные
            if clip.features.motion_score < 0.2:
                continue

            filtered.append(clip)

        return filtered

    def get_diversity_threshold(self) -> float:
        """Высокое разнообразие"""
        return 0.35

    def get_randomness_level(self) -> float:
        """Средняя случайность"""
        return 0.35
