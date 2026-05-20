"""
Travel Story Strategy - для видео путешествий с историей
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class TravelStoryStrategy(ClipSelectionStrategy):
    """
    Стратегия для Travel Story

    Цель:
    - Делать ролик как историю, а не просто нарезку лучших кадров
    - Максимальное разнообразие сцен
    - Смена локаций
    - Разные типы кадров (общие планы, детали, эмоции)
    - Структура: начало → развитие → финал
    """

    def get_strategy_name(self) -> str:
        return "travel_story"

    def get_feature_weights(self) -> Dict[str, float]:
        """
        Высокие веса:
        - uniqueness (1.6) - максимальное разнообразие
        - visual_complexity (1.0) - детали
        - technical_quality (1.1) - качество

        Средние веса для всего остального
        """
        return {
            'sharpness': 1.0,
            'brightness': 0.8,
            'contrast': 0.7,
            'motion': 0.7,
            'stability': 0.9,
            'visual_complexity': 1.0,
            'uniqueness': 1.6,
            'action': 0.5,
            'calm': 0.7,
            'technical_quality': 1.1
        }

    def get_ordering_type(self) -> str:
        """Структура истории"""
        return 'story_arc'

    def filter_candidates(self, candidates: List) -> List:
        """
        Минимальная фильтрация - нужно разнообразие

        Убираем только совсем плохие:
        - Слишком размытые (sharpness < 0.2)
        - Слишком темные (brightness < 0.15)
        """
        filtered = []

        for clip in candidates:
            # Убрать слишком размытые
            if clip.features.sharpness_score < 0.2:
                continue

            # Убрать слишком темные
            if clip.features.brightness_score < 0.15:
                continue

            filtered.append(clip)

        return filtered

    def get_diversity_threshold(self) -> float:
        """Очень высокое разнообразие"""
        return 0.5

    def get_randomness_level(self) -> float:
        """Средняя случайность для вариативности"""
        return 0.35
