"""
Business Clean Strategy - для бизнес презентаций
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class BusinessCleanStrategy(ClipSelectionStrategy):
    """
    Стратегия для Business Promo Clean

    Цель:
    - Чистые, понятные, стабильные кадры
    - Высокое техническое качество
    - Яркие и четкие планы
    - Без тряски и хаоса
    - Аккуратная презентация
    """

    def get_strategy_name(self) -> str:
        return "business_clean"

    def get_feature_weights(self) -> Dict[str, float]:
        """
        Высокие веса:
        - technical_quality (1.5) - максимальное качество
        - sharpness (1.4) - резкость
        - stability (1.3) - стабильность
        - brightness (1.0) - яркость
        """
        return {
            'sharpness': 1.4,
            'brightness': 1.0,
            'contrast': 0.8,
            'motion': 0.5,
            'stability': 1.3,
            'visual_complexity': 0.7,
            'uniqueness': 0.7,
            'action': 0.2,
            'calm': 1.0,
            'technical_quality': 1.5
        }

    def get_ordering_type(self) -> str:
        """Хронологический порядок"""
        return 'chronological'

    def filter_candidates(self, candidates: List) -> List:
        """
        Жесткая фильтрация:
        - Убрать размытые (sharpness < 0.4)
        - Убрать темные (brightness < 0.3)
        - Убрать трясущиеся (stability < 0.5)
        """
        filtered = []

        for clip in candidates:
            # Высокие требования к качеству
            if clip.features.sharpness_score < 0.4:
                continue

            if clip.features.brightness_score < 0.3:
                continue

            if clip.features.camera_stability_score < 0.5:
                continue

            filtered.append(clip)

        return filtered

    def get_diversity_threshold(self) -> float:
        """Низкое разнообразие - последовательность важнее"""
        return 0.25

    def get_randomness_level(self) -> float:
        """Минимальная случайность"""
        return 0.2
