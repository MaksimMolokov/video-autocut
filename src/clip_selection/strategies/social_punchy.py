"""
Social Punchy Strategy - для ярких соцсетей (Reels, Shorts, TikTok)
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class SocialPunchyStrategy(ClipSelectionStrategy):
    """
    Стратегия для Social Media Punchy

    Цель:
    - Яркие, короткие, выразительные моменты
    - Высокий контраст
    - Максимальное разнообразие
    - Сильное открытие (hook)
    - Энергия и динамика
    """

    def get_strategy_name(self) -> str:
        return "social_punchy"

    def get_feature_weights(self) -> Dict[str, float]:
        """
        Высокие веса:
        - uniqueness (1.4) - разнообразие
        - contrast (1.4) - контраст
        - action (1.2) - динамика
        - motion (1.2) - движение
        """
        return {
            'sharpness': 1.0,
            'brightness': 0.9,
            'contrast': 1.4,
            'motion': 1.2,
            'stability': 0.5,
            'visual_complexity': 1.1,
            'uniqueness': 1.4,
            'action': 1.2,
            'calm': 0.0,
            'technical_quality': 1.0
        }

    def get_ordering_type(self) -> str:
        """Hook в начале, затем быстрая смена"""
        return 'hook_then_fast_variation'

    def filter_candidates(self, candidates: List) -> List:
        """
        Минимальная фильтрация - нужна энергия и разнообразие

        Убираем только:
        - Слишком спокойные (action < 0.2)
        """
        filtered = []

        for clip in candidates:
            # Убрать слишком спокойные
            if clip.features.action_score < 0.2 and clip.features.contrast_score < 0.4:
                continue

            filtered.append(clip)

        return filtered

    def get_diversity_threshold(self) -> float:
        """Очень высокое разнообразие"""
        return 0.45

    def get_randomness_level(self) -> float:
        """Высокая случайность"""
        return 0.4
