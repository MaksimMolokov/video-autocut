"""
Sport Highlight Impact Strategy — structured highlight reel with impact moments.
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class SportHighlightImpactStrategy(ClipSelectionStrategy):
    """
    Стратегия для Sport Highlight Impact.

    Цель:
    - Найти кульминационные, импактные моменты
    - Сбалансировать ритм и повествование (нарастание → импакт → дыхание)
    - Более длинные фрагменты для ключевых моментов
    - Высокое качество кадра на пиковых моментах
    """

    def get_strategy_name(self) -> str:
        return "sport_highlight_impact"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness':          1.0,   # чёткость важна для хайлайтов
            'brightness':         0.6,
            'contrast':           1.0,
            'motion':             1.5,   # движение важно, но не единственный критерий
            'stability':          0.6,   # умеренная стабильность
            'visual_complexity':  0.9,
            'uniqueness':         1.2,   # разнообразие моментов
            'action':             2.0,   # акцент на экшн-моменты
            'calm':               0.1,
            'technical_quality':  1.0,
        }

    def get_ordering_type(self) -> str:
        """Дуга повествования: нарастание → пик → спад"""
        return 'story_arc'

    def filter_candidates(self, candidates: List) -> List:
        """Убрать совсем неактивные клипы, оставить даже слабые движения для структуры."""
        filtered = []
        for clip in candidates:
            if clip.features.action_score < 0.25:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.40

    def get_randomness_level(self) -> float:
        return 0.30
