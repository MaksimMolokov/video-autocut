"""
Nature Cinematic Strategy - для спокойных кинематографичных дрон-видео природы
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class NatureCinematicStrategy(ClipSelectionStrategy):
    """
    Стратегия для Drone Nature Cinematic

    Цель:
    - Выбирать красивые, спокойные, плавные, стабильные кадры
    - Длинные красивые фрагменты
    - Кадры с природой, водой, лесами, горами, небом
    - Без резких движений и тряски
    """

    def get_strategy_name(self) -> str:
        return "nature_cinematic"

    def get_feature_weights(self) -> Dict[str, float]:
        """
        Высокие веса:
        - stability (1.5) - стабильность камеры
        - calm (1.5) - спокойствие
        - technical_quality (1.2) - техническое качество
        - uniqueness (1.0) - разнообразие
        - sharpness (1.0) - резкость

        Низкие веса:
        - motion (0.3) - мало движения
        - action (0.1) - минимум экшена
        """
        return {
            'sharpness': 1.0,
            'brightness': 0.8,
            'contrast': 0.7,
            'motion': 0.3,
            'stability': 1.5,
            'visual_complexity': 0.8,
            'uniqueness': 1.0,
            'action': 0.1,
            'calm': 1.5,
            'technical_quality': 1.2
        }

    def get_ordering_type(self) -> str:
        """Плавное развитие"""
        return 'smooth_progression'

    def filter_candidates(self, candidates: List) -> List:
        """
        Отфильтровать:
        - Слишком динамичные клипы (motion > 0.7)
        - Слишком трясущиеся клипы (stability < 0.3)
        """
        filtered = []

        for clip in candidates:
            # Убрать слишком динамичные
            if clip.features.motion_score > 0.7:
                continue

            # Убрать слишком трясущиеся
            if clip.features.camera_stability_score < 0.3:
                continue

            filtered.append(clip)

        return filtered

    def get_diversity_threshold(self) -> float:
        """Средний уровень разнообразия"""
        return 0.3

    def get_randomness_level(self) -> float:
        """Низкая случайность - детерминированный выбор"""
        return 0.2
