"""
Landscape Clean Strategy - для профессионального обзора территории
"""
from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class LandscapeCleanStrategy(ClipSelectionStrategy):
    """
    Стратегия для Drone Landscape Clean
    Цель: резкие информативные обзорные кадры, понятная последовательность
    """

    def get_strategy_name(self) -> str:
        return "landscape_clean"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 1.4,
            'brightness': 0.9,
            'contrast': 0.7,
            'motion': 0.4,
            'stability': 1.5,
            'visual_complexity': 0.6,
            'uniqueness': 0.8,
            'action': 0.1,
            'calm': 1.1,
            'technical_quality': 1.3,
        }

    def get_ordering_type(self) -> str:
        return 'chronological'

    def filter_candidates(self, candidates: List) -> List:
        filtered = []
        for clip in candidates:
            if clip.features.sharpness_score < 0.35:
                continue
            if clip.features.motion_score > 0.6:
                continue
            if clip.features.camera_stability_score < 0.4:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.2

    def get_randomness_level(self) -> float:
        return 0.15
