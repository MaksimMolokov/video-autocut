"""
Event Highlights Strategy - для ярких нарезок мероприятий
"""
from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class EventHighlightsStrategy(ClipSelectionStrategy):
    """
    Стратегия для Event Highlights
    Цель: активные, разнообразные, яркие фрагменты с движением
    """

    def get_strategy_name(self) -> str:
        return "event_highlights"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 0.9,
            'brightness': 0.8,
            'contrast': 1.0,
            'motion': 1.0,
            'stability': 0.6,
            'visual_complexity': 1.1,
            'uniqueness': 1.5,
            'action': 1.0,
            'calm': 0.2,
            'technical_quality': 0.8,
        }

    def get_ordering_type(self) -> str:
        return 'story_arc'

    def filter_candidates(self, candidates: List) -> List:
        filtered = []
        for clip in candidates:
            # убрать совсем статичные
            if clip.features.action_score < 0.15:
                continue
            # убрать совсем тёмные
            if clip.features.brightness_score < 0.2:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.4

    def get_randomness_level(self) -> float:
        return 0.35
