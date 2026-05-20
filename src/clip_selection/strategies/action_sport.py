"""
Action Sport Strategy - для динамичных спортивных видео
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class ActionSportStrategy(ClipSelectionStrategy):
    """
    Стратегия для Fast Action Sport

    Цель:
    - Выбирать самые динамичные, энергичные, быстрые моменты
    - Короткие энергичные фрагменты
    - Высокая скорость движения
    - Резкие смены направления
    - Можно терпеть умеренную тряску
    """

    def get_strategy_name(self) -> str:
        return "action_sport"

    def get_feature_weights(self) -> Dict[str, float]:
        """
        Высокие веса:
        - action (1.8) - экшен
        - motion (1.6) - движение
        - uniqueness (1.0) - разнообразие

        Низкие веса:
        - calm (0.0) - не нужно спокойствие
        - stability (0.4) - стабильность менее важна
        """
        return {
            'sharpness': 0.8,
            'brightness': 0.6,
            'contrast': 0.8,
            'motion': 1.6,
            'stability': 0.4,
            'visual_complexity': 0.7,
            'uniqueness': 1.0,
            'action': 1.8,
            'calm': 0.0,
            'technical_quality': 0.9
        }

    def get_ordering_type(self) -> str:
        """Нарастание энергии"""
        return 'energy_growth'

    def filter_candidates(self, candidates: List) -> List:
        """
        Отфильтровать:
        - Слишком статичные клипы (motion < 0.3)
        - Низкий action score (action < 0.4)
        """
        filtered = []

        for clip in candidates:
            # Оставить только динамичные клипы
            if clip.features.motion_score < 0.3:
                continue

            # Убрать клипы с низким action
            if clip.features.action_score < 0.4:
                continue

            filtered.append(clip)

        return filtered

    def get_diversity_threshold(self) -> float:
        """Высокий уровень разнообразия"""
        return 0.4

    def get_randomness_level(self) -> float:
        """Средняя случайность"""
        return 0.4
