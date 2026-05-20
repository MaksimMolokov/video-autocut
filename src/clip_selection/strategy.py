"""
Базовый класс для стратегий выбора фрагментов
"""

from abc import ABC, abstractmethod
from typing import Dict, List
from dataclasses import dataclass

# Import будет работать после создания остальных модулей
# from src.video_analysis import CandidateClip
# from src.presets.preset_models import PresetSettings


class ClipSelectionStrategy(ABC):
    """
    Базовый класс для стратегий выбора фрагментов

    Каждая стратегия определяет:
    - Веса признаков для scoring
    - Правила фильтрации candidate clips
    - Тип упорядочивания выбранных клипов
    """

    def __init__(self, preset_settings=None):
        """
        Args:
            preset_settings: PresetSettings object (optional)
        """
        self.settings = preset_settings
        self.strategy_settings = preset_settings.clip_strategy if preset_settings else None

    @abstractmethod
    def get_strategy_name(self) -> str:
        """Название стратегии"""
        pass

    @abstractmethod
    def get_feature_weights(self) -> Dict[str, float]:
        """
        Вернуть веса признаков для этой стратегии

        Returns:
            Dict with feature names and their weights
            Keys: sharpness, brightness, contrast, motion, stability,
                  visual_complexity, uniqueness, action, calm, technical_quality
        """
        pass

    @abstractmethod
    def get_ordering_type(self) -> str:
        """
        Вернуть тип упорядочивания фрагментов

        Returns:
            One of: chronological, best_first, energy_growth,
                   smooth_progression, story_arc, hook_then_fast_variation
        """
        pass

    def filter_candidates(self, candidates: List) -> List:
        """
        Отфильтровать неподходящие candidate clips

        По умолчанию не фильтруем, но подклассы могут переопределить

        Args:
            candidates: List of CandidateClip objects

        Returns:
            Filtered list of CandidateClip objects
        """
        return candidates

    def should_include_clip(self, clip) -> bool:
        """
        Проверить, подходит ли клип под стратегию

        Args:
            clip: CandidateClip object

        Returns:
            True if clip should be included
        """
        return True

    def get_diversity_threshold(self) -> float:
        """
        Минимальное отличие между соседними клипами

        Returns:
            Threshold value (0.0 - 1.0)
        """
        if self.strategy_settings:
            return self.strategy_settings.diversity_threshold
        return 0.3  # default

    def get_randomness_level(self) -> float:
        """
        Уровень случайности при выборе

        Returns:
            Randomness level (0.0 = deterministic, 1.0 = maximum randomness)
        """
        if self.strategy_settings:
            return self.strategy_settings.randomness_level
        return 0.3  # default

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.get_strategy_name()}>"


class BalancedStrategy(ClipSelectionStrategy):
    """
    Дефолтная сбалансированная стратегия
    Используется когда специфичная стратегия не найдена
    """

    def get_strategy_name(self) -> str:
        return "balanced"

    def get_feature_weights(self) -> Dict[str, float]:
        return {
            'sharpness': 1.0,
            'brightness': 0.8,
            'contrast': 0.7,
            'motion': 0.6,
            'stability': 0.9,
            'visual_complexity': 0.8,
            'uniqueness': 1.0,
            'action': 0.5,
            'calm': 0.5,
            'technical_quality': 1.0
        }

    def get_ordering_type(self) -> str:
        return 'chronological'
