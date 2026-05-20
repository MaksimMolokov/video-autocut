"""
Sport Dynamic Cut Strategy — ultra-fast rhythmic sport editing.
"""

from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class SportDynamicCutStrategy(ClipSelectionStrategy):
    """
    Стратегия для Sport Dynamic Cut.

    Цель:
    - Максимально динамичные, непрерывно движущиеся моменты
    - Очень короткие фрагменты с постоянным движением
    - Ритмичная смена кадров в темп музыки
    - Допускается умеренная тряска (экшн-камера)
    """

    def get_strategy_name(self) -> str:
        return "sport_dynamic_cut"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness':          0.7,
            'brightness':         0.5,
            'contrast':           0.9,
            'motion':             2.0,   # главный приоритет — движение
            'stability':          0.3,   # тряска допустима
            'visual_complexity':  0.8,
            'uniqueness':         1.1,
            'action':             1.9,   # высокий экшн
            'calm':               0.0,   # статичные кадры не нужны
            'technical_quality':  0.8,
        }

    def get_ordering_type(self) -> str:
        """Нарастание энергии к концу"""
        return 'energy_growth'

    def filter_candidates(self, candidates: List) -> List:
        """Убрать статичные и очень спокойные клипы."""
        filtered = []
        for clip in candidates:
            if clip.features.motion_score < 0.20:
                continue
            if clip.features.action_score < 0.30:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.45

    def get_randomness_level(self) -> float:
        return 0.50
