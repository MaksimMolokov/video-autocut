"""
Конкретные стратегии выбора фрагментов для разных пресетов
"""

from .nature_cinematic import NatureCinematicStrategy
from .action_sport import ActionSportStrategy
from .travel_story import TravelStoryStrategy
from .urban_rhythm import UrbanRhythmStrategy
from .business_clean import BusinessCleanStrategy
from .social_punchy import SocialPunchyStrategy
from .intelligent_beauty import IntelligentBeautyStrategy
from .landscape_clean import LandscapeCleanStrategy
from .real_estate_tour import RealEstateTourStrategy
from .event_highlights import EventHighlightsStrategy
from .calm_documentary import CalmDocumentaryStrategy
from .sport_dynamic_cut import SportDynamicCutStrategy
from .sport_highlight_impact import SportHighlightImpactStrategy

__all__ = [
    'NatureCinematicStrategy',
    'ActionSportStrategy',
    'TravelStoryStrategy',
    'UrbanRhythmStrategy',
    'BusinessCleanStrategy',
    'SocialPunchyStrategy',
    'IntelligentBeautyStrategy',
    'LandscapeCleanStrategy',
    'RealEstateTourStrategy',
    'EventHighlightsStrategy',
    'CalmDocumentaryStrategy',
    'SportDynamicCutStrategy',
    'SportHighlightImpactStrategy',
]
