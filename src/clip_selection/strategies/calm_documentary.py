"""
Calm Documentary Strategy - для спокойного информативного монтажа
"""
from typing import Dict, List
from ..strategy import ClipSelectionStrategy


class CalmDocumentaryStrategy(ClipSelectionStrategy):
    """
    Стратегия для Calm Minimal Documentary
    Цель: спокойные стабильные информативные кадры, логичная последовательность
    """

    def get_strategy_name(self) -> str:
        return "calm_documentary"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 1.2,
            'brightness': 0.8,
            'contrast': 0.5,
            'motion': 0.2,
            'stability': 1.6,
            'visual_complexity': 0.7,
            'uniqueness': 0.6,
            'action': 0.0,
            'calm': 1.8,
            'technical_quality': 1.1,
        }

    def get_ordering_type(self) -> str:
        return 'smooth_progression'

    def filter_candidates(self, candidates: List) -> List:
        filtered = []
        for clip in candidates:
            if clip.features.motion_score > 0.55:
                continue
            if clip.features.camera_stability_score < 0.45:
                continue
            if clip.features.sharpness_score < 0.3:
                continue
            filtered.append(clip)
        return filtered

    def get_diversity_threshold(self) -> float:
        return 0.25

    def get_randomness_level(self) -> float:
        return 0.15
