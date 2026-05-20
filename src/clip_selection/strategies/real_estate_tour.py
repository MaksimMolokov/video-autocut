"""
Real Estate Tour Strategy - для съёмки недвижимости
"""
from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class RealEstateTourStrategy(ClipSelectionStrategy):
    """
    Стратегия для Real Estate / Property Tour
    Цель: стабильные, светлые, медленные, понятные обзорные кадры
    """

    def get_strategy_name(self) -> str:
        return "real_estate_tour"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 1.5,
            'brightness': 1.1,
            'contrast': 0.7,
            'motion': 0.3,
            'stability': 1.7,
            'visual_complexity': 0.5,
            'uniqueness': 0.6,
            'action': 0.0,
            'calm': 1.5,
            'technical_quality': 1.4,
        }

    def get_ordering_type(self) -> str:
        return 'smooth_progression'

    def filter_candidates(self, candidates: List) -> List:
        filtered = []
        for clip in candidates:
            if clip.features.sharpness_score < 0.4:
                continue
            if clip.features.brightness_score < 0.35:
                continue
            if clip.features.camera_stability_score < 0.55:
                continue
            if clip.features.motion_score > 0.5:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.2

    def get_randomness_level(self) -> float:
        return 0.1
