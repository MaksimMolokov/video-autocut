"""
Strategy Registry - связывает preset_id с конкретной стратегией
"""

import logging
from typing import Dict, Type, Optional

from .strategy import ClipSelectionStrategy, BalancedStrategy
from .strategies import (
    NatureCinematicStrategy,
    ActionSportStrategy,
    TravelStoryStrategy,
    UrbanRhythmStrategy,
    BusinessCleanStrategy,
    SocialPunchyStrategy,
    IntelligentBeautyStrategy,
    LandscapeCleanStrategy,
    RealEstateTourStrategy,
    EventHighlightsStrategy,
    CalmDocumentaryStrategy,
    SportDynamicCutStrategy,
    SportHighlightImpactStrategy,
    F1Strategy,
    F2Strategy,
    F3Strategy,
    F4Strategy,
    F5Strategy,
    F6Strategy,
)

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """
    Реестр стратегий выбора фрагментов

    Связывает preset_id с соответствующей стратегией
    """

    # Mapping: preset_id -> Strategy class
    _STRATEGIES: Dict[str, Type[ClipSelectionStrategy]] = {
        # Drone
        'drone_nature_cinematic': NatureCinematicStrategy,
        'drone_landscape_clean': LandscapeCleanStrategy,

        # Action
        'fast_action_sport': ActionSportStrategy,

        # Urban
        'urban_city_rhythm': UrbanRhythmStrategy,

        # Social
        'social_media_punchy': SocialPunchyStrategy,

        # Business
        'business_promo_clean': BusinessCleanStrategy,

        # Travel
        'travel_story': TravelStoryStrategy,

        # Real Estate
        'real_estate_property_tour': RealEstateTourStrategy,

        # Event
        'event_highlights': EventHighlightsStrategy,

        # Documentary
        'calm_minimal_documentary': CalmDocumentaryStrategy,

        # Intelligent Beauty Mix - новый 11-й шаблон
        'intelligent_beauty_mix': IntelligentBeautyStrategy,

        # Sport
        'sport_dynamic_cut':     SportDynamicCutStrategy,
        'sport_highlight_impact': SportHighlightImpactStrategy,

        # F1 — ultra-dynamic beat-driven montage
        'f1': F1Strategy,

        # F2 — cinematic velocity flow
        'f2': F2Strategy,

        # F3 — urban pulse cut
        'f3': F3Strategy,

        # F4 — impact sport machine
        'f4': F4Strategy,

        # F5 — premium brand smooth
        'f5': F5Strategy,

        # F6 — dream travel atmosphere
        'f6': F6Strategy,
    }

    @classmethod
    def get_strategy(
        cls,
        preset_id: str,
        preset_settings=None
    ) -> ClipSelectionStrategy:
        """
        Получить стратегию по preset_id

        Args:
            preset_id: ID пресета
            preset_settings: PresetSettings object (optional)

        Returns:
            Instance of ClipSelectionStrategy
        """
        strategy_class = cls._STRATEGIES.get(preset_id, BalancedStrategy)

        if preset_id not in cls._STRATEGIES:
            logger.warning(
                f"Strategy not found for preset '{preset_id}', "
                f"using BalancedStrategy as fallback"
            )

        strategy = strategy_class(preset_settings)

        logger.info(f"Loaded strategy: {strategy.get_strategy_name()} for preset '{preset_id}'")

        return strategy

    @classmethod
    def register_strategy(
        cls,
        preset_id: str,
        strategy_class: Type[ClipSelectionStrategy]
    ):
        """
        Зарегистрировать новую стратегию

        Args:
            preset_id: ID пресета
            strategy_class: Class of strategy
        """
        cls._STRATEGIES[preset_id] = strategy_class
        logger.info(f"Registered strategy {strategy_class.__name__} for preset '{preset_id}'")

    @classmethod
    def list_strategies(cls) -> Dict[str, str]:
        """
        Список всех зарегистрированных стратегий

        Returns:
            Dict mapping preset_id -> strategy_name
        """
        result = {}
        for preset_id, strategy_class in cls._STRATEGIES.items():
            # Create temporary instance to get name
            temp_instance = strategy_class()
            result[preset_id] = temp_instance.get_strategy_name()
        return result


if __name__ == "__main__":
    # Test strategy registry
    print("Registered strategies:\n")

    strategies = StrategyRegistry.list_strategies()

    for preset_id, strategy_name in strategies.items():
        print(f"  {preset_id:30} → {strategy_name}")

    print(f"\n✓ Total: {len(strategies)} strategies")

    # Test getting a strategy
    print("\nTesting strategy retrieval:")

    for test_preset in ['drone_nature_cinematic', 'fast_action_sport', 'unknown_preset']:
        strategy = StrategyRegistry.get_strategy(test_preset)
        print(f"  {test_preset:30} → {strategy}")
